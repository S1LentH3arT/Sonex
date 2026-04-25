import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_]+")


def _default_memory_path() -> Path:
    custom = os.getenv("SONEX_MEMORY_PATH")
    if custom:
        return Path(custom).expanduser()
    return Path.home() / ".local" / "share" / "sonex" / "memory.jsonl"


def _tokenize(text: str) -> set[str]:
    return set(_TOKEN_PATTERN.findall(text.lower()))


class MemoryStore:
    def __init__(self, path: Path | None = None):
        self.path = path or _default_memory_path()

    def _ensure_parent(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, role: str, content: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        record = {
            "id": uuid4().hex,
            "ts": datetime.now(timezone.utc).isoformat(),
            "role": role,
            "content": content,
            "metadata": metadata or {},
        }
        self._ensure_parent()
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=True) + "\n")
        return record

    def all(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []

        records: list[dict[str, Any]] = []
        with self.path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    parsed = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(parsed, dict):
                    records.append(parsed)

        return records

    def recent(self, limit: int = 10) -> list[dict[str, Any]]:
        if limit <= 0:
            return []
        return self.all()[-limit:]

    def search(self, query: str, top_k: int = 3) -> list[dict[str, Any]]:
        if top_k <= 0:
            return []

        query_tokens = _tokenize(query)
        if not query_tokens:
            return []

        scored: list[tuple[float, dict[str, Any]]] = []
        for record in self.all():
            content = str(record.get("content", ""))
            content_tokens = _tokenize(content)
            if not content_tokens:
                continue

            overlap = len(query_tokens & content_tokens)
            if overlap == 0:
                continue

            score = overlap / len(query_tokens)
            scored.append(
                (
                    score,
                    {
                        "id": record.get("id"),
                        "ts": record.get("ts"),
                        "role": record.get("role"),
                        "content": content,
                        "score": round(score, 4),
                    },
                )
            )

        scored.sort(key=lambda item: item[0], reverse=True)
        return [item for _, item in scored[:top_k]]
