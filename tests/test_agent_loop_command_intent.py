from __future__ import annotations

import unittest
from dataclasses import dataclass
from unittest.mock import patch

from src.agent.action import Action
from src.agent.core import agent_loop
from src.api.builtin_commands import CommandIntent, parse_builtin_command
from src.tools.registry import Params, ToolRegistry


def _registry(*, read_only: bool = True) -> ToolRegistry:
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


class AgentLoopCommandIntentTests(unittest.TestCase):
    def test_command_intent_is_passed_to_planner(self) -> None:
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
        with patch("src.agent.core.append_context"), \
            patch("src.agent.core.llm_plan", return_value=Action(output="answer", usage=3)), \
            patch("src.agent.core.finalize_turn", side_effect=RuntimeError("cache failed")):
            states = list(agent_loop("hello", _registry()))

        self.assertEqual(states[-1].type, "complete")
        self.assertEqual(states[-1].content, "answer")

    def test_premium_capability_error_returns_clear_final_answer(self) -> None:
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


if __name__ == "__main__":
    unittest.main()
