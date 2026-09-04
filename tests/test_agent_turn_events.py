"""Regression tests for planner-to-runner event translation."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from src.agent.turn_events import runner_event_payload


class AgentTurnEventsTests(unittest.TestCase):
    def test_event_payload_preserves_tool_batch_and_controls(self) -> None:
        event = SimpleNamespace(type="tool_batch", calls=[{"name": "Query"}], args=None)
        self.assertEqual(runner_event_payload(event), {"calls": [{"name": "Query"}]})

        blocked = SimpleNamespace(
            type="tool_blocked",
            calls=[{"name": "Bash"}],
            args={"rule_ids": ["shell"]},
        )
        self.assertEqual(
            runner_event_payload(blocked),
            {"calls": [{"name": "Bash"}], "rule_ids": ["shell"]},
        )

    def test_unknown_event_has_empty_payload(self) -> None:
        self.assertEqual(runner_event_payload(SimpleNamespace(type="done")), {})


if __name__ == "__main__":
    unittest.main()
