"""Tests test planner command intent.

Contains pytest coverage for the test planner command intent behavior.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from src.api.builtin_commands import parse_builtin_command
from src.llm.transport import ChatResponse, ToolCall, Usage
from src.llm.planner import llm_plan
from src.tools.registry import Params, ToolRegistry


class FakeClient:
    """Groups fake client tests.

    Collects related assertions for fake client behavior.
    """
    def __init__(self, response: ChatResponse) -> None:
        """Validate init.

        Exercises the init behavior through the test suite.

        Args:
            response: Pytest fixture or input used by this test.
        """
        self.response = response
        self.requests = []

    def generate(self, request):
        """Validate generate.

        Exercises the generate behavior through the test suite.

        Args:
            request: Pytest fixture or input used by this test.
        """
        self.requests.append(request)
        return self.response


def _registry() -> ToolRegistry:
    """Validate registry.

    Exercises the registry behavior through the test suite.
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
    """Groups planner command intent tests tests.

    Collects related assertions for planner command intent tests behavior.
    """
    def test_empty_allowlist_exposes_no_tools(self) -> None:
        """Validate test empty allowlist exposes no tools.

        Exercises the test empty allowlist exposes no tools behavior through the test suite.
        """
        client = FakeClient(ChatResponse(output_text="answer", usage=Usage(total_tokens=1)))
        intent = parse_builtin_command("/search jay").command_intent()
        intent = type(intent)(
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
        """Validate test command intent prompt and args are included and tools are narrowed.

        Exercises the test command intent prompt and args are included and tools are narrowed behavior through the test suite.
        """
        parsed = parse_builtin_command("/search jay")
        assert parsed is not None
        intent = parsed.command_intent()
        assert intent is not None
        client = FakeClient(
            ChatResponse(
                tool_calls=[ToolCall(id="1", name="spotify_search", arguments={"query": "jay"})],
                usage=Usage(total_tokens=7),
            )
        )

        with patch("src.llm.planner.ThinkingConfig.get_client", return_value=client), \
            patch("src.llm.planner.ThinkingConfig.get_model", return_value="model"), \
            patch("src.llm.planner.build_planning_context", return_value="cached context"):
            action = llm_plan(user_input="/search jay", tools=_registry(), command_intent=intent)

        self.assertEqual(action.tool, "spotify_search")
        request = client.requests[0]
        self.assertIn("Command intent guidance", request.messages[0]["content"])
        self.assertIn("The user invoked /search", request.messages[0]["content"])
        user_content = request.messages[1]["content"]
        self.assertIn("[command_intent]", user_content)
        self.assertIn("command: search", user_content)
        self.assertIn("args: jay", user_content)
        self.assertIn("[preloaded_memory]\ncached context", user_content)
        tool_names = [tool["function"]["name"] for tool in request.tools]
        self.assertEqual(tool_names, ["spotify_search"])


if __name__ == "__main__":
    unittest.main()
