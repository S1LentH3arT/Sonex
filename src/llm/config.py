from dataclasses import dataclass, field, replace
from typing import Any


@dataclass(slots=True)
class ProviderConfig:
    """LLM provider configuration of Sonex.

    Args:
        name: name of the provider.
        model: default model of the provider.
        api_key: api key for LLM calling.
        base_url: custom or official base url for LLM API endpoint.
        billing_mode: including api-billing mode and subscription mode.
        api_version: version of provider API.
        timeout: max waiting time for API response.
        custom_llm_provider: custom provider like Ollama, Deepseek and so on.
        extra_headers: extra request headers passed to LLM.
        options: other params, combined into payload at transport.
    """
    name: str
    model: str | None = None
    api_key: str | None = None
    base_url: str | None = None
    billing_mode: str | None = None
    api_version: str | None = None
    timeout: float | None = None
    custom_llm_provider: str | None = None
    extra_headers: dict[str, str] = field(default_factory=dict)
    options: dict[str, Any] = field(default_factory=dict)

    def with_model(self, model: str | None) -> "ProviderConfig":
        """Update default model of configuration.

        If the input model is ``None`` or the same as the origin model, return without any changes.
        """
        if model is None or model == self.model:
            return self
        return replace(self, model=model)


@dataclass(slots=True)
class RuntimeConfig:
    """Runtime configuration of Sonex.

    Args:
        default_provider: default provider of LLM.
        default_model: default model for LLM calling.
        providers: list of optional providers.
    """
    default_provider: str
    default_model: str
    providers: dict[str, ProviderConfig] = field(default_factory=dict)

    def get_provider(self, name: str | None = None, model: str | None = None) -> ProviderConfig:
        """Get provider configuration by specific name or model if provided.

        If the name is not provided, use default provider as alternative.
        """
        provider_name = name or self.default_provider
        config = self.providers.get(provider_name)
        if config is None:
            config = ProviderConfig(name=provider_name)
        resolved_model = model or config.model or self.default_model
        return config.with_model(resolved_model)