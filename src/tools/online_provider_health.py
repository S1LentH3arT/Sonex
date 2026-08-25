"""Persistent provider health and cooldown state for online audio."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any

from src.log import sonex_home

COOLDOWN_RESET_WINDOW_SECONDS = 24 * 60 * 60
RATE_LIMIT_COOLDOWNS = (5 * 60, 30 * 60, 2 * 60 * 60)
BOT_CHALLENGE_COOLDOWNS = (2 * 60 * 60, 24 * 60 * 60)
COOLDOWN_FAILURE_CLASSES = {"rate_limited", "bot_challenge"}


def _root(cache_root: Path | None = None) -> Path:
    return cache_root or sonex_home() / "cache" / "songs"


def _connect(cache_root: Path | None = None) -> sqlite3.Connection:
    root = _root(cache_root)
    root.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(root / "cache.db")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS provider_health (
            provider TEXT PRIMARY KEY,
            failure_class TEXT NOT NULL,
            level INTEGER NOT NULL,
            next_probe_at REAL NOT NULL,
            last_failure_at REAL NOT NULL
        )
        """
    )
    conn.commit()
    return conn


def _schedule(failure_class: str) -> tuple[int, ...]:
    if failure_class == "bot_challenge":
        return BOT_CHALLENGE_COOLDOWNS
    return RATE_LIMIT_COOLDOWNS


def provider_cooldown(
    provider: str,
    *,
    cache_root: Path | None = None,
    now: float | None = None,
) -> dict[str, Any] | None:
    timestamp = time.time() if now is None else float(now)
    conn = _connect(cache_root)
    row = conn.execute(
        "SELECT * FROM provider_health WHERE provider = ?", (provider,)
    ).fetchone()
    if row is None:
        conn.close()
        return None
    if timestamp - float(row["last_failure_at"]) >= COOLDOWN_RESET_WINDOW_SECONDS:
        conn.execute("DELETE FROM provider_health WHERE provider = ?", (provider,))
        conn.commit()
        conn.close()
        return None
    result = {
        "provider": str(row["provider"]),
        "failure_class": str(row["failure_class"]),
        "level": int(row["level"]),
        "next_probe_at": float(row["next_probe_at"]),
        "remaining_seconds": max(0.0, float(row["next_probe_at"]) - timestamp),
    }
    conn.close()
    return result


def activate_provider_cooldown(
    provider: str,
    failure_class: str,
    *,
    retry_after: float | None = None,
    cache_root: Path | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    if failure_class not in COOLDOWN_FAILURE_CLASSES:
        raise ValueError(f"Unsupported cooldown failure class: {failure_class}")
    timestamp = time.time() if now is None else float(now)
    conn = _connect(cache_root)
    existing = conn.execute(
        "SELECT * FROM provider_health WHERE provider = ?", (provider,)
    ).fetchone()
    same_recent_class = bool(
        existing
        and str(existing["failure_class"]) == failure_class
        and timestamp - float(existing["last_failure_at"]) < COOLDOWN_RESET_WINDOW_SECONDS
    )
    level = int(existing["level"]) + 1 if same_recent_class else 0
    schedule = _schedule(failure_class)
    base_seconds = schedule[min(level, len(schedule) - 1)]
    requested_seconds = max(0.0, float(retry_after or 0.0))
    cooldown_seconds = max(float(base_seconds), requested_seconds)
    conn.execute(
        """
        INSERT INTO provider_health(provider, failure_class, level, next_probe_at, last_failure_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(provider) DO UPDATE SET
            failure_class = excluded.failure_class,
            level = excluded.level,
            next_probe_at = excluded.next_probe_at,
            last_failure_at = excluded.last_failure_at
        """,
        (provider, failure_class, level, timestamp + cooldown_seconds, timestamp),
    )
    conn.commit()
    conn.close()
    return {
        "provider": provider,
        "failure_class": failure_class,
        "level": level,
        "cooldown_seconds": cooldown_seconds,
        "next_probe_at": timestamp + cooldown_seconds,
    }


def clear_provider_cooldown(provider: str, *, cache_root: Path | None = None) -> None:
    conn = _connect(cache_root)
    conn.execute("DELETE FROM provider_health WHERE provider = ?", (provider,))
    conn.commit()
    conn.close()
