# ADR-001: Keep Bead Generation In Process With Focused Modules

## Status

Accepted

## Context

Cover generation is asynchronous, CPU-bound, short-lived, and already launched through `asyncio.to_thread`. A separate service would add deployment, protocol, and failure-recovery complexity without a demonstrated scaling need.

## Decision

Keep generation in the Sonex process. Split catalog loading, configuration, color science, palette optimization, image orchestration, and cache/download responsibilities into separate modules.

## Alternatives Considered

- Keep all logic in `cover_patterns.py`: fewer files, but poor test isolation and ownership.
- Add a quantization service: independent scaling, but unnecessary operations and packaging cost.

## Consequences

Generation remains easy to install and follows current runtime behavior. CPU work still shares process resources, so the websocket path must continue using a worker thread and cache aggressively.
