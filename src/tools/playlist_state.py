"""Pure normalization and snapshot rules for local playlists."""

from __future__ import annotations

import re
from typing import Any

from src.music.legacy_tracks import downgrade_retired_provider_track


LIKES_PLAYLIST = "likes"
SOURCE_SONEX = "Sonex"


def _text(value: Any) -> str:
    return str(value or "").strip()


def normalize_playlist_name(value: str | None) -> str:
    name = _text(value) or LIKES_PLAYLIST
    if name.casefold() == LIKES_PLAYLIST:
        return LIKES_PLAYLIST
    return " ".join(name.split())


def normalize_source_app(value: str | None) -> str:
    source = _text(value) or SOURCE_SONEX
    if source.casefold() == SOURCE_SONEX.casefold():
        return SOURCE_SONEX
    if source.casefold() == "spotify":
        return "Spotify"
    if source.casefold() == "itunes":
        return "iTunes"
    return " ".join(source.split())


def empty_playlist(
    name: str,
    *,
    source_app: str = SOURCE_SONEX,
    external_id: str | None = None,
) -> dict[str, Any]:
    source = normalize_source_app(source_app)
    external = _text(external_id) or None
    protected = source == SOURCE_SONEX and name == LIKES_PLAYLIST
    readonly = source != SOURCE_SONEX
    return {
        "name": name,
        "source_app": source,
        "external_id": external,
        "readonly": readonly,
        "protected": protected,
        "tracks": [],
        "revision": 0,
        "created_at": None,
        "updated_at": None,
    }


def coerce_playlist(
    loaded: dict[str, Any],
    *,
    fallback_name: str,
    fallback_source_app: str = SOURCE_SONEX,
    fallback_external_id: str | None = None,
) -> dict[str, Any]:
    source = normalize_source_app(str(loaded.get("source_app") or fallback_source_app))
    name = normalize_playlist_name(str(loaded.get("name") or fallback_name))
    external = _text(loaded.get("external_id") or fallback_external_id) or None
    playlist = empty_playlist(name, source_app=source, external_id=external)
    playlist.update(loaded)
    playlist["name"] = name
    playlist["source_app"] = source
    playlist["external_id"] = external
    playlist["readonly"] = bool(loaded.get("readonly")) or source != SOURCE_SONEX
    playlist["protected"] = source == SOURCE_SONEX and name == LIKES_PLAYLIST
    raw_tracks = playlist.get("tracks")
    playlist["tracks"] = (
        [
            downgrade_retired_provider_track(track)[0]
            for track in raw_tracks
            if isinstance(track, dict)
        ]
        if isinstance(raw_tracks, list)
        else []
    )
    try:
        playlist["revision"] = max(0, int(playlist.get("revision") or 0))
    except (TypeError, ValueError):
        playlist["revision"] = 0
    return playlist


def track_key(track: dict[str, Any]) -> str:
    for key in ("cache_id", "uri", "url", "youtube_url", "spotify_url", "stream_url"):
        value = _text(track.get(key))
        if value:
            return f"{key}:{value}"
    name = _text(track.get("name") or track.get("title"))
    artist = _text(track.get("artist"))
    return f"text:{name.casefold()}|{artist.casefold()}"


def track_snapshot(track: dict[str, Any], *, saved_at: float) -> dict[str, Any]:
    track, _ = downgrade_retired_provider_track(track)
    name = _text(track.get("name") or track.get("title"))
    if not name:
        raise ValueError("Playlist track requires a name.")
    artist = _text(track.get("artist")) or "-"
    snapshot = {
        "key": track_key({**track, "name": name, "artist": artist}),
        "cache_id": _text(track.get("cache_id")) or None,
        "name": name,
        "title": name,
        "artist": artist,
        "album": _text(track.get("album")) or "-",
        "duration_ms": int(track.get("duration_ms") or 0),
        "provider": _text(track.get("provider") or track.get("source")) or "unknown",
        "saved_at": saved_at,
    }
    for key in (
        "uri",
        "url",
        "youtube_url",
        "spotify_url",
        "album_cover_url",
        "audio_path",
        "added_at",
        "requires_resolution",
        "playable",
    ):
        if track.get(key):
            snapshot[key] = track.get(key)
    if track.get("requires_resolution"):
        snapshot["playable"] = False
    return snapshot
