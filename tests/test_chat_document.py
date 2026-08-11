from __future__ import annotations

import unittest

from src.agent.chat_document import guard_agent_answer, normalize_agent_answer


class ChatDocumentTests(unittest.TestCase):
    def test_supported_markdown_becomes_plain_fallback_and_semantic_blocks(self) -> None:
        plain, document = normalize_agent_answer(
            "## 推荐\n\n- **BB88** — `方大同`\n\nVisit [Spotify](https://spotify.com)."
        )

        self.assertEqual(plain, "推荐\n\n- BB88 — 方大同\n\nVisit Spotify.")
        self.assertEqual(document["version"], 1)
        self.assertEqual(document["blocks"][0]["type"], "heading")
        item = document["blocks"][2]
        self.assertEqual(item["type"], "list_item")
        self.assertEqual(item["marker"], "-")
        self.assertEqual([span["style"] for span in item["spans"]], ["strong", "plain", "highlight"])

    def test_unterminated_code_fence_degrades_to_safe_code_block(self) -> None:
        plain, document = normalize_agent_answer("```sh\nsonex play")
        self.assertEqual(plain, "sonex play")
        self.assertEqual(document["blocks"], [{"type": "code_block", "text": "sonex play"}])

    def test_response_guard_blocks_unverified_action_success(self) -> None:
        self.assertEqual(
            guard_agent_answer("Playback started. Now playing BB88.", []),
            "I could not verify that the requested music action completed.",
        )
        self.assertEqual(
            guard_agent_answer("Playback started.", [{"status": "success"}]),
            "Playback started.",
        )

    def test_response_guard_rebuilds_ungrounded_recommendation_list(self) -> None:
        guarded = guard_agent_answer(
            "1. Invented Song — Nobody",
            [
                {
                    "status": "success",
                    "tool": "Recommend",
                    "data": {"tracks": [{"name": "BB88", "artist": "方大同"}]},
                }
            ],
        )
        self.assertIn("**BB88**", guarded)
        self.assertNotIn("Invented Song", guarded)


if __name__ == "__main__":
    unittest.main()
