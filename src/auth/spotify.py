"""Spotify support for provider authentication and credential persistence.

Implements the spotify module responsibilities used by Sonex runtime flows.
Key public entry points include SpotifyAuthError, SpotifyConfigMissingError, SpotifyLoginRequiredError, SpotifyScopeMissingError, load_spotify_env.
"""

from __future__ import annotations

import os
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import spotipy
from dotenv import load_dotenv
from spotipy.oauth2 import CacheHandler, SpotifyClientCredentials, SpotifyOAuth

from src.auth.models import OAuthToken
from src.auth.store import get_provider_auth, load_auth_store, set_api_key, set_oauth_token

SPOTIFY_PROVIDER = "spotify"
DEFAULT_SPOTIFY_SCOPES = [
    "user-read-private",
    "user-read-playback-state",
    "user-read-currently-playing",
    "user-read-recently-played",
    "user-top-read",
    "user-modify-playback-state",
    "playlist-read-private",
    "playlist-read-collaborative",
    "user-library-read",
]
DEFAULT_SPOTIFY_REDIRECT_URI = "http://127.0.0.1:9957/callback"
_ENV_LOADED = False


class SpotifyAuthError(RuntimeError):
    """Represents spotify auth error.

    Encapsulates spotify auth error data and behavior used by Sonex runtime flows. Extends runtime error semantics.
    """
    pass


class SpotifyConfigMissingError(SpotifyAuthError):
    """Represents spotify config missing error.

    Encapsulates spotify config missing error data and behavior used by Sonex runtime flows. Extends spotify auth error semantics.
    """
    pass


class SpotifyLoginRequiredError(SpotifyAuthError):
    """Represents spotify login required error.

    Encapsulates spotify login required error data and behavior used by Sonex runtime flows. Extends spotify auth error semantics.
    """
    pass


class SpotifyScopeMissingError(SpotifyAuthError):
    """Represents spotify scope missing error.

    Encapsulates spotify scope missing error data and behavior used by Sonex runtime flows. Extends spotify auth error semantics.
    """
    def __init__(self, missing_scopes: set[str]) -> None:
        """Prepares init for an internal Sonex flow.

        Typical use: Use this helper when nearby code needs init without duplicating the local rules.

        Example: __init__(missing_scopes=...) -> returns the value used by the surrounding Sonex flow.
        """
        self.missing_scopes = missing_scopes
        scopes = ", ".join(sorted(missing_scopes))
        super().__init__(f"Spotify login is missing required scope(s): {scopes}.")


class _NoopCacheHandler(CacheHandler):
    """Represents noop cache handler.

    Encapsulates noop cache handler data and behavior used by Sonex runtime flows. Extends cache handler semantics.
    """
    def get_cached_token(self) -> None:
        """Returns cached token for the current Sonex flow.

        Typical use: Use this function when runtime code needs get cached token as part of a Sonex command, playback, auth, llm, or ui path.

        Example: get_cached_token() -> returns the value used by the surrounding Sonex flow.
        """
        return None

    def save_token_to_cache(self, token_info: dict[str, Any]) -> None:
        """Persists token to cache for later use.

        Typical use: Use this function when runtime code needs save token to cache as part of a Sonex command, playback, auth, llm, or ui path.

        Example: save_token_to_cache(token_info=...) -> returns the value used by the surrounding Sonex flow.
        """
        return None


def load_spotify_env() -> None:
    """Loads spotify env from persistent state.

    Typical use: Use this function when runtime code needs load spotify env as part of a Sonex command, playback, auth, llm, or ui path.

    Example: load_spotify_env() -> returns the value used by the surrounding Sonex flow.
    """
    global _ENV_LOADED
    if _ENV_LOADED:
        return

    load_dotenv(override=False)
    _ENV_LOADED = True


def spotify_redirect_uri() -> str:
    """Coordinates spotify redirect uri for the current Sonex flow.

    Typical use: Use this function when runtime code needs spotify redirect uri as part of a Sonex command, playback, auth, llm, or ui path.

    Example: spotify_redirect_uri() -> returns the value used by the surrounding Sonex flow.
    """
    load_spotify_env()
    return os.getenv("SPOTIFY_REDIRECT_URI", DEFAULT_SPOTIFY_REDIRECT_URI)


