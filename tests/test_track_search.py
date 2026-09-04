"""Tests test track search.

Contains pytest coverage for the test track search behavior.
"""

from __future__ import annotations

import json
import os
import urllib.parse
import unittest
from urllib.error import HTTPError
from unittest.mock import patch

import src.tools.track_search as track_search


class FakeResponse:
    """Groups related response cases.

    Collects assertions that exercise response behavior without mixing unrelated fixtures.
    """
    def __init__(self, payload: dict) -> None:
        """Verifies that init behaves as expected.

        Typical use: Use this in automated tests when guarding the init behavior against regressions.

        Example: __init__() -> passes without assertion failures when the behavior remains correct.
        """
        self.payload = payload

    def __enter__(self) -> "FakeResponse":
        """Verifies that enter behaves as expected.

        Typical use: Use this in automated tests when guarding the enter behavior against regressions.

        Example: __enter__() -> passes without assertion failures when the behavior remains correct.
        """
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        """Verifies that exit behaves as expected.

        Typical use: Use this in automated tests when guarding the exit behavior against regressions.

        Example: __exit__() -> passes without assertion failures when the behavior remains correct.
        """
        return None

    def read(self, size: int = -1) -> bytes:
        """Verifies that read behaves as expected.

        Typical use: Use this in automated tests when guarding the read behavior against regressions.

        Example: read() -> passes without assertion failures when the behavior remains correct.
        """
        return json.dumps(self.payload).encode("utf-8")


