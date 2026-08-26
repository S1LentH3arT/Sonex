"""Memory support for local memory storage and retrieval.

Implements the memory module responsibilities used by Sonex runtime flows.
Key public entry points include MemoryPaths, MemoryEntry, MemoryStore.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import unicodedata
import uuid
from contextvars import ContextVar
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

import fcntl

from src.log import sonex_home
from src.session_id import create_session_id


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
    state: Path
    index: Path
    dump: Path
    settings: Path
    revisions: Path
    journal: Path
    lock: Path


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
    source: str = "legacy"
    confidence: float = 1.0
    protected: bool = False
    created_at: str | None = None
    updated_at: str | None = None
    recall_count: int = 0
    last_recalled_at: str | None = None
    review: dict[str, Any] | None = None


_ACTIVE_SESSION_ID: ContextVar[str | None] = ContextVar("sonex_memory_session_id", default=None)
_ACTIVE_TURN_ID: ContextVar[str | None] = ContextVar("sonex_memory_turn_id", default=None)


def bind_memory_scope(session_id: str, turn_id: str | None = None) -> None:
    """Bind memory operations in the current async/thread context to one chat turn."""
    _ACTIVE_SESSION_ID.set(str(session_id).strip() or None)
    _ACTIVE_TURN_ID.set(str(turn_id).strip() or None)


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
            state=sonex_home() / "memory-state.json",
            index=sonex_home() / "memory-index.json",
            dump=sonex_home() / "memory-dump.json",
            settings=sonex_home() / "memory-settings.json",
            revisions=sonex_home() / "memory-revisions.json",
            journal=sonex_home() / ".memory-transaction.json",
            lock=sonex_home() / ".memory.lock",
        )
        self.memory_entries: list[str] = []
        self.user_entries: list[str] = []
        self._entries: dict[MemoryTarget, list[MemoryEntry]] = {"memory": [], "user": []}
        self._loaded = False
        self._read_only = False
        self._read_only_reason: str | None = None
        self._metadata_rebuild_dump: dict[str, Any] = {"version": 1, "entries": [], "tombstones": []}
        self._lock_handle: Any | None = None
        self._session_store: dict[str, Path] = {}
        self.current_session_id: str | None = None

    def init_session(self, session_id: str | None = None) -> None:
        """Initialize the current session database and rebuild markdown indexes."""
        self._ensure_markdown_files()
        session_id = session_id or create_session_id()
        root = self.paths.memory.parent / "sessions" / session_id
        root.mkdir(parents=True, exist_ok=True)

        db_path = root / "agent.db"
        self._session_store[session_id] = db_path
        self.current_session_id = session_id

        with sqlite3.connect(db_path) as conn:
            self._init_schema(conn)

        self._ensure_runtime_loaded()
        self.rebuild_memory_index()

    def get_db(self) -> Path:
        """Returns db for the current Sonex flow.

        Typical use: Use this function when runtime code needs get db as part of a Sonex command, playback, auth, llm, or ui path.

        Example: get_db() -> returns the value used by the surrounding Sonex flow.
        """
        scoped_session_id = _ACTIVE_SESSION_ID.get()
        session_id = scoped_session_id or self.current_session_id
        if session_id is None or session_id not in self._session_store:
            self.init_session(session_id)
            session_id = scoped_session_id or self.current_session_id
        return self._session_store[session_id]

    def load_markdown(self, target: MemoryTarget) -> list[MemoryEntry]:
        """Parse one clean Markdown representation into structured entries."""
        return self._parse_markdown(target, self._path_for_target(target))

    def entries(self, target: MemoryTarget) -> list[MemoryEntry]:
        """Return a snapshot of the active runtime entries for one target."""
        self._ensure_runtime_loaded()
        return list(self._entries[target])

    def rebuild_memory_index(self) -> None:
        """Rebuild SQLite memory indexes from markdown source files."""
        db = self.get_db()
        self._ensure_runtime_loaded()
        entries = [*self._entries["memory"], *self._entries["user"]]
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
                    entry_id, target, content, source_path, line_no,
                    source, confidence, memory_updated_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                [
                    (
                        entry.entry_id,
                        entry.target,
                        entry.content,
                        entry.source_path,
                        entry.line_no,
                        entry.source,
                        self._effective_confidence(entry),
                        entry.updated_at,
                    )
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

        self._ensure_runtime_loaded()
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
                INSERT INTO context(type, content, tags, turn_id)
                VALUES (?, ?, ?, ?)
                """,
                (
                    role,
                    json.dumps(content, ensure_ascii=False, default=str),
                    json.dumps(tags, ensure_ascii=False),
                    _ACTIVE_TURN_ID.get(),
                ),
            )
            return int(cursor.lastrowid)

    def events_for_turn(self, turn_id: str | None = None) -> list[dict[str, Any]]:
        """Return events belonging to exactly one Agent turn in chronological order."""
        resolved_turn_id = str(turn_id or _ACTIVE_TURN_ID.get() or "").strip()
        if not resolved_turn_id:
            return []
        with sqlite3.connect(self.get_db()) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT id, type, content, tags, turn_id, created_at, access_count,
                       last_accessed, promoted_cache_key
                FROM context
                WHERE turn_id = ?
                ORDER BY id ASC
                """,
                (resolved_turn_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def enqueue_memory_candidate(self, user_input: str, turn_id: str | None = None) -> str | None:
        """Persist a post-turn curation candidate before asynchronous processing."""
        resolved_turn_id = str(turn_id or _ACTIVE_TURN_ID.get() or "").strip()
        text = str(user_input or "").strip()
        if not resolved_turn_id or not text:
            return None
        created_at = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self.get_db()) as conn:
            conn.execute(
                """
                INSERT INTO memory_candidates(turn_id, user_input, status, created_at)
                VALUES (?, ?, 'pending', ?)
                ON CONFLICT(turn_id) DO NOTHING
                """,
                (resolved_turn_id, text, created_at),
            )
        return resolved_turn_id

    def memory_candidate_allowed(self, turn_id: str | None = None) -> bool:
        """Return false when a retained candidate predates the latest Markdown reset."""
        resolved_turn_id = str(turn_id or _ACTIVE_TURN_ID.get() or "").strip()
        if not resolved_turn_id:
            return True
        with sqlite3.connect(self.get_db()) as conn:
            row = conn.execute(
                "SELECT created_at FROM memory_candidates WHERE turn_id = ?",
                (resolved_turn_id,),
            ).fetchone()
        if row is None:
            return True
        reset_epoch = self.reset_epoch()
        return reset_epoch is None or str(row[0]) > reset_epoch

    def mark_memory_candidate(self, status: str, turn_id: str | None = None) -> None:
        resolved_turn_id = str(turn_id or _ACTIVE_TURN_ID.get() or "").strip()
        if not resolved_turn_id:
            return
        with sqlite3.connect(self.get_db()) as conn:
            conn.execute(
                "UPDATE memory_candidates SET status = ? WHERE turn_id = ?",
                (str(status), resolved_turn_id),
            )

    def mark_memory_candidate_failure(self, turn_id: str | None = None) -> None:
        """Count one curator failure and stop retrying after three attempts."""
        resolved_turn_id = str(turn_id or _ACTIVE_TURN_ID.get() or "").strip()
        if not resolved_turn_id:
            return
        with sqlite3.connect(self.get_db()) as conn:
            conn.execute(
                """
                UPDATE memory_candidates
                SET attempts = attempts + 1,
                    status = CASE WHEN attempts + 1 >= 3 THEN 'failed' ELSE 'pending' END
                WHERE turn_id = ?
                """,
                (resolved_turn_id,),
            )

    def pending_memory_candidates(self, limit: int = 8) -> list[dict[str, str]]:
        """Discover retained asynchronous candidates across prior session databases."""
        limit = max(0, int(limit))
        if limit == 0:
            return []
        candidates: list[tuple[str, str, str, str]] = []
        reset_epoch = self.reset_epoch()
        sessions_root = self.paths.memory.parent / "sessions"
        if not sessions_root.exists():
            return []
        for db_path in sessions_root.glob("*/agent.db"):
            try:
                with sqlite3.connect(db_path) as conn:
                    rows = conn.execute(
                        """
                        SELECT turn_id, user_input, created_at
                        FROM memory_candidates
                        WHERE status = 'pending'
                        ORDER BY id ASC
                        LIMIT ?
                        """,
                        (limit,),
                    ).fetchall()
            except sqlite3.OperationalError:
                continue
            for turn_id, user_input, created_at in rows:
                if reset_epoch is not None and str(created_at) <= reset_epoch:
                    continue
                candidates.append(
                    (
                        str(created_at),
                        db_path.parent.name,
                        str(turn_id),
                        str(user_input),
                    )
                )
        candidates.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
        return [
            {
                "session_id": session_id,
                "turn_id": turn_id,
                "user_input": user_input,
            }
            for _created_at, session_id, turn_id, user_input in candidates[:limit]
        ]

    def record_behavior_signal(self, kind: str, item: dict[str, Any]) -> int:
        """Accumulate provider-neutral music behavior without asserting a preference."""
        name = str(item.get("name") or item.get("title") or "").strip()
        artist = str(item.get("artist") or "").strip()
        if not name:
            return 0
        normalized_kind = str(kind or "played").strip().casefold()
        identity = f"{normalized_kind}:{name.casefold()}:{artist.casefold()}"
        signal_key = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        payload = json.dumps(
            {"kind": normalized_kind, "name": name, "artist": artist},
            ensure_ascii=False,
        )
        seen_at = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self.get_db()) as conn:
            conn.execute(
                """
                INSERT INTO behavior_signals(signal_key, kind, payload, count, last_seen)
                VALUES (?, ?, ?, 1, ?)
                ON CONFLICT(signal_key) DO UPDATE SET
                    count = behavior_signals.count + 1,
                    payload = excluded.payload,
                    last_seen = excluded.last_seen
                """,
                (signal_key, normalized_kind, payload, seen_at),
            )
            row = conn.execute(
                "SELECT count FROM behavior_signals WHERE signal_key = ?",
                (signal_key,),
            ).fetchone()
        return int(row[0]) if row else 0

    def promotable_behavior_signals(self, minimum_count: int = 3, limit: int = 8) -> list[dict[str, Any]]:
        """Return repeated behavior as evidence, never as an already-proven preference."""
        with sqlite3.connect(self.get_db()) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT signal_key, kind, payload, count, last_seen
                FROM behavior_signals
                WHERE count >= ?
                ORDER BY count DESC, last_seen DESC
                LIMIT ?
                """,
                (max(2, int(minimum_count)), max(1, int(limit))),
            ).fetchall()
        reset_epoch = self.reset_epoch()
        return [
            dict(row)
            for row in rows
            if reset_epoch is None or str(row["last_seen"]) > reset_epoch
        ]

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
        # Search form cache fisrt. If missed, search context table for specific entry.
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

    def add(
        self,
        target: MemoryTarget,
        content: str,
        *,
        source: str = "explicit",
        confidence: float = 1.0,
    ) -> dict[str, Any]:
        """Coordinates add for the current Sonex flow.

        Typical use: Use this function when runtime code needs add as part of a Sonex command, playback, auth, llm, or ui path.

        Example: add(target=..., content=...) -> returns the value used by the surrounding Sonex flow.
        """
        self._ensure_runtime_loaded()
        if self._read_only:
            return {"success": False, "error": "Memory is read only."}
        content = self._normalize_content(content)
        if not content:
            return {"success": False, "error": "Content must not be empty."}
        if len(content) > (2000 if source in {"explicit", "user"} else 500):
            return {"success": False, "error": "Memory entry is too long."}
        if self._contains_sensitive_memory(content):
            return {"success": False, "error": "Credentials and secrets cannot be stored in memory."}

        loaded = self._entries[target]
        if any(entry.content == content for entry in [*self._entries["user"], *self._entries["memory"]]):
            return {"success": False, "error": "Memory entry already exists."}

        path = self._path_for_target(target)
        now = datetime.now(timezone.utc).isoformat()
        loaded.append(
            MemoryEntry(
                entry_id=str(uuid.uuid4()),
                target=target,
                content=content,
                source_path=str(path),
                line_no=len(loaded) + 1,
                source=source,
                confidence=max(0.0, min(float(confidence), 1.0)),
                protected=source in {"explicit", "legacy", "user"},
                created_at=now,
                updated_at=now,
            )
        )
        self._commit_runtime()

        return {
            "success": True,
            "current_entries": self.memory_entries if target == "memory" else self.user_entries,
            "message": "Entry added.",
        }

    def remove(self, target: MemoryTarget, content: str) -> dict[str, Any]:
        """Forget a matching entry through Memory Dump; never delete it immediately."""
        self._ensure_runtime_loaded()
        if self._read_only:
            return {"success": False, "error": "Memory is read only."}
        content = self._normalize_content(content)
        if not content:
            return {"success": False, "error": "Content must not be empty."}

        current = self._entries[target]
        match = next((entry for entry in current if entry.content == content), None)
        if match is None:
            return {"success": False, "error": "Entry not found."}
        return self.forget(match.entry_id, reason="memory operation")

    def update(
        self,
        target: MemoryTarget,
        content: str,
        *,
        previous_content: str | None = None,
        source: str = "explicit",
        confidence: float = 1.0,
    ) -> dict[str, Any]:
        """Replace or refresh one authoritative Markdown memory entry."""
        self._ensure_runtime_loaded()
        content = self._normalize_content(content)
        previous = self._normalize_content(str(previous_content or content))
        if not content:
            return {"success": False, "error": "Content must not be empty."}
        if self._contains_sensitive_memory(content):
            return {"success": False, "error": "Credentials and secrets cannot be stored in memory."}
        current = self._entries[target]
        match_index = next(
            (index for index, entry in enumerate(current) if entry.content == previous),
            None,
        )
        if match_index is None:
            return self.add(
                target,
                content,
                source=source,
                confidence=confidence,
            )
        previous_entry = current[match_index]
        self._append_revision(previous_entry, content, actor="user" if source == "explicit" else "curator")
        current[match_index] = replace(
            previous_entry,
            content=content,
            source=source,
            confidence=max(0.0, min(float(confidence), 1.0)),
            protected=previous_entry.protected or source == "explicit",
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
        self._commit_runtime()
        return {
            "success": True,
            "current_entries": self.memory_entries if target == "memory" else self.user_entries,
            "message": "Entry updated.",
        }

    def forget(
        self,
        entry_id: str,
        *,
        retention_days: int | None = None,
        reason: str = "user",
    ) -> dict[str, Any]:
        """Move one active entry to Memory Dump for a recoverable cooling period."""
        self._ensure_runtime_loaded()
        if self._read_only:
            return {"success": False, "error": "Memory is read only."}
        found = self._find_entry(entry_id)
        if found is None:
            return {"success": False, "error": "Entry not found."}
        target, index, entry = found
        settings = self.settings()
        days = int(retention_days or settings["forget_retention_days"])
        days = days if days in {1, 3, 7} else 7
        now = datetime.now(timezone.utc)
        dump = self._read_json(self.paths.dump, {"version": 1, "entries": []})
        dump_entries = list(dump.get("entries") or [])
        dump_entries.append(
            {
                "entry": self._entry_to_dict(entry),
                "original_target": target,
                "original_index": index,
                "reason": reason,
                "forgotten_at": now.isoformat(),
                "expires_at": (now + timedelta(days=days)).isoformat(),
            }
        )
        del self._entries[target][index]
        self._commit_runtime(
            extra={
                self.paths.dump: {
                    **dump,
                    "version": 1,
                    "entries": dump_entries,
                }
            }
        )
        return {"success": True, "message": "Entry moved to Memory Dump."}

    def recall(self, entry_id: str) -> dict[str, Any]:
        """Restore one dump entry to its original active target as protected memory."""
        self._ensure_runtime_loaded()
        if self._read_only:
            return {"success": False, "error": "Memory is read only."}
        dump = self._read_json(self.paths.dump, {"version": 1, "entries": []})
        entries = list(dump.get("entries") or [])
        match_index = next(
            (index for index, item in enumerate(entries) if item.get("entry", {}).get("entry_id") == entry_id),
            None,
        )
        if match_index is None:
            return {"success": False, "error": "Dump entry not found."}
        item = entries[match_index]
        entry = self._entry_from_dict(item["entry"])
        target = str(item.get("original_target") or entry.target)
        if target not in {"user", "memory"}:
            return {"success": False, "error": "Dump entry target is invalid."}
        existing = next((value for value in self._entries[target] if value.content == entry.content), None)
        if existing is None:
            position = max(0, min(int(item.get("original_index") or 0), len(self._entries[target])))
            self._entries[target].insert(position, replace(entry, protected=True, target=target))
        del entries[match_index]
        self._commit_runtime(
            extra={
                self.paths.dump: {
                    **dump,
                    "version": 1,
                    "entries": entries,
                }
            }
        )
        return {"success": True, "message": "Memory recalled."}

    def dump_entries(self) -> list[dict[str, Any]]:
        """Return live, non-expired Memory Dump records newest first."""
        self._ensure_runtime_loaded()
        self._purge_expired_dump()
        dump = self._read_json(self.paths.dump, {"version": 1, "entries": []})
        return sorted(
            list(dump.get("entries") or []),
            key=lambda item: str(item.get("forgotten_at") or ""),
            reverse=True,
        )

    def format_memory(self, target: SearchTarget = "all") -> dict[str, Any]:
        """Move an entire active target to Memory Dump and advance the reset epoch."""
        self._ensure_runtime_loaded()
        if self._read_only:
            return {"success": False, "error": "Memory is read only."}
        if target not in SUPPORTED_MEMORY_TARGETS:
            return {"success": False, "error": "Memory target is invalid."}
        targets: tuple[MemoryTarget, ...] = ("user", "memory") if target == "all" else (target,)  # type: ignore[assignment]
        dump = self._read_json(self.paths.dump, {"version": 1, "entries": []})
        dump_entries = list(dump.get("entries") or [])
        now = datetime.now(timezone.utc)
        days = int(self.settings()["forget_retention_days"])
        moved = 0
        for selected in targets:
            for index, entry in enumerate(self._entries[selected]):
                dump_entries.append(
                    {
                        "entry": self._entry_to_dict(entry),
                        "original_target": selected,
                        "original_index": index,
                        "reason": "format",
                        "forgotten_at": now.isoformat(),
                        "expires_at": (now + timedelta(days=days)).isoformat(),
                    }
                )
                moved += 1
            self._entries[selected] = []
        state = self._read_state()
        state["reset_epoch"] = now.isoformat()
        self._commit_runtime(
            extra={
                self.paths.dump: {**dump, "version": 1, "entries": dump_entries},
                self.paths.state: state,
            }
        )
        return {"success": True, "count": moved, "message": "Long-term memory formatted."}

    def rebuild_internal_metadata(self) -> dict[str, Any]:
        """Explicitly rebuild damaged JSON metadata from readable Markdown files."""
        self._ensure_runtime_loaded()
        if self._read_only_reason != "metadata_corrupt":
            return {"success": False, "error": "Memory metadata does not require rebuilding."}
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        for path in (self.paths.index, self.paths.dump, self.paths.journal):
            _, valid = self._read_json_checked(path, {})
            if not valid:
                backup = path.with_name(f"{path.name}.corrupt-{timestamp}.bak")
                path.replace(backup)
        self._read_only = False
        self._read_only_reason = None
        self._commit_runtime(extra={self.paths.dump: self._metadata_rebuild_dump})
        return {"success": True, "message": "Memory metadata rebuilt; corrupt files were backed up."}

    def move(self, entry_id: str, target: MemoryTarget) -> dict[str, Any]:
        """Move an active entry between semantic files while preserving identity."""
        self._ensure_runtime_loaded()
        if self._read_only:
            return {"success": False, "error": "Memory is read only."}
        found = self._find_entry(entry_id)
        if found is None:
            return {"success": False, "error": "Entry not found."}
        source_target, index, entry = found
        if source_target == target:
            return {"success": True, "message": "Memory is already in this file."}
        duplicate = next((item for item in self._entries[target] if item.content == entry.content), None)
        if duplicate is not None:
            return {"success": False, "error": "The target file already contains this memory."}
        del self._entries[source_target][index]
        self._entries[target].append(
            replace(entry, target=target, source_path=str(self._path_for_target(target)), protected=True)
        )
        self._append_revision(entry, entry.content, actor=f"move:{source_target}->{target}")
        self._commit_runtime()
        return {"success": True, "message": f"Memory moved to {'USER.md' if target == 'user' else 'MEMORY.md'}."}

    def revisions(self, entry_id: str) -> list[dict[str, Any]]:
        """Return the newest retained revision records for one active entry."""
        data = self._read_json(self.paths.revisions, {"entries": {}})
        return list(data.get("entries", {}).get(entry_id) or [])

    def restore_revision(self, entry_id: str, revision_index: int) -> dict[str, Any]:
        """Restore one retained before-image as a new protected revision."""
        found = self._find_entry(entry_id)
        if found is None:
            return {"success": False, "error": "Entry not found."}
        revisions = self.revisions(entry_id)
        if revision_index < 0 or revision_index >= len(revisions):
            return {"success": False, "error": "Revision not found."}
        target, index, entry = found
        content = self._normalize_content(str(revisions[revision_index].get("before") or ""))
        if not content:
            return {"success": False, "error": "Revision content is empty."}
        self._append_revision(entry, content, actor="revision:restored")
        self._entries[target][index] = replace(
            entry,
            content=content,
            protected=True,
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
        self._commit_runtime()
        return {"success": True, "message": "Memory revision restored."}

    def propose_update(self, entry_id: str, content: str, reason: str) -> dict[str, Any]:
        """Attach a bounded review proposal without changing active content."""
        self._ensure_runtime_loaded()
        found = self._find_entry(entry_id)
        if found is None:
            return {"success": False, "error": "Entry not found."}
        if self._contains_sensitive_memory(content):
            return {"success": False, "error": "Credentials and secrets cannot be stored in memory."}
        target, index, entry = found
        self._entries[target][index] = replace(
            entry,
            review={
                "content": self._normalize_content(content),
                "reason": reason,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "expires_at": (datetime.now(timezone.utc) + timedelta(days=30)).isoformat(),
            },
        )
        self._commit_runtime()
        return {"success": True, "message": "Memory review suggested."}

    def resolve_review(self, entry_id: str, *, accept: bool) -> dict[str, Any]:
        """Accept or reject one attached review proposal."""
        self._ensure_runtime_loaded()
        found = self._find_entry(entry_id)
        if found is None:
            return {"success": False, "error": "Entry not found."}
        target, index, entry = found
        if not entry.review:
            return {"success": False, "error": "No review is pending."}
        if accept:
            content = self._normalize_content(str(entry.review.get("content") or ""))
            self._append_revision(entry, content, actor="review:accepted")
            self._entries[target][index] = replace(
                entry,
                content=content,
                protected=True,
                review=None,
                updated_at=datetime.now(timezone.utc).isoformat(),
            )
        else:
            self._entries[target][index] = replace(entry, review=None)
        self._commit_runtime()
        return {"success": True, "message": "Memory review accepted." if accept else "Memory review rejected."}

    def record_recalled(self, entry_ids: list[str]) -> None:
        """Record entries that were actually injected into one Agent turn."""
        self._ensure_runtime_loaded()
        if self._read_only:
            return
        now = datetime.now(timezone.utc).isoformat()
        changed = False
        for entry_id in dict.fromkeys(entry_ids):
            found = self._find_entry(entry_id)
            if found is None:
                continue
            target, index, entry = found
            self._entries[target][index] = replace(
                entry,
                recall_count=entry.recall_count + 1,
                last_recalled_at=now,
            )
            changed = True
        if changed:
            self._commit_runtime()

    def settings(self) -> dict[str, Any]:
        """Return validated backend memory settings."""
        defaults = {
            "forget_retention_days": 7,
            "user_capacity": None,
            "memory_capacity": None,
            "automatic_forgetting": "off",
            "idle_threshold_days": 30,
            "automatic_refinement": True,
            "user_refinement_window": 8,
            "memory_refinement_window": 12,
        }
        value = self._read_json(self.paths.settings, {})
        return {**defaults, **value}

    def update_settings(self, changes: dict[str, Any]) -> dict[str, Any]:
        """Validate and persist supported memory settings."""
        self._ensure_runtime_loaded()
        if self._read_only:
            return {"success": False, "error": "Memory is read only."}
        current = self.settings()
        supported = set(current)
        if set(changes) - supported:
            return {"success": False, "error": "Unsupported memory setting."}
        updated = {**current, **changes}
        for key in ("forget_retention_days", "idle_threshold_days", "user_refinement_window", "memory_refinement_window"):
            try:
                updated[key] = int(updated[key])
            except (TypeError, ValueError):
                return {"success": False, "error": "Numeric memory settings require whole numbers."}
        for key in ("user_capacity", "memory_capacity"):
            value = updated[key]
            if isinstance(value, str) and value.strip().casefold() in {"", "none", "unlimited"}:
                updated[key] = None
            elif value is not None:
                try:
                    updated[key] = int(value)
                except (TypeError, ValueError):
                    return {"success": False, "error": "Memory capacity must be a whole number or Unlimited."}
        if not isinstance(updated["automatic_refinement"], bool):
            return {"success": False, "error": "Automatic refinement must be On or Off."}
        if updated["forget_retention_days"] not in {1, 3, 7}:
            return {"success": False, "error": "Forget retention must be 1, 3, or 7 days."}
        if updated["automatic_forgetting"] not in {"off", "idle", "capacity", "idle_capacity"}:
            return {"success": False, "error": "Automatic forgetting mode is invalid."}
        for key in ("user_refinement_window", "memory_refinement_window"):
            if not 4 <= int(updated[key]) <= 32:
                return {"success": False, "error": "Refinement window must be between 4 and 32."}
        if int(updated["idle_threshold_days"]) not in {7, 15, 30}:
            return {"success": False, "error": "Idle threshold must be 7, 15, or 30 days."}
        for key in ("user_capacity", "memory_capacity"):
            if updated[key] is not None and int(updated[key]) <= 0:
                return {"success": False, "error": "Memory capacity must be positive or Unlimited."}
        self._atomic_write(self.paths.settings, json.dumps(updated, ensure_ascii=False, indent=2) + "\n")
        return {"success": True, "settings": updated}

    def run_maintenance(self) -> list[MemoryEntry]:
        """Apply deterministic idle/capacity forgetting to unprotected inferred memory."""
        self._ensure_runtime_loaded()
        if self._read_only:
            return []
        self._expire_reviews()
        settings = self.settings()
        mode = str(settings["automatic_forgetting"])
        if mode == "off":
            self._purge_expired_dump()
            return []
        now = datetime.now(timezone.utc)
        state = self._read_state()
        candidates: list[MemoryEntry] = []
        if mode in {"idle", "idle_capacity"} and state.get("last_idle_maintenance") != now.date().isoformat():
            threshold = now - timedelta(days=max(1, int(settings["idle_threshold_days"])))
            for entry in [*self._entries["user"], *self._entries["memory"]]:
                if entry.protected or entry.source not in {"inferred", "experience"}:
                    continue
                observed = entry.last_recalled_at or entry.updated_at or entry.created_at
                try:
                    inactive = observed is None or datetime.fromisoformat(observed) <= threshold
                except ValueError:
                    inactive = False
                if inactive:
                    candidates.append(entry)
            candidates.sort(key=lambda entry: (entry.recall_count, entry.last_recalled_at or "", entry.confidence))
            if candidates:
                candidates = candidates[:max(1, (len(candidates) + 9) // 10)]
            state["last_idle_maintenance"] = now.date().isoformat()
            self._write_state(state)
        if mode in {"capacity", "idle_capacity"}:
            for target, setting_key in (("user", "user_capacity"), ("memory", "memory_capacity")):
                capacity = settings.get(setting_key)
                if capacity is None:
                    continue
                capacity = max(1, int(capacity))
                if len(self._entries[target]) < capacity:
                    continue
                target_count = max(0, int(capacity * 0.9))
                eligible = [
                    entry for entry in self._entries[target]
                    if not entry.protected and entry.source in {"inferred", "experience"}
                ]
                eligible.sort(key=lambda entry: (entry.recall_count, entry.last_recalled_at or "", entry.confidence))
                needed = max(0, len(self._entries[target]) - target_count)
                candidates.extend(eligible[:needed])
        forgotten: list[MemoryEntry] = []
        unique_candidates = list({entry.entry_id: entry for entry in candidates}.values())
        for entry in unique_candidates:
            if self.forget(entry.entry_id, reason="automatic forgetting").get("success"):
                forgotten.append(entry)
        self._purge_expired_dump()
        return forgotten

    def capacity_warnings(self) -> list[str]:
        """Return once-daily warnings when a configured soft target reaches 80 percent."""
        self._ensure_runtime_loaded()
        settings = self.settings()
        state = self._read_state()
        today = datetime.now(timezone.utc).date().isoformat()
        warnings: list[str] = []
        changed = False
        for target, setting_key, label in (
            ("user", "user_capacity", "USER.md"),
            ("memory", "memory_capacity", "MEMORY.md"),
        ):
            capacity = settings.get(setting_key)
            if capacity is None:
                continue
            count = len(self._entries[target])
            threshold = max(1, int(int(capacity) * 0.8))
            state_key = f"capacity_warning_{target}"
            if count >= threshold and state.get(state_key) != today:
                warnings.append(
                    f"{label} is at {count}/{int(capacity)} entries; larger memory can reduce recall and retrieval efficiency."
                )
                state[state_key] = today
                changed = True
            elif count < threshold:
                changed = state.pop(state_key, None) is not None or changed
        if changed and not self._read_only:
            self._write_state(state)
        return warnings

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
                turn_id TEXT,
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
                source TEXT DEFAULT 'legacy',
                confidence REAL DEFAULT 1.0,
                memory_updated_at TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS memory_candidates(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                turn_id TEXT NOT NULL UNIQUE,
                user_input TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS behavior_signals(
                signal_key TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                payload TEXT NOT NULL,
                count INTEGER NOT NULL DEFAULT 0,
                last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
        self._ensure_column(cursor, "context", "turn_id", "TEXT")
        self._ensure_column(cursor, "cache", "source", "TEXT")
        self._ensure_column(cursor, "cache", "source_context_id", "INTEGER")
        self._ensure_column(cursor, "cache", "kind", "TEXT DEFAULT 'turn_summary'")
        self._ensure_column(cursor, "memory_entries", "source", "TEXT DEFAULT 'legacy'")
        self._ensure_column(cursor, "memory_entries", "confidence", "REAL DEFAULT 1.0")
        self._ensure_column(cursor, "memory_entries", "memory_updated_at", "TEXT")
        self._ensure_column(cursor, "memory_candidates", "attempts", "INTEGER NOT NULL DEFAULT 0")

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

    def long_term_enabled(self) -> bool:
        """Long-term memory is always available; retained for caller compatibility."""
        return True

    def set_long_term_enabled(self, enabled: bool) -> bool:
        """Deprecated compatibility shim; long-term memory can no longer be disabled."""
        return True

    def consume_first_notice(self) -> bool:
        """Persist and return whether the local-memory disclosure should be shown once."""
        state = self._read_state()
        if state.get("notice_shown"):
            return False
        state["notice_shown"] = True
        self._write_state(state)
        return True

    def reset_long_term(self) -> dict[str, Any]:
        """Compatibility alias for recoverable formatting of all active memory."""
        return self.format_memory("all")

    def reset_epoch(self) -> str | None:
        value = self._read_state().get("reset_epoch")
        return str(value) if value else None

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

    def _ensure_runtime_loaded(self) -> None:
        if self._loaded:
            return
        self._ensure_markdown_files()
        self._acquire_writer_lock()
        self._recover_journal()
        index, index_valid = self._read_json_checked(self.paths.index, {})
        dump, dump_valid = self._read_json_checked(self.paths.dump, {"version": 1, "entries": []})
        if dump_valid and isinstance(dump, dict):
            self._metadata_rebuild_dump = dump
        if not index_valid or not dump_valid:
            # Markdown remains readable, but malformed internal metadata must never
            # be silently replaced by a guessed reconstruction.
            self._read_only = True
            if self._read_only_reason is None:
                self._read_only_reason = "metadata_corrupt"
        dump_entries = list(dump.get("entries") or [])
        offline_changed = False
        for target in ("user", "memory"):
            parsed = self._parse_markdown(target, self._path_for_target(target))
            indexed_list = [
                self._entry_from_dict(item)
                for item in index.get("entries", {}).get(target, [])
                if isinstance(item, dict) and item.get("entry_id")
            ]
            by_content: dict[str, list[MemoryEntry]] = {}
            for item in indexed_list:
                by_content.setdefault(self._fingerprint(item.content), []).append(item)
            restored_slots: list[MemoryEntry | None] = [None] * len(parsed)
            used_ids: set[str] = set()
            for position, entry in enumerate(parsed):
                candidates = [
                    candidate
                    for candidate in by_content.get(self._fingerprint(entry.content), [])
                    if candidate.entry_id not in used_ids
                ]
                if len(candidates) == 1:
                    previous = candidates[0]
                    restored_slots[position] = replace(previous, content=entry.content, line_no=entry.line_no)
                    used_ids.add(previous.entry_id)
            unmatched_parsed = [index for index, entry in enumerate(restored_slots) if entry is None]
            unmatched_indexed = [entry for entry in indexed_list if entry.entry_id not in used_ids]
            modification_count = min(len(unmatched_parsed), len(unmatched_indexed))
            for offset in range(modification_count):
                position = unmatched_parsed[offset]
                previous = unmatched_indexed[offset]
                restored_slots[position] = replace(
                    previous,
                    content=parsed[position].content,
                    line_no=parsed[position].line_no,
                    protected=True,
                    updated_at=datetime.now(timezone.utc).isoformat(),
                )
                used_ids.add(previous.entry_id)
                offline_changed = True
            for position in unmatched_parsed[modification_count:]:
                restored_slots[position] = parsed[position]
                used_ids.add(parsed[position].entry_id)
                offline_changed = True
            restored = [entry for entry in restored_slots if entry is not None]
            now = datetime.now(timezone.utc)
            retention = int(self.settings()["forget_retention_days"])
            for previous in indexed_list:
                if previous.entry_id in used_ids:
                    continue
                dump_entries.append(
                    {
                        "entry": self._entry_to_dict(previous),
                        "original_target": target,
                        "original_index": indexed_list.index(previous),
                        "reason": "offline deletion",
                        "forgotten_at": now.isoformat(),
                        "expires_at": (now + timedelta(days=retention)).isoformat(),
                    }
                )
                offline_changed = True
            self._entries[target] = restored
        self._loaded = True
        self._sync_public_entries()
        if not self._read_only:
            extra = {self.paths.dump: {"version": 1, "entries": dump_entries}} if offline_changed else None
            self._commit_runtime(extra=extra)

    def _parse_markdown(self, target: MemoryTarget, path: Path) -> list[MemoryEntry]:
        if not path.exists():
            return []
        lines = path.read_text(encoding="utf-8").replace("\r\n", "\n").split("\n")
        entries: list[MemoryEntry] = []
        current: list[str] | None = None
        current_line = 0
        legacy: dict[str, str] = {}
        now = datetime.now(timezone.utc).isoformat()
        for line_no, raw in enumerate(lines, 1):
            stripped = raw.strip()
            if re.match(r"^\s*[-*+]\s+", raw):
                if current is not None:
                    entries.append(self._parsed_entry(target, current, current_line, legacy, now, path))
                current = [re.sub(r"^\s*[-*+]\s+", "", raw).rstrip()]
                current_line = line_no
                legacy = {}
            elif current is not None and re.fullmatch(r"\s*<!--\s*sonex:.*?-->\s*", raw):
                legacy = self._parse_metadata(stripped)
            elif current is not None and (raw.startswith("  ") or raw.startswith("\t")):
                current.append(raw[2:].rstrip() if raw.startswith("  ") else raw[1:].rstrip())
            elif not stripped or stripped.startswith("#") or stripped.startswith("<!--"):
                continue
            elif current is not None:
                # Only an indented continuation belongs to a list entry. Ignoring
                # arbitrary top-level prose keeps the Markdown representation
                # deterministic and avoids importing accidental instructions.
                continue
        if current is not None:
            entries.append(self._parsed_entry(target, current, current_line, legacy, now, path))
        return entries

    def _parsed_entry(
        self,
        target: MemoryTarget,
        lines: list[str],
        line_no: int,
        metadata: dict[str, str],
        now: str,
        path: Path,
    ) -> MemoryEntry:
        content = self._normalize_content("\n".join(lines))
        confidence = 1.0
        try:
            confidence = float(metadata.get("confidence", 1.0))
        except ValueError:
            pass
        return MemoryEntry(
            entry_id=metadata.get("id") or str(uuid.uuid4()),
            target=target,
            content=content,
            source_path=str(path),
            line_no=line_no,
            source=metadata.get("source", "legacy"),
            confidence=max(0.0, min(confidence, 1.0)),
            protected=True,
            created_at=metadata.get("updated") or now,
            updated_at=metadata.get("updated") or now,
        )

    def _commit_runtime(self, *, extra: dict[Path, dict[str, Any]] | None = None) -> None:
        if self._read_only:
            raise PermissionError("Memory is read only.")
        self._sync_public_entries()
        index = {
            "version": 1,
            "entries": {
                target: [self._entry_to_dict(entry) for entry in self._entries[target]]
                for target in ("user", "memory")
            },
            "file_hashes": {
                target: self._fingerprint(self._render_markdown(target, self._entries[target]))
                for target in ("user", "memory")
            },
        }
        payloads: dict[Path, str] = {
            self.paths.user: self._render_markdown("user", self._entries["user"]),
            self.paths.memory: self._render_markdown("memory", self._entries["memory"]),
            self.paths.index: json.dumps(index, ensure_ascii=False, indent=2) + "\n",
        }
        for path, value in (extra or {}).items():
            payloads[path] = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
        transaction_id = str(uuid.uuid4())
        staged: dict[str, str] = {}
        for path, text in payloads.items():
            temporary = path.with_name(f".{path.name}.{transaction_id}.tmp")
            temporary.write_text(text, encoding="utf-8")
            staged[str(path)] = str(temporary)
        self._atomic_write(
            self.paths.journal,
            json.dumps({"version": 1, "staged": staged}, ensure_ascii=False, indent=2) + "\n",
        )
        for destination, temporary in staged.items():
            Path(temporary).replace(Path(destination))
        self.paths.journal.unlink(missing_ok=True)
        if self.current_session_id is not None:
            self.rebuild_memory_index()

    def _render_markdown(self, target: MemoryTarget, entries: list[MemoryEntry]) -> str:
        title = "User memory" if target == "user" else "Agent memory"
        lines = [f"# {title}", ""]
        for entry in entries:
            content_lines = entry.content.split("\n")
            lines.append(f"- {content_lines[0]}")
            lines.extend(f"  {line}" for line in content_lines[1:])
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    def _recover_journal(self) -> None:
        if self._read_only:
            return
        journal, valid = self._read_json_checked(self.paths.journal, {})
        if not valid:
            self._read_only = True
            self._read_only_reason = "metadata_corrupt"
            return
        staged = journal.get("staged") if isinstance(journal, dict) else None
        if not isinstance(staged, dict):
            return
        for destination, temporary in staged.items():
            path = Path(str(temporary))
            if path.exists():
                path.replace(Path(str(destination)))
        self.paths.journal.unlink(missing_ok=True)

    def _acquire_writer_lock(self) -> None:
        if self._lock_handle is not None:
            return
        self._lock_handle = self.paths.lock.open("a+")
        try:
            fcntl.flock(self._lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self._read_only = True
            self._read_only_reason = "writer_lock"

    def _sync_public_entries(self) -> None:
        self.user_entries = [entry.content for entry in self._entries["user"]]
        self.memory_entries = [entry.content for entry in self._entries["memory"]]

    def _find_entry(self, entry_id: str) -> tuple[MemoryTarget, int, MemoryEntry] | None:
        for target in ("user", "memory"):
            for index, entry in enumerate(self._entries[target]):
                if entry.entry_id == entry_id:
                    return target, index, entry
        return None

    def _append_revision(self, entry: MemoryEntry, next_content: str, *, actor: str) -> None:
        data = self._read_json(self.paths.revisions, {"version": 1, "entries": {}})
        histories = data.setdefault("entries", {})
        history = list(histories.get(entry.entry_id) or [])
        history.append(
            {
                "before": entry.content,
                "after": next_content,
                "actor": actor,
                "changed_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        histories[entry.entry_id] = history[-20:]
        self._atomic_write(self.paths.revisions, json.dumps(data, ensure_ascii=False, indent=2) + "\n")

    def _expire_reviews(self) -> None:
        now = datetime.now(timezone.utc)
        changed = False
        for target in ("user", "memory"):
            for index, entry in enumerate(self._entries[target]):
                review = entry.review
                if not review:
                    continue
                try:
                    expired = datetime.fromisoformat(str(review.get("expires_at") or "")) <= now
                except ValueError:
                    expired = False
                if expired:
                    self._entries[target][index] = replace(entry, review=None)
                    changed = True
        if changed:
            self._commit_runtime()

    def _purge_expired_dump(self) -> None:
        if self._read_only:
            return
        dump = self._read_json(self.paths.dump, {"version": 1, "entries": []})
        system_now = datetime.now(timezone.utc)
        state = self._read_state()
        try:
            previous_now = datetime.fromisoformat(str(state.get("dump_clock_utc") or ""))
        except ValueError:
            previous_now = system_now
        now = max(system_now, previous_now)
        retained: list[dict[str, Any]] = []
        tombstones: list[dict[str, str]] = list(dump.get("tombstones") or [])
        changed = False
        for item in dump.get("entries") or []:
            try:
                expired = datetime.fromisoformat(str(item.get("expires_at"))) <= now
            except ValueError:
                expired = False
            if expired:
                tombstones.append(
                    {
                        "entry_id": str(item.get("entry", {}).get("entry_id") or ""),
                        "deleted_at": now.isoformat(),
                        "target": str(item.get("original_target") or ""),
                    }
                )
                changed = True
            else:
                retained.append(item)
        if changed:
            self._atomic_write(
                self.paths.dump,
                json.dumps({"version": 1, "entries": retained, "tombstones": tombstones}, ensure_ascii=False, indent=2) + "\n",
            )
        if state.get("dump_clock_utc") != now.isoformat():
            state["dump_clock_utc"] = now.isoformat()
            self._write_state(state)

    @staticmethod
    def _entry_to_dict(entry: MemoryEntry) -> dict[str, Any]:
        return asdict(entry)

    @staticmethod
    def _entry_from_dict(value: dict[str, Any]) -> MemoryEntry:
        allowed = set(MemoryEntry.__dataclass_fields__)
        return MemoryEntry(**{key: item for key, item in value.items() if key in allowed})

    @staticmethod
    def _read_json(path: Path, default: Any) -> Any:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return default

    @staticmethod
    def _read_json_checked(path: Path, default: Any) -> tuple[Any, bool]:
        """Read JSON while distinguishing a missing file from damaged metadata."""
        if not path.exists():
            return default, True
        try:
            return json.loads(path.read_text(encoding="utf-8")), True
        except (OSError, json.JSONDecodeError):
            return default, False

    @staticmethod
    def _normalize_content(content: str) -> str:
        lines = unicodedata.normalize("NFC", str(content).replace("\r\n", "\n")).split("\n")
        while lines and not lines[0].strip():
            lines.pop(0)
        while lines and not lines[-1].strip():
            lines.pop()
        return "\n".join(line.rstrip() for line in lines)

    @staticmethod
    def _fingerprint(content: str) -> str:
        return hashlib.sha256(MemoryStore._normalize_content(content).encode("utf-8")).hexdigest()

    @staticmethod
    def _contains_sensitive_memory(content: str) -> bool:
        text = str(content or "")
        return bool(
            re.search(
                r"(?:api[_ -]?key|access[_ -]?token|refresh[_ -]?token|authorization|bearer|cookie|password)\s*[:=]\s*\S+",
                text,
                re.IGNORECASE,
            )
            or "-----BEGIN PRIVATE KEY-----" in text
        )

    @staticmethod
    def _parse_metadata(line: str) -> dict[str, str]:
        match = re.fullmatch(r"<!--\s*sonex:(.*?)\s*-->", line)
        if match is None:
            return {}
        return {
            key: value
            for key, value in re.findall(r"([a-z_]+)=([^\s]+)", match.group(1))
        }

    @staticmethod
    def _atomic_write(path: Path, text: str) -> None:
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(path)

    def _read_state(self) -> dict[str, Any]:
        try:
            value = json.loads(self.paths.state.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"enabled": True}
        return value if isinstance(value, dict) else {"enabled": True}

    def _write_state(self, state: dict[str, Any]) -> None:
        self.paths.state.parent.mkdir(parents=True, exist_ok=True)
        self._atomic_write(
            self.paths.state,
            json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        )

    @staticmethod
    def _effective_confidence(entry: MemoryEntry) -> float:
        if entry.source in {"explicit", "legacy"} or not entry.updated_at:
            return entry.confidence
        try:
            updated = datetime.fromisoformat(entry.updated_at)
            if updated.tzinfo is None:
                updated = updated.replace(tzinfo=timezone.utc)
            age_days = max(0.0, (datetime.now(timezone.utc) - updated).total_seconds() / 86400)
        except ValueError:
            return entry.confidence
        half_life = 180.0 if entry.source == "inferred" else 365.0
        return max(0.0, min(entry.confidence * (0.5 ** (age_days / half_life)), 1.0))

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
