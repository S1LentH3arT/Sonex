"""Validation, display sanitization, and review policy for Agent Bash commands."""

from __future__ import annotations

import posixpath
import re
import shlex
import unicodedata
from dataclasses import dataclass
from typing import Literal

from src.sandbox.guardrail import inspect_script

MAX_BASH_COMMANDS = 12
MAX_BASH_COMMAND_LENGTH = 4096
BASH_REVIEW_PAGE_SIZE = 4

PolicyLevel = Literal["allow", "review", "deny"]


@dataclass(frozen=True, slots=True)
class BashCommandDecision:
    """The normalized permission result for one structured Bash request."""

    level: PolicyLevel
    commands: tuple[str, ...]
    display_commands: tuple[str, ...]
    rule_ids: tuple[str, ...] = ()
    blocked_commands: tuple[str, ...] = ()
    blocked_rule_ids: tuple[tuple[str, ...], ...] = ()
    invalid_reason: str | None = None

    @property
    def valid(self) -> bool:
        return self.invalid_reason is None


_ANSI_CSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_ANSI_OSC_RE = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
_URL_CREDENTIAL_RE = re.compile(
    r"(?i)\b(https?://)([^/\s:@]+):([^@/\s]+)@"
)
_NAMED_SECRET_RE = re.compile(
    r"""(?ix)
    \b(
        [A-Za-z_][A-Za-z0-9_]*
        (?:token|password|passwd|secret|api_?key|access_?key|private_?key)
        [A-Za-z0-9_]*
    )
    (\s*=\s*)
    (?:
        "(?:\\.|[^"])*"
        |
        '(?:[^']*)'
        |
        [^\s;|&]+
    )
    """
)
_AUTHORIZATION_RE = re.compile(
    r"""(?ix)
    (authorization\s*[:=]\s*(?:bearer\s+|basic\s+)?)
    (?:
        "(?:\\.|[^"])*"
        |
        '(?:[^']*)'
        |
        [^\s;|&]+
    )
    """
)
_COMMAND_SUBSTITUTION_RE = re.compile(r"\$\(|`")
_PROCESS_SUBSTITUTION_RE = re.compile(r"(?:<|>)\(")
_SHELL_FUNCTION_RE = re.compile(r"(?:^|\s)[A-Za-z_][A-Za-z0-9_]*\s*\(\s*\)\s*\{")
_WRITE_REDIRECTION_RE = re.compile(r"(?<!<)(?:\d*)>(?:>|[|])?")

_INLINE_INTERPRETERS: dict[str, frozenset[str]] = {
    "bash": frozenset({"-c"}),
    "dash": frozenset({"-c"}),
    "fish": frozenset({"-c"}),
    "node": frozenset({"-e", "--eval"}),
    "perl": frozenset({"-e"}),
    "python": frozenset({"-c"}),
    "python3": frozenset({"-c"}),
    "ruby": frozenset({"-e"}),
    "sh": frozenset({"-c"}),
    "zsh": frozenset({"-c"}),
}
_FORBIDDEN_EXECUTABLES = frozenset({"eval", "source"})
_CONTROL_EXECUTABLES = frozenset(
    {"case", "do", "done", "elif", "else", "esac", "fi", "for", "function", "if", "select", "then", "until", "while"}
)
_READ_ONLY_EXECUTABLES = frozenset(
    {
        "[",
        "cat",
        "echo",
        "file",
        "grep",
        "head",
        "ls",
        "printf",
        "pwd",
        "rg",
        "stat",
        "tail",
        "test",
        "tree",
        "wc",
    }
)
_GIT_READ_ONLY_SUBCOMMANDS = frozenset(
    {"diff", "log", "rev-parse", "show", "status"}
)
_FIND_REVIEW_FLAGS = frozenset({"-delete", "-exec", "-execdir", "-fls", "-fprintf", "-fprint", "-fprint0", "-ok", "-okdir"})
_SAFE_ROOTS = ("/work", "/music", "/tmp")
_QUOTED_PUNCTUATION = {
    character: chr(0xE000 + index)
    for index, character in enumerate("|&;()<>")
}

_RULE_REASON = {
    "boundary-management": "sandbox boundary management",
    "credential-discovery": "credential discovery",
    "device-access": "device access",
    "network-client": "network access",
    "sandbox-path": "path outside the sandbox",
    "sensitive-host-path": "sensitive host path",
}


def sanitize_command_display(command: str) -> str:
    """Return a printable, credential-safe display copy without changing execution."""
    value = _ANSI_OSC_RE.sub("", str(command or ""))
    value = _ANSI_CSI_RE.sub("", value)
    value = value.replace("\x08", "")
    value = "".join(
        character
        for character in value
        if character == "\t" or unicodedata.category(character) != "Cc"
    )
    value = _URL_CREDENTIAL_RE.sub(r"\1[REDACTED]@", value)
    value = _NAMED_SECRET_RE.sub(
        lambda match: f"{match.group(1)}{match.group(2)}[REDACTED]",
        value,
    )
    return _AUTHORIZATION_RE.sub(r"\1[REDACTED]", value)


