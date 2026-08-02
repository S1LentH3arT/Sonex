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
        """Prepares init for an internal Sonex flow.

        Typical use: Use this helper when nearby code needs init without duplicating the local rules.

        Example: __init__(default_base_url=...) -> returns the value used by the surrounding Sonex flow.
        """
        self.default_base_url = default_base_url

    def send(self, request: ProviderRequest, config: ProviderConfig) -> Any:
        """Coordinates send for the current Sonex flow.

        Typical use: Use this function when runtime code needs send as part of a Sonex command, playback, auth, llm, or ui path.

        Example: send(request=..., config=...) -> returns the value used by the surrounding Sonex flow.
        """
        is_custom = config.name == "custom" or config.name.startswith("custom__")
        if not config.api_key and not is_custom:
            raise LLMTransportError(f"LLM provider '{config.name}' request failed: missing API key")
        if not (config.base_url or self.default_base_url):
            raise LLMTransportError(f"LLM provider '{config.name}' request failed: missing base URL")

        payload = dict(request.payload)
        payload["model"] = request.model
        if config.options:
            payload.update(config.options)

        http_request = _json_request(
            _chat_completions_url(config.base_url or self.default_base_url),
            payload,
            timeout=config.timeout,
        )
        if config.api_key:
            http_request.add_header("Authorization", f"Bearer {config.api_key}")
        for key, value in config.extra_headers.items():
            http_request.add_header(key, value)
        return _send_json(http_request, config.name, timeout=config.timeout)


class AnthropicOfficialTransport:
    """Represents anthropic official transport.

    Encapsulates anthropic official transport data and behavior used by Sonex runtime flows.
    """
    def send(self, request: ProviderRequest, config: ProviderConfig) -> Any:
        """Coordinates send for the current Sonex flow.

        Typical use: Use this function when runtime code needs send as part of a Sonex command, playback, auth, llm, or ui path.

        Example: send(request=..., config=...) -> returns the value used by the surrounding Sonex flow.
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
        """Coordinates send for the current Sonex flow.

        Typical use: Use this function when runtime code needs send as part of a Sonex command, playback, auth, llm, or ui path.

        Example: send(request=..., config=...) -> returns the value used by the surrounding Sonex flow.
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
    """Prepares json request for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs json request without duplicating the local rules.

    Example: _json_request(url=..., payload=..., timeout=...) -> returns the value used by the surrounding Sonex flow.
    """
    del timeout
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=body, method="POST")
    request.add_header("Content-Type", "application/json")
    return request


def _send_json(http_request: urllib.request.Request, provider: str, *, timeout: float | None) -> Any:
    """Prepares send json for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs send json without duplicating the local rules.

    Example: _send_json(http_request=..., provider=..., timeout=...) -> returns the value used by the surrounding Sonex flow.
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
    """Prepares chat completions url for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs chat completions url without duplicating the local rules.

    Example: _chat_completions_url(base_url=...) -> returns the value used by the surrounding Sonex flow.
    """
    normalized = base_url.rstrip("/")
    if normalized.endswith("/chat/completions"):
        return normalized
    return f"{normalized}/chat/completions"


def _gemini_generate_content_url(base_url: str, model: str, *, api_key: str | None) -> str:
    """Prepares gemini generate content url for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs gemini generate content url without duplicating the local rules.

    Example: _gemini_generate_content_url(base_url=..., model=..., api_key=...) -> returns the value used by the surrounding Sonex flow.
    """
    normalized = base_url.rstrip("/")
    encoded_model = urllib.parse.quote(model, safe="")
    url = f"{normalized}/models/{encoded_model}:generateContent"
    if api_key:
        return f"{url}?{urllib.parse.urlencode({'key': api_key})}"
    return url


def _join_url(base_url: str, path: str) -> str:
    """Prepares join url for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs join url without duplicating the local rules.

    Example: _join_url(base_url=..., path=...) -> returns the value used by the surrounding Sonex flow.
    """
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"
