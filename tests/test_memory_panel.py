from __future__ import annotations

import unittest

from src.ws.runner import MemorySettingsSession


class FakeEntry:
    entry_id = "entry-1"
    target = "user"
    content = "Prefers jazz"
    source_path = "USER.md"
    line_no = 1
    source = "explicit"
    confidence = 1.0
    protected = True
    created_at = "2026-01-01T00:00:00+00:00"
    updated_at = created_at
    recall_count = 0
    last_recalled_at = None
    review = None


class FakeStore:
    _read_only = False

    def entries(self, target: str) -> list[FakeEntry]:
        return [FakeEntry()] if target == "user" else []

    def dump_entries(self) -> list[dict[str, object]]:
        return []

    def settings(self) -> dict[str, object]:
        return {"forget_retention_days": 7, "automatic_refinement": True}

    def revisions(self, entry_id: str) -> list[dict[str, object]]:
        return [{"before": "Prefers rock", "actor": "user", "changed_at": "2026-01-02T00:00:00+00:00"}]

    @staticmethod
    def _entry_to_dict(entry: FakeEntry) -> dict[str, object]:
        return {
            key: getattr(entry, key)
            for key in (
                "entry_id", "target", "content", "source_path", "line_no", "source",
                "confidence", "protected", "created_at", "updated_at", "recall_count",
                "last_recalled_at", "review",
            )
        }


class FakeUI:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []
        self._memory_settings: object | None = None

    async def _send(self, payload: dict[str, object]) -> None:
        self.events.append(payload)


class MemoryPanelTests(unittest.IsolatedAsyncioTestCase):
    async def test_root_panel_only_shows_memory_management_entrypoint(self) -> None:
        ui = FakeUI()
        session = MemorySettingsSession(ui, FakeStore())
        await session.start()

        self.assertEqual(ui.events[-1]["view"], "root")
        self.assertNotIn("enabled", ui.events[-1])

    async def test_sources_keep_user_memory_and_dump_as_fixed_entries(self) -> None:
        ui = FakeUI()
        session = MemorySettingsSession(ui, FakeStore())
        await session.show_sources()
        await session.show_entries("user")

        self.assertEqual(ui.events[0]["view"], "sources")
        self.assertEqual(ui.events[1]["target"], "user")
        self.assertEqual(ui.events[1]["entries"][0]["content"], "Prefers jazz")

    async def test_settings_are_served_by_backend_memory_store(self) -> None:
        ui = FakeUI()
        session = MemorySettingsSession(ui, FakeStore())
        await session.show_settings()

        self.assertEqual(ui.events[-1]["view"], "settings")
        self.assertEqual(ui.events[-1]["settings"]["forget_retention_days"], 7)

    async def test_revisions_are_presented_as_selectable_entries(self) -> None:
        ui = FakeUI()
        session = MemorySettingsSession(ui, FakeStore())

        await session.show_revisions("user", "entry-1")

        self.assertEqual(ui.events[-1]["view"], "revisions")
        self.assertEqual(ui.events[-1]["entries"][0]["content"], "Prefers rock")
        self.assertEqual(ui.events[-1]["settings"]["entry_id"], "entry-1")


if __name__ == "__main__":
    unittest.main()
