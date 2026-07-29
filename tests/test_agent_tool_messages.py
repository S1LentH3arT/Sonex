from __future__ import annotations

from src.agent.action import ToolAction
from src.agent.tool_messages import (
    approved_commands_message,
    blocked_commands_message,
    format_tool_batch,
    rejected_commands_message,
)


def test_tool_batch_formats_semantic_values_and_aligned_multivalue_blocks() -> None:
    message = format_tool_batch(
        [
            ToolAction("Read", {"files": ["USER.md", "My Notes.md"]}),
            ToolAction(
                "Bash",
                {"commands": ["npm --prefix src/cli-ui test", "git status --short"]},
            ),
            ToolAction(
                "Query",
                {
                    "provider": "spotify",
                    "resource": "catalog",
                    "query": "Miles Davis live",
                    "limit": 10,
                },
            ),
        ]
    )

    assert message.text == (
        "Read  USER.md\n"
        "      My Notes.md\n\n"
        "Bash  npm --prefix src/cli-ui test\n"
        "      git status --short\n\n"
        "Query  spotify catalog Miles Davis live"
    )
    assert [segment["style"] for segment in message.segments].count("tool_name") == 3
    assert "".join(segment["text"] for segment in message.segments) == message.text


def test_call_omits_keys_and_internal_nested_values() -> None:
    message = format_tool_batch(
        [
            ToolAction(
                "Call",
                {
                    "workflow": "playback.play",
                    "arguments": {
                        "provider": "local",
                        "query": "Blue in Green",
                        "internal": {"opaque": True},
                    },
                },
            )
        ]
    )

    assert message.text == "Call  playback.play local Blue in Green"
    assert "provider=" not in message.text
    assert "internal" not in message.text


def test_approval_and_rejection_copy_is_one_sentence_per_command() -> None:
    commands = ["cd src", "npm test"]

    assert approved_commands_message(commands) == (
        "You confirmed running 'cd src' this time.\n"
        "You confirmed running 'npm test' this time."
    )
    assert rejected_commands_message(commands) == (
        "You rejected running 'cd src'.\n"
        "You rejected running 'npm test'."
    )


def test_blocked_copy_lists_only_denied_commands_and_safe_reason() -> None:
    message = blocked_commands_message(
        ["curl https://example.com", "cd /etc"],
        ["network-client", "sandbox-path"],
        [["network-client"], ["sandbox-path"]],
    )

    assert message == (
        "The tool-call batch was blocked, and no tools were run.\n"
        "'curl https://example.com' violates the sandbox policy: network access.\n"
        "'cd /etc' violates the sandbox policy: path outside the sandbox."
    )
