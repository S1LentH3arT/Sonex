from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Literal, Protocol

from src.tools.registry import Params, registry
from src.tools.result import ToolResult

PlayerName = Literal["mpv", "cvlc"]
PlayerBackend = Literal["auto", "mpv", "cvlc"]
PlaybackSource = Literal["local", "youtube", "spotify", "apple_music"]


def _timestamp_ms() -> int:
    return int(time.time() * 1000)


def _player_debug(message: str) -> None:
    if os.environ.get("SONEX_PLAYER_DEBUG") == "1":
        print(f"[sonex-player-debug] {message}", file=sys.stderr)


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
    volume_percent: int | None = None
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
    volume_percent: int | None = None,
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
        volume_percent=volume_percent,
        ended=ended,
    )


def _coerce_volume(value: Any) -> int:
    try:
        volume = int(value)
    except (TypeError, ValueError):
        raise ValueError("Volume must be an integer from 0 to 100.") from None
    if not 0 <= volume <= 100:
        raise ValueError("Volume must be an integer from 0 to 100.")
    return volume


class PlaybackAdapter(Protocol):
    session_id: str

    def start(self) -> PlayerState: ...

    def status(self) -> PlayerState: ...

    def pause(self) -> PlayerState: ...

    def resume(self) -> PlayerState: ...

    def stop(self) -> PlayerState: ...

    def set_volume(self, volume_percent: int) -> PlayerState: ...


