from __future__ import annotations

import subprocess
from typing import Any

from src.tools.result import ToolResult

PLAYER_CONFIRM_CHOICES = [
    {"value": "allow_always", "label": "Yes and don't ask again"},
    {"value": "allow_once", "label": "Yes for once"},
    {"value": "deny", "label": "Nope"},
]

_ALLOWED_PLAYERS: set[str] = set()
_PRIVATE_CONFIRM_KEYS = {"cmd", "choices", "success_message", "confirm_message"}


def normalize_player(player: str) -> str:
    return player.strip().lower()


def player_label(player: str) -> str:
    known = {
        "vlc": "VLC",
        "mpv": "mpv",
    }
    return known.get(normalize_player(player), player)


def is_player_allowed(player: str) -> bool:
    return normalize_player(player) in _ALLOWED_PLAYERS


def remember_player(player: str) -> None:
    _ALLOWED_PLAYERS.add(normalize_player(player))


def _public_data(data: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in data.items() if key not in _PRIVATE_CONFIRM_KEYS}


def build_player_confirm_result(
    *,
    tool: str,
    player: str,
    cmd: list[str],
    success_message: str,
    data: dict[str, Any],
) -> dict[str, Any]:
    label = player_label(player)
    return {
        "status": "requires_player_confirm",
        "tool": tool,
        "message": f"Sonex想要打开{label}音乐播放器",
        "data": {
            **data,
            "player": player,
            "player_label": label,
            "cmd": cmd,
            "success_message": success_message,
            "confirm_message": f"Sonex wanna open {label} player, confirm?",
            "choices": PLAYER_CONFIRM_CHOICES,
        },
        "error_code": None,
    }


def normalize_confirm_decision(decision: Any) -> str:
    if decision is True:
        return "allow_once"
    if decision is False or decision is None:
        return "deny"

    decision_text = str(decision).strip().lower()
    if decision_text in {"allow_always", "allow_once", "deny"}:
        return decision_text
    if decision_text in {"yes", "true", "ok"}:
        return "allow_once"
    return "deny"


def launch_player_command(
    *,
    tool: str,
    player: str,
    cmd: list[str],
    success_message: str,
    data: dict[str, Any],
) -> dict[str, Any]:
    try:
        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        return ToolResult.failure(
            tool=tool,
            message=f"Failed to launch player '{player}': {exc}",
            error_code=exc.errno,
            data=data,
        ).to_dict()

    return ToolResult.success(
        tool=tool,
        message=success_message,
        data=data,
    ).to_dict()


def complete_player_confirm(pending_result: dict[str, Any], decision: Any) -> dict[str, Any]:
    data = pending_result.get("data") or {}
    tool = str(pending_result.get("tool") or data.get("tool") or "player")
    player = str(data.get("player") or "")
    normalized = normalize_confirm_decision(decision)

    if normalized == "deny":
        return ToolResult.fail(
            tool=tool,
            message=f"Player '{player}' launch rejected.",
            error_code="PLAYER_REJECTED",
            data=_public_data(data),
        ).to_dict()

    if normalized == "allow_always":
        remember_player(player)

    cmd = data.get("cmd")
    if not isinstance(cmd, list) or not all(isinstance(part, str) for part in cmd):
        return ToolResult.fail(
            tool=tool,
            message="Invalid pending player launch command.",
            error_code="INVALID_PLAYER_COMMAND",
            data=_public_data(data),
        ).to_dict()

    return launch_player_command(
        tool=tool,
        player=player,
        cmd=cmd,
        success_message=str(data.get("success_message") or f"Playing via {player} started."),
        data=_public_data(data),
    )
