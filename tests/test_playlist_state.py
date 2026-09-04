from __future__ import annotations

from src.tools.playlist_state import coerce_playlist, normalize_playlist_name, normalize_source_app, track_snapshot


def test_playlist_state_normalizes_names_sources_and_malformed_tracks() -> None:
    assert normalize_playlist_name("  LIKES ") == "likes"
    assert normalize_source_app("itunes") == "iTunes"
    state = coerce_playlist(
        {"name": "  Road   Trip ", "source_app": " spotify ", "tracks": None, "revision": "bad"},
        fallback_name="fallback",
    )
    assert state["name"] == "Road Trip"
    assert state["source_app"] == "Spotify"
    assert state["tracks"] == []
    assert state["revision"] == 0


def test_track_snapshot_preserves_playability_boundary() -> None:
    snapshot = track_snapshot(
        {"title": "Song", "artist": "Artist", "provider": "youtube", "requires_resolution": True},
        saved_at=12.0,
    )
    assert snapshot["name"] == "Song"
    assert snapshot["playable"] is False
