"""Base support for language model configuration, catalogs, transports, and planning.

Implements the base module responsibilities used by Sonex runtime flows.
Key public entry points include BaseAdapter, DefaultAdapter.
"""

import json
from dataclasses import asdict
from typing import Protocol, Any, Callable

from src.llm.config import ProviderConfig
from src.llm.transport.base import ChatRequest, ProviderRequest, ChatResponse, ToolCall, Usage
from src.log import get_logger

logger = get_logger(__name__)

class BaseAdapter(Protocol):
    """Base adapter for all LLM providers.

    Args:
        provider_name: name of the provider.
    """
    provider_name: str

    def to_provider_request(
        self,
        request: ChatRequest,
        provider_config: ProviderConfig,
    ) -> ProviderRequest:
        """Parse a unified request and return a request with provider-style."""
        ...

    def from_provider_response(self, raw_response: Any) -> ChatResponse:
        """Resolve a raw response and return a unified response."""
        ...


LLMAdapter = BaseAdapter


class DefaultAdapter(BaseAdapter):
    """Default adapter that implements BaseAdapter in OpenAI style.

    Args:
        provider_name: name of the provider, defaults to "openai".
    """
    provider_name = "openai"

    def to_provider_request(
        self,
        request: ChatRequest,
        provider_config: ProviderConfig,
    ) -> ProviderRequest:
        """Parse a unified request and return a request in OpenAI style."""
        resolved_model = request.model or provider_config.model
        if not resolved_model:
            logger.warning(f"No model configured for provider '{provider_config.name}'.")

        payload = request.to_payload(resolved_model)
        return ProviderRequest(
            provider=provider_config.name,
            model=resolved_model,
            payload=payload,
            native_payload=self._build_native_payload(request, resolved_model),
        )

    def from_provider_response(self, raw_response: Any) -> ChatResponse:
        """Resolve a raw OpenAI-style response and return a unified response."""
        data = _to_dict(raw_response)
        if "choices" in data:
            return _parse_openai_style_response(data)
        return self._parse_native_response(data)

    def _build_native_payload(self, request: ChatRequest, resolved_model: str) -> dict[str, Any]:
        """Generate a provider-style payload by calling **to_payload( )**."""
        payload = request.to_payload(resolved_model)
        payload["model"] = resolved_model
        return payload

    def _parse_native_response(self, data: dict[str, Any]) -> ChatResponse:
        """Parse a native response and return a unified response."""
        return ChatResponse(raw_output=data)


def _to_dict(raw_response: Any) -> Any:
    """Transform a raw response into a dict format.

    - If the raw response is a ``dict`` type, return it directly.
    - If there's a callable method in response, return a callable object.
    - If there's a ``to_json`` method in response, transform it into json.
    - If the response has a ``__dict__`` attribute, return ``asdict()`` method for ``dataclass`` type and ``dict()`` method for others.
    """
    if raw_response is None:
        raise ValueError("LLM provider returned an empty response.")
    if isinstance(raw_response, dict):
        return raw_response
    model_dump = getattr(raw_response, "model_dump", None)
    if callable(model_dump):
        return model_dump()
    to_json = getattr(raw_response, "to_json", None)
    if callable(to_json):
        return json.loads(to_json())
    if hasattr(raw_response, "__dict__"):
        return asdict(raw_response) if hasattr(raw_response, "__dataclass_fields__") else dict(raw_response.__dict__)
    raise TypeError(f"Unsupported response payload: {type(raw_response)!r}")


def _parse_openai_style_response(data: dict[str, Any]) -> ChatResponse:
    """Parse a OpenAI-style ``choices[].message`` response.

    - Extract ``choices[0].message`` as target and normalize by ``_coerce_text()`` method.
    - Extract tool calls and transform into list of ``ToolCall``.
    - Parse usage data and wrap as ``Usage`` object.
    - Resolve a finish reason if exists.
    """
    choices = data.get("choices") or []
    if not choices:
        raise ValueError("LLM provider response did not include choices.")
    message = ((choices[0] if choices else {}).get("message")) or {}
    output_text = _coerce_text(message.get("content"))

    tool_calls = []
    for tool_call in message.get("tool_calls") or []:
        function = tool_call.get("function") or {}
        arguments = function.get("arguments") or {}
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                arguments = {}
        tool_calls.append(
            ToolCall(
                id=tool_call.get("id"),
                name=function.get("name", ""),
                arguments=arguments,
            )
        )

    usage_data = data.get("usage") or {}
    usage = Usage(
        prompt_tokens=int(usage_data.get("prompt_tokens") or 0),
        completion_tokens=int(usage_data.get("completion_tokens") or 0),
        total_tokens=int(usage_data.get("total_tokens") or 0),
    )

    finish_reason = (choices[0] or {}).get("finish_reason") if choices else None
    return ChatResponse(
        output_text=output_text,
        tool_calls=tool_calls,
        raw_output=data,
        usage=usage,
        finish_reason=finish_reason,
    )


def _coerce_text(content: Any) -> str:
    """Normalize message content of all response format to string."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks = []
        for item in content:
            if isinstance(item, str):
                chunks.append(item)
                continue
            if not isinstance(item, dict):
                continue
            if item.get("type") in {"text", "output_text"} and item.get("text"):
                chunks.append(item["text"])
        return "\n".join(chunks).strip()
    return str(content)
