"""Loopback-only MusicKit companion with correlated command/state semantics."""

from __future__ import annotations

import asyncio
import importlib.resources
import json
import secrets
import socket
import subprocess
import sys
import time
import webbrowser
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any, Callable

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

from src.apple_mode.token_provider import DeveloperTokenLease

APPLE_COMPANION_CONNECT_TIMEOUT_SECONDS = 10
APPLE_COMPANION_COMMAND_TIMEOUT_SECONDS = 8
APPLE_COMPANION_AUTH_TIMEOUT_SECONDS = 180


class AppleCompanionError(RuntimeError):
    code = "APPLE_COMPANION_ERROR"


class AppleCompanionNotConnected(AppleCompanionError):
    code = "APPLE_COMPANION_DISCONNECTED"


class AppleCompanionTimeout(AppleCompanionError):
    code = "APPLE_COMPANION_TIMEOUT"


class AppleCompanionUnauthorized(AppleCompanionError):
    code = "APPLE_COMPANION_UNAUTHORIZED"


class AppleSubscriptionRequired(AppleCompanionError):
    code = "APPLE_SUBSCRIPTION_REQUIRED"


@dataclass(slots=True)
class AppleCompanionSnapshot:
    connected: bool = False
    authorized: bool = False
    can_play: bool = False
    storefront: str = ""
    connection_status: str = "stopped"
    player: dict[str, Any] = field(default_factory=dict)
    queue: list[dict[str, Any]] = field(default_factory=list)
    updated_at: int = 0

    @classmethod
    def from_message(cls, message: dict[str, Any], *, connected: bool = True) -> "AppleCompanionSnapshot":
        player = message.get("player") if isinstance(message.get("player"), dict) else {}
        queue = [dict(item) for item in message.get("queue") or [] if isinstance(item, dict)]
        return cls(
            connected=connected,
            authorized=bool(message.get("authorized")),
            can_play=bool(message.get("can_play")),
            storefront=str(message.get("storefront") or "").strip().lower(),
            connection_status="ready" if connected else "disconnected",
            player=dict(player),
            queue=queue,
            updated_at=int(message.get("timestamp") or time.time() * 1000),
        )


StatePredicate = Callable[[AppleCompanionSnapshot], bool]


