from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol

from src.llm.config import ProviderConfig
from src.llm.transport import LLMTransportError, sanitize_error_message


@dataclass(frozen=True, slots=True)
class ModelInfo:
    id: str
    label: str
    provider: str
    description: str | None = None
    deprecated: bool = False
    source: str = "api"

    def to_choice(self) -> dict[str, str]:
        label = f"{self.label} (deprecated)" if self.deprecated else self.label
        return {
            "value": f"{self.provider}::{self.id}",
            "label": label,
            "provider": _provider_label(self.provider),
        }


class ModelCatalog(Protocol):
    def list_models(self, config: ProviderConfig) -> list[ModelInfo]:
        ...


DEEPSEEK_FALLBACK_MODELS = [
    ModelInfo(
        id="deepseek-v4-pro",
        label="DeepSeek V4 Pro",
        provider="deepseek",
        description="DeepSeek V4 Pro",
        source="fallback",
    ),
    ModelInfo(
        id="deepseek-v4-flash",
        label="DeepSeek V4 Flash",
        provider="deepseek",
        description="DeepSeek V4 Flash",
        source="fallback",
    ),
    ModelInfo(
        id="deepseek-chat",
        label="deepseek-chat",
        provider="deepseek",
        description="Compatibility alias for DeepSeek V4 Flash non-thinking mode.",
        deprecated=True,
        source="fallback",
    ),
    ModelInfo(
        id="deepseek-reasoner",
        label="deepseek-reasoner",
        provider="deepseek",
        description="Compatibility alias for DeepSeek V4 Flash thinking mode.",
        deprecated=True,
        source="fallback",
    ),
]


class DeepSeekModelCatalog(ModelCatalog):
    def list_models(self, config: ProviderConfig) -> list[ModelInfo]:
        try:
            models = _fetch_deepseek_models(config)
        except Exception:
            return list(DEEPSEEK_FALLBACK_MODELS)
        return models or list(DEEPSEEK_FALLBACK_MODELS)


def list_provider_models(config: ProviderConfig) -> list[ModelInfo]:
    if config.name == "deepseek":
        return DeepSeekModelCatalog().list_models(config)
    return _static_provider_models(config)


def model_choices_for_provider(config: ProviderConfig) -> list[dict[str, str]]:
    return [model.to_choice() for model in list_provider_models(config)]


def _fetch_deepseek_models(config: ProviderConfig) -> list[ModelInfo]:
    url = _join_deepseek_url(config.base_url or "https://api.deepseek.com", "models")
    request = urllib.request.Request(url, method="GET")
    if config.api_key:
        request.add_header("Authorization", f"Bearer {config.api_key}")

    try:
        with urllib.request.urlopen(request, timeout=config.timeout or 20) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise LLMTransportError(f"DeepSeek model list failed: {sanitize_error_message(detail)}") from exc

    raw_models = data.get("data") if isinstance(data, dict) else None
    if not isinstance(raw_models, list):
        return []

    models: list[ModelInfo] = []
    for item in raw_models:
        if not isinstance(item, dict):
            continue
        model_id = str(item.get("id") or "").strip()
        if not model_id:
            continue
        models.append(
            ModelInfo(
                id=model_id,
                label=_deepseek_label(model_id),
                provider="deepseek",
                deprecated=model_id in {"deepseek-chat", "deepseek-reasoner"},
                source="api",
            )
        )
    return _sort_models(models)


def _static_provider_models(config: ProviderConfig) -> list[ModelInfo]:
    if not config.model:
        return []
    return [
        ModelInfo(
            id=config.model,
            label=config.model,
            provider=config.name,
            source="static",
        )
    ]


def _join_deepseek_url(base_url: str, path: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.endswith("/v1"):
        normalized = normalized[:-3]
    return f"{normalized}/{path.lstrip('/')}"


def _deepseek_label(model_id: str) -> str:
    labels = {
        "deepseek-v4-pro": "DeepSeek V4 Pro",
        "deepseek-v4-flash": "DeepSeek V4 Flash",
        "deepseek-chat": "deepseek-chat",
        "deepseek-reasoner": "deepseek-reasoner",
    }
    return labels.get(model_id, model_id)


def _provider_label(provider: str) -> str:
    labels = {
        "openai": "OpenAI",
        "anthropic": "Anthropic",
        "gemini": "Gemini",
        "deepseek": "DeepSeek",
        "ollama": "Ollama",
    }
    return labels.get(provider, provider)


def _sort_models(models: list[ModelInfo]) -> list[ModelInfo]:
    priority = {
        "deepseek-v4-pro": 0,
        "deepseek-v4-flash": 1,
        "deepseek-chat": 90,
        "deepseek-reasoner": 91,
    }
    return sorted(models, key=lambda model: (priority.get(model.id, 50), model.label.lower()))
