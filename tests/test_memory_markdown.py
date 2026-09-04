"""Tests for the isolated Markdown memory codec."""

from __future__ import annotations

from types import SimpleNamespace

from src.memory.markdown import normalize_content, parse_markdown, render_markdown


def test_parse_markdown_keeps_bullets_and_indented_continuations(tmp_path) -> None:
    path = tmp_path / "MEMORY.md"
    path.write_text(
        "# Agent memory\n\n"
        "- first line\n"
        "  second line\n"
        "  <!-- sonex:id=entry-1 source=explicit confidence=0.5 -->\n"
        "top-level prose\n"
        "* second\n",
        encoding="utf-8",
    )

    entries = parse_markdown(
        "memory",
        path,
        lambda target, lines, line_no, metadata, now, source_path: {
            "target": target,
            "lines": lines,
            "line_no": line_no,
            "metadata": metadata,
            "now": now,
            "source_path": source_path,
        },
    )

    assert [entry["lines"] for entry in entries] == [["first line", "second line"], ["second"]]
    assert entries[0]["metadata"] == {"id": "entry-1", "source": "explicit", "confidence": "0.5"}
    assert entries[0]["line_no"] == 3


def test_render_markdown_and_normalize_content() -> None:
    entries = [SimpleNamespace(content="first\nsecond")]

    assert render_markdown("user", entries) == "# User memory\n\n- first\n  second\n"
    assert normalize_content("\r\n e\u0301  \r\n") == " é"
