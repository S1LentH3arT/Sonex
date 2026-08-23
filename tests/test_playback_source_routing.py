from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from src.music.playback_coordinator import ProviderReadiness
from src.music.netease_worker import NetEaseProviderWorker
from src.ws.runner import PlaySelectionSession, WebSocketRunner


class _UI:
    session_id = "routing-test"

    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    async def append_activity(self, **kwargs: object) -> str:
        self.events.append({"type": "activity", **kwargs})
        return str(kwargs.get("activity_id") or "activity")

    async def ask_confirm(self, payload: dict[str, object]) -> None:
        self.events.append({"type": "confirm", **payload})

    async def append_system_message(self, text: str) -> None:
        self.events.append({"type": "chat", "text": text})

    async def send_error(self, text: str) -> None:
        self.events.append({"type": "error", "text": text})


class PlaybackSourceRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_netease_search_requests_five_and_filters_native_ids(self) -> None:
        worker = NetEaseProviderWorker(executable="/usr/bin/ncm-cli")
        seen_limits: list[int] = []

        def search(query: str, *, limit: int) -> list[dict[str, object]]:
            seen_limits.append(limit)
            return [
                {
                    "title": "Song",
                    "artist": "Artist",
                    "encrypted_id": "enc",
                    "original_id": "1",
                    "playable": True,
                },
                {
                    "title": "Missing ID",
                    "artist": "Artist",
                    "playable": True,
                },
                {
                    "title": "Unavailable",
                    "artist": "Artist",
                    "encrypted_id": "enc-2",
                    "original_id": "2",
                    "playable": False,
                },
            ]

        worker.search = search
        runner = WebSocketRunner()
        ui = _UI()
        async def run_inline(func, *args, **kwargs):
            return func(*args, **kwargs)

        with patch("src.ws.runner.NetEaseProviderWorker", return_value=worker), patch(
            "src.ws.runner.asyncio.to_thread", new=run_inline
        ):
            candidates = await runner._search_authoritative_candidates(ui, "netease", "Artist Song")

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["encrypted_id"], "enc")
        self.assertEqual(seen_limits, [5])

    async def test_direct_play_starts_with_source_picker_before_catalog_search(self) -> None:
        runner = WebSocketRunner()
        ui = _UI()
        runner._probe_authoritative_providers = AsyncMock(
            return_value=[
                ProviderReadiness("netease", True, True, True, True),
                ProviderReadiness("spotify", True, True, True, True),
            ]
        )
        session = PlaySelectionSession(ui, runner, "Artist Song")
        with patch("src.ws.runner.search_local_file", return_value="No local files found."):
            task = asyncio.create_task(session.start())
            await asyncio.sleep(0.01)

        confirm = [event for event in ui.events if event.get("type") == "confirm"][-1]
        self.assertEqual(confirm["tool_name"], "playback_source")
        self.assertEqual(
            [choice["value"] for choice in confirm["choices"]],
            ["playback_source:netease", "playback_source:spotify", "playback_source:online", "cancel"],
        )
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
