"""Online play support for tool implementations used by the planner and playback flows.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import time
import urllib.parse
import urllib.request
import uuid
from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from threading import Condition, Lock
from typing import Any, Callable

import yt_dlp

from src.network.proxy import urlopen as proxy_urlopen
from src.auth.store import get_provider_auth, load_auth_store
from src.llm.transport import sanitize_error_message
from src.log import sonex_home
from src.tools import cover_sources, spotify_play
from src.tools.local_play import check_player
from src.tools.player_permission import (
    confirm_or_start_playback,
    is_player_allowed,
)
from src.tools.playback_controller import resolve_local_playback_backend, start_local_playback
from src.tools.registry import registry, Params
from src.tools.result import ToolResult
from src.tools.song_cache import resolve_cached_song, upsert_cached_song
from src.tools.online_provider_health import (
    activate_provider_cooldown,
    provider_cooldown,
)
from src.tools.youtube_runtime import (
    YoutubeQueueBusy,
    YoutubeRuntimeUnavailable,
    active_manifest,
    mark_runtime_failure,
    run_managed_ytdlp_request,
    youtube_enabled,
)
from src.tools.youtube_runtime_state import managed_runtime_failure_code, provider_failure_category
from src.tools.audio_diagnostics import record_audio_event
from src.tools.online_search_cache import (
    get_search_cache,
    make_search_cache_key,
    put_search_cache,
)
from src.tools.yt_dlp_runner import YtDlpError, YtDlpTimeoutError
from src.tools.music_matching import (
    AliasResolver,
    MatchDecision,
    audio_result_from_candidate,
    canonical_track_from_metadata,
    normalize_music_text,
    score_audio_match,
    simplified_traditional_variants,
)
from src.tools.online_identity_state import (
    COVER_TERMS,
    FEATURED_ARTIST_RE,
    FEATURED_TITLE_RE,
    IGNORABLE_TITLE_SUFFIX_RE,
    LIVE_TERMS,
    LOW_RELEVANCE_TERMS,
    NOISY_MEDIA_TERMS,
    OFFICIAL_TERMS,
    QUERY_FILLER_TERMS,
    contains_any as _contains_any,
    has_cjk as _has_cjk,
    identity_artist as _identity_artist,
    identity_artist_text as _identity_artist_text,
    identity_text as _identity_text,
    identity_title as _identity_title,
    identity_title_text as _identity_title_text,
    mostly_latin as _mostly_latin,
    normalized_rank_text as _normalized_rank_text,
    query_terms as _query_terms,
    words as _words,
)

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
    "Open /extension to configure a music source first."
)
ONLINE_AUDIO_SEARCH_TIMEOUT_SECONDS = 12.0
OPEN_AUDIO_SEARCH_TIMEOUT_SECONDS = 4.0
YOUTUBE_FALLBACK_SEARCH_TIMEOUT_SECONDS = 8.0
MAX_AUTOMATIC_PLAY_ATTEMPTS = 2
AUDIUS_API_BASE_URL = "https://api.audius.co/v1"
AUDIUS_REQUEST_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "Sonex/1.0",
}
YOUTUBE_SEARCH_COOLDOWN_SECONDS = 5 * 60.0
ONLINE_COVER_LOOKUP_TIMEOUT_SECONDS = 0.75
YOUTUBE_SEARCH_OPERATION_TIMEOUT_SECONDS = 8.0
YOUTUBE_RESOLVE_OPERATION_TIMEOUT_SECONDS = 12.0
YOUTUBE_DOWNLOAD_OPERATION_TIMEOUT_SECONDS = 60.0
_youtube_search_cooldown_until = 0.0
_youtube_search_cooldown_lock = Lock()
YOUTUBE_MIN_SEARCH_INTERVAL_SECONDS = 3.0
_youtube_search_gate = Condition(Lock())
_youtube_search_active = False
_youtube_last_search_started = 0.0
_youtube_search_inflight: dict[str, Future[list[dict[str, Any]]]] = {}


def _extract_ytdlp_info(
    *,
    operation: str,
    target: str,
    options: dict[str, Any],
    timeout_seconds: float,
) -> dict[str, Any]:
    return run_managed_ytdlp_request(
        operation=operation,
        target=target,
        options=options,
        timeout_seconds=timeout_seconds,
    )


def _record_audio_event_safe(
    *,
    trace_id: str,
    provider: str,
    phase: str,
    status: str,
    cache_root: Path | None = None,
    elapsed_ms: int | None = None,
    **metadata: Any,
) -> None:
    try:
        record_audio_event(
            trace_id=trace_id,
            provider=provider,
            phase=phase,
            status=status,
            cache_root=cache_root,
            elapsed_ms=elapsed_ms,
            **metadata,
        )
    except (OSError, sqlite3.Error):
        pass


def _youtube_search_cache_key(
    query: str,
    playback_metadata: dict[str, Any],
    query_variants: list[tuple[str, str]],
) -> str:
    artist = playback_metadata.get("artist")
    title = playback_metadata.get("name") or playback_metadata.get("title")
    album = playback_metadata.get("album")
    if not artist and not title:
        title = query
    variant_intent = "|".join(str(variant) for _, variant in query_variants)
    return make_search_cache_key(
        provider="youtube",
        artist=artist,
        title=title,
        album=album,
        variant_intent=variant_intent,
    )


def _run_gated_youtube_search(
    *,
    target: str,
    options: dict[str, Any],
    timeout_seconds: float = YOUTUBE_SEARCH_OPERATION_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Serialize real cold searches and enforce the inter-search interval."""
    global _youtube_search_active, _youtube_last_search_started
    with _youtube_search_gate:
        while _youtube_search_active:
            _youtube_search_gate.wait()
        wait_seconds = (
            _youtube_last_search_started
            + YOUTUBE_MIN_SEARCH_INTERVAL_SECONDS
            - time.monotonic()
        )
        if wait_seconds > 0:
            _youtube_search_gate.wait(timeout=wait_seconds)
        _youtube_search_active = True
        _youtube_last_search_started = time.monotonic()
    try:
        return _extract_ytdlp_info(
            operation="search",
            target=target,
            options=options,
            timeout_seconds=timeout_seconds,
        )
    finally:
        with _youtube_search_gate:
            _youtube_search_active = False
            _youtube_search_gate.notify_all()


