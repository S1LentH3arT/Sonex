"""Apple music support for tool implementations used by the planner and playback flows.

Implements the apple_music module responsibilities used by Sonex runtime flows.
Key public entry points include AppleMusicApiError, AppleMusicSubscriptionRequiredError, AppleMusicPlaybackUnavailableError, remember_recent_track, recent_tracks_snapshot.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from src.auth.apple_music import (
    AppleMusicConfigMissingError,
    AppleMusicUserTokenRequiredError,
    apple_music_auth_headers,
    apple_music_setup_message,
    ensure_apple_music_user_token,
    load_apple_music_user_token,
)
from src.llm.transport import ChatRequest
from src.log import sonex_home
from src.thinking.config import ThinkingConfig
from src.tools.music import normalize_track_shape
from src.tools.registry import Params, registry
from src.tools.result import ToolResult

APPLE_MUSIC_API_BASE = "https://api.music.apple.com/v1"
APPLE_MUSIC_DEFAULT_STOREFRONT = "us"
APPLE_MUSIC_BRIDGE_ENV = "APPLE_MUSIC_BRIDGE_URL"
MAX_RECENT_TRACKS = 10

_RECENT_TRACKS: list[dict[str, Any]] = []
_RECENT_TRACKS_LOADED = False
_BRIDGE_STATE: dict[str, Any] | None = None


class AppleMusicApiError(RuntimeError):
    """Represents apple music api error.

    Encapsulates apple music api error data and behavior used by Sonex runtime flows. Extends runtime error semantics.
    """
    def __init__(self, message: str, status: int | None = None) -> None:
        """Prepares init for an internal Sonex flow.

        Typical use: Use this helper when nearby code needs init without duplicating the local rules.

        Example: __init__(message=..., status=...) -> returns the value used by the surrounding Sonex flow.
        """
        super().__init__(message)
        self.status = status


class AppleMusicSubscriptionRequiredError(RuntimeError):
    """Represents apple music subscription required error.

    Encapsulates apple music subscription required error data and behavior used by Sonex runtime flows. Extends runtime error semantics.
    """
    pass


class AppleMusicPlaybackUnavailableError(RuntimeError):
    """Represents apple music playback unavailable error.

    Encapsulates apple music playback unavailable error data and behavior used by Sonex runtime flows. Extends runtime error semantics.
    """
    pass


def _timestamp_ms() -> int:
    """Prepares timestamp ms for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs timestamp ms without duplicating the local rules.

    Example: _timestamp_ms() -> returns the value used by the surrounding Sonex flow.
    """
    return int(time.time() * 1000)


def _iso_now() -> str:
    """Prepares iso now for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs iso now without duplicating the local rules.

    Example: _iso_now() -> returns the value used by the surrounding Sonex flow.
    """
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _apple_music_cache_dir() -> Path:
    """Prepares apple music cache dir for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs apple music cache dir without duplicating the local rules.

    Example: _apple_music_cache_dir() -> returns the value used by the surrounding Sonex flow.
    """
    return sonex_home() / "cache" / "apple_music"


def _apple_music_cover_dir() -> Path:
    """Prepares apple music cover dir for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs apple music cover dir without duplicating the local rules.

    Example: _apple_music_cover_dir() -> returns the value used by the surrounding Sonex flow.
    """
    return _apple_music_cache_dir() / "covers"


def _recent_tracks_path() -> Path:
    """Prepares recent tracks path for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs recent tracks path without duplicating the local rules.

    Example: _recent_tracks_path() -> returns the value used by the surrounding Sonex flow.
    """
    return _apple_music_cache_dir() / "recent_tracks.json"


def _track_key(track: dict[str, Any]) -> str | None:
    """Prepares track key for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs track key without duplicating the local rules.

    Example: _track_key(track=...) -> returns the value used by the surrounding Sonex flow.
    """
    key = track.get("uri") or track.get("id") or track.get("url")
    return str(key) if key else None


def _compact_track(track: dict[str, Any]) -> dict[str, Any]:
    """Prepares compact track for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs compact track without duplicating the local rules.

    Example: _compact_track(track=...) -> returns the value used by the surrounding Sonex flow.
    """
    cover_url = track.get("album_cover_url") or track.get("cover_url")
    return normalize_track_shape(
        provider="apple_music",
        track_id=track.get("id"),
        name=track.get("name") or track.get("title"),
        artists=track.get("artists") or [],
        album=track.get("album"),
        duration_ms=track.get("duration_ms") or 0,
        cover_url=cover_url,
        url=track.get("url") or track.get("apple_music_url"),
        uri=track.get("uri"),
        play_params=track.get("play_params") or {},
        is_playable=track.get("is_playable"),
        extra={
            "apple_music_url": track.get("apple_music_url") or track.get("url"),
            "album_cover_path": track.get("album_cover_path"),
            "cached_at": track.get("cached_at"),
            "last_played_at": track.get("last_played_at") or track.get("played_at"),
        },
    )


def _cover_filename(track: dict[str, Any]) -> str | None:
    """Prepares cover filename for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs cover filename without duplicating the local rules.

    Example: _cover_filename(track=...) -> returns the value used by the surrounding Sonex flow.
    """
    key = _track_key(track)
    if not key:
        return None
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", key).strip("_")
    return f"{safe[:96] or 'cover'}.jpg"


def _cache_cover(track: dict[str, Any]) -> str | None:
    """Prepares cache cover for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs cache cover without duplicating the local rules.

    Example: _cache_cover(track=...) -> returns the value used by the surrounding Sonex flow.
    """
    url = str(track.get("album_cover_url") or track.get("cover_url") or "").strip()
    if not url:
        return track.get("album_cover_path")
    filename = _cover_filename(track)
    if not filename:
        return track.get("album_cover_path")
    path = _apple_music_cover_dir() / filename
    if path.exists():
        return str(path)
    try:
        _apple_music_cover_dir().mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(url, timeout=5) as response:
            content = response.read(5 * 1024 * 1024)
        if content:
            path.write_bytes(content)
            return str(path)
    except Exception:
        return track.get("album_cover_path")
    return track.get("album_cover_path")


def _load_recent_tracks() -> None:
    """Prepares load recent tracks for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs load recent tracks without duplicating the local rules.

    Example: _load_recent_tracks() -> returns the value used by the surrounding Sonex flow.
    """
    global _RECENT_TRACKS, _RECENT_TRACKS_LOADED
    if _RECENT_TRACKS_LOADED:
        return
    _RECENT_TRACKS_LOADED = True
    path = _recent_tracks_path()
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    tracks = data.get("tracks") if isinstance(data, dict) else data
    if not isinstance(tracks, list):
        return

    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in tracks:
        if not isinstance(item, dict):
            continue
        compact = _compact_track(item)
        key = _track_key(compact)
        if not key or key in seen or not compact.get("name"):
            continue
        seen.add(key)
        deduped.append(compact)
        if len(deduped) >= MAX_RECENT_TRACKS:
            break
    _RECENT_TRACKS = deduped


def _save_recent_tracks() -> None:
    """Prepares save recent tracks for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs save recent tracks without duplicating the local rules.

    Example: _save_recent_tracks() -> returns the value used by the surrounding Sonex flow.
    """
    try:
        _apple_music_cache_dir().mkdir(parents=True, exist_ok=True)
        payload = {"version": 1, "tracks": _RECENT_TRACKS[:MAX_RECENT_TRACKS]}
        tmp = _recent_tracks_path().with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(_recent_tracks_path())
    except OSError:
        return


def remember_recent_track(track: dict[str, Any]) -> list[dict[str, Any]]:
    """Coordinates remember recent track for the current Sonex flow.

    Typical use: Use this function when runtime code needs remember recent track as part of a Sonex command, playback, auth, llm, or ui path.

    Example: remember_recent_track(track=...) -> returns the value used by the surrounding Sonex flow.
    """
    _load_recent_tracks()
    compact = _compact_track(track)
    key = _track_key(compact)
    if not key or not compact.get("name"):
        return recent_tracks_snapshot()
    now = _iso_now()
    compact["cached_at"] = compact.get("cached_at") or now
    compact["last_played_at"] = now
    cover_path = _cache_cover(compact)
    if cover_path:
        compact["album_cover_path"] = cover_path

    global _RECENT_TRACKS
    _RECENT_TRACKS = [item for item in _RECENT_TRACKS if _track_key(item) != key]
    _RECENT_TRACKS.insert(0, compact)
    _RECENT_TRACKS = _RECENT_TRACKS[:MAX_RECENT_TRACKS]
    _save_recent_tracks()
    return recent_tracks_snapshot()


def recent_tracks_snapshot(limit: int = MAX_RECENT_TRACKS) -> list[dict[str, Any]]:
    """Coordinates recent tracks snapshot for the current Sonex flow.

    Typical use: Use this function when runtime code needs recent tracks snapshot as part of a Sonex command, playback, auth, llm, or ui path.

    Example: recent_tracks_snapshot(limit=...) -> returns the value used by the surrounding Sonex flow.
    """
    _load_recent_tracks()
    return [dict(item) for item in _RECENT_TRACKS[: max(0, limit)]]


def reset_recent_tracks(*, clear_disk: bool = False, reload_from_disk: bool = False) -> None:
    """Coordinates reset recent tracks for the current Sonex flow.

    Typical use: Use this function when runtime code needs reset recent tracks as part of a Sonex command, playback, auth, llm, or ui path.

    Example: reset_recent_tracks(clear_disk=..., reload_from_disk=...) -> returns the value used by the surrounding Sonex flow.
    """
    global _RECENT_TRACKS_LOADED, _BRIDGE_STATE
    _RECENT_TRACKS.clear()
    _RECENT_TRACKS_LOADED = not reload_from_disk
    _BRIDGE_STATE = None
    if clear_disk:
        try:
            _recent_tracks_path().unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass


def _artwork_url(artwork: dict[str, Any] | None) -> str | None:
    """Prepares artwork url for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs artwork url without duplicating the local rules.

    Example: _artwork_url(artwork=...) -> returns the value used by the surrounding Sonex flow.
    """
    if not artwork:
        return None
    url = artwork.get("url")
    if not url:
        return None
    width = artwork.get("width") or 600
    height = artwork.get("height") or 600
    return str(url).replace("{w}", str(width)).replace("{h}", str(height))


def _normalize_song(item: dict[str, Any]) -> dict[str, Any]:
    """Prepares normalize song for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs normalize song without duplicating the local rules.

    Example: _normalize_song(item=...) -> returns the value used by the surrounding Sonex flow.
    """
    attrs = item.get("attributes") or {}
    artist_name = attrs.get("artistName")
    play_params = attrs.get("playParams") or {}
    song_id = item.get("id")
    return normalize_track_shape(
        provider="apple_music",
        track_id=song_id,
        name=attrs.get("name"),
        artists=[artist_name] if artist_name else [],
        album=attrs.get("albumName"),
        duration_ms=attrs.get("durationInMillis") or 0,
        cover_url=_artwork_url(attrs.get("artwork")),
        url=attrs.get("url"),
        uri=f"apple_music:song:{song_id}" if song_id else None,
        play_params=play_params,
        is_playable=bool(play_params),
        extra={
            "apple_music_url": attrs.get("url"),
            "genre_names": attrs.get("genreNames") or [],
            "release_date": attrs.get("releaseDate"),
        },
    )


def _normalize_artist(item: dict[str, Any]) -> dict[str, Any]:
    """Prepares normalize artist for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs normalize artist without duplicating the local rules.

    Example: _normalize_artist(item=...) -> returns the value used by the surrounding Sonex flow.
    """
    attrs = item.get("attributes") or {}
    return {
        "provider": "apple_music",
        "id": item.get("id"),
        "name": attrs.get("name"),
        "url": attrs.get("url"),
        "apple_music_url": attrs.get("url"),
        "genre_names": attrs.get("genreNames") or [],
    }


def _normalize_album(item: dict[str, Any]) -> dict[str, Any]:
    """Prepares normalize album for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs normalize album without duplicating the local rules.

    Example: _normalize_album(item=...) -> returns the value used by the surrounding Sonex flow.
    """
    attrs = item.get("attributes") or {}
    return {
        "provider": "apple_music",
        "id": item.get("id"),
        "name": attrs.get("name"),
        "artist": attrs.get("artistName"),
        "artists": [attrs.get("artistName")] if attrs.get("artistName") else [],
        "release_date": attrs.get("releaseDate"),
        "total_tracks": attrs.get("trackCount"),
        "album_type": "album",
        "image_url": _artwork_url(attrs.get("artwork")),
        "album_cover_url": _artwork_url(attrs.get("artwork")),
        "url": attrs.get("url"),
        "apple_music_url": attrs.get("url"),
    }


def _apple_music_request(
    path: str,
    *,
    params: dict[str, Any] | None = None,
    user: bool = False,
    method: str = "GET",
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Prepares apple music request for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs apple music request without duplicating the local rules.

    Example: _apple_music_request(path=..., params=..., user=..., method=..., body=...) -> returns the value used by the surrounding Sonex flow.
    """
    query = urllib.parse.urlencode({k: v for k, v in (params or {}).items() if v is not None})
    url = f"{APPLE_MUSIC_API_BASE}{path}"
    if query:
        url = f"{url}?{query}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = apple_music_auth_headers(user=user)
    if body is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            content = response.read()
    except urllib.error.HTTPError as exc:
        message = exc.reason or str(exc)
        try:
            payload = json.loads(exc.read().decode("utf-8"))
            errors = payload.get("errors") if isinstance(payload, dict) else None
            if errors:
                message = str(errors[0].get("title") or errors[0].get("detail") or message)
        except Exception:
            pass
        raise AppleMusicApiError(message, exc.code) from exc
    except urllib.error.URLError as exc:
        raise AppleMusicApiError(str(exc.reason or exc)) from exc
    if not content:
        return {}
    loaded = json.loads(content.decode("utf-8"))
    return loaded if isinstance(loaded, dict) else {}


