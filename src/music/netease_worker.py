"""Controlled Provider Worker boundary for the installed NetEase ``ncm-cli``."""

from __future__ import annotations

import json
import os
import pty
import re
import select
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence


SUPPORTED_NCM_CLI_VERSIONS = frozenset({"0.1.6"})
MAX_OUTPUT_BYTES = 256 * 1024
DEFAULT_TIMEOUT_SECONDS = 4.0
PLAY_TIMEOUT_SECONDS = 6.0
PLAY_STATE_POLL_SECONDS = 0.2
PLAY_STATE_MAX_ATTEMPTS = 8
PLAY_STATE_STABLE_SAMPLES = 2
LOGIN_TIMEOUT_SECONDS = 120.0
LOGIN_POLL_SECONDS = 0.05
_LOGIN_ALLOWED_SGR_RE = re.compile(r"\x1b\[(?:0|40|47)m")
_TERMINAL_CONTROL_RE = re.compile(
    r"\x1b(?:\][^\x07\x1b]*(?:\x07|\x1b\\)|\[[0-?]*[ -/]*[@-~]|[()][0-2A-Z]|[=>78])"
)


@dataclass(frozen=True)
class NetEaseWorkerHealth:
    ready: bool
    version: str | None
    login_ready: bool
    config_writable: bool
    mpv_ready: bool
    reason: str | None = None
    credentials_ready: bool = False

    @property
    def login_available(self) -> bool:
        """Return whether Sonex can safely offer the QR login bridge."""
        return (
            self.version in SUPPORTED_NCM_CLI_VERSIONS
            and self.config_writable
            and self.credentials_ready
            and self.mpv_ready
        )


@dataclass(frozen=True)
class NetEaseLoginResult:
    status: str
    output: str
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
        allowed = (
            "HOME",
            "PATH",
            "XDG_CONFIG_HOME",
            "LANG",
            "LC_ALL",
            "XDG_RUNTIME_DIR",
            "PULSE_SERVER",
            "DBUS_SESSION_BUS_ADDRESS",
            "DISPLAY",
            "WAYLAND_DISPLAY",
            "PIPEWIRE_REMOTE",
        )
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

    def login(
        self,
        *,
        on_output: Callable[[str], None] | None = None,
        cancel_event: threading.Event | None = None,
        timeout_seconds: float = LOGIN_TIMEOUT_SECONDS,
    ) -> NetEaseLoginResult:
        """Bridge the interactive ncm-cli QR login through a bounded PTY."""
        if self.executable is None:
            return NetEaseLoginResult("failed", "", "ncm-cli is not installed.")
        master, slave = pty.openpty()
        process = subprocess.Popen(
            [self.executable, "login"],
            shell=False,
            stdin=slave,
            stdout=slave,
            stderr=slave,
            env=self._environment(),
            start_new_session=True,
        )
        os.close(slave)
        with self._process_lock:
            self._active_process = process
        started = time.monotonic()
        raw = bytearray()
        last_output = ""
        status = "failed"
        reason: str | None = None
        try:
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    process.terminate()
                    status = "cancelled"
                    break
                if time.monotonic() - started >= max(0.1, timeout_seconds):
                    process.terminate()
                    status = "timeout"
                    reason = "NetEase login timed out."
                    break
                readable, _, _ = select.select([master], [], [], LOGIN_POLL_SECONDS)
                if master in readable:
                    try:
                        chunk = os.read(master, 65536)
                    except OSError:
                        chunk = b""
                    if chunk:
                        raw.extend(chunk)
                        if len(raw) > MAX_OUTPUT_BYTES:
                            process.terminate()
                            reason = "ncm-cli login output exceeded the safety limit."
                            break
                        output = _sanitize_login_output(raw.decode("utf-8", errors="replace"))
                        if output != last_output:
                            last_output = output
                            if on_output is not None:
                                on_output(output)
                return_code = process.poll()
                if return_code is not None:
                    status = "success" if return_code == 0 else "failed"
                    if return_code != 0:
                        reason = "NetEase login failed."
                    break
        finally:
            if process.poll() is None:
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=1)
            os.close(master)
            with self._process_lock:
                if self._active_process is process:
                    self._active_process = None
        return NetEaseLoginResult(status, last_output, reason)

    def logout(self) -> bool:
        """Clear ncm-cli login state without changing its base configuration."""
        result = self._run(("logout",))
        return _command_succeeded(result)

    def is_logged_in(self) -> bool:
        """Read ncm-cli login state independently of playback readiness."""
        if self.executable is None:
            return False
        return _login_check_succeeded(self._run(("login", "--check")))

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
        config_result = self._run(("config", "list"))
        credentials_ready = _config_is_ready(config_result)
        if not credentials_ready:
            return NetEaseWorkerHealth(
                False,
                version,
                False,
                True,
                mpv_ready,
                "Configure ncm-cli appId, privateKey, and player before connecting NetEase.",
                False,
            )
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
                True,
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
                True,
            )
        ready = mpv_ready
        reason = None if ready else "Install mpv before using ncm-cli playback."
        return NetEaseWorkerHealth(ready, version, login_ready, True, mpv_ready, reason, True)

    def search(self, query: str, *, limit: int = 10) -> list[dict[str, Any]]:
        bounded = min(20, max(1, int(limit)))
        result = self._run(
            (
                "search",
                "song",
                "--keyword",
                query,
                "--limit",
                str(bounded),
            )
        )
        if not _command_succeeded(result):
            raise RuntimeError("NetEase catalog search failed.")
        payload = _parse_json_output(result.stdout)
        raw_items = payload.get("songs") or payload.get("items") or payload.get("data") or []
        if isinstance(raw_items, dict):
            raw_items = (
                raw_items.get("songs")
                or raw_items.get("items")
                or raw_items.get("records")
                or []
            )
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
        active_samples = 0
        for attempt in range(PLAY_STATE_MAX_ATTEMPTS):
            if attempt:
                time.sleep(PLAY_STATE_POLL_SECONDS)
            try:
                playback_state = self.state()
            except RuntimeError:
                active_samples = 0
                continue
            if _playback_is_active(playback_state):
                active_samples += 1
                if active_samples >= PLAY_STATE_STABLE_SAMPLES:
                    break
            else:
                active_samples = 0
        else:
            raise RuntimeError(
                "NetEase playback did not enter an active state. "
                "Check the audio output and media network path."
            )
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


