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
        supports_oauth=True,
        default_base_url="https://api.openai.com/v1",
        default_model="gpt-5.5",
    ),
    "anthropic": ProviderCapability(
        name="anthropic",
        supports_api_key=True,
        supports_oauth=False,
        default_base_url="https://api.anthropic.com/v1",
        default_custom_llm_provider="anthropic",
        default_model="claude-fable-5",
    ),
    "gemini": ProviderCapability(
        name="gemini",
        supports_api_key=True,
        supports_oauth=True,
        default_base_url="https://generativelanguage.googleapis.com/v1beta",
        default_custom_llm_provider="gemini",
        default_model="gemini-3.5-flash",
    ),
    "deepseek": ProviderCapability(
        name="deepseek",
        supports_api_key=True,
        supports_oauth=False,
        default_base_url="https://api.deepseek.com",
        default_custom_llm_provider="deepseek",
        default_model="deepseek-v4-pro",
    ),
    "openrouter": ProviderCapability(
        name="openrouter",
        supports_api_key=True,
        supports_oauth=False,
        default_base_url="https://openrouter.ai/api/v1",
        default_custom_llm_provider="openai",
        default_model="openrouter/auto",
    ),
    "zai": ProviderCapability(
        name="zai",
        supports_api_key=True,
        supports_oauth=False,
        default_base_url="https://api.z.ai/api/paas/v4",
        default_custom_llm_provider="openai",
        default_model="glm-5.1",
    ),
    "kimi_global": ProviderCapability(
        name="kimi_global",
        supports_api_key=True,
        supports_oauth=False,
        default_base_url="https://api.moonshot.ai/v1",
        default_custom_llm_provider="openai",
        default_model="kimi-k2.6",
    ),
    "kimi_cn": ProviderCapability(
        name="kimi_cn",
        supports_api_key=True,
        supports_oauth=False,
        default_base_url="https://api.moonshot.cn/v1",
        default_custom_llm_provider="openai",
        default_model="kimi-k2.5",
    ),
    "minimax_global": ProviderCapability(
        name="minimax_global",
        supports_api_key=True,
        supports_oauth=False,
        default_base_url="https://api.minimax.io/v1",
        default_custom_llm_provider="openai",
        default_model="MiniMax-M2.7",
    ),
    "minimax_cn": ProviderCapability(
        name="minimax_cn",
        supports_api_key=True,
        supports_oauth=False,
        default_base_url="https://api.minimaxi.com/v1",
        default_custom_llm_provider="openai",
        default_model="MiniMax-M2.7",
    ),
    "xai": ProviderCapability(
        name="xai",
        supports_api_key=True,
        supports_oauth=False,
        default_base_url="https://api.x.ai/v1",
        default_custom_llm_provider="openai",
        default_model="grok-4.5",
    ),
    "custom": ProviderCapability(
        name="custom",
        supports_api_key=True,
        supports_oauth=False,
        default_custom_llm_provider="openai",
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
    """Coordinates normalize provider for the current Sonex flow.

    Typical use: Use this function when runtime code needs normalize provider as part of a Sonex command, playback, auth, llm, or ui path.

    Example: normalize_provider(name=...) -> returns the value used by the surrounding Sonex flow.
    """
    return name.strip().lower().replace("-", "_")


def normalize_provider_model(provider: str, model: str | None) -> str | None:
    """Coordinates normalize provider model for the current Sonex flow.

    Typical use: Use this function when runtime code needs normalize provider model as part of a Sonex command, playback, auth, llm, or ui path.

    Example: normalize_provider_model(provider=..., model=...) -> returns the value used by the surrounding Sonex flow.
    """
    if model is None:
        return None

    del provider
    return model.strip()


_PROVIDER_DISPLAY_NAMES = {
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "gemini": "Google Gemini",
    "deepseek": "DeepSeek",
    "openrouter": "OpenRouter",
    "zai": "Z.AI",
    "kimi_global": "Kimi Global",
    "kimi_cn": "Kimi CN",
    "minimax_global": "MiniMax Global",
    "minimax_cn": "MiniMax CN",
    "xai": "xAI",
    "custom": "Custom",
}


def provider_display_name(provider: str) -> str:
    """Return the formal product name shown in Sonex UI copy."""
    name = normalize_provider(provider)
    if name.startswith("custom__"):
        return "Custom"
    return _PROVIDER_DISPLAY_NAMES.get(name, provider.strip() or name)


def get_provider_capability(name: str) -> ProviderCapability:
    """Returns provider capability for the current Sonex flow.

    Typical use: Use this function when runtime code needs get provider capability as part of a Sonex command, playback, auth, llm, or ui path.

    Example: get_provider_capability(name=...) -> returns the value used by the surrounding Sonex flow.
    """
    normalized = normalize_provider(name)
    if normalized.startswith("custom__"):
        return ProviderCapability(
            name=normalized,
            supports_api_key=True,
            supports_oauth=False,
            default_custom_llm_provider="openai",
        )
    return PROVIDER_CAPABILITIES.get(
        normalized,
        ProviderCapability(
            name=normalized,
            supports_api_key=True,
            supports_oauth=False,
        ),
    )


def provider_names() -> set[str]:
    """Coordinates provider names for the current Sonex flow.

    Typical use: Use this function when runtime code needs provider names as part of a Sonex command, playback, auth, llm, or ui path.

    Example: provider_names() -> returns the value used by the surrounding Sonex flow.
    """
    return set(PROVIDER_CAPABILITIES)
