from __future__ import annotations

import unittest
from unittest.mock import patch

import src.tools.online_play as online
from src.tools.result import ToolResult


class FakeYoutubeDL:
    responses: list[dict] = []

    def __init__(self, options: dict) -> None:
        self.options = options

    def __enter__(self) -> "FakeYoutubeDL":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def extract_info(self, target: str, download: bool = False) -> dict:
        if not self.responses:
            raise AssertionError("No fake yt-dlp response configured.")
        return self.responses.pop(0)


def _playback_success(**kwargs):
    return ToolResult.success(
        tool=kwargs["tool"],
        message=kwargs["success_message"],
        data=kwargs["metadata"],
    ).to_dict()


class OnlinePlayTests(unittest.TestCase):
    def tearDown(self) -> None:
        FakeYoutubeDL.responses = []

    def test_play_youtube_song_returns_normalized_music_metadata(self) -> None:
        FakeYoutubeDL.responses = [
            {
                "entries": [
                    {
                        "id": "abc123",
                        "webpage_url": "https://www.youtube.com/watch?v=abc123",
                    }
                ]
            },
            {
                "id": "abc123",
                "title": "Song Title",
                "artist": "Artist Name",
                "album": "Album Name",
                "duration": 185,
                "thumbnail": "https://i.ytimg.com/vi/abc123/maxresdefault.jpg",
                "webpage_url": "https://www.youtube.com/watch?v=abc123",
                "url": "https://stream.example/audio.webm",
            },
        ]

        with patch("src.tools.online_play.yt_dlp.YoutubeDL", FakeYoutubeDL), \
            patch("src.tools.online_play.check_player", return_value=True), \
            patch("src.tools.online_play.is_player_allowed", return_value=True), \
            patch("src.tools.online_play.start_local_playback", side_effect=_playback_success):
            result = online.play_youtube_song("Song Artist", player="mpv")

        self.assertEqual(result["status"], "success")
        data = result["data"]
        self.assertEqual(data["provider"], "youtube")
        self.assertEqual(data["name"], "Song Title")
        self.assertEqual(data["title"], "Song Title")
        self.assertEqual(data["artist"], "Artist Name")
        self.assertEqual(data["album"], "Album Name")
        self.assertEqual(data["duration_ms"], 185000)
        self.assertEqual(data["album_cover_url"], "https://i.ytimg.com/vi/abc123/maxresdefault.jpg")
        self.assertEqual(data["url"], "https://www.youtube.com/watch?v=abc123")
        self.assertEqual(data["stream_url"], "https://stream.example/audio.webm")
        self.assertTrue(data["is_playing"])

    def test_play_youtube_song_falls_back_to_uploader_and_best_audio_format(self) -> None:
        FakeYoutubeDL.responses = [
            {"entries": [{"id": "def456"}]},
            {
                "id": "def456",
                "title": "Fallback Song",
                "uploader": "Uploader Artist",
                "duration": 12.4,
                "thumbnails": [
                    {"url": "small.jpg", "width": 120, "height": 90},
                    {"url": "large.jpg", "width": 1280, "height": 720},
                ],
                "formats": [
                    {"url": "video.mp4", "acodec": "mp4a", "vcodec": "avc1", "tbr": 500},
                    {"url": "low.webm", "acodec": "opus", "vcodec": "none", "abr": 64},
                    {"url": "high.webm", "acodec": "opus", "vcodec": "none", "abr": 160},
                ],
            },
        ]

        with patch("src.tools.online_play.yt_dlp.YoutubeDL", FakeYoutubeDL), \
            patch("src.tools.online_play.check_player", return_value=True), \
            patch("src.tools.online_play.is_player_allowed", return_value=True), \
            patch("src.tools.online_play.start_local_playback", side_effect=_playback_success):
            result = online.play_youtube_song("Fallback Song", player="mpv")

        data = result["data"]
        self.assertEqual(data["url"], "https://www.youtube.com/watch?v=def456")
        self.assertEqual(data["artist"], "Uploader Artist")
        self.assertEqual(data["album_cover_url"], "large.jpg")
        self.assertEqual(data["stream_url"], "high.webm")
        self.assertEqual(data["duration_ms"], 12400)

    def test_play_youtube_song_returns_failure_when_no_audio_stream_is_available(self) -> None:
        FakeYoutubeDL.responses = [
            {"entries": [{"id": "ghi789"}]},
            {
                "id": "ghi789",
                "title": "No Audio",
                "formats": [
                    {"url": "video.mp4", "acodec": "mp4a", "vcodec": "avc1"},
                ],
            },
        ]

        with patch("src.tools.online_play.yt_dlp.YoutubeDL", FakeYoutubeDL), \
            patch("src.tools.online_play.check_player", return_value=True), \
            patch("src.tools.online_play.start_local_playback") as launch:
            result = online.play_youtube_song("No Audio", player="mpv")

        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["error_code"], "NO_PLAYABLE_AUDIO")
        launch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
