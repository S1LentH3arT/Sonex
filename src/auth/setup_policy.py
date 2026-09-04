"""Provider authentication method policy for interactive setup."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from src.auth.browser_oauth import browser_oauth_supported
from src.auth.providers import get_provider_capability, normalize_provider, provider_display_name


_API_KEY_SIGNUP_URLS = {
    "openai": "https://platform.openai.com/api-keys",
    "gemini": "https://aistudio.google.com/app/apikey",
    "anthropic": "https://platform.claude.com/settings/keys",
    "deepseek": "https://platform.deepseek.com/",
    "openrouter": "https://openrouter.ai/keys",
    "zai": "https://z.ai/",
    "kimi_global": "https://platform.kimi.ai/",
    "kimi_cn": "https://platform.moonshot.cn/",
    "minimax_global": "https://platform.minimax.io/",
    "minimax_cn": "https://platform.minimaxi.com/",
    "xai": "https://console.x.ai/",
}


def api_key_help_text(provider: str) -> str | None:
    signup_url = _API_KEY_SIGNUP_URLS.get(normalize_provider(provider))
    return f"Haven't got an API Key? Get one at {signup_url}." if signup_url else None


def api_key_prompt(provider: str, message: str) -> dict[str, Any]:
    """Build the stable API-key prompt fields for the setup UI."""
    name = provider_display_name(provider)
    return {
        "provider": provider,
        "step": "api_key",
        "title": f"{name} API key",
        "message": message,
        "prompt": "API Key",
        "placeholder": "paste your key here",
        "help_text": api_key_help_text(provider),
        "mask": True,
    }


def auth_methods_for_provider(
    provider: str,
    *,
    auth: Any | None,
    env_api_key: str | None,
    codex_status: Callable[[], tuple[bool, str | None]],
) -> list[dict[str, str]]:
    """Return setup choices without performing provider mutations."""
    capability = get_provider_capability(provider)
    name = normalize_provider(provider)
    methods: list[dict[str, str]] = []
    if name == "custom":
        return [
            {"value": "none", "label": "No authentication"},
            {"value": "api_key", "label": "Bearer API key"},
        ]
    if name == "openai":
        available, reason = codex_status()
        label = "ChatGPT Subscription (Experimental)"
        if auth and auth.managed_auth == "codex_app_server":
            label += " — Connected"
        if available:
            methods.append({"value": "oauth", "label": label})
        else:
            methods.append({
                "value": "__unavailable_oauth__",
                "label": f"{label} — Unavailable",
                "description": reason or "Codex App Server is unavailable.",
            })
    elif capability.supports_oauth and browser_oauth_supported(provider):
        base_label = "Google OAuth (Preview)" if name == "gemini" else "OAuth"
        label = f"{base_label} — Connected" if auth and auth.oauth else base_label
        methods.append({"value": "oauth", "label": label})
    if capability.supports_api_key:
        api_key_connected = bool(env_api_key or auth and auth.api_key)
        label = "API key — Connected" if api_key_connected else "API key"
        methods.append({"value": "api_key", "label": label})
    if auth and auth.managed_auth:
        methods.append({"value": "disconnect_oauth", "label": "Disconnect ChatGPT Subscription"})
    elif auth and auth.oauth:
        methods.append({"value": "disconnect_oauth", "label": "Disconnect OAuth"})
    if auth and auth.api_key:
        methods.append({"value": "disconnect_api_key", "label": "Disconnect API key"})
    return methods


def resolve_auth_method(provider: str, raw: str) -> tuple[str, str | None]:
    """Normalize an auth method and report a policy error, if any."""
    normalized = str(raw).strip().lower().replace("-", "_")
    if normalized == "__unavailable_oauth__":
        return normalized, "unavailable_oauth"
    if normalized in {"disconnect_oauth", "disconnect_api_key"}:
        return normalized, None
    if normalized not in {"oauth", "api_key"}:
        return normalized, "invalid"
    capability = get_provider_capability(provider)
    if normalized == "oauth" and not capability.supports_oauth:
        return normalized, "unsupported_oauth"
    if normalized == "api_key" and not capability.supports_api_key:
        return normalized, "unsupported_api_key"
    return normalized, None
