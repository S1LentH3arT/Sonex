"""Regression coverage for removing a retired playback provider safely."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from src.auth.store import load_auth_store
from src.music.connections import MusicConnectionManager
from src.music.legacy_tracks import downgrade_retired_provider_track
from src.music.provider_mode import ProviderMode, load_provider_mode_intent
from src.tools.playback_queue import playback_queue_snapshot
from src.tools.playlists import list_playlist_tracks
from src.tools.up_next import up_next_snapshot


def test_retired_auth_and_connection_records_are_cleaned_on_load(tmp_path: Path) -> None:
    auth_path = tmp_path / "auth.json"
    auth_path.write_text(json.dumps({
        "version": 1,
        "default_provider": "apple_music",
        "default_model": "catalog",
        "providers": {
            "apple_music": {"auth_method": "api_key", "api_key": "retired"},
            "apple_mode": {"auth_method": "none", "base_url": "https://tokens.example"},
            "openai": {"auth_method": "api_key", "api_key": "kept"},
        },
    }), encoding="utf-8")
    store = load_auth_store(auth_path)

    assert sorted(store.providers) == ["openai"]
    assert store.default_provider is None
    assert store.default_model is None
    assert "apple" not in auth_path.read_text(encoding="utf-8").casefold()

    connections_path = tmp_path / "connections.json"
    connections_path.write_text(json.dumps({
        "version": 1,
        "preferred_provider_id": "apple_music",
        "connections": [{
            "provider_id": "apple_music",
            "status": "connected",
            "account_label": "Legacy account",
            "connected_at": "2026-01-01T00:00:00Z",
            "checked_at": "2026-01-01T00:00:00Z",
        }],
    }), encoding="utf-8")
    connections = MusicConnectionManager(path=connections_path)

    assert connections.preferred_provider_id is None
    assert connections.records() == ()
    assert "apple" not in connections_path.read_text(encoding="utf-8").casefold()


def test_retired_mode_intent_is_cleared_instead_of_restored(tmp_path: Path) -> None:
    intent_path = tmp_path / "provider-mode.json"
    intent_path.write_text(
        json.dumps({"version": 1, "provider": "apple"}),
        encoding="utf-8",
    )

    with patch("src.music.provider_mode.provider_mode_path", return_value=intent_path):
        state = load_provider_mode_intent()

    assert state.provider is ProviderMode.NORMAL
    assert not intent_path.exists()


def test_legacy_tracks_keep_metadata_and_are_reresolved_without_provider_refs(tmp_path: Path) -> None:
    legacy = {
        "name": "Legacy Song",
        "artist": "Artist",
        "album": "Album",
        "album_cover_url": "https://covers.example/song.jpg",
        "provider": "apple_music",
        "uri": "apple_music:song:123",
        "url": "https://music.apple.com/us/song/123",
        "apple_music_url": "https://music.apple.com/us/song/123",
        "playable": True,
    }
    playlist_path = tmp_path / "likes.json"
    playlist_path.write_text(json.dumps({
        "name": "likes",
        "source_app": "Sonex",
        "tracks": [legacy],
        "revision": 1,
    }), encoding="utf-8")
    playlist_track = list_playlist_tracks("likes", playlists_root=tmp_path)[0]

    queue_path = tmp_path / "playback_queue.json"
    queue_path.write_text(json.dumps({"version": 1, "tracks": [legacy]}), encoding="utf-8")
    recent_track = playback_queue_snapshot(queue_path=queue_path)[0]

    up_next_path = tmp_path / "up_next.json"
    up_next_path.write_text(json.dumps({
        "version": 1,
        "revision": 2,
        "items": [legacy],
        "failed": [],
    }), encoding="utf-8")
    queued_track = up_next_snapshot(queue_path=up_next_path)["items"][0]

    for track in (playlist_track, recent_track, queued_track):
        assert track["name"] == "Legacy Song"
        assert track["artist"] == "Artist"
        assert track["album_cover_url"] == "https://covers.example/song.jpg"
        assert track["provider"] == "metadata"
        assert track["requires_resolution"] is True
        assert track["playable"] is False
        assert "uri" not in track
        assert "apple_music_url" not in track


def test_itunes_metadata_is_not_treated_as_a_retired_playback_track() -> None:
    metadata = {
        "provider": "itunes",
        "name": "Catalog Song",
        "artist": "Artist",
        "uri": "itunes:track:123",
        "itunes_url": "https://music.apple.com/us/song/123",
    }

    normalized, changed = downgrade_retired_provider_track(metadata)

    assert changed is False
    assert normalized == metadata
