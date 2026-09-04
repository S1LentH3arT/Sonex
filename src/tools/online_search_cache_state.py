"""Pure key and payload policy for online search cache entries."""

from __future__ import annotations

import hashlib
import unicodedata
from typing import Any


REMOVED_CACHE_KEYS = {
    "audio_path",
    "formats",
    "playback_source_url",
    "requested_downloads",
    "stream_url",
}


def normalize_cache_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return " ".join(text.split())


def make_cache_key(
    *,
    provider: str,
    artist: Any,
    title: Any,
    album: Any = "",
    variant_intent: Any = "default",
) -> str:
    identity = "\0".join(
        (
            normalize_cache_text(provider),
            normalize_cache_text(artist),
            normalize_cache_text(title),
            normalize_cache_text(album),
            normalize_cache_text(variant_intent),
        )
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def metadata_only(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): metadata_only(item)
            for key, item in value.items()
            if str(key) not in REMOVED_CACHE_KEYS
        }
    if isinstance(value, list):
        return [metadata_only(item) for item in value]
    return value
