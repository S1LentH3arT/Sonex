"""Bounded post-turn long-term memory curation for Sonex."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Literal

from src.llm.transport import ChatRequest
from src.thinking.config import ThinkingConfig

from .memory import MemoryStore, memory_store


MemoryOperationKind = Literal["add", "update", "remove", "noop"]


@dataclass(frozen=True, slots=True)
class MemoryOperation:
    operation: MemoryOperationKind
    target: Literal["user", "memory"]
    content: str
    source: str = "explicit"
    confidence: float = 1.0
    previous_content: str | None = None


@dataclass(frozen=True, slots=True)
class TurnEnvelope:
    turn_id: str
    user_input: str
    events: tuple[dict[str, Any], ...]

    @classmethod
    def capture(cls, user_input: str, store: MemoryStore) -> "TurnEnvelope":
        events = tuple(store.events_for_turn())
        turn_id = str(events[0].get("turn_id") or "") if events else ""
        return cls(turn_id=turn_id, user_input=user_input, events=events)


_EXPLICIT_SAVE = re.compile(
    r"^(?:请)?(?:记住|记一下|remember(?: that)?)[：:\s]*(.+)$",
    re.IGNORECASE,
)
_EXPLICIT_REMOVE = re.compile(
    r"^(?:请)?(?:忘掉|忘记|不要记住|forget(?: that)?)[：:\s]*(.+)$",
    re.IGNORECASE,
)
_PREFERENCE_SIGNAL = re.compile(
    r"(?:喜欢|偏好|常听|不喜欢|讨厌|prefer|like|love|dislike|hate)",
    re.IGNORECASE,
)
_SECRET = re.compile(
    r"(?:api[_-]?key|access[_-]?token|refresh[_-]?token|authorization|bearer|cookie|password)\s*[:=]",
    re.IGNORECASE,
)


def explicit_memory_operation(user_input: str) -> MemoryOperation | None:
    """Recognize an explicit save/remove request without another model call."""
    text = " ".join(str(user_input or "").split())
    remove = _EXPLICIT_REMOVE.match(text)
    if remove:
        return MemoryOperation("remove", "user", remove.group(1).strip())
    save = _EXPLICIT_SAVE.match(text)
    if save:
        return MemoryOperation("add", "user", save.group(1).strip())
    return None


def curate_completed_turn(
    user_input: str,
    *,
    store: MemoryStore = memory_store,
) -> list[MemoryOperation]:
    """Extract and apply safe long-term memory operations for one completed turn."""
    if not store.long_term_enabled():
        return []
    if not store.memory_candidate_allowed():
        store.mark_memory_candidate("retained_pre_reset")
        return []
    envelope = TurnEnvelope.capture(user_input, store)
    explicit = explicit_memory_operation(user_input)
    if explicit is not None and explicit.operation == "add" and safe_memory_content(explicit.content):
        explicit = MemoryOperation(
            explicit.operation,
            _classify_explicit_target(explicit.content),
            explicit.content,
            source=explicit.source,
            confidence=explicit.confidence,
        )
    operations = [explicit] if explicit is not None else _implicit_operations(envelope, store)
    applied: list[MemoryOperation] = []
    for operation in operations:
        if operation is None or operation.operation == "noop":
            continue
        if not safe_memory_content(operation.content):
            continue
        if operation.operation == "remove":
            result = store.remove(operation.target, operation.content)
        elif operation.operation == "update":
            previous = str(operation.previous_content or "").strip()
            protected = next(
                (entry for entry in store.entries(operation.target) if entry.content == previous and entry.protected),
                None,
            )
            if protected is not None:
                result = store.propose_update(
                    protected.entry_id,
                    operation.content,
                    "The Memory Curator found related information that requires user review.",
                )
            else:
                result = store.update(
                    operation.target,
                    operation.content,
                    previous_content=operation.previous_content,
                    source=operation.source,
                    confidence=operation.confidence,
                )
        else:
            result = store.add(
                operation.target,
                operation.content,
                source=operation.source,
                confidence=operation.confidence,
            )
        if (
            operation.operation == "add"
            and not result.get("success")
            and result.get("error") == "Memory entry already exists."
        ):
            operation = MemoryOperation(
                "noop",
                operation.target,
                operation.content,
                source=operation.source,
                confidence=operation.confidence,
            )
            result = {"success": True}
        if result.get("success"):
            applied.append(operation)
    store.mark_memory_candidate("processed" if applied else "noop")
    return applied


def memory_operation_message(operation: MemoryOperation) -> str:
    verb = {
        "add": "saved",
        "update": "updated",
        "remove": "removed",
        "noop": "already exists",
    }.get(operation.operation, "updated")
    if operation.operation == "noop":
        return f"Memory already exists: {operation.content}"
    return f"Memory {verb}: {operation.content}"


def _implicit_operations(envelope: TurnEnvelope, store: MemoryStore) -> list[MemoryOperation]:
    tool_names = _tool_names(envelope.events)
    behavior_signals = store.promotable_behavior_signals()
    repeated_tool = any(
        len(store.search_context(tool, table="context", limit=20)) >= 2
        for tool in tool_names
    )
    if not _PREFERENCE_SIGNAL.search(envelope.user_input) and not repeated_tool and not behavior_signals:
        return []
    settings = store.settings()
    if not settings["automatic_refinement"]:
        return []
    existing_user = [
        store._entry_to_dict(entry)
        for entry in _relevant_entries(
            store.entries("user"),
            envelope.user_input,
            int(settings["user_refinement_window"]),
        )
    ]
    existing_agent = [
        store._entry_to_dict(entry)
        for entry in _relevant_entries(
            store.entries("memory"),
            envelope.user_input,
            int(settings["memory_refinement_window"]),
        )
    ]
    request = ChatRequest(
        model=ThinkingConfig.get_model(),
        messages=[
            {
                "role": "system",
                "content": (
                    "You are Sonex Memory Curator. Extract at most one durable item. Use target "
                    "user only for a stable music preference supported by the user's words. "
                    "Use target memory only for a reusable Music Agent workflow supported by "
                    "repeated tool evidence. Never store secrets, identity inferences, transient "
                    "requests, raw history, or one-off tool results. Call record_memory once with "
                    "operation add, update, or noop. Keep content concise and in the user's language."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "turn": {
                            "turn_id": envelope.turn_id,
                            "user_input": envelope.user_input,
                            "events": _bounded_events(envelope.events),
                        },
                        "existing_user_memory": existing_user,
                        "existing_agent_memory": existing_agent,
                        "repeated_music_behavior": behavior_signals,
                    },
                    ensure_ascii=False,
                    default=str,
                ),
            },
        ],
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "record_memory",
                    "description": "Return one bounded long-term memory decision.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "operation": {"type": "string", "enum": ["add", "update", "noop"]},
                            "target": {"type": "string", "enum": ["user", "memory"]},
                            "content": {"type": "string"},
                            "previous_content": {"type": "string"},
                            "confidence": {"type": "number"},
                        },
                        "required": ["operation", "target", "content"],
                    },
                },
            }
        ],
        tool_choice={"type": "function", "function": {"name": "record_memory"}},
        max_tokens=240,
        temperature=0,
    )
    response = ThinkingConfig.get_client().generate(request)
    if not response.tool_calls:
        return []
    payload = response.tool_calls[0].arguments
    operation = str(payload.get("operation") or "noop").casefold()
    if operation not in {"add", "update", "noop"}:
        return []
    content = " ".join(str(payload.get("content") or "").split())
    target = str(payload.get("target") or "user").casefold()
    if target not in {"user", "memory"}:
        return []
    if target == "memory" and not repeated_tool:
        return []
    previous_content = " ".join(str(payload.get("previous_content") or "").split()) or None
    confidence = payload.get("confidence", 0.8)
    try:
        bounded_confidence = max(0.0, min(float(confidence), 1.0))
    except (TypeError, ValueError):
        bounded_confidence = 0.8
    return [
        MemoryOperation(
            operation,
            target,
            content,
            source=(
                "experience"
                if target == "memory"
                else "inferred"
            ),
            confidence=bounded_confidence,
            previous_content=previous_content,
        )
    ]


def safe_memory_content(content: str) -> bool:
    text = " ".join(str(content or "").split())
    return bool(text) and len(text) <= 500 and _SECRET.search(text) is None


def _classify_explicit_target(content: str) -> Literal["user", "memory"]:
    """Let the active model classify placement without rewriting explicit text."""
    request = ChatRequest(
        model=ThinkingConfig.get_model(),
        messages=[
            {
                "role": "system",
                "content": (
                    "Classify one user-authored memory. Choose user for facts or preferences "
                    "about the user. Choose memory for reusable Sonex Agent workflows. Do not "
                    "rewrite, summarize, or evaluate the content. Call classify_memory once."
                ),
            },
            {"role": "user", "content": content},
        ],
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "classify_memory",
                    "description": "Choose the storage target for unchanged explicit memory.",
                    "parameters": {
                        "type": "object",
                        "properties": {"target": {"type": "string", "enum": ["user", "memory"]}},
                        "required": ["target"],
                    },
                },
            }
        ],
        tool_choice={"type": "function", "function": {"name": "classify_memory"}},
        max_tokens=32,
        temperature=0,
    )
    try:
        response = ThinkingConfig.get_client().generate(request)
        target = str(response.tool_calls[0].arguments.get("target") or "user").casefold()
    except Exception:
        return "user"
    return "memory" if target == "memory" else "user"


def _relevant_entries(entries: list[Any], query: str, limit: int) -> list[Any]:
    """Select a finite runtime-entry window by lexical relevance and recency."""
    terms = {
        term.casefold()
        for term in re.findall(r"[\w\u4e00-\u9fff]+", str(query or ""))
        if len(term) > 1
    }
    ranked = sorted(
        enumerate(entries),
        key=lambda item: (
            sum(term in item[1].content.casefold() for term in terms),
            item[1].recall_count,
            item[1].updated_at or "",
            item[0],
        ),
        reverse=True,
    )
    return [entry for _index, entry in ranked[:max(1, limit)]]


def _tool_names(events: tuple[dict[str, Any], ...]) -> list[str]:
    names: list[str] = []
    for event in events:
        if event.get("type") != "tool":
            continue
        try:
            payload = json.loads(str(event.get("content") or "{}"))
        except json.JSONDecodeError:
            continue
        name = str(payload.get("tool") or "").strip()
        if name:
            names.append(name)
    return list(dict.fromkeys(names))


def _bounded_events(events: tuple[dict[str, Any], ...]) -> list[dict[str, Any]]:
    bounded: list[dict[str, Any]] = []
    for event in events[-12:]:
        raw_content = event.get("content")
        try:
            parsed_content = json.loads(str(raw_content or "{}"))
        except json.JSONDecodeError:
            parsed_content = str(raw_content or "")
        content = json.dumps(
            _redact_sensitive_values(parsed_content),
            ensure_ascii=False,
            default=str,
        )
        bounded.append(
            {
                "type": str(event.get("type") or ""),
                "content": content[:1000],
                "tags": event.get("tags"),
            }
        )
    return bounded


def _redact_sensitive_values(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            normalized = str(key).casefold().replace("-", "_")
            if any(secret in normalized for secret in ("token", "api_key", "authorization", "cookie", "password")):
                redacted[str(key)] = "[redacted]"
            else:
                redacted[str(key)] = _redact_sensitive_values(item)
        return redacted
    if isinstance(value, list):
        return [_redact_sensitive_values(item) for item in value[:20]]
    return value
