"""Spotify play support for tool implementations used by the planner and playback flows.

Implements the spotify_play module responsibilities used by Sonex runtime flows.
Key public entry points include SpotifyAppPremiumRequiredError, remember_recent_track, recent_tracks_snapshot, reset_recent_tracks, spotify_search.
"""

from __future__ import annotations

import json
import re
import time
import urllib.request
from pathlib import Path
from typing import Any

import spotipy
from spotipy import SpotifyException

from src.auth.spotify import (
    SpotifyConfigMissingError,
    SpotifyLoginRequiredError,
    SpotifyScopeMissingError,
    ensure_spotify_token,
    load_spotify_token,
    spotify_app_client,
    spotify_user_client,
)
from src.llm.transport import ChatRequest
from src.log import sonex_home
from src.thinking.config import ThinkingConfig
from src.tools.registry import Params, registry
from src.tools.result import ToolResult

SPOTIFY_READ_PLAYBACK_SCOPES = {"user-read-playback-state"}
SPOTIFY_NOW_PLAYING_SCOPES = {"user-read-currently-playing"}
SPOTIFY_MODIFY_PLAYBACK_SCOPES = {"user-modify-playback-state"}
SPOTIFY_PRIVATE_SCOPES = {"user-read-private"}
SPOTIFY_RECENTLY_PLAYED_SCOPES = {"user-read-recently-played"}
SPOTIFY_TOP_READ_SCOPES = {"user-top-read"}
SPOTIFY_PLAYLIST_READ_SCOPES = {"playlist-read-private", "playlist-read-collaborative"}
SPOTIFY_LIBRARY_READ_SCOPES = {"user-library-read"}
MAX_RECENT_TRACKS = 10

_RECENT_TRACKS: list[dict[str, Any]] = []
_RECENT_TRACKS_LOADED = False


class SpotifyAppPremiumRequiredError(RuntimeError):
    """Represents spotify app premium required error.

    Encapsulates spotify app premium required error data and behavior used by Sonex runtime flows. Extends runtime error semantics.
    """
    pass


def _timestamp_ms() -> int:
    """Prepares timestamp ms for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs timestamp ms without duplicating the local rules.

    Example: _timestamp_ms() -> returns the value used by the surrounding Sonex flow.
    """
    return int(time.time() * 1000)


def _spotify_cache_dir() -> Path:
    """Prepares spotify cache dir for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs spotify cache dir without duplicating the local rules.

    Example: _spotify_cache_dir() -> returns the value used by the surrounding Sonex flow.
    """
    return sonex_home() / "cache" / "spotify"


def _spotify_cover_dir() -> Path:
    """Prepares spotify cover dir for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs spotify cover dir without duplicating the local rules.

    Example: _spotify_cover_dir() -> returns the value used by the surrounding Sonex flow.
    """
    return _spotify_cache_dir() / "covers"


def _recent_tracks_path() -> Path:
    """Prepares recent tracks path for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs recent tracks path without duplicating the local rules.

    Example: _recent_tracks_path() -> returns the value used by the surrounding Sonex flow.
    """
    return _spotify_cache_dir() / "recent_tracks.json"


def _iso_now() -> str:
    """Prepares iso now for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs iso now without duplicating the local rules.

    Example: _iso_now() -> returns the value used by the surrounding Sonex flow.
    """
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _best_image(images: list[dict[str, Any]]) -> str | None:
    """Prepares best image for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs best image without duplicating the local rules.

    Example: _best_image(images=...) -> returns the value used by the surrounding Sonex flow.
    """
    if not images:
        return None
    ranked = sorted(
        images,
        key=lambda item: (item.get("width") or 0) * (item.get("height") or 0),
        reverse=True,
    )
    return ranked[0].get("url")


def _artists_text(artists: list[dict[str, Any]]) -> str:
    """Prepares artists text for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs artists text without duplicating the local rules.

    Example: _artists_text(artists=...) -> returns the value used by the surrounding Sonex flow.
    """
    return ", ".join(artist.get("name") for artist in artists if artist.get("name"))


def _normalize_track(item: dict[str, Any]) -> dict[str, Any]:
    """Prepares normalize track for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs normalize track without duplicating the local rules.

    Example: _normalize_track(item=...) -> returns the value used by the surrounding Sonex flow.
    """
    album = item.get("album") or {}
    artists = item.get("artists") or []
    images = album.get("images") or []
    artist_names = [artist.get("name") for artist in artists if artist.get("name")]

    return {
        "id": item.get("id"),
        "name": item.get("name"),
        "duration_ms": item.get("duration_ms"),
        "artist": ", ".join(artist_names),
        "artists": artist_names,
        "album": album.get("name"),
        "album_cover_url": _best_image(images),
        "spotify_url": (item.get("external_urls") or {}).get("spotify"),
        "uri": item.get("uri"),
        "is_playable": item.get("is_playable"),
    }


def _track_key(track: dict[str, Any]) -> str | None:
    """Prepares track key for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs track key without duplicating the local rules.

    Example: _track_key(track=...) -> returns the value used by the surrounding Sonex flow.
    """
    key = track.get("uri") or track.get("id") or track.get("spotify_url")
    return str(key) if key else None


def _compact_track(track: dict[str, Any]) -> dict[str, Any]:
    """Prepares compact track for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs compact track without duplicating the local rules.

    Example: _compact_track(track=...) -> returns the value used by the surrounding Sonex flow.
    """
    return {
        "id": track.get("id"),
        "name": track.get("name") or track.get("title"),
        "duration_ms": track.get("duration_ms") or 0,
        "artist": track.get("artist") or _artists_text(track.get("artists") or []),
        "artists": track.get("artists") or [],
        "album": track.get("album"),
        "album_cover_url": track.get("album_cover_url") or track.get("image_url") or track.get("cover_url"),
        "album_cover_path": track.get("album_cover_path"),
        "spotify_url": track.get("spotify_url"),
        "uri": track.get("uri"),
        "is_playable": track.get("is_playable"),
        "cached_at": track.get("cached_at"),
        "last_played_at": track.get("last_played_at") or track.get("played_at"),
    }


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
    url = str(track.get("album_cover_url") or "").strip()
    if not url:
        return track.get("album_cover_path")

    filename = _cover_filename(track)
    if not filename:
        return track.get("album_cover_path")
    path = _spotify_cover_dir() / filename
    if path.exists():
        return str(path)

    try:
        _spotify_cover_dir().mkdir(parents=True, exist_ok=True)
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
        _spotify_cache_dir().mkdir(parents=True, exist_ok=True)
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
    global _RECENT_TRACKS_LOADED
    _RECENT_TRACKS.clear()
    _RECENT_TRACKS_LOADED = not reload_from_disk
    if clear_disk:
        try:
            _recent_tracks_path().unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass


