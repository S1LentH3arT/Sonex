"""Deepseek support for language model configuration, catalogs, transports, and planning.

Implements the deepseek module responsibilities used by Sonex runtime flows.
Key public entry points include DeepSeekTransport.
"""

from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from src.llm.config import ProviderConfig
from src.llm.transport.base import LLMTransportError, ProviderRequest, sanitize_error_message
from src.log import get_logger

logger = get_logger(__name__)


class DeepSeekTransport:
    """Represents deep seek transport.

    Encapsulates deep seek transport data and behavior used by Sonex runtime flows.
    """
    def send(self, request: ProviderRequest, config: ProviderConfig) -> Any:
        """Send for deep seek transport.

        Coordinates the send method behavior while preserving deep seek transport state and contracts.

        Args:
            request: Input value used by the send operation.
            config: Input value used by the send operation.

        Returns:
            The computed result for send.
        """
        if not config.api_key:
            raise LLMTransportError("LLM provider 'deepseek' request failed: missing API key")

        payload = dict(request.payload)
        payload["model"] = request.model
        if config.options:
            payload.update(config.options)

        body = json.dumps(payload).encode("utf-8")
        http_request = urllib.request.Request(
            _chat_completions_url(config.base_url or "https://api.deepseek.com"),
            data=body,
            method="POST",
        )
        http_request.add_header("Authorization", f"Bearer {config.api_key}")
        http_request.add_header("Content-Type", "application/json")
        for key, value in config.extra_headers.items():
            http_request.add_header(key, value)

        try:
            with urllib.request.urlopen(http_request, timeout=config.timeout or 60) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            safe_error = sanitize_error_message(detail)
            logger.error(f"Transport request failed for provider 'deepseek': {safe_error}.")
            raise LLMTransportError(f"LLM provider 'deepseek' request failed: {safe_error}") from exc
        except Exception as exc:
            safe_error = _describe_transport_error(exc)
            logger.error(f"Transport request failed for provider 'deepseek': {safe_error}.")
            raise LLMTransportError(f"LLM provider 'deepseek' request failed: {safe_error}") from exc


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
    if normalized.endswith("/v1"):
        normalized = normalized[:-3]
    return f"{normalized}/chat/completions"


def _describe_transport_error(exc: Exception) -> str:
    """Describe transport error.

    Coordinates describe transport error logic for the surrounding Sonex flow.

    Args:
        exc: Input value used by the describe transport error operation.

    Returns:
        The computed result for describe transport error.
    """
    safe_error = sanitize_error_message(exc)
    proxy = _loopback_proxy_url()
    if proxy and _is_connection_refused(exc):
        return (
            f"{safe_error} (local proxy {proxy} is not accepting connections; "
            "start the proxy or update/unset HTTPS_PROXY/HTTP_PROXY/https_proxy/http_proxy/all_proxy/ALL_PROXY.)"
        )
    if proxy and _is_tls_eof(exc):
        return (
            f"{safe_error} (local proxy {proxy} TLS connection closed unexpectedly; "
            "verify the proxy is running on the URL Python resolves, or update/unset "
            "HTTPS_PROXY/HTTP_PROXY/https_proxy/http_proxy/all_proxy/ALL_PROXY.)"
        )
    return safe_error


def _is_connection_refused(exc: Exception) -> bool:
    """Is connection refused.

    Coordinates is connection refused logic for the surrounding Sonex flow.

    Args:
        exc: Input value used by the is connection refused operation.

    Returns:
        The computed result for is connection refused.
    """
    if isinstance(exc, ConnectionRefusedError):
        return True
    reason = getattr(exc, "reason", None)
    if isinstance(reason, ConnectionRefusedError):
        return True
    return "Connection refused" in str(exc)


def _is_tls_eof(exc: Exception) -> bool:
    """Is tls eof.

    Coordinates is tls eof logic for the surrounding Sonex flow.

    Args:
        exc: Input value used by the is tls eof operation.

    Returns:
        The computed result for is tls eof.
    """
    if isinstance(exc, ssl.SSLError) and exc.errno == ssl.SSL_ERROR_EOF:
        return True
    reason = getattr(exc, "reason", None)
    if isinstance(reason, ssl.SSLError) and reason.errno == ssl.SSL_ERROR_EOF:
        return True
    return "UNEXPECTED_EOF_WHILE_READING" in str(exc) or "EOF occurred in violation of protocol" in str(exc)


def _loopback_proxy_url() -> str | None:
    """Loopback proxy url.

    Coordinates loopback proxy url logic for the surrounding Sonex flow.

    Returns:
        The computed result for loopback proxy url.
    """
    proxies = urllib.request.getproxies()
    for key in ("https", "http", "all"):
        value = proxies.get(key)
        if not value:
            continue
        parsed = urllib.parse.urlparse(value)
        host = parsed.hostname
        if host in {"127.0.0.1", "localhost", "::1"}:
            return value
    return None
