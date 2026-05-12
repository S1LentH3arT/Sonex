from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import spotipy
from dotenv import load_dotenv
from spotipy import SpotifyException
from spotipy.oauth2 import SpotifyOAuth

from src.tools.registry import registry, Params, RiskEntry

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

    # spotify缓存目录
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
        "duration_ms": item.get("duration_ms"),
        "artist": ", ".join(artist_names),
        "artists": artist_names,
        "album": album.get("name"),
        "album_cover_url": images[0].get("url") if images else None,
        "spotify_url": (item.get("external_urls") or {}).get("spotify"),
        "uri": item.get("uri"),
    }

def _normalize_artist(item: dict[str, Any]) -> dict[str, Any]:
    images = item.get("images") or []
    followers = item.get("followers") or {}

    return {
        "id": item.get("id"),
        "name": item.get("name"),
        "genres": item.get("genres") or [],
        "followers": followers.get("total"),
        "popularity": item.get("popularity"),
        "image_url": images[0].get("url") if images else None,
        "spotify_url": (item.get("external_urls") or {}).get("spotify"),
        "uri": item.get("uri"),
    }

def _normalize_album(item: dict[str, Any]) -> dict[str, Any]:
    images = item.get("images") or []
    artists = item.get("artists") or []
    artist_names = [a.get("name") for a in artists if a.get("name")]

    return {
        "id": item.get("id"),
        "name": item.get("name"),
        "artists": artist_names,
        "release_date": item.get("release_date"),
        "total_tracks": item.get("total_tracks"),
        "album_type": item.get("album_type"),
        "image_url": images[0].get("url") if images else None,
        "spotify_url": (item.get("external_urls") or {}).get("spotify"),
        "uri": item.get("uri"),
    }

# 搜索歌曲
def search_tracks(query: str, limit: int = 10) -> dict[str, Any]:
    client = _spotify_client()

    try:
        payload = client.search(
            q=query,
            type="track",
            limit=limit,
        )
    except SpotifyException as exc:
        raise RuntimeError(f"Spotify search failed: {exc}")

    tracks = payload.get("tracks", {}).get("items", []) or []

    return {
        "query": query,
        "tracks": [_normalize_track(x) for x in tracks],
    }

# 搜索专辑
def search_albums(query: str, limit: int = 10) -> dict[str, Any]:
    client = _spotify_client()

    try:
        payload = client.search(
            q=query,
            type="album",
            limit=limit,
        )
    except SpotifyException as exc:
        raise RuntimeError(f"Spotify search failed: {exc}")

    albums = payload.get("albums", {}).get("items", []) or []

    return {
        "query": query,
        "albums": [_normalize_album(x) for x in albums],
    }

# 搜索艺人
def search_artists(query: str, limit: int = 10) -> dict[str, Any]:
    client = _spotify_client()

    try:
        payload = client.search(
            q=query,
            type="artist",
            limit=limit,
        )
    except SpotifyException as exc:
        raise RuntimeError(f"Spotify search failed: {exc}")

    artists = payload.get("artists", {}).get("items", []) or []

    return {
        "query": query,
        "artists": [_normalize_artist(x) for x in artists],
    }

# 搜索音乐信息(歌曲、歌手、专辑)
def search_spotify(query: str, limit: int = 10) -> dict[str, Any]:
    client = _spotify_client()

    try:
        payload = client.search(
            q=query,
            type="track,artist,album",
            limit=limit,
        )
    except SpotifyException as exc:
        raise RuntimeError(f"Spotify search failed: {exc}")

    tracks = payload.get("tracks", {}).get("items", []) or []
    artists = payload.get("artists", {}).get("items", []) or []
    albums = payload.get("albums", {}).get("items", []) or []

    return {
        "query": query,
        "tracks": [_normalize_track(x) for x in tracks],
        "artists": [_normalize_artist(x) for x in artists],
        "albums": [_normalize_album(x) for x in albums],
    }

registry.register(
    name="search_track",
    type="search",
    description="Search tracks on Spotify and return results.",
    parameters=Params(
        type="object",
        properties={
            "query": {"type": "string", "description": "The track name or related key words."},
            "limit": {"type": "integer", "description": "The maximum number of tracks to return."},
        },
        required=["query", "limit"],
    ),
    fn=search_tracks,
    enable=True,
    required_confirm=False,
)

registry.register(
    name="search_album",
    type="search",
    description="Search albums on Spotify and return results.",
    parameters=Params(
        type="object",
        properties={
            "query": {"type": "string", "description": "The album name or related key words."},
            "limit": {"type": "integer", "description": "The maximum number of albums to return."},
        },
        required=["query", "limit"],
    ),
    fn=search_albums,
    enable=True,
    required_confirm=False,
)

registry.register(
    name="search_artist",
    type="search",
    description="Search artists on Spotify and return results.",
    parameters=Params(
        type="object",
        properties={
            "query": {"type": "string", "description": "The artist name or related key words."},
            "limit": {"type": "integer", "description": "The maximum number of artists to return."},
        },
        required=["query", "limit"],
    ),
    fn=search_artists,
    enable=True,
    required_confirm=False,
)