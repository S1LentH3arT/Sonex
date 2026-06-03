from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Callable


ToolFn = Callable[..., Any]


@dataclass(frozen=True)
class Params:
    type: str
    properties: dict[str, Any]
    required: list[str]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    type: str
    description: str
    parameters: Params
    fn: ToolFn
    enabled: bool = True
    read_only: bool = True
    confirm_required: bool = True

    def to_openai_schema(self) -> dict[str, Any]:
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
    def __init__(self) -> None:
        self.tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec | None = None, **kwargs: Any) -> None:
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
        spec = self.tools.get(name)
        if not spec or not spec.enabled:
            return None
        return spec

    def schemas(self, allowed_tools: tuple[str, ...] | set[str] | None = None) -> list[dict[str, Any]]:
        allowed = set(allowed_tools or ())
        return [
            spec.to_openai_schema()
            for spec in self.tools.values()
            if spec.enabled and (not allowed or spec.name in allowed)
        ]

    def invoke(self, name: str, args: dict[str, Any] | None = None) -> Any:
        spec = self.get(name)
        if not spec:
            raise ValueError(f"Tool '{name}' not found or not allowed.")
        return spec.fn(**(args or {}))


registry = ToolRegistry()
