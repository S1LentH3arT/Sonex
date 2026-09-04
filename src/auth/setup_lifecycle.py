"""Pure lifecycle helpers shared by provider setup sessions."""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class SetupInput:
    """Normalized setup input and its terminal classification."""

    value: str
    cancelled: bool


def parse_setup_input(raw: str) -> SetupInput:
    value = str(raw).strip()
    return SetupInput(value=value, cancelled=value.casefold() in {"__cancel__", "cancel"})


def setup_result(
    status: str,
    provider: str,
    *,
    account_label: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    """Build the stable completion event shared by setup sessions."""
    result: dict[str, Any] = {"status": status, "provider": provider}
    if account_label is not None:
        result["account_label"] = account_label
    if reason is not None:
        result["reason"] = reason
    return result


async def cancel_setup_resources(
    *,
    task: asyncio.Task[Any] | None = None,
    resource: Any | None = None,
) -> None:
    """Cancel a pending setup task and close its optional external resource."""
    if task is not None and not task.done():
        task.cancel()
    close = getattr(resource, "close", None)
    if close is None:
        return
    value = close()
    if inspect.isawaitable(value):
        await value


class CompletionOnce:
    """Settle a setup completion callback at most once."""

    def __init__(self, callback: Callable[[dict[str, Any]], Any] | None = None) -> None:
        self._callback = callback

    async def notify(self, result: dict[str, Any]) -> None:
        callback = self._callback
        self._callback = None
        if callback is None:
            return
        value = callback(result)
        if inspect.isawaitable(value):
            await value
