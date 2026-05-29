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
    parts = [f"User asked: {user_input.strip()}"]
    if tool_names:
        parts.append(f"Tools used: {', '.join(tool_names)}")
    if latest_answer:
        parts.append(f"Reusable outcome: {_clip(latest_answer, 500)}")
    if error_text:
        parts.append(f"Failure note: {_clip(error_text, 300)}")
    return " | ".join(parts)


def _latest_content(events: list[dict[str, Any]], role: str, key: str) -> str:
    for event in events:
        if event.get("type") != role:
            continue
        content = _loads(event.get("content"))
        value = content.get(key)
        if value:
            return str(value)
    return ""


def _tool_names(events: list[dict[str, Any]]) -> list[str]:
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
    payload = f"{user_input.strip()}\n{summary.strip()}".encode("utf-8")
    return f"turn:{hashlib.sha256(payload).hexdigest()[:16]}"


def _clip(text: str, limit: int) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return f"{text[:limit].rstrip()}..."
