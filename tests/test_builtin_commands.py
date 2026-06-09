"""Tests test builtin commands.

Contains pytest coverage for the test builtin commands behavior.
"""

from __future__ import annotations

import unittest

from src.api.builtin_commands import command_suggestions, format_help, parse_builtin_command


class BuiltinCommandParserTests(unittest.TestCase):
    """Groups builtin command parser tests tests.

    Collects related assertions for builtin command parser tests behavior.
    """
    def test_ignores_plain_text(self) -> None:
        """Validate test ignores plain text.

        Exercises the test ignores plain text behavior through the test suite.
        """
        self.assertIsNone(parse_builtin_command("recommend music"))

    def test_help_command(self) -> None:
        """Validate test help command.

        Exercises the test help command behavior through the test suite.
        """
        parsed = parse_builtin_command("/help")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.name, "help")
        self.assertEqual(parsed.args, "")
        self.assertTrue(parsed.known)

    def test_model_command(self) -> None:
        """Validate test model command.

        Exercises the test model command behavior through the test suite.
        """
        parsed = parse_builtin_command("/model")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.name, "model")
        self.assertEqual(parsed.args, "")
        self.assertTrue(parsed.known)

    def test_recommend_with_args(self) -> None:
        """Validate test recommend with args.

        Exercises the test recommend with args behavior through the test suite.
        """
        parsed = parse_builtin_command("/recommend 华语女声")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.name, "recommend")
        self.assertEqual(parsed.args, "华语女声")
        self.assertTrue(parsed.known)
        self.assertEqual(parsed.command.mode, "agent")
        intent = parsed.command_intent()
        self.assertIsNotNone(intent)
        assert intent is not None
        self.assertEqual(intent.command, "recommend")
        self.assertEqual(intent.args, "华语女声")
        self.assertIn("spotify_recommend", intent.allowed_tools)

    def test_search_with_query(self) -> None:
        """Validate test search with query.

        Exercises the test search with query behavior through the test suite.
        """
        parsed = parse_builtin_command("/search jay chou")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.name, "search")
        self.assertEqual(parsed.args, "jay chou")
        self.assertTrue(parsed.known)
        intent = parsed.command_intent()
        self.assertIsNotNone(intent)
        assert intent is not None
        self.assertNotIn("play_youtube_song", intent.allowed_tools)

    def test_play_number_is_plain_query_not_recent_result_intent(self) -> None:
        """Validate test play number is plain query not recent result intent.

        Exercises the test play number is plain query not recent result intent behavior through the test suite.
        """
        parsed = parse_builtin_command("/play 1")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.name, "play")
        self.assertEqual(parsed.args, "1")
        self.assertTrue(parsed.known)
        self.assertIsNone(parsed.command_intent())

    def test_volume_and_player_are_local_commands(self) -> None:
        """Validate test volume and player are local commands.

        Exercises the test volume and player are local commands behavior through the test suite.
        """
        volume = parse_builtin_command("/volume 50")
        player = parse_builtin_command("/player cvlc")

        self.assertIsNotNone(volume)
        self.assertIsNotNone(player)
        assert volume is not None
        assert player is not None
        self.assertTrue(volume.known)
        self.assertTrue(player.known)
        self.assertIsNone(volume.command_intent())
        self.assertIsNone(player.command_intent())
        self.assertEqual(volume.args, "50")
        self.assertEqual(player.args, "cvlc")

    def test_random_includes_online_playback_fallback(self) -> None:
        """Validate test random includes online playback fallback.

        Exercises the test random includes online playback fallback behavior through the test suite.
        """
        parsed = parse_builtin_command("/random")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        intent = parsed.command_intent()
        self.assertIsNotNone(intent)
        assert intent is not None
        self.assertIn("spotify_recent_tracks", intent.allowed_tools)
        self.assertIn("apple_music_recent_tracks", intent.allowed_tools)
        self.assertIn("spotify_play", intent.allowed_tools)
        self.assertIn("apple_music_play", intent.allowed_tools)
        self.assertIn("play_youtube_song", intent.allowed_tools)

    def test_setup_provider(self) -> None:
        """Validate test setup provider.

        Exercises the test setup provider behavior through the test suite.
        """
        parsed = parse_builtin_command("/setup spotify")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.name, "setup")
        self.assertEqual(parsed.args, "spotify")
        self.assertTrue(parsed.known)

    def test_bye_command_and_aliases(self) -> None:
        """Validate test bye command and aliases.

        Exercises the test bye command and aliases behavior through the test suite.
        """
        for text in ("/bye", "/exit"):
            with self.subTest(text=text):
                parsed = parse_builtin_command(text)
                self.assertIsNotNone(parsed)
                assert parsed is not None
                self.assertEqual(parsed.command.name, "bye")
                self.assertTrue(parsed.known)

    def test_quit_command(self) -> None:
        """Validate test quit command.

        Exercises the test quit command behavior through the test suite.
        """
        parsed = parse_builtin_command("/quit")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.command.name, "quit")
        self.assertTrue(parsed.known)

    def test_logout_command(self) -> None:
        """Validate test logout command.

        Exercises the test logout command behavior through the test suite.
        """
        parsed = parse_builtin_command("/logout")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.command.name, "logout")
        self.assertTrue(parsed.known)

    def test_unknown_command(self) -> None:
        """Validate test unknown command.

        Exercises the test unknown command behavior through the test suite.
        """
        parsed = parse_builtin_command("/foo")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.name, "foo")
        self.assertFalse(parsed.known)

    def test_prefix_suggestions(self) -> None:
        """Validate test prefix suggestions.

        Exercises the test prefix suggestions behavior through the test suite.
        """
        self.assertEqual([command.name for command in command_suggestions("/re")], ["recommend", "resume"])
        self.assertIn("bye", [command.name for command in command_suggestions("/b")])
        self.assertIn("/recommend", format_help("re"))
        self.assertIn("/bye", format_help())
        self.assertIn("/model", format_help())
        self.assertIn("/quit", format_help())
        self.assertEqual([command.name for command in command_suggestions("/log")], ["logout"])
        self.assertIn("/logout", format_help("log"))

    def test_suggestions_are_sorted(self) -> None:
        """Validate test suggestions are sorted.

        Exercises the test suggestions are sorted behavior through the test suite.
        """
        all_names = [command.name for command in command_suggestions()]
        self.assertEqual(all_names, sorted(all_names))

        r_names = [command.name for command in command_suggestions("/r")]
        self.assertEqual(r_names, sorted(r_names))

    def test_help_usages_and_descriptions_are_concise(self) -> None:
        """Validate test help usages and descriptions are concise.

        Exercises the test help usages and descriptions are concise behavior through the test suite.
        """
        commands = {command.name: command for command in command_suggestions()}

        self.assertEqual(commands["play"].usage, "/play <query>")
        self.assertEqual(commands["play"].description, "Play a song by query.")
        self.assertEqual(commands["recommend"].description, "Recommend songs of preferred music taste.")
        self.assertEqual(commands["search"].description, "Search songs by keywords.")

    def test_local_commands_are_marked_local(self) -> None:
        """Validate test local commands are marked local.

        Exercises the test local commands are marked local behavior through the test suite.
        """
        commands = {command.name: command for command in command_suggestions()}

        for name in ["help", "model", "logout", "setup", "bye", "quit", "volume", "player"]:
            with self.subTest(name=name):
                self.assertEqual(commands[name].mode, "local")


if __name__ == "__main__":
    unittest.main()
