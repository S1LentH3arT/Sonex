"""Online play support for tool implementations used by the planner and playback flows.

Implements the online_play module responsibilities used by Sonex runtime flows.
Key public entry points include OnlineAudioSetupRequired, OnlineAudioConfig, online_audio_config, os_value, online_audio_configured.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
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
from src.tools.music_matching import (
    AliasResolver,
    MatchDecision,
    audio_result_from_candidate,
    canonical_track_from_metadata,
    score_audio_match,
)

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
IGNORABLE_TITLE_SUFFIX_RE = re.compile(
    r"(?:\s*[\[(\-{]\s*)?(?:official(?:\s+(?:audio|music\s+video|video|mv))?|"
    r"lyrics?|lyric\s+video|(?:\d{4}\s+)?remaster(?:ed)?(?:\s+\d{4})?)(?:\s*[])}]\s*)?$",
    re.IGNORECASE,
)
FEATURED_ARTIST_RE = re.compile(r"\s+(?:feat\.?|ft\.?|featuring)\s+.*$", re.IGNORECASE)
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


class AudioIdentityMismatch(RuntimeError):
    def __init__(self, provider: str, rejected_count: int) -> None:
        self.provider = provider
        self.rejected_count = max(1, int(rejected_count or 1))
        super().__init__(
            f"{_provider_label(provider)} rejected {self.rejected_count} "
            f"identity mismatch{'es' if self.rejected_count != 1 else ''}."
        )


class IdentityCandidateList(list[dict[str, Any]]):
    def __init__(self, values: list[dict[str, Any]], *, rejected_count: int = 0) -> None:
        super().__init__(values)
        self.rejected_count = max(0, int(rejected_count or 0))


@dataclass(frozen=True, slots=True)
class OnlineAudioConfig:
    """Represents online audio config.

    Encapsulates online audio config data and behavior used by Sonex runtime flows.
    """
    jamendo_client_id: str | None = None
    audius_api_key: str | None = None


@dataclass(frozen=True, slots=True)
class IdentityContext:
    provider_identity: dict[str, Any]
    original_query: str
    provider_query: str
    language_conflict: bool


def _song_cache_root(cache_root: Path | None = None) -> Path:
    """Prepares song cache root for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs song cache root without duplicating the local rules.

    Example: _song_cache_root(cache_root=...) -> returns the value used by the surrounding Sonex flow.
    """
    return cache_root or sonex_home() / "cache" / "songs"


def _audio_cache_dir(cache_root: Path | None = None) -> Path:
    """Prepares audio cache dir for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs audio cache dir without duplicating the local rules.

    Example: _audio_cache_dir(cache_root=...) -> returns the value used by the surrounding Sonex flow.
    """
    return _song_cache_root(cache_root) / "audio"


def online_audio_config() -> OnlineAudioConfig:
    """Coordinates online audio config for the current Sonex flow.

    Typical use: Use this function when runtime code needs online audio config as part of a Sonex command, playback, auth, llm, or ui path.

    Example: online_audio_config() -> returns the value used by the surrounding Sonex flow.
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
    """Coordinates os value for the current Sonex flow.

    Typical use: Use this function when runtime code needs os value as part of a Sonex command, playback, auth, llm, or ui path.

    Example: os_value("SONEX_PROVIDER") -> "openai" when that environment variable is set.
    """
    import os

    return os.environ.get(name)


def online_audio_configured(config: OnlineAudioConfig | None = None) -> bool:
    """Coordinates online audio configured for the current Sonex flow.

    Typical use: Use this function when runtime code needs online audio configured as part of a Sonex command, playback, auth, llm, or ui path.

    Example: online_audio_configured(OnlineAudioConfig(jamendo_client_id="id")) -> True.
    """
    resolved = config or online_audio_config()
    return bool(resolved.jamendo_client_id or resolved.audius_api_key)


def _text(value: Any) -> str | None:
    """Prepares text for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs text without duplicating the local rules.

    Example: _text("  song  ") -> "song"; _text("") -> None.
    """
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _joined_text(value: Any) -> str | None:
    """Prepares joined text for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs joined text without duplicating the local rules.

    Example: _joined_text(value=...) -> returns the value used by the surrounding Sonex flow.
    """
    if isinstance(value, list):
        parts = [_text(item) for item in value]
        return ", ".join(part for part in parts if part) or None
    return _text(value)


def _non_placeholder_text(value: Any) -> str | None:
    """Prepares non placeholder text for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs non placeholder text without duplicating the local rules.

    Example: _non_placeholder_text(value=...) -> returns the value used by the surrounding Sonex flow.
    """
    text = _joined_text(value)
    if text in {None, "-"}:
        return None
    return text


