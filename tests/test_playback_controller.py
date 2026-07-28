"""Tests test playback controller.

Contains pytest coverage for the test playback controller behavior.
"""

from __future__ import annotations

import io
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from src.music.player_sinks import PlayerSinkPlayback
from src.tools import playback_controller as playback


class PlaybackControllerTests(unittest.TestCase):
    """Groups related playback controller tests cases.

    Collects assertions that exercise playback controller tests behavior without mixing unrelated fixtures.
    """
    def setUp(self) -> None:
        """Verifies that setUp behaves as expected.

        Typical use: Use this in automated tests when guarding the setUp behavior against regressions.

        Example: setUp() -> passes without assertion failures when the behavior remains correct.
        """
        self.controller = playback.LocalPlaybackController()

    def test_mpv_play_returns_current_session_state(self) -> None:
        """Verifies that mpv play returns current session state behaves as expected.

        Typical use: Use this in automated tests when guarding the mpv play returns current session state behavior against regressions.

        Example: test_mpv_play_returns_current_session_state() -> passes without assertion failures when the behavior remains correct.
        """
        adapter = Mock()
        adapter.start.return_value = playback.PlayerState(
            provider="youtube",
            source="youtube",
            player="mpv",
            session_id="session-1",
            name="Song",
            artist="Artist",
            album="Album",
            duration_ms=180000,
            progress_ms=0,
            timestamp=1234,
            is_playing=True,
        )

        with patch.object(playback, "MpvPlaybackAdapter", return_value=adapter):
            state = self.controller.play(
                source_url="https://stream.example/audio",
                source="youtube",
                metadata={"name": "Song", "artist": "Artist", "album": "Album", "duration_ms": 180000},
                player="mpv",
            )

        self.assertEqual(state.player, "mpv")
        self.assertEqual(state.session_id, "session-1")
        self.assertTrue(state.is_playing)
        self.assertEqual(self.controller.current_session_id, "session-1")

    def test_mpv_start_uses_network_buffering_options(self) -> None:
        """Verifies that mpv start uses network buffering options behaves as expected.

        Typical use: Use this in automated tests when guarding the mpv start uses network buffering options behavior against regressions.

        Example: test_mpv_start_uses_network_buffering_options() -> passes without assertion failures when the behavior remains correct.
        """
        adapter = playback.MpvPlaybackAdapter(
            source_url="https://stream.example/audio",
            source="youtube",
            metadata={"name": "Song"},
        )
        expected_state = playback.PlayerState(
            provider="youtube",
            source="youtube",
            player="mpv",
            session_id=adapter.session_id,
            name="Song",
            artist="-",
            album="-",
            duration_ms=0,
            progress_ms=0,
            timestamp=1,
            is_playing=True,
        )
        process = Mock()
        process.poll.return_value = None

        with patch.object(playback.shutil, "which", return_value="/usr/bin/mpv"), \
             patch.object(playback.subprocess, "Popen", return_value=process) as popen, \
             patch.object(playback.os.path, "exists", return_value=True), \
             patch.object(adapter, "status", return_value=expected_state):
            adapter.start()

        command = popen.call_args.args[0]
        self.assertIn("--cache=yes", command)
        self.assertIn("--demuxer-readahead-secs=30", command)
        self.assertIn("--demuxer-max-bytes=256MiB", command)

    def test_mpv_session_persists_sanitized_process_diagnostics(self) -> None:
        source_url = "https://user:secret@example.test/audio.webm?token=private"
        adapter = playback.MpvPlaybackAdapter(
            source_url=source_url,
            source="youtube",
            metadata={"name": "Song"},
        )
        expected_state = playback.PlayerState(
            provider="youtube",
            source="youtube",
            player="mpv",
            session_id=adapter.session_id,
            name="Song",
            artist="-",
            album="-",
            duration_ms=0,
            progress_ms=0,
            timestamp=1,
            is_playing=True,
        )
        process = Mock()
        process.poll.return_value = None
        process.stderr = io.BytesIO(
            f"A: 00:00:01 / 00:03:00 (1%)\nfailed to open {source_url}\n".encode()
        )

        home = tempfile.TemporaryDirectory()
        self.addCleanup(home.cleanup)
        with patch.dict(os.environ, {"SONEX_HOME": home.name}), \
                patch.object(playback.shutil, "which", return_value="/usr/bin/mpv"), \
                patch.object(playback.subprocess, "Popen", return_value=process), \
                patch.object(playback.os.path, "exists", return_value=True), \
                patch.object(adapter, "status", return_value=expected_state):
            adapter.start()
            deadline = time.monotonic() + 1
            log_paths: list[Path] = []
            while time.monotonic() < deadline:
                log_paths = list((Path(home.name) / "diagnostics" / "mpv").glob("*/mpv.log"))
                if log_paths and log_paths[0].read_text(encoding="utf-8"):
                    break
                time.sleep(0.01)

            self.assertEqual(len(log_paths), 1)
            content = log_paths[0].read_text(encoding="utf-8")
            self.assertIn("failed to open <media>", content)
            self.assertNotIn("A: 00:00:01", content)
            self.assertNotIn(source_url, content)
            self.assertNotIn("secret", content)

    def test_mpv_public_status_records_authoritative_health_sample(self) -> None:
        sample_times = iter([0.0, 1.0, 2.0, 3.0])
        adapter = playback.MpvPlaybackAdapter(
            source_url="song.webm",
            source="youtube",
            metadata={"name": "Song", "duration_ms": 180000},
            diagnostic_time_source=lambda: next(sample_times),
        )
        started_state = playback.PlayerState(
            provider="youtube",
            source="youtube",
            player="mpv",
            session_id=adapter.session_id,
            name="Song",
            artist="-",
            album="-",
            duration_ms=180000,
            progress_ms=0,
            timestamp=1,
            is_playing=True,
        )
        process = Mock()
        process.poll.return_value = None
        process.stderr = io.BytesIO()
        properties = {
            "time-pos": 0.0,
            "duration": 180.0,
            "pause": False,
            "paused-for-cache": False,
            "current-ao": "pulse",
        }
        quit_sent = {"value": False}
        request_id_types: list[type[object]] = []

        class FakeIpcSocket:
            def __init__(self) -> None:
                self.property_name = ""
                self.request_id = 0

            def __enter__(self) -> "FakeIpcSocket":
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            def settimeout(self, _timeout: float) -> None:
                return None

            def connect(self, _path: str) -> None:
                return None

            def sendall(self, payload: bytes) -> None:
                request = json.loads(payload)
                command = request["command"]
                self.property_name = command[-1] if command[0] == "get_property" else ""
                self.request_id = request["request_id"]
                request_id_types.append(type(self.request_id))
                if command[0] == "quit":
                    quit_sent["value"] = True

            def recv(self, _size: int) -> bytes:
                event = json.dumps({"event": "property-change", "name": "idle-active"}) + "\n"
                property_unavailable = bool(self.property_name and quit_sent["value"])
                response = json.dumps({
                    "error": "property unavailable" if property_unavailable else "success",
                    "data": (
                        properties[self.property_name]
                        if self.property_name and not property_unavailable
                        else None
                    ),
                    "request_id": self.request_id,
                }) + "\n"
                return (event + response).encode()

        home = tempfile.TemporaryDirectory()
        self.addCleanup(home.cleanup)
        with patch.dict(os.environ, {"SONEX_HOME": home.name}), \
                patch.object(playback.shutil, "which", return_value="/usr/bin/mpv"), \
                patch.object(playback.subprocess, "Popen", return_value=process), \
                patch.object(playback.os.path, "exists", return_value=True), \
                patch.object(adapter, "status", return_value=started_state):
            adapter.start()

        with patch.object(playback.socket, "socket", side_effect=lambda *_args, **_kwargs: FakeIpcSocket()):
            state = adapter.status()
            properties["time-pos"] = 0.4
            adapter.status()
            properties["time-pos"] = 0.8
            anomaly_state = adapter.status()
            stopped = adapter.stop()

        self.assertEqual(state.progress_ms, 0)
        self.assertEqual(anomaly_state.diagnostic_notice, "clock_drift")
        self.assertTrue(stopped.ended)
        self.assertIsNone(stopped.diagnostic_notice)
        events = [
            json.loads(line)
            for line in adapter.diagnostics.events_path.read_text(encoding="utf-8").splitlines()
        ]
        status = [event for event in events if event["event"] == "status"][-1]
        self.assertEqual(status["progress_ms"], 800)
        self.assertEqual(status["current_ao"], "pulse")
        self.assertTrue(status["ipc_ok"])
        self.assertTrue(request_id_types)
        self.assertTrue(all(request_id_type is int for request_id_type in request_id_types))
        self.assertFalse(any(event["event"] == "audio_output_changed" for event in events))
        self.assertEqual(events[-1]["event"], "session_closed")

    def test_mpv_startup_sample_does_not_report_transient_time_pos_as_ipc_failure(self) -> None:
        adapter = playback.MpvPlaybackAdapter(
            source_url="song.webm",
            source="youtube",
            metadata={"name": "Song", "duration_ms": 180000},
        )
        adapter.process = Mock()
        adapter.process.poll.return_value = None
        adapter.health_monitor = Mock()
        properties = {
            "duration": 180.0,
            "pause": False,
            "paused-for-cache": False,
            "current-ao": "pulse",
        }

        def read_property(name: str) -> object:
            if name == "time-pos":
                raise RuntimeError("property unavailable")
            return properties[name]

        with patch.object(adapter, "_property", side_effect=read_property):
            state = adapter.status(default_playing=True)

        self.assertEqual(state.progress_ms, 0)
        self.assertTrue(state.is_playing)
        adapter.health_monitor.observe.assert_called_once_with(
            progress_ms=0,
            is_playing=True,
            paused_for_cache=False,
            current_ao="pulse",
            ipc_ok=True,
        )

    def test_cvlc_start_uses_network_buffering_options(self) -> None:
        """Verifies that cvlc start uses network buffering options behaves as expected.

        Typical use: Use this in automated tests when guarding the cvlc start uses network buffering options behavior against regressions.

        Example: test_cvlc_start_uses_network_buffering_options() -> passes without assertion failures when the behavior remains correct.
        """
        adapter = playback.CvlcRcPlaybackAdapter(
            source_url="https://stream.example/audio",
            source="youtube",
            metadata={"name": "Song"},
        )
        expected_state = playback.PlayerState(
            provider="youtube",
            source="youtube",
            player="cvlc",
            session_id=adapter.session_id,
            name="Song",
            artist="-",
            album="-",
            duration_ms=0,
            progress_ms=0,
            timestamp=1,
            is_playing=True,
        )
        process = Mock()
        process.poll.return_value = None

        with patch.object(playback.shutil, "which", return_value="/usr/bin/cvlc"), \
             patch.object(playback.subprocess, "Popen", return_value=process) as popen, \
             patch.object(playback.os.path, "exists", return_value=True), \
             patch.object(adapter, "status", return_value=expected_state):
            adapter.start()

        command = popen.call_args.args[0]
        self.assertIn("--network-caching=5000", command)

    def test_auto_play_tries_mpv_only_when_mpv_fails(self) -> None:
        """Verifies that auto play tries mpv only when mpv fails behaves as expected.

        Typical use: Use this in automated tests when guarding the auto play tries mpv only when mpv fails behavior against regressions.

        Example: test_auto_play_tries_mpv_only_when_mpv_fails() -> passes without assertion failures when the behavior remains correct.
        """
        mpv_adapter = Mock()
        mpv_adapter.start.side_effect = RuntimeError("mpv missing")

        with (
            patch.object(playback, "MpvPlaybackAdapter", return_value=mpv_adapter),
            patch.object(playback, "CvlcRcPlaybackAdapter") as cvlc_adapter,
        ):
            with self.assertRaisesRegex(RuntimeError, r"mpv missing.*\/player.*choose VLC"):
                self.controller.play(source_url="song.mp3", source="youtube", metadata={"name": "Song"})

        mpv_adapter.stop.assert_called_once()
        cvlc_adapter.assert_not_called()
        self.assertIsNone(self.controller.current_session_id)

    def test_explicit_mpv_failure_does_not_fall_back_to_cvlc(self) -> None:
        """Verifies that explicit mpv failure does not fall back to cvlc behaves as expected.

        Typical use: Use this in automated tests when guarding the explicit mpv failure does not fall back to cvlc behavior against regressions.

        Example: test_explicit_mpv_failure_does_not_fall_back_to_cvlc() -> passes without assertion failures when the behavior remains correct.
        """
        mpv_adapter = Mock()
        mpv_adapter.start.side_effect = RuntimeError("mpv failed")

        with (
            patch.object(playback, "MpvPlaybackAdapter", return_value=mpv_adapter),
            patch.object(playback, "CvlcRcPlaybackAdapter") as cvlc_adapter,
        ):
            with self.assertRaisesRegex(RuntimeError, "mpv failed"):
                self.controller.play(source_url="song.mp3", source="youtube", metadata={"name": "Song"}, player="mpv")

        cvlc_adapter.assert_not_called()

    def test_explicit_cvlc_uses_cvlc_adapter(self) -> None:
        """Verifies that explicit cvlc uses cvlc adapter behaves as expected.

        Typical use: Use this in automated tests when guarding the explicit cvlc uses cvlc adapter behavior against regressions.

        Example: test_explicit_cvlc_uses_cvlc_adapter() -> passes without assertion failures when the behavior remains correct.
        """
        cvlc_adapter = Mock()
        cvlc_adapter.start.return_value = playback.PlayerState(
            provider="local",
            source="local",
            player="cvlc",
            session_id="cvlc-session",
            name="Song",
            artist="-",
            album="-",
            duration_ms=1000,
            progress_ms=0,
            timestamp=10,
            is_playing=True,
        )

        with (
            patch.object(playback, "MpvPlaybackAdapter") as mpv_adapter,
            patch.object(playback, "CvlcRcPlaybackAdapter", return_value=cvlc_adapter),
        ):
            state = self.controller.play(source_url="song.mp3", source="local", metadata={"name": "Song"}, player="cvlc")

        mpv_adapter.assert_not_called()
        self.assertEqual(state.player, "cvlc")

    def test_new_play_stops_previous_session(self) -> None:
        """Verifies that new play stops previous session behaves as expected.

        Typical use: Use this in automated tests when guarding the new play stops previous session behavior against regressions.

        Example: test_new_play_stops_previous_session() -> passes without assertion failures when the behavior remains correct.
        """
        first = Mock()
        first.start.return_value = playback.PlayerState(
            provider="youtube",
            source="youtube",
            player="mpv",
            session_id="first",
            name="First",
            artist="-",
            album="-",
            duration_ms=1000,
            progress_ms=0,
            timestamp=1,
            is_playing=True,
        )
        second = Mock()
        second.start.return_value = playback.PlayerState(
            provider="local",
            source="local",
            player="mpv",
            session_id="second",
            name="Second",
            artist="-",
            album="-",
            duration_ms=2000,
            progress_ms=0,
            timestamp=2,
            is_playing=True,
        )

        with patch.object(playback, "MpvPlaybackAdapter", side_effect=[first, second]):
            self.controller.play(source_url="one.mp3", source="youtube", metadata={"name": "First"}, player="mpv")
            self.controller.play(source_url="two.mp3", source="local", metadata={"name": "Second"}, player="mpv")

        first.stop.assert_called_once()
        self.assertEqual(self.controller.current_session_id, "second")

    def test_pause_resume_stop_and_status_delegate_to_adapter(self) -> None:
        """Verifies that pause resume stop and status delegate to adapter behaves as expected.

        Typical use: Use this in automated tests when guarding the pause resume stop and status delegate to adapter behavior against regressions.

        Example: test_pause_resume_stop_and_status_delegate_to_adapter() -> passes without assertion failures when the behavior remains correct.
        """
        adapter = Mock()
        paused = playback.PlayerState(
            provider="youtube",
            source="youtube",
            player="mpv",
            session_id="session-1",
            name="Song",
            artist="-",
            album="-",
            duration_ms=1000,
            progress_ms=250,
            timestamp=10,
            is_playing=False,
        )
        playing = playback.PlayerState(**{**paused.to_dict(), "is_playing": True, "timestamp": 11})
        stopped = playback.PlayerState(**{**paused.to_dict(), "ended": True, "timestamp": 12})
        adapter.start.return_value = playing
        adapter.pause.return_value = paused
        adapter.resume.return_value = playing
        adapter.status.return_value = playing
        volume = playback.PlayerState(**{**paused.to_dict(), "volume_percent": 55, "timestamp": 13})
        adapter.stop.return_value = stopped
        adapter.set_volume.return_value = volume

        with patch.object(playback, "MpvPlaybackAdapter", return_value=adapter):
            self.controller.play(source_url="song.mp3", source="youtube", metadata={"name": "Song"})
            self.assertFalse(self.controller.pause().is_playing)
            self.assertTrue(self.controller.resume().is_playing)
            self.assertTrue(self.controller.status().is_playing)
            self.assertEqual(self.controller.set_volume(55).volume_percent, 55)
            self.assertTrue(self.controller.stop().ended)

        adapter.pause.assert_called_once()
        adapter.resume.assert_called_once()
        adapter.status.assert_called_once()
        adapter.set_volume.assert_called_once_with(55)
        adapter.stop.assert_called_once()
        self.assertIsNone(self.controller.current_session_id)

    def test_status_releases_a_naturally_ended_session(self) -> None:
        adapter = Mock()
        playing = playback.PlayerState(
            provider="youtube",
            source="youtube",
            player="mpv",
            session_id="session-1",
            name="Song",
            artist="-",
            album="-",
            duration_ms=1000,
            progress_ms=0,
            timestamp=1,
            is_playing=True,
        )
        ended = playback.PlayerState(
            **{
                **playing.to_dict(),
                "progress_ms": 1000,
                "timestamp": 2,
                "is_playing": False,
                "ended": True,
            }
        )
        adapter.start.return_value = playing
        adapter.status.return_value = ended

        with patch.object(playback, "MpvPlaybackAdapter", return_value=adapter):
            self.controller.play(
                source_url="song.webm",
                source="youtube",
                metadata={"name": "Song"},
            )
            state = self.controller.status()

        self.assertTrue(state.ended)
        self.assertIsNone(self.controller.current_session_id)
        with self.assertRaisesRegex(RuntimeError, "No active local playback session"):
            self.controller.status()

    def test_player_backend_strategy_can_be_changed_for_session(self) -> None:
        """Verifies that player backend strategy can be changed for session behaves as expected.

        Typical use: Use this in automated tests when guarding the player backend strategy can be changed for session behavior against regressions.

        Example: test_player_backend_strategy_can_be_changed_for_session() -> passes without assertion failures when the behavior remains correct.
        """
        self.assertEqual(self.controller.set_player_backend("cvlc"), "cvlc")
        self.assertEqual(self.controller.player_backend, "cvlc")
        with self.assertRaisesRegex(ValueError, "Unsupportedlocal playback backend"):
            self.controller.set_player_backend("vlc")

    def test_available_local_playback_backends_lists_only_installed_adapters(self) -> None:
        installed = {
            "mpv": "/usr/bin/mpv",
            "vlc": "/usr/bin/vlc",
        }

        with patch.object(playback.shutil, "which", side_effect=installed.get):
            available = playback.available_local_playback_backends()

        self.assertEqual(
            [(item["backend"], item["label"], item["executable"]) for item in available],
            [
                ("mpv", "mpv", "/usr/bin/mpv"),
                ("cvlc", "VLC", "/usr/bin/vlc"),
            ],
        )

    def test_explicit_tool_player_overrides_legacy_in_memory_default(self) -> None:
        mpv = Mock()
        mpv.start.return_value = playback.PlayerState(
            provider="local",
            source="local",
            player="mpv",
            session_id="mpv-session",
            name="Song",
            artist="-",
            album="-",
            duration_ms=1000,
            progress_ms=0,
            timestamp=10,
            is_playing=True,
        )
        self.controller.set_player_backend("cvlc")

        with (
            patch.object(playback, "MpvPlaybackAdapter", return_value=mpv),
            patch.object(playback, "CvlcRcPlaybackAdapter") as cvlc_adapter,
        ):
            state = self.controller.play(
                source_url="song.mp3",
                source="local",
                metadata={"name": "Song"},
                player="mpv",
            )

        cvlc_adapter.assert_not_called()
        self.assertEqual(state.player, "mpv")

    def test_setting_default_player_allows_direct_future_launches(self) -> None:
        original_backend = playback.controller.player_backend
        self.addCleanup(playback.controller.set_player_backend, original_backend)
        with patch("src.tools.player_permission.remember_player") as remember:
            result = playback.local_playback_player("cvlc")

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["data"]["backend"], "cvlc")
        self.assertEqual(playback.resolve_local_playback_backend("auto"), "auto")
        remember.assert_called_once_with("cvlc")

    def test_start_local_playback_uses_current_backend_when_player_is_omitted(self) -> None:
        """Verifies that start local playback uses current backend when player is omitted behaves as expected.

        Typical use: Use this in automated tests when guarding the start local playback uses current backend when player is omitted behavior against regressions.

        Example: test_start_local_playback_uses_current_backend_when_player_is_omitted() -> passes without assertion failures when the behavior remains correct.
        """
        cvlc_adapter = Mock()
        cvlc_adapter.start.return_value = playback.PlayerState(
            provider="local",
            source="local",
            player="cvlc",
            session_id="cvlc-session",
            name="Song",
            artist="-",
            album="-",
            duration_ms=1000,
            progress_ms=0,
            timestamp=10,
            is_playing=True,
        )
        self.controller.set_player_backend("cvlc")

        with (
            patch.object(playback, "controller", self.controller),
            patch.object(playback, "MpvPlaybackAdapter") as mpv_adapter,
            patch.object(playback, "CvlcRcPlaybackAdapter", return_value=cvlc_adapter),
        ):
            result = playback.start_local_playback(
                tool="play_local_song",
                source_url="song.mp3",
                source="local",
                metadata={"name": "Song"},
                success_message="Playing started.",
            )

        mpv_adapter.assert_not_called()
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["data"]["player"], "cvlc")

    def test_start_local_playback_routes_through_persisted_player_sink(self) -> None:
        routed = PlayerSinkPlayback(
            sink_id="mpris:clementine",
            state={
                "name": "Song",
                "artist": "Artist",
                "album": "Album",
                "is_playing": True,
                "player": "Clementine",
            },
        )

        with patch(
            "src.music.player_sink_runtime.play_through_persisted_sink",
            return_value=routed,
        ) as dispatch, patch.object(self.controller, "play") as managed_play, patch.object(
            playback,
            "controller",
            self.controller,
        ):
            result = playback.start_local_playback(
                tool="play_local_song",
                source_url="/music/song.flac",
                source="local",
                metadata={"name": "Song", "artist": "Artist"},
                success_message="Playing started.",
            )

        dispatch.assert_called_once_with(
            source_url="/music/song.flac",
            track={"name": "Song", "artist": "Artist"},
        )
        managed_play.assert_not_called()
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["data"]["sink_id"], "mpris:clementine")
        self.assertEqual(result["data"]["player"], "Clementine")

    def test_default_player_failure_carries_replay_context(self) -> None:
        with patch(
            "src.music.player_sink_runtime.play_through_persisted_sink",
            side_effect=RuntimeError("sink unavailable"),
        ):
            result = playback.start_local_playback(
                tool="play_local_song",
                source_url="/music/song.flac",
                source="local",
                metadata={"name": "Song"},
                success_message="Playing started.",
            )

        self.assertEqual(result["error_code"], "DEFAULT_PLAYER_FAILED")
        self.assertEqual(
            result["data"]["player_recovery"],
            {
                "source_url": "/music/song.flac",
                "source": "local",
                "metadata": {"name": "Song"},
                "success_message": "Playing started.",
            },
        )

    def test_explicit_player_is_a_one_time_override_of_persisted_default(self) -> None:
        adapter = Mock()
        adapter.start.return_value = playback.PlayerState(
            provider="local",
            source="local",
            player="mpv",
            session_id="mpv-session",
            name="Song",
            artist="-",
            album="-",
            duration_ms=0,
            progress_ms=0,
            timestamp=10,
            is_playing=True,
        )
        with patch(
            "src.music.player_sink_runtime.play_through_persisted_sink",
        ) as dispatch, patch.object(
            playback,
            "MpvPlaybackAdapter",
            return_value=adapter,
        ), patch.object(
            playback,
            "controller",
            self.controller,
        ):
            result = playback.start_local_playback(
                tool="play_local_song",
                source_url="/music/song.flac",
                source="local",
                metadata={"name": "Song"},
                player="mpv",
                success_message="Playing started.",
            )

        dispatch.assert_not_called()
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["data"]["player"], "mpv")

    def test_playback_control_targets_persisted_external_sink(self) -> None:
        routed = PlayerSinkPlayback(
            sink_id="mpris:rhythmbox",
            state={"player": "Rhythmbox", "is_playing": False},
        )
        with patch(
            "src.music.player_sink_runtime.control_persisted_player_sink",
            return_value=routed,
        ) as control, patch.object(self.controller, "pause") as managed_pause, patch.object(
            playback,
            "controller",
            self.controller,
        ):
            result = playback.local_playback_pause()

        control.assert_called_once_with("pause")
        managed_pause.assert_not_called()
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["data"]["sink_id"], "mpris:rhythmbox")

    def test_volume_tool_validates_range_and_returns_state(self) -> None:
        """Verifies that volume tool validates range and returns state behaves as expected.

        Typical use: Use this in automated tests when guarding the volume tool validates range and returns state behavior against regressions.

        Example: test_volume_tool_validates_range_and_returns_state() -> passes without assertion failures when the behavior remains correct.
        """
        adapter = Mock()
        adapter.start.return_value = playback.PlayerState(
            provider="youtube",
            source="youtube",
            player="mpv",
            session_id="session-1",
            name="Song",
            artist="-",
            album="-",
            duration_ms=1000,
            progress_ms=0,
            timestamp=1,
            is_playing=True,
        )
        adapter.set_volume.return_value = playback.PlayerState(
            **{**adapter.start.return_value.to_dict(), "volume_percent": 50, "timestamp": 2}
        )

        with patch.object(playback, "MpvPlaybackAdapter", return_value=adapter):
            self.controller.play(source_url="song.mp3", source="youtube", metadata={"name": "Song"})
            with patch.object(playback, "controller", self.controller):
                result = playback.local_playback_volume(50)
                invalid = playback.local_playback_volume(101)

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["data"]["volume_percent"], 50)
        self.assertEqual(invalid["status"], "fail")
        self.assertEqual(invalid["error_code"], "INVALID_VOLUME")


if __name__ == "__main__":
    unittest.main()