class MusicKitCompanion:
    """Owns one loopback server and one authenticated MusicKit browser client."""

    def __init__(self) -> None:
        self.host = "127.0.0.1"
        self.port = 0
        self._secret = secrets.token_urlsafe(32)
        self._lease: DeveloperTokenLease | None = None
        self._snapshot = AppleCompanionSnapshot()
        self._server: uvicorn.Server | None = None
        self._server_task: asyncio.Task[None] | None = None
        self._socket: socket.socket | None = None
        self._websocket: WebSocket | None = None
        self._connected_event = asyncio.Event()
        self._state_event = asyncio.Event()
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._send_lock = asyncio.Lock()
        self._disconnected_at: float | None = None
        self._app = self._create_app()

    @property
    def snapshot(self) -> AppleCompanionSnapshot:
        return self._snapshot

    @property
    def launch_url(self) -> str:
        if not self.port:
            raise AppleCompanionError("Apple companion is not running.")
        return f"http://{self.host}:{self.port}/#session={self._secret}"

    @property
    def disconnected_seconds(self) -> float:
        if self._disconnected_at is None:
            return 0.0
        return max(0.0, time.monotonic() - self._disconnected_at)

    async def start(self, lease: DeveloperTokenLease) -> str:
        if self._server_task and not self._server_task.done():
            await self.update_developer_token(lease)
            return self.launch_url
        self._lease = lease
        self._secret = secrets.token_urlsafe(32)
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket.bind((self.host, 0))
        self._socket.listen(128)
        self._socket.setblocking(False)
        self.port = int(self._socket.getsockname()[1])
        config = uvicorn.Config(
            self._app,
            host=self.host,
            port=self.port,
            log_level="warning",
            access_log=False,
        )
        self._server = uvicorn.Server(config)
        self._server_task = asyncio.create_task(self._server.serve(sockets=[self._socket]))
        deadline = time.monotonic() + APPLE_COMPANION_CONNECT_TIMEOUT_SECONDS
        while not self._server.started:
            if self._server_task.done():
                raise AppleCompanionError("Apple companion failed to start.")
            if time.monotonic() >= deadline:
                raise AppleCompanionTimeout("Apple companion startup timed out.")
            await asyncio.sleep(0.02)
        self._snapshot.connection_status = "waiting_for_browser"
        return self.launch_url

    async def open_browser(self) -> bool:
        url = self.launch_url
        if _is_wsl():
            try:
                process = await asyncio.create_subprocess_exec(
                    "cmd.exe",
                    "/c",
                    "start",
                    "",
                    url,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return await process.wait() == 0
            except OSError:
                return False
        try:
            return bool(await asyncio.to_thread(webbrowser.open, url, 2))
        except Exception:
            return False

    async def wait_until_ready(self, timeout_seconds: float = APPLE_COMPANION_AUTH_TIMEOUT_SECONDS) -> AppleCompanionSnapshot:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            snapshot = self._snapshot
            if snapshot.connected and snapshot.authorized:
                if not snapshot.can_play:
                    raise AppleSubscriptionRequired("Apple Music subscription playback is unavailable.")
                if not snapshot.storefront:
                    raise AppleCompanionError("Apple Music did not return an authoritative storefront.")
                return snapshot
            remaining = max(0.01, deadline - time.monotonic())
            self._state_event.clear()
            try:
                await asyncio.wait_for(self._state_event.wait(), timeout=remaining)
            except TimeoutError as exc:
                raise AppleCompanionTimeout("Apple Music authorization timed out.") from exc
        raise AppleCompanionTimeout("Apple Music authorization timed out.")

    async def search(self, query: str, *, limit: int = 10) -> list[dict[str, Any]]:
        result = await self.command("search", {"query": query, "limit": max(1, min(25, limit))})
        return [dict(item) for item in result.get("tracks") or [] if isinstance(item, dict)]

    async def play(self, track: dict[str, Any]) -> AppleCompanionSnapshot:
        track_id = str(track.get("id") or "").strip()
        if not track_id:
            raise AppleCompanionError("Apple catalog track ID is missing.")
        await self.command(
            "play",
            {"track": _safe_track(track)},
            predicate=lambda state: (
                str(state.player.get("id") or "") == track_id
                and bool(state.player.get("is_playing"))
            ),
        )
        return self._snapshot

    async def queue_add(self, track: dict[str, Any]) -> AppleCompanionSnapshot:
        track_id = str(track.get("id") or "").strip()
        if not track_id:
            raise AppleCompanionError("Apple catalog track ID is missing.")
        await self.command(
            "queue_add",
            {"track": _safe_track(track)},
            predicate=lambda state: any(str(item.get("id") or "") == track_id for item in state.queue),
        )
        return self._snapshot

    async def control(self, action: str) -> AppleCompanionSnapshot:
        if action not in {"pause", "resume", "next", "previous"}:
            raise AppleCompanionError(f"Unsupported Apple playback action: {action}.")
        before_id = str(self._snapshot.player.get("id") or "")
        if action == "pause":
            predicate = lambda state: not bool(state.player.get("is_playing"))
        elif action == "resume":
            predicate = lambda state: bool(state.player.get("is_playing"))
        else:
            predicate = lambda state: bool(state.player.get("id")) and str(state.player.get("id")) != before_id
        await self.command(action, {}, predicate=predicate)
        return self._snapshot

    async def deactivate(self) -> None:
        if self._snapshot.connected:
            with suppress(AppleCompanionError):
                await self.control("pause")

    async def update_developer_token(self, lease: DeveloperTokenLease) -> None:
        """Refresh the browser's memory-only developer token when it changes."""
        previous = self._lease
        self._lease = lease
        if (
            previous is not None
            and previous.token == lease.token
            and previous.expires_at == lease.expires_at
        ):
            return
        websocket = self._websocket
        if websocket is None or not self._snapshot.connected:
            return
        async with self._send_lock:
            await websocket.send_json(
                {
                    "type": "configure",
                    "developer_token": lease.token,
                    "expires_at": lease.expires_at,
                }
            )

    async def clear_queue(self) -> None:
        if self._snapshot.connected:
            await self.command(
                "clear_queue",
                {},
                predicate=lambda state: not state.queue,
            )

    async def logout(self) -> None:
        if self._snapshot.connected:
            with suppress(AppleCompanionError):
                await self.command("logout", {})
        await self.stop()

    async def stop(self) -> None:
        websocket = self._websocket
        if websocket is not None:
            with suppress(Exception):
                await websocket.close(code=1000)
        self._websocket = None
        if self._server is not None:
            self._server.should_exit = True
        if self._server_task is not None:
            with suppress(asyncio.CancelledError, TimeoutError):
                await asyncio.wait_for(self._server_task, timeout=3)
        if self._socket is not None:
            with suppress(OSError):
                self._socket.close()
        self._server = None
        self._server_task = None
        self._socket = None
        self.port = 0
        self._lease = None
        self._snapshot = AppleCompanionSnapshot()
        self._connected_event.clear()
        self._state_event.set()

    async def command(
        self,
        action: str,
        payload: dict[str, Any],
        *,
        predicate: StatePredicate | None = None,
        timeout_seconds: float = APPLE_COMPANION_COMMAND_TIMEOUT_SECONDS,
    ) -> dict[str, Any]:
        websocket = self._websocket
        if websocket is None or not self._snapshot.connected:
            raise AppleCompanionNotConnected("Apple Music companion is not connected.")
        command_id = secrets.token_hex(12)
        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._pending[command_id] = future
        try:
            async with self._send_lock:
                await websocket.send_json(
                    {"type": "command", "id": command_id, "action": action, "payload": payload}
                )
            result = await asyncio.wait_for(future, timeout=timeout_seconds)
            if not bool(result.get("ok")):
                error = str(result.get("error") or f"Apple {action} failed.")
                try:
                    error_status = int(result.get("error_status") or 0)
                except (TypeError, ValueError):
                    error_status = 0
                if error_status == 401:
                    raise AppleCompanionUnauthorized(error)
                raise AppleCompanionError(error)
            if predicate is not None:
                await self._wait_for_state(predicate, timeout_seconds)
            return result.get("data") if isinstance(result.get("data"), dict) else {}
        except TimeoutError as exc:
            raise AppleCompanionTimeout(f"Apple {action} timed out.") from exc
        finally:
            self._pending.pop(command_id, None)

    async def _wait_for_state(self, predicate: StatePredicate, timeout_seconds: float) -> None:
        deadline = time.monotonic() + timeout_seconds
        while not predicate(self._snapshot):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise AppleCompanionTimeout("Apple Music did not publish the expected playback state.")
            self._state_event.clear()
            await asyncio.wait_for(self._state_event.wait(), timeout=remaining)

    def _create_app(self) -> FastAPI:
        app = FastAPI(title="Sonex Apple Music Companion", docs_url=None, redoc_url=None)

        @app.get("/", response_class=HTMLResponse)
        async def index() -> HTMLResponse:
            html = importlib.resources.files("src.apple_mode").joinpath("companion.html").read_text(encoding="utf-8")
            return HTMLResponse(
                html,
                headers={
                    "Cache-Control": "no-store",
                    "Content-Security-Policy": (
                        "default-src 'self' https://js-cdn.music.apple.com; "
                        "script-src 'self' 'unsafe-inline' https://js-cdn.music.apple.com; "
                        "connect-src 'self' ws://127.0.0.1:* https:; "
                        "media-src blob: https:; img-src 'self' data: https:; "
                        "style-src 'self' 'unsafe-inline';"
                    ),
                    "Referrer-Policy": "no-referrer",
                    "X-Content-Type-Options": "nosniff",
                },
            )

        @app.websocket("/ws")
        async def websocket_endpoint(websocket: WebSocket) -> None:
            expected_origin = f"http://{self.host}:{self.port}"
            if websocket.headers.get("origin") != expected_origin or self._websocket is not None:
                await websocket.close(code=1008)
                return
            await websocket.accept()
            try:
                hello = await asyncio.wait_for(websocket.receive_json(), timeout=5)
                if (
                    not isinstance(hello, dict)
                    or hello.get("type") != "hello"
                    or not secrets.compare_digest(str(hello.get("secret") or ""), self._secret)
                ):
                    await websocket.close(code=1008)
                    return
                lease = self._lease
                if lease is None or not lease.usable():
                    await websocket.send_json({"type": "fatal", "code": "APPLE_DEVELOPER_TOKEN_EXPIRED"})
                    await websocket.close(code=1011)
                    return
                self._websocket = websocket
                self._snapshot.connected = True
                self._snapshot.connection_status = "connected"
                self._disconnected_at = None
                self._connected_event.set()
                self._state_event.set()
                await websocket.send_json(
                    {
                        "type": "configure",
                        "developer_token": lease.token,
                        "expires_at": lease.expires_at,
                    }
                )
                while True:
                    message = await websocket.receive_json()
                    await self._handle_browser_message(message)
            except (WebSocketDisconnect, TimeoutError, json.JSONDecodeError):
                pass
            finally:
                if self._websocket is websocket:
                    self._websocket = None
                    self._snapshot.connected = False
                    self._snapshot.connection_status = "disconnected"
                    self._disconnected_at = time.monotonic()
                    self._connected_event.clear()
                    self._state_event.set()
                    for future in self._pending.values():
                        if not future.done():
                            future.set_exception(AppleCompanionNotConnected("Apple Music companion disconnected."))

        return app

    async def _handle_browser_message(self, message: Any) -> None:
        if not isinstance(message, dict):
            return
        message_type = message.get("type")
        if message_type == "state":
            self._snapshot = AppleCompanionSnapshot.from_message(message)
            self._state_event.set()
            return
        if message_type == "command_result":
            command_id = str(message.get("id") or "")
            future = self._pending.get(command_id)
            if future is not None and not future.done():
                future.set_result(message)


def _safe_track(track: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "id",
        "uri",
        "name",
        "title",
        "artist",
        "album",
        "duration_ms",
        "album_cover_url",
        "url",
        "apple_music_url",
    }
    return {key: track.get(key) for key in allowed if track.get(key) is not None}


def _is_wsl() -> bool:
    if sys.platform != "linux":
        return False
    try:
        return "microsoft" in open("/proc/version", encoding="utf-8").read().casefold()
    except OSError:
        return False
