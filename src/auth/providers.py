"""Providers support for provider authentication and credential persistence.

Implements the providers module responsibilities used by Sonex runtime flows.
Key public entry points include ProviderCapability, normalize_provider, normalize_provider_model, get_provider_capability, provider_names.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProviderCapability:
    """Represents provider capability.

    Encapsulates provider capability data and behavior used by Sonex runtime flows.
    """
    name: str
    supports_api_key: bool
    supports_oauth: bool
    requires_auth: bool = True
    default_base_url: str | None = None
    default_custom_llm_provider: str | None = None
    default_model: str | None = None


PROVIDER_CAPABILITIES: dict[str, ProviderCapability] = {
    "openai": ProviderCapability(
        name="openai",
        supports_api_key=True,
        supports_oauth=False,
        default_base_url="https://api.openai.com/v1",
        default_model="gpt-5.2",
    ),
    "anthropic": ProviderCapability(
        name="anthropic",
        supports_api_key=True,
        supports_oauth=False,
        default_base_url="https://api.anthropic.com/v1",
        default_custom_llm_provider="anthropic",
        default_model="claude-opus-4-1-20250805",
    ),
    "gemini": ProviderCapability(
        name="gemini",
        supports_api_key=True,
        supports_oauth=True,
        default_base_url="https://generativelanguage.googleapis.com/v1beta",
        default_custom_llm_provider="gemini",
        default_model="gemini-3-flash-preview",
    ),
    "deepseek": ProviderCapability(
        name="deepseek",
        supports_api_key=True,
        supports_oauth=False,
        default_base_url="https://api.deepseek.com",
        default_custom_llm_provider="deepseek",
        default_model="deepseek-v4-pro",
    ),
    "ollama": ProviderCapability(
        name="ollama",
        supports_api_key=False,
        supports_oauth=False,
        requires_auth=False,
        default_custom_llm_provider="ollama",
        default_model="Gemma4-31b:cloud",
    ),
    "spotify": ProviderCapability(
        name="spotify",
        supports_api_key=True,
        supports_oauth=True,
    ),
    "apple_music": ProviderCapability(
        name="apple_music",
        supports_api_key=True,
        supports_oauth=True,
    ),
}


def normalize_provider(name: str) -> str:
    """Normalize provider.

    Coordinates normalize provider logic for the surrounding Sonex flow.

    Args:
        name: Input value used by the normalize provider operation.

    Returns:
        The computed result for normalize provider.
    """
    return name.strip().lower().replace("-", "_")


def normalize_provider_model(provider: str, model: str | None) -> str | None:
    """Normalize provider model.

    Coordinates normalize provider model logic for the surrounding Sonex flow.

    Args:
        provider: Input value used by the normalize provider model operation.
        model: Input value used by the normalize provider model operation.

    Returns:
        The computed result for normalize provider model.
    """
    if model is None:
        return None

    normalized_provider = normalize_provider(provider)
    normalized_model = model.strip()
    if normalized_provider == "deepseek":
        aliases = {
            "deepseek-v4-pro": "deepseek-v4-pro",
            "deepseek-v4": "deepseek-v4-pro",
            "deepseek-v3": "deepseek-v4-flash",
            "deepseek-chat": "deepseek-v4-flash",
            "deepseek-reasoner": "deepseek-v4-flash",
        }
        return aliases.get(normalized_model.lower(), normalized_model)
    return normalized_model


def get_provider_capability(name: str) -> ProviderCapability:
    """Get provider capability.

    Coordinates get provider capability logic for the surrounding Sonex flow.

    Args:
        name: Input value used by the get provider capability operation.

    Returns:
        The computed result for get provider capability.
    """
    normalized = normalize_provider(name)
    return PROVIDER_CAPABILITIES.get(
        normalized,
        ProviderCapability(
            name=normalized,
            supports_api_key=True,
            supports_oauth=False,
        ),
    )


def provider_names() -> set[str]:
    """Provider names.

    Coordinates provider names logic for the surrounding Sonex flow.

    Returns:
        The computed result for provider names.
    """
    return set(PROVIDER_CAPABILITIES)
