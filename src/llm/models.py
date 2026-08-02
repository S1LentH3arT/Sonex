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

from src.auth.providers import provider_display_name
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
        label="DeepSeek-V4-Pro",
        provider="deepseek",
        description="DeepSeek V4 Pro",
        source="fallback",
    ),
    ModelInfo(
        id="deepseek-v4-flash",
        label="DeepSeek-V4-Flash",
        provider="deepseek",
        description="DeepSeek V4 Flash",
        source="fallback",
    ),
]
OPENAI_FALLBACK_MODELS = [
    ModelInfo(id="gpt-5.5", label="GPT-5.5", provider="openai", source="fallback"),
    ModelInfo(id="gpt-5.4", label="GPT-5.4", provider="openai", source="fallback"),
    ModelInfo(id="gpt-5.4-mini", label="GPT-5.4 mini", provider="openai", source="fallback"),
    ModelInfo(id="gpt-5.4-nano", label="GPT-5.4 nano", provider="openai", source="fallback"),
]
ANTHROPIC_FALLBACK_MODELS = [
    ModelInfo(id="claude-fable-5", label="Claude Fable 5", provider="anthropic", source="fallback"),
    ModelInfo(
        id="claude-opus-4-8",
        label="Claude Opus 4.8",
        provider="anthropic",
        source="fallback",
    ),
    ModelInfo(id="claude-sonnet-4-6", label="Claude Sonnet 4.6", provider="anthropic", source="fallback"),
    ModelInfo(id="claude-haiku-4-5-20251001", label="Claude Haiku 4.5", provider="anthropic", source="fallback"),
]
GEMINI_FALLBACK_MODELS = [
    ModelInfo(id="gemini-3.5-flash", label="Gemini 3.5 Flash", provider="gemini", source="fallback"),
    ModelInfo(id="gemini-3.1-pro", label="Gemini 3.1 Pro", provider="gemini", source="fallback"),
    ModelInfo(id="gemini-3.1-flash-lite", label="Gemini 3.1 Flash-Lite", provider="gemini", source="fallback"),
    ModelInfo(id="gemini-2.5-pro", label="Gemini 2.5 Pro", provider="gemini", source="fallback"),
    ModelInfo(id="gemini-2.5-flash", label="Gemini 2.5 Flash", provider="gemini", source="fallback"),
    ModelInfo(id="gemini-2.5-flash-lite", label="Gemini 2.5 Flash-Lite", provider="gemini", source="fallback"),
]

OPENAI_COMPATIBLE_FALLBACK_MODELS: dict[str, list[ModelInfo]] = {
    "openrouter": [ModelInfo(id="openrouter/auto", label="Auto", provider="openrouter", source="fallback")],
    "zai": [ModelInfo(id="glm-5.1", label="GLM-5.1", provider="zai", source="fallback")],
    "kimi_global": [ModelInfo(id="kimi-k2.6", label="Kimi K2.6", provider="kimi_global", source="fallback")],
    "kimi_cn": [ModelInfo(id="kimi-k2.5", label="Kimi K2.5", provider="kimi_cn", source="fallback")],
    "minimax_global": [ModelInfo(id="MiniMax-M2.7", label="MiniMax M2.7", provider="minimax_global", source="fallback")],
    "minimax_cn": [ModelInfo(id="MiniMax-M2.7", label="MiniMax M2.7", provider="minimax_cn", source="fallback")],
    "xai": [ModelInfo(id="grok-4.5", label="Grok 4.5", provider="xai", source="fallback")],
}

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


class OpenAICompatibleModelCatalog(ModelCatalog):
    """Discover chat models exposed by a first-class OpenAI-compatible provider."""

    def list_models(self, config: ProviderConfig) -> list[ModelInfo]:
        fallback = OPENAI_COMPATIBLE_FALLBACK_MODELS.get(config.name, [])
        try:
            models = _fetch_openai_compatible_models(config)
        except Exception:
            return list(fallback)
        return models or list(fallback)


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
        **{
            provider: OpenAICompatibleModelCatalog()
            for provider in OPENAI_COMPATIBLE_FALLBACK_MODELS
        },
    }
    catalog = catalogs.get(config.name)
    models = catalog.list_models(config) if catalog else _static_provider_models(config)
    _remember_model_labels(models)
    return models


_MODEL_LABELS: dict[tuple[str, str], str] = {}


def _remember_model_labels(models: list[ModelInfo]) -> None:
    for model in models:
        _MODEL_LABELS[(model.provider, model.id)] = model.label


