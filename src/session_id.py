"""Canonical identifiers for Sonex chat sessions."""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timezone


def create_uuid7(now: datetime | None = None) -> str:
    """Return a canonical RFC 9562 UUIDv7 string.

    Python 3.12 does not expose ``uuid.uuid7`` yet, so the 48-bit Unix
    millisecond timestamp and 74 cryptographically secure random bits are
    assembled directly according to the UUIDv7 wire layout.
    """

    timestamp = now or datetime.now(timezone.utc)
    timestamp_ms = int(timestamp.astimezone(timezone.utc).timestamp() * 1000)
    if not 0 <= timestamp_ms < (1 << 48):
        raise ValueError("UUIDv7 timestamp is outside the 48-bit range")

    random_bits = secrets.randbits(74)
    random_a = (random_bits >> 62) & 0xFFF
    random_b = random_bits & ((1 << 62) - 1)

    raw = bytearray(16)
    raw[0:6] = timestamp_ms.to_bytes(6, "big")
    raw[6] = 0x70 | (random_a >> 8)
    raw[7] = random_a & 0xFF
    raw[8] = 0x80 | (random_b >> 56)
    raw[9:16] = (random_b & ((1 << 56) - 1)).to_bytes(7, "big")
    return str(uuid.UUID(bytes=bytes(raw)))


def create_session_id(now: datetime | None = None) -> str:
    """Return Sonex's canonical chat-session identifier."""

    return create_uuid7(now)
