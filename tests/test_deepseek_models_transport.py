from __future__ import annotations

import json
import ssl
import unittest
import urllib.error
from unittest.mock import patch

from src.auth.providers import normalize_provider_model
from src.llm.config import ProviderConfig
from src.llm.models import (
    AnthropicModelCatalog,
    DeepSeekModelCatalog,
    GeminiModelCatalog,
    OpenAIModelCatalog,
    model_choices_for_provider,
)
from src.llm.transport.base import ChatRequest, ProviderRequest
from src.llm.transport.deepseek import DeepSeekTransport, _chat_completions_url


class _FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class DeepSeekModelCatalogTests(unittest.TestCase):
    def test_lists_models_from_deepseek_api(self) -> None:
        config = ProviderConfig(name="deepseek", api_key="sk-test", base_url="https://api.deepseek.com")

        with patch("src.llm.models.urllib.request.urlopen") as urlopen:
            urlopen.return_value = _FakeResponse(
                {
                    "data": [
                        {"id": "deepseek-v4-flash", "object": "model"},
                        {"id": "deepseek-v4-pro", "object": "model"},
                    ]
                }
            )

            models = DeepSeekModelCatalog().list_models(config)

        self.assertEqual([model.id for model in models], ["deepseek-v4-pro", "deepseek-v4-flash"])
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.deepseek.com/models")
        self.assertEqual(request.headers["Authorization"], "Bearer sk-test")

    def test_falls_back_when_deepseek_model_api_fails(self) -> None:
        config = ProviderConfig(name="deepseek", api_key="sk-test", base_url="https://api.deepseek.com")

        with patch("src.llm.models.urllib.request.urlopen", side_effect=OSError("offline")):
            choices = model_choices_for_provider(config)

        self.assertIn("deepseek::deepseek-v4-pro", [choice["value"] for choice in choices])
        self.assertIn("deepseek::deepseek-v4-flash", [choice["value"] for choice in choices])

    def test_normalizes_legacy_deepseek_model_names(self) -> None:
        self.assertEqual(normalize_provider_model("deepseek", "Deepseek-v4-pro"), "deepseek-v4-pro")
        self.assertEqual(normalize_provider_model("deepseek", "deepseek-chat"), "deepseek-v4-flash")
        self.assertEqual(normalize_provider_model("deepseek", "deepseek-reasoner"), "deepseek-v4-flash")


class OfficialProviderModelCatalogTests(unittest.TestCase):
    def test_lists_openai_models_from_models_api(self) -> None:
        config = ProviderConfig(name="openai", api_key="sk-test", base_url="https://api.openai.com/v1")

        with patch("src.llm.models.urllib.request.urlopen") as urlopen:
            urlopen.return_value = _FakeResponse(
                {
                    "data": [
                        {"id": "gpt-5-mini", "object": "model"},
                        {"id": "gpt-5.2", "object": "model"},
                    ]
                }
            )

            models = OpenAIModelCatalog().list_models(config)

        self.assertEqual([model.id for model in models], ["gpt-5.2", "gpt-5-mini"])
        self.assertEqual([model.label for model in models], ["GPT-5.2", "GPT-5 Mini"])
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.openai.com/v1/models")
        self.assertEqual(request.headers["Authorization"], "Bearer sk-test")

    def test_lists_anthropic_models_from_models_api(self) -> None:
        config = ProviderConfig(name="anthropic", api_key="sk-ant", base_url="https://api.anthropic.com/v1")

        with patch("src.llm.models.urllib.request.urlopen") as urlopen:
            urlopen.return_value = _FakeResponse(
                {
                    "data": [
                        {
                            "id": "claude-sonnet-4-20250514",
                            "display_name": "Claude Sonnet 4",
                            "type": "model",
                        },
                        {
                            "id": "claude-opus-4-1-20250805",
                            "display_name": "Claude Opus 4.1",
                            "type": "model",
                        },
                    ]
                }
            )

            models = AnthropicModelCatalog().list_models(config)

        self.assertEqual([model.id for model in models], ["claude-opus-4-1-20250805", "claude-sonnet-4-20250514"])
        self.assertEqual([model.label for model in models], ["Claude Opus 4.1", "Claude Sonnet 4"])
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.anthropic.com/v1/models")
        self.assertEqual(request.headers["X-api-key"], "sk-ant")
        self.assertEqual(request.headers["Anthropic-version"], "2023-06-01")

    def test_lists_gemini_models_from_models_api(self) -> None:
        config = ProviderConfig(name="gemini", api_key="gem-key", base_url="https://generativelanguage.googleapis.com/v1beta")

        with patch("src.llm.models.urllib.request.urlopen") as urlopen:
            urlopen.return_value = _FakeResponse(
                {
                    "models": [
                        {
                            "name": "models/gemini-embedding-001",
                            "displayName": "Gemini Embedding",
                            "supportedGenerationMethods": ["embedContent"],
                        },
                        {
                            "name": "models/gemini-3-flash-preview",
                            "displayName": "Gemini 3 Flash Preview",
                            "supportedGenerationMethods": ["generateContent"],
                        },
                    ]
                }
            )

            models = GeminiModelCatalog().list_models(config)

        self.assertEqual([model.id for model in models], ["gemini-3-flash-preview"])
        self.assertEqual([model.label for model in models], ["Gemini 3 Flash Preview"])
        request = urlopen.call_args.args[0]
        self.assertEqual(
            request.full_url,
            "https://generativelanguage.googleapis.com/v1beta/models?key=gem-key",
        )

    def test_official_provider_model_choices_fall_back_to_curated_ids(self) -> None:
        expected = {
            "openai": "openai::gpt-5.2",
            "anthropic": "anthropic::claude-opus-4-1-20250805",
            "gemini": "gemini::gemini-3-flash-preview",
        }

        with patch("src.llm.models.urllib.request.urlopen", side_effect=OSError("offline")):
            for provider, value in expected.items():
                choices = model_choices_for_provider(ProviderConfig(name=provider))
                self.assertEqual(choices[0]["value"], value)


