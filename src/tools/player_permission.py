"""Player permission support for tool implementations used by the planner and playback flows.

Implements the player_permission module responsibilities used by Sonex runtime flows.
Key public entry points include normalize_player, player_label, is_player_allowed, remember_player, build_player_confirm_result.
"""

from __future__ import annotations

import subprocess
from typing import Any

from src.tools.result import ToolResult
from src.tools.player_permission_state import (
    PLAYER_CONFIRM_CHOICES,
    normalize_confirm_decision,
    normalize_player,
    player_label,
    public_data as _public_data,
)

_ALLOWED_PLAYERS: set[str] = set()
def is_player_allowed(player: str) -> bool:
    """Checks whether is player allowed is true for the supplied input.

    Typical use: Use this function when runtime code needs is player allowed as part of a Sonex command, playback, auth, llm, or ui path.

    Example: is_player_allowed(player=...) -> returns the value used by the surrounding Sonex flow.
    """
    normalized = normalize_player(player)
    if normalized in _ALLOWED_PLAYERS:
        return True
    return normalized == "auto" and "mpv" in _ALLOWED_PLAYERS


def remember_player(player: str) -> None:
    """Coordinates remember player for the current Sonex flow.

    Typical use: Use this function when runtime code needs remember player as part of a Sonex command, playback, auth, llm, or ui path.

    Example: remember_player(player=...) -> returns the value used by the surrounding Sonex flow.
    """
    normalized = normalize_player(player)
    _ALLOWED_PLAYERS.add("mpv" if normalized == "auto" else normalized)


def build_player_confirm_result(
    *,
    tool: str,
    player: str,
    cmd: list[str],
    success_message: str,
    data: dict[str, Any],
) -> dict[str, Any]:
    """Builds player confirm result from the supplied input.

    Typical use: Use this function when runtime code needs build player confirm result as part of a Sonex command, playback, auth, llm, or ui path.

    Example: build_player_confirm_result(tool=..., player=..., cmd=..., success_message=..., data=...) -> returns the value used by the surrounding Sonex flow.
    """
    label = player_label(player)
    return {
        "status": "requires_player_confirm",
        "tool": tool,
        "message": f"Sonex needs permission to open {label}.",
        "data": {
            **data,
            "player": player,
            "player_label": label,
            "cmd": cmd,
            "success_message": success_message,
            "confirm_message": f"Allow Sonex to open {label}?",
            "choices": PLAYER_CONFIRM_CHOICES,
        },
        "error_code": None,
    }


def launch_player_command(
    *,
    tool: str,
    player: str,
    cmd: list[str],
    success_message: str,
    data: dict[str, Any],
) -> dict[str, Any]:
    """Coordinates launch player command for the current Sonex flow.

    Typical use: Use this function when runtime code needs launch player command as part of a Sonex command, playback, auth, llm, or ui path.

    Example: launch_player_command(tool=..., player=..., cmd=..., success_message=..., data=...) -> returns the value used by the surrounding Sonex flow.
    """
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
    """Coordinates complete player confirm for the current Sonex flow.

    Typical use: Use this function when runtime code needs complete player confirm as part of a Sonex command, playback, auth, llm, or ui path.

    Example: complete_player_confirm(pending_result=..., decision=...) -> returns the value used by the surrounding Sonex flow.
    """
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

    selected_player = normalized
    if selected_player in {"allow_once", "allow_always"}:
        selected_player = player

    if normalized == "allow_always":
        remember_player(player)
    elif selected_player == "mpv":
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
