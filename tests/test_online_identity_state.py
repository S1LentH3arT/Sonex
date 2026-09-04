"""Regression tests for online-audio identity normalization policy."""

from __future__ import annotations

import unittest

from src.tools.online_identity_state import (
    contains_any,
    has_cjk,
    identity_artist,
    identity_title,
    identity_title_text,
    mostly_latin,
    query_terms,
)


class OnlineIdentityStateTests(unittest.TestCase):
    def test_identity_titles_strip_only_non_identity_suffixes(self) -> None:
        self.assertEqual(identity_title("Song (Official Audio) feat. Guest"), "song")
        self.assertEqual(identity_title_text({"title": "Artist - Song", "artist": "Artist"}), "song")
        self.assertEqual(identity_artist({"artist": "Artist feat. Guest"}), "Artist")

    def test_language_and_query_helpers_are_deterministic(self) -> None:
        self.assertTrue(has_cjk("方大同"))
        self.assertTrue(mostly_latin("Khalil Fong"))
        self.assertEqual(query_terms("the Artist Live Song"), ["artist", "song"])
        self.assertTrue(contains_any("Official Music Video", ("official",)))


if __name__ == "__main__":
    unittest.main()
