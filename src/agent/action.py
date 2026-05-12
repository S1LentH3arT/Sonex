from dataclasses import dataclass, field
from typing import Any

# llm每轮执行动作
@dataclass
class Action:
    tool: str | None = None # 请求工具名
    args: dict[str, Any] = field(default_factory=dict) # 请求工具参数
    output: str | None = None # 模型文本输出
    usage: int = None # token总数
