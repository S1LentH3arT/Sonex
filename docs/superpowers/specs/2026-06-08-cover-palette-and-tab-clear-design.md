# Cover Palette and Tab Clear Design

## Goal

Improve static album-cover bead art by expanding the fixed palette from 48 to 96 colors, and prevent stale mascot banners or prior mini-player frames from remaining after Tab layout switches.

## Scope

This change preserves the existing static cover-pattern protocol, supported grid sizes, half-block rendering, and mini-player layout state machine. It does not add dynamic per-cover palettes, dithering, animation, or frontend protocol changes.

## Fixed 96-Color Palette

`src/tools/cover_patterns.py` remains the source of truth for color quantization. The fixed palette will contain exactly 96 unique RGB hex colors. The additional colors will focus on intermediate lightness, muted neutrals, skin and earth tones, and denser cyan, blue, violet, magenta, red, orange, yellow, and green transitions.

Nearest-color selection continues to use the existing weighted RGB distance and no dithering. The WebSocket payload continues to send palette indices plus the palette, so the TypeScript renderer requires no quantization logic.

Cached pattern validation already compares the stored palette with the current palette. Expanding the palette therefore invalidates old 48-color cache entries automatically and regenerates them from the official cover source on the next request.

## Tab Clear Behavior

Tab remains the only trigger for switching between constrained chat and mini-player views. Immediately before changing `smallPlaybackFocus`, the CLI writes an ANSI full-screen clear sequence and moves the cursor to the home position through Ink's `stdout` stream.

The clear operation is isolated in a small exported helper so its exact output can be unit tested without mounting the Ink application. It runs only for accepted Tab layout switches while playback is active and no confirm or slash menu owns input. Normal progress redraws, text submission, and non-Tab key handling do not clear the screen.

Clearing before the state transition removes terminal history produced by Ink `<Static>` content, including previous mascot banners, before the next chat or mini-player frame is painted.

## Tests

Python tests will assert that the palette contains 96 unique valid colors, generated indices can use the expanded range, and cache validation rejects a payload using the previous palette.

CLI tests will assert that the clear helper writes exactly one full-screen clear and cursor-home sequence. A source-level regression test will verify the Tab handler calls the helper before changing `smallPlaybackFocus`.

Verification includes focused Python and CLI tests, the full CLI test suite and build, repository Python tests, and `git diff --check` before commits.

## Commit Boundaries

1. `feat(cover): expand bead palette`
2. `fix(cli-ui): clear screen on tab switch`

The design document is committed separately. Existing unrelated working-tree changes are excluded from these commits.
