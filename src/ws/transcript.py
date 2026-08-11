"""Transcript coercion and persistence helpers for websocket sessions."""

from __future__ import annotations

import json
import re
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
        document = _coerce_chat_document(message.get("document"))
        if document:
            item["document"] = document
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


def _coerce_chat_document(value: Any) -> dict[str, Any] | None:
    """Keep only the bounded semantic document produced by the server normalizer."""
    if not isinstance(value, dict) or value.get("version") != 1:
        return None
    raw_blocks = value.get("blocks")
    if not isinstance(raw_blocks, list) or len(raw_blocks) > 100:
        return None
    allowed_blocks = {"paragraph", "heading", "list_item", "code_block", "spacer"}
    allowed_styles = {"plain", "strong", "highlight", "link"}
    blocks: list[dict[str, Any]] = []
    for raw_block in raw_blocks:
        if not isinstance(raw_block, dict) or raw_block.get("type") not in allowed_blocks:
            return None
        block_type = str(raw_block["type"])
        block: dict[str, Any] = {"type": block_type}
        if block_type == "code_block":
            block["text"] = str(raw_block.get("text") or "")[:12000]
            if raw_block.get("language"):
                block["language"] = str(raw_block["language"])[:40]
        elif block_type != "spacer":
            spans = raw_block.get("spans")
            if not isinstance(spans, list):
                return None
            safe_spans: list[dict[str, str]] = []
            for span in spans:
                if not isinstance(span, dict) or span.get("style") not in allowed_styles:
                    return None
                safe_span = {
                    "text": str(span.get("text") or ""),
                    "style": str(span["style"]),
                }
                href = str(span.get("href") or "")
                if span.get("style") == "link" and href.startswith(("https://", "http://")):
                    safe_span["href"] = href
                safe_spans.append(safe_span)
            block["spans"] = safe_spans
            if block_type == "list_item":
                marker = str(raw_block.get("marker") or "-")
                block["marker"] = marker if marker == "-" or re.fullmatch(r"\d+\.", marker) else "-"
                block["level"] = max(0, min(int(raw_block.get("level") or 0), 2))
        blocks.append(block)
    return {"version": 1, "blocks": blocks}


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
        for key in ("theme", "tone", "segments", "document"):
            if key in message:
                payload[key] = message[key]
        lines.append(json.dumps(payload, ensure_ascii=False, default=str))
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return path