def _apple_music_error(tool: str, exc: Exception, default_code: str = "APPLE_MUSIC_API_ERROR") -> dict[str, Any]:
    """Prepares apple music error for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs apple music error without duplicating the local rules.

    Example: _apple_music_error(tool=..., exc=..., default_code=...) -> returns the value used by the surrounding Sonex flow.
    """
    message = str(exc)
    code = default_code
    status = getattr(exc, "status", None)
    if isinstance(exc, AppleMusicConfigMissingError):
        code = "APPLE_MUSIC_CONFIG_MISSING"
        message = f"{message} {apple_music_setup_message()}"
    elif isinstance(exc, AppleMusicUserTokenRequiredError):
        code = "APPLE_MUSIC_USER_TOKEN_REQUIRED"
    elif isinstance(exc, AppleMusicSubscriptionRequiredError):
        code = "APPLE_MUSIC_SUBSCRIPTION_REQUIRED"
    elif isinstance(exc, AppleMusicPlaybackUnavailableError):
        code = "APPLE_MUSIC_PLAYBACK_UNAVAILABLE"
    elif status == 401:
        code = "APPLE_MUSIC_AUTH_EXPIRED"
    elif status == 403:
        code = "APPLE_MUSIC_FORBIDDEN"
    elif status == 429:
        code = "APPLE_MUSIC_RATE_LIMITED"
    return ToolResult.fail(tool=tool, message=message, error_code=code).to_dict()


