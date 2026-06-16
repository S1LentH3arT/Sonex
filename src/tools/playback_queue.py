"""Persistent playback queue for Sonex actual playback flows."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from src.log import sonex_home
from src.tools.apple_music import recent_tracks_snapshot as apple_recent_tracks_snapshot
from src.tools.song_cache import recent_cached_songs
from src.tools.spotify_play import recent_tracks_snapshot as spotify_recent_tracks_snapshot

MAX_PLAYBACK_QUEUE = 10


def _default_queue_path() -> Path:
    return sonex_home() / "cache" / "playback_queue.json"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _queue_path(queue_path: Path | None = None) -> Path:
    path = queue_path or _default_queue_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return path


def _seed_sources() -> tuple[Callable[[], list[dict[str, Any]]], ...]:
    return (
        recent_cached_songs,
        spotify_recent_tracks_snapshot,
        apple_recent_tracks_snapshot,
    )


def _track_key(track: dict[str, Any]) -> str:
    for key in (
        "cache_id",
        "uri",
        "spotify_url",
        "apple_music_url",
        "youtube_url",
        "url",
        "stream_url",
        "audio_path",
        "file_path",
        "path",
        "id",
    ):
        value = _text(track.get(key))
        if value:
            return f"{key}:{value}"
    name = _text(track.get("name") or track.get("title"))
    artist = _text(track.get("artist"))
    album = _text(track.get("album"))
    duration = int(track.get("duration_ms") or 0)
    if not name:
        return ""
    if artist or album or duration or _text(track.get("provider") or track.get("source")) == "local":
        return f"text:{name.casefold()}|{artist.casefold()}|{album.casefold()}|{duration}"
    return ""


def _played_at(value: Any, fallback: float) -> float:
    if value is None or value == "":
        return fallback
    try:
        return float(value)
    except (TypeError, ValueError):
        pass
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return fallback
    return fallback


def _snapshot_track(track: dict[str, Any], *, played_at: float) -> dict[str, Any] | None:
    name = _text(track.get("name") or track.get("title"))
    key = _track_key(track)
    if not name or not key:
        return None
    snapshot: dict[str, Any] = {
        "key": key,
        "name": name,
        "title": name,
        "artist": _text(track.get("artist")) or "-",
        "album": _text(track.get("album")) or "-",
        "duration_ms": int(track.get("duration_ms") or 0),
        "provider": _text(track.get("provider") or track.get("source")) or "unknown",
        "source": _text(track.get("source")) or None,
        "played_at": played_at,
    }
    for field in (
        "cache_id",
        "uri",
        "url",
        "stream_url",
        "youtube_url",
        "spotify_url",
        "apple_music_url",
        "audio_path",
        "file_path",
        "path",
        "album_cover_url",
        "id",
    ):
        value = track.get(field)
        if value:
            snapshot[field] = value
    return snapshot


def _load_queue(path: Path) -> list[dict[str, Any]] | None:
    if not path.exists():
        return None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    tracks = loaded.get("tracks") if isinstance(loaded, dict) else loaded
    if not isinstance(tracks, list):
        return []

    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in tracks:
        if not isinstance(item, dict):
            continue
        snapshot = _snapshot_track(item, played_at=float(item.get("played_at") or 0))
        if snapshot is None or snapshot["key"] in seen:
            continue
        seen.add(snapshot["key"])
        deduped.append(snapshot)
        if len(deduped) >= MAX_PLAYBACK_QUEUE:
            break
    return deduped


def _seed_queue() -> list[dict[str, Any]]:
    for source in _seed_sources():
        try:
            tracks = source()
        except Exception:
            tracks = []
        seeded: list[dict[str, Any]] = []
        seen: set[str] = set()
        for index, track in enumerate(tracks[:MAX_PLAYBACK_QUEUE]):
            if not isinstance(track, dict):
                continue
            snapshot = _snapshot_track(
                track,
                played_at=_played_at(track.get("played_at") or track.get("last_played_at"), float(MAX_PLAYBACK_QUEUE - index)),
            )
            if snapshot is None or snapshot["key"] in seen:
                continue
            seen.add(snapshot["key"])
            seeded.append(snapshot)
        if seeded:
            return seeded
    return []


def _save_queue(path: Path, tracks: list[dict[str, Any]]) -> None:
    payload = {"version": 1, "tracks": tracks[:MAX_PLAYBACK_QUEUE]}
    try:
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)
    except OSError:
        return


def playback_queue_snapshot(*, queue_path: Path | None = None) -> list[dict[str, Any]]:
    path = _queue_path(queue_path)
    tracks = _load_queue(path)
    if tracks is None:
        tracks = _seed_queue()
        _save_queue(path, tracks)
    return [dict(item) for item in tracks[:MAX_PLAYBACK_QUEUE]]


def remember_playback_track(
    track: dict[str, Any],
    *,
    queue_path: Path | None = None,
    now: float | None = None,
) -> list[dict[str, Any]]:
    path = _queue_path(queue_path)
    queue = playback_queue_snapshot(queue_path=path)
    played_at = time.time() if now is None else float(now)
    snapshot = _snapshot_track(track, played_at=played_at)
    if snapshot is None:
        return queue
    queue = [item for item in queue if item.get("key") != snapshot["key"]]
    queue.insert(0, snapshot)
    queue = queue[:MAX_PLAYBACK_QUEUE]
    _save_queue(path, queue)
    return [dict(item) for item in queue]
