"""Composition root for Player Sink discovery and playback routing."""

from __future__ import annotations

import asyncio
import json
import os
import shlex
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
_RUNTIME_MANAGER: PlayerSinkManager | None = None
_RUNTIME_PREFERENCES_PATH: Path | None = None
_RUNTIME_PREFERENCES_REVISION: bytes | None = None
_RUNTIME_MANAGER_LOCK = threading.RLock()
_RUNTIME_OPERATION_LOCK = threading.Lock()
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
    if source not in {"local", "youtube", "spotify"}:
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


def _managed_player_active(backend: str) -> bool:
    from src.tools.playback_controller import controller

    if controller.current_session_id is None:
        return False
    try:
        state = controller.status()
    except Exception:
        return False
    return state.player == backend and not state.ended


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


def _validate_known_player(
    play_command: tuple[str, ...],
    stop_command: tuple[str, ...],
) -> bool:
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


def _discover_desktop_executables() -> dict[str, str]:
    """Read only trusted executable paths from desktop entries."""
    trusted_names = {"clementine", "rhythmbox-client", "audacious", "audtool"}
    data_home = Path(
        os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share"
    )
    data_dirs = [
        Path(item)
        for item in os.environ.get(
            "XDG_DATA_DIRS",
            "/usr/local/share:/usr/share",
        ).split(":")
        if item
    ]
    discovered: dict[str, str] = {}
    for directory in (data_home, *data_dirs):
        applications = directory / "applications"
        if not applications.is_dir():
            continue
        for entry in applications.glob("*.desktop"):
            try:
                lines = entry.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            exec_value = next(
                (line.removeprefix("Exec=").strip() for line in lines if line.startswith("Exec=")),
                "",
            )
            try:
                command = shlex.split(exec_value)
            except ValueError:
                continue
            if not command:
                continue
            executable = Path(command[0])
            name = executable.name
            if (
                name in trusted_names
                and executable.is_absolute()
                and executable.is_file()
                and os.access(executable, os.X_OK)
            ):
                discovered.setdefault(name, str(executable))
    return discovered


