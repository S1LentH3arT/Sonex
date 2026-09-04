"""Bounded, privacy-safe diagnostics for local mpv playback sessions."""

from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path
from typing import Any, BinaryIO, Callable

from src.log.config import sonex_home
from src.tools.diagnostics_policy import SAFE_MPV_FIELDS, sanitize_diagnostic_text


class MpvDiagnosticSession:
    """Persist one bounded, sanitized mpv diagnostic session."""

    SESSION_LIMIT_BYTES = 1024 * 1024
    MPV_LOG_LIMIT_BYTES = 768 * 1024
    EVENT_LOG_LIMIT_BYTES = SESSION_LIMIT_BYTES - MPV_LOG_LIMIT_BYTES
    RETAINED_SESSIONS = 3

    def __init__(self, *, session_id: str, media_location: str) -> None:
        self.session_id = session_id
        self.media_location = media_location
        self._lock = threading.Lock()
        self._closed = False
        root = sonex_home() / "diagnostics" / "mpv"
        root.mkdir(parents=True, exist_ok=True)
        safe_session_id = re.sub(r"[^A-Za-z0-9_.-]", "_", session_id)[:80] or "unknown"
        self.session_dir = root / f"{time.time_ns():020d}-{safe_session_id}"
        self.session_dir.mkdir(parents=False, exist_ok=False)
        self.events_path = self.session_dir / "events.jsonl"
        self.mpv_log_path = self.session_dir / "mpv.log"
        self._rotate(root)
        self.record("session_started", ipc_ok=True)

    def _rotate(self, root: Path) -> None:
        session_dirs = sorted(path for path in root.iterdir() if path.is_dir())
        for stale_dir in session_dirs[:-self.RETAINED_SESSIONS]:
            for child in stale_dir.iterdir():
                if child.is_file():
                    child.unlink()
            stale_dir.rmdir()

    def _sanitize(self, value: str) -> str:
        return sanitize_diagnostic_text(value, media_location=self.media_location)

    def _append_capped(self, path: Path, text: str, limit: int) -> None:
        encoded = text.encode("utf-8", errors="replace")
        with self._lock:
            with path.open("ab") as output:
                output.write(encoded)
            if path.stat().st_size > limit:
                with path.open("rb") as source:
                    source.seek(-limit, 2)
                    tail = source.read()
                if path == self.events_path:
                    newline = tail.find(b"\n")
                    tail = tail[newline + 1:] if newline >= 0 else b""
                path.write_bytes(tail)

    def record(self, event: str, **fields: Any) -> None:
        """Append one whitelisted structured event."""
        if self._closed:
            return
        payload: dict[str, Any] = {
            "timestamp_ms": int(time.time() * 1000),
            "session_id": self.session_id,
            "event": str(event),
        }
        for key, value in fields.items():
            if key not in SAFE_MPV_FIELDS or value is None:
                continue
            payload[key] = self._sanitize(str(value)) if key == "error" else value
        self._append_capped(
            self.events_path,
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n",
            self.EVENT_LOG_LIMIT_BYTES,
        )

    def write_mpv_output(self, text: str) -> None:
        """Append sanitized mpv stderr output."""
        self._append_capped(
            self.mpv_log_path,
            self._sanitize(text),
            self.MPV_LOG_LIMIT_BYTES,
        )

    def capture_mpv_stderr(self, stream: BinaryIO) -> None:
        """Drain mpv stderr until EOF without allowing unbounded output."""
        while True:
            chunk = stream.readline()
            if not chunk:
                return
            if isinstance(chunk, bytes):
                text = chunk.decode("utf-8", errors="replace")
            else:
                text = str(chunk)
            if text.lstrip().startswith("A: "):
                continue
            self.write_mpv_output(text)

    def close(self) -> None:
        """Mark the diagnostic session complete."""
        if self._closed:
            return
        self.record("session_closed", ipc_ok=True)
        self._closed = True


