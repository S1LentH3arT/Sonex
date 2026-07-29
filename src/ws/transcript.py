"""Transcript coercion and persistence helpers for websocket sessions."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.log import sonex_home


def create_session_id(now: datetime | None = None) -> str:
    """Return the canonical UTC timestamp identifier for a chat session."""
    timestamp = now or datetime.now(timezone.utc)
    return timestamp.astimezone(timezone.utc).strftime("%Y%m%d%H%M%S%fZ")


def _coerce_transcript_messages(messages: Any) -> list[dict[str, Any]]:
    """Prepares coerce transcript messages for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs coerce transcript messages without duplicating the local rules.

    Example: _coerce_transcript_messages(messages=...) -> returns the value used by the surrounding Sonex flow.
    """
    if not isinstance(messages, list):
        return []

    transcript: list[dict[str, Any]] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "").strip()
        content = str(message.get("content") or message.get("text") or "").strip()
        if role not in {"user", "agent"} or not content:
            continue
        item: dict[str, Any] = {"role": role, "content": content}
        theme = message.get("theme")
        if theme in {"spotify", "muted"}:
            item["theme"] = theme
        tone = message.get("tone")
        if tone in {"system", "warning", "error"}:
            item["tone"] = tone
        segments = _coerce_chat_segments(message.get("segments"))
        if segments:
            item["segments"] = segments
        transcript.append(item)
    return transcript


def _coerce_chat_segments(value: Any) -> list[dict[str, str]]:
    """Keep only supported semantic rich-text spans from an untrusted client."""
    if not isinstance(value, list):
        return []
    segments: list[dict[str, str]] = []
    for segment in value:
        if not isinstance(segment, dict):
            return []
        text = str(segment.get("text") or "")
        style = str(segment.get("style") or "")
        if not text or style not in {"tool_name", "tool_value"}:
            return []
        segments.append({"text": text, "style": style})
    return segments


def _save_session_transcript(
    messages: list[dict[str, Any]],
    *,
    reason: str,
    session_id: str,
) -> Path:
    """Prepares save session transcript for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs save session transcript without duplicating the local rules.

    Example: _save_session_transcript(messages=..., reason=...) -> returns the value used by the surrounding Sonex flow.
    """
    now = datetime.now(timezone.utc)
    root = sonex_home() / "sessions" / session_id
    root.mkdir(parents=True, exist_ok=True)
    path = root / "transcript.jsonl"
    saved_at = now.isoformat()
    lines: list[str] = []
    for index, message in enumerate(messages):
        payload: dict[str, Any] = {
            "session_id": session_id,
            "saved_at": saved_at,
            "reason": reason,
            "index": index,
            "role": message["role"],
            "content": message["content"],
        }
        for key in ("theme", "tone", "segments"):
            if key in message:
                payload[key] = message[key]
        lines.append(json.dumps(payload, ensure_ascii=False, default=str))
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return path
