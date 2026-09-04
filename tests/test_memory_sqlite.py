"""Tests for the SQLite schema/search adapter."""

from __future__ import annotations

import sqlite3

from src.memory.sqlite_store import MemorySqlite


def test_schema_is_created_and_like_search_is_ordered() -> None:
    adapter = MemorySqlite()
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    adapter.init_schema(conn)
    conn.execute(
        "INSERT INTO memory_entries(entry_id, target, content, source_path, line_no, source, confidence) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("a", "user", "Prefers jazz", "USER.md", 1, "explicit", 1.0),
    )
    rows = adapter.search_like(conn, "jazz", "all", 5)
    assert [row["entry_id"] for row in rows] == ["a"]
    assert adapter.has_fts(conn)


def test_fts_search_uses_target_filter() -> None:
    adapter = MemorySqlite()
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    adapter.init_schema(conn)
    conn.executemany(
        "INSERT INTO memory_entries(entry_id, target, content, source_path, line_no) VALUES (?, ?, ?, ?, ?)",
        [("a", "user", "jazz", "USER.md", 1), ("b", "memory", "jazz", "MEMORY.md", 1)],
    )
    conn.executemany(
        "INSERT INTO memory_fts(entry_id, target, content) VALUES (?, ?, ?)",
        [("a", "user", "jazz"), ("b", "memory", "jazz")],
    )
    rows = adapter.search_fts(conn, "memory", 5, "jazz")
    assert [row["entry_id"] for row in rows] == ["b"]
