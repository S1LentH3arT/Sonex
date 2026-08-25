from __future__ import annotations

import subprocess
import unittest
from unittest.mock import patch

import src.tools.yt_dlp_runner as runner


class _FakeProcess:
    def __init__(self, *, output: str = "", timeout: bool = False) -> None:
        self.output = output
        self.timeout = timeout
        self.returncode = 0
        self.terminated = False
        self.killed = False
        self.wait_calls: list[float | None] = []

    def communicate(self, input: str | None = None, timeout: float | None = None):
        del input, timeout
        if self.timeout and not self.killed:
            raise subprocess.TimeoutExpired(cmd="yt-dlp", timeout=1)
        return self.output, ""

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True

    def wait(self, timeout: float | None = None) -> None:
        self.wait_calls.append(timeout)


class YtDlpRunnerTests(unittest.TestCase):
    def test_run_ytdlp_returns_json_payload_from_child(self) -> None:
        process = _FakeProcess(output='{"ok": true, "result": {"entries": []}}\n')
        with patch("src.tools.yt_dlp_runner.subprocess.Popen", return_value=process):
            result = runner.run_ytdlp(
                operation="search",
                target="ytsearch5:Artist Song",
                options={"quiet": True},
                timeout_seconds=8,
            )

        self.assertEqual(result, {"entries": []})
        self.assertFalse(process.terminated)
        self.assertFalse(process.killed)

    def test_run_ytdlp_terminates_and_kills_child_after_timeout(self) -> None:
        process = _FakeProcess(timeout=True)
        with patch("src.tools.yt_dlp_runner.subprocess.Popen", return_value=process):
            with self.assertRaises(runner.YtDlpTimeoutError):
                runner.run_ytdlp(
                    operation="search",
                    target="ytsearch5:Artist Song",
                    options={"quiet": True},
                    timeout_seconds=0.01,
                )

        self.assertTrue(process.terminated)
        self.assertTrue(process.killed)
