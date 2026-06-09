"""Oauth support for provider authentication and credential persistence.

Implements the oauth module responsibilities used by Sonex runtime flows.
Key public entry points include OAuthUnsupportedError, OAuthTokenExpiredError, provider_supports_oauth, save_oauth_token, ensure_oauth_token_usable.
"""

from __future__ import annotations

from datetime import datetime, timezone

from src.auth.models import OAuthToken
from src.auth.providers import get_provider_capability, normalize_provider
from src.auth.store import set_oauth_token


class OAuthUnsupportedError(RuntimeError):
    """Represents o auth unsupported error.

    Encapsulates o auth unsupported error data and behavior used by Sonex runtime flows. Extends runtime error semantics.
    """
    pass


class OAuthTokenExpiredError(RuntimeError):
    """Represents o auth token expired error.

    Encapsulates o auth token expired error data and behavior used by Sonex runtime flows. Extends runtime error semantics.
    """
    pass


def provider_supports_oauth(provider: str) -> bool:
    """Provider supports oauth.

    Coordinates provider supports oauth logic for the surrounding Sonex flow.

    Args:
        provider: Input value used by the provider supports oauth operation.

    Returns:
        The computed result for provider supports oauth.
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
) -> None:
    """Save oauth token.

    Coordinates save oauth token logic for the surrounding Sonex flow.

    Args:
        provider: Input value used by the save oauth token operation.
        access_token: Input value used by the save oauth token operation.
        refresh_token: Input value used by the save oauth token operation.
        expires_at: Input value used by the save oauth token operation.
        scopes: Input value used by the save oauth token operation.
        model: Input value used by the save oauth token operation.
        base_url: Input value used by the save oauth token operation.

    Returns:
        The computed result for save oauth token.
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
    set_oauth_token(name, token, model=model, base_url=base_url)


def ensure_oauth_token_usable(provider: str, token: OAuthToken) -> None:
    """Ensure oauth token usable.

    Coordinates ensure oauth token usable logic for the surrounding Sonex flow.

    Args:
        provider: Input value used by the ensure oauth token usable operation.
        token: Input value used by the ensure oauth token usable operation.

    Returns:
        The computed result for ensure oauth token usable.
    """
    if not token.access_token:
        raise OAuthTokenExpiredError(
            f"OAuth token for provider '{provider}' is missing. Run `sonex auth login {provider}` again."
        )
    if not token.expires_at:
        return
    try:
        expires_at = datetime.fromisoformat(token.expires_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise OAuthTokenExpiredError(
            f"OAuth token for provider '{provider}' has an invalid expires_at value. Run `sonex auth login {provider}` again."
        ) from exc
    if expires_at <= datetime.now(timezone.utc):
        raise OAuthTokenExpiredError(
            f"OAuth token for provider '{provider}' has expired. Run `sonex auth login {provider}` again."
        )