class DeepSeekTransportTests(unittest.TestCase):
    def test_builds_official_chat_completions_request(self) -> None:
        config = ProviderConfig(name="deepseek", api_key="sk-test", base_url="https://api.deepseek.com")
        chat_request = ChatRequest(
            messages=[{"role": "user", "content": "hello"}],
            tools=[{"type": "function", "function": {"name": "search", "parameters": {}}}],
            temperature=0.2,
        )
        provider_request = ProviderRequest(
            provider="deepseek",
            model="deepseek-v4-pro",
            payload=chat_request.to_payload("deepseek-v4-pro"),
            native_payload={},
        )

        with patch("src.llm.transport.deepseek.urllib.request.urlopen") as urlopen:
            urlopen.return_value = _FakeResponse(
                {
                    "choices": [
                        {"message": {"content": "ok"}, "finish_reason": "stop"},
                    ]
                }
            )
            response = DeepSeekTransport().send(provider_request, config)

        self.assertEqual(response["choices"][0]["message"]["content"], "ok")
        request = urlopen.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(request.full_url, "https://api.deepseek.com/chat/completions")
        self.assertEqual(request.headers["Authorization"], "Bearer sk-test")
        self.assertEqual(payload["model"], "deepseek-v4-pro")
        self.assertEqual(payload["messages"], [{"role": "user", "content": "hello"}])
        self.assertEqual(payload["temperature"], 0.2)
        self.assertIn("tools", payload)

    def test_chat_url_normalizes_v1_base_url(self) -> None:
        self.assertEqual(
            _chat_completions_url("https://api.deepseek.com/v1"),
            "https://api.deepseek.com/chat/completions",
        )

    def test_reports_urllib_resolved_loopback_proxy_on_connection_refused(self) -> None:
        config = ProviderConfig(name="deepseek", api_key="sk-test", base_url="https://api.deepseek.com")
        provider_request = ProviderRequest(
            provider="deepseek",
            model="deepseek-v4-pro",
            payload={"messages": [{"role": "user", "content": "hello"}]},
            native_payload={},
        )

        with (
            patch(
                "src.llm.transport.deepseek.urllib.request.urlopen",
                side_effect=urllib.error.URLError(ConnectionRefusedError(111, "Connection refused")),
            ),
            patch.dict(
                "os.environ",
                {
                    "HTTPS_PROXY": "http://127.0.0.1:7897",
                    "HTTP_PROXY": "http://127.0.0.1:7897",
                    "https_proxy": "http://127.0.0.1:10808",
                    "http_proxy": "http://127.0.0.1:10808",
                    "all_proxy": "socks5://127.0.0.1:10808",
                },
                clear=True,
            ),
        ):
            with self.assertRaisesRegex(
                Exception,
                "local proxy .*127\\.0\\.0\\.1:10808.*unset .*https_proxy.*all_proxy",
            ):
                DeepSeekTransport().send(provider_request, config)

    def test_reports_urllib_resolved_loopback_proxy_on_ssl_eof(self) -> None:
        config = ProviderConfig(name="deepseek", api_key="sk-test", base_url="https://api.deepseek.com")
        provider_request = ProviderRequest(
            provider="deepseek",
            model="deepseek-v4-pro",
            payload={"messages": [{"role": "user", "content": "hello"}]},
            native_payload={},
        )
        ssl_error = ssl.SSLError(ssl.SSL_ERROR_EOF, "EOF occurred in violation of protocol")

        with (
            patch(
                "src.llm.transport.deepseek.urllib.request.urlopen",
                side_effect=urllib.error.URLError(ssl_error),
            ),
            patch.dict(
                "os.environ",
                {
                    "HTTPS_PROXY": "http://127.0.0.1:7897",
                    "HTTP_PROXY": "http://127.0.0.1:7897",
                    "https_proxy": "http://127.0.0.1:10808",
                    "http_proxy": "http://127.0.0.1:10808",
                    "all_proxy": "socks5://127.0.0.1:10808",
                },
                clear=True,
            ),
        ):
            with self.assertRaisesRegex(
                Exception,
                "local proxy .*127\\.0\\.0\\.1:10808.*TLS connection closed unexpectedly",
            ):
                DeepSeekTransport().send(provider_request, config)


if __name__ == "__main__":
    unittest.main()
