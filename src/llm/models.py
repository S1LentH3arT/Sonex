from __future__ import annotations

import json
import urllib.error
import urllib.parse
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
OPENAI_FALLBACK_MODELS = [
    ModelInfo(id="gpt-5.2", label="GPT-5.2", provider="openai", source="fallback"),
    ModelInfo(id="gpt-5.2-pro", label="GPT-5.2 Pro", provider="openai", source="fallback"),
    ModelInfo(id="gpt-5-mini", label="GPT-5 Mini", provider="openai", source="fallback"),
    ModelInfo(id="gpt-5-nano", label="GPT-5 Nano", provider="openai", source="fallback"),
    ModelInfo(id="gpt-4.1", label="GPT-4.1", provider="openai", source="fallback"),
    ModelInfo(id="gpt-4.1-mini", label="GPT-4.1 Mini", provider="openai", source="fallback"),
]
ANTHROPIC_FALLBACK_MODELS = [
    ModelInfo(
        id="claude-opus-4-1-20250805",
        label="Claude Opus 4.1",
        provider="anthropic",
        source="fallback",
    ),
    ModelInfo(id="claude-sonnet-4-20250514", label="Claude Sonnet 4", provider="anthropic", source="fallback"),
    ModelInfo(id="claude-3-7-sonnet-20250219", label="Claude Sonnet 3.7", provider="anthropic", source="fallback"),
    ModelInfo(id="claude-3-5-haiku-20241022", label="Claude Haiku 3.5", provider="anthropic", source="fallback"),
]
GEMINI_FALLBACK_MODELS = [
    ModelInfo(id="gemini-3-flash-preview", label="Gemini 3 Flash Preview", provider="gemini", source="fallback"),
    ModelInfo(id="gemini-3-pro-preview", label="Gemini 3 Pro Preview", provider="gemini", source="fallback"),
    ModelInfo(id="gemini-2.5-pro", label="Gemini 2.5 Pro", provider="gemini", source="fallback"),
    ModelInfo(id="gemini-2.5-flash", label="Gemini 2.5 Flash", provider="gemini", source="fallback"),
]

class DeepSeekModelCatalog(ModelCatalog):
    def list_models(self, config: ProviderConfig) -> list[ModelInfo]:
        try:
            models = _fetch_deepseek_models(config)
        except Exception:
            return list(DEEPSEEK_FALLBACK_MODELS)
        return models or list(DEEPSEEK_FALLBACK_MODELS)


class OpenAIModelCatalog(ModelCatalog):
    def list_models(self, config: ProviderConfig) -> list[ModelInfo]:
        try:
            models = _fetch_openai_models(config)
        except Exception:
            return list(OPENAI_FALLBACK_MODELS)
        return models or list(OPENAI_FALLBACK_MODELS)


class AnthropicModelCatalog(ModelCatalog):
    def list_models(self, config: ProviderConfig) -> list[ModelInfo]:
        try:
            models = _fetch_anthropic_models(config)
        except Exception:
            return list(ANTHROPIC_FALLBACK_MODELS)
        return models or list(ANTHROPIC_FALLBACK_MODELS)


class GeminiModelCatalog(ModelCatalog):
    def list_models(self, config: ProviderConfig) -> list[ModelInfo]:
        try:
            models = _fetch_gemini_models(config)
        except Exception:
            return list(GEMINI_FALLBACK_MODELS)
        return models or list(GEMINI_FALLBACK_MODELS)


def list_provider_models(config: ProviderConfig) -> list[ModelInfo]:
    catalogs: dict[str, ModelCatalog] = {
        "openai": OpenAIModelCatalog(),
        "anthropic": AnthropicModelCatalog(),
        "gemini": GeminiModelCatalog(),
        "deepseek": DeepSeekModelCatalog(),
    }
    catalog = catalogs.get(config.name)
    if catalog:
        return catalog.list_models(config)
    return _static_provider_models(config)


def model_choices_for_provider(config: ProviderConfig) -> list[dict[str, str]]:
    return [model.to_choice() for model in list_provider_models(config)]


def _fetch_deepseek_models(config: ProviderConfig) -> list[ModelInfo]:
    url = _join_deepseek_url(config.base_url or "https://api.deepseek.com", "models")
    request = urllib.request.Request(url, method="GET")
    if config.api_key:
        request.add_header("Authorization", f"Bearer {config.api_key}")

    try:
        with urllib.request.urlopen(request, timeout=config.timeout or 5) as response:
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


