from __future__ import annotations

import json
import os
import socket
import subprocess
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Literal

from src.tools.registry import Params, registry
from src.tools.result import ToolResult

PlayerName = Literal["mpv", "vlc"]
PlaybackSource = Literal["local", "youtube", "spotify", "apple_music"]


def _timestamp_ms() -> int:
    return int(time.time() * 1000)


@dataclass(frozen=True)
class PlayerState:
    provider: str
    source: PlaybackSource
    player: PlayerName
    session_id: str
    name: str
    artist: str
    album: str
    duration_ms: int
    progress_ms: int
    timestamp: int
    is_playing: bool
    id: str | None = None
    uri: str | None = None
    url: str | None = None
    stream_url: str | None = None
    album_cover_url: str | None = None
    ended: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _coerce_ms(value: Any) -> int:
    try:
        return max(0, int(float(value or 0)))
    except (TypeError, ValueError):
        return 0


def _metadata_state(
    *,
    metadata: dict[str, Any],
    source: PlaybackSource,
    player: PlayerName,
    session_id: str,
    progress_ms: int = 0,
    duration_ms: int | None = None,
    is_playing: bool = True,
    ended: bool = False,
) -> PlayerState:
    duration = _coerce_ms(duration_ms if duration_ms is not None else metadata.get("duration_ms"))
    provider = str(metadata.get("provider") or source)
    return PlayerState(
        provider=provider,
        source=source,
        player=player,
        session_id=session_id,
        id=metadata.get("id"),
        name=str(metadata.get("name") or metadata.get("title") or metadata.get("file") or "-"),
        artist=str(metadata.get("artist") or "-"),
        album=str(metadata.get("album") or "-"),
        duration_ms=duration,
        progress_ms=_coerce_ms(progress_ms),
        timestamp=_timestamp_ms(),
        is_playing=is_playing,
        uri=metadata.get("uri"),
        url=metadata.get("url"),
        stream_url=metadata.get("stream_url"),
        album_cover_url=metadata.get("album_cover_url") or metadata.get("cover_url"),
        ended=ended,
    )


