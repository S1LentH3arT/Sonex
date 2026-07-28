from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock
from unittest.mock import patch

from src.api.ws_runner import WebSocketRunner
from src.music.connections import MusicConnectionRecord


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

    async def append_system_message(self, message: str) -> None:
        self.events.append({"type": "chat", "tone": "system", "text": message})

    async def append_user_message(self, message: str) -> None:
        self.events.append({"type": "chat", "role": "user", "text": message})


class MusicConnectCommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_connect_opens_unified_interactive_panel_with_actionable_accounts_only(self) -> None:
        runner = WebSocketRunner(
            music_connection_manager_factory=lambda: _FakeConnections(),
        )
        runner._run_agent_turn = AsyncMock()
        ui = _FakeUI()

        await runner._handle_user_input(ui, "/connect netease")

        self.assertFalse(runner._run_agent_turn.called)
        confirm = [event for event in ui.events if event.get("type") == "confirm"][-1]
        self.assertEqual(confirm["tool_name"], "music_connection")
        self.assertEqual(
            [choice["value"] for choice in confirm["choices"]],  # type: ignore[index]
            ["spotify", "apple_music", "deny"],
        )
        self.assertNotIn("netease", str(confirm).casefold())
        self.assertIn("Connected", confirm["choices"][0]["description"])  # type: ignore[index]
        self.assertIn("Not connected", confirm["choices"][1]["description"])  # type: ignore[index]

    async def test_connect_selection_delegates_to_interactive_provider_workflow(self) -> None:
        runner = WebSocketRunner(
            music_connection_manager_factory=lambda: _FakeConnections(),
        )
        runner._connect_music_provider = AsyncMock()
        ui = _FakeUI()
        await runner._handle_user_input(ui, "/connect")
        session = getattr(ui, "_music_connection_selection")

        await session.handle_choice("apple_music")

        runner._connect_music_provider.assert_awaited_once_with(ui, "apple_music")
        self.assertIsNone(getattr(ui, "_music_connection_selection"))

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

    async def test_apple_connection_does_not_switch_provider_mode(self) -> None:
        connections = _FakeConnections()
        runner = WebSocketRunner(
            music_connection_manager_factory=lambda: connections,
        )
        runner.apple_mode = SimpleNamespace(
            snapshot=SimpleNamespace(
                connected=True,
                authorized=True,
                can_play=True,
                storefront="us",
            )
        )
        ui = _FakeUI()
        ui.send_auth_setup = AsyncMock()

        await runner._connect_music_provider(ui, "apple_music")

        self.assertEqual(connections.connected, ("apple_music", "Storefront US"))
        self.assertIsNone(getattr(ui, "_apple_mode", None))


if __name__ == "__main__":
    unittest.main()
