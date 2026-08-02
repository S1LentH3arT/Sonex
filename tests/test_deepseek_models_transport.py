"""Tests test deepseek models transport.

Contains pytest coverage for the test deepseek models transport behavior.
"""

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
    OpenAICompatibleModelCatalog,
    list_provider_models,
    model_choices_for_provider,
    model_display_name,
)
from src.llm.transport.base import ChatRequest, ProviderRequest
from src.llm.transport.deepseek import DeepSeekTransport, _chat_completions_url


class _FakeResponse:
    """Groups related fake response cases.

    Collects assertions that exercise fake response behavior without mixing unrelated fixtures.
    """
    def __init__(self, payload: dict[str, object]) -> None:
        """Verifies that init behaves as expected.

        Typical use: Use this in automated tests when guarding the init behavior against regressions.

        Example: __init__() -> passes without assertion failures when the behavior remains correct.
        """
        self.payload = payload

    def __enter__(self) -> "_FakeResponse":
        """Verifies that enter behaves as expected.

        Typical use: Use this in automated tests when guarding the enter behavior against regressions.

        Example: __enter__() -> passes without assertion failures when the behavior remains correct.
        """
        return self

    def __exit__(self, *args: object) -> None:
        """Verifies that exit behaves as expected.

        Typical use: Use this in automated tests when guarding the exit behavior against regressions.

        Example: __exit__() -> passes without assertion failures when the behavior remains correct.
        """
        return None

    def read(self) -> bytes:
        """Verifies that read behaves as expected.

        Typical use: Use this in automated tests when guarding the read behavior against regressions.

        Example: read() -> passes without assertion failures when the behavior remains correct.
        """
        return json.dumps(self.payload).encode("utf-8")


class DeepSeekModelCatalogTests(unittest.TestCase):
    """Groups related deep seek model catalog tests cases.

    Collects assertions that exercise deep seek model catalog tests behavior without mixing unrelated fixtures.
    """
    def test_lists_models_from_deepseek_api(self) -> None:
        """Verifies that lists models from deepseek api behaves as expected.

        Typical use: Use this in automated tests when guarding the lists models from deepseek api behavior against regressions.

        Example: test_lists_models_from_deepseek_api() -> passes without assertion failures when the behavior remains correct.
        """
        config = ProviderConfig(name="deepseek", api_key="sk-test", base_url="https://api.deepseek.com")

        with patch("src.llm.models.urllib.request.urlopen") as urlopen:
            urlopen.return_value = _FakeResponse(
                {
                    "data": [
                        {"id": "deepseek-v4-flash-0731", "object": "model"},
                        {"id": "deepseek-v4-flash", "object": "model"},
                        {"id": "deepseek-v4-pro", "object": "model"},
                        {"id": "deepseek-chat", "object": "model"},
                        {"id": "deepseek-reasoner", "object": "model"},
                    ]
                }
            )

            models = DeepSeekModelCatalog().list_models(config)

        self.assertEqual(
            [model.id for model in models],
            ["deepseek-v4-pro", "deepseek-v4-flash", "deepseek-v4-flash-0731"],
        )
        self.assertEqual(
            [model.label for model in models],
            ["DeepSeek-V4-Pro", "DeepSeek-V4-Flash", "DeepSeek-V4-Flash-0731"],
        )
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.deepseek.com/models")
        self.assertEqual(request.headers["Authorization"], "Bearer sk-test")

    def test_falls_back_when_deepseek_model_api_fails(self) -> None:
        """Verifies that falls back when deepseek model api fails behaves as expected.

        Typical use: Use this in automated tests when guarding the falls back when deepseek model api fails behavior against regressions.

        Example: test_falls_back_when_deepseek_model_api_fails() -> passes without assertion failures when the behavior remains correct.
        """
        config = ProviderConfig(name="deepseek", api_key="sk-test", base_url="https://api.deepseek.com")

        with patch("src.llm.models.urllib.request.urlopen", side_effect=OSError("offline")):
            choices = model_choices_for_provider(config)

        self.assertEqual(
            [choice["value"] for choice in choices],
            [
                "deepseek::deepseek-v4-pro",
                "deepseek::deepseek-v4-flash",
            ],
        )

    def test_normalizes_legacy_deepseek_model_names(self) -> None:
        """Verifies that normalizes legacy deepseek model names behaves as expected.

        Typical use: Use this in automated tests when guarding the normalizes legacy deepseek model names behavior against regressions.

        Example: test_normalizes_legacy_deepseek_model_names() -> passes without assertion failures when the behavior remains correct.
        """
        self.assertEqual(normalize_provider_model("deepseek", "Deepseek-v4-pro"), "Deepseek-v4-pro")
        self.assertEqual(normalize_provider_model("deepseek", "deepseek-chat"), "deepseek-chat")
        self.assertEqual(normalize_provider_model("deepseek", "deepseek-reasoner"), "deepseek-reasoner")
        self.assertEqual(normalize_provider_model("deepseek", "deepseek-v4"), "deepseek-v4")
        self.assertEqual(normalize_provider_model("deepseek", "deepseek-v3"), "deepseek-v3")
        self.assertEqual(
            normalize_provider_model("deepseek", "deepseek-v4-flash-0731"),
            "deepseek-v4-flash-0731",
        )


