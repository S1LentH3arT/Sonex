from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.tools.online_provider_health import (
    activate_provider_cooldown,
    clear_provider_cooldown,
    provider_cooldown,
)


class OnlineProviderHealthTests(unittest.TestCase):
    def test_rate_limit_cooldown_persists_and_escalates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = activate_provider_cooldown("youtube", "rate_limited", cache_root=root, now=100)
            second = activate_provider_cooldown("youtube", "rate_limited", cache_root=root, now=200)

            self.assertEqual(first["cooldown_seconds"], 300)
            self.assertEqual(second["cooldown_seconds"], 1800)
            persisted = provider_cooldown("youtube", cache_root=root, now=201)
            self.assertEqual(persisted["failure_class"], "rate_limited")
            self.assertGreater(persisted["remaining_seconds"], 0)

    def test_bot_challenge_uses_longer_schedule_and_expires_after_reset_window(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = activate_provider_cooldown("youtube", "bot_challenge", cache_root=root, now=100)
            self.assertEqual(state["cooldown_seconds"], 7200)
            self.assertIsNone(provider_cooldown("youtube", cache_root=root, now=100 + 86400))

    def test_clear_provider_cooldown_is_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            activate_provider_cooldown("youtube", "rate_limited", cache_root=root, now=100)
            clear_provider_cooldown("youtube", cache_root=root)
            self.assertIsNone(provider_cooldown("youtube", cache_root=root, now=101))
