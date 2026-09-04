"""Pure player state construction and input validation."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from typing import Any, Literal


PlayerName = Literal["mpv"]
PlaybackSource = Literal["local", "youtube", "spotify"]


@dataclass(frozen=True)
class PlayerState:
    provider: str
    source: PlaybackSource
    player: PlayerName
    session_id: str
    name: str
    artist: str
    album: str
    duration_ms: int
    progress_ms: int
    timestamp: int
    is_playing: bool
    paused_for_cache: bool = False
    diagnostic_notice: str | None = None
    id: str | None = None
    uri: str | None = None
    url: str | None = None
    stream_url: str | None = None
    album_cover_url: str | None = None
    volume_percent: int | None = None
    ended: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def timestamp_ms() -> int:
    return int(time.time() * 1000)


def coerce_ms(value: Any) -> int:
    try:
        return max(0, int(float(value or 0)))
    except (TypeError, ValueError):
        return 0


def coerce_volume(value: Any) -> int:
    try:
        volume = int(value)
    except (TypeError, ValueError):
        raise ValueError("Volume must be an integer from 0 to 100.") from None
    if not 0 <= volume <= 100:
        raise ValueError("Volume must be an integer from 0 to 100.")
    return volume


def metadata_state(
    *,
    metadata: dict[str, Any],
    source: PlaybackSource,
    player: PlayerName,
    session_id: str,
    progress_ms: int = 0,
    duration_ms: int | None = None,
    is_playing: bool = True,
    paused_for_cache: bool = False,
    diagnostic_notice: str | None = None,
    volume_percent: int | None = None,
    ended: bool = False,
) -> PlayerState:
    duration = coerce_ms(duration_ms if duration_ms is not None else metadata.get("duration_ms"))
    provider = str(metadata.get("provider") or source)
    return PlayerState(
        provider=provider,
        source=source,
        player=player,
        session_id=session_id,
        id=metadata.get("id"),
        name=str(metadata.get("name") or metadata.get("title") or metadata.get("file") or "-"),
        artist=str(metadata.get("artist") or "-"),
        album=str(metadata.get("album") or "-"),
        duration_ms=duration,
        progress_ms=coerce_ms(progress_ms),
        timestamp=timestamp_ms(),
        is_playing=is_playing,
        paused_for_cache=paused_for_cache,
        diagnostic_notice=diagnostic_notice,
        uri=metadata.get("uri"),
        url=metadata.get("url"),
        stream_url=metadata.get("stream_url"),
        album_cover_url=metadata.get("album_cover_url") or metadata.get("cover_url"),
        volume_percent=volume_percent,
        ended=ended,
    )
