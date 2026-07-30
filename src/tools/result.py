"""Result support for tool implementations used by the planner and playback flows.

Implements the result module responsibilities used by Sonex runtime flows.
Key public entry points include ToolResult.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

@dataclass
class ToolResult:
    """Represents tool result.

    Encapsulates tool result data and behavior used by Sonex runtime flows.
    """
    status: str
    tool: str
    message: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    error_code: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Coordinates to dict for the current Sonex flow.

        Typical use: Use this function when runtime code needs to dict as part of a Sonex command, playback, auth, llm, or ui path.

        Example: to_dict() -> returns the value used by the surrounding Sonex flow.
        """
        return asdict(self)

    @classmethod
    def success(
            cls,
            tool: str,
            message: str = "",
            data: dict[str, Any] | None = None
    ) -> ToolResult:
        """Coordinates success for the current Sonex flow.

        Typical use: Use this function when runtime code needs success as part of a Sonex command, playback, auth, llm, or ui path.

        Example: success(tool=..., message=..., data=...) -> returns the value used by the surrounding Sonex flow.
        """
        return cls(
            status="success",
            tool=tool,
            message=message,
            data=data or {},
            error_code=None,
        )

    @classmethod
    def fail(
            cls,
            tool: str,
            message: str,
            error_code: str,
            data: dict[str, Any] | None = None
    ) -> ToolResult:
        """Coordinates fail for the current Sonex flow.

        Typical use: Use this function when runtime code needs fail as part of a Sonex command, playback, auth, llm, or ui path.

        Example: fail(tool=..., message=..., error_code=..., data=...) -> returns the value used by the surrounding Sonex flow.
        """
        return cls(
            status="fail",
            tool=tool,
            message=message,
            error_code=error_code,
            data=data or {},
        )

    @classmethod
    def failure(
            cls,
            tool: str,
            message: str,
            error_code: str | int,
            data: dict[str, Any] | None = None
    ) -> ToolResult:
        """Coordinates failure for the current Sonex flow.

        Typical use: Use this function when runtime code needs failure as part of a Sonex command, playback, auth, llm, or ui path.

        Example: failure(tool=..., message=..., error_code=..., data=...) -> returns the value used by the surrounding Sonex flow.
        """
        return cls.fail(tool=tool, message=message, error_code=str(error_code), data=data)

    @classmethod
    def error(
            cls,
            tool: str,
            message: str,
            error_code: str | int,
            data: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Coordinates error for the current Sonex flow.

        Typical use: Use this function when runtime code needs error as part of a Sonex command, playback, auth, llm, or ui path.

        Example: error(tool=..., message=..., error_code=..., data=...) -> returns the value used by the surrounding Sonex flow.
        """
        return cls.fail(tool=tool, message=message, error_code=str(error_code), data=data).to_dict()
