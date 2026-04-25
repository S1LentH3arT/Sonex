import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_]+")


def _default_rag_path() -> Path:
    custom = os.getenv("SONEX_RAG_PATH")
    if custom:
        return Path(custom).expanduser()
    return Path.home() / ".local" / "share" / "sonex" / "rag.json"


def _tokenize(text: str) -> set[str]:
    return set(_TOKEN_PATTERN.findall(text.lower()))


class RAGIndex:
    def __init__(self, path: Path | None = None):
        self.path = path or _default_rag_path()

    def _ensure_parent(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"documents": []}

        with self.path.open("r", encoding="utf-8") as f:
            try:
                payload = json.load(f)
            except json.JSONDecodeError:
                return {"documents": []}

        documents = payload.get("documents")
        if not isinstance(documents, list):
            return {"documents": []}

        return {"documents": documents}

    def _save(self, payload: dict[str, Any]) -> None:
        self._ensure_parent()
        with self.path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=True)

    def ingest_text(self, text: str, source: str = "manual") -> dict[str, Any]:
        normalized = text.strip()
        if not normalized:
            raise ValueError("text must not be empty")

        payload = self._load()
        doc = {
            "id": uuid4().hex,
            "source": source,
            "text": normalized,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        payload["documents"].append(doc)
        self._save(payload)

        return {"id": doc["id"], "source": source, "chars": len(normalized)}

    def ingest_file(self, file_path: str, source: str | None = None) -> dict[str, Any]:
        path = Path(file_path).expanduser()
        text = path.read_text(encoding="utf-8")
        return self.ingest_text(text=text, source=source or str(path))

    def search(self, query: str, top_k: int = 3) -> list[dict[str, Any]]:
        if top_k <= 0:
            return []

        query_tokens = _tokenize(query)
        if not query_tokens:
            return []

        payload = self._load()
        scored: list[tuple[float, dict[str, Any]]] = []

        for document in payload["documents"]:
            if not isinstance(document, dict):
                continue

            text = str(document.get("text", ""))
            doc_tokens = _tokenize(text)
            if not doc_tokens:
                continue

            overlap = len(query_tokens & doc_tokens)
            if overlap == 0:
                continue

            score = overlap / len(query_tokens)
            snippet = text if len(text) <= 280 else text[:280] + "..."
            scored.append(
                (
                    score,
                    {
                        "id": document.get("id"),
                        "source": document.get("source"),
                        "score": round(score, 4),
                        "snippet": snippet,
                    },
                )
            )

        scored.sort(key=lambda item: item[0], reverse=True)
        return [item for _, item in scored[:top_k]]
