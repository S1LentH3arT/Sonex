"""Online play support for tool implementations used by the planner and playback flows.

Implements the online_play module responsibilities used by Sonex runtime flows.
Key public entry points include OnlineAudioSetupRequired, OnlineAudioConfig, online_audio_config, os_value, online_audio_configured.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import yt_dlp

from src.auth.store import get_provider_auth, load_auth_store
from src.llm.transport import sanitize_error_message
from src.log import sonex_home
from src.tools import cover_sources, spotify_play
from src.tools.local_play import check_player
from src.tools.player_permission import (
    build_player_confirm_result,
    is_player_allowed,
)
from src.tools.playback_controller import start_local_playback
from src.tools.registry import registry, Params
from src.tools.result import ToolResult
from src.tools.song_cache import resolve_cached_song, upsert_cached_song

LIVE_TERMS = ("live", "concert", "session", "现场", "演唱会")
LOW_RELEVANCE_TERMS = ("cover", "tutorial", "reaction", "karaoke", "翻唱", "教程", "伴奏")
OFFICIAL_TERMS = ("official audio", "official music video", "official video", "official mv")
NOISY_MEDIA_TERMS = (
    "tv",
    "television",
    "show",
    "variety",
    "interview",
    "reaction",
    "karaoke",
    "tutorial",
    "综艺",
    "电视",
    "节目",
    "访谈",
    "教程",
    "伴奏",
)
COVER_TERMS = ("cover", "翻唱")
QUERY_FILLER_TERMS = {"the", "a", "an"}
AGE_RESTRICTED_MESSAGE = (
    "Selected YouTube result requires age verification. "
    "Choose another candidate or refine the search."
)
UNAVAILABLE_MESSAGE = (
    "Selected YouTube result is not available. "
    "Choose another candidate or refine the search."
)
ONLINE_AUDIO_SETUP_MESSAGE = (
    "Online playback requires Jamendo or Audius setup. "
    "Run /setup jamendo or /setup audius first."
)


class OnlineAudioSetupRequired(RuntimeError):
    """Represents online audio setup required.

    Encapsulates online audio setup required data and behavior used by Sonex runtime flows. Extends runtime error semantics.
    """
    pass


@dataclass(frozen=True, slots=True)
class OnlineAudioConfig:
    """Represents online audio config.

    Encapsulates online audio config data and behavior used by Sonex runtime flows.
    """
    jamendo_client_id: str | None = None
    audius_api_key: str | None = None


def _song_cache_root(cache_root: Path | None = None) -> Path:
    """Song cache root.

    Coordinates song cache root logic for the surrounding Sonex flow.

    Args:
        cache_root: Input value used by the song cache root operation.

    Returns:
        The computed result for song cache root.
    """
    return cache_root or sonex_home() / "cache" / "songs"


def _audio_cache_dir(cache_root: Path | None = None) -> Path:
    """Audio cache dir.

    Coordinates audio cache dir logic for the surrounding Sonex flow.

    Args:
        cache_root: Input value used by the audio cache dir operation.

    Returns:
        The computed result for audio cache dir.
    """
    return _song_cache_root(cache_root) / "audio"


def online_audio_config() -> OnlineAudioConfig:
    """Online audio config.

    Coordinates online audio config logic for the surrounding Sonex flow.

    Returns:
        The computed result for online audio config.
    """
    jamendo_client_id = _text(
        os_value("SONEX_JAMENDO_CLIENT_ID")
        or os_value("JAMENDO_CLIENT_ID")
    )
    audius_api_key = _text(
        os_value("SONEX_AUDIUS_API_KEY")
        or os_value("AUDIUS_API_KEY")
    )
    try:
        store = load_auth_store()
    except Exception:
        store = None
    if store:
        jamendo_auth = get_provider_auth(store, "jamendo")
        audius_auth = get_provider_auth(store, "audius")
        jamendo_client_id = jamendo_client_id or _text(jamendo_auth.api_key if jamendo_auth else None)
        audius_api_key = audius_api_key or _text(audius_auth.api_key if audius_auth else None)
    return OnlineAudioConfig(jamendo_client_id=jamendo_client_id, audius_api_key=audius_api_key)


def os_value(name: str) -> str | None:
    """Os value.

    Coordinates os value logic for the surrounding Sonex flow.

    Args:
        name: Input value used by the os value operation.

    Returns:
        The computed result for os value.
    """
    import os

    return os.environ.get(name)


def online_audio_configured(config: OnlineAudioConfig | None = None) -> bool:
    """Online audio configured.

    Coordinates online audio configured logic for the surrounding Sonex flow.

    Args:
        config: Input value used by the online audio configured operation.

    Returns:
        The computed result for online audio configured.
    """
    resolved = config or online_audio_config()
    return bool(resolved.jamendo_client_id or resolved.audius_api_key)


def _text(value: Any) -> str | None:
    """Text.

    Coordinates text logic for the surrounding Sonex flow.

    Args:
        value: Input value used by the text operation.

    Returns:
        The computed result for text.
    """
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _joined_text(value: Any) -> str | None:
    """Joined text.

    Coordinates joined text logic for the surrounding Sonex flow.

    Args:
        value: Input value used by the joined text operation.

    Returns:
        The computed result for joined text.
    """
    if isinstance(value, list):
        parts = [_text(item) for item in value]
        return ", ".join(part for part in parts if part) or None
    return _text(value)


def _non_placeholder_text(value: Any) -> str | None:
    """Non placeholder text.

    Coordinates non placeholder text logic for the surrounding Sonex flow.

    Args:
        value: Input value used by the non placeholder text operation.

    Returns:
        The computed result for non placeholder text.
    """
    text = _joined_text(value)
    if text in {None, "-"}:
        return None
    return text


def _spotify_tracks_from_result(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Spotify tracks from result.

    Coordinates spotify tracks from result logic for the surrounding Sonex flow.

    Args:
        result: Input value used by the spotify tracks from result operation.

    Returns:
        The computed result for spotify tracks from result.
    """
    if str(result.get("status") or "").lower() != "success":
        return []
    data = result.get("data")
    tracks = data.get("tracks") if isinstance(data, dict) else None
    if not isinstance(tracks, list) or not tracks:
        return []
    return [track for track in tracks if isinstance(track, dict)]


def _spotify_track_metadata(query: str, track: dict[str, Any]) -> dict[str, Any] | None:
    """Spotify track metadata.

    Coordinates spotify track metadata logic for the surrounding Sonex flow.

    Args:
        query: Input value used by the spotify track metadata operation.
        track: Input value used by the spotify track metadata operation.

    Returns:
        The computed result for spotify track metadata.
    """
    name = _non_placeholder_text(track.get("name") or track.get("title"))
    artist = _non_placeholder_text(track.get("artist") or track.get("artists"))
    if not name or not artist:
        return None
    raw_artists = track.get("artists") if isinstance(track.get("artists"), list) else [artist]
    artists = [str(item) for item in raw_artists if _non_placeholder_text(item)]
    youtube_query = f"{artist} {name}".strip()
    return {
        "metadata_source": "spotify",
        "original_query": query,
        "youtube_query": youtube_query,
        "id": _non_placeholder_text(track.get("id")),
        "name": name,
        "title": name,
        "artist": artist,
        "artists": artists,
        "album": _non_placeholder_text(track.get("album")) or "-",
        "duration_ms": int(track.get("duration_ms") or 0),
        "spotify_url": _non_placeholder_text(track.get("spotify_url")),
        "uri": _non_placeholder_text(track.get("uri")),
        "spotify_track_id": _non_placeholder_text(track.get("id")),
    }


def search_spotify_track_candidates(query: str, limit: int = 5) -> list[dict[str, Any]]:
    """Search spotify track candidates.

    Coordinates search spotify track candidates logic for the surrounding Sonex flow.

    Args:
        query: Input value used by the search spotify track candidates operation.
        limit: Input value used by the search spotify track candidates operation.

    Returns:
        The computed result for search spotify track candidates.
    """
    clean_query = query.strip()
    if not clean_query:
        return []
    bounded_limit = max(1, min(10, int(limit or 5)))
    try:
        result = spotify_play.spotify_search(query=clean_query, limit=bounded_limit, types="track")
    except Exception:
        return []
    if not isinstance(result, dict):
        return []
    candidates: list[dict[str, Any]] = []
    for track in _spotify_tracks_from_result(result):
        metadata = _spotify_track_metadata(clean_query, track)
        if metadata:
            candidates.append(metadata)
        if len(candidates) >= bounded_limit:
            break
    return candidates


def _query_fallback_metadata(query: str) -> dict[str, Any]:
    """Query fallback metadata.

    Coordinates query fallback metadata logic for the surrounding Sonex flow.

    Args:
        query: Input value used by the query fallback metadata operation.

    Returns:
        The computed result for query fallback metadata.
    """
    clean_query = query.strip()
    return {
        "metadata_source": "query_fallback",
        "original_query": clean_query,
        "youtube_query": clean_query,
    }


