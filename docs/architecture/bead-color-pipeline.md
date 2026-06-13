# Physical Bead Color Pipeline

## Scope

Sonex renders album covers with one real 5 mm fuse-bead brand per image. The default is Hama Midi; `{"beads":{"brand":"perler"}}` selects Perler Classic. An explicit unsupported brand fails closed and hides artwork without interrupting playback.

## Data Flow

```text
beads.brand
  -> validated bundled catalog
  -> EXIF orientation, white alpha composite, square crop, <=640px
  -> contrast 1.05 and UnsharpMask(1.2, 60, 3)
  -> equal-weight 32/48/64/96/128/160/192 BOX samples with bounded L* edge weight
  -> D65 sRGB Lab and vectorized CIEDE2000 matrix
  -> deterministic greedy shared 32-48 color subset
  -> 15 independent direct Top-4, no-dither variant mappings
  -> two synchronous edge-aware continuity rounds per size
  -> low-Delta-E one- and two-cell island cleanup
  -> versioned derived JSON cache
  -> cover_pattern websocket event
```

`src/tools/cover_patterns.py` owns downloads, cache persistence, and the public API. Catalog parsing, color science, palette optimization, and image orchestration live in focused modules under `src/tools/`.

## Catalog Contract

Catalog resources are JSON files in `src/tools/bead_catalog_data`. They contain brand, product line, diameter, version, license, retrieval date, source records, a calibration disclaimer, and per-color source IDs. Runtime validation rejects unknown licenses, duplicate codes, invalid RGB values, missing sources, non-5 mm lines, and material values other than `standard_opaque`.

The color codes, names, and RGB approximations come from the MIT-licensed `maxcleme/beadcolors` dataset pinned to commit `29229889daab404fb30531d4bb785fd73f7f58e3`. Brand sites are identity and product-line references. RGB values are community approximations, not official measurements.

## Cache And Failure Behavior

The cache profile includes brand, product line, catalog version, algorithm version, size sets, enhancement parameters, color-budget settings, and the fixed refinement profile. Any mismatch invalidates the entry. Source image bytes are never persisted. Cache-only `generation_diagnostics` records per-size refinement changes and fallback sizes; it is deliberately omitted from the WebSocket payload.

Refinement failures are isolated to one size and use that size's direct nearest-color grid. Decode, catalog, palette selection, and base mapping failures still make the complete pattern unavailable.

Failures produce `cover_pattern_unavailable` with one of `invalid_brand`, `catalog_invalid`, `decode_failed`, or `generation_failed`. The CLI preserves the existing cover slot as blank and does not display generated atmosphere art. Playback state is unaffected.

## Verification

Tests cover catalog validation and package resources, D65 Lab references, Sharma CIEDE2000 pairs, deterministic tie handling, stopping rules, equal multiscale weighting through 192, direct mapping, cache invalidation, usage counts, failure events, resize states, generated image fixtures, and high-resolution payload bounds. The 640×640 development benchmark for all 15 variants should remain below three seconds; CI may use an eight-second ceiling.
