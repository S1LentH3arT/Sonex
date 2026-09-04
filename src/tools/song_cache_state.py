"""Pure canonicalization rules for cached songs."""

from __future__ import annotations

import hashlib
from typing import Any


def text(value: Any) -> str:
    return str(value or "").strip()


def artists_text(item: dict[str, Any]) -> str:
    artist = text(item.get("artist"))
    if artist:
        return artist
    artists = item.get("artists")
    if isinstance(artists, list):
        return ", ".join(text(value) for value in artists if text(value))
    return ""


def cache_id_for(name: str, artist: str) -> str:
    digest = hashlib.sha1(f"{name.casefold()}|{artist.casefold()}".encode("utf-8")).hexdigest()
    return digest[:16]


def provider_summary(item: dict[str, Any]) -> list[dict[str, Any]]:
    provider = text(item.get("provider") or item.get("source"))
    summary: dict[str, Any] = {"provider": provider or "unknown"}
    for key in ("uri", "url", "stream_url", "cover_url", "album_cover_url"):
        if item.get(key):
            summary[f"has_{key}"] = True
    return [summary]


def merge_provider_details(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged = dict(existing)
    provider = text(incoming.get("provider") or incoming.get("source") or "unknown")
    providers = dict(merged.get("providers") or {})
    providers[provider] = dict(incoming)
    merged.update(incoming)
    merged["providers"] = providers
    return merged
