from __future__ import annotations

import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

import src.tools.online_play as online
from src.tools.player_permission import build_player_confirm_result, complete_player_confirm
from src.tools.result import ToolResult
from src.tools.song_cache import upsert_cached_song


class FakeYoutubeDL:
    responses: list[dict] = []
    calls: list[dict] = []

    def __init__(self, options: dict) -> None:
        self.options = options

    def __enter__(self) -> "FakeYoutubeDL":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def extract_info(self, target: str, download: bool = False) -> dict:
        self.calls.append({"target": target, "download": download, "options": self.options})
        if not self.responses:
            raise AssertionError("No fake yt-dlp response configured.")
        response = self.responses.pop(0)
        if download:
            outtmpl = str(self.options.get("outtmpl") or "")
            ext = str(response.get("ext") or "webm")
            if outtmpl:
                path = Path(outtmpl.replace("%(ext)s", ext))
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"audio")
                response.setdefault("requested_downloads", [{"filepath": str(path)}])
        return response


def _playback_success(**kwargs):
    return ToolResult.success(
        tool=kwargs["tool"],
        message=kwargs["success_message"],
        data=kwargs["metadata"],
    ).to_dict()


class OnlinePlayTests(unittest.TestCase):
    def tearDown(self) -> None:
        FakeYoutubeDL.responses = []
        FakeYoutubeDL.calls = []

    def test_search_youtube_songs_returns_five_candidates_without_downloading(self) -> None:
        FakeYoutubeDL.responses = [
            {
                "entries": [
                    {
                        "id": f"id{idx}",
                        "title": f"Song {idx}",
                        "channel": f"Channel {idx}",
                        "duration": 60 + idx,
                        "webpage_url": f"https://www.youtube.com/watch?v=id{idx}",
                    }
                    for idx in range(6)
                ]
            }
        ]

        with patch("src.tools.online_play.yt_dlp.YoutubeDL", FakeYoutubeDL):
            candidates = online.search_youtube_songs("Song Artist", limit=5)

        self.assertEqual(len(candidates), 5)
        self.assertEqual(candidates[0]["cache_id"], "youtube_id0")
        self.assertEqual(candidates[0]["name"], "Song 0")
        self.assertEqual(candidates[0]["artist"], "Channel 0")
        self.assertEqual(candidates[0]["duration_ms"], 60000)
        self.assertFalse(candidates[0]["cached"])
        self.assertEqual(FakeYoutubeDL.calls[0]["target"], "ytsearch20:Song Artist")
        self.assertFalse(any(call["download"] for call in FakeYoutubeDL.calls))

    def test_search_youtube_songs_ranks_same_song_by_popularity_and_variant(self) -> None:
        FakeYoutubeDL.responses = [
            {
                "entries": [
                    {
                        "id": "y-official",
                        "title": "Love Song Official Music Video",
                        "artist": "Y Artist",
                        "channel": "Y Artist",
                        "duration": 210,
                        "view_count": 5_000_000,
                        "like_count": 50_000,
                        "webpage_url": "https://www.youtube.com/watch?v=y-official",
                    },
                    {
                        "id": "x-live",
                        "title": "Love Song Live Version",
                        "artist": "X Artist",
                        "channel": "X Artist",
                        "duration": 230,
                        "view_count": 20_000_000,
                        "like_count": 200_000,
                        "webpage_url": "https://www.youtube.com/watch?v=x-live",
                    },
                    {
                        "id": "cover",
                        "title": "Love Song guitar cover tutorial",
                        "channel": "Cover Channel",
                        "duration": 200,
                        "view_count": 100_000_000,
                        "webpage_url": "https://www.youtube.com/watch?v=cover",
                    },
                    {
                        "id": "x-official",
                        "title": "Love Song Official Music Video",
                        "artist": "X Artist",
                        "channel": "X Artist",
                        "duration": 215,
                        "view_count": 50_000_000,
                        "like_count": 500_000,
                        "webpage_url": "https://www.youtube.com/watch?v=x-official",
                    },
                ]
            }
        ]

        with patch("src.tools.online_play.yt_dlp.YoutubeDL", FakeYoutubeDL):
            candidates = online.search_youtube_songs("Love Song", limit=5)

        self.assertEqual([candidate["youtube_id"] for candidate in candidates], ["x-official", "x-live", "y-official"])
        self.assertEqual(candidates[0]["variant_type"], "official_original")
        self.assertEqual(candidates[1]["variant_type"], "live")
        self.assertEqual(candidates[2]["variant_type"], "official_original")
        self.assertEqual(candidates[0]["raw_view_count"], 50_000_000)
        self.assertGreater(candidates[0]["popularity_score"], candidates[1]["popularity_score"])
        self.assertIn("official", candidates[0]["rank_reason"])

    def test_search_youtube_songs_prioritizes_live_when_query_requests_live(self) -> None:
        FakeYoutubeDL.responses = [
            {
                "entries": [
                    {
                        "id": "official",
                        "title": "Love Song Official Audio",
                        "artist": "X Artist",
                        "channel": "X Artist",
                        "duration": 210,
                        "view_count": 80_000_000,
                        "webpage_url": "https://www.youtube.com/watch?v=official",
                    },
                    {
                        "id": "live",
                        "title": "Love Song Live at Wembley",
                        "artist": "X Artist",
                        "channel": "X Artist",
                        "duration": 250,
                        "view_count": 20_000_000,
                        "webpage_url": "https://www.youtube.com/watch?v=live",
                    },
                ]
            }
        ]

        with patch("src.tools.online_play.yt_dlp.YoutubeDL", FakeYoutubeDL):
            candidates = online.search_youtube_songs("Love Song live", limit=5)

        self.assertEqual(candidates[0]["youtube_id"], "live")
        self.assertEqual(candidates[0]["variant_type"], "live")

    def test_search_youtube_songs_handles_missing_popularity_fields(self) -> None:
        FakeYoutubeDL.responses = [
            {
                "entries": [
                    {
                        "id": "missing",
                        "title": "Love Song Official Audio",
                        "artist": "X Artist",
                        "channel": "X Artist",
                        "duration": 210,
                        "webpage_url": "https://www.youtube.com/watch?v=missing",
                    }
                ]
            }
        ]

        with patch("src.tools.online_play.yt_dlp.YoutubeDL", FakeYoutubeDL):
            candidates = online.search_youtube_songs("Love Song", limit=5)

        self.assertEqual(candidates[0]["popularity_score"], 0)
        self.assertEqual(candidates[0]["raw_view_count"], 0)
        self.assertEqual(candidates[0]["raw_like_count"], 0)

    def test_download_youtube_candidate_writes_cache_item_and_audio_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate = {
                "provider": "youtube",
                "id": "abc123",
                "youtube_id": "abc123",
                "cache_id": "youtube_abc123",
                "query": "Song Artist",
                "name": "Song Title",
                "artist": "Artist Name",
                "album": "-",
                "duration_ms": 185000,
                "url": "https://www.youtube.com/watch?v=abc123",
                "webpage_url": "https://www.youtube.com/watch?v=abc123",
            }
            FakeYoutubeDL.responses = [
                {
                    "id": "abc123",
                    "title": "Song Title",
                    "artist": "Artist Name",
                    "duration": 185,
                    "thumbnail": "cover.jpg",
                    "webpage_url": "https://www.youtube.com/watch?v=abc123",
                    "ext": "m4a",
                }
            ]

            with patch("src.tools.online_play.yt_dlp.YoutubeDL", FakeYoutubeDL):
                item = online.download_youtube_candidate(candidate, cache_root=root)

            audio_path = Path(item["audio_path"])
            self.assertTrue(audio_path.exists())
            self.assertEqual(audio_path.parent, root / "audio")
            self.assertEqual(item["cache_id"], "youtube_abc123")
            self.assertEqual(item["youtube_id"], "abc123")
            self.assertEqual(item["audio_ext"], "m4a")
            self.assertEqual(item["stream_url"], str(audio_path))

    def test_download_youtube_candidate_reuses_existing_audio_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "audio" / "youtube_abc123.webm"
            audio.parent.mkdir(parents=True)
            audio.write_bytes(b"cached")
            upsert_cached_song(
                {
                    "provider": "youtube",
                    "cache_id": "youtube_abc123",
                    "youtube_id": "abc123",
                    "name": "Cached Song",
                    "artist": "Cached Artist",
                    "album": "-",
                    "audio_path": str(audio),
                    "audio_ext": "webm",
                    "stream_url": str(audio),
                    "url": "https://www.youtube.com/watch?v=abc123",
                },
                cache_root=root,
            )

            item = online.download_youtube_candidate(
                {
                    "provider": "youtube",
                    "id": "abc123",
                    "youtube_id": "abc123",
                    "cache_id": "youtube_abc123",
                    "query": "Cached Song",
                    "name": "Cached Song",
                    "artist": "Cached Artist",
                    "url": "https://www.youtube.com/watch?v=abc123",
                    "webpage_url": "https://www.youtube.com/watch?v=abc123",
                },
                cache_root=root,
            )

            self.assertEqual(item["audio_path"], str(audio))
            self.assertEqual(FakeYoutubeDL.calls, [])

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

        with tempfile.TemporaryDirectory() as tmp:
            with patch("src.tools.online_play.yt_dlp.YoutubeDL", FakeYoutubeDL), \
                patch("src.tools.cover_sources.lookup_cover_art_url", return_value=None), \
                patch("src.tools.online_play.check_player", return_value=True), \
                patch("src.tools.online_play.is_player_allowed", return_value=True), \
                patch("src.tools.online_play.start_local_playback", side_effect=_playback_success):
                result = online.play_youtube_song("Song Artist", player="mpv", cache_root=Path(tmp))

            self.assertEqual(result["status"], "success")
            data = result["data"]
            self.assertEqual(data["provider"], "youtube")
            self.assertEqual(data["name"], "Song Title")
            self.assertEqual(data["title"], "Song Title")
            self.assertEqual(data["artist"], "Artist Name")
            self.assertEqual(data["album"], "Album Name")
            self.assertEqual(data["duration_ms"], 185000)
            self.assertIsNone(data["album_cover_url"])
            self.assertEqual(data["url"], "https://www.youtube.com/watch?v=abc123")
            self.assertTrue(Path(data["stream_url"]).exists())
            self.assertEqual(data["audio_path"], data["stream_url"])
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

        with tempfile.TemporaryDirectory() as tmp:
            with patch("src.tools.online_play.yt_dlp.YoutubeDL", FakeYoutubeDL), \
                patch("src.tools.cover_sources.lookup_cover_art_url", return_value=None), \
                patch("src.tools.online_play.check_player", return_value=True), \
                patch("src.tools.online_play.is_player_allowed", return_value=True), \
                patch("src.tools.online_play.start_local_playback", side_effect=_playback_success):
                result = online.play_youtube_song("Fallback Song", player="mpv", cache_root=Path(tmp))

            data = result["data"]
            self.assertEqual(data["url"], "https://www.youtube.com/watch?v=def456")
            self.assertEqual(data["artist"], "Uploader Artist")
            self.assertIsNone(data["album_cover_url"])
            self.assertTrue(Path(data["stream_url"]).exists())
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

        with tempfile.TemporaryDirectory() as tmp:
            with patch("src.tools.online_play.yt_dlp.YoutubeDL", FakeYoutubeDL), \
                patch("src.tools.online_play.check_player", return_value=True), \
                patch("src.tools.online_play.start_local_playback") as launch:
                result = online.play_youtube_song("No Audio", player="mpv", cache_root=Path(tmp))

        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["error_code"], "NO_PLAYABLE_AUDIO")
        launch.assert_not_called()

    def test_player_confirm_offers_mpv_and_vlc_backend_choices(self) -> None:
        result = build_player_confirm_result(
            tool="play_youtube_song",
            player="auto",
            cmd=["sonex-local-playback", "auto", "stream"],
            success_message="Playing started.",
            data={
                "playback_source_url": "stream",
                "playback_source": "youtube",
                "playback_metadata": {"name": "Song"},
            },
        )

        choices = result["data"]["choices"]
        self.assertEqual([choice["value"] for choice in choices], ["mpv", "cvlc", "deny"])
        self.assertIn("mpv", choices[0]["label"])
        self.assertIn("VLC", choices[1]["label"])
        self.assertIn("recommended", choices[0]["description"])

    def test_player_confirm_choice_selects_requested_backend(self) -> None:
        pending = build_player_confirm_result(
            tool="play_youtube_song",
            player="auto",
            cmd=["sonex-local-playback", "auto", "stream"],
            success_message="Playing started.",
            data={
                "playback_source_url": "stream",
                "playback_source": "youtube",
                "playback_metadata": {"name": "Song"},
            },
        )
        success = ToolResult.success(
            tool="play_youtube_song",
            message="Playing started.",
            data={"name": "Song", "player": "mpv"},
        ).to_dict()

        with patch("src.tools.playback_controller.start_local_playback", return_value=success) as start:
            result = complete_player_confirm(pending, "mpv")

        self.assertEqual(result["status"], "success")
        self.assertEqual(start.call_args.kwargs["player"], "mpv")


if __name__ == "__main__":
    unittest.main()
