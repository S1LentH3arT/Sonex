"""Agent-facing Bash Tool backed by :mod:`src.sandbox.manager`."""

from __future__ import annotations

from src.sandbox.command_policy import (
    MAX_BASH_COMMAND_LENGTH,
    MAX_BASH_COMMANDS,
    inspect_commands,
)
from src.sandbox.manager import SandboxManager
from src.tools.registry import Params, ToolRegistry, registry

_manager = SandboxManager()


def Bash(
    commands: list[str],
    timeout_ms: int = 30_000,
) -> dict[str, object]:
    """Execute one ordered, reviewable command list in the mandatory sandbox."""
    decision = inspect_commands(commands)
    if not decision.valid:
        raise ValueError(decision.invalid_reason)
    if decision.level == "deny":
        raise PermissionError("Bash commands were denied by the Sonex guardrail.")
    script = "set -e -o pipefail\n" + "\n".join(decision.commands)
    return _manager.execute(script, cwd="/work", timeout_ms=timeout_ms).to_dict()


def sandbox_manager() -> SandboxManager:
    return _manager


def set_sandbox_manager_for_tests(manager: SandboxManager) -> None:
    global _manager
    _manager = manager


def register_bash_tool(tool_registry: ToolRegistry = registry) -> None:
    tool_registry.register(
        name="Bash",
        kind="agent",
        domain="sandbox",
        description=(
            "Run an ordered list of simple commands in one restricted sandbox shell. "
            "Each commands item must contain one command or one single-line pipeline. "
            "Commands run sequentially and stop on failure; cd affects later items in "
            "this call only. Complex or inline shell programs are rejected. The shell "
            "has no public network or credentials; use Query, Connect, and Call for "
            "provider operations."
        ),
        parameters=Params(
            type="object",
            properties={
                "commands": {
                    "type": "array",
                    "description": (
                        "One to twelve simple commands in execution order. Each item "
                        "must be one physical line."
                    ),
                    "items": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": MAX_BASH_COMMAND_LENGTH,
                    },
                    "minItems": 1,
                    "maxItems": MAX_BASH_COMMANDS,
                },
                "timeout_ms": {
                    "type": "integer",
                    "minimum": 1000,
                    "maximum": 120000,
                    "default": 30000,
                },
            },
            required=["commands"],
        ),
        fn=Bash,
        read_only=False,
        confirm_required=False,
        availability=lambda: _manager.ready(),
    )


register_bash_tool()
