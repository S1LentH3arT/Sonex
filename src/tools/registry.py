"""Registry support for tool implementations used by the planner and playback flows.

Implements the registry module responsibilities used by Sonex runtime flows.
Key public entry points include Params, ToolSpec, ToolRegistry.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Literal


ToolFn = Callable[..., Any]
ToolKind = Literal["system", "agent"]


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
    kind: ToolKind
    domain: str
    description: str
    parameters: Params
    fn: ToolFn
    enabled: bool = True
    read_only: bool = True
    confirm_required: bool = True
    availability: Callable[[], bool] | None = None

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
            if "kind" not in kwargs or "domain" not in kwargs:
                raise TypeError("Tool registration requires explicit 'kind' and 'domain'.")
            spec = ToolSpec(
                name=kwargs["name"],
                kind=kwargs["kind"],
                domain=kwargs["domain"],
                description=kwargs["description"],
                parameters=kwargs["parameters"],
                fn=kwargs["fn"],
                enabled=kwargs.get("enabled", kwargs.get("enable", True)),
                read_only=kwargs.get("read_only", True),
                confirm_required=kwargs.get(
                    "confirm_required",
                    not kwargs.get("read_only", True),
                ),
                availability=kwargs.get("availability"),
            )
        if spec.kind not in {"system", "agent"}:
            raise ValueError(f"Unsupported tool kind: {spec.kind!r}.")
        if not spec.domain.strip():
            raise ValueError("Tool domain cannot be empty.")

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
        if spec.availability is not None and not spec.availability():
            return None
        return spec

    def get_system(self, name: str) -> ToolSpec | None:
        """Return one enabled trusted runtime tool."""
        spec = self.get(name)
        return spec if spec is not None and spec.kind == "system" else None

    def get_agent(self, name: str) -> ToolSpec | None:
        """Return one enabled model-callable tool."""
        spec = self.get(name)
        return spec if spec is not None and spec.kind == "agent" else None

    def agent_schemas(
        self,
        allowed_tools: tuple[str, ...] | set[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Return schemas for enabled Agent Tools only."""
        allowed = None if allowed_tools is None else set(allowed_tools)
        return [
            spec.to_openai_schema()
            for spec in self.tools.values()
            if spec.enabled
            and spec.kind == "agent"
            and (spec.availability is None or spec.availability())
            and (allowed is None or spec.name in allowed)
        ]

    def invoke_system(self, name: str, args: dict[str, Any] | None = None) -> Any:
        """Invoke an enabled System Tool from a trusted runtime gateway."""
        return self.invoke(name, args)

    def invoke(self, name: str, args: dict[str, Any] | None = None) -> Any:
        """Compatibility seam restricted to System Tools only.

        New runtime code must use :meth:`invoke_system`. This method cannot
        invoke Agent Tools and therefore cannot bypass the split gateway.
        """
        spec = self.get_system(name)
        if not spec:
            raise ValueError(f"System Tool '{name}' not found or not allowed.")
        return spec.fn(**(args or {}))

    def invoke_agent(self, name: str, args: dict[str, Any] | None = None) -> Any:
        """Invoke an enabled Agent Tool from the model runtime gateway."""
        spec = self.get_agent(name)
        if not spec:
            raise ValueError(f"Agent Tool '{name}' not found or not allowed.")
        return spec.fn(**(args or {}))


registry = ToolRegistry()
