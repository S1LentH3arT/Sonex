from __future__ import annotations

import inspect
import json
import os
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP

from src.llm.transport import sanitize_error_message
from src.tools.registry import ToolRegistry, ToolSpec, registry

SONEX_MCP_ALLOW_MUTATIONS = "SONEX_MCP_ALLOW_MUTATIONS"
TRUE_VALUES = {"1", "true", "yes", "on", "allow", "enabled"}


def mcp_tools_enabled(allow_mutations: bool | None = None) -> bool:
    if allow_mutations is not None:
        return bool(allow_mutations)
    return os.getenv(SONEX_MCP_ALLOW_MUTATIONS, "").strip().lower() in TRUE_VALUES


def visible_tool_specs(
    tool_registry: ToolRegistry = registry,
    *,
    allow_mutations: bool | None = None,
) -> list[ToolSpec]:
    include_mutations = mcp_tools_enabled(allow_mutations)
    return [
        spec
        for spec in tool_registry.tools.values()
        if spec.enabled and (include_mutations or spec.read_only)
    ]


def normalize_mcp_result(tool_name: str, value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        result = dict(value)
        result.setdefault("status", "success")
        result.setdefault("tool", tool_name)
        result.setdefault("message", "")
        result.setdefault("data", {})
        result.setdefault("error_code", None)
        return _to_json_safe(result)

    return _to_json_safe(
        {
            "status": "success",
            "tool": tool_name,
            "message": "",
            "data": {"result": value},
            "error_code": None,
        }
    )


def _error_result(tool_name: str, exc: Exception) -> dict[str, Any]:
    return {
        "status": "fail",
        "tool": tool_name,
        "message": sanitize_error_message(exc),
        "data": {},
        "error_code": "MCP_TOOL_ERROR",
    }


def _to_json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _to_json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_to_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_to_json_safe(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    try:
        json.dumps(value, ensure_ascii=True)
    except TypeError:
        return str(value)
    return value


def _annotation_for_json_type(value: Any) -> Any:
    if isinstance(value, list):
        return list
    if value == "string":
        return str
    if value == "integer":
        return int
    if value == "number":
        return float
    if value == "boolean":
        return bool
    if value == "array":
        return list
    if value == "object":
        return dict
    return Any


def _tool_signature(spec: ToolSpec) -> inspect.Signature:
    properties = spec.parameters.properties or {}
    required = set(spec.parameters.required or [])
    ordered_names = [name for name in properties if name in required]
    ordered_names.extend(name for name in properties if name not in required)

    params: list[inspect.Parameter] = []
    for name in ordered_names:
        schema = properties.get(name) or {}
        annotation = _annotation_for_json_type(schema.get("type"))
        default = inspect.Parameter.empty if name in required else None
        params.append(
            inspect.Parameter(
                name,
                inspect.Parameter.KEYWORD_ONLY,
                default=default,
                annotation=annotation,
            )
        )

    return inspect.Signature(
        parameters=params,
        return_annotation=dict[str, Any],
    )


def _wrapper_for_tool(tool_registry: ToolRegistry, spec: ToolSpec):
    def call_tool(**kwargs: Any) -> dict[str, Any]:
        try:
            result = tool_registry.invoke(spec.name, kwargs)
        except Exception as exc:
            return _error_result(spec.name, exc)
        return normalize_mcp_result(spec.name, result)

    call_tool.__name__ = spec.name
    call_tool.__qualname__ = spec.name
    call_tool.__doc__ = spec.description
    call_tool.__signature__ = _tool_signature(spec)  # type: ignore[attr-defined]
    return call_tool


def build_mcp_server(
    tool_registry: ToolRegistry = registry,
    *,
    allow_mutations: bool | None = None,
    name: str = "Sonex",
    streamable_http_path: str = "/mcp",
) -> FastMCP:
    mcp = FastMCP(
        name,
        instructions=(
            "Use Sonex tools for local music search, account status, recommendations, "
            "and playback state. Playback-changing tools are hidden unless mutations "
            "are explicitly enabled by the Sonex user."
        ),
        stateless_http=True,
        json_response=True,
        streamable_http_path=streamable_http_path,
    )

    for spec in visible_tool_specs(tool_registry, allow_mutations=allow_mutations):
        mcp.add_tool(
            _wrapper_for_tool(tool_registry, spec),
            name=spec.name,
            description=spec.description,
            structured_output=True,
            meta={
                "sonex_type": spec.type,
                "sonex_read_only": spec.read_only,
            },
        )

    return mcp


def run_mcp_server(
    *,
    transport: Literal["stdio", "http"] = "stdio",
    host: str = "127.0.0.1",
    port: int = 9002,
    allow_mutations: bool | None = None,
) -> None:
    mcp = build_mcp_server(allow_mutations=allow_mutations)
    if transport == "stdio":
        mcp.run(transport="stdio")
        return

    mcp.settings.host = host
    mcp.settings.port = port
    mcp.run(transport="streamable-http")
