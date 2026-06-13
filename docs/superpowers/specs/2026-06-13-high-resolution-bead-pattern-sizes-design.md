# High-Resolution Bead Pattern Sizes Design

## Goal

Improve album-cover readability for large terminal windows by adding bead pattern sizes beyond 96 while preserving static command-line rendering, official-cover sourcing, real-brand Hama/Perler catalogs, shared 32-48 color palettes, and no-dither mapping.

## Size Set And Display

The fixed size set is 32, 36, 40, 44, 48, 56, 64, 80, 96, 112, 128, 144, 160, 176, and 192 beads per side. Sonex continues to render with the `▀` half-block character, so an `N` by `N` variant requires `N` terminal columns and `ceil(N / 2)` terminal rows.

The mini-player layout is unchanged. The CLI chooses the largest complete variant that fits the current artwork area. It does not crop, scroll, stretch, or switch into a pure artwork mode. If no generated variant fits, the existing unfit behavior leaves the artwork slot blank.

## Generation Profile

All sizes are generated and cached together in one derived artifact. The WebSocket `cover_pattern` payload and TypeScript shape remain unchanged. The backend adds high-resolution variants to the existing `variants` map and recomputes usage counts for each size.

Palette selection remains one shared adaptive catalog subset per cover. The multiscale sample set expands to 32, 48, 64, 96, 128, 160, and 192 so small high-resolution features can influence the selected colors. Each output size is still independently BOX-resampled, CIEDE2000 mapped, and edge-refined.

The algorithm version is `lab-ciede2000-edge-refine-v3`. The full profile remains cache identity, so older entries regenerate automatically.

## Failure And Performance

Per-size refinement failures continue to fall back to that size's direct nearest-color grid and record diagnostics in the cache. Decode, catalog, palette selection, and base mapping failures still produce the existing unavailable event.

A representative 640 by 640 cover generating all 15 variants should remain below three seconds in development and below eight seconds in CI. The complete WebSocket JSON payload should stay below 500 KiB for representative covers.