def _normalize_search_payload(payload: dict[str, Any], types: str) -> dict[str, Any]:
    """Prepares normalize search payload for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs normalize search payload without duplicating the local rules.

    Example: _normalize_search_payload(payload=..., types=...) -> returns the value used by the surrounding Sonex flow.
    """
    results = payload.get("results") or {}
    requested = {part.strip() for part in types.split(",") if part.strip()}
    data: dict[str, Any] = {}
    if "songs" in requested or "song" in requested or "track" in requested:
        items = ((results.get("songs") or {}).get("data") or [])
        data["tracks"] = [_normalize_song(item) for item in items if isinstance(item, dict)]
    if "artists" in requested or "artist" in requested:
        items = ((results.get("artists") or {}).get("data") or [])
        data["artists"] = [_normalize_artist(item) for item in items if isinstance(item, dict)]
    if "albums" in requested or "album" in requested:
        items = ((results.get("albums") or {}).get("data") or [])
        data["albums"] = [_normalize_album(item) for item in items if isinstance(item, dict)]
    return data


def _apple_types(types: str) -> str:
    """Prepares apple types for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs apple types without duplicating the local rules.

    Example: _apple_types(types=...) -> returns the value used by the surrounding Sonex flow.
    """
    mapped: list[str] = []
    for item in [part.strip().lower() for part in types.split(",") if part.strip()]:
        if item in {"track", "song", "songs"}:
            mapped.append("songs")
        elif item in {"artist", "artists"}:
            mapped.append("artists")
        elif item in {"album", "albums"}:
            mapped.append("albums")
    return ",".join(dict.fromkeys(mapped or ["songs", "artists", "albums"]))


