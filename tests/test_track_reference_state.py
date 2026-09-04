from __future__ import annotations

from src.tools.track_reference_state import normalize_provider, reference_key, track_reference_snapshot


def test_reference_state_normalizes_provider_and_prefers_native_identity() -> None:
    assert normalize_provider(" NetEase-Music ") == "netease_music"
    assert reference_key("spotify", {"uri": "spotify:track:1", "name": "Song"}) == (
        "uri",
        "spotify:track:1",
    )


def test_metadata_reference_key_is_deterministic_and_snapshot_is_opaque() -> None:
    track = {"title": "Song", "artist": "Artist", "duration_ms": 1000}
    assert reference_key("youtube", track) == reference_key("youtube", dict(track))
    assert track_reference_snapshot(
        "youtube:metadata:abc",
        "youtube",
        track,
        playable=False,
    ) == {
        "title": "Song",
        "artist": "Artist",
        "duration_ms": 1000,
        "provider": "youtube",
        "ref": "youtube:metadata:abc",
        "playable": False,
    }
