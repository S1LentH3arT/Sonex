from __future__ import annotations

from fastapi import FastAPI, WebSocket

from src.api.ws_runner import WebSocketRunner

app = FastAPI(title="Sonex TUI API")
runner = WebSocketRunner()


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await runner.handle_ws(ws)