def _fetch_openai_models(config: ProviderConfig) -> list[ModelInfo]:
    if not config.api_key:
        raise LLMTransportError("OpenAI model list failed: missing API key")
    request = urllib.request.Request(_join_url(config.base_url or "https://api.openai.com/v1", "models"), method="GET")
    request.add_header("Authorization", f"Bearer {config.api_key}")

    data = _read_json_response(request, config.timeout)
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
        models.append(ModelInfo(id=model_id, label=_openai_label(model_id), provider="openai", source="api"))
    return _sort_models(models)


def _fetch_anthropic_models(config: ProviderConfig) -> list[ModelInfo]:
    if not config.api_key:
        raise LLMTransportError("Anthropic model list failed: missing API key")
    request = urllib.request.Request(_join_url(config.base_url or "https://api.anthropic.com/v1", "models"), method="GET")
    request.add_header("x-api-key", config.api_key)
    request.add_header("anthropic-version", config.api_version or "2023-06-01")

    data = _read_json_response(request, config.timeout)
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
        label = str(item.get("display_name") or "").strip() or _anthropic_label(model_id)
        models.append(ModelInfo(id=model_id, label=label, provider="anthropic", source="api"))
    return _sort_models(models)


def _fetch_gemini_models(config: ProviderConfig) -> list[ModelInfo]:
    authorization = config.extra_headers.get("Authorization")
    if not config.api_key and not authorization:
        raise LLMTransportError("Gemini model list failed: missing API key or OAuth token")
    url = _join_url(config.base_url or "https://generativelanguage.googleapis.com/v1beta", "models")
    if config.api_key:
        url = f"{url}?{urllib.parse.urlencode({'key': config.api_key})}"
    request = urllib.request.Request(url, method="GET")
    if authorization:
        request.add_header("Authorization", authorization)

    data = _read_json_response(request, config.timeout)
    raw_models = data.get("models") if isinstance(data, dict) else None
    if not isinstance(raw_models, list):
        return []

    models: list[ModelInfo] = []
    for item in raw_models:
        if not isinstance(item, dict):
            continue
        methods = item.get("supportedGenerationMethods")
        if not isinstance(methods, list) or "generateContent" not in methods:
            continue
        model_id = str(item.get("name") or "").strip()
        if model_id.startswith("models/"):
            model_id = model_id.removeprefix("models/")
        if not model_id:
            continue
        label = str(item.get("displayName") or "").strip() or _gemini_label(model_id)
        models.append(ModelInfo(id=model_id, label=label, provider="gemini", source="api"))
    return _sort_models(models)


def _read_json_response(request: urllib.request.Request, timeout: float | None) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(request, timeout=timeout or 5) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise LLMTransportError(f"Model list failed: {sanitize_error_message(detail)}") from exc
    return data if isinstance(data, dict) else {}


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


def _join_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


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


def _openai_label(model_id: str) -> str:
    labels = {model.id: model.label for model in OPENAI_FALLBACK_MODELS}
    return labels.get(model_id, _title_model_id(model_id, upper_tokens={"gpt"}))


def _anthropic_label(model_id: str) -> str:
    labels = {model.id: model.label for model in ANTHROPIC_FALLBACK_MODELS}
    return labels.get(model_id, _title_model_id(model_id, upper_tokens={"claude"}))


def _gemini_label(model_id: str) -> str:
    labels = {model.id: model.label for model in GEMINI_FALLBACK_MODELS}
    return labels.get(model_id, _title_model_id(model_id, upper_tokens={"gemini"}))


def _title_model_id(model_id: str, *, upper_tokens: set[str]) -> str:
    words: list[str] = []
    for token in model_id.replace("_", "-").split("-"):
        if not token:
            continue
        if token.lower() in upper_tokens:
            words.append(token.upper())
        elif token.replace(".", "").isdigit():
            words.append(token)
        else:
            words.append(token.capitalize())
    return " ".join(words) or model_id


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
        "gpt-5.2": 0,
        "gpt-5.2-pro": 1,
        "gpt-5-mini": 2,
        "gpt-5-nano": 3,
        "gpt-4.1": 10,
        "gpt-4.1-mini": 11,
        "claude-opus-4-1-20250805": 0,
        "claude-sonnet-4-20250514": 1,
        "claude-3-7-sonnet-20250219": 2,
        "claude-3-5-haiku-20241022": 3,
        "gemini-3-flash-preview": 0,
        "gemini-3-pro-preview": 1,
        "gemini-2.5-pro": 2,
        "gemini-2.5-flash": 3,
        "deepseek-v4-pro": 0,
        "deepseek-v4-flash": 1,
        "deepseek-chat": 90,
        "deepseek-reasoner": 91,
    }
    return sorted(models, key=lambda model: (priority.get(model.id, 50), model.label.lower()))
