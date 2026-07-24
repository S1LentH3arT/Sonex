# Terminal-Native Input Cursor Blink Design

## Status

Revised and approved in conversation on 2026-07-24.

This document supersedes the earlier application-history-only design. A real
PTY reproduction proved that Sonex already stops its cursor timer when PageUp
enters application-managed history because the complete tail input dock is
unmounted. The reported failure instead occurs while the user drags the terminal
emulator's native scrollback scrollbar.

## Problem

Sonex currently implements input cursor blinking with React state and a
500-millisecond interval. Every toggle causes Ink to render the input row and
write to stdout. The existing incremental terminal writer reduces each update
to the changed row, so repeated complete-screen clears are no longer occurring,
but many terminal emulators still return native scrollback to the live bottom
whenever any stdout output arrives.

A real 80x24 PTY reproduction recorded one initial complete frame followed by
seven input-row writes during four idle seconds. A second reproduction with 24
injected chat messages showed that PageUp-managed Sonex history becomes quiet,
confirming that the unresolved failure is native terminal scrollback plus idle
cursor output.

Terminal applications do not receive the terminal emulator's native scrollbar
position or drag state through standard TTY input. Sonex therefore cannot
reliably pause its timer at the moment a native scrollbar drag begins. The
periodic stdout source must be removed instead.

## Scope

Replace application-timed cursor blinking for every Sonex `PromptInput`:

- normal chat input;
- Spotify chat input;
- login input;
- authentication and Spotify setup input;
- confirmation text input.

The change must preserve:

- a visible blinking inverse-block cursor when the terminal supports SGR blink;
- a visible steady inverse-block cursor as the compatibility fallback;
- `ink-text-input` focus and left/right editing behavior;
- all current input colors, borders, labels, layouts, and placeholders;
- the incremental terminal writer and mouse-input protocols;
- chronological chat history and history anchoring;
- WebSocket messages and session persistence formats.

The change does not suppress legitimate output caused by user input, new
messages, overlays, terminal resize, or other real state changes.

## Selected Approach

Use terminal-native SGR slow blink for the inverse cursor cell.

`ink-text-input` already renders its focused cursor between SGR inverse-video
sequences:

```text
ESC[7m cursor cell ESC[27m
```

The existing `PromptInput` transform will convert these boundaries to:

```text
ESC[5;7m cursor cell ESC[25;27m
```

SGR 5 enables terminal-managed slow blink and SGR 25 disables blink. SGR 7 and
27 continue to enable and disable inverse video. The terminal emulator performs
the visible blink locally after the frame is written, so React no longer needs
to toggle state or emit periodic stdout updates.

This is preferred over:

1. A real hardware cursor, which would require extracting cursor coordinates
   from Ink output and correctly handling CJK width, horizontal input scrolling,
   layout changes, and focus transitions.
2. An idle timeout around the existing React timer, which would still produce
   output and could return native scrollback to the bottom before the timeout.
3. Scrollbar-aware focus handling, because native scrollbar activity is not
   observable through the TTY.

## Components

### ANSI cursor transforms

`src/cli-ui/src/input-cursor.ts` will continue to own cursor-specific ANSI
transforms.

It will expose:

- `hideInputCursor(output)`, retaining the existing behavior that removes
  inverse-video boundaries;
- a new terminal-blink transform that replaces every cursor inverse-on marker
  with combined slow-blink/inverse-on and every inverse-off marker with combined
  blink-off/inverse-off.

The closing transform must disable both attributes so blink styling cannot leak
into placeholders, borders, mode labels, or later terminal output.

### PromptInput

`PromptInput` will become stateless with respect to cursor animation.

- Remove `cursorVisible`.
- Remove the cursor visibility effect.
- Remove `setInterval`, `clearInterval`, and the 500-millisecond constant.
- Keep `focus={focus}` on `TextInput`.
- Do not set `showCursor`; that prop also affects editing behavior.
- When focused, transform the fake cursor to terminal-native blinking.
- When unfocused, use the existing hide transform.

The same implementation applies to all `PromptInput` consumers so Sonex does
not maintain separate cursor animation mechanisms for chat, login, setup, and
confirmation flows.

### Terminal output

`src/cli-ui/src/terminal-frame-writer.ts` remains unchanged. It continues to
convert eligible complete Ink frames to changed-row output, but it does not
track cursor animation or terminal scrollback.

Once the initial focused input frame contains SGR slow blink, the terminal
emulator animates it without further writes from Sonex.

## Data Flow

### Focused input

1. `ink-text-input` renders an inverse cursor cell.
2. `PromptInput` receives the rendered ANSI string.
3. The cursor transform replaces inverse boundaries with combined terminal
   slow-blink and inverse boundaries.
4. Ink writes the frame once.
5. The terminal emulator performs subsequent visual blinking locally.

### Unfocused input

1. `PromptInput` receives `focus=false`.
2. The existing hide transform removes cursor inverse boundaries.
3. No blink attribute is introduced.

### Native scrollback

1. The user drags the terminal emulator's native scrollbar.
2. Sonex receives no scrollbar-position event.
3. Because there is no application cursor timer, idle Sonex produces no cursor
   stdout writes.
4. The terminal remains at the user's selected scrollback position until a
   legitimate application update occurs.

## Compatibility

Most xterm-compatible terminal emulators support SGR 5 and choose their own slow
blink cadence, commonly close to 500 milliseconds. Sonex will no longer force an
exact application-level interval.

If a terminal disables blinking for accessibility or does not implement SGR 5,
the inverse cursor remains visible and steady. This is the required graceful
fallback; Sonex will not reintroduce a JavaScript timer to compensate.

Blink appearance and cadence are terminal preferences and may vary. Cursor
visibility, focus, editing, and input submission remain application-controlled.

## Failure Handling

The transform replaces all matching inverse cursor boundaries because
`ink-text-input` may produce more than one styled fragment across different
states. Both blink and inverse attributes are disabled at every closing marker.

Plain output without cursor inverse boundaries passes through unchanged.

No debug logging or terminal capability probe is added. Capability probing would
require asynchronous terminal responses and introduce a larger input-protocol
change than this fix needs.

## Verification

Regression coverage will include:

1. ANSI transform tests showing that:
   - inverse cursor markers become combined slow-blink/inverse markers;
   - every closing marker disables both blink and inverse;
   - multiple cursor fragments are transformed;
   - plain text remains unchanged;
   - the existing hide transform still removes inverse markers.
2. `PromptInput` source-contract tests showing that:
   - cursor state, effect, timer, and 500-millisecond constant are absent;
   - focused output uses the terminal-blink transform;
   - unfocused output uses the hide transform;
   - `focus={focus}` remains;
   - `showCursor` is not introduced.
3. A real idle PTY recording of at least two seconds showing that:
   - the first frame contains SGR slow-blink markers;
   - no 500-millisecond input-row writes follow;
   - no repeated complete-screen clear appears.
4. Native scrollbar manual smoke verification showing that idle cursor animation
   no longer returns the terminal viewport to the bottom.
5. Normal chat, Spotify chat, login, setup, and confirmation source paths all
   continue to use the shared `PromptInput`.
6. Full CLI UI tests, TypeScript build, Python tests, `git diff --check`, and
   compiled `src/cli-ui/dist` inspection.
