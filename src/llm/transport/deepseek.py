from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from src.llm.config import ProviderConfig
from src.llm.transport.base import LLMTransportError, ProviderRequest, sanitize_error_message
from src.log import get_logger

logger = get_logger(__name__)


class DeepSeekTransport:
    def send(self, request: ProviderRequest, config: ProviderConfig) -> Any:
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
            safe_error = sanitize_error_message(exc)
            logger.error(f"Transport request failed for provider 'deepseek': {safe_error}.")
            raise LLMTransportError(f"LLM provider 'deepseek' request failed: {safe_error}") from exc


def _chat_completions_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.endswith("/chat/completions"):
        return normalized
    if normalized.endswith("/v1"):
        normalized = normalized[:-3]
    return f"{normalized}/chat/completions"
