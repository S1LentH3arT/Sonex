"""Markdown codec used by the local memory store."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def normalize_content(content: str) -> str:
    lines = unicodedata.normalize("NFC", str(content).replace("\r\n", "\n")).split("\n")
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(line.rstrip() for line in lines)


def parse_metadata(line: str) -> dict[str, str]:
    match = re.fullmatch(r"<!--\s*sonex:(.*?)\s*-->", line)
    if match is None:
        return {}
    return {
        key: value
        for key, value in re.findall(r"([a-z_]+)=([^\s]+)", match.group(1))
    }


EntryFactory = Callable[[str, list[str], int, dict[str, str], str, Path], Any]


def parse_markdown(
    target: str,
    path: Path,
    entry_factory: EntryFactory,
) -> list[Any]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").replace("\r\n", "\n").split("\n")
    entries: list[Any] = []
    current: list[str] | None = None
    current_line = 0
    metadata: dict[str, str] = {}
    now = datetime.now(timezone.utc).isoformat()
    for line_no, raw in enumerate(lines, 1):
        stripped = raw.strip()
        if re.match(r"^\s*[-*+]\s+", raw):
            if current is not None:
                entries.append(entry_factory(target, current, current_line, metadata, now, path))
            current = [re.sub(r"^\s*[-*+]\s+", "", raw).rstrip()]
            current_line = line_no
            metadata = {}
        elif current is not None and re.fullmatch(r"\s*<!--\s*sonex:.*?-->\s*", raw):
            metadata = parse_metadata(stripped)
        elif current is not None and (raw.startswith("  ") or raw.startswith("\t")):
            current.append(raw[2:].rstrip() if raw.startswith("  ") else raw[1:].rstrip())
        elif not stripped or stripped.startswith("#") or stripped.startswith("<!--"):
            continue
        elif current is not None:
            # Top-level prose is intentionally ignored; only indented lines
            # belong to the preceding list entry.
            continue
    if current is not None:
        entries.append(entry_factory(target, current, current_line, metadata, now, path))
    return entries


def render_markdown(target: str, entries: Iterable[Any]) -> str:
    title = "User memory" if target == "user" else "Agent memory"
    lines = [f"# {title}", ""]
    for entry in entries:
        content_lines = str(entry.content).split("\n")
        lines.append(f"- {content_lines[0]}")
        lines.extend(f"  {line}" for line in content_lines[1:])
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
