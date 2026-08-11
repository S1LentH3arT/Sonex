"""Controlled Provider Worker boundary for the installed NetEase ``ncm-cli``."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence


SUPPORTED_NCM_CLI_VERSIONS = frozenset({"0.1.6"})
MAX_OUTPUT_BYTES = 256 * 1024
DEFAULT_TIMEOUT_SECONDS = 4.0
PLAY_TIMEOUT_SECONDS = 6.0


@dataclass(frozen=True)
class NetEaseWorkerHealth:
    ready: bool
    version: str | None
    login_ready: bool
    config_writable: bool
    mpv_ready: bool
    reason: str | None = None


RunCommand = Callable[..., subprocess.CompletedProcess[str]]


class NetEaseProviderWorker:
    """Invoke a narrow ncm-cli argv allowlist without exposing a shell."""

    def __init__(
        self,
        *,
        executable: str | None = None,
        config_dir: Path | None = None,
        run_command: RunCommand = subprocess.run,
    ) -> None:
        self.executable = executable or shutil.which("ncm-cli")
        self.config_dir = config_dir or Path.home() / ".config" / "ncm-cli"
        self._run_command = run_command
        self._process_lock = threading.Lock()
        self._active_process: subprocess.Popen[str] | None = None

    def _environment(self) -> dict[str, str]:
        allowed = ("HOME", "PATH", "XDG_CONFIG_HOME", "LANG", "LC_ALL")
        return {key: os.environ[key] for key in allowed if key in os.environ}

    def _run(
        self,
        arguments: Sequence[str],
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> subprocess.CompletedProcess[str]:
        if self.executable is None:
            raise RuntimeError("ncm-cli is not installed.")
        argv = [self.executable, *arguments]
        if self._run_command is subprocess.run:
            process = subprocess.Popen(
                argv,
                shell=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=self._environment(),
            )
            with self._process_lock:
                self._active_process = process
            try:
                stdout, stderr = process.communicate(timeout=timeout_seconds)
            except subprocess.TimeoutExpired:
                process.kill()
                stdout, stderr = process.communicate()
                raise RuntimeError("ncm-cli timed out.") from None
            finally:
                with self._process_lock:
                    if self._active_process is process:
                        self._active_process = None
            completed = subprocess.CompletedProcess(
                argv,
                process.returncode,
                stdout,
                stderr,
            )
        else:
            completed = self._run_command(
                argv,
                shell=False,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                env=self._environment(),
            )
        if len(completed.stdout.encode("utf-8", errors="replace")) > MAX_OUTPUT_BYTES:
            raise RuntimeError("ncm-cli output exceeded the safety limit.")
        if len(completed.stderr.encode("utf-8", errors="replace")) > MAX_OUTPUT_BYTES:
            raise RuntimeError("ncm-cli error output exceeded the safety limit.")
        return completed

    def terminate_active(self) -> bool:
        """Terminate the currently controlled ncm-cli child, if any."""
        with self._process_lock:
            process = self._active_process
        if process is None or process.poll() is not None:
            return False
        process.terminate()
        return True

    def health(self) -> NetEaseWorkerHealth:
        if self.executable is None:
            return NetEaseWorkerHealth(False, None, False, False, False, "ncm-cli is not installed.")
        version_result = self._run(("--version",))
        version_match = re.search(r"(\d+\.\d+\.\d+)", version_result.stdout)
        version = version_match.group(1) if version_match else None
        config_writable = (
            self.config_dir.is_dir()
            and os.access(self.config_dir, os.R_OK | os.W_OK)
        )
        mpv_ready = shutil.which("mpv") is not None
        if version not in SUPPORTED_NCM_CLI_VERSIONS:
            return NetEaseWorkerHealth(False, version, False, config_writable, mpv_ready, "Unsupported ncm-cli version.")
        if not config_writable:
            return NetEaseWorkerHealth(False, version, False, False, mpv_ready, "The ncm-cli config directory is not readable and writable.")
        login_result = self._run(("login", "--check"))
        login_ready = _login_check_succeeded(login_result)
        if not login_ready:
            return NetEaseWorkerHealth(
                False,
                version,
                False,
                True,
                mpv_ready,
                "Run ncm-cli login and ensure mpv is installed.",
            )
        commands_result = self._run(("commands",))
        search_ready = (
            commands_result.returncode == 0
            and _command_is_available(commands_result.stdout, "search")
        )
        if not search_ready:
            return NetEaseWorkerHealth(
                False,
                version,
                True,
                True,
                mpv_ready,
                (
                    "ncm-cli catalog search is unavailable. "
                    "Sign in again or repair the ncm-cli command manifest."
                ),
            )
        ready = mpv_ready
        reason = None if ready else "Install mpv before using ncm-cli playback."
        return NetEaseWorkerHealth(ready, version, login_ready, True, mpv_ready, reason)

    def search(self, query: str, *, limit: int = 10) -> list[dict[str, Any]]:
        bounded = min(20, max(1, int(limit)))
        result = self._run(("search", "song", "--keyword", query))
        if not _command_succeeded(result):
            raise RuntimeError("NetEase catalog search failed.")
        payload = _parse_json_output(result.stdout)
        raw_items = payload.get("songs") or payload.get("items") or payload.get("data") or []
        if isinstance(raw_items, dict):
            raw_items = raw_items.get("songs") or raw_items.get("items") or []
        if not isinstance(raw_items, list):
            raise RuntimeError("NetEase catalog returned an unsupported schema.")
        return [_normalize_song(item) for item in raw_items[:bounded] if isinstance(item, dict)]

    def play(self, *, encrypted_id: str, original_id: str) -> dict[str, Any]:
        result = self._run(
            (
                "play",
                "--song",
                "--encrypted-id",
                encrypted_id,
                "--original-id",
                original_id,
            ),
            timeout_seconds=PLAY_TIMEOUT_SECONDS,
        )
        if not _command_succeeded(result):
            raise RuntimeError("NetEase playback failed.")
        return {
            "status": "success",
            "provider": "NetEase",
            "player": "ncm-cli/mpv",
        }

    def state(self) -> dict[str, Any]:
        result = self._run(("state",))
        if not _command_succeeded(result):
            raise RuntimeError("NetEase playback state is unavailable.")
        return _parse_json_output(result.stdout)

    def control(self, command: str) -> None:
        normalized = command.strip().casefold()
        allowed = {"pause", "resume", "stop", "prev", "next"}
        if normalized not in allowed:
            raise ValueError("Unsupported NetEase playback control.")
        result = self._run((normalized,))
        if not _command_succeeded(result):
            raise RuntimeError(f"NetEase {normalized} failed.")


def _parse_json_output(output: str) -> dict[str, Any]:
    stripped = output.strip()
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        starts = [index for index, char in enumerate(stripped) if char in "[{"]
        payload = None
        for start in reversed(starts):
            try:
                payload = json.loads(stripped[start:])
                break
            except json.JSONDecodeError:
                continue
        if payload is None:
            raise RuntimeError("ncm-cli did not return JSON output.") from None
    if isinstance(payload, list):
        return {"items": payload}
    if not isinstance(payload, dict):
        raise RuntimeError("ncm-cli returned an unsupported JSON value.")
    return payload


def _login_check_succeeded(result: subprocess.CompletedProcess[str]) -> bool:
    return _command_succeeded(result)


def _command_succeeded(result: subprocess.CompletedProcess[str]) -> bool:
    if result.returncode != 0:
        return False
    try:
        payload = _parse_json_output(result.stdout)
    except RuntimeError:
        return True
    success = payload.get("success")
    return bool(success) if isinstance(success, bool) else True


def _command_is_available(output: str, command: str) -> bool:
    expected = command.strip().casefold()
    return any(
        line.strip().split(maxsplit=1)[0].casefold() == expected
        for line in output.splitlines()
        if line.strip()
    )


def _normalize_song(item: dict[str, Any]) -> dict[str, Any]:
    encrypted_id = item.get("encryptedId") or item.get("encrypted_id")
    original_id = item.get("originalId") or item.get("original_id") or item.get("id")
    artist = item.get("artist") or item.get("artistName")
    if not artist and isinstance(item.get("artists"), list):
        artist = ", ".join(
            str(value.get("name") if isinstance(value, dict) else value)
            for value in item["artists"]
        )
    return {
        "provider": "netease",
        "id": f"{encrypted_id or ''}|{original_id or ''}",
        "title": item.get("name") or item.get("title"),
        "artist": artist,
        "album": (
            item.get("album", {}).get("name")
            if isinstance(item.get("album"), dict)
            else item.get("album")
        ),
        "duration_ms": item.get("duration") or item.get("duration_ms"),
        "encrypted_id": str(encrypted_id or ""),
        "original_id": str(original_id or ""),
    }
