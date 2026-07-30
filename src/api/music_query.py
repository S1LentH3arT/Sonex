"""Deterministic music search query planning helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass


_MAX_VARIANTS = 5
_RECOMMENDATION_MARKERS = ("推荐", "recommend", "suggest")
_QUOTE_PATTERN = re.compile(r"^[《「『“\"](?P<track>[^》」』”\"]+)[》」』”\"]\s*(?P<artist>.+)$")
_BY_PATTERN = re.compile(r"^(?P<track>.+?)\s+by\s+(?P<artist>.+)$", re.IGNORECASE)
_SEPARATOR_PATTERN = re.compile(r"^(?P<artist>.+?)\s*[-—–]\s*(?P<track>.+)$")


@dataclass(frozen=True)
class MusicSearchQueryPlan:
    """A bounded set of Spotify search variants for one user-facing query."""

    original_query: str
    artist: str | None
    track: str | None
    variants: tuple[str, ...]


def _clean_part(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip(" \t\r\n,，.。!！?？:：;；'\"“”《》「」『』")
    cleaned = " ".join(cleaned.split())
    return cleaned or None


def _clean_query(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip(" \t\r\n,，.。!！?？:：;；")
    cleaned = " ".join(cleaned.split())
    return cleaned or None


def _looks_like_recommendation(query: str) -> bool:
    lowered = query.lower()
    return any(marker in lowered for marker in _RECOMMENDATION_MARKERS)


def _split_artist_track(query: str) -> tuple[str | None, str | None]:
    quoted = _QUOTE_PATTERN.match(query)
    if quoted:
        return _clean_part(quoted.group("artist")), _clean_part(quoted.group("track"))

    by_match = _BY_PATTERN.match(query)
    if by_match:
        return _clean_part(by_match.group("artist")), _clean_part(by_match.group("track"))

    separator = _SEPARATOR_PATTERN.match(query)
    if separator:
        return _clean_part(separator.group("artist")), _clean_part(separator.group("track"))

    if "的" in query and not _looks_like_recommendation(query):
        artist, track = query.split("的", 1)
        clean_artist = _clean_part(artist)
        clean_track = _clean_part(track)
        if clean_artist and clean_track and clean_track not in {"歌", "歌曲", "音乐"}:
            return clean_artist, clean_track

    parts = query.split()
    if len(parts) >= 2 and all(re.search(r"[\u4e00-\u9fff]", part) for part in parts[:2]):
        artist = _clean_part(parts[0])
        track = _clean_part(" ".join(parts[1:]))
        if artist and track:
            return artist, track

    return None, _clean_part(query)


def _unique_variants(candidates: list[str | None]) -> tuple[str, ...]:
    variants: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        cleaned = _clean_part(candidate)
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        variants.append(cleaned)
        if len(variants) >= _MAX_VARIANTS:
            break
    return tuple(variants)


def build_music_search_query_plan(query: str) -> MusicSearchQueryPlan:
    """Builds a deterministic, bounded Spotify search plan for a playback query."""
    original_query = _clean_query(query) or ""
    if not original_query:
        return MusicSearchQueryPlan(original_query="", artist=None, track=None, variants=())
    if _looks_like_recommendation(original_query):
        return MusicSearchQueryPlan(
            original_query=original_query,
            artist=None,
            track=None,
            variants=(original_query,),
        )

    artist, track = _split_artist_track(original_query)
    if artist and track:
        variants = _unique_variants([
            f"track:{track} artist:{artist}",
            f"{artist} {track}",
            f"{track} {artist}",
            original_query,
            track,
        ])
    else:
        variants = (original_query,)
    return MusicSearchQueryPlan(
        original_query=original_query,
        artist=artist,
        track=track,
        variants=variants,
    )