class TrackSearchTests(unittest.TestCase):
    """Groups related track search tests cases.

    Collects assertions that exercise track search tests behavior without mixing unrelated fixtures.
    """
    def test_itunes_normalizes_metadata_candidates(self) -> None:
        """Verifies that itunes normalizes metadata candidates behaves as expected.

        Typical use: Use this in automated tests when guarding the itunes normalizes metadata candidates behavior against regressions.

        Example: test_itunes_normalizes_metadata_candidates() -> passes without assertion failures when the behavior remains correct.
        """
        payload = {
            "results": [
                {
                    "trackId": 123,
                    "trackName": "Canonical Song",
                    "artistName": "Canonical Artist",
                    "collectionName": "Canonical Album",
                    "collectionId": 456,
                    "artistId": 789,
                    "trackTimeMillis": 201000,
                    "isrc": "USRC17607839",
                    "previewUrl": "https://audio-ssl.itunes.apple.com/preview.m4a",
                    "releaseDate": "1976-01-01T08:00:00Z",
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
        self.assertEqual(candidate["isrc"], "USRC17607839")
        self.assertEqual(candidate["preview_url"], "https://audio-ssl.itunes.apple.com/preview.m4a")
        self.assertEqual(candidate["release_date"], "1976-01-01T08:00:00Z")
        self.assertEqual(candidate["release_year"], "1976")
        self.assertEqual(candidate["album_id"], "456")
        self.assertEqual(candidate["artist_id"], "789")
        self.assertEqual(candidate["album_cover_url"], "https://is1-ssl.mzstatic.com/image/100x100bb.jpg")
        self.assertEqual(candidate["itunes_url"], "https://music.apple.com/us/song/canonical-song/123")
        self.assertEqual(candidate["url"], "https://music.apple.com/us/song/canonical-song/123")
        self.assertEqual(candidate["uri"], "itunes:track:123")
        self.assertEqual(candidate["original_query"], "messy query")
        self.assertEqual(candidate["youtube_query"], "Canonical Artist Canonical Song")
        self.assertEqual(result["source_attempts"][0]["provider"], "itunes")
        self.assertEqual(result["source_attempts"][0]["status"], "success")
        self.assertEqual(result["source_attempts"][0]["candidate_count"], 1)
        self.assertEqual(result["source_attempts"][0]["countries"], ["JP"])
        self.assertEqual(candidate["itunes_country"], "JP")
        requested_url = urlopen.call_args_list[0].args[0].full_url
        self.assertIn("country=JP", requested_url)
        self.assertIn("media=music", requested_url)
        self.assertIn("entity=song", requested_url)

    def test_itunes_uses_chinese_region_order_for_cjk_queries(self) -> None:
        payloads = [
            {"results": []},
            {"results": []},
            {"results": []},
            {"results": [
                {
                    "trackId": 1,
                    "trackName": "忘了美丽",
                    "artistName": "方大同",
                    "collectionName": "未来",
                }
            ]},
        ]

        def fake_urlopen(request, timeout=0):
            return FakeResponse(payloads.pop(0))

        with patch.dict(os.environ, {"SONEX_ITUNES_COUNTRY": "", "SONEX_ITUNES_COUNTRIES": ""}), \
             patch("src.tools.track_search.urlopen", side_effect=fake_urlopen) as urlopen, \
             patch("src.tools.track_search.time.sleep"):
            result = track_search.search_track_metadata_candidates("方大同 忘了美丽", limit=5)

        requested = [
            urllib.parse.parse_qs(urllib.parse.urlparse(call.args[0].full_url).query)["country"][0]
            for call in urlopen.call_args_list
            if "itunes.apple.com" in call.args[0].full_url
        ]
        self.assertEqual(requested[:4], ["TW", "HK", "CN", "US"])
        self.assertEqual(result["candidates"][0]["itunes_country"], "US")
        self.assertEqual(result["source_attempts"][0]["countries"], ["TW", "HK", "CN", "US"])

    def test_itunes_uses_us_first_region_order_for_non_cjk_queries(self) -> None:
        payloads = [
            {"results": []},
            {"results": []},
            {"results": []},
            {"results": []},
            {"data": []},
            {"recordings": []},
        ]

        def fake_urlopen(request, timeout=0):
            return FakeResponse(payloads.pop(0))

        with patch.dict(os.environ, {"SONEX_ITUNES_COUNTRY": "", "SONEX_ITUNES_COUNTRIES": ""}), \
             patch("src.tools.track_search.urlopen", side_effect=fake_urlopen) as urlopen, \
             patch("src.tools.track_search.time.sleep"):
            track_search.search_track_metadata_candidates("Khalil Fong Beautiful", limit=5)

        requested = [
            urllib.parse.parse_qs(urllib.parse.urlparse(call.args[0].full_url).query).get("country", [""])[0]
            for call in urlopen.call_args_list[:4]
        ]
        self.assertEqual(requested, ["US", "TW", "HK", "CN"])

    def test_itunes_countries_env_uses_exact_order(self) -> None:
        payloads = [
            {"results": []},
            {"results": [
                {
                    "trackId": 2,
                    "trackName": "Song",
                    "artistName": "Artist",
                    "collectionName": "Album",
                }
            ]},
        ]

        def fake_urlopen(request, timeout=0):
            return FakeResponse(payloads.pop(0))

        with patch.dict(os.environ, {"SONEX_ITUNES_COUNTRIES": "HK,TW", "SONEX_ITUNES_COUNTRY": ""}), \
             patch("src.tools.track_search.urlopen", side_effect=fake_urlopen) as urlopen:
            result = track_search.search_track_metadata_candidates("Song", limit=5)

        requested = [
            urllib.parse.parse_qs(urllib.parse.urlparse(call.args[0].full_url).query)["country"][0]
            for call in urlopen.call_args_list
            if "itunes.apple.com" in call.args[0].full_url
        ]
        self.assertEqual(requested, ["HK", "TW"])
        self.assertEqual(result["source_attempts"][0]["countries"], ["HK", "TW"])

    def test_itunes_country_env_remains_single_region_override(self) -> None:
        with patch.dict(os.environ, {"SONEX_ITUNES_COUNTRY": "JP", "SONEX_ITUNES_COUNTRIES": "HK,TW"}), \
             patch("src.tools.track_search.urlopen", return_value=FakeResponse({"results": []})) as urlopen, \
             patch("src.tools.track_search.time.sleep"):
            track_search.search_track_metadata_candidates("Song", limit=5)

        requested = [
            urllib.parse.parse_qs(urllib.parse.urlparse(call.args[0].full_url).query).get("country", [""])[0]
            for call in urlopen.call_args_list
        ]
        self.assertEqual(requested[0], "JP")
        self.assertNotIn("HK", requested)
        self.assertNotIn("TW", requested)

    def test_itunes_multi_region_dedupes_before_applying_limit(self) -> None:
        payloads = [
            {"results": [
                {"trackId": 1, "trackName": "Song One", "artistName": "Artist", "collectionName": "Album"},
                {"trackId": 2, "trackName": "Song Two", "artistName": "Artist", "collectionName": "Album"},
            ]},
            {"results": [
                {"trackId": 20, "trackName": "Song One", "artistName": "Artist", "collectionName": "Album"},
                {"trackId": 3, "trackName": "Song Three", "artistName": "Artist", "collectionName": "Album"},
            ]},
            {"results": []},
            {"results": []},
        ]

        def fake_urlopen(request, timeout=0):
            return FakeResponse(payloads.pop(0))

        with patch.dict(os.environ, {"SONEX_ITUNES_COUNTRY": "", "SONEX_ITUNES_COUNTRIES": ""}), \
             patch("src.tools.track_search.urlopen", side_effect=fake_urlopen) as urlopen:
            result = track_search.search_track_metadata_candidates("Song", limit=3)

        self.assertEqual([item["id"] for item in result["candidates"]], ["1", "2", "3"])
        self.assertEqual([item["itunes_country"] for item in result["candidates"]], ["US", "US", "TW"])
        self.assertEqual(len(urlopen.call_args_list), 4)

    def test_itunes_candidates_sort_simplified_then_traditional_then_english(self) -> None:
        payloads = [
            {"results": [
                {"trackId": 1, "trackName": "忘了美麗", "artistName": "方大同", "collectionName": "未來"},
            ]},
            {"results": []},
            {"results": [
                {"trackId": 2, "trackName": "忘了美丽", "artistName": "方大同", "collectionName": "未来"},
            ]},
            {"results": [
                {"trackId": 3, "trackName": "Forgotten Beauty", "artistName": "Khalil Fong", "collectionName": "Future"},
            ]},
        ]

        def fake_urlopen(request, timeout=0):
            return FakeResponse(payloads.pop(0))

        with patch.dict(os.environ, {"SONEX_ITUNES_COUNTRY": "", "SONEX_ITUNES_COUNTRIES": ""}), \
             patch("src.tools.track_search.urlopen", side_effect=fake_urlopen):
            result = track_search.search_track_metadata_candidates("方大同 忘了美丽", limit=3)

        self.assertEqual([item["name"] for item in result["candidates"]], [
            "忘了美丽",
            "忘了美麗",
            "Forgotten Beauty",
        ])

    def test_itunes_query_match_outranks_album_script_when_original_artist_is_requested(self) -> None:
        payloads = [
            {"results": [
                {
                    "trackId": 1,
                    "trackName": "特別的人",
                    "artistName": "方大同",
                    "collectionName": "危險世界",
                },
                {
                    "trackId": 2,
                    "trackName": "特别的人 (女聲版)",
                    "artistName": "王一只",
                    "collectionName": "特别的人 (女聲版) - Single",
                },
            ]},
            {"results": []},
            {"results": [
                {
                    "trackId": 3,
                    "trackName": "特别的人",
                    "artistName": "方大同",
                    "collectionName": "危險世界",
                },
                {
                    "trackId": 4,
                    "trackName": "特别的人",
                    "artistName": "李莹小熊",
                    "collectionName": "稍尽春风",
                },
                {
                    "trackId": 5,
                    "trackName": "特别的人 (女声版)",
                    "artistName": "王一只",
                    "collectionName": "特别的人 (女声版) - Single",
                },
                {
                    "trackId": 6,
                    "trackName": "特别的人",
                    "artistName": "吴映香",
                    "collectionName": "特别 - Single",
                },
                {
                    "trackId": 7,
                    "trackName": "特别的人(女声版)",
                    "artistName": "六月",
                    "collectionName": "特别的人(女声版) - Single",
                },
            ]},
            {"results": [
                {
                    "trackId": 8,
                    "trackName": "方大同",
                    "artistName": "SIKON & MISANG",
                    "collectionName": "SEXOPHONE",
                },
            ]},
        ]

        def fake_urlopen(request, timeout=0):
            return FakeResponse(payloads.pop(0))

        with patch.dict(os.environ, {"SONEX_ITUNES_COUNTRY": "", "SONEX_ITUNES_COUNTRIES": ""}), \
             patch("src.tools.track_search.urlopen", side_effect=fake_urlopen):
            result = track_search.search_track_metadata_candidates("方大同 特别的人", limit=5)

        self.assertEqual(result["candidates"][0]["artist"], "方大同")
        self.assertEqual(result["candidates"][0]["name"], "特别的人")

    def test_itunes_region_failure_continues_to_later_regions(self) -> None:
        rate_limit = HTTPError(
            "https://itunes.apple.com/search",
            429,
            "Too Many Requests",
            {},
            None,
        )
        payloads = [
            rate_limit,
            {"results": [
                {
                    "trackId": 9,
                    "trackName": "Song",
                    "artistName": "Artist",
                    "collectionName": "Album",
                }
            ]},
            {"results": []},
            {"results": []},
            {"data": []},
            {"recordings": []},
        ]

        def fake_urlopen(request, timeout=0):
            response = payloads.pop(0)
            if isinstance(response, Exception):
                raise response
            return FakeResponse(response)

        with patch.dict(os.environ, {"SONEX_ITUNES_COUNTRY": "", "SONEX_ITUNES_COUNTRIES": ""}), \
             patch("src.tools.track_search.urlopen", side_effect=fake_urlopen), \
             patch("src.tools.track_search.time.sleep"):
            result = track_search.search_track_metadata_candidates("Song", limit=5)

        self.assertEqual(result["candidates"][0]["id"], "9")
        self.assertEqual(result["source_attempts"][0]["provider"], "itunes")
        self.assertEqual(result["source_attempts"][0]["status"], "success")
        self.assertEqual(result["source_attempts"][0]["countries"], ["US", "TW", "HK", "CN"])

    def test_deezer_and_musicbrainz_fill_to_five_with_dedupe(self) -> None:
        """Verifies that deezer and musicbrainz fill to five with dedupe behaves as expected.

        Typical use: Use this in automated tests when guarding the deezer and musicbrainz fill to five with dedupe behavior against regressions.

        Example: test_deezer_and_musicbrainz_fill_to_five_with_dedupe() -> passes without assertion failures when the behavior remains correct.
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
            {"results": []},
            {"results": []},
            {"results": []},
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
            """Verifies that fake urlopen behaves as expected.

            Typical use: Use this in automated tests when guarding the fake urlopen behavior against regressions.

            Example: fake_urlopen() -> passes without assertion failures when the behavior remains correct.
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
        """Verifies that itunes rate limit is sanitized and deezer still runs behaves as expected.

        Typical use: Use this in automated tests when guarding the itunes rate limit is sanitized and deezer still runs behavior against regressions.

        Example: test_itunes_rate_limit_is_sanitized_and_deezer_still_runs() -> passes without assertion failures when the behavior remains correct.
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

        with patch(
            "src.tools.track_search.urlopen",
            side_effect=[
                rate_limit,
                FakeResponse({"results": []}),
                FakeResponse({"results": []}),
                FakeResponse({"results": []}),
                FakeResponse(deezer_payload),
                FakeResponse({"recordings": []}),
            ],
        ):
            result = track_search.search_track_metadata_candidates("Fallback", limit=5)

        self.assertEqual(result["candidates"][0]["provider"], "deezer")
        self.assertEqual(result["source_attempts"][0]["provider"], "itunes")
        self.assertEqual(result["source_attempts"][0]["status"], "rate_limited")
        self.assertNotIn("https://", result["source_attempts"][0]["message"])


if __name__ == "__main__":
    unittest.main()