def _query_terms(text: str) -> list[str]:
    """Prepares query terms for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs query terms without duplicating the local rules.

    Example: _query_terms(text=...) -> returns the value used by the surrounding Sonex flow.
    """
    return [part for part in re.split(r"\W+", text.lower()) if part]


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
        spotify_url = str(track.get("spotify_url") or "").lower()
        name = str(track.get("name") or "").lower()
        artist = str(track.get("artist") or "").lower()
        combined = " ".join(part for part in [name, artist] if part).strip()
        if needle in {uri, spotify_url, name, combined}:
            return track
        terms = _query_terms(needle)
        if len(terms) >= 2 and all(term in combined for term in terms):
            return track
    return None


def _normalize_artist(item: dict[str, Any]) -> dict[str, Any]:
    """Prepares normalize artist for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs normalize artist without duplicating the local rules.

    Example: _normalize_artist(item=...) -> returns the value used by the surrounding Sonex flow.
    """
    images = item.get("images") or []
    followers = item.get("followers") or {}

    return {
        "id": item.get("id"),
        "name": item.get("name"),
        "genres": item.get("genres") or [],
        "followers": followers.get("total"),
        "popularity": item.get("popularity"),
        "image_url": _best_image(images),
        "spotify_url": (item.get("external_urls") or {}).get("spotify"),
        "uri": item.get("uri"),
    }


def _normalize_album(item: dict[str, Any]) -> dict[str, Any]:
    """Prepares normalize album for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs normalize album without duplicating the local rules.

    Example: _normalize_album(item=...) -> returns the value used by the surrounding Sonex flow.
    """
    images = item.get("images") or []
    artists = item.get("artists") or []
    artist_names = [a.get("name") for a in artists if a.get("name")]

    return {
        "id": item.get("id"),
        "name": item.get("name"),
        "artists": artist_names,
        "artist": ", ".join(artist_names),
        "release_date": item.get("release_date"),
        "total_tracks": item.get("total_tracks"),
        "album_type": item.get("album_type"),
        "image_url": _best_image(images),
        "spotify_url": (item.get("external_urls") or {}).get("spotify"),
        "uri": item.get("uri"),
    }


