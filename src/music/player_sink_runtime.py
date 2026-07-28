"""Composition root for Player Sink discovery and playback routing."""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import threading
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, TypeVar
from urllib.parse import unquote, urlparse

from src.music.mpris import DbusNextMprisClient, _silent_probe_uri
from src.music.player_sink_adapters import (
    CommandPlayerSinkAdapter,
    ManagedPlayerSinkAdapter,
    discover_mpris_adapters,
)
from src.music.player_sinks import (
    PlayerAsset,
    PlayerSinkAdapter,
    PlayerSinkManager,
    PlayerSinkPlayback,
)
from src.log import sonex_home

_ACTIVE_SINK_STATES: dict[str, dict[str, object]] = {}
_T = TypeVar("_T")


def _run_coroutine_sync(factory: Callable[[], Awaitable[_T]]) -> _T:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(factory())

    result: dict[str, _T] = {}
    error: list[BaseException] = []

    def run() -> None:
        try:
            result["value"] = asyncio.run(factory())
        except BaseException as exc:
            error.append(exc)

    worker = threading.Thread(target=run, name="sonex-player-sink", daemon=True)
    worker.start()
    worker.join()
    if error:
        raise error[0]
    return result["value"]


def _launch(command: tuple[str, ...]) -> None:
    subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def _process_running(executable: str) -> bool:
    target = executable.casefold()
    proc = Path("/proc")
    if not proc.is_dir():
        return False
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            name = (entry / "comm").read_text(encoding="utf-8").strip().casefold()
        except OSError:
            continue
        if name == target:
            return True
    return False


def _source_url(uri: str) -> str:
    parsed = urlparse(uri)
    if parsed.scheme == "file":
        return unquote(parsed.path)
    return uri


def _managed_play(backend: str, uri: str, track: dict[str, object]) -> dict[str, object]:
    from src.tools.playback_controller import controller

    source = str(track.get("source") or track.get("provider") or "local")
    if source not in {"local", "youtube", "spotify", "apple_music"}:
        source = "youtube"
    state = controller.play(
        source_url=_source_url(uri),
        source=source,  # type: ignore[arg-type]
        metadata=track,
        player=backend,
    )
    return state.to_dict()


def _managed_control(
    backend: str,
    action: str,
    value: int | None,
) -> dict[str, object]:
    from src.tools.playback_controller import controller

    if action == "volume":
        if value is None:
            raise ValueError("Volume must be an integer from 0 to 100.")
        state = controller.set_volume(value)
    else:
        method = {
            "pause": controller.pause,
            "resume": controller.resume,
            "stop": controller.stop,
            "status": controller.status,
        }.get(action)
        if method is None:
            raise ValueError(f"Unsupported player control: {action}.")
        state = method()
    if state.player != backend:
        raise RuntimeError(f"The active playback session does not belong to {backend}.")
    return state.to_dict()


def _validate_managed_player(backend: str) -> bool:
    from src.tools.playback_controller import controller

    try:
        state = controller.play(
            source_url=_source_url(_silent_probe_uri()),
            source="local",
            metadata={"name": "Sonex player validation", "provider": "local"},
            player=backend,
        )
        valid = state.player == backend and state.is_playing
        controller.stop()
    except Exception:
        return False
    return valid


