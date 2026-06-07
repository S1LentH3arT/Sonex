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
from src.api.ws_runner import WebSocketRunner, _queue_payload
from src.auth.store import load_auth_store, set_api_key, set_default
from src.log import configure_file_logging, sonex_log_path
from src.thinking.config import ThinkingConfig


class FakeUI:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []
        self.statuses: list[object] = []
        self.transcript: list[dict[str, str]] = []

    async def append_user_message(self, text: str) -> None:
        self.transcript.append({"role": "user", "content": text})
        self.events.append({"type": "chat", "role": "user", "text": text})

    async def append_agent_message(self, text: str) -> None:
        self.transcript.append({"role": "agent", "content": text})
        self.events.append({"type": "chat", "role": "agent", "text": text})

    async def append_activity(self, **kwargs: object) -> str:
        self.events.append({"type": "activity", **kwargs})
        return str(kwargs.get("activity_id") or "activity_test")

    async def send_spotify_setup(self, **kwargs: object) -> None:
        self.events.append({"type": "spotify_setup", **kwargs})

    async def send_auth_setup(self, **kwargs: object) -> None:
        self.events.append({"type": "auth_setup", **kwargs})

    async def send_auth_state(self, state: object) -> None:
        payload = state.to_event() if hasattr(state, "to_event") else {"type": "auth_state", "state": state}
        self.events.append(payload)

    async def send_help_panel(self, commands: list[object], **kwargs: object) -> None:
        self.events.append(
            {
                "type": "help_panel",
                "commands": commands,
                **kwargs,
            }
        )

    async def send_error(self, message: str) -> None:
        self.events.append({"type": "error", "message": message})

    async def ask_confirm(self, attached: dict[str, object]) -> None:
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
        self.events.append({"type": "cover", "url": url})

    async def send_status(self, status: object, **kwargs: object) -> None:
        self.events.append({"type": "status", "status": status, **kwargs})

    async def _send(self, payload: dict[str, object]) -> None:
        self.events.append(payload)

    async def close(self) -> None:
        self.events.append({"type": "closed"})

    def set_status(self, status: object) -> None:
        self.statuses.append(status)


