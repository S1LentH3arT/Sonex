"""Transactional local playlist and up-next edits for the compact Agent surface."""

from __future__ import annotations

import threading
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.tools.playlists import (
    LIKES_PLAYLIST,
    PlaylistVersionConflict,
    commit_playlist_state,
    delete_playlist_state,
    list_playlists,
    playlist_storage_path,
    playlist_snapshot,
)
from src.tools.modify_idempotency import (
    MAX_IDEMPOTENCY_RESULTS,
    load_idempotency_entries,
    operation_fingerprint,
    record_idempotency_entry,
)
from src.tools.result import ToolResult
from src.tools.track_refs import resolve_track_reference
from src.tools.up_next import (
    UpNextVersionConflict,
    commit_up_next_state,
    up_next_snapshot,
    up_next_storage_path,
)


PLAYLIST_ACTIONS = {
    "create",
    "add",
    "remove",
    "move",
    "reorder",
    "rename",
    "clear",
    "delete",
}
UP_NEXT_ACTIONS = {"add", "remove", "move", "clear", "replace"}
DESTRUCTIVE_ACTIONS = {"remove", "clear", "delete", "replace"}
_MAX_PENDING_MODIFICATIONS = 64
_MODIFY_LOCK = threading.RLock()
_IDEMPOTENCY_RESULTS: OrderedDict[str, dict[str, Any]] = OrderedDict()
_PENDING: OrderedDict[str, "_Plan"] = OrderedDict()


class ModifyError(ValueError):
    """A structured local modification validation failure."""

    def __init__(self, message: str, error_code: str) -> None:
        super().__init__(message)
        self.error_code = error_code


@dataclass
class _Plan:
    idempotency_key: str
    fingerprint: str
    playlist_before: dict[str, dict[str, Any]]
    playlist_after: dict[str, dict[str, Any]]
    playlist_deletes: set[str]
    up_next_before: dict[str, Any] | None
    up_next_after: dict[str, Any] | None
    preview: dict[str, Any]


def _failure(message: str, error_code: str, *, data: dict[str, Any] | None = None) -> dict[str, Any]:
    return ToolResult.fail(
        tool="Modify",
        message=message,
        error_code=error_code,
        data=data or {},
    ).to_dict()


def _idempotency_path() -> Path:
    return up_next_storage_path().with_name("modify_idempotency.json")


def _cache_key(idempotency_key: str) -> str:
    return f"{_idempotency_path()}::{idempotency_key}"


def _lookup_idempotency(
    idempotency_key: str,
    fingerprint: str,
) -> dict[str, Any] | None:
    key = _cache_key(idempotency_key)
    cached = _IDEMPOTENCY_RESULTS.get(key)
    if cached is None:
        cached = load_idempotency_entries(_idempotency_path()).get(idempotency_key)
        if cached is not None:
            _IDEMPOTENCY_RESULTS[key] = cached
    if cached is None:
        return None
    if str(cached.get("fingerprint") or "") != fingerprint:
        raise ModifyError(
            "The idempotency key was already used for different operations.",
            "IDEMPOTENCY_CONFLICT",
        )
    return dict(cached["result"])


def _record_idempotency(plan: _Plan, result: dict[str, Any]) -> None:
    path = _idempotency_path()
    entry = record_idempotency_entry(
        path,
        key=plan.idempotency_key,
        fingerprint=plan.fingerprint,
        result=result,
        completed_at=time.time(),
    )
    cache_key = _cache_key(plan.idempotency_key)
    _IDEMPOTENCY_RESULTS[cache_key] = entry
    _IDEMPOTENCY_RESULTS.move_to_end(cache_key)
    while len(_IDEMPOTENCY_RESULTS) > MAX_IDEMPOTENCY_RESULTS:
        _IDEMPOTENCY_RESULTS.popitem(last=False)


def _name(value: Any) -> str:
    name = " ".join(str(value or "").strip().split())
    return LIKES_PLAYLIST if name.casefold() == LIKES_PLAYLIST else name


def _refs(operation: dict[str, Any]) -> list[str]:
    values = operation.get("refs")
    if values is None and operation.get("ref") is not None:
        values = [operation.get("ref")]
    if not isinstance(values, list):
        return []
    return [str(value).strip() for value in values if str(value).strip()]


