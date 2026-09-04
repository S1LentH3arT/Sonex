from __future__ import annotations

import unittest

from src.music.player_command_policy import (
    application_command,
    audacious_control,
    clementine_control,
    helper_command,
    rhythmbox_control,
)


class PlayerCommandPolicyTests(unittest.TestCase):
    def test_application_command_wraps_flatpak_targets(self) -> None:
        self.assertEqual(
            application_command(
                "flatpak:org.gnome.Rhythmbox3",
                "--play-uri",
                "file:///tmp/song.wav",
                flatpak_executable="/usr/bin/flatpak",
            ),
            (
                "/usr/bin/flatpak",
                "run",
                "org.gnome.Rhythmbox3",
                "--play-uri",
                "file:///tmp/song.wav",
            ),
        )

    def test_external_control_commands_preserve_player_specific_flags(self) -> None:
        self.assertEqual(
            clementine_control("/usr/bin/clementine", "volume", 40, flatpak_executable=None),
            ("/usr/bin/clementine", "--volume", "40"),
        )
        self.assertEqual(
            rhythmbox_control("/usr/bin/rhythmbox", "volume", 40, flatpak_executable=None),
            ("/usr/bin/rhythmbox", "--set-volume", "0.4"),
        )
        self.assertIsNone(clementine_control("clementine", "status", None, flatpak_executable=None))

    def test_audacious_uses_audtool_or_flatpak_helper(self) -> None:
        self.assertEqual(
            audacious_control(
                "/usr/bin/audacious",
                "pause",
                None,
                flatpak_executable=None,
                which=lambda name: "/usr/bin/audtool" if name == "audtool" else None,
                desktop_executables={},
            ),
            ("/usr/bin/audtool", "playback-pause"),
        )
        self.assertEqual(
            helper_command(
                "flatpak:org.atheme.audacious",
                "audtool",
                "playback-stop",
                flatpak_executable="/usr/bin/flatpak",
                which=lambda _name: None,
                desktop_executables={},
            ),
            (
                "/usr/bin/flatpak",
                "run",
                "--command=audtool",
                "org.atheme.audacious",
                "playback-stop",
            ),
        )


if __name__ == "__main__":
    unittest.main()
