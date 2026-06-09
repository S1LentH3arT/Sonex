"""Tests test agent loop command intent.

Contains pytest coverage for the test agent loop command intent behavior.
"""

from __future__ import annotations

import unittest
from dataclasses import dataclass
from unittest.mock import patch

from src.agent.action import Action
from src.agent.core import agent_loop
from src.api.builtin_commands import CommandIntent, parse_builtin_command
from src.tools.registry import Params, ToolRegistry


def _registry(*, read_only: bool = True) -> ToolRegistry:
    """Validate registry.

    Exercises the registry behavior through the test suite.

    Args:
        read_only: Pytest fixture or input used by this test.
    """
    tools = ToolRegistry()
    tools.register(
        name="spotify_play" if not read_only else "spotify_search",
        type="spotify",
        description="test tool",
        parameters=Params(type="object", properties={}, required=[]),
        fn=lambda **kwargs: {"ok": True, "args": kwargs},
        read_only=read_only,
        confirm_required=not read_only,
    )
    return tools


def _youtube_registry() -> ToolRegistry:
    """Validate youtube registry.

    Exercises the youtube registry behavior through the test suite.
    """
    tools = ToolRegistry()
    tools.register(
        name="play_youtube_song",
        type="player",
        description="Play YouTube audio via a local player.",
        parameters=Params(type="object", properties={}, required=[]),
        fn=lambda **kwargs: {"ok": True, "args": kwargs},
        read_only=False,
    )
    return tools


def _premium_error_registry() -> ToolRegistry:
    """Validate premium error registry.

    Exercises the premium error registry behavior through the test suite.
    """
    tools = ToolRegistry()
    tools.register(
        name="spotify_play",
        type="player",
        description="Play Spotify audio.",
        parameters=Params(type="object", properties={}, required=[]),
        fn=lambda **kwargs: {
            "status": "fail",
            "tool": "spotify_play",
            "message": "Spotify playback control requires a Premium account.",
            "error_code": "SPOTIFY_PREMIUM_REQUIRED",
        },
        read_only=True,
    )
    return tools


def _search_premium_error_registry() -> ToolRegistry:
    """Validate search premium error registry.

    Exercises the search premium error registry behavior through the test suite.
    """
    tools = ToolRegistry()
    tools.register(
        name="spotify_search",
        type="search",
        description="Search Spotify audio.",
        parameters=Params(type="object", properties={}, required=[]),
        fn=lambda **kwargs: {
            "status": "fail",
            "tool": "spotify_search",
            "message": "Spotify app search requires a Premium account for the app owner.",
            "error_code": "SPOTIFY_APP_PREMIUM_REQUIRED",
        },
        read_only=True,
    )
    return tools


