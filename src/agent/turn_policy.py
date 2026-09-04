"""Pure policy decisions used by the bounded Agent turn loop."""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

from src.api.builtin_commands import CommandIntent


def to_serializable(value: Any) -> Any:
    """Keep JSON values intact and provide a stable fallback for other values."""
    try:
        json.dumps(value, ensure_ascii=True)
    except TypeError:
        return str(value)
    return value


def is_player_confirm_result(value: Any) -> bool:
    return isinstance(value, dict) and value.get("status") == "requires_player_confirm"


def is_suspended_interaction_result(value: Any) -> bool:
    return isinstance(value, dict) and value.get("status") in {
        "requires_play_selection",
        "requires_modify_confirmation",
    }


def is_committed_playback_result(value: Any) -> bool:
    return isinstance(value, dict) and value.get("status") in {
        "playback_completed",
        "playback_failed",
        "playback_cancelled",
    }


def normalized_call_key(tool: str, arguments: dict[str, Any]) -> str:
    """Build a stable key for repeated Agent Tool detection."""
    return json.dumps(
        {"tool": tool, "arguments": arguments},
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def spotify_premium_failure_answer(result: Any) -> str | None:
    if not isinstance(result, dict):
        return None
    error_code = result.get("error_code")
    if error_code == "SPOTIFY_APP_PREMIUM_REQUIRED":
        message = result.get("message") or "Spotify search requires a Premium account for the app owner."
        return f"{message} I can play the track through YouTube/local playback instead."
    if error_code != "SPOTIFY_PREMIUM_REQUIRED":
        return None
    message = result.get("message") or "Spotify playback requires a Premium account."
    return f"{message} I can search Spotify results, or play the track through YouTube/local playback instead."


def player_confirm_payload(result: dict[str, Any], tool_args: dict[str, Any]) -> dict[str, Any]:
    data = result.get("data") or {}
    return {
        "message": data.get("confirm_message") or result.get("message"),
        "choices": data.get("choices") or [],
        "tool_args": tool_args,
        "player": data.get("player"),
        "player_label": data.get("player_label"),
    }


def confirm_approved(decision: Any) -> bool:
    if isinstance(decision, bool):
        return decision
    return str(decision).strip().lower() in {"allow_always", "allow_once", "yes", "true", "ok"}


def confirm_interrupted(decision: Any) -> bool:
    if not isinstance(decision, dict):
        return False
    data = decision.get("data")
    return (
        decision.get("status") == "cancelled"
        and isinstance(data, dict)
        and data.get("reason") == "session_disconnected"
    )


def planning_command_intent(
    command_intent: CommandIntent | None,
    *,
    tool_call_count: int,
    tool_call_limit: int,
) -> CommandIntent | None:
    """Turn a bounded command into a text-only plan after its tool budget."""
    if command_intent is None or tool_call_count < tool_call_limit:
        return command_intent
    return replace(
        command_intent,
        allowed_tools=(),
        max_tool_calls=0,
        intent_prompt=(
            f"{command_intent.intent_prompt} The tool-call budget is now exhausted. "
            "Do not call another tool. Answer now using the tool results already returned."
        ),
    )
