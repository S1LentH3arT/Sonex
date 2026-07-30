"""Retriever support for local memory storage and retrieval.

Implements the retriever module responsibilities used by Sonex runtime flows.
Key public entry points include compile_query, retrieve_cache, retrieve_entries.
"""

from __future__ import annotations

import re
from typing import Any

from src.memory import memory_store


def compile_query(user_input: str) -> list[str]:
    """Compile user input into a stable keywordlist for rough retrieval."""
    text = user_input.strip().lower()
    tokens = re.findall(r"[a-zA-Z0-9_./-]+|[\u4e00-\u9fff]+", text)

    keys: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        if len(token) <= 1 or token in seen:
            continue
        seen.add(token)
        keys.append(token)
    return keys


def retrieve_cache(keys: list[str], limit: int = 10) -> list[dict[str, Any]]:
    """Coordinates retrieve cache for the current Sonex flow.

    Typical use: Use this function when runtime code needs retrieve cache as part of a Sonex command, playback, auth, llm, or ui path.

    Example: retrieve_cache(keys=..., limit=...) -> returns the value used by the surrounding Sonex flow.
    """
    query = " ".join(keys).strip()
    return memory_store.search_context(query, table="cache", limit=limit)


def retrieve_entries(keys: list[str], target: str, limit: int = 10) -> list[dict[str, Any]]:
    """Coordinates retrieve entries for the current Sonex flow.

    Typical use: Use this function when runtime code needs retrieve entries as part of a Sonex command, playback, auth, llm, or ui path.

    Example: retrieve_entries(keys=..., target=..., limit=...) -> returns the value used by the surrounding Sonex flow.
    """
    query = " ".join(keys).strip()
    if target not in {"memory", "user", "all"}:
        target = "all"
    return memory_store.search_memory(query, target=target, limit=limit)
