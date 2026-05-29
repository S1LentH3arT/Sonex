from __future__ import annotations

from typing import Any

from src.memory import memory_store
from src.tools.registry import Params, registry


def search_memory(query: str, target: str = "all", limit: int = 10) -> list[dict[str, Any]]:
    """Search long-term markdown memory indexed in the current SQLite session."""
    return memory_store.search_memory(query=query, target=target, limit=limit)


def search_context(query: str, target: str = "auto", limit: int = 10) -> list[dict[str, Any]]:
    """Search cache first, then full context as a fallback unless target is explicit."""
    table = target if target in {"auto", "cache", "context"} else "auto"
    return memory_store.search_context(query=query, table=table, limit=limit)


registry.register(
    name="search_memory",
    type="memory",
    description=(
        "Search long-term markdown memory. Use this when the preloaded memories "
        "are not enough and more stored project or user facts are needed."
    ),
    parameters=Params(
        type="object",
        properties={
            "query": {"type": "string", "description": "Keywords or phrase to search."},
            "target": {
                "type": "string",
                "description": "One of: memory, user, all.",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of matching memory entries to return.",
            },
        },
        required=["query"],
    ),
    fn=search_memory,
    enable=True,
    read_only=True,
    confirm_required=False,
)

registry.register(
    name="search_context",
    type="memory",
    description=(
        "Search reusable cache first, then full context if cache has no matches. "
        "Use target='context' or target='cache' to force a specific table."
    ),
    parameters=Params(
        type="object",
        properties={
            "query": {"type": "string", "description": "Keywords or phrase to search."},
            "target": {
                "type": "string",
                "description": "One of: auto, context, cache.",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of matching entries to return.",
            },
        },
        required=["query"],
    ),
    fn=search_context,
    enable=True,
    read_only=True,
    confirm_required=False,
)
