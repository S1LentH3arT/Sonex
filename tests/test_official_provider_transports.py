"""Tests test official provider transports.

Contains pytest coverage for the test official provider transports behavior.
"""

from __future__ import annotations

import json
import unittest
from typing import Any
from unittest.mock import Mock, patch

from src.llm.client import ProviderClient
from src.llm.config import ProviderConfig, RuntimeConfig
from src.llm.transport.base import ChatRequest, ProviderRequest
from src.llm.transport.official import (
    AnthropicOfficialTransport,
    GeminiOfficialTransport,
    OpenAICompatibleTransport,
)


class _FakeResponse:
    """Groups related fake response cases.

    Collects assertions that exercise fake response behavior without mixing unrelated fixtures.
    """
    def __init__(self, payload: dict[str, Any]) -> None:
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


class OfficialProviderTransportTests(unittest.TestCase):
    """Groups related official provider transport tests cases.

    Collects assertions that exercise official provider transport tests behavior without mixing unrelated fixtures.
    """
    def test_openai_compatible_transport_builds_chat_completions_request(self) -> None:
        """Verifies that openai compatible transport builds chat completions request behaves as expected.

        Typical use: Use this in automated tests when guarding the openai compatible transport builds chat completions request behavior against regressions.

        Example: test_openai_compatible_transport_builds_chat_completions_request() -> passes without assertion failures when the behavior remains correct.
        """
        config = ProviderConfig(name="openai", api_key="sk-test", base_url="https://api.openai.com/v1")
        request = ProviderRequest(
            provider="openai",
            model="gpt-5.5",
            payload={"model": "gpt-5.5", "messages": [{"role": "user", "content": "hello"}]},
            native_payload={},
        )

        with patch("src.llm.transport.official.urllib.request.urlopen") as urlopen:
            urlopen.return_value = _FakeResponse({"choices": [{"message": {"content": "ok"}}]})
            response = OpenAICompatibleTransport(default_base_url="https://api.openai.com/v1").send(request, config)

        self.assertEqual(response["choices"][0]["message"]["content"], "ok")
        http_request = urlopen.call_args.args[0]
        payload = json.loads(http_request.data.decode("utf-8"))
        self.assertEqual(http_request.full_url, "https://api.openai.com/v1/chat/completions")
        self.assertEqual(http_request.headers["Authorization"], "Bearer sk-test")
        self.assertEqual(http_request.headers["Content-type"], "application/json")
        self.assertEqual(payload["model"], "gpt-5.5")
        self.assertEqual(payload["messages"], [{"role": "user", "content": "hello"}])

    def test_anthropic_transport_uses_native_messages_request(self) -> None:
        """Verifies that anthropic transport uses native messages request behaves as expected.

        Typical use: Use this in automated tests when guarding the anthropic transport uses native messages request behavior against regressions.

        Example: test_anthropic_transport_uses_native_messages_request() -> passes without assertion failures when the behavior remains correct.
        """
        config = ProviderConfig(name="anthropic", api_key="sk-ant", api_version="2023-06-01")
        request = ProviderRequest(
            provider="anthropic",
            model="claude-opus-4-7",
            payload={},
            native_payload={
                "model": "claude-opus-4-7",
                "messages": [{"role": "user", "content": [{"type": "text", "text": "hello"}]}],
                "max_tokens": 2048,
            },
        )

        with patch("src.llm.transport.official.urllib.request.urlopen") as urlopen:
            urlopen.return_value = _FakeResponse({"content": [{"type": "text", "text": "ok"}]})
            response = AnthropicOfficialTransport().send(request, config)

        self.assertEqual(response["content"][0]["text"], "ok")
        http_request = urlopen.call_args.args[0]
        payload = json.loads(http_request.data.decode("utf-8"))
        self.assertEqual(http_request.full_url, "https://api.anthropic.com/v1/messages")
        self.assertEqual(http_request.headers["X-api-key"], "sk-ant")
        self.assertEqual(http_request.headers["Anthropic-version"], "2023-06-01")
        self.assertEqual(payload["model"], "claude-opus-4-7")
        self.assertEqual(payload["max_tokens"], 2048)

    def test_gemini_transport_builds_generate_content_request_with_api_key(self) -> None:
        """Verifies that gemini transport builds generate content request with api key behaves as expected.

        Typical use: Use this in automated tests when guarding the gemini transport builds generate content request with api key behavior against regressions.

        Example: test_gemini_transport_builds_generate_content_request_with_api_key() -> passes without assertion failures when the behavior remains correct.
        """
        config = ProviderConfig(name="gemini", api_key="gemini-key", base_url="https://generativelanguage.googleapis.com/v1beta")
        request = ProviderRequest(
            provider="gemini",
            model="gemini-3.5-flash",
            payload={},
            native_payload={
                "model": "gemini-3.5-flash",
                "contents": [{"role": "user", "parts": [{"text": "hello"}]}],
            },
        )

        with patch("src.llm.transport.official.urllib.request.urlopen") as urlopen:
            urlopen.return_value = _FakeResponse({"candidates": [{"content": {"parts": [{"text": "ok"}]}}]})
            response = GeminiOfficialTransport().send(request, config)

        self.assertEqual(response["candidates"][0]["content"]["parts"][0]["text"], "ok")
        http_request = urlopen.call_args.args[0]
        payload = json.loads(http_request.data.decode("utf-8"))
        self.assertEqual(
            http_request.full_url,
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent?key=gemini-key",
        )
        self.assertNotIn("model", payload)
        self.assertEqual(payload["contents"], [{"role": "user", "parts": [{"text": "hello"}]}])


