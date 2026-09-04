"""Per-WebSocket orchestration state and inbound message routing.

The runner object is shared by all connections.  This module keeps mutable
interaction state and owned tasks connection-scoped without changing the
transport adapter into a state bag.
"""

from __future__ import annotations

import asyncio
import json
import queue
import weakref
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Mapping, Protocol


class ConfirmOwner(Protocol):
    async def handle_choice(self, decision: Any) -> None: ...


class ConfirmRegistry:
    """Routes a confirmation id to the session that created it."""

    def __init__(self) -> None:
        self._owners: dict[str, ConfirmOwner] = {}

    def register(self, confirm_id: str, owner: ConfirmOwner) -> None:
        if confirm_id:
            self._owners[confirm_id] = owner

    def unregister(self, confirm_id: str, owner: ConfirmOwner | None = None) -> None:
        if owner is None or self._owners.get(confirm_id) is owner:
            self._owners.pop(confirm_id, None)

    async def dispatch(self, confirm_id: str, decision: Any) -> bool:
        owner = self._owners.pop(confirm_id, None)
        if owner is None:
            return False
        await owner.handle_choice(decision)
        return True

    def clear(self) -> None:
        self._owners.clear()

    def unregister_owner(self, owner: ConfirmOwner) -> None:
        for confirm_id, registered in tuple(self._owners.items()):
            if registered is owner:
                self._owners.pop(confirm_id, None)


class SessionTaskScope:
    """Owns connection tasks and isolates failures from sibling tasks."""

    def __init__(self) -> None:
        self._tasks: set[asyncio.Task[Any]] = set()

    def create_task(self, coro: Awaitable[Any], *, name: str | None = None) -> asyncio.Task[Any]:
        task = asyncio.create_task(coro, name=name)
        self._tasks.add(task)
        task.add_done_callback(self._discard_task)
        return task

    def adopt(self, task: asyncio.Task[Any]) -> asyncio.Task[Any]:
        self._tasks.add(task)
        task.add_done_callback(self._discard_task)
        return task

    def _discard_task(self, task: asyncio.Task[Any]) -> None:
        self._tasks.discard(task)
        if task.cancelled():
            return
        # Consume failures so one background task cannot become an unhandled
        # exception or cancel the connection's other work.
        try:
            task.exception()
        except BaseException:
            pass

    async def cancel_and_wait(self) -> None:
        tasks = tuple(self._tasks)
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()


@dataclass
class SessionContext:
    """Mutable orchestration state for one WebSocket connection."""

    confirm_registry: ConfirmRegistry = field(default_factory=ConfirmRegistry)
    tasks: SessionTaskScope = field(default_factory=SessionTaskScope)
    running_task: asyncio.Task[Any] | None = None
    confirm_queue: queue.Queue[tuple[str, Any]] = field(default_factory=queue.Queue)
    agent_input_queue: Any = None
    active_agent_turn_id: str | None = None
    agent_turn_interrupt_event: Any = None
    active_agent_provider_task: asyncio.Task[Any] | None = None
    agent_interaction_active: bool = False
    _closed: bool = False
    # Migration store for non-orchestration panel state. It is owned here so
    # new code does not add dynamic attributes to WebSocketUIAdapter.
    values: dict[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        return self.values.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self.values[key] = value

    def discard(self, key: str) -> None:
        self.values.pop(key, None)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self.tasks.cancel_and_wait()
        self.confirm_registry.clear()


_contexts: weakref.WeakKeyDictionary[Any, SessionContext] = weakref.WeakKeyDictionary()
_CONTEXT_FIELDS = {
    "_agent_turn_task": "running_task",
    "_agent_input_queue": "agent_input_queue",
    "_active_agent_turn_id": "active_agent_turn_id",
    "_agent_turn_interrupt_event": "agent_turn_interrupt_event",
    "_active_agent_provider_task": "active_agent_provider_task",
}


def create_session_context(ui: Any) -> SessionContext:
    context = SessionContext()
    _contexts[ui] = context
    return context


def session_context_for(ui: Any) -> SessionContext:
    context = _contexts.get(ui)
    if context is None:
        context = create_session_context(ui)
    return context


def discard_session_context(ui: Any) -> None:
    _contexts.pop(ui, None)


def live_session_contexts() -> tuple[SessionContext, ...]:
    return tuple(_contexts.values())


def session_get(ui: Any, key: str, default: Any = None) -> Any:
    context = session_context_for(ui)
    field_name = _CONTEXT_FIELDS.get(key)
    if field_name:
        value = getattr(context, field_name)
        if value is not None:
            return value
    value = context.get(key, default)
    if value is not default:
        return value
    return getattr(ui, key, default)


def session_set(ui: Any, key: str, value: Any) -> None:
    context = session_context_for(ui)
    previous = context.get(key)
    if value is None and previous is not None:
        context.confirm_registry.unregister_owner(previous)
    field_name = _CONTEXT_FIELDS.get(key)
    if field_name:
        setattr(context, field_name, value)
    else:
        context.set(key, value)
    # Keep lightweight fake UIs used by legacy unit tests working without
    # reintroducing dynamic state on the real WebSocketUIAdapter.
    if ui.__class__.__name__ != "WebSocketUIAdapter":
        setattr(ui, key, value)


def session_discard(ui: Any, key: str) -> None:
    session_set(ui, key, None)
    session_context_for(ui).discard(key)


def register_confirm_owner(ui: Any, confirm_id: str, owner: ConfirmOwner) -> None:
    session_context_for(ui).confirm_registry.register(confirm_id, owner)


ClientHandler = Callable[[dict[str, Any]], Awaitable[bool | None]]


class ClientMessageRouter:
    """Typed dispatch table for decoded client messages.

    Unknown valid message types are intentionally ignored. Handlers return
    ``True`` when the connection loop should stop (currently only ``bye``).
    """

    def __init__(self, handlers: Mapping[str, ClientHandler]) -> None:
        self._handlers = dict(handlers)

    async def dispatch(self, data: Any) -> bool:
        if not isinstance(data, dict):
            return False
        message_type = data.get("type")
        handler = self._handlers.get(message_type)
        if handler is None:
            return False
        return bool(await handler(data))


def decode_client_message(raw: str) -> dict[str, Any]:
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("Client message must be a JSON object")
    return data
