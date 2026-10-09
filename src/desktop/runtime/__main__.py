"""Line-delimited JSON transport owned by the desktop host, without a TCP port."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import TextIO

from fastapi import WebSocketDisconnect


class StdioConnection:
    def __init__(self, reader: TextIO, writer: TextIO) -> None:
        self.reader, self.writer = reader, writer

    async def accept(self) -> None:
        pass

    async def receive_text(self) -> str:
        line = await asyncio.to_thread(self.reader.readline, 131073)
        if not line:
            raise WebSocketDisconnect()
        if len(line) > 131072 or not line.endswith("\n"):
            raise ValueError("Desktop message exceeds the transport limit.")
        return line

    async def send_text(self, text: str) -> None:
        self.writer.write(text + "\n")
        self.writer.flush()

    async def close(self) -> None:
        pass


async def run(connection: StdioConnection) -> None:
    from src.desktop.runtime.runner import DesktopRunner
    from src.log import configure_file_logging
    from src.network.proxy import configure_startup_proxy
    from src.tools.playback_controller import controller
    from src.workspace import user_workspace_root

    os.chdir(user_workspace_root())
    configure_file_logging()
    configure_startup_proxy()
    try:
        await DesktopRunner().handle_ws(connection)
    finally:
        if controller.current_session_id:
            try:
                await asyncio.to_thread(controller.stop)
            except (OSError, RuntimeError):
                pass


def main() -> None:
    reader, writer = sys.stdin, sys.stdout
    if hasattr(reader, "reconfigure"):
        reader.reconfigure(encoding="utf-8")
        writer.reconfigure(encoding="utf-8", line_buffering=True)
    # Third-party diagnostic prints must never enter the JSON protocol stream.
    sys.stdout = sys.stderr
    try:
        asyncio.run(run(StdioConnection(reader, writer)))
    except Exception as exc:
        writer.write(json.dumps({"type": "error", "message": f"Runtime stopped: {exc}"}) + "\n")
        writer.flush()
        raise


if __name__ == "__main__":
    main()
