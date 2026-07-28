"""App support for fastapi and websocket routing for the sonex runtime.

Implements the app module responsibilities used by Sonex runtime flows.
Key public entry points include lifespan, websocket_endpoint.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket

from src.api.ws_runner import WebSocketRunner
from src.log import configure_file_logging

runner = WebSocketRunner()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Configure runtime resources for the FastAPI process lifetime."""
    configure_file_logging()
    yield


app = FastAPI(title="Sonex TUI API", lifespan=lifespan)


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    """Coordinates websocket endpoint for the current Sonex flow.

    Typical use: Use this function when runtime code needs websocket endpoint as part of a Sonex command, playback, auth, llm, or ui path.

    Example: await websocket_endpoint(ws=...) -> returns the value used by the surrounding Sonex flow.
    """
    await runner.handle_ws(ws)
