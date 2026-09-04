"""Regression tests for music matching normalization policy."""

from __future__ import annotations

import unittest

from src.tools.music_matching_state import (
    display_title,
    normalize_music_text,
    primary_artist,
    simplified_traditional_variants,
    version_tags,
)


class MusicMatchingStateTests(unittest.TestCase):
    def test_normalization_and_variants(self) -> None:
        self.assertEqual(
            normalize_music_text(" Ｂｅａｕｔｉｆｕｌ（Live） feat. Guest! "),
            "beautiful live feat guest",
        )
        self.assertEqual(
            simplified_traditional_variants("忘了美丽"),
            {"忘了美丽", "忘了美麗"},
        )

    def test_display_title_and_primary_artist_remove_non_identity_suffixes(self) -> None:
        self.assertEqual(display_title("Song (Official Music Video) feat. Guest"), "song")
        self.assertEqual(primary_artist("Artist feat. Guest"), "Artist")

    def test_version_tags_keep_release_context(self) -> None:
        self.assertEqual(version_tags("Song - Live"), {"live"})
        self.assertEqual(version_tags("Song (Official Audio)"), set())


if __name__ == "__main__":
    unittest.main()
