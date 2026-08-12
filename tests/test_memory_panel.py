from __future__ import annotations

import unittest

from src.ws.runner import MemorySettingsSession


class FakeStore:
    def __init__(self) -> None:
        self.enabled = True
        self.reset_count = 0

    def long_term_enabled(self) -> bool:
        return self.enabled

    def set_long_term_enabled(self, enabled: bool) -> bool:
        self.enabled = enabled
        return enabled

    def reset_long_term(self) -> dict[str, object]:
        self.reset_count += 1
        return {"success": True}


class FakeUI:
    def __init__(self) -> None:
        self.confirms: list[dict[str, object]] = []
        self.system_messages: list[str] = []
        self.warning_messages: list[str] = []
        self._memory_settings: object | None = None

    async def ask_confirm(self, payload: dict[str, object]) -> None:
        self.confirms.append(payload)

    async def append_system_message(self, text: str) -> None:
        self.system_messages.append(text)

    async def append_warning_message(self, text: str) -> None:
        self.warning_messages.append(text)


class MemoryPanelTests(unittest.IsolatedAsyncioTestCase):
    async def test_panel_toggles_long_term_memory_without_touching_short_term_state(self) -> None:
        ui = FakeUI()
        store = FakeStore()
        session = MemorySettingsSession(ui, store)
        ui._memory_settings = session

        await session.start()
        await session.handle_choice("disable")

        self.assertFalse(store.enabled)
        self.assertEqual(ui.system_messages, ["Long-term memory disabled."])
        self.assertEqual(store.reset_count, 0)

    async def test_reset_requires_a_second_confirmation(self) -> None:
        ui = FakeUI()
        store = FakeStore()
        session = MemorySettingsSession(ui, store)
        ui._memory_settings = session

        await session.start()
        await session.handle_choice("reset")
        self.assertEqual(store.reset_count, 0)
        self.assertEqual(ui.confirms[-1]["message"], "Reset long-term memory?")

        await session.handle_choice("confirm_reset")
        self.assertEqual(store.reset_count, 1)
        self.assertEqual(ui.system_messages, ["Long-term memory reset."])


if __name__ == "__main__":
    unittest.main()
