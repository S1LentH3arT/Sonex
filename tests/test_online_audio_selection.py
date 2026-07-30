from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from src.ws.runner import PlaySelectionSession, WebSocketRunner


async def _to_thread_inline(function, /, *args, **kwargs):
    return function(*args, **kwargs)


class FakeUI:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    async def append_activity(self, **event: object) -> str:
        self.events.append({"type": "activity", **event})
        return str(event.get("activity_id") or "activity")

    async def append_agent_message(self, text: str) -> None:
        self.events.append({"type": "chat", "text": text})

    async def append_system_message(self, text: str) -> None:
        self.events.append({"type": "chat", "tone": "system", "text": text})

    async def send_error(self, message: str) -> None:
        self.events.append({"type": "error", "message": message})

    async def send_cover(self, url: str) -> None:
        self.events.append({"type": "cover", "url": url})

    async def ask_confirm(self, payload: dict[str, object]) -> None:
        self.events.append(payload)


class OnlineAudioSelectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_medium_confidence_candidate_requires_confirmation_before_playback(self) -> None:
        ui = FakeUI()
        session = PlaySelectionSession(ui, WebSocketRunner(), "Canonical Song")
        metadata = {
            "metadata_source": "itunes",
            "name": "Canonical Song",
            "artist": "Canonical Artist",
        }
        candidate = {
            "provider": "youtube",
            "cache_id": "youtube_review",
            "name": "Canonical Song",
            "artist": "Canonical Artist",
            "assessment": {
                "confidence": "medium",
                "evidence": ["title_only_weak_evidence"],
                "conflicts": [],
            },
        }

        with patch(
            "src.ws.runner._search_online_audio_for_runner",
            return_value=[candidate],
        ), patch(
            "src.ws.runner.resolve_online_playback_metadata",
            return_value=metadata,
        ), patch(
            "src.ws.runner._play_online_audio_for_runner",
        ) as play, patch(
            "src.ws.runner.asyncio.to_thread",
            side_effect=_to_thread_inline,
        ):
            await session._play_selected_metadata_candidate(
                "Canonical Artist Canonical Song",
                metadata,
            )

        play.assert_not_called()
        confirms = [event for event in ui.events if event.get("type") == "confirm"]
        self.assertEqual(confirms[-1]["tool_name"], "online_audio_candidate")
        self.assertEqual(confirms[-1]["tool_args"]["stage"], "online_audio_candidates")
        self.assertIn("Needs confirmation", confirms[-1]["choices"][0]["description"])

    async def test_high_confidence_playback_tries_next_candidate_after_media_failure(self) -> None:
        ui = FakeUI()
        runner = WebSocketRunner()
        runner._sync_tool_result_ui = AsyncMock()
        session = PlaySelectionSession(ui, runner, "Canonical Song")
        metadata = {
            "metadata_source": "itunes",
            "name": "Canonical Song",
            "artist": "Canonical Artist",
        }
        candidates = [
            {
                "provider": "youtube",
                "cache_id": f"youtube_{index}",
                "name": "Canonical Song",
                "artist": "Canonical Artist",
                "assessment": {
                    "confidence": "high",
                    "evidence": ["artist_exact", "title_exact"],
                    "conflicts": [],
                },
            }
            for index in range(2)
        ]
        failure = {
            "status": "fail",
            "tool": "play_online_audio",
            "message": "Candidate unavailable.",
            "data": candidates[0],
        }
        success = {
            "status": "success",
            "tool": "play_online_audio",
            "message": "Playing.",
            "data": candidates[1],
        }

        with patch(
            "src.ws.runner._search_online_audio_for_runner",
            return_value=candidates,
        ), patch(
            "src.ws.runner.resolve_online_playback_metadata",
            return_value=metadata,
        ), patch(
            "src.ws.runner._play_online_audio_for_runner",
            side_effect=[failure, success],
        ) as play, patch(
            "src.ws.runner.upsert_cached_song",
        ), patch(
            "src.ws.runner.asyncio.to_thread",
            side_effect=_to_thread_inline,
        ):
            await session._play_selected_metadata_candidate(
                "Canonical Artist Canonical Song",
                metadata,
            )

        self.assertEqual(play.call_count, 2)
        self.assertTrue(any(
            event.get("type") == "activity"
            and event.get("title") == "Playback selection"
            and event.get("status") == "success"
            for event in ui.events
        ))


if __name__ == "__main__":
    unittest.main()
