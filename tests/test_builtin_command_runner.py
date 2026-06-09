"""Tests test builtin command runner.

Contains pytest coverage for the test builtin command runner behavior.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import WebSocketDisconnect

from src.agent.core import AgentState
from src.api import ws_runner
from src.api.music_intent import MusicIntentDecision, MusicIntentRoute
from src.api.ws_runner import WebSocketRunner, _queue_payload
from src.auth.store import load_auth_store, set_api_key, set_default
from src.log import configure_file_logging, sonex_log_path
from src.thinking.config import ThinkingConfig


class FakeUI:
    """Groups related ui cases.

    Collects assertions that exercise ui behavior without mixing unrelated fixtures.
    """
    def __init__(self) -> None:
        """Verifies that init behaves as expected.

        Typical use: Use this in automated tests when guarding the init behavior against regressions.

        Example: __init__() -> passes without assertion failures when the behavior remains correct.
        """
        self.events: list[dict[str, object]] = []
        self.statuses: list[object] = []
        self.transcript: list[dict[str, str]] = []

    async def append_user_message(self, text: str) -> None:
        """Verifies that append user message behaves as expected.

        Typical use: Use this in automated tests when guarding the append user message behavior against regressions.

        Example: append_user_message() -> passes without assertion failures when the behavior remains correct.
        """
        self.transcript.append({"role": "user", "content": text})
        self.events.append({"type": "chat", "role": "user", "text": text})

    async def append_agent_message(self, text: str) -> None:
        """Verifies that append agent message behaves as expected.

        Typical use: Use this in automated tests when guarding the append agent message behavior against regressions.

        Example: append_agent_message() -> passes without assertion failures when the behavior remains correct.
        """
        self.transcript.append({"role": "agent", "content": text})
        self.events.append({"type": "chat", "role": "agent", "text": text})

    async def append_activity(self, **kwargs: object) -> str:
        """Verifies that append activity behaves as expected.

        Typical use: Use this in automated tests when guarding the append activity behavior against regressions.

        Example: append_activity() -> passes without assertion failures when the behavior remains correct.
        """
        self.events.append({"type": "activity", **kwargs})
        return str(kwargs.get("activity_id") or "activity_test")

    async def send_spotify_setup(self, **kwargs: object) -> None:
        """Verifies that send spotify setup behaves as expected.

        Typical use: Use this in automated tests when guarding the send spotify setup behavior against regressions.

        Example: send_spotify_setup() -> passes without assertion failures when the behavior remains correct.
        """
        self.events.append({"type": "spotify_setup", **kwargs})

    async def send_auth_setup(self, **kwargs: object) -> None:
        """Verifies that send auth setup behaves as expected.

        Typical use: Use this in automated tests when guarding the send auth setup behavior against regressions.

        Example: send_auth_setup() -> passes without assertion failures when the behavior remains correct.
        """
        self.events.append({"type": "auth_setup", **kwargs})

    async def send_auth_state(self, state: object) -> None:
        """Verifies that send auth state behaves as expected.

        Typical use: Use this in automated tests when guarding the send auth state behavior against regressions.

        Example: send_auth_state() -> passes without assertion failures when the behavior remains correct.
        """
        payload = state.to_event() if hasattr(state, "to_event") else {"type": "auth_state", "state": state}
        self.events.append(payload)

    async def send_help_panel(self, commands: list[object], **kwargs: object) -> None:
        """Verifies that send help panel behaves as expected.

        Typical use: Use this in automated tests when guarding the send help panel behavior against regressions.

        Example: send_help_panel() -> passes without assertion failures when the behavior remains correct.
        """
        self.events.append(
            {
                "type": "help_panel",
                "commands": commands,
                **kwargs,
            }
        )

    async def send_error(self, message: str) -> None:
        """Verifies that send error behaves as expected.

        Typical use: Use this in automated tests when guarding the send error behavior against regressions.

        Example: send_error() -> passes without assertion failures when the behavior remains correct.
        """
        self.events.append({"type": "error", "message": message})

    async def ask_confirm(self, attached: dict[str, object]) -> None:
        """Verifies that ask confirm behaves as expected.

        Typical use: Use this in automated tests when guarding the ask confirm behavior against regressions.

        Example: ask_confirm() -> passes without assertion failures when the behavior remains correct.
        """
        self.events.append(
            {
                "type": "confirm",
                "id": attached.get("id"),
                "tool_name": attached.get("tool_name"),
                "tool_args": attached.get("tool_args") or {},
                "message": attached.get("message"),
                "choices": attached.get("choices") or [],
            }
        )

    async def send_cover(self, url: str) -> None:
        """Verifies that send cover behaves as expected.

        Typical use: Use this in automated tests when guarding the send cover behavior against regressions.

        Example: send_cover() -> passes without assertion failures when the behavior remains correct.
        """
        self.events.append({"type": "cover", "url": url})

    async def send_status(self, status: object, **kwargs: object) -> None:
        """Verifies that send status behaves as expected.

        Typical use: Use this in automated tests when guarding the send status behavior against regressions.

        Example: send_status() -> passes without assertion failures when the behavior remains correct.
        """
        self.events.append({"type": "status", "status": status, **kwargs})

    async def _send(self, payload: dict[str, object]) -> None:
        """Verifies that send behaves as expected.

        Typical use: Use this in automated tests when guarding the send behavior against regressions.

        Example: _send() -> passes without assertion failures when the behavior remains correct.
        """
        self.events.append(payload)

    async def close(self) -> None:
        """Verifies that close behaves as expected.

        Typical use: Use this in automated tests when guarding the close behavior against regressions.

        Example: close() -> passes without assertion failures when the behavior remains correct.
        """
        self.events.append({"type": "closed"})

    def set_status(self, status: object) -> None:
        """Verifies that set status behaves as expected.

        Typical use: Use this in automated tests when guarding the set status behavior against regressions.

        Example: set_status() -> passes without assertion failures when the behavior remains correct.
        """
        self.statuses.append(status)


class FakeWebSocket:
    """Groups related web socket cases.

    Collects assertions that exercise web socket behavior without mixing unrelated fixtures.
    """
    def __init__(self) -> None:
        """Verifies that init behaves as expected.

        Typical use: Use this in automated tests when guarding the init behavior against regressions.

        Example: __init__() -> passes without assertion failures when the behavior remains correct.
        """
        self.sent: list[dict[str, object]] = []
        self.accepted = False
        self._sent_user_input = False
        self._sent_confirm_result = False
        self._sent_youtube_candidate = False

    async def accept(self) -> None:
        """Verifies that accept behaves as expected.

        Typical use: Use this in automated tests when guarding the accept behavior against regressions.

        Example: accept() -> passes without assertion failures when the behavior remains correct.
        """
        self.accepted = True

    async def send_text(self, text: str) -> None:
        """Verifies that send text behaves as expected.

        Typical use: Use this in automated tests when guarding the send text behavior against regressions.

        Example: send_text() -> passes without assertion failures when the behavior remains correct.
        """
        self.sent.append(json.loads(text))

    async def receive_text(self) -> str:
        """Verifies that receive text behaves as expected.

        Typical use: Use this in automated tests when guarding the receive text behavior against regressions.

        Example: receive_text() -> passes without assertion failures when the behavior remains correct.
        """
        if not self._sent_user_input:
            self._sent_user_input = True
            return json.dumps({"type": "user_input", "text": "/play Song Artist"})
        if not self._sent_confirm_result:
            confirm_id = next(
                (
                    str(event["id"])
                    for event in self.sent
                    if event.get("type") == "confirm" and event.get("tool_name") == "playback_choice"
                ),
                None,
            )
            if confirm_id:
                self._sent_confirm_result = True
                return json.dumps({"type": "confirm_result", "id": confirm_id, "decision": "online_play"})
        if not self._sent_youtube_candidate:
            confirm_id = next(
                (
                    str(event["id"])
                    for event in self.sent
                    if event.get("type") == "confirm" and event.get("tool_name") == "online_audio_candidate"
                ),
                None,
            )
            if confirm_id:
                self._sent_youtube_candidate = True
                return json.dumps({"type": "confirm_result", "id": confirm_id, "decision": "youtube_candidate:youtube_abc"})
        await asyncio.sleep(0)
        raise WebSocketDisconnect()


class BuiltinCommandRunnerTests(unittest.IsolatedAsyncioTestCase):
    """Groups related builtin command runner tests cases.

    Collects assertions that exercise builtin command runner tests behavior without mixing unrelated fixtures.
    """
    async def test_auth_resume_reenters_music_router_without_duplicate_user_message(self) -> None:
        """Verifies that auth resume reenters music router without duplicate user message behaves as expected.

        Typical use: Use this in automated tests when guarding the auth resume reenters music router without duplicate user message behavior against regressions.

        Example: test_auth_resume_reenters_music_router_without_duplicate_user_message() -> passes without assertion failures when the behavior remains correct.
        """
        runner = WebSocketRunner()
        runner._handle_user_input = AsyncMock()
        ui = FakeUI()
        session = ws_runner.AuthSetupSession(ui, "openai", "给我推荐几首歌", runner)
        setattr(ui, "_auth_setup", session)

        with patch("src.api.ws_runner._set_runtime_default_provider"), \
             patch("src.api.ws_runner.ThinkingConfig.reload"), \
             patch("src.api.ws_runner._llm_auth_state", return_value=object()):
            await session._finish()

        runner._handle_user_input.assert_awaited_once_with(
            ui,
            "给我推荐几首歌",
            append_user_message=False,
        )

    async def test_recommendation_tool_result_is_saved_for_number_references(self) -> None:
        """Verifies that recommendation tool result is saved for number references behaves as expected.

        Typical use: Use this in automated tests when guarding the recommendation tool result is saved for number references behavior against regressions.

        Example: test_recommendation_tool_result_is_saved_for_number_references() -> passes without assertion failures when the behavior remains correct.
        """
        runner = WebSocketRunner()
        ui = FakeUI()
        result = {
            "status": "success",
            "message": "Recommended 2 tracks.",
            "data": {
                "tracks": [
                    {"name": "七里香", "artist": "周杰伦"},
                    {"name": "晴天", "artist": "周杰伦"},
                ]
            },
        }

        setattr(ui, "_recommendation_turn_active", True)
        await runner._sync_tool_result_ui(ui, "spotify_search", result)

        saved = getattr(ui, "_last_recommendation_tracks")
        self.assertEqual([track["name"] for track in saved], ["七里香", "晴天"])
        self.assertEqual([track["artist"] for track in saved], ["周杰伦", "周杰伦"])
        self.assertTrue(any(event.get("type") == "search_results" for event in ui.events))

    async def test_help_does_not_trigger_agent_or_auth_setup(self) -> None:
        """Verifies that help does not trigger agent or auth setup behaves as expected.

        Typical use: Use this in automated tests when guarding the help does not trigger agent or auth setup behavior against regressions.

        Example: test_help_does_not_trigger_agent_or_auth_setup() -> passes without assertion failures when the behavior remains correct.
        """
        runner = WebSocketRunner()
        runner._run_agent_turn = AsyncMock()
        ui = FakeUI()

        await runner._handle_user_input(ui, "/help")

        self.assertFalse(runner._run_agent_turn.called)
        self.assertFalse([event for event in ui.events if event.get("type") == "auth_setup"])
        help_events = [event for event in ui.events if event.get("type") == "help_panel"]
        self.assertTrue(help_events)
        self.assertTrue(any(command.usage == "/recommend [taste]" for command in help_events[0]["commands"]))
        self.assertFalse(any("Available commands" in str(event.get("text")) for event in ui.events))

    async def test_help_prefix_filters_help_panel_commands(self) -> None:
        """Verifies that help prefix filters help panel commands behaves as expected.

        Typical use: Use this in automated tests when guarding the help prefix filters help panel commands behavior against regressions.

        Example: test_help_prefix_filters_help_panel_commands() -> passes without assertion failures when the behavior remains correct.
        """
        runner = WebSocketRunner()
        runner._run_agent_turn = AsyncMock()
        ui = FakeUI()

        await runner._handle_user_input(ui, "/help re")

        help_events = [event for event in ui.events if event.get("type") == "help_panel"]
        self.assertTrue(help_events)
        self.assertEqual([command.name for command in help_events[0]["commands"]], ["recommend", "resume"])
        self.assertFalse(runner._run_agent_turn.called)

    async def test_bare_slash_opens_help_panel(self) -> None:
        """Verifies that bare slash opens help panel behaves as expected.

        Typical use: Use this in automated tests when guarding the bare slash opens help panel behavior against regressions.

        Example: test_bare_slash_opens_help_panel() -> passes without assertion failures when the behavior remains correct.
        """
        runner = WebSocketRunner()
        runner._run_agent_turn = AsyncMock()
        ui = FakeUI()

        await runner._handle_user_input(ui, "/")

        self.assertTrue([event for event in ui.events if event.get("type") == "help_panel"])
        self.assertFalse(runner._run_agent_turn.called)

    async def test_setup_spotify_starts_spotify_setup(self) -> None:
        """Verifies that setup spotify starts spotify setup behaves as expected.

        Typical use: Use this in automated tests when guarding the setup spotify starts spotify setup behavior against regressions.

        Example: test_setup_spotify_starts_spotify_setup() -> passes without assertion failures when the behavior remains correct.
        """
        runner = WebSocketRunner()
        runner._run_agent_turn = AsyncMock()
        ui = FakeUI()

        with patch("src.api.ws_runner.spotify_redirect_uri", return_value="http://127.0.0.1:9957/callback"):
            await runner._handle_user_input(ui, "/setup spotify")

        self.assertFalse(runner._run_agent_turn.called)
        self.assertTrue(getattr(ui, "_spotify_setup"))
        self.assertTrue([event for event in ui.events if event.get("type") == "spotify_setup"])

    async def test_unknown_command_does_not_trigger_agent(self) -> None:
        """Verifies that unknown command does not trigger agent behaves as expected.

        Typical use: Use this in automated tests when guarding the unknown command does not trigger agent behavior against regressions.

        Example: test_unknown_command_does_not_trigger_agent() -> passes without assertion failures when the behavior remains correct.
        """
        runner = WebSocketRunner()
        runner._run_agent_turn = AsyncMock()
        ui = FakeUI()

        await runner._handle_user_input(ui, "/foo")

        self.assertFalse(runner._run_agent_turn.called)
        self.assertTrue(any("Unknown command" in str(event.get("text")) for event in ui.events))

    async def test_bye_saves_transcript_and_does_not_trigger_agent(self) -> None:
        """Verifies that bye saves transcript and does not trigger agent behaves as expected.

        Typical use: Use this in automated tests when guarding the bye saves transcript and does not trigger agent behavior against regressions.

        Example: test_bye_saves_transcript_and_does_not_trigger_agent() -> passes without assertion failures when the behavior remains correct.
        """
        runner = WebSocketRunner()
        runner._run_agent_turn = AsyncMock()
        ui = FakeUI()

        with tempfile.TemporaryDirectory() as home, patch.dict("os.environ", {"SONEX_HOME": home}):
            await runner._handle_user_input(ui, "/bye")

            transcripts = list((Path(home) / "sessions").glob("*/transcript.jsonl"))
            self.assertEqual(len(transcripts), 1)
            payload = _read_jsonl(transcripts[0])

        self.assertFalse(runner._run_agent_turn.called)
        self.assertFalse([event for event in ui.events if event.get("type") == "auth_setup"])
        self.assertTrue(all(item["reason"] == "bye" for item in payload))
        self.assertTrue(payload)
        self.assertTrue(any(event.get("type") == "bye" for event in ui.events))
        self.assertTrue(any("Session saved" in str(event.get("text")) for event in ui.events))

    async def test_quit_saves_transcript_and_does_not_trigger_agent(self) -> None:
        """Verifies that quit saves transcript and does not trigger agent behaves as expected.

        Typical use: Use this in automated tests when guarding the quit saves transcript and does not trigger agent behavior against regressions.

        Example: test_quit_saves_transcript_and_does_not_trigger_agent() -> passes without assertion failures when the behavior remains correct.
        """
        runner = WebSocketRunner()
        runner._run_agent_turn = AsyncMock()
        ui = FakeUI()

        with tempfile.TemporaryDirectory() as home, patch.dict("os.environ", {"SONEX_HOME": home}):
            await runner._handle_user_input(ui, "/quit")

            transcripts = list((Path(home) / "sessions").glob("*/transcript.jsonl"))
            self.assertEqual(len(transcripts), 1)
            payload = _read_jsonl(transcripts[0])

        self.assertFalse(runner._run_agent_turn.called)
        self.assertFalse([event for event in ui.events if event.get("type") == "auth_setup"])
        self.assertTrue(all(item["reason"] == "quit" for item in payload))
        self.assertTrue(payload)
        self.assertTrue(any(event.get("type") == "bye" for event in ui.events))
        self.assertTrue(any("Session saved" in str(event.get("text")) for event in ui.events))

    async def test_logout_removes_current_auth_provider_and_exits(self) -> None:
        """Verifies that logout removes current auth provider and exits behaves as expected.

        Typical use: Use this in automated tests when guarding the logout removes current auth provider and exits behavior against regressions.

        Example: test_logout_removes_current_auth_provider_and_exits() -> passes without assertion failures when the behavior remains correct.
        """
        runner = WebSocketRunner()
        runner._run_agent_turn = AsyncMock()
        ui = FakeUI()

        with self._isolated_auth_env({"SONEX_DEFAULT_PROVIDER": "openai"}) as home:
            set_api_key("openai", "sk-test")
            set_default("openai", model="gpt-5.2")

            await runner._handle_user_input(ui, "/logout")

            store = load_auth_store()
            transcripts = list((Path(home) / "sessions").glob("*/transcript.jsonl"))
            self.assertEqual(len(transcripts), 1)
            payload = _read_jsonl(transcripts[0])

        self.assertFalse(runner._run_agent_turn.called)
        self.assertNotIn("openai", store.providers)
        self.assertIsNone(store.default_provider)
        self.assertIsNone(store.default_model)
        self.assertTrue(all(item["reason"] == "logout" for item in payload))
        self.assertTrue(any(event.get("type") == "bye" for event in ui.events))
        self.assertTrue(any(event.get("text") == "Successfully log out." for event in ui.events))

    async def test_logout_env_credentials_warns_and_exits_without_success_message(self) -> None:
        """Verifies that logout env credentials warns and exits without success message behaves as expected.

        Typical use: Use this in automated tests when guarding the logout env credentials warns and exits without success message behavior against regressions.

        Example: test_logout_env_credentials_warns_and_exits_without_success_message() -> passes without assertion failures when the behavior remains correct.
        """
        runner = WebSocketRunner()
        runner._run_agent_turn = AsyncMock()
        ui = FakeUI()

        with self._isolated_auth_env({"SONEX_DEFAULT_PROVIDER": "openai", "SONEX_OPENAI_API_KEY": "sk-env"}) as home:
            await runner._handle_user_input(ui, "/logout")

            transcripts = list((Path(home) / "sessions").glob("*/transcript.jsonl"))
            self.assertEqual(len(transcripts), 1)
            payload = _read_jsonl(transcripts[0])

        self.assertFalse(runner._run_agent_turn.called)
        self.assertTrue(all(item["reason"] == "logout" for item in payload))
        self.assertTrue(any(event.get("type") == "bye" for event in ui.events))
        self.assertTrue(any("Cannot clear environment variable credentials" in str(event.get("text")) for event in ui.events))
        self.assertFalse(any(event.get("text") == "Successfully log out." for event in ui.events))

    async def test_logout_when_not_logged_in_does_not_exit(self) -> None:
        """Verifies that logout when not logged in does not exit behaves as expected.

        Typical use: Use this in automated tests when guarding the logout when not logged in does not exit behavior against regressions.

        Example: test_logout_when_not_logged_in_does_not_exit() -> passes without assertion failures when the behavior remains correct.
        """
        runner = WebSocketRunner()
        runner._run_agent_turn = AsyncMock()
        ui = FakeUI()

        with self._isolated_auth_env({"SONEX_DEFAULT_PROVIDER": "openai"}) as home:
            await runner._handle_user_input(ui, "/logout")

            transcripts_dir = Path(home) / "sessions"
            transcripts = list(transcripts_dir.glob("*/transcript.jsonl")) if transcripts_dir.exists() else []

        self.assertFalse(runner._run_agent_turn.called)
        self.assertEqual(transcripts, [])
        self.assertFalse(any(event.get("type") == "bye" for event in ui.events))
        self.assertTrue(any(event.get("text") == "You are not logged in." for event in ui.events))

    async def test_recommend_routes_to_agent_with_command_intent(self) -> None:
        """Verifies that recommend routes to agent with command intent behaves as expected.

        Typical use: Use this in automated tests when guarding the recommend routes to agent with command intent behavior against regressions.

        Example: test_recommend_routes_to_agent_with_command_intent() -> passes without assertion failures when the behavior remains correct.
        """
        runner = WebSocketRunner()
        runner._run_agent_turn = AsyncMock()
        ui = FakeUI()

        with self._isolated_auth_env({"SONEX_DEFAULT_PROVIDER": "openai", "SONEX_OPENAI_API_KEY": "sk-test"}):
            await runner._handle_user_input(ui, "/recommend 华语女声")
            await asyncio.sleep(0)

        runner._run_agent_turn.assert_awaited_once()
        call = runner._run_agent_turn.await_args
        self.assertEqual(call.args[:2], (ui, "/recommend 华语女声"))
        intent = call.kwargs["command_intent"]
        self.assertEqual(intent.command, "recommend")
        self.assertEqual(intent.args, "华语女声")
        self.assertIn("spotify_recommend", intent.allowed_tools)

    async def test_search_routes_to_agent_with_search_intent(self) -> None:
        """Verifies that search routes to agent with search intent behaves as expected.

        Typical use: Use this in automated tests when guarding the search routes to agent with search intent behavior against regressions.

        Example: test_search_routes_to_agent_with_search_intent() -> passes without assertion failures when the behavior remains correct.
        """
        runner = WebSocketRunner()
        runner._run_agent_turn = AsyncMock()
        ui = FakeUI()

        with self._isolated_auth_env({"SONEX_DEFAULT_PROVIDER": "openai", "SONEX_OPENAI_API_KEY": "sk-test"}):
            await runner._handle_user_input(ui, "/search jay")
            await asyncio.sleep(0)

        runner._run_agent_turn.assert_awaited_once()
        intent = runner._run_agent_turn.await_args.kwargs["command_intent"]
        self.assertEqual(intent.command, "search")
        self.assertEqual(intent.args, "jay")
        self.assertIn("spotify_search", intent.allowed_tools)

    async def test_play_number_starts_play_selection_without_agent_turn(self) -> None:
        """Verifies that play number starts play selection without agent turn behaves as expected.

        Typical use: Use this in automated tests when guarding the play number starts play selection without agent turn behavior against regressions.

        Example: test_play_number_starts_play_selection_without_agent_turn() -> passes without assertion failures when the behavior remains correct.
        """
        runner = WebSocketRunner()
        runner._run_agent_turn = AsyncMock()
        ui = FakeUI()

        with patch("src.api.ws_runner.search_local_file", return_value="No local files found related to '1'."), \
             patch("src.api.ws_runner.find_best_cached_song", return_value=None), \
             self._isolated_auth_env({"SONEX_DEFAULT_PROVIDER": "openai", "SONEX_OPENAI_API_KEY": "sk-test"}):
            await runner._handle_user_input(ui, "/play 1")
            await asyncio.sleep(0)

        self.assertFalse(runner._run_agent_turn.called)
        confirm_events = [event for event in ui.events if event.get("type") == "confirm"]
        self.assertTrue(confirm_events)
        self.assertEqual(confirm_events[-1]["tool_name"], "playback_choice")
        self.assertEqual(confirm_events[-1]["tool_args"]["query"], "1")
        self.assertIn("spotify_play", [choice["value"] for choice in confirm_events[-1]["choices"]])

    async def test_play_local_match_can_skip_to_playback_method_choices(self) -> None:
        """Verifies that play local match can skip to playback method choices behaves as expected.

        Typical use: Use this in automated tests when guarding the play local match can skip to playback method choices behavior against regressions.

        Example: test_play_local_match_can_skip_to_playback_method_choices() -> passes without assertion failures when the behavior remains correct.
        """
        runner = WebSocketRunner()
        runner._run_agent_turn = AsyncMock()
        ui = FakeUI()

        with patch("src.api.ws_runner.search_local_file", return_value="/home/user/Music/song.mp3"), \
             patch("src.api.ws_runner.find_best_cached_song", return_value=None):
            await runner._handle_user_input(ui, "/play song")

            first_confirm = [event for event in ui.events if event.get("type") == "confirm"][-1]
            self.assertIn("播放本地文件 song.mp3", first_confirm["message"])
            self.assertEqual([choice["value"] for choice in first_confirm["choices"]], ["play_local", "skip_local", "cancel"])

            session = getattr(ui, "_play_selection")
            await session.handle_choice("skip_local")

        confirm_events = [event for event in ui.events if event.get("type") == "confirm"]
        self.assertEqual(confirm_events[-1]["message"], "选择播放方式")
        self.assertEqual(
            [choice["value"] for choice in confirm_events[-1]["choices"]],
            ["spotify_play", "apple_music_play", "online_play", "cancel"],
        )

    async def test_explicit_natural_language_playback_starts_selection_session(self) -> None:
        """Verifies that explicit natural language playback starts selection session behaves as expected.

        Typical use: Use this in automated tests when guarding the explicit natural language playback starts selection session behavior against regressions.

        Example: test_explicit_natural_language_playback_starts_selection_session() -> passes without assertion failures when the behavior remains correct.
        """
        runner = WebSocketRunner()
        runner._run_agent_turn = AsyncMock()
        ui = FakeUI()

        with patch("src.api.ws_runner.search_local_file", return_value="No local files found related to '青花瓷'."), \
             patch("src.api.ws_runner.find_best_cached_song", return_value=None):
            await runner._handle_user_input(ui, "播放 青花瓷")

        self.assertFalse(runner._run_agent_turn.called)
        confirm_events = [event for event in ui.events if event.get("type") == "confirm"]
        self.assertTrue(confirm_events)
        self.assertEqual(confirm_events[-1]["tool_args"]["query"], "青花瓷")
        self.assertEqual(confirm_events[-1]["tool_name"], "playback_choice")

    async def test_llm_track_play_intent_starts_play_selection(self) -> None:
        """Verifies that llm track play intent starts play selection behaves as expected.

        Typical use: Use this in automated tests when guarding the llm track play intent starts play selection behavior against regressions.

        Example: test_llm_track_play_intent_starts_play_selection() -> passes without assertion failures when the behavior remains correct.
        """
        runner = WebSocketRunner()
        runner._run_agent_turn = AsyncMock()
        ui = FakeUI()
        decision = MusicIntentDecision(
            route=MusicIntentRoute.CONFIRM_TRACK_PLAY,
            query="周杰伦 七里香",
            confidence=0.93,
        )

        with patch("src.api.ws_runner.classify_music_intent", return_value=decision), \
             patch("src.api.ws_runner.asyncio.to_thread", side_effect=_to_thread_inline), \
             patch("src.api.ws_runner.search_local_file", return_value="No local files found."), \
             patch("src.api.ws_runner.find_best_cached_song", return_value=None):
            await runner._handle_user_input(ui, "最近我对周杰伦的《七里香》很感兴趣")

        self.assertFalse(runner._run_agent_turn.called)
        self.assertIsNone(getattr(ui, "_music_intent_confirmation", None))
        confirm = [event for event in ui.events if event.get("type") == "confirm"][-1]
        self.assertEqual(confirm["tool_name"], "playback_choice")
        self.assertEqual(confirm["tool_args"]["query"], "周杰伦 七里香")

    async def test_track_interest_acceptance_starts_play_selection(self) -> None:
        """Verifies that track interest acceptance starts play selection behaves as expected.

        Typical use: Use this in automated tests when guarding the track interest acceptance starts play selection behavior against regressions.

        Example: test_track_interest_acceptance_starts_play_selection() -> passes without assertion failures when the behavior remains correct.
        """
        runner = WebSocketRunner()
        ui = FakeUI()
        decision = MusicIntentDecision(
            route=MusicIntentRoute.CONFIRM_TRACK_PLAY,
            query="周杰伦 七里香",
            confidence=0.93,
        )

        with patch("src.api.ws_runner.classify_music_intent", return_value=decision), \
             patch("src.api.ws_runner.asyncio.to_thread", side_effect=_to_thread_inline), \
             patch("src.api.ws_runner.search_local_file", return_value="No local files found."), \
             patch("src.api.ws_runner.find_best_cached_song", return_value=None):
            await runner._handle_user_input(ui, "最近我对周杰伦的《七里香》很感兴趣")

        playback_confirm = [event for event in ui.events if event.get("tool_name") == "playback_choice"][-1]
        self.assertEqual(playback_confirm["tool_args"]["query"], "周杰伦 七里香")

    async def test_general_music_question_does_not_start_playback(self) -> None:
        """Verifies that general music question does not start playback behaves as expected.

        Typical use: Use this in automated tests when guarding the general music question does not start playback behavior against regressions.

        Example: test_general_music_question_does_not_start_playback() -> passes without assertion failures when the behavior remains correct.
        """
        runner = WebSocketRunner()
        runner._run_agent_turn = AsyncMock()
        ui = FakeUI()
        decision = MusicIntentDecision(
            route=MusicIntentRoute.GENERAL,
            confidence=0.98,
        )

        with patch("src.api.ws_runner.classify_music_intent", return_value=decision), \
             patch("src.api.ws_runner.asyncio.to_thread", side_effect=_to_thread_inline), \
             patch("src.api.ws_runner._llm_auth_ready", return_value=(True, "openai", None)):
            await runner._handle_user_input(ui, "七里香的创作背景是什么")
            await asyncio.sleep(0)

        intent = runner._run_agent_turn.await_args.kwargs["command_intent"]
        self.assertIn("request_playback_selection", intent.allowed_tools)
        self.assertNotIn("spotify_play", intent.allowed_tools)
        self.assertNotIn("apple_music_play", intent.allowed_tools)
        self.assertNotIn("play_youtube_song", intent.allowed_tools)
        self.assertNotIn("play_local_song", intent.allowed_tools)
        self.assertIsNone(getattr(ui, "_play_selection", None))

    async def test_agent_playback_request_tool_starts_play_selection(self) -> None:
        """Verifies that agent playback request tool starts play selection behaves as expected.

        Typical use: Use this in automated tests when guarding the agent playback request tool starts play selection behavior against regressions.

        Example: test_agent_playback_request_tool_starts_play_selection() -> passes without assertion failures when the behavior remains correct.
        """
        runner = WebSocketRunner()
        ui = FakeUI()

        def agent_events(*args: object, **kwargs: object):
            yield AgentState(
                type="tool",
                tool="request_playback_selection",
                result={
                    "status": "requires_play_selection",
                    "tool": "request_playback_selection",
                    "message": "Entering playback selection for 青花瓷.",
                    "data": {"query": "青花瓷"},
                },
            )
            yield AgentState(type="complete", content="")

        with patch("src.api.ws_runner.agent_loop", side_effect=agent_events), \
             patch("src.api.ws_runner.search_local_file", return_value="No local files found."), \
             patch("src.api.ws_runner.find_best_cached_song", return_value=None):
            await runner._run_agent_turn(ui, "能不能来点青花瓷")

        session = getattr(ui, "_play_selection")
        self.assertEqual(session.query, "青花瓷")
        confirm = [event for event in ui.events if event.get("tool_name") == "playback_choice"][-1]
        self.assertEqual(confirm["tool_args"]["query"], "青花瓷")

    async def test_recommendation_route_uses_restricted_agent_without_confirm(self) -> None:
        """Verifies that recommendation route uses restricted agent without confirm behaves as expected.

        Typical use: Use this in automated tests when guarding the recommendation route uses restricted agent without confirm behavior against regressions.

        Example: test_recommendation_route_uses_restricted_agent_without_confirm() -> passes without assertion failures when the behavior remains correct.
        """
        runner = WebSocketRunner()
        runner._run_agent_turn = AsyncMock()
        ui = FakeUI()
        decision = MusicIntentDecision(
            route=MusicIntentRoute.RECOMMEND,
            query="周杰伦",
            confidence=0.9,
        )

        with patch("src.api.ws_runner.classify_music_intent", return_value=decision), \
             patch("src.api.ws_runner.asyncio.to_thread", side_effect=_to_thread_inline), \
             patch("src.api.ws_runner._llm_auth_ready", return_value=(True, "openai", None)):
            await runner._handle_user_input(ui, "给我推荐几首周杰伦的歌")
            await asyncio.sleep(0)

        intent = runner._run_agent_turn.await_args.kwargs["command_intent"]
        self.assertEqual(intent.command, "recommend")
        self.assertIn("spotify_recommend", intent.allowed_tools)
        self.assertNotIn("spotify_play", intent.allowed_tools)
        self.assertFalse([event for event in ui.events if event.get("type") == "confirm"])

    async def test_natural_language_recommendation_reference_starts_selected_track(self) -> None:
        """Verifies that natural language recommendation reference starts selected track behaves as expected.

        Typical use: Use this in automated tests when guarding the natural language recommendation reference starts selected track behavior against regressions.

        Example: test_natural_language_recommendation_reference_starts_selected_track() -> passes without assertion failures when the behavior remains correct.
        """
        runner = WebSocketRunner()
        runner._run_agent_turn = AsyncMock()
        ui = FakeUI()
        setattr(ui, "_last_recommendation_tracks", [
            {"name": "七里香", "artist": "周杰伦"},
            {"name": "晴天", "artist": "周杰伦"},
        ])
        decision = MusicIntentDecision(
            route=MusicIntentRoute.EXPLICIT_PLAY,
            query=None,
            recommendation_index=2,
            confidence=0.99,
        )

        with patch("src.api.ws_runner.classify_music_intent", return_value=decision), \
             patch("src.api.ws_runner.search_local_file", return_value="No local files found."), \
             patch("src.api.ws_runner.find_best_cached_song", return_value=None):
            await runner._handle_user_input(ui, "播放第 2 首")

        confirm = [event for event in ui.events if event.get("tool_name") == "playback_choice"][-1]
        self.assertEqual(confirm["tool_args"]["query"], "晴天 周杰伦")

    async def test_out_of_range_recommendation_reference_reports_valid_range(self) -> None:
        """Verifies that out of range recommendation reference reports valid range behaves as expected.

        Typical use: Use this in automated tests when guarding the out of range recommendation reference reports valid range behavior against regressions.

        Example: test_out_of_range_recommendation_reference_reports_valid_range() -> passes without assertion failures when the behavior remains correct.
        """
        runner = WebSocketRunner()
        ui = FakeUI()
        setattr(ui, "_last_recommendation_tracks", [{"name": "七里香", "artist": "周杰伦"}])
        decision = MusicIntentDecision(
            route=MusicIntentRoute.EXPLICIT_PLAY,
            query=None,
            recommendation_index=2,
            confidence=0.99,
        )

        with patch("src.api.ws_runner.classify_music_intent", return_value=decision), \
             patch("src.api.ws_runner.asyncio.to_thread", side_effect=_to_thread_inline):
            await runner._handle_user_input(ui, "就刚才第二首")

        self.assertTrue(any("1-1" in str(event.get("text")) for event in ui.events))
        self.assertIsNone(getattr(ui, "_play_selection", None))

    async def test_polite_natural_language_playback_starts_selection_session(self) -> None:
        """Verifies that polite natural language playback starts selection session behaves as expected.

        Typical use: Use this in automated tests when guarding the polite natural language playback starts selection session behavior against regressions.

        Example: test_polite_natural_language_playback_starts_selection_session() -> passes without assertion failures when the behavior remains correct.
        """
        runner = WebSocketRunner()
        runner._run_agent_turn = AsyncMock()
        ui = FakeUI()

        with patch("src.api.ws_runner.search_local_file", return_value="No local files found related to '方大同的Sorry'."), \
             patch("src.api.ws_runner.find_best_cached_song", return_value=None), \
             patch("src.api.ws_runner._llm_auth_ready", return_value=(False, "openai", "missing")):
            await runner._handle_user_input(ui, "帮我放一首方大同的Sorry")

        self.assertFalse(runner._run_agent_turn.called)
        confirm_events = [event for event in ui.events if event.get("type") == "confirm"]
        self.assertTrue(confirm_events)
        self.assertEqual(confirm_events[-1]["tool_args"]["query"], "方大同的Sorry")
        self.assertEqual(confirm_events[-1]["tool_name"], "playback_choice")

    async def test_want_to_listen_playback_online_choice_starts_song_metadata_candidates(self) -> None:
        """Verifies that want to listen playback online choice starts song metadata candidates behaves as expected.

        Typical use: Use this in automated tests when guarding the want to listen playback online choice starts song metadata candidates behavior against regressions.

        Example: test_want_to_listen_playback_online_choice_starts_song_metadata_candidates() -> passes without assertion failures when the behavior remains correct.
        """
        runner = WebSocketRunner()
        runner._run_agent_turn = AsyncMock()
        ui = FakeUI()
        metadata_result = {
            "candidates": [
                {
                    "id": "itunes-track",
                    "metadata_source": "itunes",
                    "provider": "itunes",
                    "name": "青花瓷",
                    "artist": "周杰伦",
                    "artists": ["周杰伦"],
                    "album": "我很忙",
                    "duration_ms": 239000,
                    "uri": "itunes:track:qinghuaci",
                }
            ],
            "source_attempts": [{"provider": "itunes", "status": "success", "candidate_count": 1, "credible_count": 1, "message": "iTunes returned 1 candidate."}],
        }

        with patch("src.api.ws_runner.search_local_file", return_value="No local files found related to '青花瓷'."), \
             patch("src.api.ws_runner.find_best_cached_song", return_value=None), \
             patch("src.api.ws_runner._llm_auth_ready", return_value=(False, "openai", "missing")):
            await runner._handle_user_input(ui, "我想听 青花瓷")

        self.assertFalse(runner._run_agent_turn.called)
        session = getattr(ui, "_play_selection")
        with patch("src.api.ws_runner.search_track_metadata_candidates", return_value=metadata_result) as metadata_search, \
             patch("src.api.ws_runner.search_youtube_songs") as youtube_search, \
             patch("src.api.ws_runner.online_audio_configured", return_value=True), \
             patch("src.api.ws_runner.asyncio.to_thread", side_effect=_to_thread_inline):
            await session.handle_choice("online_play")

        metadata_search.assert_called_once_with("青花瓷", 5)
        youtube_search.assert_not_called()
        confirm_events = [event for event in ui.events if event.get("type") == "confirm"]
        self.assertEqual(confirm_events[-1]["tool_name"], "song_candidate")
        self.assertEqual(confirm_events[-1]["choices"][0]["label"], "周杰伦-我很忙--青花瓷")
        self.assertTrue(any(event.get("type") == "activity" and event.get("title") == "iTunes" for event in ui.events))

    async def test_online_choice_without_open_audio_provider_still_starts_song_metadata_candidates(self) -> None:
        """Verifies that online choice without open audio provider still starts song metadata candidates behaves as expected.

        Typical use: Use this in automated tests when guarding the online choice without open audio provider still starts song metadata candidates behavior against regressions.

        Example: test_online_choice_without_open_audio_provider_still_starts_song_metadata_candidates() -> passes without assertion failures when the behavior remains correct.
        """
        runner = WebSocketRunner()
        runner._run_agent_turn = AsyncMock()
        ui = FakeUI()
        metadata_result = {
            "candidates": [
                {
                    "id": "itunes-track",
                    "metadata_source": "itunes",
                    "provider": "itunes",
                    "name": "青花瓷",
                    "artist": "周杰伦",
                    "artists": ["周杰伦"],
                    "album": "我很忙",
                    "duration_ms": 239000,
                    "uri": "itunes:track:qinghuaci",
                }
            ],
            "source_attempts": [],
        }

        with patch("src.api.ws_runner.search_local_file", return_value="No local files found related to '青花瓷'."), \
             patch("src.api.ws_runner.find_best_cached_song", return_value=None), \
             patch("src.api.ws_runner.online_audio_configured", return_value=False) as configured, \
             patch("src.api.ws_runner.search_track_metadata_candidates", return_value=metadata_result) as metadata_search, \
             patch("src.api.ws_runner.search_online_audio_candidates") as online_search, \
             patch("src.api.ws_runner.asyncio.to_thread", side_effect=_to_thread_inline):
            await runner._handle_user_input(ui, "/play 青花瓷")
            session = getattr(ui, "_play_selection")
            await session.handle_choice("online_play")

        configured.assert_not_called()
        metadata_search.assert_called_once_with("青花瓷", 5)
        online_search.assert_not_called()
        confirm_events = [event for event in ui.events if event.get("type") == "confirm"]
        self.assertEqual(confirm_events[-1]["tool_name"], "song_candidate")

    async def test_setup_jamendo_stores_open_audio_api_key(self) -> None:
        """Verifies that setup jamendo stores open audio api key behaves as expected.

        Typical use: Use this in automated tests when guarding the setup jamendo stores open audio api key behavior against regressions.

        Example: test_setup_jamendo_stores_open_audio_api_key() -> passes without assertion failures when the behavior remains correct.
        """
        runner = WebSocketRunner()
        ui = FakeUI()

        with self._isolated_auth_env({"SONEX_DEFAULT_PROVIDER": "openai", "SONEX_OPENAI_API_KEY": "sk-test"}):
            await runner._handle_user_input(ui, "/setup jamendo")
            setup = getattr(ui, "_auth_setup")
            auth_events = [event for event in ui.events if event.get("type") == "auth_setup"]
            self.assertEqual(auth_events[-1]["title"], "Jamendo setup")
            self.assertIn("developer.jamendo.com", str(auth_events[-1]["message"]))
            self.assertIn("Client ID", str(auth_events[-1]["prompt"]))
            self.assertFalse(auth_events[-1].get("mask", False))
            await setup.handle_input("jamendo-client-id")
            store = load_auth_store()

        self.assertEqual(store.providers["jamendo"].api_key, "jamendo-client-id")
        auth_events = [event for event in ui.events if event.get("type") == "auth_setup"]
        self.assertEqual(auth_events[-1]["provider"], "jamendo")
        self.assertFalse(auth_events[-1].get("active", True))

    async def test_setup_audius_guides_api_key_input_and_repeats_empty_values(self) -> None:
        """Verifies that setup audius guides api key input and repeats empty values behaves as expected.

        Typical use: Use this in automated tests when guarding the setup audius guides api key input and repeats empty values behavior against regressions.

        Example: test_setup_audius_guides_api_key_input_and_repeats_empty_values() -> passes without assertion failures when the behavior remains correct.
        """
        runner = WebSocketRunner()
        ui = FakeUI()

        with self._isolated_auth_env({"SONEX_DEFAULT_PROVIDER": "openai", "SONEX_OPENAI_API_KEY": "sk-test"}):
            await runner._handle_user_input(ui, "/setup audius")
            setup = getattr(ui, "_auth_setup")
            await setup.handle_input("   ")
            await setup.handle_input("audius-api-key")
            store = load_auth_store()

        auth_events = [event for event in ui.events if event.get("type") == "auth_setup"]
        self.assertEqual(auth_events[0]["title"], "Audius setup")
        self.assertIn("developer.audius.co", str(auth_events[0]["message"]))
        self.assertIn("API key", str(auth_events[0]["prompt"]))
        self.assertFalse(auth_events[0].get("mask", False))
        self.assertEqual(auth_events[1]["provider"], "audius")
        self.assertIn("Input cannot be empty", str(auth_events[1]["message"]))
        self.assertIn("API key", str(auth_events[1]["prompt"]))
        self.assertEqual(store.providers["audius"].api_key, "audius-api-key")
        self.assertFalse(auth_events[-1].get("active", True))

    def test_queue_payload_prefers_unified_song_cache_recent_10(self) -> None:
        """Verifies that queue payload prefers unified song cache recent 10 behaves as expected.

        Typical use: Use this in automated tests when guarding the queue payload prefers unified song cache recent 10 behavior against regressions.

        Example: test_queue_payload_prefers_unified_song_cache_recent_10() -> passes without assertion failures when the behavior remains correct.
        """
        cached_tracks = [
            {"name": f"Cached {idx}", "artist": "Artist", "duration_ms": 60_000}
            for idx in range(10)
        ]
        with patch("src.api.ws_runner.recent_cached_songs", return_value=cached_tracks), \
             patch("src.api.ws_runner.recent_tracks_snapshot", return_value=[]):
            queue = _queue_payload()

        self.assertEqual(len(queue), 10)
        self.assertEqual(queue[0]["title"], "Cached 0")
        self.assertEqual(queue[-1]["index"], "10")

    async def test_pause_command_controls_local_playback_without_agent_turn(self) -> None:
        """Verifies that pause command controls local playback without agent turn behaves as expected.

        Typical use: Use this in automated tests when guarding the pause command controls local playback without agent turn behavior against regressions.

        Example: test_pause_command_controls_local_playback_without_agent_turn() -> passes without assertion failures when the behavior remains correct.
        """
        runner = WebSocketRunner()
        runner._run_agent_turn = AsyncMock()
        ui = FakeUI()
        result = {
            "status": "success",
            "tool": "local_playback_pause",
            "message": "Playback paused.",
            "data": {
                "provider": "youtube",
                "source": "youtube",
                "player": "mpv",
                "session_id": "session-1",
                "name": "Song",
                "artist": "Artist",
                "album": "-",
                "duration_ms": 180000,
                "progress_ms": 42000,
                "timestamp": 123456,
                "is_playing": False,
            },
        }

        with patch("src.api.ws_runner.registry.invoke", return_value=result) as invoke:
            await runner._handle_user_input(ui, "/pause")

        self.assertFalse(runner._run_agent_turn.called)
        invoke.assert_called_once_with("local_playback_pause", {})
        player_events = [event for event in ui.events if event.get("type") == "player"]
        self.assertTrue(player_events)
        self.assertEqual(player_events[-1]["state"]["session_id"], "session-1")
        self.assertFalse(player_events[-1]["state"]["is_playing"])

    async def test_volume_command_controls_local_playback_without_agent_turn(self) -> None:
        """Verifies that volume command controls local playback without agent turn behaves as expected.

        Typical use: Use this in automated tests when guarding the volume command controls local playback without agent turn behavior against regressions.

        Example: test_volume_command_controls_local_playback_without_agent_turn() -> passes without assertion failures when the behavior remains correct.
        """
        runner = WebSocketRunner()
        runner._run_agent_turn = AsyncMock()
        ui = FakeUI()
        result = {
            "status": "success",
            "tool": "local_playback_volume",
            "message": "Playback volume set to 50%.",
            "data": {
                "provider": "youtube",
                "source": "youtube",
                "player": "mpv",
                "session_id": "session-1",
                "name": "Song",
                "artist": "Artist",
                "album": "-",
                "duration_ms": 180000,
                "progress_ms": 42000,
                "timestamp": 123456,
                "is_playing": True,
                "volume_percent": 50,
            },
        }

        with patch("src.api.ws_runner.registry.invoke", return_value=result) as invoke:
            await runner._handle_user_input(ui, "/volume 50")

        self.assertFalse(runner._run_agent_turn.called)
        invoke.assert_called_once_with("local_playback_volume", {"volume_percent": 50})
        player_events = [event for event in ui.events if event.get("type") == "player"]
        self.assertEqual(player_events[-1]["state"]["volume_percent"], 50)

    async def test_volume_command_rejects_invalid_argument(self) -> None:
        """Verifies that volume command rejects invalid argument behaves as expected.

        Typical use: Use this in automated tests when guarding the volume command rejects invalid argument behavior against regressions.

        Example: test_volume_command_rejects_invalid_argument() -> passes without assertion failures when the behavior remains correct.
        """
        runner = WebSocketRunner()
        runner._run_agent_turn = AsyncMock()
        ui = FakeUI()

        with patch("src.api.ws_runner.registry.invoke") as invoke:
            await runner._handle_user_input(ui, "/volume loud")

        invoke.assert_not_called()
        self.assertFalse(runner._run_agent_turn.called)
        activity_events = [event for event in ui.events if event.get("type") == "activity"]
        self.assertEqual(activity_events[-1]["status"], "error")
        self.assertIn("/volume <0-100>", activity_events[-1]["detail"])

    async def test_player_command_sets_backend_without_agent_turn(self) -> None:
        """Verifies that player command sets backend without agent turn behaves as expected.

        Typical use: Use this in automated tests when guarding the player command sets backend without agent turn behavior against regressions.

        Example: test_player_command_sets_backend_without_agent_turn() -> passes without assertion failures when the behavior remains correct.
        """
        runner = WebSocketRunner()
        runner._run_agent_turn = AsyncMock()
        ui = FakeUI()
        result = {
            "status": "success",
            "tool": "local_playback_player",
            "message": "Local playback backend set to cvlc.",
            "data": {"backend": "cvlc"},
        }

        with patch("src.api.ws_runner.registry.invoke", return_value=result) as invoke:
            await runner._handle_user_input(ui, "/player cvlc")

        self.assertFalse(runner._run_agent_turn.called)
        invoke.assert_called_once_with("local_playback_player", {"backend": "cvlc"})
        activity_events = [event for event in ui.events if event.get("type") == "activity"]
        self.assertEqual(activity_events[-1]["status"], "success")
        self.assertIn("cvlc", activity_events[-1]["detail"])

    async def test_player_command_rejects_invalid_backend(self) -> None:
        """Verifies that player command rejects invalid backend behaves as expected.

        Typical use: Use this in automated tests when guarding the player command rejects invalid backend behavior against regressions.

        Example: test_player_command_rejects_invalid_backend() -> passes without assertion failures when the behavior remains correct.
        """
        runner = WebSocketRunner()
        runner._run_agent_turn = AsyncMock()
        ui = FakeUI()

        with patch("src.api.ws_runner.registry.invoke") as invoke:
            await runner._handle_user_input(ui, "/player vlc")

        invoke.assert_not_called()
        self.assertFalse(runner._run_agent_turn.called)
        activity_events = [event for event in ui.events if event.get("type") == "activity"]
        self.assertEqual(activity_events[-1]["status"], "error")
        self.assertIn("/player <auto|mpv|cvlc>", activity_events[-1]["detail"])

    async def test_online_play_result_updates_player_and_cover(self) -> None:
        """Verifies that online play result updates player and cover behaves as expected.

        Typical use: Use this in automated tests when guarding the online play result updates player and cover behavior against regressions.

        Example: test_online_play_result_updates_player_and_cover() -> passes without assertion failures when the behavior remains correct.
        """
        runner = WebSocketRunner()
        ui = FakeUI()
        result = {
            "status": "success",
            "tool": "play_youtube_song",
            "message": "Playing 'Song Artist' online started.",
            "data": {
                "provider": "youtube",
                "name": "Song",
                "artist": "Artist",
                "album": "Album",
                "duration_ms": 180000,
                "album_cover_url": "https://coverartarchive.org/release-group/mbid/front-500",
                "url": "https://www.youtube.com/watch?v=abc",
                "stream_url": "https://stream.example/audio",
                "is_playing": True,
            },
        }

        with patch("src.api.ws_runner.remember_recent_track"):
            await runner._sync_tool_result_ui(ui, "play_youtube_song", result)

        player_events = [event for event in ui.events if event.get("type") == "player"]
        cover_events = [event for event in ui.events if event.get("type") == "cover"]
        self.assertTrue(player_events)
        self.assertEqual(player_events[-1]["state"]["provider"], "youtube")
        self.assertEqual(player_events[-1]["state"]["name"], "Song")
        self.assertEqual(player_events[-1]["state"]["youtube_url"], "https://www.youtube.com/watch?v=abc")
        self.assertIsNone(player_events[-1]["state"]["apple_music_url"])
        self.assertTrue(cover_events)
        self.assertEqual(cover_events[-1]["url"], "https://coverartarchive.org/release-group/mbid/front-500")

    async def test_online_play_result_without_official_cover_does_not_send_youtube_thumbnail(self) -> None:
        """Verifies that online play result without official cover does not send youtube thumbnail behaves as expected.

        Typical use: Use this in automated tests when guarding the online play result without official cover does not send youtube thumbnail behavior against regressions.

        Example: test_online_play_result_without_official_cover_does_not_send_youtube_thumbnail() -> passes without assertion failures when the behavior remains correct.
        """
        runner = WebSocketRunner()
        ui = FakeUI()
        result = {
            "status": "success",
            "tool": "play_youtube_song",
            "message": "Playing 'Song Artist' online started.",
            "data": {
                "provider": "youtube",
                "name": "Song",
                "artist": "Artist",
                "album": "Album",
                "duration_ms": 180000,
                "thumbnail": "https://i.ytimg.com/vi/abc/maxresdefault.jpg",
                "url": "https://www.youtube.com/watch?v=abc",
                "stream_url": "/cache/audio/youtube_abc.webm",
                "is_playing": True,
            },
        }

        with patch("src.api.ws_runner.remember_recent_track"):
            await runner._sync_tool_result_ui(ui, "play_youtube_song", result)

        self.assertFalse([event for event in ui.events if event.get("type") == "cover"])

    async def test_failed_online_play_result_does_not_enter_player_mode(self) -> None:
        """Verifies that failed online play result does not enter player mode behaves as expected.

        Typical use: Use this in automated tests when guarding the failed online play result does not enter player mode behavior against regressions.

        Example: test_failed_online_play_result_does_not_enter_player_mode() -> passes without assertion failures when the behavior remains correct.
        """
        runner = WebSocketRunner()
        ui = FakeUI()
        result = {
            "status": "fail",
            "tool": "play_youtube_song",
            "message": "Player 'vlc' is not ready.",
            "error_code": "PLAYER_MISSED",
            "data": {
                "provider": "youtube",
                "name": "Song",
                "artist": "Artist",
                "album": "Album",
                "duration_ms": 180000,
                "album_cover_url": "https://i.ytimg.com/vi/abc/maxresdefault.jpg",
                "url": "https://www.youtube.com/watch?v=abc",
                "stream_url": "https://stream.example/audio",
                "is_playing": True,
            },
        }

        with patch("src.api.ws_runner.remember_recent_track") as remember_recent_track:
            await runner._sync_tool_result_ui(ui, "play_youtube_song", result)

        self.assertFalse([event for event in ui.events if event.get("type") == "player"])
        self.assertFalse([event for event in ui.events if event.get("type") == "queue"])
        self.assertFalse([event for event in ui.events if event.get("type") == "cover"])
        remember_recent_track.assert_not_called()

    async def test_online_play_choice_reports_pending_and_enters_player_mode(self) -> None:
        """Verifies that online play choice reports pending and enters player mode behaves as expected.

        Typical use: Use this in automated tests when guarding the online play choice reports pending and enters player mode behavior against regressions.

        Example: test_online_play_choice_reports_pending_and_enters_player_mode() -> passes without assertion failures when the behavior remains correct.
        """
        runner = WebSocketRunner()
        ui = FakeUI()
        result = {
            "status": "success",
            "tool": "play_youtube_song",
            "message": "Playing 'Song Artist' online started.",
            "data": {
                "provider": "youtube",
                "name": "Song",
                "artist": "Artist",
                "album": "Album",
                "duration_ms": 180000,
                "album_cover_url": "https://i.ytimg.com/vi/abc/maxresdefault.jpg",
                "url": "https://www.youtube.com/watch?v=abc",
                "stream_url": "https://stream.example/audio",
                "is_playing": True,
            },
        }
        candidate = {
            "cache_id": "youtube_abc",
            "id": "abc",
            "youtube_id": "abc",
            "name": "Song",
            "artist": "Artist",
            "duration_ms": 180000,
            "cached": False,
        }

        with patch("src.api.ws_runner.search_local_file", return_value="No local files found related to 'Song Artist'."), \
             patch("src.api.ws_runner.find_best_cached_song", return_value=None):
            await runner._handle_user_input(ui, "/play Song Artist")
        session = getattr(ui, "_play_selection")
        with patch("src.api.ws_runner.search_youtube_songs", return_value=[candidate]), \
             patch("src.api.ws_runner.play_youtube_candidate", return_value=result), \
             patch("src.api.ws_runner.upsert_cached_song"), \
             patch("src.api.ws_runner.online_audio_configured", return_value=True), \
             patch("src.api.ws_runner.asyncio.to_thread", side_effect=_to_thread_inline):
            await session.handle_choice("online_play")
            await session.handle_choice("youtube_candidate:youtube_abc")

        activities = [event for event in ui.events if event.get("type") == "activity"]
        self.assertTrue(any(event.get("status") == "pending" and "Downloading selected audio" in str(event.get("detail")) for event in activities))
        player_events = [event for event in ui.events if event.get("type") == "player"]
        self.assertTrue(player_events)
        self.assertEqual(player_events[-1]["state"]["name"], "Song")

    async def test_online_play_choice_sends_youtube_candidate_list(self) -> None:
        """Verifies that online play choice sends youtube candidate list behaves as expected.

        Typical use: Use this in automated tests when guarding the online play choice sends youtube candidate list behavior against regressions.

        Example: test_online_play_choice_sends_youtube_candidate_list() -> passes without assertion failures when the behavior remains correct.
        """
        runner = WebSocketRunner()
        ui = FakeUI()
        candidates = [
            {
                "cache_id": f"youtube_id{idx}",
                "id": f"id{idx}",
                "youtube_id": f"id{idx}",
                "name": f"Song {idx}",
                "artist": f"Channel {idx}",
                "duration_ms": (60 + idx) * 1000,
                "cached": idx == 1,
                "variant_type": "live" if idx == 1 else "official_original",
                "raw_view_count": 1_500_000 if idx == 1 else 500_000,
            }
            for idx in range(5)
        ]

        with patch("src.api.ws_runner.search_local_file", return_value="No local files found related to 'Song Artist'."), \
             patch("src.api.ws_runner.find_best_cached_song", return_value=None):
            await runner._handle_user_input(ui, "/play Song Artist")
        session = getattr(ui, "_play_selection")
        with patch("src.api.ws_runner.search_online_audio_candidates", return_value=candidates), \
             patch("src.api.ws_runner.online_audio_configured", return_value=True), \
             patch("src.api.ws_runner.asyncio.to_thread", side_effect=_to_thread_inline):
            await session.handle_choice("online_play")

        confirm_events = [event for event in ui.events if event.get("type") == "confirm"]
        self.assertEqual(confirm_events[-1]["tool_name"], "online_audio_candidate")
        self.assertEqual(confirm_events[-1]["tool_args"]["stage"], "online_audio_candidates")
        self.assertEqual(
            [choice["value"] for choice in confirm_events[-1]["choices"]],
            [
                "youtube_candidate:youtube_id0",
                "youtube_candidate:youtube_id1",
                "youtube_candidate:youtube_id2",
                "youtube_candidate:youtube_id3",
                "youtube_candidate:youtube_id4",
                "refine_query",
            ],
        )
        self.assertIn("cached", confirm_events[-1]["choices"][1]["description"])
        self.assertIn("Live", confirm_events[-1]["choices"][1]["description"])
        self.assertIn("1.5M views", confirm_events[-1]["choices"][1]["description"])
        self.assertIn("原音", confirm_events[-1]["choices"][0]["description"])
        self.assertEqual(confirm_events[-1]["choices"][-1]["label"], "没有想听的歌曲")
        self.assertEqual(confirm_events[-1]["choices"][-1]["input"]["placeholder"], "试试补充更多信息")
        self.assertNotIn("description", confirm_events[-1]["choices"][-1])

    async def test_online_play_choice_describes_youtube_fallback_source_attempts(self) -> None:
        """Verifies that online play choice describes youtube fallback source attempts behaves as expected.

        Typical use: Use this in automated tests when guarding the online play choice describes youtube fallback source attempts behavior against regressions.

        Example: test_online_play_choice_describes_youtube_fallback_source_attempts() -> passes without assertion failures when the behavior remains correct.
        """
        runner = WebSocketRunner()
        ui = FakeUI()
        candidates = [
            {
                "cache_id": "youtube_abc",
                "id": "abc",
                "youtube_id": "abc",
                "provider": "youtube",
                "fallback_provider": "youtube",
                "fallback_reason": "Jamendo returned no credible matches.",
                "source_attempts": [
                    {
                        "provider": "jamendo",
                        "status": "no_credible_matches",
                        "candidate_count": 0,
                        "credible_count": 0,
                        "message": "Jamendo returned no credible matches.",
                    }
                ],
                "name": "Song",
                "artist": "Artist",
                "duration_ms": 180000,
                "cached": False,
            }
        ]

        with patch("src.api.ws_runner.search_local_file", return_value="No local files found related to 'Song Artist'."), \
             patch("src.api.ws_runner.find_best_cached_song", return_value=None):
            await runner._handle_user_input(ui, "/play Song Artist")
        session = getattr(ui, "_play_selection")
        with patch("src.api.ws_runner.search_online_audio_candidates", return_value=candidates), \
             patch("src.api.ws_runner.online_audio_configured", return_value=True), \
             patch("src.api.ws_runner.asyncio.to_thread", side_effect=_to_thread_inline):
            await session.handle_choice("online_play")

        confirm_events = [event for event in ui.events if event.get("type") == "confirm"]
        self.assertEqual(confirm_events[-1]["tool_name"], "online_audio_candidate")
        self.assertEqual(confirm_events[-1]["choices"][0]["value"], "youtube_candidate:youtube_abc")
        self.assertIn("YouTube fallback", confirm_events[-1]["choices"][0]["description"])
        self.assertIn("Jamendo returned no credible matches", confirm_events[-1]["choices"][0]["description"])

    async def test_online_play_choice_sends_song_candidate_list_before_audio_search(self) -> None:
        """Verifies that online play choice sends song candidate list before audio search behaves as expected.

        Typical use: Use this in automated tests when guarding the online play choice sends song candidate list before audio search behavior against regressions.

        Example: test_online_play_choice_sends_song_candidate_list_before_audio_search() -> passes without assertion failures when the behavior remains correct.
        """
        runner = WebSocketRunner()
        ui = FakeUI()
        metadata_result = {
            "candidates": [
                {
                    "id": f"itunes-{idx}",
                    "metadata_source": "itunes",
                    "provider": "itunes",
                    "name": f"Song {idx}",
                    "artist": f"Artist {idx}",
                    "artists": [f"Artist {idx}"],
                    "album": f"Album {idx}",
                    "duration_ms": (180 + idx) * 1000,
                    "uri": f"itunes:track:{idx}",
                }
                for idx in range(6)
            ],
            "source_attempts": [{"provider": "itunes", "status": "success", "candidate_count": 6, "credible_count": 6, "message": "iTunes returned 6 candidates."}],
        }

        with patch("src.api.ws_runner.search_local_file", return_value="No local files found related to 'Song Artist'."), \
             patch("src.api.ws_runner.find_best_cached_song", return_value=None):
            await runner._handle_user_input(ui, "/play Song Artist")
        session = getattr(ui, "_play_selection")
        with patch("src.api.ws_runner.search_track_metadata_candidates", return_value=metadata_result) as metadata_search, \
             patch("src.api.ws_runner.search_youtube_songs") as youtube_search, \
             patch("src.api.ws_runner.online_audio_configured", return_value=True), \
             patch("src.api.ws_runner.asyncio.to_thread", side_effect=_to_thread_inline):
            await session.handle_choice("online_play")

        metadata_search.assert_called_once_with("Song Artist", 5)
        youtube_search.assert_not_called()
        confirm_events = [event for event in ui.events if event.get("type") == "confirm"]
        self.assertEqual(confirm_events[-1]["tool_name"], "song_candidate")
        self.assertEqual(confirm_events[-1]["tool_args"]["stage"], "song_metadata_candidates")
        self.assertEqual(len(confirm_events[-1]["choices"]), 6)
        self.assertEqual(confirm_events[-1]["choices"][0]["value"], "song_candidate:0")
        self.assertEqual(confirm_events[-1]["choices"][0]["label"], "Artist 0-Album 0--Song 0")
        self.assertIn("3:00", confirm_events[-1]["choices"][0]["description"])
        self.assertEqual(confirm_events[-1]["choices"][-1]["value"], "refine_song_metadata_query")
        self.assertEqual(confirm_events[-1]["choices"][-1]["input"]["placeholder"], "试试补充更多歌曲信息")
        self.assertTrue(any(event.get("type") == "activity" and event.get("title") == "iTunes" for event in ui.events))

    async def test_song_candidate_choice_plays_online_audio_with_confirmed_metadata(self) -> None:
        """Verifies that song candidate choice plays online audio with confirmed metadata behaves as expected.

        Typical use: Use this in automated tests when guarding the song candidate choice plays online audio with confirmed metadata behavior against regressions.

        Example: test_song_candidate_choice_plays_online_audio_with_confirmed_metadata() -> passes without assertion failures when the behavior remains correct.
        """
        runner = WebSocketRunner()
        ui = FakeUI()
        song_candidate = {
            "id": "itunes-track",
            "metadata_source": "itunes",
            "provider": "itunes",
            "name": "Canonical Song",
            "artist": "Canonical Artist",
            "artists": ["Canonical Artist"],
            "album": "Canonical Album",
            "duration_ms": 201000,
            "uri": "itunes:track:canonical",
            "itunes_url": "https://music.apple.com/us/song/canonical",
        }
        online_candidate = {
            "cache_id": "youtube_abc",
            "id": "abc",
            "youtube_id": "abc",
            "name": "Canonical Song",
            "artist": "Canonical Artist",
            "duration_ms": 201000,
            "cached": False,
        }
        playback_result = {
            "status": "fail",
            "tool": "play_online_audio",
            "message": "Jamendo is not configured. Audius is not configured. Sonex fell back to YouTube. YouTube failed: Selected YouTube result is not available. Choose another candidate or refine the search.",
            "error_code": "YOUTUBE_UNAVAILABLE",
            "data": {
                "provider": "youtube",
                "fallback_provider": "youtube",
                "source_attempts": [
                    {"provider": "jamendo", "status": "missing_config", "message": "Jamendo is not configured."},
                    {"provider": "audius", "status": "missing_config", "message": "Audius is not configured."},
                ],
            },
        }

        with patch("src.api.ws_runner.search_local_file", return_value="No local files found related to 'messy query'."), \
             patch("src.api.ws_runner.find_best_cached_song", return_value=None):
            await runner._handle_user_input(ui, "/play messy query")
        session = getattr(ui, "_play_selection")
        with patch("src.api.ws_runner.search_track_metadata_candidates", return_value={"candidates": [song_candidate], "source_attempts": []}), \
             patch("src.api.ws_runner.search_online_audio_candidates", return_value=[online_candidate]) as online_search, \
             patch("src.api.ws_runner.play_online_audio_candidate", return_value=playback_result) as play_candidate, \
             patch("src.api.ws_runner.asyncio.to_thread", side_effect=_to_thread_inline):
            await session.handle_choice("online_play")
            await session.handle_choice("song_candidate:0")

        online_search.assert_called_once()
        self.assertEqual(online_search.call_args.args[0], "Canonical Artist Canonical Song")
        self.assertEqual(online_search.call_args.args[1], 1)
        metadata = online_search.call_args.kwargs["playback_metadata"]
        self.assertEqual(metadata["name"], "Canonical Song")
        self.assertEqual(metadata["artist"], "Canonical Artist")
        self.assertEqual(metadata["album"], "Canonical Album")
        self.assertEqual(metadata["uri"], "itunes:track:canonical")
        self.assertEqual(metadata["itunes_url"], "https://music.apple.com/us/song/canonical")
        self.assertEqual(metadata["original_query"], "messy query")
        play_candidate.assert_called_once_with(online_candidate, player="auto")
        confirm_events = [event for event in ui.events if event.get("type") == "confirm"]
        self.assertEqual(confirm_events[-1]["tool_name"], "song_candidate")
        self.assertFalse([event for event in confirm_events if event.get("tool_name") == "online_audio_candidate"])
        self.assertTrue(any(
            event.get("type") == "activity"
            and event.get("title") == "Jamendo"
            and event.get("status") == "error"
            for event in ui.events
        ))
        self.assertTrue(any(
            event.get("type") == "error"
            and "Selected YouTube result is not available" in str(event.get("message"))
            for event in ui.events
        ))

    async def test_song_candidate_cover_lookup_can_complete_when_audio_fails(self) -> None:
        """Verifies that song candidate cover lookup can complete when audio fails behaves as expected.

        Typical use: Use this in automated tests when guarding the song candidate cover lookup can complete when audio fails behavior against regressions.

        Example: test_song_candidate_cover_lookup_can_complete_when_audio_fails() -> passes without assertion failures when the behavior remains correct.
        """
        runner = WebSocketRunner()
        ui = FakeUI()
        song_candidate = {
            "id": "musicbrainz-recording",
            "metadata_source": "musicbrainz",
            "provider": "musicbrainz",
            "name": "Canonical Song",
            "artist": "Canonical Artist",
            "artists": ["Canonical Artist"],
            "album": "Canonical Album",
            "duration_ms": 201000,
            "uri": "musicbrainz:recording:musicbrainz-recording",
        }

        with patch("src.api.ws_runner.search_local_file", return_value="No local files found related to 'messy query'."), \
             patch("src.api.ws_runner.find_best_cached_song", return_value=None):
            await runner._handle_user_input(ui, "/play messy query")
        session = getattr(ui, "_play_selection")
        with patch("src.api.ws_runner.search_track_metadata_candidates", return_value={"candidates": [song_candidate], "source_attempts": []}), \
             patch(
                 "src.api.ws_runner.resolve_online_playback_metadata",
                 return_value={
                     **song_candidate,
                     "original_query": "messy query",
                     "youtube_query": "Canonical Artist Canonical Song",
                     "album_cover_url": "https://coverartarchive.org/release-group/mbid/front-500",
                     "cover_source": "https://coverartarchive.org/release-group/mbid/front-500",
                     "cover_source_type": "cover_art_archive",
                 },
             ), \
             patch("src.api.ws_runner.search_online_audio_candidates", side_effect=RuntimeError("YouTube unavailable")), \
             patch("src.api.ws_runner.asyncio.to_thread", side_effect=_to_thread_inline):
            await session.handle_choice("online_play")
            await session.handle_choice("song_candidate:0")

        cover_events = [event for event in ui.events if event.get("type") == "cover"]
        self.assertTrue(cover_events)
        self.assertEqual(cover_events[-1]["url"], "https://coverartarchive.org/release-group/mbid/front-500")
        self.assertTrue(any(
            event.get("type") == "error"
            and "YouTube unavailable" in str(event.get("message"))
            for event in ui.events
        ))

    async def test_song_candidate_refine_researches_metadata_not_audio(self) -> None:
        """Verifies that song candidate refine researches metadata not audio behaves as expected.

        Typical use: Use this in automated tests when guarding the song candidate refine researches metadata not audio behavior against regressions.

        Example: test_song_candidate_refine_researches_metadata_not_audio() -> passes without assertion failures when the behavior remains correct.
        """
        runner = WebSocketRunner()
        runner._run_agent_turn = AsyncMock()
        ui = FakeUI()
        first_candidate = {"name": "First", "artist": "Artist", "album": "Album", "duration_ms": 180000}
        refined_candidate = {"name": "Refined", "artist": "Artist", "album": "Album", "duration_ms": 181000}

        with patch("src.api.ws_runner.search_local_file", return_value="No local files found related to 'Song Artist'."), \
             patch("src.api.ws_runner.find_best_cached_song", return_value=None):
            await runner._handle_user_input(ui, "/play Song Artist")
        session = getattr(ui, "_play_selection")
        with patch(
            "src.api.ws_runner.search_track_metadata_candidates",
            side_effect=[
                {"candidates": [first_candidate], "source_attempts": []},
                {"candidates": [refined_candidate], "source_attempts": []},
            ],
        ) as metadata_search, \
             patch("src.api.ws_runner.search_youtube_songs") as youtube_search, \
             patch("src.api.ws_runner.online_audio_configured", return_value=True), \
             patch("src.api.ws_runner.asyncio.to_thread", side_effect=_to_thread_inline):
            await session.handle_choice("online_play")
            await session.handle_choice("refine_song_metadata_query")
            await runner._handle_user_input(ui, "live acoustic")

        self.assertEqual(metadata_search.call_args_list[0].args, ("Song Artist", 5))
        self.assertEqual(metadata_search.call_args_list[1].args, ("Song Artist live acoustic", 5))
        youtube_search.assert_not_called()
        self.assertFalse(runner._run_agent_turn.called)
        confirm_events = [event for event in ui.events if event.get("type") == "confirm"]
        self.assertEqual(confirm_events[-1]["choices"][0]["label"], "Artist-Album--Refined")

    async def test_online_play_without_metadata_candidates_falls_back_to_audio_candidates(self) -> None:
        """Verifies that online play without metadata candidates falls back to audio candidates behaves as expected.

        Typical use: Use this in automated tests when guarding the online play without metadata candidates falls back to audio candidates behavior against regressions.

        Example: test_online_play_without_metadata_candidates_falls_back_to_audio_candidates() -> passes without assertion failures when the behavior remains correct.
        """
        runner = WebSocketRunner()
        ui = FakeUI()
        online_candidate = {
            "cache_id": "youtube_abc",
            "id": "abc",
            "youtube_id": "abc",
            "name": "Fallback Song",
            "artist": "Fallback Channel",
            "duration_ms": 60000,
            "cached": False,
        }

        with patch("src.api.ws_runner.search_local_file", return_value="No local files found related to 'raw query'."), \
             patch("src.api.ws_runner.find_best_cached_song", return_value=None):
            await runner._handle_user_input(ui, "/play raw query")
        session = getattr(ui, "_play_selection")
        with patch(
            "src.api.ws_runner.search_track_metadata_candidates",
            return_value={
                "candidates": [],
                "source_attempts": [
                    {"provider": "itunes", "status": "not_found", "candidate_count": 0, "credible_count": 0, "message": "iTunes returned no candidates."},
                    {"provider": "deezer", "status": "rate_limited", "candidate_count": 0, "credible_count": 0, "message": "Deezer rate limit reached."},
                ],
            },
        ), \
             patch("src.api.ws_runner.search_online_audio_candidates", return_value=[online_candidate]) as online_search, \
             patch("src.api.ws_runner.asyncio.to_thread", side_effect=_to_thread_inline):
            await session.handle_choice("online_play")

        online_search.assert_called_once_with("raw query", 5)
        confirm_events = [event for event in ui.events if event.get("type") == "confirm"]
        self.assertEqual(confirm_events[-1]["tool_name"], "online_audio_candidate")
        self.assertTrue(any(event.get("type") == "activity" and event.get("title") == "iTunes" for event in ui.events))
        self.assertTrue(any(event.get("type") == "activity" and event.get("title") == "Deezer" for event in ui.events))
        self.assertTrue(any(
            event.get("type") == "error"
            and "No song metadata candidates found" in str(event.get("message"))
            for event in ui.events
        ))

    async def test_youtube_candidate_refine_appends_next_input_and_researches(self) -> None:
        """Verifies that youtube candidate refine appends next input and researches behaves as expected.

        Typical use: Use this in automated tests when guarding the youtube candidate refine appends next input and researches behavior against regressions.

        Example: test_youtube_candidate_refine_appends_next_input_and_researches() -> passes without assertion failures when the behavior remains correct.
        """
        runner = WebSocketRunner()
        runner._run_agent_turn = AsyncMock()
        ui = FakeUI()
        first_candidates = [
            {
                "cache_id": "youtube_first",
                "id": "first",
                "youtube_id": "first",
                "name": "First",
                "artist": "Channel",
                "duration_ms": 60000,
                "cached": False,
            }
        ]
        refined_candidates = [
            {
                "cache_id": "youtube_refined",
                "id": "refined",
                "youtube_id": "refined",
                "name": "Refined",
                "artist": "Channel",
                "duration_ms": 65000,
                "cached": False,
            }
        ]

        with patch("src.api.ws_runner.search_local_file", return_value="No local files found related to 'Song Artist'."), \
             patch("src.api.ws_runner.find_best_cached_song", return_value=None):
            await runner._handle_user_input(ui, "/play Song Artist")
        session = getattr(ui, "_play_selection")
        with patch("src.api.ws_runner.search_youtube_songs", side_effect=[first_candidates, refined_candidates]) as search, \
             patch("src.api.ws_runner.online_audio_configured", return_value=True), \
             patch("src.api.ws_runner.asyncio.to_thread", side_effect=_to_thread_inline):
            await session.handle_choice("online_play")
            await session.handle_choice("refine_query")
            await runner._handle_user_input(ui, "live acoustic")

        self.assertEqual(search.call_args_list[0].args[0], "Song Artist")
        self.assertEqual(search.call_args_list[1].args[0], "Song Artist live acoustic")
        self.assertFalse(runner._run_agent_turn.called)
        confirm_events = [event for event in ui.events if event.get("type") == "confirm"]
        self.assertEqual(confirm_events[-1]["choices"][0]["value"], "youtube_candidate:youtube_refined")

    async def test_youtube_candidate_inline_refine_researches(self) -> None:
        """Verifies that youtube candidate inline refine researches behaves as expected.

        Typical use: Use this in automated tests when guarding the youtube candidate inline refine researches behavior against regressions.

        Example: test_youtube_candidate_inline_refine_researches() -> passes without assertion failures when the behavior remains correct.
        """
        runner = WebSocketRunner()
        runner._run_agent_turn = AsyncMock()
        ui = FakeUI()
        first_candidates = [
            {
                "cache_id": "youtube_first",
                "id": "first",
                "youtube_id": "first",
                "name": "First",
                "artist": "Channel",
                "duration_ms": 60000,
                "cached": False,
            }
        ]
        refined_candidates = [
            {
                "cache_id": "youtube_refined",
                "id": "refined",
                "youtube_id": "refined",
                "name": "Refined",
                "artist": "Channel",
                "duration_ms": 65000,
                "cached": False,
            }
        ]

        with patch("src.api.ws_runner.search_local_file", return_value="No local files found related to 'Song Artist'."), \
             patch("src.api.ws_runner.find_best_cached_song", return_value=None):
            await runner._handle_user_input(ui, "/play Song Artist")
        session = getattr(ui, "_play_selection")
        with patch("src.api.ws_runner.search_youtube_songs", side_effect=[first_candidates, refined_candidates]) as search, \
             patch("src.api.ws_runner.online_audio_configured", return_value=True), \
             patch("src.api.ws_runner.asyncio.to_thread", side_effect=_to_thread_inline):
            await session.handle_choice("online_play")
            await session.handle_choice("refine_query:live%20acoustic")

        self.assertEqual(search.call_args_list[0].args[0], "Song Artist")
        self.assertEqual(search.call_args_list[1].args[0], "Song Artist live acoustic")
        self.assertFalse(runner._run_agent_turn.called)
        confirm_events = [event for event in ui.events if event.get("type") == "confirm"]
        self.assertEqual(confirm_events[-1]["choices"][0]["value"], "youtube_candidate:youtube_refined")

    async def test_youtube_candidate_choice_downloads_cache_and_plays_local_audio(self) -> None:
        """Verifies that youtube candidate choice downloads cache and plays local audio behaves as expected.

        Typical use: Use this in automated tests when guarding the youtube candidate choice downloads cache and plays local audio behavior against regressions.

        Example: test_youtube_candidate_choice_downloads_cache_and_plays_local_audio() -> passes without assertion failures when the behavior remains correct.
        """
        runner = WebSocketRunner()
        ui = FakeUI()
        candidate = {
            "cache_id": "youtube_abc",
            "id": "abc",
            "youtube_id": "abc",
            "name": "Song",
            "artist": "Artist",
            "duration_ms": 180000,
            "cached": False,
        }
        result = {
            "status": "success",
            "tool": "play_youtube_song",
            "message": "Playing 'Song Artist' online started.",
            "data": {
                "provider": "youtube",
                "source": "youtube",
                "player": "mpv",
                "session_id": "session-1",
                "name": "Song",
                "artist": "Artist",
                "album": "-",
                "duration_ms": 180000,
                "progress_ms": 0,
                "timestamp": 1,
                "is_playing": True,
                "stream_url": "/cache/audio/youtube_abc.webm",
                "audio_path": "/cache/audio/youtube_abc.webm",
            },
        }

        with patch("src.api.ws_runner.search_local_file", return_value="No local files found related to 'Song Artist'."), \
             patch("src.api.ws_runner.find_best_cached_song", return_value=None):
            await runner._handle_user_input(ui, "/play Song Artist")
        session = getattr(ui, "_play_selection")
        with patch("src.api.ws_runner.search_youtube_songs", return_value=[candidate]), \
             patch("src.api.ws_runner.play_youtube_candidate", return_value=result) as play_candidate, \
             patch("src.api.ws_runner.upsert_cached_song"), \
             patch("src.api.ws_runner.online_audio_configured", return_value=True), \
             patch("src.api.ws_runner.asyncio.to_thread", side_effect=_to_thread_inline):
            await session.handle_choice("online_play")
            await session.handle_choice("youtube_candidate:youtube_abc")

        play_candidate.assert_called_once()
        self.assertEqual(play_candidate.call_args.args[0]["cache_id"], "youtube_abc")
        self.assertEqual(play_candidate.call_args.kwargs["player"], "auto")
        player_events = [event for event in ui.events if event.get("type") == "player"]
        self.assertEqual(player_events[-1]["state"]["stream_url"], "/cache/audio/youtube_abc.webm")

    async def test_online_play_choice_handles_player_launch_confirmation(self) -> None:
        """Verifies that online play choice handles player launch confirmation behaves as expected.

        Typical use: Use this in automated tests when guarding the online play choice handles player launch confirmation behavior against regressions.

        Example: test_online_play_choice_handles_player_launch_confirmation() -> passes without assertion failures when the behavior remains correct.
        """
        runner = WebSocketRunner()
        ui = FakeUI()
        pending_result = {
            "status": "requires_player_confirm",
            "tool": "play_youtube_song",
            "message": "Sonex wants to open auto local player.",
            "data": {
                "provider": "youtube",
                "name": "Song",
                "artist": "Artist",
                "album": "Album",
                "duration_ms": 180000,
                "url": "https://www.youtube.com/watch?v=abc",
                "stream_url": "https://stream.example/audio",
                "is_playing": True,
                "player": "auto",
                "player_label": "auto local player",
                "confirm_message": "Sonex wanna open auto local player, confirm?",
                "choices": [
                    {"value": "mpv", "label": "🎧 mpv", "description": "recommended for smoother background playback."},
                    {"value": "cvlc", "label": "📻 VLC", "description": "fallback background player using the VLC rc interface."},
                    {"value": "deny", "label": "取消"},
                ],
            },
        }
        success_result = {
            "status": "success",
            "tool": "play_youtube_song",
            "message": "Playing 'Song Artist' online started.",
            "data": {
                "provider": "youtube",
                "name": "Song",
                "artist": "Artist",
                "album": "Album",
                "duration_ms": 180000,
                "url": "https://www.youtube.com/watch?v=abc",
                "stream_url": "https://stream.example/audio",
                "is_playing": True,
            },
        }
        candidate = {
            "cache_id": "youtube_abc",
            "id": "abc",
            "youtube_id": "abc",
            "name": "Song",
            "artist": "Artist",
            "duration_ms": 180000,
            "cached": False,
        }

        with patch("src.api.ws_runner.search_local_file", return_value="No local files found related to 'Song Artist'."), \
             patch("src.api.ws_runner.find_best_cached_song", return_value=None):
            await runner._handle_user_input(ui, "/play Song Artist")
        session = getattr(ui, "_play_selection")
        with patch("src.api.ws_runner.search_youtube_songs", return_value=[candidate]), \
             patch("src.api.ws_runner.play_youtube_candidate", return_value=pending_result), \
             patch("src.api.ws_runner.online_audio_configured", return_value=True), \
             patch("src.api.ws_runner.asyncio.to_thread", side_effect=_to_thread_inline):
            await session.handle_choice("online_play")
            await session.handle_choice("youtube_candidate:youtube_abc")

        confirm_events = [event for event in ui.events if event.get("type") == "confirm"]
        self.assertEqual(confirm_events[-1]["tool_name"], "play_youtube_song")
        self.assertEqual([choice["value"] for choice in confirm_events[-1]["choices"]], ["mpv", "cvlc", "deny"])
        self.assertIs(getattr(ui, "_play_selection"), session)

        with patch("src.api.ws_runner.complete_player_confirm", return_value=success_result) as complete, \
             patch("src.api.ws_runner.upsert_cached_song"), \
             patch("src.api.ws_runner.asyncio.to_thread", side_effect=_to_thread_inline):
            await session.handle_choice("mpv")

        complete.assert_called_once_with(pending_result, "mpv")
        player_events = [event for event in ui.events if event.get("type") == "player"]
        self.assertTrue(player_events)
        self.assertEqual(player_events[-1]["state"]["name"], "Song")
        self.assertIsNone(getattr(ui, "_play_selection"))

    async def test_online_play_confirm_result_from_websocket_invokes_playback(self) -> None:
        """Verifies that online play confirm result from websocket invokes playback behaves as expected.

        Typical use: Use this in automated tests when guarding the online play confirm result from websocket invokes playback behavior against regressions.

        Example: test_online_play_confirm_result_from_websocket_invokes_playback() -> passes without assertion failures when the behavior remains correct.
        """
        runner = WebSocketRunner()
        ws = FakeWebSocket()
        result = {
            "status": "success",
            "tool": "play_youtube_song",
            "message": "Playing 'Song Artist' online started.",
            "data": {
                "provider": "youtube",
                "name": "Song",
                "artist": "Artist",
                "album": "Album",
                "duration_ms": 180000,
                "url": "https://www.youtube.com/watch?v=abc",
                "stream_url": "https://stream.example/audio",
                "is_playing": True,
            },
        }
        candidate = {
            "cache_id": "youtube_abc",
            "id": "abc",
            "youtube_id": "abc",
            "name": "Song",
            "artist": "Artist",
            "duration_ms": 180000,
            "cached": False,
        }

        async def idle_sync(_ui: object) -> None:
            """Verifies that idle sync behaves as expected.

            Typical use: Use this in automated tests when guarding the idle sync behavior against regressions.

            Example: idle_sync() -> passes without assertion failures when the behavior remains correct.
            """
            return None

        with patch.object(runner, "_handle_startup_auth", new=AsyncMock()), \
             patch.object(runner, "_sync_spotify_playback", side_effect=idle_sync), \
             patch.object(runner, "_sync_local_playback", side_effect=idle_sync), \
             patch("src.api.ws_runner.search_local_file", return_value="No local files found related to 'Song Artist'."), \
             patch("src.api.ws_runner.find_best_cached_song", return_value=None), \
             patch("src.api.ws_runner.search_youtube_songs", return_value=[candidate]), \
             patch("src.api.ws_runner.upsert_cached_song"), \
             patch("src.api.ws_runner.online_audio_configured", return_value=True), \
             patch("src.api.ws_runner.asyncio.to_thread", side_effect=_to_thread_inline), \
             patch("src.api.ws_runner.play_youtube_candidate", return_value=result) as play_candidate:
            await runner.handle_ws(ws)  # type: ignore[arg-type]

        play_candidate.assert_called_once()
        self.assertEqual(play_candidate.call_args.args[0]["cache_id"], "youtube_abc")
        player_events = [event for event in ws.sent if event.get("type") == "player"]
        self.assertTrue(player_events)
        self.assertEqual(player_events[-1]["state"]["name"], "Song")

    def test_project_local_playback_state_advances_without_status_probe(self) -> None:
        """Verifies that project local playback state advances without status probe behaves as expected.

        Typical use: Use this in automated tests when guarding the project local playback state advances without status probe behavior against regressions.

        Example: test_project_local_playback_state_advances_without_status_probe() -> passes without assertion failures when the behavior remains correct.
        """
        state = {
            "name": "Song",
            "artist": "Artist",
            "album": "Album",
            "duration_ms": 10_000,
            "progress_ms": 2_000,
            "timestamp": 1_000,
            "is_playing": True,
        }

        projected = ws_runner._project_local_playback_state(state, 4_000)

        self.assertEqual(projected["progress_ms"], 5_000)
        self.assertEqual(projected["timestamp"], 4_000)
        self.assertTrue(projected["is_playing"])

    def test_project_local_playback_state_marks_ended_at_duration(self) -> None:
        """Verifies that project local playback state marks ended at duration behaves as expected.

        Typical use: Use this in automated tests when guarding the project local playback state marks ended at duration behavior against regressions.

        Example: test_project_local_playback_state_marks_ended_at_duration() -> passes without assertion failures when the behavior remains correct.
        """
        state = {
            "name": "Song",
            "artist": "Artist",
            "album": "Album",
            "duration_ms": 3_000,
            "progress_ms": 2_500,
            "timestamp": 1_000,
            "is_playing": True,
        }

        projected = ws_runner._project_local_playback_state(state, 2_000)

        self.assertEqual(projected["progress_ms"], 3_000)
        self.assertFalse(projected["is_playing"])
        self.assertTrue(projected["ended"])

    async def test_online_play_choice_reports_failure_to_chat_and_error(self) -> None:
        """Verifies that online play choice reports failure to chat and error behaves as expected.

        Typical use: Use this in automated tests when guarding the online play choice reports failure to chat and error behavior against regressions.

        Example: test_online_play_choice_reports_failure_to_chat_and_error() -> passes without assertion failures when the behavior remains correct.
        """
        runner = WebSocketRunner()
        ui = FakeUI()
        result = {
            "status": "fail",
            "tool": "play_youtube_song",
            "message": "Failed to start controllable playback: mpv is not installed.",
            "error_code": "PLAYER_START_FAILED",
            "data": {"query": "Song Artist", "method": "online_play", "provider": "youtube"},
        }
        candidate = {
            "cache_id": "youtube_abc",
            "id": "abc",
            "youtube_id": "abc",
            "name": "Song",
            "artist": "Artist",
            "duration_ms": 180000,
            "cached": False,
        }

        with patch("src.api.ws_runner.search_local_file", return_value="No local files found related to 'Song Artist'."), \
             patch("src.api.ws_runner.find_best_cached_song", return_value=None):
            await runner._handle_user_input(ui, "/play Song Artist")
        session = getattr(ui, "_play_selection")
        with patch("src.api.ws_runner.search_youtube_songs", return_value=[candidate]), \
             patch("src.api.ws_runner.play_youtube_candidate", return_value=result), \
             patch("src.api.ws_runner.online_audio_configured", return_value=True), \
             patch("src.api.ws_runner.asyncio.to_thread", side_effect=_to_thread_inline):
            await session.handle_choice("online_play")
            await session.handle_choice("youtube_candidate:youtube_abc")

        self.assertFalse([event for event in ui.events if event.get("type") == "player"])
        self.assertTrue(any(
            event.get("type") == "chat"
            and event.get("role") == "agent"
            and "mpv is not installed" in str(event.get("text"))
            for event in ui.events
        ))
        self.assertTrue(any(
            event.get("type") == "error"
            and "mpv is not installed" in str(event.get("message"))
            for event in ui.events
        ))

    def test_sonex_log_path_uses_log_filename(self) -> None:
        """Verifies that sonex log path uses log filename behaves as expected.

        Typical use: Use this in automated tests when guarding the sonex log path uses log filename behavior against regressions.

        Example: test_sonex_log_path_uses_log_filename() -> passes without assertion failures when the behavior remains correct.
        """
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {"SONEX_HOME": home}):
            self.assertEqual(sonex_log_path(), Path(home) / "log")

    def test_configure_file_logging_writes_to_log_filename(self) -> None:
        """Verifies that configure file logging writes to log filename behaves as expected.

        Typical use: Use this in automated tests when guarding the configure file logging writes to log filename behavior against regressions.

        Example: test_configure_file_logging_writes_to_log_filename() -> passes without assertion failures when the behavior remains correct.
        """
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {"SONEX_HOME": home}):
            log_path = configure_file_logging()
            logging.getLogger().info("sonex log filename test")
            for handler in logging.getLogger().handlers:
                handler.flush()

            self.assertEqual(log_path, Path(home) / "log")
            self.assertIn("sonex log filename test", log_path.read_text(encoding="utf-8"))

    async def test_agent_turn_reports_live_planning_metrics_while_llm_is_waiting(self) -> None:
        """Verifies that agent turn reports live planning metrics while llm is waiting behaves as expected.

        Typical use: Use this in automated tests when guarding the agent turn reports live planning metrics while llm is waiting behavior against regressions.

        Example: test_agent_turn_reports_live_planning_metrics_while_llm_is_waiting() -> passes without assertion failures when the behavior remains correct.
        """
        runner = WebSocketRunner()
        ui = FakeUI()

        def slow_agent_loop(user_input: str, tools: object):
            """Verifies that slow agent loop behaves as expected.

            Typical use: Use this in automated tests when guarding the slow agent loop behavior against regressions.

            Example: slow_agent_loop() -> passes without assertion failures when the behavior remains correct.
            """
            time.sleep(0.35)
            yield AgentState(type="status", content="planning", tokens=42)
            yield AgentState(type="complete", content="done")

        with patch("src.api.ws_runner.agent_loop", slow_agent_loop):
            task = asyncio.create_task(runner._run_agent_turn(ui, "hello"))
            await asyncio.sleep(0.15)
            early_status_events = [event for event in ui.events if event.get("type") == "status"]
            early_activity_events = [event for event in ui.events if event.get("type") == "activity"]
            await task

        self.assertTrue(early_status_events)
        self.assertEqual(early_status_events[-1]["tokens"], 0)
        self.assertIsNotNone(early_status_events[-1]["elapsed_ms"])
        self.assertTrue(
            [
                event
                for event in early_activity_events
                if event.get("title") == "Planning" and event.get("status") == "pending"
            ]
        )

        status_events = [event for event in ui.events if event.get("type") == "status"]
        self.assertTrue(any(event.get("tokens") == 42 for event in status_events))
        planning_events = [
            event
            for event in ui.events
            if event.get("type") == "activity" and event.get("title") == "Planning"
        ]
        self.assertEqual(
            [event.get("activity_id") for event in planning_events],
            [event.get("activity_id") for event in planning_events[:1]] * len(planning_events),
        )
        self.assertEqual(planning_events[-1]["status"], "success")

    async def test_agent_turn_marks_planning_activity_error_when_planner_fails(self) -> None:
        """Verifies that agent turn marks planning activity error when planner fails behaves as expected.

        Typical use: Use this in automated tests when guarding the agent turn marks planning activity error when planner fails behavior against regressions.

        Example: test_agent_turn_marks_planning_activity_error_when_planner_fails() -> passes without assertion failures when the behavior remains correct.
        """
        runner = WebSocketRunner()
        ui = FakeUI()

        def failing_agent_loop(user_input: str, tools: object):
            """Verifies that failing agent loop behaves as expected.

            Typical use: Use this in automated tests when guarding the failing agent loop behavior against regressions.

            Example: failing_agent_loop() -> passes without assertion failures when the behavior remains correct.
            """
            time.sleep(0.05)
            yield AgentState(type="error", content="planner unavailable")

        with patch("src.api.ws_runner.agent_loop", failing_agent_loop):
            await runner._run_agent_turn(ui, "hello")

        planning_events = [
            event
            for event in ui.events
            if event.get("type") == "activity" and event.get("title") == "Planning"
        ]
        self.assertEqual(
            [event.get("activity_id") for event in planning_events],
            [event.get("activity_id") for event in planning_events[:1]] * len(planning_events),
        )
        self.assertEqual(planning_events[-1]["status"], "error")
        self.assertTrue(any(event.get("type") == "error" for event in ui.events))
        self.assertTrue(
            any(
                event.get("type") == "chat"
                and event.get("role") == "agent"
                and "planner unavailable" in str(event.get("text"))
                for event in ui.events
            )
        )

    async def test_spotify_sync_reports_premium_failure_once_in_chat(self) -> None:
        """Verifies that spotify sync reports premium failure once in chat behaves as expected.

        Typical use: Use this in automated tests when guarding the spotify sync reports premium failure once in chat behavior against regressions.

        Example: test_spotify_sync_reports_premium_failure_once_in_chat() -> passes without assertion failures when the behavior remains correct.
        """
        runner = WebSocketRunner()
        ui = FakeUI()
        ui.closed = False
        sleeps = 0

        async def stop_after_two_sleeps(_: float) -> None:
            """Verifies that stop after two sleeps behaves as expected.

            Typical use: Use this in automated tests when guarding the stop after two sleeps behavior against regressions.

            Example: stop_after_two_sleeps() -> passes without assertion failures when the behavior remains correct.
            """
            nonlocal sleeps
            sleeps += 1
            if sleeps >= 2:
                ui.closed = True

        failure = {
            "status": "fail",
            "message": "Spotify playback state requires a Premium account.",
            "error_code": "SPOTIFY_PREMIUM_REQUIRED",
        }

        with (
            patch("src.api.ws_runner.spotify_current_playback", return_value=failure),
            patch("src.api.ws_runner.asyncio.to_thread", side_effect=_to_thread_inline),
            patch("src.api.ws_runner.asyncio.sleep", side_effect=stop_after_two_sleeps),
        ):
            await runner._sync_spotify_playback(ui)

        chat_events = [
            event
            for event in ui.events
            if event.get("type") == "chat" and event.get("role") == "agent"
        ]
        self.assertEqual(len(chat_events), 1)
        self.assertIn("Premium account", str(chat_events[0].get("text")))

    def _isolated_auth_env(self, extra: dict[str, str] | None = None):
        """Verifies that isolated auth env behaves as expected.

        Typical use: Use this in automated tests when guarding the isolated auth env behavior against regressions.

        Example: _isolated_auth_env() -> passes without assertion failures when the behavior remains correct.
        """
        home = tempfile.TemporaryDirectory()
        config_path = Path(home.name) / "missing-thinking.json"
        env = {
            "SONEX_HOME": home.name,
            "SONEX_CONFIG_PATH": str(config_path),
            "SONEX_API_KEY": "",
            "SONEX_OPENAI_API_KEY": "",
            "SONEX_ANTHROPIC_API_KEY": "",
            "SONEX_GEMINI_API_KEY": "",
            "SONEX_DEEPSEEK_API_KEY": "",
            "SONEX_DEFAULT_MODEL": "",
        }
        env.update(extra or {})
        patcher = patch.dict(os.environ, env, clear=False)

        class EnvContext:
            """Groups related env context cases.

            Collects assertions that exercise env context behavior without mixing unrelated fixtures.
            """
            def __enter__(self_nonlocal) -> str:
                """Verifies that enter behaves as expected.

                Typical use: Use this in automated tests when guarding the enter behavior against regressions.

                Example: __enter__() -> passes without assertion failures when the behavior remains correct.
                """
                patcher.start()
                ThinkingConfig._state = None
                return home.name

            def __exit__(self_nonlocal, exc_type, exc, tb) -> None:
                """Verifies that exit behaves as expected.

                Typical use: Use this in automated tests when guarding the exit behavior against regressions.

                Example: __exit__() -> passes without assertion failures when the behavior remains correct.
                """
                ThinkingConfig._state = None
                patcher.stop()
                home.cleanup()

        return EnvContext()


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    """Verifies that read jsonl behaves as expected.

    Typical use: Use this in automated tests when guarding the read jsonl behavior against regressions.

    Example: _read_jsonl() -> passes without assertion failures when the behavior remains correct.
    """
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


async def _to_thread_inline(fn, /, *args, **kwargs):
    """Verifies that to thread inline behaves as expected.

    Typical use: Use this in automated tests when guarding the to thread inline behavior against regressions.

    Example: _to_thread_inline() -> passes without assertion failures when the behavior remains correct.
    """
    return fn(*args, **kwargs)


if __name__ == "__main__":
    unittest.main()