class MpvPlaybackAdapter:
    def __init__(self, *, source_url: str, source: PlaybackSource, metadata: dict[str, Any]) -> None:
        self.source_url = source_url
        self.source = source
        self.metadata = metadata
        self.session_id = uuid.uuid4().hex
        self.socket_path = str(Path(tempfile.gettempdir()) / f"sonex-mpv-{self.session_id}.sock")
        self.process: subprocess.Popen[bytes] | None = None

    def start(self) -> PlayerState:
        self.process = subprocess.Popen(
            [
                "mpv",
                "--no-video",
                f"--input-ipc-server={self.socket_path}",
                self.source_url,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError("mpv exited before playback started.")
            if os.path.exists(self.socket_path):
                return self.status(default_playing=True)
            time.sleep(0.05)
        raise RuntimeError("mpv IPC socket was not ready.")

    def _request(self, command: list[Any]) -> Any:
        if self.process and self.process.poll() is not None:
            raise RuntimeError("mpv process is not running.")
        payload = json.dumps({"command": command}).encode("utf-8") + b"\n"
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(1)
            client.connect(self.socket_path)
            client.sendall(payload)
            response = client.recv(65536)
        if not response:
            return None
        decoded = json.loads(response.decode("utf-8"))
        if decoded.get("error") not in (None, "success"):
            raise RuntimeError(f"mpv IPC failed: {decoded.get('error')}")
        return decoded.get("data")

    def _property(self, name: str) -> Any:
        return self._request(["get_property", name])

    def status(self, *, default_playing: bool | None = None) -> PlayerState:
        try:
            progress_ms = _coerce_ms(float(self._property("time-pos") or 0) * 1000)
        except Exception:
            progress_ms = 0
        try:
            duration_ms = _coerce_ms(float(self._property("duration") or 0) * 1000)
        except Exception:
            duration_ms = None
        try:
            paused = bool(self._property("pause"))
            is_playing = not paused
        except Exception:
            is_playing = bool(default_playing)
        ended = bool(self.process and self.process.poll() is not None)
        return _metadata_state(
            metadata=self.metadata,
            source=self.source,
            player="mpv",
            session_id=self.session_id,
            progress_ms=progress_ms,
            duration_ms=duration_ms,
            is_playing=is_playing and not ended,
            ended=ended,
        )

    def pause(self) -> PlayerState:
        self._request(["set_property", "pause", True])
        return self.status(default_playing=False)

    def resume(self) -> PlayerState:
        self._request(["set_property", "pause", False])
        return self.status(default_playing=True)

    def stop(self) -> PlayerState:
        try:
            self._request(["quit"])
        except Exception:
            if self.process and self.process.poll() is None:
                self.process.terminate()
        return replace(self.status(default_playing=False), is_playing=False, ended=True)


class LocalPlaybackController:
    def __init__(self) -> None:
        self._adapter: MpvPlaybackAdapter | None = None
        self.current_session_id: str | None = None

    def play(
        self,
        *,
        source_url: str,
        source: PlaybackSource,
        metadata: dict[str, Any],
        player: str = "mpv",
    ) -> PlayerState:
        normalized_player = player.strip().lower()
        if normalized_player != "mpv":
            raise RuntimeError("Only mpv is supported for controllable local playback.")
        if self._adapter is not None:
            try:
                self._adapter.stop()
            except Exception:
                pass
        adapter = MpvPlaybackAdapter(source_url=source_url, source=source, metadata=metadata)
        state = adapter.start()
        self._adapter = adapter
        self.current_session_id = state.session_id
        return state

    def _require_adapter(self) -> MpvPlaybackAdapter:
        if self._adapter is None:
            raise RuntimeError("No active local playback session.")
        return self._adapter

    def pause(self) -> PlayerState:
        return self._require_adapter().pause()

    def resume(self) -> PlayerState:
        return self._require_adapter().resume()

    def status(self) -> PlayerState:
        return self._require_adapter().status()

    def stop(self) -> PlayerState:
        adapter = self._require_adapter()
        state = adapter.stop()
        self._adapter = None
        self.current_session_id = None
        return state


controller = LocalPlaybackController()


def start_local_playback(
    *,
    tool: str,
    source_url: str,
    source: PlaybackSource,
    metadata: dict[str, Any],
    player: str = "mpv",
    success_message: str,
) -> dict[str, Any]:
    try:
        state = controller.play(source_url=source_url, source=source, metadata=metadata, player=player)
    except Exception as exc:
        return ToolResult.fail(
            tool=tool,
            message=f"Failed to start controllable playback: {exc}",
            error_code="PLAYER_START_FAILED",
            data={**metadata, "source": source, "player": player},
        ).to_dict()
    return ToolResult.success(tool=tool, message=success_message, data=state.to_dict()).to_dict()


def _control_result(tool: str, action: str) -> dict[str, Any]:
    try:
        state = getattr(controller, action)()
    except Exception as exc:
        return ToolResult.fail(
            tool=tool,
            message=str(exc),
            error_code="NO_ACTIVE_PLAYBACK",
        ).to_dict()
    messages = {
        "pause": "Playback paused.",
        "resume": "Playback resumed.",
        "stop": "Playback stopped.",
        "status": "Playback status.",
    }
    return ToolResult.success(tool=tool, message=messages[action], data=state.to_dict()).to_dict()


def local_playback_pause() -> dict[str, Any]:
    return _control_result("local_playback_pause", "pause")


def local_playback_resume() -> dict[str, Any]:
    return _control_result("local_playback_resume", "resume")


def local_playback_stop() -> dict[str, Any]:
    return _control_result("local_playback_stop", "stop")


def local_playback_status() -> dict[str, Any]:
    return _control_result("local_playback_status", "status")


for name, description, fn in (
    ("local_playback_pause", "Pause the current local playback session.", local_playback_pause),
    ("local_playback_resume", "Resume the current local playback session.", local_playback_resume),
    ("local_playback_stop", "Stop the current local playback session.", local_playback_stop),
    ("local_playback_status", "Return current local playback progress.", local_playback_status),
):
    registry.register(
        name=name,
        type="player",
        description=description,
        parameters=Params(type="object", properties={}, required=[]),
        fn=fn,
        enable=True,
        read_only=False,
        required_confirm=False,
    )
