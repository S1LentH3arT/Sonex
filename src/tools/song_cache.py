"""Song cache support for tool implementations used by the planner and playback flows.

Implements the song_cache module responsibilities used by Sonex runtime flows.
Key public entry points include upsert_cached_song, find_best_cached_song, resolve_cached_song, recent_cached_songs.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Any

from src.log import sonex_home

MAX_CACHED_SONGS = 100
SESSION_QUEUE_LIMIT = 10


def _default_cache_root() -> Path:
    """Default cache root.

    Coordinates default cache root logic for the surrounding Sonex flow.

    Returns:
        The computed result for default cache root.
    """
    return sonex_home() / "cache" / "songs"


def _cache_paths(cache_root: Path | None = None) -> tuple[Path, Path, Path]:
    """Cache paths.

    Coordinates cache paths logic for the surrounding Sonex flow.

    Args:
        cache_root: Input value used by the cache paths operation.

    Returns:
        The computed result for cache paths.
    """
    root = cache_root or _default_cache_root()
    return root, root / "cache.db", root / "items"


def _connect(cache_root: Path | None = None) -> sqlite3.Connection:
    """Connect.

    Coordinates connect logic for the surrounding Sonex flow.

    Args:
        cache_root: Input value used by the connect operation.

    Returns:
        The computed result for connect.
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


def _text(value: Any) -> str:
    """Text.

    Coordinates text logic for the surrounding Sonex flow.

    Args:
        value: Input value used by the text operation.

    Returns:
        The computed result for text.
    """
    return str(value or "").strip()


def _artists_text(item: dict[str, Any]) -> str:
    """Artists text.

    Coordinates artists text logic for the surrounding Sonex flow.

    Args:
        item: Input value used by the artists text operation.

    Returns:
        The computed result for artists text.
    """
    artist = _text(item.get("artist"))
    if artist:
        return artist
    artists = item.get("artists")
    if isinstance(artists, list):
        return ", ".join(_text(value) for value in artists if _text(value))
    return ""


def _cache_id_for(name: str, artist: str) -> str:
    """Cache id for.

    Coordinates cache id for logic for the surrounding Sonex flow.

    Args:
        name: Input value used by the cache id for operation.
        artist: Input value used by the cache id for operation.

    Returns:
        The computed result for cache id for.
    """
    digest = hashlib.sha1(f"{name.casefold()}|{artist.casefold()}".encode("utf-8")).hexdigest()
    return digest[:16]


def _compact(row: sqlite3.Row) -> dict[str, Any]:
    """Compact.

    Coordinates compact logic for the surrounding Sonex flow.

    Args:
        row: Input value used by the compact operation.

    Returns:
        The computed result for compact.
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


def _provider_summary(item: dict[str, Any]) -> list[dict[str, Any]]:
    """Provider summary.

    Coordinates provider summary logic for the surrounding Sonex flow.

    Args:
        item: Input value used by the provider summary operation.

    Returns:
        The computed result for provider summary.
    """
    provider = _text(item.get("provider") or item.get("source"))
    summary: dict[str, Any] = {"provider": provider or "unknown"}
    for key in ("uri", "url", "stream_url", "cover_url", "album_cover_url"):
        if item.get(key):
            summary[f"has_{key}"] = True
    return [summary]


def _merge_provider_details(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    """Merge provider details.

    Coordinates merge provider details logic for the surrounding Sonex flow.

    Args:
        existing: Input value used by the merge provider details operation.
        incoming: Input value used by the merge provider details operation.

    Returns:
        The computed result for merge provider details.
    """
    merged = dict(existing)
    provider = _text(incoming.get("provider") or incoming.get("source") or "unknown")
    providers = dict(merged.get("providers") or {})
    provider_payload = dict(incoming)
    providers[provider] = provider_payload
    merged.update(incoming)
    merged["providers"] = providers
    return merged


def _delete_cached_audio(item: dict[str, Any], root: Path) -> None:
    """Delete cached audio.

    Coordinates delete cached audio logic for the surrounding Sonex flow.

    Args:
        item: Input value used by the delete cached audio operation.
        root: Input value used by the delete cached audio operation.

    Returns:
        The computed result for delete cached audio.
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
    """Prune.

    Coordinates prune logic for the surrounding Sonex flow.

    Args:
        conn: Input value used by the prune operation.
        root: Input value used by the prune operation.
        items_dir: Input value used by the prune operation.

    Returns:
        The computed result for prune.
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
    """Upsert cached song.

    Coordinates upsert cached song logic for the surrounding Sonex flow.

    Args:
        item: Input value used by the upsert cached song operation.
        cache_root: Input value used by the upsert cached song operation.
        now: Input value used by the upsert cached song operation.

    Returns:
        The computed result for upsert cached song.
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
    """Find best cached song.

    Coordinates find best cached song logic for the surrounding Sonex flow.

    Args:
        query: Input value used by the find best cached song operation.
        cache_root: Input value used by the find best cached song operation.

    Returns:
        The computed result for find best cached song.
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
    """Resolve cached song.

    Coordinates resolve cached song logic for the surrounding Sonex flow.

    Args:
        cache_id: Input value used by the resolve cached song operation.
        cache_root: Input value used by the resolve cached song operation.

    Returns:
        The computed result for resolve cached song.
    """
    _, _, items_dir = _cache_paths(cache_root)
    path = items_dir / f"{cache_id}.json"
    if not path.exists():
        raise KeyError(cache_id)
    return json.loads(path.read_text(encoding="utf-8"))


def recent_cached_songs(*, limit: int = SESSION_QUEUE_LIMIT, cache_root: Path | None = None) -> list[dict[str, Any]]:
    """Recent cached songs.

    Coordinates recent cached songs logic for the surrounding Sonex flow.

    Args:
        limit: Input value used by the recent cached songs operation.
        cache_root: Input value used by the recent cached songs operation.

    Returns:
        The computed result for recent cached songs.
    """
    bounded_limit = min(SESSION_QUEUE_LIMIT, max(1, int(limit or SESSION_QUEUE_LIMIT)))
    conn = _connect(cache_root)
    rows = conn.execute(
        "SELECT * FROM songs ORDER BY last_played_at DESC, updated_at DESC LIMIT ?",
        (bounded_limit,),
    ).fetchall()
    conn.close()
    return [_compact(row) for row in rows]
