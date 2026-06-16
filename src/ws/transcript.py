"""Transcript coercion and persistence helpers for websocket sessions."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.log import sonex_home


def _coerce_transcript_messages(messages: Any) -> list[dict[str, str]]:
    """Prepares coerce transcript messages for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs coerce transcript messages without duplicating the local rules.

    Example: _coerce_transcript_messages(messages=...) -> returns the value used by the surrounding Sonex flow.
    """
    if not isinstance(messages, list):
        return []

    transcript: list[dict[str, str]] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "").strip()
        content = str(message.get("content") or message.get("text") or "").strip()
        if role not in {"user", "agent"} or not content:
            continue
        transcript.append({"role": role, "content": content})
    return transcript

def _save_session_transcript(
    messages: list[dict[str, str]],
    *,
    reason: str,
) -> Path:
    """Prepares save session transcript for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs save session transcript without duplicating the local rules.

    Example: _save_session_transcript(messages=..., reason=...) -> returns the value used by the surrounding Sonex flow.
    """
    now = datetime.now(timezone.utc)
    session_id = now.strftime("%Y%m%d%H%M%S%fZ")
    root = sonex_home() / "sessions" / session_id
    root.mkdir(parents=True, exist_ok=True)
    path = root / "transcript.jsonl"
    saved_at = now.isoformat()
    lines = [
        json.dumps(
            {
                "session_id": session_id,
                "saved_at": saved_at,
                "reason": reason,
                "index": index,
                "role": message["role"],
                "content": message["content"],
            },
            ensure_ascii=False,
            default=str,
        )
        for index, message in enumerate(messages)
    ]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return path
