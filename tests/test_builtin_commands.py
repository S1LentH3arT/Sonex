"""Tests test builtin commands.

Contains pytest coverage for the test builtin commands behavior.
"""

from __future__ import annotations

import unittest

from src.api.builtin_commands import command_suggestions, format_help, parse_builtin_command


class BuiltinCommandParserTests(unittest.TestCase):
    """Groups related builtin command parser tests cases.

    Collects assertions that exercise builtin command parser tests behavior without mixing unrelated fixtures.
    """
    def test_ignores_plain_text(self) -> None:
        """Verifies that ignores plain text behaves as expected.

        Typical use: Use this in automated tests when guarding the ignores plain text behavior against regressions.

        Example: test_ignores_plain_text() -> passes without assertion failures when the behavior remains correct.
        """
        self.assertIsNone(parse_builtin_command("recommend music"))

    def test_help_command(self) -> None:
        """Verifies that help command behaves as expected.

        Typical use: Use this in automated tests when guarding the help command behavior against regressions.

        Example: test_help_command() -> passes without assertion failures when the behavior remains correct.
        """
        parsed = parse_builtin_command("/help")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.name, "help")
        self.assertEqual(parsed.args, "")
        self.assertTrue(parsed.known)

    def test_model_command(self) -> None:
        """Verifies that model command behaves as expected.

        Typical use: Use this in automated tests when guarding the model command behavior against regressions.

        Example: test_model_command() -> passes without assertion failures when the behavior remains correct.
        """
        parsed = parse_builtin_command("/model")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.name, "model")
        self.assertEqual(parsed.args, "")
        self.assertTrue(parsed.known)

    def test_recommend_with_args(self) -> None:
        """Verifies that recommend with args behaves as expected.

        Typical use: Use this in automated tests when guarding the recommend with args behavior against regressions.

        Example: test_recommend_with_args() -> passes without assertion failures when the behavior remains correct.
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
        """Verifies that search with query behaves as expected.

        Typical use: Use this in automated tests when guarding the search with query behavior against regressions.

        Example: test_search_with_query() -> passes without assertion failures when the behavior remains correct.
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
        """Verifies that play number is plain query not recent result intent behaves as expected.

        Typical use: Use this in automated tests when guarding the play number is plain query not recent result intent behavior against regressions.

        Example: test_play_number_is_plain_query_not_recent_result_intent() -> passes without assertion failures when the behavior remains correct.
        """
        parsed = parse_builtin_command("/play 1")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.name, "play")
        self.assertEqual(parsed.args, "1")
        self.assertTrue(parsed.known)
        self.assertIsNone(parsed.command_intent())

    def test_volume_is_internal_and_player_is_public_local_command(self) -> None:
        """Verifies that volume and player are local commands behaves as expected.

        Typical use: Use this in automated tests when guarding the volume and player are local commands behavior against regressions.

        Example: test_volume_and_player_are_local_commands() -> passes without assertion failures when the behavior remains correct.
        """
        volume = parse_builtin_command("/volume 50")
        player = parse_builtin_command("/player cvlc")

        self.assertIsNotNone(volume)
        self.assertIsNotNone(player)
        assert volume is not None
        assert player is not None
        self.assertTrue(volume.known)
        self.assertTrue(player.known)
        self.assertFalse(volume.command.visible)
        self.assertTrue(player.command.visible)
        self.assertIsNone(volume.command_intent())
        self.assertIsNone(player.command_intent())
        self.assertEqual(volume.args, "50")
        self.assertEqual(player.args, "cvlc")

        commands = {command.name: command for command in command_suggestions()}
        self.assertEqual(commands["player"].usage, "/player")
        self.assertEqual(commands["player"].description, "Choose playback backend from a panel.")

    def test_playback_control_commands_are_hidden_from_help_and_suggestions(self) -> None:
        hidden_names = {"pause", "volume", "progress", "stop"}
        public_names = {command.name for command in command_suggestions()}

        self.assertTrue(hidden_names.isdisjoint(public_names))
        self.assertEqual(command_suggestions("/pa"), [])
        self.assertNotIn("/pause", format_help())
        self.assertNotIn("/volume", format_help())

        for text in ("/pause", "/volume 50", "/progress", "/stop"):
            with self.subTest(text=text):
                parsed = parse_builtin_command(text)
                self.assertIsNotNone(parsed)
                assert parsed is not None
                self.assertTrue(parsed.known)
                self.assertFalse(parsed.command.visible)

    def test_keymap_is_local_tui_command_metadata(self) -> None:
        parsed = parse_builtin_command("/keymap off")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.name, "keymap")
        self.assertEqual(parsed.args, "off")
        self.assertTrue(parsed.known)
        self.assertIsNone(parsed.command_intent())

        commands = {command.name: command for command in command_suggestions()}
        self.assertEqual(commands["keymap"].usage, "/keymap [on|off|toggle|status]")
        self.assertEqual(commands["keymap"].description, "Toggle mini-player playback shortcuts.")

    def test_lang_is_visible_local_tui_command_metadata(self) -> None:
        parsed = parse_builtin_command("/lang zh-CN")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.name, "lang")
        self.assertEqual(parsed.args, "zh-CN")
        self.assertTrue(parsed.known)
        self.assertEqual(parsed.command.mode, "local")
        self.assertTrue(parsed.command.visible)
        self.assertIsNone(parsed.command_intent())

        commands = {command.name: command for command in command_suggestions()}
        self.assertEqual(commands["lang"].usage, "/lang")
        self.assertEqual(commands["lang"].description, "Choose the TUI display language.")

    def test_playlist_and_queue_are_local_commands(self) -> None:
        playlist = parse_builtin_command("/playlist save likes")
        queue = parse_builtin_command("/queue")

        self.assertIsNotNone(playlist)
        self.assertIsNotNone(queue)
        assert playlist is not None
        assert queue is not None
        self.assertTrue(playlist.known)
        self.assertTrue(queue.known)
        self.assertEqual(playlist.name, "playlist")
        self.assertEqual(playlist.args, "save likes")
        self.assertEqual(queue.name, "queue")
        self.assertIsNone(playlist.command_intent())
        self.assertIsNone(queue.command_intent())

        commands = {command.name: command for command in command_suggestions()}
        self.assertEqual(commands["playlist"].usage, "/playlist [name]|save [name]")
        self.assertEqual(commands["queue"].usage, "/queue")

    def test_random_includes_online_playback_fallback(self) -> None:
        """Verifies that random includes online playback fallback behaves as expected.

        Typical use: Use this in automated tests when guarding the random includes online playback fallback behavior against regressions.

        Example: test_random_includes_online_playback_fallback() -> passes without assertion failures when the behavior remains correct.
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
        """Verifies that setup provider behaves as expected.

        Typical use: Use this in automated tests when guarding the setup provider behavior against regressions.

        Example: test_setup_provider() -> passes without assertion failures when the behavior remains correct.
        """
        parsed = parse_builtin_command("/setup spotify")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.name, "setup")
        self.assertEqual(parsed.args, "spotify")
        self.assertTrue(parsed.known)

    def test_bye_command_and_aliases(self) -> None:
        """Verifies that bye command and aliases behaves as expected.

        Typical use: Use this in automated tests when guarding the bye command and aliases behavior against regressions.

        Example: test_bye_command_and_aliases() -> passes without assertion failures when the behavior remains correct.
        """
        for text in ("/bye", "/exit"):
            with self.subTest(text=text):
                parsed = parse_builtin_command(text)
                self.assertIsNotNone(parsed)
                assert parsed is not None
                self.assertEqual(parsed.command.name, "bye")
                self.assertTrue(parsed.known)

    def test_quit_command(self) -> None:
        """Verifies that quit command behaves as expected.

        Typical use: Use this in automated tests when guarding the quit command behavior against regressions.

        Example: test_quit_command() -> passes without assertion failures when the behavior remains correct.
        """
        parsed = parse_builtin_command("/quit")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.command.name, "quit")
        self.assertTrue(parsed.known)

    def test_logout_command(self) -> None:
        """Verifies that logout command behaves as expected.

        Typical use: Use this in automated tests when guarding the logout command behavior against regressions.

        Example: test_logout_command() -> passes without assertion failures when the behavior remains correct.
        """
        parsed = parse_builtin_command("/logout")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.command.name, "logout")
        self.assertTrue(parsed.known)

    def test_unknown_command(self) -> None:
        """Verifies that unknown command behaves as expected.

        Typical use: Use this in automated tests when guarding the unknown command behavior against regressions.

        Example: test_unknown_command() -> passes without assertion failures when the behavior remains correct.
        """
        parsed = parse_builtin_command("/foo")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.name, "foo")
        self.assertFalse(parsed.known)

    def test_prefix_suggestions(self) -> None:
        """Verifies that prefix suggestions behaves as expected.

        Typical use: Use this in automated tests when guarding the prefix suggestions behavior against regressions.

        Example: test_prefix_suggestions() -> passes without assertion failures when the behavior remains correct.
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
        """Verifies that suggestions are sorted behaves as expected.

        Typical use: Use this in automated tests when guarding the suggestions are sorted behavior against regressions.

        Example: test_suggestions_are_sorted() -> passes without assertion failures when the behavior remains correct.
        """
        all_names = [command.name for command in command_suggestions()]
        self.assertEqual(all_names, sorted(all_names))

        r_names = [command.name for command in command_suggestions("/r")]
        self.assertEqual(r_names, sorted(r_names))

    def test_help_usages_and_descriptions_are_concise(self) -> None:
        """Verifies that help usages and descriptions are concise behaves as expected.

        Typical use: Use this in automated tests when guarding the help usages and descriptions are concise behavior against regressions.

        Example: test_help_usages_and_descriptions_are_concise() -> passes without assertion failures when the behavior remains correct.
        """
        commands = {command.name: command for command in command_suggestions()}

        self.assertEqual(commands["play"].usage, "/play <query>")
        self.assertEqual(commands["play"].description, "Play a song by query.")
        self.assertEqual(commands["recommend"].description, "Recommend songs of preferred music taste.")
        self.assertEqual(commands["search"].description, "Search songs by keywords.")

    def test_local_commands_are_marked_local(self) -> None:
        """Verifies that local commands are markedlocal behaves as expected.

        Typical use: Use this in automated tests when guarding the local commands are markedlocal behavior against regressions.

        Example: test_local_commands_are_marked_local() -> passes without assertion failures when the behavior remains correct.
        """
        commands = {command.name: command for command in command_suggestions()}

        for name in ["help", "model", "logout", "setup", "bye", "quit", "player", "keymap", "lang"]:
            with self.subTest(name=name):
                self.assertEqual(commands[name].mode, "local")


if __name__ == "__main__":
    unittest.main()
