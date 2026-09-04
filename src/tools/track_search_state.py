"""Pure candidate shaping and identity rules for metadata search."""

from __future__ import annotations

import re
from typing import Any


def candidate(
    *,
    query: str,
    metadata_source: str,
    provider: str,
    item_id: str | None,
    name: str | None,
    artist: str | None,
    album: str | None,
    duration_ms: int,
    cover_url: str | None,
    url: str | None,
    uri: str | None,
    extra: dict[str, Any],
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "metadata_source": metadata_source,
        "provider": provider,
        "id": item_id,
        "name": name,
        "title": name,
        "artist": artist,
        "artists": [artist] if artist else [],
        "album": album,
        "duration_ms": duration_ms,
        "album_cover_url": cover_url,
        "cover_url": cover_url,
        "url": url,
        "uri": uri,
        "original_query": query,
        "youtube_query": f"{artist or ''} {name or ''}".strip() or query,
        **extra,
    }
    return {key: value for key, value in payload.items() if value not in (None, [], "")}


def is_credible(item: dict[str, Any]) -> bool:
    return bool(text(item.get("name") or item.get("title")) and text(item.get("artist")))


def dedupe_key(item: dict[str, Any]) -> str | None:
    name = normalize_key_text(item.get("name") or item.get("title"))
    artist = normalize_key_text(item.get("artist"))
    album = normalize_key_text(item.get("album"))
    if not name or not artist:
        return None
    return "|".join((name, artist, album))


def normalize_key_text(value: Any) -> str:
    return " ".join(re.findall(r"[\w\u4e00-\u9fff]+", str(value or "").casefold()))


def text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def int_ms(value: Any) -> int:
    try:
        return max(0, int(float(value or 0)))
    except (TypeError, ValueError):
        return 0


def seconds_to_ms(value: Any) -> int:
    try:
        return max(0, int(float(value or 0) * 1000))
    except (TypeError, ValueError):
        return 0


def release_year(value: Any) -> str | None:
    normalized = text(value)
    if not normalized:
        return None
    match = re.search(r"\d{4}", normalized)
    return match.group(0) if match else None