def policy_reason(rule_id: str) -> str:
    """Return stable user-facing text for one hard-deny rule."""
    return _RULE_REASON.get(rule_id, "restricted operation")


def inspect_commands(commands: object) -> BashCommandDecision:
    """Validate a reviewable command list and classify its highest risk."""
    normalized, invalid_reason = _normalize_commands(commands)
    if invalid_reason:
        return BashCommandDecision(
            level="review",
            commands=(),
            display_commands=(),
            invalid_reason=invalid_reason,
        )

    display_commands = tuple(sanitize_command_display(command) for command in normalized)
    rule_ids: list[str] = []
    blocked_commands: list[str] = []
    blocked_rule_ids: list[tuple[str, ...]] = []
    review_required = False
    cwd = "/work"

    for command in normalized:
        syntax_error = _validate_simple_command(command)
        if syntax_error:
            return BashCommandDecision(
                level="review",
                commands=normalized,
                display_commands=display_commands,
                invalid_reason=syntax_error,
            )

        guardrail = inspect_script(command)
        command_rule_ids = list(guardrail.rule_ids)
        for rule_id in guardrail.rule_ids:
            if rule_id not in rule_ids:
                rule_ids.append(rule_id)
        if not guardrail.allowed:
            blocked_commands.append(command)
            blocked_rule_ids.append(tuple(command_rule_ids))
            continue

        command_level, next_cwd = _classify_command(command, cwd)
        if command_level == "deny":
            if "sandbox-path" not in rule_ids:
                rule_ids.append("sandbox-path")
            blocked_commands.append(command)
            blocked_rule_ids.append(("sandbox-path",))
        elif command_level == "review":
            review_required = True
        if next_cwd is not None:
            cwd = next_cwd

    if rule_ids:
        return BashCommandDecision(
            level="deny",
            commands=normalized,
            display_commands=display_commands,
            rule_ids=tuple(rule_ids),
            blocked_commands=tuple(blocked_commands),
            blocked_rule_ids=tuple(blocked_rule_ids),
        )
    return BashCommandDecision(
        level="review" if review_required else "allow",
        commands=normalized,
        display_commands=display_commands,
    )


def _normalize_commands(commands: object) -> tuple[tuple[str, ...], str | None]:
    if not isinstance(commands, list) or not commands:
        return (), "Bash commands must be a non-empty array."
    if len(commands) > MAX_BASH_COMMANDS:
        return (), f"Bash accepts at most {MAX_BASH_COMMANDS} commands per call."

    normalized: list[str] = []
    for index, command in enumerate(commands, start=1):
        if not isinstance(command, str):
            return (), f"Bash command {index} must be a string."
        if "\n" in command or "\r" in command:
            return (), f"Bash command {index} must be one physical line."
        value = command.strip()
        if not value:
            return (), f"Bash command {index} cannot be empty."
        if len(value) > MAX_BASH_COMMAND_LENGTH:
            return (), f"Bash command {index} is too long to review safely."
        normalized.append(value)
    return tuple(normalized), None


def _validate_simple_command(command: str) -> str | None:
    active_view = _active_shell_view(command)
    if _COMMAND_SUBSTITUTION_RE.search(active_view):
        return "Bash commands cannot use command substitution."
    if _PROCESS_SUBSTITUTION_RE.search(active_view):
        return "Bash commands cannot use process substitution."
    if "<<" in active_view:
        return "Bash commands cannot use heredocs or here-strings."
    if _SHELL_FUNCTION_RE.search(active_view):
        return "Bash commands cannot use shell control structures or functions."

    try:
        tokens = _shell_tokens(command)
    except ValueError:
        return "Bash command quoting is invalid."
    if not tokens:
        return "Bash command cannot be empty."
    if any(token in {";", "&&", "||", "&", "(", ")"} for token in tokens):
        return "Each Bash item must be one command or one single-line pipeline."

    segments = _pipeline_segments(tokens)
    if not segments:
        return "Bash pipeline is incomplete."
    for segment in segments:
        executable, arguments, has_assignment = _segment_command(segment)
        if executable is None:
            return "Each Bash pipeline segment must include an executable command."
        name = executable.rsplit("/", 1)[-1].casefold()
        if name in _CONTROL_EXECUTABLES:
            return "Bash commands cannot use shell control structures or functions."
        if name in _FORBIDDEN_EXECUTABLES or (name == "." and arguments):
            return f"Bash cannot use the inline execution command '{name}'."
        forbidden_flags = _INLINE_INTERPRETERS.get(name)
        if forbidden_flags and any(argument in forbidden_flags for argument in arguments):
            return f"Bash cannot run inline code through '{name}'."
        if has_assignment and executable is None:
            return "Standalone shell assignments are not supported."
    return None


