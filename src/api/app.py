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
    """Asynchronously lifespan.

    Coordinates non-blocking lifespan work for the surrounding Sonex flow.

    Args:
        app: Input value used by the lifespan operation.
    """
    configure_file_logging()
    async with mcp_server.session_manager.run():
        yield


app = FastAPI(title="Sonex TUI API", lifespan=lifespan)
app.mount("/mcp", mcp_app)


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    """Asynchronously websocket endpoint.

    Coordinates non-blocking websocket endpoint work for the surrounding Sonex flow.

    Args:
        ws: Input value used by the websocket endpoint operation.

    Returns:
        The computed result for websocket endpoint.
    """
    await runner.handle_ws(ws)
