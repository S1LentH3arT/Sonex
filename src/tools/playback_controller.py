"""Playback controller support for tool implementations used by the planner and playback flows.

Implements the playback_controller module responsibilities used by Sonex runtime flows.
Key public entry points include PlayerState, PlaybackAdapter, MpvPlaybackAdapter, CvlcRcPlaybackAdapter, LocalPlaybackController.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Callable, Literal, Protocol

from src.tools.registry import Params, registry
from src.tools.result import ToolResult
from src.tools.mpv_diagnostics import MpvDiagnosticSession, MpvPlaybackHealthMonitor

PlayerName = Literal["mpv", "cvlc"]
PlayerBackend = Literal["auto", "mpv", "cvlc"]
PlaybackSource = Literal["local", "youtube", "spotify", "apple_music"]

LOCAL_PLAYBACK_APPLICATIONS: tuple[dict[str, Any], ...] = (
    {
        "backend": "mpv",
        "label": "mpv",
        "executables": ("mpv",),
        "description": "Controllable local player for stable background playback.",
    },
    {
        "backend": "cvlc",
        "label": "VLC",
        "executables": ("cvlc", "vlc"),
        "description": "Controllable VLC playback through its RC interface.",
    },
)


def available_local_playback_backends() -> list[dict[str, str]]:
    """Return installed applications backed by Sonex playback adapters."""
    available: list[dict[str, str]] = []
    for application in LOCAL_PLAYBACK_APPLICATIONS:
        executable = next(
            (
                path
                for command in application["executables"]
                if (path := shutil.which(command)) is not None
            ),
            None,
        )
        if executable is None:
            continue
        available.append(
            {
                "backend": str(application["backend"]),
                "label": str(application["label"]),
                "description": str(application["description"]),
                "executable": executable,
            }
        )
    return available


def _vlc_executable() -> str | None:
    return shutil.which("cvlc") or shutil.which("vlc")


def _timestamp_ms() -> int:
    """Prepares timestamp ms for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs timestamp ms without duplicating the local rules.

    Example: _timestamp_ms() -> returns the value used by the surrounding Sonex flow.
    """
    return int(time.time() * 1000)


def _player_debug(message: str) -> None:
    """Prepares player debug for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs player debug without duplicating the local rules.

    Example: _player_debug(message=...) -> returns the value used by the surrounding Sonex flow.
    """
    if os.environ.get("SONEX_PLAYER_DEBUG") == "1":
        print(f"[sonex-player-debug] {message}", file=sys.stderr)


@dataclass(frozen=True)
class PlayerState:
    """Represents player state.

    Encapsulates player state data and behavior used by Sonex runtime flows.
    """
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
    paused_for_cache: bool = False
    diagnostic_notice: str | None = None
    id: str | None = None
    uri: str | None = None
    url: str | None = None
    stream_url: str | None = None
    album_cover_url: str | None = None
    volume_percent: int | None = None
    ended: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Coordinates to dict for the current Sonex flow.

        Typical use: Use this function when runtime code needs to dict as part of a Sonex command, playback, auth, llm, or ui path.

        Example: to_dict() -> returns the value used by the surrounding Sonex flow.
        """
        return asdict(self)


def _coerce_ms(value: Any) -> int:
    """Prepares coerce ms for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs coerce ms without duplicating the local rules.

    Example: _coerce_ms(value=...) -> returns the value used by the surrounding Sonex flow.
    """
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
    paused_for_cache: bool = False,
    diagnostic_notice: str | None = None,
    volume_percent: int | None = None,
    ended: bool = False,
) -> PlayerState:
    """Prepares metadata state for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs metadata state without duplicating the local rules.

    Example: _metadata_state(metadata=..., source=..., player=..., session_id=..., progress_ms=..., duration_ms=..., is_playing=..., volume_percent=..., ended=...) -> returns the value used by the surrounding Sonex flow.
    """
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
        paused_for_cache=paused_for_cache,
        diagnostic_notice=diagnostic_notice,
        uri=metadata.get("uri"),
        url=metadata.get("url"),
        stream_url=metadata.get("stream_url"),
        album_cover_url=metadata.get("album_cover_url") or metadata.get("cover_url"),
        volume_percent=volume_percent,
        ended=ended,
    )


