"""Tests for provider authentication setup policy."""

from __future__ import annotations

from types import SimpleNamespace

from src.auth.setup_policy import api_key_prompt, auth_methods_for_provider, resolve_auth_method


def test_custom_policy_is_local_and_does_not_require_provider_status() -> None:
    methods = auth_methods_for_provider(
        "custom",
        auth=None,
        env_api_key=None,
        codex_status=lambda: (_ for _ in ()).throw(AssertionError("unused")),
    )

    assert [method["value"] for method in methods] == ["none", "api_key"]


def test_openai_unavailable_oauth_remains_visible_with_reason() -> None:
    methods = auth_methods_for_provider(
        "openai",
        auth=SimpleNamespace(managed_auth=None, oauth=None, api_key=None),
        env_api_key=None,
        codex_status=lambda: (False, "server missing"),
    )

    assert methods[0] == {
        "value": "__unavailable_oauth__",
        "label": "ChatGPT Subscription (Experimental) — Unavailable",
        "description": "server missing",
    }


def test_api_key_policy_marks_saved_authentication() -> None:
    methods = auth_methods_for_provider(
        "anthropic",
        auth=SimpleNamespace(managed_auth=None, oauth=None, api_key="saved"),
        env_api_key=None,
        codex_status=lambda: (True, None),
    )

    assert methods == [
        {"value": "api_key", "label": "API key — Connected"},
        {"value": "disconnect_api_key", "label": "Disconnect API key"},
    ]


def test_resolve_auth_method_reports_normalization_and_capability_errors() -> None:
    assert resolve_auth_method("openai", " API-KEY ") == ("api_key", None)
    assert resolve_auth_method("openai", "later") == ("later", "invalid")
    assert resolve_auth_method("openai", "__unavailable_oauth__") == (
        "__unavailable_oauth__",
        "unavailable_oauth",
    )
    assert resolve_auth_method("ollama", "oauth") == ("oauth", "unsupported_oauth")


def test_api_key_prompt_keeps_shared_copy_and_signup_hint() -> None:
    prompt = api_key_prompt("openai", "Paste it.")

    assert prompt == {
        "provider": "openai",
        "step": "api_key",
        "title": "OpenAI API key",
        "message": "Paste it.",
        "prompt": "API Key",
        "placeholder": "paste your key here",
        "help_text": "Haven't got an API Key? Get one at https://platform.openai.com/api-keys.",
        "mask": True,
    }