def _coalesced_youtube_search(
    cache_key: str,
    search: Callable[[], list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Share one in-flight cold search among concurrent callers."""
    owner = False
    with _youtube_search_gate:
        future = _youtube_search_inflight.get(cache_key)
        if future is None:
            future = Future()
            _youtube_search_inflight[cache_key] = future
            owner = True
    if not owner:
        return future.result()
    try:
        result = search()
        future.set_result(result)
        return result
    except Exception as exc:
        future.set_exception(exc)
        raise
    finally:
        with _youtube_search_gate:
            _youtube_search_inflight.pop(cache_key, None)


class OnlineAudioSetupRequired(RuntimeError):
    pass


class AudioIdentityMismatch(RuntimeError):
    def __init__(self, provider: str, rejected_count: int) -> None:
        self.provider = provider
        self.rejected_count = max(1, int(rejected_count or 1))
        super().__init__(
            f"{_provider_label(provider)} rejected {self.rejected_count} "
            f"identity mismatch{'es' if self.rejected_count != 1 else ''}."
        )


class OnlineAudioResolutionError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        source_attempts: list[dict[str, Any]],
        search_trace: dict[str, Any],
    ) -> None:
        self.source_attempts = [dict(item) for item in source_attempts]
        self.search_trace = dict(search_trace)
        super().__init__(message)


class IdentityCandidateList(list[dict[str, Any]]):
    def __init__(self, values: list[dict[str, Any]], *, rejected_count: int = 0) -> None:
        super().__init__(values)
        self.rejected_count = max(0, int(rejected_count or 0))


@dataclass(frozen=True, slots=True)
class OnlineAudioConfig:
    jamendo_client_id: str | None = None
    audius_api_key: str | None = None


@dataclass(frozen=True, slots=True)
class IdentityContext:
    provider_identity: dict[str, Any]
    original_query: str
    provider_query: str
    language_conflict: bool


def _song_cache_root(cache_root: Path | None = None) -> Path:
    return cache_root or sonex_home() / "cache" / "songs"


def _audio_cache_dir(cache_root: Path | None = None) -> Path:
    return _song_cache_root(cache_root) / "audio"


def online_audio_config() -> OnlineAudioConfig:
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
    import os

    return os.environ.get(name)


def online_audio_configured(config: OnlineAudioConfig | None = None) -> bool:
    resolved = config or online_audio_config()
    return bool(resolved.jamendo_client_id or resolved.audius_api_key)


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _joined_text(value: Any) -> str | None:
    if isinstance(value, list):
        parts = [_text(item) for item in value]
        return ", ".join(part for part in parts if part) or None
    return _text(value)


def _non_placeholder_text(value: Any) -> str | None:
    text = _joined_text(value)
    if text in {None, "-"}:
        return None
    return text


def _spotify_tracks_from_result(result: dict[str, Any]) -> list[dict[str, Any]]:
    if str(result.get("status") or "").lower() != "success":
        return []
    data = result.get("data")
    tracks = data.get("tracks") if isinstance(data, dict) else None
    if not isinstance(tracks, list) or not tracks:
        return []
    return [track for track in tracks if isinstance(track, dict)]


def _spotify_track_metadata(query: str, track: dict[str, Any]) -> dict[str, Any] | None:
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
        "is_playable": track.get("is_playable"),
    }


def search_spotify_track_candidates(
    query: str,
    limit: int = 5,
    *,
    query_variants: tuple[str, ...] | list[str] | None = None,
) -> list[dict[str, Any]]:
    clean_query = query.strip()
    if not clean_query:
        return []
    bounded_limit = max(1, min(10, int(limit or 5)))
    search_queries: list[str] = []
    for candidate in query_variants or (clean_query,):
        clean_candidate = str(candidate or "").strip()
        if clean_candidate and clean_candidate not in search_queries:
            search_queries.append(clean_candidate)
        if len(search_queries) >= 2:
            break
    candidates: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for search_query in search_queries:
        try:
            result = spotify_play.spotify_search(query=search_query, limit=bounded_limit, types="track")
        except Exception:
            break
        if not isinstance(result, dict):
            break
        if result.get("status") != "success":
            break
        for track in _spotify_tracks_from_result(result):
            if isinstance(track, dict) and track.get("is_playable") is False:
                continue
            metadata = _spotify_track_metadata(clean_query, track)
            if not metadata:
                continue
            dedupe_key = str(metadata.get("uri") or metadata.get("spotify_track_id") or "").strip()
            if not dedupe_key:
                dedupe_key = f"{metadata.get('artist', '')}\0{metadata.get('name', '')}"
            if dedupe_key in seen_keys:
                continue
            seen_keys.add(dedupe_key)
            candidates.append(metadata)
            if len(candidates) >= bounded_limit:
                break
        if candidates:
            break
    return candidates


def _query_fallback_metadata(query: str) -> dict[str, Any]:
    clean_query = query.strip()
    return {
        "metadata_source": "query_fallback",
        "original_query": clean_query,
        "youtube_query": clean_query,
    }


def _resolved_playback_metadata(query: str, playback_metadata: dict[str, Any] | None = None) -> dict[str, Any]:
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
            cover = cover_sources.resolve_online_cover(
                metadata,
                timeout_seconds=ONLINE_COVER_LOOKUP_TIMEOUT_SECONDS,
            )
            if cover and cover.get("source_type") == "cover_art_archive":
                metadata["album_cover_url"] = cover["cover_source"]
                metadata["cover_url"] = cover.get("cover_url") or cover["cover_source"]
                metadata["cover_source"] = cover["cover_source"]
                metadata["cover_source_type"] = cover["source_type"]
    elif not metadata.get("album_cover_url") and not metadata.get("cover_url"):
        cover = cover_sources.resolve_online_cover(
            metadata,
            timeout_seconds=ONLINE_COVER_LOOKUP_TIMEOUT_SECONDS,
        )
        if cover:
            metadata["album_cover_url"] = cover["cover_source"]
            metadata["cover_url"] = cover.get("cover_url") or cover["cover_source"]
            metadata["cover_source"] = cover["cover_source"]
            metadata["cover_source_type"] = cover["source_type"]
    return metadata


def resolve_online_playback_metadata(query: str, playback_metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    return _resolved_playback_metadata(query, playback_metadata)


def _canonical_metadata(item: dict[str, Any]) -> dict[str, Any]:
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
        "isrc",
        "preview_url",
        "release_date",
        "release_year",
        "album_id",
        "artist_id",
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


def _track_identity(item: dict[str, Any]) -> dict[str, str]:
    return {
        "title": _non_placeholder_text(item.get("name") or item.get("title") or item.get("track")) or "",
        "artist": _identity_artist(item),
        "album": _non_placeholder_text(item.get("album")) or "",
    }


def _complete_identity(identity: dict[str, Any] | None) -> bool:
    return bool(
        isinstance(identity, dict)
        and _identity_title_text(identity)
        and _identity_artist_text(identity.get("artist"))
    )


def _identity_matches(target: dict[str, Any] | None, source: dict[str, Any] | None) -> bool:
    if not _complete_identity(target):
        return True
    if not _complete_identity(source):
        return False
    resolver = AliasResolver.load()
    return (
        resolver.matches("track", _identity_title_text(target), _identity_title_text(source))
        and resolver.matches(
            "artist",
            _identity_artist_text(target.get("artist")),
            _identity_artist_text(source.get("artist")),
        )
    )


def _identity_context(query: str, playback_metadata: dict[str, Any] | None = None) -> IdentityContext:
    metadata = _canonical_metadata(playback_metadata or {})
    provider_identity = _track_identity(metadata)
    explicit_target = playback_metadata.get("target_identity") if isinstance(playback_metadata, dict) else None
    if not _complete_identity(provider_identity) and isinstance(explicit_target, dict):
        provider_identity = dict(explicit_target)
    provider_query = str(metadata.get("youtube_query") or "").strip()
    if not provider_query:
        artist = _non_placeholder_text(provider_identity.get("artist"))
        title = _non_placeholder_text(provider_identity.get("title"))
        provider_query = f"{artist or ''} {title or ''}".strip()
    provider_query = provider_query or query.strip()
    original_query = str(metadata.get("original_query") or query).strip()
    provider_text = " ".join(
        str(provider_identity.get(key) or "")
        for key in ("title", "artist", "album")
    ) or provider_query
    language_conflict = bool(
        original_query
        and provider_text
        and (
            (_mostly_latin(provider_text) and _has_cjk(original_query))
            or (_has_cjk(provider_text) and _mostly_latin(original_query))
        )
    )
    return IdentityContext(
        provider_identity=provider_identity,
        original_query=original_query,
        provider_query=provider_query,
        language_conflict=language_conflict,
    )


def _search_query_variant(query: str, context: IdentityContext) -> str:
    if context.language_conflict and query.strip() == context.original_query:
        return "original_query"
    return "provider_metadata"


def _query_identity_accepts(context: IdentityContext, source: dict[str, Any], info: dict[str, Any]) -> tuple[bool, int]:
    if not context.language_conflict or not context.original_query:
        return False, 0
    score = _similarity_score(context.original_query, info)
    terms = _query_terms(context.original_query)
    relevance = _relevance_score(context.original_query, info)
    if score < 70 or relevance <= 0 or (terms and relevance < len(terms)):
        return False, score
    variant = _variant_type(context.original_query, info)
    quality = _quality_label(context.original_query, info, variant, score)
    if variant == "live" and not _contains_any(context.original_query, LIVE_TERMS):
        return False, score
    if quality in {"cover_like", "noisy_media"} and not _contains_any(context.original_query, LOW_RELEVANCE_TERMS + NOISY_MEDIA_TERMS):
        return False, score
    if not _complete_identity(source):
        return False, score
    return True, score


def _evaluate_identity(
    *,
    query: str,
    playback_metadata: dict[str, Any] | None,
    source_identity: dict[str, Any],
    info: dict[str, Any],
) -> dict[str, Any]:
    context = _identity_context(query, playback_metadata)
    provider_match = _identity_matches(context.provider_identity, source_identity)
    query_match, query_score = _query_identity_accepts(context, source_identity, info)
    identity_match = provider_match or query_match
    if provider_match:
        match_source = "provider_metadata"
    elif query_match:
        match_source = "original_query"
    else:
        match_source = None
    return {
        "target_identity": context.provider_identity,
        "identity_match": identity_match,
        "identity_match_source": match_source,
        "provider_identity_match": provider_match,
        "query_identity_match": query_match,
        "query_identity_score": query_score,
        "search_query_variant": _search_query_variant(query, context),
    }


def _apply_match_score(candidate: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    canonical = canonical_track_from_metadata(metadata)
    if not canonical.title or not canonical.artist:
        return candidate

    source_identity = candidate.get("source_identity")
    score_candidate = candidate
    if isinstance(source_identity, dict):
        score_candidate = {
            **candidate,
            "name": source_identity.get("title") or candidate.get("name"),
            "title": source_identity.get("title") or candidate.get("title"),
            "artist": source_identity.get("artist") or "",
            "artists": [source_identity["artist"]] if source_identity.get("artist") else [],
            "album": source_identity.get("album") or candidate.get("album"),
        }
    score = score_audio_match(canonical, audio_result_from_candidate(score_candidate), AliasResolver.load())
    candidate["match_score"] = score.to_dict()
    if score.decision == MatchDecision.ACCEPT:
        candidate["identity_match"] = True
        candidate["identity_match_source"] = candidate.get("identity_match_source") or "alias_match"
    elif score.decision == MatchDecision.REJECT:
        if candidate.get("identity_match") is True and candidate.get("identity_match_source") in {
            "original_query",
            "youtube_title_query",
        }:
            return candidate
        candidate["identity_match"] = False
    return candidate


def _youtube_title_query_identity_accepts(
    query: str,
    playback_metadata: dict[str, Any] | None,
    source_identity: dict[str, Any],
    info: dict[str, Any],
) -> tuple[bool, int]:
    metadata_identity = _track_identity(_canonical_metadata(playback_metadata or {}))
    if not _complete_identity(metadata_identity):
        return False, 0
    if _identity_artist_text(source_identity.get("artist")):
        return False, 0

    inferred_identity, _ = _infer_youtube_title_identity(playback_metadata, info)
    if inferred_identity:
        variant = _variant_type(query, info)
        quality = _quality_label(query, info, variant, _similarity_score(query, info))
        if variant == "live" and not _contains_any(query, LIVE_TERMS):
            return False, 0
        if quality in {"cover_like", "noisy_media"} and not _contains_any(
            query,
            LOW_RELEVANCE_TERMS + NOISY_MEDIA_TERMS,
        ):
            return False, 0
        return True, 100

    probes = [
        str((playback_metadata or {}).get("original_query") or "").strip(),
        str(query or "").strip(),
        str((playback_metadata or {}).get("youtube_query") or "").strip(),
    ]
    best_score = 0
    for probe in dict.fromkeys(item for item in probes if item):
        score = _similarity_score(probe, info)
        best_score = max(best_score, score)
        terms = _query_terms(probe)
        relevance = _relevance_score(probe, info)
        if score < 70 or relevance <= 0 or (terms and relevance < len(terms)):
            continue
        variant = _variant_type(probe, info)
        quality = _quality_label(probe, info, variant, score)
        if variant == "live" and not _contains_any(probe, LIVE_TERMS):
            continue
        if quality in {"cover_like", "noisy_media"} and not _contains_any(probe, LOW_RELEVANCE_TERMS + NOISY_MEDIA_TERMS):
            continue
        return True, score
    return False, best_score


def _normalized_music_variants(value: Any) -> set[str]:
    return {
        normalized
        for variant in simplified_traditional_variants(str(value or ""))
        for normalized in [normalize_music_text(variant)]
        if normalized
    }


def _identity_phrase_present(haystack: str, needle: str) -> bool:
    if not haystack or not needle:
        return False
    if _has_cjk(needle):
        return needle in haystack
    haystack_words = set(_words(haystack))
    return all(word in haystack_words for word in _words(needle))


def _infer_youtube_title_identity(
    playback_metadata: dict[str, Any] | None,
    info: dict[str, Any],
) -> tuple[dict[str, str] | None, list[str]]:
    canonical = canonical_track_from_metadata(playback_metadata)
    raw_title = _rank_title(info)
    if not raw_title or not canonical.title or not canonical.artist:
        return None, []

    raw_variants = _normalized_music_variants(raw_title)
    title_variants = _normalized_music_variants(canonical.title)
    artist_variants = _normalized_music_variants(canonical.artist)
    title_match = any(
        _identity_phrase_present(raw, title)
        for raw in raw_variants
        for title in title_variants
    )
    artist_match = any(
        _identity_phrase_present(raw, artist)
        for raw in raw_variants
        for artist in artist_variants
    )
    if not title_match or not artist_match:
        return None, []

    evidence = ["youtube_title_artist_match"]
    raw_normalized = normalize_music_text(raw_title)
    direct_title = normalize_music_text(canonical.title)
    direct_artist = normalize_music_text(canonical.artist)
    if (
        not _identity_phrase_present(raw_normalized, direct_title)
        or not _identity_phrase_present(raw_normalized, direct_artist)
    ):
        evidence.append("traditional_simplified_normalized")
    return {
        "title": canonical.title,
        "artist": canonical.artist,
        "album": canonical.album,
        "provenance": "youtube_title",
    }, evidence


def _youtube_has_official_channel_evidence(candidate: dict[str, Any]) -> bool:
    if candidate.get("channel_is_verified") is True:
        return True
    channel = " ".join(
        str(candidate.get(key) or "")
        for key in ("channel", "uploader")
    ).casefold()
    return bool(
        " - topic" in channel
        or channel.endswith(" topic")
        or "official artist channel" in channel
        or "official" in channel
        or "vevo" in channel
    )


def _candidate_assessment(
    candidate: dict[str, Any],
    inferred_identity: dict[str, str] | None,
    evidence: list[str],
) -> dict[str, Any]:
    provider = str(candidate.get("provider") or "")
    match_score = candidate.get("match_score")
    hard_conflicts = list(match_score.get("hard_reject_reasons") or []) if isinstance(match_score, dict) else []
    match_decision = match_score.get("decision") if isinstance(match_score, dict) else None
    match_components = match_score.get("components") if isinstance(match_score, dict) else {}
    if isinstance(match_score, dict):
        evidence.extend(str(reason) for reason in match_score.get("reasons") or [])
    identity_source = candidate.get("identity_match_source")
    if identity_source in {"original_query", "youtube_title_query"}:
        hard_conflicts = [
            reason
            for reason in hard_conflicts
            if reason not in {"artist_mismatch", "insufficient_evidence"}
        ]
    audius_title_only = bool(
        provider == "audius"
        and isinstance(match_components, dict)
        and match_components.get("title")
        and not match_components.get("artist")
        and set(hard_conflicts).issubset({"artist_mismatch", "insufficient_evidence"})
    )
    if audius_title_only:
        hard_conflicts = []
        evidence.append("audius_title_only")
    source_identity = candidate.get("source_identity")
    youtube_structured_match = bool(
        provider == "youtube"
        and candidate.get("provider_identity_match") is True
        and _complete_identity(candidate.get("target_identity"))
        and isinstance(source_identity, dict)
        and _identity_artist_text(source_identity.get("artist"))
    )
    if youtube_structured_match:
        hard_conflicts = [
            reason
            for reason in hard_conflicts
            if reason != "insufficient_evidence"
        ]
        evidence.append("youtube_structured_metadata")
    youtube_title_inference = bool(
        provider == "youtube"
        and (inferred_identity or identity_source == "youtube_title_query")
    )
    youtube_official = bool(
        youtube_title_inference
        and _youtube_has_official_channel_evidence(candidate)
    )
    if youtube_official:
        evidence.append("youtube_official_channel")
    elif youtube_title_inference:
        evidence.append("youtube_unverified_channel")
    quality = str(candidate.get("quality_label") or "")
    variant = str(candidate.get("variant_type") or "")
    candidate_query = str(candidate.get("query") or "")
    unrequested_version = bool(
        (variant == "live" and not _contains_any(candidate_query, LIVE_TERMS))
        or (
            quality in {"cover_like", "noisy_media"}
            and not _contains_any(
                candidate_query,
                LOW_RELEVANCE_TERMS + NOISY_MEDIA_TERMS,
            )
        )
    )
    if unrequested_version:
        hard_conflicts.append("unrequested_version")
    if hard_conflicts:
        confidence = "low"
    elif audius_title_only:
        confidence = "medium"
    elif youtube_structured_match:
        confidence = "high"
    elif youtube_title_inference:
        confidence = "high" if youtube_official else "medium"
    elif identity_source == "original_query" or match_decision == MatchDecision.ACCEPT.value:
        confidence = "high"
    elif match_decision == MatchDecision.REVIEW.value:
        confidence = "medium"
    elif candidate.get("identity_match") is not True:
        confidence = "low"
    else:
        confidence = "medium"
    return {
        "confidence": confidence,
        "evidence": list(dict.fromkeys(evidence)),
        "conflicts": hard_conflicts,
    }


def _validated_identity(item: dict[str, Any], *, downloaded_path: Path | None = None) -> dict[str, Any]:
    target = item.get("target_identity")
    source = item.get("source_identity")
    assessment = item.get("assessment")
    user_verified_review = bool(
        item.get("user_verified") is True
        and isinstance(assessment, dict)
        and assessment.get("confidence") in {"medium", "high"}
        and not assessment.get("conflicts")
    )
    matches = bool(
        _identity_matches(target, source)
        or item.get("query_identity_match") is True
        or item.get("identity_match_source") == "original_query"
        or user_verified_review
    )
    item["identity_match"] = matches
    if matches:
        if user_verified_review:
            item["identity_match_source"] = "user_verified"
        return item
    if downloaded_path is not None:
        try:
            downloaded_path.unlink()
        except FileNotFoundError:
            pass
    raise RuntimeError("Downloaded audio identity does not match the selected track.")


def _merge_canonical_metadata(item: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
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
    try:
        return max(0, int(float(value or 0) * 1000))
    except (TypeError, ValueError):
        return 0


def _count(value: Any) -> int:
    try:
        return max(0, int(float(value or 0)))
    except (TypeError, ValueError):
        return 0


def _variant_type(query: str, info: dict[str, Any]) -> str:
    title = _text(info.get("track") or info.get("title") or info.get("fulltitle") or "") or ""
    channel = _text(info.get("channel") or info.get("uploader") or "") or ""
    combined = f"{title} {channel}".casefold()
    if _contains_any(combined, LIVE_TERMS):
        return "live"
    if _contains_any(combined, OFFICIAL_TERMS) or " - topic" in combined or "official" in channel.casefold() or "vevo" in channel.casefold():
        return "official_original"
    return "other"


def _rank_title(info: dict[str, Any]) -> str:
    return _text(info.get("track") or info.get("title") or info.get("fulltitle") or "") or ""


def _rank_channel(info: dict[str, Any]) -> str:
    return _text(info.get("channel") or info.get("uploader") or "") or ""


def _rank_artist(info: dict[str, Any]) -> str:
    return (
        _non_placeholder_text(info.get("artist"))
        or _non_placeholder_text(info.get("artists"))
        or _non_placeholder_text(info.get("creator"))
        or _non_placeholder_text(info.get("creators"))
        or ""
    )


def _rank_haystack(info: dict[str, Any]) -> str:
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
    title = _rank_title(info)
    if similarity < 70:
        return False
    if _contains_any(title, LIVE_TERMS + LOW_RELEVANCE_TERMS + NOISY_MEDIA_TERMS):
        return False
    return " - " in title or " – " in title or " — " in title or similarity >= 86


def _quality_label(query: str, info: dict[str, Any], variant: str, similarity: int) -> str:
    combined = f"{_rank_title(info)} {_rank_channel(info)}".casefold()
    live_requested = _contains_any(query, LIVE_TERMS)
    if variant == "live":
        return "live"
    if not live_requested and _contains_any(combined, COVER_TERMS):
        return "cover_like"
    if not live_requested and _contains_any(combined, NOISY_MEDIA_TERMS):
        return "noisy_media"
    if variant == "official_original":
        return "official_original"
    if _clean_title_match(query, info, similarity):
        return "clean_audio_match"
    return "other"


def _provider_cache_id(provider: str, provider_id: str | None, source_url: str | None = None) -> str:
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
    source_identity = _track_identity({"name": name, "artist": artist, "album": album})
    identity = _evaluate_identity(
        query=query,
        playback_metadata=metadata,
        source_identity=source_identity,
        info=info,
    )
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
        "source_identity": source_identity,
        "cached": False,
        "is_playing": True,
        **identity,
    }
    if extra_metadata:
        candidate["playback_metadata"] = {**metadata, **extra_metadata}
    _apply_match_score(candidate, metadata)
    canonical = canonical_track_from_metadata(metadata)
    if canonical.title or canonical.artist:
        candidate["canonical_identity"] = {
            "title": canonical.title,
            "artist": canonical.artist,
            "album": canonical.album,
        }
    evidence = [str(candidate["identity_match_source"])] if candidate.get("identity_match_source") else []
    candidate["assessment"] = _candidate_assessment(candidate, None, evidence)
    candidate["media"] = {"kind": "audio_only", "playable": True}
    return _merge_canonical_metadata(candidate, metadata)


def normalize_jamendo_track(
    track: dict[str, Any],
    *,
    query: str,
    playback_metadata: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
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
    artwork = track.get("artwork")
    if not isinstance(artwork, dict):
        return None
    for key in ("1000x1000", "480x480", "150x150"):
        url = _text(artwork.get(key))
        if url:
            return url
    return None


def _audius_user_name(track: dict[str, Any]) -> str | None:
    user = track.get("user")
    if isinstance(user, dict):
        return _text(user.get("name") or user.get("handle"))
    return None


def _is_audius_stream_gated(track: dict[str, Any]) -> bool:
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
    return round(math.log10(max(0, popularity) + 1) * 1000)


def _relevance_score(query: str, info: dict[str, Any]) -> int:
    terms = _query_terms(query)
    if not terms:
        return 0
    haystack = _rank_haystack(info).casefold()
    return sum(1 for term in terms if term in haystack)


def _popularity_score(info: dict[str, Any]) -> int:
    view_count = _count(info.get("view_count"))
    like_count = _count(info.get("like_count"))
    comment_count = _count(info.get("comment_count"))
    repost_count = _count(info.get("repost_count"))
    return view_count + like_count * 20 + comment_count * 5 + repost_count * 10


def _rank_reason(variant: str, popularity: int, relevance: int, similarity: int, quality: str) -> str:
    label = {
        "official_original": "official original",
        "live": "live version",
        "other": "other match",
    }.get(variant, "other match")
    return f"{label}; quality={quality}; similarity={similarity}; popularity={popularity}; relevance={relevance}"


def _is_age_restricted_info(info: dict[str, Any]) -> bool:
    try:
        age_limit = int(info.get("age_limit") or 0)
    except (TypeError, ValueError):
        age_limit = 0
    if age_limit > 0:
        return True
    availability = str(info.get("availability") or "").casefold()
    return availability == "needs_auth"


def _is_unavailable_info(info: dict[str, Any]) -> bool:
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
    text = message.casefold()
    return (
        "confirm your age" in text
        or "age verification" in text
        or "may be inappropriate for some users" in text
    )


def _is_unavailable_error(message: str) -> bool:
    text = message.casefold()
    return (
        "this video is not available" in text
        or "video unavailable" in text
        or "private video" in text
        or "members-only" in text
        or "join this channel" in text
    )


def _should_keep_candidate(query: str, info: dict[str, Any]) -> bool:
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
    stream_url = _text(info.get("url"))
    if stream_url:
        return stream_url

    formats = info.get("formats") or []
    playable_formats = [
        item for item in formats
        if isinstance(item, dict)
        and item.get("url")
        and item.get("acodec") not in (None, "none")
    ]
    if not playable_formats:
        raise RuntimeError("No playable audio format found.")

    playable_formats.sort(
        key=lambda item: (
            item.get("vcodec") in (None, "none"),
            item.get("abr") or 0,
            item.get("tbr") or 0,
        ),
        reverse=True,
    )
    return str(playable_formats[0]["url"])


def _media_kind(info: dict[str, Any]) -> str:
    formats = info.get("formats") or []
    playable = [
        item
        for item in formats
        if isinstance(item, dict)
        and item.get("acodec") not in (None, "none")
    ]
    if playable and not any(item.get("vcodec") in (None, "none") for item in playable):
        return "video_container"
    if info.get("vcodec") not in (None, "none"):
        return "video_container"
    return "audio_only"


def _media_fingerprint(info: dict[str, Any]) -> str:
    fingerprint_source = "|".join(
        str(info.get(key) or "").strip()
        for key in ("id", "title", "duration", "uploader")
    )
    return hashlib.sha256(fingerprint_source.encode("utf-8")).hexdigest()[:24]


def _webpage_url(info: dict[str, Any]) -> str | None:
    url = _text(info.get("webpage_url") or info.get("original_url"))
    if url:
        return url
    video_id = _text(info.get("id"))
    if video_id:
        return f"https://www.youtube.com/watch?v={video_id}"
    return None


def _youtube_cache_id(info: dict[str, Any]) -> str:
    video_id = _text(info.get("youtube_id") or info.get("id"))
    if video_id:
        return f"youtube_{video_id}"
    url = _webpage_url(info) or _text(info.get("url")) or ""
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    return f"youtube_{digest}"


def _cached_audio_item(
    cache_id: str,
    *,
    cache_root: Path | None = None,
    target_identity: dict[str, Any] | None = None,
    query: str | None = None,
    playback_metadata: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    try:
        item = resolve_cached_song(cache_id, cache_root=cache_root)
    except Exception:
        return None
    if _complete_identity(target_identity):
        source_identity = item.get("source_identity")
        if not isinstance(source_identity, dict):
            return None
        if not _identity_matches(target_identity, source_identity):
            identity = _evaluate_identity(
                query=str(query or item.get("query") or ""),
                playback_metadata=playback_metadata,
                source_identity=source_identity,
                info={
                    "track": source_identity.get("title") or item.get("name") or item.get("title"),
                    "artist": source_identity.get("artist") or item.get("artist"),
                    "album": source_identity.get("album") or item.get("album"),
                },
            )
            if not identity["identity_match"]:
                return None
            item.update(identity)
    audio_path = _text(item.get("audio_path"))
    if audio_path and Path(audio_path).expanduser().exists():
        item["stream_url"] = audio_path
        item["cached"] = True
        return item
    return None


def _normalize_youtube_info(
    query: str,
    info: dict[str, Any],
    stream_url: str | None = None,
    playback_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    title = _text(info.get("track") or info.get("title") or info.get("fulltitle") or query) or query
    structured_artist = (
        _non_placeholder_text(info.get("artist"))
        or _non_placeholder_text(info.get("artists"))
        or _non_placeholder_text(info.get("creator"))
        or _non_placeholder_text(info.get("creators"))
        or "-"
    )
    channel = _rank_channel(info)
    uploader = _text(info.get("uploader"))
    artist = structured_artist if structured_artist != "-" else _non_placeholder_text(uploader or channel) or "-"
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
    source_identity = _track_identity({
        "name": title,
        "artist": "" if structured_artist == "-" else structured_artist,
        "artists": info.get("artists"),
        "album": album,
    })
    identity = _evaluate_identity(
        query=query,
        playback_metadata=playback_metadata,
        source_identity=source_identity,
        info={**info, "track": title, "artist": artist, "album": album},
    )
    if not identity["identity_match"]:
        youtube_match, youtube_score = _youtube_title_query_identity_accepts(
            query,
            playback_metadata,
            source_identity,
            {**info, "track": title, "artist": artist, "album": album},
        )
        if youtube_match:
            identity = {
                **identity,
                "identity_match": True,
                "identity_match_source": "youtube_title_query",
                "query_identity_match": True,
                "query_identity_score": max(int(identity.get("query_identity_score") or 0), youtube_score),
            }
    candidate = {
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
        "channel": channel,
        "uploader": uploader,
        "channel_is_verified": info.get("channel_is_verified"),
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
        "source_identity": source_identity,
        **identity,
        "raw_view_count": _count(info.get("view_count")),
        "raw_like_count": _count(info.get("like_count")),
        "is_playing": True,
    }
    _apply_match_score(candidate, _canonical_metadata(playback_metadata or {}))
    canonical = canonical_track_from_metadata(playback_metadata)
    inferred_identity, inference_evidence = _infer_youtube_title_identity(playback_metadata, info)
    if canonical.title or canonical.artist:
        candidate["canonical_identity"] = {
            "title": canonical.title,
            "artist": canonical.artist,
            "album": canonical.album,
        }
    if inferred_identity:
        candidate["inferred_identity"] = inferred_identity
    evidence = list(inference_evidence)
    if candidate.get("identity_match_source"):
        evidence.append(str(candidate["identity_match_source"]))
    candidate["assessment"] = _candidate_assessment(candidate, inferred_identity, evidence)
    return candidate


def _rank_youtube_candidates(query: str, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
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

    def score(pair: tuple[int, dict[str, Any]]) -> tuple[int, int, int, int, int, int, int]:
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
    quality_priority = {
        "official_original": 4,
        "clean_audio_match": 3,
        "live": 2,
        "other": 1,
        "cover_like": -2,
        "noisy_media": -3,
    }
    confidence_priority = {"high": 2, "medium": 1, "low": 0}

    def score(pair: tuple[int, dict[str, Any]]) -> tuple[int, int, int, int, int]:
        _, candidate = pair
        assessment = candidate.get("assessment")
        confidence = assessment.get("confidence") if isinstance(assessment, dict) else "high"
        match_score = candidate.get("match_score")
        match_total = int(match_score.get("total_score") or 0) if isinstance(match_score, dict) else 0
        identity_strength = max(match_total, int(candidate.get("similarity_score") or 0))
        provider = str(candidate.get("provider") or "")
        metadata_completeness = sum(
            bool(candidate.get(key) and candidate.get(key) != "-")
            for key in ("duration_ms", "album", "cover_url")
        )
        return (
            confidence_priority.get(str(confidence or "high"), 0),
            identity_strength,
            quality_priority.get(str(candidate.get("quality_label") or "other"), 0),
            1 if provider in {"jamendo", "audius"} else 0,
            metadata_completeness,
        )

    indexed = list(enumerate(candidates))
    indexed.sort(key=lambda pair: str(pair[1].get("provider") or ""))
    indexed.sort(key=score, reverse=True)
    return [candidate for _, candidate in indexed]


def _credible_online_audio_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    credible: list[dict[str, Any]] = []
    for candidate in candidates:
        assessment = candidate.get("assessment")
        if isinstance(assessment, dict) and assessment.get("confidence") != "high":
            continue
        match_score = candidate.get("match_score")
        if isinstance(match_score, dict) and match_score.get("decision") != MatchDecision.ACCEPT.value:
            continue
        if int(candidate.get("similarity_score") or 0) >= 45:
            credible.append(candidate)
    return credible


def _provider_label(provider: str) -> str:
    return {"jamendo": "Jamendo", "audius": "Audius", "youtube": "YouTube"}.get(provider, provider.title())


def _sanitize_provider_error(error: Any) -> str:
    message = sanitize_error_message(error)
    return re.sub(r"(?i)(secret)\s*[:=]\s*([^\s,;]+)", r"\1=[redacted]", message)


def _source_attempt(
    provider: str,
    *,
    status: str,
    candidate_count: int = 0,
    credible_count: int = 0,
    rejected_count: int = 0,
    message: str | None = None,
) -> dict[str, Any]:
    label = _provider_label(provider)
    if not message:
        if status == "success":
            message = f"{label} returned {credible_count} credible match{'es' if credible_count != 1 else ''}."
        elif status == "missing_config":
            message = f"{label} is not configured."
        elif status == "error":
            message = f"{label} failed."
        elif status == "identity_mismatch":
            message = f"{label} rejected {rejected_count} identity mismatch{'es' if rejected_count != 1 else ''}."
        elif status == "skipped_high_confidence":
            message = f"{label} was skipped because open audio returned a high-confidence match."
        else:
            message = f"{label} returned no credible matches."
    attempt = {
        "provider": provider,
        "status": status,
        "candidate_count": max(0, int(candidate_count or 0)),
        "credible_count": max(0, int(credible_count or 0)),
        "message": _sanitize_provider_error(message),
    }
    if rejected_count:
        attempt["rejected_count"] = max(0, int(rejected_count))
    return attempt


def _fallback_reason(source_attempts: list[dict[str, Any]]) -> str:
    messages = [str(item.get("message") or "").strip() for item in source_attempts if item.get("message")]
    return " ".join(messages) or "Configured open-audio providers returned no credible matches."


def _friendly_youtube_failure_message(message: str) -> str:
    runtime_code = managed_runtime_failure_code(message)
    managed_error = _managed_runtime_tool_error(runtime_code) if runtime_code else None
    if managed_error:
        return managed_error[0]
    if _is_age_verification_error(message):
        return AGE_RESTRICTED_MESSAGE
    if _is_unavailable_error(message):
        return UNAVAILABLE_MESSAGE
    return sanitize_error_message(message)


def _with_youtube_fallback_trace(candidate: dict[str, Any], source_attempts: list[dict[str, Any]]) -> dict[str, Any]:
    traced = dict(candidate)
    reason = _fallback_reason(source_attempts)
    traced["fallback_provider"] = "youtube"
    traced["fallback_reason"] = reason
    traced["source_attempts"] = [dict(item) for item in source_attempts]
    return traced


def _format_youtube_fallback_failure(candidate: dict[str, Any], youtube_message: str) -> str:
    reason = str(candidate.get("fallback_reason") or _fallback_reason(candidate.get("source_attempts") or [])).strip()
    if reason:
        return f"{reason} Sonex fell back to YouTube. YouTube failed: {sanitize_error_message(youtube_message)}"
    return f"Sonex fell back to YouTube. YouTube failed: {sanitize_error_message(youtube_message)}"


def _json_get(url: str, *, headers: dict[str, str] | None = None, timeout: float = 10.0) -> dict[str, Any]:
    request = urllib.request.Request(url, headers=headers or {})
    with proxy_urlopen(request, timeout=timeout) as response:
        payload = response.read().decode("utf-8")
    data = json.loads(payload)
    if not isinstance(data, dict):
        raise RuntimeError("Invalid response returned.")
    return data


def _playback_search_fields(playback_metadata: dict[str, Any] | None = None) -> tuple[str | None, str | None, str | None]:
    if not isinstance(playback_metadata, dict):
        return None, None, None

    artist = _non_placeholder_text(
        playback_metadata.get("artist")
        or playback_metadata.get("artists")
    )
    title = _non_placeholder_text(
        playback_metadata.get("title")
        or playback_metadata.get("name")
    )
    album = _non_placeholder_text(playback_metadata.get("album"))
    return artist, title, album


def _progressive_audio_query_variants(
    query: str,
    playback_metadata: dict[str, Any],
) -> list[tuple[str, str]]:
    variants: list[tuple[str, str]] = []

    def add(kind: str, value: str) -> None:
        clean = " ".join(str(value or "").split())
        if clean and clean not in {item[1] for item in variants} and len(variants) < 3:
            variants.append((kind, clean))

    canonical = canonical_track_from_metadata(playback_metadata)
    if not canonical.title or not canonical.artist:
        add("raw_query", query)
        return variants
    add("media_hint", f"{canonical.artist} {canonical.title} official audio")
    add("original_query", _identity_context(query, playback_metadata).original_query)

    title_variants = sorted(
        simplified_traditional_variants(canonical.title),
        key=lambda value: (value == canonical.title, value),
    )
    for title in title_variants:
        add("localized_title", f"{canonical.artist} {title}")

    resolver = AliasResolver.load()
    for artist in resolver.aliases_for("artist", canonical.artist):
        for title in resolver.aliases_for("track", canonical.title):
            add("localized_alias", f"{artist} {title}")

    return variants


def _audius_query_variants(
    query: str,
    playback_metadata: dict[str, Any] | None,
) -> list[str]:
    variants: list[str] = []

    def add(value: str) -> None:
        clean = " ".join(str(value or "").split())
        if clean and clean not in variants and len(variants) < 3:
            variants.append(clean)

    artist, title, _ = _playback_search_fields(playback_metadata)
    add(f"{artist} {title}" if artist and title else query)
    add(_identity_context(query, playback_metadata).original_query)

    canonical = canonical_track_from_metadata(playback_metadata)
    if canonical.title and canonical.artist:
        for localized_title in sorted(
            simplified_traditional_variants(canonical.title),
            key=lambda value: (value == canonical.title, value),
        ):
            add(f"{canonical.artist} {localized_title}")
        resolver = AliasResolver.load()
        for localized_artist in resolver.aliases_for("artist", canonical.artist):
            for localized_title in resolver.aliases_for("track", canonical.title):
                add(f"{localized_artist} {localized_title}")
    return variants


def search_jamendo_audio_candidates(
    query: str,
    *,
    client_id: str,
    limit: int = 5,
    playback_metadata: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    artist, title, album = _playback_search_fields(playback_metadata)
    base_params: dict[str, Any] = {
        "client_id": client_id,
        "format": "json",
        "limit": 20 if artist and title else max(1, min(20, int(limit or 5))),
        "audioformat": "mp32",
        "imagesize": 600,
        "include": "musicinfo",
    }
    query_stages: list[tuple[dict[str, Any], str]]
    if artist and title:
        exact = {
            **base_params,
            "name": title,
            "artist_name": artist,
            "type": "single albumtrack",
            "order": "relevance",
        }
        if album:
            exact["album_name"] = album
        query_stages = [
            (exact, query),
            ({
                **base_params,
                "namesearch": title,
                "artist_name": artist,
                "type": "single albumtrack",
                "order": "relevance",
            }, query),
        ]
    else:
        query_stages = [({**base_params, "search": query}, query)]

    candidates: list[dict[str, Any]] = []
    seen_cache_ids: set[str] = set()
    rejected_count = 0
    for stage, stage_query in query_stages:
        params = urllib.parse.urlencode(stage)
        payload = _json_get(f"https://api.jamendo.com/v3.0/tracks/?{params}")
        results = payload.get("results") or []
        normalized = [
            candidate
            for item in results
            if isinstance(item, dict)
            for candidate in [normalize_jamendo_track(item, query=stage_query, playback_metadata=playback_metadata)]
            if candidate is not None
        ]
        rejected_count += sum(
            candidate.get("assessment", {}).get("confidence") == "low"
            for candidate in normalized
        )
        accepted = [
            candidate
            for candidate in normalized
            if candidate.get("assessment", {}).get("confidence") != "low"
        ]
        for candidate in accepted:
            cache_id = str(candidate.get("cache_id") or "")
            if cache_id and cache_id in seen_cache_ids:
                continue
            if cache_id:
                seen_cache_ids.add(cache_id)
            candidates.append(candidate)
        if any(_candidate_confidence(candidate) == "high" for candidate in accepted) or not (artist and title):
            break
    ranked = rank_online_audio_candidates(query, candidates)[: max(1, min(10, int(limit or 5)))]
    return IdentityCandidateList(ranked, rejected_count=rejected_count)


def _audius_stream_url(track_id: str, *, api_key: str | None = None) -> str:
    params = {"app_name": "Sonex"}
    if _text(api_key):
        params["api_key"] = str(api_key)
    return (
        f"{AUDIUS_API_BASE_URL}/tracks/{urllib.parse.quote(track_id, safe='')}/stream"
        f"?{urllib.parse.urlencode(params)}"
    )


def search_audius_audio_candidates(
    query: str,
    *,
    api_key: str,
    limit: int = 5,
    playback_metadata: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen_cache_ids: set[str] = set()
    rejected_count = 0
    for search_query in _audius_query_variants(query, playback_metadata):
        query_params = {
            "query": search_query,
            "limit": max(1, min(20, int(limit or 5))),
            "app_name": "Sonex",
        }
        if _text(api_key):
            query_params["api_key"] = api_key
        params = urllib.parse.urlencode(query_params)
        payload = _json_get(
            f"{AUDIUS_API_BASE_URL}/tracks/search?{params}",
            headers=dict(AUDIUS_REQUEST_HEADERS),
        )
        data = payload.get("data") or []
        for item in data:
            if not isinstance(item, dict):
                continue
            track_id = _text(item.get("id"))
            if not track_id:
                continue
            candidate = normalize_audius_track(
                item,
                query=search_query,
                stream_url=_audius_stream_url(track_id, api_key=api_key),
                playback_metadata=playback_metadata,
            )
            if not candidate:
                continue
            if _candidate_confidence(candidate) == "low":
                rejected_count += 1
                continue
            cache_id = str(candidate.get("cache_id") or "")
            if cache_id and cache_id in seen_cache_ids:
                continue
            if cache_id:
                seen_cache_ids.add(cache_id)
            candidates.append(candidate)
        if any(_candidate_confidence(candidate) == "high" for candidate in candidates):
            break
    ranked = rank_online_audio_candidates(query, candidates)[: max(1, min(10, int(limit or 5)))]
    return IdentityCandidateList(ranked, rejected_count=rejected_count)


def _provider_failure_code(error: Exception) -> str:
    message = str(error).casefold()
    runtime_code = managed_runtime_failure_code(error)
    return provider_failure_category(
        managed_code=runtime_code,
        timed_out=isinstance(error, TimeoutError) or "timed out" in message or "timeout" in message,
        rate_limited="429" in message or "too many requests" in message or "rate limit" in message,
        age_restricted=_is_age_verification_error(message),
        bot_challenge="not a bot" in message or "sign in to confirm" in message,
        unavailable=_is_unavailable_error(message),
    )


def _managed_runtime_tool_error(failure_code: str) -> tuple[str, str] | None:
    """Map stable managed-runtime failures to ToolResult output fields."""
    if failure_code == "youtube_po_provider_unavailable":
        return "YouTube playback is not configured. Open /extension to configure it.", "YOUTUBE_PO_PROVIDER_UNAVAILABLE"
    if failure_code == "youtube_queue_busy":
        return "Another YouTube request is still running. Try again shortly.", "YOUTUBE_QUEUE_BUSY"
    return None


def _youtube_search_cooldown_remaining(*, cache_root: Path | None = None) -> float:
    with _youtube_search_cooldown_lock:
        memory_remaining = max(0.0, _youtube_search_cooldown_until - time.monotonic())
    try:
        persistent = provider_cooldown("youtube", cache_root=cache_root)
    except (OSError, sqlite3.Error):
        persistent = None
    persistent_remaining = float(persistent.get("remaining_seconds", 0.0)) if persistent else 0.0
    return max(memory_remaining, persistent_remaining)


def _activate_youtube_search_cooldown(
    seconds: float = YOUTUBE_SEARCH_COOLDOWN_SECONDS,
    *,
    failure_class: str = "rate_limited",
    retry_after: float | None = None,
    cache_root: Path | None = None,
) -> None:
    global _youtube_search_cooldown_until
    duration = max(1.0, float(seconds))
    should_persist = True
    if should_persist:
        try:
            state = activate_provider_cooldown(
                "youtube",
                failure_class,
                retry_after=retry_after,
                cache_root=cache_root,
            )
            duration = max(duration, float(state["cooldown_seconds"]))
        except (OSError, sqlite3.Error):
            # A read-only runtime still needs the in-process circuit breaker.
            pass
    with _youtube_search_cooldown_lock:
        _youtube_search_cooldown_until = max(
            _youtube_search_cooldown_until,
            time.monotonic() + duration,
        )


def _run_online_provider_searches(
    jobs: dict[str, Callable[[], list[dict[str, Any]]]],
    *,
    timeout: float = ONLINE_AUDIO_SEARCH_TIMEOUT_SECONDS,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Exception]]:
    if not jobs:
        return {}, {}
    executor = ThreadPoolExecutor(
        max_workers=len(jobs),
        thread_name_prefix="sonex-online-audio",
    )
    futures: dict[str, Future[list[dict[str, Any]]]] = {
        provider: executor.submit(search)
        for provider, search in jobs.items()
    }
    _, pending = wait(futures.values(), timeout=max(0.1, float(timeout)))
    results: dict[str, list[dict[str, Any]]] = {}
    errors: dict[str, Exception] = {}
    for provider, future in futures.items():
        if future in pending:
            future.cancel()
            errors[provider] = TimeoutError(
                f"{_provider_label(provider)} search exceeded {timeout:g} seconds."
            )
            continue
        try:
            value = future.result()
            results[provider] = value if isinstance(value, list) else list(value or [])
        except Exception as exc:
            errors[provider] = exc
    executor.shutdown(wait=False, cancel_futures=True)
    return results, errors


def _timed_provider_search_jobs(
    jobs: dict[str, Callable[[], list[dict[str, Any]]]],
    provider_elapsed_ms: dict[str, int],
) -> dict[str, Callable[[], list[dict[str, Any]]]]:
    elapsed_lock = Lock()
    timed_jobs: dict[str, Callable[[], list[dict[str, Any]]]] = {}
    for provider, search in jobs.items():
        def timed_search(
            provider_name: str = provider,
            provider_search: Callable[[], list[dict[str, Any]]] = search,
        ) -> list[dict[str, Any]]:
            provider_started_at = time.monotonic()
            try:
                return provider_search()
            finally:
                elapsed = round((time.monotonic() - provider_started_at) * 1000)
                with elapsed_lock:
                    provider_elapsed_ms[provider_name] = elapsed

        timed_jobs[provider] = timed_search
    return timed_jobs


def _build_online_search_trace(
    *,
    trace_id: str,
    started_at: float,
    final_state: str,
    config: OnlineAudioConfig,
    candidates: list[dict[str, Any]],
    source_attempts: list[dict[str, Any]],
    provider_elapsed_ms: dict[str, int],
) -> dict[str, Any]:
    confidence_counts = {"high": 0, "medium": 0, "low": 0}
    for candidate in candidates:
        assessment = candidate.get("assessment")
        confidence = assessment.get("confidence") if isinstance(assessment, dict) else "high"
        normalized_confidence = str(confidence or "high")
        if normalized_confidence not in confidence_counts:
            normalized_confidence = "low"
        confidence_counts[normalized_confidence] += 1
    return {
        "id": trace_id,
        "elapsed_ms": round((time.monotonic() - started_at) * 1000),
        "final_state": final_state,
        "provider_capabilities": {
            "jamendo": "configured" if config.jamendo_client_id else "not_configured",
            "audius": "configured" if config.audius_api_key else "not_configured",
            "youtube": "configured",
        },
        "provider_elapsed_ms": {
            provider: max(0, int(provider_elapsed_ms.get(provider, 0)))
            for provider in ("jamendo", "audius", "youtube")
        },
        "confidence_counts": confidence_counts,
        "attempts": [dict(item) for item in source_attempts],
    }


def _search_open_audio_fallback(
    *,
    search_query: str,
    limit: int,
    playback_metadata: dict[str, Any],
    config: OnlineAudioConfig,
    provider_elapsed_ms: dict[str, int],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Search Jamendo and Audius together after the YouTube primary attempt."""
    jobs: dict[str, Callable[[], list[dict[str, Any]]]] = {}
    if config.jamendo_client_id:
        jobs["jamendo"] = lambda: search_jamendo_audio_candidates(
            search_query,
            client_id=str(config.jamendo_client_id),
            limit=limit,
            playback_metadata=playback_metadata,
        )
    if config.audius_api_key:
        jobs["audius"] = lambda: search_audius_audio_candidates(
            search_query,
            api_key=str(config.audius_api_key),
            limit=limit,
            playback_metadata=playback_metadata,
        )
    if not jobs:
        return [], [
            _source_attempt("jamendo", status="missing_config"),
            _source_attempt("audius", status="missing_config"),
        ]

    provider_results, provider_errors = _run_online_provider_searches(
        _timed_provider_search_jobs(jobs, provider_elapsed_ms),
        timeout=OPEN_AUDIO_SEARCH_TIMEOUT_SECONDS,
    )
    candidates: list[dict[str, Any]] = []
    attempts: list[dict[str, Any]] = []
    for provider, configured in (
        ("jamendo", bool(config.jamendo_client_id)),
        ("audius", bool(config.audius_api_key)),
    ):
        if not configured:
            attempts.append(_source_attempt(provider, status="missing_config"))
            continue
        error = provider_errors.get(provider)
        if error is not None:
            attempts.append(
                _source_attempt(
                    provider,
                    status=_provider_failure_code(error),
                    message=f"{_provider_label(provider)} failed: {_sanitize_provider_error(error)}",
                )
            )
            continue
        provider_candidates = provider_results.get(provider, [])
        credible = _credible_online_audio_candidates(provider_candidates)
        review_candidates = [
            candidate
            for candidate in provider_candidates
            if _candidate_confidence(candidate) == "medium"
        ]
        rejected_count = int(getattr(provider_candidates, "rejected_count", 0) or 0)
        attempts.append(
            _source_attempt(
                provider,
                status="success" if credible or review_candidates else ("identity_mismatch" if rejected_count else "no_credible_matches"),
                candidate_count=len(provider_candidates) + rejected_count,
                credible_count=len(credible),
                rejected_count=rejected_count,
            )
        )
        candidates.extend(credible)
        candidates.extend(review_candidates)
    return candidates, attempts


def resolve_online_audio_candidates(
    query: str,
    limit: int = 5,
    *,
    cache_root: Path | None = None,
    playback_metadata: dict[str, Any] | None = None,
    config: OnlineAudioConfig | None = None,
) -> list[dict[str, Any]]:
    resolved_config = config or online_audio_config()
    resolved_metadata = resolve_online_playback_metadata(query, playback_metadata)
    search_query = str(resolved_metadata.get("youtube_query") or query).strip() or query
    trace_id = f"audio-{uuid.uuid4().hex[:12]}"
    started_at = time.monotonic()
    provider_elapsed_ms: dict[str, int] = {}

    youtube_error: Exception | None = None
    source_attempts: list[dict[str, Any]] = []
    youtube_candidates: list[dict[str, Any]] = []
    youtube_cooldown = _youtube_search_cooldown_remaining(cache_root=cache_root)
    if not youtube_enabled():
        pass
    elif youtube_cooldown > 0:
        youtube_error = RuntimeError(
            f"YouTube is cooling down for {math.ceil(youtube_cooldown)} seconds."
        )
    else:
        total_elapsed = time.monotonic() - started_at
        youtube_timeout = min(
            YOUTUBE_FALLBACK_SEARCH_TIMEOUT_SECONDS,
            max(0.0, ONLINE_AUDIO_SEARCH_TIMEOUT_SECONDS - total_elapsed),
        )
        if youtube_timeout <= 0:
            youtube_error = TimeoutError(
                f"YouTube search exceeded the {ONLINE_AUDIO_SEARCH_TIMEOUT_SECONDS:g}-second total budget."
            )
        else:
            youtube_jobs = {
                "youtube": lambda: search_youtube_songs(
                    search_query,
                    limit=limit,
                    cache_root=cache_root,
                    playback_metadata=resolved_metadata,
                )
            }
            youtube_results, youtube_errors = _run_online_provider_searches(
                _timed_provider_search_jobs(youtube_jobs, provider_elapsed_ms),
                timeout=youtube_timeout,
            )
            youtube_candidates = youtube_results.get("youtube", [])
            youtube_error = youtube_errors.get("youtube")
            provider_elapsed_ms.setdefault(
                "youtube",
                round((time.monotonic() - started_at) * 1000),
            )

    if youtube_error is not None:
        if isinstance(youtube_error, AudioIdentityMismatch):
            source_attempts.append(
                _source_attempt(
                    "youtube",
                    status="identity_mismatch",
                    candidate_count=youtube_error.rejected_count,
                    rejected_count=youtube_error.rejected_count,
                )
            )
        else:
            failure_code = _provider_failure_code(youtube_error)
            if failure_code in {"provider_rate_limited", "provider_bot_challenge"}:
                _activate_youtube_search_cooldown(
                    failure_class=(
                        "bot_challenge"
                        if failure_code == "provider_bot_challenge"
                        else "rate_limited"
                    ),
                    cache_root=cache_root,
                )
                failure_message = "YouTube is temporarily unavailable; search is cooling down."
            elif "cooling down" in str(youtube_error).casefold():
                failure_code = "provider_temporarily_unavailable"
                failure_message = str(youtube_error)
            else:
                failure_message = _friendly_youtube_failure_message(str(youtube_error))
            source_attempts.append(
                _source_attempt(
                    "youtube",
                    status=failure_code,
                    message=f"YouTube failed: {failure_message}",
                )
            )
    else:
        youtube_rejected = int(getattr(youtube_candidates, "rejected_count", 0) or 0)
        source_attempts.append(
            _source_attempt(
                "youtube",
                status="success" if youtube_candidates else ("identity_mismatch" if youtube_rejected else "no_credible_matches"),
                candidate_count=len(youtube_candidates) + youtube_rejected,
                credible_count=sum(
                    _candidate_confidence(candidate) == "high"
                    for candidate in youtube_candidates
                ),
                rejected_count=youtube_rejected,
            )
        )

    youtube_high_candidates = [
        candidate for candidate in youtube_candidates
        if _candidate_confidence(candidate) == "high"
    ]
    if youtube_high_candidates:
        candidates = youtube_high_candidates
    else:
        open_candidates, open_attempts = _search_open_audio_fallback(
            search_query=search_query,
            limit=limit,
            playback_metadata=resolved_metadata,
            config=resolved_config,
            provider_elapsed_ms=provider_elapsed_ms,
        )
        source_attempts.extend(open_attempts)
        open_high_candidates = [
            candidate for candidate in open_candidates
            if _candidate_confidence(candidate) == "high"
        ]
        candidates = open_high_candidates or [*youtube_candidates, *open_candidates]

    if not candidates:
        message = _fallback_reason(source_attempts)
        youtube_failure_code = _provider_failure_code(youtube_error) if youtube_error is not None else ""
        if (
            youtube_error is not None
            and not isinstance(youtube_error, AudioIdentityMismatch)
            and youtube_failure_code not in {
                "provider_rate_limited",
                "provider_bot_challenge",
                "provider_temporarily_unavailable",
            }
            and "cooling down" not in str(youtube_error).casefold()
        ):
            message = (
                f"{message} YouTube failed: "
                f"{_friendly_youtube_failure_message(str(youtube_error))}"
            )
        search_trace = _build_online_search_trace(
            trace_id=trace_id,
            started_at=started_at,
            final_state="no_candidate",
            config=resolved_config,
            candidates=[],
            source_attempts=source_attempts,
            provider_elapsed_ms=provider_elapsed_ms,
        )
        raise OnlineAudioResolutionError(
            message,
            source_attempts=source_attempts,
            search_trace=search_trace,
        )

    search_trace = _build_online_search_trace(
        trace_id=trace_id,
        started_at=started_at,
        final_state="candidate_found",
        config=resolved_config,
        candidates=candidates,
        source_attempts=source_attempts,
        provider_elapsed_ms=provider_elapsed_ms,
    )
    elapsed_ms = int(search_trace["elapsed_ms"])
    for candidate in candidates:
        candidate["source_attempts"] = [dict(item) for item in source_attempts]
        candidate["search_trace_id"] = trace_id
        candidate["search_elapsed_ms"] = elapsed_ms
        candidate["search_trace"] = dict(search_trace)
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
    return resolve_online_audio_candidates(
        query,
        limit=limit,
        cache_root=cache_root,
        playback_metadata=playback_metadata,
    )


def _search_youtube_songs_uncached(
    query: str,
    limit: int = 5,
    *,
    cache_root: Path | None = None,
    playback_metadata: dict[str, Any] | None = None,
    deadline: float | None = None,
) -> list[dict[str, Any]]:
    playback_metadata = resolve_online_playback_metadata(query, playback_metadata)
    query_variants = _progressive_audio_query_variants(query, playback_metadata)
    youtube_query = _identity_context(query, playback_metadata).provider_query or query
    bounded_limit = max(1, min(10, int(limit or 5)))
    search_limit = min(20, max(8, bounded_limit * 4))
    options = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "ignoreerrors": True,
        "extract_flat": "in_playlist",
        "socket_timeout": 4,
    }

    candidates: list[dict[str, Any]] = []
    seen_cache_ids: set[str] = set()
    rejected_count = 0
    for _, variant_query in query_variants:
            remaining = (
                YOUTUBE_SEARCH_OPERATION_TIMEOUT_SECONDS
                if deadline is None
                else deadline - time.monotonic()
            )
            if remaining <= 0:
                raise YtDlpTimeoutError("YouTube search exceeded its total time budget.")
            payload = _run_gated_youtube_search(
                target=f"ytsearch{search_limit}:{variant_query}",
                options=options,
                timeout_seconds=min(YOUTUBE_SEARCH_OPERATION_TIMEOUT_SECONDS, remaining),
            )

            if not isinstance(payload, dict):
                raise RuntimeError("Invalid response returned.")

            entries = payload.get("entries") or []
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                if not _should_keep_candidate(variant_query, entry):
                    continue
                candidate = _merge_canonical_metadata(
                    _normalize_youtube_info(variant_query, entry, None, playback_metadata),
                    playback_metadata,
                )
                assessment = candidate.get("assessment")
                confidence = assessment.get("confidence") if isinstance(assessment, dict) else None
                if confidence == "low" or (
                    candidate.get("identity_match") is False
                    and confidence != "medium"
                ):
                    rejected_count += 1
                    continue
                cache_id = str(candidate["cache_id"])
                if cache_id in seen_cache_ids:
                    continue
                seen_cache_ids.add(cache_id)
                candidate["query"] = variant_query
                candidate["original_query"] = playback_metadata.get("original_query") or query
                candidate["youtube_query"] = youtube_query
                cached = _cached_audio_item(
                    cache_id,
                    cache_root=cache_root,
                    target_identity=candidate.get("target_identity"),
                    query=variant_query,
                    playback_metadata=playback_metadata,
                )
                candidate["cached"] = cached is not None
                if cached:
                    candidate["audio_path"] = cached.get("audio_path")
                    candidate["audio_ext"] = cached.get("audio_ext")
                candidates.append(candidate)
            high_confidence_count = sum(
                1
                for candidate in candidates
                if isinstance(candidate.get("assessment"), dict)
                and candidate["assessment"].get("confidence") == "high"
            )
            if high_confidence_count >= 1:
                break
    if not candidates:
        if rejected_count:
            raise AudioIdentityMismatch("youtube", rejected_count)
        raise RuntimeError("No valid matches found.")
    ranked = _rank_youtube_candidates(youtube_query, candidates)[:bounded_limit]
    return IdentityCandidateList(ranked, rejected_count=rejected_count)


def search_youtube_songs(
    query: str,
    limit: int = 5,
    *,
    cache_root: Path | None = None,
    playback_metadata: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Search YouTube with persistent metadata caching and single-flight protection."""
    resolved_metadata = resolve_online_playback_metadata(query, playback_metadata)
    query_variants = _progressive_audio_query_variants(query, resolved_metadata)
    trace_id = f"audio-{uuid.uuid4().hex[:12]}"
    cache_enabled = True
    cache_key = _youtube_search_cache_key(query, resolved_metadata, query_variants)
    if cache_enabled:
        try:
            cached = get_search_cache(
                cache_key,
                provider="youtube",
                cache_root=cache_root,
            )
        except (OSError, sqlite3.Error):
            cached = None
        if cached is not None:
            hydrated: list[dict[str, Any]] = []
            for candidate in cached:
                if not isinstance(candidate, dict):
                    continue
                item = dict(candidate)
                cached_audio = _cached_audio_item(
                    str(item.get("cache_id") or ""),
                    cache_root=cache_root,
                    target_identity=item.get("target_identity"),
                    query=str(item.get("query") or query),
                    playback_metadata=resolved_metadata,
                )
                item["cached"] = cached_audio is not None
                if cached_audio:
                    item["audio_path"] = cached_audio.get("audio_path")
                    item["audio_ext"] = cached_audio.get("audio_ext")
                hydrated.append(item)
            _record_audio_event_safe(
                trace_id=trace_id,
                provider="youtube",
                phase="search",
                status="cache_hit",
                cache_root=cache_root,
                cache_hit=True,
                candidate_count=len(hydrated),
            )
            return IdentityCandidateList(hydrated)

    def uncached_search() -> list[dict[str, Any]]:
        search_started = time.monotonic()
        deadline = search_started + YOUTUBE_SEARCH_OPERATION_TIMEOUT_SECONDS
        _record_audio_event_safe(
            trace_id=trace_id,
            provider="youtube",
            phase="search",
            status="started",
            cache_root=cache_root,
            cache_hit=False,
        )
        try:
            result = _search_youtube_songs_uncached(
                query,
                limit=limit,
                cache_root=cache_root,
                playback_metadata=resolved_metadata,
                deadline=deadline,
            )
        except AudioIdentityMismatch:
            _record_audio_event_safe(
                trace_id=trace_id,
                provider="youtube",
                phase="search",
                status="identity_mismatch",
                cache_root=cache_root,
                elapsed_ms=round((time.monotonic() - search_started) * 1000),
            )
            if cache_enabled:
                try:
                    put_search_cache(
                        cache_key,
                        [],
                        provider="youtube",
                        cache_root=cache_root,
                    )
                except (OSError, sqlite3.Error):
                    pass
            raise
        except RuntimeError as exc:
            _record_audio_event_safe(
                trace_id=trace_id,
                provider="youtube",
                phase="search",
                status="empty" if str(exc) == "No valid matches found." else "error",
                cache_root=cache_root,
                elapsed_ms=round((time.monotonic() - search_started) * 1000),
            )
            if cache_enabled and str(exc) == "No valid matches found.":
                try:
                    put_search_cache(
                        cache_key,
                        [],
                        provider="youtube",
                        cache_root=cache_root,
                    )
                except (OSError, sqlite3.Error):
                    pass
            raise
        if cache_enabled:
            try:
                put_search_cache(
                    cache_key,
                    [dict(candidate) for candidate in result],
                    provider="youtube",
                    cache_root=cache_root,
                )
            except (OSError, sqlite3.Error):
                pass
        _record_audio_event_safe(
            trace_id=trace_id,
            provider="youtube",
            phase="search",
            status="success",
            cache_root=cache_root,
            elapsed_ms=round((time.monotonic() - search_started) * 1000),
            candidate_count=len(result),
        )
        return result

    if not cache_enabled:
        return uncached_search()
    return IdentityCandidateList(
        _coalesced_youtube_search(cache_key, uncached_search)
    )


def _downloaded_filepath(info: dict[str, Any], fallback: Path) -> Path:
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
    trace_id = str(candidate.get("search_trace_id") or f"audio-{uuid.uuid4().hex[:12]}")
    cache_id = _text(candidate.get("cache_id")) or _youtube_cache_id(candidate)
    cached = _cached_audio_item(
        cache_id,
        cache_root=cache_root,
        target_identity=candidate.get("target_identity"),
        query=str(candidate.get("query") or ""),
        playback_metadata=candidate,
    )
    if cached:
        _record_audio_event_safe(
            trace_id=trace_id,
            provider="youtube",
            phase="download",
            status="cache_hit",
            cache_root=cache_root,
            cache_hit=True,
        )
        return {**cached, "youtube_runtime_id": "", "youtube_runtime_verified": False}

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
    _record_audio_event_safe(
        trace_id=trace_id,
        provider="youtube",
        phase="download",
        status="started",
        cache_root=cache_root,
        cache_hit=False,
    )
    info = _extract_ytdlp_info(
        operation="download",
        target=webpage_url,
        options=options,
        timeout_seconds=YOUTUBE_DOWNLOAD_OPERATION_TIMEOUT_SECONDS,
    )
    if not isinstance(info, dict):
        raise RuntimeError("Invalid response returned.")
    if "formats" in info:
        _audio_stream_url(info)

    canonical_metadata = _canonical_metadata(candidate)
    canonical_track = canonical_track_from_metadata(canonical_metadata)
    target_identity = candidate.get("target_identity")
    if (
        (not canonical_track.title or not canonical_track.artist)
        and isinstance(target_identity, dict)
        and _complete_identity(target_identity)
    ):
        canonical_metadata = {
            "metadata_source": "user_verified_candidate",
            "name": target_identity.get("title"),
            "title": target_identity.get("title"),
            "artist": target_identity.get("artist"),
            "album": target_identity.get("album"),
            "original_query": candidate.get("original_query") or candidate.get("query"),
            "youtube_query": candidate.get("youtube_query") or candidate.get("query"),
        }
    merged = {**candidate, **info}
    for cover_key in ("official_album_cover_url", "provider_album_cover_url"):
        if candidate.get(cover_key):
            merged[cover_key] = candidate[cover_key]
    merged["webpage_url"] = _webpage_url(merged) or webpage_url
    identity_source = dict(merged)
    for key in ("artist", "artists", "creator", "creators"):
        if key not in info:
            identity_source.pop(key, None)
    audio_path = _downloaded_filepath(merged, audio_dir / f"{cache_id}.webm")
    audio_ext = audio_path.suffix.lstrip(".") or _text(merged.get("ext")) or "webm"
    item = {
        **_merge_canonical_metadata(
            _normalize_youtube_info(
                str(candidate.get("query") or merged.get("query") or merged.get("title") or ""),
                identity_source,
                str(audio_path),
                canonical_metadata,
            ),
            canonical_metadata,
        ),
        "cache_id": cache_id,
        "youtube_id": _text(merged.get("youtube_id") or merged.get("id")),
        "audio_path": str(audio_path),
        "audio_ext": audio_ext,
        "stream_url": str(audio_path),
        "cached": True,
        "media": {
            "kind": _media_kind(info),
            "playable": True,
        },
        "media_fingerprint": _media_fingerprint(info),
        "youtube_runtime_id": str((active_manifest() or {}).get("runtime_id") or ""),
        "youtube_runtime_verified": True,
    }
    if candidate.get("user_verified") is True:
        item["user_verified"] = True
        item["user_verified_at"] = candidate.get("user_verified_at")
    item["query"] = str(candidate.get("query") or item.get("query") or "")
    item["original_query"] = candidate.get("original_query") or item.get("original_query") or item["query"]
    item["youtube_query"] = candidate.get("youtube_query") or item.get("youtube_query") or item["query"]
    if item.get("identity_match_source") == "youtube_title_query" and item.get("identity_match") is True:
        item["identity_match_source"] = "youtube_title_query"
        item["query_identity_match"] = True
    elif isinstance(candidate.get("target_identity"), dict):
        identity = _evaluate_identity(
            query=item["query"],
            playback_metadata={**candidate, "original_query": item["original_query"], "youtube_query": item["youtube_query"]},
            source_identity=item.get("source_identity") or {},
            info={
                "track": (item.get("source_identity") or {}).get("title") or item.get("name") or item.get("title"),
                "artist": (item.get("source_identity") or {}).get("artist") or item.get("artist"),
                "album": (item.get("source_identity") or {}).get("album") or item.get("album"),
            },
        )
        item.update(identity)
    _validated_identity(item, downloaded_path=audio_path)
    cover = (
        None
        if item.get("cover_source_type") == "cover_art_archive"
        else cover_sources.resolve_online_cover(
            item,
            timeout_seconds=ONLINE_COVER_LOOKUP_TIMEOUT_SECONDS,
        )
    )
    if cover:
        item["album_cover_url"] = cover["cover_source"]
        item["cover_url"] = cover.get("cover_url") or cover["cover_source"]
        item["cover_source"] = cover["cover_source"]
        item["cover_source_type"] = cover["source_type"]
    upsert_cached_song(item, cache_root=cache_root)
    _record_audio_event_safe(
        trace_id=trace_id,
        provider="youtube",
        phase="download",
        status="success",
        cache_root=cache_root,
        candidate_count=1,
    )
    return item


def _extension_from_url(url: str, default: str = "mp3") -> str:
    path = urllib.parse.urlparse(url).path
    suffix = Path(path).suffix.lstrip(".").lower()
    if suffix and len(suffix) <= 5:
        return suffix
    return default


def download_open_audio_candidate(candidate: dict[str, Any], *, cache_root: Path | None = None) -> dict[str, Any]:
    provider = str(candidate.get("provider") or "online")
    if provider == "youtube":
        return download_youtube_candidate(candidate, cache_root=cache_root)
    _validated_identity(candidate)
    cache_id = _text(candidate.get("cache_id")) or _provider_cache_id(provider, _text(candidate.get("id")), _text(candidate.get("download_url")))
    cached = _cached_audio_item(
        cache_id,
        cache_root=cache_root,
        target_identity=candidate.get("target_identity"),
        query=str(candidate.get("query") or ""),
        playback_metadata=candidate,
    )
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
    with proxy_urlopen(request, timeout=30) as response, audio_path.open("wb") as output:
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
    _validated_identity(item, downloaded_path=audio_path)
    upsert_cached_song(item, cache_root=cache_root)
    return item


def play_online_audio_candidate(
    candidate: dict[str, Any],
    *,
    player: str = "auto",
    cache_root: Path | None = None,
) -> dict[str, Any]:
    player = resolve_local_playback_backend(player)
    provider = str(candidate.get("provider") or "online")
    if provider == "youtube":
        return play_youtube_candidate(candidate, player=player, cache_root=cache_root)
    try:
        data = download_open_audio_candidate(candidate, cache_root=cache_root)
    except Exception as exc:
        message = sanitize_message(str(exc))
        return ToolResult.fail(
            tool="play_youtube_song",
            message=message,
            error_code=(
                "ONLINE_AUDIO_IDENTITY_MISMATCH"
                if "identity does not match" in message.casefold()
                else "ONLINE_AUDIO_RESOLVE_FAILED"
            ),
            data={"query": candidate.get("query"), "player": player, "method": "online_play", "provider": provider},
        ).to_dict()

    try:
        _validated_identity(data)
    except RuntimeError as exc:
        return ToolResult.fail(
            tool="play_youtube_song",
            message=sanitize_message(str(exc)),
            error_code="ONLINE_AUDIO_IDENTITY_MISMATCH",
            data={"query": candidate.get("query"), "player": player, "method": "online_play", "provider": provider},
        ).to_dict()

    if not check_player(player):
        return ToolResult.error(
            tool="play_youtube_song",
            message=f"Player '{player}' is not ready.",
            error_code="PLAYER_MISSED",
            data={**data, "player": player, "method": "online_play"},
        )

    audio_path = str(data["audio_path"])
    data = {**data, "player": player, "method": "online_play", "source": provider}
    success_message = f"Playing '{data.get('query') or data.get('name')}' online started."
    return confirm_or_start_playback(
        tool="play_youtube_song",
        source_url=audio_path,
        source=provider,
        metadata=data,
        player=player,
        success_message=success_message,
        is_allowed=is_player_allowed,
        start=start_local_playback,
    )


def sanitize_message(message: str) -> str:
    return message.strip() or "Online audio resolve failed."


def play_youtube_candidate(
    candidate: dict[str, Any],
    *,
    player: str = "auto",
    cache_root: Path | None = None,
) -> dict[str, Any]:
    player = resolve_local_playback_backend(player)
    is_youtube_fallback = candidate.get("fallback_provider") == "youtube"
    try:
        data = download_youtube_candidate(candidate, cache_root=cache_root)
    except Exception as exc:
        message = str(exc)
        failure_code = _provider_failure_code(exc)
        if failure_code in {"provider_rate_limited", "provider_bot_challenge"}:
            _activate_youtube_search_cooldown(
                failure_class=(
                    "bot_challenge"
                    if failure_code == "provider_bot_challenge"
                    else "rate_limited"
                ),
                cache_root=cache_root,
            )
            message = "YouTube is temporarily unavailable; playback is cooling down."
            error_code = "YOUTUBE_TEMPORARILY_UNAVAILABLE"
        elif "identity does not match" in message.casefold():
            error_code = "ONLINE_AUDIO_IDENTITY_MISMATCH"
        elif _is_age_verification_error(message):
            message = AGE_RESTRICTED_MESSAGE
            error_code = "YOUTUBE_AGE_RESTRICTED"
        elif _is_unavailable_error(message):
            message = UNAVAILABLE_MESSAGE
            error_code = "YOUTUBE_UNAVAILABLE"
        else:
            managed_error = _managed_runtime_tool_error(failure_code)
            if managed_error:
                message, error_code = managed_error
            else:
                error_code = "NO_PLAYABLE_AUDIO" if "No playable audio" in message else "YOUTUBE_RESOLVE_FAILED"
        _record_audio_event_safe(
            trace_id=str(candidate.get("search_trace_id") or f"audio-{uuid.uuid4().hex[:12]}"),
            provider="youtube",
            phase="resolve",
            status="error",
            cache_root=cache_root,
            failure_class=failure_code,
        )
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

    try:
        _validated_identity(data)
    except RuntimeError as exc:
        return ToolResult.fail(
            tool="play_online_audio" if is_youtube_fallback else "play_youtube_song",
            message=str(exc),
            error_code="ONLINE_AUDIO_IDENTITY_MISMATCH",
            data={"query": candidate.get("query"), "player": player, "method": "online_play", "provider": "youtube"},
        ).to_dict()

    if not check_player(player):
        return ToolResult.error(
            tool="play_youtube_song",
            message=f"Player '{player}' is not ready.",
            error_code="PLAYER_MISSED",
            data={**data, "player": player, "method": "online_play"},
        )

    audio_path = str(data["audio_path"])
    data = {**data, "player": player, "method": "online_play", "source": "youtube"}
    success_message = f"Playing '{data.get('query') or data.get('name')}' online started."
    playback_result = confirm_or_start_playback(
        tool="play_youtube_song",
        source_url=audio_path,
        source="youtube",
        metadata=data,
        player=player,
        success_message=success_message,
        is_allowed=is_player_allowed,
        start=start_local_playback,
    )
    _record_audio_event_safe(
        trace_id=str(candidate.get("search_trace_id") or f"audio-{uuid.uuid4().hex[:12]}"),
        provider="youtube",
        phase="player_start",
        status=str(playback_result.get("status") or "unknown"),
        cache_root=cache_root,
        started=playback_result.get("status") == "success",
    )
    return playback_result


def resolve_youtube_song(query: str) -> dict[str, Any]:
    options = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
    }

    payload = _extract_ytdlp_info(
        operation="search",
        target=f"ytsearch1:{query}",
        options=options,
        timeout_seconds=YOUTUBE_SEARCH_OPERATION_TIMEOUT_SECONDS,
    )

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
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "format": "bestaudio/best",
        "skip_download": True,
    }

    info = _extract_ytdlp_info(
        operation="resolve",
        target=webpage_url,
        options=stream_opts,
        timeout_seconds=YOUTUBE_RESOLVE_OPERATION_TIMEOUT_SECONDS,
    )
    if not isinstance(info, dict):
        raise RuntimeError("Invalid response returned.")

    merged_info = {**first_entry, **info}
    merged_info["webpage_url"] = _webpage_url(merged_info) or webpage_url
    stream_url = _audio_stream_url(merged_info)
    return _normalize_youtube_info(query, merged_info, stream_url)


def search_and_resolve_song(query: str) -> str:
    candidate = search_youtube_songs(query, limit=1)[0]
    if _candidate_confidence(candidate) != "high":
        raise RuntimeError("Online audio candidate requires user confirmation.")
    return str(download_youtube_candidate(candidate)["stream_url"])


def _candidate_confidence(candidate: dict[str, Any]) -> str:
    assessment = candidate.get("assessment")
    if not isinstance(assessment, dict):
        return "high"
    confidence = str(assessment.get("confidence") or "low")
    return confidence if confidence in {"high", "medium", "low"} else "low"


def _play_automatic_candidates(
    candidates: list[dict[str, Any]],
    play_candidate: Callable[[dict[str, Any]], dict[str, Any]],
) -> dict[str, Any] | None:
    retryable_error_codes = {
        "ONLINE_AUDIO_IDENTITY_MISMATCH",
        "ONLINE_AUDIO_RESOLVE_FAILED",
        "YOUTUBE_AGE_RESTRICTED",
        "YOUTUBE_UNAVAILABLE",
        "YOUTUBE_RESOLVE_FAILED",
        "NO_PLAYABLE_AUDIO",
    }
    result: dict[str, Any] | None = None
    for candidate in candidates[:MAX_AUTOMATIC_PLAY_ATTEMPTS]:
        result = play_candidate(candidate)
        error_code = str(result.get("error_code") or "")
        if not error_code:
            return result

        message = str(result.get("message") or "")
        provider_failure = _provider_failure_code(RuntimeError(message))
        provider = str(candidate.get("provider") or "")
        if (
            error_code == "YOUTUBE_TEMPORARILY_UNAVAILABLE"
            or provider_failure in {"provider_rate_limited", "provider_bot_challenge"}
        ):
            if provider == "youtube":
                _activate_youtube_search_cooldown(
                    failure_class=(
                        "bot_challenge"
                        if provider_failure == "provider_bot_challenge"
                        else "rate_limited"
                    ),
                )
            return result
        if error_code not in retryable_error_codes:
            return result
    return result


def _review_required_result(
    *,
    tool: str,
    query: str,
    player: str,
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    return ToolResult.fail(
        tool=tool,
        message="Candidate identity needs confirmation before playback.",
        error_code="ONLINE_AUDIO_REVIEW_REQUIRED",
        data={
            "query": query,
            "player": player,
            "method": "online_play",
            "candidates": candidates,
        },
    ).to_dict()


def play_youtube_song(
    query: str,
    player: str = "auto",
    cache_root: Path | None = None,
    playback_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    player = resolve_local_playback_backend(player)
    identity_retry_limit = 5 if _complete_identity(_track_identity(playback_metadata or {})) else 1
    if online_audio_configured():
        try:
            candidates = resolve_online_audio_candidates(
                query,
                limit=identity_retry_limit,
                cache_root=cache_root,
                playback_metadata=playback_metadata,
            )
        except Exception as exc:
            data: dict[str, Any] = {
                "query": query,
                "player": player,
                "method": "online_play",
                "provider": "online_audio",
            }
            if isinstance(exc, OnlineAudioResolutionError):
                data["source_attempts"] = exc.source_attempts
                data["search_trace"] = exc.search_trace
            return ToolResult.fail(
                tool="play_online_audio",
                message=sanitize_error_message(exc),
                error_code="ONLINE_AUDIO_RESOLVE_FAILED",
                data=data,
            ).to_dict()
        automatic_candidates = [
            candidate
            for candidate in candidates
            if _candidate_confidence(candidate) == "high"
        ]
        if not automatic_candidates:
            return _review_required_result(
                tool="play_online_audio",
                query=query,
                player=player,
                candidates=candidates,
            )
        result = _play_automatic_candidates(
            automatic_candidates,
            lambda candidate: play_online_audio_candidate(
                candidate,
                player=player,
                cache_root=cache_root,
            ),
        )
        return result or ToolResult.fail(
            tool="play_online_audio",
            message="No high-confidence online audio candidate could be played.",
            error_code="ONLINE_AUDIO_RESOLVE_FAILED",
        ).to_dict()

    try:
        candidates = search_youtube_songs(
            query,
            limit=identity_retry_limit,
            cache_root=cache_root,
            playback_metadata=playback_metadata,
        )
    except Exception as exc:
        message = str(exc)
        error_code = "NO_PLAYABLE_AUDIO" if "No playable audio" in message else "YOUTUBE_RESOLVE_FAILED"
        return ToolResult.fail(
            tool="play_youtube_song",
            message=message,
            error_code=error_code,
            data={"query": query, "player": player, "method": "online_play", "provider": "youtube"},
        ).to_dict()
    automatic_candidates = [
        candidate
        for candidate in candidates
        if _candidate_confidence(candidate) == "high"
    ]
    if not automatic_candidates:
        return _review_required_result(
            tool="play_youtube_song",
            query=query,
            player=player,
            candidates=candidates,
        )
    result = _play_automatic_candidates(
        automatic_candidates,
        lambda candidate: play_youtube_candidate(
            candidate,
            player=player,
            cache_root=cache_root,
        ),
    )
    return result or ToolResult.fail(
        tool="play_youtube_song",
        message="No high-confidence YouTube candidate could be played.",
        error_code="YOUTUBE_RESOLVE_FAILED",
    ).to_dict()

registry.register(
    name="play_youtube_song",
    kind="system",
    domain="playback",
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