def _coerce_volume(value: Any) -> int:
    """Prepares coerce volume for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs coerce volume without duplicating the local rules.

    Example: _coerce_volume(value=...) -> returns the value used by the surrounding Sonex flow.
    """
    try:
        volume = int(value)
    except (TypeError, ValueError):
        raise ValueError("Volume must be an integer from 0 to 100.") from None
    if not 0 <= volume <= 100:
        raise ValueError("Volume must be an integer from 0 to 100.")
    return volume


class PlaybackAdapter(Protocol):
    """Represents playback adapter.

    Encapsulates playback adapter data and behavior used by Sonex runtime flows. Extends protocol semantics.
    """
    session_id: str

    def start(self) -> PlayerState:
        """Start playback through the adapter.

        Returns:
            The current player state after playback starts.
        """
        ...

    def status(self) -> PlayerState:
        """Read the current playback status.

        Returns:
            The latest player state reported by the adapter.
        """
        ...

    def pause(self) -> PlayerState:
        """Pause active playback.

        Returns:
            The player state after pause is applied.
        """
        ...

    def resume(self) -> PlayerState:
        """Resume paused playback.

        Returns:
            The player state after playback resumes.
        """
        ...

    def stop(self) -> PlayerState:
        """Stop active playback.

        Returns:
            The player state after stop is applied.
        """
        ...

    def set_volume(self, volume_percent: int) -> PlayerState:
        """Set playback volume.

        Args:
            volume_percent: Volume percentage in the inclusive 0 to 100 range.

        Returns:
            The player state after the volume change.
        """
        ...


