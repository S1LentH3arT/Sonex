"""SQLite schema and search adapter for the local memory store."""

from __future__ import annotations

import sqlite3
from typing import Any


class MemorySqlite:
    """Keep SQLite schema/FTS details outside the memory domain facade."""

    def init_schema(self, conn: sqlite3.Connection) -> None:
        cursor = conn.cursor()
        cursor.executescript(
            """
            CREATE TABLE IF NOT EXISTS context(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT NOT NULL,
                content TEXT NOT NULL,
                tags TEXT NOT NULL,
                access_count INTEGER DEFAULT 0,
                last_accessed TIMESTAMP,
                promoted_cache_key TEXT,
                turn_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS cache(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT UNIQUE,
                summary TEXT NOT NULL,
                tags TEXT NOT NULL,
                importance REAL DEFAULT 0,
                source TEXT,
                source_context_id INTEGER,
                kind TEXT DEFAULT 'turn_summary',
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS memory_entries(
                entry_id TEXT PRIMARY KEY,
                target TEXT NOT NULL,
                content TEXT NOT NULL,
                source_path TEXT NOT NULL,
                line_no INTEGER NOT NULL,
                source TEXT DEFAULT 'legacy',
                confidence REAL DEFAULT 1.0,
                memory_updated_at TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS memory_candidates(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                turn_id TEXT NOT NULL UNIQUE,
                user_input TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS behavior_signals(
                signal_key TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                payload TEXT NOT NULL,
                count INTEGER NOT NULL DEFAULT 0,
                last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_memory_entries_target ON memory_entries(target);
            CREATE INDEX IF NOT EXISTS idx_context_access ON context(access_count, last_accessed);
            CREATE INDEX IF NOT EXISTS idx_cache_kind ON cache(kind);
            """
        )
        self._ensure_columns(cursor)
        self._ensure_fts(cursor)

    def _ensure_columns(self, cursor: sqlite3.Cursor) -> None:
        for table, column, ddl in (
            ("context", "access_count", "INTEGER DEFAULT 0"),
            ("context", "last_accessed", "TIMESTAMP"),
            ("context", "promoted_cache_key", "TEXT"),
            ("context", "turn_id", "TEXT"),
            ("cache", "source", "TEXT"),
            ("cache", "source_context_id", "INTEGER"),
            ("cache", "kind", "TEXT DEFAULT 'turn_summary'"),
            ("memory_entries", "source", "TEXT DEFAULT 'legacy'"),
            ("memory_entries", "confidence", "REAL DEFAULT 1.0"),
            ("memory_entries", "memory_updated_at", "TEXT"),
            ("memory_candidates", "attempts", "INTEGER NOT NULL DEFAULT 0"),
        ):
            self._ensure_column(cursor, table, column, ddl)

    @staticmethod
    def _ensure_column(cursor: sqlite3.Cursor, table: str, column: str, ddl: str) -> None:
        existing = {row[1] for row in cursor.execute(f"PRAGMA table_info({table})")}
        if column not in existing:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")

    @staticmethod
    def _ensure_fts(cursor: sqlite3.Cursor) -> None:
        try:
            cursor.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts
                USING fts5(entry_id UNINDEXED, target UNINDEXED, content)
                """
            )
        except sqlite3.OperationalError:
            pass

    @staticmethod
    def has_fts(conn: sqlite3.Connection) -> bool:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'memory_fts'"
        ).fetchone()
        return row is not None

    @staticmethod
    def search_fts(
        conn: sqlite3.Connection,
        target: str,
        limit: int,
        fts_query: str,
    ) -> list[sqlite3.Row]:
        target_clause = "" if target == "all" else "AND e.target = ?"
        params: list[Any] = [fts_query]
        if target != "all":
            params.append(target)
        params.append(limit)
        return conn.execute(
            f"""
            SELECT e.entry_id, e.target, e.content, e.source_path, e.line_no,
                   e.source, e.confidence, e.memory_updated_at, e.updated_at
            FROM memory_fts f
            JOIN memory_entries e ON e.entry_id = f.entry_id
            WHERE memory_fts MATCH ? {target_clause}
            ORDER BY bm25(memory_fts),
                     CASE WHEN e.source = 'explicit' THEN 0 ELSE 1 END,
                     e.confidence DESC, e.updated_at DESC
            LIMIT ?
            """,
            params,
        ).fetchall()

    @staticmethod
    def search_like(
        conn: sqlite3.Connection,
        query: str,
        target: str,
        limit: int,
    ) -> list[sqlite3.Row]:
        pattern = f"%{query}%"
        target_clause = "" if target == "all" else "AND target = ?"
        params: list[Any] = [pattern]
        if target != "all":
            params.append(target)
        params.append(limit)
        return conn.execute(
            f"""
            SELECT entry_id, target, content, source_path, line_no,
                   source, confidence, memory_updated_at, updated_at
            FROM memory_entries
            WHERE content LIKE ? {target_clause}
            ORDER BY CASE WHEN source = 'explicit' THEN 0 ELSE 1 END,
                     confidence DESC, updated_at DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
