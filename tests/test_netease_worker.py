from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from src.music.netease_worker import NetEaseProviderWorker


class NetEaseWorkerTests(unittest.TestCase):
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
            stdout = "ncm-cli 0.1.6" if argv[-1] == "--version" else "{}"
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
        self.assertEqual(calls[-1][-2:], ["login", "--check"])


if __name__ == "__main__":
    unittest.main()
