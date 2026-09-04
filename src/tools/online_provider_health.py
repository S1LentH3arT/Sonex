"""Persistent provider health and cooldown state for online audio."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any

from src.log import sonex_home
from src.tools.online_provider_health_state import (
    BOT_CHALLENGE_COOLDOWNS,
    COOLDOWN_FAILURE_CLASSES,
    COOLDOWN_RESET_WINDOW_SECONDS,
    RATE_LIMIT_COOLDOWNS,
    calculate_cooldown,
)


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
    state = calculate_cooldown(
        provider,
        failure_class,
        existing=dict(existing) if existing is not None else None,
        retry_after=retry_after,
        now=timestamp,
    )
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
        (provider, failure_class, state["level"], state["next_probe_at"], timestamp),
    )
    conn.commit()
    conn.close()
    return {
        "provider": provider,
        "failure_class": failure_class,
        "level": state["level"],
        "cooldown_seconds": state["cooldown_seconds"],
        "next_probe_at": state["next_probe_at"],
    }


def clear_provider_cooldown(provider: str, *, cache_root: Path | None = None) -> None:
    conn = _connect(cache_root)
    conn.execute("DELETE FROM provider_health WHERE provider = ?", (provider,))
    conn.commit()
    conn.close()
