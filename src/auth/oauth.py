from __future__ import annotations

from datetime import datetime, timezone

from src.auth.models import OAuthToken
from src.auth.providers import get_provider_capability, normalize_provider
from src.auth.store import set_oauth_token


class OAuthUnsupportedError(RuntimeError):
    pass


class OAuthTokenExpiredError(RuntimeError):
    pass


def provider_supports_oauth(provider: str) -> bool:
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
