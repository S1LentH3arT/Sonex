"""Tests playback queue persistence for Sonex playback flows."""

from __future__ import annotations

import os
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from collections.abc import Iterator
from unittest.mock import patch

from src.tools.playback_queue import playback_queue_snapshot, remember_playback_track


@contextmanager
def empty_seed_sources() -> Iterator[None]:
    with patch("src.tools.playback_queue.recent_cached_songs", return_value=[]), patch(
        "src.tools.playback_queue.spotify_recent_tracks_snapshot", return_value=[]
    ), patch("src.tools.playback_queue.apple_recent_tracks_snapshot", return_value=[]):
        yield


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

    def test_first_load_accepts_iso_played_at_from_seed_sources(self) -> None:
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {"SONEX_HOME": home}):
            with patch(
                "src.tools.playback_queue.recent_cached_songs",
                return_value=[{"name": "Cached Song", "artist": "Cached Artist", "played_at": "2026-06-16T15:15:17Z"}],
            ), patch("src.tools.playback_queue.spotify_recent_tracks_snapshot", return_value=[]), patch(
                "src.tools.playback_queue.apple_recent_tracks_snapshot", return_value=[]
            ):
                queue = playback_queue_snapshot()

        self.assertEqual([item["name"] for item in queue], ["Cached Song"])
        self.assertGreater(queue[0]["played_at"], 0)

    def test_persisted_reload_uses_queue_file_instead_of_reseeding(self) -> None:
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {"SONEX_HOME": home}):
            with empty_seed_sources():
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
            with empty_seed_sources():
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
            with empty_seed_sources():
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
            with empty_seed_sources():
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
