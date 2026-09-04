"""Regression tests for pure playback queue identity rules."""

from __future__ import annotations

import unittest

from src.tools.playback_queue_state import played_at_value, snapshot_track, track_key


class PlaybackQueueStateTests(unittest.TestCase):
    def test_track_key_prefers_stable_reference(self) -> None:
        self.assertEqual(track_key({"uri": "spotify:track:1", "name": "Song"}), "uri:spotify:track:1")
        self.assertEqual(track_key({"name": "Song", "artist": "Artist", "duration_ms": 1000}), "text:song|artist||1000")
        self.assertEqual(track_key({"name": "Song"}), "")

    def test_snapshot_is_bounded_and_marks_unresolved_tracks(self) -> None:
        snapshot = snapshot_track(
            {"name": "Song", "artist": "Artist", "requires_resolution": True, "url": "https://example.test"},
            played_at=12.5,
        )
        assert snapshot is not None
        self.assertEqual(snapshot["playable"], False)
        self.assertEqual(snapshot["key"], "url:https://example.test")
        self.assertIsNone(snapshot_track({"provider": "youtube"}, played_at=1))

    def test_played_at_accepts_numeric_and_iso_values(self) -> None:
        self.assertEqual(played_at_value(3, 0), 3.0)
        self.assertGreater(played_at_value("2026-06-17T09:17:48Z", 0), 0)
        self.assertEqual(played_at_value("bad", 7), 7)


if __name__ == "__main__":
    unittest.main()
