"""Focused contracts for Apple Mode lifecycle, matching, and token handling."""

from __future__ import annotations

import asyncio
import os
import tempfile
import time
import unittest
from unittest.mock import patch

from src.apple_mode.companion import (
    AppleCompanionSnapshot,
    AppleCompanionUnauthorized,
    MusicKitCompanion,
)
from src.apple_mode.matching import AppleCandidateDecision, rank_apple_candidates
from src.apple_mode.provider_mode import (
    ProviderMode,
    ProviderModeCoordinator,
    ProviderModeState,
    load_provider_mode_intent,
    save_provider_mode_intent,
)
from src.apple_mode.token_provider import (
    DeveloperTokenLease,
    DeveloperTokenManager,
    DeveloperTokenError,
    HttpDeveloperTokenProvider,
    configured_apple_token_broker_url,
    developer_token_provider_from_env,
    save_apple_token_broker_url,
)
from src.apple_mode.service import AppleEntryStart, AppleModeService
from src.ws.runner import WebSocketRunner


class FakeTokenProvider:
    def __init__(self, leases: list[DeveloperTokenLease | Exception]) -> None:
        self.leases = list(leases)
        self.calls = 0

    async def fetch(self) -> DeveloperTokenLease:
        self.calls += 1
        value = self.leases.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


class FakeAppleService:
    def __init__(self, *, fail_entry: bool = False) -> None:
        self.fail_entry = fail_entry
        self.snapshot = AppleCompanionSnapshot(
            connected=True,
            authorized=True,
            can_play=True,
            storefront="hk",
            connection_status="ready",
        )
        self.exit_calls = 0

    async def begin_entry(self, *, open_browser: bool) -> AppleEntryStart:
        if self.fail_entry:
            raise RuntimeError("broker unavailable")
        return AppleEntryStart("http://127.0.0.1:1234/#session=redacted", open_browser, True)

    async def complete_entry(self) -> AppleCompanionSnapshot:
        return self.snapshot

    async def exit_mode(self) -> None:
        self.exit_calls += 1

    def player_state(self) -> dict[str, object]:
        return {}

    def queue_tracks(self) -> list[dict[str, object]]:
        return []


class FakeWebSocket:
    def __init__(self) -> None:
        self.messages: list[dict[str, object]] = []

    async def send_json(self, message: dict[str, object]) -> None:
        self.messages.append(message)


class FakeSearchCompanion:
    def __init__(self) -> None:
        self.snapshot = AppleCompanionSnapshot()
        self.search_calls = 0
        self.refreshed: list[DeveloperTokenLease] = []

    async def search(self, query: str, *, limit: int) -> list[dict[str, object]]:
        self.search_calls += 1
        if self.search_calls == 1:
            raise AppleCompanionUnauthorized("HTTP 401")
        return [{"id": "track", "name": query, "artist": "Artist"}]

    async def update_developer_token(self, lease: DeveloperTokenLease) -> None:
        self.refreshed.append(lease)


class FakeModeUI:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []
        self.transcript: list[dict[str, str]] = []
        self.closed = False

    async def _send(self, event: dict[str, object]) -> None:
        self.events.append(event)

    async def append_activity(self, **event: object) -> str:
        self.events.append({"type": "activity", **event})
        return "activity"

    async def append_agent_message(self, text: str) -> None:
        self.transcript.append({"role": "agent", "content": text})

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

    async def send_cover(self, url: str) -> None:
        self.events.append({"type": "cover", "url": url})

    async def send_auth_setup(self, **event: object) -> None:
        self.events.append({"type": "auth_setup", **event})


class AppleModeMatchingTests(unittest.TestCase):
    def test_structured_chinese_query_auto_selects_exact_track(self) -> None:
        ranked = rank_apple_candidates(
            "track: 愛不來 (feat. MISS KO) artist: 方大同 album: 危險世界 source: iTunes",
            [
                {
                    "id": "right",
                    "name": "愛不來 (feat. MISS KO)",
                    "artist": "方大同",
                    "album": "危險世界",
                },
                {
                    "id": "live",
                    "name": "愛不來 (Live)",
                    "artist": "方大同",
                    "album": "危險世界",
                },
            ],
        )
        self.assertEqual(ranked.decision, AppleCandidateDecision.AUTO)
        self.assertEqual(ranked.candidates[0]["id"], "right")

    def test_simplified_and_traditional_title_are_equivalent(self) -> None:
        ranked = rank_apple_candidates(
            "track: 爱爱爱 artist: 方大同 album: 爱爱爱 source: iTunes",
            [{"id": "track", "name": "愛愛愛", "artist": "方大同", "album": "愛愛愛"}],
        )
        self.assertEqual(ranked.decision, AppleCandidateDecision.AUTO)

    def test_album_contradiction_is_rejected(self) -> None:
        ranked = rank_apple_candidates(
            "track: 三人游 artist: 方大同 album: 橙月 source: iTunes",
            [{"id": "wrong", "name": "三人游", "artist": "方大同", "album": "Live Session"}],
        )
        self.assertEqual(ranked.decision, AppleCandidateDecision.REJECT)

    def test_multiple_exact_versions_require_picker(self) -> None:
        ranked = rank_apple_candidates(
            "track: 特別的人 artist: 方大同 album: 危險世界 source: iTunes",
            [
                {"id": "one", "name": "特別的人", "artist": "方大同", "album": "危險世界"},
                {"id": "two", "name": "特別的人", "artist": "方大同", "album": "危險世界"},
            ],
        )
        self.assertEqual(ranked.decision, AppleCandidateDecision.PICKER)

    def test_natural_query_containing_title_and_artist_auto_selects(self) -> None:
        ranked = rank_apple_candidates(
            "特別的人 方大同",
            [{"id": "track", "name": "特別的人", "artist": "方大同", "album": "危險世界"}],
        )
        self.assertEqual(ranked.decision, AppleCandidateDecision.AUTO)


