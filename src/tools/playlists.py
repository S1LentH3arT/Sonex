"""Playlist persistence for Sonex playback and queue flows."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from src.log import sonex_home
from src.music.legacy_tracks import downgrade_retired_provider_track, is_retired_provider_track

LIKES_PLAYLIST = "likes"
SOURCE_SONEX = "Sonex"
SPOTIFY_LIBRARY_PLAYLIST = "Spotify Library"
SPOTIFY_LIBRARY_EXTERNAL_ID = "spotify-library"


class PlaylistVersionConflict(RuntimeError):
    """Raised when a playlist write was planned against a stale revision."""


def _default_playlists_root() -> Path:
    return sonex_home() / "cache" / "playlists"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _playlist_name(value: str | None) -> str:
    name = _text(value) or LIKES_PLAYLIST
    if name.casefold() == LIKES_PLAYLIST:
        return LIKES_PLAYLIST
    return " ".join(name.split())


def _source_app(value: str | None) -> str:
    source = _text(value) or SOURCE_SONEX
    if source.casefold() == SOURCE_SONEX.casefold():
        return SOURCE_SONEX
    if source.casefold() == "spotify":
        return "Spotify"
    if source.casefold() == "itunes":
        return "iTunes"
    return " ".join(source.split())


def _playlist_slug(name: str) -> str:
    if name == LIKES_PLAYLIST:
        return LIKES_PLAYLIST
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", name.casefold()).strip("-._")
    return slug or "playlist"


def _root(playlists_root: Path | None = None) -> Path:
    root = playlists_root or _default_playlists_root()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _playlist_path(
    name: str,
    playlists_root: Path | None = None,
    *,
    source_app: str = SOURCE_SONEX,
    external_id: str | None = None,
) -> Path:
    source = _source_app(source_app)
    external = _text(external_id)
    if source == SOURCE_SONEX and not external:
        filename = f"{_playlist_slug(name)}.json"
    else:
        identifier = external or name
        filename = f"{_playlist_slug(source)}--{_playlist_slug(identifier)}.json"
    return _root(playlists_root) / filename


def _empty_playlist(
    name: str,
    *,
    source_app: str = SOURCE_SONEX,
    external_id: str | None = None,
) -> dict[str, Any]:
    source = _source_app(source_app)
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


def _coerce_playlist(
    loaded: dict[str, Any],
    *,
    fallback_name: str,
    fallback_source_app: str = SOURCE_SONEX,
    fallback_external_id: str | None = None,
) -> dict[str, Any]:
    source = _source_app(str(loaded.get("source_app") or fallback_source_app))
    name = _playlist_name(str(loaded.get("name") or fallback_name))
    external = _text(loaded.get("external_id") or fallback_external_id) or None
    playlist = _empty_playlist(name, source_app=source, external_id=external)
    playlist.update(loaded)
    playlist["name"] = name
    playlist["source_app"] = source
    playlist["external_id"] = external
    playlist["readonly"] = bool(loaded.get("readonly")) or source != SOURCE_SONEX
    playlist["protected"] = source == SOURCE_SONEX and name == LIKES_PLAYLIST
    if not isinstance(playlist.get("tracks"), list):
        playlist["tracks"] = []
    else:
        playlist["tracks"] = [
            downgrade_retired_provider_track(track)[0]
            for track in playlist["tracks"]
            if isinstance(track, dict)
        ]
    try:
        playlist["revision"] = max(0, int(playlist.get("revision") or 0))
    except (TypeError, ValueError):
        playlist["revision"] = 0
    return playlist


def _load_playlist(
    name: str,
    playlists_root: Path | None = None,
    *,
    source_app: str = SOURCE_SONEX,
    external_id: str | None = None,
) -> dict[str, Any]:
    name = _playlist_name(name)
    source = _source_app(source_app)
    external = _text(external_id) or None
    path = _playlist_path(name, playlists_root, source_app=source, external_id=external)
    if not path.exists():
        return _empty_playlist(name, source_app=source, external_id=external)
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        loaded = {}
    if not isinstance(loaded, dict):
        loaded = {}
    loaded_tracks = loaded.get("tracks")
    needs_migration = isinstance(loaded_tracks, list) and any(
        isinstance(track, dict) and is_retired_provider_track(track)
        for track in loaded_tracks
    )
    playlist = _coerce_playlist(
        loaded,
        fallback_name=name,
        fallback_source_app=source,
        fallback_external_id=external,
    )
    if needs_migration:
        _save_playlist(playlist, playlists_root)
    return playlist


def _save_playlist(playlist: dict[str, Any], playlists_root: Path | None = None) -> None:
    name = _playlist_name(str(playlist.get("name") or LIKES_PLAYLIST))
    source = _source_app(str(playlist.get("source_app") or SOURCE_SONEX))
    external = _text(playlist.get("external_id")) or None
    playlist = {
        **playlist,
        "name": name,
        "source_app": source,
        "external_id": external,
        "readonly": bool(playlist.get("readonly")) or source != SOURCE_SONEX,
        "protected": source == SOURCE_SONEX and name == LIKES_PLAYLIST,
        "revision": max(0, int(playlist.get("revision") or 0)),
    }
    path = _playlist_path(name, playlists_root, source_app=source, external_id=external)
    path.write_text(json.dumps(playlist, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _track_key(track: dict[str, Any]) -> str:
    for key in ("cache_id", "uri", "url", "youtube_url", "spotify_url", "stream_url"):
        value = _text(track.get(key))
        if value:
            return f"{key}:{value}"
    name = _text(track.get("name") or track.get("title"))
    artist = _text(track.get("artist"))
    return f"text:{name.casefold()}|{artist.casefold()}"


def _track_snapshot(track: dict[str, Any], *, saved_at: float) -> dict[str, Any]:
    track, _ = downgrade_retired_provider_track(track)
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


def _playlist_label(playlist: dict[str, Any]) -> str:
    name = str(playlist.get("name") or LIKES_PLAYLIST)
    source = _source_app(str(playlist.get("source_app") or SOURCE_SONEX))
    if source == SOURCE_SONEX:
        return name
    return f"[{source}] {name}"


def _playlist_ref_value(playlist: dict[str, Any]) -> str:
    name = str(playlist.get("name") or LIKES_PLAYLIST)
    source = _source_app(str(playlist.get("source_app") or SOURCE_SONEX))
    external = _text(playlist.get("external_id"))
    if source == SOURCE_SONEX and not external:
        return f"playlist:{name}"
    return f"playlist_ref:{source}:{external or name}"


def _playlist_sort_key(playlist: dict[str, Any]) -> tuple[bool, str, str]:
    name = str(playlist.get("name") or "").casefold()
    source = _source_app(str(playlist.get("source_app") or SOURCE_SONEX))
    source_rank = "0" if source == SOURCE_SONEX else source.casefold()
    return (not (source == SOURCE_SONEX and name == LIKES_PLAYLIST), name, source_rank)


def list_playlists(*, playlists_root: Path | None = None) -> list[dict[str, Any]]:
    root = _root(playlists_root)
    playlists: dict[tuple[str, str, str], dict[str, Any]] = {}
    likes = _load_playlist(LIKES_PLAYLIST, root)
    playlists[(SOURCE_SONEX, "", LIKES_PLAYLIST)] = likes
    for path in sorted(root.glob("*.json")):
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(loaded, dict):
            continue
        playlist = _coerce_playlist(loaded, fallback_name=path.stem)
        key = (
            str(playlist.get("source_app") or SOURCE_SONEX),
            str(playlist.get("external_id") or ""),
            str(playlist.get("name") or LIKES_PLAYLIST),
        )
        playlists[key] = playlist
    rows = []
    for playlist in playlists.values():
        name = str(playlist.get("name") or LIKES_PLAYLIST)
        source = _source_app(str(playlist.get("source_app") or SOURCE_SONEX))
        external = _text(playlist.get("external_id")) or None
        rows.append(
            {
                "name": name,
                "label": _playlist_label(playlist),
                "value": _playlist_ref_value(playlist),
                "source_app": source,
                "external_id": external,
                "readonly": bool(playlist.get("readonly")),
                "protected": source == SOURCE_SONEX and name == LIKES_PLAYLIST,
                "track_count": len(playlist.get("tracks") or []),
                "updated_at": playlist.get("updated_at"),
            }
        )
    return sorted(rows, key=_playlist_sort_key)


def playlist_choices(*, playlists_root: Path | None = None, writable_only: bool = True) -> list[dict[str, Any]]:
    choices = []
    for playlist in list_playlists(playlists_root=playlists_root):
        if writable_only and playlist.get("readonly"):
            continue
        count = int(playlist.get("track_count") or 0)
        choices.append(
            {
                "value": str(playlist.get("value") or f"playlist:{playlist['name']}"),
                "label": str(playlist.get("label") or playlist["name"]),
                "description": f"{count} saved track" + ("" if count == 1 else "s"),
                "track_count": count,
                "name": str(playlist.get("name") or LIKES_PLAYLIST),
                "source_app": str(playlist.get("source_app") or SOURCE_SONEX),
                "external_id": str(playlist.get("external_id") or ""),
                "readonly": str(bool(playlist.get("readonly"))).lower(),
            }
        )
    return choices


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
    if playlist.get("readonly"):
        raise ValueError(f"Playlist {name} is read-only.")
    if playlist.get("created_at") is None:
        playlist["created_at"] = timestamp
    snapshot = _track_snapshot(track, saved_at=timestamp)
    tracks = list(playlist.get("tracks") or [])
    duplicate = next((item for item in tracks if item.get("key") == snapshot["key"]), None)
    if duplicate is None:
        tracks.append(snapshot)
        playlist["tracks"] = tracks
        playlist["revision"] = int(playlist.get("revision") or 0) + 1
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
            "source_app": SOURCE_SONEX,
            "external_id": None,
            "readonly": False,
            "protected": name == LIKES_PLAYLIST,
            "track_count": len(tracks),
            "updated_at": playlist.get("updated_at"),
        },
        "track": saved_track,
    }


def upsert_mirror_playlist(
    *,
    source_app: str,
    name: str,
    tracks: list[dict[str, Any]],
    external_id: str | None = None,
    playlists_root: Path | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    source = _source_app(source_app)
    if source == SOURCE_SONEX:
        raise ValueError("Mirror playlists must use a non-Sonex source.")
    playlist_name = _playlist_name(name)
    timestamp = time.time() if now is None else float(now)
    existing = _load_playlist(playlist_name, playlists_root, source_app=source, external_id=external_id)
    snapshots: list[dict[str, Any]] = []
    for track in tracks:
        try:
            snapshots.append(_track_snapshot({**track, "provider": track.get("provider") or source.casefold()}, saved_at=timestamp))
        except ValueError:
            continue
    playlist = {
        **existing,
        "name": playlist_name,
        "source_app": source,
        "external_id": _text(external_id) or None,
        "readonly": True,
        "protected": False,
        "tracks": snapshots,
        "revision": int(existing.get("revision") or 0) + 1,
        "created_at": existing.get("created_at") or timestamp,
        "updated_at": timestamp,
    }
    _save_playlist(playlist, playlists_root)
    return {
        "name": playlist_name,
        "label": _playlist_label(playlist),
        "source_app": source,
        "external_id": playlist.get("external_id"),
        "readonly": True,
        "track_count": len(snapshots),
        "updated_at": timestamp,
    }


def track_in_playlist(
    track: dict[str, Any],
    *,
    playlist_name: str = LIKES_PLAYLIST,
    playlists_root: Path | None = None,
) -> bool:
    name = _playlist_name(playlist_name)
    try:
        key = _track_key(_track_snapshot(track, saved_at=0))
    except ValueError:
        return False
    playlist = _load_playlist(name, playlists_root)
    return any(item.get("key") == key for item in playlist.get("tracks") or [])


def track_in_any_playlist(
    track: dict[str, Any],
    *,
    playlists_root: Path | None = None,
    writable_only: bool = True,
) -> bool:
    try:
        key = _track_key(_track_snapshot(track, saved_at=0))
    except ValueError:
        return False
    for playlist_meta in list_playlists(playlists_root=playlists_root):
        if writable_only and playlist_meta.get("readonly"):
            continue
        playlist = _load_playlist(
            str(playlist_meta.get("name") or LIKES_PLAYLIST),
            playlists_root,
            source_app=str(playlist_meta.get("source_app") or SOURCE_SONEX),
            external_id=_text(playlist_meta.get("external_id")) or None,
        )
        if any(item.get("key") == key for item in playlist.get("tracks") or []):
            return True
    return False


def list_playlist_tracks(
    playlist_name: str = LIKES_PLAYLIST,
    *,
    playlists_root: Path | None = None,
    source_app: str = SOURCE_SONEX,
    external_id: str | None = None,
) -> list[dict[str, Any]]:
    playlist = _load_playlist(_playlist_name(playlist_name), playlists_root, source_app=source_app, external_id=external_id)
    return list(playlist.get("tracks") or [])


def playlist_snapshot(
    playlist_name: str,
    *,
    playlists_root: Path | None = None,
) -> dict[str, Any]:
    """Return one detached local playlist state including its revision."""
    playlist = _load_playlist(_playlist_name(playlist_name), playlists_root)
    return {
        **playlist,
        "tracks": [dict(track) for track in playlist.get("tracks") or []],
    }


def playlist_storage_path(
    playlist_name: str,
    *,
    playlists_root: Path | None = None,
) -> Path:
    """Return the canonical local storage path for transaction coordination."""
    return _playlist_path(_playlist_name(playlist_name), playlists_root)


def commit_playlist_state(
    playlist: dict[str, Any],
    *,
    expected_revision: int,
    playlists_root: Path | None = None,
) -> dict[str, Any]:
    """Atomically save one local playlist when its revision still matches."""
    name = _playlist_name(str(playlist.get("name") or LIKES_PLAYLIST))
    current = _load_playlist(name, playlists_root)
    if current.get("readonly"):
        raise ValueError(f"Playlist {name} is read-only.")
    current_revision = int(current.get("revision") or 0)
    if current_revision != int(expected_revision):
        raise PlaylistVersionConflict(
            f"Expected playlist revision {expected_revision}, found {current_revision}."
        )
    committed = {
        **playlist,
        "name": name,
        "source_app": SOURCE_SONEX,
        "external_id": None,
        "readonly": False,
        "protected": name == LIKES_PLAYLIST,
        "revision": current_revision + 1,
    }
    _save_playlist(committed, playlists_root)
    return playlist_snapshot(name, playlists_root=playlists_root)


def delete_playlist_state(
    playlist_name: str,
    *,
    expected_revision: int,
    playlists_root: Path | None = None,
) -> None:
    """Delete one unprotected local playlist after a revision check."""
    name = _playlist_name(playlist_name)
    if name == LIKES_PLAYLIST:
        raise ValueError("The likes playlist cannot be deleted.")
    current = _load_playlist(name, playlists_root)
    current_revision = int(current.get("revision") or 0)
    if current_revision != int(expected_revision):
        raise PlaylistVersionConflict(
            f"Expected playlist revision {expected_revision}, found {current_revision}."
        )
    path = _playlist_path(name, playlists_root)
    try:
        path.unlink()
    except FileNotFoundError:
        return
