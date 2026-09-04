"""Bounded structured track references shared by Agent music tools."""

from __future__ import annotations

import hashlib
import json
import threading
from collections import OrderedDict
from typing import Any


_MAX_TRACK_REFS = 2048
_TRACK_REFS: OrderedDict[str, dict[str, Any]] = OrderedDict()
_TRACK_REFS_LOCK = threading.Lock()
_PLAYABLE_PROVIDERS = {"local", "spotify"}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _reference_key(provider: str, track: dict[str, Any]) -> tuple[str, str]:
    for key in ("uri", "id", "cache_id", "url"):
        value = _text(track.get(key))
        if value:
            return key, value
    canonical = {
        "provider": provider,
        "name": _text(track.get("name") or track.get("title")).casefold(),
        "artist": _text(track.get("artist")).casefold(),
        "album": _text(track.get("album")).casefold(),
        "duration_ms": int(track.get("duration_ms") or 0),
    }
    digest = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:24]
    return "metadata", digest


def remember_track_reference(
    provider: str,
    track: dict[str, Any],
    *,
    playable: bool | None = None,
) -> str:
    """Store one bounded canonical track snapshot and return its opaque reference."""
    normalized_provider = _text(provider).casefold().replace("-", "_") or "unknown"
    key, value = _reference_key(normalized_provider, track)
    ref = f"{normalized_provider}:{key}:{value}"
    resolved_playable = (
        normalized_provider in _PLAYABLE_PROVIDERS
        if playable is None
        else bool(playable)
    )
    snapshot = {
        **track,
        "provider": normalized_provider,
        "ref": ref,
        "playable": resolved_playable,
    }
    with _TRACK_REFS_LOCK:
        _TRACK_REFS[ref] = snapshot
        _TRACK_REFS.move_to_end(ref)
        while len(_TRACK_REFS) > _MAX_TRACK_REFS:
            _TRACK_REFS.popitem(last=False)
    return ref


def remember_existing_track_reference(
    ref: str,
    provider: str,
    track: dict[str, Any],
    *,
    playable: bool,
) -> str:
    """Attach structured metadata to an existing opaque playback reference."""
    normalized_ref = _text(ref)
    normalized_provider = _text(provider).casefold().replace("-", "_") or "unknown"
    snapshot = {
        **track,
        "provider": normalized_provider,
        "ref": normalized_ref,
        "playable": bool(playable),
    }
    with _TRACK_REFS_LOCK:
        _TRACK_REFS[normalized_ref] = snapshot
        _TRACK_REFS.move_to_end(normalized_ref)
        while len(_TRACK_REFS) > _MAX_TRACK_REFS:
            _TRACK_REFS.popitem(last=False)
    return normalized_ref


def resolve_track_reference(ref: str) -> dict[str, Any] | None:
    """Resolve one reference produced by a Sonex read tool."""
    normalized = _text(ref)
    with _TRACK_REFS_LOCK:
        item = _TRACK_REFS.get(normalized)
        if item is None:
            return None
        _TRACK_REFS.move_to_end(normalized)
        return dict(item)
