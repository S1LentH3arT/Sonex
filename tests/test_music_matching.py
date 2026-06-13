"""Tests for cross-language music identity matching."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.tools.music_matching import (
    AliasResolver,
    AudioSearchResult,
    CanonicalTrack,
    FingerprintUnavailableVerifier,
    MatchDecision,
    expand_audio_queries,
    normalize_music_text,
    score_audio_match,
    simplified_traditional_variants,
)


class MusicMatchingTests(unittest.TestCase):
    def test_normalize_music_text_handles_width_case_feat_and_punctuation(self) -> None:
        self.assertEqual(
            normalize_music_text(" Ｂｅａｕｔｉｆｕｌ（Live） feat. Guest! "),
            "beautiful live feat guest",
        )

    def test_simplified_traditional_variants_are_lightweight(self) -> None:
        self.assertEqual(
            simplified_traditional_variants("忘了美丽 未来"),
            {"忘了美丽 未来", "忘了美麗 未來"},
        )

    def test_builtin_alias_resolver_matches_khalil_fong_beautiful(self) -> None:
        resolver = AliasResolver()

        self.assertTrue(resolver.matches("artist", "Khalil Fong", "方大同"))
        self.assertTrue(resolver.matches("track", "Beautiful", "忘了美麗"))
        self.assertTrue(resolver.matches("album", "Wonderland", "未来"))

    def test_alias_resolver_loads_user_aliases_and_known_mismatches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            alias_file = Path(tmp) / "music_aliases.json"
            alias_file.write_text(
                """
                {
                  "aliases": {
                    "artist": {"A-Lin": ["黄丽玲", "黃麗玲"]},
                    "track": [{"canonical": "Romadiw", "aliases": ["如果可以"]}]
                  },
                  "known_mismatches": [
                    {
                      "title": "Beautiful",
                      "artist": "Khalil Fong",
                      "candidate_title": "特别的人",
                      "candidate_artist": "方大同"
                    }
                  ]
                }
                """,
                encoding="utf-8",
            )

            with patch("src.tools.music_matching.sonex_home", return_value=Path(tmp)):
                resolver = AliasResolver.load()

        self.assertTrue(resolver.matches("artist", "A-Lin", "黃麗玲"))
        self.assertTrue(resolver.matches("track", "Romadiw", "如果可以"))
        self.assertTrue(
            resolver.is_known_mismatch(
                CanonicalTrack(title="Beautiful", artist="Khalil Fong"),
                AudioSearchResult(title="特别的人", artist="方大同", provider="jamendo"),
            )
        )

    def test_expand_audio_queries_orders_ids_metadata_aliases_and_loose_recall(self) -> None:
        track = CanonicalTrack(
            title="Beautiful",
            artist="Khalil Fong",
            album="Wonderland",
            duration_ms=241000,
            isrc="HKI190700123",
            musicbrainz_recording_id="mbid-1",
        )

        queries = expand_audio_queries(track, AliasResolver())

        self.assertEqual(queries[0].kind, "stable_id")
        self.assertIn("HKI190700123", queries[0].query)
        self.assertEqual(queries[1].kind, "stable_id")
        self.assertIn("mbid-1", queries[1].query)
        self.assertIn(("metadata", "Khalil Fong Beautiful Wonderland"), [(item.kind, item.query) for item in queries])
        self.assertIn(("alias", "方大同 忘了美丽 未来"), [(item.kind, item.query) for item in queries])
        self.assertEqual(queries[-1].kind, "title_only")

    def test_score_accepts_cross_language_alias_match(self) -> None:
        score = score_audio_match(
            CanonicalTrack(title="Beautiful", artist="Khalil Fong", album="Wonderland", duration_ms=241000),
            AudioSearchResult(title="忘了美丽", artist="方大同", album="未来", duration_ms=240000, provider="jamendo"),
            AliasResolver(),
        )

        self.assertEqual(score.decision, MatchDecision.ACCEPT)
        self.assertIn("title_alias", score.reasons)
        self.assertIn("artist_alias", score.reasons)
        self.assertGreaterEqual(score.total_score, 80)

    def test_score_hard_rejects_same_title_different_artist(self) -> None:
        score = score_audio_match(
            CanonicalTrack(title="Beautiful", artist="Khalil Fong"),
            AudioSearchResult(title="Beautiful", artist="Wrong Artist", provider="audius"),
            AliasResolver(),
        )

        self.assertEqual(score.decision, MatchDecision.REJECT)
        self.assertIn("artist_mismatch", score.hard_reject_reasons)

    def test_score_hard_rejects_large_duration_and_version_conflicts(self) -> None:
        duration = score_audio_match(
            CanonicalTrack(title="Beautiful", artist="Khalil Fong", duration_ms=241000),
            AudioSearchResult(title="Beautiful", artist="Khalil Fong", duration_ms=400000, provider="jamendo"),
            AliasResolver(),
        )
        version = score_audio_match(
            CanonicalTrack(title="Beautiful", artist="Khalil Fong"),
            AudioSearchResult(title="Beautiful Live", artist="Khalil Fong", provider="jamendo"),
            AliasResolver(),
        )

        self.assertEqual(duration.decision, MatchDecision.REJECT)
        self.assertIn("duration_conflict", duration.hard_reject_reasons)
        self.assertEqual(version.decision, MatchDecision.REJECT)
        self.assertIn("version_conflict", version.hard_reject_reasons)

    def test_title_only_evidence_is_review_not_accept(self) -> None:
        score = score_audio_match(
            CanonicalTrack(title="Beautiful", artist="Khalil Fong"),
            AudioSearchResult(title="Beautiful", artist="", provider="jamendo"),
            AliasResolver(),
        )

        self.assertEqual(score.decision, MatchDecision.REVIEW)
        self.assertIn("title_only_weak_evidence", score.reasons)

    def test_fingerprint_verifier_is_explicitly_unavailable(self) -> None:
        verifier = FingerprintUnavailableVerifier()

        self.assertFalse(verifier.available)
        with self.assertRaises(NotImplementedError):
            verifier.verify(Path("/tmp/audio.mp3"), CanonicalTrack(title="Beautiful", artist="Khalil Fong"))


if __name__ == "__main__":
    unittest.main()
