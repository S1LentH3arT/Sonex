"""Pure player permission and confirmation decisions."""

from __future__ import annotations

from typing import Any


PLAYER_CONFIRM_CHOICES = [
    {
        "value": "mpv",
        "label": "mpv",
        "description": "default controllable backend for smooth background playback",
    },
    {"value": "deny", "label": "Cancel"},
]

PRIVATE_CONFIRM_KEYS = {
    "cmd",
    "choices",
    "success_message",
    "confirm_message",
    "playback_source_url",
    "playback_source",
    "playback_metadata",
}


def normalize_player(player: str) -> str:
    return player.strip().lower()


def player_label(player: str) -> str:
    return {"auto": "mpv", "mpv": "mpv"}.get(normalize_player(player), player)


def public_data(data: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in data.items() if key not in PRIVATE_CONFIRM_KEYS}


def normalize_confirm_decision(decision: Any) -> str:
    if decision is True:
        return "allow_once"
    if decision is False or decision is None:
        return "deny"
    decision_text = str(decision).strip().lower()
    if decision_text in {"allow_always", "allow_once", "mpv", "deny"}:
        return decision_text
    if decision_text in {"yes", "true", "ok"}:
        return "allow_once"
    return "deny"
