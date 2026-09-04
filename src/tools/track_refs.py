"""Bounded structured track references shared by Agent music tools."""

from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Any

from src.tools.track_reference_state import (
    PLAYABLE_PROVIDERS,
    normalize_provider,
    reference_key,
    track_reference_snapshot,
)


_MAX_TRACK_REFS = 2048
_TRACK_REFS: OrderedDict[str, dict[str, Any]] = OrderedDict()
_TRACK_REFS_LOCK = threading.Lock()


def _text(value: Any) -> str:
    return str(value or "").strip()


def remember_track_reference(
    provider: str,
    track: dict[str, Any],
    *,
    playable: bool | None = None,
) -> str:
    """Store one bounded canonical track snapshot and return its opaque reference."""
    normalized_provider = normalize_provider(provider)
    key, value = reference_key(normalized_provider, track)
    ref = f"{normalized_provider}:{key}:{value}"
    resolved_playable = (
        normalized_provider in PLAYABLE_PROVIDERS
        if playable is None
        else bool(playable)
    )
    snapshot = track_reference_snapshot(
        ref,
        normalized_provider,
        track,
        playable=resolved_playable,
    )
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
    normalized_ref = str(ref or "").strip()
    normalized_provider = normalize_provider(provider)
    snapshot = track_reference_snapshot(
        normalized_ref,
        normalized_provider,
        track,
        playable=playable,
    )
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
