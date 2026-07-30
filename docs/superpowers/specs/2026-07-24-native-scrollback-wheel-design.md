# Terminal-Native Chat Wheel Design

## Status

Approved in conversation on 2026-07-24.

This design supersedes the mouse-wheel portion of the earlier application
timeline design. PageUp and PageDown remain application-managed history
controls.

## Problem

Sonex currently enables xterm mouse tracking in ordinary and Spotify chat:

```text
ESC[?1000h ESC[?1006h
```

With tracking enabled, the terminal sends wheel movement to Sonex as SGR mouse
sequences instead of moving its native scrollback. Sonex converts each wheel-up
event into a chat offset change, Ink renders the historical chat window, and
the incremental terminal writer emits changed-row output. Terminal emulators
may return native scrollback to the live bottom whenever that output arrives.

A real 80x24 PTY reproduction using the compiled runtime proved that:

- the running entrypoint enables both mouse modes;
- three SGR wheel-up events each change the rendered history window;
- each event emits approximately 0.5 to 0.6 KB of absolute row updates;
- the idle interval after the wheel events produces no periodic cursor output;
- the chat offset does not reset on its own.

The remaining jump is therefore caused by application-managed wheel rendering,
not by cursor blinking or an unexpected offset reset.

Standard TTY input does not expose the terminal emulator's native scrollbar
position. Sonex cannot reliably distinguish a user browsing native scrollback
from a user at the live bottom and selectively suppress output.

## Requirements

### Functional

- Ordinary mouse-wheel input must remain owned by the terminal emulator.
- The terminal's right-side scrollbar must remain usable as native scrollback.
- A wheel gesture must not change Sonex chat state or trigger Sonex rendering.
- PageUp and PageDown must continue to browse the application-managed chat
  timeline in five-record steps.
- Application-managed history must continue to hide the tail input dock and
  restore it when returning to the latest position.
- Ordinary chat and Spotify chat must use the same wheel behavior.
- Login, setup, confirmation, selector, help, player, and overlay regions must
  not add mouse handling.
- Startup must disable xterm mouse tracking once in case a previous abnormal
  process exit left the terminal mode enabled.

### Preserved Contracts

- Keep chronological chat history, item retention, and history anchoring.
- Keep the flowing input dock and three-row empty-conversation reserve.
- Keep terminal-native input cursor blinking.
- Keep incremental terminal frame rendering for legitimate application
  updates.
- Keep the WebSocket protocol and session-save format unchanged.
- Keep all message rendering, colors, subjects, markers, and Spotify styling
  unchanged.

## Considered Approaches

### A. Terminal-native wheel with application keyboard history

Disable mouse reporting and let the terminal own ordinary wheel gestures.
Retain PageUp and PageDown as explicit Sonex history controls.

This is the selected approach. It is the only option that makes wheel input
produce no Sonex state change or stdout output while preserving the existing
application history as an alternate keyboard-accessible view.

### B. Disable tracking after the first wheel event

Sonex could consume the first reported wheel event, disable tracking, and let
later events reach native scrollback. The first event would still cause a mode
write or redraw and could still return the viewport to the bottom. Behavior
would also change mid-gesture, so this approach is rejected.

### C. Fully application-managed history in an alternate screen

An alternate screen would make Sonex the sole scrolling authority and avoid
mixing native and application views. It would remove the required terminal
scrollbar and native scrollback workflow, so this approach is rejected.

## Selected Architecture

### CLI entrypoint

`src/cli-ui/src/index.tsx` will:

1. write `ESC[?1006l ESC[?1000l` once before Ink begins rendering;
2. pass `process.stdin` directly to Ink;
3. retain `createIncrementalStdout(process.stdout)`;
4. stop constructing or disposing a mouse input adapter.

The disable order intentionally reverses the previous enable order. The
one-time defensive reset prevents stale mouse-reporting state from an abnormal
prior exit without enabling any new mouse mode.

### App

`src/cli-ui/src/App.tsx` will:

- remove the mouse-wheel source prop;
- remove the effect that enables mouse tracking and subscribes to wheel events;
- keep `scrollChat` because PageUp and PageDown still use it;
- keep all overlay and region enablement rules for keyboard input unchanged.