class ProviderModeCoordinatorTests(unittest.IsolatedAsyncioTestCase):
    async def test_target_prepare_failure_preserves_previous_provider(self) -> None:
        coordinator = ProviderModeCoordinator(ProviderModeState(provider=ProviderMode.SPOTIFY))
        calls: list[str] = []

        async def prepare() -> None:
            calls.append("prepare")
            raise RuntimeError("not ready")

        async def pause(_provider: ProviderMode) -> None:
            calls.append("pause")

        async def commit(_provider: ProviderMode) -> None:
            calls.append("commit")

        with self.assertRaisesRegex(RuntimeError, "not ready"):
            await coordinator.switch(
                ProviderMode.APPLE,
                prepare=prepare,
                pause_previous=pause,
                commit=commit,
            )
        self.assertEqual(coordinator.state.provider, ProviderMode.SPOTIFY)
        self.assertEqual(calls, ["prepare"])

    async def test_successful_switch_prepares_then_pauses_then_commits(self) -> None:
        coordinator = ProviderModeCoordinator(ProviderModeState(provider=ProviderMode.SPOTIFY))
        calls: list[str] = []

        async def prepare() -> None:
            calls.append("prepare")

        async def pause(provider: ProviderMode) -> None:
            calls.append(f"pause:{provider.value}")

        async def commit(provider: ProviderMode) -> None:
            calls.append(f"commit:{provider.value}")

        state = await coordinator.switch(
            ProviderMode.APPLE,
            prepare=prepare,
            pause_previous=pause,
            commit=commit,
        )
        self.assertEqual(state.provider, ProviderMode.APPLE)
        self.assertEqual(calls, ["prepare", "pause:spotify", "commit:apple"])


class DeveloperTokenManagerTests(unittest.IsolatedAsyncioTestCase):
    async def test_unexpired_token_is_kept_when_refresh_fails(self) -> None:
        now = int(time.time())
        provider = FakeTokenProvider(
            [
                DeveloperTokenLease("first", now + 301, "fake"),
                RuntimeError("broker down"),
                RuntimeError("broker still down"),
            ]
        )
        manager = DeveloperTokenManager(provider)
        first = await manager.get()
        fallback = await manager.get(force_refresh=True)
        self.assertEqual(first.token, "first")
        self.assertEqual(fallback.token, "first")
        self.assertEqual(provider.calls, 3)

    async def test_expired_token_does_not_mask_refresh_failure(self) -> None:
        now = int(time.time())
        provider = FakeTokenProvider(
            [
                DeveloperTokenLease("expired-soon", now + 1, "fake"),
                RuntimeError("broker down"),
                RuntimeError("broker still down"),
            ]
        )
        manager = DeveloperTokenManager(provider)
        await manager.get()
        with patch("src.apple_mode.token_provider.time.time", return_value=now + 2):
            with self.assertRaisesRegex(RuntimeError, "broker.*down"):
                await manager.get(force_refresh=True)

    async def test_failed_background_refresh_is_temporarily_backed_off(self) -> None:
        now = int(time.time())
        provider = FakeTokenProvider(
            [
                DeveloperTokenLease("still-valid", now + 200, "fake"),
                RuntimeError("broker down"),
                RuntimeError("broker still down"),
            ]
        )
        manager = DeveloperTokenManager(provider)
        await manager.get()
        fallback = await manager.get()
        backed_off = await manager.get()

        self.assertEqual(fallback.token, "still-valid")
        self.assertEqual(backed_off.token, "still-valid")
        self.assertEqual(provider.calls, 3)


