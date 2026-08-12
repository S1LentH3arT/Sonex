"""Safe semantic normalization for user-visible LLM answers."""

from __future__ import annotations

import re
from typing import Any


CHAT_DOCUMENT_VERSION = 1
_ACTION_SUCCESS = re.compile(
    r"(?:已(?:开始)?播放|已添加|已连接|已修改|播放已开始|"
    r"(?:started|now) playing|added (?:it|the track)|connected successfully|playlist (?:was )?updated)",
    re.IGNORECASE,
)


def normalize_agent_answer(markdown: str) -> tuple[str, dict[str, Any]]:
    """Parse the supported Markdown subset into a provider-neutral ChatDocument."""
    source = str(markdown or "").replace("\r\n", "\n").replace("\r", "\n")
    blocks: list[dict[str, Any]] = []
    code_lines: list[str] | None = None
    code_language = ""

    for raw_line in source.split("\n"):
        fence = re.match(r"^\s*```([^`]*)$", raw_line)
        if fence:
            if code_lines is None:
                code_lines = []
                code_language = fence.group(1).strip()
            else:
                blocks.append(
                    {
                        "type": "code_block",
                        "text": "\n".join(code_lines),
                        **({"language": code_language} if code_language else {}),
                    }
                )
                code_lines = None
                code_language = ""
            continue
        if code_lines is not None:
            code_lines.append(raw_line)
            continue

        if not raw_line.strip():
            if blocks and blocks[-1].get("type") != "spacer":
                blocks.append({"type": "spacer"})
            continue

        heading = re.match(r"^\s{0,3}#{1,3}\s+(.+?)\s*$", raw_line)
        if heading:
            blocks.append({"type": "heading", "spans": _inline_spans(heading.group(1))})
            continue
        unordered = re.match(r"^\s{0,6}[-*+]\s+(.+)$", raw_line)
        if unordered:
            indent = min(2, len(raw_line) - len(raw_line.lstrip(" "))) // 2
            blocks.append(
                {
                    "type": "list_item",
                    "marker": "-",
                    "level": indent,
                    "spans": _inline_spans(unordered.group(1)),
                }
            )
            continue
        ordered = re.match(r"^\s{0,6}(\d+)[.)]\s+(.+)$", raw_line)
        if ordered:
            indent = min(2, len(raw_line) - len(raw_line.lstrip(" "))) // 2
            blocks.append(
                {
                    "type": "list_item",
                    "marker": f"{ordered.group(1)}.",
                    "level": indent,
                    "spans": _inline_spans(ordered.group(2)),
                }
            )
            continue
        blocks.append({"type": "paragraph", "spans": _inline_spans(raw_line.strip())})

    if code_lines is not None:
        # An unterminated fence is content, not a terminal control instruction.
        blocks.append({"type": "code_block", "text": "\n".join(code_lines)})

    while blocks and blocks[-1].get("type") == "spacer":
        blocks.pop()
    plain = _plain_text(blocks)
    return plain, {"version": CHAT_DOCUMENT_VERSION, "blocks": blocks}


def guard_agent_answer(content: str, tool_results: list[Any]) -> str:
    """Block ungrounded claims that a state-changing music action completed."""
    recommendation_tracks = _recommendation_tracks(tool_results)
    if recommendation_tracks and not _recommendation_lines_are_grounded(content, recommendation_tracks):
        return _safe_recommendation_answer(recommendation_tracks, content)
    if not _ACTION_SUCCESS.search(content):
        return content
    if any(_successful_tool_result(result) for result in tool_results):
        return content
    if re.search(r"[\u4e00-\u9fff]", content):
        return "我无法确认请求的音乐操作已经完成。"
    return "I could not verify that the requested music action completed."


def _inline_spans(text: str) -> list[dict[str, str]]:
    spans: list[dict[str, str]] = []
    pattern = re.compile(r"(\*\*.+?\*\*|`[^`]+`|\[[^\]]+\]\([^\s)]+\))")
    cursor = 0
    for match in pattern.finditer(text):
        if match.start() > cursor:
            spans.append({"text": text[cursor : match.start()], "style": "plain"})
        token = match.group(0)
        if token.startswith("**"):
            spans.append({"text": token[2:-2], "style": "strong"})
        elif token.startswith("`"):
            spans.append({"text": token[1:-1], "style": "highlight"})
        else:
            label, url = re.match(r"\[([^\]]+)\]\(([^)]+)\)", token).groups()  # type: ignore[union-attr]
            if re.match(r"^https?://", url, re.IGNORECASE):
                spans.append({"text": label, "style": "link", "href": url})
            else:
                spans.append({"text": label, "style": "plain"})
        cursor = match.end()
    if cursor < len(text):
        spans.append({"text": text[cursor:], "style": "plain"})
    return spans or [{"text": "", "style": "plain"}]


def _plain_text(blocks: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for block in blocks:
        kind = block.get("type")
        if kind == "spacer":
            if lines and lines[-1] != "":
                lines.append("")
            continue
        if kind == "code_block":
            lines.extend(str(block.get("text") or "").split("\n"))
            continue
        text = "".join(str(span.get("text") or "") for span in block.get("spans") or [])
        if kind == "list_item":
            level = max(0, min(int(block.get("level") or 0), 2))
            text = f"{'  ' * level}{block.get('marker') or '-'} {text}"
        lines.append(text)
    return "\n".join(lines).strip()


def _successful_tool_result(result: Any) -> bool:
    if not isinstance(result, dict):
        return False
    return str(result.get("status") or "").casefold() in {
        "success",
        "ok",
        "playback_completed",
        "connected",
    }


def _recommendation_tracks(tool_results: list[Any]) -> list[dict[str, Any]]:
    for result in tool_results:
        if not isinstance(result, dict) or str(result.get("tool") or "").casefold() != "recommend":
            continue
        if not _successful_tool_result(result):
            continue
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        return [item for item in data.get("tracks", []) if isinstance(item, dict)]
    return []


def _recommendation_lines_are_grounded(content: str, tracks: list[dict[str, Any]]) -> bool:
    names = [
        str(track.get("name") or track.get("title") or "").strip().casefold()
        for track in tracks
    ]
    names = [name for name in names if name]
    list_lines = [
        line
        for line in content.splitlines()
        if re.match(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)", line)
    ]
    if not list_lines:
        return False
    return all(any(name in line.casefold() for name in names) for line in list_lines)


def _safe_recommendation_answer(tracks: list[dict[str, Any]], original: str) -> str:
    chinese = bool(re.search(r"[\u4e00-\u9fff]", original))
    title = "## 推荐" if chinese else "## Recommendations"
    question = "想听哪一首？" if chinese else "Which one would you like to hear?"
    lines = [title, ""]
    for track in tracks[:10]:
        name = str(track.get("name") or track.get("title") or "Unknown track").strip()
        artist = str(track.get("artist") or "").strip()
        if not artist and isinstance(track.get("artists"), list):
            artist = ", ".join(str(item) for item in track["artists"] if item)
        suffix = f" — `{artist}`" if artist else ""
        lines.append(f"- **{name}**{suffix}")
    lines.extend(("", question))
    return "\n".join(lines)
