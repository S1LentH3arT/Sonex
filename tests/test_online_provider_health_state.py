from __future__ import annotations

import unittest

from src.tools.online_provider_health_state import calculate_cooldown, cooldown_schedule


class OnlineProviderHealthStateTests(unittest.TestCase):
    def test_schedule_rejects_unknown_failure_classes(self) -> None:
        self.assertEqual(cooldown_schedule("rate_limited"), (300, 1800, 7200))
        with self.assertRaises(ValueError):
            cooldown_schedule("network_error")

    def test_recent_same_class_escalates_and_retry_after_wins(self) -> None:
        state = calculate_cooldown(
            "youtube",
            "rate_limited",
            existing={"failure_class": "rate_limited", "level": 1, "last_failure_at": 900},
            retry_after=20_000,
            now=1_000,
        )
        self.assertEqual(state["level"], 2)
        self.assertEqual(state["cooldown_seconds"], 20_000)
        self.assertEqual(state["next_probe_at"], 21_000)

    def test_old_or_different_failure_class_resets_escalation(self) -> None:
        old = calculate_cooldown(
            "youtube",
            "bot_challenge",
            existing={"failure_class": "bot_challenge", "level": 1, "last_failure_at": 0},
            now=86_400,
        )
        different = calculate_cooldown(
            "youtube",
            "rate_limited",
            existing={"failure_class": "bot_challenge", "level": 1, "last_failure_at": 999},
            now=1_000,
        )
        self.assertEqual(old["level"], 0)
        self.assertEqual(different["level"], 0)


if __name__ == "__main__":
    unittest.main()
