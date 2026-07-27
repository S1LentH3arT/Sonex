"""Behavioral tests for persisted mpv playback diagnostics."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.tools.mpv_diagnostics import MpvDiagnosticSession, MpvPlaybackHealthMonitor


class MpvDiagnosticSessionTests(unittest.TestCase):
    def test_sessions_rotate_cap_output_and_redact_media_locations(self) -> None:
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {"SONEX_HOME": home}):
            media_url = "https://user:secret@example.test/audio.webm?token=private"
            media_path = "/home/silence/Music/private-song.webm"
            for index in range(4):
                session = MpvDiagnosticSession(
                    session_id=f"session-{index}",
                    media_location=media_url if index == 3 else media_path,
                )
                session.record(
                    "status",
                    progress_ms=index * 1000,
                    is_playing=True,
                    current_ao="pulse",
                )
                session.write_mpv_output(
                    f"opening {session.media_location}\n"
                    + ("x" * (MpvDiagnosticSession.MPV_LOG_LIMIT_BYTES + 1024))
                )
                session.close()
                session.record("status", progress_ms=999999, is_playing=False)
                session.close()

            root = Path(home) / "diagnostics" / "mpv"
            session_dirs = sorted(path for path in root.iterdir() if path.is_dir())
            self.assertEqual(len(session_dirs), 3)
            for session_dir in session_dirs:
                files = list(session_dir.iterdir())
                self.assertLessEqual(sum(path.stat().st_size for path in files), 1024 * 1024)
                content = "\n".join(path.read_text(encoding="utf-8", errors="replace") for path in files)
                self.assertNotIn(media_url, content)
                self.assertNotIn(media_path, content)
                self.assertNotIn("secret", content)
                self.assertNotIn("private", content)

            newest_events = session_dirs[-1] / "events.jsonl"
            payload = next(
                json.loads(line)
                for line in newest_events.read_text(encoding="utf-8").splitlines()
                if json.loads(line)["event"] == "status"
            )
            self.assertEqual(payload["event"], "status")
            self.assertEqual(payload["current_ao"], "pulse")
            events = [
                json.loads(line)
                for line in newest_events.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(events[-1]["event"], "session_closed")
            self.assertFalse(any(event.get("progress_ms") == 999999 for event in events))

    def test_capped_event_log_keeps_complete_json_lines(self) -> None:
        with tempfile.TemporaryDirectory() as home, \
                patch.dict(os.environ, {"SONEX_HOME": home}), \
                patch.object(MpvDiagnosticSession, "EVENT_LOG_LIMIT_BYTES", 512):
            session = MpvDiagnosticSession(session_id="session-cap", media_location="song.webm")
            for progress_ms in range(100):
                session.record(
                    "status",
                    progress_ms=progress_ms,
                    is_playing=True,
                    current_ao="pulse",
                )

            lines = session.events_path.read_text(encoding="utf-8").splitlines()
            events = [json.loads(line) for line in lines]
            self.assertTrue(events)
            self.assertEqual(events[-1]["progress_ms"], 99)

    def test_sustained_clock_drift_triggers_a_bounded_diagnostic_burst(self) -> None:
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {"SONEX_HOME": home}):
            session = MpvDiagnosticSession(session_id="session-drift", media_location="song.webm")
            times = iter([0.0, 1.0, 2.0, 3.0])
            monitor = MpvPlaybackHealthMonitor(
                session=session,
                burst_sampler=lambda: {
                    "progress_ms": 900,
                    "is_playing": True,
                    "paused_for_cache": False,
                    "current_ao": "pulse",
                    "ipc_ok": True,
                },
                time_source=lambda: next(times),
                burst_duration_seconds=0.03,
                burst_interval_seconds=0.005,
            )

            first_anomaly = monitor.observe(
                progress_ms=0,
                is_playing=True,
                paused_for_cache=False,
                current_ao="pulse",
                ipc_ok=True,
            )
            second_anomaly = monitor.observe(
                progress_ms=400,
                is_playing=True,
                paused_for_cache=False,
                current_ao="pulse",
                ipc_ok=True,
            )
            third_anomaly = monitor.observe(
                progress_ms=800,
                is_playing=True,
                paused_for_cache=False,
                current_ao="pulse",
                ipc_ok=True,
            )
            self.assertIsNone(first_anomaly)
            self.assertIsNone(second_anomaly)
            self.assertEqual(third_anomaly, "clock_drift")
            self.assertTrue(monitor.wait_for_burst(timeout=1))
            repeated_anomaly = monitor.observe(
                progress_ms=1200,
                is_playing=True,
                paused_for_cache=False,
                current_ao="pulse",
                ipc_ok=True,
            )
            self.assertIsNone(repeated_anomaly)
            self.assertTrue(monitor.wait_for_burst(timeout=1))

            events = [
                json.loads(line)
                for line in session.events_path.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(sum(event["event"] == "clock_drift" for event in events), 1)
            burst_samples = [event for event in events if event["event"] == "burst_sample"]
            self.assertGreaterEqual(len(burst_samples), 2)
            self.assertTrue(all(event["burst"] is True for event in burst_samples))

    def test_closing_monitor_stops_an_active_burst(self) -> None:
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {"SONEX_HOME": home}):
            session = MpvDiagnosticSession(session_id="session-close", media_location="song.webm")
            monitor = MpvPlaybackHealthMonitor(
                session=session,
                burst_sampler=lambda: {
                    "progress_ms": 0,
                    "is_playing": True,
                    "ipc_ok": False,
                },
                burst_duration_seconds=10,
                burst_interval_seconds=0.01,
            )
            monitor.observe(
                progress_ms=0,
                is_playing=True,
                paused_for_cache=False,
                current_ao="pulse",
                ipc_ok=False,
                error="IPC unavailable",
            )

            monitor.close()

            self.assertTrue(monitor.wait_for_burst(timeout=0.2))


if __name__ == "__main__":
    unittest.main()
