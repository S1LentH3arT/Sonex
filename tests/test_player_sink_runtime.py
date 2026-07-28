from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from src.music.player_sink_runtime import (
    build_player_sink_manager,
    has_persisted_player_sink,
)


class PlayerSinkRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_persisted_sink_check_reads_only_the_preference_record(self) -> None:
        with TemporaryDirectory() as temporary:
            preferences = Path(temporary) / "player-preferences.json"
            self.assertFalse(has_persisted_player_sink(preferences))
            preferences.write_text(
                '{"version":1,"default_sink_id":"mpris:clementine"}',
                encoding="utf-8",
            )
            self.assertTrue(has_persisted_player_sink(preferences))

    async def test_factory_lists_managed_and_known_external_players_without_launching(self) -> None:
        with TemporaryDirectory() as temporary:
            launched: list[tuple[str, ...]] = []
            executable_paths = {
                "mpv": "/usr/bin/mpv",
                "rhythmbox-client": "/usr/bin/rhythmbox-client",
            }
            manager = build_player_sink_manager(
                preferences_path=Path(temporary) / "player-preferences.json",
                available_managed=(
                    {
                        "backend": "mpv",
                        "label": "mpv",
                        "description": "Managed playback",
                        "executable": "/usr/bin/mpv",
                    },
                ),
                which=executable_paths.get,
                launch=lambda command: launched.append(command),
                is_process_running=lambda executable: False,
                validate_command_player=lambda _adapter_id: True,
                discover_mpris=lambda: _empty_discovery(),
            )

            options = await manager.options()

            self.assertEqual(
                [option.sink_id for option in options],
                ["managed:mpv", "mpris:rhythmbox"],
            )
            self.assertEqual(launched, [])

    async def test_factory_omits_mineradio_without_a_supported_linux_adapter(self) -> None:
        with TemporaryDirectory() as temporary:
            manager = build_player_sink_manager(
                preferences_path=Path(temporary) / "player-preferences.json",
                available_managed=(),
                which=lambda executable: "/opt/mineradio" if executable == "mineradio" else None,
                launch=lambda command: None,
                is_process_running=lambda executable: False,
                validate_command_player=lambda _adapter_id: True,
                discover_mpris=lambda: _empty_discovery(),
            )

            options = await manager.options()

            self.assertEqual(options, ())


async def _empty_discovery() -> tuple[object, ...]:
    return ()


if __name__ == "__main__":
    unittest.main()
