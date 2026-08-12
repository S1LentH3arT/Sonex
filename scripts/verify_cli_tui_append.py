#!/usr/bin/env python3
from __future__ import annotations

import fcntl
import os
import pathlib
import pty
import re
import select
import signal
import struct
import subprocess
import sys
import termios
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "src" / "cli-ui" / "test" / "fixtures" / "append-render-fixture.mjs"
NON_TTY_FIXTURE = (
    ROOT / "src" / "cli-ui" / "test" / "fixtures" / "non-tty-render-fixture.mjs"
)
ALT_ENTER = b"\x1b[?1049h"
ALT_LEAVE = b"\x1b[?1049l"
CLEAR = b"\x1b[2J"
SCROLLBACK_CLEAR = b"\x1b[3J"
MOUSE_DISABLE = b"\x1b[?1006l\x1b[?1000l"
CURSOR_SHOW = b"\x1b[?25h"


def capture(
    *,
    rows: int = 24,
    columns: int = 80,
    signal_from_alternate: bool = False,
) -> bytes:
    master, slave = pty.openpty()
    fcntl.ioctl(
        slave,
        termios.TIOCSWINSZ,
        struct.pack("HHHH", rows, columns, 0, 0),
    )
    os.write(slave, b"PREEXISTING_MARKER\r\n")
    process = subprocess.Popen(
        ["node", str(FIXTURE)],
        cwd=ROOT,
        env={
            **os.environ,
            # The child owns a real PTY even when this verifier runs in CI.
            # Ink's CI mode suppresses intermediate interactive frames.
            "CI": "false",
            "SONEX_APPEND_FIXTURE_SIGNAL": "1" if signal_from_alternate else "0",
        },
        stdin=slave,
        stdout=slave,
        stderr=slave,
        close_fds=True,
    )
    os.close(slave)
    output = bytearray()
    deadline = time.monotonic() + 5
    signal_sent = False

    try:
        while time.monotonic() < deadline:
            readable, _, _ = select.select([master], [], [], 0.1)
            if master in readable:
                try:
                    chunk = os.read(master, 65536)
                except OSError:
                    break
                if not chunk:
                    break
                output.extend(chunk)
                if (
                    signal_from_alternate
                    and not signal_sent
                    and b"ALT_SURFACE" in output
                ):
                    process.send_signal(signal.SIGTERM)
                    signal_sent = True
            if process.poll() is not None and not readable:
                break
    finally:
        os.close(master)

    return_code = process.wait(timeout=1)
    expected_return_code = 143 if signal_from_alternate else 0
    if return_code != expected_return_code:
        raise AssertionError(f"fixture exited with {return_code}: {bytes(output)!r}")
    return bytes(output)


def main() -> int:
    output = capture()
    enter = output.index(ALT_ENTER)
    leave = output.index(ALT_LEAVE, enter)
    alternate_output = output[enter:leave]

    marker = output.index(b"PREEXISTING_MARKER")
    before = output.index(b"RECORD_BEFORE_ALT")
    history_end = output.index(b"STATIC_HISTORY_39")
    during = output.index(b"RECORD_DURING_ALT")

    assert marker < before < history_end < enter
    assert during > leave
    assert b"LIVE_TAIL" in output
    assert b"ALT_SURFACE" in output
    assert b"RECORD_BEFORE_ALT" not in alternate_output
    assert b"RECORD_DURING_ALT" not in alternate_output
    assert b"STATIC_HISTORY_" not in alternate_output
    assert output.count(b"RECORD_BEFORE_ALT") == 1
    for index in range(40):
        marker_pattern = rb"STATIC_HISTORY_" + str(index).encode() + rb"(?![0-9])"
        assert len(re.findall(marker_pattern, output)) == 1
    assert CLEAR not in output[:enter]
    assert CLEAR not in output[leave + len(ALT_LEAVE):]
    assert SCROLLBACK_CLEAR not in output[:enter]
    assert SCROLLBACK_CLEAR not in output[leave + len(ALT_LEAVE):]
    assert MOUSE_DISABLE in output
    assert CURSOR_SHOW in output

    for rows, columns in ((40, 100), (10, 60)):
        sized_output = capture(rows=rows, columns=columns)
        sized_enter = sized_output.index(ALT_ENTER)
        sized_leave = sized_output.index(ALT_LEAVE, sized_enter)
        assert CLEAR not in sized_output[:sized_enter]
        assert SCROLLBACK_CLEAR not in sized_output[:sized_enter]
        assert b"RECORD_BEFORE_ALT" not in sized_output[sized_enter:sized_leave]
        assert b"STATIC_HISTORY_" not in sized_output[sized_enter:sized_leave]
        assert CLEAR not in sized_output[sized_leave + len(ALT_LEAVE):]
        assert SCROLLBACK_CLEAR not in sized_output[sized_leave + len(ALT_LEAVE):]

    signal_output = capture(signal_from_alternate=True)
    signal_enter = signal_output.index(ALT_ENTER)
    signal_leave = signal_output.index(ALT_LEAVE, signal_enter)
    after_signal_leave = signal_output[signal_leave + len(ALT_LEAVE):]
    assert b"ALT_SURFACE" in signal_output[signal_enter:signal_leave]
    assert CLEAR not in after_signal_leave
    assert SCROLLBACK_CLEAR not in after_signal_leave
    assert b"ALT_SURFACE" not in after_signal_leave
    assert b"RECORD_BEFORE_ALT" not in after_signal_leave
    assert MOUSE_DISABLE in after_signal_leave
    assert CURSOR_SHOW in after_signal_leave

    non_tty_output = subprocess.run(
        ["node", str(NON_TTY_FIXTURE)],
        cwd=ROOT,
        env={**os.environ, "CI": "false"},
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    ).stdout
    assert b"NON_TTY_FIRST" in non_tty_output
    assert b"NON_TTY_SECOND" in non_tty_output
    assert b"NON_TTY_THIRD" in non_tty_output
    assert non_tty_output.count(b"NON_TTY_RECORD") == 1
    for control in (
        ALT_ENTER,
        ALT_LEAVE,
        CLEAR,
        SCROLLBACK_CLEAR,
        MOUSE_DISABLE,
        CURSOR_SHOW,
        b"\x1b[2K",
        b"\x1b[1A",
        b"\x1b[G",
    ):
        assert control not in non_tty_output
    print("append-render PTY verification passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
