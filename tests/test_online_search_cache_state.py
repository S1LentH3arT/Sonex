from __future__ import annotations

from src.tools.online_search_cache_state import make_cache_key, metadata_only, normalize_cache_text


def test_cache_key_normalizes_equivalent_query_text() -> None:
    assert normalize_cache_text("  Café\nSong ") == "café song"
    assert make_cache_key(provider="YouTube", artist="A", title="B") == make_cache_key(
        provider="youtube", artist=" a ", title="b"
    )


def test_metadata_only_removes_playback_artifacts_recursively() -> None:
    assert metadata_only({"id": "1", "stream_url": "secret", "items": [{"audio_path": "/tmp/a"}]}) == {
        "id": "1",
        "items": [{}],
    }
