from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from src.api.ws_runner import PlayRequestParse, WebSocketRunner
from src.auth.models import OAuthToken
from src.auth.store import load_auth_store, set_api_key, set_oauth_token
from src.thinking.config import ThinkingConfig


class FakeUI:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []
        self.statuses: list[object] = []

    async def append_user_message(self, text: str) -> None:
        self.events.append({"type": "chat", "role": "user", "text": text})

    async def append_activity(self, **kwargs: object) -> str:
        self.events.append({"type": "activity", **kwargs})
        return str(kwargs.get("activity_id") or "activity_test")

    async def send_auth_setup(self, **kwargs: object) -> None:
        self.events.append({"type": "auth_setup", **kwargs})

    async def send_auth_state(self, state: object) -> None:
        self.events.append(state.to_event())

    def set_status(self, status: object) -> None:
        self.statuses.append(status)


class AuthSetupTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        ThinkingConfig._state = None

    def tearDown(self) -> None:
        ThinkingConfig._state = None

    async def test_missing_openai_login_starts_auth_setup_without_planner(self) -> None:
        with self._isolated_auth_env():
            runner = WebSocketRunner()
            runner._run_agent_turn = AsyncMock()
            ui = FakeUI()

            await runner._handle_user_input(ui, "hello")

            self.assertFalse(runner._run_agent_turn.called)
            auth_events = [event for event in ui.events if event.get("type") == "auth_setup"]
            self.assertEqual(auth_events[-1]["provider"], "openai")
            self.assertEqual(auth_events[-1]["step"], "api_key")
            self.assertTrue(auth_events[-1]["mask"])

    async def test_api_key_login_saves_auth_and_continues_pending_input(self) -> None:
        with self._isolated_auth_env():
            runner = WebSocketRunner()
            runner._run_agent_turn = AsyncMock()
            ui = FakeUI()

            await runner._handle_user_input(ui, "continue me")
            setup = getattr(ui, "_auth_setup")
            await setup.handle_input("sk-test")
            await asyncio.sleep(0)

            provider = load_auth_store().providers["openai"]
            self.assertEqual(provider.api_key, "sk-test")
            runner._run_agent_turn.assert_called_once_with(ui, "continue me")

    async def test_ollama_default_provider_does_not_require_login(self) -> None:
        with self._isolated_auth_env({"SONEX_DEFAULT_PROVIDER": "ollama"}):
            runner = WebSocketRunner()
            runner._run_agent_turn = AsyncMock()
            ui = FakeUI()

            await runner._handle_user_input(ui, "hello")
            await asyncio.sleep(0)

            runner._run_agent_turn.assert_called_once_with(ui, "hello")
            self.assertFalse([event for event in ui.events if event.get("type") == "auth_setup"])

    async def test_existing_auth_store_key_does_not_require_login(self) -> None:
        with self._isolated_auth_env():
            set_api_key("openai", "sk-existing")
            runner = WebSocketRunner()
            runner._run_agent_turn = AsyncMock()
            ui = FakeUI()

            await runner._handle_user_input(ui, "hello")
            await asyncio.sleep(0)

            runner._run_agent_turn.assert_called_once_with(ui, "hello")
            self.assertFalse([event for event in ui.events if event.get("type") == "auth_setup"])

    async def test_plain_input_with_existing_auth_does_not_call_play_optimizer(self) -> None:
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
            runner._run_agent_turn.assert_called_once_with(ui, "hello")
            self.assertFalse([event for event in ui.events if event.get("type") == "auth_setup"])

    async def test_startup_missing_auth_starts_setup(self) -> None:
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
                ["openai", "anthropic", "gemini", "deepseek", "ollama"],
            )

    async def test_startup_existing_auth_store_key_skips_setup(self) -> None:
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
        with self._isolated_auth_env({"SONEX_OPENAI_API_KEY": "sk-env"}):
            runner = WebSocketRunner()
            ui = FakeUI()

            await runner._handle_startup_auth(ui)

            auth_states = [event for event in ui.events if event.get("type") == "auth_state"]
            self.assertTrue(auth_states[-1]["ready"])
            self.assertEqual(auth_states[-1]["auth_type"], "api_key")
            self.assertEqual(auth_states[-1]["credential_source"], "env")
            self.assertFalse([event for event in ui.events if event.get("type") == "auth_setup"])

    async def test_startup_ollama_skips_setup_as_local(self) -> None:
        with self._isolated_auth_env({"SONEX_DEFAULT_PROVIDER": "ollama"}):
            runner = WebSocketRunner()
            ui = FakeUI()

            await runner._handle_startup_auth(ui)

            auth_states = [event for event in ui.events if event.get("type") == "auth_state"]
            self.assertTrue(auth_states[-1]["ready"])
            self.assertEqual(auth_states[-1]["auth_type"], "local")
            self.assertEqual(auth_states[-1]["credential_source"], "local")
            self.assertFalse([event for event in ui.events if event.get("type") == "auth_setup"])

    async def test_startup_api_key_login_saves_auth_without_agent_turn(self) -> None:
        with self._isolated_auth_env():
            runner = WebSocketRunner()
            runner._run_agent_turn = AsyncMock()
            ui = FakeUI()

            await runner._handle_startup_auth(ui)
            setup = getattr(ui, "_auth_setup")
            await setup.handle_input("openai")
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
            self.assertEqual(load_auth_store().default_provider, "gemini")

    async def test_startup_anthropic_api_key_sets_default_provider(self) -> None:
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

    async def test_startup_ollama_selection_completes_as_local(self) -> None:
        with self._isolated_auth_env():
            runner = WebSocketRunner()
            runner._run_agent_turn = AsyncMock()
            ui = FakeUI()

            await runner._handle_startup_auth(ui)
            setup = getattr(ui, "_auth_setup")
            await setup.handle_input("ollama")
            await asyncio.sleep(0)

            store = load_auth_store()
            self.assertEqual(store.default_provider, "ollama")
            self.assertEqual(store.default_model, "Gemma4-31b:cloud")
            self.assertFalse(runner._run_agent_turn.called)
            auth_states = [event for event in ui.events if event.get("type") == "auth_state"]
            self.assertTrue(auth_states[-1]["ready"])
            self.assertEqual(auth_states[-1]["provider"], "ollama")
            self.assertEqual(auth_states[-1]["model"], "Gemma4-31b:cloud")
            self.assertEqual(auth_states[-1]["auth_type"], "local")

    async def test_provider_defaults_apply_to_runtime_config(self) -> None:
        with self._isolated_auth_env({"SONEX_DEFAULT_PROVIDER": "anthropic"}):
            ThinkingConfig.reload()

            self.assertEqual(ThinkingConfig.get_model(), "claude-opus-4-1-20250805")
            self.assertEqual(ThinkingConfig.get_provider_config("openai").model, "gpt-5.2")
            self.assertEqual(ThinkingConfig.get_provider_config("gemini").model, "gemini-3-flash-preview")
            self.assertEqual(ThinkingConfig.get_provider_config("ollama").model, "Gemma4-31b:cloud")
            self.assertEqual(ThinkingConfig.get_provider_config("deepseek").model, "deepseek-v4-pro")

    async def test_model_command_opens_model_choices(self) -> None:
        with self._isolated_auth_env({"SONEX_OPENAI_API_KEY": "sk-env"}):
            runner = WebSocketRunner()
            runner._run_agent_turn = AsyncMock()
            ui = FakeUI()

            with patch(
                "src.api.ws_runner._model_choices_for_provider",
                return_value=[
                    {"value": "openai::gpt-5.2", "label": "GPT-5.2", "provider": "OpenAI"},
                    {"value": "openai::gpt-5.2-pro", "label": "GPT-5.2 Pro", "provider": "OpenAI"},
                    {"value": "openai::gpt-5-mini", "label": "GPT-5 Mini", "provider": "OpenAI"},
                ],
            ):
                await runner._handle_user_input(ui, "/model")

            self.assertFalse(runner._run_agent_turn.called)
            auth_events = [event for event in ui.events if event.get("type") == "auth_setup"]
            self.assertEqual(auth_events[-1]["step"], "model")
            values = [choice["value"] for choice in auth_events[-1]["models"]]
            self.assertEqual(values[:3], ["openai::gpt-5.2", "openai::gpt-5.2-pro", "openai::gpt-5-mini"])
            self.assertGreater(len(values), 1)

    async def test_model_selection_sets_default_provider_and_model(self) -> None:
        with self._isolated_auth_env({"SONEX_OPENAI_API_KEY": "sk-env"}):
            runner = WebSocketRunner()
            ui = FakeUI()

            with patch(
                "src.api.ws_runner._model_choices_for_provider",
                return_value=[
                    {"value": "openai::gpt-5.2", "label": "GPT-5.2", "provider": "OpenAI"},
                ],
            ):
                await runner._handle_user_input(ui, "/model")
                setup = getattr(ui, "_model_setup")
                await setup.handle_input("GPT-5.2")

            store = load_auth_store()
            self.assertEqual(store.default_provider, "openai")
            self.assertEqual(store.default_model, "gpt-5.2")
            self.assertEqual(store.providers["openai"].model, "gpt-5.2")
            auth_states = [event for event in ui.events if event.get("type") == "auth_state"]
            self.assertTrue(auth_states[-1]["ready"])
            self.assertEqual(auth_states[-1]["provider"], "openai")
            self.assertEqual(auth_states[-1]["model"], "gpt-5.2")

    def _isolated_auth_env(self, extra: dict[str, str] | None = None):
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
            def __enter__(self_nonlocal) -> None:
                patcher.start()
                ThinkingConfig._state = None
                return None

            def __exit__(self_nonlocal, exc_type, exc, tb) -> None:
                ThinkingConfig._state = None
                patcher.stop()
                home.cleanup()

        return EnvContext()


if __name__ == "__main__":
    unittest.main()
