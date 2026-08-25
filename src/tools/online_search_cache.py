"""Persistent candidate-search cache for online audio providers."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import unicodedata
from pathlib import Path
from typing import Any

from src.log import sonex_home

POSITIVE_TTL_SECONDS = 24 * 60 * 60
EMPTY_TTL_SECONDS = 10 * 60
MAX_SEARCH_CACHE_ENTRIES = 500
_REMOVED_KEYS = {
    "audio_path",
    "formats",
    "playback_source_url",
    "requested_downloads",
    "stream_url",
}


def _root(cache_root: Path | None = None) -> Path:
    return cache_root or sonex_home() / "cache" / "songs"


def _connect(cache_root: Path | None = None) -> sqlite3.Connection:
    root = _root(cache_root)
    root.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(root / "cache.db")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS search_cache (
            cache_key TEXT PRIMARY KEY,
            provider TEXT NOT NULL,
            payload TEXT NOT NULL,
            expires_at REAL NOT NULL,
            last_access_at REAL NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_search_cache_lru "
        "ON search_cache(last_access_at DESC)"
    )
    conn.commit()
    return conn


def _normalized(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return " ".join(text.split())


def make_search_cache_key(
    *,
    provider: str,
    artist: Any,
    title: Any,
    album: Any = "",
    variant_intent: Any = "default",
) -> str:
    identity = "\0".join(
        (
            _normalized(provider),
            _normalized(artist),
            _normalized(title),
            _normalized(album),
            _normalized(variant_intent),
        )
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _metadata_only(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _metadata_only(item)
            for key, item in value.items()
            if str(key) not in _REMOVED_KEYS
        }
    if isinstance(value, list):
        return [_metadata_only(item) for item in value]
    return value


def get_search_cache(
    cache_key: str,
    *,
    provider: str,
    cache_root: Path | None = None,
    now: float | None = None,
) -> list[dict[str, Any]] | None:
    timestamp = time.time() if now is None else float(now)
    conn = _connect(cache_root)
    row = conn.execute(
        "SELECT payload, expires_at FROM search_cache WHERE cache_key = ? AND provider = ?",
        (cache_key, provider),
    ).fetchone()
    if row is None:
        conn.close()
        return None
    if float(row["expires_at"]) <= timestamp:
        conn.execute("DELETE FROM search_cache WHERE cache_key = ?", (cache_key,))
        conn.commit()
        conn.close()
        return None
    try:
        payload = json.loads(str(row["payload"]))
    except json.JSONDecodeError:
        conn.execute("DELETE FROM search_cache WHERE cache_key = ?", (cache_key,))
        conn.commit()
        conn.close()
        return None
    conn.execute(
        "UPDATE search_cache SET last_access_at = ? WHERE cache_key = ?",
        (timestamp, cache_key),
    )
    conn.commit()
    conn.close()
    return payload if isinstance(payload, list) else None


def put_search_cache(
    cache_key: str,
    candidates: list[dict[str, Any]],
    *,
    provider: str,
    cache_root: Path | None = None,
    now: float | None = None,
) -> None:
    timestamp = time.time() if now is None else float(now)
    ttl = POSITIVE_TTL_SECONDS if candidates else EMPTY_TTL_SECONDS
    payload = _metadata_only(candidates)
    conn = _connect(cache_root)
    conn.execute(
        """
        INSERT INTO search_cache(cache_key, provider, payload, expires_at, last_access_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(cache_key) DO UPDATE SET
            provider = excluded.provider,
            payload = excluded.payload,
            expires_at = excluded.expires_at,
            last_access_at = excluded.last_access_at
        """,
        (
            cache_key,
            provider,
            json.dumps(payload, ensure_ascii=False, default=str),
            timestamp + ttl,
            timestamp,
        ),
    )
    conn.execute(
        """
        DELETE FROM search_cache
        WHERE cache_key IN (
            SELECT cache_key FROM search_cache
            ORDER BY last_access_at DESC
            LIMIT -1 OFFSET ?
        )
        """,
        (MAX_SEARCH_CACHE_ENTRIES,),
    )
    conn.commit()
    conn.close()
