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
    """Coordinates append context for the current Sonex flow.

    Typical use: Use this function when runtime code needs append context as part of a Sonex command, playback, auth, llm, or ui path.

    Example: append_context(role=..., context=..., tags=..., table_name=...) -> returns the value used by the surrounding Sonex flow.
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
    """Coordinates append cache for the current Sonex flow.

    Typical use: Use this function when runtime code needs append cache as part of a Sonex command, playback, auth, llm, or ui path.

    Example: append_cache(key=..., summary=..., tags=..., importance=..., source=..., source_context_id=..., kind=...) -> returns the value used by the surrounding Sonex flow.
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
    """Coordinates append tool summary for the current Sonex flow.

    Typical use: Use this function when runtime code needs append tool summary as part of a Sonex command, playback, auth, llm, or ui path.

    Example: append_tool_summary(context_id=..., tool=..., args=..., result=...) -> returns the value used by the surrounding Sonex flow.
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
    """Prepares build tool summary for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs build tool summary without duplicating the local rules.

    Example: _build_tool_summary(tool=..., args=..., result=...) -> returns the value used by the surrounding Sonex flow.
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
    """Prepares build summary for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs build summary without duplicating the local rules.

    Example: _build_summary(user_input=..., latest_answer=..., tool_names=..., error_text=...) -> returns the value used by the surrounding Sonex flow.
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
    """Prepares latest content for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs latest content without duplicating the local rules.

    Example: _latest_content(events=..., role=..., key=...) -> returns the value used by the surrounding Sonex flow.
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
    """Prepares tool names for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs tool names without duplicating the local rules.

    Example: _tool_names(events=...) -> returns the value used by the surrounding Sonex flow.
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
    """Prepares loads for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs loads without duplicating the local rules.

    Example: _loads(value=...) -> returns the value used by the surrounding Sonex flow.
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
    """Prepares loads list for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs loads list without duplicating the local rules.

    Example: _loads_list(value=...) -> returns the value used by the surrounding Sonex flow.
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
    """Prepares cache key for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs cache key without duplicating the local rules.

    Example: _cache_key(user_input=..., summary=...) -> returns the value used by the surrounding Sonex flow.
    """
    payload = f"{user_input.strip()}\n{summary.strip()}".encode("utf-8")
    return f"turn:{hashlib.sha256(payload).hexdigest()[:16]}"


def _clip(text: str, limit: int) -> str:
    """Prepares clip for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs clip without duplicating the local rules.

    Example: _clip(text=..., limit=...) -> returns the value used by the surrounding Sonex flow.
    """
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return f"{text[:limit].rstrip()}..."
