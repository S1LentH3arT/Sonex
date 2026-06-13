# ADR-005: Add High-Resolution Bead Pattern Variants

## Status

Accepted

## Context

The existing 96 by 96 bead pattern is the first size that can loosely preserve many album covers. Larger terminal windows can display more detail because Sonex renders one bead column per terminal column and two bead rows per terminal row with half-block characters. A 128 by 128 pattern needs 128 columns and 64 rows in the artwork area, while 192 by 192 needs 192 columns and 96 rows. PowerShell, zsh, and Ghostty do not require separate handling; their usable size is the terminal column and row count reported to the TUI.

## Decision

Generate 15 variants for each cover: 32, 36, 40, 44, 48, 56, 64, 80, 96, 112, 128, 144, 160, 176, and 192. Extend shared-palette sampling to 32, 48, 64, 96, 128, 160, and 192 so high-resolution details can influence the 32-48 color subset. Keep one complete `cover_pattern` event and let the CLI choose the largest variant that fits the existing artwork area.

## Alternatives Considered

- Two-stage generation: improves first paint, but creates partial cache and repeated event complexity.
- Terminal-size-aware backend generation: saves CPU and payload size, but requires new client size events and per-size cache management.
- Pure artwork mode: makes larger sizes easier to display, but adds user interaction and changes mini-player behavior.

## Consequences

Cache entries are incompatible with v2 because the algorithm version and full profile change. Cold generation and payload size increase, but cache hits remain simple and protocol-compatible. Large variants only appear when the terminal can fully contain them; otherwise the UI falls back to the largest smaller size or hides the artwork if none fit.
