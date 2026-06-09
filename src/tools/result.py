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
        """To dict for tool result.

        Coordinates the to dict method behavior while preserving tool result state and contracts.

        Returns:
            The computed result for to dict.
        """
        return asdict(self)

    @classmethod
    def success(
            cls,
            tool: str,
            message: str = "",
            data: dict[str, Any] | None = None
    ) -> ToolResult:
        """Success for tool result.

        Coordinates the success method behavior while preserving tool result state and contracts.

        Args:
            tool: Input value used by the success operation.
            message: Input value used by the success operation.
            data: Input value used by the success operation.

        Returns:
            The computed result for success.
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
        """Fail for tool result.

        Coordinates the fail method behavior while preserving tool result state and contracts.

        Args:
            tool: Input value used by the fail operation.
            message: Input value used by the fail operation.
            error_code: Input value used by the fail operation.
            data: Input value used by the fail operation.

        Returns:
            The computed result for fail.
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
        """Failure for tool result.

        Coordinates the failure method behavior while preserving tool result state and contracts.

        Args:
            tool: Input value used by the failure operation.
            message: Input value used by the failure operation.
            error_code: Input value used by the failure operation.
            data: Input value used by the failure operation.

        Returns:
            The computed result for failure.
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
        """Error for tool result.

        Coordinates the error method behavior while preserving tool result state and contracts.

        Args:
            tool: Input value used by the error operation.
            message: Input value used by the error operation.
            error_code: Input value used by the error operation.
            data: Input value used by the error operation.

        Returns:
            The computed result for error.
        """
        return cls.fail(tool=tool, message=message, error_code=str(error_code), data=data).to_dict()
