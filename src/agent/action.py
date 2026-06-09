"""Action support for agent planning, tool execution, and ui event streaming.

Implements the action module responsibilities used by Sonex runtime flows.
Key public entry points include Action.
"""

from dataclasses import dataclass, field
from typing import Any

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
