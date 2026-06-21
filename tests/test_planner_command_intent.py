"""Tests test planner command intent.

Contains pytest coverage for the test planner command intent behavior.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from src.api.builtin_commands import CommandIntent
from src.llm.transport import ChatResponse, ToolCall, Usage
from src.llm.planner import llm_plan
from src.tools.registry import Params, ToolRegistry


def _search_intent() -> CommandIntent:
    return CommandIntent(
        command="search",
        raw="search jay",
        args="jay",
        intent_prompt="Treat this as an interactive search request.",
        allowed_tools=("spotify_search",),
    )


class FakeClient:
    """Groups related client cases.

    Collects assertions that exercise client behavior without mixing unrelated fixtures.
    """
    def __init__(self, response: ChatResponse) -> None:
        """Verifies that init behaves as expected.

        Typical use: Use this in automated tests when guarding the init behavior against regressions.

        Example: __init__() -> passes without assertion failures when the behavior remains correct.
        """
        self.response = response
        self.requests = []

    def generate(self, request):
        """Verifies that generate behaves as expected.

        Typical use: Use this in automated tests when guarding the generate behavior against regressions.

        Example: generate() -> passes without assertion failures when the behavior remains correct.
        """
        self.requests.append(request)
        return self.response


def _registry() -> ToolRegistry:
    """Verifies that registry behaves as expected.

    Typical use: Use this in automated tests when guarding the registry behavior against regressions.

    Example: _registry() -> passes without assertion failures when the behavior remains correct.
    """
    tools = ToolRegistry()
    for name in ["spotify_search", "spotify_recommend", "spotify_play"]:
        tools.register(
            name=name,
            type="spotify",
            description=f"{name} tool",
            parameters=Params(type="object", properties={}, required=[]),
            fn=lambda: None,
            read_only=name != "spotify_play",
            confirm_required=name == "spotify_play",
        )
    return tools


class PlannerCommandIntentTests(unittest.TestCase):
    """Groups related planner command intent tests cases.

    Collects assertions that exercise planner command intent tests behavior without mixing unrelated fixtures.
    """
    def test_empty_allowlist_exposes_no_tools(self) -> None:
        """Verifies that empty allowlist exposes no tools behaves as expected.

        Typical use: Use this in automated tests when guarding the empty allowlist exposes no tools behavior against regressions.

        Example: test_empty_allowlist_exposes_no_tools() -> passes without assertion failures when the behavior remains correct.
        """
        client = FakeClient(ChatResponse(output_text="answer", usage=Usage(total_tokens=1)))
        intent = CommandIntent(
            command="general",
            raw="hello",
            args="",
            intent_prompt="No tools.",
            allowed_tools=(),
        )

        with patch("src.llm.planner.ThinkingConfig.get_client", return_value=client), \
             patch("src.llm.planner.ThinkingConfig.get_model", return_value="model"), \
             patch("src.llm.planner.build_planning_context", return_value=""):
            llm_plan(user_input="hello", tools=_registry(), command_intent=intent)

        self.assertEqual(client.requests[0].tools, [])
        self.assertIn("allowed_tools: none", client.requests[0].messages[1]["content"])

    def test_command_intent_prompt_and_args_are_included_and_tools_are_narrowed(self) -> None:
        """Verifies that command intent prompt and args are included and tools are narrowed behaves as expected.

        Typical use: Use this in automated tests when guarding the command intent prompt and args are included and tools are narrowed behavior against regressions.

        Example: test_command_intent_prompt_and_args_are_included_and_tools_are_narrowed() -> passes without assertion failures when the behavior remains correct.
        """
        intent = _search_intent()
        client = FakeClient(
            ChatResponse(
                tool_calls=[ToolCall(id="1", name="spotify_search", arguments={"query": "jay"})],
                usage=Usage(total_tokens=7),
            )
        )

        with patch("src.llm.planner.ThinkingConfig.get_client", return_value=client), \
            patch("src.llm.planner.ThinkingConfig.get_model", return_value="model"), \
            patch("src.llm.planner.build_planning_context", return_value="cached context"):
            action = llm_plan(user_input="search jay", tools=_registry(), command_intent=intent)

        self.assertEqual(action.tool, "spotify_search")
        request = client.requests[0]
        self.assertIn("Command intent guidance", request.messages[0]["content"])
        self.assertIn("Treat this as an interactive search request.", request.messages[0]["content"])
        user_content = request.messages[1]["content"]
        self.assertIn("[command_intent]", user_content)
        self.assertIn("command: search", user_content)
        self.assertIn("args: jay", user_content)
        self.assertIn("[preloaded_memory]\ncached context", user_content)
        tool_names = [tool["function"]["name"] for tool in request.tools]
        self.assertEqual(tool_names, ["spotify_search"])


if __name__ == "__main__":
    unittest.main()
