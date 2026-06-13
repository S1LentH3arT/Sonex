# ADR-002: Use Lab, CIEDE2000, And Deterministic Greedy Palette Selection

## Status

Accepted

## Context

Weighted RGB nearest-neighbor mapping does not model perceptual differences well, and independently quantizing each size changes bead identity between terminal layouts.

## Decision

Convert D65 sRGB samples and catalog colors to Lab, precompute vectorized CIEDE2000 distances, and greedily select one shared palette. Select at least 32 colors, stop after 32 when the best relative improvement is below one percent, and cap at 48. Resolve ties by catalog order. Map all configured sizes directly without dithering.

## Alternatives Considered

- Weighted RGB nearest neighbor: faster but perceptually weaker.
- K-means followed by catalog snapping: compact, but initialization and snapping reduce determinism.
- Exact combinatorial optimization: stronger optimum guarantees, but impractical for interactive generation.

## Consequences

All sizes share stable physical bead identities and are deterministic. NumPy becomes a runtime dependency, and CIEDE2000 costs more CPU than RGB distance, mitigated by vectorization and caching.
