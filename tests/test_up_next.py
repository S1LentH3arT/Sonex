"""Persistent upcoming-playback queue contracts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.tools.up_next import (
    UpNextFullError,
    append_up_next_track,
    commit_up_next_state,
    consume_up_next_entry,
    fail_up_next_entry,
    fail_up_next_head,
    up_next_snapshot,
)
from src.tools.up_next_state import MAX_UP_NEXT


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
    assert [
        {key: value for key, value in item.items() if key != "entry_id"}
        for item in restored["items"]
    ] == state["items"]
    assert len({item["entry_id"] for item in restored["items"]}) == 2


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


def test_up_next_rejects_add_when_queue_is_full_without_changing_revision(tmp_path: Path) -> None:
    path = tmp_path / "up_next.json"
    commit_up_next_state(
        {
            "revision": 0,
            "items": [
                {"ref": f"local:{index}", "name": str(index), "playable": True}
                for index in range(MAX_UP_NEXT)
            ],
            "failed": [],
        },
        expected_revision=0,
        queue_path=path,
    )
    before = up_next_snapshot(queue_path=path)

    with pytest.raises(UpNextFullError):
        append_up_next_track(
            {"ref": "local:new", "name": "New", "playable": True},
            queue_path=path,
        )

    after = up_next_snapshot(queue_path=path)
    assert after == before


def test_settlement_removes_started_entry_after_queue_reorder(tmp_path: Path) -> None:
    path = tmp_path / "up_next.json"
    committed = commit_up_next_state(
        {
            "revision": 0,
            "items": [
                {"ref": "local:a", "name": "A", "playable": True},
                {"ref": "local:b", "name": "B", "playable": True},
            ],
            "failed": [],
        },
        expected_revision=0,
        queue_path=path,
    )
    entry_id = committed["items"][0]["entry_id"]
    commit_up_next_state(
        {**committed, "items": [committed["items"][1], committed["items"][0]]},
        expected_revision=committed["revision"],
        queue_path=path,
    )

    settled = consume_up_next_entry(entry_id, queue_path=path)

    assert [item["ref"] for item in settled["items"]] == ["local:b"]
    unchanged = consume_up_next_entry(entry_id, queue_path=path)
    assert unchanged["revision"] == settled["revision"]


def test_old_settlement_does_not_remove_readded_same_track(tmp_path: Path) -> None:
    path = tmp_path / "up_next.json"
    committed = commit_up_next_state(
        {
            "revision": 0,
            "items": [{"ref": "local:a", "name": "A", "playable": True}],
            "failed": [],
        },
        expected_revision=0,
        queue_path=path,
    )
    old_entry_id = committed["items"][0]["entry_id"]
    committed = commit_up_next_state(
        {**committed, "items": []},
        expected_revision=committed["revision"],
        queue_path=path,
    )
    committed = append_up_next_track(
        {"ref": "local:a", "name": "A", "playable": True}, queue_path=path
    )

    settled = consume_up_next_entry(old_entry_id, queue_path=path)

    assert [item["ref"] for item in settled["items"]] == ["local:a"]


def test_legacy_queue_gets_persisted_entry_ids_on_read(tmp_path: Path) -> None:
    path = tmp_path / "up_next.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "revision": 3,
                "items": [{"ref": "local:a", "name": "A", "playable": True}],
                "failed": [],
            }
        ),
        encoding="utf-8",
    )

    first = up_next_snapshot(queue_path=path)
    persisted = json.loads(path.read_text(encoding="utf-8"))
    second = up_next_snapshot(queue_path=path)

    assert first["items"][0]["entry_id"]
    assert persisted["items"][0]["entry_id"] == first["items"][0]["entry_id"]
    assert second["items"][0]["entry_id"] == first["items"][0]["entry_id"]
    assert second["revision"] == 3


def test_failure_settlement_records_the_matching_track_after_reorder(tmp_path: Path) -> None:
    path = tmp_path / "up_next.json"
    committed = commit_up_next_state(
        {
            "revision": 0,
            "items": [
                {"ref": "local:a", "name": "A", "playable": True},
                {"ref": "local:b", "name": "B", "playable": True},
            ],
            "failed": [],
        },
        expected_revision=0,
        queue_path=path,
    )
    entry_id = committed["items"][0]["entry_id"]
    commit_up_next_state(
        {**committed, "items": [committed["items"][1], committed["items"][0]]},
        expected_revision=committed["revision"],
        queue_path=path,
    )

    settled = fail_up_next_entry(entry_id, "route failed", queue_path=path)

    assert [item["ref"] for item in settled["items"]] == ["local:b"]
    assert settled["failed"][0]["ref"] == "local:a"
    assert settled["failed"][0]["entry_id"] == entry_id


def test_commit_rejects_oversized_queue_without_silent_truncation(tmp_path: Path) -> None:
    path = tmp_path / "up_next.json"
    first = commit_up_next_state(
        {"revision": 0, "items": [], "failed": []},
        expected_revision=0,
        queue_path=path,
    )

    with pytest.raises(UpNextFullError):
        commit_up_next_state(
            {
                **first,
                "items": [
                    {"ref": f"local:{index}", "playable": True}
                    for index in range(MAX_UP_NEXT + 1)
                ],
            },
            expected_revision=first["revision"],
            queue_path=path,
        )

    assert up_next_snapshot(queue_path=path) == first