class DeveloperTokenConfigurationTests(unittest.TestCase):
    def test_saved_broker_url_is_used_when_environment_is_absent(self) -> None:
        with tempfile.TemporaryDirectory() as home, patch.dict(
            os.environ,
            {"SONEX_HOME": home},
            clear=True,
        ):
            save_apple_token_broker_url("https://tokens.example.test/")
            provider = developer_token_provider_from_env()

        self.assertIsInstance(provider, HttpDeveloperTokenProvider)
        self.assertEqual(provider.broker_url, "https://tokens.example.test")

    def test_environment_broker_url_takes_precedence_over_saved_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as home, patch.dict(
            os.environ,
            {"SONEX_HOME": home},
            clear=True,
        ):
            save_apple_token_broker_url("https://saved.example.test")
            os.environ["SONEX_APPLE_TOKEN_BROKER_URL"] = "https://env.example.test/"
            resolved = configured_apple_token_broker_url()

        self.assertEqual(resolved, "https://env.example.test")

    def test_invalid_broker_url_is_rejected_before_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as home, patch.dict(
            os.environ,
            {"SONEX_HOME": home},
            clear=True,
        ):
            with self.assertRaises(DeveloperTokenError):
                save_apple_token_broker_url("tokens.example.test?secret=value")
            self.assertEqual(configured_apple_token_broker_url(), "")


class AppleCompanionLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_deactivate_keeps_session_secret_for_warm_reconnect(self) -> None:
        companion = MusicKitCompanion()
        original_secret = companion._secret

        await companion.deactivate()

        self.assertEqual(companion._secret, original_secret)

    async def test_changed_developer_token_is_pushed_to_connected_browser(self) -> None:
        companion = MusicKitCompanion()
        socket = FakeWebSocket()
        companion._websocket = socket  # type: ignore[assignment]
        companion._snapshot.connected = True
        companion._lease = DeveloperTokenLease("old", 100, "fake")

        await companion.update_developer_token(
            DeveloperTokenLease("new", 200, "fake")
        )

        self.assertEqual(
            socket.messages,
            [
                {
                    "type": "configure",
                    "developer_token": "new",
                    "expires_at": 200,
                }
            ],
        )

    async def test_catalog_401_refreshes_token_once_before_retry(self) -> None:
        now = int(time.time())
        companion = FakeSearchCompanion()
        provider = FakeTokenProvider(
            [DeveloperTokenLease("fresh", now + 900, "fake")]
        )
        service = AppleModeService(companion=companion)  # type: ignore[arg-type]
        service._token_manager = DeveloperTokenManager(provider)

        result = await service.search("Song")

        self.assertEqual(companion.search_calls, 2)
        self.assertEqual(provider.calls, 1)
        self.assertEqual(companion.refreshed[0].token, "fresh")
        self.assertEqual(result.candidates[0]["id"], "track")


class ProviderModePersistenceTests(unittest.TestCase):
    def test_persists_only_version_and_provider_intent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with patch.dict(os.environ, {"SONEX_HOME": temporary}):
                save_provider_mode_intent(ProviderModeState(provider=ProviderMode.APPLE))
                loaded = load_provider_mode_intent()
                self.assertEqual(loaded.provider, ProviderMode.APPLE)
                payload = (open(f"{temporary}/provider-mode.json", encoding="utf-8").read())
                self.assertNotIn("token", payload.casefold())
                self.assertNotIn("storefront", payload.casefold())


class AppleModeRunnerLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_apple_prepare_preserves_spotify_mode(self) -> None:
        runner = WebSocketRunner()
        runner.apple_mode = FakeAppleService(fail_entry=True)  # type: ignore[assignment]
        ui = FakeModeUI()
        setattr(ui, "_spotify_mode", {"enabled": True, "device_id": "device"})

        await runner._handle_apple_mode_command(ui, "")

        self.assertTrue(runner._spotify_mode_enabled(ui))
        self.assertFalse(runner._apple_mode_enabled(ui))
        self.assertIn("broker unavailable", ui.transcript[-1]["content"])
        self.assertEqual(ui.events[-1].get("tone"), "system")

    async def test_switch_to_apple_pauses_spotify_only_after_target_ready(self) -> None:
        runner = WebSocketRunner()
        service = FakeAppleService()
        runner.apple_mode = service  # type: ignore[assignment]
        ui = FakeModeUI()
        setattr(ui, "_spotify_mode", {"enabled": True, "device_id": "device"})

        with tempfile.TemporaryDirectory() as temporary:
            with (
                patch.dict(os.environ, {"SONEX_HOME": temporary}),
                patch(
                    "src.ws.runner._run_spotify_mode_call",
                    return_value={"status": "success", "data": {}},
                ) as pause_spotify,
            ):
                await runner._handle_apple_mode_command(ui, "")

        pause_spotify.assert_awaited_once()
        self.assertFalse(runner._spotify_mode_enabled(ui))
        self.assertTrue(runner._apple_mode_enabled(ui))
        provider_events = [event for event in ui.events if event.get("type") == "provider_mode"]
        self.assertEqual(provider_events[-1]["provider"], "apple")
        self.assertEqual(provider_events[-1]["storefront"], "hk")


if __name__ == "__main__":
    unittest.main()