def _normalize_current_playback(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Prepares normalize current playback for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs normalize current playback without duplicating the local rules.

    Example: _normalize_current_playback(payload=...) -> returns the value used by the surrounding Sonex flow.
    """
    if not payload:
        return {
            "is_playing": False,
            "progress_ms": 0,
            "timestamp": _timestamp_ms(),
            "item": None,
            "device": None,
        }

    item = payload.get("item") or {}
    track = _normalize_track(item) if item.get("type") == "track" or item.get("name") else {}
    progress_ms = payload.get("progress_ms") or 0
    timestamp = payload.get("timestamp") or _timestamp_ms()
    device = payload.get("device") or {}

    return {
        **track,
        "progress_ms": progress_ms,
        "timestamp": timestamp,
        "started_at": timestamp - progress_ms,
        "is_playing": bool(payload.get("is_playing")),
        "currently_playing_type": payload.get("currently_playing_type"),
        "device": {
            "id": device.get("id"),
            "name": device.get("name"),
            "type": device.get("type"),
            "is_active": device.get("is_active"),
            "is_restricted": device.get("is_restricted"),
            "volume_percent": device.get("volume_percent"),
        } if device else None,
    }


def _normalize_device(device: dict[str, Any]) -> dict[str, Any]:
    """Prepares normalize device for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs normalize device without duplicating the local rules.

    Example: _normalize_device(device=...) -> returns the value used by the surrounding Sonex flow.
    """
    return {
        "id": device.get("id"),
        "name": device.get("name"),
        "type": device.get("type"),
        "is_active": device.get("is_active"),
        "is_restricted": device.get("is_restricted"),
        "volume_percent": device.get("volume_percent"),
        "supports_volume": device.get("supports_volume"),
    }


def _normalize_playlist(item: dict[str, Any]) -> dict[str, Any]:
    owner = item.get("owner") if isinstance(item.get("owner"), dict) else {}
    tracks = item.get("tracks") if isinstance(item.get("tracks"), dict) else {}
    return {
        "id": item.get("id"),
        "name": item.get("name"),
        "description": item.get("description"),
        "owner": owner.get("display_name") or owner.get("id"),
        "track_count": tracks.get("total") or 0,
        "spotify_url": (item.get("external_urls") or {}).get("spotify"),
        "uri": item.get("uri"),
        "public": item.get("public"),
        "collaborative": item.get("collaborative"),
    }


def _list_devices(client: Any) -> list[dict[str, Any]]:
    """Prepares list devices for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs list devices without duplicating the local rules.

    Example: _list_devices(client=...) -> returns the value used by the surrounding Sonex flow.
    """
    payload = client.devices()
    return [_normalize_device(device) for device in (payload.get("devices") or [])]


def _find_device(
    client: Any,
    *,
    device_id: str | None = None,
    device_name: str | None = None,
) -> dict[str, Any] | None:
    """Prepares find device for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs find device without duplicating the local rules.

    Example: _find_device(client=..., device_id=..., device_name=...) -> returns the value used by the surrounding Sonex flow.
    """
    if not device_id and not device_name:
        return None

    devices = _list_devices(client)
    if device_id:
        return next((device for device in devices if device.get("id") == device_id), None)

    needle = str(device_name or "").strip().lower()
    exact = next((device for device in devices if str(device.get("name") or "").lower() == needle), None)
    if exact:
        return exact
    return next((device for device in devices if needle in str(device.get("name") or "").lower()), None)


def _error_message(exc: Exception) -> str:
    """Prepares error message for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs error message without duplicating the local rules.

    Example: _error_message(exc=...) -> returns the value used by the surrounding Sonex flow.
    """
    message = str(exc)
    if isinstance(exc, SpotifyException):
        message = exc.msg or exc.reason or message
    return message


def _is_app_owner_premium_error(message: str) -> bool:
    """Prepares is app owner premium error for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs is app owner premium error without duplicating the local rules.

    Example: _is_app_owner_premium_error(message=...) -> returns the value used by the surrounding Sonex flow.
    """
    lowered = message.lower()
    return "premium" in lowered and "owner of the app" in lowered


def _spotify_retry_after(exc: Exception) -> str | None:
    headers = getattr(exc, "headers", None)
    value = None
    if isinstance(headers, dict):
        value = headers.get("Retry-After") or headers.get("retry-after")
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _spotify_error(tool: str, exc: Exception, default_code: str = "SPOTIFY_ERROR") -> dict[str, Any]:
    """Prepares spotify error for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs spotify error without duplicating the local rules.

    Example: _spotify_error(tool=..., exc=..., default_code=...) -> returns the value used by the surrounding Sonex flow.
    """
    status = getattr(exc, "http_status", None)
    message = _error_message(exc)
    lowered = message.lower()
    code = default_code
    data: dict[str, Any] = {}

    if isinstance(exc, SpotifyConfigMissingError):
        code = "SPOTIFY_CONFIG_MISSING"
    elif isinstance(exc, SpotifyLoginRequiredError):
        code = "SPOTIFY_LOGIN_REQUIRED"
    elif isinstance(exc, SpotifyScopeMissingError):
        code = "SPOTIFY_SCOPE_MISSING"
    elif isinstance(exc, SpotifyAppPremiumRequiredError):
        code = "SPOTIFY_APP_PREMIUM_REQUIRED"
        message = "Spotify app search requires a Premium account for the app owner."
    elif status == 401:
        code = "SPOTIFY_AUTH_EXPIRED"
    elif status == 403 and tool == "spotify_search" and _is_app_owner_premium_error(message):
        code = "SPOTIFY_APP_PREMIUM_REQUIRED"
        message = "Spotify app search requires a Premium account for the app owner."
    elif status == 403 and "premium" in lowered:
        code = "SPOTIFY_PREMIUM_REQUIRED"
    elif status == 403:
        code = "SPOTIFY_FORBIDDEN"
    elif status == 404:
        code = "SPOTIFY_NO_ACTIVE_DEVICE"
    elif status == 429:
        code = "SPOTIFY_RATE_LIMITED"
        retry_after = _spotify_retry_after(exc)
        message = "Spotify says Too Many Requests. Requests are too frequent; try again later."
        if retry_after:
            data["retry_after"] = f"{retry_after} seconds"
            message = f"{message} Try again after {retry_after} seconds."

    return ToolResult.fail(tool=tool, message=message, error_code=code, data=data).to_dict()


def _search_with_client(query: str, limit: int, types: str, *, use_user: bool = False) -> dict[str, Any]:
    """Prepares search with client for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs search with client without duplicating the local rules.

    Example: _search_with_client(query=..., limit=..., types=..., use_user=...) -> returns the value used by the surrounding Sonex flow.
    """
    client = spotify_user_client() if use_user else spotify_app_client()
    return client.search(q=query, type=types, limit=limit)


def _search_payload(query: str, limit: int, types: str) -> tuple[dict[str, Any], str]:
    """Prepares search payload for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs search payload without duplicating the local rules.

    Example: _search_payload(query=..., limit=..., types=...) -> returns the value used by the surrounding Sonex flow.
    """
    try:
        return _search_with_client(query, limit, types), "app"
    except SpotifyConfigMissingError:
        pass
    except SpotifyException as exc:
        if getattr(exc, "http_status", None) == 403:
            try:
                return _search_with_client(query, limit, types, use_user=True), "user"
            except SpotifyLoginRequiredError:
                if "premium" in _error_message(exc).lower():
                    raise SpotifyAppPremiumRequiredError(
                        "Spotify app search requires a Premium account for the app owner."
                    ) from exc
                raise SpotifyConfigMissingError(
                    "Spotify app search is unavailable and no user account is logged in."
                ) from exc
        raise

    return _search_with_client(query, limit, types, use_user=True), "user"


def _normalize_search_payload(payload: dict[str, Any], types: str) -> dict[str, Any]:
    """Prepares normalize search payload for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs normalize search payload without duplicating the local rules.

    Example: _normalize_search_payload(payload=..., types=...) -> returns the value used by the surrounding Sonex flow.
    """
    data: dict[str, Any] = {}
    requested = {part.strip() for part in types.split(",") if part.strip()}
    if "track" in requested:
        tracks = payload.get("tracks", {}).get("items", []) or []
        data["tracks"] = [_normalize_track(x) for x in tracks]
    if "artist" in requested:
        artists = payload.get("artists", {}).get("items", []) or []
        data["artists"] = [_normalize_artist(x) for x in artists]
    if "album" in requested:
        albums = payload.get("albums", {}).get("items", []) or []
        data["albums"] = [_normalize_album(x) for x in albums]
    return data


def spotify_search(query: str, limit: int = 10, types: str = "track,artist,album") -> dict[str, Any]:
    """Coordinates spotify search for the current Sonex flow.

    Typical use: Use this function when runtime code needs spotify search as part of a Sonex command, playback, auth, llm, or ui path.

    Example: spotify_search(query=..., limit=..., types=...) -> returns the value used by the surrounding Sonex flow.
    """
    try:
        payload, auth_mode = _search_payload(query, limit, types)
    except Exception as exc:
        result = _spotify_error("spotify_search", exc, "SPOTIFY_API_ERROR")
        return result

    data = {
        "query": query,
        "types": types,
        "auth_mode": auth_mode,
        **_normalize_search_payload(payload, types),
    }
    return ToolResult.success(tool="spotify_search", message="Spotify search completed.", data=data).to_dict()


def _spotify_product(*, requests_timeout: float | None = None) -> tuple[str, dict[str, Any] | None]:
    """Prepares spotify product for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs spotify product without duplicating the local rules.

    Example: _spotify_product() -> returns the value used by the surrounding Sonex flow.
    """
    try:
        if requests_timeout is None:
            client = spotify_user_client(SPOTIFY_PRIVATE_SCOPES)
        else:
            token = ensure_spotify_token(SPOTIFY_PRIVATE_SCOPES)
            client = spotipy.Spotify(auth=token.access_token, requests_timeout=requests_timeout, retries=0)
        profile = client.current_user()
    except SpotifyLoginRequiredError:
        return "unknown", None
    except Exception:
        return "unknown", None
    return str(profile.get("product") or "unknown").lower(), profile


def _account_capabilities(product: str, scopes: set[str], logged_in: bool) -> dict[str, bool]:
    """Prepares account capabilities for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs account capabilities without duplicating the local rules.

    Example: _account_capabilities(product=..., scopes=..., logged_in=...) -> returns the value used by the surrounding Sonex flow.
    """
    return {
        "search": True,
        "account": logged_in,
        "current_playback": (
            logged_in
            and _product_allows_premium_capability(product)
            and bool(scopes & (SPOTIFY_READ_PLAYBACK_SCOPES | SPOTIFY_NOW_PLAYING_SCOPES))
        ),
        "playback_control": logged_in
        and _product_allows_premium_capability(product)
        and SPOTIFY_MODIFY_PLAYBACK_SCOPES <= scopes,
        "playlist_read": logged_in and SPOTIFY_PLAYLIST_READ_SCOPES <= scopes,
        "library_read": logged_in and SPOTIFY_LIBRARY_READ_SCOPES <= scopes,
    }


def _product_allows_premium_capability(product: str) -> bool:
    return product in {"premium", "unknown"}


def _product_is_known_non_premium(product: Any) -> bool:
    return str(product or "").lower() in {"free", "open"}


def spotify_account(requests_timeout: float | None = None) -> dict[str, Any]:
    """Coordinates spotify account for the current Sonex flow.

    Typical use: Use this function when runtime code needs spotify account as part of a Sonex command, playback, auth, llm, or ui path.

    Example: spotify_account() -> returns the value used by the surrounding Sonex flow.
    """
    token = load_spotify_token()
    logged_in = bool(token and token.access_token)
    scopes = set(token.scopes if token else [])
    product, profile = _spotify_product(requests_timeout=requests_timeout) if logged_in else ("unknown", None)
    data = {
        "logged_in": logged_in,
        "product": product,
        "scopes": sorted(scopes),
        "capabilities": _account_capabilities(product, scopes, logged_in),
    }
    if profile:
        data["profile"] = {
            "id": profile.get("id"),
            "display_name": profile.get("display_name"),
            "spotify_url": (profile.get("external_urls") or {}).get("spotify"),
        }
    return ToolResult.success(tool="spotify_account", message="Spotify account checked.", data=data).to_dict()


def spotify_current_playback() -> dict[str, Any]:
    """Coordinates spotify current playback for the current Sonex flow.

    Typical use: Use this function when runtime code needs spotify current playback as part of a Sonex command, playback, auth, llm, or ui path.

    Example: spotify_current_playback() -> returns the value used by the surrounding Sonex flow.
    """
    account = spotify_account()
    data = account.get("data") if isinstance(account, dict) else {}
    capabilities = data.get("capabilities") if isinstance(data, dict) else {}
    if data.get("logged_in") and not capabilities.get("current_playback"):
        scopes = set(data.get("scopes") or [])
        if _product_is_known_non_premium(data.get("product")):
            return ToolResult.fail(
                tool="spotify_current_playback",
                message="Spotify playback state requires a Premium account.",
                error_code="SPOTIFY_PREMIUM_REQUIRED",
            ).to_dict()
        if not scopes & (SPOTIFY_READ_PLAYBACK_SCOPES | SPOTIFY_NOW_PLAYING_SCOPES):
            return ToolResult.fail(
                tool="spotify_current_playback",
                message="Spotify playback state scope is missing. Run `sonex auth login spotify` again.",
                error_code="SPOTIFY_SCOPE_MISSING",
            ).to_dict()

    try:
        client = spotify_user_client(SPOTIFY_READ_PLAYBACK_SCOPES)
        playback = client.current_playback()
    except Exception as exc:
        return _spotify_error("spotify_current_playback", exc, "SPOTIFY_API_ERROR")

    data = _normalize_current_playback(playback)
    message = "No active Spotify playback." if not data.get("item") and not data.get("name") else "Current playback loaded."
    return ToolResult.success(tool="spotify_current_playback", message=message, data=data).to_dict()


def spotify_recent_tracks(limit: int = MAX_RECENT_TRACKS) -> dict[str, Any]:
    """Coordinates spotify recent tracks for the current Sonex flow.

    Typical use: Use this function when runtime code needs spotify recent tracks as part of a Sonex command, playback, auth, llm, or ui path.

    Example: spotify_recent_tracks(limit=...) -> returns the value used by the surrounding Sonex flow.
    """
    bounded_limit = min(MAX_RECENT_TRACKS, max(1, int(limit or MAX_RECENT_TRACKS)))
    try:
        client = spotify_user_client(SPOTIFY_RECENTLY_PLAYED_SCOPES)
        payload = client.current_user_recently_played(limit=bounded_limit)
    except Exception as exc:
        return _spotify_error("spotify_recent_tracks", exc, "SPOTIFY_API_ERROR")

    tracks: list[dict[str, Any]] = []
    for item in payload.get("items") or []:
        track_payload = item.get("track") or item
        if not isinstance(track_payload, dict):
            continue
        track = _normalize_track(track_payload)
        played_at = item.get("played_at")
        if played_at:
            track["played_at"] = played_at
        tracks.append(track)
        remember_recent_track(track)

    return ToolResult.success(
        tool="spotify_recent_tracks",
        message=f"Loaded {len(tracks)} recently played Spotify track(s).",
        data={"tracks": tracks[:bounded_limit]},
    ).to_dict()


def spotify_saved_tracks(limit: int = 50, offset: int = 0) -> dict[str, Any]:
    """List the current user's saved Spotify tracks in Sonex's compact track shape."""
    bounded_limit = min(50, max(1, int(limit or 50)))
    bounded_offset = max(0, int(offset or 0))
    try:
        client = spotify_user_client(SPOTIFY_LIBRARY_READ_SCOPES)
        payload = client.current_user_saved_tracks(limit=bounded_limit, offset=bounded_offset)
    except Exception as exc:
        return _spotify_error("spotify_saved_tracks", exc, "SPOTIFY_API_ERROR")

    tracks: list[dict[str, Any]] = []
    for item in payload.get("items") or []:
        if not isinstance(item, dict):
            continue
        track_payload = item.get("track")
        if not isinstance(track_payload, dict) or track_payload.get("type") not in {None, "track"}:
            continue
        track = _normalize_track(track_payload)
        if not track.get("uri"):
            continue
        track["provider"] = "spotify"
        if item.get("added_at"):
            track["added_at"] = item.get("added_at")
        tracks.append(track)

    return ToolResult.success(
        tool="spotify_saved_tracks",
        message=f"Loaded {len(tracks)} saved Spotify track(s).",
        data={"tracks": tracks, "limit": bounded_limit, "offset": bounded_offset},
    ).to_dict()


def spotify_playlists(limit: int = 50, offset: int = 0) -> dict[str, Any]:
    """List current user's Spotify playlists in a compact Sonex shape."""
    bounded_limit = min(50, max(1, int(limit or 50)))
    bounded_offset = max(0, int(offset or 0))
    try:
        client = spotify_user_client(SPOTIFY_PLAYLIST_READ_SCOPES)
        payload = client.current_user_playlists(limit=bounded_limit, offset=bounded_offset)
    except Exception as exc:
        return _spotify_error("spotify_playlists", exc, "SPOTIFY_API_ERROR")

    playlists = [
        _normalize_playlist(item)
        for item in payload.get("items") or []
        if isinstance(item, dict)
    ]
    return ToolResult.success(
        tool="spotify_playlists",
        message=f"Loaded {len(playlists)} Spotify playlist(s).",
        data={"playlists": playlists, "limit": bounded_limit, "offset": bounded_offset},
    ).to_dict()


def spotify_playlist_tracks(playlist_id: str, limit: int = 50, offset: int = 0) -> dict[str, Any]:
    """List tracks from a Spotify playlist in the same compact track shape as spotify_play."""
    playlist_id = str(playlist_id or "").strip()
    if not playlist_id:
        return ToolResult.fail(
            tool="spotify_playlist_tracks",
            message="Provide a Spotify playlist_id.",
            error_code="SPOTIFY_PLAYLIST_REQUIRED",
        ).to_dict()
    bounded_limit = min(100, max(1, int(limit or 50)))
    bounded_offset = max(0, int(offset or 0))
    try:
        client = spotify_user_client(SPOTIFY_PLAYLIST_READ_SCOPES)
        payload = client.playlist_items(
            playlist_id,
            fields="items(track(id,name,duration_ms,artists(name),album(name,images),external_urls,uri,type,is_playable))",
            limit=bounded_limit,
            offset=bounded_offset,
            additional_types=("track",),
        )
    except Exception as exc:
        return _spotify_error("spotify_playlist_tracks", exc, "SPOTIFY_API_ERROR")

    tracks: list[dict[str, Any]] = []
    for item in payload.get("items") or []:
        if not isinstance(item, dict):
            continue
        track_payload = item.get("track")
        if not isinstance(track_payload, dict) or track_payload.get("type") not in {None, "track"}:
            continue
        track = _normalize_track(track_payload)
        if track.get("uri"):
            tracks.append(track)
    return ToolResult.success(
        tool="spotify_playlist_tracks",
        message=f"Loaded {len(tracks)} Spotify playlist track(s).",
        data={"playlist_id": playlist_id, "tracks": tracks, "limit": bounded_limit, "offset": bounded_offset},
    ).to_dict()


def _queue_track(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict) or item.get("type") not in {None, "track"}:
        return None
    track = _normalize_track(item)
    uri = str(track.get("uri") or "")
    if not uri.startswith("spotify:track:"):
        return None
    return track


def spotify_queue(limit: int = 50) -> dict[str, Any]:
    """Read the user's Spotify queue in the same compact track shape as spotify_play."""
    bounded_limit = min(50, max(1, int(limit or 50)))
    try:
        client = spotify_user_client(SPOTIFY_READ_PLAYBACK_SCOPES)
        payload = client.queue()
    except Exception as exc:
        return _spotify_error("spotify_queue", exc, "SPOTIFY_API_ERROR")

    current = _queue_track(payload.get("currently_playing")) if isinstance(payload, dict) else None
    queued: list[dict[str, Any]] = []
    for item in (payload.get("queue") if isinstance(payload, dict) else None) or []:
        track = _queue_track(item)
        if track:
            queued.append(track)

    tracks = ([current] if current else []) + queued
    tracks = tracks[:bounded_limit]
    queue_tracks = queued[: max(0, bounded_limit - (1 if current else 0))]
    return ToolResult.success(
        tool="spotify_queue",
        message=f"Loaded {len(tracks)} Spotify queue track(s).",
        data={
            "tracks": tracks,
            "currently_playing": current,
            "queue": queue_tracks,
            "limit": bounded_limit,
        },
    ).to_dict()


def _require_premium_control(tool: str) -> dict[str, Any] | None:
    """Prepares require premium control for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs require premium control without duplicating the local rules.

    Example: _require_premium_control(tool=...) -> returns the value used by the surrounding Sonex flow.
    """
    account = spotify_account()
    data = account.get("data") or {}
    if not data.get("logged_in"):
        return ToolResult.fail(
            tool=tool,
            message="Run `sonex auth login spotify` before controlling Spotify playback.",
            error_code="SPOTIFY_LOGIN_REQUIRED",
        ).to_dict()
    if _product_is_known_non_premium(data.get("product")):
        return ToolResult.fail(
            tool=tool,
            message="Spotify playback control requires a Premium account.",
            error_code="SPOTIFY_PREMIUM_REQUIRED",
            data={"spotify_url": "https://open.spotify.com/"},
        ).to_dict()
    if not (data.get("capabilities") or {}).get("playback_control"):
        return ToolResult.fail(
            tool=tool,
            message="Spotify playback control scope is missing. Run `sonex auth login spotify` again.",
            error_code="SPOTIFY_SCOPE_MISSING",
        ).to_dict()
    try:
        spotify_user_client(SPOTIFY_MODIFY_PLAYBACK_SCOPES | SPOTIFY_PRIVATE_SCOPES)
    except Exception as exc:
        return _spotify_error(tool, exc, "SPOTIFY_API_ERROR")
    return None


def _has_active_device(client: Any) -> bool:
    """Prepares has active device for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs has active device without duplicating the local rules.

    Example: _has_active_device(client=...) -> returns the value used by the surrounding Sonex flow.
    """
    try:
        payload = client.devices()
    except SpotifyException:
        return True
    devices = payload.get("devices") or []
    return any(device.get("is_active") for device in devices)


def spotify_devices() -> dict[str, Any]:
    """Coordinates spotify devices for the current Sonex flow.

    Typical use: Use this function when runtime code needs spotify devices as part of a Sonex command, playback, auth, llm, or ui path.

    Example: spotify_devices() -> returns the value used by the surrounding Sonex flow.
    """
    try:
        client = spotify_user_client(SPOTIFY_READ_PLAYBACK_SCOPES)
        devices = _list_devices(client)
    except Exception as exc:
        return _spotify_error("spotify_devices", exc, "SPOTIFY_API_ERROR")

    return ToolResult.success(
        tool="spotify_devices",
        message=f"Found {len(devices)} Spotify device(s).",
        data={"devices": devices},
    ).to_dict()


def spotify_transfer_playback(
    device_id: str | None = None,
    device_name: str | None = None,
    play: bool = True,
) -> dict[str, Any]:
    """Coordinates spotify transfer playback for the current Sonex flow.

    Typical use: Use this function when runtime code needs spotify transfer playback as part of a Sonex command, playback, auth, llm, or ui path.

    Example: spotify_transfer_playback(device_id=..., device_name=..., play=...) -> returns the value used by the surrounding Sonex flow.
    """
    blocked = _require_premium_control("spotify_transfer_playback")
    if blocked:
        return blocked
    if not device_id and not device_name:
        return ToolResult.fail(
            tool="spotify_transfer_playback",
            message="Provide a Spotify device_id or device_name.",
            error_code="SPOTIFY_DEVICE_REQUIRED",
        ).to_dict()

    try:
        client = spotify_user_client(SPOTIFY_MODIFY_PLAYBACK_SCOPES | SPOTIFY_READ_PLAYBACK_SCOPES)
        device = _find_device(client, device_id=device_id, device_name=device_name)
        if not device:
            return ToolResult.fail(
                tool="spotify_transfer_playback",
                message=f"Spotify device not found: {device_name or device_id}.",
                error_code="SPOTIFY_DEVICE_NOT_FOUND",
                data={"devices": _list_devices(client)},
            ).to_dict()
        if device.get("is_restricted"):
            return ToolResult.fail(
                tool="spotify_transfer_playback",
                message=f"Spotify device '{device.get('name')}' is restricted and cannot be controlled.",
                error_code="SPOTIFY_DEVICE_RESTRICTED",
                data={"device": device},
            ).to_dict()
        client.transfer_playback(device_id=str(device.get("id")), force_play=play)
    except Exception as exc:
        return _spotify_error("spotify_transfer_playback", exc, "SPOTIFY_API_ERROR")

    return ToolResult.success(
        tool="spotify_transfer_playback",
        message=f"Spotify playback transferred to {device.get('name')}.",
        data={"device": device, "is_playing": play, "timestamp": _timestamp_ms()},
    ).to_dict()


def spotify_play(
    query: str | None = None,
    uri: str | None = None,
    device_id: str | None = None,
    device_name: str | None = None,
) -> dict[str, Any]:
    """Coordinates spotify play for the current Sonex flow.

    Typical use: Use this function when runtime code needs spotify play as part of a Sonex command, playback, auth, llm, or ui path.

    Example: spotify_play(query=..., uri=..., device_id=..., device_name=...) -> returns the value used by the surrounding Sonex flow.
    """
    blocked = _require_premium_control("spotify_play")
    if blocked:
        return blocked
    if not uri and not query:
        return ToolResult.fail(
            tool="spotify_play",
            message="Provide a Spotify URI or a search query.",
            error_code="SPOTIFY_QUERY_REQUIRED",
        ).to_dict()

    track: dict[str, Any] | None = None
    cache_hit = False
    if not uri and query:
        cached = _cached_track_for_query(query)
        if cached and cached.get("uri"):
            track = cached
            uri = str(cached.get("uri"))
            cache_hit = True
        else:
            search_result = spotify_search(query=query, limit=1, types="track")
            if search_result.get("status") != "success":
                return search_result
            tracks = ((search_result.get("data") or {}).get("tracks") or [])
            if not tracks:
                return ToolResult.fail(
                    tool="spotify_play",
                    message=f"No Spotify tracks found for '{query}'.",
                    error_code="SPOTIFY_NO_MATCH",
                ).to_dict()
            track = tracks[0]
            uri = track.get("uri")

    try:
        client = spotify_user_client(SPOTIFY_MODIFY_PLAYBACK_SCOPES | SPOTIFY_READ_PLAYBACK_SCOPES)
        device: dict[str, Any] | None = None
        if device_id or device_name:
            device = _find_device(client, device_id=device_id, device_name=device_name)
            if not device:
                return ToolResult.fail(
                    tool="spotify_play",
                    message=f"Spotify device not found: {device_name or device_id}.",
                    error_code="SPOTIFY_DEVICE_NOT_FOUND",
                    data={"devices": _list_devices(client)},
                ).to_dict()
            if device.get("is_restricted"):
                return ToolResult.fail(
                    tool="spotify_play",
                    message=f"Spotify device '{device.get('name')}' is restricted and cannot be controlled.",
                    error_code="SPOTIFY_DEVICE_RESTRICTED",
                    data={"device": device},
                ).to_dict()
            device_id = str(device.get("id") or "")
        if not device_id and not _has_active_device(client):
            return ToolResult.fail(
                tool="spotify_play",
                message="No active Spotify device found. Open Spotify on your phone or desktop first.",
                error_code="SPOTIFY_NO_ACTIVE_DEVICE",
            ).to_dict()
        client.start_playback(device_id=device_id, uris=[str(uri)])
    except Exception as exc:
        return _spotify_error("spotify_play", exc, "SPOTIFY_API_ERROR")

    data = {
        "query": query,
        "uri": uri,
        "method": "spotify_connect",
        "is_playing": True,
        "progress_ms": 0,
        "timestamp": _timestamp_ms(),
        "cache_hit": cache_hit,
    }
    if device_id:
        data["device_id"] = device_id
    if device_name:
        data["device_name"] = device_name
    if track:
        data.update(track)
        remember_recent_track(track)
    return ToolResult.success(tool="spotify_play", message="Spotify playback started.", data=data).to_dict()


def _user_preferences_text() -> str:
    """Prepares user preferences text for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs user preferences text without duplicating the local rules.

    Example: _user_preferences_text() -> returns the value used by the surrounding Sonex flow.
    """
    user_path = sonex_home() / "USER.md"
    if not user_path.exists():
        return ""
    return user_path.read_text(encoding="utf-8").strip()


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


def _spotify_candidate_tracks(query: str, limit: int) -> list[dict[str, Any]]:
    """Prepares spotify candidate tracks for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs spotify candidate tracks without duplicating the local rules.

    Example: _spotify_candidate_tracks(query=..., limit=...) -> returns the value used by the surrounding Sonex flow.
    """
    candidates: list[dict[str, Any]] = []

    local_recent = recent_tracks_snapshot()
    candidates.extend(local_recent)

    recent_result = spotify_recent_tracks(limit=MAX_RECENT_TRACKS)
    if recent_result.get("status") == "success":
        candidates.extend((recent_result.get("data") or {}).get("tracks") or [])

    if query.strip():
        search_result = spotify_search(query=query, limit=max(limit, 10), types="track")
        if search_result.get("status") == "success":
            candidates.extend((search_result.get("data") or {}).get("tracks") or [])

    artist_terms = []
    for track in local_recent[:5]:
        artist = str(track.get("artist") or "").strip()
        if artist and artist not in artist_terms:
            artist_terms.append(artist)
    for artist in artist_terms[:3]:
        search_result = spotify_search(query=f"artist:{artist}", limit=5, types="track")
        if search_result.get("status") == "success":
            candidates.extend((search_result.get("data") or {}).get("tracks") or [])

    try:
        client = spotify_user_client(SPOTIFY_TOP_READ_SCOPES)
        payload = client.current_user_top_tracks(limit=10, time_range="medium_term")
        candidates.extend([_normalize_track(item) for item in payload.get("items") or []])
    except Exception:
        pass

    return _dedupe_tracks(candidates, limit=50)


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
        "Rank Spotify candidate tracks for a music recommendation request.\n"
        "You must only recommend songs from candidate_tracks. Do not invent songs, artists, or URIs.\n"
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
                    "content": "You are a strict music recommender that only ranks provided Spotify candidates.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=800,
        )
    )
    parsed = _parse_recommendation_json(response.output_text)
    ranked: list[dict[str, str]] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        uri = str(item.get("uri") or "")
        reason = str(item.get("reason") or "Matches your recent listening.")
        if uri:
            ranked.append({"uri": uri, "reason": reason})
    return ranked


