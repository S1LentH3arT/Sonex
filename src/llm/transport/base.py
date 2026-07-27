"""Base support for language model configuration, catalogs, transports, and planning.

Implements the base module responsibilities used by Sonex runtime flows.
Key public entry points include LLMTransportError, sanitize_error_message, ToolCall, Usage, ChatRequest.
"""

import re
from dataclasses import dataclass, field
from typing import Protocol, Any

from src.llm.config import ProviderConfig
from src.log import get_logger

logger = get_logger(__name__)


class LLMTransportError(RuntimeError):
    """Raised when the configured LLM provider cannot complete a request."""


_SECRET_PATTERNS = (
    re.compile(r"(?i)(api[_-]?key|token|authorization|bearer)\s*[:=]\s*([^\s,;]+)"),
    re.compile(r"(?i)bearer\s+([^\s,;]+)"),
)
_URL_PRIVATE_SUFFIX_PATTERN = re.compile(
    r"(https?://[^\s?#)\]}]+)(?:(?:\?[^ \t\r\n#)\]}]*)(?:#[^ \t\r\n)\]}]*)?|(?:#[^ \t\r\n)\]}]*))",
    re.IGNORECASE,
)


def sanitize_error_message(error: Any, *, limit: int = 500) -> str:
    """Coordinates sanitize error message for the current Sonex flow.

    Typical use: Use this function when runtime code needs sanitize error message as part of a Sonex command, playback, auth, llm, or ui path.

    Example: sanitize_error_message(error=..., limit=...) -> returns the value used by the surrounding Sonex flow.
    """
    text = str(error).strip() or error.__class__.__name__
    text = " ".join(text.split())
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(lambda match: match.group(0).replace(match.group(match.lastindex), "[redacted]"), text)
    text = _URL_PRIVATE_SUFFIX_PATTERN.sub(r"\1?[redacted]", text)
    if len(text) > limit:
        text = f"{text[: limit - 1]}..."
    return text


@dataclass(slots=True)
class ToolCall:
    """Sonex unified tool call format."""
    id: str | None
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Usage:
    """Token usage data.

    ``prompt_tokens`` for input token estimation, ``completion_tokens`` for output token estimation.
    """
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass(slots=True)
class ChatRequest:
    """Unified defined request format, handling mainstream request protocol like OpenAI, Anthropic and Google.

    Which means that it's a provider-friendly request format.
    """
    messages: list[dict[str, Any]]
    model: str | None = None
    provider: str | None = None
    tools: list[dict[str, Any]] = field(default_factory=list)
    tool_choice: str | dict[str, Any] | None = None
    max_tokens: int | None = None
    temperature: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    provider_options: dict[str, Any] = field(default_factory=dict)

    def to_payload(self, resolved_model: str) -> dict[str, Any]:
        """Transform request to dict format payload."""
        payload: dict[str, Any] = {
            "model": resolved_model,
            "messages": self.messages,
        }
        if self.tools:
            payload["tools"] = self.tools
        if self.tool_choice is not None:
            payload["tool_choice"] = self.tool_choice
        if self.max_tokens is not None:
            payload["max_tokens"] = self.max_tokens
        if self.temperature is not None:
            payload["temperature"] = self.temperature
        if self.metadata:
            payload["metadata"] = self.metadata
        if self.provider_options:
            payload.update(self.provider_options)
        return payload


@dataclass(slots=True)
class ChatResponse:
    """Unified response format which extracts raw response and normalize.

    Divide tool calling data and output text as two parts, with ``raw_output`` as reference.
    """
    output_text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw_output: Any = None
    usage: Usage = field(default_factory=Usage)
    finish_reason: str | None = None


@dataclass(slots=True)
class ProviderRequest:
    """Provider-specific request payloads prepared from a unified chat request."""
    provider: str
    model: str
    payload: dict[str, Any]
    native_payload: dict[str, Any]


class LLMTransport(Protocol):
    """Represents llm transport.

    Encapsulates llm transport data and behavior used by Sonex runtime flows. Extends protocol semantics.
    """
    def send(self, request: ProviderRequest, config: ProviderConfig) -> Any:
        """Coordinates send for the current Sonex flow.

        Typical use: Use this function when runtime code needs send as part of a Sonex command, playback, auth, llm, or ui path.

        Example: send(request=..., config=...) -> returns the value used by the surrounding Sonex flow.
        """
        ...


class LiteLLMTransport(LLMTransport):
    """Represents lite llm transport.

    Encapsulates lite llm transport data and behavior used by Sonex runtime flows. Extends llm transport semantics.
    """
    def send(self, request: ProviderRequest, config: ProviderConfig) -> Any:
        """Coordinates send for the current Sonex flow.

        Typical use: Use this function when runtime code needs send as part of a Sonex command, playback, auth, llm, or ui path.

        Example: send(request=..., config=...) -> returns the value used by the surrounding Sonex flow.
        """
        from litellm import completion

        payload = dict(request.payload)
        payload["model"] = _resolve_transport_model(request.model, config)

        if config.api_key:
            payload["api_key"] = config.api_key
        if config.base_url:
            payload["base_url"] = config.base_url
        if config.api_version:
            payload["api_version"] = config.api_version
        if config.timeout is not None:
            payload["timeout"] = config.timeout
        if config.extra_headers:
            payload["extra_headers"] = config.extra_headers
        if config.custom_llm_provider:
            payload["custom_llm_provider"] = config.custom_llm_provider
        if config.options:
            payload.update(config.options)

        try:
            return completion(**payload)
        except Exception as exc:
            safe_error = sanitize_error_message(exc)
            logger.error(f"Transport request failed for provider '{config.name}': {safe_error}.")
            raise LLMTransportError(
                f"LLM provider '{config.name}' request failed: {safe_error}"
            ) from exc


def _resolve_transport_model(model: str, config: ProviderConfig) -> str:
    """Prepares resolve transport model for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs resolve transport model without duplicating the local rules.

    Example: _resolve_transport_model(model=..., config=...) -> returns the value used by the surrounding Sonex flow.
    """
    if "/" in model:
        return model

    prefixes = {
        "anthropic": "anthropic",
        "gemini": "gemini",
        "deepseek": "deepseek",
        "ollama": "ollama",
    }
    prefix = prefixes.get(config.name)
    if prefix:
        return f"{prefix}/{model}"
    return model
