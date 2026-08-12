from __future__ import annotations

import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from src.music.netease_worker import NetEaseProviderWorker


class NetEaseWorkerTests(unittest.TestCase):
    def test_logout_uses_fixed_argv_without_shell(self) -> None:
        calls: list[tuple[list[str], dict[str, object]]] = []

        def run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            calls.append((argv, kwargs))
            return subprocess.CompletedProcess(argv, 0, stdout='{"success":true}', stderr="")

        worker = NetEaseProviderWorker(executable="/usr/bin/ncm-cli", run_command=run)

        self.assertTrue(worker.logout())
        self.assertEqual(calls[0][0], ["/usr/bin/ncm-cli", "logout"])
        self.assertIs(calls[0][1]["shell"], False)

    def test_login_check_is_independent_of_playback_health(self) -> None:
        calls: list[list[str]] = []

        def run(argv: list[str], **_: object) -> subprocess.CompletedProcess[str]:
            calls.append(argv)
            return subprocess.CompletedProcess(argv, 0, stdout='{"success":true}', stderr="")

        worker = NetEaseProviderWorker(executable="/usr/bin/ncm-cli", run_command=run)

        self.assertTrue(worker.is_logged_in())
        self.assertEqual(calls, [["/usr/bin/ncm-cli", "login", "--check"]])

    def test_login_bridge_streams_terminal_qr_and_can_be_cancelled(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "ncm-cli"
            executable.write_text(
                "#!/usr/bin/env python3\n"
                "import signal, sys, time\n"
                "signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))\n"
                "print('Scan with NetEase:')\n"
                "print('\\x1b[47m  \\x1b[40m  \\x1b[0m')\n"
                "sys.stdout.flush()\n"
                "while True: time.sleep(0.05)\n",
                encoding="utf-8",
            )
            executable.chmod(0o755)
            cancel = threading.Event()
            updates: list[str] = []
            worker = NetEaseProviderWorker(executable=str(executable))

            timer = threading.Timer(0.1, cancel.set)
            timer.start()
            try:
                result = worker.login(
                    on_output=updates.append,
                    cancel_event=cancel,
                    timeout_seconds=2,
                )
            finally:
                timer.cancel()

        self.assertEqual(result.status, "cancelled")
        self.assertTrue(any("Scan with NetEase:" in update for update in updates))
        self.assertTrue(any("\x1b[47m" in update for update in updates))
        self.assertNotIn("\x1b[2J", result.output)

    def test_search_uses_fixed_argv_without_shell_and_normalizes_ids(self) -> None:
        calls: list[tuple[list[str], dict[str, object]]] = []

        def run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            calls.append((argv, kwargs))
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout='{"songs":[{"name":"BB88","artist":"方大同","encryptedId":"enc","originalId":"88"}]}',
                stderr="",
            )

        worker = NetEaseProviderWorker(executable="/usr/bin/ncm-cli", run_command=run)
        songs = worker.search("方大同 BB88")

        self.assertEqual(
            calls[0][0],
            ["/usr/bin/ncm-cli", "search", "song", "--keyword", "方大同 BB88"],
        )
        self.assertIs(calls[0][1]["shell"], False)
        self.assertEqual(songs[0]["id"], "enc|88")

    def test_health_does_not_configure_or_play(self) -> None:
        calls: list[list[str]] = []

        def run(argv: list[str], **_: object) -> subprocess.CompletedProcess[str]:
            calls.append(argv)
            if argv[-1] == "--version":
                stdout = "ncm-cli 0.1.6"
            elif argv[-2:] == ["config", "list"]:
                stdout = "appId: app\nprivateKey: key\nplayer: mpv\n"
            else:
                stdout = "{}"
            return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")

        with tempfile.TemporaryDirectory() as directory:
            worker = NetEaseProviderWorker(
                executable="/usr/bin/ncm-cli",
                config_dir=Path(directory),
                run_command=run,
            )
            worker.health()

        flattened = " ".join(part for call in calls for part in call)
        self.assertNotIn("configure", flattened)
        self.assertNotIn("play", flattened)
        self.assertEqual(calls[-2][-2:], ["login", "--check"])
        self.assertEqual(calls[-1][-1], "commands")

    def test_health_rejects_login_check_json_failure_even_with_zero_exit_code(self) -> None:
        def run(argv: list[str], **_: object) -> subprocess.CompletedProcess[str]:
            if argv[-1] == "--version":
                stdout = "ncm-cli 0.1.6"
            elif argv[-2:] == ["config", "list"]:
                stdout = "appId: app\nprivateKey: key\nplayer: mpv\n"
            elif argv[-2:] == ["login", "--check"]:
                stdout = '{"success":false,"message":"not logged in"}'
            else:
                stdout = ""
            return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")

        with tempfile.TemporaryDirectory() as directory, patch(
            "src.music.netease_worker.shutil.which",
            return_value="/usr/bin/mpv",
        ):
            health = NetEaseProviderWorker(
                executable="/usr/bin/ncm-cli",
                config_dir=Path(directory),
                run_command=run,
            ).health()

        self.assertFalse(health.login_ready)
        self.assertFalse(health.ready)

    def test_health_requires_the_dynamic_search_command_before_routing(self) -> None:
        calls: list[list[str]] = []

        def run(argv: list[str], **_: object) -> subprocess.CompletedProcess[str]:
            calls.append(argv)
            if argv[-1] == "--version":
                stdout = "ncm-cli 0.1.6"
            elif argv[-2:] == ["config", "list"]:
                stdout = "appId: app\nprivateKey: key\nplayer: mpv\n"
            elif argv[-2:] == ["login", "--check"]:
                stdout = '{"success":true}'
            elif argv[-1] == "commands":
                stdout = "play  Play a song\nstate  Show playback state\n"
            else:
                stdout = ""
            return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")

        with tempfile.TemporaryDirectory() as directory, patch(
            "src.music.netease_worker.shutil.which",
            return_value="/usr/bin/mpv",
        ):
            health = NetEaseProviderWorker(
                executable="/usr/bin/ncm-cli",
                config_dir=Path(directory),
                run_command=run,
            ).health()

        self.assertFalse(health.ready)
        self.assertIn("search", str(health.reason).casefold())
        self.assertIn(["/usr/bin/ncm-cli", "commands"], calls)

    def test_health_accepts_logged_in_cli_with_search_and_mpv(self) -> None:
        def run(argv: list[str], **_: object) -> subprocess.CompletedProcess[str]:
            if argv[-1] == "--version":
                stdout = "ncm-cli 0.1.6"
            elif argv[-2:] == ["config", "list"]:
                stdout = "appId: app\nprivateKey: key\nplayer: mpv\n"
            elif argv[-2:] == ["login", "--check"]:
                stdout = '{"success":true}'
            elif argv[-1] == "commands":
                stdout = "search  Search songs\nplay  Play a song\n"
            else:
                stdout = ""
            return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")

        with tempfile.TemporaryDirectory() as directory, patch(
            "src.music.netease_worker.shutil.which",
            return_value="/usr/bin/mpv",
        ):
            health = NetEaseProviderWorker(
                executable="/usr/bin/ncm-cli",
                config_dir=Path(directory),
                run_command=run,
            ).health()

        self.assertTrue(health.login_ready)
        self.assertTrue(health.ready)
        self.assertIsNone(health.reason)

    def test_health_requires_base_credentials_before_offering_login(self) -> None:
        def run(argv: list[str], **_: object) -> subprocess.CompletedProcess[str]:
            stdout = "ncm-cli 0.1.6" if argv[-1] == "--version" else "player: mpv\n"
            return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")

        with tempfile.TemporaryDirectory() as directory, patch(
            "src.music.netease_worker.shutil.which",
            return_value="/usr/bin/mpv",
        ):
            health = NetEaseProviderWorker(
                executable="/usr/bin/ncm-cli",
                config_dir=Path(directory),
                run_command=run,
            ).health()

        self.assertFalse(health.login_available)
        self.assertIn("appid", str(health.reason).casefold())

    def test_play_rejects_json_failure_even_with_zero_exit_code(self) -> None:
        def run(argv: list[str], **_: object) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout='{"success":false,"message":"login required"}',
                stderr="",
            )

        worker = NetEaseProviderWorker(
            executable="/usr/bin/ncm-cli",
            run_command=run,
        )

        with self.assertRaisesRegex(RuntimeError, "playback failed"):
            worker.play(encrypted_id="enc", original_id="88")


if __name__ == "__main__":
    unittest.main()