def spotify_scopes() -> list[str]:
    """Coordinates spotify scopes for the current Sonex flow.

    Typical use: Use this function when runtime code needs spotify scopes as part of a Sonex command, playback, auth, llm, or ui path.

    Example: spotify_scopes() -> returns the value used by the surrounding Sonex flow.
    """
    load_spotify_env()
    raw = os.getenv("SPOTIFY_SCOPE")
    if not raw:
        return DEFAULT_SPOTIFY_SCOPES
    return [scope for scope in raw.replace(",", " ").split() if scope]


def spotify_app_credentials() -> tuple[str, str]:
    """Coordinates spotify app credentials for the current Sonex flow.

    Typical use: Use this function when runtime code needs spotify app credentials as part of a Sonex command, playback, auth, llm, or ui path.

    Example: spotify_app_credentials() -> returns the value used by the surrounding Sonex flow.
    """
    load_spotify_env()
    client_id = os.getenv("SPOTIFY_CLIENT_ID")
    client_secret = os.getenv("SPOTIFY_CLIENT_SECRET")
    if client_id and client_secret:
        return client_id, client_secret

    provider = get_provider_auth(load_auth_store(), SPOTIFY_PROVIDER)
    if provider and provider.api_key and ":" in provider.api_key:
        saved_id, saved_secret = provider.api_key.split(":", 1)
        if saved_id and saved_secret:
            return saved_id, saved_secret

    raise SpotifyConfigMissingError(
        "Spotify app credentials are missing. Set SPOTIFY_CLIENT_ID and "
        "SPOTIFY_CLIENT_SECRET, or store them as client_id:client_secret."
    )


def save_spotify_app_credentials(client_id: str, client_secret: str) -> Path:
    """Persists spotify app credentials for later use.

    Typical use: Use this function when runtime code needs save spotify app credentials as part of a Sonex command, playback, auth, llm, or ui path.

    Example: save_spotify_app_credentials(client_id=..., client_secret=...) -> returns the value used by the surrounding Sonex flow.
    """
    client_id = client_id.strip()
    client_secret = client_secret.strip()
    if not client_id or not client_secret:
        raise SpotifyConfigMissingError("Spotify client id and client secret are required.")
    return set_api_key(SPOTIFY_PROVIDER, f"{client_id}:{client_secret}")


def spotify_oauth_manager(*, state: str | None = None, scopes: list[str] | None = None) -> SpotifyOAuth:
    """Coordinates spotify oauth manager for the current Sonex flow.

    Typical use: Use this function when runtime code needs spotify oauth manager as part of a Sonex command, playback, auth, llm, or ui path.

    Example: spotify_oauth_manager(state=..., scopes=...) -> returns the value used by the surrounding Sonex flow.
    """
    client_id, client_secret = spotify_app_credentials()
    return SpotifyOAuth(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=spotify_redirect_uri(),
        state=state,
        scope=" ".join(scopes or spotify_scopes()),
        open_browser=False,
        cache_handler=_NoopCacheHandler(),
    )


def spotify_app_client() -> spotipy.Spotify:
    """Coordinates spotify app client for the current Sonex flow.

    Typical use: Use this function when runtime code needs spotify app client as part of a Sonex command, playback, auth, llm, or ui path.

    Example: spotify_app_client() -> returns the value used by the surrounding Sonex flow.
    """
    client_id, client_secret = spotify_app_credentials()
    return spotipy.Spotify(
        auth_manager=SpotifyClientCredentials(
            client_id=client_id,
            client_secret=client_secret,
        )
    )


def _iso_from_epoch(expires_at: int | float | None) -> str | None:
    """Prepares iso from epoch for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs iso from epoch without duplicating the local rules.

    Example: _iso_from_epoch(expires_at=...) -> returns the value used by the surrounding Sonex flow.
    """
    if not expires_at:
        return None
    return datetime.fromtimestamp(float(expires_at), timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00",
        "Z",
    )


