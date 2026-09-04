from __future__ import annotations

from unittest.mock import patch

import pytest

from src.agent.action import Action, ToolAction
from src.agent.core import agent_loop
from src.tools.registry import Params, ToolRegistry


def _registry(invocations: list[str]) -> ToolRegistry:
    tools = ToolRegistry()
    for name in ("Read", "Bash", "Query"):
        tools.register(
            name=name,
            kind="agent",
            domain="test",
            description="test",
            parameters=Params(type="object", properties={}, required=[]),
            fn=lambda _name=name, **_kwargs: invocations.append(_name) or {"status": "success"},
            read_only=name != "Bash",
            confirm_required=False,
        )
    return tools


def test_multi_tool_batch_is_announced_once_then_runs_in_model_order() -> None:
    invocations: list[str] = []
    tools = _registry(invocations)
    planned = Action(
        tool_calls=[
            ToolAction("Read", {"query": "preferences"}),
            ToolAction("Bash", {"commands": ["git status --short"]}),
            ToolAction("Query", {"provider": "local", "resource": "library"}),
        ],
        usage=4,
    )

    with patch("src.agent.core.append_context"), patch(
        "src.agent.core.append_tool_summary"
    ), patch("src.agent.core.finalize_turn"), patch(
        "src.agent.core.llm_plan",
        side_effect=[planned, Action(output="done", usage=2)],
    ):
        states = list(agent_loop("inspect", tools))

    assert [state.type for state in states].count("tool_batch") == 1
    batch = next(state for state in states if state.type == "tool_batch")
    assert [call.tool for call in batch.calls or []] == ["Read", "Bash", "Query"]
    assert invocations == ["Read", "Bash", "Query"]


def test_review_batch_pages_by_four_and_approves_before_announcement() -> None:
    invocations: list[str] = []
    commands = [f"npm run task-{index}" for index in range(9)]
    tools = _registry(invocations)
    gen = agent_loop("build", tools)

    with patch("src.agent.core.append_context"), patch(
        "src.agent.core.append_tool_summary"
    ), patch(
        "src.agent.core.llm_plan",
        return_value=Action(
            tool_calls=[ToolAction("Bash", {"commands": commands})],
            usage=1,
        ),
    ):
        assert next(gen).type == "status"
        first = next(gen)
        assert first.type == "confirm"
        assert first.args["commands"] == commands[:4]
        assert first.args["message"] == "Tool call double check 1/3"

        second = gen.send("allow_once")
        assert second.args["commands"] == commands[4:8]
        third = gen.send("allow_once")
        assert third.args["commands"] == commands[8:]

        approved = gen.send("allow_once")
        assert approved.type == "tool_approved"
        assert approved.args["commands"] == commands
        announced = next(gen)
        assert announced.type == "tool_batch"
        started = next(gen)
        assert started.type == "tool"


def test_rejecting_a_later_page_terminates_without_tool_announcement() -> None:
    invocations: list[str] = []
    commands = [f"npm run task-{index}" for index in range(5)]
    tools = _registry(invocations)

    with patch("src.agent.core.append_context"), patch(
        "src.agent.core.llm_plan",
        return_value=Action(
            tool_calls=[ToolAction("Bash", {"commands": commands})],
            usage=1,
        ),
    ):
        gen = agent_loop("build", tools)
        assert next(gen).type == "status"
        assert next(gen).type == "confirm"
        assert gen.send("allow_once").type == "confirm"
        rejected = gen.send("deny")
        assert rejected.type == "tool_rejected"
        with pytest.raises(StopIteration):
            next(gen)

    assert invocations == []


def test_hard_deny_blocks_the_whole_tool_batch_without_confirmation() -> None:
    invocations: list[str] = []
    tools = _registry(invocations)

    with patch("src.agent.core.append_context"), patch(
        "src.agent.core.llm_plan",
        return_value=Action(
            tool_calls=[
                ToolAction("Read", {"query": "context"}),
                ToolAction("Bash", {"commands": ["ls", "curl https://example.com"]}),
            ],
            usage=1,
        ),
    ):
        states = list(agent_loop("inspect", tools))

    assert [state.type for state in states] == ["status", "tool_blocked"]
    assert states[-1].args["commands"] == ["curl https://example.com"]
    assert invocations == []


def test_invalid_bash_gets_one_rewrite_then_a_warning() -> None:
    invocations: list[str] = []
    tools = _registry(invocations)
    invalid = Action(
        tool_calls=[ToolAction("Bash", {"commands": ["python -c 'print(1)'"]})],
        usage=1,
    )

    with patch("src.agent.core.append_context"), patch(
        "src.agent.core.llm_plan",
        side_effect=[invalid, invalid],
    ) as planner:
        states = list(agent_loop("run code", tools))

    assert [state.type for state in states] == ["status", "status", "warning"]
    assert states[-1].content == "Agent could not produce reviewable Bash commands."
    assert "planning_feedback" in planner.call_args_list[1].kwargs
    assert invocations == []


def test_committed_playback_selection_ends_without_second_llm_plan() -> None:
    tools = ToolRegistry()
    tools.register(
        name="Call",
        kind="agent",
        domain="workflow",
        description="test",
        parameters=Params(type="object", properties={}, required=[]),
        fn=lambda **_: {
            "status": "requires_play_selection",
            "data": {"query": "方大同 BB88"},
        },
        read_only=False,
        confirm_required=False,
    )
    with patch("src.agent.core.append_context"), patch(
        "src.agent.core.append_tool_summary"
    ), patch("src.agent.core.finalize_turn"), patch(
        "src.agent.core.llm_plan",
        return_value=Action(
            tool="Call",
            args={
                "workflow": "playback.select",
                "arguments": {"query": "方大同 BB88"},
            },
            usage=1,
        ),
    ) as planner:
        gen = agent_loop("播放方大同的BB88", tools)
        assert next(gen).type == "status"
        assert next(gen).type == "tool_batch"
        assert next(gen).type == "tool"
        assert next(gen).type == "interaction"
        tool_result = gen.send(
            {
                "status": "playback_completed",
                "data": {"provider": "Spotify"},
            }
        )
        assert tool_result.type == "tool"
        assert next(gen).type == "complete"

    planner.assert_called_once()