def _resolved_tracks(refs: list[str], *, playable: bool) -> list[dict[str, Any]]:
    tracks: list[dict[str, Any]] = []
    for ref in refs:
        track = resolve_track_reference(ref)
        if track is None:
            raise ModifyError(
                f"Track reference is invalid or expired: {ref}.",
                "INVALID_REF",
            )
        if playable and not track.get("playable"):
            raise ModifyError(
                f"Track reference is metadata-only and cannot enter up next: {ref}.",
                "REF_NOT_PLAYABLE",
            )
        tracks.append(
            {
                **track,
                "ref": ref,
                "name": str(track.get("name") or track.get("title") or "").strip(),
            }
        )
    return tracks


def _existing_playlist_names() -> set[str]:
    return {
        str(item.get("name") or "").casefold()
        for item in list_playlists()
        if str(item.get("source_app") or "Sonex") == "Sonex"
    }


def _load_playlist(
    name: str,
    before: dict[str, dict[str, Any]],
    after: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    if name not in after:
        snapshot = playlist_snapshot(name)
        before[name] = snapshot
        after[name] = {
            **snapshot,
            "tracks": [dict(track) for track in snapshot.get("tracks") or []],
        }
    return after[name]


def _item_ref(track: dict[str, Any]) -> str:
    explicit = str(track.get("ref") or "").strip()
    if explicit:
        return explicit
    provider = str(track.get("provider") or track.get("source") or "unknown").strip().casefold()
    for key in ("uri", "id", "cache_id", "url"):
        value = str(track.get(key) or "").strip()
        if value:
            return f"{provider}:{key}:{value}"
    return str(track.get("key") or "").strip()


def _track_index(tracks: list[dict[str, Any]], ref: str) -> int | None:
    for index, track in enumerate(tracks):
        if _item_ref(track) == ref:
            return index
    return None


def _apply_playlist_operation(
    operation: dict[str, Any],
    *,
    before: dict[str, dict[str, Any]],
    after: dict[str, dict[str, Any]],
    deletes: set[str],
    existing_names: set[str],
) -> tuple[int, str]:
    action = str(operation.get("action") or "").strip().casefold()
    if action not in PLAYLIST_ACTIONS:
        raise ModifyError(f"Unsupported playlist action: {action or '-'}.", "ACTION_UNSUPPORTED")
    name = _name(operation.get("name") or LIKES_PLAYLIST)
    if not name:
        raise ModifyError("Playlist operations require name.", "INVALID_ARGUMENT")
    protected = name.casefold() == LIKES_PLAYLIST

    if action == "create":
        if name.casefold() in existing_names:
            raise ModifyError(f"Playlist already exists: {name}.", "ALREADY_EXISTS")
        state = _load_playlist(name, before, after)
        state["created_at"] = state.get("created_at") or time.time()
        state["updated_at"] = time.time()
        existing_names.add(name.casefold())
        return 0, f"Create playlist {name}"

    state = _load_playlist(name, before, after)
    tracks = list(state.get("tracks") or [])
    if action == "add":
        refs = _refs(operation)
        if not refs:
            raise ModifyError("Playlist add requires refs.", "INVALID_ARGUMENT")
        added = 0
        for track in _resolved_tracks(refs, playable=False):
            ref = str(track["ref"])
            if _track_index(tracks, ref) is not None:
                continue
            tracks.append({**track, "saved_at": time.time(), "key": ref})
            added += 1
        state["tracks"] = tracks
        state["created_at"] = state.get("created_at") or time.time()
        state["updated_at"] = time.time()
        existing_names.add(name.casefold())
        return added, f"Add {added} track(s) to {name}"

    if action == "remove":
        refs = set(_refs(operation))
        if not refs:
            raise ModifyError("Playlist remove requires refs.", "INVALID_ARGUMENT")
        kept = [track for track in tracks if _item_ref(track) not in refs]
        removed = len(tracks) - len(kept)
        state["tracks"] = kept
        state["updated_at"] = time.time()
        return removed, f"Remove {removed} track(s) from {name}"

    if action == "move":
        refs = _refs(operation)
        if len(refs) != 1:
            raise ModifyError("Playlist move requires exactly one ref.", "INVALID_ARGUMENT")
        index = _track_index(tracks, refs[0])
        if index is None:
            raise ModifyError("Track is not in the playlist.", "TRACK_NOT_FOUND")
        try:
            destination = max(0, min(len(tracks) - 1, int(operation.get("index"))))
        except (TypeError, ValueError):
            raise ModifyError("Playlist move requires index.", "INVALID_ARGUMENT") from None
        track = tracks.pop(index)
        tracks.insert(destination, track)
        state["tracks"] = tracks
        state["updated_at"] = time.time()
        return 0, f"Move one track in {name}"

    if action == "reorder":
        order = _refs(operation)
        current_refs = [_item_ref(track) for track in tracks]
        if len(order) != len(current_refs) or set(order) != set(current_refs):
            raise ModifyError(
                "Playlist reorder refs must exactly match the current playlist.",
                "INVALID_ARGUMENT",
            )
        by_ref = {_item_ref(track): track for track in tracks}
        state["tracks"] = [by_ref[ref] for ref in order]
        state["updated_at"] = time.time()
        return 0, f"Reorder {name}"

    if action == "rename":
        if protected:
            raise ModifyError("The likes playlist cannot be renamed.", "PROTECTED_PLAYLIST")
        new_name = _name(operation.get("new_name"))
        if not new_name:
            raise ModifyError("Playlist rename requires new_name.", "INVALID_ARGUMENT")
        if new_name.casefold() in existing_names:
            raise ModifyError(f"Playlist already exists: {new_name}.", "ALREADY_EXISTS")
        before[new_name] = playlist_snapshot(new_name)
        renamed = {**state, "name": new_name, "updated_at": time.time()}
        after[new_name] = renamed
        after.pop(name, None)
        deletes.add(name)
        existing_names.discard(name.casefold())
        existing_names.add(new_name.casefold())
        return 0, f"Rename {name} to {new_name}"

    if action == "clear":
        if protected:
            raise ModifyError("The likes playlist cannot be cleared.", "PROTECTED_PLAYLIST")
        affected = len(tracks)
        state["tracks"] = []
        state["updated_at"] = time.time()
        return affected, f"Clear {affected} track(s) from {name}"

    if protected:
        raise ModifyError("The likes playlist cannot be deleted.", "PROTECTED_PLAYLIST")
    affected = len(tracks)
    deletes.add(name)
    after.pop(name, None)
    existing_names.discard(name.casefold())
    return affected, f"Delete playlist {name}"


def _apply_up_next_operation(
    operation: dict[str, Any],
    state: dict[str, Any],
) -> tuple[int, str]:
    action = str(operation.get("action") or "").strip().casefold()
    if action not in UP_NEXT_ACTIONS:
        raise ModifyError(f"Unsupported up-next action: {action or '-'}.", "ACTION_UNSUPPORTED")
    items = list(state.get("items") or [])

    if action == "add":
        refs = _refs(operation)
        if not refs:
            raise ModifyError("Up-next add requires refs.", "INVALID_ARGUMENT")
        added = 0
        for track in _resolved_tracks(refs, playable=True):
            if _track_index(items, str(track["ref"])) is not None:
                continue
            items.append(track)
            added += 1
        state["items"] = items
        return added, f"Add {added} track(s) to up next"

    if action == "remove":
        refs = set(_refs(operation))
        if not refs:
            raise ModifyError("Up-next remove requires refs.", "INVALID_ARGUMENT")
        kept = [track for track in items if _item_ref(track) not in refs]
        removed = len(items) - len(kept)
        state["items"] = kept
        return removed, f"Remove {removed} track(s) from up next"

    if action == "move":
        refs = _refs(operation)
        if len(refs) != 1:
            raise ModifyError("Up-next move requires exactly one ref.", "INVALID_ARGUMENT")
        index = _track_index(items, refs[0])
        if index is None:
            raise ModifyError("Track is not in up next.", "TRACK_NOT_FOUND")
        try:
            destination = max(0, min(len(items) - 1, int(operation.get("index"))))
        except (TypeError, ValueError):
            raise ModifyError("Up-next move requires index.", "INVALID_ARGUMENT") from None
        item = items.pop(index)
        items.insert(destination, item)
        state["items"] = items
        return 0, "Move one track in up next"

    if action == "clear":
        affected = len(items)
        state["items"] = []
        return affected, f"Clear {affected} track(s) from up next"

    refs = _refs(operation)
    replacement = _resolved_tracks(refs, playable=True)
    affected = len(items)
    state["items"] = replacement
    return affected, f"Replace {affected} queued track(s) with {len(replacement)} track(s)"


def _build_plan(
    operations: list[dict[str, Any]],
    idempotency_key: str,
    fingerprint: str,
) -> _Plan:
    if not operations or not all(isinstance(item, dict) for item in operations):
        raise ModifyError("Modify requires a non-empty operations array.", "INVALID_ARGUMENT")
    playlist_before: dict[str, dict[str, Any]] = {}
    playlist_after: dict[str, dict[str, Any]] = {}
    playlist_deletes: set[str] = set()
    up_before: dict[str, Any] | None = None
    up_after: dict[str, Any] | None = None
    existing_names = _existing_playlist_names()
    affected_tracks = 0
    descriptions: list[str] = []
    destructive = False

    for operation in operations:
        target = str(operation.get("target") or "").strip().casefold()
        action = str(operation.get("action") or "").strip().casefold()
        destructive = destructive or action in DESTRUCTIVE_ACTIONS
        if target == "playlist":
            affected, description = _apply_playlist_operation(
                operation,
                before=playlist_before,
                after=playlist_after,
                deletes=playlist_deletes,
                existing_names=existing_names,
            )
        elif target == "up_next":
            if up_after is None:
                up_before = up_next_snapshot()
                up_after = {
                    **up_before,
                    "items": [dict(item) for item in up_before["items"]],
                    "failed": [dict(item) for item in up_before["failed"]],
                }
            affected, description = _apply_up_next_operation(operation, up_after)
        else:
            raise ModifyError(f"Unsupported modify target: {target or '-'}.", "TARGET_UNSUPPORTED")
        affected_tracks += affected
        descriptions.append(description)

    return _Plan(
        idempotency_key=idempotency_key,
        fingerprint=fingerprint,
        playlist_before=playlist_before,
        playlist_after=playlist_after,
        playlist_deletes=playlist_deletes,
        up_next_before=up_before,
        up_next_after=up_after,
        preview={
            "destructive": destructive,
            "affected_tracks": affected_tracks,
            "operations": descriptions,
        },
    )


def _assert_current_versions(plan: _Plan) -> None:
    for name, before in plan.playlist_before.items():
        current = playlist_snapshot(name)
        if int(current.get("revision") or 0) != int(before.get("revision") or 0):
            raise ModifyError(
                f"Playlist changed after preview: {name}.",
                "VERSION_CONFLICT",
            )
    if plan.up_next_before is not None:
        current = up_next_snapshot()
        if current["revision"] != plan.up_next_before["revision"]:
            raise ModifyError("Up next changed after preview.", "VERSION_CONFLICT")


def _storage_snapshots(plan: _Plan) -> dict[Path, bytes | None]:
    names = set(plan.playlist_before) | set(plan.playlist_after) | plan.playlist_deletes
    paths = {playlist_storage_path(name) for name in names}
    if plan.up_next_before is not None:
        paths.add(up_next_storage_path())
    paths.add(_idempotency_path())
    snapshots: dict[Path, bytes | None] = {}
    for path in paths:
        try:
            snapshots[path] = path.read_bytes()
        except FileNotFoundError:
            snapshots[path] = None
    return snapshots


def _restore_storage(snapshots: dict[Path, bytes | None]) -> None:
    for path, content in snapshots.items():
        if content is None:
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".rollback")
        temporary.write_bytes(content)
        temporary.replace(path)