class OfficialProviderModelCatalogTests(unittest.TestCase):
    """Groups related official provider model catalog tests cases.

    Collects assertions that exercise official provider model catalog tests behavior without mixing unrelated fixtures.
    """
    def test_lists_openai_models_from_models_api(self) -> None:
        """Verifies that lists openai models from models api behaves as expected.

        Typical use: Use this in automated tests when guarding the lists openai models from models api behavior against regressions.

        Example: test_lists_openai_models_from_models_api() -> passes without assertion failures when the behavior remains correct.
        """
        config = ProviderConfig(name="openai", api_key="sk-test", base_url="https://api.openai.com/v1")

        with patch("src.llm.models.urllib.request.urlopen") as urlopen:
            urlopen.return_value = _FakeResponse(
                {
                    "data": [
                        {"id": "gpt-5.4-mini", "object": "model"},
                        {"id": "gpt-5.5", "object": "model"},
                        {"id": "gpt-6-preview", "object": "model"},
                        {"id": "text-embedding-4", "object": "model"},
                    ]
                }
            )

            models = OpenAIModelCatalog().list_models(config)

        self.assertEqual([model.id for model in models], ["gpt-5.5", "gpt-5.4-mini", "gpt-6-preview"])
        self.assertEqual([model.label for model in models], ["GPT-5.5", "GPT-5.4 mini", "gpt-6-preview"])
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.openai.com/v1/models")
        self.assertEqual(request.headers["Authorization"], "Bearer sk-test")

    def test_lists_anthropic_models_from_models_api(self) -> None:
        """Verifies that lists anthropic models from models api behaves as expected.

        Typical use: Use this in automated tests when guarding the lists anthropic models from models api behavior against regressions.

        Example: test_lists_anthropic_models_from_models_api() -> passes without assertion failures when the behavior remains correct.
        """
        config = ProviderConfig(name="anthropic", api_key="sk-ant", base_url="https://api.anthropic.com/v1")

        with patch("src.llm.models.urllib.request.urlopen") as urlopen:
            urlopen.return_value = _FakeResponse(
                {
                    "data": [
                        {
                            "id": "claude-sonnet-4-6",
                            "display_name": "Claude Sonnet 4.6",
                            "type": "model",
                        },
                        {
                            "id": "claude-mythos-5",
                            "display_name": "Claude Mythos 5",
                            "type": "model",
                        },
                        {
                            "id": "claude-fable-5",
                            "display_name": "Claude Fable 5",
                            "type": "model",
                        },
                    ]
                }
            )

            models = list_provider_models(config)

        self.assertEqual(
            [model.id for model in models],
            ["claude-fable-5", "claude-sonnet-4-6", "claude-mythos-5"],
        )
        self.assertEqual(
            [model.label for model in models],
            ["Claude Fable 5", "Claude Sonnet 4.6", "Claude Mythos 5"],
        )
        self.assertEqual(
            model_display_name("anthropic", "claude-sonnet-4-6"),
            "Claude Sonnet 4.6",
        )
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.anthropic.com/v1/models")
        self.assertEqual(request.headers["X-api-key"], "sk-ant")
        self.assertEqual(request.headers["Anthropic-version"], "2023-06-01")

    def test_lists_gemini_models_from_models_api(self) -> None:
        """Verifies that lists gemini models from models api behaves as expected.

        Typical use: Use this in automated tests when guarding the lists gemini models from models api behavior against regressions.

        Example: test_lists_gemini_models_from_models_api() -> passes without assertion failures when the behavior remains correct.
        """
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
                            "name": "models/gemini-3.5-flash",
                            "displayName": "Gemini 3.5 Flash",
                            "supportedGenerationMethods": ["generateContent"],
                        },
                        {
                            "name": "models/gemini-4-pro-preview",
                            "displayName": "Gemini 4 Pro Preview",
                            "supportedGenerationMethods": ["generateContent"],
                        },
                        {
                            "name": "models/veo-3.1-preview",
                            "displayName": "Veo 3.1 Preview",
                            "supportedGenerationMethods": ["generateVideos"],
                        },
                    ]
                }
            )

            models = GeminiModelCatalog().list_models(config)

        self.assertEqual([model.id for model in models], ["gemini-3.5-flash", "gemini-4-pro-preview"])
        self.assertEqual([model.label for model in models], ["Gemini 3.5 Flash", "Gemini 4 Pro Preview"])
        request = urlopen.call_args.args[0]
        self.assertEqual(
            request.full_url,
            "https://generativelanguage.googleapis.com/v1beta/models?key=gem-key",
        )

    def test_official_provider_model_choices_fall_back_to_curated_ids(self) -> None:
        """Verifies that official provider model choices fall back to curated ids behaves as expected.

        Typical use: Use this in automated tests when guarding the official provider model choices fall back to curated ids behavior against regressions.

        Example: test_official_provider_model_choices_fall_back_to_curated_ids() -> passes without assertion failures when the behavior remains correct.
        """
        expected = {
            "openai": "openai::gpt-5.5",
            "anthropic": "anthropic::claude-fable-5",
            "gemini": "gemini::gemini-3.5-flash",
        }

        with patch("src.llm.models.urllib.request.urlopen", side_effect=OSError("offline")):
            for provider, value in expected.items():
                choices = model_choices_for_provider(ProviderConfig(name=provider))
                self.assertEqual(choices[0]["value"], value)
        self.assertEqual(model_display_name("openai", "gpt-5.5"), "GPT-5.5")
        self.assertEqual(model_display_name("deepseek", "deepseek-v4-flash"), "DeepSeek-V4-Flash")

    def test_openrouter_catalog_preserves_exact_versioned_ids_and_filters_non_agent_models(self) -> None:
        config = ProviderConfig(
            name="openrouter",
            api_key="or-key",
            base_url="https://openrouter.ai/api/v1",
        )
        with patch("src.llm.models.urllib.request.urlopen") as urlopen:
            urlopen.return_value = _FakeResponse({
                "data": [
                    {
                        "id": "deepseek/deepseek-v4-flash-0731",
                        "name": "DeepSeek: DeepSeek V4 Flash 0731",
                        "output_modalities": ["text"],
                        "supported_parameters": ["tools", "tool_choice"],
                    },
                    {
                        "id": "deepseek/deepseek-v4-flash",
                        "name": "DeepSeek: DeepSeek V4 Flash",
                        "output_modalities": ["text"],
                        "supported_parameters": ["tools"],
                    },
                    {
                        "id": "provider/image-model",
                        "name": "Image Model",
                        "output_modalities": ["image"],
                        "supported_parameters": ["tools"],
                    },
                    {
                        "id": "provider/chat-without-tools",
                        "name": "Chat without tools",
                        "output_modalities": ["text"],
                        "supported_parameters": ["temperature"],
                    },
                ],
            })

            models = OpenAICompatibleModelCatalog().list_models(config)

        self.assertEqual(
            [model.id for model in models],
            ["deepseek/deepseek-v4-flash", "deepseek/deepseek-v4-flash-0731"],
        )
        self.assertEqual(models[1].label, "DeepSeek: DeepSeek V4 Flash 0731")
        self.assertEqual(urlopen.call_args.args[0].full_url, "https://openrouter.ai/api/v1/models")


