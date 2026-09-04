"""Bounded yt-dlp execution for Sonex online-audio operations."""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from typing import Any


class YtDlpError(RuntimeError):
    """Raised when the isolated yt-dlp worker returns an error."""


class YtDlpTimeoutError(TimeoutError):
    """Raised when the isolated yt-dlp worker exceeds its wall-clock budget."""


def _terminate_process(process: subprocess.Popen[str]) -> None:
    process.terminate()
    try:
        process.communicate(timeout=2.0)
        return
    except (subprocess.TimeoutExpired, OSError):
        pass
    process.kill()
    try:
        process.communicate(timeout=2.0)
    except (subprocess.TimeoutExpired, OSError):
        process.wait(timeout=2.0)


def _force_stop_process(process: subprocess.Popen[str]) -> None:
    process.terminate()
    try:
        process.wait(timeout=2.0)
        return
    except (subprocess.TimeoutExpired, OSError):
        pass
    process.kill()
    try:
        process.wait(timeout=2.0)
    except (subprocess.TimeoutExpired, OSError):
        pass


def _communicate_download_with_watchdog(
    process: subprocess.Popen[str],
    payload: str,
    *,
    timeout_seconds: float,
    no_progress_seconds: float,
) -> tuple[str, str]:
    if process.stdin is None or process.stdout is None or process.stderr is None:
        raise YtDlpError("yt-dlp worker pipes are unavailable.")
    process.stdin.write(payload)
    process.stdin.close()
    stdout_chunks: list[str] = []
    stderr_chunks: list[str] = []
    last_progress = [time.monotonic()]

    def drain(stream: Any, chunks: list[str], track_progress: bool) -> None:
        for line in iter(stream.readline, ""):
            chunks.append(line)
            if track_progress and line.strip() == "SONEX_PROGRESS":
                last_progress[0] = time.monotonic()

    stdout_thread = threading.Thread(
        target=drain,
        args=(process.stdout, stdout_chunks, False),
        daemon=True,
    )
    stderr_thread = threading.Thread(
        target=drain,
        args=(process.stderr, stderr_chunks, True),
        daemon=True,
    )
    stdout_thread.start()
    stderr_thread.start()
    started = time.monotonic()
    timeout_reason: str | None = None
    while process.poll() is None:
        now = time.monotonic()
        if now - started >= max(0.01, float(timeout_seconds)):
            timeout_reason = f"yt-dlp download exceeded {float(timeout_seconds):g} seconds."
            break
        if now - last_progress[0] >= max(0.1, float(no_progress_seconds)):
            timeout_reason = (
                f"yt-dlp download made no progress for {float(no_progress_seconds):g} seconds."
            )
            break
        time.sleep(0.05)
    if timeout_reason:
        _force_stop_process(process)
    stdout_thread.join(timeout=2.0)
    stderr_thread.join(timeout=2.0)
    if timeout_reason:
        raise YtDlpTimeoutError(timeout_reason)
    return "".join(stdout_chunks), "".join(stderr_chunks)


def run_ytdlp(
    *,
    operation: str,
    target: str,
    options: dict[str, Any],
    timeout_seconds: float,
    no_progress_seconds: float = 15.0,
) -> dict[str, Any]:
    """Run one yt-dlp operation in a child process that can be terminated."""
    payload = {
        "operation": operation,
        "target": target,
        "options": options,
    }
    process = subprocess.Popen(
        _worker_command(),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=_worker_environment(),
    )
    serialized_payload = json.dumps(payload, ensure_ascii=False, default=str)
    try:
        if operation == "download" and hasattr(process, "poll"):
            stdout, stderr = _communicate_download_with_watchdog(
                process,
                serialized_payload,
                timeout_seconds=timeout_seconds,
                no_progress_seconds=no_progress_seconds,
            )
        else:
            stdout, stderr = process.communicate(
                input=serialized_payload,
                timeout=max(0.01, float(timeout_seconds)),
            )
    except subprocess.TimeoutExpired as exc:
        _terminate_process(process)
        raise YtDlpTimeoutError(
            f"yt-dlp {operation} exceeded {float(timeout_seconds):g} seconds."
        ) from exc

    raw_output = (stdout or "").strip().splitlines()
    response: dict[str, Any] | None = None
    for line in reversed(raw_output):
        try:
            candidate = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict):
            response = candidate
            break

    if not response:
        detail = (stderr or stdout or "yt-dlp worker returned no JSON response").strip()
        raise YtDlpError(detail)
    if not response.get("ok"):
        detail = str(response.get("error") or stderr or "yt-dlp operation failed").strip()
        raise YtDlpError(detail)
    result = response.get("result")
    if not isinstance(result, dict):
        raise YtDlpError("yt-dlp worker returned an invalid result.")
    if process.returncode not in (0, None):
        raise YtDlpError((stderr or "yt-dlp worker failed").strip())
    return result


def _worker_command() -> list[str]:
    """Return the active managed worker command, preserving direct test use."""
    from src.tools.youtube_runtime import worker_command

    return worker_command()


def _worker_environment() -> dict[str, str]:
    from src.tools.youtube_runtime import worker_env

    return worker_env()
