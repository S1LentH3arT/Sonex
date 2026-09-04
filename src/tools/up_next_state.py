"""Pure state transitions for the persistent Up-Next queue."""

from __future__ import annotations

from typing import Any

from src.music.legacy_tracks import downgrade_retired_provider_track


MAX_UP_NEXT = 100
MAX_FAILED_UP_NEXT = 100


def empty_up_next_state() -> dict[str, Any]:
    return {"revision": 0, "items": [], "failed": []}


def coerce_up_next_state(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return empty_up_next_state()
    raw_items = value.get("items", [])
    raw_failed = value.get("failed", [])
    if not isinstance(raw_items, list):
        raw_items = []
    if not isinstance(raw_failed, list):
        raw_failed = []
    items = [
        downgrade_retired_provider_track(item)[0]
        for item in raw_items
        if isinstance(item, dict)
    ]
    failed = [
        downgrade_retired_provider_track(item)[0]
        for item in raw_failed
        if isinstance(item, dict)
    ]
    try:
        revision = max(0, int(value.get("revision") or 0))
    except (TypeError, ValueError):
        revision = 0
    return {
        "revision": revision,
        "items": items[:MAX_UP_NEXT],
        "failed": failed[:MAX_FAILED_UP_NEXT],
    }


def append_up_next_state(state: dict[str, Any], track: dict[str, Any]) -> dict[str, Any]:
    """Append one structured track without changing the queue revision."""
    ref = str(track.get("ref") or "").strip()
    if not ref:
        raise ValueError("Up-next tracks require a structured ref.")
    if not track.get("playable") and not track.get("requires_resolution"):
        raise ValueError("Up-next tracks require an available playback route.")
    if any(str(item.get("ref") or "") == ref for item in state["items"]):
        return state
    return {
        **state,
        "items": [*state["items"], dict(track)][:MAX_UP_NEXT],
    }


def consume_up_next_head_state(state: dict[str, Any]) -> dict[str, Any]:
    if not state["items"]:
        return state
    return {**state, "items": list(state["items"][1:])}


def fail_up_next_head_state(
    state: dict[str, Any],
    reason: str,
    *,
    failed_at: float,
) -> dict[str, Any]:
    if not state["items"]:
        return state
    failed = {
        **state["items"][0],
        "failure_reason": str(reason or "Playback failed."),
        "failed_at": failed_at,
    }
    return {
        **state,
        "items": list(state["items"][1:]),
        "failed": [failed, *state["failed"]][:MAX_FAILED_UP_NEXT],
    }