def _sanitize_login_output(output: str) -> str:
    """Keep QR foreground/background SGR while removing active terminal controls."""
    preserved: list[str] = []

    def remember(match: re.Match[str]) -> str:
        preserved.append(match.group(0))
        return f"\x00SGR{len(preserved) - 1}\x00"

    text = _LOGIN_ALLOWED_SGR_RE.sub(remember, output)
    text = _TERMINAL_CONTROL_RE.sub("", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    for index, sequence in enumerate(preserved):
        text = text.replace(f"\x00SGR{index}\x00", sequence)
    return text


def _login_check_succeeded(result: subprocess.CompletedProcess[str]) -> bool:
    return _command_succeeded(result)


def _config_is_ready(result: subprocess.CompletedProcess[str]) -> bool:
    if result.returncode != 0:
        return False
    configured: set[str] = set()
    for line in result.stdout.splitlines():
        key, separator, value = line.partition(":")
        if separator and value.strip():
            configured.add(key.strip().casefold())
    return {"appid", "privatekey", "player"}.issubset(configured)


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


def _playback_is_active(payload: dict[str, Any]) -> bool:
    state = payload.get("state")
    if not isinstance(state, dict):
        state = payload
    return str(state.get("status") or "").strip().casefold() in {"play", "playing"}


def _normalize_song(item: dict[str, Any]) -> dict[str, Any]:
    encrypted_id = item.get("encryptedId") or item.get("encrypted_id")
    schema_id = item.get("id")
    if not encrypted_id and re.fullmatch(r"[0-9A-Fa-f]{32}", str(schema_id or "")):
        encrypted_id = schema_id
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
        "playable": item.get("visible") is not False and item.get("playFlag") is not False,
    }
