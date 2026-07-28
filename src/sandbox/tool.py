"""Agent-facing Bash Tool backed by :mod:`src.sandbox.manager`."""

from __future__ import annotations

from src.sandbox.manager import SandboxManager
from src.tools.registry import Params, ToolRegistry, registry

_manager = SandboxManager()


def Bash(
    script: str,
    cwd: str = "/work",
    timeout_ms: int = 30_000,
) -> dict[str, object]:
    """Execute native Bash syntax inside the mandatory Sonex sandbox."""
    return _manager.execute(script, cwd=cwd, timeout_ms=timeout_ms).to_dict()


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
            "Run native Bash syntax in the restricted Sonex sandbox. The shell has "
            "no public network or credentials; use Query, Connect, and Call for "
            "provider operations."
        ),
        parameters=Params(
            type="object",
            properties={
                "script": {"type": "string", "description": "Bash script to execute."},
                "cwd": {
                    "type": "string",
                    "description": "Sandbox cwd within /work, /music, or /tmp.",
                    "default": "/work",
                },
                "timeout_ms": {
                    "type": "integer",
                    "minimum": 1000,
                    "maximum": 120000,
                    "default": 30000,
                },
            },
            required=["script"],
        ),
        fn=Bash,
        read_only=False,
        confirm_required=False,
        availability=lambda: _manager.ready(),
    )


register_bash_tool()
