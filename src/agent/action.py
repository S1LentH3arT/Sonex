from dataclasses import dataclass, field
from typing import Any


@dataclass
class Action:
    tool: str | None = None
    args: dict[str, Any] = field(default_factory=dict)
    final_answer: str | None = None
    done: bool = False
