from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BuiltinCommand:
    name: str
    usage: str
    description: str
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class ParsedCommand:
    raw: str
    name: str
    args: str
    command: BuiltinCommand | None

    @property
    def known(self) -> bool:
        return self.command is not None


BUILTIN_COMMANDS: tuple[BuiltinCommand, ...] = (
    BuiltinCommand("help", "/help", "Show available Sonex commands.", aliases=("?",)),
    BuiltinCommand("model", "/model", "Switch the active model for this session."),
    BuiltinCommand("logout", "/logout", "Log out current LLM provider and exit."),
    BuiltinCommand("recommend", "/recommend [taste]", "Recommend songs from your taste and listening history.", aliases=("rec",)),
    BuiltinCommand("random", "/random", "Play a random song from your recent Sonex queue."),
    BuiltinCommand("search", "/search <query>", "Search songs and refresh the result list."),
    BuiltinCommand("play", "/play <query|number>", "Play a song by query or by current search result number."),
    BuiltinCommand("setup", "/setup [spotify|apple_music]", "Configure a music provider."),
    BuiltinCommand("bye", "/bye", "Save the current session and exit safely.", aliases=("exit",)),
    BuiltinCommand("quit", "/quit", "Save the current session and exit safely."),
)

_COMMANDS_BY_NAME = {
    alias: command
    for command in BUILTIN_COMMANDS
    for alias in (command.name, *command.aliases)
}


def parse_builtin_command(text: str) -> ParsedCommand | None:
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
    commands = command_suggestions(prefix)
    if not commands:
        return "Unknown command. Type /help to see available commands."
    rows = [f"{command.usage} - {command.description}" for command in commands]
    return "Available commands:\n" + "\n".join(rows)
