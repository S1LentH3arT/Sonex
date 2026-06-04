from __future__ import annotations

import asyncio
import json
import unittest
from pathlib import Path

from src.mcp.server import build_mcp_server, normalize_mcp_result, visible_tool_specs
from src.tools import registry
from src.tools.registry import Params, ToolRegistry


def _structured_result(value: object) -> dict[str, object]:
    if isinstance(value, tuple) and len(value) == 2 and isinstance(value[1], dict):
        return value[1]
    if isinstance(value, dict):
        return value
    raise AssertionError(f"Unexpected MCP result: {value!r}")


def _registry() -> ToolRegistry:
    tools = ToolRegistry()

    def read_status(query: str, limit: int = 10) -> dict[str, object]:
        return {
            "status": "success",
            "tool": "read_status",
            "message": "read",
            "data": {"query": query, "limit": limit},
        }

    def play_song(query: str) -> dict[str, object]:
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
    def test_visible_tools_are_read_only_by_default(self) -> None:
        names = [spec.name for spec in visible_tool_specs(_registry())]

        self.assertIn("read_status", names)
        self.assertNotIn("play_song", names)

    def test_visible_tools_include_mutations_when_enabled(self) -> None:
        names = [spec.name for spec in visible_tool_specs(_registry(), allow_mutations=True)]

        self.assertEqual(names, ["read_status", "play_song"])

    def test_real_registry_hides_playback_mutations_by_default(self) -> None:
        names = [spec.name for spec in visible_tool_specs(registry)]

        self.assertIn("spotify_search", names)
        self.assertIn("spotify_current_playback", names)
        self.assertNotIn("spotify_play", names)
        self.assertNotIn("play_local_song", names)

    def test_normalize_result_preserves_tool_result_shape_and_json_safety(self) -> None:
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
        async def run() -> list[str]:
            server = build_mcp_server(_registry())
            tools = await server.list_tools()
            return [tool.name for tool in tools]

        names = asyncio.run(run())

        self.assertEqual(names, ["read_status"])

    def test_fastapi_mounts_mcp_alongside_websocket(self) -> None:
        from src.api.app import app

        paths = [getattr(route, "path", None) for route in app.routes]

        self.assertIn("/mcp", paths)
        self.assertIn("/ws", paths)

    def test_mcp_server_invokes_registry_with_args(self) -> None:
        async def run() -> dict[str, object]:
            server = build_mcp_server(_registry())
            result = await server.call_tool("read_status", {"query": "jazz", "limit": 3})
            return _structured_result(result)

        result = asyncio.run(run())

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["data"], {"query": "jazz", "limit": 3})

    def test_mcp_tool_exception_returns_structured_failure(self) -> None:
        tools = _registry()

        def broken() -> None:
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
            server = build_mcp_server(tools)
            result = await server.call_tool("broken", {})
            return _structured_result(result)

        result = asyncio.run(run())

        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["tool"], "broken")
        self.assertEqual(result["error_code"], "MCP_TOOL_ERROR")


if __name__ == "__main__":
    unittest.main()
