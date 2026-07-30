"""Best-effort command guardrail used before the OS sandbox boundary."""

from __future__ import annotations

import hashlib
import re
import shlex
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GuardrailDecision:
    allowed: bool
    policy: str
    rule_ids: tuple[str, ...]
    command_shape: tuple[str, ...]
    script_sha256: str
    script_length: int


_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "sensitive-host-path",
        re.compile(
            r"(?ix)"
            r"(?:^|[\s;|&<>()])"
            r"(?:~(?:/|$)|/root(?:/|$)|/home(?:/|$)|"
            r"[^\s]*\.ssh(?:/|$)|[^\s]*\.config(?:/|$)|"
            r"[^\s]*\.env(?:\s|$)|/proc/(?:self|\d+)/environ)"
        ),
    ),
    (
        "boundary-management",
        re.compile(
            r"(?ix)(?:^|[\s;|&])"
            r"(?:sudo|su|doas|mount|umount|nsenter|unshare|bwrap|chroot|"
            r"pivot_root|setpriv|capsh|systemctl|service|shutdown|reboot)"
            r"(?:\s|$)"
        ),
    ),
    (
        "device-access",
        re.compile(r"(?i)(?:^|[\s<>()])/(?:dev/(?:sd|nvme|mapper|mem|kmem)|sys/)(?:[^\s]*)"),
    ),
    (
        "credential-discovery",
        re.compile(
            r"(?ix)(?:^|[\s;|&])"
            r"(?:printenv|env)\s*(?:$|[;|&])|"
            r"(?:cat|sed|awk|grep|strings)\s+[^\n;|&]*(?:credential|token|secret|password)"
        ),
    ),
    (
        "network-client",
        re.compile(
            r"(?ix)(?:^|[\s;|&])"
            r"(?:curl|wget|nc|ncat|netcat|socat|ssh|scp|sftp|ftp|telnet)"
            r"(?:\s|$)"
        ),
    ),
)

_COMMAND_BOUNDARY = re.compile(r"(?:^|[;&|]\s*|\n\s*)([A-Za-z0-9_./+-]+)")


def _command_shape(script: str) -> tuple[str, ...]:
    commands: list[str] = []
    for match in _COMMAND_BOUNDARY.finditer(script):
        value = match.group(1)
        try:
            token = shlex.split(value)[0]
        except (ValueError, IndexError):
            token = value
        name = token.rsplit("/", 1)[-1]
        if name and name not in commands:
            commands.append(name[:48])
        if len(commands) >= 12:
            break
    return tuple(commands)


def inspect_script(script: str) -> GuardrailDecision:
    """Reject explicit boundary and sensitive-data attempts.

    This check is deliberately narrow. Unknown shell semantics are allowed and
    audited because Bubblewrap, not this parser, owns containment.
    """
    value = str(script or "")
    digest = hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()
    matched = tuple(rule_id for rule_id, pattern in _RULES if pattern.search(value))
    return GuardrailDecision(
        allowed=not matched,
        policy="allowed" if not matched else "denied",
        rule_ids=matched,
        command_shape=_command_shape(value),
        script_sha256=digest,
        script_length=len(value),
    )