def apple_music_search(
    query: str,
    limit: int = 10,
    types: str = "songs,artists,albums",
    storefront: str = APPLE_MUSIC_DEFAULT_STOREFRONT,
) -> dict[str, Any]:
    """Coordinates apple music search for the current Sonex flow.

    Typical use: Use this function when runtime code needs apple music search as part of a Sonex command, playback, auth, llm, or ui path.

    Example: apple_music_search(query=..., limit=..., types=..., storefront=...) -> returns the value used by the surrounding Sonex flow.
    """
    try:
        payload = _apple_music_request(
            f"/catalog/{storefront}/search",
            params={"term": query, "types": _apple_types(types), "limit": max(1, min(25, int(limit or 10)))},
        )
    except Exception as exc:
        return _apple_music_error("apple_music_search", exc)
    data = {
        "provider": "apple_music",
        "query": query,
        "types": types,
        "storefront": storefront,
        **_normalize_search_payload(payload, types),
    }
    return ToolResult.success(tool="apple_music_search", message="Apple Music search completed.", data=data).to_dict()


def _account_capabilities(has_developer_token: bool, logged_in: bool, subscription: dict[str, Any]) -> dict[str, bool]:
    """Prepares account capabilities for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs account capabilities without duplicating the local rules.

    Example: _account_capabilities(has_developer_token=..., logged_in=..., subscription=...) -> returns the value used by the surrounding Sonex flow.
    """
    can_play = bool(subscription.get("canPlayCatalogContent"))
    can_library = bool(subscription.get("canPlayCatalogContent") or subscription.get("canPlayLibraryContent"))
    return {
        "search": has_developer_token,
        "account": logged_in,
        "recent_tracks": logged_in,
        "recommendations": logged_in,
        "library": logged_in and can_library,
        "playback_control": logged_in and can_play and bool(_bridge_url()),
        "music_kit_bridge": bool(_bridge_url()),
    }


def apple_music_account() -> dict[str, Any]:
    """Coordinates apple music account for the current Sonex flow.

    Typical use: Use this function when runtime code needs apple music account as part of a Sonex command, playback, auth, llm, or ui path.

    Example: apple_music_account() -> returns the value used by the surrounding Sonex flow.
    """
    has_developer_token = True
    subscription: dict[str, Any] = {}
    try:
        apple_music_auth_headers()
    except Exception as exc:
        has_developer_token = False
        return _apple_music_error("apple_music_account", exc)

    token = load_apple_music_user_token()
    logged_in = bool(token and token.access_token)
    if logged_in:
        try:
            payload = _apple_music_request("/me/storefront", user=True)
            subscription = payload.get("data", [{}])[0].get("attributes", {}).get("subscription", {}) or {}
        except Exception:
            subscription = {}
    data = {
        "provider": "apple_music",
        "logged_in": logged_in,
        "subscription": subscription,
        "capabilities": _account_capabilities(has_developer_token, logged_in, subscription),
    }
    return ToolResult.success(tool="apple_music_account", message="Apple Music account checked.", data=data).to_dict()


