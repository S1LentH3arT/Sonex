"""Core support for agent planning, tool execution, and ui event streaming.

Implements the core module responsibilities used by Sonex runtime flows.
Key public entry points include AgentState, agent_loop.
"""

import json
import logging
from dataclasses import dataclass
from typing import Any, Generator

from src.api.builtin_commands import CommandIntent
from src.llm.planner import llm_plan
from src.llm.transport import sanitize_error_message
from src.memory.memory_hook import append_context, append_tool_summary, finalize_turn
from src.tools.player_permission import complete_player_confirm
from src.tools.registry import ToolRegistry

MAX_TOKEN_LIMIT = 60000
logger = logging.getLogger(__name__)

@dataclass
class AgentState:
    """state type includes: status, tool, context, error
    status: agent is doing something, e.g. "compacting", "planning", "cleaning"
    tool: agent is calling a tool
    complete: agent has finished executing
    error: something went wrong
    confirm: current step requires confirmation
    """
    type: str = None
    tool: str = None
    args: dict = None
    result: Any = None
    content: str = ""
    tokens: int = 0
    is_error: bool = False

def _to_serializable(value: Any) -> Any:
    """Prepares to serializable for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs to serializable without duplicating the local rules.

    Example: _to_serializable(value=...) -> returns the value used by the surrounding Sonex flow.
    """
    try:
        json.dumps(value, ensure_ascii=True)
    except TypeError:
        return str(value)
    return value

def _format_error(exc: Exception) -> str:
    """Prepares format error for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs format error without duplicating the local rules.

    Example: _format_error(exc=...) -> returns the value used by the surrounding Sonex flow.
    """
    return sanitize_error_message(exc)

def _is_player_confirm_result(value: Any) -> bool:
    """Prepares is player confirm result for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs is player confirm result without duplicating the local rules.

    Example: _is_player_confirm_result(value=...) -> returns the value used by the surrounding Sonex flow.
    """
    return isinstance(value, dict) and value.get("status") == "requires_player_confirm"

def _spotify_premium_failure_answer(result: Any) -> str | None:
    """Prepares spotify premium failure answer for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs spotify premium failure answer without duplicating the local rules.

    Example: _spotify_premium_failure_answer(result=...) -> returns the value used by the surrounding Sonex flow.
    """
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

def _player_confirm_payload(result: dict[str, Any], tool_args: dict[str, Any]) -> dict[str, Any]:
    """Prepares player confirm payload for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs player confirm payload without duplicating the local rules.

    Example: _player_confirm_payload(result=..., tool_args=...) -> returns the value used by the surrounding Sonex flow.
    """
    data = result.get("data") or {}
    return {
        "message": data.get("confirm_message") or result.get("message"),
        "choices": data.get("choices") or [],
        "tool_args": tool_args,
        "player": data.get("player"),
        "player_label": data.get("player_label"),
    }

def _confirm_approved(decision: Any) -> bool:
    """Prepares confirm approved for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs confirm approved without duplicating the local rules.

    Example: _confirm_approved(decision=...) -> returns the value used by the surrounding Sonex flow.
    """
    if isinstance(decision, bool):
        return decision
    return str(decision).strip().lower() in {"allow_always", "allow_once", "yes", "true", "ok"}

def _safe_memory_call(label: str, fn: Any, *args: Any, **kwargs: Any) -> Any:
    """Prepares safe memory call for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs safe memory call without duplicating the local rules.

    Example: _safe_memory_call(label=..., fn=...) -> returns the value used by the surrounding Sonex flow.
    """
    try:
        return fn(*args, **kwargs)
    except Exception as exc:
        logger.warning("%s failed: %s", label, _format_error(exc))
        return None

