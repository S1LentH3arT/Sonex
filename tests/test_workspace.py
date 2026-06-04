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
    def test_user_workspace_root_defaults_to_home(self) -> None:
        with tempfile.TemporaryDirectory() as home, patch.object(Path, "home", return_value=Path(home)):
            self.assertEqual(user_workspace_root(), Path(home).resolve())

    def test_user_workspace_rejects_system_paths(self) -> None:
        with tempfile.TemporaryDirectory() as home, patch.object(Path, "home", return_value=Path(home)):
            with self.assertRaises(WorkspaceBoundaryError):
                ensure_within_user_workspace("/etc")

            with self.assertRaises(WorkspaceBoundaryError):
                ensure_within_user_workspace("/usr")

            allowed = ensure_within_user_workspace("Music/song.mp3")

        self.assertEqual(allowed, Path(home, "Music", "song.mp3").resolve())

    def test_local_music_search_uses_user_workspace_music_dir(self) -> None:
        with tempfile.TemporaryDirectory() as home, patch.object(Path, "home", return_value=Path(home)):
            music_dir = Path(home) / "Music"
            music_dir.mkdir()
            song = music_dir / "quiet-song.mp3"
            song.write_text("audio", encoding="utf-8")

            result = local_play.search_local_file("quiet")

        self.assertEqual(result, str(song))

    def test_ink_tui_runs_from_user_workspace(self) -> None:
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
