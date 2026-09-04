"""Persistence helpers for Modify operation idempotency records."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


MAX_IDEMPOTENCY_RESULTS = 256


def operation_fingerprint(operations: list[dict[str, Any]]) -> str:
    payload = json.dumps(
        operations,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_idempotency_entries(path: Path) -> dict[str, dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}
    entries = payload.get("entries") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        return {}
    return {
        str(entry.get("key")): dict(entry)
        for entry in entries
        if isinstance(entry, dict)
        and str(entry.get("key") or "")
        and isinstance(entry.get("result"), dict)
    }


def record_idempotency_entry(
    path: Path,
    *,
    key: str,
    fingerprint: str,
    result: dict[str, Any],
    completed_at: float,
) -> dict[str, Any]:
    entries = load_idempotency_entries(path)
    entry = {
        "key": key,
        "fingerprint": fingerprint,
        "result": result,
        "completed_at": completed_at,
    }
    entries[key] = entry
    ordered = sorted(
        entries.values(),
        key=lambda item: float(item.get("completed_at") or 0),
        reverse=True,
    )[:MAX_IDEMPOTENCY_RESULTS]
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps({"version": 1, "entries": ordered}, ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
    return entry
