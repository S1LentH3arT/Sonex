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
    enabled: bool = True


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
    BuiltinCommand("help", "/help", "show available Sonex commands", aliases=("?",)),
    BuiltinCommand("info", "/info", "show current runtime information"),
    BuiltinCommand("keymap", "/keymap [on|off|toggle|status]", "enable or disable mini-player playback shortcuts"),
    BuiltinCommand("lang", "/lang", "choose the TUI display language", enabled=False),
    BuiltinCommand("model", "/model", "switch the active model for this session"),
    BuiltinCommand("logout", "/logout", "sign out from the current LLM provider and exit"),
    BuiltinCommand("playlist", "/playlist [name]|save [name]", "browse playlists or save the current song"),
    BuiltinCommand("queue", "/queue", "show the playback queue"),
    BuiltinCommand("apple", "/apple", "enter or exit persistent Apple Mode"),
    BuiltinCommand("connect", "/connect", "connect a supported music account"),
    BuiltinCommand("spotify", "/spotify", "enter or exit persistent Spotify mode"),
    BuiltinCommand("pause", "/pause", "pause current local playback", visible=False),
    BuiltinCommand("resume", "/resume", "resume current local playback"),
    BuiltinCommand("stop", "/stop", "stop current local playback", visible=False),
    BuiltinCommand("progress", "/progress", "show current local playback progress", visible=False),
    BuiltinCommand("next", "/next", "skip to the next provider track", visible=False),
    BuiltinCommand("previous", "/previous", "return to the previous provider track", visible=False),
    BuiltinCommand("volume", "/volume <0-100>", "set current local playback volume", visible=False),
    BuiltinCommand("player", "/player", "detect available players and set the device default"),
    BuiltinCommand(
        "recommend",
        "/recommend [taste]",
        "recommend songs based on a taste hint",
        aliases=("rec",),
        mode="agent",
        intent_prompt=(
            "The user invoked /recommend. Treat the args as a music taste hint. "
            "Use Query and Read to recommend real tracks, return a concise numbered "
            "text list, and end with a normal question about what the user wants to hear. "
            "Do not start playback."
        ),
        allowed_tools=("Read", "Query"),
    ),
    BuiltinCommand(
        "random",
        "/random",
        "play a random song from the recent Sonex queue",
        mode="agent",
        intent_prompt=(
            "The user invoked /random. Use Query to choose a track from recent listening "
            "or queue context, then use Call with playback.select or playback.play."
        ),
        allowed_tools=("Query", "Call"),
    ),
    BuiltinCommand("sandbox", "/sandbox", "check or configure the Agent Bash sandbox"),
    BuiltinCommand("bye", "/bye", "save the current session and exit safely"),
    BuiltinCommand("exit", "/exit", "save the current session and exit safely"),
)

_COMMANDS_BY_NAME = {
    alias: command
    for command in BUILTIN_COMMANDS
    if command.enabled
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
    commands = sorted(
        (command for command in BUILTIN_COMMANDS if command.enabled and command.visible),
        key=lambda command: command.name.lower(),
    )
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
