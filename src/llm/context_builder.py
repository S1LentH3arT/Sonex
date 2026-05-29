from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from src.memory import memory_store

DEFAULT_PLANNING_TOKEN_BUDGET = 6000
MAX_PLANNING_TOKEN_BUDGET = 10000

_EVENT_WEIGHTS = {
    "error": 5,
    "tool": 4,
    "user": 3,
    "agent": 2,
    "warn": 2,
}


@dataclass(slots=True)
class PlanningContextBuilder:
    token_budget: int = DEFAULT_PLANNING_TOKEN_BUDGET

    def build(self, user_input: str) -> str:
        budget = max(500, min(int(self.token_budget), MAX_PLANNING_TOKEN_BUDGET))
        payload = {
            "purpose": (
                "This is a compact model-only planning buffer, not the complete "
                "user-visible conversation history."
            ),
            "current_input": user_input,
            "relevant_user_memory": _trim_items(
                memory_store.search_memory(user_input, target="user", limit=4),
                max_text=600,
            ),
            "relevant_project_memory": _trim_items(
                memory_store.search_memory(user_input, target="memory", limit=6),
                max_text=700,
            ),
            "relevant_cache": _trim_items(
                memory_store.search_context(user_input, table="cache", limit=6),
                max_text=700,
            ),
            "recent_buffer": _trim_items(
                _select_recent_events(memory_store.search_context("", table="context", limit=18)),
                max_text=650,
            ),
            "retrieval_policy": (
                "If necessary facts are missing, call search_memory or search_context. "
                "search_context defaults to cache-first and falls back to full context."
            ),
        }
        return _fit_budget(payload, budget)


def build_planning_context(user_input: str, token_budget: int = DEFAULT_PLANNING_TOKEN_BUDGET) -> str:
    return PlanningContextBuilder(token_budget=token_budget).build(user_input)


def estimate_tokens(text: str) -> int:
    # Lightweight approximation: English averages ~4 chars/token; CJK is denser.
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    non_cjk = max(0, len(text) - cjk)
    return max(1, (non_cjk // 4) + cjk + 1)


def _select_recent_events(events: list[dict[str, Any]], limit: int = 8) -> list[dict[str, Any]]:
    def score(item: dict[str, Any]) -> tuple[int, int, int]:
        event_type = str(item.get("type") or "")
        access_count = int(item.get("access_count") or 0)
        item_id = int(item.get("id") or 0)
        return (_EVENT_WEIGHTS.get(event_type, 1), access_count, item_id)

    selected = sorted(events, key=score, reverse=True)[:limit]
    return sorted(selected, key=lambda item: int(item.get("id") or 0))


def _trim_items(items: list[dict[str, Any]], max_text: int) -> list[dict[str, Any]]:
    trimmed: list[dict[str, Any]] = []
    for item in items:
        next_item = dict(item)
        for key in ("content", "summary"):
            value = next_item.get(key)
            if isinstance(value, str):
                next_item[key] = _clip(value, max_text)
        trimmed.append(next_item)
    return trimmed


def _fit_budget(payload: dict[str, Any], budget: int) -> str:
    fitted = dict(payload)
    section_order = [
        "recent_buffer",
        "relevant_cache",
        "relevant_project_memory",
        "relevant_user_memory",
    ]

    text = _dump(fitted)
    while estimate_tokens(text) > budget:
        changed = False
        for section in section_order:
            items = fitted.get(section)
            if isinstance(items, list) and items:
                items.pop()
                changed = True
                break
        if not changed:
            break
        text = _dump(fitted)
    return text


def _dump(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str, indent=2)


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return f"{text[:limit].rstrip()}..."