class DeepSeekTransportTests(unittest.TestCase):
    """Groups related deep seek transport tests cases.

    Collects assertions that exercise deep seek transport tests behavior without mixing unrelated fixtures.
    """
    def test_builds_official_chat_completions_request(self) -> None:
        """Verifies that builds official chat completions request behaves as expected.

        Typical use: Use this in automated tests when guarding the builds official chat completions request behavior against regressions.

        Example: test_builds_official_chat_completions_request() -> passes without assertion failures when the behavior remains correct.
        """
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
        """Verifies that chat url normalizes v1 base url behaves as expected.

        Typical use: Use this in automated tests when guarding the chat url normalizes v1 base url behavior against regressions.

        Example: test_chat_url_normalizes_v1_base_url() -> passes without assertion failures when the behavior remains correct.
        """
        self.assertEqual(
            _chat_completions_url("https://api.deepseek.com/v1"),
            "https://api.deepseek.com/chat/completions",
        )

    def test_reports_urllib_resolved_loopback_proxy_on_connection_refused(self) -> None:
        """Verifies that reports urllib resolvedloopback proxy on connection refused behaves as expected.

        Typical use: Use this in automated tests when guarding the reports urllib resolvedloopback proxy on connection refused behavior against regressions.

        Example: test_reports_urllib_resolved_loopback_proxy_on_connection_refused() -> passes without assertion failures when the behavior remains correct.
        """
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
        """Verifies that reports urllib resolvedloopback proxy on ssl eof behaves as expected.

        Typical use: Use this in automated tests when guarding the reports urllib resolvedloopback proxy on ssl eof behavior against regressions.

        Example: test_reports_urllib_resolved_loopback_proxy_on_ssl_eof() -> passes without assertion failures when the behavior remains correct.
        """
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
