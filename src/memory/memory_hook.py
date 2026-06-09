"""Memory hook support for local memory storage and retrieval.

Implements the memory_hook module responsibilities used by Sonex runtime flows.
Key public entry points include append_context, append_cache, append_tool_summary, finalize_turn.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from src.memory import memory_store


def append_context(
    role: str,
    context: dict[str, Any],
    tags: list[str],
    table_name: str = "context",
) -> int:
    """Append context.

    Coordinates append context logic for the surrounding Sonex flow.

    Args:
        role: Input value used by the append context operation.
        context: Input value used by the append context operation.
        tags: Input value used by the append context operation.
        table_name: Input value used by the append context operation.

    Returns:
        The computed result for append context.
    """
    if table_name != "context":
        raise ValueError("append_context only supports the context table.")
    return memory_store.append_context(role, context, tags)


def append_cache(
    key: str,
    summary: str,
    tags: list[str],
    importance: float = 0,
    source: str | None = None,
    source_context_id: int | None = None,
    kind: str = "turn_summary",
) -> None:
    """Append cache.

    Coordinates append cache logic for the surrounding Sonex flow.

    Args:
        key: Input value used by the append cache operation.
        summary: Input value used by the append cache operation.
        tags: Input value used by the append cache operation.
        importance: Input value used by the append cache operation.
        source: Input value used by the append cache operation.
        source_context_id: Input value used by the append cache operation.
        kind: Input value used by the append cache operation.

    Returns:
        The computed result for append cache.
    """
    memory_store.upsert_cache(
        key=key,
        summary=summary,
        tags=tags,
        importance=importance,
        source=source,
        source_context_id=source_context_id,
        kind=kind,
    )


def append_tool_summary(context_id: int, tool: str, args: dict[str, Any], result: Any) -> dict[str, Any]:
    """Append tool summary.

    Coordinates append tool summary logic for the surrounding Sonex flow.

    Args:
        context_id: Input value used by the append tool summary operation.
        tool: Input value used by the append tool summary operation.
        args: Input value used by the append tool summary operation.
        result: Input value used by the append tool summary operation.

    Returns:
        The computed result for append tool summary.
    """
    summary = _build_tool_summary(tool=tool, args=args, result=result)
    key = f"tool:{tool}:{context_id}"
    tags = ["tool_summary", "tool", tool]
    memory_store.upsert_cache(
        key=key,
        summary=summary,
        tags=tags,
        importance=0.7,
        source="context",
        source_context_id=context_id,
        kind="tool_summary",
    )
    return {"success": True, "key": key, "summary": summary, "tags": tags}


def finalize_turn(user_input: str) -> dict[str, Any]:
    """Persist a reusable experience candidate for the completed turn."""
    events = memory_store.search_context("", table="context", limit=20)
    if not events:
        return {"success": False, "error": "No context events found."}

    latest_answer = _latest_content(events, "agent", "agent_output")
    tool_names = _tool_names(events)
    error_text = _latest_content(events, "error", "error_text")

    summary = _build_summary(
        user_input=user_input,
        latest_answer=latest_answer,
        tool_names=tool_names,
        error_text=error_text,
    )
    key = _cache_key(user_input, summary)
    tags = ["turn", "experience", *tool_names]
    if error_text:
        tags.append("error")

    memory_store.upsert_cache(
        key=key,
        summary=summary,
        tags=tags,
        importance=0.6 if latest_answer else 0.3,
        source="turn",
        source_context_id=None,
        kind="turn_summary",
    )
    return {"success": True, "key": key, "summary": summary, "tags": tags}


def _build_tool_summary(tool: str, args: dict[str, Any], result: Any) -> str:
    """Build tool summary.

    Coordinates build tool summary logic for the surrounding Sonex flow.

    Args:
        tool: Input value used by the build tool summary operation.
        args: Input value used by the build tool summary operation.
        result: Input value used by the build tool summary operation.

    Returns:
        The computed result for build tool summary.
    """
    args_text = _clip(json.dumps(args, ensure_ascii=False, default=str), 240)
    result_text = _clip(json.dumps(result, ensure_ascii=False, default=str), 700)
    return f"Tool {tool} called with args {args_text}; result summary: {result_text}"


def _build_summary(
    *,
    user_input: str,
    latest_answer: str,
    tool_names: list[str],
    error_text: str,
) -> str:
    """Build summary.

    Coordinates build summary logic for the surrounding Sonex flow.

    Args:
        user_input: Input value used by the build summary operation.
        latest_answer: Input value used by the build summary operation.
        tool_names: Input value used by the build summary operation.
        error_text: Input value used by the build summary operation.

    Returns:
        The computed result for build summary.
    """
    parts = [f"User asked: {user_input.strip()}"]
    if tool_names:
        parts.append(f"Tools used: {', '.join(tool_names)}")
    if latest_answer:
        parts.append(f"Reusable outcome: {_clip(latest_answer, 500)}")
    if error_text:
        parts.append(f"Failure note: {_clip(error_text, 300)}")
    return " | ".join(parts)


def _latest_content(events: list[dict[str, Any]], role: str, key: str) -> str:
    """Latest content.

    Coordinates latest content logic for the surrounding Sonex flow.

    Args:
        events: Input value used by the latest content operation.
        role: Input value used by the latest content operation.
        key: Input value used by the latest content operation.

    Returns:
        The computed result for latest content.
    """
    for event in events:
        if event.get("type") != role:
            continue
        content = _loads(event.get("content"))
        value = content.get(key)
        if value:
            return str(value)
    return ""


def _tool_names(events: list[dict[str, Any]]) -> list[str]:
    """Tool names.

    Coordinates tool names logic for the surrounding Sonex flow.

    Args:
        events: Input value used by the tool names operation.

    Returns:
        The computed result for tool names.
    """
    names: list[str] = []
    for event in events:
        if event.get("type") != "tool":
            continue
        tags = _loads_list(event.get("tags"))
        for tag in tags:
            if tag in {"tool", "result"}:
                continue
            if tag not in names:
                names.append(tag)
    return names


def _loads(value: Any) -> dict[str, Any]:
    """Loads.

    Coordinates loads logic for the surrounding Sonex flow.

    Args:
        value: Input value used by the loads operation.

    Returns:
        The computed result for loads.
    """
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _loads_list(value: Any) -> list[str]:
    """Loads list.

    Coordinates loads list logic for the surrounding Sonex flow.

    Args:
        value: Input value used by the loads list operation.

    Returns:
        The computed result for loads list.
    """
    if isinstance(value, list):
        return [str(item) for item in value]
    if not isinstance(value, str):
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed]


def _cache_key(user_input: str, summary: str) -> str:
    """Cache key.

    Coordinates cache key logic for the surrounding Sonex flow.

    Args:
        user_input: Input value used by the cache key operation.
        summary: Input value used by the cache key operation.

    Returns:
        The computed result for cache key.
    """
    payload = f"{user_input.strip()}\n{summary.strip()}".encode("utf-8")
    return f"turn:{hashlib.sha256(payload).hexdigest()[:16]}"


def _clip(text: str, limit: int) -> str:
    """Clip.

    Coordinates clip logic for the surrounding Sonex flow.

    Args:
        text: Input value used by the clip operation.
        limit: Input value used by the clip operation.

    Returns:
        The computed result for clip.
    """
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return f"{text[:limit].rstrip()}..."