def _commit(plan: _Plan) -> dict[str, Any]:
    _assert_current_versions(plan)
    storage_snapshots = _storage_snapshots(plan)
    versions: dict[str, int] = {}
    try:
        for name, state in plan.playlist_after.items():
            before = plan.playlist_before[name]
            committed = commit_playlist_state(
                state,
                expected_revision=int(before.get("revision") or 0),
            )
            versions[f"playlist:{name}"] = int(committed.get("revision") or 0)
        for name in plan.playlist_deletes:
            before = plan.playlist_before[name]
            delete_playlist_state(
                name,
                expected_revision=int(before.get("revision") or 0),
            )
            versions[f"playlist:{name}"] = int(before.get("revision") or 0) + 1
        if plan.up_next_after is not None and plan.up_next_before is not None:
            committed_up_next = commit_up_next_state(
                plan.up_next_after,
                expected_revision=plan.up_next_before["revision"],
            )
            versions["up_next"] = committed_up_next["revision"]
        result = ToolResult.success(
            tool="Modify",
            message=f"Applied {len(plan.preview['operations'])} local modification(s).",
            data={
                "changed_operations": len(plan.preview["operations"]),
                "affected_tracks": plan.preview["affected_tracks"],
                "versions": versions,
            },
        ).to_dict()
        _record_idempotency(plan, result)
        return result
    except Exception as exc:
        _restore_storage(storage_snapshots)
        if isinstance(exc, (PlaylistVersionConflict, UpNextVersionConflict)):
            raise ModifyError(str(exc), "VERSION_CONFLICT") from exc
        raise