def _discover_flatpak_applications(
    flatpak_executable: str | None,
) -> frozenset[str]:
    if flatpak_executable is None:
        return frozenset()
    try:
        result = subprocess.run(
            (flatpak_executable, "list", "--app", "--columns=application"),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=1,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return frozenset()
    if result.returncode != 0:
        return frozenset()
    return frozenset(line.strip() for line in result.stdout.splitlines() if line.strip())


def build_player_sink_manager(
    *,
    preferences_path: Path | None = None,
    available_managed: tuple[dict[str, str], ...] | None = None,
    which: Callable[[str], str | None] = shutil.which,
    launch: Callable[[tuple[str, ...]], None] = _launch,
    is_process_running: Callable[[str], bool] = _process_running,
    validate_command_player: Callable[[str], bool] | None = None,
    discover_mpris: Callable[[], Awaitable[tuple[PlayerSinkAdapter, ...]]] | None = None,
    desktop_executables: dict[str, str] | None = None,
    flatpak_applications: frozenset[str] | None = None,
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
                is_active=_managed_player_active,
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
                is_active=_managed_player_active,
            )
        )

    inspect_host_installations = which is shutil.which
    if desktop_executables is None:
        desktop_executables = (
            _discover_desktop_executables() if inspect_host_installations else {}
        )
    flatpak_executable = which("flatpak")
    if flatpak_applications is None:
        flatpak_applications = (
            _discover_flatpak_applications(flatpak_executable)
            if inspect_host_installations
            else frozenset()
        )

    def application_command(target: str, *arguments: str) -> tuple[str, ...]:
        if target.startswith("flatpak:"):
            return (
                flatpak_executable or "flatpak",
                "run",
                target.removeprefix("flatpak:"),
                *arguments,
            )
        return target, *arguments

    def helper_command(
        target: str,
        helper: str,
        *arguments: str,
    ) -> tuple[str, ...] | None:
        if target.startswith("flatpak:"):
            return (
                flatpak_executable or "flatpak",
                "run",
                f"--command={helper}",
                target.removeprefix("flatpak:"),
                *arguments,
            )
        executable = which(helper) or desktop_executables.get(helper)
        return (executable, *arguments) if executable else None

    def clementine_control(
        executable: str,
        action: str,
        value: int | None,
    ) -> tuple[str, ...] | None:
        if action == "volume" and value is not None:
            return application_command(executable, "--volume", str(value))
        flag = {"pause": "--pause", "resume": "--play", "stop": "--stop"}.get(action)
        return application_command(executable, flag) if flag else None

    def rhythmbox_control(
        executable: str,
        action: str,
        value: int | None,
    ) -> tuple[str, ...] | None:
        if action == "volume" and value is not None:
            return application_command(executable, "--set-volume", str(value / 100))
        flag = {"pause": "--pause", "resume": "--play", "stop": "--stop"}.get(action)
        return application_command(executable, flag) if flag else None

    def audacious_control(
        _executable: str,
        action: str,
        value: int | None,
    ) -> tuple[str, ...] | None:
        if action == "volume" and value is not None:
            return helper_command(_executable, "audtool", "set-volume", str(value))
        command = {
            "pause": "playback-pause",
            "resume": "playback-play",
            "stop": "playback-stop",
        }.get(action)
        return helper_command(_executable, "audtool", command) if command else None

    known = (
        (
            "mpris:clementine",
            "Clementine",
            ("clementine",),
            lambda executable, uri: application_command(executable, "--load", uri),
            "clementine",
            clementine_control,
            "org.clementine_player.Clementine",
        ),
        (
            "mpris:rhythmbox",
            "Rhythmbox",
            ("rhythmbox-client",),
            lambda executable, uri: application_command(executable, "--play-uri", uri),
            "rhythmbox",
            rhythmbox_control,
            "org.gnome.Rhythmbox3",
        ),
        (
            "mpris:audacious",
            "Audacious",
            ("audacious",),
            lambda executable, uri: application_command(executable, uri),
            "audacious",
            audacious_control,
            "org.atheme.audacious",
        ),
    )
    for (
        sink_id,
        display_name,
        executables,
        command_builder,
        process_name,
        control_builder,
        flatpak_app_id,
    ) in known:
        target = next(
            (
                path
                for executable in executables
                if (path := which(executable) or desktop_executables.get(executable))
            ),
            None,
        )
        if target is None and flatpak_app_id in flatpak_applications:
            target = f"flatpak:{flatpak_app_id}"
        if target is None:
            continue
        adapter_which = lambda _executable, resolved=target: resolved
        can_control = (
            sink_id != "mpris:audacious"
            or target.startswith("flatpak:")
            or which("audtool") is not None
            or desktop_executables.get("audtool") is not None
        )
        if validate_command_player is not None:
            validate_injection = lambda adapter_id=sink_id: validate_command_player(
                adapter_id
            )
        else:
            validate_injection = lambda target=target, builder=command_builder, control=control_builder: _validate_known_player(
                builder(target, _silent_probe_uri()),
                control(target, "stop", None) or (),
            )
        adapters.append(
            CommandPlayerSinkAdapter(
                sink_id=sink_id,
                display_name=display_name,
                description="External player controlled by its supported interface.",
                executable_names=executables,
                build_play_command=command_builder,
                which=adapter_which,
                launch=launch,
                is_active=lambda name=process_name: is_process_running(name),
                validate_injection=validate_injection,
                build_control_command=control_builder,
                can_control=can_control,
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


def _player_preferences_path() -> Path:
    return sonex_home() / "music" / "player-preferences.json"


def _preferences_revision(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except OSError:
        return None


def _persisted_player_sink_manager() -> PlayerSinkManager:
    """Reuse adapter state until another process changes the preference record."""
    global _RUNTIME_MANAGER, _RUNTIME_PREFERENCES_PATH, _RUNTIME_PREFERENCES_REVISION

    path = _player_preferences_path()
    revision = _preferences_revision(path)
    with _RUNTIME_MANAGER_LOCK:
        if (
            _RUNTIME_MANAGER is None
            or path != _RUNTIME_PREFERENCES_PATH
            or revision != _RUNTIME_PREFERENCES_REVISION
        ):
            _RUNTIME_MANAGER = build_player_sink_manager(preferences_path=path)
            _RUNTIME_PREFERENCES_PATH = path
            _RUNTIME_PREFERENCES_REVISION = revision
        return _RUNTIME_MANAGER


def _remember_preferences_revision() -> None:
    global _RUNTIME_PREFERENCES_REVISION

    with _RUNTIME_MANAGER_LOCK:
        _RUNTIME_PREFERENCES_REVISION = _preferences_revision(_player_preferences_path())


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
    with _RUNTIME_OPERATION_LOCK:
        manager = _persisted_player_sink_manager()
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
        _remember_preferences_revision()
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
    with _RUNTIME_OPERATION_LOCK:
        manager = _persisted_player_sink_manager()
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
