"""Oauth support for provider authentication and credential persistence.

Implements the oauth module responsibilities used by Sonex runtime flows.
Key public entry points include OAuthUnsupportedError, OAuthTokenExpiredError, provider_supports_oauth, save_oauth_token, ensure_oauth_token_usable.
"""

from __future__ import annotations

from datetime import datetime, timezone

from src.auth.models import OAuthToken
from src.auth.providers import get_provider_capability, normalize_provider
from src.auth.store import set_oauth_token

_ACCESS_TOKEN_CACHE: dict[str, OAuthToken] = {}


class OAuthUnsupportedError(RuntimeError):
    """Represents oauth unsupported error.

    Encapsulates oauth unsupported error data and behavior used by Sonex runtime flows. Extends runtime error semantics.
    """
    pass


class OAuthTokenExpiredError(RuntimeError):
    """Represents oauth token expired error.

    Encapsulates oauth token expired error data and behavior used by Sonex runtime flows. Extends runtime error semantics.
    """
    pass


def provider_supports_oauth(provider: str) -> bool:
    """Coordinates provider supports oauth for the current Sonex flow.

    Typical use: Use this function when runtime code needs provider supports oauth as part of a Sonex command, playback, auth, llm, or ui path.

    Example: provider_supports_oauth(provider=...) -> returns the value used by the surrounding Sonex flow.
    """
    return get_provider_capability(provider).supports_oauth


def save_oauth_token(
    provider: str,
    *,
    access_token: str,
    refresh_token: str | None = None,
    expires_at: str | None = None,
    scopes: list[str] | None = None,
    model: str | None = None,
    base_url: str | None = None,
    project_id: str | None = None,
) -> None:
    """Persists oauth token for later use.

    Typical use: Use this function when runtime code needs save oauth token as part of a Sonex command, playback, auth, llm, or ui path.

    Example: save_oauth_token(provider=..., access_token=..., refresh_token=..., expires_at=..., scopes=..., model=..., base_url=...) -> returns the value used by the surrounding Sonex flow.
    """
    name = normalize_provider(provider)
    if not provider_supports_oauth(name):
        raise OAuthUnsupportedError(
            f"Provider '{name}' does not support OAuth in Sonex yet. Use API key login instead."
        )
    token = OAuthToken(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=expires_at,
        scopes=scopes or [],
    )
    _ACCESS_TOKEN_CACHE[name] = token
    set_oauth_token(
        name,
        token,
        model=model,
        base_url=base_url,
        project_id=project_id,
    )


def ensure_oauth_token_usable(
    provider: str,
    token: OAuthToken,
    *,
    project_id: str | None = None,
) -> OAuthToken:
    """Coordinates ensure oauth token usable for the current Sonex flow.

    Typical use: Use this function when runtime code needs ensure oauth token usable as part of a Sonex command, playback, auth, llm, or ui path.

    Example: ensure_oauth_token_usable(provider=..., token=...) -> returns the value used by the surrounding Sonex flow.
    """
    name = normalize_provider(provider)
    cached = _ACCESS_TOKEN_CACHE.get(name)
    if not token.access_token and cached and cached.access_token:
        token.access_token = cached.access_token
        token.expires_at = cached.expires_at
        token.scopes = cached.scopes
    expired = False
    if not token.access_token:
        expired = True
    if not token.expires_at and not expired:
        return token
    try:
        expires_at = (
            datetime.fromisoformat(token.expires_at.replace("Z", "+00:00"))
            if token.expires_at
            else None
        )
    except ValueError as exc:
        raise OAuthTokenExpiredError(
            f"OAuth token for provider '{provider}' has an invalid expires_at value. Open /login and reconnect it."
        ) from exc
    if expires_at is not None and expires_at <= datetime.now(timezone.utc):
        expired = True
    if not expired:
        return token
    if token.refresh_token and name == "gemini":
        try:
            from src.auth.browser_oauth import refresh_browser_oauth_token

            refreshed = refresh_browser_oauth_token(provider, token, project_id=project_id)
            _ACCESS_TOKEN_CACHE[name] = refreshed
            return refreshed
        except Exception as exc:
            raise OAuthTokenExpiredError(
                "Google OAuth access expired and refresh failed. Open /login and reconnect Google Gemini."
            ) from exc
    if not token.access_token:
        raise OAuthTokenExpiredError(
            f"OAuth token for provider '{provider}' is missing. Open /login and reconnect it."
        )
    if expired:
        raise OAuthTokenExpiredError(
            f"OAuth token for provider '{provider}' has expired. Open /login and reconnect it."
        )
    return token


def clear_oauth_access_cache(provider: str) -> None:
    """Forget an in-memory OAuth access token."""
    _ACCESS_TOKEN_CACHE.pop(normalize_provider(provider), None)
