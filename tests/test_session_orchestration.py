"""Behavior checks for connection-scoped WebSocket orchestration."""

from __future__ import annotations

import asyncio
import unittest

from src.ws.session_orchestration import (
    ClientMessageRouter,
    ConfirmRegistry,
    SessionTaskScope,
    create_session_context,
    decode_client_message,
    discard_session_context,
    session_context_for,
)


class _Owner:
    def __init__(self) -> None:
        self.decisions: list[object] = []

    async def handle_choice(self, decision: object) -> None:
        self.decisions.append(decision)


class _SessionKey:
    pass


class SessionOrchestrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_confirm_registry_dispatches_once_and_unknown_falls_through(self) -> None:
        registry = ConfirmRegistry()
        owner = _Owner()
        registry.register("confirm-1", owner)

        self.assertTrue(await registry.dispatch("confirm-1", "allow_once"))
        self.assertFalse(await registry.dispatch("confirm-1", "deny"))
        self.assertEqual(owner.decisions, ["allow_once"])

    async def test_task_scope_isolates_failure_and_cancels_siblings(self) -> None:
        scope = SessionTaskScope()
        failed = scope.create_task(self._fail())
        sibling = scope.create_task(asyncio.sleep(60))
        await asyncio.sleep(0)
        self.assertTrue(failed.done())
        self.assertFalse(sibling.done())
        await scope.cancel_and_wait()
        self.assertTrue(sibling.cancelled())

    async def test_contexts_are_isolated(self) -> None:
        first = _SessionKey()
        second = _SessionKey()
        first_context = create_session_context(first)
        second_context = create_session_context(second)
        first_context.active_agent_turn_id = "turn-1"
        self.assertEqual(session_context_for(first).active_agent_turn_id, "turn-1")
        self.assertIsNone(session_context_for(second).active_agent_turn_id)
        discard_session_context(first)
        discard_session_context(second)

    async def test_router_ignores_unknown_and_stops_on_bye(self) -> None:
        seen: list[str] = []

        async def handle(data: dict[str, object]) -> None:
            seen.append(str(data["type"]))

        async def bye(_data: dict[str, object]) -> bool:
            seen.append("bye")
            return True

        router = ClientMessageRouter({"known": handle, "bye": bye})
        self.assertFalse(await router.dispatch({"type": "unknown"}))
        self.assertFalse(await router.dispatch({"type": "known"}))
        self.assertTrue(await router.dispatch({"type": "bye"}))
        self.assertEqual(seen, ["known", "bye"])

    async def test_decode_requires_json_object(self) -> None:
        self.assertEqual(decode_client_message('{"type":"known"}')["type"], "known")
        with self.assertRaises(ValueError):
            decode_client_message("[]")

    async def _fail(self) -> None:
        raise RuntimeError("isolated")
