"""App support for fastapi and websocket routing for the sonex runtime.

Implements the app module responsibilities used by Sonex runtime flows.
Key public entry points include lifespan, websocket_endpoint.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket

from src.api.ws_runner import WebSocketRunner
from src.log import configure_file_logging
from src.mcp import build_mcp_server

runner = WebSocketRunner()
mcp_server = build_mcp_server(streamable_http_path="/")
mcp_app = mcp_server.streamable_http_app()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Coordinates lifespan for the current Sonex flow.

    Typical use: Use this function when runtime code needs lifespan as part of a Sonex command, playback, auth, llm, or ui path.

    Example: await lifespan(app=...) -> returns the value used by the surrounding Sonex flow.
    """
    configure_file_logging()
    async with mcp_server.session_manager.run():
        yield


app = FastAPI(title="Sonex TUI API", lifespan=lifespan)
app.mount("/mcp", mcp_app)


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    """Coordinates websocket endpoint for the current Sonex flow.

    Typical use: Use this function when runtime code needs websocket endpoint as part of a Sonex command, playback, auth, llm, or ui path.

    Example: await websocket_endpoint(ws=...) -> returns the value used by the surrounding Sonex flow.
    """
    await runner.handle_ws(ws)
