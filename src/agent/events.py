"""Events support for agent planning, tool execution, and ui event streaming.

Implements the events module responsibilities used by Sonex runtime flows.
Key public entry points include RunnerEvent, UiStatus.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class RunnerEvent:
    """Represents runner event.

    Encapsulates runner event data and behavior used by Sonex runtime flows.
    """
    type: str
    data: dict[str, Any]


@dataclass
class UiStatus:
    """Represents ui status.

    Encapsulates ui status data and behavior used by Sonex runtime flows.
    """
    phase: str
    message: str
    tool_name: str | None = None
    step: int | None = None
    max_steps: int | None = None
