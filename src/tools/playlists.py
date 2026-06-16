"""Playlist persistence for Sonex playback and queue flows."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from src.log import sonex_home

LIKES_PLAYLIST = "likes"


def _default_playlists_root() -> Path:
    return sonex_home() / "cache" / "playlists"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _playlist_name(value: str | None) -> str:
    name = _text(value) or LIKES_PLAYLIST
    if name.casefold() == LIKES_PLAYLIST:
        return LIKES_PLAYLIST
    return " ".join(name.split())


def _playlist_slug(name: str) -> str:
    if name == LIKES_PLAYLIST:
        return LIKES_PLAYLIST
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", name.casefold()).strip("-._")
    return slug or "playlist"


def _root(playlists_root: Path | None = None) -> Path:
    root = playlists_root or _default_playlists_root()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _playlist_path(name: str, playlists_root: Path | None = None) -> Path:
    return _root(playlists_root) / f"{_playlist_slug(name)}.json"


def _empty_playlist(name: str) -> dict[str, Any]:
    return {
        "name": name,
        "protected": name == LIKES_PLAYLIST,
        "tracks": [],
        "created_at": None,
        "updated_at": None,
    }


def _load_playlist(name: str, playlists_root: Path | None = None) -> dict[str, Any]:
    path = _playlist_path(name, playlists_root)
    if not path.exists():
        return _empty_playlist(name)
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        loaded = {}
    playlist = _empty_playlist(name)
    if isinstance(loaded, dict):
        playlist.update(loaded)
    playlist["name"] = name
    playlist["protected"] = name == LIKES_PLAYLIST
    if not isinstance(playlist.get("tracks"), list):
        playlist["tracks"] = []
    return playlist


def _save_playlist(playlist: dict[str, Any], playlists_root: Path | None = None) -> None:
    name = _playlist_name(str(playlist.get("name") or LIKES_PLAYLIST))
    playlist = {**playlist, "name": name, "protected": name == LIKES_PLAYLIST}
    path = _playlist_path(name, playlists_root)
    path.write_text(json.dumps(playlist, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _track_key(track: dict[str, Any]) -> str:
    for key in ("cache_id", "uri", "url", "youtube_url", "apple_music_url", "spotify_url", "stream_url"):
        value = _text(track.get(key))
        if value:
            return f"{key}:{value}"
    name = _text(track.get("name") or track.get("title"))
    artist = _text(track.get("artist"))
    return f"text:{name.casefold()}|{artist.casefold()}"


def _track_snapshot(track: dict[str, Any], *, saved_at: float) -> dict[str, Any]:
    name = _text(track.get("name") or track.get("title"))
    if not name:
        raise ValueError("Playlist track requires a name.")
    artist = _text(track.get("artist")) or "-"
    snapshot = {
        "key": _track_key({**track, "name": name, "artist": artist}),
        "cache_id": _text(track.get("cache_id")) or None,
        "name": name,
        "title": name,
        "artist": artist,
        "album": _text(track.get("album")) or "-",
        "duration_ms": int(track.get("duration_ms") or 0),
        "provider": _text(track.get("provider") or track.get("source")) or "unknown",
        "saved_at": saved_at,
    }
    for key in ("uri", "url", "youtube_url", "spotify_url", "apple_music_url", "album_cover_url", "audio_path"):
        if track.get(key):
            snapshot[key] = track.get(key)
    return snapshot


def list_playlists(*, playlists_root: Path | None = None) -> list[dict[str, Any]]:
    root = _root(playlists_root)
    playlists: dict[str, dict[str, Any]] = {LIKES_PLAYLIST: _load_playlist(LIKES_PLAYLIST, root)}
    for path in sorted(root.glob("*.json")):
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(loaded, dict):
            continue
        name = _playlist_name(str(loaded.get("name") or path.stem))
        playlists[name] = _load_playlist(name, root)
    rows = []
    for name, playlist in playlists.items():
        rows.append(
            {
                "name": name,
                "protected": name == LIKES_PLAYLIST,
                "track_count": len(playlist.get("tracks") or []),
                "updated_at": playlist.get("updated_at"),
            }
        )
    return sorted(rows, key=lambda item: (item["name"] != LIKES_PLAYLIST, str(item["name"]).casefold()))


def playlist_choices(*, playlists_root: Path | None = None) -> list[dict[str, str]]:
    choices = []
    for playlist in list_playlists(playlists_root=playlists_root):
        count = int(playlist.get("track_count") or 0)
        choices.append(
            {
                "value": f"playlist:{playlist['name']}",
                "label": str(playlist["name"]),
                "description": f"{count} saved track" + ("" if count == 1 else "s"),
            }
        )
    return choices


def create_playlist(name: str, *, playlists_root: Path | None = None) -> dict[str, Any]:
    playlist_name = _playlist_name(name)
    path = _playlist_path(playlist_name, playlists_root)
    if path.exists():
        playlist = _load_playlist(playlist_name, playlists_root)
    else:
        playlist = _empty_playlist(playlist_name)
        _save_playlist(playlist, playlists_root)
    tracks = list(playlist.get("tracks") or [])
    return {
        "name": str(playlist.get("name") or playlist_name),
        "protected": playlist_name == LIKES_PLAYLIST,
        "track_count": len(tracks),
        "updated_at": playlist.get("updated_at"),
    }


def save_track_to_playlist(
    track: dict[str, Any],
    *,
    playlist_name: str = LIKES_PLAYLIST,
    playlists_root: Path | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    name = _playlist_name(playlist_name)
    timestamp = time.time() if now is None else float(now)
    playlist = _load_playlist(name, playlists_root)
    if playlist.get("created_at") is None:
        playlist["created_at"] = timestamp
    snapshot = _track_snapshot(track, saved_at=timestamp)
    tracks = list(playlist.get("tracks") or [])
    duplicate = next((item for item in tracks if item.get("key") == snapshot["key"]), None)
    if duplicate is None:
        tracks.append(snapshot)
        playlist["tracks"] = tracks
        playlist["updated_at"] = timestamp
        _save_playlist(playlist, playlists_root)
        added = True
        saved_track = snapshot
    else:
        saved_track = duplicate
        added = False
    return {
        "added": added,
        "playlist": {
            "name": name,
            "protected": name == LIKES_PLAYLIST,
            "track_count": len(tracks),
            "updated_at": playlist.get("updated_at"),
        },
        "track": saved_track,
    }


def list_playlist_tracks(
    playlist_name: str = LIKES_PLAYLIST,
    *,
    playlists_root: Path | None = None,
) -> list[dict[str, Any]]:
    playlist = _load_playlist(_playlist_name(playlist_name), playlists_root)
    return list(playlist.get("tracks") or [])
