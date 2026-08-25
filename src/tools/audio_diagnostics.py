"""Local-only structured diagnostics for online audio."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from src.log import sonex_home

RETENTION_SECONDS = 7 * 24 * 60 * 60
MAX_EVENTS = 2000
_ALLOWED_METADATA = {
    "cache_hit",
    "candidate_count",
    "confidence_counts",
    "failure_class",
    "fallback_provider",
    "provider_elapsed_ms",
    "stable_30s",
    "started",
    "yt_dlp_version",
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
        CREATE TABLE IF NOT EXISTS audio_events (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            trace_id TEXT NOT NULL,
            provider TEXT NOT NULL,
            phase TEXT NOT NULL,
            status TEXT NOT NULL,
            elapsed_ms INTEGER,
            metadata TEXT NOT NULL,
            created_at REAL NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_audio_events_created ON audio_events(created_at DESC)")
    return conn


def record_audio_event(
    *,
    trace_id: str,
    provider: str,
    phase: str,
    status: str,
    elapsed_ms: int | None = None,
    cache_root: Path | None = None,
    **metadata: Any,
) -> None:
    safe_metadata = {
        key: value
        for key, value in metadata.items()
        if key in _ALLOWED_METADATA
    }
    now = time.time()
    conn = _connect(cache_root)
    conn.execute(
        """
        INSERT INTO audio_events(trace_id, provider, phase, status, elapsed_ms, metadata, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            trace_id,
            provider,
            phase,
            status,
            elapsed_ms,
            json.dumps(safe_metadata, ensure_ascii=False, default=str),
            now,
        ),
    )
    conn.execute("DELETE FROM audio_events WHERE created_at < ?", (now - RETENTION_SECONDS,))
    conn.execute(
        """
        DELETE FROM audio_events
        WHERE event_id IN (
            SELECT event_id FROM audio_events ORDER BY created_at DESC LIMIT -1 OFFSET ?
        )
        """,
        (MAX_EVENTS,),
    )
    conn.commit()
    conn.close()


def audio_diagnostics_summary(
    *,
    cache_root: Path | None = None,
    now: float | None = None,
) -> list[dict[str, Any]]:
    timestamp = time.time() if now is None else float(now)
    conn = _connect(cache_root)
    rows = conn.execute(
        """
        SELECT phase, status, COUNT(*) AS count
        FROM audio_events
        WHERE created_at >= ?
        GROUP BY phase, status
        ORDER BY phase, status
        """,
        (timestamp - 24 * 60 * 60,),
    ).fetchall()
    conn.close()
    return [
        {"phase": str(row["phase"]), "status": str(row["status"]), "count": int(row["count"])}
        for row in rows
    ]
