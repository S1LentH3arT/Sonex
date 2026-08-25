from __future__ import annotations

import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import src.tools.online_play as online


def _youtube_payload() -> dict[str, object]:
    return {
        "entries": [
            {
                "id": "official",
                "title": "Song Official Audio",
                "track": "Song Official Audio",
                "channel": "Artist - Topic",
                "artist": "Artist",
                "channel_is_verified": True,
                "webpage_url": "https://www.youtube.com/watch?v=official",
            }
        ]
    }


class OnlinePlayGuardTests(unittest.TestCase):
    def test_repeated_search_uses_persistent_candidate_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch(
                "src.tools.online_play._extract_ytdlp_info",
                return_value=_youtube_payload(),
            ) as extract:
                first = online.search_youtube_songs(
                    "Artist Song",
                    cache_root=root,
                    playback_metadata={"artist": "Artist", "title": "Song"},
                )
                second = online.search_youtube_songs(
                    "Artist Song",
                    cache_root=root,
                    playback_metadata={"artist": "Artist", "title": "Song"},
                )

            self.assertEqual([item["youtube_id"] for item in first], ["official"])
            self.assertEqual([item["youtube_id"] for item in second], ["official"])
            extract.assert_called_once()

    def test_concurrent_same_search_is_single_flight(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            calls = 0

            def fake_extract(**_: object) -> dict[str, object]:
                nonlocal calls
                calls += 1
                return _youtube_payload()

            with patch("src.tools.online_play._extract_ytdlp_info", side_effect=fake_extract), \
                 patch("src.tools.online_play.YOUTUBE_MIN_SEARCH_INTERVAL_SECONDS", 0.01):
                with ThreadPoolExecutor(max_workers=2) as executor:
                    results = list(
                        executor.map(
                            lambda _: online.search_youtube_songs(
                                "Artist Song",
                                cache_root=root,
                                playback_metadata={"artist": "Artist", "title": "Song"},
                            ),
                            (1, 2),
                        )
                    )

            self.assertEqual(calls, 1)
            self.assertEqual([item["youtube_id"] for item in results[0]], ["official"])
            self.assertEqual([item["youtube_id"] for item in results[1]], ["official"])
