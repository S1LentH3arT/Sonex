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
    """To serializable.

    Coordinates to serializable logic for the surrounding Sonex flow.

    Args:
        value: Input value used by the to serializable operation.

    Returns:
        The computed result for to serializable.
    """
    try:
        json.dumps(value, ensure_ascii=True)
    except TypeError:
        return str(value)
    return value

def _format_error(exc: Exception) -> str:
    """Format error.

    Coordinates format error logic for the surrounding Sonex flow.

    Args:
        exc: Input value used by the format error operation.

    Returns:
        The computed result for format error.
    """
    return sanitize_error_message(exc)

def _is_player_confirm_result(value: Any) -> bool:
    """Is player confirm result.

    Coordinates is player confirm result logic for the surrounding Sonex flow.

    Args:
        value: Input value used by the is player confirm result operation.

    Returns:
        The computed result for is player confirm result.
    """
    return isinstance(value, dict) and value.get("status") == "requires_player_confirm"

def _spotify_premium_failure_answer(result: Any) -> str | None:
    """Spotify premium failure answer.

    Coordinates spotify premium failure answer logic for the surrounding Sonex flow.

    Args:
        result: Input value used by the spotify premium failure answer operation.

    Returns:
        The computed result for spotify premium failure answer.
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
    """Player confirm payload.

    Coordinates player confirm payload logic for the surrounding Sonex flow.

    Args:
        result: Input value used by the player confirm payload operation.
        tool_args: Input value used by the player confirm payload operation.

    Returns:
        The computed result for player confirm payload.
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
    """Confirm approved.

    Coordinates confirm approved logic for the surrounding Sonex flow.

    Args:
        decision: Input value used by the confirm approved operation.

    Returns:
        The computed result for confirm approved.
    """
    if isinstance(decision, bool):
        return decision
    return str(decision).strip().lower() in {"allow_always", "allow_once", "yes", "true", "ok"}

def _safe_memory_call(label: str, fn: Any, *args: Any, **kwargs: Any) -> Any:
    """Safe memory call.

    Coordinates safe memory call logic for the surrounding Sonex flow.

    Args:
        label: Input value used by the safe memory call operation.
        fn: Input value used by the safe memory call operation.
        args: Input value used by the safe memory call operation.
        kwargs: Input value used by the safe memory call operation.

    Returns:
        The computed result for safe memory call.
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
    """Agent loop.

    Coordinates agent loop logic for the surrounding Sonex flow.

    Args:
        user_input: Input value used by the agent loop operation.
        tools: Input value used by the agent loop operation.
        command_intent: Input value used by the agent loop operation.

    Returns:
        The computed result for agent loop.
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
