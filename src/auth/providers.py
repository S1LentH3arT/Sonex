from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProviderCapability:
    name: str
    supports_api_key: bool
    supports_oauth: bool
    requires_auth: bool = True
    default_base_url: str | None = None
    default_custom_llm_provider: str | None = None


PROVIDER_CAPABILITIES: dict[str, ProviderCapability] = {
    "openai": ProviderCapability(
        name="openai",
        supports_api_key=True,
        supports_oauth=False,
    ),
    "anthropic": ProviderCapability(
        name="anthropic",
        supports_api_key=True,
        supports_oauth=False,
        default_custom_llm_provider="anthropic",
    ),
    "gemini": ProviderCapability(
        name="gemini",
        supports_api_key=True,
        supports_oauth=True,
        default_custom_llm_provider="gemini",
    ),
    "deepseek": ProviderCapability(
        name="deepseek",
        supports_api_key=True,
        supports_oauth=False,
        default_custom_llm_provider="deepseek",
    ),
    "ollama": ProviderCapability(
        name="ollama",
        supports_api_key=False,
        supports_oauth=False,
        requires_auth=False,
        default_custom_llm_provider="ollama",
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
    return name.strip().lower().replace("-", "_")


def get_provider_capability(name: str) -> ProviderCapability:
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
    return set(PROVIDER_CAPABILITIES)
