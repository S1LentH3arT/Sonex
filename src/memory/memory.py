"""Memory support for local memory storage and retrieval.

Implements the memory module responsibilities used by Sonex runtime flows.
Key public entry points include MemoryPaths, MemoryEntry, MemoryStore.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from src.log import sonex_home


MemoryTarget = Literal["memory", "user"]
SearchTarget = Literal["memory", "user", "all"]
ContextTable = Literal["context", "cache"]
SearchContextTable = Literal["auto", "context", "cache"]

SUPPORTED_CONTEXT_QUERY_PARAMS = {"id", "type", "content", "tags"}
SUPPORTED_CACHE_QUERY_PARAMS = {"id", "key", "summary", "tags"}
SUPPORTED_CONTEXT_TABLES = {"auto", "context", "cache"}
SUPPORTED_MEMORY_TARGETS = {"memory", "user", "all"}


@dataclass(frozen=True)
class MemoryPaths:
    """Represents memory paths.

    Encapsulates memory paths data and behavior used by Sonex runtime flows.
    """
    memory: Path
    user: Path


@dataclass(frozen=True)
class MemoryEntry:
    """Represents memory entry.

    Encapsulates memory entry data and behavior used by Sonex runtime flows.
    """
    entry_id: str
    target: MemoryTarget
    content: str
    source_path: str
    line_no: int


class MemoryStore:
    """Represents memory store.

    Encapsulates memory store data and behavior used by Sonex runtime flows.
    """
    def __init__(self) -> None:
        """Init for memory store.

        Coordinates the init method behavior while preserving memory store state and contracts.
        """
        self.paths = MemoryPaths(
            memory=sonex_home() / "MEMORY.md",
            user=sonex_home() / "USER.md",
        )
        self.memory_entries: list[str] = []
        self.user_entries: list[str] = []
        self._session_store: dict[str, Path] = {}
        self.current_session_id: str | None = None

    def init_session(self) -> None:
        """Initialize the current session database and rebuild markdown indexes."""
        self._ensure_markdown_files()
        session_id = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%fZ")
        root = sonex_home() / "sessions" / session_id
        root.mkdir(parents=True, exist_ok=True)

        db_path = root / "agent.db"
        self._session_store[session_id] = db_path
        self.current_session_id = session_id

        with sqlite3.connect(db_path) as conn:
            self._init_schema(conn)

        self.rebuild_memory_index()

    def get_db(self) -> Path:
        """Returns db for the current Sonex flow.

        Typical use: Use this function when runtime code needs get db as part of a Sonex command, playback, auth, llm, or ui path.

        Example: get_db() -> returns the value used by the surrounding Sonex flow.
        """
        if self.current_session_id is None:
            self.init_session()
        return self._session_store[self.current_session_id]

    def load_markdown(self, target: MemoryTarget) -> list[MemoryEntry]:
        """Loads markdown from persistent state.

        Typical use: Use this function when runtime code needs load markdown as part of a Sonex command, playback, auth, llm, or ui path.

        Example: load_markdown(target=...) -> returns the value used by the surrounding Sonex flow.
        """
        path = self._path_for_target(target)
        entries: list[MemoryEntry] = []
        if not path.exists():
            return entries

        for line_no, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            content = self._clean_markdown_line(raw_line)
            if not content:
                continue
            entries.append(
                MemoryEntry(
                    entry_id=self._entry_id(target, content),
                    target=target,
                    content=content,
                    source_path=str(path),
                    line_no=line_no,
                )
            )
        return entries

    def rebuild_memory_index(self) -> None:
        """Rebuild SQLite memory indexes from markdown source files."""
        db = self.get_db()
        entries = [*self.load_markdown("memory"), *self.load_markdown("user")]
        self.memory_entries = [entry.content for entry in entries if entry.target == "memory"]
        self.user_entries = [entry.content for entry in entries if entry.target == "user"]

        with sqlite3.connect(db) as conn:
            self._init_schema(conn)
            cursor = conn.cursor()
            cursor.execute("DELETE FROM memory_entries")
            if self._has_fts(conn):
                cursor.execute("DELETE FROM memory_fts")

            cursor.executemany(
                """
                INSERT OR REPLACE INTO memory_entries(
                    entry_id, target, content, source_path, line_no, updated_at
                )
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                [
                    (entry.entry_id, entry.target, entry.content, entry.source_path, entry.line_no)
                    for entry in entries
                ],
            )
            if self._has_fts(conn):
                cursor.executemany(
                    """
                    INSERT INTO memory_fts(entry_id, target, content)
                    VALUES (?, ?, ?)
                    """,
                    [(entry.entry_id, entry.target, entry.content) for entry in entries],
                )

    def search_memory(
        self,
        query: str,
        target: SearchTarget = "all",
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Coordinates search memory for the current Sonex flow.

        Typical use: Use this function when runtime code needs search memory as part of a Sonex command, playback, auth, llm, or ui path.

        Example: search_memory(query=..., target=..., limit=...) -> returns the value used by the surrounding Sonex flow.
        """
        if target not in SUPPORTED_MEMORY_TARGETS:
            raise ValueError(f"Unsupported memory target: {target}")

        query = query.strip()
        if not query:
            return []

        self.rebuild_memory_index()
        db = self.get_db()
        limit = self._coerce_limit(limit)
        with sqlite3.connect(db) as conn:
            conn.row_factory = sqlite3.Row
            self._init_schema(conn)
            if self._has_fts(conn):
                rows = self._search_memory_fts(conn, query, target, limit)
                if not rows:
                    rows = self._search_memory_like(conn, query, target, limit)
            else:
                rows = self._search_memory_like(conn, query, target, limit)
        return [dict(row) for row in rows]

    def append_context(self, role: str, content: dict[str, Any], tags: list[str]) -> int:
        """Coordinates append context for the current Sonex flow.

        Typical use: Use this function when runtime code needs append context as part of a Sonex command, playback, auth, llm, or ui path.

        Example: append_context(role=..., content=..., tags=...) -> returns the value used by the surrounding Sonex flow.
        """
        with sqlite3.connect(self.get_db()) as conn:
            cursor = conn.execute(
                """
                INSERT INTO context(type, content, tags)
                VALUES (?, ?, ?)
                """,
                (
                    role,
                    json.dumps(content, ensure_ascii=False, default=str),
                    json.dumps(tags, ensure_ascii=False),
                ),
            )
            return int(cursor.lastrowid)

    def search_context(
        self,
        query: str,
        table: SearchContextTable = "auto",
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Coordinates search context for the current Sonex flow.

        Typical use: Use this function when runtime code needs search context as part of a Sonex command, playback, auth, llm, or ui path.

        Example: search_context(query=..., table=..., limit=...) -> returns the value used by the surrounding Sonex flow.
        """
        if table not in SUPPORTED_CONTEXT_TABLES:
            raise ValueError(f"Unsupported context table: {table}")

        query = query.strip()
        limit = self._coerce_limit(limit)
        if table == "auto":
            cache_hits = self.search_context(query, table="cache", limit=limit)
            if cache_hits:
                return cache_hits
            return self.search_context(query, table="context", limit=limit)

        if not query:
            return self._recent_context(table, limit)

        pattern = f"%{query}%"
        with sqlite3.connect(self.get_db()) as conn:
            conn.row_factory = sqlite3.Row
            if table == "context":
                rows = conn.execute(
                    """
                    SELECT id, type, content, tags, created_at, access_count,
                           last_accessed, promoted_cache_key
                    FROM context
                    WHERE content LIKE ? OR tags LIKE ? OR type LIKE ?
                    ORDER BY access_count DESC, created_at DESC, id DESC
                    LIMIT ?
                    """,
                    (pattern, pattern, pattern, limit),
                ).fetchall()
                self._record_context_accesses(conn, [int(row["id"]) for row in rows])
            else:
                rows = conn.execute(
                    """
                    SELECT id, key, summary, tags, importance, last_updated,
                           source, source_context_id, kind
                    FROM cache
                    WHERE key LIKE ? OR summary LIKE ? OR tags LIKE ?
                    ORDER BY importance DESC, last_updated DESC, id DESC
                    LIMIT ?
                    """,
                    (pattern, pattern, pattern, limit),
                ).fetchall()
        return [dict(row) for row in rows]

    def upsert_cache(
        self,
        key: str,
        summary: str,
        tags: list[str],
        importance: float = 0,
        source: str | None = None,
        source_context_id: int | None = None,
        kind: str = "turn_summary",
    ) -> None:
        """Coordinates upsert cache for the current Sonex flow.

        Typical use: Use this function when runtime code needs upsert cache as part of a Sonex command, playback, auth, llm, or ui path.

        Example: upsert_cache(key=..., summary=..., tags=..., importance=..., source=..., source_context_id=..., kind=...) -> returns the value used by the surrounding Sonex flow.
        """
        key = key.strip()
        summary = summary.strip()
        if not key or not summary:
            return

        with sqlite3.connect(self.get_db()) as conn:
            conn.execute(
                """
                INSERT INTO cache(
                    key, summary, tags, importance, source,
                    source_context_id, kind, last_updated
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(key) DO UPDATE SET
                    summary = excluded.summary,
                    tags = excluded.tags,
                    importance = excluded.importance,
                    source = excluded.source,
                    source_context_id = excluded.source_context_id,
                    kind = excluded.kind,
                    last_updated = CURRENT_TIMESTAMP
                """,
                (
                    key,
                    summary,
                    json.dumps(tags, ensure_ascii=False),
                    float(importance),
                    source,
                    source_context_id,
                    kind,
                ),
            )

    def record_context_access(self, context_id: int) -> None:
        """Coordinates record context access for the current Sonex flow.

        Typical use: Use this function when runtime code needs record context access as part of a Sonex command, playback, auth, llm, or ui path.

        Example: record_context_access(context_id=...) -> returns the value used by the surrounding Sonex flow.
        """
        with sqlite3.connect(self.get_db()) as conn:
            conn.row_factory = sqlite3.Row
            self._record_context_accesses(conn, [context_id])

    def query(
        self,
        param: str,
        query: str,
        target: ContextTable,
        limit: int = 5,
    ) -> dict[str, str] | list[dict[str, Any]]:
        """Coordinates query for the current Sonex flow.

        Typical use: Use this function when runtime code needs query as part of a Sonex command, playback, auth, llm, or ui path.

        Example: query(param=..., query=..., target=..., limit=...) -> returns the value used by the surrounding Sonex flow.
        """
        params = SUPPORTED_CONTEXT_QUERY_PARAMS if target == "context" else SUPPORTED_CACHE_QUERY_PARAMS
        if target not in {"context", "cache"}:
            return {"error": f"Target '{target}' is not supported."}
        if param not in params:
            return {
                "error": f"Param '{param}' is not supported.",
                "help": f"Try these: {sorted(params)}.",
            }

        operator = "LIKE" if "%" in query else "="
        limit = self._coerce_limit(limit)
        with sqlite3.connect(self.get_db()) as conn:
            conn.row_factory = sqlite3.Row
            if target == "context":
                sql = (
                    f"SELECT id, type, content, tags, created_at, access_count, "
                    f"last_accessed, promoted_cache_key FROM context "
                    f"WHERE {param} {operator} ? "
                    "ORDER BY created_at DESC, id DESC LIMIT ?"
                )
            else:
                sql = (
                    f"SELECT id, key, summary, tags, importance, last_updated, "
                    f"source, source_context_id, kind FROM cache "
                    f"WHERE {param} {operator} ? "
                    "ORDER BY importance DESC, last_updated DESC, id DESC LIMIT ?"
                )
            rows = conn.execute(sql, (query, limit)).fetchall()
            if target == "context":
                self._record_context_accesses(conn, [int(row["id"]) for row in rows])
        return [dict(row) for row in rows]

    def add(self, target: MemoryTarget, content: str) -> dict[str, Any]:
        """Coordinates add for the current Sonex flow.

        Typical use: Use this function when runtime code needs add as part of a Sonex command, playback, auth, llm, or ui path.

        Example: add(target=..., content=...) -> returns the value used by the surrounding Sonex flow.
        """
        content = content.strip()
        if not content:
            return {"success": False, "error": "Content must not be empty."}

        entries = self.memory_entries if target == "memory" else self.user_entries
        if content in entries:
            return {"success": False, "error": "Memory entry already exists."}

        path = self._path_for_target(target)
        with path.open("a", encoding="utf-8") as f:
            f.write(f"{content}\n")
        self.rebuild_memory_index()

        return {
            "success": True,
            "current_entries": self.memory_entries if target == "memory" else self.user_entries,
            "message": "Entry added.",
        }

    def remove(self, target: MemoryTarget, content: str) -> dict[str, Any]:
        """Coordinates remove for the current Sonex flow.

        Typical use: Use this function when runtime code needs remove as part of a Sonex command, playback, auth, llm, or ui path.

        Example: remove(target=..., content=...) -> returns the value used by the surrounding Sonex flow.
        """
        content = content.strip()
        if not content:
            return {"success": False, "error": "Content must not be empty."}

        entries = self.memory_entries if target == "memory" else self.user_entries
        if content not in entries:
            return {"success": False, "error": "Entry not found."}

        entries = [entry for entry in entries if entry != content]
        self._set_entries(target, entries)
        self._save_file(self._path_for_target(target), entries)
        self.rebuild_memory_index()

        return {
            "success": True,
            "current_entries": entries,
            "message": "Entry removed.",
        }

    def _init_schema(self, conn: sqlite3.Connection) -> None:
        """Prepares init schema for an internal Sonex flow.

        Typical use: Use this helper when nearby code needs init schema without duplicating the local rules.

        Example: _init_schema(conn=...) -> returns the value used by the surrounding Sonex flow.
        """
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS context(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT NOT NULL,
                content TEXT NOT NULL,
                tags TEXT NOT NULL,
                access_count INTEGER DEFAULT 0,
                last_accessed TIMESTAMP,
                promoted_cache_key TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cursor.execute(
            """
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
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS memory_entries(
                entry_id TEXT PRIMARY KEY,
                target TEXT NOT NULL,
                content TEXT NOT NULL,
                source_path TEXT NOT NULL,
                line_no INTEGER NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_memory_entries_target ON memory_entries(target)")
        self._ensure_columns(cursor)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_context_access ON context(access_count, last_accessed)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_cache_kind ON cache(kind)")
        self._ensure_fts(cursor)

    def _ensure_columns(self, cursor: sqlite3.Cursor) -> None:
        """Prepares ensure columns for an internal Sonex flow.

        Typical use: Use this helper when nearby code needs ensure columns without duplicating the local rules.

        Example: _ensure_columns(cursor=...) -> returns the value used by the surrounding Sonex flow.
        """
        self._ensure_column(cursor, "context", "access_count", "INTEGER DEFAULT 0")
        self._ensure_column(cursor, "context", "last_accessed", "TIMESTAMP")
        self._ensure_column(cursor, "context", "promoted_cache_key", "TEXT")
        self._ensure_column(cursor, "cache", "source", "TEXT")
        self._ensure_column(cursor, "cache", "source_context_id", "INTEGER")
        self._ensure_column(cursor, "cache", "kind", "TEXT DEFAULT 'turn_summary'")

    @staticmethod
    def _ensure_column(cursor: sqlite3.Cursor, table: str, column: str, ddl: str) -> None:
        """Prepares ensure column for an internal Sonex flow.

        Typical use: Use this helper when nearby code needs ensure column without duplicating the local rules.

        Example: _ensure_column(cursor=..., table=..., column=..., ddl=...) -> returns the value used by the surrounding Sonex flow.
        """
        existing = {row[1] for row in cursor.execute(f"PRAGMA table_info({table})")}
        if column not in existing:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")

    def _ensure_fts(self, cursor: sqlite3.Cursor) -> None:
        """Prepares ensure fts for an internal Sonex flow.

        Typical use: Use this helper when nearby code needs ensure fts without duplicating the local rules.

        Example: _ensure_fts(cursor=...) -> returns the value used by the surrounding Sonex flow.
        """
        try:
            cursor.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts
                USING fts5(entry_id UNINDEXED, target UNINDEXED, content)
                """
            )
        except sqlite3.OperationalError:
            pass

    def _has_fts(self, conn: sqlite3.Connection) -> bool:
        """Prepares has fts for an internal Sonex flow.

        Typical use: Use this helper when nearby code needs has fts without duplicating the local rules.

        Example: _has_fts(conn=...) -> returns the value used by the surrounding Sonex flow.
        """
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'memory_fts'"
        ).fetchone()
        return row is not None

    def _search_memory_fts(
        self,
        conn: sqlite3.Connection,
        query: str,
        target: SearchTarget,
        limit: int,
    ) -> list[sqlite3.Row]:
        """Prepares search memory fts for an internal Sonex flow.

        Typical use: Use this helper when nearby code needs search memory fts without duplicating the local rules.

        Example: _search_memory_fts(conn=..., query=..., target=..., limit=...) -> returns the value used by the surrounding Sonex flow.
        """
        fts_query = self._to_fts_query(query)
        target_clause = "" if target == "all" else "AND e.target = ?"
        params: list[Any] = [fts_query]
        if target != "all":
            params.append(target)
        params.append(limit)
        return conn.execute(
            f"""
            SELECT e.entry_id, e.target, e.content, e.source_path, e.line_no, e.updated_at
            FROM memory_fts f
            JOIN memory_entries e ON e.entry_id = f.entry_id
            WHERE memory_fts MATCH ? {target_clause}
            ORDER BY bm25(memory_fts), e.updated_at DESC
            LIMIT ?
            """,
            params,
        ).fetchall()

    def _search_memory_like(
        self,
        conn: sqlite3.Connection,
        query: str,
        target: SearchTarget,
        limit: int,
    ) -> list[sqlite3.Row]:
        """Prepares search memory like for an internal Sonex flow.

        Typical use: Use this helper when nearby code needs search memory like without duplicating the local rules.

        Example: _search_memory_like(conn=..., query=..., target=..., limit=...) -> returns the value used by the surrounding Sonex flow.
        """
        pattern = f"%{query}%"
        target_clause = "" if target == "all" else "AND target = ?"
        params: list[Any] = [pattern]
        if target != "all":
            params.append(target)
        params.append(limit)
        return conn.execute(
            f"""
            SELECT entry_id, target, content, source_path, line_no, updated_at
            FROM memory_entries
            WHERE content LIKE ? {target_clause}
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            params,
        ).fetchall()

    def _recent_context(self, table: ContextTable, limit: int) -> list[dict[str, Any]]:
        """Prepares recent context for an internal Sonex flow.

        Typical use: Use this helper when nearby code needs recent context without duplicating the local rules.

        Example: _recent_context(table=..., limit=...) -> returns the value used by the surrounding Sonex flow.
        """
        with sqlite3.connect(self.get_db()) as conn:
            conn.row_factory = sqlite3.Row
            if table == "context":
                rows = conn.execute(
                    """
                    SELECT id, type, content, tags, created_at, access_count,
                           last_accessed, promoted_cache_key
                    FROM context
                    ORDER BY created_at DESC, id DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT id, key, summary, tags, importance, last_updated,
                           source, source_context_id, kind
                    FROM cache
                    ORDER BY importance DESC, last_updated DESC, id DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        return [dict(row) for row in rows]

    def _record_context_accesses(self, conn: sqlite3.Connection, context_ids: list[int]) -> None:
        """Prepares record context accesses for an internal Sonex flow.

        Typical use: Use this helper when nearby code needs record context accesses without duplicating the local rules.

        Example: _record_context_accesses(conn=..., context_ids=...) -> returns the value used by the surrounding Sonex flow.
        """
        for context_id in dict.fromkeys(context_ids):
            row = conn.execute(
                """
                SELECT id, type, content, tags, access_count, promoted_cache_key
                FROM context
                WHERE id = ?
                """,
                (context_id,),
            ).fetchone()
            if row is None:
                continue

            next_count = int(row["access_count"] or 0) + 1
            conn.execute(
                """
                UPDATE context
                SET access_count = ?, last_accessed = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (next_count, context_id),
            )
            if next_count >= 3 and not row["promoted_cache_key"]:
                self._promote_context_row(conn, row)

    def _promote_context_row(self, conn: sqlite3.Connection, row: sqlite3.Row) -> None:
        """Prepares promote context row for an internal Sonex flow.

        Typical use: Use this helper when nearby code needs promote context row without duplicating the local rules.

        Example: _promote_context_row(conn=..., row=...) -> returns the value used by the surrounding Sonex flow.
        """
        context_id = int(row["id"])
        key = f"context:{context_id}"
        summary = self._summarize_context_row(row)
        tags = ["promoted_context", f"context:{row['type']}", *self._loads_list(row["tags"])]
        conn.execute(
            """
            INSERT INTO cache(
                key, summary, tags, importance, source,
                source_context_id, kind, last_updated
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET
                summary = excluded.summary,
                tags = excluded.tags,
                importance = excluded.importance,
                source = excluded.source,
                source_context_id = excluded.source_context_id,
                kind = excluded.kind,
                last_updated = CURRENT_TIMESTAMP
            """,
            (
                key,
                summary,
                json.dumps(tags, ensure_ascii=False),
                0.8,
                "context",
                context_id,
                "promoted_context",
            ),
        )
        conn.execute(
            "UPDATE context SET promoted_cache_key = ? WHERE id = ?",
            (key, context_id),
        )

    def _summarize_context_row(self, row: sqlite3.Row) -> str:
        """Prepares summarize context row for an internal Sonex flow.

        Typical use: Use this helper when nearby code needs summarize context row without duplicating the local rules.

        Example: _summarize_context_row(row=...) -> returns the value used by the surrounding Sonex flow.
        """
        payload = self._loads_dict(row["content"])
        if row["type"] == "tool":
            tool = payload.get("tool", "unknown")
            result = self._clip_text(json.dumps(payload.get("result"), ensure_ascii=False, default=str), 600)
            return f"Frequently used tool result from {tool}: {result}"
        if row["type"] == "user":
            return f"Frequently referenced user input: {self._clip_text(str(payload.get('user', payload)), 600)}"
        if row["type"] == "agent":
            return f"Frequently referenced agent output: {self._clip_text(str(payload.get('agent_output', payload)), 600)}"
        if row["type"] == "error":
            return f"Frequently referenced error: {self._clip_text(str(payload.get('error_text', payload)), 600)}"
        return f"Frequently referenced context: {self._clip_text(json.dumps(payload, ensure_ascii=False, default=str), 600)}"

    def _ensure_markdown_files(self) -> None:
        """Prepares ensure markdown files for an internal Sonex flow.

        Typical use: Use this helper when nearby code needs ensure markdown files without duplicating the local rules.

        Example: _ensure_markdown_files() -> returns the value used by the surrounding Sonex flow.
        """
        self.paths.memory.parent.mkdir(parents=True, exist_ok=True)
        for path in (self.paths.memory, self.paths.user):
            if not path.exists():
                path.write_text("", encoding="utf-8")

    def _path_for_target(self, target: MemoryTarget) -> Path:
        """Prepares path for target for an internal Sonex flow.

        Typical use: Use this helper when nearby code needs path for target without duplicating the local rules.

        Example: _path_for_target(target=...) -> returns the value used by the surrounding Sonex flow.
        """
        if target == "memory":
            return self.paths.memory
        if target == "user":
            return self.paths.user
        raise ValueError(f"Unsupported memory target: {target}")

    def _set_entries(self, target: MemoryTarget, entries: list[str]) -> None:
        """Prepares set entries for an internal Sonex flow.

        Typical use: Use this helper when nearby code needs set entries without duplicating the local rules.

        Example: _set_entries(target=..., entries=...) -> returns the value used by the surrounding Sonex flow.
        """
        if target == "memory":
            self.memory_entries = entries
        else:
            self.user_entries = entries

    @staticmethod
    def _save_file(path: Path, entries: list[str]) -> None:
        """Prepares save file for an internal Sonex flow.

        Typical use: Use this helper when nearby code needs save file without duplicating the local rules.

        Example: _save_file(path=..., entries=...) -> returns the value used by the surrounding Sonex flow.
        """
        text = "\n".join(entries)
        if text:
            text = f"{text}\n"
        path.write_text(text, encoding="utf-8")

    @staticmethod
    def _clean_markdown_line(line: str) -> str:
        """Prepares clean markdown line for an internal Sonex flow.

        Typical use: Use this helper when nearby code needs clean markdown line without duplicating the local rules.

        Example: _clean_markdown_line(line=...) -> returns the value used by the surrounding Sonex flow.
        """
        text = line.strip()
        text = re.sub(r"^\s{0,3}#{1,6}\s*", "", text)
        text = re.sub(r"^\s{0,3}[-*+]\s+", "", text)
        text = re.sub(r"^\s{0,3}\d+[.)]\s+", "", text)
        return text.strip()

    @staticmethod
    def _entry_id(target: str, content: str) -> str:
        """Prepares entry id for an internal Sonex flow.

        Typical use: Use this helper when nearby code needs entry id without duplicating the local rules.

        Example: _entry_id(target=..., content=...) -> returns the value used by the surrounding Sonex flow.
        """
        normalized = re.sub(r"\s+", " ", content.strip().lower())
        payload = f"{target}:{normalized}".encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    @staticmethod
    def _loads_dict(value: Any) -> dict[str, Any]:
        """Prepares loads dict for an internal Sonex flow.

        Typical use: Use this helper when nearby code needs loads dict without duplicating the local rules.

        Example: _loads_dict(value=...) -> returns the value used by the surrounding Sonex flow.
        """
        if isinstance(value, dict):
            return value
        if not isinstance(value, str):
            return {}
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    @staticmethod
    def _loads_list(value: Any) -> list[str]:
        """Prepares loads list for an internal Sonex flow.

        Typical use: Use this helper when nearby code needs loads list without duplicating the local rules.

        Example: _loads_list(value=...) -> returns the value used by the surrounding Sonex flow.
        """
        if isinstance(value, list):
            return [str(item) for item in value]
        if not isinstance(value, str):
            return []
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        if not isinstance(parsed, list):
            return []
        return [str(item) for item in parsed]

    @staticmethod
    def _clip_text(text: str, limit: int) -> str:
        """Prepares clip text for an internal Sonex flow.

        Typical use: Use this helper when nearby code needs clip text without duplicating the local rules.

        Example: _clip_text(text=..., limit=...) -> returns the value used by the surrounding Sonex flow.
        """
        text = " ".join(text.split())
        if len(text) <= limit:
            return text
        return f"{text[:limit].rstrip()}..."

    @staticmethod
    def _to_fts_query(query: str) -> str:
        """Prepares to fts query for an internal Sonex flow.

        Typical use: Use this helper when nearby code needs to fts query without duplicating the local rules.

        Example: _to_fts_query(query=...) -> returns the value used by the surrounding Sonex flow.
        """
        tokens = re.findall(r"[a-zA-Z0-9_./-]+|[\u4e00-\u9fff]+", query.lower())
        if not tokens:
            return query.replace('"', '""')
        return " OR ".join(f'"{token.replace(chr(34), chr(34) * 2)}"' for token in tokens)

    @staticmethod
    def _coerce_limit(limit: int) -> int:
        """Prepares coerce limit for an internal Sonex flow.

        Typical use: Use this helper when nearby code needs coerce limit without duplicating the local rules.

        Example: _coerce_limit(limit=...) -> returns the value used by the surrounding Sonex flow.
        """
        try:
            value = int(limit)
        except (TypeError, ValueError):
            value = 10
        return max(1, min(value, 50))


memory_store = MemoryStore()