class MpvPlaybackAdapter:
    def __init__(self, *, source_url: str, source: PlaybackSource, metadata: dict[str, Any]) -> None:
        self.source_url = source_url
        self.source = source
        self.metadata = metadata
        self.session_id = uuid.uuid4().hex
        self.socket_path = str(Path(tempfile.gettempdir()) / f"sonex-mpv-{self.session_id}.sock")
        self.process: subprocess.Popen[bytes] | None = None
        self.volume_percent: int | None = None

    def start(self) -> PlayerState:
        if shutil.which("mpv") is None:
            raise RuntimeError("mpv is not installed or not on PATH.")
        self.process = subprocess.Popen(
            [
                "mpv",
                "--no-video",
                "--cache=yes",
                "--demuxer-readahead-secs=30",
                "--demuxer-max-bytes=256MiB",
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
            volume_percent=self.volume_percent,
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

    def set_volume(self, volume_percent: int) -> PlayerState:
        volume = _coerce_volume(volume_percent)
        self._request(["set_property", "volume", volume])
        self.volume_percent = volume
        return self.status()


class CvlcRcPlaybackAdapter:
    def __init__(self, *, source_url: str, source: PlaybackSource, metadata: dict[str, Any]) -> None:
        self.source_url = source_url
        self.source = source
        self.metadata = metadata
        self.session_id = uuid.uuid4().hex
        self.socket_path = str(Path(tempfile.gettempdir()) / f"sonex-cvlc-{self.session_id}.sock")
        self.process: subprocess.Popen[bytes] | None = None
        self.started_at = _timestamp_ms()
        self.progress_ms = 0
        self.is_playing = True
        self.volume_percent: int | None = None

    def start(self) -> PlayerState:
        if shutil.which("cvlc") is None:
            raise RuntimeError("cvlc is not installed or not on PATH.")
        self.process = subprocess.Popen(
            [
                "cvlc",
                "--no-video",
                "--network-caching=5000",
                "--extraintf",
                "oldrc",
                "--rc-unix",
                self.socket_path,
                self.source_url,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError("cvlc exited before playback started.")
            if os.path.exists(self.socket_path):
                return self.status()
            time.sleep(0.05)
        raise RuntimeError("cvlc rc socket was not ready.")

    def _send(self, command: str) -> None:
        if self.process and self.process.poll() is not None:
            raise RuntimeError("cvlc process is not running.")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(1)
            client.connect(self.socket_path)
            client.sendall(command.encode("utf-8") + b"\n")

    def status(self) -> PlayerState:
        ended = bool(self.process and self.process.poll() is not None)
        progress_ms = self.progress_ms
        if self.is_playing and not ended:
            progress_ms += max(0, _timestamp_ms() - self.started_at)
        return _metadata_state(
            metadata=self.metadata,
            source=self.source,
            player="cvlc",
            session_id=self.session_id,
            progress_ms=progress_ms,
            is_playing=self.is_playing and not ended,
            volume_percent=self.volume_percent,
            ended=ended,
        )

    def pause(self) -> PlayerState:
        self._send("pause")
        self.progress_ms = self.status().progress_ms
        self.is_playing = False
        return self.status()

    def resume(self) -> PlayerState:
        self._send("play")
        self.started_at = _timestamp_ms()
        self.is_playing = True
        return self.status()

    def stop(self) -> PlayerState:
        try:
            self._send("stop")
            self._send("quit")
        except Exception:
            if self.process and self.process.poll() is None:
                self.process.terminate()
        return replace(self.status(), is_playing=False, ended=True)

    def set_volume(self, volume_percent: int) -> PlayerState:
        volume = _coerce_volume(volume_percent)
        self._send(f"volume {round(volume * 256 / 100)}")
        self.volume_percent = volume
        return self.status()


class LocalPlaybackController:
    def __init__(self) -> None:
        self._adapter: PlaybackAdapter | None = None
        self.current_session_id: str | None = None
        self.player_backend: PlayerBackend = "auto"

    def play(
        self,
        *,
        source_url: str,
        source: PlaybackSource,
        metadata: dict[str, Any],
        player: str | None = None,
    ) -> PlayerState:
        backend = self._normalize_backend(player or self.player_backend)
        if self._adapter is not None:
            try:
                self._adapter.stop()
            except Exception:
                pass
        adapter, state = self._start_adapter(
            backend=backend,
            source_url=source_url,
            source=source,
            metadata=metadata,
        )
        self._adapter = adapter
        self.current_session_id = state.session_id
        return state

    def _normalize_backend(self, backend: str) -> PlayerBackend:
        normalized = backend.strip().lower()
        if normalized not in {"auto", "mpv", "cvlc"}:
            raise ValueError("Unsupported local playback backend. Use auto, mpv, or cvlc.")
        return normalized  # type: ignore[return-value]

    def set_player_backend(self, backend: str) -> PlayerBackend:
        self.player_backend = self._normalize_backend(backend)
        return self.player_backend

    def _adapter_for(
        self,
        backend: Literal["mpv", "cvlc"],
        *,
        source_url: str,
        source: PlaybackSource,
        metadata: dict[str, Any],
    ) -> PlaybackAdapter:
        adapter_cls = MpvPlaybackAdapter if backend == "mpv" else CvlcRcPlaybackAdapter
        return adapter_cls(source_url=source_url, source=source, metadata=metadata)

    def _start_adapter(
        self,
        *,
        backend: PlayerBackend,
        source_url: str,
        source: PlaybackSource,
        metadata: dict[str, Any],
    ) -> tuple[PlaybackAdapter, PlayerState]:
        backends: tuple[Literal["mpv", "cvlc"], ...] = ("mpv", "cvlc") if backend == "auto" else (backend,)
        failures: list[str] = []
        for candidate in backends:
            adapter = self._adapter_for(candidate, source_url=source_url, source=source, metadata=metadata)
            try:
                return adapter, adapter.start()
            except Exception as exc:
                _player_debug(f"{candidate} start failed: {exc}")
                failures.append(f"{candidate}: {exc}")
                try:
                    adapter.stop()
                except Exception:
                    pass
                if backend != "auto":
                    raise
        raise RuntimeError("; ".join(failures) or "No playback backend could start.")

    def _require_adapter(self) -> PlaybackAdapter:
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

    def set_volume(self, volume_percent: int) -> PlayerState:
        return self._require_adapter().set_volume(_coerce_volume(volume_percent))


controller = LocalPlaybackController()


def start_local_playback(
    *,
    tool: str,
    source_url: str,
    source: PlaybackSource,
    metadata: dict[str, Any],
    player: str = "auto",
    success_message: str,
) -> dict[str, Any]:
    selected_player = None if player.strip().lower() == "auto" else player
    try:
        state = controller.play(source_url=source_url, source=source, metadata=metadata, player=selected_player)
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


def local_playback_volume(volume_percent: int) -> dict[str, Any]:
    try:
        volume = _coerce_volume(volume_percent)
    except ValueError as exc:
        return ToolResult.fail(
            tool="local_playback_volume",
            message=str(exc),
            error_code="INVALID_VOLUME",
        ).to_dict()
    try:
        state = controller.set_volume(volume)
    except Exception as exc:
        return ToolResult.fail(
            tool="local_playback_volume",
            message=str(exc),
            error_code="NO_ACTIVE_PLAYBACK",
        ).to_dict()
    return ToolResult.success(
        tool="local_playback_volume",
        message=f"Playback volume set to {volume}%.",
        data=state.to_dict(),
    ).to_dict()


def local_playback_player(backend: str) -> dict[str, Any]:
    try:
        selected = controller.set_player_backend(backend)
    except ValueError as exc:
        return ToolResult.fail(
            tool="local_playback_player",
            message=str(exc),
            error_code="INVALID_PLAYER_BACKEND",
        ).to_dict()
    return ToolResult.success(
        tool="local_playback_player",
        message=f"Local playback backend set to {selected}.",
        data={"backend": selected},
    ).to_dict()


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

registry.register(
    name="local_playback_volume",
    type="player",
    description="Set current local playback volume from 0 to 100 percent.",
    parameters=Params(
        type="object",
        properties={"volume_percent": {"type": "integer", "minimum": 0, "maximum": 100}},
        required=["volume_percent"],
    ),
    fn=local_playback_volume,
    enable=True,
    read_only=False,
    required_confirm=False,
)

registry.register(
    name="local_playback_player",
    type="player",
    description="Set local playback backend strategy for this session.",
    parameters=Params(
        type="object",
        properties={"backend": {"type": "string", "enum": ["auto", "mpv", "cvlc"]}},
        required=["backend"],
    ),
    fn=local_playback_player,
    enable=True,
    read_only=False,
    required_confirm=False,
)
