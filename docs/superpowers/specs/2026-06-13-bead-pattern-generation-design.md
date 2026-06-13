# Bead Pattern Generation Refinement Design

## Goal

Improve construction readability of the existing Hama/Perler cover patterns without changing official-cover selection, WebSocket payloads, or static TUI rendering. The generator should form coherent same-color regions, remove low-contrast one- and two-cell islands, and preserve strong edges and small high-contrast details.

## Fixed Profile

The refinement profile is part of cache identity and is intentionally not user-configurable:

- Four nearest palette candidates per cell.
- Two synchronous smoothing rounds.
- Continuity weight `2.5`.
- Edge scale `12` Delta E.
- Maximum island size `2`.
- Maximum island merge distance `18` Delta E.

## Data Flow

Each output size starts with its own BOX-resampled image and direct CIEDE2000 nearest-color mapping. `PaletteMapping` retains the source Lab grid, selected palette Lab values, nearest grid, and deterministic Top-4 candidates with their perceptual errors.

Refinement evaluates only those Top-4 candidates. A vectorized four-neighbor objective adds continuity cost in flat regions and attenuates that cost across source-image edges. Every smoothing round reads the previous complete grid and writes a new grid, so scan order cannot affect output. A final connected-component pass merges one- and two-cell islands only when a neighboring color is an allowed candidate and its palette Delta E is no greater than `18`.

All configured sizes share the selected physical bead palette but are mapped and refined independently. Usage counts are computed from the final grid.

## Failure And Cache Behavior

Refinement failure is isolated by size. The affected size uses its already-computed nearest-color grid, other sizes remain refined, and `generation_diagnostics.fallback_sizes` records the degradation in the derived cache. Decode, catalog, palette selection, or base mapping failures retain the existing unavailable-event behavior.

The original refinement algorithm version was `lab-ciede2000-edge-refine-v2`; later size-set changes may advance the version while preserving this refinement profile. The complete generation profile, including the fixed refinement profile, remains the cache identity, so older entries are regenerated automatically. `generation_diagnostics` is cache-only and is not added to the `cover_pattern` WebSocket payload.

## Quality And Performance Gates

Synthetic quality fixtures must reduce isolated cells by at least 30 percent and adjacent color changes by at least 10 percent while increasing mean CIEDE2000 mapping error by no more than 10 percent. Current performance gates are defined by the active size-set design.

## External References

The design independently applies common fuse-bead generation ideas documented by PBDX and Beadify: fixed physical palettes, perceptual nearest-color mapping, same-color grouping, island cleanup, and edge/detail preservation. No source code or runtime dependency is copied from either project.
