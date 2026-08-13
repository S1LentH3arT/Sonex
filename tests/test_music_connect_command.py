from __future__ import annotations

import asyncio
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock
from unittest.mock import patch

from src.api.ws_runner import WebSocketRunner
from src.music.connections import MusicConnectionRecord
from src.music.connections import MusicConnectionManager
from src.music.netease_worker import NetEaseLoginResult


async def _to_thread_inline(function: object, *args: object, **kwargs: object) -> object:
    return function(*args, **kwargs)  # type: ignore[operator]


class _FakeConnections:
    preferred_provider_id = "spotify"

    def record(self, provider_id: str) -> MusicConnectionRecord | None:
        if provider_id != "spotify":
            return None
        return MusicConnectionRecord(
            provider_id="spotify",
            status="connected",
            account_label="Spotify User",
            connected_at="2026-07-28T00:00:00+00:00",
            checked_at="2026-07-28T00:00:00+00:00",
        )

    def mark_connected(self, provider_id: str, *, account_label: str | None = None) -> None:
        self.connected = (provider_id, account_label)

    def mark_unavailable(self, provider_id: str, *, reason: str) -> None:
        self.unavailable = (provider_id, reason)


class _FakeUI:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    async def append_activity(self, **event: object) -> None:
        self.events.append({"type": "activity", **event})

    async def ask_confirm(self, event: dict[str, object]) -> None:
        self.events.append(event)

    async def dismiss_confirm(self, confirm_id: str) -> None:
        self.events.append({"type": "confirm_dismiss", "id": confirm_id})

    async def append_system_message(self, message: str) -> None:
        self.events.append({"type": "chat", "tone": "system", "text": message})

    async def append_user_message(self, message: str) -> None:
        self.events.append({"type": "chat", "role": "user", "text": message})

    async def send_spotify_setup(self, **event: object) -> None:
        self.events.append({"type": "spotify_setup", **event})

    async def send_auth_setup(self, **event: object) -> None:
        self.events.append({"type": "auth_setup", **event})

    async def send_netease_login(self, **event: object) -> None:
        self.events.append({"type": "netease_login", **event})


class MusicConnectCommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_configured_unlogged_netease_opens_qr_login_surface(self) -> None:
        connections = _FakeConnections()
        runner = WebSocketRunner(
            music_connection_manager_factory=lambda: connections,
        )
        ui = _FakeUI()
        health = type(
            "Health",
            (),
            {"ready": False, "login_available": True, "login_ready": False, "reason": "Sign in."},
        )()

        with patch("src.api.ws_runner.NetEaseProviderWorker.health", return_value=health), patch(
            "src.api.ws_runner.NetEaseProviderWorker.login",
            return_value=NetEaseLoginResult("cancelled", ""),
        ) as login:
            await runner._connect_music_provider(ui, "netease", emit_feedback=False)
            session = getattr(ui, "_netease_login_session")
            self.assertIsNotNone(session)
            self.assertEqual(ui.events[-1]["type"], "netease_login")
            self.assertTrue(ui.events[-1]["active"])
            login.assert_not_called()
            await session.cancel()
            if session.task is not None:
                await session.task

    async def test_connect_opens_unified_interactive_panel_with_actionable_accounts_only(self) -> None:
        runner = WebSocketRunner(
            music_connection_manager_factory=lambda: _FakeConnections(),
        )
        runner._run_agent_turn = AsyncMock()
        ui = _FakeUI()

        await runner._handle_user_input(ui, "/connect")

        self.assertFalse(runner._run_agent_turn.called)
        confirm = [event for event in ui.events if event.get("type") == "confirm"][-1]
        self.assertEqual(confirm["tool_name"], "music_connection")
        self.assertEqual(
            [choice["value"] for choice in confirm["choices"]],  # type: ignore[index]
            ["spotify", "netease", "jamendo", "audius"],
        )
        self.assertEqual(confirm["message"], "Music connections")
        self.assertEqual(
            confirm["tool_args"]["hint"],  # type: ignore[index]
            "↑/↓ to select · Enter to connect/check · Esc to close",
        )
        self.assertEqual(confirm["choices"][0]["description"], "Connected · Spotify User")  # type: ignore[index]
        self.assertEqual(confirm["choices"][0]["connection_status"], "connected")  # type: ignore[index]
        self.assertEqual(confirm["choices"][1]["description"], "Not connected")  # type: ignore[index]
        self.assertEqual(confirm["choices"][1]["connection_status"], "missing")  # type: ignore[index]
        self.assertEqual(confirm["choices"][3]["description"], "Connected")  # type: ignore[index]
        self.assertEqual(confirm["choices"][3]["connection_status"], "connected")  # type: ignore[index]
        self.assertEqual([event["type"] for event in ui.events], ["chat", "confirm"])

    async def test_connect_selection_delegates_to_interactive_provider_workflow(self) -> None:
        runner = WebSocketRunner(
            music_connection_manager_factory=lambda: _FakeConnections(),
        )
        runner._connect_music_provider = AsyncMock()
        ui = _FakeUI()
        await runner._handle_user_input(ui, "/connect")
        session = getattr(ui, "_music_connection_selection")

        await session.handle_choice("netease")
        await asyncio.sleep(0)

        runner._connect_music_provider.assert_awaited_once()
        call = runner._connect_music_provider.await_args
        self.assertEqual(call.args[:2], (ui, "netease"))
        self.assertFalse(call.kwargs["emit_feedback"])
        self.assertIs(getattr(ui, "_music_connection_selection"), session)
        checking = [event for event in ui.events if event.get("type") == "confirm"][-1]
        netease = next(choice for choice in checking["choices"] if choice["value"] == "netease")  # type: ignore[index]
        self.assertEqual(netease["connection_status"], "checking")
        self.assertEqual(netease["description"], "Checking connection...")

    async def test_connect_cancel_is_silent_and_dismisses_the_panel(self) -> None:
        runner = WebSocketRunner(
            music_connection_manager_factory=lambda: _FakeConnections(),
        )
        ui = _FakeUI()
        await runner._handle_user_input(ui, "/connect")
        session = getattr(ui, "_music_connection_selection")
        before = len([event for event in ui.events if event.get("type") in {"chat", "activity"}])

        await session.handle_choice("deny")

        after = len([event for event in ui.events if event.get("type") in {"chat", "activity"}])
        self.assertEqual(after, before)
        self.assertIsNone(getattr(ui, "_music_connection_selection"))
        self.assertTrue(any(event.get("type") == "confirm_dismiss" for event in ui.events))

    async def test_connect_allows_only_one_provider_operation_and_discards_late_result(self) -> None:
        runner = WebSocketRunner(
            music_connection_manager_factory=lambda: _FakeConnections(),
        )
        callbacks: list[object] = []

        async def deferred_connect(
            _ui: object,
            _provider_id: str,
            *,
            complete: object,
            emit_feedback: bool,
        ) -> None:
            self.assertFalse(emit_feedback)
            callbacks.append(complete)

        runner._connect_music_provider = AsyncMock(side_effect=deferred_connect)
        ui = _FakeUI()
        await runner._handle_user_input(ui, "/connect")
        session = getattr(ui, "_music_connection_selection")

        await session.handle_choice("spotify")
        await session.handle_choice("netease")
        await asyncio.sleep(0)
        self.assertEqual(runner._connect_music_provider.await_count, 1)

        await session.handle_choice("deny")
        late_complete = callbacks[0]
        late_complete({  # type: ignore[operator]
            "status": "connected",
            "message": "late",
            "data": {"provider": "spotify", "account_label": "Late"},
        })
        await asyncio.sleep(0)
        self.assertIsNone(getattr(ui, "_music_connection_selection"))
        self.assertEqual(ui.events[-1]["type"], "confirm_dismiss")

    async def test_connect_setup_flow_emits_only_the_interactive_setup_surface(self) -> None:
        connections = _FakeConnections()
        runner = WebSocketRunner(
            music_connection_manager_factory=lambda: connections,
        )
        ui = _FakeUI()

        with patch("src.api.ws_runner.load_spotify_token", return_value=None):
            await runner._connect_music_provider(
                ui,
                "spotify",
                complete=lambda _result: None,
                emit_feedback=False,
            )

        self.assertTrue(any(event.get("type") == "spotify_setup" for event in ui.events))
        self.assertFalse(any(event.get("type") in {"chat", "activity"} for event in ui.events))

    async def test_connect_completion_updates_only_the_provider_row(self) -> None:
        with TemporaryDirectory() as temporary:
            connections = MusicConnectionManager(
                path=Path(temporary) / "connections.json",
            )
            runner = WebSocketRunner(
                music_connection_manager_factory=lambda: connections,
            )
            ui = _FakeUI()
            await runner._handle_user_input(ui, "/connect")
            session = getattr(ui, "_music_connection_selection")
            transcript_count = len(
                [event for event in ui.events if event.get("type") in {"chat", "activity"}]
            )

            async def connected(
                _ui: object,
                _provider_id: str,
                *,
                complete: object,
                emit_feedback: bool,
            ) -> None:
                self.assertFalse(emit_feedback)
                complete({  # type: ignore[operator]
                    "status": "connected",
                    "message": "connected",
                    "data": {"provider": "spotify", "account_label": "Spotify User"},
                })

            runner._connect_music_provider = AsyncMock(side_effect=connected)
            await session.handle_choice("spotify")
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            confirm = [event for event in ui.events if event.get("type") == "confirm"][-1]
            spotify = next(choice for choice in confirm["choices"] if choice["value"] == "spotify")  # type: ignore[index]
            self.assertEqual(spotify["connection_status"], "connected")
            self.assertEqual(spotify["description"], "Connected · Spotify User")

            async def failed(
                _ui: object,
                _provider_id: str,
                *,
                complete: object,
                emit_feedback: bool,
            ) -> None:
                self.assertFalse(emit_feedback)
                complete({  # type: ignore[operator]
                    "status": "failed",
                    "message": "sensitive upstream detail",
                    "data": {"provider": "netease", "reason": "worker_not_ready"},
                })

            runner._connect_music_provider = AsyncMock(side_effect=failed)
            await session.handle_choice("netease")
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            confirm = [event for event in ui.events if event.get("type") == "confirm"][-1]
            netease = next(choice for choice in confirm["choices"] if choice["value"] == "netease")  # type: ignore[index]
            self.assertEqual(netease["connection_status"], "warning")
            self.assertEqual(netease["description"], "press Enter to retry")
            self.assertEqual(connections.record("netease").reason, "connection_failed")  # type: ignore[union-attr]
            self.assertEqual(
                len([event for event in ui.events if event.get("type") in {"chat", "activity"}]),
                transcript_count,
            )

    async def test_spotify_connection_health_check_persists_non_secret_account_identity(self) -> None:
        connections = _FakeConnections()
        runner = WebSocketRunner(
            music_connection_manager_factory=lambda: connections,
        )
        ui = _FakeUI()
        with patch("src.api.ws_runner.load_spotify_token", return_value=object()), patch(
            "src.api.ws_runner.spotify_account",
            return_value={
                "status": "success",
                "data": {
                    "logged_in": True,
                    "display_name": "Spotify User",
                    "product": "premium",
                },
            },
        ), patch(
            "src.api.ws_runner.asyncio.to_thread",
            side_effect=_to_thread_inline,
        ):
            await asyncio.wait_for(
                runner._connect_music_provider(ui, "spotify"),
                timeout=1,
            )

        self.assertEqual(connections.connected, ("spotify", "Spotify User"))
        self.assertTrue(any(event.get("text") == "Spotify connected · Spotify User." for event in ui.events))

    async def test_spotify_connection_never_uses_email_or_raw_id_as_account_summary(self) -> None:
        connections = _FakeConnections()
        runner = WebSocketRunner(
            music_connection_manager_factory=lambda: connections,
        )
        ui = _FakeUI()
        with patch("src.api.ws_runner.load_spotify_token", return_value=object()), patch(
            "src.api.ws_runner.spotify_account",
            return_value={
                "status": "success",
                "data": {
                    "logged_in": True,
                    "email": "private@example.com",
                    "id": "raw-account-id",
                },
            },
        ), patch(
            "src.api.ws_runner.asyncio.to_thread",
            side_effect=_to_thread_inline,
        ):
            await runner._connect_music_provider(ui, "spotify", emit_feedback=False)

        self.assertEqual(connections.connected, ("spotify", None))
        self.assertFalse(any(event.get("type") in {"chat", "activity"} for event in ui.events))

if __name__ == "__main__":
    unittest.main()
