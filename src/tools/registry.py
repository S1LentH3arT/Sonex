"""Registry support for tool implementations used by the planner and playback flows.

Implements the registry module responsibilities used by Sonex runtime flows.
Key public entry points include Params, ToolSpec, ToolRegistry.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Callable


ToolFn = Callable[..., Any]


@dataclass(frozen=True)
class Params:
    """Represents params.

    Encapsulates params data and behavior used by Sonex runtime flows.
    """
    type: str
    properties: dict[str, Any]
    required: list[str]


@dataclass(frozen=True)
class ToolSpec:
    """Represents tool spec.

    Encapsulates tool spec data and behavior used by Sonex runtime flows.
    """
    name: str
    type: str
    description: str
    parameters: Params
    fn: ToolFn
    enabled: bool = True
    read_only: bool = True
    confirm_required: bool = True

    def to_openai_schema(self) -> dict[str, Any]:
        """Coordinates to openai schema for the current Sonex flow.

        Typical use: Use this function when runtime code needs to openai schema as part of a Sonex command, playback, auth, llm, or ui path.

        Example: to_openai_schema() -> returns the value used by the surrounding Sonex flow.
        """
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": self.parameters.type,
                    "properties": self.parameters.properties,
                    "required": self.parameters.required,
                },
            },
        }


class ToolRegistry:
    """Represents tool registry.

    Encapsulates tool registry data and behavior used by Sonex runtime flows.
    """
    def __init__(self) -> None:
        """Init for tool registry.

        Coordinates the init method behavior while preserving tool registry state and contracts.
        """
        self.tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec | None = None, **kwargs: Any) -> None:
        """Coordinates register for the current Sonex flow.

        Typical use: Use this function when runtime code needs register as part of a Sonex command, playback, auth, llm, or ui path.

        Example: register(spec=...) -> returns the value used by the surrounding Sonex flow.
        """
        if spec is None:
            spec = ToolSpec(
                name=kwargs["name"],
                type=kwargs["type"],
                description=kwargs["description"],
                parameters=kwargs["parameters"],
                fn=kwargs["fn"],
                enabled=kwargs.get("enabled", kwargs.get("enable", True)),
                read_only=kwargs.get("read_only", True),
                confirm_required=not kwargs.get("read_only", True),
            )
        elif spec.confirm_required != (not spec.read_only):
            spec = replace(spec, confirm_required=not spec.read_only)

        if spec.name in self.tools:
            raise ValueError(f"Tool '{spec.name}' already registered.")
        self.tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec | None:
        """Coordinates get for the current Sonex flow.

        Typical use: Use this function when runtime code needs get as part of a Sonex command, playback, auth, llm, or ui path.

        Example: get(name=...) -> returns the value used by the surrounding Sonex flow.
        """
        spec = self.tools.get(name)
        if not spec or not spec.enabled:
            return None
        return spec

    def schemas(self, allowed_tools: tuple[str, ...] | set[str] | None = None) -> list[dict[str, Any]]:
        """Coordinates schemas for the current Sonex flow.

        Typical use: Use this function when runtime code needs schemas as part of a Sonex command, playback, auth, llm, or ui path.

        Example: schemas(allowed_tools=...) -> returns the value used by the surrounding Sonex flow.
        """
        allowed = None if allowed_tools is None else set(allowed_tools)
        return [
            spec.to_openai_schema()
            for spec in self.tools.values()
            if spec.enabled and (allowed is None or spec.name in allowed)
        ]

    def invoke(self, name: str, args: dict[str, Any] | None = None) -> Any:
        """Coordinates invoke for the current Sonex flow.

        Typical use: Use this function when runtime code needs invoke as part of a Sonex command, playback, auth, llm, or ui path.

        Example: invoke(name=..., args=...) -> returns the value used by the surrounding Sonex flow.
        """
        spec = self.get(name)
        if not spec:
            raise ValueError(f"Tool '{name}' not found or not allowed.")
        return spec.fn(**(args or {}))


registry = ToolRegistry()