class MpvPlaybackHealthMonitor:
    """Detect playback-clock anomalies and capture a short diagnostic burst."""

    def __init__(
        self,
        *,
        session: MpvDiagnosticSession,
        burst_sampler: Callable[[], dict[str, Any]],
        time_source: Callable[[], float] = time.monotonic,
        burst_duration_seconds: float = 10.0,
        burst_interval_seconds: float = 0.1,
    ) -> None:
        self.session = session
        self.burst_sampler = burst_sampler
        self.time_source = time_source
        self.burst_duration_seconds = burst_duration_seconds
        self.burst_interval_seconds = burst_interval_seconds
        self._previous_wall: float | None = None
        self._previous_progress_ms: int | None = None
        self._previous_ao: str | None = None
        self._drift_strikes = 0
        self._anomaly_latched = False
        self._burst_lock = threading.Lock()
        self._burst_thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def observe(
        self,
        *,
        progress_ms: int,
        is_playing: bool,
        paused_for_cache: bool,
        current_ao: str | None,
        ipc_ok: bool,
        error: str | None = None,
    ) -> str | None:
        """Record one regular sample and trigger burst capture on anomalies."""
        now = self.time_source()
        ratio: float | None = None
        if (
            ipc_ok
            and is_playing
            and not paused_for_cache
            and self._previous_wall is not None
            and self._previous_progress_ms is not None
        ):
            wall_delta = now - self._previous_wall
            if wall_delta > 0:
                ratio = max(0.0, (progress_ms - self._previous_progress_ms) / (wall_delta * 1000))

        self.session.record(
            "status",
            progress_ms=progress_ms,
            wall_ms=round(now * 1000),
            media_wall_ratio=round(ratio, 3) if ratio is not None else None,
            is_playing=is_playing,
            paused_for_cache=paused_for_cache,
            current_ao=current_ao,
            ipc_ok=ipc_ok,
            error=error,
        )

        anomaly: str | None = None
        if not ipc_ok:
            anomaly = "ipc_failure"
        elif paused_for_cache:
            anomaly = "cache_pause"
        elif self._previous_ao is not None and current_ao != self._previous_ao:
            anomaly = "audio_output_changed"
        elif ratio is not None and ratio < 0.8:
            self._drift_strikes += 1
            if self._drift_strikes >= 2:
                anomaly = "clock_drift"
        else:
            self._drift_strikes = 0

        if ipc_ok:
            self._previous_wall = now
            self._previous_progress_ms = progress_ms
            self._previous_ao = current_ao

        reported_anomaly: str | None = None
        if anomaly and not self._anomaly_latched:
            self.session.record(
                anomaly,
                progress_ms=progress_ms,
                media_wall_ratio=round(ratio, 3) if ratio is not None else None,
                paused_for_cache=paused_for_cache,
                current_ao=current_ao,
                ipc_ok=ipc_ok,
                error=error,
            )
            self._start_burst()
            self._anomaly_latched = True
            reported_anomaly = anomaly
        elif (
            anomaly is None
            and ipc_ok
            and not paused_for_cache
            and (ratio is None or ratio >= 0.8)
        ):
            self._anomaly_latched = False
        return reported_anomaly

    def _start_burst(self) -> None:
        with self._burst_lock:
            if self._burst_thread and self._burst_thread.is_alive():
                return
            self._burst_thread = threading.Thread(
                target=self._capture_burst,
                name=f"sonex-mpv-burst-{self.session.session_id[:8]}",
                daemon=True,
            )
            self._burst_thread.start()

    def _capture_burst(self) -> None:
        deadline = time.monotonic() + self.burst_duration_seconds
        while not self._stop_event.is_set() and time.monotonic() < deadline:
            try:
                sample = self.burst_sampler()
                self.session.record("burst_sample", burst=True, **sample)
            except Exception as exc:
                self.session.record(
                    "burst_sample",
                    burst=True,
                    ipc_ok=False,
                    error=str(exc),
                )
            if self._stop_event.wait(max(0.0, self.burst_interval_seconds)):
                return

    def wait_for_burst(self, timeout: float | None = None) -> bool:
        """Wait for the current burst to finish."""
        thread = self._burst_thread
        if thread is None:
            return False
        thread.join(timeout=timeout)
        return not thread.is_alive()

    def close(self) -> None:
        """Stop any active burst before its session directory is released."""
        self._stop_event.set()
        thread = self._burst_thread
        if thread and thread.is_alive():
            thread.join(timeout=max(0.2, self.burst_interval_seconds * 2))