def model_display_name(provider: str, model_id: str) -> str:
    """Return an explicit provider display name, or the exact API model ID."""
    remembered = _MODEL_LABELS.get((provider, model_id))
    if remembered:
        return remembered
    for models in (
        DEEPSEEK_FALLBACK_MODELS,
        OPENAI_FALLBACK_MODELS,
        ANTHROPIC_FALLBACK_MODELS,
        GEMINI_FALLBACK_MODELS,
        *OPENAI_COMPATIBLE_FALLBACK_MODELS.values(),
    ):
        for model in models:
            if model.provider == provider and model.id == model_id:
                return model.label
    return model_id


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
        label = _model_label_from_metadata(item, "deepseek", model_id)
        models.append(
            ModelInfo(
                id=model_id,
                label=label,
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
        label = _model_label_from_metadata(item, "openai", model_id)
        models.append(ModelInfo(id=model_id, label=label, provider="openai", source="api"))
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
        label = _model_label_from_metadata(item, "anthropic", model_id)
        models.append(ModelInfo(id=model_id, label=label, provider="anthropic", source="api"))
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
    if config.extra_headers.get("x-goog-user-project"):
        request.add_header("x-goog-user-project", config.extra_headers["x-goog-user-project"])

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
        label = str(item.get("displayName") or model_id).strip() or model_id
        models.append(ModelInfo(id=model_id, label=label, provider="gemini", source="api"))
    return _sort_models(models)


def _fetch_openai_compatible_models(config: ProviderConfig) -> list[ModelInfo]:
    if not config.api_key:
        raise LLMTransportError(f"{provider_display_name(config.name)} model list failed: missing API key")
    if not config.base_url:
        raise LLMTransportError(f"{provider_display_name(config.name)} model list failed: missing base URL")
    request = urllib.request.Request(_join_url(config.base_url, "models"), method="GET")
    request.add_header("Authorization", f"Bearer {config.api_key}")
    for key, value in config.extra_headers.items():
        request.add_header(key, value)

    data = _read_json_response(request, config.timeout)
    raw_models = data.get("data") if isinstance(data, dict) else None
    if not isinstance(raw_models, list):
        return []

    models: list[ModelInfo] = []
    for item in raw_models:
        if not isinstance(item, dict):
            continue
        model_id = str(item.get("id") or "").strip()
        if not model_id or not _is_agent_text_model(item, model_id):
            continue
        label = _model_label_from_metadata(item, config.name, model_id)
        models.append(ModelInfo(id=model_id, label=label, provider=config.name, source="api"))
    return _sort_models(models)


def _is_supported_deepseek_model(model_id: str) -> bool:
    normalized = model_id.lower()
    if normalized in {"deepseek-chat", "deepseek-reasoner"}:
        return False
    return not any(token in normalized for token in ("embedding", "image", "rerank", "tts"))


def _is_supported_openai_model(model_id: str) -> bool:
    normalized = model_id.lower()
    excluded = (
        "babbage",
        "curie",
        "dall-e",
        "davinci",
        "audio",
        "embedding",
        "image",
        "moderation",
        "realtime",
        "search",
        "transcribe",
        "tts",
        "whisper",
    )
    return not any(token in normalized for token in excluded)


def _is_supported_anthropic_model(model_id: str) -> bool:
    return bool(model_id.strip())


def _is_supported_gemini_model(model_id: str) -> bool:
    return not any(
        token in model_id.lower()
        for token in ("embedding", "live", "tts", "imagen", "veo", "lyria", "banana")
    )


def _is_agent_text_model(item: dict[str, Any], model_id: str) -> bool:
    normalized = model_id.casefold()
    excluded = (
        "audio", "embed", "embedding", "image", "imagen", "moderation",
        "rerank", "realtime", "speech", "transcrib", "tts", "veo", "whisper",
    )
    if any(token in normalized for token in excluded):
        return False
    architecture = item.get("architecture")
    modalities = item.get("output_modalities")
    if modalities is None and isinstance(architecture, dict):
        modalities = architecture.get("output_modalities")
    if isinstance(modalities, list) and modalities:
        normalized_modalities = {str(value).casefold() for value in modalities}
        if "text" not in normalized_modalities:
            return False
    supported_parameters = item.get("supported_parameters")
    if isinstance(supported_parameters, list) and supported_parameters:
        normalized_parameters = {str(value).casefold() for value in supported_parameters}
        supports_tools = any(
            parameter.startswith("tool")
            or parameter in {"functions", "function_calling"}
            for parameter in normalized_parameters
        )
        if not supports_tools:
            return False
    return True


def _model_label_from_metadata(item: dict[str, Any], provider: str, model_id: str) -> str:
    for key in ("display_name", "displayName", "name"):
        value = str(item.get(key) or "").strip()
        if value and value != model_id:
            return value
    known = {
        (model.provider, model.id): model.label
        for models in (
            DEEPSEEK_FALLBACK_MODELS,
            OPENAI_FALLBACK_MODELS,
            ANTHROPIC_FALLBACK_MODELS,
            GEMINI_FALLBACK_MODELS,
            *OPENAI_COMPATIBLE_FALLBACK_MODELS.values(),
        )
        for model in models
    }
    if (provider, model_id) in known:
        return known[(provider, model_id)]
    if provider == "deepseek" and model_id.casefold().startswith("deepseek-"):
        parts = model_id.split("-")
        return "-".join(["DeepSeek", *[part.upper() if part[:1].casefold() == "v" and part[1:].isdigit() else part.title() for part in parts[1:]]])
    return model_id


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


def _provider_label(provider: str) -> str:
    """Prepares provider label for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs provider label without duplicating the local rules.

    Example: _provider_label(provider=...) -> returns the value used by the surrounding Sonex flow.
    """
    return provider_display_name(provider)


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
