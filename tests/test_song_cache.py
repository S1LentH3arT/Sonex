from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.tools.song_cache import (
    find_best_cached_song,
    recent_cached_songs,
    resolve_cached_song,
    upsert_cached_song,
)


class SongCacheTests(unittest.TestCase):
    def test_cache_retains_only_recent_100_and_exposes_recent_10(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for idx in range(101):
                upsert_cached_song(
                    {
                        "name": f"Song {idx}",
                        "artist": f"Artist {idx}",
                        "album": f"Album {idx}",
                        "provider": "youtube",
                        "url": f"https://example.test/{idx}",
                        "provider_payload": {"idx": idx},
                    },
                    cache_root=root,
                    now=idx,
                )

            self.assertIsNone(find_best_cached_song("Song 0 Artist 0", cache_root=root))
            latest = find_best_cached_song("Song 100 Artist 100", cache_root=root)
            self.assertIsNotNone(latest)
            self.assertEqual(latest["name"], "Song 100")
            self.assertNotIn("provider_payload", latest)

            recent = recent_cached_songs(cache_root=root)
            self.assertEqual(len(recent), 10)
            self.assertEqual(recent[0]["name"], "Song 100")
            self.assertEqual(recent[-1]["name"], "Song 91")

    def test_resolve_cached_song_reads_full_item_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            compact = upsert_cached_song(
                {
                    "name": "Cache Song",
                    "artist": "Cache Artist",
                    "album": "Cache Album",
                    "provider": "spotify",
                    "uri": "spotify:track:cache",
                    "cover_url": "https://images.test/cover.jpg",
                    "provider_payload": {"secret": "full"},
                },
                cache_root=root,
                now=10,
            )

            resolved = resolve_cached_song(str(compact["cache_id"]), cache_root=root)
            self.assertEqual(resolved["uri"], "spotify:track:cache")
            self.assertEqual(resolved["cover_url"], "https://images.test/cover.jpg")
            self.assertEqual(resolved["provider_payload"], {"secret": "full"})


if __name__ == "__main__":
    unittest.main()
