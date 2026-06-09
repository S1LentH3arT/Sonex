"""Playback controller support for tool implementations used by the planner and playback flows.

Implements the playback_controller module responsibilities used by Sonex runtime flows.
Key public entry points include PlayerState, PlaybackAdapter, MpvPlaybackAdapter, CvlcRcPlaybackAdapter, LocalPlaybackController.
"""

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
    """Timestamp ms.

    Coordinates timestamp ms logic for the surrounding Sonex flow.

    Returns:
        The computed result for timestamp ms.
    """
    return int(time.time() * 1000)


def _player_debug(message: str) -> None:
    """Player debug.

    Coordinates player debug logic for the surrounding Sonex flow.

    Args:
        message: Input value used by the player debug operation.

    Returns:
        The computed result for player debug.
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
    id: str | None = None
    uri: str | None = None
    url: str | None = None
    stream_url: str | None = None
    album_cover_url: str | None = None
    volume_percent: int | None = None
    ended: bool = False

    def to_dict(self) -> dict[str, Any]:
        """To dict for player state.

        Coordinates the to dict method behavior while preserving player state state and contracts.

        Returns:
            The computed result for to dict.
        """
        return asdict(self)


def _coerce_ms(value: Any) -> int:
    """Coerce ms.

    Coordinates coerce ms logic for the surrounding Sonex flow.

    Args:
        value: Input value used by the coerce ms operation.

    Returns:
        The computed result for coerce ms.
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
    volume_percent: int | None = None,
    ended: bool = False,
) -> PlayerState:
    """Metadata state.

    Coordinates metadata state logic for the surrounding Sonex flow.

    Args:
        metadata: Input value used by the metadata state operation.
        source: Input value used by the metadata state operation.
        player: Input value used by the metadata state operation.
        session_id: Input value used by the metadata state operation.
        progress_ms: Input value used by the metadata state operation.
        duration_ms: Input value used by the metadata state operation.
        is_playing: Input value used by the metadata state operation.
        volume_percent: Input value used by the metadata state operation.
        ended: Input value used by the metadata state operation.

    Returns:
        The computed result for metadata state.
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
        uri=metadata.get("uri"),
        url=metadata.get("url"),
        stream_url=metadata.get("stream_url"),
        album_cover_url=metadata.get("album_cover_url") or metadata.get("cover_url"),
        volume_percent=volume_percent,
        ended=ended,
    )


def _coerce_volume(value: Any) -> int:
    """Coerce volume.

    Coordinates coerce volume logic for the surrounding Sonex flow.

    Args:
        value: Input value used by the coerce volume operation.

    Returns:
        The computed result for coerce volume.
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
    def __init__(self, *, source_url: str, source: PlaybackSource, metadata: dict[str, Any]) -> None:
        """Init for mpv playback adapter.

        Coordinates the init method behavior while preserving mpv playback adapter state and contracts.

        Args:
            source_url: Input value used by the init operation.
            source: Input value used by the init operation.
            metadata: Input value used by the init operation.
        """
        self.source_url = source_url
        self.source = source
        self.metadata = metadata
        self.session_id = uuid.uuid4().hex
        self.socket_path = str(Path(tempfile.gettempdir()) / f"sonex-mpv-{self.session_id}.sock")
        self.process: subprocess.Popen[bytes] | None = None
        self.volume_percent: int | None = None

    def start(self) -> PlayerState:
        """Start for mpv playback adapter.

        Coordinates the start method behavior while preserving mpv playback adapter state and contracts.

        Returns:
            The computed result for start.
        """
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
        """Request for mpv playback adapter.

        Coordinates the request method behavior while preserving mpv playback adapter state and contracts.

        Args:
            command: Input value used by the request operation.

        Returns:
            The computed result for request.
        """
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
        """Property for mpv playback adapter.

        Coordinates the property method behavior while preserving mpv playback adapter state and contracts.

        Args:
            name: Input value used by the property operation.

        Returns:
            The computed result for property.
        """
        return self._request(["get_property", name])

    def status(self, *, default_playing: bool | None = None) -> PlayerState:
        """Status for mpv playback adapter.

        Coordinates the status method behavior while preserving mpv playback adapter state and contracts.

        Args:
            default_playing: Input value used by the status operation.

        Returns:
            The computed result for status.
        """
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
        """Pause for mpv playback adapter.

        Coordinates the pause method behavior while preserving mpv playback adapter state and contracts.

        Returns:
            The computed result for pause.
        """
        self._request(["set_property", "pause", True])
        return self.status(default_playing=False)

    def resume(self) -> PlayerState:
        """Resume for mpv playback adapter.

        Coordinates the resume method behavior while preserving mpv playback adapter state and contracts.

        Returns:
            The computed result for resume.
        """
        self._request(["set_property", "pause", False])
        return self.status(default_playing=True)

    def stop(self) -> PlayerState:
        """Stop for mpv playback adapter.

        Coordinates the stop method behavior while preserving mpv playback adapter state and contracts.

        Returns:
            The computed result for stop.
        """
        try:
            self._request(["quit"])
        except Exception:
            if self.process and self.process.poll() is None:
                self.process.terminate()
        return replace(self.status(default_playing=False), is_playing=False, ended=True)

    def set_volume(self, volume_percent: int) -> PlayerState:
        """Set volume for mpv playback adapter.

        Coordinates the set volume method behavior while preserving mpv playback adapter state and contracts.

        Args:
            volume_percent: Input value used by the set volume operation.

        Returns:
            The computed result for set volume.
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
        """Init for cvlc rc playback adapter.

        Coordinates the init method behavior while preserving cvlc rc playback adapter state and contracts.

        Args:
            source_url: Input value used by the init operation.
            source: Input value used by the init operation.
            metadata: Input value used by the init operation.
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
        """Start for cvlc rc playback adapter.

        Coordinates the start method behavior while preserving cvlc rc playback adapter state and contracts.

        Returns:
            The computed result for start.
        """
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
        """Send for cvlc rc playback adapter.

        Coordinates the send method behavior while preserving cvlc rc playback adapter state and contracts.

        Args:
            command: Input value used by the send operation.

        Returns:
            The computed result for send.
        """
        if self.process and self.process.poll() is not None:
            raise RuntimeError("cvlc process is not running.")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(1)
            client.connect(self.socket_path)
            client.sendall(command.encode("utf-8") + b"\n")

    def status(self) -> PlayerState:
        """Status for cvlc rc playback adapter.

        Coordinates the status method behavior while preserving cvlc rc playback adapter state and contracts.

        Returns:
            The computed result for status.
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
        """Pause for cvlc rc playback adapter.

        Coordinates the pause method behavior while preserving cvlc rc playback adapter state and contracts.

        Returns:
            The computed result for pause.
        """
        self._send("pause")
        self.progress_ms = self.status().progress_ms
        self.is_playing = False
        return self.status()

    def resume(self) -> PlayerState:
        """Resume for cvlc rc playback adapter.

        Coordinates the resume method behavior while preserving cvlc rc playback adapter state and contracts.

        Returns:
            The computed result for resume.
        """
        self._send("play")
        self.started_at = _timestamp_ms()
        self.is_playing = True
        return self.status()

    def stop(self) -> PlayerState:
        """Stop for cvlc rc playback adapter.

        Coordinates the stop method behavior while preserving cvlc rc playback adapter state and contracts.

        Returns:
            The computed result for stop.
        """
        try:
            self._send("stop")
            self._send("quit")
        except Exception:
            if self.process and self.process.poll() is None:
                self.process.terminate()
        return replace(self.status(), is_playing=False, ended=True)

    def set_volume(self, volume_percent: int) -> PlayerState:
        """Set volume for cvlc rc playback adapter.

        Coordinates the set volume method behavior while preserving cvlc rc playback adapter state and contracts.

        Args:
            volume_percent: Input value used by the set volume operation.

        Returns:
            The computed result for set volume.
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
        """Play for local playback controller.

        Coordinates the play method behavior while preserving local playback controller state and contracts.

        Args:
            source_url: Input value used by the play operation.
            source: Input value used by the play operation.
            metadata: Input value used by the play operation.
            player: Input value used by the play operation.

        Returns:
            The computed result for play.
        """
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
        """Normalize backend for local playback controller.

        Coordinates the normalize backend method behavior while preserving local playback controller state and contracts.

        Args:
            backend: Input value used by the normalize backend operation.

        Returns:
            The computed result for normalize backend.
        """
        normalized = backend.strip().lower()
        if normalized not in {"auto", "mpv", "cvlc"}:
            raise ValueError("Unsupported local playback backend. Use auto, mpv, or cvlc.")
        return normalized  # type: ignore[return-value]

    def set_player_backend(self, backend: str) -> PlayerBackend:
        """Set player backend for local playback controller.

        Coordinates the set player backend method behavior while preserving local playback controller state and contracts.

        Args:
            backend: Input value used by the set player backend operation.

        Returns:
            The computed result for set player backend.
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
        """Adapter for for local playback controller.

        Coordinates the adapter for method behavior while preserving local playback controller state and contracts.

        Args:
            backend: Input value used by the adapter for operation.
            source_url: Input value used by the adapter for operation.
            source: Input value used by the adapter for operation.
            metadata: Input value used by the adapter for operation.

        Returns:
            The computed result for adapter for.
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
        """Start adapter for local playback controller.

        Coordinates the start adapter method behavior while preserving local playback controller state and contracts.

        Args:
            backend: Input value used by the start adapter operation.
            source_url: Input value used by the start adapter operation.
            source: Input value used by the start adapter operation.
            metadata: Input value used by the start adapter operation.

        Returns:
            The computed result for start adapter.
        """
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
        """Require adapter for local playback controller.

        Coordinates the require adapter method behavior while preserving local playback controller state and contracts.

        Returns:
            The computed result for require adapter.
        """
        if self._adapter is None:
            raise RuntimeError("No active local playback session.")
        return self._adapter

    def pause(self) -> PlayerState:
        """Pause for local playback controller.

        Coordinates the pause method behavior while preserving local playback controller state and contracts.

        Returns:
            The computed result for pause.
        """
        return self._require_adapter().pause()

    def resume(self) -> PlayerState:
        """Resume for local playback controller.

        Coordinates the resume method behavior while preserving local playback controller state and contracts.

        Returns:
            The computed result for resume.
        """
        return self._require_adapter().resume()

    def status(self) -> PlayerState:
        """Status for local playback controller.

        Coordinates the status method behavior while preserving local playback controller state and contracts.

        Returns:
            The computed result for status.
        """
        return self._require_adapter().status()

    def stop(self) -> PlayerState:
        """Stop for local playback controller.

        Coordinates the stop method behavior while preserving local playback controller state and contracts.

        Returns:
            The computed result for stop.
        """
        adapter = self._require_adapter()
        state = adapter.stop()
        self._adapter = None
        self.current_session_id = None
        return state

    def set_volume(self, volume_percent: int) -> PlayerState:
        """Set volume for local playback controller.

        Coordinates the set volume method behavior while preserving local playback controller state and contracts.

        Args:
            volume_percent: Input value used by the set volume operation.

        Returns:
            The computed result for set volume.
        """
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
    """Start local playback.

    Coordinates start local playback logic for the surrounding Sonex flow.

    Args:
        tool: Input value used by the start local playback operation.
        source_url: Input value used by the start local playback operation.
        source: Input value used by the start local playback operation.
        metadata: Input value used by the start local playback operation.
        player: Input value used by the start local playback operation.
        success_message: Input value used by the start local playback operation.

    Returns:
        The computed result for start local playback.
    """
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
    """Control result.

    Coordinates control result logic for the surrounding Sonex flow.

    Args:
        tool: Input value used by the control result operation.
        action: Input value used by the control result operation.

    Returns:
        The computed result for control result.
    """
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
    """Local playback pause.

    Coordinates local playback pause logic for the surrounding Sonex flow.

    Returns:
        The computed result for local playback pause.
    """
    return _control_result("local_playback_pause", "pause")


def local_playback_resume() -> dict[str, Any]:
    """Local playback resume.

    Coordinates local playback resume logic for the surrounding Sonex flow.

    Returns:
        The computed result for local playback resume.
    """
    return _control_result("local_playback_resume", "resume")


def local_playback_stop() -> dict[str, Any]:
    """Local playback stop.

    Coordinates local playback stop logic for the surrounding Sonex flow.

    Returns:
        The computed result for local playback stop.
    """
    return _control_result("local_playback_stop", "stop")


def local_playback_status() -> dict[str, Any]:
    """Local playback status.

    Coordinates local playback status logic for the surrounding Sonex flow.

    Returns:
        The computed result for local playback status.
    """
    return _control_result("local_playback_status", "status")


def local_playback_volume(volume_percent: int) -> dict[str, Any]:
    """Local playback volume.

    Coordinates local playback volume logic for the surrounding Sonex flow.

    Args:
        volume_percent: Input value used by the local playback volume operation.

    Returns:
        The computed result for local playback volume.
    """
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
    """Local playback player.

    Coordinates local playback player logic for the surrounding Sonex flow.

    Args:
        backend: Input value used by the local playback player operation.

    Returns:
        The computed result for local playback player.
    """
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
