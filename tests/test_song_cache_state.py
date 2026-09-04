from __future__ import annotations

from src.tools.song_cache_state import artists_text, cache_id_for, merge_provider_details, provider_summary


def test_song_state_canonicalizes_artist_and_cache_id() -> None:
    assert artists_text({"artists": ["A", " B "]}) == "A, B"
    assert cache_id_for("Song", "Artist") == cache_id_for("song", "artist")


def test_song_state_merges_provider_details_without_playback_side_effects() -> None:
    merged = merge_provider_details({"providers": {"spotify": {"uri": "old"}}}, {"provider": "youtube", "url": "new"})
    assert merged["providers"]["spotify"]["uri"] == "old"
    assert merged["providers"]["youtube"]["url"] == "new"
    assert provider_summary({"provider": "youtube", "url": "new"}) == [{"provider": "youtube", "has_url": True}]
