from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.tools.online_search_cache import (
    EMPTY_TTL_SECONDS,
    POSITIVE_TTL_SECONDS,
    get_search_cache,
    make_search_cache_key,
    put_search_cache,
)


class OnlineSearchCacheTests(unittest.TestCase):
    def test_cache_normalizes_identity_and_removes_stream_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            key = make_search_cache_key(
                provider="YouTube",
                artist="  Artist ",
                title="Song",
                album="Album",
                variant_intent="default",
            )
            equivalent = make_search_cache_key(
                provider="youtube",
                artist="Artist",
                title="Song",
                album="Album",
                variant_intent="default",
            )
            self.assertEqual(key, equivalent)

            put_search_cache(
                key,
                [{"id": "video", "title": "Song", "stream_url": "secret"}],
                provider="youtube",
                cache_root=root,
                now=100,
            )

            cached = get_search_cache(key, provider="youtube", cache_root=root, now=100)
            self.assertEqual(cached, [{"id": "video", "title": "Song"}])

    def test_empty_result_has_short_ttl_and_is_distinct_from_miss(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            key = make_search_cache_key(provider="youtube", artist="A", title="B")
            put_search_cache(key, [], provider="youtube", cache_root=root, now=100)
            self.assertEqual(get_search_cache(key, provider="youtube", cache_root=root, now=100 + EMPTY_TTL_SECONDS - 1), [])
            self.assertIsNone(get_search_cache(key, provider="youtube", cache_root=root, now=100 + EMPTY_TTL_SECONDS + 1))

    def test_positive_result_has_day_ttl(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            key = make_search_cache_key(provider="youtube", artist="A", title="B")
            put_search_cache(key, [{"id": "video"}], provider="youtube", cache_root=root, now=100)
            self.assertEqual(get_search_cache(key, provider="youtube", cache_root=root, now=100 + POSITIVE_TTL_SECONDS - 1), [{"id": "video"}])
            self.assertIsNone(get_search_cache(key, provider="youtube", cache_root=root, now=100 + POSITIVE_TTL_SECONDS + 1))
