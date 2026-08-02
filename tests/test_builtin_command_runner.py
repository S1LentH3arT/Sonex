"""Tests test builtin command runner.

Contains pytest coverage for the test builtin command runner behavior.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import WebSocketDisconnect

from src.agent.action import ToolAction
from src.agent.core import AgentState
from src.api import ws_runner
from src.api.builtin_commands import CommandIntent
from src.api.music_intent import MusicIntentDecision, MusicIntentRoute
from src.api.ws_runner import WebSocketRunner, _decorate_player_state, _player_sync_signature, _queue_payload, _track_panel_payload
from src.auth.models import OAuthToken
from src.auth.store import load_auth_store, set_api_key, set_default
from src.log import configure_file_logging, sonex_log_path
from src.music.playback_coordinator import ProviderReadiness, RecordingIdentity
from src.music.player_sinks import PlayerSelectionResult
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
        self.session_id = "test-session"

    async def append_user_message(self, text: str) -> None:
        """Verifies that append user message behaves as expected.

        Typical use: Use this in automated tests when guarding the append user message behavior against regressions.

        Example: append_user_message() -> passes without assertion failures when the behavior remains correct.
        """
        self.transcript.append({"role": "user", "content": text})
        self.events.append({"type": "chat", "role": "user", "text": text})

    async def append_agent_message(
        self,
        text: str,
        *,
        segments: object | None = None,
    ) -> None:
        """Verifies that append agent message behaves as expected.

        Typical use: Use this in automated tests when guarding the append agent message behavior against regressions.

        Example: append_agent_message() -> passes without assertion failures when the behavior remains correct.
        """
        self.transcript.append({"role": "agent", "content": text})
        event = {"type": "chat", "role": "agent", "text": text}
        mode = getattr(self, "_spotify_mode", None)
        if isinstance(mode, dict) and mode.get("enabled"):
            event["theme"] = "spotify"
        if segments is not None:
            event["segments"] = segments
        self.events.append(event)

    async def append_system_message(self, text: str) -> None:
        self.transcript.append({"role": "agent", "content": text})
        self.events.append(
            {
                "type": "chat",
                "role": "agent",
                "tone": "system",
                "text": text,
            }
        )

    async def append_warning_message(self, text: str) -> None:
        self.transcript.append({"role": "agent", "content": text})
        self.events.append(
            {
                "type": "chat",
                "role": "agent",
                "tone": "warning",
                "text": text,
            }
        )

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

    async def send_agent_working_state(self, turn_id: str, *, active: bool) -> None:
        self.events.append(
            {
                "type": "agent_working_state",
                "turn_id": turn_id,
                "active": active,
            }
        )

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
                "warning": attached.get("warning"),
                "hide_hint": attached.get("hide_hint"),
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

    async def send_input_state(self, disabled: bool, reason: str | None = None) -> None:
        """Records input-state events for command-flow assertions."""
        self.events.append({"type": "input_state", "disabled": disabled, "reason": reason})

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


class MusicCandidateLabelTests(unittest.TestCase):
    def test_music_candidate_display_preserves_raw_fields(self) -> None:
        self.assertTrue(hasattr(ws_runner, "music_candidate_display"))

        display = ws_runner.music_candidate_display(
            "周杰伦 Jay Chou",
            "我很忙 Still Fantasy",
            "青花瓷 Blue and White Porcelain",
        )

        self.assertEqual(display, {
            "kind": "music_candidate",
            "artist": "周杰伦 Jay Chou",
            "album": "我很忙 Still Fantasy",
            "title": "青花瓷 Blue and White Porcelain",
        })

    def test_music_candidate_display_uses_dash_for_blank_fields(self) -> None:
        self.assertTrue(hasattr(ws_runner, "music_candidate_display"))

        display = ws_runner.music_candidate_display(" ", "", None)

        self.assertEqual(display, {
            "kind": "music_candidate",
            "artist": "-",
            "album": "-",
            "title": "-",
        })

    def test_music_candidate_label_uses_fixed_character_columns(self) -> None:
        self.assertTrue(hasattr(ws_runner, "format_music_candidate_label"))

        label = ws_runner.format_music_candidate_label("周杰伦", "我很忙", "青花瓷")

        self.assertEqual(label, f"{'周杰伦'.ljust(24)} {'我很忙'.ljust(24)} 青花瓷")

    def test_music_candidate_label_aligns_title_after_album_column(self) -> None:
        self.assertTrue(hasattr(ws_runner, "format_music_candidate_label"))

        short_album = ws_runner.format_music_candidate_label("Artist", "EP", "Short title")
        long_album = ws_runner.format_music_candidate_label("Artist", "abcdefghijklmnopq", "Long title")

        self.assertEqual(short_album.index("Short title"), 50)
        self.assertEqual(long_album.index("Long title"), 50)

    def test_music_candidate_label_truncates_columns_by_python_character_count(self) -> None:
        self.assertTrue(hasattr(ws_runner, "format_music_candidate_label"))

        label = ws_runner.format_music_candidate_label(
            "abcdefghijklmnopqrstuvwxy",
            "abcdefghijklmnopqrstuvwxy",
            "full title stays visible",
        )

        self.assertEqual(label, "abcdefghijklmnopqrstu... abcdefghijklmnopqrstu... full title stays visible")

    def test_music_candidate_label_uses_dash_for_blank_fields(self) -> None:
        self.assertTrue(hasattr(ws_runner, "format_music_candidate_label"))

        label = ws_runner.format_music_candidate_label("  ", "", None)

        self.assertEqual(label, f"{'-'.ljust(24)} {'-'.ljust(24)} -")


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
            return json.dumps({"type": "user_input", "text": "play Song Artist"})
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


class PlayerBackendWebSocket:
    def __init__(self) -> None:
        self.sent: list[dict[str, object]] = []
        self.accepted = False
        self._sent_player_command = False
        self._sent_confirm_result = False

    async def accept(self) -> None:
        self.accepted = True

    async def send_text(self, text: str) -> None:
        self.sent.append(json.loads(text))

    async def receive_text(self) -> str:
        if not self._sent_player_command:
            self._sent_player_command = True
            return json.dumps({"type": "user_input", "text": "/player mpv"})
        if not self._sent_confirm_result:
            confirm_id = next(
                (
                    str(event["id"])
                    for event in self.sent
                    if event.get("type") == "confirm" and event.get("tool_name") == "local_playback_player"
                ),
                None,
            )
            if confirm_id:
                self._sent_confirm_result = True
                return json.dumps({"type": "confirm_result", "id": confirm_id, "decision": "managed:cvlc"})
        await asyncio.sleep(0)
        raise WebSocketDisconnect()


class DisconnectingWebSocket:
    def __init__(self) -> None:
        self.sent: list[dict[str, object]] = []
        self.accepted = False

    async def accept(self) -> None:
        self.accepted = True

    async def send_text(self, text: str) -> None:
        self.sent.append(json.loads(text))

    async def receive_text(self) -> str:
        await asyncio.sleep(0)
        raise WebSocketDisconnect()


class BuiltinCommandRunnerTests(unittest.IsolatedAsyncioTestCase):
    """Groups related builtin command runner tests cases.

    Collects assertions that exercise builtin command runner tests behavior without mixing unrelated fixtures.
    """

    async def test_active_agent_turn_queues_user_messages_fifo_and_warns_at_limit(self) -> None:
        runner = WebSocketRunner()
        ui = FakeUI()
        blocker = asyncio.Event()
        active = asyncio.create_task(blocker.wait())
        setattr(ui, "_agent_turn_task", active)
        try:
            for index in range(11):
                await runner._handle_user_input(ui, f"queued {index}")
        finally:
            active.cancel()

        self.assertEqual(
            list(getattr(ui, "_agent_input_queue")),
            [f"queued {index}" for index in range(10)],
        )
        self.assertTrue(
            any(
                event.get("tone") == "warning"
                and "queue is full" in str(event.get("text"))
                for event in ui.events
            )
        )
        self.assertEqual(
            [
                item.get("execution")
                for item in ui.transcript
                if item.get("role") == "user"
            ][:10],
            ["queued"] * 10,
        )

    async def test_agent_interrupt_is_turn_bound_and_cancels_provider_work_once(self) -> None:
        runner = WebSocketRunner()
        ui = FakeUI()
        interrupt_event = threading.Event()
        provider_task = asyncio.create_task(asyncio.sleep(60))
        setattr(ui, "_active_agent_turn_id", "turn-current")
        setattr(ui, "_agent_turn_interrupt_event", interrupt_event)
        setattr(ui, "_active_agent_provider_task", provider_task)

        interrupted = await runner._handle_agent_turn_interrupt(
            ui,
            "turn-current",
        )
        await asyncio.sleep(0)
        stale = await runner._handle_agent_turn_interrupt(
            ui,
            "turn-current",
        )

        self.assertTrue(interrupted)
        self.assertFalse(stale)
        self.assertTrue(interrupt_event.is_set())
        self.assertTrue(provider_task.cancelled())
        self.assertEqual(
            [
                event
                for event in ui.events
                if event.get("type") == "agent_working_state"
            ],
            [
                {
                    "type": "agent_working_state",
                    "turn_id": "turn-current",
                    "active": False,
                }
            ],
        )
        self.assertEqual(
            [
                event.get("text")
                for event in ui.events
                if event.get("tone") == "system"
            ],
            ["Agent turn interrupted."],
        )

    async def test_agent_interrupt_returns_without_waiting_for_blocked_planner_thread(self) -> None:
        runner = WebSocketRunner()
        ui = FakeUI()
        release = threading.Event()

        def blocked_agent_loop(*_args: object, **_kwargs: object):
            release.wait(timeout=2)
            yield AgentState(type="complete", content="late")

        with patch("src.api.ws_runner.agent_loop", blocked_agent_loop):
            task = asyncio.create_task(runner._run_agent_turn(ui, "hello"))
            for _ in range(20):
                await asyncio.sleep(0.01)
                turn_id = getattr(ui, "_active_agent_turn_id", None)
                if turn_id:
                    break
            else:
                self.fail("Agent turn never entered Working state.")

            interrupted = await runner._handle_agent_turn_interrupt(ui, turn_id)
            await asyncio.wait_for(task, timeout=0.5)
            release.set()

        self.assertTrue(interrupted)
        self.assertFalse(
            any(
                event.get("type") == "chat"
                and event.get("text") == "late"
                for event in ui.events
            )
        )

    async def test_authoritative_route_rejection_tries_next_ready_provider(self) -> None:
        runner = WebSocketRunner()
        ui = FakeUI()
        spotify = ProviderReadiness(
            "spotify",
            True,
            True,
            True,
            True,
            startup_latency_ms=10,
        )
        netease = ProviderReadiness(
            "netease",
            True,
            True,
            True,
            True,
            startup_latency_ms=20,
        )
        runner._probe_authoritative_providers = AsyncMock(
            return_value=[netease, spotify]
        )
        runner._confirm_agent_playback_route = AsyncMock(
            side_effect=[False, True]
        )
        runner._ensure_authoritative_mode = AsyncMock(return_value=True)
        runner._try_selected_native_provider = AsyncMock(
            return_value={
                "status": "playback_completed",
                "message": "NetEase playback started.",
                "data": {"provider": "netease"},
            }
        )

        result = await runner._route_authoritative_provider(
            ui,
            identity=RecordingIdentity("BB88", "方大同"),
            selected_candidate={"title": "BB88", "artist": "方大同"},
            requested_provider=None,
            hard_provider=False,
        )

        self.assertEqual(result["status"], "playback_completed")
        self.assertEqual(
            [
                call.kwargs["provider"]
                for call in runner._confirm_agent_playback_route.await_args_list
            ],
            ["spotify", "netease"],
        )
        self.assertEqual(
            runner._try_selected_native_provider.await_args.kwargs["provider"],
            "netease",
        )

    async def test_explicit_provider_rejection_does_not_cross_provider_boundary(self) -> None:
        runner = WebSocketRunner()
        ui = FakeUI()
        providers = [
            ProviderReadiness("spotify", True, True, True, True),
            ProviderReadiness("netease", True, True, True, True),
        ]
        runner._probe_authoritative_providers = AsyncMock(return_value=providers)
        runner._confirm_agent_playback_route = AsyncMock(return_value=False)
        runner._ensure_authoritative_mode = AsyncMock(return_value=True)
        runner._try_selected_native_provider = AsyncMock()

        result = await runner._route_authoritative_provider(
            ui,
            identity=RecordingIdentity("BB88", "方大同"),
            selected_candidate={"title": "BB88", "artist": "方大同"},
            requested_provider="spotify",
            hard_provider=True,
        )

        self.assertEqual(result["status"], "playback_failed")
        runner._try_selected_native_provider.assert_not_awaited()
        self.assertEqual(result["data"]["attempted"], ["spotify"])

    async def test_agent_community_fallback_offers_only_one_explicit_alternative(self) -> None:
        runner = WebSocketRunner()
        ui = FakeUI()
        completed: list[dict[str, object]] = []
        session = ws_runner.PlaySelectionSession(
            ui,
            runner,
            "方大同 BB88",
            on_finish=completed.append,
        )
        session.selected_playback_metadata = {
            "title": "BB88",
            "name": "BB88",
            "artist": "方大同",
            "duration_ms": 240_000,
        }
        alternative = {
            "cache_id": "alternative-1",
            "provider": "audius",
            "title": "BB88 (Live)",
            "name": "BB88 (Live)",
            "artist": "方大同",
            "duration_ms": 260_000,
            "assessment": {"confidence": "medium"},
        }

        with patch(
            "src.api.ws_runner._search_online_audio_for_runner",
            return_value=[alternative],
        ), patch(
            "src.api.ws_runner.resolve_online_playback_metadata",
            return_value={},
        ):
            await session._play_selected_metadata_candidate(
                "方大同 BB88",
                session.selected_playback_metadata,
            )

        confirmations = [
            event for event in ui.events if event.get("type") == "confirm"
        ]
        self.assertEqual(len(confirmations), 1)
        self.assertIn("Alternative version: BB88 (Live)", confirmations[0]["message"])
        values = [
            choice.get("value")
            for choice in confirmations[0]["choices"]
        ]
        self.assertEqual(values, ["youtube_candidate:alternative-1", "deny"])
        self.assertNotIn("refine_query", values)
        self.assertEqual(completed, [])

    def test_verified_cache_requires_exact_identity_and_existing_audio(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            audio_path = Path(directory) / "bb88.mp3"
            audio_path.write_bytes(b"audio")
            cached = {
                "cache_id": "bb88",
                "title": "BB88",
                "name": "BB88",
                "artist": "方大同",
                "duration_ms": 240_000,
                "audio_path": str(audio_path),
            }
            with patch(
                "src.api.ws_runner.find_best_cached_song",
                return_value={"cache_id": "bb88"},
            ), patch(
                "src.api.ws_runner.resolve_cached_song",
                return_value=cached,
            ):
                exact = WebSocketRunner._verified_cached_recording(
                    RecordingIdentity(
                        "BB88",
                        "方大同",
                        duration_ms=240_000,
                    )
                )
                mismatch = WebSocketRunner._verified_cached_recording(
                    RecordingIdentity(
                        "BB88 (Live)",
                        "方大同",
                        duration_ms=260_000,
                    )
                )

        self.assertEqual(exact["playback_path"], str(audio_path))
        self.assertTrue(exact["cached"])
        self.assertIsNone(mismatch)

    _RETIRED_DIRECT_ROUTING_TESTS = {
        "test_explicit_natural_language_playback_starts_selection_session",
        "test_general_music_question_does_not_start_playback",
        "test_llm_track_play_intent_starts_play_selection",
        "test_missing_online_audio_setup_ends_without_method_panel",
        "test_natural_language_recommendation_reference_starts_selected_track",
        "test_normal_mode_starts_metadata_before_open_audio_setup_is_needed",
        "test_normal_playback_does_not_probe_provider_accounts",
        "test_online_play_choice_describes_youtube_fallback_source_attempts",
        "test_online_play_choice_handles_player_launch_confirmation",
        "test_online_play_choice_reports_failure_to_chat_and_error",
        "test_online_play_choice_reports_pending_and_enters_player_mode",
        "test_online_play_choice_sends_song_candidate_list_before_audio_search",
        "test_online_play_choice_sends_youtube_candidate_list",
        "test_online_play_confirm_result_from_websocket_invokes_playback",
        "test_online_play_without_metadata_candidates_falls_back_to_audio_candidates",
        "test_out_of_range_recommendation_reference_reports_valid_range",
        "test_play_local_match_can_skip_directly_to_song_candidates",
        "test_play_number_starts_song_candidates_without_method_panel",
        "test_polite_natural_language_playback_starts_selection_session",
        "test_random_outside_spotify_mode_still_routes_to_agent_intent",
        "test_recommend_queues_visible_recommendations_without_agent_turn",
        "test_recommend_returns_immediately_while_providers_load",
        "test_recommend_uses_other_provider_when_one_provider_fails",
        "test_recommend_without_args_uses_empty_query_intro",
        "test_recommendation_route_uses_restricted_agent_without_confirm",
        "test_setup_apple_cancel_hides_panel_and_appends_system_message",
        "test_setup_apple_stores_token_service_url_from_terminal_panel",
        "test_setup_audius_guides_api_key_input_and_repeats_empty_values",
        "test_setup_jamendo_stores_open_audio_api_key",
        "test_setup_spotify_starts_spotify_setup",
        "test_song_candidate_choice_plays_online_audio_with_confirmed_metadata",
        "test_song_candidate_cover_lookup_can_complete_when_audio_fails",
        "test_song_candidate_direct_success_announces_playing_once",
        "test_song_candidate_player_confirmation_reports_choice_and_playing",
        "test_song_candidate_player_failure_has_no_success_feedback",
        "test_song_candidate_player_non_success_choices_have_no_feedback",
        "test_song_candidate_refine_researches_metadata_not_audio",
        "test_spotify_command_is_not_available_inside_spotify_mode",
        "test_spotify_mode_random_plays_random_recent_track_without_agent_turn",
        "test_spotify_mode_random_reports_empty_recent_tracks_without_playing",
        "test_spotify_mode_random_reports_play_failure",
        "test_spotify_mode_random_reports_recent_tracks_failure_without_agent_turn",
        "test_spotify_mode_random_returns_immediately_while_recent_tracks_load",
        "test_spotify_mode_recommend_queue_failure_is_visible",
        "test_spotify_mode_recommend_queues_spotify_tracks_without_agent_turn",
        "test_spotify_mode_recommend_timeout_covers_queue_add",
        "test_spotify_mode_track_choice_plays_selected_uri_on_device",
        "test_spotify_off_is_not_available_inside_spotify_mode",
        "test_track_interest_acceptance_starts_play_selection",
        "test_want_to_listen_starts_song_metadata_candidates_without_method_choice",
        "test_youtube_candidate_choice_downloads_cache_and_plays_local_audio",
        "test_youtube_candidate_inline_refine_researches",
        "test_youtube_candidate_refine_appends_next_input_and_researches",
    }

    def setUp(self) -> None:
        """Isolate Spotify synchronization scheduling metadata for each test."""
        if self._testMethodName in self._RETIRED_DIRECT_ROUTING_TESTS:
            self.skipTest(
                "Retired direct-router contract; Agent Tool coverage lives in "
                "test_agent_tool_surface.py."
            )
        self._spotify_sync_home = tempfile.TemporaryDirectory()
        self._spotify_sync_path_patch = patch(
            "src.tools.spotify_library_sync.spotify_library_sync_state_path",
            return_value=Path(self._spotify_sync_home.name) / "library_sync.json",
        )
        self._spotify_sync_path_patch.start()
        self._player_home_patch = patch(
            "src.music.player_sinks.sonex_home",
            return_value=Path(self._spotify_sync_home.name),
        )
        self._player_home_patch.start()
        self._metadata_search_patch = patch(
            "src.api.ws_runner.search_track_metadata_candidates",
            return_value={"candidates": [], "source_attempts": []},
        )
        self._metadata_search_patch.start()
        self._online_audio_search_patch = patch(
            "src.api.ws_runner.search_online_audio_candidates",
            return_value=[],
        )
        self._online_audio_search_patch.start()
        self._player_detection_patch = patch(
            "src.api.ws_runner.available_local_playback_backends",
            return_value=[
                {
                    "backend": "mpv",
                    "label": "mpv",
                    "description": "Controllable local player for stable background playback.",
                    "executable": "/usr/bin/mpv",
                },
                {
                    "backend": "cvlc",
                    "label": "VLC",
                    "description": "Controllable VLC playback through its RC interface.",
                    "executable": "/usr/bin/cvlc",
                },
            ],
        )
        self._player_detection = self._player_detection_patch.start()
        self._managed_player_validation_patch = patch(
            "src.music.player_sink_runtime._validate_managed_player",
            return_value=True,
        )
        self._managed_player_validation_patch.start()
        self._to_thread_patch = patch(
            "src.api.ws_runner.asyncio.to_thread",
            side_effect=_to_thread_inline,
        )
        self._to_thread_patch.start()

    def tearDown(self) -> None:
        """Restore Spotify sync state resolution and remove temporary data."""
        self._to_thread_patch.stop()
        self._player_detection_patch.stop()
        self._managed_player_validation_patch.stop()
        self._online_audio_search_patch.stop()
        self._metadata_search_patch.stop()
        self._spotify_sync_path_patch.stop()
        self._player_home_patch.stop()
        self._spotify_sync_home.cleanup()

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

    async def test_websocket_starts_local_playback_sync_task(self) -> None:
        runner = WebSocketRunner()
        ws = DisconnectingWebSocket()

        async def idle_sync(_ui: object) -> None:
            while True:
                await asyncio.sleep(60)

        spotify_sync = AsyncMock(side_effect=idle_sync)
        local_sync = AsyncMock(side_effect=idle_sync)
        with patch.object(runner, "_handle_startup_auth", new=AsyncMock()), \
             patch.object(runner, "_sync_spotify_playback", new=spotify_sync), \
             patch.object(runner, "_sync_local_playback", new=local_sync), \
             patch("src.api.ws_runner.create_session_id", return_value="session-1"):
            await runner.handle_ws(ws)  # type: ignore[arg-type]

        self.assertTrue(ws.accepted)
        self.assertEqual(local_sync.await_count, 1)
        self.assertEqual(
            ws.sent[0],
            {"type": "session_state", "session_id": "session-1"},
        )
        self.assertEqual(ws.sent[1]["type"], "queue")
        self.assertIn("tracks", ws.sent[1])

    async def test_handle_bye_reuses_connection_session_id(self) -> None:
        runner = WebSocketRunner()
        ui = AsyncMock()
        ui.session_id = "session-1"

        with patch(
            "src.api.ws_runner._save_session_transcript",
            return_value=Path("/tmp/sessions/session-1/transcript.jsonl"),
        ) as save_transcript:
            await runner._handle_bye(
                ui,
                messages=[{"role": "user", "content": "hello"}],
                reason="bye",
            )

        save_transcript.assert_called_once_with(
            [{"role": "user", "content": "hello"}],
            reason="bye",
            session_id="session-1",
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

    async def test_login_opens_provider_picker_without_agent_turn(self) -> None:
        runner = WebSocketRunner()
        runner._run_agent_turn = AsyncMock()
        ui = FakeUI()

        await runner._handle_user_input(ui, "/login")

        auth_events = [event for event in ui.events if event.get("type") == "auth_setup"]
        self.assertFalse(runner._run_agent_turn.called)
        self.assertEqual(auth_events[-1]["step"], "provider")
        self.assertEqual(
            [choice["value"] for choice in auth_events[-1]["providers"]],
            [
                "openai", "gemini", "anthropic", "deepseek", "openrouter", "zai",
                "kimi_global", "kimi_cn", "minimax_global", "minimax_cn", "xai", "custom",
            ],
        )

    async def test_login_rejects_provider_arguments(self) -> None:
        runner = WebSocketRunner()
        runner._run_agent_turn = AsyncMock()
        ui = FakeUI()

        await runner._handle_user_input(ui, "/login openai")

        self.assertFalse(runner._run_agent_turn.called)
        self.assertFalse([event for event in ui.events if event.get("type") == "auth_setup"])
        self.assertTrue(any(event.get("text") == "Usage: /login" for event in ui.events))

    async def test_lang_is_treated_as_an_unknown_command(self) -> None:
        runner = WebSocketRunner()
        runner._run_agent_turn = AsyncMock()
        ui = FakeUI()

        await runner._handle_user_input(ui, "/lang")

        self.assertFalse(runner._run_agent_turn.called)
        self.assertFalse([event for event in ui.events if event.get("type") == "auth_setup"])
        self.assertTrue(any(
            event.get("text") == "Unknown command: /lang. Type /help to view available commands."
            for event in ui.events
        ))

    async def test_info_backend_fallback_reports_runtime_without_agent_or_auth_setup(self) -> None:
        runner = WebSocketRunner()
        runner._run_agent_turn = AsyncMock()
        ui = FakeUI()
        state = ws_runner.AuthRuntimeState(
            ready=True,
            provider="openai",
            model="gpt-info",
            auth_type="oauth",
            credential_source="auth.json",
        )

        with patch("src.api.ws_runner._llm_auth_state", return_value=state):
            await runner._handle_user_input(ui, "/info")

        self.assertFalse(runner._run_agent_turn.called)
        self.assertFalse([event for event in ui.events if event.get("type") == "auth_setup"])
        info_events = [
            event for event in ui.events
            if event.get("type") == "chat" and event.get("role") == "agent"
        ]
        self.assertEqual(len(info_events), 1)
        self.assertEqual(info_events[0].get("tone"), "system")
        text = str(info_events[0].get("text"))
        self.assertIn("Model: gpt-info", text)
        self.assertIn("Provider: openai", text)
        self.assertIn("Auth: oauth", text)
        self.assertIn("CWD: ", text)

    async def test_info_is_available_in_spotify_mode(self) -> None:
        runner = WebSocketRunner()
        runner._run_agent_turn = AsyncMock()
        ui = FakeUI()
        setattr(ui, "_spotify_mode", {"enabled": True})
        state = ws_runner.AuthRuntimeState(
            ready=True,
            provider="openai",
            model="gpt-spotify-info",
            auth_type="api_key",
            credential_source="env",
        )

        with patch("src.api.ws_runner._llm_auth_state", return_value=state):
            await runner._handle_user_input(ui, "/info")

        self.assertFalse(runner._run_agent_turn.called)
        self.assertFalse(any("not available in Spotify mode" in str(event) for event in ui.events))
        self.assertTrue(any("Model: gpt-spotify-info" in str(event.get("text")) for event in ui.events))

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

    async def test_spotify_command_refuses_free_account(self) -> None:
        runner = WebSocketRunner()
        runner._run_agent_turn = AsyncMock()
        ui = FakeUI()

        with patch("src.api.ws_runner.spotify_account", return_value={
            "status": "success",
            "data": {"logged_in": True, "product": "free", "capabilities": {"playback_control": False}},
        }), patch("src.api.ws_runner.spotify_devices") as devices, \
             patch("src.api.ws_runner.asyncio.to_thread", side_effect=_to_thread_inline):
            await runner._handle_user_input(ui, "/spotify")

        devices.assert_not_called()
        self.assertFalse(runner._run_agent_turn.called)
        self.assertIsNone(getattr(ui, "_spotify_mode", None))
        self.assertTrue(any("Premium" in str(event.get("detail")) for event in ui.events if event.get("type") == "activity"))

    async def test_spotify_command_allows_unknown_product_with_required_scopes(self) -> None:
        runner = WebSocketRunner()
        runner._run_agent_turn = AsyncMock()
        ui = FakeUI()

        with patch("src.api.ws_runner.spotify_account", return_value={
            "status": "success",
            "data": {
                "logged_in": True,
                "product": "unknown",
                "scopes": sorted(ws_runner.SPOTIFY_MODE_REQUIRED_SCOPES),
                "capabilities": {"playback_control": True, "current_playback": True, "playlist_read": True, "library_read": True},
            },
        }), patch("src.api.ws_runner.spotify_devices", return_value={
            "status": "success",
            "data": {"devices": [{"id": "desktop", "name": "Studio Desktop", "type": "Computer", "is_active": True}]},
        }), patch("src.api.ws_runner.asyncio.to_thread", side_effect=_to_thread_inline):
            await runner._handle_user_input(ui, "/spotify")

        self.assertFalse(runner._run_agent_turn.called)
        self.assertTrue(getattr(ui, "_spotify_mode")["enabled"])
        self.assertEqual(getattr(ui, "_spotify_mode")["device_name"], "Studio Desktop")
        self.assertFalse(any("requires Spotify Premium" in str(event.get("detail")) for event in ui.events if event.get("type") == "activity"))

    async def test_spotify_command_reports_rate_limited_account_check(self) -> None:
        runner = WebSocketRunner()
        runner._run_agent_turn = AsyncMock()
        ui = FakeUI()
        message = "Spotify says Too Many Requests. Requests are too frequent; try again later."

        with patch("src.api.ws_runner.spotify_account", return_value={
            "status": "fail",
            "message": message,
            "error_code": "SPOTIFY_RATE_LIMITED",
            "data": {"retry_after": "30 seconds"},
        }), patch("src.api.ws_runner.spotify_devices") as devices, \
             patch("src.api.ws_runner.asyncio.to_thread", side_effect=_to_thread_inline):
            await runner._handle_user_input(ui, "/spotify")

        devices.assert_not_called()
        self.assertFalse(runner._run_agent_turn.called)
        self.assertIsNone(getattr(ui, "_spotify_mode", None))
        self.assertTrue(any(message in str(event.get("detail")) for event in ui.events if event.get("type") == "activity"))
        self.assertTrue(any(message in str(event.get("text")) for event in ui.events if event.get("type") == "chat"))

    async def test_spotify_setup_does_not_claim_account_verified_after_rate_limit(self) -> None:
        ui = FakeUI()
        session = ws_runner.SpotifySetupSession(ui)
        message = (
            "Spotify says Too Many Requests. Requests are too frequent; try again later. "
            "Try again after 30 seconds."
        )
        account = {
            "status": "fail",
            "message": message,
            "error_code": "SPOTIFY_RATE_LIMITED",
            "data": {"retry_after": "30 seconds"},
        }

        with patch(
            "src.api.ws_runner._spotify_loopback_login_for_tui",
            return_value=account,
        ), patch("src.api.ws_runner.asyncio.to_thread", side_effect=_to_thread_inline):
            await session._finish_oauth("https://accounts.spotify.com/authorize", "state")

        activities = [event for event in ui.events if event.get("type") == "activity"]
        setup_events = [event for event in ui.events if event.get("type") == "spotify_setup"]
        self.assertEqual(activities[-1]["title"], "Spotify verification pending")
        self.assertEqual(activities[-1]["status"], "error")
        self.assertIn("authorization was saved", str(activities[-1]["detail"]))
        self.assertIn(message, str(activities[-1]["detail"]))
        self.assertEqual(setup_events[-1]["title"], "Spotify authorized; verification pending")
        self.assertNotIn("Account product: unknown", str(setup_events[-1]["message"]))

    async def test_spotify_command_reports_pending_before_account_check_returns(self) -> None:
        runner = WebSocketRunner()
        runner._run_agent_turn = AsyncMock()
        ui = FakeUI()

        async def blocked_to_thread(fn, /, *args, **kwargs):
            await asyncio.sleep(30)

        with patch("src.api.ws_runner.asyncio.to_thread", side_effect=blocked_to_thread):
            task = asyncio.create_task(runner._handle_user_input(ui, "/spotify"))
            await asyncio.sleep(0)
            try:
                self.assertTrue(
                    any(
                        event.get("type") == "activity"
                        and event.get("status") == "pending"
                        and "Checking Spotify account" in str(event.get("detail"))
                        for event in ui.events
                    )
                )
            finally:
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task

    async def test_spotify_command_times_out_account_check_with_visible_error(self) -> None:
        runner = WebSocketRunner()
        runner._run_agent_turn = AsyncMock()
        ui = FakeUI()

        async def blocked_to_thread(fn, /, *args, **kwargs):
            await asyncio.sleep(30)

        with patch("src.api.ws_runner.SPOTIFY_MODE_CALL_TIMEOUT_SECONDS", 0.01), \
             patch("src.api.ws_runner.asyncio.to_thread", side_effect=blocked_to_thread):
            await runner._handle_user_input(ui, "/spotify")

        self.assertFalse(runner._run_agent_turn.called)
        self.assertIsNone(getattr(ui, "_spotify_mode", None))
        self.assertTrue(
            any(
                event.get("type") == "activity"
                and event.get("status") == "error"
                and "Spotify did not respond while checking your account" in str(event.get("detail"))
                for event in ui.events
            )
        )
        self.assertTrue(
            any(
                event.get("type") == "chat"
                and "Spotify did not respond while checking your account" in str(event.get("text"))
                for event in ui.events
            )
        )

    async def test_spotify_command_starts_reauth_when_scopes_are_missing(self) -> None:
        runner = WebSocketRunner()
        runner._run_agent_turn = AsyncMock()
        ui = FakeUI()

        with patch("src.api.ws_runner.spotify_account", return_value={
            "status": "success",
            "data": {
                "logged_in": True,
                "product": "premium",
                "scopes": [
                    "user-read-private",
                    "user-read-playback-state",
                    "user-modify-playback-state",
                ],
                "capabilities": {"playback_control": True, "current_playback": True, "playlist_read": False},
            },
        }), patch("src.api.ws_runner.spotify_devices") as devices, \
             patch("src.api.ws_runner.spotify_redirect_uri", return_value="http://127.0.0.1:9957/callback"), \
             patch("src.api.ws_runner.spotify_authorize_url", return_value=("https://accounts.spotify.com/authorize", "state")), \
             patch("src.api.ws_runner.SpotifySetupSession._finish_oauth", new_callable=AsyncMock), \
             patch("src.api.ws_runner.asyncio.to_thread", side_effect=_to_thread_inline):
            await runner._handle_user_input(ui, "/spotify")

        devices.assert_not_called()
        self.assertFalse(runner._run_agent_turn.called)
        self.assertIsNone(getattr(ui, "_spotify_mode", None))
        self.assertTrue(getattr(ui, "_spotify_setup"))
        spotify_setup_events = [event for event in ui.events if event.get("type") == "spotify_setup"]
        self.assertTrue(spotify_setup_events)
        self.assertEqual(spotify_setup_events[-1]["step"], "oauth")
        messages = [str(event.get("text")) for event in ui.events if event.get("type") == "chat"]
        self.assertTrue(any("Spotify authorization must be renewed" in message for message in messages))
        self.assertTrue(any("playlist-read-private" in message for message in messages))
        self.assertTrue(any("playlist-read-collaborative" in message for message in messages))
        self.assertTrue(any("user-library-read" in message for message in messages))

    async def test_spotify_command_asks_for_inactive_device_choice(self) -> None:
        runner = WebSocketRunner()
        ui = FakeUI()

        with patch("src.api.ws_runner.spotify_account", return_value={
            "status": "success",
            "data": {
                "logged_in": True,
                "product": "premium",
                "scopes": [
                    "user-read-private",
                    "user-read-playback-state",
                    "user-modify-playback-state",
                    "playlist-read-private",
                    "playlist-read-collaborative",
                    "user-library-read",
                ],
                "capabilities": {"playback_control": True, "current_playback": True, "playlist_read": True, "library_read": True},
            },
        }), patch("src.api.ws_runner.spotify_devices", return_value={
            "status": "success",
            "data": {"devices": [{"id": "desktop", "name": "Studio Desktop", "type": "Computer", "is_active": False}]},
        }), patch("src.api.ws_runner.asyncio.to_thread", side_effect=_to_thread_inline):
            await runner._handle_user_input(ui, "/spotify")

        self.assertIsNone(getattr(ui, "_spotify_mode", None))
        confirm = [event for event in ui.events if event.get("tool_name") == "spotify_device"][-1]
        self.assertEqual(confirm["choices"][0]["value"], "spotify_device:desktop")
        self.assertIn("Studio Desktop", confirm["choices"][0]["label"])

        session = getattr(ui, "_spotify_device_selection")
        await session.handle_choice("spotify_device:desktop")
        mode = getattr(ui, "_spotify_mode")
        self.assertTrue(mode["enabled"])
        self.assertEqual(mode["device_id"], "desktop")
        self.assertEqual(mode["device_name"], "Studio Desktop")
        mode_events = [event for event in ui.events if event.get("type") == "spotify_mode"]
        self.assertTrue(mode_events)
        self.assertTrue(mode_events[-1]["enabled"])
        self.assertEqual(mode_events[-1]["device_name"], "Studio Desktop")

    async def test_spotify_command_persists_active_device_mode(self) -> None:
        runner = WebSocketRunner()
        ui = FakeUI()

        with self._isolated_auth_env(), \
             patch("src.api.ws_runner.spotify_account", return_value={
                 "status": "success",
                 "data": {
                     "logged_in": True,
                     "product": "premium",
                     "scopes": sorted(ws_runner.SPOTIFY_MODE_REQUIRED_SCOPES),
                     "capabilities": {"playback_control": True, "current_playback": True, "playlist_read": True, "library_read": True},
                 },
             }), patch("src.api.ws_runner.spotify_devices", return_value={
                 "status": "success",
                 "data": {"devices": [{"id": "desktop", "name": "Studio Desktop", "type": "Computer", "is_active": True}]},
             }), patch("src.api.ws_runner.asyncio.to_thread", side_effect=_to_thread_inline):
            await runner._handle_user_input(ui, "/spotify")
            saved = json.loads((Path(os.environ["SONEX_HOME"]) / "spotify-mode.json").read_text(encoding="utf-8"))

        self.assertTrue(saved["enabled"])
        self.assertEqual(saved["device_id"], "desktop")
        self.assertEqual(saved["device_name"], "Studio Desktop")
        self.assertEqual(saved["scopes"], sorted(ws_runner.SPOTIFY_MODE_REQUIRED_SCOPES))
        self.assertIn("updated_at", saved)

    async def test_spotify_device_choice_persists_selected_mode(self) -> None:
        ui = FakeUI()
        session = ws_runner.SpotifyDeviceSelectionSession(
            ui,
            [{"id": "desktop", "name": "Studio Desktop", "type": "Computer", "is_active": False}],
        )

        with self._isolated_auth_env():
            await session.handle_choice("spotify_device:desktop")
            saved = json.loads((Path(os.environ["SONEX_HOME"]) / "spotify-mode.json").read_text(encoding="utf-8"))

        self.assertTrue(saved["enabled"])
        self.assertEqual(saved["device_id"], "desktop")
        self.assertEqual(saved["device_name"], "Studio Desktop")

    async def test_startup_restores_spotify_mode_from_local_token_without_api_preflight(self) -> None:
        runner = WebSocketRunner()
        ui = FakeUI()
        expires_at = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat().replace("+00:00", "Z")
        token = OAuthToken(access_token="access", expires_at=expires_at, scopes=sorted(ws_runner.SPOTIFY_MODE_REQUIRED_SCOPES))

        with self._isolated_auth_env():
            path = Path(os.environ["SONEX_HOME"]) / "spotify-mode.json"
            path.write_text(json.dumps({
                "version": 1,
                "enabled": True,
                "device_id": "desktop",
                "device_name": "Studio Desktop",
                "entered_at": 1,
                "updated_at": 2,
                "token_expires_at": expires_at,
                "scopes": sorted(ws_runner.SPOTIFY_MODE_REQUIRED_SCOPES),
            }), encoding="utf-8")
            with patch("src.api.ws_runner.load_spotify_token", return_value=token), \
                 patch("src.api.ws_runner.spotify_account") as account, \
                 patch("src.api.ws_runner.spotify_devices") as devices:
                await runner._restore_persistent_spotify_mode(ui)

        account.assert_not_called()
        devices.assert_not_called()
        self.assertTrue(getattr(ui, "_spotify_mode")["enabled"])
        self.assertEqual(getattr(ui, "_spotify_mode")["device_name"], "Studio Desktop")
        self.assertTrue([event for event in ui.events if event.get("type") == "spotify_mode" and event.get("enabled")])

    async def test_startup_clears_expired_spotify_mode(self) -> None:
        runner = WebSocketRunner()
        ui = FakeUI()
        expired_at = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
        token = OAuthToken(access_token="access", expires_at=expired_at, scopes=sorted(ws_runner.SPOTIFY_MODE_REQUIRED_SCOPES))

        with self._isolated_auth_env():
            path = Path(os.environ["SONEX_HOME"]) / "spotify-mode.json"
            path.write_text(json.dumps({"version": 1, "enabled": True, "device_id": "desktop"}), encoding="utf-8")
            with patch("src.api.ws_runner.load_spotify_token", return_value=token):
                await runner._restore_persistent_spotify_mode(ui)
            self.assertFalse(path.exists())

        self.assertIsNone(getattr(ui, "_spotify_mode", None))

    async def test_startup_clears_corrupt_spotify_mode(self) -> None:
        runner = WebSocketRunner()
        ui = FakeUI()

        with self._isolated_auth_env():
            path = Path(os.environ["SONEX_HOME"]) / "spotify-mode.json"
            path.write_text("{", encoding="utf-8")
            await runner._restore_persistent_spotify_mode(ui)
            self.assertFalse(path.exists())

        self.assertIsNone(getattr(ui, "_spotify_mode", None))

    async def test_spotify_command_is_not_available_inside_spotify_mode(self) -> None:
        runner = WebSocketRunner()
        runner._run_agent_turn = AsyncMock()
        ui = FakeUI()
        setattr(ui, "_spotify_mode", {"enabled": True, "device_id": "desktop", "device_name": "Studio Desktop"})

        with self._isolated_auth_env():
            path = Path(os.environ["SONEX_HOME"]) / "spotify-mode.json"
            path.write_text(json.dumps({"version": 1, "enabled": True}), encoding="utf-8")
            await runner._handle_user_input(ui, "/spotify")
            self.assertTrue(path.exists())

        self.assertFalse(runner._run_agent_turn.called)
        self.assertTrue(getattr(ui, "_spotify_mode")["enabled"])
        self.assertTrue(any("not available in Spotify mode" in str(event.get("text")) for event in ui.events))

    async def test_spotify_off_is_not_available_inside_spotify_mode(self) -> None:
        runner = WebSocketRunner()
        ui = FakeUI()
        setattr(ui, "_spotify_mode", {"enabled": True, "device_id": "desktop", "device_name": "Studio Desktop"})

        with self._isolated_auth_env():
            path = Path(os.environ["SONEX_HOME"]) / "spotify-mode.json"
            path.write_text(json.dumps({"version": 1, "enabled": True}), encoding="utf-8")
            await runner._handle_user_input(ui, "/spotify off")
            self.assertTrue(path.exists())

        self.assertTrue(getattr(ui, "_spotify_mode")["enabled"])
        self.assertTrue(any("not available in Spotify mode" in str(event.get("text")) for event in ui.events))

    async def test_keymap_command_is_reported_as_tui_handled(self) -> None:
        runner = WebSocketRunner()
        runner._run_agent_turn = AsyncMock()
        ui = FakeUI()

        await runner._handle_user_input(ui, "/keymap status")

        self.assertFalse(runner._run_agent_turn.called)
        self.assertTrue(any("handled by the TUI" in str(event.get("text")) for event in ui.events))

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
        command_messages = [
            event for event in ui.events
            if "Unknown command" in str(event.get("text"))
        ]
        self.assertTrue(command_messages)
        self.assertEqual(command_messages[-1].get("tone"), "system")

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

    async def test_exit_saves_transcript_and_does_not_trigger_agent(self) -> None:
        """Verifies that exit saves transcript and does not trigger agent behaves as expected.

        Typical use: Use this in automated tests when guarding the exit saves transcript and does not trigger agent behavior against regressions.

        Example: test_exit_saves_transcript_and_does_not_trigger_agent() -> passes without assertion failures when the behavior remains correct.
        """
        runner = WebSocketRunner()
        runner._run_agent_turn = AsyncMock()
        ui = FakeUI()

        with tempfile.TemporaryDirectory() as home, patch.dict("os.environ", {"SONEX_HOME": home}):
            await runner._handle_user_input(ui, "/exit")

            transcripts = list((Path(home) / "sessions").glob("*/transcript.jsonl"))
            self.assertEqual(len(transcripts), 1)
            payload = _read_jsonl(transcripts[0])

        self.assertFalse(runner._run_agent_turn.called)
        self.assertFalse([event for event in ui.events if event.get("type") == "auth_setup"])
        self.assertTrue(all(item["reason"] == "exit" for item in payload))
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
            set_default("openai", model="gpt-5.5")

            await runner._handle_user_input(ui, "/logout")

            store = load_auth_store()
            transcripts = list((Path(home) / "sessions").glob("*/transcript.jsonl"))
            self.assertEqual(len(transcripts), 1)
            payload = _read_jsonl(transcripts[0])

        self.assertFalse(runner._run_agent_turn.called)
        self.assertIn("openai", store.providers)
        self.assertIsNone(store.providers["openai"].api_key)
        self.assertIsNone(store.default_provider)
        self.assertIsNone(store.default_provider)
        self.assertIsNone(store.default_model)
        self.assertTrue(all(item["reason"] == "logout" for item in payload))
        self.assertTrue(any(event.get("type") == "bye" for event in ui.events))
        self.assertTrue(any(
            event.get("text")
            == "Signed out of the active LLM connection. Other saved provider credentials were preserved."
            for event in ui.events
        ))

    async def test_logout_clears_spotify_mode_before_next_startup(self) -> None:
        runner = WebSocketRunner()
        ui = FakeUI()
        expires_at = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat().replace("+00:00", "Z")
        token = OAuthToken(
            access_token="access",
            expires_at=expires_at,
            scopes=sorted(ws_runner.SPOTIFY_MODE_REQUIRED_SCOPES),
        )
        mode = {
            "version": 1,
            "enabled": True,
            "device_id": "desktop",
            "device_name": "Studio Desktop",
            "entered_at": 1,
            "updated_at": 2,
            "token_expires_at": expires_at,
            "scopes": sorted(ws_runner.SPOTIFY_MODE_REQUIRED_SCOPES),
        }

        with self._isolated_auth_env({"SONEX_DEFAULT_PROVIDER": "openai"}) as home:
            set_api_key("openai", "sk-test")
            set_default("openai", model="gpt-5.5")
            setattr(ui, "_spotify_mode", mode)
            await runner.provider_modes.restore(
                ws_runner.ProviderModeState(provider=ws_runner.ProviderMode.SPOTIFY)
            )
            spotify_mode_path = Path(home) / "spotify-mode.json"
            spotify_mode_path.write_text(json.dumps(mode), encoding="utf-8")
            ws_runner.save_provider_mode_intent(
                ws_runner.ProviderModeState(provider=ws_runner.ProviderMode.SPOTIFY)
            )

            await runner._handle_user_input(ui, "/logout")

            restarted_runner = WebSocketRunner()
            restarted_ui = FakeUI()
            with patch("src.api.ws_runner.load_spotify_token", return_value=token):
                await restarted_runner._restore_persistent_spotify_mode(restarted_ui)
                await restarted_runner._restore_provider_mode(restarted_ui)

            provider_events = [
                event for event in restarted_ui.events
                if event.get("type") == "provider_mode"
            ]
            logout_spotify_events = [
                event for event in ui.events
                if event.get("type") == "spotify_mode"
            ]
            logout_provider_events = [
                event for event in ui.events
                if event.get("type") == "provider_mode"
            ]
            self.assertEqual(
                {
                    "logout_spotify_enabled": runner._spotify_mode_enabled(ui),
                    "logout_provider": runner.provider_modes.state.provider.value,
                    "logout_spotify_event": logout_spotify_events[-1]["enabled"],
                    "logout_provider_event": logout_provider_events[-1]["provider"],
                    "spotify_mode_file": spotify_mode_path.exists(),
                    "provider_mode_file": (Path(home) / "provider-mode.json").exists(),
                    "restart_spotify_enabled": restarted_runner._spotify_mode_enabled(restarted_ui),
                    "restart_provider": restarted_runner.provider_modes.state.provider.value,
                    "restart_event": provider_events[-1]["provider"],
                },
                {
                    "logout_spotify_enabled": False,
                    "logout_provider": "normal",
                    "logout_spotify_event": False,
                    "logout_provider_event": "normal",
                    "spotify_mode_file": False,
                    "provider_mode_file": False,
                    "restart_spotify_enabled": False,
                    "restart_provider": "normal",
                    "restart_event": "normal",
                },
            )

    async def test_logout_clears_apple_mode_state(self) -> None:
        runner = WebSocketRunner()
        ui = FakeUI()

        with self._isolated_auth_env({"SONEX_DEFAULT_PROVIDER": "openai"}) as home:
            set_api_key("openai", "sk-test")
            set_default("openai", model="gpt-5.5")
            setattr(
                ui,
                "_apple_mode",
                {
                    "enabled": True,
                    "storefront": "us",
                    "connection_status": "ready",
                },
            )
            await runner.provider_modes.restore(
                ws_runner.ProviderModeState(provider=ws_runner.ProviderMode.APPLE)
            )
            ws_runner.save_provider_mode_intent(
                ws_runner.ProviderModeState(provider=ws_runner.ProviderMode.APPLE)
            )

            await runner._handle_user_input(ui, "/logout")

            self.assertIsNone(getattr(ui, "_apple_mode", None))
            self.assertEqual(runner.provider_modes.state.provider, ws_runner.ProviderMode.NORMAL)
            self.assertFalse((Path(home) / "provider-mode.json").exists())

        provider_events = [
            event for event in ui.events
            if event.get("type") == "provider_mode"
        ]
        self.assertEqual(provider_events[-1]["provider"], "normal")

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
        self.assertFalse(any(event.get("text") == "Signed out successfully." for event in ui.events))

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

    async def test_recommend_queues_visible_recommendations_without_agent_turn(self) -> None:
        runner = WebSocketRunner()
        runner._run_agent_turn = AsyncMock()
        ui = FakeUI()
        spotify_tracks = [
            {"name": "七里香", "artist": "周杰伦", "uri": "spotify:track:1", "recommendation_reason": "recent match"},
            {"name": "晴天", "artist": "周杰伦", "uri": "spotify:track:2", "recommendation_reason": "same mood"},
            {"name": "重复", "artist": "A", "uri": "spotify:track:dup"},
        ]
        apple_tracks = [
            {"name": "重复", "artist": "A", "url": "https://music.apple.com/dup"},
            {"name": "倒带", "artist": "蔡依林", "url": "https://music.apple.com/1", "recommendation_reason": "pop fit"},
            {"name": "红色高跟鞋", "artist": "蔡健雅", "url": "https://music.apple.com/2"},
            {"name": "如果云知道", "artist": "许茹芸", "url": "https://music.apple.com/3"},
        ]

        with patch("src.api.ws_runner.spotify_recommend", return_value={
            "status": "success",
            "data": {"tracks": spotify_tracks},
        }) as spotify_recommend, patch("src.api.ws_runner.apple_music_recommend", return_value={
            "status": "success",
            "data": {"tracks": apple_tracks},
        }) as apple_recommend, patch("src.api.ws_runner.playback_queue_snapshot", return_value=[
            {"name": "稻香", "artist": "周杰伦"}
        ]), patch("src.api.ws_runner.remember_playback_track", side_effect=lambda track: [track]) as remember, patch(
            "src.api.ws_runner.asyncio.to_thread",
            side_effect=_to_thread_inline,
        ):
            await runner._handle_user_input(ui, "/recommend 华语女声")
            self.assertIsNotNone(runner._running_task)
            assert runner._running_task is not None
            await runner._running_task

        self.assertFalse(runner._run_agent_turn.called)
        spotify_recommend.assert_called_once_with(query="华语女声", limit=5, recent_tracks=[{"name": "稻香", "artist": "周杰伦"}])
        apple_recommend.assert_called_once_with(query="华语女声", limit=5, recent_tracks=[{"name": "稻香", "artist": "周杰伦"}])
        self.assertEqual(remember.call_count, 5)
        saved = getattr(ui, "_last_recommendation_tracks")
        self.assertEqual([track["name"] for track in saved], ["七里香", "晴天", "重复", "倒带", "红色高跟鞋"])
        self.assertTrue(any(event.get("type") == "search_results" for event in ui.events))
        self.assertTrue(any(event.get("type") == "queue" for event in ui.events))
        chat = [event for event in ui.events if event.get("type") == "chat" and event.get("role") == "agent"][-1]
        self.assertIn('Recommended 5 tracks for "华语女声"', str(chat.get("text")))
        self.assertIn("1. 七里香 - 周杰伦: recent match", str(chat.get("text")))
        self.assertFalse(any(event.get("type") == "player" for event in ui.events))

    async def test_recommend_without_args_uses_empty_query_intro(self) -> None:
        runner = WebSocketRunner()
        runner._run_agent_turn = AsyncMock()
        ui = FakeUI()
        track = {"name": "Song", "artist": "Artist", "uri": "spotify:track:1"}

        with patch("src.api.ws_runner.spotify_recommend", return_value={"status": "success", "data": {"tracks": [track]}}) as spotify_recommend, patch(
            "src.api.ws_runner.apple_music_recommend",
            return_value={"status": "success", "data": {"tracks": []}},
        ), patch("src.api.ws_runner.playback_queue_snapshot", return_value=[]), patch(
            "src.api.ws_runner.remember_playback_track",
            return_value=[track],
        ), patch("src.api.ws_runner.asyncio.to_thread", side_effect=_to_thread_inline):
            await runner._handle_user_input(ui, "/recommend")
            self.assertIsNotNone(runner._running_task)
            assert runner._running_task is not None
            await runner._running_task

        spotify_recommend.assert_called_once_with(query="", limit=5, recent_tracks=[])
        chat = [event for event in ui.events if event.get("type") == "chat" and event.get("role") == "agent"][-1]
        self.assertIn("Recommended 1 track based on recent playback and USER.md", str(chat.get("text")))

    async def test_recommend_uses_other_provider_when_one_provider_fails(self) -> None:
        runner = WebSocketRunner()
        runner._run_agent_turn = AsyncMock()
        ui = FakeUI()
        track = {"name": "倒带", "artist": "蔡依林", "url": "https://music.apple.com/1"}

        with patch("src.api.ws_runner.spotify_recommend", side_effect=RuntimeError("spotify unavailable")), patch(
            "src.api.ws_runner.apple_music_recommend",
            return_value={"status": "success", "data": {"tracks": [track]}},
        ), patch("src.api.ws_runner.playback_queue_snapshot", return_value=[]), patch(
            "src.api.ws_runner.remember_playback_track",
            return_value=[track],
        ), patch("src.api.ws_runner.asyncio.to_thread", side_effect=_to_thread_inline):
            await runner._handle_user_input(ui, "/recommend R&B")
            self.assertIsNotNone(runner._running_task)
            assert runner._running_task is not None
            await runner._running_task

        self.assertFalse(runner._run_agent_turn.called)
        saved = getattr(ui, "_last_recommendation_tracks")
        self.assertEqual([item["name"] for item in saved], ["倒带"])
        self.assertTrue(any(event.get("type") == "search_results" for event in ui.events))
        self.assertTrue(any('Recommended 1 track for "R&B"' in str(event.get("text")) for event in ui.events))

    async def test_recommend_returns_immediately_while_providers_load(self) -> None:
        runner = WebSocketRunner()
        runner._run_agent_turn = AsyncMock()
        ui = FakeUI()

        async def never_returns(*_args, **_kwargs):
            await asyncio.sleep(10)

        with (
            patch("src.api.ws_runner.asyncio.to_thread", side_effect=never_returns),
            patch("src.api.ws_runner.playback_queue_snapshot", return_value=[]),
            patch("src.api.ws_runner.RECOMMEND_COMMAND_TIMEOUT_SECONDS", 0.001),
        ):
            await asyncio.wait_for(runner._handle_user_input(ui, "/recommend"), timeout=0.05)
            self.assertIsNotNone(runner._running_task)
            assert runner._running_task is not None
            await runner._running_task
            self.assertTrue(
                any(
                    event.get("type") == "input_state"
                    and event.get("disabled") is True
                    and event.get("reason") == "recommendation"
                    for event in ui.events
                )
            )

        self.assertFalse(runner._run_agent_turn.called)
        self.assertTrue(any(event.get("type") == "activity" and event.get("title") == "Recommendations" for event in ui.events))
        self.assertTrue(any("Recommendations timed out after 60 seconds" in str(event.get("detail")) for event in ui.events))
        self.assertTrue(any("Recommendations timed out after 60 seconds" in str(event.get("text")) for event in ui.events))
        self.assertIsNone(runner._running_task)
        self.assertTrue(
            any(
                event.get("type") == "input_state"
                and event.get("disabled") is False
                and event.get("reason") == "recommendation"
                for event in ui.events
            )
        )

    async def test_spotify_mode_recommend_timeout_covers_queue_add(self) -> None:
        runner = WebSocketRunner()
        ui = FakeUI()
        setattr(ui, "_spotify_mode", {"enabled": True, "device_id": "desktop", "device_name": "Studio Desktop"})
        track = {"name": "Blinding Lights", "artist": "The Weeknd", "uri": "spotify:track:1"}

        async def recommend_then_hang(func, *args, **kwargs):
            if func is spotify_recommend:
                return func(*args, **kwargs)
            await asyncio.sleep(10)

        with patch("src.api.ws_runner.spotify_recommend", return_value={
            "status": "success",
            "data": {"tracks": [track]},
        }) as spotify_recommend, patch(
            "src.api.ws_runner.spotify_queue_add",
            return_value={"status": "success", "message": "Added to Spotify queue."},
        ), patch(
            "src.api.ws_runner.asyncio.to_thread",
            side_effect=recommend_then_hang,
        ), patch(
            "src.api.ws_runner.RECOMMEND_COMMAND_TIMEOUT_SECONDS",
            0.001,
        ):
            await runner._handle_user_input(ui, "/recommend")
            self.assertIsNotNone(runner._running_task)
            assert runner._running_task is not None
            await runner._running_task

        self.assertTrue(any("Recommendations timed out after 60 seconds" in str(event.get("detail")) for event in ui.events))
        self.assertIsNone(runner._running_task)
        self.assertTrue(
            any(
                event.get("type") == "input_state"
                and event.get("disabled") is False
                and event.get("reason") == "recommendation"
                for event in ui.events
            )
        )

    async def test_search_slash_command_is_not_user_facing(self) -> None:
        """Verifies that search slash command is not user facing.

        Typical use: Use this in automated tests when guarding the public command surface against regressions.

        Example: test_search_slash_command_is_not_user_facing() -> passes without assertion failures when the behavior remains correct.
        """
        runner = WebSocketRunner()
        runner._run_agent_turn = AsyncMock()
        ui = FakeUI()

        with self._isolated_auth_env({"SONEX_DEFAULT_PROVIDER": "openai", "SONEX_OPENAI_API_KEY": "sk-test"}):
            await runner._handle_user_input(ui, "/search jay")
            await asyncio.sleep(0)

        self.assertFalse(runner._run_agent_turn.called)
        self.assertTrue(any(
            event.get("type") == "activity"
            and event.get("title") == "Unknown command"
            and "/search" in str(event.get("detail"))
            for event in ui.events
        ))

    async def test_play_number_starts_song_candidates_without_method_panel(self) -> None:
        """Verifies that play number starts play selection without agent turn behaves as expected.

        Typical use: Use this in automated tests when guarding the play number starts play selection without agent turn behavior against regressions.

        Example: test_play_number_starts_play_selection_without_agent_turn() -> passes without assertion failures when the behavior remains correct.
        """
        runner = WebSocketRunner()
        runner._run_agent_turn = AsyncMock()
        ui = FakeUI()

        metadata_result = {
            "candidates": [{"name": "Song 1", "artist": "Artist", "album": "Album"}],
            "source_attempts": [],
        }
        with patch("src.api.ws_runner.search_local_file", return_value="No local files found related to '1'."), \
             patch("src.api.ws_runner.search_track_metadata_candidates", return_value=metadata_result), \
             patch("src.api.ws_runner.asyncio.to_thread", side_effect=_to_thread_inline), \
             self._isolated_auth_env({"SONEX_DEFAULT_PROVIDER": "openai", "SONEX_OPENAI_API_KEY": "sk-test"}):
            await runner._handle_user_input(ui, "play 1")

        self.assertFalse(runner._run_agent_turn.called)
        confirm_events = [event for event in ui.events if event.get("type") == "confirm"]
        self.assertTrue(confirm_events)
        self.assertEqual(confirm_events[-1]["tool_name"], "song_candidate")
        self.assertEqual(
            confirm_events[-1]["message"],
            "Select the version to play",
        )
        self.assertEqual(confirm_events[-1]["tool_args"]["query"], "1")
        self.assertFalse(any(event.get("tool_args", {}).get("stage") == "method_choice" for event in confirm_events))

    async def test_play_local_match_can_skip_directly_to_song_candidates(self) -> None:
        """Verifies that skipping a local match bypasses playback method selection.

        Typical use: Use this in automated tests when guarding the play local match can skip to playback method choices behavior against regressions.

        Example: skipping the local match opens song candidates directly.
        """
        runner = WebSocketRunner()
        runner._run_agent_turn = AsyncMock()
        ui = FakeUI()

        metadata_result = {
            "candidates": [{"name": "Song", "artist": "Artist", "album": "Album"}],
            "source_attempts": [],
        }
        with patch("src.api.ws_runner.search_local_file", return_value="/home/user/Music/song.mp3"):
            await runner._handle_user_input(ui, "play song")

            first_confirm = [event for event in ui.events if event.get("type") == "confirm"][-1]
            self.assertIn("Play local file song.mp3", first_confirm["message"])
            self.assertEqual([choice["value"] for choice in first_confirm["choices"]], ["play_local", "skip_local", "cancel"])

            session = getattr(ui, "_play_selection")
            with patch("src.api.ws_runner.search_track_metadata_candidates", return_value=metadata_result), patch(
                "src.api.ws_runner.asyncio.to_thread",
                side_effect=_to_thread_inline,
            ):
                await session.handle_choice("skip_local")

        confirm_events = [event for event in ui.events if event.get("type") == "confirm"]
        self.assertEqual(confirm_events[-1]["tool_name"], "song_candidate")
        self.assertFalse(any(event.get("tool_args", {}).get("stage") == "method_choice" for event in confirm_events))

    async def test_normal_playback_does_not_probe_provider_accounts(self) -> None:
        runner = WebSocketRunner()
        ui = FakeUI()
        metadata_result = {
            "candidates": [{"name": "Song", "artist": "Artist", "album": "Album"}],
            "source_attempts": [],
        }
        with patch("src.api.ws_runner.search_local_file", return_value="No local files found."), \
             patch("src.api.ws_runner.search_track_metadata_candidates", return_value=metadata_result), \
             patch("src.api.ws_runner.spotify_account") as spotify_account_check, \
             patch("src.api.ws_runner.load_apple_music_user_token") as apple_music_account_check, \
             patch("src.api.ws_runner.asyncio.to_thread", side_effect=_to_thread_inline):
            await runner._handle_user_input(ui, "play song")

        spotify_account_check.assert_not_called()
        apple_music_account_check.assert_not_called()
        confirms = [event for event in ui.events if event.get("type") == "confirm"]
        self.assertEqual(confirms[-1]["tool_name"], "song_candidate")
        self.assertFalse(any(event.get("tool_args", {}).get("stage") == "method_choice" for event in confirms))

    async def test_explicit_natural_language_playback_starts_selection_session(self) -> None:
        """Verifies that explicit natural language playback starts selection session behaves as expected.

        Typical use: Use this in automated tests when guarding the explicit natural language playback starts selection session behavior against regressions.

        Example: test_explicit_natural_language_playback_starts_selection_session() -> passes without assertion failures when the behavior remains correct.
        """
        runner = WebSocketRunner()
        runner._run_agent_turn = AsyncMock()
        ui = FakeUI()

        with patch("src.api.ws_runner.search_local_file", return_value="No local files found related to '青花瓷'."), \
             patch("src.api.ws_runner.search_track_metadata_candidates", return_value=_metadata_result("青花瓷")), \
             patch("src.api.ws_runner.asyncio.to_thread", side_effect=_to_thread_inline):
            await runner._handle_user_input(ui, "播放 青花瓷")

        self.assertFalse(runner._run_agent_turn.called)
        confirm_events = [event for event in ui.events if event.get("type") == "confirm"]
        self.assertTrue(confirm_events)
        self.assertEqual(confirm_events[-1]["tool_args"]["query"], "青花瓷")
        self.assertEqual(confirm_events[-1]["tool_name"], "song_candidate")

    async def test_spotify_mode_playback_shows_spotify_track_candidates(self) -> None:
        runner = WebSocketRunner()
        runner._run_agent_turn = AsyncMock()
        ui = FakeUI()
        setattr(ui, "_spotify_mode", {"enabled": True, "device_id": "desktop", "device_name": "Studio Desktop"})
        tracks = [
            {
                "name": "青花瓷",
                "artist": "周杰伦",
                "album": "我很忙",
                "duration_ms": 239000,
                "uri": "spotify:track:qinghuaci",
            }
        ]

        with patch("src.api.ws_runner.search_spotify_track_candidates", return_value=tracks) as search, \
             patch("src.api.ws_runner.asyncio.to_thread", side_effect=_to_thread_inline), \
             patch("src.api.ws_runner.search_local_file") as local_search:
            await runner._start_spotify_track_selection(ui, "方大同的因为你")
            await runner._start_spotify_track_selection(ui, "  方大同的因为你  ")

        search.assert_called_once()
        self.assertEqual(search.call_args.args[:2], ("方大同的因为你", 5))
        self.assertEqual(search.call_args.kwargs["query_variants"][0], "track:因为你 artist:方大同")
        self.assertIn("因为你 方大同", search.call_args.kwargs["query_variants"])
        local_search.assert_not_called()
        self.assertFalse(runner._run_agent_turn.called)
        confirm = [event for event in ui.events if event.get("tool_name") == "spotify_track"][-1]
        self.assertEqual(confirm["choices"][0]["value"], "spotify_track:0")
        self.assertEqual(confirm["choices"][0]["display"], {
            "kind": "music_candidate",
            "artist": "周杰伦",
            "album": "我很忙",
            "title": "青花瓷",
        })
        self.assertEqual(confirm["choices"][0]["label"], f"{'周杰伦'.ljust(24)} {'我很忙'.ljust(24)} 青花瓷")
        self.assertEqual(confirm["choices"][0]["description"], "")

    async def test_spotify_mode_track_choice_plays_selected_uri_on_device(self) -> None:
        runner = WebSocketRunner()
        ui = FakeUI()
        setattr(ui, "_spotify_mode", {"enabled": True, "device_id": "desktop", "device_name": "Studio Desktop"})
        tracks = [
            {
                "name": "青花瓷",
                "artist": "周杰伦",
                "album": "我很忙",
                "duration_ms": 239000,
                "uri": "spotify:track:qinghuaci",
            }
        ]

        with patch("src.api.ws_runner.search_spotify_track_candidates", return_value=tracks), \
             patch("src.api.ws_runner.asyncio.to_thread", side_effect=_to_thread_inline):
            await runner._handle_user_input(ui, "播放 青花瓷")

        session = getattr(ui, "_spotify_play_selection")
        with patch("src.api.ws_runner.registry.invoke", return_value={
            "status": "success",
            "tool": "spotify_play",
            "message": "Spotify playback started.",
            "data": {**tracks[0], "is_playing": True, "provider": "spotify", "progress_ms": 0, "timestamp": 1000},
        }) as invoke, patch("src.api.ws_runner.asyncio.to_thread", side_effect=_to_thread_inline):
            await session.handle_choice("spotify_track:0")

        invoke.assert_called_once_with("spotify_play", {"uri": "spotify:track:qinghuaci", "device_id": "desktop"})
        self.assertIsNone(getattr(ui, "_spotify_play_selection", None))
        self.assertTrue(any(event.get("type") == "player" for event in ui.events))
        self.assertTrue(getattr(ui, "_spotify_sync_event").is_set())

    async def test_spotify_mode_recommend_queues_spotify_tracks_without_agent_turn(self) -> None:
        runner = WebSocketRunner()
        runner._run_agent_turn = AsyncMock()
        ui = FakeUI()
        setattr(ui, "_spotify_mode", {"enabled": True, "device_id": "desktop", "device_name": "Studio Desktop"})
        tracks = [
            {"name": "Blinding Lights", "artist": "The Weeknd", "uri": "spotify:track:1"},
            {"name": "Levitating", "artist": "Dua Lipa", "uri": "spotify:track:2"},
        ]

        with patch("src.api.ws_runner.spotify_recommend", return_value={
            "status": "success",
            "data": {"tracks": tracks},
        }) as spotify_recommend, patch("src.api.ws_runner.spotify_queue_add", return_value={
            "status": "success",
            "message": "Added to Spotify queue.",
        }) as queue_add, patch("src.api.ws_runner.spotify_queue", return_value={
            "status": "success",
            "data": {"tracks": tracks},
        }) as spotify_queue, patch("src.api.ws_runner.playback_queue_snapshot", return_value=[]), patch(
            "src.api.ws_runner.remember_playback_track"
        ) as remember, patch("src.api.ws_runner.asyncio.to_thread", side_effect=_to_thread_inline):
            await runner._handle_user_input(ui, "/recommend 华语女声")
            self.assertIsNotNone(runner._running_task)
            assert runner._running_task is not None
            await runner._running_task

        self.assertFalse(runner._run_agent_turn.called)
        spotify_recommend.assert_called_once_with(query="华语女声", limit=5, recent_tracks=[])
        self.assertEqual(queue_add.call_args_list[0].args, ("spotify:track:1",))
        self.assertEqual(queue_add.call_args_list[0].kwargs, {"device_id": "desktop"})
        self.assertEqual(queue_add.call_args_list[1].args, ("spotify:track:2",))
        spotify_queue.assert_called_once_with(50)
        remember.assert_not_called()
        self.assertTrue(any(event.get("type") == "track_panel" and event.get("title") == "Spotify Queue" for event in ui.events))
        self.assertFalse(any(event.get("type") == "player" for event in ui.events))

    async def test_spotify_mode_recommend_queue_failure_is_visible(self) -> None:
        runner = WebSocketRunner()
        runner._run_agent_turn = AsyncMock()
        ui = FakeUI()
        setattr(ui, "_spotify_mode", {"enabled": True, "device_id": "desktop", "device_name": "Studio Desktop"})
        track = {"name": "Blinding Lights", "artist": "The Weeknd", "uri": "spotify:track:1"}

        with patch("src.api.ws_runner.spotify_recommend", return_value={
            "status": "success",
            "data": {"tracks": [track]},
        }), patch("src.api.ws_runner.spotify_queue_add", return_value={
            "status": "fail",
            "message": "No active Spotify device found.",
            "error_code": "SPOTIFY_DEVICE_REQUIRED",
        }), patch("src.api.ws_runner.spotify_queue") as spotify_queue, patch("src.api.ws_runner.playback_queue_snapshot", return_value=[]), patch(
            "src.api.ws_runner.asyncio.to_thread",
            side_effect=_to_thread_inline,
        ):
            await runner._handle_user_input(ui, "/recommend")
            self.assertIsNotNone(runner._running_task)
            assert runner._running_task is not None
            await runner._running_task

        spotify_queue.assert_not_called()
        self.assertTrue(any("No active Spotify device found." in str(event.get("text")) for event in ui.events))
        self.assertTrue(any(event.get("type") == "search_results" for event in ui.events))

    async def test_spotify_mode_random_plays_random_recent_track_without_agent_turn(self) -> None:
        runner = WebSocketRunner()
        runner._run_agent_turn = AsyncMock()
        ui = FakeUI()
        setattr(ui, "_spotify_mode", {"enabled": True, "device_id": "desktop", "device_name": "Studio Desktop"})
        recent_tracks = [
            {"name": "Missing URI", "artist": "Artist"},
            {"name": "Recent One", "artist": "Artist", "uri": "spotify:track:one"},
            {"name": "Duplicate", "artist": "Artist", "uri": "spotify:track:one"},
            {"name": "Recent Two", "artist": "Artist", "uri": "spotify:track:two"},
            {"name": "Episode", "artist": "Host", "uri": "spotify:episode:one"},
        ]
        play_result = {
            "status": "success",
            "tool": "spotify_play",
            "message": "Spotify playback started.",
            "data": {
                "provider": "spotify",
                "source": "spotify",
                "uri": "spotify:track:two",
                "name": "Recent Two",
                "artist": "Artist",
                "duration_ms": 180000,
                "progress_ms": 0,
                "timestamp": 1000,
                "is_playing": True,
            },
        }

        with (
            patch("src.api.ws_runner.spotify_recent_tracks", return_value={
                "status": "success",
                "data": {"tracks": recent_tracks},
            }) as recent,
            patch("src.api.ws_runner.random.choice", return_value=recent_tracks[3]) as choice,
            patch("src.api.ws_runner.registry.invoke", return_value=play_result) as invoke,
            patch("src.api.ws_runner._llm_auth_ready", return_value=(False, "openai", "missing")) as llm_auth,
            patch("src.api.ws_runner.asyncio.to_thread", side_effect=_to_thread_inline),
        ):
            for _ in range(2):
                await runner._handle_user_input(ui, "/random")
                self.assertIsNotNone(runner._running_task)
                assert runner._running_task is not None
                await runner._running_task

        recent.assert_called_once_with(50)
        self.assertEqual(choice.call_count, 2)
        self.assertEqual([track["uri"] for track in choice.call_args.args[0]], ["spotify:track:one", "spotify:track:two"])
        self.assertEqual(invoke.call_count, 2)
        invoke.assert_called_with("spotify_play", {"uri": "spotify:track:two", "device_id": "desktop"})
        llm_auth.assert_not_called()
        self.assertFalse(runner._run_agent_turn.called)
        self.assertFalse([event for event in ui.events if event.get("type") == "auth_setup"])
        player_events = [event for event in ui.events if event.get("type") == "player"]
        self.assertTrue(player_events)

    async def test_spotify_mode_random_returns_immediately_while_recent_tracks_load(self) -> None:
        runner = WebSocketRunner()
        runner._run_agent_turn = AsyncMock()
        ui = FakeUI()
        setattr(ui, "_spotify_mode", {"enabled": True, "device_id": "desktop", "device_name": "Studio Desktop"})

        async def never_returns(*_args, **_kwargs):
            await asyncio.sleep(10)

        with (
            patch("src.api.ws_runner.asyncio.to_thread", side_effect=never_returns),
            patch("src.api.ws_runner.SPOTIFY_MODE_CALL_TIMEOUT_SECONDS", 0.001),
        ):
            await asyncio.wait_for(runner._handle_user_input(ui, "/random"), timeout=0.05)
            self.assertIsNotNone(runner._running_task)
            assert runner._running_task is not None
            await runner._running_task

        self.assertTrue(any("Choosing from recently played Spotify tracks" in str(event.get("detail")) for event in ui.events))
        self.assertTrue(any("Spotify recent tracks timed out" in str(event.get("text")) for event in ui.events))

    async def test_spotify_mode_random_reports_empty_recent_tracks_without_playing(self) -> None:
        runner = WebSocketRunner()
        runner._run_agent_turn = AsyncMock()
        ui = FakeUI()
        setattr(ui, "_spotify_mode", {"enabled": True, "device_id": "desktop", "device_name": "Studio Desktop"})

        with (
            patch("src.api.ws_runner.spotify_recent_tracks", return_value={
                "status": "success",
                "data": {"tracks": [{"name": "Episode", "uri": "spotify:episode:one"}, {"name": "No URI"}]},
            }) as recent,
            patch("src.api.ws_runner.registry.invoke") as invoke,
            patch("src.api.ws_runner.asyncio.to_thread", side_effect=_to_thread_inline),
        ):
            await runner._handle_user_input(ui, "/random")
            self.assertIsNotNone(runner._running_task)
            assert runner._running_task is not None
            await runner._running_task

        recent.assert_called_once_with(50)
        invoke.assert_not_called()
        self.assertFalse(runner._run_agent_turn.called)
        self.assertTrue(any("recently played Spotify tracks" in str(event.get("text")) for event in ui.events))

    async def test_spotify_mode_random_reports_recent_tracks_failure_without_agent_turn(self) -> None:
        runner = WebSocketRunner()
        runner._run_agent_turn = AsyncMock()
        ui = FakeUI()
        setattr(ui, "_spotify_mode", {"enabled": True, "device_id": "desktop", "device_name": "Studio Desktop"})

        with (
            patch("src.api.ws_runner.spotify_recent_tracks", return_value={
                "status": "fail",
                "message": "Spotify recently played scope is missing. Open /spotify to reconnect.",
                "error_code": "SPOTIFY_SCOPE_MISSING",
            }),
            patch("src.api.ws_runner.registry.invoke") as invoke,
            patch("src.api.ws_runner._llm_auth_ready", return_value=(False, "openai", "missing")) as llm_auth,
            patch("src.api.ws_runner.asyncio.to_thread", side_effect=_to_thread_inline),
        ):
            await runner._handle_user_input(ui, "/random")
            self.assertIsNotNone(runner._running_task)
            assert runner._running_task is not None
            await runner._running_task

        invoke.assert_not_called()
        llm_auth.assert_not_called()
        self.assertFalse(runner._run_agent_turn.called)
        self.assertTrue(any("scope is missing" in str(event.get("text")) for event in ui.events))

    async def test_spotify_mode_random_reports_play_failure(self) -> None:
        runner = WebSocketRunner()
        runner._run_agent_turn = AsyncMock()
        ui = FakeUI()
        setattr(ui, "_spotify_mode", {"enabled": True, "device_id": "desktop", "device_name": "Studio Desktop"})

        with (
            patch("src.api.ws_runner.spotify_recent_tracks", return_value={
                "status": "success",
                "data": {"tracks": [{"name": "Recent", "uri": "spotify:track:recent"}]},
            }),
            patch("src.api.ws_runner.random.choice", return_value={"name": "Recent", "uri": "spotify:track:recent"}),
            patch("src.api.ws_runner.registry.invoke", return_value={
                "status": "fail",
                "message": "Spotify playback requires an active device.",
                "error_code": "SPOTIFY_NO_ACTIVE_DEVICE",
            }) as invoke,
            patch("src.api.ws_runner.asyncio.to_thread", side_effect=_to_thread_inline),
        ):
            await runner._handle_user_input(ui, "/random")
            self.assertIsNotNone(runner._running_task)
            assert runner._running_task is not None
            await runner._running_task

        invoke.assert_called_once_with("spotify_play", {"uri": "spotify:track:recent", "device_id": "desktop"})
        self.assertFalse(runner._run_agent_turn.called)
        self.assertTrue(any(event.get("type") == "error" and "active device" in str(event.get("message")) for event in ui.events))
        self.assertTrue(any("active device" in str(event.get("text")) for event in ui.events))

    async def test_random_outside_spotify_mode_still_routes_to_agent_intent(self) -> None:
        runner = WebSocketRunner()
        runner._run_agent_turn = AsyncMock()
        ui = FakeUI()

        with (
            patch("src.api.ws_runner.spotify_recent_tracks") as recent,
            patch("src.api.ws_runner._llm_auth_ready", return_value=(True, "openai", None)),
        ):
            await runner._handle_user_input(ui, "/random")
            await asyncio.sleep(0)

        recent.assert_not_called()
        intent = runner._run_agent_turn.await_args.kwargs["command_intent"]
        self.assertIn("spotify_recent_tracks", intent.allowed_tools)
        self.assertNotIn("apple_music_recent_tracks", intent.allowed_tools)
        self.assertNotIn("apple_music_play", intent.allowed_tools)
        self.assertIn("play_youtube_song", intent.allowed_tools)

    async def test_spotify_mode_rejects_non_spotify_mode_command_in_chat(self) -> None:
        runner = WebSocketRunner()
        runner._run_agent_turn = AsyncMock()
        ui = FakeUI()
        setattr(ui, "_spotify_mode", {"enabled": True, "device_id": "desktop", "device_name": "Studio Desktop"})

        await runner._handle_user_input(ui, "/help")

        self.assertFalse(runner._run_agent_turn.called)
        self.assertTrue(any("not available in Spotify mode" in str(event.get("text")) for event in ui.events))
        self.assertFalse(any(event.get("type") == "help_panel" for event in ui.events))

    async def test_spotify_mode_playlist_command_imports_once_then_browses_local_mirrors(self) -> None:
        runner = WebSocketRunner()
        ui = FakeUI()
        setattr(ui, "_spotify_mode", {"enabled": True, "device_id": "desktop", "device_name": "Studio Desktop"})
        playlists = [{"id": "playlist-1", "name": "Road", "owner": "Me", "track_count": 1}]
        tracks = [{"name": "Song", "artist": "Artist", "duration_ms": 123000, "uri": "spotify:track:1"}]
        saved_tracks = [{"name": "Saved Song", "artist": "Artist", "duration_ms": 123000, "uri": "spotify:track:saved"}]
        choices = [
            {"value": "playlist_ref:Spotify:spotify-library", "label": "[Spotify] Spotify Library", "description": "1 saved track", "track_count": 1},
            {"value": "playlist_ref:Spotify:playlist-1", "label": "[Spotify] Road", "description": "1 saved track", "track_count": 1},
        ]

        with patch("src.api.ws_runner.spotify_saved_tracks", return_value={
            "status": "success",
            "data": {"tracks": saved_tracks},
        }) as saved, patch("src.api.ws_runner.spotify_playlists", return_value={
            "status": "success",
            "data": {"playlists": playlists},
        }) as list_playlists, patch("src.api.ws_runner.spotify_playlist_tracks", return_value={
            "status": "success",
            "data": {"tracks": tracks},
        }) as playlist_tracks, patch("src.api.ws_runner.upsert_mirror_playlist") as upsert, patch(
            "src.api.ws_runner.playlist_choices",
            return_value=choices,
        ) as local_choices, patch("src.api.ws_runner.asyncio.to_thread", side_effect=_to_thread_inline):
            await runner._handle_user_input(ui, "/playlist")
            await runner._handle_user_input(ui, "/playlist")

        saved.assert_called_once_with(50, 0)
        list_playlists.assert_called_once_with(50, 0)
        playlist_tracks.assert_called_once_with("playlist-1", 100, 0)
        self.assertEqual(upsert.call_count, 2)
        local_choices.assert_called_with(writable_only=False)
        confirms = [event for event in ui.events if event.get("tool_name") == "playlist_browse"]
        self.assertEqual(len(confirms), 3)
        self.assertEqual(confirms[-1]["choices"][0]["label"], "[Spotify] Spotify Library")
        self.assertTrue(getattr(ui, "_spotify_library_synced"))

    async def test_spotify_mode_concurrent_playlist_commands_share_one_sync(self) -> None:
        runner = WebSocketRunner()
        ui = FakeUI()
        setattr(ui, "_spotify_mode", {"enabled": True, "device_id": "desktop"})
        started = asyncio.Event()
        release = asyncio.Event()

        async def sync_once(_ui: object) -> tuple[bool, str]:
            started.set()
            await release.wait()
            return True, "Spotify playlists synced."

        with patch.object(runner, "_sync_spotify_library_to_playlists", side_effect=sync_once) as sync, patch.object(
            runner,
            "_show_playlist_browse",
            new=AsyncMock(),
        ):
            first = asyncio.create_task(runner._show_spotify_playlists(ui))
            await started.wait()
            second = asyncio.create_task(runner._show_spotify_playlists(ui))
            await asyncio.sleep(0)
            release.set()
            await asyncio.gather(first, second)

        sync.assert_awaited_once_with(ui)

    async def test_spotify_mode_playlist_uses_fresh_persisted_mirrors_across_sessions(self) -> None:
        state = ws_runner.SpotifyLibrarySyncState(last_success_at=time.time())
        ws_runner.save_spotify_library_sync_state(state)
        runner = WebSocketRunner()
        ui = FakeUI()
        setattr(ui, "_spotify_mode", {"enabled": True, "device_id": "desktop"})

        with patch("src.api.ws_runner._spotify_mirror_external_ids", return_value={"spotify-library"}), patch(
            "src.api.ws_runner.spotify_saved_tracks",
        ) as saved, patch(
            "src.api.ws_runner.playlist_choices",
            return_value=[{"value": "playlist:likes", "label": "likes", "description": "0 saved tracks"}],
        ):
            await runner._handle_user_input(ui, "/playlist")

        saved.assert_not_called()
        self.assertTrue(getattr(ui, "_spotify_library_synced"))
        self.assertTrue(any(event.get("tool_name") == "playlist_browse" for event in ui.events))

    async def test_spotify_mode_playlist_failure_backoff_survives_new_ui_session(self) -> None:
        runner = WebSocketRunner()
        first_ui = FakeUI()
        second_ui = FakeUI()
        setattr(first_ui, "_spotify_mode", {"enabled": True, "device_id": "desktop"})
        setattr(second_ui, "_spotify_mode", {"enabled": True, "device_id": "desktop"})
        failure = {
            "status": "fail",
            "message": "Spotify did not respond before the request timeout.",
            "error_code": "SPOTIFY_READ_TIMEOUT",
        }

        with patch("src.api.ws_runner.spotify_saved_tracks", return_value=failure) as saved, patch(
            "src.api.ws_runner.playlist_choices",
            return_value=[{"value": "playlist:likes", "label": "likes", "description": "0 saved tracks"}],
        ), patch("src.api.ws_runner.asyncio.to_thread", side_effect=_to_thread_inline):
            await runner._handle_user_input(first_ui, "/playlist")
            await runner._handle_user_input(second_ui, "/playlist")

        saved.assert_called_once()
        self.assertTrue(
            any("will retry after" in str(event.get("detail")) for event in second_ui.events)
        )

    async def test_spotify_mode_playlist_sync_skips_unchanged_snapshot(self) -> None:
        now = time.time()
        state = ws_runner.SpotifyLibrarySyncState(
            saved_tracks_cursor="2026-07-11T00:00:00Z",
            last_full_saved_tracks_at=now,
            playlist_snapshots={"playlist-1": "snapshot-1"},
        )
        ws_runner.save_spotify_library_sync_state(state)
        runner = WebSocketRunner()
        ui = FakeUI()

        with patch(
            "src.api.ws_runner._spotify_mirror_external_ids",
            return_value={"spotify-library", "playlist-1"},
        ), patch("src.api.ws_runner.spotify_saved_tracks", return_value={
            "status": "success",
            "data": {"tracks": []},
        }), patch("src.api.ws_runner.spotify_playlists", return_value={
            "status": "success",
            "data": {"playlists": [{"id": "playlist-1", "name": "Road", "snapshot_id": "snapshot-1"}]},
        }), patch("src.api.ws_runner.spotify_playlist_tracks") as playlist_tracks, patch(
            "src.api.ws_runner.upsert_mirror_playlist",
        ) as upsert, patch("src.api.ws_runner.asyncio.to_thread", side_effect=_to_thread_inline):
            synced, _message = await runner._sync_spotify_library_to_playlists(ui)

        self.assertTrue(synced)
        playlist_tracks.assert_not_called()
        upsert.assert_not_called()

    async def test_spotify_mode_playlist_sync_merges_incremental_saved_tracks(self) -> None:
        now = time.time()
        state = ws_runner.SpotifyLibrarySyncState(
            saved_tracks_cursor="2026-07-11T00:00:00Z",
            last_full_saved_tracks_at=now,
        )
        ws_runner.save_spotify_library_sync_state(state)
        runner = WebSocketRunner()
        ui = FakeUI()
        new_track = {
            "name": "New",
            "artist": "Artist",
            "uri": "spotify:track:new",
            "added_at": "2026-07-12T00:00:00Z",
        }
        cursor_track = {
            "name": "Old",
            "artist": "Artist",
            "uri": "spotify:track:old",
            "added_at": "2026-07-11T00:00:00Z",
        }

        with patch(
            "src.api.ws_runner._spotify_mirror_external_ids",
            return_value={"spotify-library"},
        ), patch("src.api.ws_runner.spotify_saved_tracks", return_value={
            "status": "success",
            "data": {"tracks": [new_track, cursor_track]},
        }), patch("src.api.ws_runner.list_playlist_tracks", return_value=[cursor_track]), patch(
            "src.api.ws_runner.spotify_playlists",
            return_value={"status": "success", "data": {"playlists": []}},
        ), patch("src.api.ws_runner.upsert_mirror_playlist") as upsert, patch(
            "src.api.ws_runner.asyncio.to_thread",
            side_effect=_to_thread_inline,
        ):
            synced, _message = await runner._sync_spotify_library_to_playlists(ui)

        self.assertTrue(synced)
        stored_tracks = upsert.call_args.kwargs["tracks"]
        self.assertEqual([track["uri"] for track in stored_tracks], ["spotify:track:new", "spotify:track:old"])

    async def test_spotify_mode_playlist_sync_keeps_partial_mirrors(self) -> None:
        runner = WebSocketRunner()
        ui = FakeUI()
        inaccessible = {
            "status": "fail",
            "message": "Spotify denied access to this playlist.",
            "error_code": "SPOTIFY_FORBIDDEN",
        }
        available = {
            "status": "success",
            "data": {
                "tracks": [
                    {
                        "name": "Available",
                        "artist": "Artist",
                        "uri": "spotify:track:available",
                    }
                ]
            },
        }

        with patch(
            "src.api.ws_runner._spotify_mirror_external_ids",
            return_value={"spotify-library"},
        ), patch("src.api.ws_runner.spotify_saved_tracks", return_value={
            "status": "success",
            "data": {"tracks": []},
        }), patch("src.api.ws_runner.spotify_playlists", return_value={
            "status": "success",
            "data": {
                "playlists": [
                    {"id": "private", "name": "Private"},
                    {"id": "available", "name": "Available"},
                ]
            },
        }), patch(
            "src.api.ws_runner.spotify_playlist_tracks",
            side_effect=[inaccessible, available],
        ), patch("src.api.ws_runner.upsert_mirror_playlist") as upsert, patch(
            "src.api.ws_runner.asyncio.to_thread",
            side_effect=_to_thread_inline,
        ):
            synced, message = await runner._sync_spotify_library_to_playlists(ui)

        self.assertFalse(synced)
        self.assertIn("denied access", message)
        external_ids = [call.kwargs["external_id"] for call in upsert.call_args_list]
        self.assertEqual(external_ids, ["spotify-library", "available"])

    async def test_spotify_session_cache_returns_stale_read_during_cooldown(self) -> None:
        coordinator = ws_runner.SpotifySessionRequestCoordinator()
        fetch = AsyncMock(return_value={"status": "success", "data": {"tracks": ["cached"]}})
        with patch("src.api.ws_runner.spotify_api_cooldown_remaining", return_value=0):
            value, source = await coordinator.get_or_fetch(
                "queue",
                ttl_seconds=0,
                fetch=fetch,
                cacheable=ws_runner._spotify_success_result,
            )
        self.assertEqual(source, "network")
        self.assertEqual(value["data"]["tracks"], ["cached"])

        with patch("src.api.ws_runner.spotify_api_cooldown_remaining", return_value=10):
            stale, source = await coordinator.get_or_fetch(
                "queue",
                ttl_seconds=0,
                fetch=fetch,
                cacheable=ws_runner._spotify_success_result,
            )

        self.assertEqual(source, "stale_cache")
        self.assertEqual(stale, value)
        fetch.assert_awaited_once()

    async def test_spotify_mode_playlist_sync_times_out_with_chat_error(self) -> None:
        runner = WebSocketRunner()
        ui = FakeUI()
        setattr(ui, "_spotify_mode", {"enabled": True, "device_id": "desktop", "device_name": "Studio Desktop"})
        choices = [{"value": "playlist_ref:Spotify:spotify-library", "label": "[Spotify] Spotify Library", "description": "20 saved tracks", "track_count": 20}]

        async def never_returns(*_args, **_kwargs):
            await asyncio.sleep(10)

        with patch("src.api.ws_runner.asyncio.to_thread", side_effect=never_returns), patch(
            "src.api.ws_runner.SPOTIFY_MODE_CALL_TIMEOUT_SECONDS",
            0.001,
        ), patch("src.api.ws_runner.playlist_choices", return_value=choices):
            await runner._handle_user_input(ui, "/playlist")
            task = ws_runner._spotify_session_requests(ui).playlist_sync_task
            if task is not None:
                await task

        self.assertTrue(any("Spotify Library sync timed out" in str(event.get("text") or event.get("detail")) for event in ui.events))
        self.assertTrue(any(event.get("theme") == "spotify" for event in ui.events if event.get("role") == "agent"))
        self.assertTrue(any("Existing local playlists remain available" in str(event.get("detail")) for event in ui.events))
        confirms = [event for event in ui.events if event.get("tool_name") == "playlist_browse"]
        self.assertEqual(confirms[-1]["choices"][0]["label"], "[Spotify] Spotify Library")

    async def test_spotify_mode_playlist_rate_limit_reports_retry_after(self) -> None:
        runner = WebSocketRunner()
        ui = FakeUI()
        setattr(ui, "_spotify_mode", {"enabled": True, "device_id": "desktop", "device_name": "Studio Desktop"})

        with patch("src.api.ws_runner.spotify_saved_tracks", return_value={
            "status": "fail",
            "message": "Spotify says Too Many Requests. Requests are too frequent; try again later.",
            "error_code": "SPOTIFY_RATE_LIMITED",
            "data": {"retry_after": "62861 seconds"},
        }), patch("src.api.ws_runner.playlist_choices", return_value=[]), patch(
            "src.api.ws_runner.asyncio.to_thread",
            side_effect=_to_thread_inline,
        ):
            await runner._handle_user_input(ui, "/playlist")

        texts = [str(event.get("text") or event.get("detail") or "") for event in ui.events]
        self.assertTrue(any("Spotify is rate limited" in text for text in texts))
        self.assertTrue(any("62861 seconds" in text for text in texts))
        state = ws_runner.load_spotify_library_sync_state()
        self.assertGreater(state.next_retry_at - time.time(), 62_000)

    async def test_spotify_mode_playlist_sync_failure_opens_existing_local_mirrors(self) -> None:
        runner = WebSocketRunner()
        ui = FakeUI()
        setattr(ui, "_spotify_mode", {"enabled": True, "device_id": "desktop", "device_name": "Studio Desktop"})
        choices = [
            {"value": "playlist_ref:Spotify:spotify-library", "label": "[Spotify] Spotify Library", "description": "20 saved tracks", "track_count": 20},
        ]

        with patch("src.api.ws_runner.spotify_saved_tracks", return_value={
            "status": "fail",
            "message": "Spotify says Too Many Requests. Requests are too frequent; try again later.",
            "error_code": "SPOTIFY_RATE_LIMITED",
            "data": {"retry_after": "62861 seconds"},
        }) as saved, patch("src.api.ws_runner.playlist_choices", return_value=choices) as local_choices, patch(
            "src.api.ws_runner.asyncio.to_thread",
            side_effect=_to_thread_inline,
        ):
            await runner._handle_user_input(ui, "/playlist")
            await runner._handle_user_input(ui, "/playlist")

        saved.assert_called_once()
        local_choices.assert_called_with(writable_only=False)
        self.assertFalse(getattr(ui, "_spotify_library_synced", False))
        self.assertTrue(any("Existing local playlists remain available" in str(event.get("detail")) for event in ui.events))
        confirms = [event for event in ui.events if event.get("tool_name") == "playlist_browse"]
        self.assertEqual(confirms[-1]["choices"][0]["label"], "[Spotify] Spotify Library")

    async def test_spotify_mode_playlist_network_failure_uses_stable_message(self) -> None:
        runner = WebSocketRunner()
        ui = FakeUI()
        setattr(ui, "_spotify_mode", {"enabled": True, "device_id": "desktop", "device_name": "Studio Desktop"})
        raw_error = (
            "HTTPSConnectionPool(host='api.spotify.com', port=443): Max retries exceeded with url: "
            "/v1/me/tracks?limit=50&offset=0 (Caused by SSLError(SSLEOFError(8, "
            "'[SSL:UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol (_ssl.c:1000)')))"
        )

        with patch("src.api.ws_runner.spotify_saved_tracks", return_value={
            "status": "fail",
            "message": raw_error,
            "error_code": "SPOTIFY_API_ERROR",
        }), patch(
            "src.api.ws_runner.playlist_choices",
            return_value=[{"value": "playlist:likes", "label": "likes", "description": "0 saved tracks", "track_count": 0}],
        ), patch("src.api.ws_runner.asyncio.to_thread", side_effect=_to_thread_inline):
            await runner._handle_user_input(ui, "/playlist")

        texts = [str(event.get("text") or event.get("detail") or "") for event in ui.events]
        self.assertTrue(any("Spotify API request failed over the current network route" in text for text in texts))
        self.assertFalse(any("HTTPSConnectionPool" in text for text in texts))
        self.assertTrue(any("Existing local playlists remain available" in text for text in texts))
        confirms = [event for event in ui.events if event.get("tool_name") == "playlist_browse"]
        self.assertEqual(confirms[-1]["choices"][0]["label"], "likes")

    async def test_spotify_mode_playlist_proxy_failure_uses_actionable_message(self) -> None:
        runner = WebSocketRunner()
        ui = FakeUI()
        setattr(ui, "_spotify_mode", {"enabled": True, "device_id": "desktop", "device_name": "Studio Desktop"})
        proxy_message = (
            "Connection refused (local proxy http://127.0.0.1:7897 is not accepting connections; "
            "start the proxy or update/unset HTTPS_PROXY/HTTP_PROXY/https_proxy/http_proxy/all_proxy/ALL_PROXY.)"
        )

        with patch("src.api.ws_runner.spotify_saved_tracks", return_value={
            "status": "fail",
            "message": proxy_message,
            "error_code": "SPOTIFY_PROXY_UNAVAILABLE",
        }), patch(
            "src.api.ws_runner.playlist_choices",
            return_value=[{"value": "playlist:likes", "label": "likes", "description": "0 saved tracks", "track_count": 0}],
        ), patch("src.api.ws_runner.asyncio.to_thread", side_effect=_to_thread_inline):
            await runner._handle_user_input(ui, "/playlist")

        texts = [str(event.get("text") or event.get("detail") or "") for event in ui.events]
        self.assertTrue(any("local proxy http://127.0.0.1:7897" in text for text in texts))
        self.assertTrue(any("start the proxy" in text for text in texts))
        self.assertTrue(any("Existing local playlists remain available" in text for text in texts))
        confirms = [event for event in ui.events if event.get("tool_name") == "playlist_browse"]
        self.assertEqual(confirms[-1]["choices"][0]["label"], "likes")

    async def test_spotify_mode_playlist_sync_fetches_all_playlist_tracks(self) -> None:
        runner = WebSocketRunner()
        ui = FakeUI()
        setattr(ui, "_spotify_mode", {"enabled": True, "device_id": "desktop", "device_name": "Studio Desktop"})
        playlist = {"id": "playlist-1", "name": "Road", "owner": "Me", "track_count": 101}
        fetched_limits_offsets: list[tuple[int, int]] = []

        def playlist_tracks(playlist_id: str, limit: int = 50, offset: int = 0) -> dict:
            fetched_limits_offsets.append((limit, offset))
            count = 100 if offset == 0 else 1
            return {
                "status": "success",
                "data": {
                    "tracks": [
                        {"name": f"Song {offset + idx}", "artist": "Artist", "duration_ms": 123000, "uri": f"spotify:track:{offset + idx}"}
                        for idx in range(count)
                    ],
                },
            }

        with patch("src.api.ws_runner.spotify_saved_tracks", return_value={
            "status": "success",
            "data": {"tracks": []},
        }), patch("src.api.ws_runner.spotify_playlists", return_value={
            "status": "success",
            "data": {"playlists": [playlist]},
        }), patch("src.api.ws_runner.spotify_playlist_tracks", side_effect=playlist_tracks), patch(
            "src.api.ws_runner.upsert_mirror_playlist",
        ) as upsert, patch("src.api.ws_runner.playlist_choices", return_value=[]), patch(
            "src.api.ws_runner.asyncio.to_thread",
            side_effect=_to_thread_inline,
        ):
            await runner._handle_user_input(ui, "/playlist")

        self.assertEqual(fetched_limits_offsets, [(100, 0), (100, 100)])
        playlist_upsert = [call for call in upsert.call_args_list if call.kwargs.get("external_id") == "playlist-1"][-1]
        self.assertEqual(len(playlist_upsert.kwargs["tracks"]), 101)

    async def test_spotify_mode_playlist_sync_fetches_all_saved_tracks(self) -> None:
        runner = WebSocketRunner()
        ui = FakeUI()
        setattr(ui, "_spotify_mode", {"enabled": True, "device_id": "desktop", "device_name": "Studio Desktop"})
        fetched_limits_offsets: list[tuple[int, int]] = []

        def saved_tracks(limit: int = 50, offset: int = 0) -> dict:
            fetched_limits_offsets.append((limit, offset))
            count = 50 if offset == 0 else 48
            return {
                "status": "success",
                "data": {
                    "tracks": [
                        {"name": f"Saved {offset + idx}", "artist": "Artist", "duration_ms": 123000, "uri": f"spotify:track:saved-{offset + idx}"}
                        for idx in range(count)
                    ],
                },
            }

        with patch("src.api.ws_runner.spotify_saved_tracks", side_effect=saved_tracks), patch(
            "src.api.ws_runner.spotify_playlists",
            return_value={"status": "success", "data": {"playlists": []}},
        ), patch("src.api.ws_runner.upsert_mirror_playlist") as upsert, patch(
            "src.api.ws_runner.playlist_choices",
            return_value=[],
        ), patch("src.api.ws_runner.asyncio.to_thread", side_effect=_to_thread_inline):
            await runner._handle_user_input(ui, "/playlist")

        self.assertEqual(fetched_limits_offsets, [(50, 0), (50, 50)])
        library_upsert = [call for call in upsert.call_args_list if call.kwargs.get("external_id") == "spotify-library"][-1]
        self.assertEqual(len(library_upsert.kwargs["tracks"]), 98)

    async def test_spotify_mode_playlist_sync_fetches_all_playlist_pages(self) -> None:
        fetched_limits_offsets: list[tuple[int, int]] = []

        def playlists(limit: int = 50, offset: int = 0) -> dict:
            fetched_limits_offsets.append((limit, offset))
            count = 50 if offset == 0 else 2
            return {
                "status": "success",
                "data": {
                    "playlists": [
                        {"id": f"playlist-{offset + index}", "name": f"List {offset + index}"}
                        for index in range(count)
                    ]
                },
            }

        with patch("src.api.ws_runner.spotify_playlists", side_effect=playlists), patch(
            "src.api.ws_runner.asyncio.to_thread",
            side_effect=_to_thread_inline,
        ):
            ok, items, _result = await ws_runner._fetch_all_spotify_playlists()

        self.assertTrue(ok)
        self.assertEqual(fetched_limits_offsets, [(50, 0), (50, 50)])
        self.assertEqual(len(items), 52)

    async def test_spotify_mode_playlist_command_keeps_liked_songs_when_no_playlists(self) -> None:
        runner = WebSocketRunner()
        ui = FakeUI()
        setattr(ui, "_spotify_mode", {"enabled": True, "device_id": "desktop", "device_name": "Studio Desktop"})
        saved_tracks = [{"name": "Saved Song", "artist": "Artist", "duration_ms": 123000, "uri": "spotify:track:saved"}]

        with patch("src.api.ws_runner.spotify_saved_tracks", return_value={
            "status": "success",
            "data": {"tracks": saved_tracks},
        }), patch("src.api.ws_runner.spotify_playlists", return_value={
            "status": "success",
            "data": {"playlists": []},
        }), patch("src.api.ws_runner.upsert_mirror_playlist"), patch(
            "src.api.ws_runner.playlist_choices",
            return_value=[{"value": "playlist_ref:Spotify:spotify-library", "label": "[Spotify] Spotify Library", "description": "1 saved track", "track_count": 1}],
        ), patch("src.api.ws_runner.asyncio.to_thread", side_effect=_to_thread_inline):
            await runner._handle_user_input(ui, "/playlist")

        details = [str(event.get("detail") or "") for event in ui.events]
        self.assertFalse(any("No Spotify playlists found" in detail for detail in details))
        confirms = [event for event in ui.events if event.get("tool_name") == "playlist_browse"]
        self.assertEqual(confirms[-1]["choices"][0]["label"], "[Spotify] Spotify Library")

    async def test_spotify_mode_queue_command_shows_spotify_queue(self) -> None:
        runner = WebSocketRunner()
        runner._run_agent_turn = AsyncMock()
        ui = FakeUI()
        setattr(ui, "_spotify_mode", {"enabled": True, "device_id": "desktop", "device_name": "Studio Desktop"})
        tracks = [{"name": "Queued Song", "artist": "Artist", "duration_ms": 123000, "uri": "spotify:track:1"}]

        with (
            patch("src.api.ws_runner.spotify_queue", return_value={
                "status": "success",
                "data": {"tracks": tracks},
            }) as spotify_queue,
            patch("src.api.ws_runner.playback_queue_snapshot", side_effect=AssertionError("local queue should not be read")),
            patch("src.api.ws_runner.asyncio.to_thread", side_effect=_to_thread_inline),
        ):
            await runner._handle_user_input(ui, "/queue")
            await runner._handle_user_input(ui, "/queue")

        spotify_queue.assert_called_once_with(50)
        self.assertFalse(runner._run_agent_turn.called)
        panel = [event for event in ui.events if event.get("type") == "track_panel"][-1]
        self.assertEqual(panel["panel"], "queue")
        self.assertEqual(panel["title"], "Spotify Queue")
        self.assertEqual(panel["tracks"][0]["title"], "Queued Song")

    async def test_spotify_playback_sync_does_not_poll_outside_spotify_mode(self) -> None:
        runner = WebSocketRunner()
        ui = FakeUI()
        ui.closed = False

        async def stop_after_sleep(_ui: object, seconds: float) -> None:
            self.assertEqual(seconds, ws_runner.SPOTIFY_PLAYBACK_IDLE_POLL_SECONDS)
            ui.closed = True

        with patch("src.api.ws_runner.spotify_current_playback") as playback, patch(
            "src.api.ws_runner._wait_for_spotify_sync",
            side_effect=stop_after_sleep,
        ):
            await runner._sync_spotify_playback(ui)

        playback.assert_not_called()

    async def test_track_panel_queue_add_appends_selected_track_to_up_next(self) -> None:
        runner = WebSocketRunner()
        ui = FakeUI()
        track = {
            "index": "01",
            "title": "Queued Song",
            "name": "Queued Song",
            "artist": "Artist",
            "duration": "02:03",
            "duration_ms": 123000,
            "uri": "spotify:track:queued",
            "provider": "spotify",
        }

        resolved = {
            **track,
            "ref": "spotify:uri:spotify:track:queued",
            "playable": True,
        }
        with patch(
            "src.api.ws_runner.remember_track_reference",
            return_value=resolved["ref"],
        ), patch(
            "src.api.ws_runner.resolve_track_reference",
            return_value=resolved,
        ), patch(
            "src.api.ws_runner.append_up_next_track",
            return_value={"revision": 1, "items": [resolved], "failed": []},
        ) as append, patch(
            "src.api.ws_runner._queue_payload",
            return_value=[track],
        ):
            await runner._handle_track_panel_action(ui, {"action": "queue_add", "track": track, "panel": "playlist", "title": "Spotify Playlist: Road"})

        append.assert_called_once_with(resolved)
        queue_events = [event for event in ui.events if event.get("type") == "queue"]
        self.assertEqual(queue_events[-1]["tracks"], [track])
        details = [str(event.get("detail") or "") for event in ui.events]
        self.assertTrue(any("Added to playback queue" in detail for detail in details))

    async def test_up_next_play_skips_failed_head_and_reports_one_caution(self) -> None:
        runner = WebSocketRunner()
        ui = FakeUI()
        first = {
            "ref": "spotify:uri:spotify:track:first",
            "name": "First",
            "provider": "spotify",
            "playable": True,
        }
        second = {
            "ref": "spotify:uri:spotify:track:second",
            "name": "Second",
            "provider": "spotify",
            "playable": True,
        }
        runner._play_track_panel_track = AsyncMock(
            side_effect=[
                (False, "First route failed."),
                (True, ""),
            ]
        )
        with patch("src.api.ws_runner.up_next_snapshot", return_value={
            "revision": 1,
            "items": [first, second],
            "failed": [],
        }), patch("src.api.ws_runner.fail_up_next_head", return_value={
            "revision": 2,
            "items": [second],
            "failed": [{**first, "failure_reason": "First route failed."}],
        }) as fail_head, patch(
            "src.api.ws_runner.consume_up_next_head",
        ) as consume_head, patch(
            "src.api.ws_runner._queue_payload",
            return_value=[],
        ):
            await runner._play_up_next_from_selection(ui, first)

        self.assertEqual(runner._play_track_panel_track.await_count, 2)
        fail_head.assert_called_once_with("First route failed.")
        consume_head.assert_called_once_with()
        cautions = [event for event in ui.events if event.get("type") == "error"]
        self.assertEqual(len(cautions), 1)
        self.assertIn("skipping 1 queued track", str(cautions[0]["message"]))

    async def test_track_panel_enter_plays_spotify_uri_on_selected_device(self) -> None:
        runner = WebSocketRunner()
        ui = FakeUI()
        setattr(ui, "_spotify_mode", {"enabled": True, "device_id": "desktop", "device_name": "Studio Desktop"})
        track = {
            "index": "01",
            "title": "Spotify Song",
            "name": "Spotify Song",
            "artist": "Artist",
            "duration": "02:03",
            "duration_ms": 123000,
            "uri": "spotify:track:selected",
            "provider": "spotify",
        }
        result = {
            "status": "success",
            "tool": "spotify_play",
            "message": "Spotify playback started.",
            "data": {**track, "is_playing": True, "progress_ms": 0},
        }

        with patch("src.api.ws_runner.registry.invoke", return_value=result) as invoke, patch(
            "src.api.ws_runner.asyncio.to_thread",
            side_effect=_to_thread_inline,
        ):
            await runner._handle_track_panel_action(ui, {"action": "play", "track": track, "panel": "playlist", "title": "Spotify Playlist: Road"})

        invoke.assert_called_once_with("spotify_play", {"uri": "spotify:track:selected", "device_id": "desktop"})
        player_events = [event for event in ui.events if event.get("type") == "player"]
        self.assertTrue(player_events)

    async def test_spotify_mode_queue_command_reports_spotify_queue_failure(self) -> None:
        runner = WebSocketRunner()
        ui = FakeUI()
        setattr(ui, "_spotify_mode", {"enabled": True, "device_id": "desktop", "device_name": "Studio Desktop"})

        with (
            patch("src.api.ws_runner.spotify_queue", return_value={
                "status": "fail",
                "message": "Spotify playback state requires a Premium account.",
                "error_code": "SPOTIFY_PREMIUM_REQUIRED",
            }),
            patch("src.api.ws_runner.asyncio.to_thread", side_effect=_to_thread_inline),
        ):
            await runner._handle_user_input(ui, "/queue")

        panels = [event for event in ui.events if event.get("type") == "track_panel"]
        self.assertFalse(panels)
        self.assertTrue(any("Premium" in str(event.get("text")) for event in ui.events))

    async def test_spotify_mode_queue_command_times_out_with_chat_error(self) -> None:
        runner = WebSocketRunner()
        ui = FakeUI()
        setattr(ui, "_spotify_mode", {"enabled": True, "device_id": "desktop", "device_name": "Studio Desktop"})

        async def never_returns(*_args, **_kwargs):
            await asyncio.sleep(10)

        with patch("src.api.ws_runner.asyncio.to_thread", side_effect=never_returns), patch(
            "src.api.ws_runner.SPOTIFY_MODE_CALL_TIMEOUT_SECONDS",
            0.001,
        ):
            await runner._handle_user_input(ui, "/queue")

        panels = [event for event in ui.events if event.get("type") == "track_panel"]
        self.assertFalse(panels)
        self.assertTrue(any("Spotify queue timed out" in str(event.get("text")) for event in ui.events))
        self.assertTrue(any("Spotify queue timed out" in str(event.get("detail")) for event in ui.events))

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
             patch("src.api.ws_runner.search_track_metadata_candidates", return_value=_metadata_result("周杰伦 七里香")):
            await runner._handle_user_input(ui, "最近我对周杰伦的《七里香》很感兴趣")

        self.assertFalse(runner._run_agent_turn.called)
        self.assertIsNone(getattr(ui, "_music_intent_confirmation", None))
        confirm = [event for event in ui.events if event.get("type") == "confirm"][-1]
        self.assertEqual(confirm["tool_name"], "song_candidate")
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
             patch("src.api.ws_runner.search_track_metadata_candidates", return_value=_metadata_result("周杰伦 七里香")):
            await runner._handle_user_input(ui, "最近我对周杰伦的《七里香》很感兴趣")

        playback_confirm = [event for event in ui.events if event.get("tool_name") == "song_candidate"][-1]
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
             patch("src.api.ws_runner.search_track_metadata_candidates", return_value=_metadata_result("青花瓷")), \
             patch("src.api.ws_runner.asyncio.to_thread", side_effect=_to_thread_inline):
            await runner._run_agent_turn(ui, "能不能来点青花瓷")

        session = getattr(ui, "_play_selection")
        self.assertEqual(session.query, "青花瓷")
        confirm = [event for event in ui.events if event.get("tool_name") == "song_candidate"][-1]
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
        self.assertEqual(intent.allowed_tools, ("Recommend",))
        self.assertEqual(intent.max_tool_calls, 1)
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
             patch("src.api.ws_runner.search_track_metadata_candidates", return_value=_metadata_result("晴天 周杰伦")), \
             patch("src.api.ws_runner.asyncio.to_thread", side_effect=_to_thread_inline):
            await runner._handle_user_input(ui, "播放第 2 首")

        confirm = [event for event in ui.events if event.get("tool_name") == "song_candidate"][-1]
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

        self.assertTrue(any("from 1 to 1" in str(event.get("text")) for event in ui.events))
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
             patch("src.api.ws_runner._llm_auth_ready", return_value=(False, "openai", "missing")), \
             patch("src.api.ws_runner.search_track_metadata_candidates", return_value=_metadata_result("方大同的Sorry")), \
             patch("src.api.ws_runner.asyncio.to_thread", side_effect=_to_thread_inline):
            await runner._handle_user_input(ui, "帮我放一首方大同的Sorry")

        self.assertFalse(runner._run_agent_turn.called)
        confirm_events = [event for event in ui.events if event.get("type") == "confirm"]
        self.assertTrue(confirm_events)
        self.assertEqual(confirm_events[-1]["tool_args"]["query"], "方大同的Sorry")
        self.assertEqual(confirm_events[-1]["tool_name"], "song_candidate")

    async def test_want_to_listen_starts_song_metadata_candidates_without_method_choice(self) -> None:
        """Verifies that a play request starts metadata candidates directly.

        Typical use: Use this in automated tests when guarding the want to listen playback online choice starts song metadata candidates behavior against regressions.

        Example: a want-to-listen request emits a song-candidate confirmation.
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
             patch("src.api.ws_runner._llm_auth_ready", return_value=(False, "openai", "missing")), \
             patch("src.api.ws_runner.search_track_metadata_candidates", return_value=metadata_result) as metadata_search, \
             patch("src.api.ws_runner.search_youtube_songs") as youtube_search, \
             patch("src.api.ws_runner.asyncio.to_thread", side_effect=_to_thread_inline):
            await runner._handle_user_input(ui, "我想听 青花瓷")

        self.assertFalse(runner._run_agent_turn.called)
        metadata_search.assert_called_once_with("青花瓷", 5)
        youtube_search.assert_not_called()
        confirm_events = [event for event in ui.events if event.get("type") == "confirm"]
        self.assertEqual(confirm_events[-1]["tool_name"], "song_candidate")
        self.assertEqual(confirm_events[-1]["choices"][0]["label"], f"{'周杰伦'.ljust(24)} {'我很忙'.ljust(24)} 青花瓷")
        self.assertNotIn("3:59", confirm_events[-1]["choices"][0]["description"])
        self.assertTrue(any(event.get("type") == "activity" and event.get("title") == "iTunes" for event in ui.events))

    async def test_normal_mode_starts_metadata_before_open_audio_setup_is_needed(self) -> None:
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
             patch("src.api.ws_runner.online_audio_configured", return_value=False) as configured, \
             patch("src.api.ws_runner.search_track_metadata_candidates", return_value=metadata_result) as metadata_search, \
             patch("src.api.ws_runner.search_online_audio_candidates") as online_search, \
             patch("src.api.ws_runner.asyncio.to_thread", side_effect=_to_thread_inline):
            await runner._handle_user_input(ui, "play 青花瓷")

        configured.assert_not_called()
        metadata_search.assert_called_once_with("青花瓷", 5)
        online_search.assert_not_called()
        confirm_events = [event for event in ui.events if event.get("type") == "confirm"]
        self.assertEqual(confirm_events[-1]["tool_name"], "song_candidate")

    async def test_missing_online_audio_setup_ends_without_method_panel(self) -> None:
        runner = WebSocketRunner()
        ui = FakeUI()

        with patch("src.api.ws_runner.search_local_file", return_value="No local files found."), patch(
            "src.api.ws_runner.search_online_audio_candidates",
            side_effect=ws_runner.OnlineAudioSetupRequired("setup required"),
        ):
            await runner._handle_user_input(ui, "play song")

        self.assertIsNone(getattr(ui, "_play_selection", None))
        confirms = [event for event in ui.events if event.get("type") == "confirm"]
        self.assertFalse(any(event.get("tool_args", {}).get("stage") == "method_choice" for event in confirms))
        self.assertTrue(any(
            event.get("type") == "error" and ws_runner.ONLINE_AUDIO_SETUP_MESSAGE in str(event.get("message"))
            for event in ui.events
        ))

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

    async def test_setup_apple_stores_token_service_url_from_terminal_panel(self) -> None:
        runner = WebSocketRunner()
        ui = FakeUI()

        with self._isolated_auth_env({"SONEX_DEFAULT_PROVIDER": "openai", "SONEX_OPENAI_API_KEY": "sk-test"}):
            await runner._handle_user_input(ui, "/setup apple")
            setup = getattr(ui, "_apple_music_setup")
            auth_events = [event for event in ui.events if event.get("type") == "auth_setup"]
            self.assertEqual(auth_events[-1]["title"], "Apple Music token setup")
            self.assertIn("developer-token service URL", str(auth_events[-1]["message"]))
            self.assertEqual(auth_events[-1]["prompt"], "Apple token service URL")
            self.assertFalse(auth_events[-1].get("mask", False))

            await setup.handle_input("not-a-url")
            self.assertIn("must be an http(s) URL", str(
                [event for event in ui.events if event.get("type") == "auth_setup"][-1]["message"]
            ))

            await setup.handle_input("https://tokens.example.test/")
            store = load_auth_store()

        self.assertEqual(store.providers["apple_mode"].base_url, "https://tokens.example.test")
        auth_events = [event for event in ui.events if event.get("type") == "auth_setup"]
        self.assertEqual(auth_events[-1]["title"], "Apple Music token configured")
        self.assertFalse(auth_events[-1].get("active", True))
        self.assertIsNone(getattr(ui, "_apple_music_setup"))

    async def test_setup_apple_cancel_hides_panel_and_appends_system_message(self) -> None:
        runner = WebSocketRunner()
        ui = FakeUI()

        with self._isolated_auth_env({"SONEX_DEFAULT_PROVIDER": "openai", "SONEX_OPENAI_API_KEY": "sk-test"}):
            await runner._handle_user_input(ui, "/setup apple")
            setup = getattr(ui, "_apple_music_setup")
            await setup.handle_input("__cancel__")

        auth_events = [event for event in ui.events if event.get("type") == "auth_setup"]
        self.assertEqual(auth_events[-1]["step"], "cancelled")
        self.assertFalse(auth_events[-1].get("active", True))
        self.assertIsNone(getattr(ui, "_apple_music_setup"))

        system_events = [
            event
            for event in ui.events
            if event.get("type") == "chat" and event.get("tone") == "system"
        ]
        self.assertTrue(system_events)
        self.assertIn("canceled", str(system_events[-1]["text"]).lower())
        self.assertIn("panel hidden", str(system_events[-1]["text"]).lower())

    async def test_apple_without_token_configuration_opens_terminal_setup_panel(self) -> None:
        runner = WebSocketRunner()
        ui = FakeUI()

        with self._isolated_auth_env({
            "SONEX_DEFAULT_PROVIDER": "openai",
            "SONEX_OPENAI_API_KEY": "sk-test",
            "SONEX_APPLE_TOKEN_BROKER_URL": "",
        }):
            await runner._handle_user_input(ui, "/apple")

        setup = getattr(ui, "_apple_music_setup", None)
        auth_events = [event for event in ui.events if event.get("type") == "auth_setup"]
        self.assertIsNotNone(setup)
        self.assertTrue(auth_events)
        self.assertEqual(auth_events[-1]["title"], "Apple Music token setup")
        self.assertEqual(auth_events[-1]["prompt"], "Apple token service URL")
        self.assertIsNot(auth_events[-1].get("active"), False)
        self.assertFalse(any(
            "Apple Mode token service is not configured" in str(event.get("text"))
            for event in ui.events
            if event.get("type") == "chat"
        ))

    def test_queue_payload_reads_dedicated_up_next_snapshot(self) -> None:
        queue_tracks = [
            {"name": f"Queued {idx}", "artist": "Artist", "duration_ms": 60_000}
            for idx in range(10)
        ]
        with patch("src.api.ws_runner.up_next_snapshot", return_value={
            "revision": 3,
            "items": queue_tracks,
            "failed": [],
        }):
            queue = _queue_payload()

        self.assertEqual(len(queue), 10)
        self.assertEqual(queue[0]["title"], "Queued 0-Artist")
        self.assertEqual(queue[-1]["index"], "10")

    def test_track_panel_payload_uses_queue_title_and_tracks(self) -> None:
        queue_tracks = [
            {"name": "Queued Song", "artist": "Artist", "duration_ms": 90_000}
        ]
        with patch("src.api.ws_runner.up_next_snapshot", return_value={
            "revision": 1,
            "items": queue_tracks,
            "failed": [],
        }):
            panel = _track_panel_payload("queue", "Queue", _queue_payload())

        self.assertEqual(panel["type"], "track_panel")
        self.assertEqual(panel["panel"], "queue")
        self.assertEqual(panel["title"], "Queue")
        self.assertNotIn("hint", panel)
        self.assertEqual(panel["tracks"][0]["title"], "Queued Song-Artist")

    async def test_queue_command_sends_track_panel_without_agent_turn(self) -> None:
        runner = WebSocketRunner()
        runner._run_agent_turn = AsyncMock()
        ui = FakeUI()
        queue_tracks = [{"name": "Queued Song", "artist": "Artist", "duration_ms": 90_000}]

        with patch("src.api.ws_runner.up_next_snapshot", return_value={
            "revision": 1,
            "items": queue_tracks,
            "failed": [],
        }):
            await runner._handle_user_input(ui, "/queue")

        self.assertFalse(runner._run_agent_turn.called)
        panels = [event for event in ui.events if event.get("type") == "track_panel"]
        self.assertEqual(panels[-1]["panel"], "queue")
        self.assertNotIn("hint", panels[-1])
        self.assertEqual(panels[-1]["tracks"][0]["title"], "Queued Song-Artist")
        self.assertEqual(len(panels[-1]["tracks"]), 1)
        activity_events = [event for event in ui.events if event.get("type") == "activity"]
        self.assertIn("playback queue", str(activity_events[-1]["detail"]).lower())

    async def test_playlist_command_sends_playlist_track_panel(self) -> None:
        runner = WebSocketRunner()
        runner._run_agent_turn = AsyncMock()
        ui = FakeUI()
        tracks = [{"index": "01", "title": "Saved Song", "artist": "Artist", "duration": "03:00"}]

        with patch("src.api.ws_runner.playlist_panel_tracks", return_value=tracks):
            await runner._handle_user_input(ui, "/playlist likes")

        self.assertFalse(runner._run_agent_turn.called)
        panels = [event for event in ui.events if event.get("type") == "track_panel"]
        self.assertEqual(panels[-1]["panel"], "playlist")
        self.assertEqual(panels[-1]["title"], "Playlist: likes")
        self.assertEqual(panels[-1]["tracks"], tracks)

    async def test_playlist_command_without_name_browses_imported_mirrors(self) -> None:
        runner = WebSocketRunner()
        runner._run_agent_turn = AsyncMock()
        ui = FakeUI()

        with patch("src.api.ws_runner.playlist_choices", return_value=[
            {"value": "playlist:likes", "label": "likes", "description": "0 saved tracks", "track_count": 0},
            {"value": "playlist_ref:Spotify:spotify-library", "label": "[Spotify] Spotify Library", "description": "1 saved track", "track_count": 1},
        ]):
            await runner._handle_user_input(ui, "/playlist")

        self.assertFalse(runner._run_agent_turn.called)
        confirms = [event for event in ui.events if event.get("tool_name") == "playlist_browse"]
        self.assertEqual(confirms[-1]["choices"][1]["label"], "[Spotify] Spotify Library")
        self.assertEqual(confirms[-1]["choices"][1]["track_count"], 1)

    async def test_playlist_save_opens_target_picker_defaulting_to_likes(self) -> None:
        runner = WebSocketRunner()
        runner._run_agent_turn = AsyncMock()
        ui = FakeUI()
        setattr(ui, "_last_player_state", {
            "name": "Current Song",
            "artist": "Current Artist",
            "album": "-",
            "duration_ms": 180000,
            "provider": "youtube",
        })

        with patch("src.api.ws_runner.playlist_choices", return_value=[
            {"value": "playlist:likes", "label": "likes", "description": "1 saved track", "track_count": 1},
            {"value": "playlist:road", "label": "road", "description": "0 saved tracks", "track_count": 0},
        ]):
            await runner._handle_user_input(ui, "/playlist save")

        self.assertFalse(runner._run_agent_turn.called)
        confirms = [event for event in ui.events if event.get("type") == "confirm"]
        self.assertEqual(confirms[-1]["tool_name"], "playlist_save")
        self.assertEqual(confirms[-1]["choices"][0]["value"], "playlist:likes")

    async def test_playlist_save_choice_saves_current_track(self) -> None:
        runner = WebSocketRunner()
        ui = FakeUI()
        setattr(ui, "_last_player_state", {
            "name": "Current Song",
            "artist": "Current Artist",
            "album": "-",
            "duration_ms": 180000,
            "provider": "youtube",
        })

        await runner._start_playlist_save(ui, "")
        session = getattr(ui, "_playlist_save")
        with patch("src.api.ws_runner.save_track_to_playlist", return_value={
            "added": True,
            "playlist": {"name": "likes", "track_count": 1},
            "track": {"name": "Current Song", "artist": "Current Artist"},
        }) as save_track:
            await session.handle_choice("playlist:likes")

        save_track.assert_called_once()
        self.assertTrue(any("Saved to likes" in str(event.get("text")) for event in ui.events))

    def test_player_state_decoration_includes_likes_membership(self) -> None:
        state = {
            "name": "Current Song",
            "artist": "Current Artist",
            "album": "-",
            "duration_ms": 180000,
            "provider": "youtube",
        }

        with patch("src.api.ws_runner.track_in_playlist", return_value=True) as in_likes, \
                patch("src.api.ws_runner.track_in_any_playlist") as in_playlist:
            decorated = _decorate_player_state(state)

        in_playlist.assert_not_called()
        in_likes.assert_called_once()
        self.assertIsNot(decorated, state)
        self.assertTrue(decorated["is_liked"])
        self.assertTrue(decorated["is_in_playlist"])

        with patch("src.api.ws_runner.track_in_playlist", return_value=False), \
                patch("src.api.ws_runner.track_in_any_playlist", return_value=False):
            self.assertFalse(_decorate_player_state(state)["is_liked"])

    async def test_player_event_includes_likes_membership(self) -> None:
        runner = WebSocketRunner()
        ui = FakeUI()
        result = {
            "status": "success",
            "tool": "local_playback_player",
            "message": "Playback backend set.",
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
            },
        }

        with patch("src.api.ws_runner.registry.invoke", return_value=result), \
                patch("src.api.ws_runner.track_in_playlist", return_value=True), \
                patch("src.api.ws_runner.track_in_any_playlist", return_value=True):
            await runner._sync_tool_result_ui(ui, "local_playback_status", result)

        player_events = [event for event in ui.events if event.get("type") == "player"]
        self.assertTrue(player_events[-1]["state"]["is_liked"])
        self.assertTrue(player_events[-1]["state"]["is_in_playlist"])

    async def test_playlist_save_to_likes_emits_updated_liked_player_state(self) -> None:
        runner = WebSocketRunner()
        ui = FakeUI()
        setattr(ui, "_last_player_state", {
            "name": "Current Song",
            "artist": "Current Artist",
            "album": "-",
            "duration_ms": 180000,
            "provider": "youtube",
            "is_liked": False,
        })

        await runner._start_playlist_save(ui, "")
        session = getattr(ui, "_playlist_save")
        with patch("src.api.ws_runner.save_track_to_playlist", return_value={
            "added": True,
            "playlist": {"name": "likes", "track_count": 1},
            "track": {"name": "Current Song", "artist": "Current Artist"},
        }), patch("src.api.ws_runner.track_in_playlist", return_value=True), \
                patch("src.api.ws_runner.track_in_any_playlist", return_value=True):
            await session.handle_choice("playlist:likes")

        player_events = [event for event in ui.events if event.get("type") == "player"]
        self.assertTrue(player_events)
        self.assertTrue(player_events[-1]["state"]["is_liked"])
        self.assertTrue(player_events[-1]["state"]["is_in_playlist"])

    async def test_playlist_save_to_named_playlist_emits_updated_membership(self) -> None:
        runner = WebSocketRunner()
        ui = FakeUI()
        setattr(ui, "_last_player_state", {
            "name": "Current Song",
            "artist": "Current Artist",
            "album": "-",
            "duration_ms": 180000,
            "provider": "youtube",
            "is_liked": False,
            "is_in_playlist": False,
        })

        with patch("src.api.ws_runner.save_track_to_playlist", return_value={
            "added": True,
            "playlist": {"name": "road trip", "track_count": 1},
            "track": {"name": "Current Song", "artist": "Current Artist"},
        }), patch("src.api.ws_runner.track_in_playlist", return_value=False), \
                patch("src.api.ws_runner.track_in_any_playlist", return_value=True):
            await runner._start_playlist_save(ui, "road trip")

        player_events = [event for event in ui.events if event.get("type") == "player"]
        self.assertTrue(player_events)
        self.assertFalse(player_events[-1]["state"]["is_liked"])
        self.assertTrue(player_events[-1]["state"]["is_in_playlist"])

    async def test_pause_command_is_not_user_accessible_from_chat(self) -> None:
        runner = WebSocketRunner()
        runner._run_agent_turn = AsyncMock()
        ui = FakeUI()

        with patch("src.api.ws_runner.registry.invoke") as invoke:
            await runner._handle_user_input(ui, "/pause")

        invoke.assert_not_called()
        self.assertFalse(runner._run_agent_turn.called)
        self.assertTrue(any("keyboard shortcut" in str(event.get("text")) for event in ui.events))

    async def test_internal_pause_command_controls_local_playback_without_agent_turn(self) -> None:
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
            await runner._handle_internal_command(ui, "/pause")

        self.assertFalse(runner._run_agent_turn.called)
        invoke.assert_called_once_with("local_playback_pause", {})
        player_events = [event for event in ui.events if event.get("type") == "player"]
        self.assertTrue(player_events)
        self.assertEqual(player_events[-1]["state"]["session_id"], "session-1")
        self.assertFalse(player_events[-1]["state"]["is_playing"])

    async def test_internal_pause_command_controls_selected_spotify_device_without_agent_turn(self) -> None:
        runner = WebSocketRunner()
        runner._run_agent_turn = AsyncMock()
        ui = FakeUI()
        setattr(ui, "_spotify_mode", {"enabled": True, "device_id": "desktop", "device_name": "Studio Desktop"})
        result = {
            "status": "success",
            "tool": "spotify_pause",
            "message": "Spotify playback paused.",
            "data": {"is_playing": False},
        }

        with patch("src.api.ws_runner.registry.invoke", return_value=result) as invoke, patch(
            "src.api.ws_runner._request_spotify_sync"
        ) as request_sync:
            await runner._handle_internal_command(ui, "/pause")

        self.assertFalse(runner._run_agent_turn.called)
        invoke.assert_called_once_with("spotify_pause", {"device_id": "desktop"})
        request_sync.assert_called_once_with(ui)

    async def test_internal_resume_command_controls_selected_spotify_device(self) -> None:
        runner = WebSocketRunner()
        ui = FakeUI()
        setattr(ui, "_spotify_mode", {"enabled": True, "device_id": "desktop", "device_name": "Studio Desktop"})
        result = {
            "status": "success",
            "tool": "spotify_resume",
            "message": "Spotify playback resumed.",
            "data": {"is_playing": True},
        }

        with patch("src.api.ws_runner.registry.invoke", return_value=result) as invoke, patch(
            "src.api.ws_runner._request_spotify_sync"
        ) as request_sync:
            await runner._handle_internal_command(ui, "/resume")

        invoke.assert_called_once_with("spotify_resume", {"device_id": "desktop"})
        request_sync.assert_called_once_with(ui)

    async def test_failed_spotify_pause_keeps_state_and_requests_correction(self) -> None:
        runner = WebSocketRunner()
        runner._run_agent_turn = AsyncMock()
        ui = FakeUI()
        setattr(ui, "_spotify_mode", {"enabled": True, "device_id": "desktop"})
        setattr(ui, "_last_player_state", {"provider": "spotify", "name": "Song", "is_playing": True})
        result = {
            "status": "fail",
            "tool": "spotify_pause",
            "message": "Spotify device is unavailable.",
            "error_code": "SPOTIFY_DEVICE_REQUIRED",
            "data": {},
        }

        with patch("src.api.ws_runner.registry.invoke", return_value=result), patch(
            "src.api.ws_runner._request_spotify_sync"
        ) as request_sync:
            await runner._handle_internal_command(ui, "/pause")

        self.assertFalse(runner._run_agent_turn.called)
        self.assertEqual(getattr(ui, "_last_player_state")["is_playing"], True)
        request_sync.assert_called_once_with(ui)
        self.assertTrue(any(event.get("status") == "error" for event in ui.events))

    async def test_internal_stop_remains_local_in_spotify_mode(self) -> None:
        runner = WebSocketRunner()
        ui = FakeUI()
        setattr(ui, "_spotify_mode", {"enabled": True, "device_id": "desktop"})
        result = {
            "status": "success",
            "tool": "local_playback_stop",
            "message": "Playback stopped.",
            "data": {"name": "Song", "is_playing": False, "ended": True},
        }

        with patch("src.api.ws_runner.registry.invoke", return_value=result) as invoke:
            await runner._handle_internal_command(ui, "/stop")

        invoke.assert_called_once_with("local_playback_stop", {})

    async def test_spotify_play_result_enters_starting_state_until_live_sync_confirms_playback(self) -> None:
        runner = WebSocketRunner()
        ui = FakeUI()
        result = {
            "status": "success",
            "tool": "spotify_play",
            "message": "Started Spotify playback.",
            "data": {
                "provider": "spotify",
                "source": "spotify",
                "uri": "spotify:track:abc",
                "name": "Song",
                "artist": "Artist",
                "album": "Album",
                "duration_ms": 180000,
                "progress_ms": 0,
                "timestamp": 1000,
                "is_playing": True,
            },
        }

        await runner._sync_tool_result_ui(ui, "spotify_play", result)

        player_events = [event for event in ui.events if event.get("type") == "player"]
        self.assertTrue(player_events)
        state = player_events[-1]["state"]
        self.assertEqual(state["playback_status"], "starting")
        self.assertEqual(state["progress_source"], "spotify_pending")
        self.assertFalse(state["is_playing"])
        self.assertEqual(state["progress_ms"], 0)

    def test_spotify_player_sync_signature_tracks_one_second_progress_changes(self) -> None:
        first = {
            "name": "Song",
            "artist": "Artist",
            "album": "Album",
            "duration_ms": 180000,
            "progress_ms": 1000,
            "is_playing": True,
            "source": "spotify",
        }
        second = {**first, "progress_ms": 2000}

        self.assertNotEqual(_player_sync_signature(first), _player_sync_signature(second))

    async def test_spotify_live_sync_marks_progress_anchor(self) -> None:
        runner = WebSocketRunner()
        ui = FakeUI()
        ui.closed = False
        setattr(ui, "_spotify_mode", {"enabled": True, "device_id": "desktop"})
        playback = {
            "status": "success",
            "data": {
                "provider": "spotify",
                "source": "spotify",
                "name": "Song",
                "artist": "Artist",
                "album": "Album",
                "duration_ms": 180000,
                "progress_ms": 42000,
                "timestamp": 123456,
                "is_playing": True,
            },
        }

        async def stop_after_first_sleep(_ui: object, seconds: float) -> None:
            self.assertEqual(seconds, ws_runner.SPOTIFY_PLAYBACK_ACTIVE_POLL_SECONDS)
            ui.closed = True

        async def call_inline(func: object, *args: object, **kwargs: object) -> object:
            return func(*args, **kwargs)  # type: ignore[operator]

        with patch("src.api.ws_runner.spotify_current_playback", return_value=playback), \
                patch("src.api.ws_runner._timestamp_ms", return_value=200000), \
                patch("src.api.ws_runner._remember_actual_playback"), \
                patch("src.api.ws_runner._queue_payload", return_value=[]), \
                patch("src.api.ws_runner.asyncio.to_thread", side_effect=call_inline), \
                patch("src.api.ws_runner._wait_for_spotify_sync", side_effect=stop_after_first_sleep):
            await runner._sync_spotify_playback(ui)

        player_events = [event for event in ui.events if event.get("type") == "player"]
        self.assertTrue(player_events)
        state = player_events[-1]["state"]
        self.assertEqual(state["progress_source"], "spotify_live")
        self.assertEqual(state["progress_anchor_ms"], 200000)

    async def test_local_playback_sync_emits_authoritative_anchored_progress(self) -> None:
        runner = WebSocketRunner()
        ui = FakeUI()
        ui.closed = False
        playback = {
            "status": "success",
            "data": {
                "provider": "youtube",
                "source": "youtube",
                "player": "mpv",
                "session_id": "local-session",
                "name": "Song",
                "artist": "Artist",
                "album": "Album",
                "duration_ms": 180000,
                "progress_ms": 42000,
                "timestamp": 123456,
                "is_playing": True,
                "diagnostic_notice": "clock_drift",
            },
        }

        async def stop_after_first_wait(_ui: object, seconds: float) -> None:
            self.assertEqual(seconds, ws_runner.LOCAL_PLAYBACK_POLL_SECONDS)
            ui.closed = True

        async def call_inline(func: object, *args: object, **kwargs: object) -> object:
            return func(*args, **kwargs)  # type: ignore[operator]

        with patch("src.api.ws_runner.local_playback_status", return_value=playback), \
                patch("src.api.ws_runner._timestamp_ms", return_value=200000), \
                patch("src.api.ws_runner.asyncio.to_thread", side_effect=call_inline), \
                patch("src.api.ws_runner._wait_for_local_playback_sync", side_effect=stop_after_first_wait):
            await runner._sync_local_playback(ui)

        player_events = [event for event in ui.events if event.get("type") == "player"]
        self.assertEqual(len(player_events), 1)
        state = player_events[0]["state"]
        self.assertEqual(state["progress_ms"], 42000)
        self.assertEqual(state["progress_source"], "local_player")
        self.assertEqual(state["progress_anchor_ms"], 200000)
        self.assertFalse(state["progress_sync_lost"])
        self.assertEqual(state["diagnostic_notice"], "clock_drift")

    async def test_local_playback_sync_marks_cache_pause_as_buffering(self) -> None:
        runner = WebSocketRunner()
        ui = FakeUI()
        ui.closed = False
        playback = {
            "status": "success",
            "data": {
                "provider": "youtube",
                "source": "youtube",
                "player": "mpv",
                "session_id": "local-session",
                "name": "Song",
                "artist": "Artist",
                "album": "Album",
                "duration_ms": 180000,
                "progress_ms": 42000,
                "timestamp": 123456,
                "is_playing": True,
                "paused_for_cache": True,
            },
        }

        async def stop_after_first_wait(_ui: object, _seconds: float) -> None:
            ui.closed = True

        async def call_inline(func: object, *args: object, **kwargs: object) -> object:
            return func(*args, **kwargs)  # type: ignore[operator]

        with patch("src.api.ws_runner.local_playback_status", return_value=playback), \
                patch("src.api.ws_runner.asyncio.to_thread", side_effect=call_inline), \
                patch("src.api.ws_runner._wait_for_local_playback_sync", side_effect=stop_after_first_wait):
            await runner._sync_local_playback(ui)

        state = [event for event in ui.events if event.get("type") == "player"][-1]["state"]
        self.assertTrue(state["paused_for_cache"])
        self.assertEqual(state["playback_status"], "buffering")

    async def test_local_playback_sync_freezes_once_when_authoritative_status_is_lost(self) -> None:
        runner = WebSocketRunner()
        ui = FakeUI()
        ui.closed = False
        playing = {
            "status": "success",
            "data": {
                "provider": "youtube",
                "source": "youtube",
                "player": "mpv",
                "session_id": "local-session",
                "name": "Song",
                "artist": "Artist",
                "album": "Album",
                "duration_ms": 180000,
                "progress_ms": 42000,
                "timestamp": 123456,
                "is_playing": True,
            },
        }
        unavailable = {
            "status": "fail",
            "error_code": "PLAYBACK_STATUS_UNAVAILABLE",
            "message": "mpv IPC failed",
        }
        wait_count = 0

        async def stop_after_third_wait(_ui: object, _seconds: float) -> None:
            nonlocal wait_count
            wait_count += 1
            if wait_count == 3:
                ui.closed = True

        async def call_inline(func: object, *args: object, **kwargs: object) -> object:
            return func(*args, **kwargs)  # type: ignore[operator]

        with patch("src.api.ws_runner.local_playback_status", side_effect=[playing, unavailable, unavailable]), \
                patch("src.api.ws_runner._timestamp_ms", return_value=200000), \
                patch("src.api.ws_runner.asyncio.to_thread", side_effect=call_inline), \
                patch("src.api.ws_runner._wait_for_local_playback_sync", side_effect=stop_after_third_wait):
            await runner._sync_local_playback(ui)

        player_events = [event for event in ui.events if event.get("type") == "player"]
        self.assertEqual(len(player_events), 2)
        frozen = player_events[-1]["state"]
        self.assertEqual(frozen["progress_ms"], 42000)
        self.assertTrue(frozen["is_playing"])
        self.assertTrue(frozen["progress_sync_lost"])
        self.assertEqual(frozen["playback_status"], "syncing")
        self.assertFalse(any(event.get("type") == "chat" for event in ui.events))

    async def test_local_playback_sync_does_not_overwrite_spotify_mode(self) -> None:
        runner = WebSocketRunner()
        ui = FakeUI()
        ui.closed = False
        setattr(ui, "_spotify_mode", {"enabled": True, "device_id": "desktop"})

        async def stop_after_first_wait(_ui: object, _seconds: float) -> None:
            ui.closed = True

        with patch("src.api.ws_runner.local_playback_status") as playback, \
                patch("src.api.ws_runner._wait_for_local_playback_sync", side_effect=stop_after_first_wait):
            await runner._sync_local_playback(ui)

        playback.assert_not_called()
        self.assertFalse(any(event.get("type") == "player" for event in ui.events))

    async def test_volume_command_is_not_user_accessible_from_chat(self) -> None:
        runner = WebSocketRunner()
        runner._run_agent_turn = AsyncMock()
        ui = FakeUI()

        with patch("src.api.ws_runner.registry.invoke") as invoke:
            await runner._handle_user_input(ui, "/volume 50")

        invoke.assert_not_called()
        self.assertFalse(runner._run_agent_turn.called)
        self.assertTrue(any("keyboard shortcut" in str(event.get("text")) for event in ui.events))

    async def test_internal_volume_command_controls_local_playback_without_agent_turn(self) -> None:
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
            await runner._handle_internal_command(ui, "/volume 50")

        self.assertFalse(runner._run_agent_turn.called)
        invoke.assert_called_once_with("local_playback_volume", {"volume_percent": 50})
        player_events = [event for event in ui.events if event.get("type") == "player"]
        self.assertEqual(player_events[-1]["state"]["volume_percent"], 50)

    async def test_internal_volume_command_rejects_invalid_argument(self) -> None:
        """Verifies that volume command rejects invalid argument behaves as expected.

        Typical use: Use this in automated tests when guarding the volume command rejects invalid argument behavior against regressions.

        Example: test_volume_command_rejects_invalid_argument() -> passes without assertion failures when the behavior remains correct.
        """
        runner = WebSocketRunner()
        runner._run_agent_turn = AsyncMock()
        ui = FakeUI()

        with patch("src.api.ws_runner.registry.invoke") as invoke:
            await runner._handle_internal_command(ui, "/volume loud")

        invoke.assert_not_called()
        self.assertFalse(runner._run_agent_turn.called)
        activity_events = [event for event in ui.events if event.get("type") == "activity"]
        self.assertEqual(activity_events[-1]["status"], "error")
        self.assertIn("/volume <0-100>", activity_events[-1]["detail"])

    async def test_player_command_opens_backend_choice_panel_without_agent_turn(self) -> None:
        """Verifies that player command opens backend choice panel without agent turn behaves as expected.

        Typical use: Use this in automated tests when guarding the player command opens backend choice panel behavior against regressions.

        Example: test_player_command_opens_backend_choice_panel_without_agent_turn() -> passes without assertion failures when the behavior remains correct.
        """
        runner = WebSocketRunner()
        runner._run_agent_turn = AsyncMock()
        ui = FakeUI()

        with patch("src.api.ws_runner.registry.invoke") as invoke:
            await runner._handle_user_input(ui, "/player")

        self.assertFalse(runner._run_agent_turn.called)
        invoke.assert_not_called()
        confirm_events = [event for event in ui.events if event.get("type") == "confirm"]
        self.assertTrue(confirm_events)
        self.assertEqual(confirm_events[-1]["tool_name"], "local_playback_player")
        self.assertEqual(confirm_events[-1]["tool_args"]["stage"], "player_backend_selection")
        self.assertEqual(
            [choice["value"] for choice in confirm_events[-1]["choices"]],
            ["managed:mpv", "managed:cvlc", "deny"],
        )
        self.assertEqual([choice["label"] for choice in confirm_events[-1]["choices"]], ["mpv", "VLC", "Cancel"])
        self.assertEqual(
            [choice.get("description") for choice in confirm_events[-1]["choices"]],
            [
                "Managed playback with Sonex controls.",
                "Managed playback with Sonex controls.",
                None,
            ],
        )
        self.assertTrue(getattr(ui, "_player_backend_selection"))

    async def test_player_command_ignores_typed_backend_and_opens_same_panel(self) -> None:
        """Verifies that player command ignores typed backend and opens same panel behaves as expected.

        Typical use: Use this in automated tests when guarding the player command ignores typed backend behavior against regressions.

        Example: test_player_command_ignores_typed_backend_and_opens_same_panel() -> passes without assertion failures when the behavior remains correct.
        """
        runner = WebSocketRunner()
        runner._run_agent_turn = AsyncMock()
        ui = FakeUI()

        with patch("src.api.ws_runner.registry.invoke") as invoke:
            await runner._handle_user_input(ui, "/player vlc")

        invoke.assert_not_called()
        self.assertFalse(runner._run_agent_turn.called)
        confirm_events = [event for event in ui.events if event.get("type") == "confirm"]
        self.assertTrue(confirm_events)
        self.assertEqual(
            [choice["value"] for choice in confirm_events[-1]["choices"]],
            ["managed:mpv", "managed:cvlc", "deny"],
        )
        self.assertFalse([event for event in ui.events if event.get("status") == "error"])

    async def test_player_detection_is_cached_for_the_websocket_session(self) -> None:
        runner = WebSocketRunner()
        ui = FakeUI()

        await runner._handle_user_input(ui, "/player")
        await runner._handle_user_input(ui, "/player")

        self._player_detection.assert_called_once_with()
        confirm_events = [event for event in ui.events if event.get("type") == "confirm"]
        self.assertEqual(len(confirm_events), 2)

    async def test_player_command_reports_when_no_supported_application_is_installed(self) -> None:
        runner = WebSocketRunner()
        ui = FakeUI()
        self._player_detection.return_value = []

        await runner._handle_user_input(ui, "/player")

        self.assertFalse([event for event in ui.events if event.get("type") == "confirm"])
        self.assertIsNone(getattr(ui, "_player_backend_selection", None))
        self.assertTrue(any(
            event.get("type") == "activity"
            and event.get("status") == "error"
            and "Install mpv, VLC" in str(event.get("detail"))
            for event in ui.events
        ))

    async def test_player_backend_choice_persists_manager_selection(self) -> None:
        runner = WebSocketRunner()
        runner._run_agent_turn = AsyncMock()
        ui = FakeUI()
        await runner._handle_user_input(ui, "/player")
        session = getattr(ui, "_player_backend_selection")
        with patch("src.api.ws_runner.registry.invoke") as invoke:
            await session.handle_choice("managed:cvlc")

        invoke.assert_not_called()
        self.assertEqual(session.manager.default_sink_id, "managed:cvlc")
        self.assertIsNone(getattr(ui, "_player_backend_selection"))
        activity_events = [event for event in ui.events if event.get("type") == "activity"]
        self.assertEqual(activity_events[-1]["status"], "success")
        self.assertIn("VLC", activity_events[-1]["detail"])
        self.assertTrue(any(
            event.get("type") == "chat"
            and event.get("role") == "agent"
            and event.get("tone") == "system"
            and event.get("text") == "player: VLC"
            for event in ui.events
        ))
        self.assertFalse(any(
            event.get("tone") == "system"
            and str(event.get("text", "")).startswith("on playing:")
            for event in ui.events
        ))

    async def test_player_backend_confirm_result_from_websocket_persists_selection(self) -> None:
        runner = WebSocketRunner()
        ws = PlayerBackendWebSocket()
        async def idle_sync(_ui: object) -> None:
            while True:
                await asyncio.sleep(60)

        with patch.object(runner, "_handle_startup_auth", new=AsyncMock()), \
                patch.object(runner, "_restore_persistent_spotify_mode", new=AsyncMock()), \
                patch.object(runner, "_sync_spotify_playback", side_effect=idle_sync), \
                patch("src.api.ws_runner.registry.invoke") as invoke:
            await runner.handle_ws(ws)  # type: ignore[arg-type]

        invoke.assert_not_called()
        self.assertEqual(
            runner._player_sink_manager_instance.default_sink_id,  # type: ignore[union-attr]
            "managed:cvlc",
        )
        self.assertTrue(any(event.get("type") == "confirm" for event in ws.sent))
        queued = []
        while not runner._confirm_queue.empty():
            queued.append(runner._confirm_queue.get_nowait())
        self.assertNotIn("managed:cvlc", [decision for _confirm_id, decision in queued])

    async def test_player_backend_cancel_does_not_invoke_tool(self) -> None:
        runner = WebSocketRunner()
        ui = FakeUI()

        await runner._handle_user_input(ui, "/player mpv")
        session = getattr(ui, "_player_backend_selection")
        with patch("src.api.ws_runner.registry.invoke") as invoke:
            await session.handle_choice("deny")

        invoke.assert_not_called()
        self.assertIsNone(getattr(ui, "_player_backend_selection"))
        self.assertTrue(any("unchanged" in str(event.get("text")) for event in ui.events))
        self.assertFalse(any(
            event.get("tone") == "system"
            and str(event.get("text", "")).startswith("player:")
            for event in ui.events
        ))

    async def test_player_backend_invalid_choice_has_no_system_feedback(self) -> None:
        runner = WebSocketRunner()
        ui = FakeUI()

        await runner._handle_user_input(ui, "/player")
        session = getattr(ui, "_player_backend_selection")
        with patch("src.api.ws_runner.registry.invoke") as invoke:
            await session.handle_choice("not-a-player")

        invoke.assert_not_called()
        self.assertTrue(any(
            event.get("type") == "chat"
            and event.get("text") == "Default player unchanged."
            for event in ui.events
        ))
        self.assertFalse(any(
            event.get("tone") == "system"
            and str(event.get("text", "")).startswith("player:")
            for event in ui.events
        ))

    async def test_player_backend_failure_has_no_system_feedback(self) -> None:
        runner = WebSocketRunner()
        ui = FakeUI()
        await runner._handle_user_input(ui, "/player")
        session = getattr(ui, "_player_backend_selection")
        session.manager.select = AsyncMock(return_value=PlayerSelectionResult(
            status="failed",
            sink_id="managed:mpv",
            message="Backend selection failed.",
            previous_sink_id=None,
        ))
        await session.handle_choice("managed:mpv")

        self.assertFalse(any(
            event.get("tone") == "system"
            and str(event.get("text", "")).startswith("player:")
            for event in ui.events
        ))

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

        with patch("src.api.ws_runner.remember_recent_track"), patch("src.api.ws_runner.remember_playback_track") as remember_playback_track:
            await runner._sync_tool_result_ui(ui, "play_youtube_song", result)

        player_events = [event for event in ui.events if event.get("type") == "player"]
        cover_events = [event for event in ui.events if event.get("type") == "cover"]
        self.assertTrue(player_events)
        self.assertEqual(player_events[-1]["state"]["provider"], "youtube")
        self.assertEqual(player_events[-1]["state"]["name"], "Song")
        self.assertEqual(player_events[-1]["state"]["youtube_url"], "https://www.youtube.com/watch?v=abc")
        self.assertIsNone(player_events[-1]["state"]["apple_music_url"])
        remember_playback_track.assert_called_once()
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

        with patch("src.api.ws_runner.remember_recent_track") as remember_recent_track, patch("src.api.ws_runner.remember_playback_track") as remember_playback_track:
            await runner._sync_tool_result_ui(ui, "play_youtube_song", result)

        self.assertFalse([event for event in ui.events if event.get("type") == "player"])
        self.assertFalse([event for event in ui.events if event.get("type") == "queue"])
        self.assertFalse([event for event in ui.events if event.get("type") == "cover"])
        remember_recent_track.assert_not_called()
        remember_playback_track.assert_not_called()

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
            await runner._handle_user_input(ui, "play Song Artist")
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
            await runner._handle_user_input(ui, "play Song Artist")
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
        self.assertIn("Official", confirm_events[-1]["choices"][0]["description"])
        self.assertEqual(confirm_events[-1]["choices"][-1]["label"], "Not found? Type to supplement.")
        self.assertEqual(confirm_events[-1]["choices"][-1]["input"]["placeholder"], "")
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
            await runner._handle_user_input(ui, "play Song Artist")
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
            await runner._handle_user_input(ui, "play Song Artist")
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
        self.assertEqual(confirm_events[-1]["choices"][0]["display"], {
            "kind": "music_candidate",
            "artist": "Artist 0",
            "album": "Album 0",
            "title": "Song 0",
        })
        self.assertEqual(confirm_events[-1]["choices"][0]["label"], f"{'Artist 0'.ljust(24)} {'Album 0'.ljust(24)} Song 0")
        self.assertNotIn("3:00", confirm_events[-1]["choices"][0]["description"])
        self.assertEqual(confirm_events[-1]["choices"][-1]["value"], "refine_song_metadata_query")
        self.assertEqual(confirm_events[-1]["choices"][-1]["label"], "Not found? Type to supplement.")
        self.assertEqual(confirm_events[-1]["choices"][-1]["input"]["placeholder"], "")
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
        candidate_feedback = (
            "track: Canonical Song\n"
            "artist: Canonical Artist\n"
            "album: Canonical Album\n"
            "source: iTunes"
        )

        def play_candidate_with_feedback(
            candidate: dict[str, object],
            *,
            player: str,
        ) -> dict[str, object]:
            self.assertTrue(any(
                event.get("type") == "chat"
                and event.get("role") == "agent"
                and event.get("text") == candidate_feedback
                and event.get("tone") is None
                for event in ui.events
            ))
            return playback_result

        with patch("src.api.ws_runner.search_local_file", return_value="No local files found related to 'messy query'."), \
             patch("src.api.ws_runner.search_track_metadata_candidates", return_value={"candidates": [song_candidate], "source_attempts": []}):
            await runner._handle_user_input(ui, "play messy query")
        session = getattr(ui, "_play_selection")
        with patch("src.api.ws_runner.search_online_audio_candidates", return_value=[online_candidate]) as online_search, \
             patch("src.api.ws_runner.play_online_audio_candidate", side_effect=play_candidate_with_feedback) as play_candidate, \
             patch("src.api.ws_runner.asyncio.to_thread", side_effect=_to_thread_inline):
            await session.handle_choice("song_candidate:0")

        online_search.assert_called_once()
        self.assertEqual(online_search.call_args.args[0], "Canonical Artist Canonical Song")
        self.assertEqual(online_search.call_args.args[1], 5)
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
        chat_events = [
            event for event in ui.events
            if event.get("type") == "chat"
        ]
        self.assertTrue(any(
            event.get("role") == "agent"
            and event.get("text") == candidate_feedback
            and event.get("tone") is None
            for event in chat_events
        ))
        self.assertFalse(any(
            event.get("tone") == "system"
            and str(event.get("text", "")).startswith("on playing:")
            for event in chat_events
        ))

    async def test_song_candidate_direct_success_announces_playing_once(self) -> None:
        runner = WebSocketRunner()
        ui = FakeUI()
        song_candidate = {
            "metadata_source": "itunes",
            "name": "Sorry",
            "artist": "方大同",
            "album": "未来",
        }
        online_candidate = {
            "cache_id": "audio-1",
            "name": "Sorry",
            "artist": "方大同",
        }
        success = {
            "status": "success",
            "tool": "play_online_audio",
            "message": "Playing started.",
            "data": {
                "name": "Sorry",
                "player": "mpv",
                "is_playing": True,
            },
        }

        with patch(
            "src.api.ws_runner.search_local_file",
            return_value="No local files found.",
        ), patch(
            "src.api.ws_runner.search_track_metadata_candidates",
            return_value={"candidates": [song_candidate], "source_attempts": []},
        ), patch(
            "src.api.ws_runner.asyncio.to_thread",
            side_effect=_to_thread_inline,
        ):
            await runner._handle_user_input(ui, "play Sorry")

        session = getattr(ui, "_play_selection")
        with patch(
            "src.api.ws_runner.resolve_online_playback_metadata",
            return_value={},
        ), patch(
            "src.api.ws_runner.search_online_audio_candidates",
            return_value=[online_candidate],
        ), patch(
            "src.api.ws_runner.play_online_audio_candidate",
            return_value=success,
        ), patch(
            "src.api.ws_runner.upsert_cached_song",
        ), patch(
            "src.api.ws_runner.asyncio.to_thread",
            side_effect=_to_thread_inline,
        ):
            await session.handle_choice("song_candidate:0")

        chat_events = [
            event for event in ui.events
            if event.get("type") == "chat"
        ]
        self.assertEqual(
            [
                event.get("text")
                for event in chat_events
                if str(event.get("text", "")).startswith("track:")
            ],
            ["track: Sorry\nartist: 方大同\nalbum: 未来\nsource: iTunes"],
        )
        self.assertEqual(
            [
                event.get("text")
                for event in chat_events
                if event.get("tone") == "system"
                and str(event.get("text", "")).startswith("on playing:")
            ],
            ["on playing: Sorry"],
        )
        self.assertFalse(any(
            str(event.get("text", "")).startswith("player:")
            for event in chat_events
        ))

    async def test_song_candidate_player_confirmation_reports_choice_and_playing(
        self,
    ) -> None:
        runner = WebSocketRunner()
        ui = FakeUI()
        pending = {
            "status": "requires_player_confirm",
            "tool": "play_online_audio",
            "message": "Confirm player.",
            "data": {
                "name": "Sorry",
                "player": "auto",
                "choices": [
                    {"value": "mpv", "label": "mpv"},
                    {"value": "cvlc", "label": "VLC"},
                    {"value": "deny", "label": "取消"},
                ],
            },
        }
        success = {
            "status": "success",
            "tool": "play_online_audio",
            "message": "Playing started.",
            "data": {
                "name": "Sorry",
                "player": "mpv",
                "is_playing": True,
            },
        }
        session = await _start_song_candidate_player_confirmation(
            runner,
            ui,
            pending,
        )

        with patch(
            "src.api.ws_runner.complete_player_confirm",
            return_value=success,
        ), patch(
            "src.api.ws_runner.upsert_cached_song",
        ), patch(
            "src.api.ws_runner.asyncio.to_thread",
            side_effect=_to_thread_inline,
        ):
            await session.handle_choice("mpv")

        feedback = [
            (event.get("tone"), event.get("text"))
            for event in ui.events
            if event.get("type") == "chat"
            and (
                str(event.get("text", "")).startswith("track:")
                or str(event.get("text", "")).startswith("player:")
                or str(event.get("text", "")).startswith("on playing:")
            )
        ]
        self.assertEqual(
            feedback,
            [
                (
                    None,
                    "track: Sorry\n"
                    "artist: 方大同\n"
                    "album: 未来\n"
                    "source: iTunes",
                ),
                (None, "player: mpv"),
                ("system", "on playing: Sorry"),
            ],
        )

    async def test_song_candidate_player_non_success_choices_have_no_feedback(
        self,
    ) -> None:
        pending = {
            "status": "requires_player_confirm",
            "tool": "play_online_audio",
            "message": "Confirm player.",
            "data": {
                "name": "Sorry",
                "player": "auto",
                "choices": [
                    {"value": "mpv", "label": "mpv"},
                    {"value": "deny", "label": "取消"},
                ],
            },
        }

        for label, decision, expired, expected_detail in (
            ("deny", "deny", False, "Playback failed."),
            ("invalid", "not-a-player", False, "Playback failed."),
            ("expired", "mpv", True, "Player confirmation expired."),
        ):
            with self.subTest(label=label):
                runner = WebSocketRunner()
                ui = FakeUI()
                session = await _start_song_candidate_player_confirmation(
                    runner,
                    ui,
                    pending,
                )
                if expired:
                    session.pending_player_confirm_result = None

                with patch(
                    "src.api.ws_runner.asyncio.to_thread",
                    side_effect=_to_thread_inline,
                ):
                    if expired:
                        await session._complete_player_confirmation(decision)
                    else:
                        await session.handle_choice(decision)

                feedback = [
                    str(event.get("text", ""))
                    for event in ui.events
                    if event.get("type") == "chat"
                    and (
                        str(event.get("text", "")).startswith("player:")
                        or str(event.get("text", "")).startswith("on playing:")
                    )
                ]
                self.assertEqual(feedback, [])
                self.assertTrue(any(
                    event.get("type") == "activity"
                    and event.get("status") == "error"
                    and event.get("detail") == expected_detail
                    for event in ui.events
                ))

    async def test_song_candidate_player_failure_has_no_success_feedback(
        self,
    ) -> None:
        runner = WebSocketRunner()
        ui = FakeUI()
        pending = {
            "status": "requires_player_confirm",
            "tool": "play_online_audio",
            "message": "Confirm player.",
            "data": {
                "name": "Sorry",
                "player": "auto",
                "choices": [
                    {"value": "mpv", "label": "mpv"},
                    {"value": "deny", "label": "取消"},
                ],
            },
        }
        failure = {
            "status": "fail",
            "tool": "play_online_audio",
            "message": "Player launch failed.",
            "error_code": "PLAYBACK_FAILED",
            "data": {"name": "Sorry"},
        }
        session = await _start_song_candidate_player_confirmation(
            runner,
            ui,
            pending,
        )

        with patch(
            "src.api.ws_runner.complete_player_confirm",
            return_value=failure,
        ), patch(
            "src.api.ws_runner.asyncio.to_thread",
            side_effect=_to_thread_inline,
        ):
            await session.handle_choice("mpv")

        feedback_text = [
            str(event.get("text", ""))
            for event in ui.events
            if event.get("type") == "chat"
        ]
        self.assertIn(
            "track: Sorry\n"
            "artist: 方大同\n"
            "album: 未来\n"
            "source: iTunes",
            feedback_text,
        )
        self.assertFalse(any(
            text.startswith("player:") or text.startswith("on playing:")
            for text in feedback_text
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
            await runner._handle_user_input(ui, "play messy query")
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
            await runner._handle_user_input(ui, "play Song Artist")
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
        self.assertEqual(confirm_events[-1]["choices"][0]["label"], f"{'Artist'.ljust(24)} {'Album'.ljust(24)} Refined")
        self.assertNotIn("3:01", confirm_events[-1]["choices"][0]["description"])

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
            await runner._handle_user_input(ui, "play raw query")
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
            await runner._handle_user_input(ui, "play Song Artist")
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
            await runner._handle_user_input(ui, "play Song Artist")
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
            await runner._handle_user_input(ui, "play Song Artist")
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
            "message": "Sonex wants to open auto local player (mpv default).",
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
                "player_label": "auto local player (mpv default)",
                "confirm_message": "Sonex wanna open auto local player (mpv default), confirm?",
                "choices": [
                    {"value": "mpv", "label": "mpv", "description": "default controllable backend for smoother background playback."},
                    {"value": "cvlc", "label": "VLC", "description": "manual diagnostic backend; use only when you explicitly want VLC."},
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
            await runner._handle_user_input(ui, "play Song Artist")
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
             patch.object(runner, "_restore_persistent_spotify_mode", new=AsyncMock()), \
             patch.object(runner, "_sync_spotify_playback", side_effect=idle_sync), \
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

    async def test_online_play_choice_reports_failure_only_as_caution(self) -> None:
        """Verify a terminal playback failure emits one Caution and no Agent copy.

        This covers the aggregated Jamendo/Audius/YouTube failure shown in chat.
        """
        runner = WebSocketRunner()
        ui = FakeUI()
        result = {
            "status": "fail",
            "tool": "play_youtube_song",
            "message": (
                "Jamendo returned no credible matches. "
                "Audius returned no credible matches. "
                "Sonex fell back to YouTube. "
                "YouTube failed: YouTube is temporarily unavailable; playback is cooling down."
            ),
            "error_code": "ONLINE_AUDIO_RESOLVE_FAILED",
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
        session = ws_runner.PlaySelectionSession(ui, runner, "Song Artist")
        with patch(
            "src.api.ws_runner.play_online_audio_candidate",
            return_value=result,
        ), patch(
            "src.api.ws_runner.asyncio.to_thread",
            side_effect=_to_thread_inline,
        ):
            await session._play_online_audio_candidate(candidate)

        self.assertFalse([event for event in ui.events if event.get("type") == "player"])
        expected = (
            "Playback failed. Technical detail: "
            "Jamendo returned no credible matches. "
            "Audius returned no credible matches. "
            "Sonex fell back to YouTube. "
            "YouTube failed: YouTube is temporarily unavailable; playback is cooling down."
        )
        self.assertFalse(any(
            event.get("type") == "chat"
            and event.get("role") == "agent"
            and event.get("text") == expected
            for event in ui.events
        ))
        self.assertEqual(
            [
                event.get("message")
                for event in ui.events
                if event.get("type") == "error"
                and event.get("message") == expected
            ],
            [expected],
        )

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

    async def test_agent_turn_reports_live_planning_status_without_run_metrics(self) -> None:
        """Verifies that agent turn reports live planning status without run metrics.

        Typical use: Use this in automated tests when guarding planning status against old token/time counters.

        Example: test_agent_turn_reports_live_planning_status_without_run_metrics() -> passes without assertion failures when the behavior remains correct.
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
        self.assertNotIn("tokens", early_status_events[-1])
        self.assertNotIn("elapsed_ms", early_status_events[-1])
        self.assertTrue(
            [
                event
                for event in early_activity_events
                if event.get("title") == "Planning" and event.get("status") == "pending"
            ]
        )

        status_events = [event for event in ui.events if event.get("type") == "status"]
        self.assertTrue(status_events)
        self.assertFalse(any("tokens" in event or "elapsed_ms" in event for event in status_events))
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
        agent_answers = [
            event for event in ui.events
            if event.get("type") == "chat" and event.get("text") == "done"
        ]
        self.assertEqual(len(agent_answers), 1)
        self.assertIsNone(agent_answers[0].get("tone"))
        working_events = [
            event for event in ui.events
            if event.get("type") == "agent_working_state"
        ]
        self.assertEqual(
            [event.get("active") for event in working_events],
            [True, False],
        )

    async def test_recommend_failure_emits_one_caution_and_no_agent_error_copy(self) -> None:
        runner = WebSocketRunner()
        ui = FakeUI()
        failure = {
            "status": "fail",
            "tool": "Recommend",
            "message": "No credible recommendations are available from connected providers.",
            "error_code": "NO_RECOMMENDATIONS",
            "data": {"tracks": [], "failed": [], "skipped": []},
        }

        def recommendation_events(*_args: object, **_kwargs: object):
            yield AgentState(type="tool", tool="Recommend", result=failure)
            yield AgentState(type="complete", content="")

        intent = CommandIntent(
            command="recommend",
            raw="/recommend",
            args="",
            intent_prompt="Call Recommend once.",
            allowed_tools=("Recommend",),
            max_tool_calls=1,
        )
        with patch("src.api.ws_runner.agent_loop", recommendation_events):
            await runner._run_agent_turn(ui, "/recommend", command_intent=intent)

        caution = [
            event for event in ui.events
            if event.get("type") == "error"
            and "Recommendation failed. Technical detail:" in str(event.get("message"))
        ]
        agent_copies = [
            event for event in ui.events
            if event.get("type") == "chat"
            and event.get("role") == "agent"
            and "No credible recommendations" in str(event.get("text"))
        ]
        self.assertEqual(len(caution), 1)
        self.assertEqual(agent_copies, [])

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

    async def test_agent_turn_appends_approval_before_rich_tool_batch_message(self) -> None:
        runner = WebSocketRunner()
        ui = FakeUI()
        commands = ["cd src/cli-ui", "npm test"]
        calls = [
            ToolAction("Read", {"query": "preferences"}),
            ToolAction("Bash", {"commands": commands}),
        ]

        def approved_agent_loop(user_input: str, tools: object):
            yield AgentState(type="status", content="planning")
            yield AgentState(
                type="tool_approved",
                calls=calls,
                args={"commands": commands},
            )
            yield AgentState(type="tool_batch", calls=calls)

        with patch("src.api.ws_runner.agent_loop", approved_agent_loop):
            await runner._run_agent_turn(ui, "build")

        chat_events = [
            event for event in ui.events if event.get("type") == "chat"
        ]
        self.assertEqual(chat_events[0]["tone"], "system")
        self.assertIn("You confirmed running 'npm test' this time.", chat_events[0]["text"])
        self.assertEqual(
            chat_events[1]["text"],
            "Read preferences\n\nBash cd src/cli-ui\n     npm test",
        )
        self.assertTrue(chat_events[1].get("segments"))

    async def test_agent_turn_flushes_tool_chat_before_execution_resumes(self) -> None:
        runner = WebSocketRunner()
        order: list[str] = []

        class OrderedUI(FakeUI):
            async def append_agent_message(
                self,
                text: str,
                *,
                segments: object | None = None,
            ) -> None:
                order.append("tool message")
                await super().append_agent_message(text, segments=segments)

        ui = OrderedUI()
        calls = [ToolAction("Read", {"query": "preferences"})]

        def gated_agent_loop(user_input: str, tools: object):
            yield AgentState(type="tool_batch", calls=calls)
            order.append("execution resumed")

        with patch("src.api.ws_runner.agent_loop", gated_agent_loop):
            await runner._run_agent_turn(ui, "read")

        self.assertEqual(order, ["tool message", "execution resumed"])

    async def test_spotify_sync_reports_premium_failure_once_in_chat(self) -> None:
        """Verifies that spotify sync reports premium failure once in chat behaves as expected.

        Typical use: Use this in automated tests when guarding the spotify sync reports premium failure once in chat behavior against regressions.

        Example: test_spotify_sync_reports_premium_failure_once_in_chat() -> passes without assertion failures when the behavior remains correct.
        """
        runner = WebSocketRunner()
        ui = FakeUI()
        ui.closed = False
        setattr(ui, "_spotify_mode", {"enabled": True, "device_id": "desktop"})
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

    async def test_natural_language_playback_routes_to_agent_call_surface(self) -> None:
        runner = WebSocketRunner()
        runner._run_agent_turn = AsyncMock()
        ui = FakeUI()

        with patch(
            "src.api.ws_runner._llm_auth_ready",
            return_value=(True, "openai", None),
        ):
            await runner._handle_user_input(ui, "play Blue in Green")
            await asyncio.sleep(0)

        runner._run_agent_turn.assert_awaited_once()
        intent = runner._run_agent_turn.await_args.kwargs["command_intent"]
        self.assertIn("Call", intent.allowed_tools)
        self.assertNotIn("spotify_play", intent.allowed_tools)
        self.assertIn("playback.select", intent.intent_prompt)
        self.assertFalse(any(event.get("type") == "confirm" for event in ui.events))

    async def test_spotify_command_in_mode_opens_exact_exit_panel(self) -> None:
        runner = WebSocketRunner()
        runner._exit_spotify_mode = AsyncMock()
        ui = FakeUI()
        setattr(
            ui,
            "_spotify_mode",
            {"enabled": True, "device_id": "desktop"},
        )

        await runner._handle_user_input(ui, "/spotify")

        confirm = [event for event in ui.events if event.get("type") == "confirm"][-1]
        self.assertEqual(confirm["tool_name"], "provider_mode_exit")
        self.assertEqual(confirm["message"], "Exit Spotify Mode?")
        self.assertEqual(
            confirm["warning"],
            "Running '/spotify' will exit Spotify Mode. Continue?",
        )
        self.assertTrue(confirm["hide_hint"])
        self.assertEqual(
            [choice["label"] for choice in confirm["choices"]],
            ["Yes, I insist", "No, return"],
        )
        self.assertTrue(getattr(ui, "_spotify_mode")["enabled"])

        handled = await runner._handle_confirm_result(
            ui,
            confirm["id"],
            "confirm_exit",
        )
        self.assertTrue(handled)
        runner._exit_spotify_mode.assert_awaited_once_with(ui)

    async def test_spotify_off_is_rejected_as_argument(self) -> None:
        runner = WebSocketRunner()
        ui = FakeUI()
        setattr(ui, "_spotify_mode", {"enabled": True})

        await runner._handle_user_input(ui, "/spotify off")

        self.assertTrue(getattr(ui, "_spotify_mode")["enabled"])
        self.assertTrue(
            any(event.get("text") == "Usage: /spotify" for event in ui.events)
        )

    async def test_connect_panel_lists_initial_agent_providers_without_emoji(self) -> None:
        runner = WebSocketRunner()
        ui = FakeUI()

        with self._isolated_auth_env():
            await runner._handle_user_input(ui, "/connect")

        confirm = [event for event in ui.events if event.get("type") == "confirm"][-1]
        labels = [choice["label"] for choice in confirm["choices"]]
        self.assertEqual(
            labels,
            [
                "Spotify",
                "Apple Music",
                "NetEase Cloud Music",
                "Jamendo",
                "Audius",
                "Cancel",
            ],
        )
        self.assertFalse(any(label.startswith(("🎵", "🍎", "🟢")) for label in labels))


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


async def _start_song_candidate_player_confirmation(
    runner: WebSocketRunner,
    ui: FakeUI,
    pending: dict[str, object],
) -> object:
    song_candidate = {
        "metadata_source": "itunes",
        "name": "Sorry",
        "artist": "方大同",
        "album": "未来",
    }
    online_candidate = {
        "cache_id": "audio-1",
        "name": "Sorry",
        "artist": "方大同",
    }
    with patch(
        "src.api.ws_runner.search_local_file",
        return_value="No local files found.",
    ), patch(
        "src.api.ws_runner.search_track_metadata_candidates",
        return_value={"candidates": [song_candidate], "source_attempts": []},
    ), patch(
        "src.api.ws_runner.asyncio.to_thread",
        side_effect=_to_thread_inline,
    ):
        await runner._handle_user_input(ui, "play Sorry")

    session = getattr(ui, "_play_selection")
    with patch(
        "src.api.ws_runner.resolve_online_playback_metadata",
        return_value={},
    ), patch(
        "src.api.ws_runner.search_online_audio_candidates",
        return_value=[online_candidate],
    ), patch(
        "src.api.ws_runner.play_online_audio_candidate",
        return_value=pending,
    ), patch(
        "src.api.ws_runner.asyncio.to_thread",
        side_effect=_to_thread_inline,
    ):
        await session.handle_choice("song_candidate:0")
    return session


async def _to_thread_inline(fn, /, *args, **kwargs):
    """Verifies that to thread inline behaves as expected.

    Typical use: Use this in automated tests when guarding the to thread inline behavior against regressions.

    Example: _to_thread_inline() -> passes without assertion failures when the behavior remains correct.
    """
    return fn(*args, **kwargs)


def _metadata_result(query: str) -> dict[str, object]:
    """Return one deterministic metadata candidate for playback-routing tests."""
    return {
        "candidates": [
            {
                "id": f"metadata:{query}",
                "metadata_source": "itunes",
                "provider": "itunes",
                "name": query,
                "artist": "Artist",
                "album": "Album",
            }
        ],
        "source_attempts": [],
    }


if __name__ == "__main__":
    unittest.main()
