"""Config support for runtime model and provider configuration.

Implements the config module responsibilities used by Sonex runtime flows.
Key public entry points include ThinkingRuntimeState, ThinkingConfig.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from src.auth.oauth import ensure_oauth_token_usable
from src.auth.providers import get_provider_capability, normalize_provider, normalize_provider_model, provider_names
from src.auth.store import AuthStoreError, get_provider_auth, load_auth_store
from src.llm import RuntimeConfig, ProviderConfig
from src.llm.client import ProviderClient
from src.log import sonex_home


@dataclass(slots=True)
class ThinkingRuntimeState:
    """Represents thinking runtime state.

    Encapsulates thinking runtime state data and behavior used by Sonex runtime flows.
    """
    config_path: Path
    runtime_config: RuntimeConfig
    client: ProviderClient


class ThinkingConfig:
    """Represents thinking config.

    Encapsulates thinking config data and behavior used by Sonex runtime flows.
    """
    _state: ThinkingRuntimeState | None = None

    @classmethod
    def init(cls, model: str | None = None, config_path: Path | None = None) -> "ThinkingConfig":
        """Coordinates init for the current Sonex flow.

        Typical use: Use this function when runtime code needs init as part of a Sonex command, playback, auth, llm, or ui path.

        Example: init(model=..., config_path=...) -> returns the value used by the surrounding Sonex flow.
        """
        cls.reload(model=model, config_path=config_path)
        return cls

    @classmethod
    def reload(cls, model: str | None = None, config_path: Path | None = None) -> None:
        """Coordinates reload for the current Sonex flow.

        Typical use: Use this function when runtime code needs reload as part of a Sonex command, playback, auth, llm, or ui path.

        Example: reload(model=..., config_path=...) -> returns the value used by the surrounding Sonex flow.
        """
        _load_env_files()
        resolved_path = config_path or _default_config_path()
        runtime_config = _build_runtime_config(model_override=model, config_path=resolved_path)
        cls._state = ThinkingRuntimeState(
            config_path=resolved_path,
            runtime_config=runtime_config,
            client=ProviderClient(runtime_config=runtime_config),
        )

    @classmethod
    def get_client(cls) -> ProviderClient:
        """Returns client for the current Sonex flow.

        Typical use: Use this function when runtime code needs get client as part of a Sonex command, playback, auth, llm, or ui path.

        Example: get_client() -> returns the value used by the surrounding Sonex flow.
        """
        if cls._state is None:
            cls.reload()
        return cls._state.client

    @classmethod
    def get_runtime_config(cls) -> RuntimeConfig:
        """Returns runtime config for the current Sonex flow.

        Typical use: Use this function when runtime code needs get runtime config as part of a Sonex command, playback, auth, llm, or ui path.

        Example: get_runtime_config() -> returns the value used by the surrounding Sonex flow.
        """
        if cls._state is None:
            cls.reload()
        return cls._state.runtime_config

    @classmethod
    def get_provider(cls) -> str:
        """Returns provider for the current Sonex flow.

        Typical use: Use this function when runtime code needs get provider as part of a Sonex command, playback, auth, llm, or ui path.

        Example: get_provider() -> returns the value used by the surrounding Sonex flow.
        """
        return cls.get_runtime_config().default_provider

    @classmethod
    def get_model(cls) -> str:
        """Returns model for the current Sonex flow.

        Typical use: Use this function when runtime code needs get model as part of a Sonex command, playback, auth, llm, or ui path.

        Example: get_model() -> returns the value used by the surrounding Sonex flow.
        """
        return cls.get_runtime_config().default_model

    @classmethod
    def get_provider_config(cls, provider: str | None = None) -> ProviderConfig:
        """Returns provider config for the current Sonex flow.

        Typical use: Use this function when runtime code needs get provider config as part of a Sonex command, playback, auth, llm, or ui path.

        Example: get_provider_config(provider=...) -> returns the value used by the surrounding Sonex flow.
        """
        runtime = cls.get_runtime_config()
        return runtime.get_provider(provider)


def _default_config_path() -> Path:
    """Prepares default config path for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs default config path without duplicating the local rules.

    Example: _default_config_path() -> returns the value used by the surrounding Sonex flow.
    """
    custom = os.getenv("SONEX_CONFIG_PATH")
    if custom:
        return Path(custom).expanduser()
    return sonex_home() / "thinking.json"


def _load_config_file(path: Path) -> dict[str, Any]:
    """Prepares load config file for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs load config file without duplicating the local rules.

    Example: _load_config_file(path=...) -> returns the value used by the surrounding Sonex flow.
    """
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _save_config_file(path: Path, data: dict[str, Any]) -> None:
    """Prepares save config file for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs save config file without duplicating the local rules.

    Example: _save_config_file(path=..., data=...) -> returns the value used by the surrounding Sonex flow.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=True)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _load_env_files() -> None:
    """Prepares load env files for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs load env files without duplicating the local rules.

    Example: _load_env_files() -> returns the value used by the surrounding Sonex flow.
    """
    load_dotenv(override=False)