def spotify_recommend(query: str, limit: int = 10) -> dict[str, Any]:
    """Coordinates spotify recommend for the current Sonex flow.

    Typical use: Use this function when runtime code needs spotify recommend as part of a Sonex command, playback, auth, llm, or ui path.

    Example: spotify_recommend(query=..., limit=...) -> returns the value used by the surrounding Sonex flow.
    """
    bounded_limit = min(MAX_RECENT_TRACKS, max(1, int(limit or MAX_RECENT_TRACKS)))
    preferences = _user_preferences_text()
    local_recent = recent_tracks_snapshot()
    candidates = _spotify_candidate_tracks(query=query, limit=bounded_limit)
    if not candidates:
        return ToolResult.fail(
            tool="spotify_recommend",
            message="No Spotify recommendation candidates found. Search or play a few tracks first.",
            error_code="SPOTIFY_RECOMMEND_NO_CANDIDATES",
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
        item["recommendation_reason"] = reason_by_uri.get(uri) or "Matched from Spotify candidates and recent listening."
        recommendations.append(item)
        if len(recommendations) >= bounded_limit:
            break

    return ToolResult.success(
        tool="spotify_recommend",
        message=f"Recommended {len(recommendations)} Spotify track(s).",
        data={
            "query": query,
            "tracks": recommendations,
            "user_memory_loaded": bool(preferences),
            "candidate_count": len(candidates),
        },
    ).to_dict()


def spotify_pause() -> dict[str, Any]:
    """Coordinates spotify pause for the current Sonex flow.

    Typical use: Use this function when runtime code needs spotify pause as part of a Sonex command, playback, auth, llm, or ui path.

    Example: spotify_pause() -> returns the value used by the surrounding Sonex flow.
    """
    blocked = _require_premium_control("spotify_pause")
    if blocked:
        return blocked
    try:
        spotify_user_client(SPOTIFY_MODIFY_PLAYBACK_SCOPES).pause_playback()
    except Exception as exc:
        return _spotify_error("spotify_pause", exc, "SPOTIFY_API_ERROR")
    return ToolResult.success(tool="spotify_pause", message="Spotify playback paused.", data={"is_playing": False}).to_dict()


def spotify_resume() -> dict[str, Any]:
    """Coordinates spotify resume for the current Sonex flow.

    Typical use: Use this function when runtime code needs spotify resume as part of a Sonex command, playback, auth, llm, or ui path.

    Example: spotify_resume() -> returns the value used by the surrounding Sonex flow.
    """
    blocked = _require_premium_control("spotify_resume")
    if blocked:
        return blocked
    try:
        spotify_user_client(SPOTIFY_MODIFY_PLAYBACK_SCOPES).start_playback()
    except Exception as exc:
        return _spotify_error("spotify_resume", exc, "SPOTIFY_API_ERROR")
    return ToolResult.success(tool="spotify_resume", message="Spotify playback resumed.", data={"is_playing": True}).to_dict()


def spotify_next() -> dict[str, Any]:
    """Coordinates spotify next for the current Sonex flow.

    Typical use: Use this function when runtime code needs spotify next as part of a Sonex command, playback, auth, llm, or ui path.

    Example: spotify_next() -> returns the value used by the surrounding Sonex flow.
    """
    blocked = _require_premium_control("spotify_next")
    if blocked:
        return blocked
    try:
        spotify_user_client(SPOTIFY_MODIFY_PLAYBACK_SCOPES).next_track()
    except Exception as exc:
        return _spotify_error("spotify_next", exc, "SPOTIFY_API_ERROR")
    return ToolResult.success(tool="spotify_next", message="Skipped to next Spotify track.").to_dict()


def spotify_previous() -> dict[str, Any]:
    """Coordinates spotify previous for the current Sonex flow.

    Typical use: Use this function when runtime code needs spotify previous as part of a Sonex command, playback, auth, llm, or ui path.

    Example: spotify_previous() -> returns the value used by the surrounding Sonex flow.
    """
    blocked = _require_premium_control("spotify_previous")
    if blocked:
        return blocked
    try:
        spotify_user_client(SPOTIFY_MODIFY_PLAYBACK_SCOPES).previous_track()
    except Exception as exc:
        return _spotify_error("spotify_previous", exc, "SPOTIFY_API_ERROR")
    return ToolResult.success(tool="spotify_previous", message="Skipped to previous Spotify track.").to_dict()


def search_tracks(query: str, limit: int = 10) -> dict[str, Any]:
    """Coordinates search tracks for the current Sonex flow.

    Typical use: Use this function when runtime code needs search tracks as part of a Sonex command, playback, auth, llm, or ui path.

    Example: search_tracks(query=..., limit=...) -> returns the value used by the surrounding Sonex flow.
    """
    return spotify_search(query=query, limit=limit, types="track")


def search_albums(query: str, limit: int = 10) -> dict[str, Any]:
    """Coordinates search albums for the current Sonex flow.

    Typical use: Use this function when runtime code needs search albums as part of a Sonex command, playback, auth, llm, or ui path.

    Example: search_albums(query=..., limit=...) -> returns the value used by the surrounding Sonex flow.
    """
    return spotify_search(query=query, limit=limit, types="album")


def search_artists(query: str, limit: int = 10) -> dict[str, Any]:
    """Coordinates search artists for the current Sonex flow.

    Typical use: Use this function when runtime code needs search artists as part of a Sonex command, playback, auth, llm, or ui path.

    Example: search_artists(query=..., limit=...) -> returns the value used by the surrounding Sonex flow.
    """
    return spotify_search(query=query, limit=limit, types="artist")


def search_spotify(query: str, limit: int = 10) -> dict[str, Any]:
    """Coordinates search spotify for the current Sonex flow.

    Typical use: Use this function when runtime code needs search spotify as part of a Sonex command, playback, auth, llm, or ui path.

    Example: search_spotify(query=..., limit=...) -> returns the value used by the surrounding Sonex flow.
    """
    return spotify_search(query=query, limit=limit)


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
        type="spotify",
        description=description,
        parameters=Params(type="object", properties=properties, required=required),
        fn=fn,
        enable=True,
        read_only=read_only,
        required_confirm=False,
    )


