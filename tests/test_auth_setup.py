"""Tests test auth setup.

Contains pytest coverage for the test auth setup behavior.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from src.api.music_intent import MusicIntentDecision, MusicIntentRoute
from src.api.ws_runner import PlayRequestParse, WebSocketRunner
from src.auth.models import OAuthToken
from src.auth.store import load_auth_store, set_api_key, set_default, set_oauth_token
from src.thinking.config import ThinkingConfig


class FakeUI:
    """Groups related ui cases.

    Collects assertions that exercise ui behavior without mixing unrelated fixtures.
    """
    def __init__(self) -> None:
        """Verifies that init behaves as expected.

        Typical use: Use this in automated tests when guarding the init behavior against regressions.

        Example: __init__() -> passes without assertion failures when the behavior remains correct.
        """
        self.events: list[dict[str, object]] = []
        self.statuses: list[object] = []

    async def append_user_message(self, text: str) -> None:
        """Verifies that append user message behaves as expected.

        Typical use: Use this in automated tests when guarding the append user message behavior against regressions.

        Example: append_user_message() -> passes without assertion failures when the behavior remains correct.
        """
        self.events.append({"type": "chat", "role": "user", "text": text})

    async def append_system_message(self, text: str) -> None:
        """Collects local System notices appended to the chat transcript."""
        self.events.append({"type": "chat", "role": "agent", "tone": "system", "text": text})

    async def append_caution_message(self, text: str) -> None:
        self.events.append({"type": "chat", "role": "agent", "tone": "error", "text": text})

    async def append_activity(self, **kwargs: object) -> str:
        """Verifies that append activity behaves as expected.

        Typical use: Use this in automated tests when guarding the append activity behavior against regressions.

        Example: append_activity() -> passes without assertion failures when the behavior remains correct.
        """
        self.events.append({"type": "activity", **kwargs})
        return str(kwargs.get("activity_id") or "activity_test")

    async def send_auth_setup(self, **kwargs: object) -> None:
        """Verifies that send auth setup behaves as expected.

        Typical use: Use this in automated tests when guarding the send auth setup behavior against regressions.

        Example: send_auth_setup() -> passes without assertion failures when the behavior remains correct.
        """
        self.events.append({"type": "auth_setup", **kwargs})

    async def send_auth_state(self, state: object) -> None:
        """Verifies that send auth state behaves as expected.

        Typical use: Use this in automated tests when guarding the send auth state behavior against regressions.

        Example: send_auth_state() -> passes without assertion failures when the behavior remains correct.
        """
        self.events.append(state.to_event())

    def set_status(self, status: object) -> None:
        """Verifies that set status behaves as expected.

        Typical use: Use this in automated tests when guarding the set status behavior against regressions.

        Example: set_status() -> passes without assertion failures when the behavior remains correct.
        """
        self.statuses.append(status)


class AuthSetupTests(unittest.IsolatedAsyncioTestCase):
    """Groups related auth setup tests cases.

    Collects assertions that exercise auth setup tests behavior without mixing unrelated fixtures.
    """
    def setUp(self) -> None:
        """Verifies that setUp behaves as expected.

        Typical use: Use this in automated tests when guarding the setUp behavior against regressions.

        Example: setUp() -> passes without assertion failures when the behavior remains correct.
        """
        ThinkingConfig._state = None
        self.music_intent_patch = patch(
            "src.api.ws_runner.classify_music_intent_fast",
            return_value=MusicIntentDecision(MusicIntentRoute.GENERAL, confidence=1.0),
        )
        self.music_intent_patch.start()

    def tearDown(self) -> None:
        """Verifies that tearDown behaves as expected.

        Typical use: Use this in automated tests when guarding the tearDown behavior against regressions.

        Example: tearDown() -> passes without assertion failures when the behavior remains correct.
        """
        self.music_intent_patch.stop()
        ThinkingConfig._state = None

    async def test_missing_openai_login_starts_auth_setup_without_planner(self) -> None:
        """Verifies that missing openai login starts auth setup without planner behaves as expected.

        Typical use: Use this in automated tests when guarding the missing openai login starts auth setup without planner behavior against regressions.

        Example: test_missing_openai_login_starts_auth_setup_without_planner() -> passes without assertion failures when the behavior remains correct.
        """
        with self._isolated_auth_env():
            runner = WebSocketRunner()
            runner._run_agent_turn = AsyncMock()
            ui = FakeUI()

            await runner._handle_user_input(ui, "hello")

            self.assertFalse(runner._run_agent_turn.called)
            auth_events = [event for event in ui.events if event.get("type") == "auth_setup"]
            self.assertEqual(auth_events[-1]["provider"], "openai")
            self.assertEqual(auth_events[-1]["step"], "method")
            self.assertEqual(
                [method["value"] for method in auth_events[-1]["methods"][:2]],
                ["oauth", "api_key"],
            )
            self.assertNotIn("mask", auth_events[-1])

    async def test_api_key_login_saves_auth_and_continues_pending_input(self) -> None:
        """Verifies that api key login saves auth and continues pending input behaves as expected.

        Typical use: Use this in automated tests when guarding the api key login saves auth and continues pending input behavior against regressions.

        Example: test_api_key_login_saves_auth_and_continues_pending_input() -> passes without assertion failures when the behavior remains correct.
        """
        with self._isolated_auth_env():
            runner = WebSocketRunner()
            runner._run_agent_turn = AsyncMock()
            ui = FakeUI()

            await runner._handle_user_input(ui, "continue me")
            setup = getattr(ui, "_auth_setup")
            await setup.handle_input("api_key")
            api_key_event = [event for event in ui.events if event.get("type") == "auth_setup"][-1]
            self.assertEqual(api_key_event["title"], "OpenAI API key")
            self.assertEqual(api_key_event["prompt"], "API Key")
            self.assertEqual(api_key_event["placeholder"], "paste your key here")
            self.assertEqual(
                api_key_event["help_text"],
                "Haven't got an API Key? Get one at https://platform.openai.com/api-keys.",
            )
            await setup.handle_input("sk-test")
            await asyncio.sleep(0)

            provider = load_auth_store().providers["openai"]
            self.assertEqual(provider.api_key, "sk-test")
            runner._run_agent_turn.assert_called_once()
            call = runner._run_agent_turn.call_args
            self.assertEqual(call.args[:2], (ui, "continue me"))
            self.assertEqual(call.kwargs["command_intent"].command, "general")

    async def test_retired_ollama_default_is_ignored(self) -> None:
        """Verifies that ollama default provider does not require login behaves as expected.

        Typical use: Use this in automated tests when guarding the ollama default provider does not require login behavior against regressions.

        Example: test_ollama_default_provider_does_not_require_login() -> passes without assertion failures when the behavior remains correct.
        """
        with self._isolated_auth_env({"SONEX_DEFAULT_PROVIDER": "ollama"}):
            runner = WebSocketRunner()
            runner._run_agent_turn = AsyncMock()
            ui = FakeUI()

            await runner._handle_user_input(ui, "hello")
            await asyncio.sleep(0)

            runner._run_agent_turn.assert_not_called()
            auth_events = [event for event in ui.events if event.get("type") == "auth_setup"]
            self.assertEqual(auth_events[-1]["provider"], "openai")

    async def test_existing_auth_store_key_does_not_require_login(self) -> None:
        """Verifies that existing auth store key does not require login behaves as expected.

        Typical use: Use this in automated tests when guarding the existing auth store key does not require login behavior against regressions.

        Example: test_existing_auth_store_key_does_not_require_login() -> passes without assertion failures when the behavior remains correct.
        """
        with self._isolated_auth_env():
            set_api_key("openai", "sk-existing")
            runner = WebSocketRunner()
            runner._run_agent_turn = AsyncMock()
            ui = FakeUI()

            await runner._handle_user_input(ui, "hello")
            await asyncio.sleep(0)

            runner._run_agent_turn.assert_called_once()
            self.assertEqual(runner._run_agent_turn.call_args.args[:2], (ui, "hello"))
            self.assertFalse([event for event in ui.events if event.get("type") == "auth_setup"])

    async def test_plain_input_with_existing_auth_does_not_call_play_optimizer(self) -> None:
        """Verifies that plain input with existing auth does not call play optimizer behaves as expected.

        Typical use: Use this in automated tests when guarding the plain input with existing auth does not call play optimizer behavior against regressions.

        Example: test_plain_input_with_existing_auth_does_not_call_play_optimizer() -> passes without assertion failures when the behavior remains correct.
        """
        with self._isolated_auth_env():
            set_api_key("openai", "sk-existing")
            runner = WebSocketRunner()
            runner._run_agent_turn = AsyncMock()
            ui = FakeUI()

            with patch(
                "src.api.ws_runner._optimize_play_prompt",
                return_value=PlayRequestParse(False, None, "low", "hello"),
            ) as optimize:
                await runner._handle_user_input(ui, "hello")
                await asyncio.sleep(0)

            optimize.assert_not_called()
            runner._run_agent_turn.assert_called_once()
            self.assertEqual(runner._run_agent_turn.call_args.args[:2], (ui, "hello"))
            self.assertFalse([event for event in ui.events if event.get("type") == "auth_setup"])

    async def test_startup_missing_auth_starts_setup(self) -> None:
        """Verifies that startup missing auth starts setup behaves as expected.

        Typical use: Use this in automated tests when guarding the startup missing auth starts setup behavior against regressions.

        Example: test_startup_missing_auth_starts_setup() -> passes without assertion failures when the behavior remains correct.
        """
        with self._isolated_auth_env():
            runner = WebSocketRunner()
            runner._run_agent_turn = AsyncMock()
            ui = FakeUI()

            await runner._handle_startup_auth(ui)

            self.assertFalse(runner._run_agent_turn.called)
            auth_states = [event for event in ui.events if event.get("type") == "auth_state"]
            self.assertFalse(auth_states[-1]["ready"])
            self.assertEqual(auth_states[-1]["provider"], "openai")
            auth_events = [event for event in ui.events if event.get("type") == "auth_setup"]
            self.assertEqual(auth_events[-1]["step"], "provider")
            self.assertEqual(
                [choice["value"] for choice in auth_events[-1]["providers"]],
                [
                    "openai", "gemini", "anthropic", "deepseek", "openrouter", "zai",
                    "kimi_global", "kimi_cn", "minimax_global", "minimax_cn", "xai", "custom",
                ],
            )

    async def test_startup_existing_auth_store_key_skips_setup(self) -> None:
        """Verifies that startup existing auth store key skips setup behaves as expected.

        Typical use: Use this in automated tests when guarding the startup existing auth store key skips setup behavior against regressions.

        Example: test_startup_existing_auth_store_key_skips_setup() -> passes without assertion failures when the behavior remains correct.
        """
        with self._isolated_auth_env():
            set_api_key("openai", "sk-existing")
            runner = WebSocketRunner()
            ui = FakeUI()

            await runner._handle_startup_auth(ui)

            auth_states = [event for event in ui.events if event.get("type") == "auth_state"]
            self.assertTrue(auth_states[-1]["ready"])
            self.assertEqual(auth_states[-1]["auth_type"], "api_key")
            self.assertEqual(auth_states[-1]["credential_source"], "auth.json")
            self.assertFalse([event for event in ui.events if event.get("type") == "auth_setup"])

    async def test_startup_existing_auth_store_oauth_skips_setup(self) -> None:
        """Verifies that startup existing auth store oauth skips setup behaves as expected.

        Typical use: Use this in automated tests when guarding the startup existing auth store oauth skips setup behavior against regressions.

        Example: test_startup_existing_auth_store_oauth_skips_setup() -> passes without assertion failures when the behavior remains correct.
        """
        with self._isolated_auth_env({"SONEX_DEFAULT_PROVIDER": "gemini"}):
            set_oauth_token("gemini", OAuthToken(access_token="ya29-token"))
            runner = WebSocketRunner()
            ui = FakeUI()

            await runner._handle_startup_auth(ui)

            auth_states = [event for event in ui.events if event.get("type") == "auth_state"]
            self.assertTrue(auth_states[-1]["ready"])
            self.assertEqual(auth_states[-1]["auth_type"], "oauth")
            self.assertEqual(auth_states[-1]["credential_source"], "auth.json")
            self.assertFalse([event for event in ui.events if event.get("type") == "auth_setup"])

    async def test_startup_empty_auth_store_entry_starts_setup(self) -> None:
        """Verifies that startup empty auth store entry starts setup behaves as expected.

        Typical use: Use this in automated tests when guarding the startup empty auth store entry starts setup behavior against regressions.

        Example: test_startup_empty_auth_store_entry_starts_setup() -> passes without assertion failures when the behavior remains correct.
        """
        with self._isolated_auth_env():
            auth_path = Path(os.environ["SONEX_HOME"]) / "auth.json"
            auth_path.write_text(
                '{"version": 1, "providers": {"openai": {"auth_method": "api_key"}}}',
                encoding="utf-8",
            )
            runner = WebSocketRunner()
            ui = FakeUI()

            await runner._handle_startup_auth(ui)

            auth_states = [event for event in ui.events if event.get("type") == "auth_state"]
            self.assertFalse(auth_states[-1]["ready"])
            self.assertEqual(auth_states[-1]["credential_source"], "missing")
            self.assertTrue([event for event in ui.events if event.get("type") == "auth_setup"])

    async def test_startup_env_api_key_skips_setup(self) -> None:
        """Verifies that startup env api key skips setup behaves as expected.

        Typical use: Use this in automated tests when guarding the startup env api key skips setup behavior against regressions.

        Example: test_startup_env_api_key_skips_setup() -> passes without assertion failures when the behavior remains correct.
        """
        with self._isolated_auth_env({"SONEX_OPENAI_API_KEY": "sk-env"}):
            runner = WebSocketRunner()
            ui = FakeUI()

            await runner._handle_startup_auth(ui)

            auth_states = [event for event in ui.events if event.get("type") == "auth_state"]
            self.assertTrue(auth_states[-1]["ready"])
            self.assertEqual(auth_states[-1]["auth_type"], "api_key")
            self.assertEqual(auth_states[-1]["credential_source"], "env")
            self.assertFalse([event for event in ui.events if event.get("type") == "auth_setup"])

    async def test_startup_retired_ollama_falls_back_to_openai_login(self) -> None:
        """Verifies that startup ollama skips setup as local behaves as expected.

        Typical use: Use this in automated tests when guarding the startup ollama skips setup as local behavior against regressions.

        Example: test_startup_ollama_skips_setup_as_local() -> passes without assertion failures when the behavior remains correct.
        """
        with self._isolated_auth_env({"SONEX_DEFAULT_PROVIDER": "ollama"}):
            runner = WebSocketRunner()
            ui = FakeUI()

            await runner._handle_startup_auth(ui)

            auth_states = [event for event in ui.events if event.get("type") == "auth_state"]
            self.assertFalse(auth_states[-1]["ready"])
            self.assertEqual(auth_states[-1]["provider"], "openai")
            self.assertTrue([event for event in ui.events if event.get("type") == "auth_setup"])

    async def test_startup_api_key_login_saves_auth_without_agent_turn(self) -> None:
        """Verifies that startup api key login saves auth without agent turn behaves as expected.

        Typical use: Use this in automated tests when guarding the startup api key login saves auth without agent turn behavior against regressions.

        Example: test_startup_api_key_login_saves_auth_without_agent_turn() -> passes without assertion failures when the behavior remains correct.
        """
        with self._isolated_auth_env():
            runner = WebSocketRunner()
            runner._run_agent_turn = AsyncMock()
            ui = FakeUI()

            await runner._handle_startup_auth(ui)
            setup = getattr(ui, "_auth_setup")
            await setup.handle_input("openai")
            await setup.handle_input("api_key")
            await setup.handle_input("sk-test")
            await asyncio.sleep(0)

            store = load_auth_store()
            self.assertEqual(store.default_provider, "openai")
            provider = load_auth_store().providers["openai"]
            self.assertEqual(provider.api_key, "sk-test")
            self.assertFalse(runner._run_agent_turn.called)
            auth_states = [event for event in ui.events if event.get("type") == "auth_state"]
            self.assertTrue(auth_states[-1]["ready"])
            self.assertEqual(auth_states[-1]["credential_source"], "auth.json")

    async def test_startup_provider_selection_advances_to_method_choices(self) -> None:
        """Verifies that startup provider selection advances to method choices behaves as expected.

        Typical use: Use this in automated tests when guarding the startup provider selection advances to method choices behavior against regressions.

        Example: test_startup_provider_selection_advances_to_method_choices() -> passes without assertion failures when the behavior remains correct.
        """
        with self._isolated_auth_env():
            runner = WebSocketRunner()
            ui = FakeUI()

            await runner._handle_startup_auth(ui)
            setup = getattr(ui, "_auth_setup")
            await setup.handle_input("gemini")

            auth_events = [event for event in ui.events if event.get("type") == "auth_setup"]
            self.assertEqual(auth_events[-1]["provider"], "gemini")
            self.assertEqual(auth_events[-1]["step"], "method")
            self.assertEqual([choice["value"] for choice in auth_events[-1]["methods"]], ["oauth", "api_key"])
            self.assertIsNone(load_auth_store().default_provider)

    async def test_login_provider_status_counts_environment_api_keys(self) -> None:
        with self._isolated_auth_env({"SONEX_OPENAI_API_KEY": "sk-env"}):
            runner = WebSocketRunner()
            runner._run_agent_turn = AsyncMock()
            ui = FakeUI()

            await runner._handle_user_input(ui, "/login")

            event = [event for event in ui.events if event.get("type") == "auth_setup"][-1]
            providers = {choice["value"]: choice for choice in event["providers"]}
            self.assertEqual(providers["openai"]["connection_status"], "active")
            self.assertEqual(providers["openai"]["label"], "OpenAI — Active")
            self.assertEqual(providers["deepseek"]["connection_status"], "missing")
            self.assertEqual(providers["deepseek"]["label"], "DeepSeek — Not connected")

    async def test_login_distinguishes_active_saved_and_missing_providers(self) -> None:
        with self._isolated_auth_env({"SONEX_DEFAULT_PROVIDER": ""}):
            set_api_key("openai", "sk-openai")
            set_api_key("deepseek", "sk-deepseek")
            set_default("openai", "gpt-5.5")
            runner = WebSocketRunner()
            ui = FakeUI()

            await runner._handle_user_input(ui, "/login")

            event = [event for event in ui.events if event.get("type") == "auth_setup"][-1]
            providers = {choice["value"]: choice for choice in event["providers"]}
            self.assertEqual(providers["openai"]["connection_status"], "active")
            self.assertEqual(providers["deepseek"]["connection_status"], "saved")
            self.assertEqual(providers["openrouter"]["connection_status"], "missing")

    async def test_login_reactivates_saved_provider_without_asking_for_key(self) -> None:
        with self._isolated_auth_env({"SONEX_DEFAULT_PROVIDER": ""}):
            set_api_key("openai", "sk-openai")
            set_api_key("deepseek", "sk-deepseek")
            set_default("openai", "gpt-5.5")
            runner = WebSocketRunner()
            ui = FakeUI()

            await runner._handle_user_input(ui, "/login")
            setup = getattr(ui, "_auth_setup")
            await setup.handle_input("deepseek")

            store = load_auth_store()
            self.assertEqual(store.default_provider, "deepseek")
            self.assertEqual(store.providers["openai"].api_key, "sk-openai")
            self.assertEqual(store.providers["deepseek"].api_key, "sk-deepseek")
            self.assertFalse(any(
                event.get("type") == "auth_setup" and event.get("step") == "api_key"
                for event in ui.events
            ))

    async def test_zai_login_saves_selected_service_endpoint(self) -> None:
        with self._isolated_auth_env():
            runner = WebSocketRunner()
            ui = FakeUI()

            await runner._handle_user_input(ui, "/login")
            setup = getattr(ui, "_auth_setup")
            await setup.handle_input("zai")
            service_event = [event for event in ui.events if event.get("type") == "auth_setup"][-1]
            self.assertEqual([choice["value"] for choice in service_event["methods"]], ["api", "coding_plan"])
            await setup.handle_input("coding_plan")
            await setup.handle_input("zai-key")

            auth = load_auth_store().providers["zai"]
            self.assertEqual(auth.base_url, "https://api.z.ai/api/coding/paas/v4")
            self.assertEqual(load_auth_store().default_provider, "zai")

    async def test_custom_bearer_key_prompt_uses_shared_api_key_copy_without_signup_link(self) -> None:
        with self._isolated_auth_env():
            runner = WebSocketRunner()
            ui = FakeUI()

            await runner._handle_user_input(ui, "/login")
            setup = getattr(ui, "_auth_setup")
            await setup.handle_input("custom")
            await setup.handle_input("__add_custom__")
            await setup.handle_input("Local Test")
            await setup.handle_input("http://127.0.0.1:11434/v1")
            await setup.handle_input("api_key")

            event = [event for event in ui.events if event.get("type") == "auth_setup"][-1]
            self.assertEqual(event["step"], "custom_api_key")
            self.assertEqual(event["prompt"], "API Key")
            self.assertEqual(event["placeholder"], "paste your key here")
            self.assertNotIn("help_text", event)

    async def test_startup_anthropic_api_key_sets_default_provider(self) -> None:
        """Verifies that startup anthropic api key sets default provider behaves as expected.

        Typical use: Use this in automated tests when guarding the startup anthropic api key sets default provider behavior against regressions.

        Example: test_startup_anthropic_api_key_sets_default_provider() -> passes without assertion failures when the behavior remains correct.
        """
        with self._isolated_auth_env():
            runner = WebSocketRunner()
            runner._run_agent_turn = AsyncMock()
            ui = FakeUI()

            await runner._handle_startup_auth(ui)
            setup = getattr(ui, "_auth_setup")
            await setup.handle_input("anthropic")
            await setup.handle_input("sk-ant")
            await asyncio.sleep(0)

            store = load_auth_store()
            self.assertEqual(store.default_provider, "anthropic")
            self.assertEqual(store.providers["anthropic"].api_key, "sk-ant")
            self.assertFalse(runner._run_agent_turn.called)
            auth_states = [event for event in ui.events if event.get("type") == "auth_state"]
            self.assertEqual(auth_states[-1]["provider"], "anthropic")
            self.assertTrue(auth_states[-1]["ready"])

    async def test_retired_ollama_is_not_a_provider_choice(self) -> None:
        """Verifies that startup ollama selection completes as local behaves as expected.

        Typical use: Use this in automated tests when guarding the startup ollama selection completes as local behavior against regressions.

        Example: test_startup_ollama_selection_completes_as_local() -> passes without assertion failures when the behavior remains correct.
        """
        with self._isolated_auth_env():
            runner = WebSocketRunner()
            runner._run_agent_turn = AsyncMock()
            ui = FakeUI()

            await runner._handle_startup_auth(ui)
            setup = getattr(ui, "_auth_setup")
            await setup.handle_input("ollama")
            await asyncio.sleep(0)

            store = load_auth_store()
            self.assertIsNone(store.default_provider)
            self.assertFalse(runner._run_agent_turn.called)
            auth_events = [event for event in ui.events if event.get("type") == "auth_setup"]
            self.assertEqual(auth_events[-1]["step"], "provider")

    async def test_provider_defaults_apply_to_runtime_config(self) -> None:
        """Verifies that provider defaults apply to runtime config behaves as expected.

        Typical use: Use this in automated tests when guarding the provider defaults apply to runtime config behavior against regressions.

        Example: test_provider_defaults_apply_to_runtime_config() -> passes without assertion failures when the behavior remains correct.
        """
        with self._isolated_auth_env({"SONEX_DEFAULT_PROVIDER": "anthropic"}):
            ThinkingConfig.reload()

            self.assertEqual(ThinkingConfig.get_model(), "claude-fable-5")
            self.assertEqual(ThinkingConfig.get_provider_config("openai").model, "gpt-5.5")
            self.assertEqual(ThinkingConfig.get_provider_config("gemini").model, "gemini-3.5-flash")
            self.assertEqual(ThinkingConfig.get_provider_config("custom").custom_llm_provider, "openai")
            self.assertEqual(ThinkingConfig.get_provider_config("deepseek").model, "deepseek-v4-pro")
            self.assertEqual(ThinkingConfig.get_provider_config("openrouter").base_url, "https://openrouter.ai/api/v1")
            self.assertEqual(ThinkingConfig.get_provider_config("zai").base_url, "https://api.z.ai/api/paas/v4")
            self.assertEqual(ThinkingConfig.get_provider_config("kimi_global").base_url, "https://api.moonshot.ai/v1")
            self.assertEqual(ThinkingConfig.get_provider_config("kimi_cn").base_url, "https://api.moonshot.cn/v1")
            self.assertEqual(ThinkingConfig.get_provider_config("minimax_global").base_url, "https://api.minimax.io/v1")
            self.assertEqual(ThinkingConfig.get_provider_config("minimax_cn").base_url, "https://api.minimaxi.com/v1")
            self.assertEqual(ThinkingConfig.get_provider_config("xai").base_url, "https://api.x.ai/v1")

    async def test_model_command_opens_model_choices(self) -> None:
        """Verifies that model command opens model choices behaves as expected.

        Typical use: Use this in automated tests when guarding the model command opens model choices behavior against regressions.

        Example: test_model_command_opens_model_choices() -> passes without assertion failures when the behavior remains correct.
        """
        with self._isolated_auth_env({"SONEX_OPENAI_API_KEY": "sk-env"}):
            runner = WebSocketRunner()
            runner._run_agent_turn = AsyncMock()
            ui = FakeUI()

            with patch(
                "src.api.ws_runner._model_choices_for_provider",
                return_value=[
                    {"value": "openai::gpt-5.5", "label": "GPT-5.5", "provider": "OpenAI"},
                    {"value": "openai::gpt-5.4", "label": "gpt-5.4", "provider": "OpenAI"},
                    {"value": "openai::gpt-5.4-mini", "label": "gpt-5.4-mini", "provider": "OpenAI"},
                ],
            ):
                await runner._handle_user_input(ui, "/model")

            self.assertFalse(runner._run_agent_turn.called)
            auth_events = [event for event in ui.events if event.get("type") == "auth_setup"]
            self.assertEqual(auth_events[-1]["step"], "model")
            values = [choice["value"] for choice in auth_events[-1]["models"]]
            self.assertEqual(values[:3], ["openai::gpt-5.5", "openai::gpt-5.4", "openai::gpt-5.4-mini"])
            self.assertGreater(len(values), 1)

    async def test_model_selection_sets_default_provider_and_model(self) -> None:
        """Verifies that model selection sets default provider and model behaves as expected.

        Typical use: Use this in automated tests when guarding the model selection sets default provider and model behavior against regressions.

        Example: test_model_selection_sets_default_provider_and_model() -> passes without assertion failures when the behavior remains correct.
        """
        with self._isolated_auth_env({"SONEX_OPENAI_API_KEY": "sk-env"}):
            runner = WebSocketRunner()
            ui = FakeUI()

            with patch(
                "src.api.ws_runner._model_choices_for_provider",
                return_value=[
                    {"value": "openai::gpt-5.5", "label": "GPT-5.5", "provider": "OpenAI"},
                ],
            ):
                await runner._handle_user_input(ui, "/model")
                setup = getattr(ui, "_model_setup")
                await setup.handle_input("gpt-5.5")

            store = load_auth_store()
            self.assertEqual(store.default_provider, "openai")
            self.assertEqual(store.default_model, "gpt-5.5")
            self.assertEqual(store.providers["openai"].model, "gpt-5.5")
            auth_states = [event for event in ui.events if event.get("type") == "auth_state"]
            self.assertTrue(auth_states[-1]["ready"])
            self.assertEqual(auth_states[-1]["provider"], "openai")
            self.assertEqual(auth_states[-1]["model"], "gpt-5.5")
            confirmation_panels = [
                event
                for event in ui.events
                if event.get("type") == "auth_setup" and event.get("title") == "Model switched"
            ]
            self.assertEqual(confirmation_panels, [])
            dismissal_events = [
                event
                for event in ui.events
                if event.get("type") == "auth_setup"
                and event.get("step") == "model"
                and event.get("active") is False
            ]
            self.assertEqual(len(dismissal_events), 1)
            switch_messages = [
                event
                for event in ui.events
                if event.get("type") == "chat"
                and event.get("tone") == "system"
                and str(event.get("text", "")).startswith("✔  ")
            ]
            self.assertEqual(
                switch_messages,
                [
                    {
                        "type": "chat",
                        "role": "agent",
                        "tone": "system",
                        "text": "✔  Model has been switched to OpenAI: GPT-5.5.",
                    }
                ],
            )

    async def test_model_command_rejects_unconnected_provider_without_mutation(self) -> None:
        with self._isolated_auth_env():
            runner = WebSocketRunner()
            ui = FakeUI()

            await runner._handle_user_input(ui, "/model")

            self.assertIsNone(getattr(ui, "_model_setup"))
            self.assertFalse(any(event.get("type") == "auth_setup" for event in ui.events))
            self.assertEqual(
                [event for event in ui.events if event.get("tone") == "error"],
                [{
                    "type": "chat",
                    "role": "agent",
                    "tone": "error",
                    "text": '✖  OpenAI is not connected. Try "/login" to connect.',
                }],
            )
            self.assertIsNone(load_auth_store().default_model)

    async def test_model_selection_cancel_closes_setup(self) -> None:
        """Verifies that model selection cancel closes setup without changing model.

        Typical use: Use this in automated tests when guarding the model selection cancel behavior against regressions.

        Example: test_model_selection_cancel_closes_setup() -> passes without assertion failures when the behavior remains correct.
        """
        with self._isolated_auth_env({"SONEX_OPENAI_API_KEY": "sk-env"}):
            runner = WebSocketRunner()
            ui = FakeUI()

            with patch(
                "src.api.ws_runner._model_choices_for_provider",
                return_value=[
                    {"value": "openai::gpt-5.5", "label": "gpt-5.5", "provider": "OpenAI"},
                ],
            ):
                await runner._handle_user_input(ui, "/model")
                setup = getattr(ui, "_model_setup")
                auth_event_count = len([event for event in ui.events if event.get("type") == "auth_setup"])
                await setup.handle_input("__cancel__")

            self.assertIsNone(getattr(ui, "_model_setup"))
            auth_events = [event for event in ui.events if event.get("type") == "auth_setup"]
            self.assertEqual(len(auth_events), auth_event_count)

    def _isolated_auth_env(self, extra: dict[str, str] | None = None):
        """Verifies that isolated auth env behaves as expected.

        Typical use: Use this in automated tests when guarding the isolated auth env behavior against regressions.

        Example: _isolated_auth_env() -> passes without assertion failures when the behavior remains correct.
        """
        home = tempfile.TemporaryDirectory()
        config_path = Path(home.name) / "missing-thinking.json"
        env = {
            "SONEX_HOME": home.name,
            "SONEX_CONFIG_PATH": str(config_path),
            "SONEX_API_KEY": "",
            "SONEX_OPENAI_API_KEY": "",
            "SONEX_DEFAULT_PROVIDER": "openai",
        }
        env.update(extra or {})
        patcher = patch.dict(os.environ, env, clear=False)

        class EnvContext:
            """Groups related env context cases.

            Collects assertions that exercise env context behavior without mixing unrelated fixtures.
            """
            def __enter__(self_nonlocal) -> None:
                """Verifies that enter behaves as expected.

                Typical use: Use this in automated tests when guarding the enter behavior against regressions.

                Example: __enter__() -> passes without assertion failures when the behavior remains correct.
                """
                patcher.start()
                ThinkingConfig._state = None
                return None

            def __exit__(self_nonlocal, exc_type, exc, tb) -> None:
                """Verifies that exit behaves as expected.

                Typical use: Use this in automated tests when guarding the exit behavior against regressions.

                Example: __exit__() -> passes without assertion failures when the behavior remains correct.
                """
                ThinkingConfig._state = None
                patcher.stop()
                home.cleanup()

        return EnvContext()


if __name__ == "__main__":
    unittest.main()
