from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket

from src.api.ws_runner import WebSocketRunner
from src.mcp import build_mcp_server

runner = WebSocketRunner()
mcp_server = build_mcp_server(streamable_http_path="/")
mcp_app = mcp_server.streamable_http_app()


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with mcp_server.session_manager.run():
        yield


app = FastAPI(title="Sonex TUI API", lifespan=lifespan)
app.mount("/mcp", mcp_app)


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await runner.handle_ws(ws)
