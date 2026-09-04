from __future__ import annotations

from src.tools.player_permission_state import (
    normalize_confirm_decision,
    normalize_player,
    player_label,
    public_data,
)


def test_player_state_normalizes_labels_and_decisions() -> None:
    assert normalize_player(" MPV ") == "mpv"
    assert player_label("auto") == "mpv"
    assert normalize_confirm_decision(True) == "allow_once"
    assert normalize_confirm_decision("unexpected") == "deny"


def test_public_data_hides_launch_details() -> None:
    assert public_data({"player": "mpv", "cmd": ["mpv"], "success_message": "ok"}) == {
        "player": "mpv"
    }
