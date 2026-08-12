from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.auth.browser_oauth import (
    BrowserOAuthConfig,
    BrowserOAuthPending,
    complete_browser_oauth,
)
from src.auth.models import OAuthToken
from src.auth.store import load_auth_store, set_api_key, set_oauth_token
from src.llm.custom import normalize_custom_base_url
from src.llm.transport.base import ProviderRequest, Usage
from src.llm.transport.codex_app_server import _structured_output_to_openai


class LlmOauthV1Tests(unittest.TestCase):
    def test_custom_endpoint_rejects_credentials_and_flags_remote_http(self) -> None:
        with self.assertRaisesRegex(ValueError, "username or password"):
            normalize_custom_base_url("https://user:secret@example.com/v1")
        endpoint = normalize_custom_base_url("http://example.com/v1/chat/completions")
        self.assertEqual(endpoint.base_url, "http://example.com/v1")
        self.assertTrue(endpoint.insecure_remote)
        self.assertFalse(normalize_custom_base_url("http://127.0.0.1:11434").insecure_remote)

    def test_api_key_and_oauth_are_stored_independently(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "auth.json"
            set_oauth_token("gemini", OAuthToken(access_token="access"), path=path)
            set_api_key("gemini", "key", path=path)
            provider = load_auth_store(path).providers["gemini"]
            self.assertEqual(provider.auth_method, "api_key")
            self.assertEqual(provider.api_key, "key")
            self.assertIsNotNone(provider.oauth)

    def test_refresh_reference_omits_access_token_from_auth_json(self) -> None:
        token = OAuthToken(
            access_token="short-lived",
            refresh_token="refresh",
            refresh_token_ref="keyring://refresh:gemini",
        )
        self.assertEqual(
            token.to_dict(),
            {"refresh_token_ref": "keyring://refresh:gemini"},
        )

    def test_manual_google_callback_validates_state_and_exchanges_code(self) -> None:
        config = BrowserOAuthConfig(
            provider="gemini",
            client_id="client",
            client_secret=None,
            auth_url="https://accounts.google.com/o/oauth2/v2/auth",
            token_url="https://oauth2.googleapis.com/token",
            scopes=["scope"],
            redirect_uri="http://127.0.0.1:9958/callback",
        )
        pending = BrowserOAuthPending(config, "expected", "verifier", "https://example.test/auth")
        with patch(
            "src.auth.browser_oauth._exchange_code",
            return_value={"access_token": "access"},
        ) as exchange, patch("src.auth.browser_oauth._save_token_info") as save:
            complete_browser_oauth(
                pending,
                "http://127.0.0.1:9958/callback?code=code&state=expected",
                project_id="project-id",
            )
        exchange.assert_called_once_with(config, code="code", verifier="verifier")
        save.assert_called_once_with(
            "gemini",
            {"access_token": "access"},
            ["scope"],
            project_id="project-id",
        )

    def test_codex_structured_output_rejects_unregistered_tools(self) -> None:
        request = ProviderRequest(
            provider="openai",
            model="gpt-test",
            payload={
                "tools": [
                    {"type": "function", "function": {"name": "Call", "parameters": {}}}
                ]
            },
            native_payload={},
        )
        response = _structured_output_to_openai(
            '{"output_text":"","tool_calls":[{"id":"1","name":"Call","arguments":{"x":1}}]}',
            request,
            Usage(total_tokens=3),
        )
        self.assertEqual(
            response["choices"][0]["message"]["tool_calls"][0]["function"]["name"],
            "Call",
        )
        with self.assertRaisesRegex(Exception, "unregistered"):
            _structured_output_to_openai(
                '{"output_text":"","tool_calls":[{"id":"1","name":"Bash","arguments":{}}]}',
                request,
                Usage(),
            )


if __name__ == "__main__":
    unittest.main()