class FakeWebSocket:
    def __init__(self) -> None:
        self.sent: list[dict[str, object]] = []
        self.accepted = False
        self._sent_user_input = False
        self._sent_confirm_result = False
        self._sent_youtube_candidate = False

    async def accept(self) -> None:
        self.accepted = True

    async def send_text(self, text: str) -> None:
        self.sent.append(json.loads(text))

    async def receive_text(self) -> str:
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
    async def test_help_does_not_trigger_agent_or_auth_setup(self) -> None:
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
        runner = WebSocketRunner()
        runner._run_agent_turn = AsyncMock()
        ui = FakeUI()

        await runner._handle_user_input(ui, "/help re")

        help_events = [event for event in ui.events if event.get("type") == "help_panel"]
        self.assertTrue(help_events)
        self.assertEqual([command.name for command in help_events[0]["commands"]], ["recommend", "resume"])
        self.assertFalse(runner._run_agent_turn.called)

    async def test_bare_slash_opens_help_panel(self) -> None:
        runner = WebSocketRunner()
        runner._run_agent_turn = AsyncMock()
        ui = FakeUI()

        await runner._handle_user_input(ui, "/")

        self.assertTrue([event for event in ui.events if event.get("type") == "help_panel"])
        self.assertFalse(runner._run_agent_turn.called)

    async def test_setup_spotify_starts_spotify_setup(self) -> None:
        runner = WebSocketRunner()
        runner._run_agent_turn = AsyncMock()
        ui = FakeUI()

        with patch("src.api.ws_runner.spotify_redirect_uri", return_value="http://127.0.0.1:9957/callback"):
            await runner._handle_user_input(ui, "/setup spotify")

        self.assertFalse(runner._run_agent_turn.called)
        self.assertTrue(getattr(ui, "_spotify_setup"))
        self.assertTrue([event for event in ui.events if event.get("type") == "spotify_setup"])

    async def test_unknown_command_does_not_trigger_agent(self) -> None:
        runner = WebSocketRunner()
        runner._run_agent_turn = AsyncMock()
        ui = FakeUI()

        await runner._handle_user_input(ui, "/foo")

        self.assertFalse(runner._run_agent_turn.called)
        self.assertTrue(any("Unknown command" in str(event.get("text")) for event in ui.events))

    async def test_bye_saves_transcript_and_does_not_trigger_agent(self) -> None:
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

    async def test_want_to_listen_playback_online_choice_starts_spotify_candidates(self) -> None:
        runner = WebSocketRunner()
        runner._run_agent_turn = AsyncMock()
        ui = FakeUI()
        spotify_candidates = [
            {
                "id": "spotify-track",
                "name": "青花瓷",
                "artist": "周杰伦",
                "artists": ["周杰伦"],
                "album": "我很忙",
                "duration_ms": 239000,
                "uri": "spotify:track:qinghuaci",
            }
        ]

        with patch("src.api.ws_runner.search_local_file", return_value="No local files found related to '青花瓷'."), \
             patch("src.api.ws_runner.find_best_cached_song", return_value=None), \
             patch("src.api.ws_runner._llm_auth_ready", return_value=(False, "openai", "missing")):
            await runner._handle_user_input(ui, "我想听 青花瓷")

        self.assertFalse(runner._run_agent_turn.called)
        session = getattr(ui, "_play_selection")
        with patch("src.api.ws_runner.search_spotify_track_candidates", return_value=spotify_candidates) as spotify_search, \
             patch("src.api.ws_runner.search_youtube_songs") as youtube_search, \
             patch("src.api.ws_runner.online_audio_configured", return_value=True), \
             patch("src.api.ws_runner.asyncio.to_thread", side_effect=_to_thread_inline):
            await session.handle_choice("online_play")

        spotify_search.assert_called_once_with("青花瓷", 5)
        youtube_search.assert_not_called()
        confirm_events = [event for event in ui.events if event.get("type") == "confirm"]
        self.assertEqual(confirm_events[-1]["tool_name"], "spotify_candidate")
        self.assertEqual(confirm_events[-1]["choices"][0]["label"], "周杰伦-我很忙--青花瓷")

    async def test_online_choice_without_open_audio_provider_shows_setup_required(self) -> None:
        runner = WebSocketRunner()
        runner._run_agent_turn = AsyncMock()
        ui = FakeUI()

        with patch("src.api.ws_runner.search_local_file", return_value="No local files found related to '青花瓷'."), \
             patch("src.api.ws_runner.find_best_cached_song", return_value=None), \
             patch("src.api.ws_runner.online_audio_configured", return_value=False), \
             patch("src.api.ws_runner.search_spotify_track_candidates") as spotify_search, \
             patch("src.api.ws_runner.search_online_audio_candidates") as online_search:
            await runner._handle_user_input(ui, "/play 青花瓷")
            session = getattr(ui, "_play_selection")
            await session.handle_choice("online_play")

        spotify_search.assert_not_called()
        online_search.assert_not_called()
        self.assertTrue(any("Jamendo or Audius" in str(event.get("text")) for event in ui.events))
        confirm_events = [event for event in ui.events if event.get("type") == "confirm"]
        self.assertEqual(confirm_events[-1]["tool_name"], "playback_choice")

    async def test_setup_jamendo_stores_open_audio_api_key(self) -> None:
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

    async def test_online_play_choice_sends_spotify_candidate_list_before_youtube_search(self) -> None:
        runner = WebSocketRunner()
        ui = FakeUI()
        spotify_candidates = [
            {
                "id": f"spotify-{idx}",
                "name": f"Song {idx}",
                "artist": f"Artist {idx}",
                "artists": [f"Artist {idx}"],
                "album": f"Album {idx}",
                "duration_ms": (180 + idx) * 1000,
                "uri": f"spotify:track:{idx}",
            }
            for idx in range(6)
        ]

        with patch("src.api.ws_runner.search_local_file", return_value="No local files found related to 'Song Artist'."), \
             patch("src.api.ws_runner.find_best_cached_song", return_value=None):
            await runner._handle_user_input(ui, "/play Song Artist")
        session = getattr(ui, "_play_selection")
        with patch("src.api.ws_runner.search_spotify_track_candidates", return_value=spotify_candidates) as spotify_search, \
             patch("src.api.ws_runner.search_youtube_songs") as youtube_search, \
             patch("src.api.ws_runner.online_audio_configured", return_value=True), \
             patch("src.api.ws_runner.asyncio.to_thread", side_effect=_to_thread_inline):
            await session.handle_choice("online_play")

        spotify_search.assert_called_once_with("Song Artist", 5)
        youtube_search.assert_not_called()
        confirm_events = [event for event in ui.events if event.get("type") == "confirm"]
        self.assertEqual(confirm_events[-1]["tool_name"], "spotify_candidate")
        self.assertEqual(confirm_events[-1]["tool_args"]["stage"], "spotify_candidates")
        self.assertEqual(len(confirm_events[-1]["choices"]), 6)
        self.assertEqual(confirm_events[-1]["choices"][0]["value"], "spotify_candidate:0")
        self.assertEqual(confirm_events[-1]["choices"][0]["label"], "Artist 0-Album 0--Song 0")
        self.assertIn("3:00", confirm_events[-1]["choices"][0]["description"])
        self.assertEqual(confirm_events[-1]["choices"][-1]["value"], "refine_spotify_query")
        self.assertEqual(confirm_events[-1]["choices"][-1]["input"]["placeholder"], "试试补充更多歌曲信息")

    async def test_spotify_candidate_choice_searches_youtube_with_confirmed_metadata(self) -> None:
        runner = WebSocketRunner()
        ui = FakeUI()
        spotify_candidate = {
            "id": "spotify-track",
            "name": "Canonical Song",
            "artist": "Canonical Artist",
            "artists": ["Canonical Artist"],
            "album": "Canonical Album",
            "duration_ms": 201000,
            "uri": "spotify:track:canonical",
        }
        youtube_candidate = {
            "cache_id": "youtube_abc",
            "id": "abc",
            "youtube_id": "abc",
            "name": "Canonical Song",
            "artist": "Canonical Artist",
            "duration_ms": 201000,
            "cached": False,
        }

        with patch("src.api.ws_runner.search_local_file", return_value="No local files found related to 'messy query'."), \
             patch("src.api.ws_runner.find_best_cached_song", return_value=None):
            await runner._handle_user_input(ui, "/play messy query")
        session = getattr(ui, "_play_selection")
        with patch("src.api.ws_runner.search_spotify_track_candidates", return_value=[spotify_candidate]), \
             patch("src.api.ws_runner.search_youtube_songs", return_value=[youtube_candidate]) as youtube_search, \
             patch("src.api.ws_runner.online_audio_configured", return_value=True), \
             patch("src.api.ws_runner.asyncio.to_thread", side_effect=_to_thread_inline):
            await session.handle_choice("online_play")
            await session.handle_choice("spotify_candidate:0")

        youtube_search.assert_called_once()
        self.assertEqual(youtube_search.call_args.args[0], "Canonical Artist Canonical Song")
        self.assertEqual(youtube_search.call_args.args[1], 5)
        metadata = youtube_search.call_args.kwargs["playback_metadata"]
        self.assertEqual(metadata["name"], "Canonical Song")
        self.assertEqual(metadata["artist"], "Canonical Artist")
        self.assertEqual(metadata["album"], "Canonical Album")
        self.assertEqual(metadata["uri"], "spotify:track:canonical")
        self.assertEqual(metadata["original_query"], "messy query")
        confirm_events = [event for event in ui.events if event.get("type") == "confirm"]
        self.assertEqual(confirm_events[-1]["tool_name"], "online_audio_candidate")
        self.assertEqual(confirm_events[-1]["choices"][0]["value"], "youtube_candidate:youtube_abc")

    async def test_spotify_candidate_refine_researches_spotify_not_youtube(self) -> None:
        runner = WebSocketRunner()
        runner._run_agent_turn = AsyncMock()
        ui = FakeUI()
        first_candidate = {"name": "First", "artist": "Artist", "album": "Album", "duration_ms": 180000}
        refined_candidate = {"name": "Refined", "artist": "Artist", "album": "Album", "duration_ms": 181000}

        with patch("src.api.ws_runner.search_local_file", return_value="No local files found related to 'Song Artist'."), \
             patch("src.api.ws_runner.find_best_cached_song", return_value=None):
            await runner._handle_user_input(ui, "/play Song Artist")
        session = getattr(ui, "_play_selection")
        with patch("src.api.ws_runner.search_spotify_track_candidates", side_effect=[[first_candidate], [refined_candidate]]) as spotify_search, \
             patch("src.api.ws_runner.search_youtube_songs") as youtube_search, \
             patch("src.api.ws_runner.online_audio_configured", return_value=True), \
             patch("src.api.ws_runner.asyncio.to_thread", side_effect=_to_thread_inline):
            await session.handle_choice("online_play")
            await session.handle_choice("refine_spotify_query")
            await runner._handle_user_input(ui, "live acoustic")

        self.assertEqual(spotify_search.call_args_list[0].args, ("Song Artist", 5))
        self.assertEqual(spotify_search.call_args_list[1].args, ("Song Artist live acoustic", 5))
        youtube_search.assert_not_called()
        self.assertFalse(runner._run_agent_turn.called)
        confirm_events = [event for event in ui.events if event.get("type") == "confirm"]
        self.assertEqual(confirm_events[-1]["choices"][0]["label"], "Artist-Album--Refined")

    async def test_youtube_candidate_refine_appends_next_input_and_researches(self) -> None:
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
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {"SONEX_HOME": home}):
            self.assertEqual(sonex_log_path(), Path(home) / "log")

    def test_configure_file_logging_writes_to_log_filename(self) -> None:
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {"SONEX_HOME": home}):
            log_path = configure_file_logging()
            logging.getLogger().info("sonex log filename test")
            for handler in logging.getLogger().handlers:
                handler.flush()

            self.assertEqual(log_path, Path(home) / "log")
            self.assertIn("sonex log filename test", log_path.read_text(encoding="utf-8"))

    async def test_agent_turn_reports_live_planning_metrics_while_llm_is_waiting(self) -> None:
        runner = WebSocketRunner()
        ui = FakeUI()

        def slow_agent_loop(user_input: str, tools: object):
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
        runner = WebSocketRunner()
        ui = FakeUI()

        def failing_agent_loop(user_input: str, tools: object):
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
        runner = WebSocketRunner()
        ui = FakeUI()
        ui.closed = False
        sleeps = 0

        async def stop_after_two_sleeps(_: float) -> None:
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
            def __enter__(self_nonlocal) -> str:
                patcher.start()
                ThinkingConfig._state = None
                return home.name

            def __exit__(self_nonlocal, exc_type, exc, tb) -> None:
                ThinkingConfig._state = None
                patcher.stop()
                home.cleanup()

        return EnvContext()


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


async def _to_thread_inline(fn, /, *args, **kwargs):
    return fn(*args, **kwargs)


if __name__ == "__main__":
    unittest.main()