class AgentLoopCommandIntentTests(unittest.TestCase):
    """Groups agent loop command intent tests tests.

    Collects related assertions for agent loop command intent tests behavior.
    """
    def test_empty_allowed_tools_rejects_planner_tool_call(self) -> None:
        """Validate test empty allowed tools rejects planner tool call.

        Exercises the test empty allowed tools rejects planner tool call behavior through the test suite.
        """
        tools = _registry()
        intent = CommandIntent(
            command="general",
            raw="hello",
            args="",
            intent_prompt="Answer without tools.",
            allowed_tools=(),
        )

        with patch("src.agent.core.append_context"), \
            patch("src.agent.core.llm_plan", return_value=Action(tool="spotify_search", args={"query": "x"}, usage=1)), \
            patch.object(tools, "invoke", wraps=tools.invoke) as invoke:
            state = next(state for state in agent_loop("hello", tools, command_intent=intent) if state.type == "error")

        self.assertIn("not allowed", state.content)
        invoke.assert_not_called()

    def test_planner_playback_tool_outside_allowlist_is_rejected(self) -> None:
        """Validate test planner playback tool outside allowlist is rejected.

        Exercises the test planner playback tool outside allowlist is rejected behavior through the test suite.
        """
        tools = _youtube_registry()
        intent = CommandIntent(
            command="recommend",
            raw="recommend songs",
            args="songs",
            intent_prompt="Recommend only.",
            allowed_tools=("spotify_recommend",),
        )

        with patch("src.agent.core.append_context"), \
            patch("src.agent.core.llm_plan", return_value=Action(tool="play_youtube_song", args={"query": "song"}, usage=1)), \
            patch.object(tools, "invoke", wraps=tools.invoke) as invoke:
            state = next(state for state in agent_loop("recommend songs", tools, command_intent=intent) if state.type == "error")

        self.assertIn("not allowed", state.content)
        invoke.assert_not_called()

    def test_command_intent_is_passed_to_planner(self) -> None:
        """Validate test command intent is passed to planner.

        Exercises the test command intent is passed to planner behavior through the test suite.
        """
        parsed = parse_builtin_command("/search jay")
        assert parsed is not None
        intent = parsed.command_intent()
        assert intent is not None

        with patch("src.agent.core.append_context"), \
            patch("src.agent.core.append_tool_summary"), \
            patch("src.agent.core.llm_plan", return_value=Action(output="answer", usage=3)) as plan, \
            patch("src.agent.core.finalize_turn"):
            states = list(agent_loop("/search jay", _registry(), command_intent=intent))

        plan.assert_called_once()
        self.assertEqual(plan.call_args.kwargs["command_intent"], intent)
        self.assertEqual(states[-1].type, "complete")
        self.assertEqual(states[-1].content, "answer")

    def test_rejected_write_tool_is_not_invoked(self) -> None:
        """Validate test rejected write tool is not invoked.

        Exercises the test rejected write tool is not invoked behavior through the test suite.
        """
        tools = _registry(read_only=False)
        intent = CommandIntent(
            command="test",
            raw="/test",
            args="song",
            intent_prompt="Test write confirmation.",
            allowed_tools=("spotify_play",),
        )

        with patch("src.agent.core.append_context"), \
            patch("src.agent.core.llm_plan", return_value=Action(tool="spotify_play", args={"query": "song"}, usage=4)), \
            patch.object(tools, "invoke", wraps=tools.invoke) as invoke:
            gen = agent_loop("/test song", tools, command_intent=intent)
            first = next(gen)
            self.assertEqual(first.type, "status")
            confirm = next(gen)
            self.assertEqual(confirm.type, "confirm")
            self.assertEqual(confirm.tool, "spotify_play")
            followup = gen.send("deny")

        self.assertEqual(followup.type, "status")
        invoke.assert_not_called()

    def test_youtube_playback_tool_requires_confirmation_before_invocation(self) -> None:
        """Validate test youtube playback tool requires confirmation before invocation.

        Exercises the test youtube playback tool requires confirmation before invocation behavior through the test suite.
        """
        tools = _youtube_registry()
        intent = CommandIntent(
            command="test",
            raw="/test",
            args="song",
            intent_prompt="Test playback confirmation.",
            allowed_tools=("play_youtube_song",),
        )

        with patch("src.agent.core.append_context"), \
            patch("src.agent.core.llm_plan", return_value=Action(tool="play_youtube_song", args={"query": "song"}, usage=4)), \
            patch.object(tools, "invoke", wraps=tools.invoke) as invoke:
            gen = agent_loop("/test song", tools, command_intent=intent)
            first = next(gen)
            self.assertEqual(first.type, "status")
            confirm = next(gen)
            self.assertEqual(confirm.type, "confirm")
            self.assertEqual(confirm.tool, "play_youtube_song")
            followup = gen.send("deny")

        self.assertEqual(followup.type, "status")
        invoke.assert_not_called()

    def test_finalize_turn_failure_does_not_block_final_answer(self) -> None:
        """Validate test finalize turn failure does not block final answer.

        Exercises the test finalize turn failure does not block final answer behavior through the test suite.
        """
        with patch("src.agent.core.append_context"), \
            patch("src.agent.core.llm_plan", return_value=Action(output="answer", usage=3)), \
            patch("src.agent.core.finalize_turn", side_effect=RuntimeError("cache failed")):
            states = list(agent_loop("hello", _registry()))

        self.assertEqual(states[-1].type, "complete")
        self.assertEqual(states[-1].content, "answer")

    def test_premium_capability_error_returns_clear_final_answer(self) -> None:
        """Validate test premium capability error returns clear final answer.

        Exercises the test premium capability error returns clear final answer behavior through the test suite.
        """
        tools = _premium_error_registry()

        with patch("src.agent.core.append_context"), \
            patch("src.agent.core.append_tool_summary"), \
            patch("src.agent.core.finalize_turn"), \
            patch("src.agent.core.llm_plan", return_value=Action(tool="spotify_play", args={"query": "song"}, usage=3)) as plan:
            states = list(agent_loop("play song", tools))

        self.assertEqual(states[-1].type, "complete")
        self.assertIn("Spotify", states[-1].content)
        self.assertIn("Premium", states[-1].content)
        self.assertIn("YouTube", states[-1].content)
        plan.assert_called_once()

    def test_spotify_search_premium_error_does_not_claim_spotify_search_works(self) -> None:
        """Validate test spotify search premium error does not claim spotify search works.

        Exercises the test spotify search premium error does not claim spotify search works behavior through the test suite.
        """
        tools = _search_premium_error_registry()

        with patch("src.agent.core.append_context"), \
            patch("src.agent.core.append_tool_summary"), \
            patch("src.agent.core.finalize_turn"), \
            patch("src.agent.core.llm_plan", return_value=Action(tool="spotify_search", args={"query": "song"}, usage=3)) as plan:
            states = list(agent_loop("search song", tools))

        self.assertEqual(states[-1].type, "complete")
        self.assertIn("Spotify app search requires", states[-1].content)
        self.assertIn("YouTube/local playback", states[-1].content)
        self.assertNotIn("search Spotify results", states[-1].content)
        plan.assert_called_once()


if __name__ == "__main__":
    unittest.main()