def apple_music_recent_tracks(limit: int = MAX_RECENT_TRACKS) -> dict[str, Any]:
    """Coordinates apple music recent tracks for the current Sonex flow.

    Typical use: Use this function when runtime code needs apple music recent tracks as part of a Sonex command, playback, auth, llm, or ui path.

    Example: apple_music_recent_tracks(limit=...) -> returns the value used by the surrounding Sonex flow.
    """
    bounded_limit = min(MAX_RECENT_TRACKS, max(1, int(limit or MAX_RECENT_TRACKS)))
    try:
        ensure_apple_music_user_token()
        payload = _apple_music_request("/me/recent/played/tracks", params={"limit": bounded_limit}, user=True)
    except Exception as exc:
        return _apple_music_error("apple_music_recent_tracks", exc)
    tracks = [_normalize_song(item) for item in (payload.get("data") or []) if isinstance(item, dict)]
    for track in tracks:
        remember_recent_track(track)
    return ToolResult.success(
        tool="apple_music_recent_tracks",
        message=f"Loaded {len(tracks)} recently played Apple Music track(s).",
        data={"provider": "apple_music", "tracks": tracks[:bounded_limit]},
    ).to_dict()


def _dedupe_tracks(tracks: list[dict[str, Any]], limit: int = 40) -> list[dict[str, Any]]:
    """Prepares dedupe tracks for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs dedupe tracks without duplicating the local rules.

    Example: _dedupe_tracks(tracks=..., limit=...) -> returns the value used by the surrounding Sonex flow.
    """
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for track in tracks:
        compact = _compact_track(track)
        key = _track_key(compact)
        if not key or key in seen or not compact.get("name"):
            continue
        seen.add(key)
        deduped.append(compact)
        if len(deduped) >= limit:
            break
    return deduped


def _candidate_tracks(query: str, limit: int) -> list[dict[str, Any]]:
    """Prepares candidate tracks for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs candidate tracks without duplicating the local rules.

    Example: _candidate_tracks(query=..., limit=...) -> returns the value used by the surrounding Sonex flow.
    """
    candidates = recent_tracks_snapshot()
    recent = apple_music_recent_tracks(limit=MAX_RECENT_TRACKS)
    if recent.get("status") == "success":
        candidates.extend((recent.get("data") or {}).get("tracks") or [])
    if query.strip():
        search = apple_music_search(query=query, limit=max(limit, 10), types="songs")
        if search.get("status") == "success":
            candidates.extend((search.get("data") or {}).get("tracks") or [])
    return _dedupe_tracks(candidates, limit=50)


def _user_preferences_text() -> str:
    """Prepares user preferences text for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs user preferences text without duplicating the local rules.

    Example: _user_preferences_text() -> returns the value used by the surrounding Sonex flow.
    """
    user_path = sonex_home() / "USER.md"
    if not user_path.exists():
        return ""
    return user_path.read_text(encoding="utf-8").strip()