def _spotify_tracks_from_result(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Prepares spotify tracks from result for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs spotify tracks from result without duplicating the local rules.

    Example: _spotify_tracks_from_result(result=...) -> returns the value used by the surrounding Sonex flow.
    """
    if str(result.get("status") or "").lower() != "success":
        return []
    data = result.get("data")
    tracks = data.get("tracks") if isinstance(data, dict) else None
    if not isinstance(tracks, list) or not tracks:
        return []
    return [track for track in tracks if isinstance(track, dict)]


def _spotify_track_metadata(query: str, track: dict[str, Any]) -> dict[str, Any] | None:
    """Prepares spotify track metadata for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs spotify track metadata without duplicating the local rules.

    Example: _spotify_track_metadata(query=..., track=...) -> returns the value used by the surrounding Sonex flow.
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


def search_spotify_track_candidates(
    query: str,
    limit: int = 5,
    *,
    query_variants: tuple[str, ...] | list[str] | None = None,
) -> list[dict[str, Any]]:
    """Coordinates search spotify track candidates for the current Sonex flow.

    Typical use: Use this function when runtime code needs search spotify track candidates as part of a Sonex command, playback, auth, llm, or ui path.

    Example: search_spotify_track_candidates(query=..., limit=...) -> returns the value used by the surrounding Sonex flow.
    """
    clean_query = query.strip()
    if not clean_query:
        return []
    bounded_limit = max(1, min(10, int(limit or 5)))
    search_queries: list[str] = []
    for candidate in query_variants or (clean_query,):
        clean_candidate = str(candidate or "").strip()
        if clean_candidate and clean_candidate not in search_queries:
            search_queries.append(clean_candidate)
        if len(search_queries) >= 5:
            break
    candidates: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for search_query in search_queries:
        try:
            result = spotify_play.spotify_search(query=search_query, limit=bounded_limit, types="track")
        except Exception:
            continue
        if not isinstance(result, dict):
            continue
        for track in _spotify_tracks_from_result(result):
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
        if len(candidates) >= bounded_limit:
            break
    return candidates


def _query_fallback_metadata(query: str) -> dict[str, Any]:
    """Prepares query fallback metadata for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs query fallback metadata without duplicating the local rules.

    Example: _query_fallback_metadata(query=...) -> returns the value used by the surrounding Sonex flow.
    """
    clean_query = query.strip()
    return {
        "metadata_source": "query_fallback",
        "original_query": clean_query,
        "youtube_query": clean_query,
    }


def _resolved_playback_metadata(query: str, playback_metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    """Prepares resolved playback metadata for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs resolved playback metadata without duplicating the local rules.

    Example: _resolved_playback_metadata(query=..., playback_metadata=...) -> returns the value used by the surrounding Sonex flow.
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
    """Resolves online playback metadata from available runtime state.

    Typical use: Use this function when runtime code needs resolve online playback metadata as part of a Sonex command, playback, auth, llm, or ui path.

    Example: resolve_online_playback_metadata(query=..., playback_metadata=...) -> returns the value used by the surrounding Sonex flow.
    """
    return _resolved_playback_metadata(query, playback_metadata)


def _canonical_metadata(item: dict[str, Any]) -> dict[str, Any]:
    """Prepares canonical metadata for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs canonical metadata without duplicating the local rules.

    Example: _canonical_metadata(item=...) -> returns the value used by the surrounding Sonex flow.
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


def _identity_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    text = "".join(character if character.isalnum() else " " for character in text)
    return " ".join(text.split())


def _has_cjk(value: Any) -> bool:
    return any("\u4e00" <= character <= "\u9fff" for character in str(value or ""))


def _latin_ratio(value: Any) -> float:
    letters = [character for character in str(value or "") if character.isalpha()]
    if not letters:
        return 0.0
    latin = [
        character for character in letters
        if "LATIN" in unicodedata.name(character, "")
    ]
    return len(latin) / len(letters)


def _mostly_latin(value: Any) -> bool:
    return _latin_ratio(value) >= 0.7


def _identity_title(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    previous = None
    while text and text != previous:
        previous = text
        text = IGNORABLE_TITLE_SUFFIX_RE.sub("", text).strip()
    return _identity_text(text)


def _identity_title_text(identity: dict[str, Any]) -> str:
    title = unicodedata.normalize("NFKC", str(identity.get("title") or "")).strip()
    artist = unicodedata.normalize("NFKC", str(identity.get("artist") or "")).strip()
    if artist:
        title = re.sub(
            rf"^\s*{re.escape(artist)}\s*[-–—:|]\s*",
            "",
            title,
            count=1,
            flags=re.IGNORECASE,
        )
    return _identity_title(title)


def _identity_artist(item: dict[str, Any]) -> str:
    artists = item.get("artists")
    if isinstance(artists, list) and artists:
        primary = _non_placeholder_text(artists[0])
        if primary:
            return primary
    artist = _non_placeholder_text(item.get("artist")) or ""
    return FEATURED_ARTIST_RE.sub("", artist).strip()


def _identity_artist_text(value: Any) -> str:
    return _identity_text(FEATURED_ARTIST_RE.sub("", str(value or "")).strip())


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
    return (
        _identity_title_text(target) == _identity_title_text(source)
        and _identity_artist_text(target.get("artist")) == _identity_artist_text(source.get("artist"))
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


def _validated_identity(item: dict[str, Any], *, downloaded_path: Path | None = None) -> dict[str, Any]:
    target = item.get("target_identity")
    source = item.get("source_identity")
    matches = bool(
        _identity_matches(target, source)
        or item.get("query_identity_match") is True
        or item.get("identity_match_source") == "original_query"
    )
    item["identity_match"] = matches
    if matches:
        return item
    if downloaded_path is not None:
        try:
            downloaded_path.unlink()
        except FileNotFoundError:
            pass
    raise RuntimeError("Downloaded audio identity does not match the selected track.")


def _merge_canonical_metadata(item: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    """Prepares merge canonical metadata for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs merge canonical metadata without duplicating the local rules.

    Example: _merge_canonical_metadata(item=..., metadata=...) -> returns the value used by the surrounding Sonex flow.
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
    """Prepares duration ms for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs duration ms without duplicating the local rules.

    Example: _duration_ms(value=...) -> returns the value used by the surrounding Sonex flow.
    """
    try:
        return max(0, int(float(value or 0) * 1000))
    except (TypeError, ValueError):
        return 0


def _count(value: Any) -> int:
    """Prepares count for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs count without duplicating the local rules.

    Example: _count(value=...) -> returns the value used by the surrounding Sonex flow.
    """
    try:
        return max(0, int(float(value or 0)))
    except (TypeError, ValueError):
        return 0


def _words(value: str) -> list[str]:
    """Prepares words for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs words without duplicating the local rules.

    Example: _words(value=...) -> returns the value used by the surrounding Sonex flow.
    """
    return re.findall(r"[\w\u4e00-\u9fff]+", value.casefold())


def _normalized_rank_text(value: str) -> str:
    """Prepares normalized rank text for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs normalized rank text without duplicating the local rules.

    Example: _normalized_rank_text(value=...) -> returns the value used by the surrounding Sonex flow.
    """
    return " ".join(_words(value))


def _query_terms(query: str) -> list[str]:
    """Prepares query terms for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs query terms without duplicating the local rules.

    Example: _query_terms(query=...) -> returns the value used by the surrounding Sonex flow.
    """
    terms = _words(query)
    return [term for term in terms if term not in QUERY_FILLER_TERMS and term not in LIVE_TERMS]


def _contains_any(value: str, terms: tuple[str, ...]) -> bool:
    """Prepares contains any for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs contains any without duplicating the local rules.

    Example: _contains_any(value=..., terms=...) -> returns the value used by the surrounding Sonex flow.
    """
    text = value.casefold()
    return any(term in text for term in terms)


def _variant_type(query: str, info: dict[str, Any]) -> str:
    """Prepares variant type for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs variant type without duplicating the local rules.

    Example: _variant_type(query=..., info=...) -> returns the value used by the surrounding Sonex flow.
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
    """Prepares rank title for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs rank title without duplicating the local rules.

    Example: _rank_title(info=...) -> returns the value used by the surrounding Sonex flow.
    """
    return _text(info.get("track") or info.get("title") or info.get("fulltitle") or "") or ""


def _rank_channel(info: dict[str, Any]) -> str:
    """Prepares rank channel for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs rank channel without duplicating the local rules.

    Example: _rank_channel(info=...) -> returns the value used by the surrounding Sonex flow.
    """
    return _text(info.get("channel") or info.get("uploader") or "") or ""


def _rank_artist(info: dict[str, Any]) -> str:
    """Prepares rank artist for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs rank artist without duplicating the local rules.

    Example: _rank_artist(info=...) -> returns the value used by the surrounding Sonex flow.
    """
    return (
        _non_placeholder_text(info.get("artist"))
        or _non_placeholder_text(info.get("artists"))
        or _non_placeholder_text(info.get("creator"))
        or _non_placeholder_text(info.get("creators"))
        or ""
    )


def _rank_haystack(info: dict[str, Any]) -> str:
    """Prepares rank haystack for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs rank haystack without duplicating the local rules.

    Example: _rank_haystack(info=...) -> returns the value used by the surrounding Sonex flow.
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
    """Prepares similarity score for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs similarity score without duplicating the local rules.

    Example: _similarity_score(query=..., info=...) -> returns the value used by the surrounding Sonex flow.
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
    """Prepares clean title match for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs clean title match without duplicating the local rules.

    Example: _clean_title_match(query=..., info=..., similarity=...) -> returns the value used by the surrounding Sonex flow.
    """
    title = _rank_title(info)
    if similarity < 70:
        return False
    if _contains_any(title, LIVE_TERMS + LOW_RELEVANCE_TERMS + NOISY_MEDIA_TERMS):
        return False
    return " - " in title or " – " in title or " — " in title or similarity >= 86


def _quality_label(query: str, info: dict[str, Any], variant: str, similarity: int) -> str:
    """Prepares quality label for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs quality label without duplicating the local rules.

    Example: _quality_label(query=..., info=..., variant=..., similarity=...) -> returns the value used by the surrounding Sonex flow.
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
    """Prepares provider cache id for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs provider cache id without duplicating the local rules.

    Example: _provider_cache_id(provider=..., provider_id=..., source_url=...) -> returns the value used by the surrounding Sonex flow.
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
    """Prepares open audio candidate for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs open audio candidate without duplicating the local rules.

    Example: _open_audio_candidate(provider=..., provider_id=..., query=..., name=..., artist=..., album=..., duration_ms=..., cover_url=..., source_url=..., download_url=..., webpage_url=..., playback_metadata=..., extra_metadata=...) -> returns the value used by the surrounding Sonex flow.
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
    return _merge_canonical_metadata(candidate, metadata)


def normalize_jamendo_track(
    track: dict[str, Any],
    *,
    query: str,
    playback_metadata: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Coordinates normalize jamendo track for the current Sonex flow.

    Typical use: Use this function when runtime code needs normalize jamendo track as part of a Sonex command, playback, auth, llm, or ui path.

    Example: normalize_jamendo_track(track=..., query=..., playback_metadata=...) -> returns the value used by the surrounding Sonex flow.
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
    """Prepares best audius artwork for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs best audius artwork without duplicating the local rules.

    Example: _best_audius_artwork(track=...) -> returns the value used by the surrounding Sonex flow.
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
    """Prepares audius username for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs audius username without duplicating the local rules.

    Example: _audius_user_name(track=...) -> returns the value used by the surrounding Sonex flow.
    """
    user = track.get("user")
    if isinstance(user, dict):
        return _text(user.get("name") or user.get("handle"))
    return None


def _is_audius_stream_gated(track: dict[str, Any]) -> bool:
    """Prepares is audius stream gated for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs is audius stream gated without duplicating the local rules.

    Example: _is_audius_stream_gated(track=...) -> returns the value used by the surrounding Sonex flow.
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
    """Coordinates normalize audius track for the current Sonex flow.

    Typical use: Use this function when runtime code needs normalize audius track as part of a Sonex command, playback, auth, llm, or ui path.

    Example: normalize_audius_track(track=..., query=..., stream_url=..., playback_metadata=...) -> returns the value used by the surrounding Sonex flow.
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
    """Prepares popularity tiebreaker for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs popularity tiebreaker without duplicating the local rules.

    Example: _popularity_tiebreaker(popularity=...) -> returns the value used by the surrounding Sonex flow.
    """
    return round(math.log10(max(0, popularity) + 1) * 1000)


def _relevance_score(query: str, info: dict[str, Any]) -> int:
    """Prepares relevance score for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs relevance score without duplicating the local rules.

    Example: _relevance_score(query=..., info=...) -> returns the value used by the surrounding Sonex flow.
    """
    terms = _query_terms(query)
    if not terms:
        return 0
    haystack = _rank_haystack(info).casefold()
    return sum(1 for term in terms if term in haystack)


def _popularity_score(info: dict[str, Any]) -> int:
    """Prepares popularity score for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs popularity score without duplicating the local rules.

    Example: _popularity_score(info=...) -> returns the value used by the surrounding Sonex flow.
    """
    view_count = _count(info.get("view_count"))
    like_count = _count(info.get("like_count"))
    comment_count = _count(info.get("comment_count"))
    repost_count = _count(info.get("repost_count"))
    return view_count + like_count * 20 + comment_count * 5 + repost_count * 10


def _rank_reason(variant: str, popularity: int, relevance: int, similarity: int, quality: str) -> str:
    """Prepares rank reason for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs rank reason without duplicating the local rules.

    Example: _rank_reason(variant=..., popularity=..., relevance=..., similarity=..., quality=...) -> returns the value used by the surrounding Sonex flow.
    """
    label = {
        "official_original": "official original",
        "live": "live version",
        "other": "other match",
    }.get(variant, "other match")
    return f"{label}; quality={quality}; similarity={similarity}; popularity={popularity}; relevance={relevance}"


def _is_age_restricted_info(info: dict[str, Any]) -> bool:
    """Prepares is age restricted info for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs is age restricted info without duplicating the local rules.

    Example: _is_age_restricted_info(info=...) -> returns the value used by the surrounding Sonex flow.
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
    """Prepares is unavailable info for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs is unavailable info without duplicating the local rules.

    Example: _is_unavailable_info(info=...) -> returns the value used by the surrounding Sonex flow.
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
    """Prepares is age verification error for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs is age verification error without duplicating the local rules.

    Example: _is_age_verification_error(message=...) -> returns the value used by the surrounding Sonex flow.
    """
    text = message.casefold()
    return (
        "confirm your age" in text
        or "age verification" in text
        or "may be inappropriate for some users" in text
    )


def _is_unavailable_error(message: str) -> bool:
    """Prepares is unavailable error for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs is unavailable error without duplicating the local rules.

    Example: _is_unavailable_error(message=...) -> returns the value used by the surrounding Sonex flow.
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
    """Prepares should keep candidate for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs should keep candidate without duplicating the local rules.

    Example: _should_keep_candidate(query=..., info=...) -> returns the value used by the surrounding Sonex flow.
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
    """Prepares best thumbnail for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs best thumbnail without duplicating the local rules.

    Example: _best_thumbnail(info=...) -> returns the value used by the surrounding Sonex flow.
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
    """Prepares audio stream url for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs audio stream url without duplicating the local rules.

    Example: _audio_stream_url(info=...) -> returns the value used by the surrounding Sonex flow.
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
    """Prepares webpage url for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs webpage url without duplicating the local rules.

    Example: _webpage_url(info=...) -> returns the value used by the surrounding Sonex flow.
    """
    url = _text(info.get("webpage_url") or info.get("original_url"))
    if url:
        return url
    video_id = _text(info.get("id"))
    if video_id:
        return f"https://www.youtube.com/watch?v={video_id}"
    return None


def _youtube_cache_id(info: dict[str, Any]) -> str:
    """Prepares youtube cache id for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs youtube cache id without duplicating the local rules.

    Example: _youtube_cache_id(info=...) -> returns the value used by the surrounding Sonex flow.
    """
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
    """Prepares cached audio item for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs cached audio item without duplicating the local rules.

    Example: _cached_audio_item(cache_id=..., cache_root=...) -> returns the value used by the surrounding Sonex flow.
    """
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
    """Prepares normalize youtube info for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs normalize youtube info without duplicating the local rules.

    Example: _normalize_youtube_info(query=..., info=..., stream_url=...) -> returns the value used by the surrounding Sonex flow.
    """
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
    return candidate


def _rank_youtube_candidates(query: str, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Prepares rank youtube candidates for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs rank youtube candidates without duplicating the local rules.

    Example: _rank_youtube_candidates(query=..., candidates=...) -> returns the value used by the surrounding Sonex flow.
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
        """Coordinates score for the current Sonex flow.

        Typical use: Use this function when runtime code needs score as part of a Sonex command, playback, auth, llm, or ui path.

        Example: score(pair=...) -> returns the value used by the surrounding Sonex flow.
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
    """Coordinates rank online audio candidates for the current Sonex flow.

    Typical use: Use this function when runtime code needs rank online audio candidates as part of a Sonex command, playback, auth, llm, or ui path.

    Example: rank_online_audio_candidates(query=..., candidates=...) -> returns the value used by the surrounding Sonex flow.
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
        """Coordinates score for the current Sonex flow.

        Typical use: Use this function when runtime code needs score as part of a Sonex command, playback, auth, llm, or ui path.

        Example: score(pair=...) -> returns the value used by the surrounding Sonex flow.
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
    """Prepares credible online audio candidates for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs credible online audio candidates without duplicating the local rules.

    Example: _credible_online_audio_candidates(candidates=...) -> returns the value used by the surrounding Sonex flow.
    """
    credible: list[dict[str, Any]] = []
    for candidate in candidates:
        match_score = candidate.get("match_score")
        if isinstance(match_score, dict) and match_score.get("decision") != MatchDecision.ACCEPT.value:
            continue
        if int(candidate.get("similarity_score") or 0) >= 45:
            credible.append(candidate)
    return credible


def _provider_label(provider: str) -> str:
    """Prepares provider label for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs provider label without duplicating the local rules.

    Example: _provider_label(provider=...) -> returns the value used by the surrounding Sonex flow.
    """
    return {"jamendo": "Jamendo", "audius": "Audius", "youtube": "YouTube"}.get(provider, provider.title())


def _sanitize_provider_error(error: Any) -> str:
    """Prepares sanitize provider error for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs sanitize provider error without duplicating the local rules.

    Example: _sanitize_provider_error(error=...) -> returns the value used by the surrounding Sonex flow.
    """
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
    """Prepares source attempt for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs source attempt without duplicating the local rules.

    Example: _source_attempt(provider=..., status=..., candidate_count=..., credible_count=..., message=...) -> returns the value used by the surrounding Sonex flow.
    """
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
    """Prepares fallback reason for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs fallback reason without duplicating the local rules.

    Example: _fallback_reason(source_attempts=...) -> returns the value used by the surrounding Sonex flow.
    """
    messages = [str(item.get("message") or "").strip() for item in source_attempts if item.get("message")]
    return " ".join(messages) or "Configured open-audio providers returned no credible matches."


def _friendly_youtube_failure_message(message: str) -> str:
    """Prepares friendly youtube failure message for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs friendly youtube failure message without duplicating the local rules.

    Example: _friendly_youtube_failure_message(message=...) -> returns the value used by the surrounding Sonex flow.
    """
    if _is_age_verification_error(message):
        return AGE_RESTRICTED_MESSAGE
    if _is_unavailable_error(message):
        return UNAVAILABLE_MESSAGE
    return sanitize_error_message(message)


def _with_youtube_fallback_trace(candidate: dict[str, Any], source_attempts: list[dict[str, Any]]) -> dict[str, Any]:
    """Prepares with youtube fallback trace for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs with youtube fallback trace without duplicating the local rules.

    Example: _with_youtube_fallback_trace(candidate=..., source_attempts=...) -> returns the value used by the surrounding Sonex flow.
    """
    traced = dict(candidate)
    reason = _fallback_reason(source_attempts)
    traced["fallback_provider"] = "youtube"
    traced["fallback_reason"] = reason
    traced["source_attempts"] = [dict(item) for item in source_attempts]
    return traced


def _format_youtube_fallback_failure(candidate: dict[str, Any], youtube_message: str) -> str:
    """Prepares format youtube fallback failure for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs format youtube fallback failure without duplicating the local rules.

    Example: _format_youtube_fallback_failure(candidate=..., youtube_message=...) -> returns the value used by the surrounding Sonex flow.
    """
    reason = str(candidate.get("fallback_reason") or _fallback_reason(candidate.get("source_attempts") or [])).strip()
    if reason:
        return f"{reason} Sonex fell back to YouTube. YouTube failed: {sanitize_error_message(youtube_message)}"
    return f"Sonex fell back to YouTube. YouTube failed: {sanitize_error_message(youtube_message)}"


def _json_get(url: str, *, headers: dict[str, str] | None = None, timeout: float = 10.0) -> dict[str, Any]:
    """Prepares json get for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs json get without duplicating the local rules.

    Example: _json_get(url=..., headers=..., timeout=...) -> returns the value used by the surrounding Sonex flow.
    """
    request = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(request, timeout=timeout) as response:
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


def _audio_query_variants(query: str, playback_metadata: dict[str, Any] | None = None) -> list[tuple[str, str]]:
    context = _identity_context(query, playback_metadata)
    variants = [("provider_metadata", context.provider_query)]
    if context.language_conflict and context.original_query and context.original_query != context.provider_query:
        variants.append(("original_query", context.original_query))
    return variants


def search_jamendo_audio_candidates(
    query: str,
    *,
    client_id: str,
    limit: int = 5,
    playback_metadata: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Coordinates search jamendo audio candidates for the current Sonex flow.

    Typical use: Use this function when runtime code needs search jamendo audio candidates as part of a Sonex command, playback, auth, llm, or ui path.

    Example: search_jamendo_audio_candidates(query=..., client_id=..., limit=..., playback_metadata=...) -> returns the value used by the surrounding Sonex flow.
    """
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
        for variant, variant_query in _audio_query_variants(query, playback_metadata):
            if variant == "original_query":
                query_stages.append(({**base_params, "search": variant_query}, variant_query))
    else:
        query_stages = [({**base_params, "search": query}, query)]

    candidates: list[dict[str, Any]] = []
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
        rejected_count += sum(candidate.get("identity_match") is False for candidate in normalized)
        candidates = [candidate for candidate in normalized if candidate.get("identity_match") is not False]
        if candidates or not (artist and title):
            break
    ranked = rank_online_audio_candidates(query, candidates)[: max(1, min(10, int(limit or 5)))]
    return IdentityCandidateList(ranked, rejected_count=rejected_count)


def _audius_stream_url(track_id: str) -> str:
    """Prepares audius stream url for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs audius stream url without duplicating the local rules.

    Example: _audius_stream_url(track_id=...) -> returns the value used by the surrounding Sonex flow.
    """
    return f"https://discoveryprovider.audius.co/v1/tracks/{urllib.parse.quote(track_id)}/stream?app_name=Sonex"


def search_audius_audio_candidates(
    query: str,
    *,
    api_key: str,
    limit: int = 5,
    playback_metadata: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Coordinates search audius audio candidates for the current Sonex flow.

    Typical use: Use this function when runtime code needs search audius audio candidates as part of a Sonex command, playback, auth, llm, or ui path.

    Example: search_audius_audio_candidates(query=..., api_key=..., limit=..., playback_metadata=...) -> returns the value used by the surrounding Sonex flow.
    """
    artist, title, album = _playback_search_fields(playback_metadata)

    search_queries: list[str]
    if artist and title:
        search_query = f"{artist} {title}"
        if album:
            search_query = f"{artist} {title} {album}"
        search_queries = [search_query]
        for variant, variant_query in _audio_query_variants(query, playback_metadata):
            if variant == "original_query":
                search_queries.append(variant_query)
    else:
        search_queries = [query]

    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    candidates = []
    for search_query in search_queries:
        params = urllib.parse.urlencode(
            {
                "query": search_query,
                "limit": max(1, min(20, int(limit or 5))),
                "app_name": "Sonex",
            }
        )
        payload = _json_get(f"https://discoveryprovider.audius.co/v1/tracks/search?{params}", headers=headers)
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
                stream_url=_audius_stream_url(track_id),
                playback_metadata=playback_metadata,
            )
            if candidate:
                candidates.append(candidate)
    rejected_count = sum(candidate.get("identity_match") is False for candidate in candidates)
    candidates = [candidate for candidate in candidates if candidate.get("identity_match") is not False]
    ranked = rank_online_audio_candidates(query, candidates)[: max(1, min(10, int(limit or 5)))]
    return IdentityCandidateList(ranked, rejected_count=rejected_count)


def resolve_online_audio_candidates(
    query: str,
    limit: int = 5,
    *,
    cache_root: Path | None = None,
    playback_metadata: dict[str, Any] | None = None,
    config: OnlineAudioConfig | None = None,
) -> list[dict[str, Any]]:
    """Resolves online audio candidates from available runtime state.

    Typical use: Use this function when runtime code needs resolve online audio candidates as part of a Sonex command, playback, auth, llm, or ui path.

    Example: resolve_online_audio_candidates(query=..., limit=..., cache_root=..., playback_metadata=..., config=...) -> returns the value used by the surrounding Sonex flow.
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
            rejected_count = int(getattr(provider_candidates, "rejected_count", 0) or 0)
            source_attempts.append(
                _source_attempt(
                    "jamendo",
                    status="success" if credible else ("identity_mismatch" if rejected_count else "no_credible_matches"),
                    candidate_count=len(provider_candidates) + rejected_count,
                    credible_count=len(credible),
                    rejected_count=rejected_count,
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
            rejected_count = int(getattr(provider_candidates, "rejected_count", 0) or 0)
            source_attempts.append(
                _source_attempt(
                    "audius",
                    status="success" if credible else ("identity_mismatch" if rejected_count else "no_credible_matches"),
                    candidate_count=len(provider_candidates) + rejected_count,
                    credible_count=len(credible),
                    rejected_count=rejected_count,
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
            youtube_candidates = search_youtube_songs(
                search_query,
                limit=limit,
                cache_root=cache_root,
                playback_metadata=resolved_metadata,
            )
            youtube_rejected = int(getattr(youtube_candidates, "rejected_count", 0) or 0)
            for candidate in youtube_candidates:
                traced = _with_youtube_fallback_trace(candidate, source_attempts)
                if youtube_rejected:
                    traced["source_attempts"].append(
                        _source_attempt(
                            "youtube",
                            status="success",
                            candidate_count=len(youtube_candidates) + youtube_rejected,
                            credible_count=len(youtube_candidates),
                            rejected_count=youtube_rejected,
                            message=(
                                f"YouTube returned {len(youtube_candidates)} identity-verified matches "
                                f"after rejecting {youtube_rejected} mismatches."
                            ),
                        )
                    )
                candidates.append(traced)
        except AudioIdentityMismatch as exc:
            source_attempts.append(
                _source_attempt(
                    exc.provider,
                    status="identity_mismatch",
                    candidate_count=exc.rejected_count,
                    rejected_count=exc.rejected_count,
                )
            )
            raise RuntimeError(_fallback_reason(source_attempts)) from exc
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
    """Coordinates search online audio candidates for the current Sonex flow.

    Typical use: Use this function when runtime code needs search online audio candidates as part of a Sonex command, playback, auth, llm, or ui path.

    Example: search_online_audio_candidates(query=..., limit=..., cache_root=..., playback_metadata=...) -> returns the value used by the surrounding Sonex flow.
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
    """Coordinates search youtube songs for the current Sonex flow.

    Typical use: Use this function when runtime code needs search youtube songs as part of a Sonex command, playback, auth, llm, or ui path.

    Example: search_youtube_songs(query=..., limit=..., cache_root=..., playback_metadata=...) -> returns the value used by the surrounding Sonex flow.
    """
    playback_metadata = resolve_online_playback_metadata(query, playback_metadata)
    query_variants = _audio_query_variants(query, playback_metadata)
    youtube_query = query_variants[0][1]
    bounded_limit = max(1, min(10, int(limit or 5)))
    search_limit = min(50, max(bounded_limit, bounded_limit * 8))
    options = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
    }

    candidates: list[dict[str, Any]] = []
    seen_cache_ids: set[str] = set()
    rejected_count = 0
    with yt_dlp.YoutubeDL(options) as ydl:
        for _, variant_query in query_variants:
            payload = ydl.extract_info(f"ytsearch{search_limit}:{variant_query}", download=False)

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
                if candidate.get("identity_match") is False:
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
    if not candidates:
        if rejected_count:
            raise AudioIdentityMismatch("youtube", rejected_count)
        raise RuntimeError("No valid matches found.")
    ranked = _rank_youtube_candidates(youtube_query, candidates)[:bounded_limit]
    return IdentityCandidateList(ranked, rejected_count=rejected_count)


def _downloaded_filepath(info: dict[str, Any], fallback: Path) -> Path:
    """Prepares downloaded filepath for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs downloaded filepath without duplicating the local rules.

    Example: _downloaded_filepath(info=..., fallback=...) -> returns the value used by the surrounding Sonex flow.
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
    """Coordinates download youtube candidate for the current Sonex flow.

    Typical use: Use this function when runtime code needs download youtube candidate as part of a Sonex command, playback, auth, llm, or ui path.

    Example: download_youtube_candidate(candidate=..., cache_root=...) -> returns the value used by the surrounding Sonex flow.
    """
    cache_id = _text(candidate.get("cache_id")) or _youtube_cache_id(candidate)
    cached = _cached_audio_item(
        cache_id,
        cache_root=cache_root,
        target_identity=candidate.get("target_identity"),
        query=str(candidate.get("query") or ""),
        playback_metadata=candidate,
    )
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
    }
    item["query"] = str(candidate.get("query") or item.get("query") or "")
    item["original_query"] = candidate.get("original_query") or item.get("original_query") or item["query"]
    item["youtube_query"] = candidate.get("youtube_query") or item.get("youtube_query") or item["query"]
    if candidate.get("identity_match_source") == "youtube_title_query" and item.get("identity_match") is True:
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
    cover = None if item.get("cover_source_type") == "cover_art_archive" else cover_sources.resolve_online_cover(item)
    if cover:
        item["album_cover_url"] = cover["cover_source"]
        item["cover_url"] = cover.get("cover_url") or cover["cover_source"]
        item["cover_source"] = cover["cover_source"]
        item["cover_source_type"] = cover["source_type"]
    upsert_cached_song(item, cache_root=cache_root)
    return item


def _extension_from_url(url: str, default: str = "mp3") -> str:
    """Prepares extension from url for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs extension from url without duplicating the local rules.

    Example: _extension_from_url(url=..., default=...) -> returns the value used by the surrounding Sonex flow.
    """
    path = urllib.parse.urlparse(url).path
    suffix = Path(path).suffix.lstrip(".").lower()
    if suffix and len(suffix) <= 5:
        return suffix
    return default


def download_open_audio_candidate(candidate: dict[str, Any], *, cache_root: Path | None = None) -> dict[str, Any]:
    """Coordinates download open audio candidate for the current Sonex flow.

    Typical use: Use this function when runtime code needs download open audio candidate as part of a Sonex command, playback, auth, llm, or ui path.

    Example: download_open_audio_candidate(candidate=..., cache_root=...) -> returns the value used by the surrounding Sonex flow.
    """
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
    _validated_identity(item, downloaded_path=audio_path)
    upsert_cached_song(item, cache_root=cache_root)
    return item


def play_online_audio_candidate(
    candidate: dict[str, Any],
    *,
    player: str = "auto",
    cache_root: Path | None = None,
) -> dict[str, Any]:
    """Coordinates play online audio candidate for the current Sonex flow.

    Typical use: Use this function when runtime code needs play online audio candidate as part of a Sonex command, playback, auth, llm, or ui path.

    Example: play_online_audio_candidate(candidate=..., player=..., cache_root=...) -> returns the value used by the surrounding Sonex flow.
    """
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
    """Coordinates sanitize message for the current Sonex flow.

    Typical use: Use this function when runtime code needs sanitize message as part of a Sonex command, playback, auth, llm, or ui path.

    Example: sanitize_message(message=...) -> returns the value used by the surrounding Sonex flow.
    """
    return message.strip() or "Online audio resolve failed."


def play_youtube_candidate(
    candidate: dict[str, Any],
    *,
    player: str = "auto",
    cache_root: Path | None = None,
) -> dict[str, Any]:
    """Coordinates play youtube candidate for the current Sonex flow.

    Typical use: Use this function when runtime code needs play youtube candidate as part of a Sonex command, playback, auth, llm, or ui path.

    Example: play_youtube_candidate(candidate=..., player=..., cache_root=...) -> returns the value used by the surrounding Sonex flow.
    """
    is_youtube_fallback = candidate.get("fallback_provider") == "youtube"
    try:
        data = download_youtube_candidate(candidate, cache_root=cache_root)
    except Exception as exc:
        message = str(exc)
        if "identity does not match" in message.casefold():
            error_code = "ONLINE_AUDIO_IDENTITY_MISMATCH"
        elif _is_age_verification_error(message):
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

    try:
        _validated_identity(data)
    except RuntimeError as exc:
        return ToolResult.fail(
            tool="play_online_audio" if is_youtube_fallback else "play_youtube_song",
            message=str(exc),
            error_code="ONLINE_AUDIO_IDENTITY_MISMATCH",
            data={"query": candidate.get("query"), "player": player, "method": "online_play", "provider": "youtube"},
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


def resolve_youtube_song(query: str) -> dict[str, Any]:
    """Resolves youtube song from available runtime state.

    Typical use: Use this function when runtime code needs resolve youtube song as part of a Sonex command, playback, auth, llm, or ui path.

    Example: resolve_youtube_song(query=...) -> returns the value used by the surrounding Sonex flow.
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
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "format": "bestaudio/best",
        "skip_download": True,
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
    """Coordinates search and resolve song for the current Sonex flow.

    Typical use: Use this function when runtime code needs search and resolve song as part of a Sonex command, playback, auth, llm, or ui path.

    Example: search_and_resolve_song(query=...) -> returns the value used by the surrounding Sonex flow.
    """
    candidate = search_youtube_songs(query, limit=1)[0]
    return str(download_youtube_candidate(candidate)["stream_url"])


def play_youtube_song(
    query: str,
    player: str = "auto",
    cache_root: Path | None = None,
    playback_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Coordinates play youtube song for the current Sonex flow.

    Typical use: Use this function when runtime code needs play youtube song as part of a Sonex command, playback, auth, llm, or ui path.

    Example: play_youtube_song(query=..., player=..., cache_root=..., playback_metadata=...) -> returns the value used by the surrounding Sonex flow.
    """
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
            return ToolResult.fail(
                tool="play_online_audio",
                message=sanitize_error_message(exc),
                error_code="ONLINE_AUDIO_RESOLVE_FAILED",
                data={"query": query, "player": player, "method": "online_play", "provider": "online_audio"},
            ).to_dict()
        result: dict[str, Any] | None = None
        for candidate in candidates:
            result = play_online_audio_candidate(candidate, player=player, cache_root=cache_root)
            if result.get("error_code") != "ONLINE_AUDIO_IDENTITY_MISMATCH":
                return result
        return result or ToolResult.fail(
            tool="play_online_audio",
            message="No identity-verified online audio candidate could be played.",
            error_code="ONLINE_AUDIO_IDENTITY_MISMATCH",
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
    result = None
    for candidate in candidates:
        result = play_youtube_candidate(candidate, player=player, cache_root=cache_root)
        if result.get("error_code") != "ONLINE_AUDIO_IDENTITY_MISMATCH":
            return result
    return result or ToolResult.fail(
        tool="play_youtube_song",
        message="No identity-verified YouTube candidate could be played.",
        error_code="ONLINE_AUDIO_IDENTITY_MISMATCH",
    ).to_dict()

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
