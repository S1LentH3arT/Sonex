from dataclasses import dataclass
from typing import Any, Callable

from src.agent.memory import MemoryStore

_MEMORY_STORE = MemoryStore()
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

# 工具仓库
class ToolRegistry:
    tools: dict[str, ToolSpec]
    def __init__(self) -> None:
        self.tools = {}

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self.tools:
            raise ValueError(f"Tool '{spec.name}' already registered.")
        self.tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec | None:
        spec = self.tools.get(name)
        if not spec or not spec.enabled or not spec.read_only:
            return None
        return spec

    # 返回OpenAI格式的工具列表给LLM
    def schemas(self) -> list[dict[str, Any]]:
        return [spec.to_openai_schema() for spec in self.tools.values() if spec.enabled and not spec.read_only]

    def invoke(self, name: str, args: dict[str, Any] | None = None) -> Any:
        spec = self.get(name)
        if not spec:
            raise ValueError(f"Tool '{name}' not found or not allowed.")
        return spec.fn(**(args or {}))

registry = ToolRegistry()