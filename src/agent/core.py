"""Core support for agent planning, tool execution, and ui event streaming.

Implements the core module responsibilities used by Sonex runtime flows.
Key public entry points include AgentState, agent_loop.
"""

import json
import logging
from dataclasses import dataclass
from typing import Any, Generator

from src.api.builtin_commands import CommandIntent
from src.agent.action import ToolAction
from src.llm.planner import llm_plan
from src.llm.transport import sanitize_error_message
from src.memory.hooks import append_context, append_tool_summary, finalize_turn
from src.sandbox.command_policy import BASH_REVIEW_PAGE_SIZE, BashCommandDecision, inspect_commands
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
    calls: list[ToolAction] | None = None

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


def _is_suspended_interaction_result(value: Any) -> bool:
    """Return whether an Agent Tool asked the UI runtime to suspend the turn."""
    return isinstance(value, dict) and value.get("status") in {
        "requires_play_selection",
        "requires_connection",
    }

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


def _confirm_interrupted(decision: Any) -> bool:
    """Return whether confirmation ended because the client disconnected."""
    if not isinstance(decision, dict):
        return False
    data = decision.get("data")
    return (
        decision.get("status") == "cancelled"
        and isinstance(data, dict)
        and data.get("reason") == "session_disconnected"
    )

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
    total_tokens = 0
    planning_feedback: str | None = None
    bash_rewrite_used = False

    while True:
        try:
            plan_args: dict[str, Any] = {
                "user_input": user_input,
                "tools": tools,
                "command_intent": command_intent,
            }
            if planning_feedback:
                plan_args["planning_feedback"] = planning_feedback
            action = llm_plan(**plan_args)
        except Exception as exc:
            error_text = _format_error(exc)
            message = f"Planning failed: {error_text}"
            _safe_memory_call("append planning error", append_context, "error", {"error_text": message}, ["error", "planning"])
            yield AgentState(type="error", content=error_text, is_error=True)
            return

        planning_feedback = None
        total_tokens += action.usage or 0
        yield AgentState(type="status", content="planning", tokens=total_tokens)

        calls = action.calls()
        if not calls:
            answer = action.output or ""
            _safe_memory_call("append agent context", append_context, "agent", {"agent_output": answer}, ["agent", "output", "complete"])
            _safe_memory_call("finalize turn", finalize_turn, user_input)
            yield AgentState(type="complete", content=answer)
            return

        batch_error: str | None = None
        for call in calls:
            if command_intent is not None and call.tool not in command_intent.allowed_tools:
                batch_error = f"Tool '{call.tool}' not allowed for '{command_intent.command}'."
                break
            if not isinstance(call.args, dict):
                batch_error = "Planner returned invalid tool arguments."
                break
            if tools.get_agent(call.tool) is None:
                batch_error = f"Tool '{call.tool}' not found or not allowed."
                break
        if batch_error:
            _safe_memory_call("append invalid tool batch", append_context, "error", {"error_text": batch_error}, ["error", "tool"])
            yield AgentState(type="error", content=batch_error, is_error=True)
            return

        bash_calls = [call for call in calls if call.tool == "Bash"]
        bash_decision: BashCommandDecision | None = None
        if len(bash_calls) > 1:
            invalid_reason = "Use at most one Bash tool call per response."
        elif bash_calls:
            bash_decision = inspect_commands(bash_calls[0].args.get("commands"))
            invalid_reason = bash_decision.invalid_reason
        else:
            invalid_reason = None

        if invalid_reason:
            if not bash_rewrite_used:
                bash_rewrite_used = True
                planning_feedback = (
                    f"Your Bash request was invalid: {invalid_reason} "
                    "Rewrite it once using one Bash call with reviewable commands."
                )
                continue
            warning = "Agent could not produce reviewable Bash commands."
            _safe_memory_call("append invalid Bash warning", append_context, "warn", {"warning": warning}, ["warning", "Bash"])
            yield AgentState(type="warning", content=warning)
            return

        if bash_decision is not None and bash_decision.level == "deny":
            yield AgentState(
                type="tool_blocked",
                calls=calls,
                args={
                    "commands": list(bash_decision.blocked_commands),
                    "rule_ids": list(bash_decision.rule_ids),
                    "command_rule_ids": [
                        list(rule_ids)
                        for rule_ids in bash_decision.blocked_rule_ids
                    ],
                },
            )
            return

        # Preserve confirmation behavior for any legacy Agent Tool that still
        # explicitly opts into the registry-level confirmation contract.
        generic_rejected = False
        for call in calls:
            tool_func = tools.get_agent(call.tool)
            if tool_func is None or call.tool == "Bash" or not tool_func.confirm_required:
                continue
            decision = yield AgentState(type="confirm", tool=call.tool, args=call.args)
            if not _confirm_approved(decision):
                message = f"Tool '{call.tool}' execution rejected."
                _safe_memory_call("append tool rejection", append_context, "warn", {"warning": message}, ["reject", "tool", call.tool])
                generic_rejected = True
                break
        if generic_rejected:
            yield AgentState(type="status", content="cleaning", tokens=total_tokens)
            continue

        if bash_decision is not None and bash_decision.level == "review":
            display_commands = list(bash_decision.display_commands)
            page_count = (len(display_commands) + BASH_REVIEW_PAGE_SIZE - 1) // BASH_REVIEW_PAGE_SIZE
            for page_index in range(page_count):
                start = page_index * BASH_REVIEW_PAGE_SIZE
                page_commands = display_commands[start : start + BASH_REVIEW_PAGE_SIZE]
                title = "Tool call double check"
                if page_count > 1:
                    title = f"{title} {page_index + 1}/{page_count}"
                decision = yield AgentState(
                    type="confirm",
                    tool="Bash",
                    args={
                        "variant": "tool_call_review",
                        "message": title,
                        "warning": "Please review the Bash command(s) below before permission.",
                        "commands": page_commands,
                        "page_index": page_index,
                        "page_count": page_count,
                        "choices": [
                            {"value": "allow_once", "label": "Yes, I approve"},
                            {"value": "deny", "label": "No"},
                        ],
                    },
                )
                if _confirm_interrupted(decision):
                    return
                if not _confirm_approved(decision):
                    yield AgentState(
                        type="tool_rejected",
                        calls=calls,
                        args={"commands": display_commands},
                    )
                    return
            yield AgentState(
                type="tool_approved",
                calls=calls,
                args={"commands": display_commands},
            )

        # This is the durable Agent message boundary: validation and
        # authorization are complete, but no tool has started yet.
        yield AgentState(type="tool_batch", calls=calls, tokens=total_tokens)

        capability_answer: str | None = None
        for call in calls:
            tool_args = call.args
            yield AgentState(
                type="tool",
                tool=call.tool,
                args=tool_args,
                tokens=total_tokens,
            )

            try:
                res = tools.invoke_agent(call.tool, tool_args)
                tool_result = _to_serializable(res)
            except Exception as exc:
                error_text = _format_error(exc)
                message = f"Tool execution failed: {error_text}"
                _safe_memory_call("append tool execution error", append_context, "error", {"error_text": message}, ["error", "tool", call.tool])
                yield AgentState(
                    type="error",
                    tool=call.tool,
                    content=message,
                    is_error=True,
                )
                break

            if _is_player_confirm_result(tool_result):
                decision = yield AgentState(
                    type="confirm",
                    tool=call.tool,
                    args=_player_confirm_payload(tool_result, tool_args),
                )
                tool_result = _to_serializable(complete_player_confirm(tool_result, decision))

            if _is_suspended_interaction_result(tool_result):
                interaction_result = yield AgentState(
                    type="interaction",
                    tool=call.tool,
                    args={"request": tool_result},
                )
                tool_result = _to_serializable(interaction_result)

            yield AgentState(type="tool", tool=call.tool, result=tool_result)

            context_id = _safe_memory_call(
                "append tool context",
                append_context,
                "tool",
                {"tool": call.tool, "args": tool_args, "result": tool_result},
                ["tool", "result", call.tool],
            )
            if isinstance(context_id, int):
                _safe_memory_call("append tool summary", append_tool_summary, context_id, call.tool, tool_args, tool_result)

            capability_answer = capability_answer or _spotify_premium_failure_answer(tool_result)

        if capability_answer:
            _safe_memory_call(
                "append agent context",
                append_context,
                "agent",
                {"agent_output": capability_answer},
                ["agent", "output", "complete"],
            )
            _safe_memory_call("finalize turn", finalize_turn, user_input)
            yield AgentState(type="complete", content=capability_answer, tokens=total_tokens)
            return

        yield AgentState(type="status", content="cleaning", tokens=total_tokens)
