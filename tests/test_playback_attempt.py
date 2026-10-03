from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src.ws.runner import PlaybackAttemptSession


class _UI:
    pass


async def _to_thread_inline(function, *args, **kwargs):
    return function(*args, **kwargs)


class PlaybackAttemptTests(unittest.IsolatedAsyncioTestCase):
    async def test_resumes_after_player_confirmation(self) -> None:
        pending = {
            "status": "requires_player_confirm",
            "tool": "play_online_audio",
            "message": "Allow player launch?",
            "data": {
                "player": "auto",
                "choices": [{"value": "mpv", "label": "mpv"}],
            },
        }
        success = {
            "status": "success",
            "tool": "play_online_audio",
            "data": {"name": "Song", "player": "mpv", "is_playing": True},
        }
        ui = _UI()
        ui.append_activity = AsyncMock()
        ui.send_error = AsyncMock()
        ui.append_agent_message = AsyncMock()
        ui.append_system_message = AsyncMock()
        runner = SimpleNamespace(
        _sync_tool_result_ui=AsyncMock(),
        _handoff_previous_provider=AsyncMock(),
    )
        ask_confirm = AsyncMock()
        finish = AsyncMock()
        attempt = PlaybackAttemptSession(
            ui,
            runner,
            "Song Artist",
            ask_confirm=ask_confirm,
            finish=finish,
        )

        with patch("src.ws.runner.registry.invoke_system", return_value=pending), \
            patch("src.ws.runner.complete_player_confirm", return_value=success) as complete, \
            patch("src.ws.runner.upsert_cached_song"), \
            patch("src.ws.runner.asyncio.to_thread", side_effect=_to_thread_inline):
            result = await attempt.invoke_tool("play_online_audio", {"query": "Song Artist"})
            self.assertIs(result, pending)
            self.assertIs(attempt.pending_player_confirm_result, pending)
            ask_confirm.assert_awaited_once()
            self.assertEqual(ask_confirm.await_args.kwargs["tool_args"]["stage"], "player_confirm")

            await attempt.complete_player_confirmation(
                "mpv",
                selected_metadata={"name": "Song", "artist": "Artist"},
                agent_handoff=True,
            )

        complete.assert_called_once_with(pending, "mpv")
        runner._handoff_previous_provider.assert_awaited_once_with(ui, "online")
        runner._sync_tool_result_ui.assert_awaited_with(ui, "play_online_audio", success)
        ui.append_system_message.assert_awaited_once()
        ui.append_agent_message.assert_not_awaited()
        finish.assert_awaited_once_with("Online playback selected.")
        self.assertIsNone(attempt.pending_player_confirm_result)
