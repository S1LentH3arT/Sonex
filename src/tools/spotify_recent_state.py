"""Pure recent-track identity and projection rules for Spotify playback."""

from __future__ import annotations

import re
from typing import Any


def artists_text(artists: list[dict[str, Any]]) -> str:
    return ", ".join(artist.get("name") for artist in artists if artist.get("name"))


def track_key(track: dict[str, Any]) -> str | None:
    key = track.get("uri") or track.get("id") or track.get("spotify_url")
    return str(key) if key else None


def compact_track(track: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": track.get("id"),
        "name": track.get("name") or track.get("title"),
        "duration_ms": track.get("duration_ms") or 0,
        "artist": track.get("artist") or artists_text(track.get("artists") or []),
        "artists": track.get("artists") or [],
        "album": track.get("album"),
        "album_cover_url": track.get("album_cover_url") or track.get("image_url") or track.get("cover_url"),
        "album_cover_path": track.get("album_cover_path"),
        "spotify_url": track.get("spotify_url"),
        "uri": track.get("uri"),
        "is_playable": track.get("is_playable"),
        "cached_at": track.get("cached_at"),
        "last_played_at": track.get("last_played_at") or track.get("played_at"),
    }


def query_terms(value: str) -> list[str]:
    return [part for part in re.split(r"\W+", value.lower()) if part]
