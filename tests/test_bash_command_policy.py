from __future__ import annotations

from src.sandbox.command_policy import inspect_commands, sanitize_command_display


def test_read_only_commands_are_allowed_without_review() -> None:
    decision = inspect_commands(
        ["cd src", "git status --short", "rg AgentState | head"]
    )

    assert decision.valid
    assert decision.level == "allow"


def test_unknown_write_and_build_commands_require_review() -> None:
    decision = inspect_commands(
        ["cd src/cli-ui", "npm test", "printf done > result.txt"]
    )

    assert decision.valid
    assert decision.level == "review"
    assert decision.display_commands == (
        "cd src/cli-ui",
        "npm test",
        "printf done > result.txt",
    )


def test_highest_risk_denies_the_whole_batch_and_tracks_blocked_command() -> None:
    decision = inspect_commands(["ls", "curl https://example.com", "git status"])

    assert decision.valid
    assert decision.level == "deny"
    assert decision.blocked_commands == ("curl https://example.com",)
    assert decision.blocked_rule_ids == (("network-client",),)
    assert "network-client" in decision.rule_ids


def test_long_or_dynamic_shell_programs_are_invalid() -> None:
    invalid_batches = [
        ["printf one\nprintf two"],
        ["for item in one two; do echo \"$item\"; done"],
        ["echo $(git status)"],
        ["python -c \"print('hidden program')\""],
        ["bash -c 'git status'"],
        ["echo one && echo two"],
    ]

    for commands in invalid_batches:
        decision = inspect_commands(commands)
        assert not decision.valid, commands


def test_quoted_shell_punctuation_remains_an_ordinary_argument() -> None:
    decision = inspect_commands(
        ["printf '%s' ';'", "echo 'a | b'", "rg '\\$(' src"]
    )

    assert decision.valid
    assert decision.level == "allow"


def test_command_list_has_a_twelve_item_limit() -> None:
    decision = inspect_commands(["pwd"] * 13)

    assert not decision.valid
    assert decision.invalid_reason == "Bash accepts at most 12 commands per call."


def test_display_copy_removes_terminal_controls_and_redacts_credentials() -> None:
    command = (
        "\x1b[31mAPI_TOKEN=secret\x1b[0m "
        "curl -H 'Authorization: Bearer abc123' "
        "https://user:pass@example.com"
    )

    display = sanitize_command_display(command)

    assert "\x1b" not in display
    assert "secret" not in display
    assert "abc123" not in display
    assert "user:pass" not in display
    assert display.count("[REDACTED]") == 3


def test_cd_outside_sandbox_is_hard_denied() -> None:
    decision = inspect_commands(["cd /etc", "ls"])

    assert decision.level == "deny"
    assert decision.blocked_commands == ("cd /etc",)
    assert decision.blocked_rule_ids == (("sandbox-path",),)
    assert "sandbox-path" in decision.rule_ids
