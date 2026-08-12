"""Compatibility helpers for tracks saved by retired playback providers."""

from __future__ import annotations

from typing import Any


_RETIRED_PLAYBACK_PROVIDERS = frozenset({"apple", "apple_music"})
_RETIRED_REFERENCE_PREFIXES = ("apple:", "apple_music:")


def is_retired_provider_track(track: dict[str, Any]) -> bool:
    """Return whether a persisted track depends on a retired playback route."""
    provider = str(track.get("provider") or "").strip().casefold()
    source = str(track.get("source") or "").strip().casefold()
    uri = str(track.get("uri") or "").strip().casefold()
    ref = str(track.get("ref") or "").strip().casefold()
    return (
        provider in _RETIRED_PLAYBACK_PROVIDERS
        or source in _RETIRED_PLAYBACK_PROVIDERS
        or uri.startswith(_RETIRED_REFERENCE_PREFIXES)
        or ref.startswith(_RETIRED_REFERENCE_PREFIXES)
    )


def downgrade_retired_provider_track(track: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Keep descriptive metadata while removing retired playback references."""
    normalized = dict(track)
    if not is_retired_provider_track(normalized):
        return normalized, False

    retired_url = str(normalized.get("apple_music_url") or "").strip()
    for key in (
        "apple_music_url",
        "id",
        "uri",
        "ref",
        "cache_id",
        "audio_path",
        "file_path",
        "path",
        "stream_url",
        "youtube_url",
        "spotify_url",
    ):
        normalized.pop(key, None)
    url = str(normalized.get("url") or "").strip()
    if not url or url == retired_url or "music.apple.com/" in url.casefold():
        normalized.pop("url", None)
    normalized["provider"] = "metadata"
    normalized["source"] = "metadata"
    normalized["playable"] = False
    normalized["requires_resolution"] = True
    normalized.pop("key", None)
    return normalized, normalized != track
