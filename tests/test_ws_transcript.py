from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from src.ws.transcript import (
    _coerce_transcript_messages,
    _save_session_transcript,
    create_session_id,
)


class SessionTranscriptTests(unittest.TestCase):
    def test_create_session_id_uses_utc_timestamp_format(self) -> None:
        now = datetime(2026, 7, 25, 9, 15, 30, 123456, tzinfo=timezone.utc)

        self.assertEqual(create_session_id(now), "20260725091530123456Z")

    def test_save_uses_supplied_session_id_for_path_and_records(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch(
            "src.ws.transcript.sonex_home",
            return_value=Path(directory),
        ):
            path = _save_session_transcript(
                [{"role": "user", "content": "hello"}],
                reason="bye",
                session_id="20260725091530123456Z",
            )
            record = json.loads(path.read_text(encoding="utf-8").strip())

            self.assertEqual(path.parent.name, "20260725091530123456Z")
            self.assertEqual(record["session_id"], "20260725091530123456Z")

    def test_rich_segments_survive_coercion_and_persistence(self) -> None:
        segments = [
            {"text": "Bash", "style": "tool_name"},
            {"text": "  npm test", "style": "tool_value"},
        ]
        messages = _coerce_transcript_messages(
            [
                {
                    "role": "agent",
                    "content": "Bash  npm test",
                    "segments": segments,
                    "tone": "system",
                }
            ]
        )

        self.assertEqual(messages[0]["segments"], segments)
        self.assertEqual(messages[0]["tone"], "system")

        with tempfile.TemporaryDirectory() as directory, patch(
            "src.ws.transcript.sonex_home",
            return_value=Path(directory),
        ):
            path = _save_session_transcript(
                messages,
                reason="bye",
                session_id="session-rich",
            )
            record = json.loads(path.read_text(encoding="utf-8").strip())
            self.assertEqual(record["segments"], segments)
            self.assertEqual(record["tone"], "system")
