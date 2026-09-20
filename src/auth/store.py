"""Store support for provider authentication and credential persistence.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.auth.models import AuthStore, OAuthToken, ProviderAuth
from src.auth.providers import normalize_provider, normalize_provider_model
from src.auth.secure_store import delete_refresh_token, load_refresh_token, store_refresh_token
from src.log import sonex_home


_RETIRED_PROVIDER_NAMES = frozenset({"apple_music", "apple_mode"})


class AuthStoreError(RuntimeError):
    pass


def auth_store_path() -> Path:
    return sonex_home() / "auth.json"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_auth_store(path: Path | None = None) -> AuthStore:
    resolved = path or auth_store_path()
    if not resolved.exists():
        return AuthStore()
    try:
        with resolved.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        raise AuthStoreError(f"Invalid auth store JSON at {resolved}: {exc}") from exc
    except OSError as exc:
        raise AuthStoreError(f"Could not read auth store at {resolved}: {exc}") from exc
    if not isinstance(data, dict):
        raise AuthStoreError(f"Invalid auth store at {resolved}: expected a JSON object.")
    store = AuthStore.from_dict(data)
    for provider in store.providers.values():
        if provider.oauth and provider.oauth.refresh_token_ref:
            provider.oauth.refresh_token = load_refresh_token(provider.oauth.refresh_token_ref)
    retired = [
        store.providers.pop(name)
        for name in _RETIRED_PROVIDER_NAMES
        if name in store.providers
    ]
    retired_default = store.default_provider in _RETIRED_PROVIDER_NAMES
    if retired:
        for provider in retired:
            if provider.oauth:
                delete_refresh_token(provider.oauth.refresh_token_ref)
    if retired_default:
        store.default_provider = None
        store.default_model = None
    if retired or retired_default:
        save_auth_store(store, resolved)
    return store


def save_auth_store(store: AuthStore, path: Path | None = None) -> Path:
    resolved = path or auth_store_path()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    tmp = resolved.with_suffix(f"{resolved.suffix}.tmp")
    try:
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(store.to_dict(), f, indent=2, ensure_ascii=True)
            f.write("\n")
        os.chmod(tmp, 0o600)
        tmp.replace(resolved)
        os.chmod(resolved, 0o600)
    except OSError as exc:
        raise AuthStoreError(f"Could not write auth store at {resolved}: {exc}") from exc
    return resolved


def get_provider_auth(store: AuthStore, provider: str) -> ProviderAuth | None:
    return store.providers.get(normalize_provider(provider))


def set_api_key(
    provider: str,
    api_key: str,
    *,
    model: str | None = None,
    base_url: str | None = None,
    custom_llm_provider: str | None = None,
    path: Path | None = None,
) -> Path:
    store = load_auth_store(path)
    name = normalize_provider(provider)
    current = store.providers.get(name) or ProviderAuth(name=name)
    current.auth_method = "api_key"
    current.api_key = api_key
    current.oauth = current.oauth
    current.model = normalize_provider_model(name, model or current.model)
    current.base_url = base_url if base_url is not None else current.base_url
    current.custom_llm_provider = custom_llm_provider or current.custom_llm_provider
    current.updated_at = utc_now_iso()
    store.providers[name] = current
    return save_auth_store(store, path)


def set_provider_config(
    provider: str,
    *,
    model: str | None = None,
    base_url: str | None = None,
    custom_llm_provider: str | None = None,
    path: Path | None = None,
) -> Path:
    store = load_auth_store(path)
    name = normalize_provider(provider)
    current = store.providers.get(name) or ProviderAuth(name=name)
    current.auth_method = "none"
    current.model = normalize_provider_model(name, model or current.model)
    current.base_url = base_url if base_url is not None else current.base_url
    current.custom_llm_provider = custom_llm_provider or current.custom_llm_provider
    current.updated_at = utc_now_iso()
    store.providers[name] = current
    return save_auth_store(store, path)


def set_custom_profile(
    profile_id: str,
    *,
    display_name: str,
    base_url: str,
    model: str,
    api_key: str | None = None,
    model_ids: list[str] | None = None,
    needs_review: bool = False,
    allow_insecure_http: bool = False,
    timeout: float | None = None,
    path: Path | None = None,
) -> Path:
    """Create or replace a named OpenAI-compatible Custom connection."""
    name = normalize_provider(profile_id)
    if not name.startswith("custom__"):
        raise AuthStoreError("Custom profile IDs must start with 'custom__'.")
    store = load_auth_store(path)
    current = store.providers.get(name) or ProviderAuth(name=name)
    current.auth_method = "api_key" if api_key else "none"
    current.api_key = api_key
    current.oauth = None
    current.model = model.strip()
    current.base_url = base_url.strip()
    current.custom_llm_provider = "openai"
    current.display_name = display_name.strip()
    current.model_ids = list(dict.fromkeys(
        item.strip() for item in (model_ids or [model]) if item.strip()
    ))
    current.needs_review = needs_review
    current.allow_insecure_http = allow_insecure_http
    current.timeout = timeout
    current.updated_at = utc_now_iso()
    store.providers[name] = current
    return save_auth_store(store, path)


def set_oauth_token(
    provider: str,
    token: OAuthToken,
    *,
    model: str | None = None,
    base_url: str | None = None,
    project_id: str | None = None,
    path: Path | None = None,
) -> Path:
    store = load_auth_store(path)
    name = normalize_provider(provider)
    current = store.providers.get(name) or ProviderAuth(name=name)
    current.auth_method = "oauth"
    if name == "gemini" and token.refresh_token:
        token.refresh_token_ref = store_refresh_token(name, token.refresh_token)
    elif name == "gemini" and current.oauth and current.oauth.refresh_token_ref:
        token.refresh_token = current.oauth.refresh_token
        token.refresh_token_ref = current.oauth.refresh_token_ref
    current.oauth = token
    current.model = normalize_provider_model(name, model or current.model)
    current.base_url = base_url if base_url is not None else current.base_url
    current.project_id = project_id if project_id is not None else current.project_id
    current.updated_at = utc_now_iso()
    store.providers[name] = current
    return save_auth_store(store, path)


def set_managed_auth(
    provider: str,
    managed_auth: str,
    *,
    model: str | None = None,
    path: Path | None = None,
) -> Path:
    """Activate a provider credential lifecycle owned by an isolated runtime."""
    store = load_auth_store(path)
    name = normalize_provider(provider)
    current = store.providers.get(name) or ProviderAuth(name=name)
    current.auth_method = "oauth"
    current.managed_auth = managed_auth
    current.model = normalize_provider_model(name, model or current.model)
    current.updated_at = utc_now_iso()
    store.providers[name] = current
    return save_auth_store(store, path)


def set_experimental_confirmation(
    provider: str,
    confirmed: bool = True,
    *,
    path: Path | None = None,
) -> Path:
    """Remember a provider-scoped one-time experimental feature confirmation."""
    store = load_auth_store(path)
    name = normalize_provider(provider)
    current = store.providers.get(name) or ProviderAuth(name=name)
    current.experimental_confirmed = confirmed
    current.updated_at = utc_now_iso()
    store.providers[name] = current
    return save_auth_store(store, path)


def remove_provider_method(
    provider: str,
    method: str,
    *,
    path: Path | None = None,
) -> bool:
    """Disconnect one auth method while preserving other provider credentials."""
    store = load_auth_store(path)
    name = normalize_provider(provider)
    current = store.providers.get(name)
    if current is None:
        return False
    removed = False
    if method == "api_key":
        removed = current.api_key is not None
        current.api_key = None
        current.auth_method = "api_key"
    elif method == "oauth":
        removed = current.oauth is not None or current.managed_auth is not None
        if current.oauth:
            delete_refresh_token(current.oauth.refresh_token_ref)
        current.oauth = None
        current.managed_auth = None
        current.auth_method = "oauth"
    else:
        raise AuthStoreError(f"Unsupported auth method '{method}'.")
    current.updated_at = utc_now_iso()
    store.providers[name] = current
    save_auth_store(store, path)
    return removed


def remove_provider(provider: str, *, path: Path | None = None) -> bool:
    store = load_auth_store(path)
    name = normalize_provider(provider)
    provider_auth = store.providers.pop(name, None)
    removed = provider_auth is not None
    if provider_auth and provider_auth.oauth:
        delete_refresh_token(provider_auth.oauth.refresh_token_ref)
    if store.default_provider == name:
        store.default_provider = None
        store.default_model = None
    save_auth_store(store, path)
    return removed


def set_default(provider: str, model: str | None = None, *, path: Path | None = None) -> Path:
    store = load_auth_store(path)
    store.default_provider = normalize_provider(provider)
    if model:
        store.default_model = normalize_provider_model(store.default_provider, model)
        current = store.providers.get(store.default_provider) or ProviderAuth(name=store.default_provider)
        current.model = store.default_model
        current.updated_at = utc_now_iso()
        store.providers[store.default_provider] = current
    return save_auth_store(store, path)


def clear_default(*, path: Path | None = None) -> Path:
    """Clear automatic provider/model selection without deleting credentials."""
    store = load_auth_store(path)
    store.default_provider = None
    store.default_model = None
    return save_auth_store(store, path)


def redacted(value: str | None, *, visible: int = 4) -> str:
    if not value:
        return "-"
    if len(value) <= visible * 2:
        return "*" * len(value)
    return f"{value[:visible]}...{value[-visible:]}"


def provider_to_public_dict(provider: ProviderAuth) -> dict[str, Any]:
    return {
        "provider": provider.name,
        "auth_method": provider.auth_method,
        "api_key": redacted(provider.api_key),
        "oauth": "configured" if provider.oauth else "-",
        "model": provider.model or "-",
        "base_url": provider.base_url or "-",
        "updated_at": provider.updated_at or "-",
    }
