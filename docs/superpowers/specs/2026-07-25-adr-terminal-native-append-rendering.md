# ADR-002: Use Terminal-Native Append Rendering

## Status

Accepted in conversation on 2026-07-25.

Supersedes `2026-07-24-adr-measured-conversation-flow.md` and the
application-managed PageUp/PageDown portion of
`2026-07-24-native-scrollback-wheel-design.md`.

## Context

Sonex currently owns a terminal-height virtual chat viewport. It caps the
frontend timeline, selects visible records with a scroll offset, and relies on
an incremental frame writer to reduce Ink's full-screen repaint behavior.

That design cannot make the terminal emulator's scrollback the authoritative
conversation history. Users cannot reliably browse shell output that preceded
Sonex, and ordinary chat behaves like an exclusive TUI rather than a command
that appends output downward.

The new design must preserve Sonex's current message and input styling,
Spotify behavior, dynamic interaction panels, WebSocket protocol, session
format, and explicit full-screen playback experiences.

## Decision

Render ordinary chat as two regions in the main terminal buffer:

1. an immutable committed transcript rendered through Ink `<Static>`;
2. a small dynamic tail containing input, status, and non-full-screen
   interaction panels.

Do not size the main root to terminal height, clear the main screen, maintain a
virtual history viewport, or handle PageUp/PageDown as Sonex chat history.
Native terminal scrollback, wheel behavior, selection, and copy own history.

Commit local user input immediately and reconcile the backend's existing
`chat:user` echo with a frontend text-count ledger. Keep all other permanent
versus transient event classification in one commit coordinator.

Use an explicit terminal surface controller to enter the alternate screen only
for the mini player, Spotify immersive mode, and full-screen track panels. The
controller clears Ink's current live output and resets incremental frame state
before every buffer transition, then restores the main dynamic tail below the
preserved transcript.

Keep incremental full-frame rewriting only as an alternate-screen optimization.
Do not use it as the main chat-history mechanism.

## Consequences

### Positive

- Pre-launch shell output and the complete Sonex conversation remain in native
  terminal scrollback.
- Mouse wheel, scrollbar, selection, copy, and terminal search retain native
  behavior.
- Ordinary cursor, status, and input updates redraw only the dynamic tail.
- Existing React/Ink message and banner components remain reusable.
- The WebSocket protocol and Python session/transcript models do not change.
- Full-screen playback surfaces remain isolated and temporary.
- The main architecture becomes simpler by removing viewport measurement,
  scroll offsets, and row-window estimation.

### Negative

- Committed history cannot be edited or restyled after output.
- Previously committed records do not reflow under application control after a
  terminal resize.
- Frontend transcript text grows linearly for the lifetime of a process.
- User-message echo reconciliation depends on the backend continuing to echo
  accepted user input without a protocol-level event ID.
- Main/alternate buffer transitions require strict cleanup ordering and
  dedicated failure tests.

### Neutral

- New records after resize use the new terminal width, so one session may
  contain records committed at different widths.
- PageUp and PageDown no longer browse a Sonex-owned history window; terminal
  shortcuts such as `Shift+PageUp` remain emulator-specific.
- The 80-item limit may remain for unrelated bounded UI collections such as
  activity, but not for the committed transcript.

## Alternatives Considered

### Custom Inline History Writer

Manually insert finalized rows above a live viewport using cursor movement,
scroll regions, reverse index, and terminal-specific compatibility paths.

Rejected because it requires a custom terminal rendering engine, makes current
Ink components difficult to reuse, and expands the compatibility surface
across terminal emulators and multiplexers.

### Separate Ink Roots for Main and Alternate Screens

Maintain two renderer instances backed by a shared external store.

Rejected because it requires lifting most App state and coordinating input,
WebSocket, and lifecycle ownership across roots. A surface controller plus
explicit Ink-output resets provides sufficient isolation.

### Retain Full-Screen Virtual History

Keep the measured conversation flow and improve frame differencing.

Rejected because it cannot preserve pre-launch shell output or make native
scrollback the source of truth.

## Failure Modes and Mitigations

- **Duplicate backend user echo:** consume a matching pending echo count instead
  of committing a second record.
- **Send failure after local commit:** retain the user record and append an error
  record.
- **Main history erased on surface return:** clear live rows and reset the frame
  cache before both enter and leave operations.
- **Repeated or failed cleanup:** make terminal surface transitions and
  `dispose()` idempotent.
- **Resize corruption:** never replay or clear committed main history; redraw
  only the live tail.
- **Control-sequence injection:** render untrusted content through Ink and
  restrict direct stdout writes to trusted lifecycle constants.
- **Non-TTY corruption:** disable alternate-screen, mouse, and cursor control
  output outside a TTY.

## Operational Impact

- No new dependency is introduced.
- Runtime verification must use compiled `src/cli-ui/dist` through
  `scripts/sonex`.
- PTY tests validate byte-level clear and cleanup behavior.
- Real-terminal checks remain necessary for scrollbar, selection, copy, and
  resize behavior because a PTY does not emulate a terminal scrollback UI.

## References

- `docs/superpowers/specs/2026-07-25-terminal-native-append-rendering-design.md`
- `docs/superpowers/specs/2026-07-24-flowing-chat-input-design.md`
- `docs/superpowers/specs/2026-07-24-native-scrollback-wheel-design.md`
- `src/cli-ui/src/terminal-frame-writer.ts`
- `src/ws/ui.py`
- [Codex terminal history insertion](https://github.com/openai/codex/blob/main/codex-rs/tui/src/insert_history.rs)
