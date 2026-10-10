"""Local browser UI backed by Sonex's persistent Agent and player runtime."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles

from src.log import configure_file_logging
from src.tools.playback_controller import controller
from src.web.hub import BrowserHub
from src.web.runtime.runner import WebRunner

FRONTEND = Path(__file__).resolve().parent / "static"


class HubRunner(WebRunner):
    def _create_ui(self, connection: BrowserHub):
        ui = super()._create_ui(connection)
        connection.ui = ui
        return ui


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_file_logging()
    hub = BrowserHub()
    runner = HubRunner()
    app.state.hub = hub
    task = asyncio.create_task(runner.handle_ws(hub), name="sonex-web-runtime")
    app.state.runtime_task = task
    try:
        await asyncio.wait_for(hub.ready.wait(), timeout=30)
        yield
    finally:
        await hub.close()
        with suppress(asyncio.CancelledError):
            await task
        if controller.current_session_id:
            with suppress(OSError, RuntimeError):
                await asyncio.to_thread(controller.stop)


app = FastAPI(title="Sonex", lifespan=lifespan)


def _same_local_origin(websocket: WebSocket) -> bool:
    origin = websocket.headers.get("origin")
    host = websocket.headers.get("host", "").lower()
    if not origin or not host:
        return False
    parsed = urlsplit(origin)
    return (
        parsed.scheme == "http"
        and parsed.netloc.lower() == host
        and parsed.hostname in {"127.0.0.1", "localhost"}
    )


@app.websocket("/web/ws")
async def web_socket(websocket: WebSocket) -> None:
    if not _same_local_origin(websocket):
        await websocket.close(code=1008)
        return
    hub: BrowserHub = websocket.app.state.hub
    await hub.attach(websocket)
    try:
        await hub.receive_from(websocket)
    except WebSocketDisconnect:
        pass
    finally:
        await hub.detach(websocket)


@app.get("/")
async def index() -> Response:
    index_file = FRONTEND / "index.html"
    if not index_file.is_file():
        return PlainTextResponse(
            "Sonex web assets are missing. Build them with npm --prefix src/web/frontend run build.",
            status_code=503,
        )
    return FileResponse(index_file)


if FRONTEND.is_dir():
    app.mount("/assets", StaticFiles(directory=FRONTEND / "assets"), name="assets")
