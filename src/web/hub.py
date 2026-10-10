"""Keep the Agent Runtime alive while browser tabs connect and disconnect."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect


class BrowserHub:
    def __init__(self) -> None:
        self.clients: dict[WebSocket, asyncio.Lock] = {}
        self.incoming: asyncio.Queue[str | None] = asyncio.Queue()
        self.ready = asyncio.Event()
        self.ui: Any = None

    async def accept(self) -> None:
        pass

    async def receive_text(self) -> str:
        message = await self.incoming.get()
        if message is None:
            raise WebSocketDisconnect(code=1001)
        return message

    async def send_text(self, text: str) -> None:
        try:
            if json.loads(text).get("type") == "web_snapshot":
                self.ready.set()
        except (AttributeError, json.JSONDecodeError):
            pass
        await asyncio.gather(
            *(self._send(client, lock, text) for client, lock in tuple(self.clients.items()))
        )

    async def _send(self, client: WebSocket, lock: asyncio.Lock, text: str) -> None:
        try:
            async with lock:
                await client.send_text(text)
        except (RuntimeError, WebSocketDisconnect, OSError):
            self.clients.pop(client, None)

    async def attach(self, client: WebSocket) -> None:
        await client.accept()
        self.clients[client] = asyncio.Lock()
        await self.ready.wait()
        if self.ui is not None:
            await self.ui.snapshot()

    async def detach(self, client: WebSocket) -> None:
        self.clients.pop(client, None)

    async def receive_from(self, client: WebSocket) -> None:
        while True:
            await self.incoming.put(await client.receive_text())

    async def close(self) -> None:
        self.incoming.put_nowait(None)
        clients = tuple(self.clients)
        self.clients.clear()
        await asyncio.gather(
            *(client.close(code=1001) for client in clients), return_exceptions=True
        )