### Mouse adapter

`src/cli-ui/src/mouse-input.ts` and its dedicated SGR/X10 parsing tests will be
removed because no runtime path will enable or consume terminal mouse reports.
Keeping an unused adapter would obscure the native-wheel contract and invite a
future accidental reactivation.

The one-time mouse-disable constant will live in `src/cli-ui/src/index.tsx`
next to the only write that uses it. No event parser or subscription interface
will remain.

## Data Flow

### Native wheel

1. Sonex starts and disables xterm button-event and SGR mouse reporting.
2. The user moves the mouse wheel.
3. The terminal emulator changes its native scrollback viewport.
4. Sonex receives no input sequence.
5. `chatScrollOffset` remains unchanged.
6. Sonex emits no wheel-related stdout output.

### Application history keys

1. Ink receives PageUp or PageDown from `process.stdin`.
2. The existing handler calls `scrollChat(5)` or `scrollChat(-5)`.
3. The timeline reducer updates `chatScrollOffset`.
4. The conversation flow hides or restores the tail dock according to the
   resulting offset.
5. The incremental writer emits only rows changed by that explicit
   application action.

### Legitimate asynchronous output

New messages, connection changes, resize events, and user actions still render
normally. A standard TTY does not report native scrollbar position, so Sonex
cannot defer these updates only while native scrollback is active. Whether an
asynchronous write returns the viewport to the bottom remains terminal-emulator
behavior and is outside this fix.

## Failure and Compatibility Behavior

- Terminals that never enabled mouse tracking safely ignore the disable
  sequence.
- A terminal left in mouse-reporting mode by an abnormal prior exit is restored
  before Ink starts accepting input.
- If an external program enables mouse reporting after Sonex starts, Sonex does
  not parse those sequences; that external terminal-state mutation is outside
  Sonex's lifecycle.
- PageUp and PageDown provide an application-managed history fallback when
  native scrollback does not contain the desired content.
- No third-party mouse dependency or terminal capability probe is introduced.

## Testing

### Source contracts

Add or revise tests to prove:

- the entrypoint writes the disable sequence exactly once before rendering;
- the entrypoint never writes either mouse-tracking enable sequence;
- Ink receives `process.stdin` directly;
- `App` no longer accepts or subscribes to a mouse-wheel source;
- the PageUp and PageDown handler still calls `scrollChat(5)` and
  `scrollChat(-5)`;
- the terminal frame writer and terminal-native cursor transform remain
  unchanged.

Remove tests whose only contract is SGR/X10 parsing or mouse subscription.

### Behavioral tests

Keep the timeline, chat-window, and conversation-flow tests that cover:

- application history offset changes;
- append anchoring while in application history;
- tail-dock hiding and restoration;
- non-overflowing chat refusing application history movement;
- ordinary and Spotify conversation layout parity.

### PTY verification

Run the compiled `src/cli-ui/dist` entrypoint in a real 80x24 PTY and verify:

- output contains one `ESC[?1006l ESC[?1000l` startup reset;
- output contains no `ESC[?1000h` or `ESC[?1006h`;
- after the initial connection frame stabilizes, idle time produces no
  periodic writes;
- PageUp still renders application history and hides the input dock.

A PTY captures application bytes but does not implement a terminal emulator's
native scrollback viewport. Automated verification therefore proves the
necessary boundary—no mouse tracking and no wheel-triggered Sonex output—while
the final viewport behavior requires a real-terminal smoke check.

### Integrated verification

Run:

```bash
git diff --check
npm --prefix src/cli-ui test
npm --prefix src/cli-ui run build
.venv/bin/python -m pytest -q
```

Inspect the compiled entrypoint to ensure the actual `scripts/sonex` runtime
uses direct stdin, the defensive disable sequence, and no mouse adapter.

## Non-Goals

- Detecting the native scrollbar position
- Buffering legitimate asynchronous messages while native scrollback is active
- Adding a draggable scrollbar inside Sonex
- Reworking Ink into an append-only terminal renderer
- Moving PageUp or PageDown to terminal-native handling
- Changing non-chat UI behavior or visual styling
