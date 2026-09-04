from __future__ import annotations

import unittest

from src.agent.turn_policy import (
    confirm_approved,
    confirm_interrupted,
    is_committed_playback_result,
    is_player_confirm_result,
    is_suspended_interaction_result,
    normalized_call_key,
    planning_command_intent,
    player_confirm_payload,
    spotify_premium_failure_answer,
    to_serializable,
)
from src.api.builtin_commands import CommandIntent


class AgentTurnPolicyTests(unittest.TestCase):
    def test_serialization_keeps_json_values_and_stringifies_unknown_values(self) -> None:
        class Unknown:
            def __str__(self) -> str:
                return "unknown"

        self.assertEqual(to_serializable({"ok": [1, True]}), {"ok": [1, True]})
        self.assertEqual(to_serializable(Unknown()), "unknown")

    def test_call_key_is_stable_for_argument_order(self) -> None:
        self.assertEqual(
            normalized_call_key("Search", {"b": 2, "a": 1}),
            normalized_call_key("Search", {"a": 1, "b": 2}),
        )

    def test_exhausted_command_becomes_text_only(self) -> None:
        intent = CommandIntent(
            command="recommend",
            raw="/recommend",
            args="",
            intent_prompt="Recommend a track.",
            allowed_tools=("Recommend",),
            max_tool_calls=1,
        )
        limited = planning_command_intent(intent, tool_call_count=1, tool_call_limit=1)
        self.assertEqual(limited.allowed_tools, ())
        self.assertEqual(limited.max_tool_calls, 0)
        self.assertIn("Do not call another tool", limited.intent_prompt)
        self.assertEqual(intent.allowed_tools, ("Recommend",))

    def test_result_classifiers_cover_only_terminal_protocol_states(self) -> None:
        self.assertTrue(is_player_confirm_result({"status": "requires_player_confirm"}))
        self.assertTrue(is_suspended_interaction_result({"status": "requires_play_selection"}))
        self.assertTrue(is_committed_playback_result({"status": "playback_failed"}))
        self.assertFalse(is_committed_playback_result({"status": "requires_play_selection"}))

    def test_confirmation_policy_and_payload_are_normalized(self) -> None:
        result = {
            "message": "fallback",
            "data": {"confirm_message": "Choose a player", "choices": ["mpv"], "player": "mpv"},
        }
        self.assertEqual(
            player_confirm_payload(result, {"uri": "song"}),
            {
                "message": "Choose a player",
                "choices": ["mpv"],
                "tool_args": {"uri": "song"},
                "player": "mpv",
                "player_label": None,
            },
        )
        self.assertTrue(confirm_approved("allow_once"))
        self.assertFalse(confirm_approved("deny"))
        self.assertTrue(
            confirm_interrupted({"status": "cancelled", "data": {"reason": "session_disconnected"}})
        )

    def test_spotify_premium_answer_is_only_for_known_failures(self) -> None:
        self.assertIn(
            "YouTube/local playback",
            spotify_premium_failure_answer({"error_code": "SPOTIFY_APP_PREMIUM_REQUIRED"}),
        )
        self.assertIsNone(spotify_premium_failure_answer({"error_code": "OTHER"}))


if __name__ == "__main__":
    unittest.main()