def agent_loop(
    user_input: str,
    tools: ToolRegistry,
    command_intent: CommandIntent | None = None,
) -> Generator[AgentState, AgentState, None]:
    """Coordinates agent loop for the current Sonex flow.

    Typical use: Use this function when runtime code needs agent loop as part of a Sonex command, playback, auth, llm, or ui path.

    Example: agent_loop(user_input=..., tools=..., command_intent=...) -> returns the value used by the surrounding Sonex flow.
    """
    user_context: dict[str, Any]= {"user": user_input}
    if command_intent:
        user_context["command_intent"] = {
            "command": command_intent.command,
            "raw": command_intent.raw,
            "args": command_intent.args,
            "allowed_tools": list(command_intent.allowed_tools),
        }
    _safe_memory_call("append user context", append_context, "user", user_context, ["user_input", "user"])
    _total_tokens = 0


    while True:
        # 执行planner
        try:
            action = llm_plan(user_input=user_input, tools=tools, command_intent=command_intent)
        except Exception as exc:
            error_text = _format_error(exc)
            message = f"Planning failed: {error_text}"
            _safe_memory_call("append planning error", append_context, "error", {"error_text": message}, ["error", "planning"])
            yield AgentState(
                type="error",
                content=error_text,
                is_error=True,
            )
            return

        _total_tokens += action.usage or 0

        yield AgentState(
            type="status",
            content="planning",
            tokens=_total_tokens,
        )

        # 如果llm执行结果中没有工具调用，则loop结束
        if action.tool is None:
            answer = action.output
            _safe_memory_call("append agent context", append_context, "agent", {"agent_output": answer}, ["agent", "output", "complete"])
            _safe_memory_call("finalize turn", finalize_turn, user_input)
            yield AgentState(
                type="complete",
                content=answer,
            )
            return

        if command_intent is not None and action.tool not in command_intent.allowed_tools:
            message = f"Tool '{action.tool}' not allowed for '{command_intent.command}'."
            _safe_memory_call("append unauthorized tool error", append_context, "error", {"error_text": message}, ["error", "tool", action.tool])
            yield AgentState(type="error", content=message, is_error=True)
            return

        # 使用工具
        tool_func = tools.get(action.tool)
        if not tool_func:
            message = f"Tool '{action.tool}' not found or not allowed."
            _safe_memory_call("append tool missing error", append_context, "error", {"error_text": message}, ["error", "tool", f"{action.tool}"])
            yield AgentState(
                type="error",
                content=message,
                is_error=True,
            )
            continue

        if tool_func.confirm_required:
            decision = yield AgentState(
                type="confirm",
                tool=action.tool,
                args=action.args,
            )
            if not _confirm_approved(decision):
                message = f"Tool '{action.tool}' execution rejected."
                _safe_memory_call("append tool rejection", append_context, "warn", {"warning": message}, ["reject", "tool", f"{action.tool}"])
                continue

        tool_args = action.args or {}
        if not isinstance(tool_args, dict):
            message = "Planner returned invalid tool arguments."
            _safe_memory_call("append tool args error", append_context, "error", {"error_text": message}, ["error", "tool", f"{action.args}"])
            yield AgentState(
                type="error",
                content=message,
                is_error=True,
            )
            continue

        yield AgentState(
            type="tool",
            tool=action.tool,
            args=tool_args,
            tokens=_total_tokens,
        )

        tool_result = Any
        try:
            res = tools.invoke(action.tool, tool_args)
            tool_result = _to_serializable(res)
        except Exception as exc:
            error_text = _format_error(exc)
            message = f"Tool execution failed: {error_text}"
            _safe_memory_call("append tool execution error", append_context, "error", {"error_text": message}, ["error", "tool", f"{action.tool}"])
            yield AgentState(
                type="error",
                tool=action.tool,
                content=message,
                is_error=True,
            )
            continue

        if _is_player_confirm_result(tool_result):
            decision = yield AgentState(
                type="confirm",
                tool=action.tool,
                args=_player_confirm_payload(tool_result, tool_args),
            )
            tool_result = _to_serializable(complete_player_confirm(tool_result, decision))

        yield AgentState(
            type="tool",
            tool=action.tool,
            result=tool_result,
        )

        context_id = _safe_memory_call(
            "append tool context",
            append_context,
            "tool",
            {"tool": action.tool, "args": tool_args, "result": tool_result},
            ["tool", "result", f"{action.tool}"],
        )
        if isinstance(context_id, int):
            _safe_memory_call("append tool summary", append_tool_summary, context_id, action.tool, tool_args, tool_result)

        capability_answer = _spotify_premium_failure_answer(tool_result)
        if capability_answer:
            _safe_memory_call(
                "append agent context",
                append_context,
                "agent",
                {"agent_output": capability_answer},
                ["agent", "output", "complete"],
            )
            _safe_memory_call("finalize turn", finalize_turn, user_input)
            yield AgentState(
                type="complete",
                content=capability_answer,
                tokens=_total_tokens,
            )
            return

        yield AgentState(
            type="status",
            content="cleaning",
            tokens=_total_tokens,
        )
