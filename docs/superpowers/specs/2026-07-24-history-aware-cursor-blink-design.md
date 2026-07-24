# History-Aware Cursor Blink Design

## Status

Approved in conversation on 2026-07-24.

## Problem

Sonex keeps the chat input cursor blinking every 500 milliseconds. The existing
incremental terminal writer prevents those updates from clearing and repainting
the complete terminal, but every blink still writes a changed input row to
stdout. Many terminal emulators return their viewport to the live bottom when
any new output arrives, interrupting history browsing.

A real 80x24 PTY reproduction recorded one initial full-screen clear and seven
cursor-row updates during four seconds. This proves that repeated complete-frame
clears are no longer the active cause: the remaining problem is periodic output
while the user is browsing history.

## Scope

This change applies to Sonex's application-managed chat history:

- mouse-wheel chat scrolling;
- PageUp and PageDown chat scrolling;
- normal chat and Spotify chat.

It does not add support for detecting a terminal emulator's native scrollback
position or scrollbar. Standard TTY input does not expose that state reliably.

The change must preserve:

- the 500 millisecond cursor blink interval at the latest message;
- `ink-text-input` focus and left/right editing behavior;
- chronological chat history and history anchoring when new messages arrive;
- the existing mouse input protocol and filtering;
- overlay, setup, confirmation, mini-player, and Spotify immersive behavior;
- WebSocket messages and session persistence formats.

## Selected Approach

Use chat timeline state to control cursor activity.

`chatScrollOffset > 0` means the user is browsing application-managed history.
While that condition holds, Sonex stops the cursor blink timer without changing
the input's long-term logical focus. Returning to `chatScrollOffset === 0`
automatically restores the existing 500 millisecond blink.

This is preferred over:

1. A global input-focus state machine, which would broaden the change across
   unrelated panels and interactions.
2. Freezing stdout in the terminal-frame writer, which could suppress required
   chat, resize, or overlay updates.
3. Click-to-focus handling, which would require new mouse-coordinate parsing and
   hit testing that is outside the requested application-history scope.

## Components

### App history state

`App` derives a `historyBrowsing` condition from `chatScrollOffset > 0`.
Existing scroll actions continue to own the transition into and out of history.
The timeline reducer remains the source of truth.

`App` also handles printable input while history is visible. Because the flowing
layout removes the tail input dock from the historical viewport, printable input
must be captured before `PromptInput` is mounted again.

### History input classification

A small pure helper classifies an Ink input event as history-restoring text.
It accepts printable Unicode text, spaces, and multi-character paste input.
It rejects:

- Ctrl or Meta combinations;
- PageUp and PageDown;
- arrow and navigation keys;
- Tab, Escape, Return, Backspace, and Delete;
- empty input and control characters.

This helper keeps input policy independently testable and prevents terminal or
mouse control input from entering the chat draft.

### PromptInput cursor activity

`PromptInput` receives a cursor-blink enable flag independent from `focus`.

- `focus` continues to control `ink-text-input` input and editing semantics.
- the new flag controls only creation of the 500 millisecond interval;
- disabling the flag cleans up the active timer;
- enabling it restores cursor visibility and starts the timer again.

The flag defaults to enabled for login and setup inputs that are not part of chat
history browsing.

### Conversation plumbing

`ConversationColumn` and `InputDock` pass the history-derived cursor activity
state to the chat `PromptInput`. The existing behavior that hides the tail dock
while `chatScrollOffset > 0` remains unchanged. The explicit cursor flag makes
timer ownership clear and protects the behavior if the tail dock's rendering
policy changes later.

## Event Flow

### Entering history

1. The user scrolls upward with the wheel or PageUp.
2. The timeline reducer produces `chatScrollOffset > 0`.
3. The conversation enters history-browsing state.
4. The cursor blink interval is stopped and the tail dock leaves the viewport.
5. No periodic cursor render is produced while history remains active.

### Returning through scrolling

1. PageDown or wheel-down returns `chatScrollOffset` to zero.
2. The tail dock becomes visible below the latest message.
3. Cursor blink activity is enabled.
4. The cursor resumes the existing 500 millisecond effect.

### Returning through typing

1. A printable character or paste arrives while history is active.
2. The history-input helper accepts the text.
3. `App` resets the chat scroll offset to zero.
4. The accepted text is appended to the existing draft.
5. The tail dock and input reappear with the complete draft.
6. Cursor blinking resumes.

If the draft already contains text, history-restoring text is appended to its
end. Control and navigation input never modifies the draft.

## Interaction Boundaries

- PageUp and PageDown retain their existing scrolling behavior.
- Empty-input Up and Down do not regain chat-scrolling behavior.
- Mandatory confirmation and setup interactions retain their existing automatic
  return to the latest message.
- History-restoring input handling is inactive while an overlay or setup flow
  already owns keyboard input.
- Appending ordinary messages while in history keeps the visible history anchor.
- Non-raw terminals retain existing fallback behavior.

## Failure Handling

Unexpected or unclassified key events are ignored in history mode. They do not
reset the scroll position or mutate the input draft.

Cursor timer cleanup must be idempotent so unmounting the tail dock, changing
history state, or leaving the chat region cannot leave a background interval
running.

The terminal-frame writer remains responsible only for converting eligible Ink
full frames into changed-row output. It does not gain chat-state knowledge.

## Verification

Regression coverage will include:

1. Pure history-input classification tests for ASCII, Chinese text, spaces,
   paste input, navigation keys, modifiers, and control characters.
2. Cursor behavior tests showing that:
   - enabled blinking retains the 500 millisecond interval;
   - disabled blinking produces no periodic render across multiple intervals;
   - re-enabling restores blinking.
3. App integration tests showing that:
   - PageUp and PageDown only scroll;
   - printable history input returns to the latest message and preserves text;
   - message append continues to preserve the history anchor;
   - overlay and setup handlers retain keyboard ownership.
4. Existing incremental-frame, mouse-input, timeline, input-cursor, and layout
   regression suites.
5. A real PTY check verifying that history mode produces no periodic cursor-row
   writes.
6. Full CLI UI tests, TypeScript build, Python tests, `git diff --check`, and
   compiled `src/cli-ui/dist` inspection.

If Ink component timing cannot be tested reliably with the current dependency
set, cursor timing will be extracted into an independently testable controller
and paired with the real PTY verification. No new test dependency is required.
