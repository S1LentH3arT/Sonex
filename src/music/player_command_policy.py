"""Pure command construction for supported external Player Sinks."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Callable


WhichExecutable = Callable[[str], str | None]


def application_command(
    target: str,
    *arguments: str,
    flatpak_executable: str | None,
) -> tuple[str, ...]:
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
    flatpak_executable: str | None,
    which: WhichExecutable,
    desktop_executables: Mapping[str, str],
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
    target: str,
    action: str,
    value: int | None,
    *,
    flatpak_executable: str | None,
) -> tuple[str, ...] | None:
    if action == "volume" and value is not None:
        return application_command(target, "--volume", str(value), flatpak_executable=flatpak_executable)
    flag = {"pause": "--pause", "resume": "--play", "stop": "--stop"}.get(action)
    return application_command(target, flag, flatpak_executable=flatpak_executable) if flag else None


def rhythmbox_control(
    target: str,
    action: str,
    value: int | None,
    *,
    flatpak_executable: str | None,
) -> tuple[str, ...] | None:
    if action == "volume" and value is not None:
        return application_command(
            target,
            "--set-volume",
            str(value / 100),
            flatpak_executable=flatpak_executable,
        )
    flag = {"pause": "--pause", "resume": "--play", "stop": "--stop"}.get(action)
    return application_command(target, flag, flatpak_executable=flatpak_executable) if flag else None


def audacious_control(
    target: str,
    action: str,
    value: int | None,
    *,
    flatpak_executable: str | None,
    which: WhichExecutable,
    desktop_executables: Mapping[str, str],
) -> tuple[str, ...] | None:
    if action == "volume" and value is not None:
        return helper_command(
            target,
            "audtool",
            "set-volume",
            str(value),
            flatpak_executable=flatpak_executable,
            which=which,
            desktop_executables=desktop_executables,
        )
    command = {
        "pause": "playback-pause",
        "resume": "playback-play",
        "stop": "playback-stop",
    }.get(action)
    return (
        helper_command(
            target,
            "audtool",
            command,
            flatpak_executable=flatpak_executable,
            which=which,
            desktop_executables=desktop_executables,
        )
        if command
        else None
    )
