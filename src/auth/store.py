"""Store support for provider authentication and credential persistence.

Implements the store module responsibilities used by Sonex runtime flows.
Key public entry points include AuthStoreError, auth_store_path, utc_now_iso, load_auth_store, save_auth_store.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.auth.models import AuthStore, OAuthToken, ProviderAuth
from src.auth.providers import normalize_provider, normalize_provider_model
from src.log import sonex_home


class AuthStoreError(RuntimeError):
    """Represents auth store error.

    Encapsulates auth store error data and behavior used by Sonex runtime flows. Extends runtime error semantics.
    """
    pass


def auth_store_path() -> Path:
    """Auth store path.

    Coordinates auth store path logic for the surrounding Sonex flow.

    Returns:
        The computed result for auth store path.
    """
    return sonex_home() / "auth.json"


def utc_now_iso() -> str:
    """Utc now iso.

    Coordinates utc now iso logic for the surrounding Sonex flow.

    Returns:
        The computed result for utc now iso.
    """
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_auth_store(path: Path | None = None) -> AuthStore:
    """Load auth store.

    Coordinates load auth store logic for the surrounding Sonex flow.

    Args:
        path: Input value used by the load auth store operation.

    Returns:
        The computed result for load auth store.
    """
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
    return AuthStore.from_dict(data)


def save_auth_store(store: AuthStore, path: Path | None = None) -> Path:
    """Save auth store.

    Coordinates save auth store logic for the surrounding Sonex flow.

    Args:
        store: Input value used by the save auth store operation.
        path: Input value used by the save auth store operation.

    Returns:
        The computed result for save auth store.
    """
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
    """Get provider auth.

    Coordinates get provider auth logic for the surrounding Sonex flow.

    Args:
        store: Input value used by the get provider auth operation.
        provider: Input value used by the get provider auth operation.

    Returns:
        The computed result for get provider auth.
    """
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
    """Set api key.

    Coordinates set api key logic for the surrounding Sonex flow.

    Args:
        provider: Input value used by the set api key operation.
        api_key: Input value used by the set api key operation.
        model: Input value used by the set api key operation.
        base_url: Input value used by the set api key operation.
        custom_llm_provider: Input value used by the set api key operation.
        path: Input value used by the set api key operation.

    Returns:
        The computed result for set api key.
    """
    store = load_auth_store(path)
    name = normalize_provider(provider)
    current = store.providers.get(name) or ProviderAuth(name=name)
    current.auth_method = "api_key"
    current.api_key = api_key
    current.oauth = current.oauth if current.oauth and name in {"gemini", "spotify", "apple_music"} else None
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
    """Set provider config.

    Coordinates set provider config logic for the surrounding Sonex flow.

    Args:
        provider: Input value used by the set provider config operation.
        model: Input value used by the set provider config operation.
        base_url: Input value used by the set provider config operation.
        custom_llm_provider: Input value used by the set provider config operation.
        path: Input value used by the set provider config operation.

    Returns:
        The computed result for set provider config.
    """
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


def set_oauth_token(
    provider: str,
    token: OAuthToken,
    *,
    model: str | None = None,
    base_url: str | None = None,
    path: Path | None = None,
) -> Path:
    """Set oauth token.

    Coordinates set oauth token logic for the surrounding Sonex flow.

    Args:
        provider: Input value used by the set oauth token operation.
        token: Input value used by the set oauth token operation.
        model: Input value used by the set oauth token operation.
        base_url: Input value used by the set oauth token operation.
        path: Input value used by the set oauth token operation.

    Returns:
        The computed result for set oauth token.
    """
    store = load_auth_store(path)
    name = normalize_provider(provider)
    current = store.providers.get(name) or ProviderAuth(name=name)
    current.auth_method = "oauth"
    current.oauth = token
    current.model = normalize_provider_model(name, model or current.model)
    current.base_url = base_url if base_url is not None else current.base_url
    current.updated_at = utc_now_iso()
    store.providers[name] = current
    return save_auth_store(store, path)


def remove_provider(provider: str, *, path: Path | None = None) -> bool:
    """Remove provider.

    Coordinates remove provider logic for the surrounding Sonex flow.

    Args:
        provider: Input value used by the remove provider operation.
        path: Input value used by the remove provider operation.

    Returns:
        The computed result for remove provider.
    """
    store = load_auth_store(path)
    name = normalize_provider(provider)
    removed = store.providers.pop(name, None) is not None
    if store.default_provider == name:
        store.default_provider = None
        store.default_model = None
    save_auth_store(store, path)
    return removed


def set_default(provider: str, model: str | None = None, *, path: Path | None = None) -> Path:
    """Set default.

    Coordinates set default logic for the surrounding Sonex flow.

    Args:
        provider: Input value used by the set default operation.
        model: Input value used by the set default operation.
        path: Input value used by the set default operation.

    Returns:
        The computed result for set default.
    """
    store = load_auth_store(path)
    store.default_provider = normalize_provider(provider)
    if model:
        store.default_model = normalize_provider_model(store.default_provider, model)
        current = store.providers.get(store.default_provider) or ProviderAuth(name=store.default_provider)
        current.model = store.default_model
        current.updated_at = utc_now_iso()
        store.providers[store.default_provider] = current
    return save_auth_store(store, path)


def redacted(value: str | None, *, visible: int = 4) -> str:
    """Redacted.

    Coordinates redacted logic for the surrounding Sonex flow.

    Args:
        value: Input value used by the redacted operation.
        visible: Input value used by the redacted operation.

    Returns:
        The computed result for redacted.
    """
    if not value:
        return "-"
    if len(value) <= visible * 2:
        return "*" * len(value)
    return f"{value[:visible]}...{value[-visible:]}"


def provider_to_public_dict(provider: ProviderAuth) -> dict[str, Any]:
    """Provider to public dict.

    Coordinates provider to public dict logic for the surrounding Sonex flow.

    Args:
        provider: Input value used by the provider to public dict operation.

    Returns:
        The computed result for provider to public dict.
    """
    return {
        "provider": provider.name,
        "auth_method": provider.auth_method,
        "api_key": redacted(provider.api_key),
        "oauth": "configured" if provider.oauth else "-",
        "model": provider.model or "-",
        "base_url": provider.base_url or "-",
        "updated_at": provider.updated_at or "-",
    }
