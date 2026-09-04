"""Regression tests for pure cover-source metadata policy."""

from __future__ import annotations

import unittest

from src.tools.cover_source_state import (
    caa_front_endpoints,
    provider_cover_url,
    recording_cover_ids,
    score_recording,
    terms,
)


class CoverSourceStateTests(unittest.TestCase):
    def test_provider_cover_rejects_youtube_thumbnails(self) -> None:
        self.assertEqual(provider_cover_url({"provider": "spotify", "cover_url": "https://img.test/a"}), "https://img.test/a")
        self.assertIsNone(provider_cover_url({"provider": "youtube", "cover_url": "https://i.ytimg.com/vi/a"}))

    def test_recording_ids_and_endpoints_are_deterministic(self) -> None:
        recording = {"releases": [{"release-group": {"id": "group/1"}, "id": "release"}]}
        self.assertEqual(recording_cover_ids(recording), ("group/1", "release"))
        self.assertEqual(
            caa_front_endpoints("group/1", "release"),
            [
                "https://coverartarchive.org/release-group/group/1/front",
                "https://coverartarchive.org/release-group/group/1/front-500",
                "https://coverartarchive.org/release/release/front",
                "https://coverartarchive.org/release/release/front-500",
            ],
        )

    def test_recording_score_uses_title_artist_album_and_provider_score(self) -> None:
        recording = {
            "title": "Song",
            "artist-credit": [{"name": "Artist"}],
            "releases": [{"title": "Album"}],
            "score": 100,
        }
        self.assertEqual(score_recording(recording, name_terms=terms("Song"), artist_terms=terms("Artist"), album_terms=terms("Album")), 10)


if __name__ == "__main__":
    unittest.main()