class MpvPlaybackAdapter:
    """Represents mpv playback adapter.

    Encapsulates mpv playback adapter data and behavior used by Sonex runtime flows.
    """
    def __init__(
        self,
        *,
        source_url: str,
        source: PlaybackSource,
        metadata: dict[str, Any],
        diagnostic_time_source: Callable[[], float] = time.monotonic,
    ) -> None:
        """Prepares init for an internal Sonex flow.

        Typical use: Use this helper when nearby code needs init without duplicating the local rules.

        Example: __init__(source_url=..., source=..., metadata=...) -> returns the value used by the surrounding Sonex flow.
        """
        self.source_url = source_url
        self.source = source
        self.metadata = metadata
        self._diagnostic_time_source = diagnostic_time_source
        self.session_id = uuid.uuid4().hex
        self.socket_path = str(Path(tempfile.gettempdir()) / f"sonex-mpv-{self.session_id}.sock")
        self.process: subprocess.Popen[bytes] | None = None
        self.volume_percent: int | None = None
        self.diagnostics: MpvDiagnosticSession | None = None
        self.health_monitor: MpvPlaybackHealthMonitor | None = None
        self._stderr_thread: threading.Thread | None = None
        self._last_progress_ms = 0
        self._last_duration_ms: int | None = None

    def start(self) -> PlayerState:
        """Coordinates start for the current Sonex flow.

        Typical use: Use this function when runtime code needs start as part of a Sonex command, playback, auth, llm, or ui path.

        Example: start() -> returns the value used by the surrounding Sonex flow.
        """
        if shutil.which("mpv") is None:
            raise RuntimeError("mpv is not installed or not on PATH.")
        try:
            self.diagnostics = MpvDiagnosticSession(
                session_id=self.session_id,
                media_location=self.source_url,
            )
        except OSError:
            self.diagnostics = None
        if self.diagnostics:
            self.health_monitor = MpvPlaybackHealthMonitor(
                session=self.diagnostics,
                burst_sampler=self._diagnostic_probe,
                time_source=self._diagnostic_time_source,
            )
        try:
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
                stderr=subprocess.PIPE if self.diagnostics else subprocess.DEVNULL,
                start_new_session=True,
            )
        except Exception as exc:
            self._close_diagnostics("start_failed", error=str(exc))
            raise
        if self.diagnostics and isinstance(self.process.stderr, io.IOBase):
            self._stderr_thread = threading.Thread(
                target=self.diagnostics.capture_mpv_stderr,
                args=(self.process.stderr,),
                name=f"sonex-mpv-log-{self.session_id[:8]}",
                daemon=True,
            )
            self._stderr_thread.start()
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                self._close_diagnostics("start_failed", error="mpv exited before playback started")
                raise RuntimeError("mpv exited before playback started.")
            if os.path.exists(self.socket_path):
                return self.status(default_playing=True)
            time.sleep(0.05)
        self._close_diagnostics("start_failed", error="mpv IPC socket was not ready")
        raise RuntimeError("mpv IPC socket was not ready.")

    def _request(self, command: list[Any]) -> Any:
        """Prepares request for an internal Sonex flow.

        Typical use: Use this helper when nearby code needs request without duplicating the local rules.

        Example: _request(command=...) -> returns the value used by the surrounding Sonex flow.
        """
        if self.process and self.process.poll() is not None:
            raise RuntimeError("mpv process is not running.")
        request_id = uuid.uuid4().int & ((1 << 63) - 1)
        payload = json.dumps({
            "command": command,
            "request_id": request_id,
        }).encode("utf-8") + b"\n"
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(1)
            client.connect(self.socket_path)
            client.sendall(payload)
            buffered = b""
            while True:
                response = client.recv(65536)
                if not response:
                    break
                buffered += response
                while b"\n" in buffered:
                    line, buffered = buffered.split(b"\n", 1)
                    if not line.strip():
                        continue
                    decoded = json.loads(line.decode("utf-8"))
                    if decoded.get("request_id") != request_id:
                        continue
                    if decoded.get("error") not in (None, "success"):
                        raise RuntimeError(f"mpv IPC failed: {decoded.get('error')}")
                    return decoded.get("data")
        raise RuntimeError("mpv IPC returned no matching response.")

    def _property(self, name: str) -> Any:
        """Prepares property for an internal Sonex flow.

        Typical use: Use this helper when nearby code needs property without duplicating the local rules.

        Example: _property(name=...) -> returns the value used by the surrounding Sonex flow.
        """
        return self._request(["get_property", name])

    def _diagnostic_probe(self) -> dict[str, Any]:
        """Read one high-frequency diagnostic sample from mpv."""
        progress_ms = _coerce_ms(float(self._property("time-pos") or 0) * 1000)
        paused = bool(self._property("pause"))
        paused_for_cache = bool(self._property("paused-for-cache"))
        current_ao_value = self._property("current-ao")
        return {
            "progress_ms": progress_ms,
            "is_playing": not paused,
            "paused_for_cache": paused_for_cache,
            "current_ao": str(current_ao_value) if current_ao_value else None,
            "ipc_ok": True,
        }

    def _close_diagnostics(self, event: str, *, error: str | None = None) -> None:
        if self.health_monitor:
            self.health_monitor.close()
        if self.diagnostics:
            self.diagnostics.record(
                event,
                progress_ms=self._last_progress_ms,
                is_playing=False,
                ipc_ok=error is None,
                error=error,
            )
            self.diagnostics.close()

    def status(self, *, default_playing: bool | None = None) -> PlayerState:
        """Coordinates status for the current Sonex flow.

        Typical use: Use this function when runtime code needs status as part of a Sonex command, playback, auth, llm, or ui path.

        Example: status(default_playing=...) -> returns the value used by the surrounding Sonex flow.
        """
        ended = bool(self.process and self.process.poll() is not None)
        if ended:
            self._close_diagnostics("process_ended")
            return _metadata_state(
                metadata=self.metadata,
                source=self.source,
                player="mpv",
                session_id=self.session_id,
                progress_ms=self._last_progress_ms,
                duration_ms=self._last_duration_ms,
                is_playing=False,
                paused_for_cache=False,
                volume_percent=self.volume_percent,
                ended=True,
            )

        try:
            progress_ms = _coerce_ms(float(self._property("time-pos") or 0) * 1000)
            self._last_progress_ms = progress_ms
        except Exception as exc:
            if self.health_monitor and default_playing is None:
                self.health_monitor.observe(
                    progress_ms=self._last_progress_ms,
                    is_playing=bool(default_playing),
                    paused_for_cache=False,
                    current_ao=None,
                    ipc_ok=False,
                    error=str(exc),
                )
            if default_playing is None:
                raise RuntimeError("mpv progress status is unavailable.") from exc
            progress_ms = self._last_progress_ms
        try:
            duration_ms = _coerce_ms(float(self._property("duration") or 0) * 1000)
            self._last_duration_ms = duration_ms
        except Exception:
            duration_ms = self._last_duration_ms
        try:
            paused = bool(self._property("pause"))
            is_playing = not paused
        except Exception:
            is_playing = bool(default_playing)
        try:
            paused_for_cache = bool(self._property("paused-for-cache"))
        except Exception:
            paused_for_cache = False
        try:
            current_ao_value = self._property("current-ao")
            current_ao = str(current_ao_value) if current_ao_value else None
        except Exception:
            current_ao = None
        diagnostic_notice = None
        if self.health_monitor:
            diagnostic_notice = self.health_monitor.observe(
                progress_ms=progress_ms,
                is_playing=is_playing,
                paused_for_cache=paused_for_cache,
                current_ao=current_ao,
                ipc_ok=True,
            )
        return _metadata_state(
            metadata=self.metadata,
            source=self.source,
            player="mpv",
            session_id=self.session_id,
            progress_ms=progress_ms,
            duration_ms=duration_ms,
            is_playing=is_playing,
            paused_for_cache=paused_for_cache,
            diagnostic_notice=diagnostic_notice,
            volume_percent=self.volume_percent,
            ended=False,
        )

    def pause(self) -> PlayerState:
        """Coordinates pause for the current Sonex flow.

        Typical use: Use this function when runtime code needs pause as part of a Sonex command, playback, auth, llm, or ui path.

        Example: pause() -> returns the value used by the surrounding Sonex flow.
        """
        self._request(["set_property", "pause", True])
        return self.status(default_playing=False)

    def resume(self) -> PlayerState:
        """Coordinates resume for the current Sonex flow.

        Typical use: Use this function when runtime code needs resume as part of a Sonex command, playback, auth, llm, or ui path.

        Example: resume() -> returns the value used by the surrounding Sonex flow.
        """
        self._request(["set_property", "pause", False])
        return self.status(default_playing=True)

    def stop(self) -> PlayerState:
        """Coordinates stop for the current Sonex flow.

        Typical use: Use this function when runtime code needs stop as part of a Sonex command, playback, auth, llm, or ui path.

        Example: stop() -> returns the value used by the surrounding Sonex flow.
        """
        try:
            final_state = self.status(default_playing=False)
        except Exception:
            final_state = _metadata_state(
                metadata=self.metadata,
                source=self.source,
                player="mpv",
                session_id=self.session_id,
                progress_ms=self._last_progress_ms,
                duration_ms=self._last_duration_ms,
                is_playing=False,
                volume_percent=self.volume_percent,
            )
        try:
            self._request(["quit"])
        except Exception:
            if self.process and self.process.poll() is None:
                self.process.terminate()
        try:
            return replace(final_state, is_playing=False, diagnostic_notice=None, ended=True)
        finally:
            self._close_diagnostics("playback_stopped")

    def set_volume(self, volume_percent: int) -> PlayerState:
        """Coordinates set volume for the current Sonex flow.

        Typical use: Use this function when runtime code needs set volume as part of a Sonex command, playback, auth, llm, or ui path.

        Example: set_volume(volume_percent=...) -> returns the value used by the surrounding Sonex flow.
        """
        volume = _coerce_volume(volume_percent)
        self._request(["set_property", "volume", volume])
        self.volume_percent = volume
        return self.status()


