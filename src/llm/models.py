"""Models support for language model configuration, catalogs, transports, and planning.

Implements the models module responsibilities used by Sonex runtime flows.
Key public entry points include ModelInfo, ModelCatalog, DeepSeekModelCatalog, OpenAIModelCatalog, AnthropicModelCatalog.
"""

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
    """Represents model info.

    Encapsulates model info data and behavior used by Sonex runtime flows.
    """
    id: str
    label: str
    provider: str
    description: str | None = None
    deprecated: bool = False
    source: str = "api"

    def to_choice(self) -> dict[str, str]:
        """Coordinates to choice for the current Sonex flow.

        Typical use: Use this function when runtime code needs to choice as part of a Sonex command, playback, auth, llm, or ui path.

        Example: to_choice() -> returns the value used by the surrounding Sonex flow.
        """
        label = f"{self.label} (deprecated)" if self.deprecated else self.label
        return {
            "value": f"{self.provider}::{self.id}",
            "label": label,
            "provider": _provider_label(self.provider),
        }


class ModelCatalog(Protocol):
    """Represents model catalog.

    Encapsulates model catalog data and behavior used by Sonex runtime flows. Extends protocol semantics.
    """
    def list_models(self, config: ProviderConfig) -> list[ModelInfo]:
        """Coordinates list models for the current Sonex flow.

        Typical use: Use this function when runtime code needs list models as part of a Sonex command, playback, auth, llm, or ui path.

        Example: list_models(config=...) -> returns the value used by the surrounding Sonex flow.
        """
        ...


DEEPSEEK_FALLBACK_MODELS = [
    ModelInfo(
        id="deepseek-v4-pro",
        label="deepseek-v4-pro",
        provider="deepseek",
        description="DeepSeek V4 Pro",
        source="fallback",
    ),
    ModelInfo(
        id="deepseek-v4-flash",
        label="deepseek-v4-flash",
        provider="deepseek",
        description="DeepSeek V4 Flash",
        source="fallback",
    ),
]
OPENAI_FALLBACK_MODELS = [
    ModelInfo(id="gpt-5.5", label="gpt-5.5", provider="openai", source="fallback"),
    ModelInfo(id="gpt-5.4", label="gpt-5.4", provider="openai", source="fallback"),
    ModelInfo(id="gpt-5.4-mini", label="gpt-5.4-mini", provider="openai", source="fallback"),
    ModelInfo(id="gpt-5.4-nano", label="gpt-5.4-nano", provider="openai", source="fallback"),
]
ANTHROPIC_FALLBACK_MODELS = [
    ModelInfo(id="claude-fable-5", label="claude-fable-5", provider="anthropic", source="fallback"),
    ModelInfo(
        id="claude-opus-4-8",
        label="claude-opus-4-8",
        provider="anthropic",
        source="fallback",
    ),
    ModelInfo(id="claude-sonnet-4-6", label="claude-sonnet-4-6", provider="anthropic", source="fallback"),
    ModelInfo(id="claude-haiku-4-5-20251001", label="claude-haiku-4-5-20251001", provider="anthropic", source="fallback"),
]
GEMINI_FALLBACK_MODELS = [
    ModelInfo(id="gemini-3.5-flash", label="gemini-3.5-flash", provider="gemini", source="fallback"),
    ModelInfo(id="gemini-3.1-pro", label="gemini-3.1-pro", provider="gemini", source="fallback"),
    ModelInfo(id="gemini-3.1-flash-lite", label="gemini-3.1-flash-lite", provider="gemini", source="fallback"),
    ModelInfo(id="gemini-2.5-pro", label="gemini-2.5-pro", provider="gemini", source="fallback"),
    ModelInfo(id="gemini-2.5-flash", label="gemini-2.5-flash", provider="gemini", source="fallback"),
    ModelInfo(id="gemini-2.5-flash-lite", label="gemini-2.5-flash-lite", provider="gemini", source="fallback"),
]

class DeepSeekModelCatalog(ModelCatalog):
    """Represents deep seek model catalog.

    Encapsulates deep seek model catalog data and behavior used by Sonex runtime flows. Extends model catalog semantics.
    """
    def list_models(self, config: ProviderConfig) -> list[ModelInfo]:
        """Coordinates list models for the current Sonex flow.

        Typical use: Use this function when runtime code needs list models as part of a Sonex command, playback, auth, llm, or ui path.

        Example: list_models(config=...) -> returns the value used by the surrounding Sonex flow.
        """
        try:
            models = _fetch_deepseek_models(config)
        except Exception:
            return list(DEEPSEEK_FALLBACK_MODELS)
        return models or list(DEEPSEEK_FALLBACK_MODELS)


class OpenAIModelCatalog(ModelCatalog):
    """Represents open a i model catalog.

    Encapsulates open a i model catalog data and behavior used by Sonex runtime flows. Extends model catalog semantics.
    """
    def list_models(self, config: ProviderConfig) -> list[ModelInfo]:
        """Coordinates list models for the current Sonex flow.

        Typical use: Use this function when runtime code needs list models as part of a Sonex command, playback, auth, llm, or ui path.

        Example: list_models(config=...) -> returns the value used by the surrounding Sonex flow.
        """
        try:
            models = _fetch_openai_models(config)
        except Exception:
            return list(OPENAI_FALLBACK_MODELS)
        return models or list(OPENAI_FALLBACK_MODELS)


