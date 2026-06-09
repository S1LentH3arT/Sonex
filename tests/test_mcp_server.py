"""Tests test mcp server.

Contains pytest coverage for the test mcp server behavior.
"""

from __future__ import annotations

import asyncio
import json
import unittest
from pathlib import Path

from src.mcp.server import build_mcp_server, normalize_mcp_result, visible_tool_specs
from src.tools import registry
from src.tools.registry import Params, ToolRegistry


def _structured_result(value: object) -> dict[str, object]:
    """Verifies that structured result behaves as expected.

    Typical use: Use this in automated tests when guarding the structured result behavior against regressions.

    Example: _structured_result() -> passes without assertion failures when the behavior remains correct.
    """
    if isinstance(value, tuple) and len(value) == 2 and isinstance(value[1], dict):
        return value[1]
    if isinstance(value, dict):
        return value
    raise AssertionError(f"Unexpected MCP result: {value!r}")


def _registry() -> ToolRegistry:
    """Verifies that registry behaves as expected.

    Typical use: Use this in automated tests when guarding the registry behavior against regressions.

    Example: _registry() -> passes without assertion failures when the behavior remains correct.
    """
    tools = ToolRegistry()

    def read_status(query: str, limit: int = 10) -> dict[str, object]:
        """Verifies that read status behaves as expected.

        Typical use: Use this in automated tests when guarding the read status behavior against regressions.

        Example: read_status() -> passes without assertion failures when the behavior remains correct.
        """
        return {
            "status": "success",
            "tool": "read_status",
            "message": "read",
            "data": {"query": query, "limit": limit},
        }

    def play_song(query: str) -> dict[str, object]:
        """Verifies that play song behaves as expected.

        Typical use: Use this in automated tests when guarding the play song behavior against regressions.

        Example: play_song() -> passes without assertion failures when the behavior remains correct.
        """
        return {
            "status": "success",
            "tool": "play_song",
            "message": "played",
            "data": {"query": query},
        }

    tools.register(
        name="read_status",
        type="test",
        description="Read status.",
        parameters=Params(
            type="object",
            properties={
                "query": {"type": "string", "description": "Search query."},
                "limit": {"type": "integer", "description": "Maximum results."},
            },
            required=["query"],
        ),
        fn=read_status,
        read_only=True,
        required_confirm=False,
    )
    tools.register(
        name="play_song",
        type="test",
        description="Play a song.",
        parameters=Params(
            type="object",
            properties={"query": {"type": "string", "description": "Search query."}},
            required=["query"],
        ),
        fn=play_song,
        read_only=False,
        required_confirm=False,
    )
    return tools


