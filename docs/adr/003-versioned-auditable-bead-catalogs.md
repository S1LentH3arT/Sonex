# ADR-003: Bundle Versioned And Auditable Bead Catalogs

## Status

Accepted

## Context

Brand color lists and community RGB approximations change independently. Runtime downloads would make output non-reproducible and could silently introduce incompatible licenses or special materials.

## Decision

Bundle validated JSON catalogs for Hama Midi and Perler Classic. Pin source revisions, record licenses and retrieval dates, preserve per-color identity/RGB source IDs, label RGB as community approximation, and permit only standard opaque 5 mm colors. Include catalog and algorithm versions in cache identity and output metadata.

## Alternatives Considered

- Fetch catalogs at runtime: fresher data, but non-deterministic and network-dependent.
- Store RGB values without provenance: simpler, but not auditable.
- Retain the hand-authored generic palette: stable, but not tied to purchasable bead colors.

## Consequences

Builds are reproducible and failures are explicit. Catalog updates require source/license review, regeneration, validation, and a version change.
