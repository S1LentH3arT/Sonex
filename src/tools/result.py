from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

@dataclass
class ToolResult:
    status: str
    tool: str
    message: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    error_code: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def success(
            cls,
            tool: str,
            message: str = "",
            data: dict[str, Any] | None = None
    ) -> ToolResult:
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
        return cls.fail(tool=tool, message=message, error_code=str(error_code), data=data)

    @classmethod
    def error(
            cls,
            tool: str,
            message: str,
            error_code: str | int,
            data: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        return cls.fail(tool=tool, message=message, error_code=str(error_code), data=data).to_dict()
