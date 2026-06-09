"""Tests test playback controller.

Contains pytest coverage for the test playback controller behavior.
"""

from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from src.tools import playback_controller as playback


class PlaybackControllerTests(unittest.TestCase):
    """Groups playback controller tests tests.

    Collects related assertions for playback controller tests behavior.
    """
    def setUp(self) -> None:
        """Validate set up.

        Exercises the set up behavior through the test suite.
        """
        self.controller = playback.LocalPlaybackController()

    def test_mpv_play_returns_current_session_state(self) -> None:
        """Validate test mpv play returns current session state.

        Exercises the test mpv play returns current session state behavior through the test suite.
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
        """Validate test mpv start uses network buffering options.

        Exercises the test mpv start uses network buffering options behavior through the test suite.
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

    def test_cvlc_start_uses_network_buffering_options(self) -> None:
        """Validate test cvlc start uses network buffering options.

        Exercises the test cvlc start uses network buffering options behavior through the test suite.
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

    def test_auto_play_falls_back_to_cvlc_when_mpv_fails(self) -> None:
        """Validate test auto play falls back to cvlc when mpv fails.

        Exercises the test auto play falls back to cvlc when mpv fails behavior through the test suite.
        """
        mpv_adapter = Mock()
        mpv_adapter.start.side_effect = RuntimeError("mpv missing")
        cvlc_adapter = Mock()
        cvlc_adapter.start.return_value = playback.PlayerState(
            provider="youtube",
            source="youtube",
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
            patch.object(playback, "MpvPlaybackAdapter", return_value=mpv_adapter),
            patch.object(playback, "CvlcRcPlaybackAdapter", return_value=cvlc_adapter),
        ):
            state = self.controller.play(source_url="song.mp3", source="youtube", metadata={"name": "Song"})

        mpv_adapter.stop.assert_called_once()
        self.assertEqual(state.player, "cvlc")
        self.assertEqual(self.controller.current_session_id, "cvlc-session")

    def test_explicit_mpv_failure_does_not_fall_back_to_cvlc(self) -> None:
        """Validate test explicit mpv failure does not fall back to cvlc.

        Exercises the test explicit mpv failure does not fall back to cvlc behavior through the test suite.
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
        """Validate test explicit cvlc uses cvlc adapter.

        Exercises the test explicit cvlc uses cvlc adapter behavior through the test suite.
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
        """Validate test new play stops previous session.

        Exercises the test new play stops previous session behavior through the test suite.
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
        """Validate test pause resume stop and status delegate to adapter.

        Exercises the test pause resume stop and status delegate to adapter behavior through the test suite.
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

    def test_player_backend_strategy_can_be_changed_for_session(self) -> None:
        """Validate test player backend strategy can be changed for session.

        Exercises the test player backend strategy can be changed for session behavior through the test suite.
        """
        self.assertEqual(self.controller.set_player_backend("cvlc"), "cvlc")
        self.assertEqual(self.controller.player_backend, "cvlc")
        with self.assertRaisesRegex(ValueError, "Unsupported local playback backend"):
            self.controller.set_player_backend("vlc")

    def test_start_local_playback_uses_current_backend_when_player_is_omitted(self) -> None:
        """Validate test start local playback uses current backend when player is omitted.

        Exercises the test start local playback uses current backend when player is omitted behavior through the test suite.
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

    def test_volume_tool_validates_range_and_returns_state(self) -> None:
        """Validate test volume tool validates range and returns state.

        Exercises the test volume tool validates range and returns state behavior through the test suite.
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
