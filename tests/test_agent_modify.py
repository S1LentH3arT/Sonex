"""Contracts for local playlist and up-next Agent modifications."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from src.tools import agent_modify
from src.tools.agent_modify import Modify, complete_modify_confirmation
from src.tools.agent_surface import remember_track_reference
from src.tools.playlists import list_playlist_tracks, list_playlists
from src.tools.up_next import up_next_snapshot


def _paths(tmp_path: Path):
    return (
        patch("src.tools.playlists._default_playlists_root", return_value=tmp_path / "playlists"),
        patch("src.tools.up_next._default_up_next_path", return_value=tmp_path / "up_next.json"),
    )


def test_modify_batches_playlist_writes_and_retries_idempotently(tmp_path: Path) -> None:
    ref = remember_track_reference(
        "spotify",
        {"name": "BB88", "artist": "方大同", "uri": "spotify:track:bb88"},
        playable=True,
    )
    operations = [
        {"target": "playlist", "action": "create", "name": "Commute"},
        {"target": "playlist", "action": "add", "name": "Commute", "refs": [ref]},
    ]
    playlists_patch, up_next_patch = _paths(tmp_path)
    with playlists_patch, up_next_patch:
        first = Modify(operations, idempotency_key="turn-1")
        second = Modify(operations, idempotency_key="turn-1")
        agent_modify._IDEMPOTENCY_RESULTS.clear()
        after_restart = Modify(operations, idempotency_key="turn-1")

        assert first["status"] == "success"
        assert second == first
        assert after_restart == first
        assert [track["name"] for track in list_playlist_tracks("Commute")] == ["BB88"]


def test_modify_destructive_operation_requires_preview_confirmation(tmp_path: Path) -> None:
    ref = remember_track_reference(
        "spotify",
        {"name": "BB88", "artist": "方大同", "uri": "spotify:track:bb88"},
        playable=True,
    )
    playlists_patch, up_next_patch = _paths(tmp_path)
    with playlists_patch, up_next_patch:
        Modify(
            [{"target": "playlist", "action": "add", "name": "Commute", "refs": [ref]}],
            idempotency_key="seed",
        )
        pending = Modify(
            [{"target": "playlist", "action": "remove", "name": "Commute", "refs": [ref]}],
            idempotency_key="remove-1",
        )

        assert pending["status"] == "requires_modify_confirmation"
        assert pending["data"]["preview"]["affected_tracks"] == 1
        assert len(list_playlist_tracks("Commute")) == 1

        committed = complete_modify_confirmation(
            pending["data"]["confirmation_token"],
            "allow_once",
        )

        assert committed["status"] == "success"
        assert list_playlist_tracks("Commute") == []


def test_modify_rejects_reusing_idempotency_key_for_different_operations(tmp_path: Path) -> None:
    playlists_patch, up_next_patch = _paths(tmp_path)
    with playlists_patch, up_next_patch:
        first = Modify(
            [{"target": "playlist", "action": "create", "name": "One"}],
            idempotency_key="same-key",
        )
        conflict = Modify(
            [{"target": "playlist", "action": "create", "name": "Two"}],
            idempotency_key="same-key",
        )

        assert first["status"] == "success"
        assert conflict["status"] == "fail"
        assert conflict["error_code"] == "IDEMPOTENCY_CONFLICT"


def test_modify_protects_likes_case_insensitively(tmp_path: Path) -> None:
    playlists_patch, up_next_patch = _paths(tmp_path)
    with playlists_patch, up_next_patch:
        result = Modify(
            [{"target": "playlist", "action": "delete", "name": "LIKES"}],
            idempotency_key="protect-likes",
        )

        assert result["status"] == "fail"
        assert result["error_code"] == "PROTECTED_PLAYLIST"


def test_modify_rejects_stale_confirmation_without_overwriting_new_state(tmp_path: Path) -> None:
    first_ref = remember_track_reference(
        "spotify",
        {"name": "BB88", "artist": "方大同", "uri": "spotify:track:bb88"},
        playable=True,
    )
    second_ref = remember_track_reference(
        "spotify",
        {"name": "特别的人", "artist": "方大同", "uri": "spotify:track:special"},
        playable=True,
    )
    playlists_patch, up_next_patch = _paths(tmp_path)
    with playlists_patch, up_next_patch:
        Modify(
            [{"target": "playlist", "action": "add", "name": "Commute", "refs": [first_ref]}],
            idempotency_key="stale-seed",
        )
        pending = Modify(
            [{"target": "playlist", "action": "clear", "name": "Commute"}],
            idempotency_key="stale-clear",
        )
        Modify(
            [{"target": "playlist", "action": "add", "name": "Commute", "refs": [second_ref]}],
            idempotency_key="concurrent-add",
        )

        result = complete_modify_confirmation(
            pending["data"]["confirmation_token"],
            "allow_once",
        )

        assert result["status"] == "fail"
        assert result["error_code"] == "VERSION_CONFLICT"
        assert [item["name"] for item in list_playlist_tracks("Commute")] == [
            "BB88",
            "特别的人",
        ]


def test_modify_up_next_requires_a_playable_reference_and_persists(tmp_path: Path) -> None:
    metadata_ref = remember_track_reference(
        "itunes",
        {"name": "Metadata Song", "artist": "Artist", "id": "itunes-1"},
        playable=False,
    )
    playable_ref = remember_track_reference(
        "spotify",
        {"name": "Playable Song", "artist": "Artist", "uri": "spotify:track:playable"},
        playable=True,
    )
    playlists_patch, up_next_patch = _paths(tmp_path)
    with playlists_patch, up_next_patch:
        rejected = Modify(
            [{"target": "up_next", "action": "add", "refs": [metadata_ref]}],
            idempotency_key="metadata",
        )
        accepted = Modify(
            [{"target": "up_next", "action": "add", "refs": [playable_ref]}],
            idempotency_key="playable",
        )

        assert rejected["status"] == "fail"
        assert rejected["error_code"] == "REF_NOT_PLAYABLE"
        assert accepted["status"] == "success"
        restored = up_next_snapshot()
        assert restored["revision"] == 1
        assert [item["name"] for item in restored["items"]] == ["Playable Song"]


def test_modify_validates_entire_batch_before_creating_files(tmp_path: Path) -> None:
    playlists_patch, up_next_patch = _paths(tmp_path)
    with playlists_patch, up_next_patch:
        result = Modify(
            [
                {"target": "playlist", "action": "create", "name": "Commute"},
                {"target": "up_next", "action": "teleport"},
            ],
            idempotency_key="invalid-batch",
        )

        assert result["status"] == "fail"
        assert result["error_code"] == "ACTION_UNSUPPORTED"
        assert all(item["name"] != "Commute" for item in list_playlists())


def test_modify_rolls_back_prior_file_when_later_commit_fails(tmp_path: Path) -> None:
    ref = remember_track_reference(
        "spotify",
        {"name": "BB88", "artist": "方大同", "uri": "spotify:track:rollback"},
        playable=True,
    )
    playlists_patch, up_next_patch = _paths(tmp_path)
    with playlists_patch, up_next_patch, patch(
        "src.tools.agent_modify.commit_up_next_state",
        side_effect=OSError("disk unavailable"),
    ):
        with pytest.raises(OSError, match="disk unavailable"):
            Modify(
                [
                    {"target": "playlist", "action": "add", "name": "Rollback", "refs": [ref]},
                    {"target": "up_next", "action": "add", "refs": [ref]},
                ],
                idempotency_key="rollback-test",
            )

        assert all(item["name"] != "Rollback" for item in list_playlists())