def _resolved_playback_metadata(query: str, playback_metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    """Resolved playback metadata.

    Coordinates resolved playback metadata logic for the surrounding Sonex flow.

    Args:
        query: Input value used by the resolved playback metadata operation.
        playback_metadata: Input value used by the resolved playback metadata operation.

    Returns:
        The computed result for resolved playback metadata.
    """
    if not isinstance(playback_metadata, dict) or not playback_metadata:
        return _query_fallback_metadata(query)

    metadata = _canonical_metadata({**playback_metadata, "metadata_source": playback_metadata.get("metadata_source") or playback_metadata.get("provider") or "metadata"})
    if not metadata.get("original_query"):
        metadata["original_query"] = query.strip()
    if not metadata.get("youtube_query"):
        artist = _non_placeholder_text(metadata.get("artist"))
        name = _non_placeholder_text(metadata.get("name") or metadata.get("title"))
        metadata["youtube_query"] = f"{artist or ''} {name or ''}".strip() or query.strip()
    if metadata.get("metadata_source") == "spotify":
        if metadata.get("cover_source_type") != "cover_art_archive":
            for key in ("album_cover_url", "cover_url", "cover_source", "cover_source_type"):
                metadata.pop(key, None)
            cover = cover_sources.resolve_online_cover(metadata)
            if cover and cover.get("source_type") == "cover_art_archive":
                metadata["album_cover_url"] = cover["cover_source"]
                metadata["cover_url"] = cover.get("cover_url") or cover["cover_source"]
                metadata["cover_source"] = cover["cover_source"]
                metadata["cover_source_type"] = cover["source_type"]
    elif not metadata.get("album_cover_url") and not metadata.get("cover_url"):
        cover = cover_sources.resolve_online_cover(metadata)
        if cover:
            metadata["album_cover_url"] = cover["cover_source"]
            metadata["cover_url"] = cover.get("cover_url") or cover["cover_source"]
            metadata["cover_source"] = cover["cover_source"]
            metadata["cover_source_type"] = cover["source_type"]
    return metadata


def resolve_online_playback_metadata(query: str, playback_metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    """Resolve online playback metadata.

    Coordinates resolve online playback metadata logic for the surrounding Sonex flow.

    Args:
        query: Input value used by the resolve online playback metadata operation.
        playback_metadata: Input value used by the resolve online playback metadata operation.

    Returns:
        The computed result for resolve online playback metadata.
    """
    return _resolved_playback_metadata(query, playback_metadata)


def _canonical_metadata(item: dict[str, Any]) -> dict[str, Any]:
    """Canonical metadata.

    Coordinates canonical metadata logic for the surrounding Sonex flow.

    Args:
        item: Input value used by the canonical metadata operation.

    Returns:
        The computed result for canonical metadata.
    """
    metadata: dict[str, Any] = {}
    source = str(item.get("metadata_source") or item.get("provider") or "").strip().lower()
    confirmed_metadata = bool(source and source not in {"query_fallback", "youtube", "jamendo", "audius", "online_audio"})
    base_keys = (
        "metadata_source",
        "original_query",
        "youtube_query",
        "cover_source",
        "cover_source_type",
    )
    metadata_keys = (
        "provider",
        "id",
        "name",
        "title",
        "artist",
        "artists",
        "album",
        "duration_ms",
        "album_cover_url",
        "cover_url",
        "url",
        "itunes_url",
        "deezer_url",
        "musicbrainz_url",
        "musicbrainz_recording_id",
    )
    spotify_keys = (
        "spotify_url",
        "uri",
        "spotify_track_id",
    )
    generic_keys = ("uri",)
    keys = base_keys + (metadata_keys + generic_keys if confirmed_metadata else ()) + (spotify_keys if item.get("metadata_source") == "spotify" else ())
    for key in keys:
        if key in item and item.get(key) is not None:
            metadata[key] = item[key]
    return metadata


def _merge_canonical_metadata(item: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    """Merge canonical metadata.

    Coordinates merge canonical metadata logic for the surrounding Sonex flow.

    Args:
        item: Input value used by the merge canonical metadata operation.
        metadata: Input value used by the merge canonical metadata operation.

    Returns:
        The computed result for merge canonical metadata.
    """
    if not metadata:
        return item
    merged = dict(item)
    for key, value in metadata.items():
        if value is None:
            continue
        if key in {
            "name",
            "title",
            "artist",
            "artists",
            "album",
            "duration_ms",
            "spotify_url",
            "uri",
            "spotify_track_id",
            "itunes_url",
            "deezer_url",
            "musicbrainz_url",
            "musicbrainz_recording_id",
        }:
            merged[key] = value
        else:
            if not merged.get(key):
                merged[key] = value
    return merged


def _duration_ms(value: Any) -> int:
    """Duration ms.

    Coordinates duration ms logic for the surrounding Sonex flow.

    Args:
        value: Input value used by the duration ms operation.

    Returns:
        The computed result for duration ms.
    """
    try:
        return max(0, int(float(value or 0) * 1000))
    except (TypeError, ValueError):
        return 0


def _count(value: Any) -> int:
    """Count.

    Coordinates count logic for the surrounding Sonex flow.

    Args:
        value: Input value used by the count operation.

    Returns:
        The computed result for count.
    """
    try:
        return max(0, int(float(value or 0)))
    except (TypeError, ValueError):
        return 0


def _words(value: str) -> list[str]:
    """Words.

    Coordinates words logic for the surrounding Sonex flow.

    Args:
        value: Input value used by the words operation.

    Returns:
        The computed result for words.
    """
    return re.findall(r"[\w\u4e00-\u9fff]+", value.casefold())


def _normalized_rank_text(value: str) -> str:
    """Normalized rank text.

    Coordinates normalized rank text logic for the surrounding Sonex flow.

    Args:
        value: Input value used by the normalized rank text operation.

    Returns:
        The computed result for normalized rank text.
    """
    return " ".join(_words(value))


def _query_terms(query: str) -> list[str]:
    """Query terms.

    Coordinates query terms logic for the surrounding Sonex flow.

    Args:
        query: Input value used by the query terms operation.

    Returns:
        The computed result for query terms.
    """
    terms = _words(query)
    return [term for term in terms if term not in QUERY_FILLER_TERMS and term not in LIVE_TERMS]


def _contains_any(value: str, terms: tuple[str, ...]) -> bool:
    """Contains any.

    Coordinates contains any logic for the surrounding Sonex flow.

    Args:
        value: Input value used by the contains any operation.
        terms: Input value used by the contains any operation.

    Returns:
        The computed result for contains any.
    """
    text = value.casefold()
    return any(term in text for term in terms)


def _variant_type(query: str, info: dict[str, Any]) -> str:
    """Variant type.

    Coordinates variant type logic for the surrounding Sonex flow.

    Args:
        query: Input value used by the variant type operation.
        info: Input value used by the variant type operation.

    Returns:
        The computed result for variant type.
    """
    title = _text(info.get("track") or info.get("title") or info.get("fulltitle") or "") or ""
    channel = _text(info.get("channel") or info.get("uploader") or "") or ""
    combined = f"{title} {channel}".casefold()
    if _contains_any(combined, LIVE_TERMS):
        return "live"
    if _contains_any(combined, OFFICIAL_TERMS) or " - topic" in combined or "official" in channel.casefold() or "vevo" in channel.casefold():
        return "official_original"
    return "other"


def _rank_title(info: dict[str, Any]) -> str:
    """Rank title.

    Coordinates rank title logic for the surrounding Sonex flow.

    Args:
        info: Input value used by the rank title operation.

    Returns:
        The computed result for rank title.
    """
    return _text(info.get("track") or info.get("title") or info.get("fulltitle") or "") or ""


def _rank_channel(info: dict[str, Any]) -> str:
    """Rank channel.

    Coordinates rank channel logic for the surrounding Sonex flow.

    Args:
        info: Input value used by the rank channel operation.

    Returns:
        The computed result for rank channel.
    """
    return _text(info.get("channel") or info.get("uploader") or "") or ""


def _rank_artist(info: dict[str, Any]) -> str:
    """Rank artist.

    Coordinates rank artist logic for the surrounding Sonex flow.

    Args:
        info: Input value used by the rank artist operation.

    Returns:
        The computed result for rank artist.
    """
    return (
        _non_placeholder_text(info.get("artist"))
        or _non_placeholder_text(info.get("artists"))
        or _non_placeholder_text(info.get("creator"))
        or _non_placeholder_text(info.get("creators"))
        or ""
    )


def _rank_haystack(info: dict[str, Any]) -> str:
    """Rank haystack.

    Coordinates rank haystack logic for the surrounding Sonex flow.

    Args:
        info: Input value used by the rank haystack operation.

    Returns:
        The computed result for rank haystack.
    """
    return " ".join(
        str(value or "")
        for value in (
            info.get("track"),
            info.get("title"),
            info.get("fulltitle"),
            info.get("artist"),
            info.get("artists"),
            info.get("creator"),
            info.get("uploader"),
            info.get("channel"),
        )
    )


def _similarity_score(query: str, info: dict[str, Any]) -> int:
    """Similarity score.

    Coordinates similarity score logic for the surrounding Sonex flow.

    Args:
        query: Input value used by the similarity score operation.
        info: Input value used by the similarity score operation.

    Returns:
        The computed result for similarity score.
    """
    query_norm = _normalized_rank_text(query)
    if not query_norm:
        return 0

    title_norm = _normalized_rank_text(_rank_title(info))
    artist_norm = _normalized_rank_text(_rank_artist(info) or _rank_channel(info))
    variants = [title_norm]
    if artist_norm and title_norm:
        variants.extend((f"{artist_norm} {title_norm}", f"{title_norm} {artist_norm}"))
    best_ratio = max((SequenceMatcher(None, query_norm, value).ratio() for value in variants if value), default=0.0)

    terms = _query_terms(query)
    haystack_words = set(_words(_rank_haystack(info)))
    coverage = sum(1 for term in terms if term in haystack_words) / len(terms) if terms else 0.0
    return round((best_ratio * 0.6 + coverage * 0.4) * 100)


def _clean_title_match(query: str, info: dict[str, Any], similarity: int) -> bool:
    """Clean title match.

    Coordinates clean title match logic for the surrounding Sonex flow.

    Args:
        query: Input value used by the clean title match operation.
        info: Input value used by the clean title match operation.
        similarity: Input value used by the clean title match operation.

    Returns:
        The computed result for clean title match.
    """
    title = _rank_title(info)
    if similarity < 70:
        return False
    if _contains_any(title, LIVE_TERMS + LOW_RELEVANCE_TERMS + NOISY_MEDIA_TERMS):
        return False
    return " - " in title or " – " in title or " — " in title or similarity >= 86


def _quality_label(query: str, info: dict[str, Any], variant: str, similarity: int) -> str:
    """Quality label.

    Coordinates quality label logic for the surrounding Sonex flow.

    Args:
        query: Input value used by the quality label operation.
        info: Input value used by the quality label operation.
        variant: Input value used by the quality label operation.
        similarity: Input value used by the quality label operation.

    Returns:
        The computed result for quality label.
    """
    combined = f"{_rank_title(info)} {_rank_channel(info)}".casefold()
    live_requested = _contains_any(query, LIVE_TERMS)
    if variant == "live":
        return "live"
    if variant == "official_original":
        return "official_original"
    if not live_requested and _contains_any(combined, COVER_TERMS):
        return "cover_like"
    if not live_requested and _contains_any(combined, NOISY_MEDIA_TERMS):
        return "noisy_media"
    if _clean_title_match(query, info, similarity):
        return "clean_audio_match"
    return "other"


def _provider_cache_id(provider: str, provider_id: str | None, source_url: str | None = None) -> str:
    """Provider cache id.

    Coordinates provider cache id logic for the surrounding Sonex flow.

    Args:
        provider: Input value used by the provider cache id operation.
        provider_id: Input value used by the provider cache id operation.
        source_url: Input value used by the provider cache id operation.

    Returns:
        The computed result for provider cache id.
    """
    if provider_id:
        return f"{provider}_{provider_id}"
    digest_source = source_url or provider
    digest = hashlib.sha1(digest_source.encode("utf-8")).hexdigest()[:16]
    return f"{provider}_{digest}"


def _open_audio_candidate(
    *,
    provider: str,
    provider_id: str | None,
    query: str,
    name: str,
    artist: str,
    album: str | None,
    duration_ms: int,
    cover_url: str | None,
    source_url: str,
    download_url: str | None,
    webpage_url: str | None,
    playback_metadata: dict[str, Any] | None = None,
    extra_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Open audio candidate.

    Coordinates open audio candidate logic for the surrounding Sonex flow.

    Args:
        provider: Input value used by the open audio candidate operation.
        provider_id: Input value used by the open audio candidate operation.
        query: Input value used by the open audio candidate operation.
        name: Input value used by the open audio candidate operation.
        artist: Input value used by the open audio candidate operation.
        album: Input value used by the open audio candidate operation.
        duration_ms: Input value used by the open audio candidate operation.
        cover_url: Input value used by the open audio candidate operation.
        source_url: Input value used by the open audio candidate operation.
        download_url: Input value used by the open audio candidate operation.
        webpage_url: Input value used by the open audio candidate operation.
        playback_metadata: Input value used by the open audio candidate operation.
        extra_metadata: Input value used by the open audio candidate operation.

    Returns:
        The computed result for open audio candidate.
    """
    info = {
        "id": provider_id,
        "title": name,
        "track": name,
        "artist": artist,
        "album": album,
    }
    variant = _variant_type(query, info)
    similarity = _similarity_score(query, info)
    quality = _quality_label(query, info, variant, similarity)
    metadata = _canonical_metadata(playback_metadata or {})
    candidate: dict[str, Any] = {
        "provider": provider,
        "id": provider_id,
        "cache_id": _provider_cache_id(provider, provider_id, source_url),
        "query": query,
        "name": name,
        "title": name,
        "artist": artist or "-",
        "artists": [artist] if artist else [],
        "album": album or "-",
        "duration_ms": duration_ms,
        "album_cover_url": cover_url,
        "cover_url": cover_url,
        "source_url": source_url,
        "download_url": download_url or source_url,
        "webpage_url": webpage_url,
        "url": webpage_url,
        "stream_url": source_url,
        "quality_label": quality,
        "variant_type": variant,
        "similarity_score": similarity,
        "relevance_score": _relevance_score(query, info),
        "popularity_score": 0,
        "rank_reason": _rank_reason(variant, 0, _relevance_score(query, info), similarity, quality),
        "playback_metadata": metadata,
        "cached": False,
        "is_playing": True,
    }
    if extra_metadata:
        candidate["playback_metadata"] = {**metadata, **extra_metadata}
    return _merge_canonical_metadata(candidate, metadata)


def normalize_jamendo_track(
    track: dict[str, Any],
    *,
    query: str,
    playback_metadata: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Normalize jamendo track.

    Coordinates normalize jamendo track logic for the surrounding Sonex flow.

    Args:
        track: Input value used by the normalize jamendo track operation.
        query: Input value used by the normalize jamendo track operation.
        playback_metadata: Input value used by the normalize jamendo track operation.

    Returns:
        The computed result for normalize jamendo track.
    """
    source_url = _text(track.get("audio"))
    download_url = _text(track.get("audiodownload"))
    if not source_url and not download_url:
        return None
    provider_id = _text(track.get("id"))
    name = _text(track.get("name") or track.get("title") or query) or query
    artist = _text(track.get("artist_name") or track.get("artist")) or "-"
    cover_url = _text(track.get("album_image") or track.get("image"))
    return _open_audio_candidate(
        provider="jamendo",
        provider_id=provider_id,
        query=query,
        name=name,
        artist=artist,
        album=_text(track.get("album_name") or track.get("album")),
        duration_ms=_duration_ms(track.get("duration")),
        cover_url=cover_url,
        source_url=source_url or str(download_url),
        download_url=download_url or source_url,
        webpage_url=_text(track.get("shareurl") or track.get("shorturl")),
        playback_metadata=playback_metadata,
        extra_metadata={"tags": track.get("tags") or []},
    )


def _best_audius_artwork(track: dict[str, Any]) -> str | None:
    """Best audius artwork.

    Coordinates best audius artwork logic for the surrounding Sonex flow.

    Args:
        track: Input value used by the best audius artwork operation.

    Returns:
        The computed result for best audius artwork.
    """
    artwork = track.get("artwork")
    if not isinstance(artwork, dict):
        return None
    for key in ("1000x1000", "480x480", "150x150"):
        url = _text(artwork.get(key))
        if url:
            return url
    return None


def _audius_user_name(track: dict[str, Any]) -> str | None:
    """Audius user name.

    Coordinates audius user name logic for the surrounding Sonex flow.

    Args:
        track: Input value used by the audius user name operation.

    Returns:
        The computed result for audius user name.
    """
    user = track.get("user")
    if isinstance(user, dict):
        return _text(user.get("name") or user.get("handle"))
    return None


def _is_audius_stream_gated(track: dict[str, Any]) -> bool:
    """Is audius stream gated.

    Coordinates is audius stream gated logic for the surrounding Sonex flow.

    Args:
        track: Input value used by the is audius stream gated operation.

    Returns:
        The computed result for is audius stream gated.
    """
    if bool(track.get("is_stream_gated")):
        return True
    availability = str(track.get("stream_conditions") or "").casefold()
    return bool(availability and availability not in {"none", "null"})


def normalize_audius_track(
    track: dict[str, Any],
    *,
    query: str,
    stream_url: str,
    playback_metadata: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Normalize audius track.

    Coordinates normalize audius track logic for the surrounding Sonex flow.

    Args:
        track: Input value used by the normalize audius track operation.
        query: Input value used by the normalize audius track operation.
        stream_url: Input value used by the normalize audius track operation.
        playback_metadata: Input value used by the normalize audius track operation.

    Returns:
        The computed result for normalize audius track.
    """
    if _is_audius_stream_gated(track):
        return None
    provider_id = _text(track.get("id"))
    if not provider_id or not _text(stream_url):
        return None
    name = _text(track.get("title") or track.get("name") or query) or query
    artist = _audius_user_name(track) or _text(track.get("artist")) or "-"
    return _open_audio_candidate(
        provider="audius",
        provider_id=provider_id,
        query=query,
        name=name,
        artist=artist,
        album=_text(track.get("album") or track.get("playlist_name")),
        duration_ms=_duration_ms(track.get("duration")),
        cover_url=_best_audius_artwork(track),
        source_url=stream_url,
        download_url=stream_url,
        webpage_url=_text(track.get("permalink") or track.get("permalink_url")),
        playback_metadata=playback_metadata,
    )


def _popularity_tiebreaker(popularity: int) -> int:
    """Popularity tiebreaker.

    Coordinates popularity tiebreaker logic for the surrounding Sonex flow.

    Args:
        popularity: Input value used by the popularity tiebreaker operation.

    Returns:
        The computed result for popularity tiebreaker.
    """
    return round(math.log10(max(0, popularity) + 1) * 1000)


def _relevance_score(query: str, info: dict[str, Any]) -> int:
    """Relevance score.

    Coordinates relevance score logic for the surrounding Sonex flow.

    Args:
        query: Input value used by the relevance score operation.
        info: Input value used by the relevance score operation.

    Returns:
        The computed result for relevance score.
    """
    terms = _query_terms(query)
    if not terms:
        return 0
    haystack = _rank_haystack(info).casefold()
    return sum(1 for term in terms if term in haystack)


def _popularity_score(info: dict[str, Any]) -> int:
    """Popularity score.

    Coordinates popularity score logic for the surrounding Sonex flow.

    Args:
        info: Input value used by the popularity score operation.

    Returns:
        The computed result for popularity score.
    """
    view_count = _count(info.get("view_count"))
    like_count = _count(info.get("like_count"))
    comment_count = _count(info.get("comment_count"))
    repost_count = _count(info.get("repost_count"))
    return view_count + like_count * 20 + comment_count * 5 + repost_count * 10


def _rank_reason(variant: str, popularity: int, relevance: int, similarity: int, quality: str) -> str:
    """Rank reason.

    Coordinates rank reason logic for the surrounding Sonex flow.

    Args:
        variant: Input value used by the rank reason operation.
        popularity: Input value used by the rank reason operation.
        relevance: Input value used by the rank reason operation.
        similarity: Input value used by the rank reason operation.
        quality: Input value used by the rank reason operation.

    Returns:
        The computed result for rank reason.
    """
    label = {
        "official_original": "official original",
        "live": "live version",
        "other": "other match",
    }.get(variant, "other match")
    return f"{label}; quality={quality}; similarity={similarity}; popularity={popularity}; relevance={relevance}"


def _is_age_restricted_info(info: dict[str, Any]) -> bool:
    """Is age restricted info.

    Coordinates is age restricted info logic for the surrounding Sonex flow.

    Args:
        info: Input value used by the is age restricted info operation.

    Returns:
        The computed result for is age restricted info.
    """
    try:
        age_limit = int(info.get("age_limit") or 0)
    except (TypeError, ValueError):
        age_limit = 0
    if age_limit > 0:
        return True
    availability = str(info.get("availability") or "").casefold()
    return availability == "needs_auth"


def _is_unavailable_info(info: dict[str, Any]) -> bool:
    """Is unavailable info.

    Coordinates is unavailable info logic for the surrounding Sonex flow.

    Args:
        info: Input value used by the is unavailable info operation.

    Returns:
        The computed result for is unavailable info.
    """
    availability = str(info.get("availability") or "").casefold()
    return availability in {
        "unavailable",
        "private",
        "premium_only",
        "subscriber_only",
        "needs_subscription",
        "needs_premium",
    }


def _is_age_verification_error(message: str) -> bool:
    """Is age verification error.

    Coordinates is age verification error logic for the surrounding Sonex flow.

    Args:
        message: Input value used by the is age verification error operation.

    Returns:
        The computed result for is age verification error.
    """
    text = message.casefold()
    return (
        "confirm your age" in text
        or "age verification" in text
        or "may be inappropriate for some users" in text
    )


def _is_unavailable_error(message: str) -> bool:
    """Is unavailable error.

    Coordinates is unavailable error logic for the surrounding Sonex flow.

    Args:
        message: Input value used by the is unavailable error operation.

    Returns:
        The computed result for is unavailable error.
    """
    text = message.casefold()
    return (
        "this video is not available" in text
        or "video unavailable" in text
        or "private video" in text
        or "members-only" in text
        or "join this channel" in text
    )


def _should_keep_candidate(query: str, info: dict[str, Any]) -> bool:
    """Should keep candidate.

    Coordinates should keep candidate logic for the surrounding Sonex flow.

    Args:
        query: Input value used by the should keep candidate operation.
        info: Input value used by the should keep candidate operation.

    Returns:
        The computed result for should keep candidate.
    """
    if _is_age_restricted_info(info) or _is_unavailable_info(info):
        return False
    title = _rank_title(info)
    if not title:
        return bool(_text(info.get("id")) or _webpage_url(info))
    if _relevance_score(query, info) <= 0:
        return False
    if not _contains_any(query, LOW_RELEVANCE_TERMS) and _contains_any(title, LOW_RELEVANCE_TERMS):
        return False
    return True


def _best_thumbnail(info: dict[str, Any]) -> str | None:
    """Best thumbnail.

    Coordinates best thumbnail logic for the surrounding Sonex flow.

    Args:
        info: Input value used by the best thumbnail operation.

    Returns:
        The computed result for best thumbnail.
    """
    direct = _text(info.get("thumbnail"))
    if direct:
        return direct

    thumbnails = info.get("thumbnails")
    if not isinstance(thumbnails, list):
        return None
    candidates = [item for item in thumbnails if isinstance(item, dict) and item.get("url")]
    if not candidates:
        return None
    candidates.sort(
        key=lambda item: (item.get("width") or 0) * (item.get("height") or 0),
        reverse=True,
    )
    return _text(candidates[0].get("url"))


def _audio_stream_url(info: dict[str, Any]) -> str:
    """Audio stream url.

    Coordinates audio stream url logic for the surrounding Sonex flow.

    Args:
        info: Input value used by the audio stream url operation.

    Returns:
        The computed result for audio stream url.
    """
    stream_url = _text(info.get("url"))
    if stream_url:
        return stream_url

    formats = info.get("formats") or []
    audio_formats = [
        item for item in formats
        if isinstance(item, dict)
        and item.get("url")
        and item.get("acodec") not in (None, "none")
        and item.get("vcodec") in (None, "none")
    ]
    if not audio_formats:
        raise RuntimeError("No playable audio-only format found.")

    audio_formats.sort(key=lambda item: (item.get("abr") or 0, item.get("tbr") or 0), reverse=True)
    return str(audio_formats[0]["url"])


def _webpage_url(info: dict[str, Any]) -> str | None:
    """Webpage url.

    Coordinates webpage url logic for the surrounding Sonex flow.

    Args:
        info: Input value used by the webpage url operation.

    Returns:
        The computed result for webpage url.
    """
    url = _text(info.get("webpage_url") or info.get("original_url"))
    if url:
        return url
    video_id = _text(info.get("id"))
    if video_id:
        return f"https://www.youtube.com/watch?v={video_id}"
    return None


def _youtube_cache_id(info: dict[str, Any]) -> str:
    """Youtube cache id.

    Coordinates youtube cache id logic for the surrounding Sonex flow.

    Args:
        info: Input value used by the youtube cache id operation.

    Returns:
        The computed result for youtube cache id.
    """
    video_id = _text(info.get("youtube_id") or info.get("id"))
    if video_id:
        return f"youtube_{video_id}"
    url = _webpage_url(info) or _text(info.get("url")) or ""
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    return f"youtube_{digest}"


def _cached_audio_item(cache_id: str, *, cache_root: Path | None = None) -> dict[str, Any] | None:
    """Cached audio item.

    Coordinates cached audio item logic for the surrounding Sonex flow.

    Args:
        cache_id: Input value used by the cached audio item operation.
        cache_root: Input value used by the cached audio item operation.

    Returns:
        The computed result for cached audio item.
    """
    try:
        item = resolve_cached_song(cache_id, cache_root=cache_root)
    except Exception:
        return None
    audio_path = _text(item.get("audio_path"))
    if audio_path and Path(audio_path).expanduser().exists():
        item["stream_url"] = audio_path
        item["cached"] = True
        return item
    return None


def _normalize_youtube_info(query: str, info: dict[str, Any], stream_url: str | None = None) -> dict[str, Any]:
    """Normalize youtube info.

    Coordinates normalize youtube info logic for the surrounding Sonex flow.

    Args:
        query: Input value used by the normalize youtube info operation.
        info: Input value used by the normalize youtube info operation.
        stream_url: Input value used by the normalize youtube info operation.

    Returns:
        The computed result for normalize youtube info.
    """
    title = _text(info.get("track") or info.get("title") or info.get("fulltitle") or query) or query
    artist = (
        _non_placeholder_text(info.get("artist"))
        or _non_placeholder_text(info.get("artists"))
        or _non_placeholder_text(info.get("creator"))
        or _non_placeholder_text(info.get("creators"))
        or _non_placeholder_text(info.get("uploader"))
        or _non_placeholder_text(info.get("channel"))
        or "-"
    )
    album = _text(info.get("album") or info.get("playlist_title") or info.get("series"))
    cover_url = _text(info.get("official_album_cover_url") or info.get("provider_album_cover_url"))
    webpage_url = _webpage_url(info)
    youtube_id = _text(info.get("youtube_id") or info.get("id"))
    cache_id = _youtube_cache_id({**info, "youtube_id": youtube_id})
    variant = _variant_type(query, info)
    popularity = _popularity_score(info)
    relevance = _relevance_score(query, info)
    similarity = _similarity_score(query, info)
    quality = _quality_label(query, info, variant, similarity)
    return {
        "provider": "youtube",
        "id": youtube_id,
        "youtube_id": youtube_id,
        "cache_id": cache_id,
        "query": query,
        "name": title,
        "title": title,
        "artist": artist,
        "artists": [artist] if artist and artist != "-" else [],
        "album": album or "-",
        "duration_ms": _duration_ms(info.get("duration")),
        "album_cover_url": cover_url,
        "cover_url": cover_url,
        "url": webpage_url,
        "webpage_url": webpage_url,
        "stream_url": stream_url,
        "variant_type": variant,
        "popularity_score": popularity,
        "relevance_score": relevance,
        "similarity_score": similarity,
        "quality_label": quality,
        "rank_reason": _rank_reason(variant, popularity, relevance, similarity, quality),
        "raw_view_count": _count(info.get("view_count")),
        "raw_like_count": _count(info.get("like_count")),
        "is_playing": True,
    }


def _rank_youtube_candidates(query: str, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rank youtube candidates.

    Coordinates rank youtube candidates logic for the surrounding Sonex flow.

    Args:
        query: Input value used by the rank youtube candidates operation.
        candidates: Input value used by the rank youtube candidates operation.

    Returns:
        The computed result for rank youtube candidates.
    """
    live_requested = _contains_any(query, LIVE_TERMS)
    quality_priority = {
        "official_original": 4,
        "clean_audio_match": 3,
        "live": 2,
        "other": 1,
        "cover_like": -2,
        "noisy_media": -3,
    }
    if live_requested:
        quality_priority = {
            "live": 4,
            "official_original": 3,
            "clean_audio_match": 2,
            "other": 1,
            "cover_like": 0,
            "noisy_media": -1,
        }

    def score(pair: tuple[int, dict[str, Any]]) -> tuple[int, int, int, int, int]:
        """Score.

        Coordinates score logic for the surrounding Sonex flow.

        Args:
            pair: Input value used by the score operation.

        Returns:
            The computed result for score.
        """
        index, candidate = pair
        quality = str(candidate.get("quality_label") or "other")
        noisy_penalty = 25 if quality in {"noisy_media", "cover_like"} and not live_requested else 0
        similarity = max(0, int(candidate.get("similarity_score") or 0) - noisy_penalty)
        popularity = _popularity_tiebreaker(int(candidate.get("popularity_score") or 0))
        relevance = int(candidate.get("relevance_score") or 0)
        return (
            similarity,
            quality_priority.get(quality, 0),
            relevance,
            popularity,
            -index,
        )

    indexed = list(enumerate(candidates))
    indexed.sort(key=score, reverse=True)
    return [candidate for _, candidate in indexed]


def rank_online_audio_candidates(query: str, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rank online audio candidates.

    Coordinates rank online audio candidates logic for the surrounding Sonex flow.

    Args:
        query: Input value used by the rank online audio candidates operation.
        candidates: Input value used by the rank online audio candidates operation.

    Returns:
        The computed result for rank online audio candidates.
    """
    quality_priority = {
        "official_original": 4,
        "clean_audio_match": 3,
        "live": 2,
        "other": 1,
        "cover_like": -2,
        "noisy_media": -3,
    }
    provider_priority = {"jamendo": 3, "audius": 2, "youtube": 1}

    def score(pair: tuple[int, dict[str, Any]]) -> tuple[int, int, int, int]:
        """Score.

        Coordinates score logic for the surrounding Sonex flow.

        Args:
            pair: Input value used by the score operation.

        Returns:
            The computed result for score.
        """
        index, candidate = pair
        return (
            int(candidate.get("similarity_score") or 0),
            quality_priority.get(str(candidate.get("quality_label") or "other"), 0),
            provider_priority.get(str(candidate.get("provider") or ""), 0),
            -index,
        )

    indexed = list(enumerate(candidates))
    indexed.sort(key=score, reverse=True)
    return [candidate for _, candidate in indexed]


def _credible_online_audio_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Credible online audio candidates.

    Coordinates credible online audio candidates logic for the surrounding Sonex flow.

    Args:
        candidates: Input value used by the credible online audio candidates operation.

    Returns:
        The computed result for credible online audio candidates.
    """
    return [
        candidate for candidate in candidates
        if int(candidate.get("similarity_score") or 0) >= 45
    ]


def _provider_label(provider: str) -> str:
    """Provider label.

    Coordinates provider label logic for the surrounding Sonex flow.

    Args:
        provider: Input value used by the provider label operation.

    Returns:
        The computed result for provider label.
    """
    return {"jamendo": "Jamendo", "audius": "Audius", "youtube": "YouTube"}.get(provider, provider.title())


def _sanitize_provider_error(error: Any) -> str:
    """Sanitize provider error.

    Coordinates sanitize provider error logic for the surrounding Sonex flow.

    Args:
        error: Input value used by the sanitize provider error operation.

    Returns:
        The computed result for sanitize provider error.
    """
    message = sanitize_error_message(error)
    return re.sub(r"(?i)(secret)\s*[:=]\s*([^\s,;]+)", r"\1=[redacted]", message)


def _source_attempt(
    provider: str,
    *,
    status: str,
    candidate_count: int = 0,
    credible_count: int = 0,
    message: str | None = None,
) -> dict[str, Any]:
    """Source attempt.

    Coordinates source attempt logic for the surrounding Sonex flow.

    Args:
        provider: Input value used by the source attempt operation.
        status: Input value used by the source attempt operation.
        candidate_count: Input value used by the source attempt operation.
        credible_count: Input value used by the source attempt operation.
        message: Input value used by the source attempt operation.

    Returns:
        The computed result for source attempt.
    """
    label = _provider_label(provider)
    if not message:
        if status == "success":
            message = f"{label} returned {credible_count} credible match{'es' if credible_count != 1 else ''}."
        elif status == "missing_config":
            message = f"{label} is not configured."
        elif status == "error":
            message = f"{label} failed."
        else:
            message = f"{label} returned no credible matches."
    return {
        "provider": provider,
        "status": status,
        "candidate_count": max(0, int(candidate_count or 0)),
        "credible_count": max(0, int(credible_count or 0)),
        "message": _sanitize_provider_error(message),
    }


def _fallback_reason(source_attempts: list[dict[str, Any]]) -> str:
    """Fallback reason.

    Coordinates fallback reason logic for the surrounding Sonex flow.

    Args:
        source_attempts: Input value used by the fallback reason operation.

    Returns:
        The computed result for fallback reason.
    """
    messages = [str(item.get("message") or "").strip() for item in source_attempts if item.get("message")]
    return " ".join(messages) or "Configured open-audio providers returned no credible matches."


def _friendly_youtube_failure_message(message: str) -> str:
    """Friendly youtube failure message.

    Coordinates friendly youtube failure message logic for the surrounding Sonex flow.

    Args:
        message: Input value used by the friendly youtube failure message operation.

    Returns:
        The computed result for friendly youtube failure message.
    """
    if _is_age_verification_error(message):
        return AGE_RESTRICTED_MESSAGE
    if _is_unavailable_error(message):
        return UNAVAILABLE_MESSAGE
    return sanitize_error_message(message)


def _with_youtube_fallback_trace(candidate: dict[str, Any], source_attempts: list[dict[str, Any]]) -> dict[str, Any]:
    """With youtube fallback trace.

    Coordinates with youtube fallback trace logic for the surrounding Sonex flow.

    Args:
        candidate: Input value used by the with youtube fallback trace operation.
        source_attempts: Input value used by the with youtube fallback trace operation.

    Returns:
        The computed result for with youtube fallback trace.
    """
    traced = dict(candidate)
    reason = _fallback_reason(source_attempts)
    traced["fallback_provider"] = "youtube"
    traced["fallback_reason"] = reason
    traced["source_attempts"] = [dict(item) for item in source_attempts]
    return traced


def _format_youtube_fallback_failure(candidate: dict[str, Any], youtube_message: str) -> str:
    """Format youtube fallback failure.

    Coordinates format youtube fallback failure logic for the surrounding Sonex flow.

    Args:
        candidate: Input value used by the format youtube fallback failure operation.
        youtube_message: Input value used by the format youtube fallback failure operation.

    Returns:
        The computed result for format youtube fallback failure.
    """
    reason = str(candidate.get("fallback_reason") or _fallback_reason(candidate.get("source_attempts") or [])).strip()
    if reason:
        return f"{reason} Sonex fell back to YouTube. YouTube failed: {sanitize_error_message(youtube_message)}"
    return f"Sonex fell back to YouTube. YouTube failed: {sanitize_error_message(youtube_message)}"


def _json_get(url: str, *, headers: dict[str, str] | None = None, timeout: float = 10.0) -> dict[str, Any]:
    """Json get.

    Coordinates json get logic for the surrounding Sonex flow.

    Args:
        url: Input value used by the json get operation.
        headers: Input value used by the json get operation.
        timeout: Input value used by the json get operation.

    Returns:
        The computed result for json get.
    """
    request = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = response.read().decode("utf-8")
    data = json.loads(payload)
    if not isinstance(data, dict):
        raise RuntimeError("Invalid response returned.")
    return data


def search_jamendo_audio_candidates(
    query: str,
    *,
    client_id: str,
    limit: int = 5,
    playback_metadata: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Search jamendo audio candidates.

    Coordinates search jamendo audio candidates logic for the surrounding Sonex flow.

    Args:
        query: Input value used by the search jamendo audio candidates operation.
        client_id: Input value used by the search jamendo audio candidates operation.
        limit: Input value used by the search jamendo audio candidates operation.
        playback_metadata: Input value used by the search jamendo audio candidates operation.

    Returns:
        The computed result for search jamendo audio candidates.
    """
    params = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "format": "json",
            "limit": max(1, min(20, int(limit or 5))),
            "search": query,
            "audioformat": "mp32",
            "imagesize": 600,
            "include": "musicinfo",
        }
    )
    payload = _json_get(f"https://api.jamendo.com/v3.0/tracks/?{params}")
    results = payload.get("results") or []
    candidates = [
        candidate
        for item in results
        if isinstance(item, dict)
        for candidate in [normalize_jamendo_track(item, query=query, playback_metadata=playback_metadata)]
        if candidate is not None
    ]
    return rank_online_audio_candidates(query, candidates)[: max(1, min(10, int(limit or 5)))]


def _audius_stream_url(track_id: str) -> str:
    """Audius stream url.

    Coordinates audius stream url logic for the surrounding Sonex flow.

    Args:
        track_id: Input value used by the audius stream url operation.

    Returns:
        The computed result for audius stream url.
    """
    return f"https://discoveryprovider.audius.co/v1/tracks/{urllib.parse.quote(track_id)}/stream?app_name=Sonex"


def search_audius_audio_candidates(
    query: str,
    *,
    api_key: str,
    limit: int = 5,
    playback_metadata: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Search audius audio candidates.

    Coordinates search audius audio candidates logic for the surrounding Sonex flow.

    Args:
        query: Input value used by the search audius audio candidates operation.
        api_key: Input value used by the search audius audio candidates operation.
        limit: Input value used by the search audius audio candidates operation.
        playback_metadata: Input value used by the search audius audio candidates operation.

    Returns:
        The computed result for search audius audio candidates.
    """
    params = urllib.parse.urlencode(
        {
            "query": query,
            "limit": max(1, min(20, int(limit or 5))),
            "app_name": "Sonex",
        }
    )
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    payload = _json_get(f"https://discoveryprovider.audius.co/v1/tracks/search?{params}", headers=headers)
    data = payload.get("data") or []
    candidates = []
    for item in data:
        if not isinstance(item, dict):
            continue
        track_id = _text(item.get("id"))
        if not track_id:
            continue
        candidate = normalize_audius_track(
            item,
            query=query,
            stream_url=_audius_stream_url(track_id),
            playback_metadata=playback_metadata,
        )
        if candidate:
            candidates.append(candidate)
    return rank_online_audio_candidates(query, candidates)[: max(1, min(10, int(limit or 5)))]


def resolve_online_audio_candidates(
    query: str,
    limit: int = 5,
    *,
    cache_root: Path | None = None,
    playback_metadata: dict[str, Any] | None = None,
    config: OnlineAudioConfig | None = None,
) -> list[dict[str, Any]]:
    """Resolve online audio candidates.

    Coordinates resolve online audio candidates logic for the surrounding Sonex flow.

    Args:
        query: Input value used by the resolve online audio candidates operation.
        limit: Input value used by the resolve online audio candidates operation.
        cache_root: Input value used by the resolve online audio candidates operation.
        playback_metadata: Input value used by the resolve online audio candidates operation.
        config: Input value used by the resolve online audio candidates operation.

    Returns:
        The computed result for resolve online audio candidates.
    """
    resolved_config = config or online_audio_config()

    resolved_metadata = resolve_online_playback_metadata(query, playback_metadata)
    search_query = str(resolved_metadata.get("youtube_query") or query).strip() or query
    candidates: list[dict[str, Any]] = []
    source_attempts: list[dict[str, Any]] = []
    if resolved_config.jamendo_client_id:
        try:
            provider_candidates = search_jamendo_audio_candidates(
                search_query,
                client_id=resolved_config.jamendo_client_id,
                limit=limit,
                playback_metadata=resolved_metadata,
            )
            credible = _credible_online_audio_candidates(provider_candidates)
            source_attempts.append(
                _source_attempt(
                    "jamendo",
                    status="success" if credible else "no_credible_matches",
                    candidate_count=len(provider_candidates),
                    credible_count=len(credible),
                )
            )
            candidates.extend(provider_candidates)
        except Exception as exc:
            source_attempts.append(
                _source_attempt(
                    "jamendo",
                    status="error",
                    message=f"Jamendo failed: {sanitize_error_message(exc)}",
                )
            )
    else:
        source_attempts.append(_source_attempt("jamendo", status="missing_config"))
    if resolved_config.audius_api_key:
        try:
            provider_candidates = search_audius_audio_candidates(
                search_query,
                api_key=resolved_config.audius_api_key,
                limit=limit,
                playback_metadata=resolved_metadata,
            )
            credible = _credible_online_audio_candidates(provider_candidates)
            source_attempts.append(
                _source_attempt(
                    "audius",
                    status="success" if credible else "no_credible_matches",
                    candidate_count=len(provider_candidates),
                    credible_count=len(credible),
                )
            )
            candidates.extend(provider_candidates)
        except Exception as exc:
            source_attempts.append(
                _source_attempt(
                    "audius",
                    status="error",
                    message=f"Audius failed: {sanitize_error_message(exc)}",
                )
            )
    else:
        source_attempts.append(_source_attempt("audius", status="missing_config"))

    candidates = _credible_online_audio_candidates(candidates)
    if candidates:
        for candidate in candidates:
            candidate.setdefault("source_attempts", [dict(item) for item in source_attempts])
    if not candidates:
        try:
            candidates.extend(
                _with_youtube_fallback_trace(candidate, source_attempts)
                for candidate in search_youtube_songs(
                    search_query,
                    limit=limit,
                    cache_root=cache_root,
                    playback_metadata=resolved_metadata,
                )
            )
        except Exception as exc:
            raise RuntimeError(
                _format_youtube_fallback_failure(
                    {"source_attempts": source_attempts, "fallback_reason": _fallback_reason(source_attempts)},
                    _friendly_youtube_failure_message(str(exc)),
                )
            ) from exc
    if not candidates:
        raise RuntimeError("No valid online audio matches found.")
    ranked = rank_online_audio_candidates(search_query, candidates)
    bounded_limit = max(1, min(10, int(limit or 5)))
    return ranked[:bounded_limit]


def search_online_audio_candidates(
    query: str,
    limit: int = 5,
    *,
    cache_root: Path | None = None,
    playback_metadata: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Search online audio candidates.

    Coordinates search online audio candidates logic for the surrounding Sonex flow.

    Args:
        query: Input value used by the search online audio candidates operation.
        limit: Input value used by the search online audio candidates operation.
        cache_root: Input value used by the search online audio candidates operation.
        playback_metadata: Input value used by the search online audio candidates operation.

    Returns:
        The computed result for search online audio candidates.
    """
    return resolve_online_audio_candidates(
        query,
        limit=limit,
        cache_root=cache_root,
        playback_metadata=playback_metadata,
    )


def search_youtube_songs(
    query: str,
    limit: int = 5,
    *,
    cache_root: Path | None = None,
    playback_metadata: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Search youtube songs.

    Coordinates search youtube songs logic for the surrounding Sonex flow.

    Args:
        query: Input value used by the search youtube songs operation.
        limit: Input value used by the search youtube songs operation.
        cache_root: Input value used by the search youtube songs operation.
        playback_metadata: Input value used by the search youtube songs operation.

    Returns:
        The computed result for search youtube songs.
    """
    playback_metadata = resolve_online_playback_metadata(query, playback_metadata)
    youtube_query = str(playback_metadata.get("youtube_query") or query).strip() or query
    bounded_limit = max(1, min(10, int(limit or 5)))
    search_limit = min(50, max(bounded_limit, bounded_limit * 8))
    options = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
    }

    with yt_dlp.YoutubeDL(options) as ydl:
        payload = ydl.extract_info(f"ytsearch{search_limit}:{youtube_query}", download=False)

    if not isinstance(payload, dict):
        raise RuntimeError("Invalid response returned.")

    entries = payload.get("entries") or []
    candidates: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if not _should_keep_candidate(youtube_query, entry):
            continue
        candidate = _merge_canonical_metadata(
            _normalize_youtube_info(youtube_query, entry, None),
            playback_metadata,
        )
        candidate["query"] = youtube_query
        candidate["original_query"] = playback_metadata.get("original_query") or query
        candidate["youtube_query"] = youtube_query
        cached = _cached_audio_item(str(candidate["cache_id"]), cache_root=cache_root)
        candidate["cached"] = cached is not None
        if cached:
            candidate["audio_path"] = cached.get("audio_path")
            candidate["audio_ext"] = cached.get("audio_ext")
        candidates.append(candidate)
    if not candidates:
        raise RuntimeError("No valid matches found.")
    return _rank_youtube_candidates(youtube_query, candidates)[:bounded_limit]


def _downloaded_filepath(info: dict[str, Any], fallback: Path) -> Path:
    """Downloaded filepath.

    Coordinates downloaded filepath logic for the surrounding Sonex flow.

    Args:
        info: Input value used by the downloaded filepath operation.
        fallback: Input value used by the downloaded filepath operation.

    Returns:
        The computed result for downloaded filepath.
    """
    downloads = info.get("requested_downloads")
    if isinstance(downloads, list):
        for item in downloads:
            if isinstance(item, dict):
                path = _text(item.get("filepath") or item.get("_filename"))
                if path:
                    return Path(path).expanduser()
    ext = _text(info.get("ext")) or fallback.suffix.lstrip(".") or "webm"
    return fallback.with_suffix(f".{ext}")


def download_youtube_candidate(candidate: dict[str, Any], *, cache_root: Path | None = None) -> dict[str, Any]:
    """Download youtube candidate.

    Coordinates download youtube candidate logic for the surrounding Sonex flow.

    Args:
        candidate: Input value used by the download youtube candidate operation.
        cache_root: Input value used by the download youtube candidate operation.

    Returns:
        The computed result for download youtube candidate.
    """
    cache_id = _text(candidate.get("cache_id")) or _youtube_cache_id(candidate)
    cached = _cached_audio_item(cache_id, cache_root=cache_root)
    if cached:
        return cached

    webpage_url = _text(candidate.get("webpage_url") or candidate.get("url"))
    if not webpage_url:
        raise RuntimeError("Unable to resolve a playable YouTube URL.")

    audio_dir = _audio_cache_dir(cache_root)
    audio_dir.mkdir(parents=True, exist_ok=True)
    outtmpl = str(audio_dir / f"{cache_id}.%(ext)s")
    options = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "format": "bestaudio/best",
        "outtmpl": outtmpl,
    }
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(webpage_url, download=True)
    if not isinstance(info, dict):
        raise RuntimeError("Invalid response returned.")
    if "formats" in info:
        _audio_stream_url(info)

    canonical_metadata = _canonical_metadata(candidate)
    merged = {**candidate, **info}
    for cover_key in ("official_album_cover_url", "provider_album_cover_url"):
        if candidate.get(cover_key):
            merged[cover_key] = candidate[cover_key]
    merged["webpage_url"] = _webpage_url(merged) or webpage_url
    audio_path = _downloaded_filepath(merged, audio_dir / f"{cache_id}.webm")
    audio_ext = audio_path.suffix.lstrip(".") or _text(merged.get("ext")) or "webm"
    item = {
        **_merge_canonical_metadata(
            _normalize_youtube_info(str(candidate.get("query") or merged.get("query") or merged.get("title") or ""), merged, str(audio_path)),
            canonical_metadata,
        ),
        "cache_id": cache_id,
        "youtube_id": _text(merged.get("youtube_id") or merged.get("id")),
        "audio_path": str(audio_path),
        "audio_ext": audio_ext,
        "stream_url": str(audio_path),
        "cached": True,
    }
    item["query"] = str(candidate.get("query") or item.get("query") or "")
    item["original_query"] = candidate.get("original_query") or item.get("original_query") or item["query"]
    item["youtube_query"] = candidate.get("youtube_query") or item.get("youtube_query") or item["query"]
    cover = None if item.get("cover_source_type") == "cover_art_archive" else cover_sources.resolve_online_cover(item)
    if cover:
        item["album_cover_url"] = cover["cover_source"]
        item["cover_url"] = cover.get("cover_url") or cover["cover_source"]
        item["cover_source"] = cover["cover_source"]
        item["cover_source_type"] = cover["source_type"]
    upsert_cached_song(item, cache_root=cache_root)
    return item


def _extension_from_url(url: str, default: str = "mp3") -> str:
    """Extension from url.

    Coordinates extension from url logic for the surrounding Sonex flow.

    Args:
        url: Input value used by the extension from url operation.
        default: Input value used by the extension from url operation.

    Returns:
        The computed result for extension from url.
    """
    path = urllib.parse.urlparse(url).path
    suffix = Path(path).suffix.lstrip(".").lower()
    if suffix and len(suffix) <= 5:
        return suffix
    return default


def download_open_audio_candidate(candidate: dict[str, Any], *, cache_root: Path | None = None) -> dict[str, Any]:
    """Download open audio candidate.

    Coordinates download open audio candidate logic for the surrounding Sonex flow.

    Args:
        candidate: Input value used by the download open audio candidate operation.
        cache_root: Input value used by the download open audio candidate operation.

    Returns:
        The computed result for download open audio candidate.
    """
    provider = str(candidate.get("provider") or "online")
    if provider == "youtube":
        return download_youtube_candidate(candidate, cache_root=cache_root)
    cache_id = _text(candidate.get("cache_id")) or _provider_cache_id(provider, _text(candidate.get("id")), _text(candidate.get("download_url")))
    cached = _cached_audio_item(cache_id, cache_root=cache_root)
    if cached:
        return cached
    download_url = _text(candidate.get("download_url") or candidate.get("source_url") or candidate.get("stream_url"))
    if not download_url:
        raise RuntimeError("Unable to resolve a playable online audio URL.")

    audio_dir = _audio_cache_dir(cache_root)
    audio_dir.mkdir(parents=True, exist_ok=True)
    audio_ext = _extension_from_url(download_url)
    audio_path = audio_dir / f"{cache_id}.{audio_ext}"
    request = urllib.request.Request(download_url, headers={"User-Agent": "Sonex/1.0"})
    with urllib.request.urlopen(request, timeout=30) as response, audio_path.open("wb") as output:
        while True:
            chunk = response.read(1024 * 256)
            if not chunk:
                break
            output.write(chunk)

    item = {
        **candidate,
        "cache_id": cache_id,
        "audio_path": str(audio_path),
        "audio_ext": audio_ext,
        "stream_url": str(audio_path),
        "cached": True,
    }
    upsert_cached_song(item, cache_root=cache_root)
    return item


def play_online_audio_candidate(
    candidate: dict[str, Any],
    *,
    player: str = "auto",
    cache_root: Path | None = None,
) -> dict[str, Any]:
    """Play online audio candidate.

    Coordinates play online audio candidate logic for the surrounding Sonex flow.

    Args:
        candidate: Input value used by the play online audio candidate operation.
        player: Input value used by the play online audio candidate operation.
        cache_root: Input value used by the play online audio candidate operation.

    Returns:
        The computed result for play online audio candidate.
    """
    provider = str(candidate.get("provider") or "online")
    if provider == "youtube":
        return play_youtube_candidate(candidate, player=player, cache_root=cache_root)
    try:
        data = download_open_audio_candidate(candidate, cache_root=cache_root)
    except Exception as exc:
        return ToolResult.fail(
            tool="play_youtube_song",
            message=sanitize_message(str(exc)),
            error_code="ONLINE_AUDIO_RESOLVE_FAILED",
            data={"query": candidate.get("query"), "player": player, "method": "online_play", "provider": provider},
        ).to_dict()

    if player != "auto" and not check_player(player):
        return ToolResult.error(
            tool="play_youtube_song",
            message=f"Player '{player}' is not ready.",
            error_code="PLAYER_MISSED",
            data={**data, "player": player, "method": "online_play"},
        )

    audio_path = str(data["audio_path"])
    if player == "auto":
        cmd = ["sonex-local-playback", "auto", audio_path]
    elif player == "mpv":
        cmd = ["mpv", "--no-video", audio_path]
    elif player == "cvlc":
        cmd = ["cvlc", "--no-video", audio_path]
    else:
        cmd = [player, "--play-and-exit", audio_path]
    data = {**data, "player": player, "method": "online_play", "source": provider}
    success_message = f"Playing '{data.get('query') or data.get('name')}' online started."

    if not is_player_allowed(player):
        return build_player_confirm_result(
            tool="play_youtube_song",
            player=player,
            cmd=cmd,
            success_message=success_message,
            data={
                **data,
                "playback_source_url": audio_path,
                "playback_source": provider,
                "playback_metadata": data,
            },
        )

    return start_local_playback(
        tool="play_youtube_song",
        source_url=audio_path,
        source=provider,
        metadata=data,
        player=player,
        success_message=success_message,
    )


def sanitize_message(message: str) -> str:
    """Sanitize message.

    Coordinates sanitize message logic for the surrounding Sonex flow.

    Args:
        message: Input value used by the sanitize message operation.

    Returns:
        The computed result for sanitize message.
    """
    return message.strip() or "Online audio resolve failed."


def play_youtube_candidate(
    candidate: dict[str, Any],
    *,
    player: str = "auto",
    cache_root: Path | None = None,
) -> dict[str, Any]:
    """Play youtube candidate.

    Coordinates play youtube candidate logic for the surrounding Sonex flow.

    Args:
        candidate: Input value used by the play youtube candidate operation.
        player: Input value used by the play youtube candidate operation.
        cache_root: Input value used by the play youtube candidate operation.

    Returns:
        The computed result for play youtube candidate.
    """
    is_youtube_fallback = candidate.get("fallback_provider") == "youtube"
    try:
        data = download_youtube_candidate(candidate, cache_root=cache_root)
    except Exception as exc:
        message = str(exc)
        if _is_age_verification_error(message):
            message = AGE_RESTRICTED_MESSAGE
            error_code = "YOUTUBE_AGE_RESTRICTED"
        elif _is_unavailable_error(message):
            message = UNAVAILABLE_MESSAGE
            error_code = "YOUTUBE_UNAVAILABLE"
        else:
            error_code = "NO_PLAYABLE_AUDIO" if "No playable audio" in message else "YOUTUBE_RESOLVE_FAILED"
        display_message = _format_youtube_fallback_failure(candidate, message) if is_youtube_fallback else message
        return ToolResult.fail(
            tool="play_online_audio" if is_youtube_fallback else "play_youtube_song",
            message=display_message,
            error_code=error_code,
            data={
                "query": candidate.get("query"),
                "player": player,
                "method": "online_play",
                "provider": "youtube",
                "fallback_provider": candidate.get("fallback_provider"),
                "fallback_reason": candidate.get("fallback_reason"),
                "source_attempts": candidate.get("source_attempts") or [],
            },
        ).to_dict()

    if player != "auto" and not check_player(player):
        return ToolResult.error(
            tool="play_youtube_song",
            message=f"Player '{player}' is not ready.",
            error_code="PLAYER_MISSED",
            data={**data, "player": player, "method": "online_play"},
        )

    audio_path = str(data["audio_path"])
    if player == "auto":
        cmd = ["sonex-local-playback", "auto", audio_path]
    elif player == "mpv":
        cmd = ["mpv", "--no-video", audio_path]
    elif player == "cvlc":
        cmd = ["cvlc", "--no-video", audio_path]
    else:
        cmd = [player, "--play-and-exit", audio_path]
    data = {**data, "player": player, "method": "online_play", "source": "youtube"}
    success_message = f"Playing '{data.get('query') or data.get('name')}' online started."

    if not is_player_allowed(player):
        return build_player_confirm_result(
            tool="play_youtube_song",
            player=player,
            cmd=cmd,
            success_message=success_message,
            data={
                **data,
                "playback_source_url": audio_path,
                "playback_source": "youtube",
                "playback_metadata": data,
            },
        )

    return start_local_playback(
        tool="play_youtube_song",
        source_url=audio_path,
        source="youtube",
        metadata=data,
        player=player,
        success_message=success_message,
    )


# 在youtube上搜索歌曲并解析音频流
def resolve_youtube_song(query: str) -> dict[str, Any]:
    """Resolve youtube song.

    Coordinates resolve youtube song logic for the surrounding Sonex flow.

    Args:
        query: Input value used by the resolve youtube song operation.

    Returns:
        The computed result for resolve youtube song.
    """
    options = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
    }

    with yt_dlp.YoutubeDL(options) as ydl:
        payload = ydl.extract_info(f"ytsearch1:{query}", download=False)

    if not isinstance(payload, dict):
        raise RuntimeError("Invalid response returned.")

    entries = payload.get("entries") or []
    if not entries or not isinstance(entries[0], dict):
        raise RuntimeError("No valid matches found.")
    first_entry = entries[0]

    video_id = first_entry.get("id")
    webpage_url = first_entry.get("webpage_url")

    if not webpage_url and video_id:
        webpage_url = f"https://www.youtube.com/watch?v={video_id}"

    if not webpage_url:
        raise RuntimeError("Unable to resolve a playable YouTube URL.")

    stream_opts = {
        "quiet": True,  # 减少控制台输出
        "no_warnings": True,  # 不打印warning日志信息
        "noplaylist": True,  # 搜索结果关联playlist取单条视频
        "format": "bestaudio/best",  # 优先最佳音频流
        "skip_download": True,  # 只解析不下载
    }

    with yt_dlp.YoutubeDL(stream_opts) as ydl:
        info = ydl.extract_info(webpage_url, download=False)
    if not isinstance(info, dict):
        raise RuntimeError("Invalid response returned.")

    merged_info = {**first_entry, **info}
    merged_info["webpage_url"] = _webpage_url(merged_info) or webpage_url
    stream_url = _audio_stream_url(merged_info)
    return _normalize_youtube_info(query, merged_info, stream_url)


def search_and_resolve_song(query: str) -> str:
    """Search and resolve song.

    Coordinates search and resolve song logic for the surrounding Sonex flow.

    Args:
        query: Input value used by the search and resolve song operation.

    Returns:
        The computed result for search and resolve song.
    """
    candidate = search_youtube_songs(query, limit=1)[0]
    return str(download_youtube_candidate(candidate)["stream_url"])


def play_youtube_song(
    query: str,
    player: str = "auto",
    cache_root: Path | None = None,
    playback_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Play youtube song.

    Coordinates play youtube song logic for the surrounding Sonex flow.

    Args:
        query: Input value used by the play youtube song operation.
        player: Input value used by the play youtube song operation.
        cache_root: Input value used by the play youtube song operation.
        playback_metadata: Input value used by the play youtube song operation.

    Returns:
        The computed result for play youtube song.
    """
    if online_audio_configured():
        try:
            candidate = resolve_online_audio_candidates(
                query,
                limit=1,
                cache_root=cache_root,
                playback_metadata=playback_metadata,
            )[0]
        except Exception as exc:
            return ToolResult.fail(
                tool="play_online_audio",
                message=sanitize_error_message(exc),
                error_code="ONLINE_AUDIO_RESOLVE_FAILED",
                data={"query": query, "player": player, "method": "online_play", "provider": "online_audio"},
            ).to_dict()
        return play_online_audio_candidate(candidate, player=player, cache_root=cache_root)

    try:
        candidate = search_youtube_songs(
            query,
            limit=1,
            cache_root=cache_root,
            playback_metadata=playback_metadata,
        )[0]
    except Exception as exc:
        message = str(exc)
        error_code = "NO_PLAYABLE_AUDIO" if "No playable audio" in message else "YOUTUBE_RESOLVE_FAILED"
        return ToolResult.fail(
            tool="play_youtube_song",
            message=message,
            error_code=error_code,
            data={"query": query, "player": player, "method": "online_play", "provider": "youtube"},
        ).to_dict()
    return play_youtube_candidate(candidate, player=player, cache_root=cache_root)

registry.register(
    name="play_youtube_song",
    type="player",
    description="Play a resolved audio extract from youtube via mpv music player.",
    parameters=Params(
        type="object",
        properties={
            "query": {"type": "string", "description": "The song name or related key words."},
            "playback_metadata": {
                "type": "object",
                "description": "Optional confirmed provider metadata to use for YouTube search and playback metadata.",
            },
        },
        required=["query"],
    ),
    fn=play_youtube_song,
    enable=True,
    read_only=False,
    required_confirm=False,
)