class AnthropicModelCatalog(ModelCatalog):
    """Represents anthropic model catalog.

    Encapsulates anthropic model catalog data and behavior used by Sonex runtime flows. Extends model catalog semantics.
    """
    def list_models(self, config: ProviderConfig) -> list[ModelInfo]:
        """Coordinates list models for the current Sonex flow.

        Typical use: Use this function when runtime code needs list models as part of a Sonex command, playback, auth, llm, or ui path.

        Example: list_models(config=...) -> returns the value used by the surrounding Sonex flow.
        """
        try:
            models = _fetch_anthropic_models(config)
        except Exception:
            return list(ANTHROPIC_FALLBACK_MODELS)
        return models or list(ANTHROPIC_FALLBACK_MODELS)


class GeminiModelCatalog(ModelCatalog):
    """Represents gemini model catalog.

    Encapsulates gemini model catalog data and behavior used by Sonex runtime flows. Extends model catalog semantics.
    """
    def list_models(self, config: ProviderConfig) -> list[ModelInfo]:
        """Coordinates list models for the current Sonex flow.

        Typical use: Use this function when runtime code needs list models as part of a Sonex command, playback, auth, llm, or ui path.

        Example: list_models(config=...) -> returns the value used by the surrounding Sonex flow.
        """
        try:
            models = _fetch_gemini_models(config)
        except Exception:
            return list(GEMINI_FALLBACK_MODELS)
        return models or list(GEMINI_FALLBACK_MODELS)


def list_provider_models(config: ProviderConfig) -> list[ModelInfo]:
    """Coordinates list provider models for the current Sonex flow.

    Typical use: Use this function when runtime code needs list provider models as part of a Sonex command, playback, auth, llm, or ui path.

    Example: list_provider_models(config=...) -> returns the value used by the surrounding Sonex flow.
    """
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
    """Coordinates model choices for provider for the current Sonex flow.

    Typical use: Use this function when runtime code needs model choices for provider as part of a Sonex command, playback, auth, llm, or ui path.

    Example: model_choices_for_provider(config=...) -> returns the value used by the surrounding Sonex flow.
    """
    return [model.to_choice() for model in list_provider_models(config)]


def _fetch_deepseek_models(config: ProviderConfig) -> list[ModelInfo]:
    """Prepares fetch deepseek models for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs fetch deepseek models without duplicating the local rules.

    Example: _fetch_deepseek_models(config=...) -> returns the value used by the surrounding Sonex flow.
    """
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
        if not model_id or not _is_supported_deepseek_model(model_id):
            continue
        models.append(
            ModelInfo(
                id=model_id,
                label=model_id,
                provider="deepseek",
                source="api",
            )
        )
    return _sort_models(models)


def _fetch_openai_models(config: ProviderConfig) -> list[ModelInfo]:
    """Prepares fetch openai models for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs fetch openai models without duplicating the local rules.

    Example: _fetch_openai_models(config=...) -> returns the value used by the surrounding Sonex flow.
    """
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
        if not model_id or not _is_supported_openai_model(model_id):
            continue
        models.append(ModelInfo(id=model_id, label=model_id, provider="openai", source="api"))
    return _sort_models(models)


def _fetch_anthropic_models(config: ProviderConfig) -> list[ModelInfo]:
    """Prepares fetch anthropic models for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs fetch anthropic models without duplicating the local rules.

    Example: _fetch_anthropic_models(config=...) -> returns the value used by the surrounding Sonex flow.
    """
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
        if not model_id or not _is_supported_anthropic_model(model_id):
            continue
        models.append(ModelInfo(id=model_id, label=model_id, provider="anthropic", source="api"))
    return _sort_models(models)


def _fetch_gemini_models(config: ProviderConfig) -> list[ModelInfo]:
    """Prepares fetch gemini models for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs fetch gemini models without duplicating the local rules.

    Example: _fetch_gemini_models(config=...) -> returns the value used by the surrounding Sonex flow.
    """
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
        if not model_id or not _is_supported_gemini_model(model_id):
            continue
        models.append(ModelInfo(id=model_id, label=model_id, provider="gemini", source="api"))
    return _sort_models(models)


def _is_supported_deepseek_model(model_id: str) -> bool:
    return model_id in {"deepseek-v4-pro", "deepseek-v4-flash"}


def _is_supported_openai_model(model_id: str) -> bool:
    return model_id in {"gpt-5.5", "gpt-5.4", "gpt-5.4-mini", "gpt-5.4-nano"}


def _is_supported_anthropic_model(model_id: str) -> bool:
    if model_id in {"claude-mythos-5", "claude-mythos-preview"}:
        return False
    return model_id in {
        "claude-fable-5",
        "claude-opus-4-8",
        "claude-sonnet-4-6",
        "claude-haiku-4-5-20251001",
    }


