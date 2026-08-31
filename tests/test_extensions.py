from __future__ import annotations

import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.extensions import ExtensionManager, ExtensionStatus


class ExtensionManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.home = tempfile.TemporaryDirectory()
        self.previous_home = os.environ.get("SONEX_HOME")
        os.environ["SONEX_HOME"] = self.home.name
        self.state_path = Path(self.home.name) / "extensions" / "state.json"

    def tearDown(self) -> None:
        if self.previous_home is None:
            os.environ.pop("SONEX_HOME", None)
        else:
            os.environ["SONEX_HOME"] = self.previous_home
        self.home.cleanup()

    def test_snapshot_is_stable_and_contains_only_v1_builtins(self) -> None:
        manager = ExtensionManager(path=self.state_path)
        self.assertEqual([item.extension_id for item in manager.snapshot()], ["audius", "jamendo", "spotify", "youtube"])
        self.assertEqual(manager.get("youtube").description, "search and stream audio through YouTube")

    def test_enabled_state_is_versioned_and_atomic(self) -> None:
        manager = ExtensionManager(path=self.state_path)
        manager.set_enabled("spotify", False)
        payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["version"], 1)
        self.assertFalse(payload["extensions"]["spotify"]["enabled"])
        self.assertEqual(manager.get("spotify").status, ExtensionStatus.DISABLED)

    def test_reset_is_not_available_for_environment_credentials(self) -> None:
        manager = ExtensionManager(path=self.state_path)
        with patch.dict(os.environ, {"AUDIUS_API_KEY": "from-env"}, clear=False):
            self.assertFalse(manager.get("audius").reset_available)

    def test_youtube_pending_runtime_is_unapplied_until_restart(self) -> None:
        manager = ExtensionManager(path=self.state_path)
        with patch(
            "src.extensions.manager.runtime_status",
            return_value={"status": "restart_required"},
        ):
            view = manager.get("youtube")
        self.assertEqual(view.status, ExtensionStatus.UNAPPLIED)
        self.assertFalse(view.reset_available)

    def test_snapshot_does_not_probe_network(self) -> None:
        with patch(
            "src.extensions.manager.urllib.request.urlopen",
            side_effect=AssertionError("list view must remain local"),
        ):
            manager = ExtensionManager(path=self.state_path)
            manager.snapshot()

    def test_initialization_retires_only_the_legacy_connections_file(self) -> None:
        legacy = Path(self.home.name) / "music" / "connections.json"
        legacy.parent.mkdir(parents=True)
        legacy.write_text("{}", encoding="utf-8")
        unrelated = Path(self.home.name) / "music" / "history.json"
        unrelated.write_text("{}", encoding="utf-8")

        ExtensionManager(path=self.state_path)

        self.assertFalse(legacy.exists())
        self.assertTrue(unrelated.exists())

    def test_quick_check_publishes_waiting_then_terminal_snapshot(self) -> None:
        manager = ExtensionManager(path=self.state_path)
        updates: list[ExtensionStatus] = []

        async def capture(view: object) -> None:
            updates.append(view.status)  # type: ignore[attr-defined]

        with patch.object(manager, "_credential_info", return_value=(True, False, None)), patch.object(manager, "_perform_check", return_value=(True, None)):
            result = asyncio.run(manager.run_action("jamendo", "quick_check", on_update=capture))
        self.assertEqual(updates[0], ExtensionStatus.WAITING)
        self.assertEqual(result.status, ExtensionStatus.ENABLED)


if __name__ == "__main__":
    unittest.main()
