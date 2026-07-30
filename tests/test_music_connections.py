from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from src.music.connections import MusicConnectionManager


class MusicConnectionManagerTests(unittest.TestCase):
    def test_first_connected_provider_becomes_preferred_without_later_overwrite(self) -> None:
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "connections.json"
            manager = MusicConnectionManager(path=path)

            manager.mark_connected("spotify", account_label="Spotify User")
            manager.mark_connected("apple_music", account_label="Apple Music")

            self.assertEqual(manager.preferred_provider_id, "spotify")
            self.assertEqual(
                [record.provider_id for record in manager.records()],
                ["apple_music", "spotify"],
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
