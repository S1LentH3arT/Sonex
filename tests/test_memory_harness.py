from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.memory.curator import (
    curate_completed_turn,
    explicit_memory_operation,
    memory_operation_message,
)
from src.memory.hooks import finalize_turn
from src.memory.memory import MemoryStore, bind_memory_scope


class MemoryHarnessTests(unittest.TestCase):
    def _store(self, home: str) -> MemoryStore:
        with patch.dict("os.environ", {"SONEX_HOME": home}):
            return MemoryStore()

    def test_sqlite_context_is_isolated_by_canonical_chat_session(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            store = self._store(home)
            bind_memory_scope("session-a", "turn-a")
            store.append_context("user", {"user": "alpha"}, ["user"])
            first_db = store.get_db()

            bind_memory_scope("session-b", "turn-b")
            store.append_context("user", {"user": "beta"}, ["user"])
            second_db = store.get_db()

            self.assertNotEqual(first_db, second_db)
            self.assertIn("beta", store.search_context("", table="context", limit=4)[0]["content"])
            self.assertNotIn("alpha", store.search_context("", table="context", limit=4)[0]["content"])

    def test_finalize_turn_uses_exact_turn_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            store = self._store(home)
            with patch("src.memory.hooks.memory_store", store):
                bind_memory_scope("session", "turn-one")
                store.append_context("user", {"user": "first"}, ["user"])
                store.append_context(
                    "tool",
                    {"tool": "Query", "args": {}, "result": {"status": "failed"}},
                    ["tool", "Query"],
                )
                finalize_turn("first")

                bind_memory_scope("session", "turn-two")
                store.append_context("user", {"user": "second"}, ["user"])
                store.append_context("agent", {"agent_output": "second answer"}, ["agent"])
                finalize_turn("second")

                summaries = store.search_context("", table="cache", limit=10)
            second = next(item for item in summaries if item["key"] == "turn:turn-two")
            self.assertIn("second answer", second["summary"])
            self.assertNotIn("Query", second["summary"])

    def test_markdown_is_authoritative_and_reset_does_not_clear_sqlite(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            store = self._store(home)
            bind_memory_scope("session", "turn")
            store.append_context("user", {"user": "keep short context"}, ["user"])
            result = store.add("user", "喜欢安静的器乐", source="explicit")

            self.assertTrue(result["success"])
            markdown = Path(home, "USER.md").read_text(encoding="utf-8")
            self.assertIn("## Explicit", markdown)
            self.assertIn("<!-- sonex:", markdown)
            self.assertEqual([entry.content for entry in store.load_markdown("user")], ["喜欢安静的器乐"])

            db_path = store.get_db()
            store.reset_long_term()
            self.assertEqual(Path(home, "USER.md").read_text(encoding="utf-8"), "")
            with sqlite3.connect(db_path) as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM context").fetchone()[0], 1)

    def test_disabled_long_term_memory_is_not_retrieved(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            store = self._store(home)
            bind_memory_scope("session", "turn")
            store.add("user", "Prefers jazz")
            store.set_long_term_enabled(False)
            self.assertEqual(store.search_memory("jazz", target="user"), [])

    def test_reset_retains_sqlite_candidate_but_blocks_its_future_promotion(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            store = self._store(home)
            bind_memory_scope("session", "turn-before-reset")
            store.enqueue_memory_candidate("I like jazz")
            db_path = store.get_db()

            store.reset_long_term()

            self.assertFalse(store.memory_candidate_allowed())
            self.assertEqual(store.pending_memory_candidates(), [])
            with sqlite3.connect(db_path) as conn:
                row = conn.execute(
                    "SELECT status FROM memory_candidates WHERE turn_id = ?",
                    ("turn-before-reset",),
                ).fetchone()
            self.assertEqual(row, ("pending",))

    def test_repeated_playback_becomes_evidence_and_survives_long_term_reset(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            store = self._store(home)
            bind_memory_scope("session", "turn")
            track = {"name": "BB88", "artist": "方大同"}
            self.assertEqual(store.record_behavior_signal("played", track), 1)
            self.assertEqual(store.record_behavior_signal("played", track), 2)
            self.assertEqual(store.record_behavior_signal("played", track), 3)
            self.assertEqual(store.promotable_behavior_signals()[0]["count"], 3)

            store.reset_long_term()

            self.assertEqual(store.promotable_behavior_signals(), [])
            with sqlite3.connect(store.get_db()) as conn:
                self.assertEqual(conn.execute("SELECT count FROM behavior_signals").fetchone(), (3,))

    def test_explicit_memory_copy_is_stable(self) -> None:
        operation = explicit_memory_operation("记住：我喜欢 City Pop")
        self.assertIsNotNone(operation)
        assert operation is not None
        self.assertEqual(operation.content, "我喜欢 City Pop")
        self.assertEqual(memory_operation_message(operation), "Memory saved: 我喜欢 City Pop")

    def test_repeated_explicit_memory_refreshes_as_updated(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            store = self._store(home)
            bind_memory_scope("session", "turn-one")
            first = curate_completed_turn("记住：我喜欢 City Pop", store=store)
            bind_memory_scope("session", "turn-two")
            second = curate_completed_turn("记住：我喜欢 City Pop", store=store)

            self.assertEqual(first[0].operation, "add")
            self.assertEqual(second[0].operation, "update")
            self.assertEqual(memory_operation_message(second[0]), "Memory updated: 我喜欢 City Pop")


if __name__ == "__main__":
    unittest.main()
