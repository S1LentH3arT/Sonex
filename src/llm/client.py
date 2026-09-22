"""Client support for language model configuration, catalogs, transports, and planning.
"""

from __future__ import annotations

from src.llm import RuntimeConfig
from src.llm.adapter import LLMAdapter
from src.llm.adapter.base import DefaultAdapter
from src.llm.adapter.anthropic_adapter import AnthropicAdapter
from src.llm.adapter.gemini_adapter import GeminiAdapter
from src.llm.transport import (
    AnthropicOfficialTransport,
    CodexAppServerTransport,
    GeminiOfficialTransport,
    LLMTransport,
    ChatRequest,
    ChatResponse,
    OpenAICompatibleTransport,
)
from src.llm.transport.deepseek import DeepSeekTransport
from src.llm.usage import report_token_usage
from src.log import get_logger

logger = get_logger(__name__)

_DEFAULT_ADAPTERS = {
    "openai": DefaultAdapter(),
    "anthropic": AnthropicAdapter(),
    "gemini": GeminiAdapter(),
    "deepseek": DefaultAdapter(),
    "custom": DefaultAdapter(),
    **{
        provider: DefaultAdapter()
        for provider in (
            "openrouter",
            "zai",
            "kimi_global",
            "kimi_cn",
            "minimax_global",
            "minimax_cn",
            "xai",
        )
    },
}

_OPENAI_COMPATIBLE_PROVIDERS = {
    "openrouter",
    "zai",
    "kimi_global",
    "kimi_cn",
    "minimax_global",
    "minimax_cn",
    "xai",
}

class ProviderClient:
    """Entry point of LLM calling.

    Args:
        runtime_config: include provider and model for resolve.
        adapters: list of adapters. Default adapters include official providers and Custom.
    """
    def __init__(
        self,
        runtime_config: RuntimeConfig,
        adapters: dict[str, LLMAdapter] = None,
        provider_transports: dict[str, LLMTransport] | None = None,
    ) -> None:
        self.runtime_config = runtime_config
        self.provider_transports = provider_transports or {
            "openai": OpenAICompatibleTransport(default_base_url="https://api.openai.com/v1"),
            "anthropic": AnthropicOfficialTransport(),
            "gemini": GeminiOfficialTransport(),
            "deepseek": DeepSeekTransport(),
            **{
                provider: OpenAICompatibleTransport(default_base_url="")
                for provider in _OPENAI_COMPATIBLE_PROVIDERS
            },
        }
        if adapters is None:
            adapters = _DEFAULT_ADAPTERS
        self.adapters = adapters

    def generate(self, request: ChatRequest) -> ChatResponse:
        """Generate a typical chat request.

        - Resolve provider from request.
        - If adapter is ``None``, raise error and record a log.
        - Call the provider transport and get a raw response.
        - Parse the raw response to a unified format and return.
        """
        provider_name = request.provider or self.runtime_config.default_provider
        provider_config = self.runtime_config.get_provider(provider_name, model=request.model)
        adapter = self.adapters.get(provider_name)
        if adapter is None and provider_name.startswith("custom__"):
            adapter = DefaultAdapter()
        if adapter is None:
            message = f"Provider '{provider_name}' is not supported."
            logger.error(message)
            raise RuntimeError(message)

        provider_request = adapter.to_provider_request(request, provider_config)
        transport = (
            OpenAICompatibleTransport(default_base_url=provider_config.base_url or "")
            if provider_name == "custom" or provider_name.startswith("custom__")
            else CodexAppServerTransport()
            if provider_name == "openai" and provider_config.billing_mode == "chatgpt_subscription"
            else self.provider_transports.get(provider_name)
        )
        if transport is None:
            message = f"Provider '{provider_name}' is not supported."
            logger.error(message)
            raise RuntimeError(message)
        raw_response = transport.send(provider_request, provider_config)
        if raw_response is None:
            raise RuntimeError(f"Provider '{provider_name}' returned an empty response.")
        response = adapter.from_provider_response(raw_response)
        report_token_usage(response.usage)
        if not response.tool_calls and not response.output_text:
            raise RuntimeError(f"Provider '{provider_name}' returned no text or tool call.")
        if response.raw_output is None:
            response.raw_output = raw_response
        return response
