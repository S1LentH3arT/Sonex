import shlex
from dataclasses import dataclass
from typing import Callable, Any


@dataclass
class CommandResult:
    handled: bool
    message: str = ""
    should_exit: bool = False

@dataclass
class CommandSpec:
    name: str
    help_text: str
    handler: Callable[[list[str], Any], CommandResult]
    aliases: tuple[str, ...] = ()

class CommandRegistry:
    def __int__(self) -> None:
        self._commands: dict[str, CommandSpec] = {}

    def register(self, command: CommandSpec) -> None:
        self._commands[command.name] = command
        for alias in command.aliases:
            self._commands[alias] = command

    def get_help(self) -> str:
        lines = []
        seen = set()
        for name, command in self._commands.items():
            if command in seen:
                continue
            seen.add(command)
            alias_text = f" ({', '.join(command.aliases)})"
            lines.append(f"{command.name}{alias_text} - {command.help_text}")
        return "\n".join(lines)

    def dispatch(self, raw_text: str, app: Any) -> CommandResult:
        text = raw_text.strip()
        if not text.startswith("/"):
            return CommandResult(handled=False)
        parts = shlex.split(text[1:])
        if not parts:
            return CommandResult(handled=True, message="Type /help to see available commands.")

        name = parts[0]
        args = parts[1:]

        command = self._commands.get(name)
        if command is None:
            return CommandResult(handled=False, message=f"Unknown command: /{name}. Type /help to see available commands.")
        return command.handler(args, app)

registry = CommandRegistry()

def cmd_help() -> CommandResult:
    return CommandResult(handled=False, message=registry.get_help())

def cmd_exit() -> CommandResult:
    return CommandResult(handled=False, message="Ringing out...", should_exit=True)