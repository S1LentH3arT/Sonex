from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from src.music.player_preferences import (
    PlayerSinkPreferences,
    read_player_preferences,
    write_player_preferences,
)


class PlayerSinkPreferencesTests(unittest.TestCase):
    def test_invalid_or_unknown_payload_is_unconfigured(self) -> None:
        self.assertEqual(PlayerSinkPreferences.from_payload({"version": 2}), PlayerSinkPreferences())
        self.assertEqual(PlayerSinkPreferences.from_payload({"version": 1, "default_sink_id": 7}), PlayerSinkPreferences())

    def test_round_trip_preserves_default_and_pending_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "music" / "player-preferences.json"
            preferences = PlayerSinkPreferences(default_sink_id="managed:mpv", pending_sink_id="mpris:clementine")

            write_player_preferences(path, preferences)

            self.assertEqual(read_player_preferences(path), preferences)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), preferences.to_payload())
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)

    def test_missing_file_returns_empty_preferences(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            self.assertEqual(
                read_player_preferences(Path(temporary) / "missing.json"),
                PlayerSinkPreferences(),
            )


if __name__ == "__main__":
    unittest.main()
