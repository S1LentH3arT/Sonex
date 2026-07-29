from __future__ import annotations

import json
import unittest

from src.ws.ui import WebSocketUIAdapter


class RecordingWebSocket:
    def __init__(self) -> None:
        self.sent: list[dict[str, object]] = []

    async def send_text(self, text: str) -> None:
        self.sent.append(json.loads(text))


class WebSocketUIAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_append_system_message_uses_existing_chat_shape(self) -> None:
        ws = RecordingWebSocket()
        ui = WebSocketUIAdapter(ws, session_id="session-1")  # type: ignore[arg-type]

        await ui.append_system_message("player: VLC")

        self.assertEqual(
            ui.transcript,
            [{"role": "agent", "content": "player: VLC"}],
        )
        self.assertEqual(
            ws.sent,
            [
                {
                    "type": "chat",
                    "role": "agent",
                    "tone": "system",
                    "text": "player: VLC",
                }
            ],
        )

    async def test_send_session_state_uses_owned_session_id(self) -> None:
        ws = RecordingWebSocket()
        ui = WebSocketUIAdapter(ws, session_id="session-1")  # type: ignore[arg-type]

        await ui.send_session_state()

        self.assertEqual(ui.session_id, "session-1")
        self.assertEqual(
            ws.sent,
            [{"type": "session_state", "session_id": "session-1"}],
        )

    async def test_append_agent_message_persists_rich_tool_segments(self) -> None:
        ws = RecordingWebSocket()
        ui = WebSocketUIAdapter(ws, session_id="session-1")  # type: ignore[arg-type]
        segments = [
            {"text": "Read", "style": "tool_name"},
            {"text": "  USER.md", "style": "tool_value"},
        ]

        await ui.append_agent_message("Read  USER.md", segments=segments)

        self.assertEqual(
            ui.transcript,
            [
                {
                    "role": "agent",
                    "content": "Read  USER.md",
                    "segments": segments,
                }
            ],
        )
        self.assertEqual(ws.sent[0]["segments"], segments)