def _build_runtime_config(model_override: str | None, config_path: Path) -> RuntimeConfig:
    """Prepares build runtime config for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs build runtime config without duplicating the local rules.

    Example: _build_runtime_config(model_override=..., config_path=...) -> returns the value used by the surrounding Sonex flow.
    """
    file_config = _load_config_file(config_path)
    file_providers = file_config.get("providers") or {}
    auth_store = load_auth_store()

    default_provider = normalize_provider(str(
        os.getenv("SONEX_DEFAULT_PROVIDER")
        or os.getenv("SONEX_PROVIDER")
        or auth_store.default_provider
        or file_config.get("default_provider")
        or "openai"
    ))
    default_model = normalize_provider_model(
        default_provider,
        model_override
        or os.getenv("SONEX_DEFAULT_MODEL")
        or os.getenv("SONEX_MODEL")
        or auth_store.default_model
        or file_config.get("default_model")
        or _provider_default_model(default_provider)
        or "gpt-5.5",
    )

    provider_name_set = {*provider_names(), *file_providers.keys(), *auth_store.providers.keys(), default_provider}
    providers: dict[str, ProviderConfig] = {}
    for name in sorted(provider_name_set):
        providers[name] = _build_provider_config(
            name=name,
            file_config=file_providers.get(name) or {},
            auth_config=get_provider_auth(auth_store, name),
            default_model=default_model,
            is_default=(name == default_provider),
        )

    return RuntimeConfig(
        default_provider=default_provider,
        default_model=default_model,
        providers=providers,
    )


def _build_provider_config(
    *,
    name: str,
    file_config: dict[str, Any],
    auth_config: Any,
    default_model: str,
    is_default: bool,
) -> ProviderConfig:
    """Prepares build provider config for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs build provider config without duplicating the local rules.

    Example: _build_provider_config(name=..., file_config=..., auth_config=..., default_model=..., is_default=...) -> returns the value used by the surrounding Sonex flow.
    """
    prefix = f"SONEX_{name.upper()}_"
    capability = get_provider_capability(name)
    env_api_key = os.getenv(f"{prefix}API_KEY") or (os.getenv("SONEX_API_KEY") if name == "openai" else None)
    auth_api_key = auth_config.api_key if auth_config else None
    auth_oauth = auth_config.oauth if auth_config else None
    auth_method = auth_config.auth_method if auth_config else "auto"
    extra_headers = dict(file_config.get("extra_headers") or {})

    api_key = (
        env_api_key
        or auth_api_key
        or file_config.get("api_key")
    )
    base_url = (
        os.getenv(f"{prefix}BASE_URL")
        or (os.getenv("SONEX_BASE_URL") if name == "openai" else None)
        or (auth_config.base_url if auth_config else None)
        or file_config.get("base_url")
        or capability.default_base_url
    )
    model = normalize_provider_model(
        name,
        os.getenv(f"{prefix}MODEL")
        or (auth_config.model if auth_config else None)
        or file_config.get("model")
        or (default_model if is_default else None)
        or capability.default_model,
    )
    timeout_raw = os.getenv(f"{prefix}TIMEOUT") or file_config.get("timeout")
    timeout = float(timeout_raw) if timeout_raw not in (None, "") else None
    custom_llm_provider = (
        os.getenv(f"{prefix}CUSTOM_LLM_PROVIDER")
        or (auth_config.custom_llm_provider if auth_config else None)
        or file_config.get("custom_llm_provider")
        or capability.default_custom_llm_provider
        or _default_custom_provider(name)
    )

    if not env_api_key and auth_oauth and auth_method in {"auto", "oauth"}:
        if is_default:
            ensure_oauth_token_usable(name, auth_oauth)
            api_key = None
            extra_headers["Authorization"] = f"Bearer {auth_oauth.access_token}"
        else:
            try:
                ensure_oauth_token_usable(name, auth_oauth)
            except Exception:
                pass
            else:
                api_key = None
                extra_headers["Authorization"] = f"Bearer {auth_oauth.access_token}"

    return ProviderConfig(
        name=name,
        model=model,
        api_key=api_key,
        base_url=base_url,
        billing_mode=os.getenv(f"{prefix}BILLING_MODE") or file_config.get("billing_mode"),
        api_version=os.getenv(f"{prefix}API_VERSION") or file_config.get("api_version"),
        timeout=timeout,
        custom_llm_provider=custom_llm_provider,
        extra_headers=extra_headers,
        options=file_config.get("options") or {},
    )


def _provider_default_model(name: str) -> str | None:
    """Prepares provider default model for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs provider default model without duplicating the local rules.

    Example: _provider_default_model(name=...) -> returns the value used by the surrounding Sonex flow.
    """
    return get_provider_capability(name).default_model


def _default_custom_provider(name: str) -> str | None:
    """Prepares default custom provider for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs default custom provider without duplicating the local rules.

    Example: _default_custom_provider(name=...) -> returns the value used by the surrounding Sonex flow.
    """
    provider_map = {
        "openai": None,
        "anthropic": "anthropic",
        "gemini": "gemini",
        "ollama": "ollama",
        "deepseek": "deepseek",
    }
    return provider_map.get(name)
