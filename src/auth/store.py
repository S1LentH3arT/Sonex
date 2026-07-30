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
    """Coordinates auth store path for the current Sonex flow.

    Typical use: Use this function when runtime code needs auth store path as part of a Sonex command, playback, auth, llm, or ui path.

    Example: auth_store_path() -> returns the value used by the surrounding Sonex flow.
    """
    return sonex_home() / "auth.json"


def utc_now_iso() -> str:
    """Coordinates utc now iso for the current Sonex flow.

    Typical use: Use this function when runtime code needs utc now iso as part of a Sonex command, playback, auth, llm, or ui path.

    Example: utc_now_iso() -> returns the value used by the surrounding Sonex flow.
    """
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_auth_store(path: Path | None = None) -> AuthStore:
    """Loads auth store from persistent state.

    Typical use: Use this function when runtime code needs load auth store as part of a Sonex command, playback, auth, llm, or ui path.

    Example: load_auth_store(path=...) -> returns the value used by the surrounding Sonex flow.
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
    """Persists auth store for later use.

    Typical use: Use this function when runtime code needs save auth store as part of a Sonex command, playback, auth, llm, or ui path.

    Example: save_auth_store(store=..., path=...) -> returns the value used by the surrounding Sonex flow.
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
    """Returns provider auth for the current Sonex flow.

    Typical use: Use this function when runtime code needs get provider auth as part of a Sonex command, playback, auth, llm, or ui path.

    Example: get_provider_auth(store=..., provider=...) -> returns the value used by the surrounding Sonex flow.
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
    """Coordinates set api key for the current Sonex flow.

    Typical use: Use this function when runtime code needs set api key as part of a Sonex command, playback, auth, llm, or ui path.

    Example: set_api_key(provider=..., api_key=..., model=..., base_url=..., custom_llm_provider=..., path=...) -> returns the value used by the surrounding Sonex flow.
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
    """Coordinates set provider config for the current Sonex flow.

    Typical use: Use this function when runtime code needs set provider config as part of a Sonex command, playback, auth, llm, or ui path.

    Example: set_provider_config(provider=..., model=..., base_url=..., custom_llm_provider=..., path=...) -> returns the value used by the surrounding Sonex flow.
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
    """Coordinates set oauth token for the current Sonex flow.

    Typical use: Use this function when runtime code needs set oauth token as part of a Sonex command, playback, auth, llm, or ui path.

    Example: set_oauth_token(provider=..., token=..., model=..., base_url=..., path=...) -> returns the value used by the surrounding Sonex flow.
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
    """Coordinates remove provider for the current Sonex flow.

    Typical use: Use this function when runtime code needs remove provider as part of a Sonex command, playback, auth, llm, or ui path.

    Example: remove_provider(provider=..., path=...) -> returns the value used by the surrounding Sonex flow.
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
    """Coordinates set default for the current Sonex flow.

    Typical use: Use this function when runtime code needs set default as part of a Sonex command, playback, auth, llm, or ui path.

    Example: set_default(provider=..., model=..., path=...) -> returns the value used by the surrounding Sonex flow.
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
    """Coordinates redacted for the current Sonex flow.

    Typical use: Use this function when runtime code needs redacted as part of a Sonex command, playback, auth, llm, or ui path.

    Example: redacted(value=..., visible=...) -> returns the value used by the surrounding Sonex flow.
    """
    if not value:
        return "-"
    if len(value) <= visible * 2:
        return "*" * len(value)
    return f"{value[:visible]}...{value[-visible:]}"


def provider_to_public_dict(provider: ProviderAuth) -> dict[str, Any]:
    """Coordinates provider to public dict for the current Sonex flow.

    Typical use: Use this function when runtime code needs provider to public dict as part of a Sonex command, playback, auth, llm, or ui path.

    Example: provider_to_public_dict(provider=...) -> returns the value used by the surrounding Sonex flow.
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