def _parse_recommendation_json(text: str) -> list[dict[str, Any]]:
    """Prepares parse recommendation json for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs parse recommendation json without duplicating the local rules.

    Example: _parse_recommendation_json(text=...) -> returns the value used by the surrounding Sonex flow.
    """
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return []
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def _rank_candidates_with_llm(
    *,
    query: str,
    preferences: str,
    recent_tracks: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    limit: int,
) -> list[dict[str, str]]:
    """Prepares rank candidates with llm for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs rank candidates with llm without duplicating the local rules.

    Example: _rank_candidates_with_llm(query=..., preferences=..., recent_tracks=..., candidates=..., limit=...) -> returns the value used by the surrounding Sonex flow.
    """
    compact_candidates = [
        {
            "uri": track.get("uri"),
            "id": track.get("id"),
            "name": track.get("name"),
            "artist": track.get("artist"),
            "album": track.get("album"),
        }
        for track in candidates
    ]
    prompt = (
        "Rank Apple Music candidate tracks for a music recommendation request.\n"
        "You must only recommend songs from candidate_tracks. Do not invent songs, artists, or URIs.\n"
        "Ranking priority is user_query first, then recent_tracks, then user_preferences_from_USER_md.\n"
        "Return JSON only, as an array of objects with uri and reason.\n\n"
        f"user_query: {query}\n"
        f"user_preferences_from_USER_md: {preferences or '(empty)'}\n"
        f"recent_tracks: {json.dumps(recent_tracks[:10], ensure_ascii=False)}\n"
        f"candidate_tracks: {json.dumps(compact_candidates, ensure_ascii=False)}\n"
        f"max_results: {limit}\n"
    )
    response = ThinkingConfig.get_client().generate(
        ChatRequest(
            model=ThinkingConfig.get_model(),
            messages=[
                {
                    "role": "system",
                    "content": "You are a strict music recommender that only ranks provided Apple Music candidates.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=800,
        )
    )
    ranked: list[dict[str, str]] = []
    for item in _parse_recommendation_json(response.output_text):
        if not isinstance(item, dict):
            continue
        uri = str(item.get("uri") or "")
        reason = str(item.get("reason") or "Matches your recent listening.")
        if uri:
            ranked.append({"uri": uri, "reason": reason})
    return ranked


def apple_music_recommend(query: str, limit: int = 10, recent_tracks: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Coordinates apple music recommend for the current Sonex flow.

    Typical use: Use this function when runtime code needs apple music recommend as part of a Sonex command, playback, auth, llm, or ui path.

    Example: apple_music_recommend(query=..., limit=...) -> returns the value used by the surrounding Sonex flow.
    """
    bounded_limit = min(MAX_RECENT_TRACKS, max(1, int(limit or MAX_RECENT_TRACKS)))
    preferences = _user_preferences_text()
    local_recent = list(recent_tracks) if recent_tracks is not None else recent_tracks_snapshot()
    candidates = _candidate_tracks(query=query, limit=bounded_limit)
    if not candidates:
        return ToolResult.fail(
            tool="apple_music_recommend",
            message="No Apple Music recommendation candidates found. Search or load recent tracks first.",
            error_code="APPLE_MUSIC_RECOMMEND_NO_CANDIDATES",
        ).to_dict()
    reason_by_uri: dict[str, str] = {}
    try:
        ranked = _rank_candidates_with_llm(
            query=query,
            preferences=preferences,
            recent_tracks=local_recent,
            candidates=candidates,
            limit=bounded_limit,
        )
        reason_by_uri = {item["uri"]: item["reason"] for item in ranked}
        order = {item["uri"]: idx for idx, item in enumerate(ranked)}
        candidates.sort(key=lambda track: order.get(str(track.get("uri")), len(order)))
    except Exception:
        reason_by_uri = {}

    recommendations = []
    for track in candidates:
        uri = str(track.get("uri") or "")
        item = dict(track)
        item["recommendation_reason"] = reason_by_uri.get(uri) or "Matched from Apple Music candidates and recent listening."
        recommendations.append(item)
        if len(recommendations) >= bounded_limit:
            break
    return ToolResult.success(
        tool="apple_music_recommend",
        message=f"Recommended {len(recommendations)} Apple Music track(s).",
        data={
            "provider": "apple_music",
            "query": query,
            "tracks": recommendations,
            "user_memory_loaded": bool(preferences),
            "candidate_count": len(candidates),
        },
    ).to_dict()


def _bridge_url() -> str | None:
    """Prepares bridge url for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs bridge url without duplicating the local rules.

    Example: _bridge_url() -> returns the value used by the surrounding Sonex flow.
    """
    import os

    value = os.getenv(APPLE_MUSIC_BRIDGE_ENV, "").strip().rstrip("/")
    return value or None


def _bridge_request(path: str, payload: dict[str, Any] | None = None, method: str = "POST") -> dict[str, Any]:
    """Prepares bridge request for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs bridge request without duplicating the local rules.

    Example: _bridge_request(path=..., payload=..., method=...) -> returns the value used by the surrounding Sonex flow.
    """
    base = _bridge_url()
    if not base:
        raise AppleMusicPlaybackUnavailableError(
            "Apple Music playback control requires a local MusicKit bridge. Set APPLE_MUSIC_BRIDGE_URL."
        )
    data = json.dumps(payload or {}).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"}
    request = urllib.request.Request(f"{base}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            content = response.read()
    except Exception as exc:
        raise AppleMusicPlaybackUnavailableError(f"Apple Music bridge request failed: {exc}") from exc
    if not content:
        return {}
    loaded = json.loads(content.decode("utf-8"))
    return loaded if isinstance(loaded, dict) else {}


def _require_playback_control(tool: str) -> dict[str, Any] | None:
    """Prepares require playback control for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs require playback control without duplicating the local rules.

    Example: _require_playback_control(tool=...) -> returns the value used by the surrounding Sonex flow.
    """
    try:
        ensure_apple_music_user_token()
    except Exception as exc:
        return _apple_music_error(tool, exc)
    account = apple_music_account()
    data = account.get("data") or {}
    subscription = data.get("subscription") or {}
    if not subscription.get("canPlayCatalogContent"):
        return ToolResult.fail(
            tool=tool,
            message="Apple Music catalog playback requires an account that can play catalog content.",
            error_code="APPLE_MUSIC_SUBSCRIPTION_REQUIRED",
            data={"provider": "apple_music", "subscription": subscription},
        ).to_dict()
    if not _bridge_url():
        return _apple_music_error(
            tool,
            AppleMusicPlaybackUnavailableError(
                "Apple Music playback needs Sonex's local MusicKit bridge; cross-device Apple Music client control is not supported."
            ),
        )
    return None


def _cached_track_for_query(query: str) -> dict[str, Any] | None:
    """Prepares cached track for query for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs cached track for query without duplicating the local rules.

    Example: _cached_track_for_query(query=...) -> returns the value used by the surrounding Sonex flow.
    """
    needle = " ".join(query.strip().lower().split())
    if not needle:
        return None
    for track in recent_tracks_snapshot():
        uri = str(track.get("uri") or "").lower()
        url = str(track.get("url") or track.get("apple_music_url") or "").lower()
        name = str(track.get("name") or "").lower()
        artist = str(track.get("artist") or "").lower()
        combined = " ".join(part for part in [name, artist] if part).strip()
        if needle in {uri, url, name, combined}:
            return track
        terms = [part for part in re.split(r"\W+", needle) if part]
        if len(terms) >= 2 and all(term in combined for term in terms):
            return track
    return None


def apple_music_current_playback() -> dict[str, Any]:
    """Coordinates apple music current playback for the current Sonex flow.

    Typical use: Use this function when runtime code needs apple music current playback as part of a Sonex command, playback, auth, llm, or ui path.

    Example: apple_music_current_playback() -> returns the value used by the surrounding Sonex flow.
    """
    if _bridge_url():
        try:
            data = _bridge_request("/current", payload=None, method="GET")
            if data:
                data["provider"] = "apple_music"
                return ToolResult.success(
                    tool="apple_music_current_playback",
                    message="Current Apple Music playback loaded.",
                    data=data,
                ).to_dict()
        except Exception as exc:
            return _apple_music_error("apple_music_current_playback", exc)
    if _BRIDGE_STATE:
        return ToolResult.success(
            tool="apple_music_current_playback",
            message="Current Apple Music bridge state loaded.",
            data=dict(_BRIDGE_STATE),
        ).to_dict()
    return _apple_music_error(
        "apple_music_current_playback",
        AppleMusicPlaybackUnavailableError("No Apple Music MusicKit bridge is configured or active."),
    )


def apple_music_play(query: str | None = None, uri: str | None = None, storefront: str = APPLE_MUSIC_DEFAULT_STOREFRONT) -> dict[str, Any]:
    """Coordinates apple music play for the current Sonex flow.

    Typical use: Use this function when runtime code needs apple music play as part of a Sonex command, playback, auth, llm, or ui path.

    Example: apple_music_play(query=..., uri=..., storefront=...) -> returns the value used by the surrounding Sonex flow.
    """
    blocked = _require_playback_control("apple_music_play")
    if blocked:
        return blocked
    if not uri and not query:
        return ToolResult.fail(
            tool="apple_music_play",
            message="Provide an Apple Music URI or search query.",
            error_code="APPLE_MUSIC_QUERY_REQUIRED",
        ).to_dict()

    track: dict[str, Any] | None = None
    if not uri and query:
        cached = _cached_track_for_query(query)
        if cached and cached.get("uri"):
            track = cached
            uri = str(cached.get("uri"))
        else:
            search = apple_music_search(query=query, limit=1, types="songs", storefront=storefront)
            if search.get("status") != "success":
                return search
            tracks = (search.get("data") or {}).get("tracks") or []
            if not tracks:
                return ToolResult.fail(
                    tool="apple_music_play",
                    message=f"No Apple Music tracks found for '{query}'.",
                    error_code="APPLE_MUSIC_NO_MATCH",
                ).to_dict()
            track = tracks[0]
            uri = track.get("uri")

    payload = {"uri": uri, "track": track}
    try:
        bridge_data = _bridge_request("/play", payload=payload)
    except Exception as exc:
        return _apple_music_error("apple_music_play", exc)

    state = {
        "provider": "apple_music",
        "uri": uri,
        "method": "musickit_bridge",
        "is_playing": True,
        "progress_ms": 0,
        "timestamp": _timestamp_ms(),
    }
    if track:
        state.update(track)
        remember_recent_track(track)
    state.update(bridge_data)
    global _BRIDGE_STATE
    _BRIDGE_STATE = dict(state)
    return ToolResult.success(tool="apple_music_play", message="Apple Music playback started.", data=state).to_dict()


def _bridge_control(tool: str, path: str, is_playing: bool | None = None) -> dict[str, Any]:
    """Prepares bridge control for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs bridge control without duplicating the local rules.

    Example: _bridge_control(tool=..., path=..., is_playing=...) -> returns the value used by the surrounding Sonex flow.
    """
    blocked = _require_playback_control(tool)
    if blocked:
        return blocked
    try:
        data = _bridge_request(path)
    except Exception as exc:
        return _apple_music_error(tool, exc)
    state = {"provider": "apple_music", "timestamp": _timestamp_ms(), **data}
    if is_playing is not None:
        state["is_playing"] = is_playing
    global _BRIDGE_STATE
    if _BRIDGE_STATE:
        _BRIDGE_STATE.update(state)
    else:
        _BRIDGE_STATE = dict(state)
    return ToolResult.success(tool=tool, message=f"Apple Music {tool.removeprefix('apple_music_')} completed.", data=state).to_dict()


def apple_music_pause() -> dict[str, Any]:
    """Coordinates apple music pause for the current Sonex flow.

    Typical use: Use this function when runtime code needs apple music pause as part of a Sonex command, playback, auth, llm, or ui path.

    Example: apple_music_pause() -> returns the value used by the surrounding Sonex flow.
    """
    return _bridge_control("apple_music_pause", "/pause", is_playing=False)


def apple_music_resume() -> dict[str, Any]:
    """Coordinates apple music resume for the current Sonex flow.

    Typical use: Use this function when runtime code needs apple music resume as part of a Sonex command, playback, auth, llm, or ui path.

    Example: apple_music_resume() -> returns the value used by the surrounding Sonex flow.
    """
    return _bridge_control("apple_music_resume", "/resume", is_playing=True)


def apple_music_next() -> dict[str, Any]:
    """Coordinates apple music next for the current Sonex flow.

    Typical use: Use this function when runtime code needs apple music next as part of a Sonex command, playback, auth, llm, or ui path.

    Example: apple_music_next() -> returns the value used by the surrounding Sonex flow.
    """
    return _bridge_control("apple_music_next", "/next")


def apple_music_previous() -> dict[str, Any]:
    """Coordinates apple music previous for the current Sonex flow.

    Typical use: Use this function when runtime code needs apple music previous as part of a Sonex command, playback, auth, llm, or ui path.

    Example: apple_music_previous() -> returns the value used by the surrounding Sonex flow.
    """
    return _bridge_control("apple_music_previous", "/previous")


def _register_tool(
    name: str,
    description: str,
    properties: dict[str, Any],
    required: list[str],
    fn: Any,
    *,
    read_only: bool = True,
) -> None:
    """Prepares register tool for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs register tool without duplicating the local rules.

    Example: _register_tool(name=..., description=..., properties=..., required=..., fn=..., read_only=...) -> returns the value used by the surrounding Sonex flow.
    """
    registry.register(
        name=name,
        kind="system",
        domain="apple_music",
        description=description,
        parameters=Params(type="object", properties=properties, required=required),
        fn=fn,
        enable=True,
        read_only=read_only,
        required_confirm=not read_only,
    )


_register_tool(
    "apple_music_search",
    "Search tracks, artists, and albums on Apple Music and return metadata plus cover art.",
    {
        "query": {"type": "string", "description": "The song, artist, album, or related keywords."},
        "limit": {"type": "integer", "description": "Maximum number of items per type to return."},
        "types": {"type": "string", "description": "Comma-separated item types: songs, artists, albums."},
        "storefront": {"type": "string", "description": "Apple Music storefront, such as us or cn."},
    },
    ["query"],
    apple_music_search,
)
_register_tool("apple_music_account", "Show Apple Music login, subscription, and playback capabilities.", {}, [], apple_music_account)
_register_tool("apple_music_current_playback", "Read the active Sonex MusicKit bridge playback state.", {}, [], apple_music_current_playback)
_register_tool("apple_music_recent_tracks", "Read the user's recently played Apple Music tracks.", {}, [], apple_music_recent_tracks)
_register_tool(
    "apple_music_recommend",
    "Recommend real Apple Music tracks from Apple Music candidates using USER.md preferences and recent listening.",
    {
        "query": {"type": "string", "description": "The recommendation request or taste hint."},
        "limit": {"type": "integer", "description": "Maximum number of recommendations to return."},
    },
    ["query"],
    apple_music_recommend,
)
_register_tool(
    "apple_music_play",
    "Play an Apple Music track through Sonex's local MusicKit bridge by search query or URI.",
    {
        "query": {"type": "string", "description": "Track name or keywords to search before playing."},
        "uri": {"type": "string", "description": "Apple Music track URI to play directly."},
        "storefront": {"type": "string", "description": "Apple Music storefront, such as us or cn."},
    },
    [],
    apple_music_play,
    read_only=False,
)
_register_tool("apple_music_pause", "Pause Apple Music playback through Sonex's MusicKit bridge.", {}, [], apple_music_pause, read_only=False)
_register_tool("apple_music_resume", "Resume Apple Music playback through Sonex's MusicKit bridge.", {}, [], apple_music_resume, read_only=False)
_register_tool("apple_music_next", "Skip to the next Apple Music track through Sonex's MusicKit bridge.", {}, [], apple_music_next, read_only=False)
_register_tool("apple_music_previous", "Skip to the previous Apple Music track through Sonex's MusicKit bridge.", {}, [], apple_music_previous, read_only=False)
