"""Regression tests for pure Spotify recent-track projections."""

from __future__ import annotations

import unittest

from src.tools.spotify_recent_state import artists_text, compact_track, query_terms, track_key


class SpotifyRecentStateTests(unittest.TestCase):
    def test_track_key_and_artist_projection(self) -> None:
        self.assertEqual(track_key({"uri": "spotify:track:1", "id": "1"}), "spotify:track:1")
        self.assertEqual(track_key({"name": "No ref"}), None)
        self.assertEqual(artists_text([{"name": "A"}, {"name": "B"}, {}]), "A, B")

    def test_compact_track_preserves_legacy_aliases(self) -> None:
        result = compact_track(
            {
                "title": "Song",
                "artists": [{"name": "Artist"}],
                "cover_url": "https://example.test/cover.jpg",
                "played_at": "2026-01-01",
            }
        )
        self.assertEqual(result["name"], "Song")
        self.assertEqual(result["artist"], "Artist")
        self.assertEqual(result["album_cover_url"], "https://example.test/cover.jpg")
        self.assertEqual(result["last_played_at"], "2026-01-01")

    def test_query_terms_are_case_insensitive_and_bounded_to_words(self) -> None:
        self.assertEqual(query_terms("  Artist - Song! "), ["artist", "song"])


if __name__ == "__main__":
    unittest.main()
