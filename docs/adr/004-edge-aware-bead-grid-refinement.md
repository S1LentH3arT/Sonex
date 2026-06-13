# ADR-004: Add Edge-Aware Bead Grid Refinement

## Status

Accepted

## Context

Direct nearest-color mapping is perceptually accurate per cell but often produces scattered beads and frequent color changes in nearly flat regions. Global blur or unrestricted majority filtering would make patterns easier to build at the cost of crossing real boundaries and deleting eyes, text, and other small high-contrast details.

## Decision

Keep the shared Hama/Perler palette and direct CIEDE2000 mapping as the baseline. For each output size, retain four deterministic nearest candidates per cell, run two synchronous edge-weighted four-neighbor optimization rounds, and merge connected islands of at most two cells only when the target palette color is within Delta E 18. Use the fixed profile in cache identity and fall back per size when refinement alone fails.

## Alternatives Considered

- Majority filtering: simple, but ignores source edges and color distance.
- Global image smoothing before mapping: reduces noise, but permanently removes details before palette matching.
- Graph-cut or integer optimization: stronger global objectives, but excessive complexity and latency for interactive variants.
- User-facing tuning controls: flexible, but expands configuration and cache combinations without a demonstrated CLI need.

## Consequences

Patterns become more contiguous and construction-friendly while preserving strong details. Generation performs additional vectorized work and a small connected-component pass per size. Cache entries become incompatible with v1 and gain cache-only generation diagnostics; the WebSocket and TUI contracts remain unchanged.
