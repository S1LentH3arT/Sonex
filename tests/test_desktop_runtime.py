from __future__ import annotations

import asyncio
import io
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from src.desktop.runtime.__main__ import StdioConnection
from src.desktop.runtime.sessions import SessionStore
from src.desktop.runtime.runner import DesktopRunner, DesktopUI
from src.ws.session_orchestration import session_context_for


@pytest.fixture(autouse=True)
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SONEX_HOME", str(tmp_path / ".sonex"))


def test_session_store_reads_cli_history_and_preserves_rich_content(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    session_id = store.create()
    messages = [{"role": "user", "content": "你好"}, {"role": "agent", "content": "Song", "tone": "system"}]
    store.save(session_id, messages)
    assert store.read(session_id) == messages
    assert store.list()[0]["title"] == "你好"
    assert json.loads((tmp_path / session_id / "transcript.jsonl").read_text().splitlines()[0])["session_id"] == session_id


@pytest.mark.parametrize("session_id", ["../secret", "/tmp/secret", "..", "x/y", "x\\y", ""])
def test_session_paths_cannot_escape_the_store(tmp_path: Path, session_id: str) -> None:
    with pytest.raises(ValueError):
        SessionStore(tmp_path).read(session_id)


def test_session_store_rejects_symlinked_transcript(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions")
    session_id = store.create()
    target = tmp_path / "outside"
    target.write_text("private")
    path = store.directory(session_id) / "transcript.jsonl"
    path.unlink()
    try:
        path.symlink_to(target)
    except OSError as exc:
        if getattr(exc, "winerror", None) == 1314:
            pytest.skip("Windows runner does not grant symlink privileges")
        raise
    with pytest.raises(ValueError):
        store.save(session_id, [])
    assert target.read_text() == "private"


def test_stdio_keeps_unicode_and_framing() -> None:
    async def check() -> None:
        output = io.StringIO()
        connection = StdioConnection(io.StringIO('{"text":"音乐"}\n'), output)
        assert json.loads(await connection.receive_text())["text"] == "音乐"
        await connection.send_text('{"text":"你好"}')
        assert output.getvalue() == '{"text":"你好"}\n'
    asyncio.run(check())


def test_session_switch_is_blocked_during_turn_and_keeps_player_state(tmp_path: Path) -> None:
    async def check() -> None:
        store = SessionStore(tmp_path)
        ui = DesktopUI(AsyncMock(), store)
        runner = DesktopRunner(store)
        original = ui.session_id
        other = store.create()
        context = session_context_for(ui)
        context.agent_interaction_active = True
        with pytest.raises(ValueError):
            await runner._switch(ui, other)
        assert ui.session_id == original
        context.agent_interaction_active = False
        context.values["_last_player_state"] = {"name": "Still playing"}
        context.values["_last_recommendation_tracks"] = ["old session"]
        await runner._switch(ui, other)
        assert ui.session_id == other
        assert context.values["_last_player_state"]["name"] == "Still playing"
        assert "_last_recommendation_tracks" not in context.values
    asyncio.run(check())


def test_chat_is_persisted_without_bye(tmp_path: Path) -> None:
    async def check() -> None:
        store = SessionStore(tmp_path)
        ui = DesktopUI(AsyncMock(), store)
        await ui.append_user_message("Keep me after a crash")
        assert store.read(ui.session_id)[0]["content"] == "Keep me after a crash"
    asyncio.run(check())


def test_stale_queue_mutation_is_rejected_and_refreshed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SONEX_HOME", str(tmp_path))
    async def check() -> None:
        store = SessionStore(tmp_path / "sessions")
        connection = AsyncMock()
        ui = DesktopUI(connection, store)
        with patch("src.desktop.runtime.runner.commit_up_next_state") as commit:
            await DesktopRunner(store).handle_desktop(ui, {"action": "queue", "command": "remove", "entry_id": "one", "revision": 99})
            commit.assert_not_called()
        events = [json.loads(call.args[0]) for call in connection.send_text.call_args_list]
        assert any(event["type"] == "error" for event in events)
        assert events[-1]["type"] == "desktop_queue"
    asyncio.run(check())


def test_mpv_seek_uses_absolute_milliseconds_and_rejects_invalid_values() -> None:
    from src.tools.playback_controller import LocalPlaybackController, MpvPlaybackAdapter
    from unittest.mock import Mock
    controller = LocalPlaybackController()
    adapter = MpvPlaybackAdapter(source_url="song.flac", source="local", metadata={})
    controller._adapter = adapter
    with patch.object(adapter, "_request") as request, patch.object(adapter, "status", return_value=Mock()):
        controller.seek(12500)
        request.assert_called_once_with(["seek", 12.5, "absolute+exact"])
        for invalid in [-1, float("nan"), float("inf"), True, "100"]:
            with pytest.raises(ValueError):
                controller.seek(invalid)


def test_natural_end_advances_once_but_manual_stop_does_not(tmp_path: Path) -> None:
    async def check() -> None:
        ui = DesktopUI(AsyncMock(), SessionStore(tmp_path))
        ui.on_track_end = AsyncMock()
        end = {"type": "player", "state": {"session_id": "playback-1", "ended": True, "progress_source": "local_player"}}
        await ui._send(end)
        await ui._send(end)
        await asyncio.sleep(0)
        ui.on_track_end.assert_awaited_once()
        await ui._send({"type": "player", "state": {"session_id": "manual-stop", "ended": True}})
        await asyncio.sleep(0)
        ui.on_track_end.assert_awaited_once()
    asyncio.run(check())


def test_auto_queue_cannot_replace_a_newly_started_track(tmp_path: Path) -> None:
    async def check() -> None:
        store = SessionStore(tmp_path)
        runner = DesktopRunner(store)
        ui = DesktopUI(AsyncMock(), store)
        with patch("src.desktop.runtime.runner.controller") as controller, \
                patch.object(runner, "_play_up_next_from_selection", new=AsyncMock()) as play:
            controller.current_session_id = "a-new-track"
            await runner._advance_queue(ui)
            play.assert_not_awaited()
    asyncio.run(check())


def test_auto_queue_plays_the_head_through_shared_playback(tmp_path: Path) -> None:
    async def check() -> None:
        store = SessionStore(tmp_path)
        runner = DesktopRunner(store)
        ui = DesktopUI(AsyncMock(), store)
        head = {"entry_id": "track", "ref": "local:track"}
        with patch("src.desktop.runtime.runner.controller") as controller, \
                patch("src.desktop.runtime.runner.up_next_snapshot", return_value={"items": [head]}), \
                patch.object(runner, "_play_up_next_from_selection", new=AsyncMock()) as play:
            controller.current_session_id = None
            await runner._advance_queue(ui)
            play.assert_awaited_once_with(ui, head)
            assert not ui.queue_advancing
            ui.auto_queue = False
            play.reset_mock()
            await runner._advance_queue(ui)
            play.assert_not_awaited()
    asyncio.run(check())


def test_outdated_cover_is_not_delivered(tmp_path: Path) -> None:
    async def check() -> None:
        connection = AsyncMock()
        ui = DesktopUI(connection, SessionStore(tmp_path))
        await ui._send({"type": "cover", "url": "new-cover"})
        connection.send_text.reset_mock()
        await ui._send({"type": "cover_image", "source_url": "old-cover", "data": "old"})
        connection.send_text.assert_not_awaited()
    asyncio.run(check())


def test_selected_queue_entry_is_promoted_before_shared_playback(tmp_path: Path) -> None:
    from src.tools.up_next import commit_up_next_state, up_next_snapshot

    async def check() -> None:
        store = SessionStore(tmp_path / "sessions")
        runner = DesktopRunner(store)
        ui = DesktopUI(AsyncMock(), store)
        state = up_next_snapshot()
        state["items"] = [
            {"ref": "local:first", "name": "First", "provider": "local"},
            {"ref": "local:second", "name": "Second", "provider": "local"},
        ]
        commit_up_next_state(state, expected_revision=state["revision"])
        state = up_next_snapshot()
        selected = state["items"][1]
        with patch.object(runner, "_play_up_next_from_selection", new=AsyncMock()) as play:
            await runner._queue(ui, {"command": "play", "entry_id": selected["entry_id"], "revision": state["revision"]})
            play.assert_awaited_once_with(ui, selected)
        assert up_next_snapshot()["items"][0]["entry_id"] == selected["entry_id"]
    asyncio.run(check())


def test_real_runtime_stdio_startup_and_eof(tmp_path: Path) -> None:
    import os
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-m", "src.desktop.runtime"],
        input='{"type":"desktop","action":"sessions"}\n',
        text=True, encoding="utf-8", capture_output=True, timeout=30,
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "SONEX_HOME": str(tmp_path / ".sonex")},
    )
    assert result.returncode == 0, result.stderr
    events = [json.loads(line) for line in result.stdout.splitlines()]
    assert {"desktop_snapshot", "desktop_sessions"} <= {event["type"] for event in events}


@pytest.mark.parametrize("kind", ["auth", "model"])
def test_cancelled_setup_unlocks_new_sessions(tmp_path: Path, kind: str) -> None:
    from src.ws.runner import AuthSetupSession, ModelSelectionSession

    async def check() -> None:
        ui = DesktopUI(AsyncMock(), SessionStore(tmp_path))
        runner = DesktopRunner(ui.store)
        await ui.send_auth_setup(provider="openai", step="provider", title="Connect", message="Choose")
        with pytest.raises(ValueError):
            runner._require_idle(ui)
        setup = AuthSetupSession(ui, "openai", None, runner) if kind == "auth" else ModelSelectionSession(ui)
        await setup.handle_input("__cancel__")
        assert ui.latest["auth_setup"]["active"] is False
        runner._require_idle(ui)
    asyncio.run(check())