_register_tool(
    "spotify_search",
    "Search tracks, artists, and albums on Spotify and return metadata plus cover art.",
    {
        "query": {"type": "string", "description": "The song, artist, album, or related keywords."},
        "limit": {"type": "integer", "description": "Maximum number of items per type to return."},
        "types": {"type": "string", "description": "Comma-separated Spotify item types: track, artist, album."},
    },
    ["query"],
    spotify_search,
)

_register_tool("spotify_account", "Show Spotify login status and account capabilities.", {}, [], spotify_account)
_register_tool("spotify_current_playback", "Read the user's current Spotify playback state.", {}, [], spotify_current_playback)
_register_tool("spotify_recent_tracks", "Read the user's recently played Spotify tracks.", {}, [], spotify_recent_tracks)
_register_tool("spotify_playlists", "List current user's Spotify playlists.", {}, [], spotify_playlists)
_register_tool("spotify_saved_tracks", "List current user's saved Spotify tracks.", {}, [], spotify_saved_tracks)
_register_tool(
    "spotify_playlist_tracks",
    "List tracks from one Spotify playlist.",
    {
        "playlist_id": {"type": "string", "description": "Spotify playlist id."},
        "limit": {"type": "integer", "description": "Maximum number of tracks to return."},
    },
    ["playlist_id"],
    spotify_playlist_tracks,
)
_register_tool("spotify_queue", "Read the user's current Spotify playback queue.", {}, [], spotify_queue)
_register_tool("spotify_devices", "List the user's available Spotify Connect devices.", {}, [], spotify_devices)
_register_tool(
    "spotify_recommend",
    "Recommend real Spotify tracks from Spotify candidates using USER.md preferences and recent listening.",
    {
        "query": {"type": "string", "description": "The recommendation request or taste hint."},
        "limit": {"type": "integer", "description": "Maximum number of recommendations to return."},
    },
    ["query"],
    spotify_recommend,
)
_register_tool(
    "spotify_transfer_playback",
    "Transfer Spotify playback to an available Spotify Connect device.",
    {
        "device_id": {"type": "string", "description": "Spotify Connect device id."},
        "device_name": {"type": "string", "description": "Spotify Connect device name, exact or partial."},
        "play": {"type": "boolean", "description": "Start playback after transfer."},
    },
    [],
    spotify_transfer_playback,
    read_only=False,
)
_register_tool(
    "spotify_play",
    "Play a Spotify track by search query or URI on the user's active or selected Spotify Connect device.",
    {
        "query": {"type": "string", "description": "Track name or keywords to search before playing."},
        "uri": {"type": "string", "description": "Spotify track URI to play directly."},
        "device_id": {"type": "string", "description": "Optional Spotify Connect device id."},
        "device_name": {"type": "string", "description": "Optional Spotify Connect device name, exact or partial."},
    },
    [],
    spotify_play,
    read_only=False,
)
_register_tool("spotify_pause", "Pause Spotify playback.", {}, [], spotify_pause, read_only=False)
_register_tool("spotify_resume", "Resume Spotify playback.", {}, [], spotify_resume, read_only=False)
_register_tool("spotify_next", "Skip to the next Spotify track.", {}, [], spotify_next, read_only=False)
_register_tool("spotify_previous", "Skip to the previous Spotify track.", {}, [], spotify_previous, read_only=False)

_register_tool(
    "search_track",
    "Search tracks on Spotify and return results.",
    {
        "query": {"type": "string", "description": "The track name or related keywords."},
        "limit": {"type": "integer", "description": "Maximum number of tracks to return."},
    },
    ["query"],
    search_tracks,
)
_register_tool(
    "search_album",
    "Search albums on Spotify and return results.",
    {
        "query": {"type": "string", "description": "The album name or related keywords."},
        "limit": {"type": "integer", "description": "Maximum number of albums to return."},
    },
    ["query"],
    search_albums,
)
_register_tool(
    "search_artist",
    "Search artists on Spotify and return results.",
    {
        "query": {"type": "string", "description": "The artist name or related keywords."},
        "limit": {"type": "integer", "description": "Maximum number of artists to return."},
    },
    ["query"],
    search_artists,
)