class CvlcRcPlaybackAdapter:
    """Represents cvlc rc playback adapter.

    Encapsulates cvlc rc playback adapter data and behavior used by Sonex runtime flows.
    """
    def __init__(self, *, source_url: str, source: PlaybackSource, metadata: dict[str, Any]) -> None:
        """Prepares init for an internal Sonex flow.

        Typical use: Use this helper when nearby code needs init without duplicating the local rules.

        Example: __init__(source_url=..., source=..., metadata=...) -> returns the value used by the surrounding Sonex flow.
        """
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
        """Coordinates start for the current Sonex flow.

        Typical use: Use this function when runtime code needs start as part of a Sonex command, playback, auth, llm, or ui path.

        Example: start() -> returns the value used by the surrounding Sonex flow.
        """
        executable = _vlc_executable()
        if executable is None:
            raise RuntimeError("VLC is not installed or not on PATH.")
        self.process = subprocess.Popen(
            [
                executable,
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
        """Prepares send for an internal Sonex flow.

        Typical use: Use this helper when nearby code needs send without duplicating the local rules.

        Example: _send(command=...) -> returns the value used by the surrounding Sonex flow.
        """
        if self.process and self.process.poll() is not None:
            raise RuntimeError("cvlc process is not running.")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(1)
            client.connect(self.socket_path)
            client.sendall(command.encode("utf-8") + b"\n")

    def status(self) -> PlayerState:
        """Coordinates status for the current Sonex flow.

        Typical use: Use this function when runtime code needs status as part of a Sonex command, playback, auth, llm, or ui path.

        Example: status() -> returns the value used by the surrounding Sonex flow.
        """
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
        """Coordinates pause for the current Sonex flow.

        Typical use: Use this function when runtime code needs pause as part of a Sonex command, playback, auth, llm, or ui path.

        Example: pause() -> returns the value used by the surrounding Sonex flow.
        """
        self._send("pause")
        self.progress_ms = self.status().progress_ms
        self.is_playing = False
        return self.status()

    def resume(self) -> PlayerState:
        """Coordinates resume for the current Sonex flow.

        Typical use: Use this function when runtime code needs resume as part of a Sonex command, playback, auth, llm, or ui path.

        Example: resume() -> returns the value used by the surrounding Sonex flow.
        """
        self._send("play")
        self.started_at = _timestamp_ms()
        self.is_playing = True
        return self.status()

    def stop(self) -> PlayerState:
        """Coordinates stop for the current Sonex flow.

        Typical use: Use this function when runtime code needs stop as part of a Sonex command, playback, auth, llm, or ui path.

        Example: stop() -> returns the value used by the surrounding Sonex flow.
        """
        try:
            self._send("stop")
            self._send("quit")
        except Exception:
            if self.process and self.process.poll() is None:
                self.process.terminate()
        return replace(self.status(), is_playing=False, ended=True)

    def set_volume(self, volume_percent: int) -> PlayerState:
        """Coordinates set volume for the current Sonex flow.

        Typical use: Use this function when runtime code needs set volume as part of a Sonex command, playback, auth, llm, or ui path.

        Example: set_volume(volume_percent=...) -> returns the value used by the surrounding Sonex flow.
        """
        volume = _coerce_volume(volume_percent)
        self._send(f"volume {round(volume * 256 / 100)}")
        self.volume_percent = volume
        return self.status()


class LocalPlaybackController:
    """Represents local playback controller.

    Encapsulates local playback controller data and behavior used by Sonex runtime flows.
    """
    def __init__(self) -> None:
        """Init for local playback controller.

        Coordinates the init method behavior while preserving local playback controller state and contracts.
        """
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
        """Coordinates play for the current Sonex flow.

        Typical use: Use this function when runtime code needs play as part of a Sonex command, playback, auth, llm, or ui path.

        Example: play(source_url=..., source=..., metadata=..., player=...) -> returns the value used by the surrounding Sonex flow.
        """
        requested_backend = self._normalize_backend(player or "auto")
        backend = (
            requested_backend
            if requested_backend != "auto"
            else self.player_backend
        )
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
        """Prepares normalize backend for an internal Sonex flow.

        Typical use: Use this helper when nearby code needs normalize backend without duplicating the local rules.

        Example: _normalize_backend(backend=...) -> returns the value used by the surrounding Sonex flow.
        """
        normalized = backend.strip().lower()
        if normalized not in {"auto", "mpv", "cvlc"}:
            raise ValueError("Unsupportedlocal playback backend. Use auto, mpv, or cvlc.")
        return normalized  # type: ignore[return-value]

    def set_player_backend(self, backend: str) -> PlayerBackend:
        """Coordinates set player backend for the current Sonex flow.

        Typical use: Use this function when runtime code needs set player backend as part of a Sonex command, playback, auth, llm, or ui path.

        Example: set_player_backend(backend=...) -> returns the value used by the surrounding Sonex flow.
        """
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
        """Prepares adapter for for an internal Sonex flow.

        Typical use: Use this helper when nearby code needs adapter for without duplicating the local rules.

        Example: _adapter_for(backend=..., source_url=..., source=..., metadata=...) -> returns the value used by the surrounding Sonex flow.
        """
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
        """Prepares start adapter for an internal Sonex flow.

        Typical use: Use this helper when nearby code needs start adapter without duplicating the local rules.

        Example: _start_adapter(backend=..., source_url=..., source=..., metadata=...) -> returns the value used by the surrounding Sonex flow.
        """
        backends: tuple[Literal["mpv", "cvlc"], ...] = ("mpv",) if backend == "auto" else (backend,)
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
        detail = "; ".join(failures) or "No playback backend could start."
        if backend == "auto":
            raise RuntimeError(
                f"{detail}. auto uses mpv only for playback stability; run /player "
                "and choose VLC if you want to try the manual diagnostic backend."
            )
        raise RuntimeError(detail)

    def _require_adapter(self) -> PlaybackAdapter:
        """Prepares require adapter for an internal Sonex flow.

        Typical use: Use this helper when nearby code needs require adapter without duplicating the local rules.

        Example: _require_adapter() -> returns the value used by the surrounding Sonex flow.
        """
        if self._adapter is None:
            raise RuntimeError("No active local playback session.")
        return self._adapter

    def pause(self) -> PlayerState:
        """Coordinates pause for the current Sonex flow.

        Typical use: Use this function when runtime code needs pause as part of a Sonex command, playback, auth, llm, or ui path.

        Example: pause() -> returns the value used by the surrounding Sonex flow.
        """
        return self._require_adapter().pause()

    def resume(self) -> PlayerState:
        """Coordinates resume for the current Sonex flow.

        Typical use: Use this function when runtime code needs resume as part of a Sonex command, playback, auth, llm, or ui path.

        Example: resume() -> returns the value used by the surrounding Sonex flow.
        """
        return self._require_adapter().resume()

    def status(self) -> PlayerState:
        """Coordinates status for the current Sonex flow.

        Typical use: Use this function when runtime code needs status as part of a Sonex command, playback, auth, llm, or ui path.

        Example: status() -> returns the value used by the surrounding Sonex flow.
        """
        state = self._require_adapter().status()
        if state.ended:
            self._adapter = None
            self.current_session_id = None
        return state

    def stop(self) -> PlayerState:
        """Coordinates stop for the current Sonex flow.

        Typical use: Use this function when runtime code needs stop as part of a Sonex command, playback, auth, llm, or ui path.

        Example: stop() -> returns the value used by the surrounding Sonex flow.
        """
        adapter = self._require_adapter()
        state = adapter.stop()
        self._adapter = None
        self.current_session_id = None
        return state

    def set_volume(self, volume_percent: int) -> PlayerState:
        """Coordinates set volume for the current Sonex flow.

        Typical use: Use this function when runtime code needs set volume as part of a Sonex command, playback, auth, llm, or ui path.

        Example: set_volume(volume_percent=...) -> returns the value used by the surrounding Sonex flow.
        """
        return self._require_adapter().set_volume(_coerce_volume(volume_percent))


controller = LocalPlaybackController()


def resolve_local_playback_backend(player: str = "auto") -> PlayerBackend:
    """Normalize a tool-supplied player without consuming the ``auto`` route."""
    return controller._normalize_backend(player)


def start_local_playback(
    *,
    tool: str,
    source_url: str,
    source: PlaybackSource,
    metadata: dict[str, Any],
    player: str = "auto",
    success_message: str,
) -> dict[str, Any]:
    """Coordinates start local playback for the current Sonex flow.

    Typical use: Use this function when runtime code needs start local playback as part of a Sonex command, playback, auth, llm, or ui path.

    Example: start_local_playback(tool=..., source_url=..., source=..., metadata=..., player=..., success_message=...) -> returns the value used by the surrounding Sonex flow.
    """
    from src.music.player_sink_runtime import play_through_persisted_sink

    if player.strip().casefold() == "auto":
        try:
            routed = play_through_persisted_sink(
                source_url=source_url,
                track=metadata,
            )
        except Exception as exc:
            return ToolResult.fail(
                tool=tool,
                message=(
                    f"Default player failed: {exc}. Run /player to change it, "
                    "or explicitly choose mpv for this playback."
                ),
                error_code="DEFAULT_PLAYER_FAILED",
                data={
                    **metadata,
                    "source": source,
                    "player": player,
                    "player_recovery": {
                        "source_url": source_url,
                        "source": source,
                        "metadata": metadata,
                        "success_message": success_message,
                    },
                },
            ).to_dict()
        if routed is not None:
            return ToolResult.success(
                tool=tool,
                message=success_message,
                data={
                    **metadata,
                    **routed.state,
                    "sink_id": routed.sink_id,
                    "source": source,
                },
            ).to_dict()

    selected_player = resolve_local_playback_backend(player)
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
    """Prepares control result for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs control result without duplicating the local rules.

    Example: _control_result(tool=..., action=...) -> returns the value used by the surrounding Sonex flow.
    """
    from src.music.player_sink_runtime import control_persisted_player_sink

    messages = {
        "pause": "Playback paused.",
        "resume": "Playback resumed.",
        "stop": "Playback stopped.",
        "status": "Playback status.",
    }
    try:
        routed = control_persisted_player_sink(action)
        if routed is not None:
            return ToolResult.success(
                tool=tool,
                message=messages[action],
                data={**routed.state, "sink_id": routed.sink_id},
            ).to_dict()
        state = getattr(controller, action)()
    except Exception as exc:
        error_code = (
            "PLAYBACK_STATUS_UNAVAILABLE"
            if action == "status" and controller.current_session_id
            else "NO_ACTIVE_PLAYBACK"
        )
        return ToolResult.fail(
            tool=tool,
            message=str(exc),
            error_code=error_code,
        ).to_dict()
    return ToolResult.success(tool=tool, message=messages[action], data=state.to_dict()).to_dict()


def local_playback_pause() -> dict[str, Any]:
    """Coordinates local playback pause for the current Sonex flow.

    Typical use: Use this function when runtime code needs local playback pause as part of a Sonex command, playback, auth, llm, or ui path.

    Example: local_playback_pause() -> returns the value used by the surrounding Sonex flow.
    """
    return _control_result("local_playback_pause", "pause")


def local_playback_resume() -> dict[str, Any]:
    """Coordinates local playback resume for the current Sonex flow.

    Typical use: Use this function when runtime code needs local playback resume as part of a Sonex command, playback, auth, llm, or ui path.

    Example: local_playback_resume() -> returns the value used by the surrounding Sonex flow.
    """
    return _control_result("local_playback_resume", "resume")


def local_playback_stop() -> dict[str, Any]:
    """Coordinates local playback stop for the current Sonex flow.

    Typical use: Use this function when runtime code needs local playback stop as part of a Sonex command, playback, auth, llm, or ui path.

    Example: local_playback_stop() -> returns the value used by the surrounding Sonex flow.
    """
    return _control_result("local_playback_stop", "stop")


def local_playback_status() -> dict[str, Any]:
    """Coordinates local playback status for the current Sonex flow.

    Typical use: Use this function when runtime code needs local playback status as part of a Sonex command, playback, auth, llm, or ui path.

    Example: local_playback_status() -> returns the value used by the surrounding Sonex flow.
    """
    return _control_result("local_playback_status", "status")


def local_playback_volume(volume_percent: int) -> dict[str, Any]:
    """Coordinates local playback volume for the current Sonex flow.

    Typical use: Use this function when runtime code needs local playback volume as part of a Sonex command, playback, auth, llm, or ui path.

    Example: local_playback_volume(volume_percent=...) -> returns the value used by the surrounding Sonex flow.
    """
    try:
        volume = _coerce_volume(volume_percent)
    except ValueError as exc:
        return ToolResult.fail(
            tool="local_playback_volume",
            message=str(exc),
            error_code="INVALID_VOLUME",
        ).to_dict()
    from src.music.player_sink_runtime import control_persisted_player_sink

    try:
        routed = control_persisted_player_sink("volume", volume)
        if routed is not None:
            return ToolResult.success(
                tool="local_playback_volume",
                message=f"Playback volume set to {volume}%.",
                data={**routed.state, "sink_id": routed.sink_id},
            ).to_dict()
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
    """Coordinates local playback player for the current Sonex flow.

    Typical use: Use this function when runtime code needs local playback player as part of a Sonex command, playback, auth, llm, or ui path.

    Example: local_playback_player(backend=...) -> returns the value used by the surrounding Sonex flow.
    """
    try:
        selected = controller.set_player_backend(backend)
    except ValueError as exc:
        return ToolResult.fail(
            tool="local_playback_player",
            message=str(exc),
            error_code="INVALID_PLAYER_BACKEND",
        ).to_dict()
    from src.tools.player_permission import remember_player

    remember_player(selected)
    return ToolResult.success(
        tool="local_playback_player",
        message=f"Default local player set to {selected}.",
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
    description="Set the default local player for this session.",
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
