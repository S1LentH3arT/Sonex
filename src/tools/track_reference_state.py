"""Pure normalization and snapshot rules for structured track references."""

from __future__ import annotations

import hashlib
import json
from typing import Any


PLAYABLE_PROVIDERS = {"local", "spotify"}


def normalize_provider(provider: Any) -> str:
    return str(provider or "").strip().casefold().replace("-", "_") or "unknown"


def reference_key(provider: str, track: dict[str, Any]) -> tuple[str, str]:
    for key in ("uri", "id", "cache_id", "url"):
        value = str(track.get(key) or "").strip()
        if value:
            return key, value
    canonical = {
        "provider": provider,
        "name": str(track.get("name") or track.get("title") or "").strip().casefold(),
        "artist": str(track.get("artist") or "").strip().casefold(),
        "album": str(track.get("album") or "").strip().casefold(),
        "duration_ms": int(track.get("duration_ms") or 0),
    }
    digest = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:24]
    return "metadata", digest


def track_reference_snapshot(
    ref: str,
    provider: str,
    track: dict[str, Any],
    *,
    playable: bool,
) -> dict[str, Any]:
    return {
        **track,
        "provider": provider,
        "ref": ref,
        "playable": bool(playable),
    }
