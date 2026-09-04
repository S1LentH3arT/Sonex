from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from src.tools.audio_diagnostics import audio_diagnostics_summary, record_audio_event


class AudioDiagnosticsTests(unittest.TestCase):
    def test_persisted_event_is_local_and_redacts_identity_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            record_audio_event(
                trace_id="trace-1",
                provider="youtube",
                phase="search",
                status="success",
                cache_root=root,
                cache_hit=False,
                query="secret song",
                stream_url="https://secret.example/stream",
            )

            summary = audio_diagnostics_summary(cache_root=root)
            self.assertEqual(summary, [{"phase": "search", "status": "success", "count": 1}])
            conn = sqlite3.connect(root / "cache.db")
            raw = conn.execute("SELECT metadata FROM audio_events").fetchone()[0]
            conn.close()
            self.assertNotIn("secret song", raw)
            self.assertNotIn("stream", raw)
