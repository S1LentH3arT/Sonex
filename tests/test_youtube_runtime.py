from __future__ import annotations

import json
import os
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.tools import youtube_runtime as runtime


class YoutubeRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._home = tempfile.TemporaryDirectory()
        self._previous_home = os.environ.get("SONEX_HOME")
        os.environ["SONEX_HOME"] = self._home.name

    def tearDown(self) -> None:
        if self._previous_home is None:
            os.environ.pop("SONEX_HOME", None)
        else:
            os.environ["SONEX_HOME"] = self._previous_home
        self._home.cleanup()

    def _manifest(self) -> dict[str, object]:
        bundle = Path(self._home.name) / "bundle"
        python_path = bundle / "venv" / "bin" / "python"
        server_path = bundle / "server.js"
        python_path.parent.mkdir(parents=True, exist_ok=True)
        python_path.touch()
        server_path.touch()
        return {
            "format": runtime.RUNTIME_FORMAT,
            "runtime_id": "candidate-1",
            "bundle_path": str(bundle),
            "python_executable": str(python_path),
            "server_entry": str(server_path),
            "provider_version": "1.3.2",
            "yt_dlp_version": "2026.08.19",
        }

    def test_prepare_worker_forces_mweb_provider_and_strips_cookies(self) -> None:
        manifest = self._manifest()
        with patch.object(runtime, "active_manifest", return_value=manifest), patch.object(
            runtime, "ensure_provider_running", return_value="http://127.0.0.1:45231"
        ):
            options, provider_url = runtime.prepare_worker(
                {
                    "quiet": True,
                    "cookiefile": "/tmp/should-not-be-used.txt",
                    "cookiesfrombrowser": ("chrome",),
                    "extractor_args": {"youtube": {"player_client": ["web"]}},
                }
            )

        self.assertEqual(provider_url, "http://127.0.0.1:45231")
        self.assertTrue(options["ignoreconfig"])
        self.assertNotIn("cookiefile", options)
        self.assertNotIn("cookiesfrombrowser", options)
        self.assertEqual(options["extractor_args"]["youtube"]["player_client"], ["mweb"])
        self.assertEqual(
            options["extractor_args"]["youtubepot-bgutilhttp"]["base_url"],
            ["http://127.0.0.1:45231"],
        )

    def test_prepare_worker_fails_closed_without_active_manifest(self) -> None:
        with self.assertRaises(runtime.YoutubeRuntimeUnavailable) as caught:
            runtime.prepare_worker({"quiet": True})
        self.assertEqual(caught.exception.code, "YOUTUBE_PO_PROVIDER_UNAVAILABLE")

    def test_search_does_not_start_provider_or_inject_token_options(self) -> None:
        manifest = self._manifest()
        with patch.object(runtime, "active_manifest", return_value=manifest), patch.object(
            runtime, "ensure_provider_running"
        ) as ensure_provider:
            options, provider_url = runtime.prepare_worker({"quiet": True}, operation="search")
        ensure_provider.assert_not_called()
        self.assertEqual(provider_url, "")
        self.assertTrue(options["ignoreconfig"])
        self.assertNotIn("youtubepot-bgutilhttp", options.get("extractor_args", {}))

    def test_pending_runtime_is_activated_atomically_and_previous_is_kept(self) -> None:
        previous = self._manifest() | {"runtime_id": "previous"}
        candidate = self._manifest() | {"runtime_id": "candidate"}
        runtime._write_json(runtime._active_manifest_path(), previous)
        runtime._write_json(runtime._pending_manifest_path(), candidate)

        self.assertTrue(runtime.activate_pending_runtime())
        self.assertEqual(runtime.active_manifest()["runtime_id"], "candidate")  # type: ignore[index]
        self.assertEqual(runtime._read_json(runtime.runtime_root() / "previous.json")["runtime_id"], "previous")  # type: ignore[index]
        self.assertIsNone(runtime.pending_manifest())

    def test_request_gate_records_egress_without_waiting_in_tests(self) -> None:
        with patch.object(runtime, "REQUEST_MIN_INTERVAL_SECONDS", 0.0):
            with runtime.youtube_request_gate(options={"proxy": "http://user:secret@example.test:8080"}, timeout=1):
                pass
        state_files = list((Path(self._home.name) / "youtube-runtime" / "requests").glob("*.json"))
        self.assertEqual(len(state_files), 1)
        state = json.loads(state_files[0].read_text(encoding="utf-8"))
        self.assertEqual(state["egress"], "http://example.test:8080")

    def test_start_update_job_is_idempotent_when_worker_is_running(self) -> None:
        fake_process = MagicMock(pid=1234)
        fake_process.poll.return_value = None
        with patch.object(runtime.subprocess, "Popen", return_value=fake_process) as popen, patch.object(
            runtime, "_pid_alive", return_value=True
        ):
            first = runtime.start_update_job(reason="setup")
            second = runtime.start_update_job(reason="setup")
        self.assertEqual(first["pid"], 1234)
        self.assertEqual(second["pid"], 1234)
        popen.assert_called_once()

    def test_offline_package_bundle_detects_both_manual_wheels(self) -> None:
        offline = runtime.state_root() / "offline"
        offline.mkdir(parents=True)
        (offline / "yt_dlp-2026.08.19-py3-none-any.whl").write_bytes(b"yt-dlp")
        (offline / "bgutil_ytdlp_pot_provider-1.3.2-py3-none-any.whl").write_bytes(b"provider")

        bundle = runtime.offline_package_bundle()

        self.assertIsNotNone(bundle)
        assert bundle is not None
        self.assertEqual(bundle["yt-dlp"]["version"], "2026.08.19")
        self.assertEqual(bundle["bgutil-ytdlp-pot-provider"]["version"], "1.3.2")

    def test_yt_dlp_install_uses_manual_wheels_without_index(self) -> None:
        offline = runtime.state_root() / "offline"
        offline.mkdir(parents=True)
        yt_wheel = offline / "yt_dlp-2026.08.19-py3-none-any.whl"
        provider_wheel = offline / "bgutil_ytdlp_pot_provider-1.3.2-py3-none-any.whl"
        yt_wheel.write_bytes(b"yt-dlp")
        provider_wheel.write_bytes(b"provider")
        bundle = runtime.offline_package_bundle()
        assert bundle is not None

        components = Path(self._home.name) / "components"
        with patch.object(runtime, "_components_root", return_value=components), patch.object(
            runtime, "_component_manifest", return_value={}
        ), patch.object(runtime, "_run_checked") as run_checked:
            runtime._install_yt_dlp_component(
                Path(self._home.name) / "staging",
                "2026.08.19",
                "ignored",
                "1.3.2",
                "ignored",
                offline_bundle=bundle,
            )

        pip_command = run_checked.call_args_list[-1].args[0]
        self.assertIn("--no-index", pip_command)
        self.assertIn(str(yt_wheel), pip_command)
        self.assertIn(str(provider_wheel), pip_command)

    def test_safe_extract_rejects_links_that_escape_destination(self) -> None:
        archive = Path(self._home.name) / "unsafe.tar"
        with tarfile.open(archive, "w") as handle:
            link = tarfile.TarInfo("link")
            link.type = tarfile.SYMTYPE
            link.linkname = "../../outside"
            handle.addfile(link)

        with self.assertRaises(tarfile.FilterError):
            runtime._safe_extract_tar(archive, Path(self._home.name) / "extract")

    def test_update_uses_manual_bundle_without_online_version_lookup(self) -> None:
        offline = runtime.state_root() / "offline"
        offline.mkdir(parents=True)
        (offline / "yt_dlp-2026.08.19-py3-none-any.whl").write_bytes(b"yt-dlp")
        (offline / "bgutil_ytdlp_pot_provider-1.3.2-py3-none-any.whl").write_bytes(b"provider")
        runtime._update_state(status="running", component="yt-dlp", started_at=runtime.time.time())

        with patch.object(runtime, "latest_versions") as latest_versions, patch.object(
            runtime, "_pypi_wheel_hash"
        ) as wheel_hash, patch.object(runtime, "_install_yt_dlp_component") as install:
            runtime._perform_update()

        latest_versions.assert_not_called()
        wheel_hash.assert_not_called()
        self.assertEqual(install.call_args.kwargs["offline_bundle"]["yt-dlp"]["version"], "2026.08.19")


if __name__ == "__main__":
    unittest.main()
