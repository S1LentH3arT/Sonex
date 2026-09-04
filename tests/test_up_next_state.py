from __future__ import annotations

import unittest

from src.tools.up_next_state import (
    append_up_next_state,
    coerce_up_next_state,
    consume_up_next_head_state,
    fail_up_next_head_state,
)


class UpNextStateTests(unittest.TestCase):
    def test_coerce_state_bounds_revision_and_items(self) -> None:
        state = coerce_up_next_state({"revision": "bad", "items": ["invalid"], "failed": []})
        self.assertEqual(state, {"revision": 0, "items": [], "failed": []})
        self.assertEqual(coerce_up_next_state({"items": None, "failed": None}), {"revision": 0, "items": [], "failed": []})

    def test_append_is_idempotent_and_does_not_mutate_input(self) -> None:
        original = {"revision": 3, "items": [], "failed": []}
        track = {"ref": "spotify:track:1", "playable": True, "name": "Song"}
        appended = append_up_next_state(original, track)
        duplicate = append_up_next_state(appended, track)
        self.assertEqual(original["items"], [])
        self.assertEqual(appended["items"], [track])
        self.assertIs(duplicate, appended)

    def test_consume_and_fail_move_only_the_head(self) -> None:
        state = {
            "revision": 1,
            "items": [
                {"ref": "one", "playable": True},
                {"ref": "two", "playable": True},
            ],
            "failed": [],
        }
        consumed = consume_up_next_head_state(state)
        failed = fail_up_next_head_state(state, "unavailable", failed_at=12.5)
        self.assertEqual([item["ref"] for item in consumed["items"]], ["two"])
        self.assertEqual([item["ref"] for item in failed["items"]], ["two"])
        self.assertEqual(failed["failed"][0]["failure_reason"], "unavailable")
        self.assertEqual(failed["failed"][0]["failed_at"], 12.5)


if __name__ == "__main__":
    unittest.main()
