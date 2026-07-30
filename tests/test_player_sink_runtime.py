from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from src.music import player_sink_runtime as runtime
from src.music.player_sinks import PlayerSinkPlayback
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

    async def test_factory_merges_trusted_desktop_and_flatpak_installations(self) -> None:
        with TemporaryDirectory() as temporary:
            manager = build_player_sink_manager(
                preferences_path=Path(temporary) / "player-preferences.json",
                available_managed=(),
                which=lambda executable: (
                    "/usr/bin/flatpak" if executable == "flatpak" else None
                ),
                launch=lambda command: None,
                is_process_running=lambda executable: False,
                validate_command_player=lambda _adapter_id: True,
                discover_mpris=lambda: _empty_discovery(),
                desktop_executables={
                    "clementine": "/opt/clementine/clementine",
                },
                flatpak_applications=frozenset({"org.gnome.Rhythmbox3"}),
            )

            options = await manager.options()

            self.assertEqual(
                [option.sink_id for option in options],
                ["mpris:clementine", "mpris:rhythmbox"],
            )

    async def test_factory_disables_native_audacious_without_audtool(self) -> None:
        with TemporaryDirectory() as temporary:
            manager = build_player_sink_manager(
                preferences_path=Path(temporary) / "player-preferences.json",
                available_managed=(),
                which=lambda executable: (
                    "/usr/bin/audacious" if executable == "audacious" else None
                ),
                launch=lambda command: None,
                is_process_running=lambda executable: False,
                validate_command_player=lambda _adapter_id: True,
                discover_mpris=lambda: _empty_discovery(),
                desktop_executables={},
                flatpak_applications=frozenset(),
            )

            (option,) = await manager.options()

            self.assertEqual(option.sink_id, "mpris:audacious")
            self.assertTrue(option.disabled)
            self.assertEqual(option.disabled_reason, "Playback control unavailable")

    def test_persisted_runtime_reuses_manager_until_preferences_change(self) -> None:
        class FakeManager:
            default_sink_id = "mpris:rhythmbox"
            pending_sink_id = None

            async def control(
                self,
                action: str,
                value: int | None = None,
            ) -> PlayerSinkPlayback:
                return PlayerSinkPlayback(
                    sink_id=self.default_sink_id,
                    state={"player": "Rhythmbox", "is_playing": action == "resume"},
                )

        with TemporaryDirectory() as temporary:
            preferences = Path(temporary) / "player-preferences.json"
            preferences.write_text(
                '{"version":1,"default_sink_id":"mpris:rhythmbox"}',
                encoding="utf-8",
            )
            build_calls: list[Path] = []

            def build(*, preferences_path: Path) -> FakeManager:
                build_calls.append(preferences_path)
                return FakeManager()

            with (
                patch.object(runtime, "_player_preferences_path", return_value=preferences),
                patch.object(runtime, "build_player_sink_manager", side_effect=build),
                patch.object(runtime, "_RUNTIME_MANAGER", None),
                patch.object(runtime, "_RUNTIME_PREFERENCES_PATH", None),
                patch.object(runtime, "_RUNTIME_PREFERENCES_REVISION", None),
            ):
                runtime.control_persisted_player_sink("pause")
                runtime.control_persisted_player_sink("resume")
                self.assertEqual(build_calls, [preferences])

                preferences.write_text(
                    '{"version":1,"default_sink_id":"managed:mpv"}',
                    encoding="utf-8",
                )
                runtime.control_persisted_player_sink("status")

            self.assertEqual(build_calls, [preferences, preferences])


async def _empty_discovery() -> tuple[object, ...]:
    return ()


if __name__ == "__main__":
    unittest.main()
