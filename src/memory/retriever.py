from __future__ import annotations

import re
from typing import Any

from src.memory import memory_store


def compile_query(user_input: str) -> list[str]:
    """Compile user input into a stable keyword list for rough retrieval."""
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
    query = " ".join(keys).strip()
    return memory_store.search_context(query, table="cache", limit=limit)


def retrieve_entries(keys: list[str], target: str, limit: int = 10) -> list[dict[str, Any]]:
    query = " ".join(keys).strip()
    if target not in {"memory", "user", "all"}:
        target = "all"
    return memory_store.search_memory(query, target=target, limit=limit)
