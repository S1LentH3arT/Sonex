from __future__ import annotations

from typing import Any


def normalize_track_shape(
    *,
    provider: str,
    track_id: Any = None,
    name: Any = None,
    artists: list[str] | None = None,
    album: Any = None,
    duration_ms: Any = None,
    cover_url: Any = None,
    url: Any = None,
    uri: Any = None,
    play_params: dict[str, Any] | None = None,
    is_playable: Any = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    artist_names = [str(artist) for artist in (artists or []) if artist]
    title = str(name) if name is not None else None
    data: dict[str, Any] = {
        "provider": provider,
        "id": track_id,
        "name": title,
        "title": title,
        "artist": ", ".join(artist_names),
        "artists": artist_names,
        "album": album,
        "duration_ms": duration_ms or 0,
        "cover_url": cover_url,
        "album_cover_url": cover_url,
        "url": url,
        "uri": uri,
        "play_params": play_params or {},
        "is_playable": is_playable,
    }
    if extra:
        data.update(extra)
    return data
