from __future__ import annotations

import pytest

from src.tools.playback_state import coerce_ms, coerce_volume, metadata_state


def test_state_coercion_clamps_invalid_values() -> None:
    assert coerce_ms("12.8") == 12
    assert coerce_ms(-2) == 0
    assert coerce_ms("bad") == 0
    assert coerce_volume(0) == 0
    assert coerce_volume(100) == 100
    with pytest.raises(ValueError):
        coerce_volume(101)


def test_metadata_state_applies_stable_fallbacks() -> None:
    state = metadata_state(
        metadata={"title": "Song", "cover_url": "cover", "duration_ms": "1500"},
        source="local",
        player="mpv",
        session_id="session",
    )
    assert state.name == "Song"
    assert state.artist == "-"
    assert state.duration_ms == 1500
    assert state.album_cover_url == "cover"