def _is_supported_gemini_model(model_id: str) -> bool:
    if any(token in model_id for token in ("embedding", "live", "tts", "imagen", "veo", "lyria", "banana")):
        return False
    return model_id in {
        "gemini-3.5-flash",
        "gemini-3.1-pro",
        "gemini-3.1-flash-lite",
        "gemini-2.5-pro",
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
    }


def _read_json_response(request: urllib.request.Request, timeout: float | None) -> dict[str, Any]:
    """Prepares read json response for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs read json response without duplicating the local rules.

    Example: _read_json_response(request=..., timeout=...) -> returns the value used by the surrounding Sonex flow.
    """
    try:
        with urllib.request.urlopen(request, timeout=timeout or 5) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise LLMTransportError(f"Model list failed: {sanitize_error_message(detail)}") from exc
    return data if isinstance(data, dict) else {}


def _static_provider_models(config: ProviderConfig) -> list[ModelInfo]:
    """Prepares static provider models for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs static provider models without duplicating the local rules.

    Example: _static_provider_models(config=...) -> returns the value used by the surrounding Sonex flow.
    """
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
    """Prepares join url for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs join url without duplicating the local rules.

    Example: _join_url(base_url=..., path=...) -> returns the value used by the surrounding Sonex flow.
    """
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def _join_deepseek_url(base_url: str, path: str) -> str:
    """Prepares join deepseek url for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs join deepseek url without duplicating the local rules.

    Example: _join_deepseek_url(base_url=..., path=...) -> returns the value used by the surrounding Sonex flow.
    """
    normalized = base_url.rstrip("/")
    if normalized.endswith("/v1"):
        normalized = normalized[:-3]
    return f"{normalized}/{path.lstrip('/')}"


def _deepseek_label(model_id: str) -> str:
    """Prepares deepseek label for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs deepseek label without duplicating the local rules.

    Example: _deepseek_label(model_id=...) -> returns the value used by the surrounding Sonex flow.
    """
    labels = {
        "deepseek-v4-pro": "DeepSeek V4 Pro",
        "deepseek-v4-flash": "DeepSeek V4 Flash",
        "deepseek-chat": "deepseek-chat",
        "deepseek-reasoner": "deepseek-reasoner",
    }
    return labels.get(model_id, model_id)


def _openai_label(model_id: str) -> str:
    """Prepares openai label for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs openai label without duplicating the local rules.

    Example: _openai_label(model_id=...) -> returns the value used by the surrounding Sonex flow.
    """
    labels = {model.id: model.label for model in OPENAI_FALLBACK_MODELS}
    return labels.get(model_id, _title_model_id(model_id, upper_tokens={"gpt"}))


def _anthropic_label(model_id: str) -> str:
    """Prepares anthropic label for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs anthropic label without duplicating the local rules.

    Example: _anthropic_label(model_id=...) -> returns the value used by the surrounding Sonex flow.
    """
    labels = {model.id: model.label for model in ANTHROPIC_FALLBACK_MODELS}
    return labels.get(model_id, _title_model_id(model_id, upper_tokens={"claude"}))


def _gemini_label(model_id: str) -> str:
    """Prepares gemini label for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs gemini label without duplicating the local rules.

    Example: _gemini_label(model_id=...) -> returns the value used by the surrounding Sonex flow.
    """
    labels = {model.id: model.label for model in GEMINI_FALLBACK_MODELS}
    return labels.get(model_id, _title_model_id(model_id, upper_tokens={"gemini"}))


def _title_model_id(model_id: str, *, upper_tokens: set[str]) -> str:
    """Prepares title model id for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs title model id without duplicating the local rules.

    Example: _title_model_id(model_id=..., upper_tokens=...) -> returns the value used by the surrounding Sonex flow.
    """
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
    """Prepares provider label for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs provider label without duplicating the local rules.

    Example: _provider_label(provider=...) -> returns the value used by the surrounding Sonex flow.
    """
    labels = {
        "openai": "OpenAI",
        "anthropic": "Anthropic",
        "gemini": "Gemini",
        "deepseek": "Deepseek",
        "ollama": "Ollama",
    }
    return labels.get(provider, provider)


def _sort_models(models: list[ModelInfo]) -> list[ModelInfo]:
    """Prepares sort models for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs sort models without duplicating the local rules.

    Example: _sort_models(models=...) -> returns the value used by the surrounding Sonex flow.
    """
    priority = {
        "gpt-5.5": 0,
        "gpt-5.4": 1,
        "gpt-5.4-mini": 2,
        "gpt-5.4-nano": 3,
        "claude-fable-5": 0,
        "claude-opus-4-8": 1,
        "claude-sonnet-4-6": 2,
        "claude-haiku-4-5-20251001": 3,
        "gemini-3.5-flash": 0,
        "gemini-3.1-pro": 1,
        "gemini-3.1-flash-lite": 2,
        "gemini-2.5-pro": 3,
        "gemini-2.5-flash": 4,
        "gemini-2.5-flash-lite": 5,
        "deepseek-v4-pro": 0,
        "deepseek-v4-flash": 1,
    }
    return sorted(models, key=lambda model: (priority.get(model.id, 50), model.label.lower()))
