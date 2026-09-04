from __future__ import annotations

import unittest

from src.api.builtin_commands import command_suggestions, parse_builtin_command


class ExtensionCommandMigrationTests(unittest.TestCase):
    def test_connect_is_unknown_and_not_discoverable(self) -> None:
        parsed = parse_builtin_command("/connect")

        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertFalse(parsed.known)
        self.assertNotIn("connect", {command.name for command in command_suggestions()})

    def test_extension_is_the_parameterless_music_lifecycle_command(self) -> None:
        parsed = parse_builtin_command("/extension")

        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertTrue(parsed.known)
        self.assertEqual(parsed.name, "extension")
        self.assertEqual(parsed.args, "")


if __name__ == "__main__":
    unittest.main()