class ProviderClientRoutingTests(unittest.TestCase):
    """Groups related provider client routing tests cases.

    Collects assertions that exercise provider client routing tests behavior without mixing unrelated fixtures.
    """
    def test_known_cloud_provider_uses_official_transport_before_litellm_fallback(self) -> None:
        """Verifies that known cloud provider uses official transport before litellm fallback behaves as expected.

        Typical use: Use this in automated tests when guarding the known cloud provider uses official transport before litellm fallback behavior against regressions.

        Example: test_known_cloud_provider_uses_official_transport_before_litellm_fallback() -> passes without assertion failures when the behavior remains correct.
        """
        runtime = RuntimeConfig(
            default_provider="openai",
            default_model="gpt-5.5",
            providers={"openai": ProviderConfig(name="openai", model="gpt-5.5", api_key="sk-test")},
        )
        fallback = Mock()
        fallback.send.side_effect = AssertionError("LiteLLM fallback should not be used for openai")
        official = Mock()
        official.send.return_value = {"choices": [{"message": {"content": "ok"}}]}

        client = ProviderClient(runtime_config=runtime, transport=fallback, provider_transports={"openai": official})
        response = client.generate(ChatRequest(messages=[{"role": "user", "content": "hello"}]))

        self.assertEqual(response.output_text, "ok")
        official.send.assert_called_once()
        fallback.send.assert_not_called()

    def test_anthropic_client_builds_native_payload_for_official_transport(self) -> None:
        """Verifies that anthropic client builds native payload for official transport behaves as expected.

        Typical use: Use this in automated tests when guarding the anthropic client builds native payload for official transport behavior against regressions.

        Example: test_anthropic_client_builds_native_payload_for_official_transport() -> passes without assertion failures when the behavior remains correct.
        """
        runtime = RuntimeConfig(
            default_provider="anthropic",
            default_model="claude-opus-4-7",
            providers={"anthropic": ProviderConfig(name="anthropic", model="claude-opus-4-7", api_key="sk-ant")},
        )
        official = Mock()
        official.send.return_value = {"content": [{"type": "text", "text": "ok"}]}

        client = ProviderClient(runtime_config=runtime, provider_transports={"anthropic": official})
        response = client.generate(ChatRequest(messages=[{"role": "user", "content": "hello"}], max_tokens=128))

        self.assertEqual(response.output_text, "ok")
        provider_request = official.send.call_args.args[0]
        self.assertEqual(provider_request.native_payload["messages"][0]["content"][0]["text"], "hello")
        self.assertEqual(provider_request.native_payload["max_tokens"], 128)

    def test_unknown_provider_uses_litellm_fallback(self) -> None:
        """Verifies that unknown provider uses litellm fallback behaves as expected.

        Typical use: Use this in automated tests when guarding the unknown provider uses litellm fallback behavior against regressions.

        Example: test_unknown_provider_uses_litellm_fallback() -> passes without assertion failures when the behavior remains correct.
        """
        runtime = RuntimeConfig(
            default_provider="custom",
            default_model="custom-model",
            providers={"custom": ProviderConfig(name="custom", model="custom-model", api_key="sk-test")},
        )
        fallback = Mock()
        fallback.send.return_value = {"choices": [{"message": {"content": "ok"}}]}

        client = ProviderClient(runtime_config=runtime, transport=fallback)
        response = client.generate(ChatRequest(messages=[{"role": "user", "content": "hello"}]))

        self.assertEqual(response.output_text, "ok")
        fallback.send.assert_called_once()


if __name__ == "__main__":
    unittest.main()