def _validate_known_player(adapter_id: str, which: Callable[[str], str | None]) -> bool:
    probe_uri = _silent_probe_uri()
    commands: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {}
    if executable := which("clementine"):
        commands["mpris:clementine"] = (
            (executable, "--load", probe_uri),
            (executable, "--stop"),
        )
    if executable := which("rhythmbox-client"):
        commands["mpris:rhythmbox"] = (
            (executable, "--play-uri", probe_uri),
            (executable, "--stop"),
        )
    if executable := which("audacious"):
        stop = which("audtool")
        commands["mpris:audacious"] = (
            (executable, probe_uri),
            (stop, "playback-stop") if stop else (),
        )
    pair = commands.get(adapter_id)
    if pair is None:
        return False
    play_command, stop_command = pair
    try:
        process = subprocess.Popen(
            play_command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        deadline = time.monotonic() + 1
        while process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        accepted = process.poll() in {None, 0}
        if stop_command:
            subprocess.run(
                stop_command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=2,
                check=False,
            )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return accepted


def build_player_sink_manager(
    *,
    preferences_path: Path | None = None,
    available_managed: tuple[dict[str, str], ...] | None = None,
    which: Callable[[str], str | None] = shutil.which,
    launch: Callable[[tuple[str, ...]], None] = _launch,
    is_process_running: Callable[[str], bool] = _process_running,
    validate_command_player: Callable[[str], bool] | None = None,
    discover_mpris: Callable[[], Awaitable[tuple[PlayerSinkAdapter, ...]]] | None = None,
) -> PlayerSinkManager:
    """Build the device-persistent manager without scanning or launching players."""
    if available_managed is None:
        from src.tools.playback_controller import available_local_playback_backends

        available_managed = tuple(available_local_playback_backends())

    managed_paths = {
        str(item["backend"]): str(item["executable"])
        for item in available_managed
        if item.get("backend") and item.get("executable")
    }

    def managed_which(executable: str) -> str | None:
        if executable == "vlc":
            return managed_paths.get("cvlc")
        return managed_paths.get(executable)

    adapters: list[PlayerSinkAdapter] = []
    if "mpv" in managed_paths:
        adapters.append(
            ManagedPlayerSinkAdapter(
                backend="mpv",
                display_name="mpv",
                executable_names=("mpv",),
                which=managed_which,
                play_managed=_managed_play,
                validate_managed=_validate_managed_player,
                control_managed=_managed_control,
            )
        )
    if "cvlc" in managed_paths:
        adapters.append(
            ManagedPlayerSinkAdapter(
                backend="cvlc",
                display_name="VLC",
                executable_names=("cvlc", "vlc"),
                which=managed_which,
                play_managed=_managed_play,
                validate_managed=_validate_managed_player,
                control_managed=_managed_control,
            )
        )

    validator = validate_command_player or (
        lambda adapter_id: _validate_known_player(adapter_id, which)
    )

    def clementine_control(
        executable: str,
        action: str,
        value: int | None,
    ) -> tuple[str, ...] | None:
        if action == "volume" and value is not None:
            return executable, "--volume", str(value)
        flag = {"pause": "--pause", "resume": "--play", "stop": "--stop"}.get(action)
        return (executable, flag) if flag else None

    def rhythmbox_control(
        executable: str,
        action: str,
        value: int | None,
    ) -> tuple[str, ...] | None:
        if action == "volume" and value is not None:
            return executable, "--set-volume", str(value / 100)
        flag = {"pause": "--pause", "resume": "--play", "stop": "--stop"}.get(action)
        return (executable, flag) if flag else None

    def audacious_control(
        _executable: str,
        action: str,
        value: int | None,
    ) -> tuple[str, ...] | None:
        audtool = which("audtool")
        if audtool is None:
            return None
        if action == "volume" and value is not None:
            return audtool, "set-volume", str(value)
        command = {
            "pause": "playback-pause",
            "resume": "playback-play",
            "stop": "playback-stop",
        }.get(action)
        return (audtool, command) if command else None

    known = (
        (
            "mpris:clementine",
            "Clementine",
            ("clementine",),
            lambda executable, uri: (executable, "--load", uri),
            "clementine",
            clementine_control,
        ),
        (
            "mpris:rhythmbox",
            "Rhythmbox",
            ("rhythmbox-client",),
            lambda executable, uri: (executable, "--play-uri", uri),
            "rhythmbox",
            rhythmbox_control,
        ),
        (
            "mpris:audacious",
            "Audacious",
            ("audacious",),
            lambda executable, uri: (executable, uri),
            "audacious",
            audacious_control,
        ),
    )
    for (
        sink_id,
        display_name,
        executables,
        command_builder,
        process_name,
        control_builder,
    ) in known:
        if not any(which(executable) for executable in executables):
            continue
        adapters.append(
            CommandPlayerSinkAdapter(
                sink_id=sink_id,
                display_name=display_name,
                description="External player controlled by its supported interface.",
                executable_names=executables,
                build_play_command=command_builder,
                which=which,
                launch=launch,
                is_active=lambda name=process_name: is_process_running(name),
                validate_injection=lambda adapter_id=sink_id: validator(adapter_id),
                build_control_command=control_builder,
            )
        )

    if discover_mpris is None:
        client = DbusNextMprisClient()
        discover_mpris = lambda: discover_mpris_adapters(client)
    return PlayerSinkManager(
        adapters=tuple(adapters),
        adapter_discovery=discover_mpris,
        preferences_path=preferences_path,
    )


async def play_through_player_sink(
    manager: PlayerSinkManager,
    *,
    source_url: str,
    track: dict[str, object],
) -> PlayerSinkPlayback:
    parsed = urlparse(source_url)
    if parsed.scheme in {"http", "https"}:
        asset = PlayerAsset(kind="public_http", uri=source_url)
    else:
        path = Path(source_url).expanduser().resolve()
        asset = PlayerAsset(kind="file_uri", uri=path.as_uri())
    return await manager.play(asset, track)


def play_through_persisted_sink(
    *,
    source_url: str,
    track: dict[str, object],
) -> PlayerSinkPlayback | None:
    """Route sync tool playback when a persisted Player Sink default exists."""
    manager = build_player_sink_manager()
    if manager.default_sink_id is None and manager.pending_sink_id is None:
        return None
    playback = _run_coroutine_sync(
        lambda: play_through_player_sink(
            manager,
            source_url=source_url,
            track=track,
        )
    )
    _ACTIVE_SINK_STATES[playback.sink_id] = dict(playback.state)
    return playback


def has_persisted_player_sink(preferences_path: Path | None = None) -> bool:
    path = preferences_path or sonex_home() / "music" / "player-preferences.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return False
    return bool(
        isinstance(payload, dict)
        and payload.get("version") == 1
        and (
            isinstance(payload.get("default_sink_id"), str)
            or isinstance(payload.get("pending_sink_id"), str)
        )
    )


def control_persisted_player_sink(
    action: str,
    value: int | None = None,
) -> PlayerSinkPlayback | None:
    manager = build_player_sink_manager()
    if manager.default_sink_id is None:
        return None
    playback = _run_coroutine_sync(lambda: manager.control(action, value))
    previous = _ACTIVE_SINK_STATES.get(playback.sink_id, {})
    merged = {**previous, **playback.state}
    if action == "stop":
        merged["ended"] = True
        merged["is_playing"] = False
    _ACTIVE_SINK_STATES[playback.sink_id] = merged
    return PlayerSinkPlayback(sink_id=playback.sink_id, state=merged)
