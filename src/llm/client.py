from __future__ import annotations

from src.llm import RuntimeConfig
from src.llm.adapter import LLMAdapter
from src.llm.adapter.base import DefaultAdapter
from src.llm.adapter.anthropic_adapter import AnthropicAdapter
from src.llm.adapter.gemini_adapter import GeminiAdapter
from src.llm.adapter.ollama_adapter import OllamaAdapter
from src.llm.transport import LLMTransport, ChatRequest, ChatResponse, LiteLLMTransport
from src.llm.transport.deepseek import DeepSeekTransport
from src.log import get_logger

logger = get_logger(__name__)

_DEFAULT_ADAPTERS = {
    "openai": DefaultAdapter(),
    "anthropic": AnthropicAdapter(),
    "gemini": GeminiAdapter(),
    "deepseek": DefaultAdapter(),
    "ollama": OllamaAdapter(),
}

class ProviderClient:
    """Entry point of LLM calling.

    Args:
        runtime_config: include provider and model for resolve.
        transport: the transport for sending request to provider.
        adapters: list of adapters. Default adapters: "anthropic", "gemini", "ollama".
    """
    def __init__(
        self,
        runtime_config: RuntimeConfig,
        transport: LLMTransport | None = None,
        adapters: dict[str, LLMAdapter] = None,
    ) -> None:
        self.runtime_config = runtime_config
        self.transport = transport or LiteLLMTransport()
        self.provider_transports = {
            "deepseek": DeepSeekTransport(),
        } if transport is None else {}
        if adapters is None:
            adapters = _DEFAULT_ADAPTERS
        self.adapters = adapters

    def generate(self, request: ChatRequest) -> ChatResponse:
        """Generate a typical chat request.

        - Resolve provider from request.
        - If adapter is ``None``, raise error and record a log.
        - Calling ``self.transport.send()`` and get a raw response.
        - Parse the raw response to a unified format and return.
        """
        provider_name = request.provider or self.runtime_config.default_provider
        provider_config = self.runtime_config.get_provider(provider_name, model=request.model)
        adapter = self.adapters.get(provider_name)
        if adapter is None:
            message = f"Provider '{provider_name}' is not supported."
            logger.error(message)
            raise RuntimeError(message)

        provider_request = adapter.to_provider_request(request, provider_config)
        transport = self.provider_transports.get(provider_name, self.transport)
        raw_response = transport.send(provider_request, provider_config)
        if raw_response is None:
            raise RuntimeError(f"Provider '{provider_name}' returned an empty response.")
        response = adapter.from_provider_response(raw_response)
        if not response.tool_calls and not response.output_text:
            raise RuntimeError(f"Provider '{provider_name}' returned no text or tool call.")
        if response.raw_output is None:
            response.raw_output = raw_response
        return response
