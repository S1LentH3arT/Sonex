"""Official support for language model configuration, catalogs, transports, and planning.

Implements the official module responsibilities used by Sonex runtime flows.
Key public entry points include OpenAICompatibleTransport, AnthropicOfficialTransport, GeminiOfficialTransport.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from src.llm.config import ProviderConfig
from src.llm.transport.base import LLMTransportError, ProviderRequest, sanitize_error_message
from src.log import get_logger

logger = get_logger(__name__)


class OpenAICompatibleTransport:
    """Represents open a i compatible transport.

    Encapsulates open a i compatible transport data and behavior used by Sonex runtime flows.
    """
    def __init__(self, *, default_base_url: str) -> None:
        """Init for open a i compatible transport.

        Coordinates the init method behavior while preserving open a i compatible transport state and contracts.

        Args:
            default_base_url: Input value used by the init operation.
        """
        self.default_base_url = default_base_url

    def send(self, request: ProviderRequest, config: ProviderConfig) -> Any:
        """Send for open a i compatible transport.

        Coordinates the send method behavior while preserving open a i compatible transport state and contracts.

        Args:
            request: Input value used by the send operation.
            config: Input value used by the send operation.

        Returns:
            The computed result for send.
        """
        if not config.api_key:
            raise LLMTransportError(f"LLM provider '{config.name}' request failed: missing API key")

        payload = dict(request.payload)
        payload["model"] = request.model
        if config.options:
            payload.update(config.options)

        http_request = _json_request(
            _chat_completions_url(config.base_url or self.default_base_url),
            payload,
            timeout=config.timeout,
        )
        http_request.add_header("Authorization", f"Bearer {config.api_key}")
        for key, value in config.extra_headers.items():
            http_request.add_header(key, value)
        return _send_json(http_request, config.name, timeout=config.timeout)


class AnthropicOfficialTransport:
    """Represents anthropic official transport.

    Encapsulates anthropic official transport data and behavior used by Sonex runtime flows.
    """
    def send(self, request: ProviderRequest, config: ProviderConfig) -> Any:
        """Send for anthropic official transport.

        Coordinates the send method behavior while preserving anthropic official transport state and contracts.

        Args:
            request: Input value used by the send operation.
            config: Input value used by the send operation.

        Returns:
            The computed result for send.
        """
        if not config.api_key:
            raise LLMTransportError("LLM provider 'anthropic' request failed: missing API key")

        payload = dict(request.native_payload or request.payload)
        payload["model"] = request.model
        payload.setdefault("max_tokens", int(config.options.get("max_tokens") or 4096))
        if config.options:
            payload.update({key: value for key, value in config.options.items() if key != "max_tokens"})

        http_request = _json_request(
            _join_url(config.base_url or "https://api.anthropic.com/v1", "messages"),
            payload,
            timeout=config.timeout,
        )
        http_request.add_header("x-api-key", config.api_key)
        http_request.add_header("anthropic-version", config.api_version or "2023-06-01")
        for key, value in config.extra_headers.items():
            http_request.add_header(key, value)
        return _send_json(http_request, "anthropic", timeout=config.timeout)


class GeminiOfficialTransport:
    """Represents gemini official transport.

    Encapsulates gemini official transport data and behavior used by Sonex runtime flows.
    """
    def send(self, request: ProviderRequest, config: ProviderConfig) -> Any:
        """Send for gemini official transport.

        Coordinates the send method behavior while preserving gemini official transport state and contracts.

        Args:
            request: Input value used by the send operation.
            config: Input value used by the send operation.

        Returns:
            The computed result for send.
        """
        if not config.api_key and "Authorization" not in config.extra_headers:
            raise LLMTransportError("LLM provider 'gemini' request failed: missing API key or OAuth token")

        payload = dict(request.native_payload or request.payload)
        payload.pop("model", None)
        if config.options:
            payload.update(config.options)

        url = _gemini_generate_content_url(
            config.base_url or "https://generativelanguage.googleapis.com/v1beta",
            request.model,
            api_key=config.api_key if "Authorization" not in config.extra_headers else None,
        )
        http_request = _json_request(url, payload, timeout=config.timeout)
        for key, value in config.extra_headers.items():
            http_request.add_header(key, value)
        return _send_json(http_request, "gemini", timeout=config.timeout)


def _json_request(url: str, payload: dict[str, Any], *, timeout: float | None) -> urllib.request.Request:
    """Json request.

    Coordinates json request logic for the surrounding Sonex flow.

    Args:
        url: Input value used by the json request operation.
        payload: Input value used by the json request operation.
        timeout: Input value used by the json request operation.

    Returns:
        The computed result for json request.
    """
    del timeout
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=body, method="POST")
    request.add_header("Content-Type", "application/json")
    return request


def _send_json(http_request: urllib.request.Request, provider: str, *, timeout: float | None) -> Any:
    """Send json.

    Coordinates send json logic for the surrounding Sonex flow.

    Args:
        http_request: Input value used by the send json operation.
        provider: Input value used by the send json operation.
        timeout: Input value used by the send json operation.

    Returns:
        The computed result for send json.
    """
    try:
        with urllib.request.urlopen(http_request, timeout=timeout or 60) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        safe_error = sanitize_error_message(detail)
        logger.error(f"Transport request failed for provider '{provider}': {safe_error}.")
        raise LLMTransportError(f"LLM provider '{provider}' request failed: {safe_error}") from exc
    except Exception as exc:
        safe_error = sanitize_error_message(exc)
        logger.error(f"Transport request failed for provider '{provider}': {safe_error}.")
        raise LLMTransportError(f"LLM provider '{provider}' request failed: {safe_error}") from exc


def _chat_completions_url(base_url: str) -> str:
    """Chat completions url.

    Coordinates chat completions url logic for the surrounding Sonex flow.

    Args:
        base_url: Input value used by the chat completions url operation.

    Returns:
        The computed result for chat completions url.
    """
    normalized = base_url.rstrip("/")
    if normalized.endswith("/chat/completions"):
        return normalized
    return f"{normalized}/chat/completions"


def _gemini_generate_content_url(base_url: str, model: str, *, api_key: str | None) -> str:
    """Gemini generate content url.

    Coordinates gemini generate content url logic for the surrounding Sonex flow.

    Args:
        base_url: Input value used by the gemini generate content url operation.
        model: Input value used by the gemini generate content url operation.
        api_key: Input value used by the gemini generate content url operation.

    Returns:
        The computed result for gemini generate content url.
    """
    normalized = base_url.rstrip("/")
    encoded_model = urllib.parse.quote(model, safe="")
    url = f"{normalized}/models/{encoded_model}:generateContent"
    if api_key:
        return f"{url}?{urllib.parse.urlencode({'key': api_key})}"
    return url


def _join_url(base_url: str, path: str) -> str:
    """Join url.

    Coordinates join url logic for the surrounding Sonex flow.

    Args:
        base_url: Input value used by the join url operation.
        path: Input value used by the join url operation.

    Returns:
        The computed result for join url.
    """
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"
