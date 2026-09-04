from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from src.music.connections import MusicConnectionManager, sanitize_account_label


class MusicConnectionManagerTests(unittest.TestCase):
    def test_account_label_is_single_line_terminal_safe_and_display_width_bounded(self) -> None:
        label = "  \x1b[31mSILENCE\x1b[0m\n\t账户  " + "界" * 40

        cleaned = sanitize_account_label(label)

        self.assertIsNotNone(cleaned)
        assert cleaned is not None
        self.assertTrue(cleaned.startswith("SILENCE 账户 "))
        self.assertNotIn("\x1b", cleaned)
        self.assertNotIn("\n", cleaned)
        self.assertLessEqual(sum(2 if "W" == __import__("unicodedata").east_asian_width(char) else 1 for char in cleaned), 64)

    def test_empty_or_control_only_account_label_is_not_persisted(self) -> None:
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "connections.json"
            manager = MusicConnectionManager(path=path)

            manager.mark_connected("spotify", account_label="\x1b[31m\n\t")

            record = manager.record("spotify")
            self.assertIsNotNone(record)
            assert record is not None
            self.assertIsNone(record.account_label)

    def test_first_connected_provider_becomes_preferred_without_later_overwrite(self) -> None:
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "connections.json"
            manager = MusicConnectionManager(path=path)

            manager.mark_connected("spotify", account_label="Spotify User")
            self.assertEqual(manager.preferred_provider_id, "spotify")
            self.assertEqual(
                [record.provider_id for record in manager.records()],
                ["spotify"],
            )
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["preferred_provider_id"], "spotify")
            self.assertNotIn("token", json.dumps(payload).casefold())

    def test_health_failure_does_not_delete_connection_or_preferred_provider(self) -> None:
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "connections.json"
            manager = MusicConnectionManager(path=path)
            manager.mark_connected("spotify", account_label="Spotify User")

            manager.mark_unavailable("spotify", reason="Account check timed out.")

            record = manager.record("spotify")
            self.assertIsNotNone(record)
            assert record is not None
            self.assertEqual(record.status, "unavailable")
            self.assertEqual(record.reason, "Account check timed out.")
            self.assertEqual(manager.preferred_provider_id, "spotify")


if __name__ == "__main__":
    unittest.main()
