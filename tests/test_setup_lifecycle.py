"""Tests for provider setup lifecycle primitives."""

from __future__ import annotations

import asyncio
from unittest.mock import Mock

from src.auth.setup_lifecycle import CompletionOnce, cancel_setup_resources, parse_setup_input, setup_result


def test_parse_setup_input_normalizes_and_classifies_cancel() -> None:
    assert parse_setup_input("  API_KEY  ").value == "API_KEY"
    assert parse_setup_input("cancel").cancelled
    assert parse_setup_input("__CANCEL__").cancelled
    assert not parse_setup_input("oauth").cancelled


def test_completion_once_settles_callback_once() -> None:
    results: list[dict[str, str]] = []

    async def callback(result: dict[str, str]) -> None:
        results.append(result)

    completion = CompletionOnce(callback)

    async def run() -> None:
        await completion.notify({"status": "connected"})
        await completion.notify({"status": "cancelled"})

    asyncio.run(run())

    assert results == [{"status": "connected"}]


def test_setup_result_keeps_terminal_event_shape_compact() -> None:
    assert setup_result("connected", "jamendo", account_label="application") == {
        "status": "connected",
        "provider": "jamendo",
        "account_label": "application",
    }
    assert setup_result("cancelled", "spotify", reason="user_cancelled") == {
        "status": "cancelled",
        "provider": "spotify",
        "reason": "user_cancelled",
    }


def test_cancel_setup_resources_cancels_task_and_closes_resource() -> None:
    class Resource:
        def __init__(self) -> None:
            self.close = Mock()

    async def run() -> tuple[asyncio.Task[None], Resource]:
        async def pending() -> None:
            await asyncio.sleep(60)

        task = asyncio.create_task(pending())
        resource = Resource()
        await cancel_setup_resources(task=task, resource=resource)
        await asyncio.gather(task, return_exceptions=True)
        return task, resource

    task, resource = asyncio.run(run())

    assert task.cancelled()
    resource.close.assert_called_once_with()
