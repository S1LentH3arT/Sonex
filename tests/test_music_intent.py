"""Tests test music intent.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from src.api.music_intent import MusicIntentRoute, classify_music_intent
from src.llm.transport import ChatResponse, Usage


class _Client:
    def __init__(self, output_text: str) -> None:
        self.output_text = output_text
        self.requests = []

    def generate(self, request):
        self.requests.append(request)
        return ChatResponse(output_text=self.output_text, usage=Usage(total_tokens=1))


class MusicIntentTests(unittest.TestCase):
    def test_explicit_play_fast_path(self) -> None:
        decision = classify_music_intent("帮我放一首七里香")

        self.assertEqual(decision.route, MusicIntentRoute.EXPLICIT_PLAY)
        self.assertEqual(decision.query, "七里香")

    def test_classifier_routes_track_interest_to_confirmation(self) -> None:
        client = _Client(
            '{"route":"confirm_track_play","query":"周杰伦 七里香",'
            '"recommendation_index":null,"confidence":0.91}'
        )

        with patch("src.api.music_intent.ThinkingConfig.get_client", return_value=client), \
             patch("src.api.music_intent.ThinkingConfig.get_model", return_value="model"):
            decision = classify_music_intent("最近我对周杰伦的《七里香》很感兴趣")

        self.assertEqual(decision.route, MusicIntentRoute.CONFIRM_TRACK_PLAY)
        self.assertEqual(decision.query, "周杰伦 七里香")
        self.assertEqual(client.requests[0].temperature, 0)

    def test_classifier_routes_recommendation_requests(self) -> None:
        for text in ("给我推荐几首周杰伦的歌", "我最近对周杰伦很感兴趣"):
            with self.subTest(text=text):
                client = _Client(
                    '{"route":"recommend","query":"周杰伦",'
                    '"recommendation_index":null,"confidence":0.9}'
                )
                with patch("src.api.music_intent.ThinkingConfig.get_client", return_value=client), \
                     patch("src.api.music_intent.ThinkingConfig.get_model", return_value="model"):
                    decision = classify_music_intent(text)
                self.assertEqual(decision.route, MusicIntentRoute.RECOMMEND)

    def test_classifier_keeps_song_background_question_general(self) -> None:
        client = _Client(
            '{"route":"general","query":null,'
            '"recommendation_index":null,"confidence":0.98}'
        )
        with patch("src.api.music_intent.ThinkingConfig.get_client", return_value=client), \
             patch("src.api.music_intent.ThinkingConfig.get_model", return_value="model"):
            decision = classify_music_intent("七里香的创作背景是什么")

        self.assertEqual(decision.route, MusicIntentRoute.GENERAL)

    def test_invalid_low_confidence_and_errors_fall_back_to_general(self) -> None:
        outputs = (
            "not json",
            '{"route":"explicit_play","query":"七里香",'
            '"recommendation_index":null,"confidence":0.4}',
        )
        for output in outputs:
            with self.subTest(output=output):
                client = _Client(output)
                with patch("src.api.music_intent.ThinkingConfig.get_client", return_value=client), \
                     patch("src.api.music_intent.ThinkingConfig.get_model", return_value="model"):
                    decision = classify_music_intent("模糊输入")
                self.assertEqual(decision.route, MusicIntentRoute.GENERAL)

        with patch("src.api.music_intent.ThinkingConfig.get_client", side_effect=TimeoutError):
            decision = classify_music_intent("模糊输入")
        self.assertEqual(decision.route, MusicIntentRoute.GENERAL)


if __name__ == "__main__":
    unittest.main()
