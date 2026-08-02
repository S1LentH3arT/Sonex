from __future__ import annotations

import asyncio
import json
import unittest

from src.ws.ui import WebSocketUIAdapter
from src.llm.transport import Usage


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

    async def test_append_caution_message_uses_error_tone_and_persists(self) -> None:
        ws = RecordingWebSocket()
        ui = WebSocketUIAdapter(ws, session_id="session-1")  # type: ignore[arg-type]

        await ui.append_caution_message('✖  OpenRouter is not connected. Try "/login" to connect.')

        self.assertEqual(
            ui.transcript,
            [{
                "role": "agent",
                "content": '✖  OpenRouter is not connected. Try "/login" to connect.',
            }],
        )
        self.assertEqual(ws.sent[0]["tone"], "error")

    async def test_send_session_state_uses_owned_session_id(self) -> None:
        ws = RecordingWebSocket()
        ui = WebSocketUIAdapter(ws, session_id="session-1")  # type: ignore[arg-type]

        await ui.send_session_state()

        self.assertEqual(ui.session_id, "session-1")
        self.assertEqual(
            ws.sent,
            [{"type": "session_state", "session_id": "session-1"}],
        )

    async def test_record_token_usage_publishes_cumulative_session_totals(self) -> None:
        ws = RecordingWebSocket()
        ui = WebSocketUIAdapter(ws, session_id="session-1")  # type: ignore[arg-type]

        ui.record_token_usage(Usage(prompt_tokens=120, completion_tokens=34, total_tokens=154))
        ui.record_token_usage(Usage(prompt_tokens=6, completion_tokens=2, total_tokens=8))
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        self.assertEqual(ui.input_tokens, 126)
        self.assertEqual(ui.output_tokens, 36)
        self.assertEqual(
            ws.sent,
            [
                {"type": "usage_state", "input_tokens": 120, "output_tokens": 34},
                {"type": "usage_state", "input_tokens": 126, "output_tokens": 36},
            ],
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
