from __future__ import annotations

import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.extensions import ExtensionActionError, ExtensionManager, ExtensionStatus


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
        manager.set_enabled("spotify", False, expected_revision=0)
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

    def test_unapplied_runtime_exposes_prepare_restart_action(self) -> None:
        manager = ExtensionManager(path=self.state_path)
        with patch(
            "src.extensions.manager.runtime_status",
            return_value={"status": "restart_required"},
        ):
            self.assertEqual(manager.actions("youtube"), ("quick_check", "prepare_restart"))

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
            result = asyncio.run(manager.run_action("jamendo", "quick_check", expected_revision=0, on_update=capture))
        self.assertEqual(updates[0], ExtensionStatus.WAITING)
        self.assertEqual(result.status, ExtensionStatus.ENABLED)

    def test_actions_are_derived_by_manager(self) -> None:
        manager = ExtensionManager(path=self.state_path)
        self.assertEqual(manager.actions("audius"), ("quick_check", "setup"))
        with patch.dict(os.environ, {"AUDIUS_API_KEY": "from-env"}, clear=False):
            self.assertEqual(manager.actions("audius"), ("quick_check", "disable"))

    def test_state_change_rejects_stale_revision(self) -> None:
        manager = ExtensionManager(path=self.state_path)
        manager.set_enabled("spotify", False, expected_revision=0)
        with self.assertRaisesRegex(ExtensionActionError, "revision"):
            asyncio.run(manager.run_action("spotify", "enable", expected_revision=0))

    def test_run_action_rejects_action_not_in_current_snapshot(self) -> None:
        manager = ExtensionManager(path=self.state_path)
        with self.assertRaisesRegex(ExtensionActionError, "not available"):
            asyncio.run(manager.run_action("spotify", "disable", expected_revision=0))

    def test_setup_draft_is_session_bound_and_discardable(self) -> None:
        manager = ExtensionManager(path=self.state_path)
        manager.begin_setup("session-1", "jamendo")
        manager.update_setup_draft("session-1", "jamendo", "api_key", "secret")
        self.assertEqual(manager.setup_draft("session-1", "jamendo"), {"api_key": "secret"})
        self.assertEqual(manager.setup_revision("session-1", "jamendo"), 0)
        self.assertNotIn("secret", self.state_path.read_text(encoding="utf-8") if self.state_path.exists() else "")
        manager.discard_setup("session-1", "jamendo")
        self.assertEqual(manager.setup_draft("session-1", "jamendo"), {})

    def test_setup_draft_expires_without_persisting(self) -> None:
        manager = ExtensionManager(path=self.state_path)
        with patch("src.extensions.manager.time.monotonic", side_effect=[10.0, 611.0]):
            manager.begin_setup("session-1", "jamendo")
            self.assertEqual(manager.setup_draft("session-1", "jamendo"), {})
        with self.assertRaisesRegex(ExtensionActionError, "not active"):
            manager.setup_revision("session-1", "jamendo")


if __name__ == "__main__":
    unittest.main()
