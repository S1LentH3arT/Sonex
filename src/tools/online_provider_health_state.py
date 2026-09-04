"""Pure cooldown policy for online provider health."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


COOLDOWN_RESET_WINDOW_SECONDS = 24 * 60 * 60
RATE_LIMIT_COOLDOWNS = (5 * 60, 30 * 60, 2 * 60 * 60)
BOT_CHALLENGE_COOLDOWNS = (2 * 60 * 60, 24 * 60 * 60)
COOLDOWN_FAILURE_CLASSES = {"rate_limited", "bot_challenge"}


def cooldown_schedule(failure_class: str) -> tuple[int, ...]:
    if failure_class == "bot_challenge":
        return BOT_CHALLENGE_COOLDOWNS
    if failure_class == "rate_limited":
        return RATE_LIMIT_COOLDOWNS
    raise ValueError(f"Unsupported cooldown failure class: {failure_class}")


def calculate_cooldown(
    provider: str,
    failure_class: str,
    *,
    existing: Mapping[str, Any] | None = None,
    retry_after: float | None = None,
    now: float,
) -> dict[str, Any]:
    """Calculate the next persisted cooldown without performing I/O."""
    schedule = cooldown_schedule(failure_class)
    same_recent_class = bool(
        existing
        and str(existing.get("failure_class")) == failure_class
        and now - float(existing.get("last_failure_at", 0)) < COOLDOWN_RESET_WINDOW_SECONDS
    )
    level = int(existing.get("level", -1)) + 1 if same_recent_class else 0
    base_seconds = schedule[min(level, len(schedule) - 1)]
    requested_seconds = max(0.0, float(retry_after or 0.0))
    cooldown_seconds = max(float(base_seconds), requested_seconds)
    return {
        "provider": provider,
        "failure_class": failure_class,
        "level": level,
        "cooldown_seconds": cooldown_seconds,
        "next_probe_at": now + cooldown_seconds,
    }
