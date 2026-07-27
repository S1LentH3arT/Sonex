"""Builtin commands support for fastapi and websocket routing for the sonex runtime.

Implements the builtin_commands module responsibilities used by Sonex runtime flows.
Key public entry points include BuiltinCommand, CommandIntent, ParsedCommand, parse_builtin_command, command_suggestions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class BuiltinCommand:
    """Represents builtin command.

    Encapsulates builtin command data and behavior used by Sonex runtime flows.
    """
    name: str
    usage: str
    description: str
    aliases: tuple[str, ...] = ()
    mode: Literal["local", "agent"] = "local"
    intent_prompt: str | None = None
    allowed_tools: tuple[str, ...] = ()
    visible: bool = True


@dataclass(frozen=True)
class CommandIntent:
    """Represents command intent.

    Encapsulates command intent data and behavior used by Sonex runtime flows.
    """
    command: str
    raw: str
    args: str
    intent_prompt: str
    allowed_tools: tuple[str, ...] = ()


@dataclass(frozen=True)
class ParsedCommand:
    """Represents parsed command.

    Encapsulates parsed command data and behavior used by Sonex runtime flows.
    """
    raw: str
    name: str
    args: str
    command: BuiltinCommand | None

    @property
    def known(self) -> bool:
        """Coordinates known for the current Sonex flow.

        Typical use: Use this function when runtime code needs known as part of a Sonex command, playback, auth, llm, or ui path.

        Example: known() -> returns the value used by the surrounding Sonex flow.
        """
        return self.command is not None

    def command_intent(self) -> CommandIntent | None:
        """Coordinates command intent for the current Sonex flow.

        Typical use: Use this function when runtime code needs command intent as part of a Sonex command, playback, auth, llm, or ui path.

        Example: command_intent() -> returns the value used by the surrounding Sonex flow.
        """
        if self.command is None or self.command.mode != "agent":
            return None
        return CommandIntent(
            command=self.command.name,
            raw=self.raw,
            args=self.args,
            intent_prompt=self.command.intent_prompt or "",
            allowed_tools=self.command.allowed_tools,
        )


BUILTIN_COMMANDS: tuple[BuiltinCommand, ...] = (
    BuiltinCommand("help", "/help", "Show available Sonex commands.", aliases=("?",)),
    BuiltinCommand("info", "/info", "Show current runtime information."),
    BuiltinCommand("keymap", "/keymap [on|off|toggle|status]", "Toggle mini-player playback shortcuts."),
    BuiltinCommand("lang", "/lang", "Choose the TUI display language."),
    BuiltinCommand("model", "/model", "Switch the active model for this session."),
    BuiltinCommand("logout", "/logout", "Log out current LLM provider and exit."),
    BuiltinCommand("playlist", "/playlist [name]|save [name]", "Browse playlists or save the current song."),
    BuiltinCommand("queue", "/queue", "Show the playback queue."),
    BuiltinCommand("apple", "/apple [off]", "Enter or exit persistent Apple Mode."),
    BuiltinCommand("spotify", "/spotify [off]", "Enter or exit persistent Spotify mode."),
    BuiltinCommand("pause", "/pause", "Pause current local playback.", visible=False),
    BuiltinCommand("resume", "/resume", "Resume current local playback."),
    BuiltinCommand("stop", "/stop", "Stop current local playback.", visible=False),
    BuiltinCommand("progress", "/progress", "Show current local playback progress.", visible=False),
    BuiltinCommand("next", "/next", "Skip to the next provider track.", visible=False),
    BuiltinCommand("previous", "/previous", "Return to the previous provider track.", visible=False),
    BuiltinCommand("volume", "/volume <0-100>", "Set current local playback volume.", visible=False),
    BuiltinCommand("player", "/player", "Choose playback backend from a panel."),
    BuiltinCommand(
        "recommend",
        "/recommend [taste]",
        "Recommend songs of preferred music taste.",
        aliases=("rec",),
        mode="agent",
        intent_prompt=(
            "The user invoked /recommend. Treat the args as a music taste hint. "
            "Prefer recommendation tools, return a concise numbered text list, and end with a normal "
            "question about what the user wants to hear. Do not start playback."
        ),
        allowed_tools=(
            "spotify_recommend",
            "spotify_recent_tracks",
            "spotify_search",
        ),
    ),
    BuiltinCommand(
        "random",
        "/random",
        "Play a random song from your recent Sonex queue.",
        mode="agent",
        intent_prompt=(
            "The user invoked /random. Choose a track from recent listening or cached queue context, "
            "then prefer Spotify or Apple Music playback. If platform playback is not viable, "
            "fall back to online playback with play_youtube_song using the selected title and artist."
        ),
        allowed_tools=(
            "spotify_recent_tracks",
            "spotify_play",
            "play_youtube_song",
        ),
    ),
    BuiltinCommand("setup", "/setup [provider]", "Configure a music provider."),
    BuiltinCommand("bye", "/bye", "Save the current session and exit safely."),
    BuiltinCommand("exit", "/exit", "Save the current session and exit safely."),
)

_COMMANDS_BY_NAME = {
    alias: command
    for command in BUILTIN_COMMANDS
    for alias in (command.name, *command.aliases)
}


def parse_builtin_command(text: str) -> ParsedCommand | None:
    """Parses builtin command into structured data.

    Typical use: Use this function when runtime code needs parse builtin command as part of a Sonex command, playback, auth, llm, or ui path.

    Example: parse_builtin_command("/help") -> ParsedCommand(name="help", args="", known=True).
    """
    stripped = text.strip()
    if not stripped.startswith("/"):
        return None

    body = stripped[1:].strip()
    if not body:
        return ParsedCommand(raw=stripped, name="", args="", command=None)

    name, _, args = body.partition(" ")
    normalized = name.strip().lower().replace("-", "_")
    return ParsedCommand(
        raw=stripped,
        name=normalized,
        args=args.strip(),
        command=_COMMANDS_BY_NAME.get(normalized),
    )


def command_suggestions(prefix: str = "") -> list[BuiltinCommand]:
    """Coordinates command suggestions for the current Sonex flow.

    Typical use: Use this function when runtime code needs command suggestions as part of a Sonex command, playback, auth, llm, or ui path.

    Example: command_suggestions(prefix=...) -> returns the value used by the surrounding Sonex flow.
    """
    normalized = prefix.strip().lower().removeprefix("/")
    commands = sorted((command for command in BUILTIN_COMMANDS if command.visible), key=lambda command: command.name.lower())
    if not normalized:
        return list(commands)
    return [
        command
        for command in commands
        if command.name.startswith(normalized)
        or any(alias.startswith(normalized) for alias in command.aliases)
    ]


def format_help(prefix: str = "") -> str:
    """Formats help for display.

    Typical use: Use this function when runtime code needs format help as part of a Sonex command, playback, auth, llm, or ui path.

    Example: format_help(prefix=...) -> returns the value used by the surrounding Sonex flow.
    """
    commands = command_suggestions(prefix)
    if not commands:
        return "Unknown command. Type /help to see available commands."
    rows = [f"{command.usage} - {command.description}" for command in commands]
    return "Available commands:\n" + "\n".join(rows)