def _shell_tokens(command: str) -> list[str]:
    lexer = shlex.shlex(
        _mask_quoted_punctuation(command),
        posix=True,
        punctuation_chars="|&;()<>",
    )
    lexer.whitespace_split = True
    lexer.commenters = ""
    return list(lexer)


def _mask_quoted_punctuation(command: str) -> str:
    """Keep quoted shell metacharacters from becoming structural tokens."""
    output: list[str] = []
    quote: str | None = None
    escaped = False
    for character in command:
        if escaped:
            output.append(character)
            escaped = False
            continue
        if character == "\\" and quote != "'":
            output.append(character)
            escaped = True
            continue
        if quote is None and character in {"'", '"'}:
            quote = character
            output.append(character)
            continue
        if quote == character:
            quote = None
            output.append(character)
            continue
        if quote is not None and character in _QUOTED_PUNCTUATION:
            output.append(_QUOTED_PUNCTUATION[character])
            continue
        output.append(character)
    return "".join(output)


def _active_shell_view(command: str) -> str:
    """Mask single-quoted and escaped literals before expansion checks."""
    output: list[str] = []
    quote: str | None = None
    escaped = False
    for character in command:
        if escaped:
            output.append(" ")
            escaped = False
            continue
        if character == "\\" and quote != "'":
            output.append(" ")
            escaped = True
            continue
        if quote is None and character == "'":
            quote = "'"
            output.append(" ")
            continue
        if quote == "'" and character == "'":
            quote = None
            output.append(" ")
            continue
        if quote == "'":
            output.append(" ")
            continue
        if character == '"':
            quote = None if quote == '"' else '"'
            output.append(" ")
            continue
        output.append(character)
    return "".join(output)


def _pipeline_segments(tokens: list[str]) -> list[list[str]]:
    segments: list[list[str]] = [[]]
    for token in tokens:
        if token == "|":
            if not segments[-1]:
                return []
            segments.append([])
            continue
        segments[-1].append(token)
    return segments if segments[-1] else []


def _segment_command(segment: list[str]) -> tuple[str | None, list[str], bool]:
    filtered: list[str] = []
    skip_redirection_target = False
    for token in segment:
        if skip_redirection_target:
            skip_redirection_target = False
            continue
        if token in {"<", ">", ">>", "<>", ">|"} or re.fullmatch(r"\d*(?:<|>|>>|<>)", token):
            skip_redirection_target = True
            continue
        filtered.append(token)

    index = 0
    has_assignment = False
    while index < len(filtered) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", filtered[index]):
        has_assignment = True
        index += 1
    if index >= len(filtered):
        return None, [], has_assignment
    return filtered[index], filtered[index + 1 :], has_assignment


def _classify_command(command: str, cwd: str) -> tuple[PolicyLevel, str | None]:
    tokens = _shell_tokens(command)
    if _WRITE_REDIRECTION_RE.search(command):
        return "review", None

    level: PolicyLevel = "allow"
    next_cwd: str | None = None
    for segment in _pipeline_segments(tokens):
        executable, arguments, has_assignment = _segment_command(segment)
        if executable is None:
            return "review", None
        name = executable.rsplit("/", 1)[-1].casefold()
        if has_assignment:
            level = "review"

        if name == "cd":
            cd_level, resolved = _classify_cd(arguments, cwd)
            if cd_level == "deny":
                return "deny", None
            if cd_level == "review":
                level = "review"
            if resolved is not None:
                next_cwd = resolved
            continue
        if name == "find":
            if any(argument.casefold() in _FIND_REVIEW_FLAGS for argument in arguments):
                level = "review"
            continue
        if name == "sed":
            if any(
                argument == "-i"
                or argument.startswith("-i")
                or argument.startswith("--in-place")
                for argument in arguments
            ):
                level = "review"
            continue
        if name == "git":
            subcommand = next(
                (
                    argument.casefold()
                    for argument in arguments
                    if argument and not argument.startswith("-")
                ),
                "",
            )
            if subcommand not in _GIT_READ_ONLY_SUBCOMMANDS:
                level = "review"
            continue
        if name not in _READ_ONLY_EXECUTABLES:
            level = "review"
    return level, next_cwd


def _classify_cd(arguments: list[str], cwd: str) -> tuple[PolicyLevel, str | None]:
    targets = [argument for argument in arguments if not argument.startswith("-")]
    if len(targets) != 1:
        return "review", None
    target = targets[0]
    if any(character in target for character in ("$", "*", "?", "[", "]", "{", "}")):
        return "review", None
    resolved = posixpath.normpath(
        target if target.startswith("/") else posixpath.join(cwd, target)
    )
    if not any(resolved == root or resolved.startswith(f"{root}/") for root in _SAFE_ROOTS):
        return "deny", None
    return "allow", resolved
