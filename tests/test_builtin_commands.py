"""Tests test builtin commands.

Contains pytest coverage for the test builtin commands behavior.
"""

from __future__ import annotations

import unittest

from src.api.builtin_commands import BUILTIN_COMMANDS, command_suggestions, format_help, parse_builtin_command


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

    def test_info_command_is_visible_local_metadata(self) -> None:
        parsed = parse_builtin_command("/info")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.name, "info")
        self.assertEqual(parsed.args, "")
        self.assertTrue(parsed.known)
        self.assertEqual(parsed.command.mode, "local")
        self.assertTrue(parsed.command.visible)
        self.assertIsNone(parsed.command_intent())

        commands = {command.name: command for command in command_suggestions()}
        self.assertEqual(commands["info"].usage, "/info")
        self.assertEqual(commands["info"].description, "show current runtime information")
        self.assertIn("/info", format_help())

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
        self.assertEqual(intent.allowed_tools, ("Recommend",))
        self.assertEqual(intent.max_tool_calls, 1)

    def test_play_and_search_are_not_user_level_commands(self) -> None:
        """Verifies that play and search are not public slash commands.

        Typical use: Use this in automated tests when guarding the public command surface against regressions.

        Example: test_play_and_search_are_not_user_level_commands() -> passes without assertion failures when the behavior remains correct.
        """
        search = parse_builtin_command("/search jay chou")
        play = parse_builtin_command("/play 1")

        self.assertIsNotNone(search)
        self.assertIsNotNone(play)
        assert search is not None
        assert play is not None
        self.assertFalse(search.known)
        self.assertFalse(play.known)
        self.assertIsNone(search.command_intent())
        self.assertIsNone(play.command_intent())

        commands = {command.name: command for command in command_suggestions()}
        self.assertNotIn("search", commands)
        self.assertNotIn("play", commands)

    def test_volume_is_internal_and_player_command_is_removed(self) -> None:
        volume = parse_builtin_command("/volume 50")
        player = parse_builtin_command("/player")

        self.assertIsNotNone(volume)
        self.assertIsNotNone(player)
        assert volume is not None
        assert player is not None
        self.assertTrue(volume.known)
        self.assertFalse(player.known)
        self.assertFalse(volume.command.visible)
        self.assertIsNone(volume.command_intent())
        self.assertIsNone(player.command_intent())
        self.assertEqual(volume.args, "50")

        commands = {command.name: command for command in command_suggestions()}
        self.assertNotIn("player", commands)

    def test_connect_is_a_visible_interactive_local_command(self) -> None:
        parsed = parse_builtin_command("/connect spotify")

        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertTrue(parsed.known)
        self.assertEqual(parsed.args, "spotify")
        self.assertIsNone(parsed.command_intent())
        commands = {command.name: command for command in command_suggestions()}
        self.assertEqual(commands["connect"].usage, "/connect")
        self.assertEqual(
            commands["connect"].description,
            "connect a supported music account",
        )

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
        self.assertEqual(commands["keymap"].description, "enable or disable mini-player playback shortcuts")

    def test_lang_definition_is_retained_but_disabled(self) -> None:
        parsed = parse_builtin_command("/lang zh-CN")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.name, "lang")
        self.assertEqual(parsed.args, "zh-CN")
        self.assertFalse(parsed.known)
        self.assertIsNone(parsed.command_intent())

        definition = next(command for command in BUILTIN_COMMANDS if command.name == "lang")
        self.assertFalse(definition.enabled)
        self.assertTrue(definition.visible)
        commands = {command.name: command for command in command_suggestions()}
        self.assertNotIn("lang", commands)
        self.assertNotIn("/lang", format_help())

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

    def test_spotify_mode_is_visible_local_command(self) -> None:
        parsed = parse_builtin_command("/spotify off")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertTrue(parsed.known)
        self.assertEqual(parsed.name, "spotify")
        self.assertEqual(parsed.args, "off")
        self.assertEqual(parsed.command.mode, "local")
        self.assertTrue(parsed.command.visible)
        self.assertIsNone(parsed.command_intent())

        commands = {command.name: command for command in command_suggestions()}
        self.assertEqual(commands["spotify"].usage, "/spotify")
        self.assertEqual(commands["spotify"].description, "enter or exit persistent Spotify mode")

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
        self.assertEqual(intent.allowed_tools, ("Query", "Call"))

    def test_sandbox_replaces_setup_provider_command(self) -> None:
        """Verifies that sandbox is local and the legacy setup command is retired.

        Typical use: Use this in automated tests when guarding the setup provider behavior against regressions.

        Example: test_setup_provider() -> passes without assertion failures when the behavior remains correct.
        """
        sandbox = parse_builtin_command("/sandbox")
        setup = parse_builtin_command("/setup spotify")
        self.assertIsNotNone(sandbox)
        self.assertIsNotNone(setup)
        assert sandbox is not None
        assert setup is not None
        self.assertTrue(sandbox.known)
        self.assertEqual(sandbox.command.usage, "/sandbox")
        self.assertFalse(setup.known)

    def test_bye_command(self) -> None:
        """Verifies that the bye command behaves as expected.

        Typical use: Use this in automated tests when guarding the bye command behavior against regressions.

        Example: test_bye_command() -> passes without assertion failures when the behavior remains correct.
        """
        parsed = parse_builtin_command("/bye")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.command.name, "bye")
        self.assertTrue(parsed.known)

    def test_exit_replaces_quit_command(self) -> None:
        """Verifies that exit replaces the retired quit command.

        Typical use: Use this in automated tests when guarding the exit command behavior against regressions.

        Example: test_exit_replaces_quit_command() -> passes without assertion failures when the behavior remains correct.
        """
        exit_command = parse_builtin_command("/exit")
        self.assertIsNotNone(exit_command)
        assert exit_command is not None
        self.assertEqual(exit_command.command.name, "exit")
        self.assertTrue(exit_command.known)

        quit_command = parse_builtin_command("/quit")
        self.assertIsNotNone(quit_command)
        assert quit_command is not None
        self.assertFalse(quit_command.known)

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
        self.assertIn("/exit", format_help())
        self.assertIn("/model", format_help())
        self.assertNotIn("/quit", format_help())
        self.assertEqual([command.name for command in command_suggestions("/log")], ["login", "logout"])
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

        self.assertEqual(commands["recommend"].description, "recommend songs based on a taste hint")
        for command in commands.values():
            self.assertEqual(command.description[0], command.description[0].lower())
            self.assertFalse(command.description.endswith("."))
        self.assertNotIn("play", commands)
        self.assertNotIn("search", commands)

    def test_local_commands_are_marked_local(self) -> None:
        """Verifies that local commands are markedlocal behaves as expected.

        Typical use: Use this in automated tests when guarding the local commands are markedlocal behavior against regressions.

        Example: test_local_commands_are_marked_local() -> passes without assertion failures when the behavior remains correct.
        """
        commands = {command.name: command for command in command_suggestions()}

        for name in ["help", "info", "model", "logout", "sandbox", "bye", "exit", "keymap"]:
            with self.subTest(name=name):
                self.assertEqual(commands[name].mode, "local")


if __name__ == "__main__":
    unittest.main()
