"""Tests playlist persistence behavior for Sonex music flows."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.tools.playlists import (
    list_playlist_tracks,
    list_playlists,
    playlist_choices,
    save_track_to_playlist,
    track_in_playlist,
)


class PlaylistStoreTests(unittest.TestCase):
    def test_likes_exists_by_default_and_duplicate_saves_are_noops(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            track = {
                "cache_id": "track_1",
                "name": "Orange Moon",
                "artist": "Khalil Fong",
                "album": "Orange Moon",
                "duration_ms": 240000,
                "provider": "youtube",
            }

            first = save_track_to_playlist(track, playlist_name="likes", playlists_root=root, now=10)
            second = save_track_to_playlist(track, playlist_name="likes", playlists_root=root, now=20)

            self.assertTrue(first["added"])
            self.assertFalse(second["added"])
            self.assertEqual(second["playlist"]["name"], "likes")
            self.assertEqual([playlist["name"] for playlist in list_playlists(playlists_root=root)], ["likes"])
            tracks = list_playlist_tracks("likes", playlists_root=root)
            self.assertEqual(len(tracks), 1)
            self.assertEqual(tracks[0]["name"], "Orange Moon")
            self.assertEqual(tracks[0]["saved_at"], 10)

    def test_user_playlist_is_created_and_choices_default_to_likes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            save_track_to_playlist(
                {"name": "Song A", "artist": "Artist A", "album": "-", "provider": "spotify"},
                playlist_name="road trip",
                playlists_root=root,
                now=1,
            )

            playlists = list_playlists(playlists_root=root)
            self.assertEqual([playlist["name"] for playlist in playlists], ["likes", "road trip"])
            choices = playlist_choices(playlists_root=root)
            self.assertEqual(choices[0]["value"], "playlist:likes")
            self.assertEqual(choices[0]["label"], "likes")
            self.assertEqual(choices[1]["value"], "playlist:road trip")

    def test_track_in_playlist_matches_saved_likes_track_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            track = {
                "cache_id": "track_1",
                "name": "Orange Moon",
                "artist": "Khalil Fong",
                "album": "Orange Moon",
                "duration_ms": 240000,
                "provider": "youtube",
            }
            save_track_to_playlist(track, playlist_name="likes", playlists_root=root, now=10)
            before = {path.name: path.stat().st_mtime_ns for path in root.glob("*.json")}

            self.assertTrue(track_in_playlist(track, playlist_name="likes", playlists_root=root))
            self.assertFalse(track_in_playlist({**track, "cache_id": "track_2", "name": "Blue Moon"}, playlist_name="likes", playlists_root=root))

            after = {path.name: path.stat().st_mtime_ns for path in root.glob("*.json")}
            self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
