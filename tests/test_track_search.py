"""Tests test track search.

Contains pytest coverage for the test track search behavior.
"""

from __future__ import annotations

import json
import unittest
from urllib.error import HTTPError
from unittest.mock import patch

import src.tools.track_search as track_search


class FakeResponse:
    """Groups fake response tests.

    Collects related assertions for fake response behavior.
    """
    def __init__(self, payload: dict) -> None:
        """Validate init.

        Exercises the init behavior through the test suite.

        Args:
            payload: Pytest fixture or input used by this test.
        """
        self.payload = payload

    def __enter__(self) -> "FakeResponse":
        """Validate enter.

        Exercises the enter behavior through the test suite.
        """
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        """Validate exit.

        Exercises the exit behavior through the test suite.

        Args:
            exc_type: Pytest fixture or input used by this test.
            exc: Pytest fixture or input used by this test.
            tb: Pytest fixture or input used by this test.
        """
        return None

    def read(self, size: int = -1) -> bytes:
        """Validate read.

        Exercises the read behavior through the test suite.

        Args:
            size: Pytest fixture or input used by this test.
        """
        return json.dumps(self.payload).encode("utf-8")


class TrackSearchTests(unittest.TestCase):
    """Groups track search tests tests.

    Collects related assertions for track search tests behavior.
    """
    def test_itunes_normalizes_metadata_candidates(self) -> None:
        """Validate test itunes normalizes metadata candidates.

        Exercises the test itunes normalizes metadata candidates behavior through the test suite.
        """
        payload = {
            "results": [
                {
                    "trackId": 123,
                    "trackName": "Canonical Song",
                    "artistName": "Canonical Artist",
                    "collectionName": "Canonical Album",
                    "trackTimeMillis": 201000,
                    "artworkUrl100": "https://is1-ssl.mzstatic.com/image/100x100bb.jpg",
                    "trackViewUrl": "https://music.apple.com/us/song/canonical-song/123",
                }
            ]
        }

        with patch("src.tools.track_search.urlopen", return_value=FakeResponse(payload)) as urlopen:
            result = track_search.search_track_metadata_candidates("messy query", limit=5, country="JP")

        self.assertEqual(len(result["candidates"]), 1)
        candidate = result["candidates"][0]
        self.assertEqual(candidate["metadata_source"], "itunes")
        self.assertEqual(candidate["provider"], "itunes")
        self.assertEqual(candidate["id"], "123")
        self.assertEqual(candidate["name"], "Canonical Song")
        self.assertEqual(candidate["artist"], "Canonical Artist")
        self.assertEqual(candidate["artists"], ["Canonical Artist"])
        self.assertEqual(candidate["album"], "Canonical Album")
        self.assertEqual(candidate["duration_ms"], 201000)
        self.assertEqual(candidate["album_cover_url"], "https://is1-ssl.mzstatic.com/image/100x100bb.jpg")
        self.assertEqual(candidate["itunes_url"], "https://music.apple.com/us/song/canonical-song/123")
        self.assertEqual(candidate["url"], "https://music.apple.com/us/song/canonical-song/123")
        self.assertEqual(candidate["uri"], "itunes:track:123")
        self.assertEqual(candidate["original_query"], "messy query")
        self.assertEqual(candidate["youtube_query"], "Canonical Artist Canonical Song")
        self.assertEqual(result["source_attempts"][0]["provider"], "itunes")
        self.assertEqual(result["source_attempts"][0]["status"], "success")
        self.assertEqual(result["source_attempts"][0]["candidate_count"], 1)
        requested_url = urlopen.call_args_list[0].args[0].full_url
        self.assertIn("country=JP", requested_url)
        self.assertIn("media=music", requested_url)
        self.assertIn("entity=song", requested_url)

    def test_deezer_and_musicbrainz_fill_to_five_with_dedupe(self) -> None:
        """Validate test deezer and musicbrainz fill to five with dedupe.

        Exercises the test deezer and musicbrainz fill to five with dedupe behavior through the test suite.
        """
        payloads = [
            {
                "results": [
                    {
                        "trackId": 1,
                        "trackName": "Song One",
                        "artistName": "Artist One",
                        "collectionName": "Album One",
                    },
                    {
                        "trackId": 2,
                        "trackName": "Song Two",
                        "artistName": "Artist Two",
                        "collectionName": "Album Two",
                    },
                ]
            },
            {
                "data": [
                    {
                        "id": 20,
                        "title": "Song Two",
                        "duration": 180,
                        "link": "https://deezer.page/track/20",
                        "artist": {"name": "Artist Two"},
                        "album": {"title": "Album Two", "cover_medium": "https://deezer.cover/two.jpg"},
                    },
                    {
                        "id": 30,
                        "title": "Song Three",
                        "duration": 181,
                        "link": "https://deezer.page/track/30",
                        "artist": {"name": "Artist Three"},
                        "album": {"title": "Album Three", "cover_medium": "https://deezer.cover/three.jpg"},
                    },
                ]
            },
            {
                "recordings": [
                    {
                        "id": "mbid-3",
                        "title": "Song Three",
                        "length": "181000",
                        "artist-credit": [{"name": "Artist Three"}],
                        "releases": [{"title": "Album Three"}],
                    },
                    {
                        "id": "mbid-4",
                        "title": "Song Four",
                        "length": "182000",
                        "artist-credit": [{"name": "Artist Four"}],
                        "releases": [{"title": "Album Four"}],
                    },
                    {
                        "id": "mbid-5",
                        "title": "Song Five",
                        "length": "183000",
                        "artist-credit": [{"name": "Artist Five"}],
                        "releases": [{"title": "Album Five"}],
                    },
                ]
            },
        ]

        def fake_urlopen(request, timeout=0):
            """Validate fake urlopen.

            Exercises the fake urlopen behavior through the test suite.

            Args:
                request: Pytest fixture or input used by this test.
                timeout: Pytest fixture or input used by this test.
            """
            return FakeResponse(payloads.pop(0))

        with patch("src.tools.track_search.urlopen", side_effect=fake_urlopen), \
             patch("src.tools.track_search.time.sleep"):
            result = track_search.search_track_metadata_candidates("Song", limit=5)

        self.assertEqual(
            [(item["provider"], item["name"], item["artist"]) for item in result["candidates"]],
            [
                ("itunes", "Song One", "Artist One"),
                ("itunes", "Song Two", "Artist Two"),
                ("deezer", "Song Three", "Artist Three"),
                ("musicbrainz", "Song Four", "Artist Four"),
                ("musicbrainz", "Song Five", "Artist Five"),
            ],
        )
        self.assertEqual([attempt["provider"] for attempt in result["source_attempts"]], ["itunes", "deezer", "musicbrainz"])

    def test_itunes_rate_limit_is_sanitized_and_deezer_still_runs(self) -> None:
        """Validate test itunes rate limit is sanitized and deezer still runs.

        Exercises the test itunes rate limit is sanitized and deezer still runs behavior through the test suite.
        """
        rate_limit = HTTPError(
            "https://itunes.apple.com/search",
            429,
            "Too Many Requests",
            {},
            None,
        )
        deezer_payload = {
            "data": [
                {
                    "id": 77,
                    "title": "Fallback Song",
                    "duration": 200,
                    "artist": {"name": "Fallback Artist"},
                    "album": {"title": "Fallback Album"},
                }
            ]
        }

        with patch("src.tools.track_search.urlopen", side_effect=[rate_limit, FakeResponse(deezer_payload), FakeResponse({"recordings": []})]):
            result = track_search.search_track_metadata_candidates("Fallback", limit=5)

        self.assertEqual(result["candidates"][0]["provider"], "deezer")
        self.assertEqual(result["source_attempts"][0]["provider"], "itunes")
        self.assertEqual(result["source_attempts"][0]["status"], "rate_limited")
        self.assertNotIn("https://", result["source_attempts"][0]["message"])


if __name__ == "__main__":
    unittest.main()