def save_spotify_token_info(token_info: dict[str, Any]) -> None:
    """Persists spotify token info for later use.

    Typical use: Use this function when runtime code needs save spotify token info as part of a Sonex command, playback, auth, llm, or ui path.

    Example: save_spotify_token_info(token_info=...) -> returns the value used by the surrounding Sonex flow.
    """
    access_token = str(token_info.get("access_token") or "")
    if not access_token:
        raise SpotifyAuthError("Spotify did not return an access token.")

    scope_value = token_info.get("scope") or ""
    scopes = [scope for scope in str(scope_value).replace(",", " ").split() if scope]
    token = OAuthToken(
        access_token=access_token,
        refresh_token=token_info.get("refresh_token"),
        expires_at=_iso_from_epoch(token_info.get("expires_at")),
        scopes=scopes,
    )
    set_oauth_token(SPOTIFY_PROVIDER, token)


def load_spotify_token() -> OAuthToken | None:
    """Loads spotify token from persistent state.

    Typical use: Use this function when runtime code needs load spotify token as part of a Sonex command, playback, auth, llm, or ui path.

    Example: load_spotify_token() -> returns the value used by the surrounding Sonex flow.
    """
    provider = get_provider_auth(load_auth_store(), SPOTIFY_PROVIDER)
    return provider.oauth if provider else None


def _is_expired(token: OAuthToken) -> bool:
    """Prepares is expired for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs is expired without duplicating the local rules.

    Example: _is_expired(token=...) -> returns the value used by the surrounding Sonex flow.
    """
    if not token.expires_at:
        return False
    try:
        expires_at = datetime.fromisoformat(token.expires_at.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return True
    return expires_at <= time.time() + 60


def refresh_spotify_token(token: OAuthToken) -> OAuthToken:
    """Coordinates refresh spotify token for the current Sonex flow.

    Typical use: Use this function when runtime code needs refresh spotify token as part of a Sonex command, playback, auth, llm, or ui path.

    Example: refresh_spotify_token(token=...) -> returns the value used by the surrounding Sonex flow.
    """
    if not token.refresh_token:
        raise SpotifyLoginRequiredError("Spotify token expired and no refresh token is available.")

    oauth = spotify_oauth_manager(scopes=token.scopes or spotify_scopes())
    token_info = oauth.refresh_access_token(token.refresh_token)
    if token.refresh_token and not token_info.get("refresh_token"):
        token_info["refresh_token"] = token.refresh_token
    save_spotify_token_info(token_info)
    refreshed = load_spotify_token()
    if not refreshed:
        raise SpotifyLoginRequiredError("Spotify token refresh failed.")
    return refreshed


def ensure_spotify_token(required_scopes: set[str] | None = None) -> OAuthToken:
    """Coordinates ensure spotify token for the current Sonex flow.

    Typical use: Use this function when runtime code needs ensure spotify token as part of a Sonex command, playback, auth, llm, or ui path.

    Example: ensure_spotify_token(required_scopes=...) -> returns the value used by the surrounding Sonex flow.
    """
    token = load_spotify_token()
    if not token or not token.access_token:
        raise SpotifyLoginRequiredError("Run `sonex auth login spotify` to connect your Spotify account.")
    if _is_expired(token):
        token = refresh_spotify_token(token)

    missing = (required_scopes or set()) - set(token.scopes)
    if missing:
        raise SpotifyScopeMissingError(missing)
    return token


def spotify_user_client(
    required_scopes: set[str] | None = None,
    *,
    requests_timeout: float | None = None,
    retries: int | None = None,
) -> spotipy.Spotify:
    """Coordinates spotify user client for the current Sonex flow.

    Typical use: Use this function when runtime code needs spotify user client as part of a Sonex command, playback, auth, llm, or ui path.

    Example: spotify_user_client(required_scopes=...) -> returns the value used by the surrounding Sonex flow.
    """
    token = ensure_spotify_token(required_scopes)
    kwargs: dict[str, object] = {"auth": token.access_token}
    if requests_timeout is not None:
        kwargs["requests_timeout"] = requests_timeout
    if retries is not None:
        kwargs["retries"] = retries
    return spotipy.Spotify(**kwargs)


def spotify_authorize_url() -> tuple[str, str]:
    """Coordinates spotify authorize url for the current Sonex flow.

    Typical use: Use this function when runtime code needs spotify authorize url as part of a Sonex command, playback, auth, llm, or ui path.

    Example: spotify_authorize_url() -> returns the value used by the surrounding Sonex flow.
    """
    state = secrets.token_urlsafe(24)
    oauth = spotify_oauth_manager(state=state)
    return oauth.get_authorize_url(state=state), state