def Modify(
    operations: list[dict[str, Any]],
    idempotency_key: str,
) -> dict[str, Any]:
    """Plan and atomically apply one batch of local music-library modifications."""
    key = str(idempotency_key or "").strip()
    if not key:
        return _failure("Modify requires idempotency_key.", "INVALID_ARGUMENT")
    with _MODIFY_LOCK:
        fingerprint = operation_fingerprint(operations)
        try:
            cached = _lookup_idempotency(key, fingerprint)
        except ModifyError as exc:
            return _failure(str(exc), exc.error_code)
        if cached is not None:
            return cached
        for token, pending in _PENDING.items():
            if pending.idempotency_key == key:
                if pending.fingerprint != fingerprint:
                    return _failure(
                        "The idempotency key is pending for different operations.",
                        "IDEMPOTENCY_CONFLICT",
                    )
                return {
                    "status": "requires_modify_confirmation",
                    "tool": "Modify",
                    "message": "Destructive local changes require confirmation.",
                    "data": {
                        "confirmation_token": token,
                        "preview": pending.preview,
                    },
                    "error_code": None,
                }
        try:
            plan = _build_plan(operations, key, fingerprint)
            if not plan.preview["destructive"]:
                return _commit(plan)
            token = uuid.uuid4().hex
            _PENDING[token] = plan
            while len(_PENDING) > _MAX_PENDING_MODIFICATIONS:
                _PENDING.popitem(last=False)
            return {
                "status": "requires_modify_confirmation",
                "tool": "Modify",
                "message": "Destructive local changes require confirmation.",
                "data": {
                    "confirmation_token": token,
                    "preview": plan.preview,
                    "choices": [
                        {"value": "allow_once", "label": "Yes, apply changes"},
                        {"value": "deny", "label": "No"},
                    ],
                },
                "error_code": None,
            }
        except ModifyError as exc:
            return _failure(str(exc), exc.error_code)


def complete_modify_confirmation(token: str, decision: Any) -> dict[str, Any]:
    """Commit or reject one previously previewed destructive modification."""
    normalized_token = str(token or "").strip()
    approved = (
        decision is True
        or str(decision or "").strip().casefold() in {"allow", "allow_once", "approve", "yes"}
    )
    with _MODIFY_LOCK:
        plan = _PENDING.pop(normalized_token, None)
        if plan is None:
            return _failure(
                "The modification preview expired or was already completed.",
                "CONFIRMATION_EXPIRED",
            )
        if not approved:
            result = {
                "status": "cancelled",
                "tool": "Modify",
                "message": "Local modification cancelled.",
                "data": {"reason": "user_rejected"},
                "error_code": None,
            }
            _record_idempotency(plan, result)
            return result
        try:
            return _commit(plan)
        except ModifyError as exc:
            return _failure(str(exc), exc.error_code)
