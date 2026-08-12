"""Persistent upcoming-playback queue contracts."""

from __future__ import annotations

from pathlib import Path

from src.tools.up_next import (
    append_up_next_track,
    commit_up_next_state,
    fail_up_next_head,
    up_next_snapshot,
)


def test_up_next_accepts_metadata_that_requires_resolution(tmp_path: Path) -> None:
    path = tmp_path / "up_next.json"

    state = append_up_next_track(
        {
            "ref": "metadata:track:legacy",
            "name": "Legacy Song",
            "artist": "Artist",
            "provider": "metadata",
            "playable": False,
            "requires_resolution": True,
        },
        queue_path=path,
    )

    assert state["items"][0]["requires_resolution"] is True


def test_up_next_persists_revision_and_consumes_only_after_success(tmp_path: Path) -> None:
    path = tmp_path / "up_next.json"
    state = {
        "revision": 0,
        "items": [
            {"ref": "spotify:uri:spotify:track:1", "name": "One", "playable": True},
            {"ref": "spotify:uri:spotify:track:2", "name": "Two", "playable": True},
        ],
        "failed": [],
    }

    committed = commit_up_next_state(state, expected_revision=0, queue_path=path)
    restored = up_next_snapshot(queue_path=path)

    assert committed["revision"] == 1
    assert restored["items"] == state["items"]


def test_failed_head_moves_to_failed_history_and_advances(tmp_path: Path) -> None:
    path = tmp_path / "up_next.json"
    commit_up_next_state(
        {
            "revision": 0,
            "items": [
                {"ref": "spotify:uri:spotify:track:1", "name": "One", "playable": True},
                {"ref": "spotify:uri:spotify:track:2", "name": "Two", "playable": True},
            ],
            "failed": [],
        },
        expected_revision=0,
        queue_path=path,
    )

    result = fail_up_next_head("No playable route.", queue_path=path)

    assert result["revision"] == 2
    assert [item["name"] for item in result["items"]] == ["Two"]
    assert result["failed"][0]["name"] == "One"
    assert result["failed"][0]["failure_reason"] == "No playable route."
