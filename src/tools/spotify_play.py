from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import spotipy
from dotenv import load_dotenv
from spotipy.oauth2 import SpotifyOAuth

DEFAULT_SPOTIFY_SCOPE = "user-read-playback-state user-modify-playback-state user-read-currently-playing"
_ENV_LOADED = False


def _load_env_files() -> None:
    global _ENV_LOADED
    if _ENV_LOADED:
        return

    load_dotenv(override=False)

    project_root = Path(__file__).resolve().parents[2]
    dev_env = project_root / "dev.env"
    if dev_env.exists():
        load_dotenv(dotenv_path=dev_env, override=False)

    _ENV_LOADED = True


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if value:
        return value
    raise RuntimeError(f"Missing required environment variable: {name}")


def _spotify_client() -> spotipy.Spotify:
    _load_env_files()

    cache_path = Path(
        os.getenv("SPOTIFY_CACHE_PATH")
        or (Path.home() / "sonex" / ".cache" / "spotify_token_cache")
    ).expanduser()
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    auth_manager = SpotifyOAuth(
        client_id=_require_env("SPOTIFY_CLIENT_ID"),
        client_secret=_require_env("SPOTIFY_CLIENT_SECRET"),
        redirect_uri=os.getenv("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:9957/callback"),
        scope=os.getenv("SPOTIFY_SCOPE", DEFAULT_SPOTIFY_SCOPE),
        open_browser=False,
        cache_path=str(cache_path),
    )
    return spotipy.Spotify(auth_manager=auth_manager)


def _normalize_track(item: dict[str, Any]) -> dict[str, Any]:
    album = item.get("album") or {}
    artists = item.get("artists") or []
    images = album.get("images") or []

    artist_names = [artist.get("name") for artist in artists if artist.get("name")]

    return {
        "id": item.get("id"),
        "name": item.get("name"),
        "artist": ", ".join(artist_names),
        "artists": artist_names,
        "album": album.get("name"),
        "album_cover_url": images[0].get("url") if images else None,
        "spotify_url": (item.get("external_urls") or {}).get("spotify"),
        "uri": item.get("uri"),
    }


def search_spotify_tracks(query: str, limit: int = 5) -> dict[str, Any]:
    if not query.strip():
        raise ValueError("query cannot be empty")
    if limit < 1 or limit > 20:
        raise ValueError("limit must be between 1 and 20")

    client = _spotify_client()
    payload = client
    items = (payload.get("tracks") or {}).get("items") or []

    tracks = [_normalize_track(item) for item in items]
    return {
        "query": query,
        "count": len(tracks),
        "tracks": tracks,
        "raw": payload,
    }


def play_spotify(query: str) -> dict[str, Any]:
    result = search_spotify_tracks(query=query, limit=1)
    tracks = result["tracks"]

    if not tracks:
        raise RuntimeError(f"No track found for query: {query}")

    uri = tracks[0].get("uri")
    if not uri:
        raise RuntimeError("Spotify returned a track without a playable URI")

    client = _spotify_client()
    try:
        client.start_playback(uris=[uri])
    except spotipy.SpotifyException as exc:
        raise RuntimeError(
            "Unable to start playback. Open Spotify on an active device and try again."
        ) from exc

    return {"status": "ok", "query": query, "track": tracks[0]}
