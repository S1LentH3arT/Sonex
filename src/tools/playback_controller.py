"""Playback controller support for tool implementations used by the planner and playback flows.
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
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable, Literal, Protocol

from src.tools.registry import Params, registry
from src.tools.result import ToolResult
from src.tools.mpv_diagnostics import MpvDiagnosticSession, MpvPlaybackHealthMonitor
from src.tools.playback_state import (
    PlayerName,
    PlayerState,
    PlaybackSource,
    coerce_ms as _coerce_ms,
    coerce_volume as _coerce_volume,
    metadata_state as _metadata_state,
    timestamp_ms as _timestamp_ms,
)

PlayerBackend = Literal["mpv"]

LOCAL_PLAYBACK_APPLICATIONS: tuple[dict[str, Any], ...] = (
    {
        "backend": "mpv",
        "label": "mpv",
        "executables": ("mpv",),
        "description": "Controllable local player for stable background playback.",
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


def _player_debug(message: str) -> None:
    if os.environ.get("SONEX_PLAYER_DEBUG") == "1":
        print(f"[sonex-player-debug] {message}", file=sys.stderr)


class PlaybackAdapter(Protocol):
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
    def __init__(
        self,
        *,
        source_url: str,
        source: PlaybackSource,
        metadata: dict[str, Any],
        diagnostic_time_source: Callable[[], float] = time.monotonic,
    ) -> None:
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

    def _request_with_client(self, client: socket.socket, command: list[Any]) -> Any:
        """Send one correlated command over an already connected mpv IPC client."""
        request_id = uuid.uuid4().int & ((1 << 63) - 1)
        payload = json.dumps({
            "command": command,
            "request_id": request_id,
        }).encode("utf-8") + b"\n"
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

    def _request(self, command: list[Any]) -> Any:
        if self.process and self.process.poll() is not None:
            raise RuntimeError("mpv process is not running.")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(1)
            client.connect(self.socket_path)
            return self._request_with_client(client, command)

    def _properties(self, names: tuple[str, ...]) -> dict[str, Any]:
        """Read one status snapshot while reusing a single mpv IPC connection."""
        if self.process and self.process.poll() is not None:
            error = RuntimeError("mpv process is not running.")
            return {name: error for name in names}
        results: dict[str, Any] = {}
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(1)
                client.connect(self.socket_path)
                for name in names:
                    try:
                        results[name] = self._request_with_client(
                            client,
                            ["get_property", name],
                        )
                    except Exception as exc:
                        results[name] = exc
        except Exception as exc:
            return {name: exc for name in names}
        return results

    @staticmethod
    def _snapshot_value(snapshot: dict[str, Any], name: str) -> Any:
        value = snapshot[name]
        if isinstance(value, Exception):
            raise value
        return value

    def _property(self, name: str) -> Any:
        return self._request(["get_property", name])

    def _diagnostic_probe(self) -> dict[str, Any]:
        """Read one high-frequency diagnostic sample from mpv."""
        snapshot = self._properties(
            ("time-pos", "pause", "paused-for-cache", "current-ao")
        )
        progress_ms = _coerce_ms(
            float(self._snapshot_value(snapshot, "time-pos") or 0) * 1000
        )
        paused = bool(self._snapshot_value(snapshot, "pause"))
        paused_for_cache = bool(
            self._snapshot_value(snapshot, "paused-for-cache")
        )
        current_ao_value = self._snapshot_value(snapshot, "current-ao")
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

        snapshot = self._properties(
            ("time-pos", "duration", "pause", "paused-for-cache", "current-ao")
        )
        try:
            progress_ms = _coerce_ms(
                float(self._snapshot_value(snapshot, "time-pos") or 0) * 1000
            )
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
            duration_ms = _coerce_ms(
                float(self._snapshot_value(snapshot, "duration") or 0) * 1000
            )
            self._last_duration_ms = duration_ms
        except Exception:
            duration_ms = self._last_duration_ms
        try:
            paused = bool(self._snapshot_value(snapshot, "pause"))
            is_playing = not paused
        except Exception:
            is_playing = bool(default_playing)
        try:
            paused_for_cache = bool(
                self._snapshot_value(snapshot, "paused-for-cache")
            )
        except Exception:
            paused_for_cache = False
        try:
            current_ao_value = self._snapshot_value(snapshot, "current-ao")
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
        self._request(["set_property", "pause", True])
        return self.status(default_playing=False)

    def resume(self) -> PlayerState:
        self._request(["set_property", "pause", False])
        return self.status(default_playing=True)

    def stop(self) -> PlayerState:
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
        volume = _coerce_volume(volume_percent)
        self._request(["set_property", "volume", volume])
        self.volume_percent = volume
        return self.status()


class LocalPlaybackController:
    def __init__(self) -> None:
        """Init for local playback controller.

        Coordinates the init method behavior while preserving local playback controller state and contracts.
        """
        self._adapter: PlaybackAdapter | None = None
        self.current_session_id: str | None = None

    def play(
        self,
        *,
        source_url: str,
        source: PlaybackSource,
        metadata: dict[str, Any],
        player: str | None = None,
    ) -> PlayerState:
        backend = self._normalize_backend(player or "auto")
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
        if normalized not in {"auto", "mpv"}:
            raise ValueError("Unsupported local playback backend. Sonex uses mpv.")
        return "mpv"

    def _adapter_for(
        self,
        backend: Literal["mpv"],
        *,
        source_url: str,
        source: PlaybackSource,
        metadata: dict[str, Any],
    ) -> PlaybackAdapter:
        return MpvPlaybackAdapter(source_url=source_url, source=source, metadata=metadata)

    def _start_adapter(
        self,
        *,
        backend: PlayerBackend,
        source_url: str,
        source: PlaybackSource,
        metadata: dict[str, Any],
    ) -> tuple[PlaybackAdapter, PlayerState]:
        adapter = self._adapter_for(
            "mpv",
            source_url=source_url,
            source=source,
            metadata=metadata,
        )
        try:
            return adapter, adapter.start()
        except Exception as exc:
            _player_debug(f"mpv start failed: {exc}")
            try:
                adapter.stop()
            except Exception:
                pass
            raise

    def _require_adapter(self) -> PlaybackAdapter:
        if self._adapter is None:
            raise RuntimeError("No active local playback session.")
        return self._adapter

    def pause(self) -> PlayerState:
        return self._require_adapter().pause()

    def resume(self) -> PlayerState:
        return self._require_adapter().resume()

    def status(self) -> PlayerState:
        state = self._require_adapter().status()
        if state.ended:
            self._adapter = None
            self.current_session_id = None
        return state

    def stop(self) -> PlayerState:
        adapter = self._require_adapter()
        state = adapter.stop()
        self._adapter = None
        self.current_session_id = None
        return state

    def set_volume(self, volume_percent: int) -> PlayerState:
        return self._require_adapter().set_volume(_coerce_volume(volume_percent))


controller = LocalPlaybackController()


def resolve_local_playback_backend(player: str = "auto") -> PlayerBackend:
    """Normalize every supported local or online playback request to mpv."""
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
    result = ToolResult.success(tool=tool, message=success_message, data=state.to_dict()).to_dict()
    if source == "youtube":
        from src.tools.youtube_runtime import mark_runtime_success_for_playback

        mark_runtime_success_for_playback(metadata)
    return result


def _control_result(tool: str, action: str) -> dict[str, Any]:
    messages = {
        "pause": "Playback paused.",
        "resume": "Playback resumed.",
        "stop": "Playback stopped.",
        "status": "Playback status.",
    }
    try:
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


for name, description, fn in (
    ("local_playback_pause", "Pause the current local playback session.", local_playback_pause),
    ("local_playback_resume", "Resume the current local playback session.", local_playback_resume),
    ("local_playback_stop", "Stop the current local playback session.", local_playback_stop),
    ("local_playback_status", "Return current local playback progress.", local_playback_status),
):
    registry.register(
        name=name,
        kind="system",
        domain="playback",
        description=description,
        parameters=Params(type="object", properties={}, required=[]),
        fn=fn,
        enable=True,
        read_only=False,
        required_confirm=False,
    )

registry.register(
    name="local_playback_volume",
    kind="system",
    domain="playback",
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