class McpServerTests(unittest.TestCase):
    """Groups related mcp server tests cases.

    Collects assertions that exercise mcp server tests behavior without mixing unrelated fixtures.
    """
    def test_visible_tools_are_read_only_by_default(self) -> None:
        """Verifies that visible tools are read only by default behaves as expected.

        Typical use: Use this in automated tests when guarding the visible tools are read only by default behavior against regressions.

        Example: test_visible_tools_are_read_only_by_default() -> passes without assertion failures when the behavior remains correct.
        """
        names = [spec.name for spec in visible_tool_specs(_registry())]

        self.assertIn("read_status", names)
        self.assertNotIn("play_song", names)

    def test_visible_tools_include_mutations_when_enabled(self) -> None:
        """Verifies that visible tools include mutations when enabled behaves as expected.

        Typical use: Use this in automated tests when guarding the visible tools include mutations when enabled behavior against regressions.

        Example: test_visible_tools_include_mutations_when_enabled() -> passes without assertion failures when the behavior remains correct.
        """
        names = [spec.name for spec in visible_tool_specs(_registry(), allow_mutations=True)]

        self.assertEqual(names, ["read_status", "play_song"])

    def test_real_registry_hides_playback_mutations_by_default(self) -> None:
        """Verifies that real registry hides playback mutations by default behaves as expected.

        Typical use: Use this in automated tests when guarding the real registry hides playback mutations by default behavior against regressions.

        Example: test_real_registry_hides_playback_mutations_by_default() -> passes without assertion failures when the behavior remains correct.
        """
        names = [spec.name for spec in visible_tool_specs(registry)]

        self.assertIn("spotify_search", names)
        self.assertIn("spotify_current_playback", names)
        self.assertNotIn("spotify_play", names)
        self.assertNotIn("play_local_song", names)

    def test_normalize_result_preserves_tool_result_shape_and_json_safety(self) -> None:
        """Verifies that normalize result preserves tool result shape and json safety behaves as expected.

        Typical use: Use this in automated tests when guarding the normalize result preserves tool result shape and json safety behavior against regressions.

        Example: test_normalize_result_preserves_tool_result_shape_and_json_safety() -> passes without assertion failures when the behavior remains correct.
        """
        result = normalize_mcp_result(
            "read_status",
            {
                "status": "success",
                "tool": "read_status",
                "data": {"path": Path("/tmp/song.mp3")},
            },
        )

        self.assertEqual(result["message"], "")
        self.assertIsNone(result["error_code"])
        self.assertEqual(result["data"]["path"], "/tmp/song.mp3")
        json.dumps(result)

    def test_mcp_server_lists_only_read_only_tools_by_default(self) -> None:
        """Verifies that mcp server lists only read only tools by default behaves as expected.

        Typical use: Use this in automated tests when guarding the mcp server lists only read only tools by default behavior against regressions.

        Example: test_mcp_server_lists_only_read_only_tools_by_default() -> passes without assertion failures when the behavior remains correct.
        """
        async def run() -> list[str]:
            """Verifies that run behaves as expected.

            Typical use: Use this in automated tests when guarding the run behavior against regressions.

            Example: run() -> passes without assertion failures when the behavior remains correct.
            """
            server = build_mcp_server(_registry())
            tools = await server.list_tools()
            return [tool.name for tool in tools]

        names = asyncio.run(run())

        self.assertEqual(names, ["read_status"])

    def test_fastapi_mounts_mcp_alongside_websocket(self) -> None:
        """Verifies that fastapi mounts mcp alongside websocket behaves as expected.

        Typical use: Use this in automated tests when guarding the fastapi mounts mcp alongside websocket behavior against regressions.

        Example: test_fastapi_mounts_mcp_alongside_websocket() -> passes without assertion failures when the behavior remains correct.
        """
        from src.api.app import app

        paths = [getattr(route, "path", None) for route in app.routes]

        self.assertIn("/mcp", paths)
        self.assertIn("/ws", paths)

    def test_mcp_server_invokes_registry_with_args(self) -> None:
        """Verifies that mcp server invokes registry with args behaves as expected.

        Typical use: Use this in automated tests when guarding the mcp server invokes registry with args behavior against regressions.

        Example: test_mcp_server_invokes_registry_with_args() -> passes without assertion failures when the behavior remains correct.
        """
        async def run() -> dict[str, object]:
            """Verifies that run behaves as expected.

            Typical use: Use this in automated tests when guarding the run behavior against regressions.

            Example: run() -> passes without assertion failures when the behavior remains correct.
            """
            server = build_mcp_server(_registry())
            result = await server.call_tool("read_status", {"query": "jazz", "limit": 3})
            return _structured_result(result)

        result = asyncio.run(run())

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["data"], {"query": "jazz", "limit": 3})

    def test_mcp_tool_exception_returns_structured_failure(self) -> None:
        """Verifies that mcp tool exception returns structured failure behaves as expected.

        Typical use: Use this in automated tests when guarding the mcp tool exception returns structured failure behavior against regressions.

        Example: test_mcp_tool_exception_returns_structured_failure() -> passes without assertion failures when the behavior remains correct.
        """
        tools = _registry()

        def broken() -> None:
            """Verifies that broken behaves as expected.

            Typical use: Use this in automated tests when guarding the broken behavior against regressions.

            Example: broken() -> passes without assertion failures when the behavior remains correct.
            """
            raise RuntimeError("boom")

        tools.register(
            name="broken",
            type="test",
            description="Broken tool.",
            parameters=Params(type="object", properties={}, required=[]),
            fn=broken,
            read_only=True,
            required_confirm=False,
        )

        async def run() -> dict[str, object]:
            """Verifies that run behaves as expected.

            Typical use: Use this in automated tests when guarding the run behavior against regressions.

            Example: run() -> passes without assertion failures when the behavior remains correct.
            """
            server = build_mcp_server(tools)
            result = await server.call_tool("broken", {})
            return _structured_result(result)

        result = asyncio.run(run())

        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["tool"], "broken")
        self.assertEqual(result["error_code"], "MCP_TOOL_ERROR")


if __name__ == "__main__":
    unittest.main()
