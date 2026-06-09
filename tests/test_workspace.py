"""Tests test workspace.

Contains pytest coverage for the test workspace behavior.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import src.main as main
from src.tools import local_play
from src.workspace import WorkspaceBoundaryError, ensure_within_user_workspace, user_workspace_root


class WorkspaceTests(unittest.TestCase):
    """Groups related workspace tests cases.

    Collects assertions that exercise workspace tests behavior without mixing unrelated fixtures.
    """
    def test_user_workspace_root_defaults_to_home(self) -> None:
        """Verifies that user workspace root defaults to home behaves as expected.

        Typical use: Use this in automated tests when guarding the user workspace root defaults to home behavior against regressions.

        Example: test_user_workspace_root_defaults_to_home() -> passes without assertion failures when the behavior remains correct.
        """
        with tempfile.TemporaryDirectory() as home, patch.object(Path, "home", return_value=Path(home)):
            self.assertEqual(user_workspace_root(), Path(home).resolve())

    def test_user_workspace_rejects_system_paths(self) -> None:
        """Verifies that user workspace rejects system paths behaves as expected.

        Typical use: Use this in automated tests when guarding the user workspace rejects system paths behavior against regressions.

        Example: test_user_workspace_rejects_system_paths() -> passes without assertion failures when the behavior remains correct.
        """
        with tempfile.TemporaryDirectory() as home, patch.object(Path, "home", return_value=Path(home)):
            with self.assertRaises(WorkspaceBoundaryError):
                ensure_within_user_workspace("/etc")

            with self.assertRaises(WorkspaceBoundaryError):
                ensure_within_user_workspace("/usr")

            allowed = ensure_within_user_workspace("Music/song.mp3")

        self.assertEqual(allowed, Path(home, "Music", "song.mp3").resolve())

    def test_local_music_search_uses_user_workspace_music_dir(self) -> None:
        """Verifies that local music search uses user workspace music dir behaves as expected.

        Typical use: Use this in automated tests when guarding the local music search uses user workspace music dir behavior against regressions.

        Example: test_local_music_search_uses_user_workspace_music_dir() -> passes without assertion failures when the behavior remains correct.
        """
        with tempfile.TemporaryDirectory() as home, patch.object(Path, "home", return_value=Path(home)):
            music_dir = Path(home) / "Music"
            music_dir.mkdir()
            song = music_dir / "quiet-song.mp3"
            song.write_text("audio", encoding="utf-8")

            result = local_play.search_local_file("quiet")

        self.assertEqual(result, str(song))

    def test_ink_tui_runs_from_user_workspace(self) -> None:
        """Verifies that ink tui runs from user workspace behaves as expected.

        Typical use: Use this in automated tests when guarding the ink tui runs from user workspace behavior against regressions.

        Example: test_ink_tui_runs_from_user_workspace() -> passes without assertion failures when the behavior remains correct.
        """
        with tempfile.TemporaryDirectory() as home:
            with (
                patch.object(Path, "home", return_value=Path(home)),
                patch.object(main, "_build_ink_ui_if_needed", return_value=None),
                patch.object(main.subprocess, "run", return_value=MagicMock(returncode=0)) as run,
            ):
                result = main._run_ink_tui("127.0.0.1", 9001)

            self.assertEqual(result, 0)
            self.assertEqual(run.call_args.kwargs["cwd"], Path(home).resolve())
            self.assertEqual(run.call_args.kwargs["env"]["SONEX_WS_URL"], "ws://127.0.0.1:9001/ws")

    def test_api_process_runs_from_user_workspace_with_project_pythonpath(self) -> None:
        """Verifies that api process runs from user workspace with project pythonpath behaves as expected.

        Typical use: Use this in automated tests when guarding the api process runs from user workspace with project pythonpath behavior against regressions.

        Example: test_api_process_runs_from_user_workspace_with_project_pythonpath() -> passes without assertion failures when the behavior remains correct.
        """
        with tempfile.TemporaryDirectory() as home:
            with (
                patch.object(Path, "home", return_value=Path(home)),
                patch.object(main.subprocess, "Popen", return_value=MagicMock()) as popen,
                patch.dict(os.environ, {}, clear=True),
            ):
                main._start_api_process("127.0.0.1", 9001)

            kwargs = popen.call_args.kwargs
            self.assertEqual(kwargs["cwd"], Path(home).resolve())
            self.assertIn(str(main._project_root()), kwargs["env"]["PYTHONPATH"])


if __name__ == "__main__":
    unittest.main()
