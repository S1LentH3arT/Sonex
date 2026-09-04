"""Pure identity and snapshot rules for the persistent playback queue."""

from __future__ import annotations

from datetime import datetime
from typing import Any


def text(value: Any) -> str:
    return str(value or "").strip()


def played_at_value(value: Any, fallback: float) -> float:
    if isinstance(value, int | float):
        return float(value)
    normalized = text(value)
    if not normalized:
        return fallback
    try:
        return float(normalized)
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(normalized.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return fallback


def track_key(track: dict[str, Any]) -> str:
    for key in (
        "cache_id",
        "uri",
        "spotify_url",
        "youtube_url",
        "url",
        "stream_url",
        "audio_path",
        "file_path",
        "path",
        "id",
    ):
        value = text(track.get(key))
        if value:
            return f"{key}:{value}"
    name = text(track.get("name") or track.get("title"))
    artist = text(track.get("artist"))
    album = text(track.get("album"))
    duration = int(track.get("duration_ms") or 0)
    if not name:
        return ""
    if artist or album or duration or text(track.get("provider") or track.get("source")) == "local":
        return f"text:{name.casefold()}|{artist.casefold()}|{album.casefold()}|{duration}"
    return ""


def snapshot_track(track: dict[str, Any], *, played_at: float) -> dict[str, Any] | None:
    name = text(track.get("name") or track.get("title"))
    key = track_key(track)
    if not name or not key:
        return None
    snapshot: dict[str, Any] = {
        "key": key,
        "name": name,
        "title": name,
        "artist": text(track.get("artist")) or "-",
        "album": text(track.get("album")) or "-",
        "duration_ms": int(track.get("duration_ms") or 0),
        "provider": text(track.get("provider") or track.get("source")) or "unknown",
        "source": text(track.get("source")) or None,
        "played_at": played_at,
    }
    for field in (
        "cache_id",
        "uri",
        "url",
        "stream_url",
        "youtube_url",
        "spotify_url",
        "audio_path",
        "file_path",
        "path",
        "album_cover_url",
        "id",
        "requires_resolution",
    ):
        value = track.get(field)
        if value:
            snapshot[field] = value
    if track.get("requires_resolution"):
        snapshot["playable"] = False
    return snapshot
