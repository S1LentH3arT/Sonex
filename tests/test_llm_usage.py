"""Tests for session-scoped LLM token usage reporting."""

from __future__ import annotations

import unittest
from unittest.mock import Mock

from src.llm.client import ProviderClient
from src.llm.config import ProviderConfig, RuntimeConfig
from src.llm.transport import ChatRequest
from src.llm.usage import reset_token_usage_observer, set_token_usage_observer


class LLMUsageTests(unittest.TestCase):
    def test_provider_client_reports_normalized_input_and_output_tokens(self) -> None:
        runtime = RuntimeConfig(
            default_provider="openai",
            default_model="gpt-test",
            providers={
                "openai": ProviderConfig(
                    name="openai",
                    model="gpt-test",
                    api_key="test-key",
                )
            },
        )
        transport = Mock()
        transport.send.return_value = {
            "choices": [{"message": {"content": "ok"}}],
            "usage": {
                "prompt_tokens": 120,
                "completion_tokens": 34,
                "total_tokens": 154,
            },
        }
        client = ProviderClient(
            runtime_config=runtime,
            provider_transports={"openai": transport},
        )
        observed: list[tuple[int, int]] = []
        token = set_token_usage_observer(
            lambda usage: observed.append(
                (usage.prompt_tokens, usage.completion_tokens)
            )
        )
        try:
            client.generate(ChatRequest(messages=[{"role": "user", "content": "hello"}]))
        finally:
            reset_token_usage_observer(token)

        self.assertEqual(observed, [(120, 34)])


if __name__ == "__main__":
    unittest.main()
