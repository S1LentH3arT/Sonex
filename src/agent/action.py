"""Action support for agent planning, tool execution, and ui event streaming.

Implements the action module responsibilities used by Sonex runtime flows.
Key public entry points include Action.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ToolAction:
    """One model-requested Agent Tool invocation."""

    tool: str
    args: dict[str, Any] = field(default_factory=dict)
    call_id: str | None = None


# llm每轮执行动作
@dataclass
class Action:
    """Represents action.

    Encapsulates action data and behavior used by Sonex runtime flows.
    """
    tool: str | None = None # 请求工具名
    args: dict[str, Any] = field(default_factory=dict) # 请求工具参数
    output: str | None = None # 模型文本输出
    usage: int = None # token总数
    tool_calls: list[ToolAction] = field(default_factory=list)

    def calls(self) -> list[ToolAction]:
        """Return the full ordered tool batch while preserving legacy callers."""
        if self.tool_calls:
            return list(self.tool_calls)
        if self.tool is None:
            return []
        return [ToolAction(tool=self.tool, args=self.args)]
