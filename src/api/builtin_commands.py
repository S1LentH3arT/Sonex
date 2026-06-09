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
        """Known for parsed command.

        Coordinates the known method behavior while preserving parsed command state and contracts.

        Returns:
            The computed result for known.
        """
        return self.command is not None

    def command_intent(self) -> CommandIntent | None:
        """Command intent for parsed command.

        Coordinates the command intent method behavior while preserving parsed command state and contracts.

        Returns:
            The computed result for command intent.
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
    BuiltinCommand("model", "/model", "Switch the active model for this session."),
    BuiltinCommand("logout", "/logout", "Log out current LLM provider and exit."),
    BuiltinCommand("pause", "/pause", "Pause current local playback."),
    BuiltinCommand("resume", "/resume", "Resume current local playback."),
    BuiltinCommand("stop", "/stop", "Stop current local playback."),
    BuiltinCommand("progress", "/progress", "Show current local playback progress."),
    BuiltinCommand("volume", "/volume <0-100>", "Set current local playback volume."),
    BuiltinCommand("player", "/player <auto|mpv|cvlc>", "Set local playback backend strategy."),
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
            "apple_music_recommend",
            "spotify_recent_tracks",
            "apple_music_recent_tracks",
            "spotify_search",
            "apple_music_search",
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
            "apple_music_recent_tracks",
            "spotify_play",
            "apple_music_play",
            "play_youtube_song",
        ),
    ),
    BuiltinCommand(
        "search",
        "/search <query>",
        "Search songs by keywords.",
        mode="agent",
        intent_prompt=(
            "The user invoked /search. Treat the args as the search query and prefer track search tools. "
            "If args are missing, ask for a query instead of inventing one."
        ),
        allowed_tools=("spotify_search", "search_track", "apple_music_search"),
    ),
    BuiltinCommand(
        "play",
        "/play <query>",
        "Play a song by query.",
    ),
    BuiltinCommand("setup", "/setup [provider]", "Configure a music provider."),
    BuiltinCommand("bye", "/bye", "Save the current session and exit safely.", aliases=("exit",)),
    BuiltinCommand("quit", "/quit", "Save the current session and exit safely."),
)

_COMMANDS_BY_NAME = {
    alias: command
    for command in BUILTIN_COMMANDS
    for alias in (command.name, *command.aliases)
}


def parse_builtin_command(text: str) -> ParsedCommand | None:
    """Parse builtin command.

    Coordinates parse builtin command logic for the surrounding Sonex flow.

    Args:
        text: Input value used by the parse builtin command operation.

    Returns:
        The computed result for parse builtin command.
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
    """Command suggestions.

    Coordinates command suggestions logic for the surrounding Sonex flow.

    Args:
        prefix: Input value used by the command suggestions operation.

    Returns:
        The computed result for command suggestions.
    """
    normalized = prefix.strip().lower().removeprefix("/")
    commands = sorted(BUILTIN_COMMANDS, key=lambda command: command.name.lower())
    if not normalized:
        return list(commands)
    return [
        command
        for command in commands
        if command.name.startswith(normalized)
        or any(alias.startswith(normalized) for alias in command.aliases)
    ]


def format_help(prefix: str = "") -> str:
    """Format help.

    Coordinates format help logic for the surrounding Sonex flow.

    Args:
        prefix: Input value used by the format help operation.

    Returns:
        The computed result for format help.
    """
    commands = command_suggestions(prefix)
    if not commands:
        return "Unknown command. Type /help to see available commands."
    rows = [f"{command.usage} - {command.description}" for command in commands]
    return "Available commands:\n" + "\n".join(rows)
