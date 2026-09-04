"""Persistent, editable queue of tracks scheduled after current playback."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

from src.log import sonex_home
from src.music.legacy_tracks import is_retired_provider_track
from src.tools.up_next_state import (
    MAX_FAILED_UP_NEXT,
    MAX_UP_NEXT,
    append_up_next_state,
    coerce_up_next_state,
    consume_up_next_head_state,
    empty_up_next_state,
    fail_up_next_head_state,
)


_UP_NEXT_LOCK = threading.RLock()


class UpNextVersionConflict(RuntimeError):
    """Raised when an edit was planned against a stale queue revision."""


def _default_up_next_path() -> Path:
    return sonex_home() / "cache" / "up_next.json"


def _path(queue_path: Path | None = None) -> Path:
    path = queue_path or _default_up_next_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _empty_state() -> dict[str, Any]:
    return empty_up_next_state()


def _coerce_state(value: Any) -> dict[str, Any]:
    return coerce_up_next_state(value)


def _load(path: Path) -> dict[str, Any]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return _empty_state()
    loaded_items = loaded.get("items") if isinstance(loaded, dict) else None
    loaded_failed = loaded.get("failed") if isinstance(loaded, dict) else None
    persisted_tracks = (
        (loaded_items if isinstance(loaded_items, list) else [])
        + (loaded_failed if isinstance(loaded_failed, list) else [])
    )
    needs_migration = any(
        isinstance(item, dict) and is_retired_provider_track(item)
        for item in persisted_tracks
    )
    state = _coerce_state(loaded)
    if needs_migration:
        _save(path, state)
    return state


def _save(path: Path, state: dict[str, Any]) -> None:
    payload = {
        "version": 1,
        "revision": int(state["revision"]),
        "items": list(state["items"])[:MAX_UP_NEXT],
        "failed": list(state["failed"])[:MAX_FAILED_UP_NEXT],
    }
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def up_next_snapshot(*, queue_path: Path | None = None) -> dict[str, Any]:
    """Return a detached snapshot of the persistent upcoming queue."""
    with _UP_NEXT_LOCK:
        state = _load(_path(queue_path))
        return {
            "revision": state["revision"],
            "items": [dict(item) for item in state["items"]],
            "failed": [dict(item) for item in state["failed"]],
        }


def up_next_storage_path(*, queue_path: Path | None = None) -> Path:
    """Return the canonical queue path for transaction coordination."""
    return _path(queue_path)


def commit_up_next_state(
    state: dict[str, Any],
    *,
    expected_revision: int,
    queue_path: Path | None = None,
) -> dict[str, Any]:
    """Atomically replace queue contents when the observed revision still matches."""
    path = _path(queue_path)
    with _UP_NEXT_LOCK:
        current = _load(path)
        if current["revision"] != int(expected_revision):
            raise UpNextVersionConflict(
                f"Expected up-next revision {expected_revision}, found {current['revision']}."
            )
        proposed = _coerce_state(state)
        proposed["revision"] = current["revision"] + 1
        _save(path, proposed)
        return {
            "revision": proposed["revision"],
            "items": [dict(item) for item in proposed["items"]],
            "failed": [dict(item) for item in proposed["failed"]],
        }


def consume_up_next_head(*, queue_path: Path | None = None) -> dict[str, Any]:
    """Remove the head only after the caller has confirmed playback started."""
    with _UP_NEXT_LOCK:
        current = up_next_snapshot(queue_path=queue_path)
        next_state = consume_up_next_head_state(current)
        if next_state is current:
            return current
        current = next_state
        return commit_up_next_state(
            current,
            expected_revision=current["revision"],
            queue_path=queue_path,
        )


def append_up_next_track(
    track: dict[str, Any],
    *,
    queue_path: Path | None = None,
) -> dict[str, Any]:
    """Idempotently append one already-resolved playable track."""
    with _UP_NEXT_LOCK:
        current = up_next_snapshot(queue_path=queue_path)
        next_state = append_up_next_state(current, track)
        if next_state is current:
            return current
        current = next_state
        return commit_up_next_state(
            current,
            expected_revision=current["revision"],
            queue_path=queue_path,
        )


def fail_up_next_head(
    reason: str,
    *,
    queue_path: Path | None = None,
) -> dict[str, Any]:
    """Move one failed head to bounded failure history and advance the queue."""
    with _UP_NEXT_LOCK:
        current = up_next_snapshot(queue_path=queue_path)
        next_state = fail_up_next_head_state(current, reason, failed_at=time.time())
        if next_state is current:
            return current
        current = next_state
        return commit_up_next_state(
            current,
            expected_revision=current["revision"],
            queue_path=queue_path,
        )
