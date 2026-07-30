"""Tests for Spotify search query planning."""

from __future__ import annotations

import unittest

from src.api.music_query import build_music_search_query_plan


class MusicQueryPlanTests(unittest.TestCase):
    def test_chinese_artist_possessive_track_query_builds_structured_variants(self) -> None:
        plan = build_music_search_query_plan("方大同的因为你")

        self.assertEqual(plan.artist, "方大同")
        self.assertEqual(plan.track, "因为你")
        self.assertEqual(plan.variants[0], "track:因为你 artist:方大同")
        self.assertIn("方大同 因为你", plan.variants)
        self.assertIn("因为你 方大同", plan.variants)

    def test_direct_track_query_keeps_simple_plan(self) -> None:
        plan = build_music_search_query_plan("青花瓷")

        self.assertIsNone(plan.artist)
        self.assertEqual(plan.track, "青花瓷")
        self.assertEqual(plan.variants, ("青花瓷",))

    def test_recommendation_text_is_not_reclassified_as_track_search(self) -> None:
        plan = build_music_search_query_plan("给我推荐几首方大同的歌")

        self.assertIsNone(plan.artist)
        self.assertIsNone(plan.track)
        self.assertEqual(plan.variants, ("给我推荐几首方大同的歌",))

    def test_quoted_track_artist_query_builds_structured_variants(self) -> None:
        plan = build_music_search_query_plan("《因为你》方大同")

        self.assertEqual(plan.artist, "方大同")
        self.assertEqual(plan.track, "因为你")
        self.assertEqual(plan.variants[0], "track:因为你 artist:方大同")

    def test_english_by_query_builds_structured_variants(self) -> None:
        plan = build_music_search_query_plan("Because of You by Khalil Fong")

        self.assertEqual(plan.artist, "Khalil Fong")
        self.assertEqual(plan.track, "Because of You")
        self.assertEqual(plan.variants[0], "track:Because of You artist:Khalil Fong")


if __name__ == "__main__":
    unittest.main()
