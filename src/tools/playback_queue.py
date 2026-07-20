"""Persistent playback queue for Sonex actual playback flows."""

from __future__ import annotations

import json
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from src.log import sonex_home
from src.tools.apple_music import recent_tracks_snapshot as apple_recent_tracks_snapshot
from src.tools.song_cache import recent_cached_songs
from src.tools.spotify_play import recent_tracks_snapshot as spotify_recent_tracks_snapshot

MAX_PLAYBACK_QUEUE = 10
_PLAYABLE_LOCATOR_FIELDS = (
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
)
_PLACEHOLDER_VALUES = {"", "-", "unknown", "none", "null"}


def _default_queue_path() -> Path:
    return sonex_home() / "cache" / "playback_queue.json"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _played_at_value(value: Any, fallback: float) -> float:
    if isinstance(value, int | float):
        return float(value)
    text = _text(value)
    if not text:
        return fallback
    try:
        return float(text)
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return fallback


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


def _meaningful_text(value: Any) -> bool:
    return _text(value).casefold() not in _PLACEHOLDER_VALUES


def is_persistable_playback_track(track: dict[str, Any]) -> bool:
    """Returns whether a playback payload has enough identity to represent a track."""
    if not _meaningful_text(track.get("name") or track.get("title")):
        return False
    if any(_text(track.get(field)) for field in _PLAYABLE_LOCATOR_FIELDS):
        return True
    if _text(track.get("provider") or track.get("source")).casefold() == "local":
        return True
    return bool(
        _meaningful_text(track.get("artist"))
        or _meaningful_text(track.get("album"))
        or int(track.get("duration_ms") or 0) > 0
    )


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
        snapshot = _snapshot_track(item, played_at=_played_at_value(item.get("played_at"), 0))
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
            if not is_persistable_playback_track(track):
                continue
            snapshot = _snapshot_track(
                track,
                played_at=_played_at_value(
                    track.get("played_at") or track.get("last_played_at"),
                    float(MAX_PLAYBACK_QUEUE - index),
                ),
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
    queue = _load_queue(path) or []
    if not is_persistable_playback_track(track):
        return [dict(item) for item in queue]
    played_at = time.time() if now is None else float(now)
    snapshot = _snapshot_track(track, played_at=played_at)
    if snapshot is None:
        return queue
    queue = [item for item in queue if item.get("key") != snapshot["key"]]
    queue.insert(0, snapshot)
    queue = queue[:MAX_PLAYBACK_QUEUE]
    _save_queue(path, queue)
    return [dict(item) for item in queue]


def remove_playback_device_artifact(
    device_id: str,
    *,
    queue_path: Path | None = None,
) -> int:
    """Removes a legacy device-shaped queue item while preserving a backup."""
    normalized_device_id = _text(device_id)
    if not normalized_device_id:
        return 0
    path = _queue_path(queue_path)
    queue = _load_queue(path)
    if queue is None:
        return 0

    retained = [
        item
        for item in queue
        if not (
            _text(item.get("id")) == normalized_device_id
            and not is_persistable_playback_track(item)
        )
    ]
    removed = len(queue) - len(retained)
    if not removed:
        return 0

    backup_path = path.with_suffix(f"{path.suffix}.bak")
    try:
        if not backup_path.exists():
            shutil.copy2(path, backup_path)
    except OSError:
        return 0
    _save_queue(path, retained)
    return removed
