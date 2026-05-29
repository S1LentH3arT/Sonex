from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class RunnerEvent:
    type: str
    data: dict[str, Any]


@dataclass
class UiStatus:
    phase: str
    message: str
    tool_name: str | None = None
    step: int | None = None
    max_steps: int | None = None
