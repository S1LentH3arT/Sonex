from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.tools.audio_doctor import audio_doctor_report


class AudioDoctorTests(unittest.TestCase):
    def test_report_reads_runtime_without_upgrading(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch("src.tools.audio_doctor.sonex_home", return_value=Path(tmp)), \
                 patch("src.tools.audio_doctor._installed_version", return_value="2026.1"), \
                 patch("src.tools.audio_doctor.provider_cooldown", return_value=None):
                report = audio_doctor_report(check_updates=False)

        self.assertEqual(report["yt_dlp_version"], "2026.1")
        self.assertTrue(report["worker_module"])
        self.assertFalse(report["update_available"])
