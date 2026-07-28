from __future__ import annotations

import unittest

from src.api.ws_runner import WebSocketRunner
from src.music.player_sinks import PlayerSelectionResult, PlayerSinkOption


class _FakeManager:
    def __init__(self) -> None:
        self.option_calls = 0
        self.selections: list[str] = []

    async def options(self, *, refresh: bool = False) -> tuple[PlayerSinkOption, ...]:
        self.option_calls += 1
        return (
            PlayerSinkOption(
                sink_id="managed:mpv",
                label="mpv",
                description="Managed playback.",
                installed=True,
                running=False,
                controllable=True,
                injectable=True,
                disabled=False,
            ),
            PlayerSinkOption(
                sink_id="mpris:remote",
                label="Remote",
                description="External MPRIS player.",
                installed=False,
                running=True,
                controllable=True,
                injectable=False,
                disabled=True,
                disabled_reason="Remote control only",
            ),
        )

    async def select(self, sink_id: str) -> PlayerSelectionResult:
        self.selections.append(sink_id)
        return PlayerSelectionResult(
            status="selected",
            sink_id=sink_id,
            message="mpv is ready as the default player.",
            previous_sink_id=None,
        )


class _FakeUI:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    async def append_activity(self, **event: object) -> None:
        self.events.append({"type": "activity", **event})

    async def ask_confirm(self, event: dict[str, object]) -> None:
        self.events.append(event)

    async def append_system_message(self, message: str) -> None:
        self.events.append({"type": "chat", "tone": "system", "text": message})


class PlayerSinkCommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_player_panel_includes_disabled_discovered_players_and_caches_scan(self) -> None:
        manager = _FakeManager()
        runner = WebSocketRunner(player_sink_manager_factory=lambda: manager)
        ui = _FakeUI()

        await runner._handle_local_playback_player(ui, "")
        await runner._handle_local_playback_player(ui, "")

        self.assertEqual(manager.option_calls, 2)
        confirms = [event for event in ui.events if event.get("type") == "confirm"]
        self.assertEqual(
            [choice["value"] for choice in confirms[0]["choices"]],  # type: ignore[index]
            ["managed:mpv", "mpris:remote", "deny"],
        )
        self.assertTrue(confirms[0]["choices"][1]["disabled"])  # type: ignore[index]
        self.assertEqual(
            confirms[0]["choices"][1]["disabled_reason"],  # type: ignore[index]
            "Remote control only",
        )

    async def test_player_selection_uses_manager_and_rejects_disabled_value(self) -> None:
        manager = _FakeManager()
        runner = WebSocketRunner(player_sink_manager_factory=lambda: manager)
        ui = _FakeUI()
        await runner._handle_local_playback_player(ui, "")
        session = getattr(ui, "_player_backend_selection")

        await session.handle_choice("mpris:remote")
        self.assertEqual(manager.selections, [])

        await runner._handle_local_playback_player(ui, "")
        session = getattr(ui, "_player_backend_selection")
        await session.handle_choice("managed:mpv")

        self.assertEqual(manager.selections, ["managed:mpv"])
        self.assertTrue(any(event.get("text") == "player: mpv" for event in ui.events))


if __name__ == "__main__":
    unittest.main()
