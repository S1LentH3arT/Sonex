"""User-facing Agent Tool message formatting.

This module owns the semantic display contract. It intentionally never renders
ANSI escape sequences; the terminal client maps segment styles to its theme.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from src.agent.action import ToolAction
from src.sandbox.command_policy import policy_reason, sanitize_command_display


@dataclass(frozen=True, slots=True)
class RichToolMessage:
    """Plain-text fallback plus structured terminal-rendering segments."""

    text: str
    segments: tuple[dict[str, Any], ...]


_CALL_ARGUMENT_PRIORITY = (
    "provider",
    "query",
    "ref",
    "command",
    "player",
    "title",
    "artist",
    "album",
)


def format_tool_batch(calls: Iterable[ToolAction]) -> RichToolMessage:
    """Format one ordered model tool batch as one Agent chat message."""
    blocks = [_format_tool_call(call) for call in calls]
    text_parts: list[str] = []
    segments: list[dict[str, Any]] = []
    for index, block in enumerate(blocks):
        if index:
            text_parts.append("\n\n")
            segments.append({"text": "\n\n", "style": "tool_value"})
        text_parts.append(block.text)
        segments.extend(block.segments)
    return RichToolMessage(text="".join(text_parts), segments=tuple(segments))


def approved_commands_message(commands: Iterable[str]) -> str:
    """Return the exact one-time approval audit copy."""
    return "\n".join(
        f"You confirmed running '{sanitize_command_display(command)}' this time."
        for command in commands
    )


def rejected_commands_message(commands: Iterable[str]) -> str:
    """Return the exact rejected-command audit copy."""
    return "\n".join(
        f"You rejected running '{sanitize_command_display(command)}'."
        for command in commands
    )


def blocked_commands_message(
    commands: Iterable[str],
    rule_ids: Iterable[str],
    command_rule_ids: Iterable[Iterable[str]] | None = None,
) -> str:
    """Return one stable System message for a hard-denied tool batch."""
    safe_commands = [sanitize_command_display(command) for command in commands]
    fallback_reasons = tuple(rule_ids)
    per_command_rules = list(command_rule_ids or ())
    lines = ["The tool-call batch was blocked, and no tools were run."]
    for index, command in enumerate(safe_commands):
        current_rules = (
            tuple(per_command_rules[index])
            if index < len(per_command_rules)
            else fallback_reasons
        )
        reasons = ", ".join(
            dict.fromkeys(policy_reason(rule_id) for rule_id in current_rules)
        )
        lines.append(
            f"'{command}' violates the sandbox policy: "
            f"{reasons or 'restricted operation'}."
        )
    return "\n".join(lines)


def _format_tool_call(call: ToolAction) -> RichToolMessage:
    formatter = {
        "Bash": _format_bash,
        "Call": _format_call,
        "Connect": _format_connect,
        "Query": _format_query,
        "Read": _format_read,
    }.get(call.tool, _format_fallback)
    values = formatter(call.args or {})
    return _tool_block(call.tool, values)


def _tool_block(tool_name: str, values: list[str]) -> RichToolMessage:
    safe_name = _clean_value(tool_name) or "Tool"
    safe_values = [_clean_value(value) for value in values if _clean_value(value)]
    if not safe_values:
        return RichToolMessage(
            text=safe_name,
            segments=({"text": safe_name, "style": "tool_name"},),
        )

    indent = " " * (len(safe_name) + 1)
    text = f"{safe_name} {safe_values[0]}"
    segments: list[dict[str, Any]] = [
        {"text": safe_name, "style": "tool_name"},
        {"text": f" {safe_values[0]}", "style": "tool_value"},
    ]
    for value in safe_values[1:]:
        text += f"\n{indent}{value}"
        segments.append({"text": f"\n{indent}{value}", "style": "tool_value"})
    return RichToolMessage(text=text, segments=tuple(segments))


def _format_bash(args: dict[str, Any]) -> list[str]:
    commands = args.get("commands")
    if isinstance(commands, list):
        return [sanitize_command_display(str(command)) for command in commands]
    return []


def _format_read(args: dict[str, Any]) -> list[str]:
    for key in ("files", "paths"):
        values = args.get(key)
        if isinstance(values, list):
            return [_clean_value(value) for value in values]
    values = [_clean_value(args.get("query"))]
    source = _clean_value(args.get("source"))
    if source and source != "auto":
        values.append(source)
    return [" ".join(value for value in values if value)]


def _format_query(args: dict[str, Any]) -> list[str]:
    return [
        " ".join(
            value
            for value in (
                _clean_value(args.get("provider")),
                _clean_value(args.get("resource")),
                _clean_value(args.get("query") or args.get("ref")),
            )
            if value
        )
    ]


def _format_connect(args: dict[str, Any]) -> list[str]:
    return [_clean_value(args.get("provider"))]


def _format_call(args: dict[str, Any]) -> list[str]:
    values = [_clean_value(args.get("workflow"))]
    arguments = args.get("arguments")
    if isinstance(arguments, dict):
        seen: set[str] = set()
        for key in _CALL_ARGUMENT_PRIORITY:
            value = _clean_value(arguments.get(key))
            if value:
                values.append(value)
                seen.add(key)
        for key, raw_value in arguments.items():
            if key in seen or isinstance(raw_value, (dict, list)):
                continue
            value = _clean_value(raw_value)
            if value:
                values.append(value)
    joined = " ".join(value for value in values if value)
    return [joined] if joined else []


def _format_fallback(args: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for value in args.values():
        if isinstance(value, list):
            values.extend(_clean_value(item) for item in value)
        elif not isinstance(value, dict):
            values.append(_clean_value(value))
    return [value for value in values if value]


def _clean_value(value: Any) -> str:
    if value is None:
        return ""
    return sanitize_command_display(str(value)).strip()
