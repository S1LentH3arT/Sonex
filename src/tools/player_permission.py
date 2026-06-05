from __future__ import annotations

import subprocess
from typing import Any

from src.tools.result import ToolResult

PLAYER_CONFIRM_CHOICES = [
    {
        "value": "mpv",
        "label": "🎧 mpv",
        "description": "recommended for smoother background playback.",
    },
    {
        "value": "cvlc",
        "label": "📻 VLC",
        "description": "fallback background player using the VLC rc interface.",
    },
    {"value": "deny", "label": "取消"},
]

_ALLOWED_PLAYERS: set[str] = set()
_PRIVATE_CONFIRM_KEYS = {
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
    known = {
        "auto": "auto local player",
        "vlc": "VLC",
        "mpv": "mpv",
        "cvlc": "VLC",
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
    if decision_text in {"allow_always", "allow_once", "mpv", "cvlc", "vlc", "deny"}:
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

    selected_player = "cvlc" if normalized == "vlc" else normalized
    if selected_player in {"allow_once", "allow_always"}:
        selected_player = player

    if normalized == "allow_always":
        remember_player(player)
    elif selected_player in {"mpv", "cvlc"}:
        remember_player(selected_player)

    cmd = data.get("cmd")
    if not isinstance(cmd, list) or not all(isinstance(part, str) for part in cmd):
        return ToolResult.fail(
            tool=tool,
            message="Invalid pending player launch command.",
            error_code="INVALID_PLAYER_COMMAND",
            data=_public_data(data),
        ).to_dict()

    playback_source_url = data.get("playback_source_url")
    playback_source = data.get("playback_source")
    playback_metadata = data.get("playback_metadata")
    if isinstance(playback_source_url, str) and isinstance(playback_source, str) and isinstance(playback_metadata, dict):
        from src.tools.playback_controller import start_local_playback

        return start_local_playback(
            tool=tool,
            source_url=playback_source_url,
            source=playback_source,  # type: ignore[arg-type]
            metadata=playback_metadata,
            player=selected_player,
            success_message=str(data.get("success_message") or f"Playing via {selected_player} started."),
        )

    return launch_player_command(
        tool=tool,
        player=selected_player,
        cmd=cmd,
        success_message=str(data.get("success_message") or f"Playing via {selected_player} started."),
        data=_public_data(data),
    )
