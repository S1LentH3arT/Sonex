"""Song cache support for tool implementations used by the planner and playback flows.

Implements the song_cache module responsibilities used by Sonex runtime flows.
Key public entry points include upsert_cached_song, find_best_cached_song, resolve_cached_song, recent_cached_songs.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Any

from src.log import sonex_home
from src.tools.song_cache_state import (
    artists_text as _artists_text,
    cache_id_for as _cache_id_for,
    merge_provider_details as _merge_provider_details,
    provider_summary as _provider_summary,
    text as _text,
)

MAX_CACHED_SONGS = 100
SESSION_QUEUE_LIMIT = 10


def _default_cache_root() -> Path:
    """Prepares default cache root for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs default cache root without duplicating the local rules.

    Example: _default_cache_root() -> returns the value used by the surrounding Sonex flow.
    """
    return sonex_home() / "cache" / "songs"


def _cache_paths(cache_root: Path | None = None) -> tuple[Path, Path, Path]:
    """Prepares cache paths for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs cache paths without duplicating the local rules.

    Example: _cache_paths(cache_root=...) -> returns the value used by the surrounding Sonex flow.
    """
    root = cache_root or _default_cache_root()
    return root, root / "cache.db", root / "items"


def _connect(cache_root: Path | None = None) -> sqlite3.Connection:
    """Prepares connect for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs connect without duplicating the local rules.

    Example: _connect(cache_root=...) -> returns the value used by the surrounding Sonex flow.
    """
    root, db_path, items_dir = _cache_paths(cache_root)
    root.mkdir(parents=True, exist_ok=True)
    items_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS songs (
            cache_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            artist TEXT NOT NULL,
            album TEXT,
            provider_summary TEXT NOT NULL,
            updated_at REAL NOT NULL,
            last_played_at REAL NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_songs_last_played ON songs(last_played_at DESC)")
    conn.commit()
    return conn


def _compact(row: sqlite3.Row) -> dict[str, Any]:
    """Prepares compact for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs compact without duplicating the local rules.

    Example: _compact(row=...) -> returns the value used by the surrounding Sonex flow.
    """
    providers = json.loads(row["provider_summary"] or "[]")
    return {
        "cache_id": row["cache_id"],
        "name": row["name"],
        "artist": row["artist"],
        "album": row["album"],
        "providers": providers,
        "updated_at": row["updated_at"],
        "last_played_at": row["last_played_at"],
    }


def _delete_cached_audio(item: dict[str, Any], root: Path) -> None:
    """Prepares delete cached audio for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs delete cached audio without duplicating the local rules.

    Example: _delete_cached_audio(item=..., root=...) -> returns the value used by the surrounding Sonex flow.
    """
    audio_path = _text(item.get("audio_path"))
    if not audio_path:
        return
    try:
        path = Path(audio_path).expanduser().resolve()
        audio_dir = (root / "audio").resolve()
        path.relative_to(audio_dir)
    except (OSError, ValueError):
        return
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def _prune(conn: sqlite3.Connection, root: Path, items_dir: Path) -> None:
    """Prepares prune for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs prune without duplicating the local rules.

    Example: _prune(conn=..., root=..., items_dir=...) -> returns the value used by the surrounding Sonex flow.
    """
    rows = conn.execute(
        "SELECT cache_id FROM songs ORDER BY last_played_at DESC, updated_at DESC LIMIT -1 OFFSET ?",
        (MAX_CACHED_SONGS,),
    ).fetchall()
    stale_ids = [str(row["cache_id"]) for row in rows]
    if not stale_ids:
        return
    conn.executemany("DELETE FROM songs WHERE cache_id = ?", [(cache_id,) for cache_id in stale_ids])
    for cache_id in stale_ids:
        item_path = items_dir / f"{cache_id}.json"
        try:
            item = json.loads(item_path.read_text(encoding="utf-8"))
            if isinstance(item, dict):
                _delete_cached_audio(item, root)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            pass
        try:
            item_path.unlink()
        except FileNotFoundError:
            pass


def upsert_cached_song(
    item: dict[str, Any],
    *,
    cache_root: Path | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    """Coordinates upsert cached song for the current Sonex flow.

    Typical use: Use this function when runtime code needs upsert cached song as part of a Sonex command, playback, auth, llm, or ui path.

    Example: upsert_cached_song(item=..., cache_root=..., now=...) -> returns the value used by the surrounding Sonex flow.
    """
    timestamp = time.time() if now is None else float(now)
    name = _text(item.get("name") or item.get("title") or item.get("query"))
    artist = _artists_text(item) or "-"
    if not name:
        raise ValueError("Cached song requires a name.")
    cache_id = _text(item.get("cache_id")) or _cache_id_for(name, artist)
    album = _text(item.get("album")) or "-"
    root, _, items_dir = _cache_paths(cache_root)
    conn = _connect(root)
    item_path = items_dir / f"{cache_id}.json"
    existing: dict[str, Any] = {}
    if item_path.exists():
        existing = json.loads(item_path.read_text(encoding="utf-8"))
    full_item = _merge_provider_details(existing, {**item, "cache_id": cache_id, "name": name, "artist": artist, "album": album})
    item_path.write_text(json.dumps(full_item, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    conn.execute(
        """
        INSERT INTO songs(cache_id, name, artist, album, provider_summary, updated_at, last_played_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(cache_id) DO UPDATE SET
            name = excluded.name,
            artist = excluded.artist,
            album = excluded.album,
            provider_summary = excluded.provider_summary,
            updated_at = excluded.updated_at,
            last_played_at = excluded.last_played_at
        """,
        (cache_id, name, artist, album, json.dumps(_provider_summary(full_item), ensure_ascii=False), timestamp, timestamp),
    )
    _prune(conn, root, items_dir)
    conn.commit()
    compact = conn.execute("SELECT * FROM songs WHERE cache_id = ?", (cache_id,)).fetchone()
    conn.close()
    return _compact(compact)


def find_best_cached_song(query: str, *, cache_root: Path | None = None) -> dict[str, Any] | None:
    """Coordinates find best cached song for the current Sonex flow.

    Typical use: Use this function when runtime code needs find best cached song as part of a Sonex command, playback, auth, llm, or ui path.

    Example: find_best_cached_song(query=..., cache_root=...) -> returns the value used by the surrounding Sonex flow.
    """
    needle = _text(query).casefold()
    if not needle:
        return None
    conn = _connect(cache_root)
    rows = conn.execute("SELECT * FROM songs ORDER BY last_played_at DESC, updated_at DESC").fetchall()
    conn.close()
    needle_tokens = re.findall(r"\w+", needle)
    for row in rows:
        haystack = f"{row['name']} {row['artist']} {row['album'] or ''}".casefold()
        haystack_tokens = set(re.findall(r"\w+", haystack))
        if needle == haystack or (needle_tokens and all(part in haystack_tokens for part in needle_tokens)):
            return _compact(row)
    return None


def resolve_cached_song(cache_id: str, *, cache_root: Path | None = None) -> dict[str, Any]:
    """Resolves cached song from available runtime state.

    Typical use: Use this function when runtime code needs resolve cached song as part of a Sonex command, playback, auth, llm, or ui path.

    Example: resolve_cached_song(cache_id=..., cache_root=...) -> returns the value used by the surrounding Sonex flow.
    """
    _, _, items_dir = _cache_paths(cache_root)
    path = items_dir / f"{cache_id}.json"
    if not path.exists():
        raise KeyError(cache_id)
    return json.loads(path.read_text(encoding="utf-8"))


def recent_cached_songs(*, limit: int = SESSION_QUEUE_LIMIT, cache_root: Path | None = None) -> list[dict[str, Any]]:
    """Coordinates recent cached songs for the current Sonex flow.

    Typical use: Use this function when runtime code needs recent cached songs as part of a Sonex command, playback, auth, llm, or ui path.

    Example: recent_cached_songs(limit=..., cache_root=...) -> returns the value used by the surrounding Sonex flow.
    """
    bounded_limit = min(SESSION_QUEUE_LIMIT, max(1, int(limit or SESSION_QUEUE_LIMIT)))
    conn = _connect(cache_root)
    rows = conn.execute(
        "SELECT * FROM songs ORDER BY last_played_at DESC, updated_at DESC LIMIT ?",
        (bounded_limit,),
    ).fetchall()
    conn.close()
    return [_compact(row) for row in rows]
