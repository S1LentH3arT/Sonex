"""App support for fastapi and websocket routing for the sonex runtime.
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
    await runner.handle_ws(ws)
