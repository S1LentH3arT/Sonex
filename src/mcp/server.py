"""Server support for mcp server exposure for sonex tools.

Implements the server module responsibilities used by Sonex runtime flows.
Key public entry points include mcp_tools_enabled, visible_tool_specs, normalize_mcp_result, build_mcp_server, run_mcp_server.
"""

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
    """Coordinates mcp tools enabled for the current Sonex flow.

    Typical use: Use this function when runtime code needs mcp tools enabled as part of a Sonex command, playback, auth, llm, or ui path.

    Example: mcp_tools_enabled(allow_mutations=...) -> returns the value used by the surrounding Sonex flow.
    """
    if allow_mutations is not None:
        return bool(allow_mutations)
    return os.getenv(SONEX_MCP_ALLOW_MUTATIONS, "").strip().lower() in TRUE_VALUES


def visible_tool_specs(
    tool_registry: ToolRegistry = registry,
    *,
    allow_mutations: bool | None = None,
) -> list[ToolSpec]:
    """Coordinates visible tool specs for the current Sonex flow.

    Typical use: Use this function when runtime code needs visible tool specs as part of a Sonex command, playback, auth, llm, or ui path.

    Example: visible_tool_specs(tool_registry=..., allow_mutations=...) -> returns the value used by the surrounding Sonex flow.
    """
    include_mutations = mcp_tools_enabled(allow_mutations)
    return [
        spec
        for spec in tool_registry.tools.values()
        if spec.enabled and (include_mutations or spec.read_only)
    ]


def normalize_mcp_result(tool_name: str, value: Any) -> dict[str, Any]:
    """Coordinates normalize mcp result for the current Sonex flow.

    Typical use: Use this function when runtime code needs normalize mcp result as part of a Sonex command, playback, auth, llm, or ui path.

    Example: normalize_mcp_result(tool_name=..., value=...) -> returns the value used by the surrounding Sonex flow.
    """
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
    """Prepares error result for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs error result without duplicating the local rules.

    Example: _error_result(tool_name=..., exc=...) -> returns the value used by the surrounding Sonex flow.
    """
    return {
        "status": "fail",
        "tool": tool_name,
        "message": sanitize_error_message(exc),
        "data": {},
        "error_code": "MCP_TOOL_ERROR",
    }


def _to_json_safe(value: Any) -> Any:
    """Prepares to json safe for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs to json safe without duplicating the local rules.

    Example: _to_json_safe(value=...) -> returns the value used by the surrounding Sonex flow.
    """
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
    """Prepares annotation for json type for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs annotation for json type without duplicating the local rules.

    Example: _annotation_for_json_type(value=...) -> returns the value used by the surrounding Sonex flow.
    """
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
    """Prepares tool signature for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs tool signature without duplicating the local rules.

    Example: _tool_signature(spec=...) -> returns the value used by the surrounding Sonex flow.
    """
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
    """Prepares wrapper for tool for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs wrapper for tool without duplicating the local rules.

    Example: _wrapper_for_tool(tool_registry=..., spec=...) -> returns the value used by the surrounding Sonex flow.
    """
    def call_tool(**kwargs: Any) -> dict[str, Any]:
        """Coordinates call tool for the current Sonex flow.

        Typical use: Use this function when runtime code needs call tool as part of a Sonex command, playback, auth, llm, or ui path.

        Example: call_tool() -> returns the value used by the surrounding Sonex flow.
        """
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
    """Builds mcp server from the supplied input.

    Typical use: Use this function when runtime code needs build mcp server as part of a Sonex command, playback, auth, llm, or ui path.

    Example: build_mcp_server(tool_registry=..., allow_mutations=..., name=..., streamable_http_path=...) -> returns the value used by the surrounding Sonex flow.
    """
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
    """Coordinates run mcp server for the current Sonex flow.

    Typical use: Use this function when runtime code needs run mcp server as part of a Sonex command, playback, auth, llm, or ui path.

    Example: run_mcp_server(transport=..., host=..., port=..., allow_mutations=...) -> returns the value used by the surrounding Sonex flow.
    """
    mcp = build_mcp_server(allow_mutations=allow_mutations)
    if transport == "stdio":
        mcp.run(transport="stdio")
        return

    mcp.settings.host = host
    mcp.settings.port = port
    mcp.run(transport="streamable-http")
