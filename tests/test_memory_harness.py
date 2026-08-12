from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.memory.curator import (
    _classify_explicit_target,
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

    def test_runtime_entries_round_trip_through_clean_markdown_and_index(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            store = self._store(home)
            bind_memory_scope("session", "turn")
            store.append_context("user", {"user": "keep short context"}, ["user"])
            result = store.add("user", "喜欢安静的器乐", source="explicit")

            self.assertTrue(result["success"])
            markdown = Path(home, "USER.md").read_text(encoding="utf-8")
            self.assertEqual(markdown, "# User memory\n\n- 喜欢安静的器乐\n")
            self.assertNotIn("<!-- sonex:", markdown)
            self.assertEqual([entry.content for entry in store.entries("user")], ["喜欢安静的器乐"])
            self.assertTrue(Path(home, "memory-index.json").exists())

            db_path = store.get_db()
            store.reset_long_term()
            self.assertEqual(Path(home, "USER.md").read_text(encoding="utf-8"), "# User memory\n")
            self.assertEqual(len(store.dump_entries()), 1)
            with sqlite3.connect(db_path) as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM context").fetchone()[0], 1)

    def test_multiline_entry_round_trips_without_markdown_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            store = self._store(home)
            bind_memory_scope("session", "turn")
            result = store.add("memory", "Uses local playback.\nPrefer ncm-cli when available.")

            self.assertTrue(result["success"])
            markdown = Path(home, "MEMORY.md").read_text(encoding="utf-8")
            self.assertIn("- Uses local playback.\n  Prefer ncm-cli when available.", markdown)
            reloaded = self._store(home)
            bind_memory_scope("session-reload", "turn")
            reloaded.init_session("session-reload")
            self.assertEqual(
                reloaded.entries("memory")[0].content,
                "Uses local playback.\nPrefer ncm-cli when available.",
            )

    def test_forget_hides_entry_and_recall_restores_stable_identity(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            store = self._store(home)
            bind_memory_scope("session", "turn")
            store.add("user", "Prefers City Pop")
            entry = store.entries("user")[0]

            forgotten = store.forget(entry.entry_id, retention_days=7, reason="user")
            self.assertTrue(forgotten["success"])
            self.assertEqual(store.entries("user"), [])
            self.assertEqual(store.search_memory("City Pop", target="user"), [])
            self.assertEqual(store.dump_entries()[0]["entry"]["entry_id"], entry.entry_id)

            recalled = store.recall(entry.entry_id)
            self.assertTrue(recalled["success"])
            self.assertEqual(store.entries("user")[0].entry_id, entry.entry_id)
            self.assertTrue(store.entries("user")[0].protected)

    def test_format_moves_all_entries_to_dump_in_one_recoverable_state(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            store = self._store(home)
            bind_memory_scope("session", "turn")
            store.add("user", "Prefers jazz")
            store.add("memory", "Use local playback")

            result = store.format_memory("all")

            self.assertEqual(result["count"], 2)
            self.assertEqual(store.entries("user"), [])
            self.assertEqual(store.entries("memory"), [])
            self.assertEqual({item["reason"] for item in store.dump_entries()}, {"format"})
            self.assertIsNotNone(store.reset_epoch())

    def test_dump_tombstones_survive_later_forget_and_recall(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            store = self._store(home)
            bind_memory_scope("session", "turn")
            store.add("user", "Prefers jazz")
            entry = store.entries("user")[0]
            store._atomic_write(
                store.paths.dump,
                json.dumps({"version": 1, "entries": [], "tombstones": [{"entry_id": "expired"}]}) + "\n",
            )

            store.forget(entry.entry_id)
            store.recall(entry.entry_id)

            dump = json.loads(store.paths.dump.read_text(encoding="utf-8"))
            self.assertEqual(dump["tombstones"], [{"entry_id": "expired"}])

    def test_corrupt_index_is_read_only_until_explicit_rebuild(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            first = self._store(home)
            bind_memory_scope("session", "turn")
            first.add("user", "Prefers jazz")
            first._lock_handle.close()
            Path(home, "memory-index.json").write_text("{broken", encoding="utf-8")

            second = self._store(home)
            bind_memory_scope("session-two", "turn")
            second.init_session("session-two")

            self.assertEqual(second._read_only_reason, "metadata_corrupt")
            self.assertFalse(second.add("user", "Prefers rock")["success"])
            rebuilt = second.rebuild_internal_metadata()
            self.assertTrue(rebuilt["success"])
            self.assertTrue(Path(home, "memory-index.json").exists())
            self.assertEqual(second.entries("user")[0].content, "Prefers jazz")
            self.assertTrue(list(Path(home).glob("memory-index.json.corrupt-*.bak")))

    def test_user_edits_reject_credential_material(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            store = self._store(home)
            bind_memory_scope("session", "turn")

            result = store.add("user", "api_key=sk-example", source="explicit")

            self.assertFalse(result["success"])
            self.assertEqual(store.entries("user"), [])

    def test_numeric_settings_accept_custom_values_and_unlimited(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            store = self._store(home)
            bind_memory_scope("session", "turn")

            first = store.update_settings({"user_capacity": "137", "user_refinement_window": "17"})
            second = store.update_settings({"user_capacity": "Unlimited"})

            self.assertTrue(first["success"])
            self.assertEqual(first["settings"]["user_capacity"], 137)
            self.assertEqual(first["settings"]["user_refinement_window"], 17)
            self.assertIsNone(second["settings"]["user_capacity"])

    def test_curator_candidates_stop_retrying_after_three_failures(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            store = self._store(home)
            bind_memory_scope("session", "turn")
            store.enqueue_memory_candidate("I prefer jazz")

            store.mark_memory_candidate_failure()
            self.assertEqual(len(store.pending_memory_candidates()), 1)
            store.mark_memory_candidate_failure()
            self.assertEqual(len(store.pending_memory_candidates()), 1)
            store.mark_memory_candidate_failure()

            self.assertEqual(store.pending_memory_candidates(), [])
            with sqlite3.connect(store.get_db()) as conn:
                self.assertEqual(
                    conn.execute(
                        "SELECT status, attempts FROM memory_candidates WHERE turn_id = 'turn'"
                    ).fetchone(),
                    ("failed", 3),
                )

    def test_capacity_warning_is_emitted_once_per_day_at_eighty_percent(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            store = self._store(home)
            bind_memory_scope("session", "turn")
            store.update_settings({"memory_capacity": 5})
            for index in range(4):
                store.add("memory", f"Inferred {index}", source="inferred")

            first = store.capacity_warnings()
            second = store.capacity_warnings()

            self.assertEqual(len(first), 1)
            self.assertIn("4/5 entries", first[0])
            self.assertEqual(second, [])

    def test_explicit_target_classifier_never_rewrites_content(self) -> None:
        response = type(
            "Response",
            (),
            {"tool_calls": [type("Call", (), {"arguments": {"target": "memory"}})()]},
        )()
        client = type("Client", (), {"generate": lambda _self, _request: response})()

        with patch("src.memory.curator.ThinkingConfig.get_client", return_value=client), \
             patch("src.memory.curator.ThinkingConfig.get_model", return_value="test"):
            target = _classify_explicit_target("Always verify playback before reporting success")

        self.assertEqual(target, "memory")

    def test_revision_history_is_bounded_and_restorable(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            store = self._store(home)
            bind_memory_scope("session", "turn")
            store.add("user", "Version 0")
            entry_id = store.entries("user")[0].entry_id
            for index in range(1, 23):
                store.update("user", f"Version {index}", previous_content=f"Version {index - 1}")

            revisions = store.revisions(entry_id)
            self.assertEqual(len(revisions), 20)
            restored = store.restore_revision(entry_id, 0)
            self.assertTrue(restored["success"])
            self.assertEqual(store.entries("user")[0].content, "Version 2")
            self.assertTrue(store.entries("user")[0].protected)

    def test_offline_addition_is_imported_as_protected_memory(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            first = self._store(home)
            bind_memory_scope("session", "turn")
            first.add("user", "Prefers jazz")
            first._lock_handle.close()

            Path(home, "USER.md").write_text(
                "# User memory\n\n- Prefers jazz\n\n- Prefers short answers\n",
                encoding="utf-8",
            )
            second = self._store(home)
            bind_memory_scope("session-two", "turn")
            second.init_session("session-two")

            self.assertEqual(len(second.entries("user")), 2)
            self.assertTrue(second.entries("user")[1].protected)

    def test_offline_insertion_keeps_existing_entry_identity(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            first = self._store(home)
            bind_memory_scope("session", "turn")
            first.add("user", "Prefers jazz")
            existing_id = first.entries("user")[0].entry_id
            first._lock_handle.close()

            Path(home, "USER.md").write_text(
                "# User memory\n\n- Prefers short answers\n\n- Prefers jazz\n",
                encoding="utf-8",
            )
            second = self._store(home)
            bind_memory_scope("session-two", "turn")
            second.init_session("session-two")

            self.assertEqual(second.entries("user")[1].entry_id, existing_id)
            self.assertNotEqual(second.entries("user")[0].entry_id, existing_id)

    def test_offline_deletion_moves_entry_to_memory_dump(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            first = self._store(home)
            bind_memory_scope("session", "turn")
            first.add("user", "Prefers jazz")
            entry_id = first.entries("user")[0].entry_id
            first._lock_handle.close()

            Path(home, "USER.md").write_text("# User memory\n", encoding="utf-8")
            second = self._store(home)
            bind_memory_scope("session-two", "turn")
            second.init_session("session-two")

            self.assertEqual(second.entries("user"), [])
            self.assertEqual(second.dump_entries()[0]["entry"]["entry_id"], entry_id)
            self.assertEqual(second.dump_entries()[0]["reason"], "offline deletion")

    def test_second_store_becomes_read_only_while_writer_lock_is_held(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            writer = self._store(home)
            bind_memory_scope("writer", "turn")
            writer.add("user", "Prefers jazz")

            reader = self._store(home)
            bind_memory_scope("reader", "turn")
            reader.init_session("reader")

            self.assertEqual(reader.entries("user")[0].content, "Prefers jazz")
            self.assertFalse(reader.add("user", "Prefers rock")["success"])

    def test_automatic_forgetting_never_moves_protected_memory(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            store = self._store(home)
            bind_memory_scope("session", "turn")
            store.add("memory", "Old inferred workflow", source="inferred", confidence=0.2)
            store.add("memory", "Old protected workflow", source="explicit")
            old = "2020-01-01T00:00:00+00:00"
            store._entries["memory"][0] = store._entry_from_dict({
                **store._entry_to_dict(store._entries["memory"][0]),
                "created_at": old,
                "updated_at": old,
            })
            store._entries["memory"][1] = store._entry_from_dict({
                **store._entry_to_dict(store._entries["memory"][1]),
                "created_at": old,
                "updated_at": old,
            })
            store._commit_runtime()
            store.update_settings({"automatic_forgetting": "idle", "idle_threshold_days": 7})

            forgotten = store.run_maintenance()

            self.assertEqual([entry.content for entry in forgotten], ["Old inferred workflow"])
            self.assertEqual([entry.content for entry in store.entries("memory")], ["Old protected workflow"])

    def test_capacity_pressure_cleans_to_ninety_percent_of_soft_target(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            store = self._store(home)
            bind_memory_scope("session", "turn")
            for index in range(10):
                store.add("memory", f"Inferred {index}", source="inferred", confidence=0.5)
            store.update_settings({"automatic_forgetting": "capacity", "memory_capacity": 10})

            forgotten = store.run_maintenance()

            self.assertEqual(len(forgotten), 1)
            self.assertEqual(len(store.entries("memory")), 9)

    def test_long_term_memory_cannot_be_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            store = self._store(home)
            bind_memory_scope("session", "turn")
            store.add("user", "Prefers jazz")
            store.set_long_term_enabled(False)
            self.assertTrue(store.long_term_enabled())
            self.assertEqual(store.search_memory("jazz", target="user")[0]["content"], "Prefers jazz")

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

    def test_repeated_explicit_memory_is_a_deduplicated_noop(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            store = self._store(home)
            bind_memory_scope("session", "turn-one")
            first = curate_completed_turn("记住：我喜欢 City Pop", store=store)
            bind_memory_scope("session", "turn-two")
            second = curate_completed_turn("记住：我喜欢 City Pop", store=store)

            self.assertEqual(first[0].operation, "add")
            self.assertEqual(second[0].operation, "noop")
            self.assertEqual(memory_operation_message(second[0]), "Memory already exists: 我喜欢 City Pop")
            self.assertEqual(store.revisions(store.entries("user")[0].entry_id), [])


if __name__ == "__main__":
    unittest.main()
