"""Tests playback queue persistence for Sonex playback flows."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.tools.playback_queue import (
    playback_queue_snapshot,
    remember_playback_track,
    remove_playback_device_artifact,
)


class PlaybackQueueTests(unittest.TestCase):
    def test_first_load_seeds_from_existing_recent_sources(self) -> None:
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {"SONEX_HOME": home}):
            with patch(
                "src.tools.playback_queue.recent_cached_songs",
                return_value=[{"name": "Cached Song", "artist": "Cached Artist", "duration_ms": 61_000}],
            ), patch(
                "src.tools.playback_queue.spotify_recent_tracks_snapshot",
                return_value=[{"name": "Spotify Song", "artist": "Spotify Artist", "duration_ms": 62_000}],
            ), patch(
                "src.tools.playback_queue.apple_recent_tracks_snapshot",
                return_value=[{"name": "Apple Song", "artist": "Apple Artist", "duration_ms": 63_000}],
            ):
                queue = playback_queue_snapshot()
                queue_path = Path(home) / "cache" / "playback_queue.json"
                self.assertTrue(queue_path.exists())

        self.assertEqual([item["name"] for item in queue], ["Cached Song"])

    def test_seed_queue_accepts_iso_played_at_timestamps(self) -> None:
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {"SONEX_HOME": home}):
            with patch("src.tools.playback_queue.recent_cached_songs", return_value=[]), patch(
                "src.tools.playback_queue.spotify_recent_tracks_snapshot",
                return_value=[
                    {
                        "name": "Spotify Recent",
                        "artist": "Artist",
                        "duration_ms": 62_000,
                        "played_at": "2026-06-17T09:17:48Z",
                    }
                ],
            ), patch("src.tools.playback_queue.apple_recent_tracks_snapshot", return_value=[]):
                queue = playback_queue_snapshot()

        self.assertEqual(queue[0]["name"], "Spotify Recent")
        self.assertGreater(queue[0]["played_at"], 0)

    def test_persisted_reload_uses_queue_file_instead_of_reseeding(self) -> None:
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {"SONEX_HOME": home}):
            remembered = remember_playback_track(
                {
                    "name": "Persisted Song",
                    "artist": "Persisted Artist",
                    "provider": "youtube",
                    "url": "https://example.test/persisted",
                    "duration_ms": 64_000,
                }
            )
            self.assertEqual(remembered[0]["name"], "Persisted Song")

            with patch("src.tools.playback_queue.recent_cached_songs", side_effect=AssertionError("should not reseed")), patch(
                "src.tools.playback_queue.spotify_recent_tracks_snapshot", side_effect=AssertionError("should not reseed")
            ), patch("src.tools.playback_queue.apple_recent_tracks_snapshot", side_effect=AssertionError("should not reseed")):
                queue = playback_queue_snapshot()

        self.assertEqual([item["name"] for item in queue], ["Persisted Song"])

    def test_replayed_track_is_deduped_and_moved_to_front(self) -> None:
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {"SONEX_HOME": home}):
            remember_playback_track(
                {
                    "name": "First Song",
                    "artist": "Artist",
                    "provider": "youtube",
                    "url": "https://example.test/first",
                    "duration_ms": 60_000,
                }
            )
            remember_playback_track(
                {
                    "name": "Second Song",
                    "artist": "Artist",
                    "provider": "youtube",
                    "url": "https://example.test/second",
                    "duration_ms": 61_000,
                }
            )
            queue = remember_playback_track(
                {
                    "name": "First Song",
                    "artist": "Artist",
                    "provider": "youtube",
                    "url": "https://example.test/first",
                    "duration_ms": 60_000,
                }
            )

        self.assertEqual([item["name"] for item in queue], ["First Song", "Second Song"])

    def test_queue_is_newest_first_and_capped_at_10(self) -> None:
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {"SONEX_HOME": home}):
            for idx in range(12):
                remember_playback_track(
                    {
                        "name": f"Song {idx}",
                        "artist": "Artist",
                        "provider": "youtube",
                        "url": f"https://example.test/{idx}",
                        "duration_ms": 60_000 + idx,
                    },
                    now=idx,
                )
            queue = playback_queue_snapshot()

        self.assertEqual(len(queue), 10)
        self.assertEqual(queue[0]["name"], "Song 11")
        self.assertEqual(queue[-1]["name"], "Song 2")

    def test_empty_or_malformed_identity_does_not_update_queue(self) -> None:
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {"SONEX_HOME": home}):
            remember_playback_track(
                {
                    "name": "Valid Song",
                    "artist": "Artist",
                    "provider": "youtube",
                    "url": "https://example.test/valid",
                    "duration_ms": 60_000,
                }
            )
            queue = remember_playback_track({"provider": "youtube"})

        self.assertEqual([item["name"] for item in queue], ["Valid Song"])

    def test_device_like_identity_does_not_update_queue(self) -> None:
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {"SONEX_HOME": home}):
            remember_playback_track(
                {
                    "name": "Valid Song",
                    "artist": "Artist",
                    "provider": "youtube",
                    "url": "https://example.test/valid",
                }
            )
            queue = remember_playback_track(
                {
                    "id": "spotify-device-id",
                    "name": "SILENCE",
                    "artist": "-",
                    "album": "-",
                    "provider": "unknown",
                }
            )

        self.assertEqual([item["name"] for item in queue], ["Valid Song"])

    def test_remove_playback_device_artifact_is_targeted_backed_up_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {"SONEX_HOME": home}):
            queue_path = Path(home) / "cache" / "playback_queue.json"
            queue_path.parent.mkdir(parents=True)
            queue_path.write_text(
                """{
  "version": 1,
  "tracks": [
    {"id": "desktop", "name": "SILENCE", "artist": "-", "album": "-", "provider": "unknown"},
    {"id": "phone", "name": "PHONE", "artist": "-", "album": "-", "provider": "unknown"},
    {"id": "track-id", "name": "Valid Song", "artist": "Artist", "provider": "spotify", "uri": "spotify:track:valid"}
  ]
}
""",
                encoding="utf-8",
            )

            removed = remove_playback_device_artifact("desktop")
            queue = playback_queue_snapshot()
            backup_path = queue_path.with_suffix(".json.bak")
            removed_again = remove_playback_device_artifact("desktop")
            backup_exists = backup_path.exists()
            backup_text = backup_path.read_text(encoding="utf-8")

        self.assertEqual(removed, 1)
        self.assertEqual(removed_again, 0)
        self.assertEqual([item["name"] for item in queue], ["PHONE", "Valid Song"])
        self.assertTrue(backup_exists)
        self.assertIn("SILENCE", backup_text)
