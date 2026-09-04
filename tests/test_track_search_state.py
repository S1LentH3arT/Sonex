"""Regression tests for pure track-search candidate rules."""

from __future__ import annotations

import unittest

from src.tools.track_search_state import (
    candidate,
    dedupe_key,
    int_ms,
    is_credible,
    normalize_key_text,
    release_year,
    seconds_to_ms,
    text,
)


class TrackSearchStateTests(unittest.TestCase):
    def test_candidate_omits_empty_fields_and_builds_youtube_query(self) -> None:
        result = candidate(
            query="fallback",
            metadata_source="itunes",
            provider="itunes",
            item_id="42",
            name=" Song ",
            artist="Artist",
            album=None,
            duration_ms=1000,
            cover_url=None,
            url=None,
            uri="itunes:track:42",
            extra={"preview_url": ""},
        )

        self.assertEqual(result["youtube_query"], "Artist  Song")
        self.assertEqual(result["artists"], ["Artist"])
        self.assertNotIn("album", result)
        self.assertNotIn("preview_url", result)

    def test_credibility_and_dedupe_are_stable(self) -> None:
        item = {"title": "Song!", "artist": " The Band ", "album": "Album"}
        self.assertTrue(is_credible(item))
        self.assertEqual(dedupe_key(item), "song|the band|album")
        self.assertEqual(dedupe_key({"title": "Song"}), None)

    def test_scalar_coercions_are_fail_closed(self) -> None:
        self.assertEqual(text("  value "), "value")
        self.assertIsNone(text("  "))
        self.assertEqual(normalize_key_text("Beyoncé — Song"), "beyoncé song")
        self.assertEqual(int_ms("201000.9"), 201000)
        self.assertEqual(int_ms("bad"), 0)
        self.assertEqual(seconds_to_ms("201.5"), 201500)
        self.assertEqual(seconds_to_ms(-1), 0)
        self.assertEqual(release_year("1976-01-01"), "1976")
        self.assertIsNone(release_year("unknown"))


if __name__ == "__main__":
    unittest.main()
