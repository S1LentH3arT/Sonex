"""Tests test online play.

Contains pytest coverage for the test online play behavior.
"""

from __future__ import annotations

import unittest
import tempfile
import urllib.parse
from pathlib import Path
from unittest.mock import patch

from yt_dlp.utils import DownloadError

import src.tools.online_play as online
from src.tools.player_permission import build_player_confirm_result, complete_player_confirm
from src.tools.result import ToolResult
from src.tools.song_cache import upsert_cached_song


class FakeYoutubeDL:
    """Groups related youtube d l cases.

    Collects assertions that exercise youtube d l behavior without mixing unrelated fixtures.
    """
    responses: list[dict] = []
    calls: list[dict] = []

    def __init__(self, options: dict) -> None:
        """Verifies that init behaves as expected.

        Typical use: Use this in automated tests when guarding the init behavior against regressions.

        Example: __init__() -> passes without assertion failures when the behavior remains correct.
        """
        self.options = options

    def __enter__(self) -> "FakeYoutubeDL":
        """Verifies that enter behaves as expected.

        Typical use: Use this in automated tests when guarding the enter behavior against regressions.

        Example: __enter__() -> passes without assertion failures when the behavior remains correct.
        """
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        """Verifies that exit behaves as expected.

        Typical use: Use this in automated tests when guarding the exit behavior against regressions.

        Example: __exit__() -> passes without assertion failures when the behavior remains correct.
        """
        return None

    def extract_info(self, target: str, download: bool = False) -> dict:
        """Verifies that extract info behaves as expected.

        Typical use: Use this in automated tests when guarding the extract info behavior against regressions.

        Example: extract_info() -> passes without assertion failures when the behavior remains correct.
        """
        self.calls.append({"target": target, "download": download, "options": self.options})
        if not self.responses:
            raise AssertionError("No fake yt-dlp response configured.")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
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
    """Verifies that playback success behaves as expected.

    Typical use: Use this in automated tests when guarding the playback success behavior against regressions.

    Example: _playback_success() -> passes without assertion failures when the behavior remains correct.
    """
    return ToolResult.success(
        tool=kwargs["tool"],
        message=kwargs["success_message"],
        data=kwargs["metadata"],
    ).to_dict()


class OnlinePlayTests(unittest.TestCase):
    """Groups related online play tests cases.

    Collects assertions that exercise online play tests behavior without mixing unrelated fixtures.
    """
    def tearDown(self) -> None:
        """Verifies that tearDown behaves as expected.

        Typical use: Use this in automated tests when guarding the tearDown behavior against regressions.

        Example: tearDown() -> passes without assertion failures when the behavior remains correct.
        """
        FakeYoutubeDL.responses = []
        FakeYoutubeDL.calls = []

    def test_search_spotify_track_candidates_returns_bounded_normalized_tracks(self) -> None:
        """Verifies that search spotify track candidates returns bounded normalized tracks behaves as expected.

        Typical use: Use this in automated tests when guarding the search spotify track candidates returns bounded normalized tracks behavior against regressions.

        Example: test_search_spotify_track_candidates_returns_bounded_normalized_tracks() -> passes without assertion failures when the behavior remains correct.
        """
        spotify_result = {
            "status": "success",
            "data": {
                "tracks": [
                    {
                        "id": f"spotify-track-{idx}",
                        "name": f"Song {idx}",
                        "artist": f"Artist {idx}",
                        "artists": [f"Artist {idx}"],
                        "album": f"Album {idx}",
                        "duration_ms": (180 + idx) * 1000,
                        "spotify_url": f"https://open.spotify.com/track/{idx}",
                        "uri": f"spotify:track:{idx}",
                    }
                    for idx in range(6)
                ]
            },
        }

        with patch("src.tools.spotify_play.spotify_search", return_value=spotify_result) as spotify_search:
            candidates = online.search_spotify_track_candidates("messy query", limit=5)

        spotify_search.assert_called_once_with(query="messy query", limit=5, types="track")
        self.assertEqual(len(candidates), 5)
        self.assertEqual(candidates[0]["metadata_source"], "spotify")
        self.assertEqual(candidates[0]["name"], "Song 0")
        self.assertEqual(candidates[0]["artist"], "Artist 0")
        self.assertEqual(candidates[0]["album"], "Album 0")
        self.assertEqual(candidates[0]["duration_ms"], 180000)
        self.assertEqual(candidates[0]["youtube_query"], "Artist 0 Song 0")
        self.assertEqual(candidates[0]["original_query"], "messy query")

    def test_search_spotify_track_candidates_returns_empty_on_failure(self) -> None:
        """Verifies that search spotify track candidates returns empty on failure behaves as expected.

        Typical use: Use this in automated tests when guarding the search spotify track candidates returns empty on failure behavior against regressions.

        Example: test_search_spotify_track_candidates_returns_empty_on_failure() -> passes without assertion failures when the behavior remains correct.
        """
        with patch("src.tools.spotify_play.spotify_search", side_effect=RuntimeError("no token")):
            self.assertEqual(online.search_spotify_track_candidates("query", limit=5), [])

    def test_normalize_jamendo_track_keeps_stream_download_cover_and_metadata(self) -> None:
        """Verifies that normalize jamendo track keeps stream download cover and metadata behaves as expected.

        Typical use: Use this in automated tests when guarding the normalize jamendo track keeps stream download cover and metadata behavior against regressions.

        Example: test_normalize_jamendo_track_keeps_stream_download_cover_and_metadata() -> passes without assertion failures when the behavior remains correct.
        """
        track = {
            "id": "jam-1",
            "name": "Canonical Song",
            "artist_name": "Canonical Artist",
            "album_name": "Canonical Album",
            "duration": "201",
            "audio": "https://audio.example/stream.mp3",
            "audiodownload": "https://audio.example/download.mp3",
            "album_image": "https://img.example/album.jpg",
            "shareurl": "https://www.jamendo.com/track/1",
            "tags": ["pop"],
        }

        candidate = online.normalize_jamendo_track(
            track,
            query="Canonical Artist Canonical Song",
            playback_metadata={"metadata_source": "spotify", "name": "Canonical Song", "artist": "Canonical Artist"},
        )

        self.assertIsNotNone(candidate)
        assert candidate is not None
        self.assertEqual(candidate["provider"], "jamendo")
        self.assertEqual(candidate["id"], "jam-1")
        self.assertEqual(candidate["cache_id"], "jamendo_jam-1")
        self.assertEqual(candidate["name"], "Canonical Song")
        self.assertEqual(candidate["artist"], "Canonical Artist")
        self.assertEqual(candidate["album"], "Canonical Album")
        self.assertEqual(candidate["duration_ms"], 201000)
        self.assertEqual(candidate["source_url"], "https://audio.example/stream.mp3")
        self.assertEqual(candidate["download_url"], "https://audio.example/download.mp3")
        self.assertEqual(candidate["cover_url"], "https://img.example/album.jpg")
        self.assertEqual(candidate["webpage_url"], "https://www.jamendo.com/track/1")
        self.assertEqual(candidate["playback_metadata"]["metadata_source"], "spotify")

    def test_normalize_jamendo_track_returns_none_without_playable_url(self) -> None:
        """Verifies that normalize jamendo track returns none without playable url behaves as expected.

        Typical use: Use this in automated tests when guarding the normalize jamendo track returns none without playable url behavior against regressions.

        Example: test_normalize_jamendo_track_returns_none_without_playable_url() -> passes without assertion failures when the behavior remains correct.
        """
        candidate = online.normalize_jamendo_track(
            {"id": "jam-1", "name": "Song", "artist_name": "Artist"},
            query="Artist Song",
        )

        self.assertIsNone(candidate)

    def test_itunes_metadata_does_not_replace_jamendo_audio_source_identity(self) -> None:
        """Verifies that itunes metadata does not replace jamendo audio source identity behaves as expected.

        Typical use: Use this in automated tests when guarding the itunes metadata does not replace jamendo audio source identity behavior against regressions.

        Example: test_itunes_metadata_does_not_replace_jamendo_audio_source_identity() -> passes without assertion failures when the behavior remains correct.
        """
        candidate = online.normalize_jamendo_track(
            {
                "id": "jam-1",
                "name": "Sorry",
                "artist_name": "Jamendo Artist",
                "audio": "https://audio.example/stream.mp3",
                "audiodownload": "https://audio.example/download.mp3",
                "shareurl": "https://www.jamendo.com/track/jam-1",
            },
            query="Fang Datong Sorry",
            playback_metadata={
                "metadata_source": "itunes",
                "provider": "itunes",
                "id": "itunes-1",
                "name": "Sorry",
                "artist": "Fang Datong",
                "url": "https://music.apple.com/song/itunes-1",
                "itunes_url": "https://music.apple.com/song/itunes-1",
            },
        )

        self.assertIsNotNone(candidate)
        assert candidate is not None
        self.assertEqual(candidate["provider"], "jamendo")
        self.assertEqual(candidate["id"], "jam-1")
        self.assertEqual(candidate["url"], "https://www.jamendo.com/track/jam-1")
        self.assertEqual(candidate["download_url"], "https://audio.example/download.mp3")
        self.assertEqual(candidate["playback_metadata"]["provider"], "itunes")
        self.assertEqual(candidate["playback_metadata"]["itunes_url"], "https://music.apple.com/song/itunes-1")

    def test_jamendo_wrong_artist_cannot_inherit_selected_metadata_identity(self) -> None:
        candidate = online.normalize_jamendo_track(
            {
                "id": "jam-wrong-artist",
                "name": "Sorry",
                "artist_name": "Jamendo Artist",
                "audio": "https://audio.example/wrong.mp3",
            },
            query="Fang Datong Sorry",
            playback_metadata={
                "metadata_source": "spotify",
                "name": "Sorry",
                "artist": "Fang Datong",
                "artists": ["Fang Datong"],
                "album": "The Dreamer",
            },
        )

        self.assertIsNotNone(candidate)
        assert candidate is not None
        self.assertEqual(candidate["target_identity"]["artist"], "Fang Datong")
        self.assertEqual(candidate["source_identity"]["artist"], "Jamendo Artist")
        self.assertFalse(candidate["identity_match"])

    def test_jamendo_selected_track_uses_exact_identity_query(self) -> None:
        captured_urls: list[str] = []

        def fake_json_get(url: str, **_: object) -> dict[str, object]:
            captured_urls.append(url)
            return {"results": []}

        with patch("src.tools.online_play._json_get", side_effect=fake_json_get):
            online.search_jamendo_audio_candidates(
                "Fang Datong Sorry",
                client_id="client-id",
                limit=5,
                playback_metadata={
                    "metadata_source": "spotify",
                    "name": "Sorry",
                    "artist": "Fang Datong",
                    "album": "The Dreamer",
                },
            )

        params = urllib.parse.parse_qs(urllib.parse.urlparse(captured_urls[0]).query)
        self.assertEqual(params["name"], ["Sorry"])
        self.assertEqual(params["artist_name"], ["Fang Datong"])
        self.assertEqual(params["album_name"], ["The Dreamer"])
        self.assertEqual(params["limit"], ["20"])
        self.assertEqual(params["type"], ["single albumtrack"])
        self.assertEqual(params["order"], ["relevance"])
        self.assertNotIn("search", params)

    def test_jamendo_selected_track_relaxes_album_after_identity_mismatch(self) -> None:
        captured_urls: list[str] = []

        def fake_json_get(url: str, **_: object) -> dict[str, object]:
            captured_urls.append(url)
            if len(captured_urls) == 1:
                return {
                    "results": [{
                        "id": "wrong",
                        "name": "Sorry",
                        "artist_name": "Wrong Artist",
                        "audio": "https://audio.example/wrong.mp3",
                    }]
                }
            return {
                "results": [{
                    "id": "right",
                    "name": "Sorry (Official Audio)",
                    "artist_name": "Fang Datong feat. Guest",
                    "audio": "https://audio.example/right.mp3",
                }]
            }

        with patch("src.tools.online_play._json_get", side_effect=fake_json_get):
            candidates = online.search_jamendo_audio_candidates(
                "Fang Datong Sorry",
                client_id="client-id",
                playback_metadata={
                    "metadata_source": "spotify",
                    "name": "Sorry",
                    "artist": "Fang Datong",
                    "album": "The Dreamer",
                },
            )

        self.assertEqual([candidate["id"] for candidate in candidates], ["right"])
        fallback_params = urllib.parse.parse_qs(urllib.parse.urlparse(captured_urls[1]).query)
        self.assertEqual(fallback_params["namesearch"], ["Sorry"])
        self.assertEqual(fallback_params["artist_name"], ["Fang Datong"])
        self.assertNotIn("album_name", fallback_params)

    def test_identity_matching_ignores_display_suffixes_but_preserves_versions(self) -> None:
        target = {"title": "Ｓｏｒｒｙ!", "artist": "Fang-Datong"}

        self.assertTrue(online._identity_matches(target, {"title": "Sorry (Official Audio)", "artist": "Fang Datong feat. Guest"}))
        self.assertTrue(online._identity_matches(target, {"title": "Sorry [2011 Remastered]", "artist": "Fang Datong"}))
        self.assertTrue(online._identity_matches(target, {"title": "Fang Datong - Sorry Official Video", "artist": "Fang Datong"}))
        for version in ("Sorry Live", "Sorry Cover", "Sorry Remix", "Sorry Karaoke"):
            with self.subTest(version=version):
                self.assertFalse(online._identity_matches(target, {"title": version, "artist": "Fang Datong"}))

    def test_normalize_jamendo_track_accepts_stream_without_download_url(self) -> None:
        """Verifies that normalize jamendo track accepts stream without download url behaves as expected.

        Typical use: Use this in automated tests when guarding the normalize jamendo track accepts stream without download url behavior against regressions.

        Example: test_normalize_jamendo_track_accepts_stream_without_download_url() -> passes without assertion failures when the behavior remains correct.
        """
        candidate = online.normalize_jamendo_track(
            {
                "id": "jam-2",
                "name": "Stream Only",
                "artist_name": "Artist",
                "audio": "https://audio.example/stream-only.mp3",
                "audiodownload_allowed": True,
            },
            query="Artist Stream Only",
        )

        self.assertIsNotNone(candidate)
        assert candidate is not None
        self.assertEqual(candidate["source_url"], "https://audio.example/stream-only.mp3")
        self.assertEqual(candidate["download_url"], "https://audio.example/stream-only.mp3")

    def test_normalize_audius_track_uses_best_artwork_and_excludes_gated_tracks(self) -> None:
        """Verifies that normalize audius track uses best artwork and excludes gated tracks behaves as expected.

        Typical use: Use this in automated tests when guarding the normalize audius track uses best artwork and excludes gated tracks behavior against regressions.

        Example: test_normalize_audius_track_uses_best_artwork_and_excludes_gated_tracks() -> passes without assertion failures when the behavior remains correct.
        """
        gated = online.normalize_audius_track(
            {
                "id": "aud-gated",
                "title": "Gated Song",
                "user": {"name": "Artist"},
                "is_stream_gated": True,
                "permalink": "https://audius.co/artist/gated",
            },
            query="Artist Gated Song",
            stream_url="https://audius.example/stream/gated",
        )
        self.assertIsNone(gated)

        candidate = online.normalize_audius_track(
            {
                "id": "aud-1",
                "title": "Canonical Song",
                "user": {"name": "Canonical Artist"},
                "duration": 202,
                "artwork": {
                    "150x150": "https://img.example/150.jpg",
                    "480x480": "https://img.example/480.jpg",
                    "1000x1000": "https://img.example/1000.jpg",
                },
                "permalink": "https://audius.co/artist/song",
            },
            query="Canonical Artist Canonical Song",
            stream_url="https://audius.example/stream/aud-1",
        )

        self.assertIsNotNone(candidate)
        assert candidate is not None
        self.assertEqual(candidate["provider"], "audius")
        self.assertEqual(candidate["cache_id"], "audius_aud-1")
        self.assertEqual(candidate["source_url"], "https://audius.example/stream/aud-1")
        self.assertEqual(candidate["download_url"], "https://audius.example/stream/aud-1")
        self.assertEqual(candidate["cover_url"], "https://img.example/1000.jpg")
        self.assertEqual(candidate["duration_ms"], 202000)

    def test_audius_selected_track_filters_wrong_identity_before_ranking(self) -> None:
        payload = {
            "data": [
                {"id": "wrong", "title": "Sorry", "user": {"name": "Wrong Artist"}},
                {"id": "right", "title": "Sorry (Official Audio)", "user": {"name": "Fang Datong"}},
            ]
        }

        with patch("src.tools.online_play._json_get", return_value=payload):
            candidates = online.search_audius_audio_candidates(
                "Fang Datong Sorry",
                api_key="api-key",
                playback_metadata={
                    "metadata_source": "spotify",
                    "name": "Sorry",
                    "artist": "Fang Datong",
                },
            )

        self.assertEqual([candidate["id"] for candidate in candidates], ["right"])
        self.assertTrue(candidates[0]["identity_match"])

    def test_youtube_selected_track_filters_wrong_identity_before_ranking(self) -> None:
        FakeYoutubeDL.responses = [{
            "entries": [
                {
                    "id": "wrong",
                    "track": "Sorry",
                    "artist": "Wrong Artist",
                    "webpage_url": "https://www.youtube.com/watch?v=wrong",
                },
                {
                    "id": "right",
                    "track": "Sorry (Official Audio)",
                    "artist": "Fang Datong",
                    "webpage_url": "https://www.youtube.com/watch?v=right",
                },
            ]
        }]

        with patch("src.tools.online_play.yt_dlp.YoutubeDL", FakeYoutubeDL):
            candidates = online.search_youtube_songs(
                "Fang Datong Sorry",
                playback_metadata={
                    "metadata_source": "spotify",
                    "name": "Sorry",
                    "artist": "Fang Datong",
                },
            )

        self.assertEqual([candidate["youtube_id"] for candidate in candidates], ["right"])
        self.assertEqual(candidates[0]["source_identity"]["artist"], "Fang Datong")

    def test_resolve_online_audio_records_missing_config_before_youtube(self) -> None:
        """Verifies that resolve online audio records missing config before youtube behaves as expected.

        Typical use: Use this in automated tests when guarding the resolve online audio records missing config before youtube behavior against regressions.

        Example: test_resolve_online_audio_records_missing_config_before_youtube() -> passes without assertion failures when the behavior remains correct.
        """
        config = online.OnlineAudioConfig(jamendo_client_id=None, audius_api_key=None)
        youtube_candidate = {
            "provider": "youtube",
            "cache_id": "youtube_yt-1",
            "id": "yt-1",
            "name": "Song",
            "artist": "Artist",
            "quality_label": "clean_audio_match",
            "similarity_score": 92,
        }

        with patch("src.tools.online_play.search_jamendo_audio_candidates") as jamendo_search, \
             patch("src.tools.online_play.search_audius_audio_candidates") as audius_search, \
             patch("src.tools.online_play.search_youtube_songs", return_value=[youtube_candidate]) as youtube_search:
            candidates = online.resolve_online_audio_candidates("Artist Song", config=config)

        jamendo_search.assert_not_called()
        audius_search.assert_not_called()
        youtube_search.assert_called_once()
        self.assertEqual(candidates[0]["cache_id"], "youtube_yt-1")
        self.assertEqual(
            candidates[0]["source_attempts"],
            [
                {
                    "provider": "jamendo",
                    "status": "missing_config",
                    "candidate_count": 0,
                    "credible_count": 0,
                    "message": "Jamendo is not configured.",
                },
                {
                    "provider": "audius",
                    "status": "missing_config",
                    "candidate_count": 0,
                    "credible_count": 0,
                    "message": "Audius is not configured.",
                },
            ],
        )
        self.assertIn("Jamendo is not configured", candidates[0]["fallback_reason"])
        self.assertIn("Audius is not configured", candidates[0]["fallback_reason"])

    def test_resolve_online_audio_youtube_search_failure_keeps_attempt_trace(self) -> None:
        """Verifies that resolve online audio youtube search failure keeps attempt trace behaves as expected.

        Typical use: Use this in automated tests when guarding the resolve online audio youtube search failure keeps attempt trace behavior against regressions.

        Example: test_resolve_online_audio_youtube_search_failure_keeps_attempt_trace() -> passes without assertion failures when the behavior remains correct.
        """
        config = online.OnlineAudioConfig(jamendo_client_id=None, audius_api_key=None)

        with patch(
            "src.tools.online_play.search_youtube_songs",
            side_effect=RuntimeError("ERROR: [youtube] wYB9Vu282ZU: This video is not available"),
        ):
            with self.assertRaisesRegex(RuntimeError, "Jamendo is not configured") as cm:
                online.resolve_online_audio_candidates("Artist Song", config=config)
            message = str(cm.exception)

        self.assertIn("Audius is not configured", message)
        self.assertIn("Sonex fell back to YouTube", message)
        self.assertIn("Selected YouTube result is not available", message)
        self.assertNotIn("ERROR: [youtube]", message)
        self.assertNotIn("wYB9Vu282ZU", message)

    def test_resolve_online_audio_reports_youtube_identity_mismatch(self) -> None:
        FakeYoutubeDL.responses = [{
            "entries": [{
                "id": "wrong",
                "track": "Sorry",
                "artist": "Wrong Artist",
                "webpage_url": "https://www.youtube.com/watch?v=wrong",
            }]
        }]

        with patch("src.tools.online_play.yt_dlp.YoutubeDL", FakeYoutubeDL):
            with self.assertRaisesRegex(RuntimeError, "YouTube rejected 1 identity mismatch"):
                online.resolve_online_audio_candidates(
                    "Fang Datong Sorry",
                    config=online.OnlineAudioConfig(),
                    playback_metadata={
                        "metadata_source": "spotify",
                        "name": "Sorry",
                        "artist": "Fang Datong",
                    },
                )

    def test_resolve_online_audio_tries_youtube_only_after_configured_sources_fail(self) -> None:
        """Verifies that resolve online audio tries youtube only after configured sources fail behaves as expected.

        Typical use: Use this in automated tests when guarding the resolve online audio tries youtube only after configured sources fail behavior against regressions.

        Example: test_resolve_online_audio_tries_youtube_only_after_configured_sources_fail() -> passes without assertion failures when the behavior remains correct.
        """
        config = online.OnlineAudioConfig(jamendo_client_id="jamendo-id", audius_api_key=None)
        youtube_candidate = {
            "provider": "youtube",
            "cache_id": "youtube_yt-1",
            "id": "yt-1",
            "name": "Song",
            "artist": "Artist",
            "quality_label": "clean_audio_match",
            "similarity_score": 92,
        }

        with patch("src.tools.online_play.search_jamendo_audio_candidates", return_value=[]) as jamendo_search, \
             patch("src.tools.online_play.search_audius_audio_candidates") as audius_search, \
             patch("src.tools.online_play.search_youtube_songs", return_value=[youtube_candidate]) as youtube_search:
            candidates = online.resolve_online_audio_candidates("Artist Song", config=config)

        jamendo_search.assert_called_once()
        audius_search.assert_not_called()
        youtube_search.assert_called_once()
        self.assertEqual(candidates[0]["cache_id"], "youtube_yt-1")
        self.assertEqual(candidates[0]["fallback_provider"], "youtube")
        self.assertIn("Jamendo returned no credible matches", candidates[0]["fallback_reason"])
        self.assertEqual(
            candidates[0]["source_attempts"],
            [
                {
                    "provider": "jamendo",
                    "status": "no_credible_matches",
                    "candidate_count": 0,
                    "credible_count": 0,
                    "message": "Jamendo returned no credible matches.",
                },
                {
                    "provider": "audius",
                    "status": "missing_config",
                    "candidate_count": 0,
                    "credible_count": 0,
                    "message": "Audius is not configured.",
                },
            ],
        )

    def test_resolve_online_audio_filters_low_similarity_before_youtube_fallback(self) -> None:
        """Verifies that resolve online audio filters low similarity before youtube fallback behaves as expected.

        Typical use: Use this in automated tests when guarding the resolve online audio filters low similarity before youtube fallback behavior against regressions.

        Example: test_resolve_online_audio_filters_low_similarity_before_youtube_fallback() -> passes without assertion failures when the behavior remains correct.
        """
        config = online.OnlineAudioConfig(jamendo_client_id="jamendo-id", audius_api_key=None)
        low_similarity = {
            "provider": "jamendo",
            "cache_id": "jamendo_wrong",
            "id": "wrong",
            "name": "Wrong Song",
            "artist": "Other Artist",
            "quality_label": "official_original",
            "similarity_score": 24,
        }
        youtube_candidate = {
            "provider": "youtube",
            "cache_id": "youtube_yt-1",
            "id": "yt-1",
            "name": "Song",
            "artist": "Artist",
            "quality_label": "clean_audio_match",
            "similarity_score": 92,
        }

        with patch("src.tools.online_play.search_jamendo_audio_candidates", return_value=[low_similarity]), \
             patch("src.tools.online_play.search_youtube_songs", return_value=[youtube_candidate]) as youtube_search:
            candidates = online.resolve_online_audio_candidates("Artist Song", config=config)

        youtube_search.assert_called_once()
        self.assertEqual(candidates[0]["cache_id"], "youtube_yt-1")
        self.assertEqual(candidates[0]["fallback_provider"], "youtube")

    def test_resolve_online_audio_reports_identity_mismatch_rejections(self) -> None:
        config = online.OnlineAudioConfig(jamendo_client_id="jamendo-id", audius_api_key=None)
        wrong_payload = {
            "results": [{
                "id": "wrong",
                "name": "Sorry",
                "artist_name": "Wrong Artist",
                "audio": "https://audio.example/wrong.mp3",
            }]
        }
        youtube = {
            "provider": "youtube",
            "cache_id": "youtube_right",
            "name": "Sorry",
            "artist": "Fang Datong",
            "similarity_score": 100,
        }

        with patch("src.tools.online_play._json_get", return_value=wrong_payload), \
             patch("src.tools.online_play.search_youtube_songs", return_value=[youtube]):
            candidates = online.resolve_online_audio_candidates(
                "Fang Datong Sorry",
                config=config,
                playback_metadata={
                    "metadata_source": "spotify",
                    "name": "Sorry",
                    "artist": "Fang Datong",
                    "album": "The Dreamer",
                },
            )

        attempt = candidates[0]["source_attempts"][0]
        self.assertEqual(attempt["status"], "identity_mismatch")
        self.assertEqual(attempt["rejected_count"], 2)

    def test_resolve_online_audio_keeps_provider_error_trace_before_youtube_fallback(self) -> None:
        """Verifies that resolve online audio keeps provider error trace before youtube fallback behaves as expected.

        Typical use: Use this in automated tests when guarding the resolve online audio keeps provider error trace before youtube fallback behavior against regressions.

        Example: test_resolve_online_audio_keeps_provider_error_trace_before_youtube_fallback() -> passes without assertion failures when the behavior remains correct.
        """
        config = online.OnlineAudioConfig(jamendo_client_id="jamendo-id", audius_api_key=None)
        youtube_candidate = {
            "provider": "youtube",
            "cache_id": "youtube_yt-1",
            "id": "yt-1",
            "name": "Song",
            "artist": "Artist",
            "quality_label": "clean_audio_match",
            "similarity_score": 92,
        }

        with patch("src.tools.online_play.search_jamendo_audio_candidates", side_effect=RuntimeError("token secret=abc123 failed")), \
             patch("src.tools.online_play.search_youtube_songs", return_value=[youtube_candidate]):
            candidates = online.resolve_online_audio_candidates("Artist Song", config=config)

        self.assertEqual(candidates[0]["cache_id"], "youtube_yt-1")
        self.assertEqual(candidates[0]["source_attempts"][0]["status"], "error")
        self.assertIn("Jamendo failed:", candidates[0]["source_attempts"][0]["message"])
        self.assertNotIn("secret=abc123", candidates[0]["source_attempts"][0]["message"])
        self.assertIn("Jamendo failed:", candidates[0]["fallback_reason"])

    def test_rank_online_audio_candidates_uses_similarity_quality_before_provider_priority(self) -> None:
        """Verifies that rank online audio candidates uses similarity quality before provider priority behaves as expected.

        Typical use: Use this in automated tests when guarding the rank online audio candidates uses similarity quality before provider priority behavior against regressions.

        Example: test_rank_online_audio_candidates_uses_similarity_quality_before_provider_priority() -> passes without assertion failures when the behavior remains correct.
        """
        audius = {
            "provider": "audius",
            "id": "aud-1",
            "name": "Canonical Song",
            "artist": "Canonical Artist",
            "similarity_score": 96,
            "quality_label": "official_original",
        }
        jamendo = {
            "provider": "jamendo",
            "id": "jam-1",
            "name": "Wrong Song",
            "artist": "Other Artist",
            "similarity_score": 55,
            "quality_label": "official_original",
        }

        ranked = online.rank_online_audio_candidates("Canonical Artist Canonical Song", [jamendo, audius])

        self.assertEqual([candidate["provider"] for candidate in ranked], ["audius", "jamendo"])

    def test_search_youtube_songs_returns_five_candidates_without_downloading(self) -> None:
        """Verifies that search youtube songs returns five candidates without downloading behaves as expected.

        Typical use: Use this in automated tests when guarding the search youtube songs returns five candidates without downloading behavior against regressions.

        Example: test_search_youtube_songs_returns_five_candidates_without_downloading() -> passes without assertion failures when the behavior remains correct.
        """
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
        self.assertEqual(FakeYoutubeDL.calls[0]["target"], "ytsearch40:Song Artist")
        self.assertFalse(any(call["download"] for call in FakeYoutubeDL.calls))

    def test_search_youtube_songs_uses_confirmed_spotify_metadata_without_spotify_lookup(self) -> None:
        """Verifies that search youtube songs uses confirmed spotify metadata without spotify lookup behaves as expected.

        Typical use: Use this in automated tests when guarding the search youtube songs uses confirmed spotify metadata without spotify lookup behavior against regressions.

        Example: test_search_youtube_songs_uses_confirmed_spotify_metadata_without_spotify_lookup() -> passes without assertion failures when the behavior remains correct.
        """
        playback_metadata = {
            "metadata_source": "spotify",
            "original_query": "messy user query",
            "youtube_query": "Canonical Artist Canonical Song",
            "name": "Canonical Song",
            "title": "Canonical Song",
            "artist": "Canonical Artist",
            "artists": ["Canonical Artist"],
            "album": "Canonical Album",
            "duration_ms": 201000,
            "uri": "spotify:track:canonical",
        }
        FakeYoutubeDL.responses = [
            {
                "entries": [
                    {
                        "id": "abc123",
                        "track": "Canonical Song",
                        "artist": "Canonical Artist",
                        "duration": 185,
                        "webpage_url": "https://www.youtube.com/watch?v=abc123",
                    }
                ]
            }
        ]

        with patch("src.tools.spotify_play.spotify_search") as spotify_search, \
             patch("src.tools.online_play.yt_dlp.YoutubeDL", FakeYoutubeDL):
            candidates = online.search_youtube_songs(
                "ignored query",
                limit=5,
                playback_metadata=playback_metadata,
            )

        spotify_search.assert_not_called()
        self.assertEqual(FakeYoutubeDL.calls[0]["target"], "ytsearch40:Canonical Artist Canonical Song")
        self.assertEqual(candidates[0]["name"], "Canonical Song")
        self.assertEqual(candidates[0]["artist"], "Canonical Artist")
        self.assertEqual(candidates[0]["album"], "Canonical Album")
        self.assertEqual(candidates[0]["duration_ms"], 201000)
        self.assertEqual(candidates[0]["uri"], "spotify:track:canonical")
        self.assertEqual(candidates[0]["metadata_source"], "spotify")

    def test_search_youtube_songs_ranks_official_match_above_higher_view_noisy_media(self) -> None:
        """Verifies that search youtube songs ranks official match above higher view noisy media behaves as expected.

        Typical use: Use this in automated tests when guarding the search youtube songs ranks official match above higher view noisy media behavior against regressions.

        Example: test_search_youtube_songs_ranks_official_match_above_higher_view_noisy_media() -> passes without assertion failures when the behavior remains correct.
        """
        FakeYoutubeDL.responses = [
            {
                "entries": [
                    {
                        "id": "tv-show",
                        "title": "Love Song on Morning TV with celebrity interview",
                        "artist": "TV Cast",
                        "channel": "Hit Variety Show",
                        "duration": 210,
                        "view_count": 120_000_000,
                        "like_count": 900_000,
                        "webpage_url": "https://www.youtube.com/watch?v=tv-show",
                    },
                    {
                        "id": "official",
                        "title": "Love Song Official Music Video",
                        "artist": "X Artist",
                        "channel": "X Artist",
                        "duration": 215,
                        "view_count": 20_000_000,
                        "like_count": 250_000,
                        "webpage_url": "https://www.youtube.com/watch?v=official",
                    },
                    {
                        "id": "cover",
                        "title": "Love Song guitar cover tutorial",
                        "channel": "Cover Channel",
                        "duration": 200,
                        "view_count": 100_000_000,
                        "webpage_url": "https://www.youtube.com/watch?v=cover",
                    },
                ]
            }
        ]

        with patch("src.tools.online_play.yt_dlp.YoutubeDL", FakeYoutubeDL):
            candidates = online.search_youtube_songs("Love Song", limit=5)

        self.assertEqual([candidate["youtube_id"] for candidate in candidates], ["official", "tv-show"])
        self.assertEqual(candidates[0]["variant_type"], "official_original")
        self.assertEqual(candidates[0]["quality_label"], "official_original")
        self.assertGreater(candidates[0]["similarity_score"], 0)
        self.assertEqual(candidates[1]["quality_label"], "noisy_media")
        self.assertGreater(candidates[1]["popularity_score"], candidates[0]["popularity_score"])
        self.assertIn("official", candidates[0]["rank_reason"])

    def test_search_youtube_songs_ranks_clean_match_above_higher_view_show_result(self) -> None:
        """Verifies that search youtube songs ranks clean match above higher view show result behaves as expected.

        Typical use: Use this in automated tests when guarding the search youtube songs ranks clean match above higher view show result behavior against regressions.

        Example: test_search_youtube_songs_ranks_clean_match_above_higher_view_show_result() -> passes without assertion failures when the behavior remains correct.
        """
        FakeYoutubeDL.responses = [
            {
                "entries": [
                    {
                        "id": "show",
                        "title": "Love Song finale performance on singing show",
                        "artist": "Contestant",
                        "channel": "Prime Time Show",
                        "duration": 230,
                        "view_count": 80_000_000,
                        "webpage_url": "https://www.youtube.com/watch?v=show",
                    },
                    {
                        "id": "clean",
                        "title": "X Artist - Love Song",
                        "channel": "Music Archive",
                        "duration": 215,
                        "view_count": 800_000,
                        "webpage_url": "https://www.youtube.com/watch?v=clean",
                    },
                ]
            }
        ]

        with patch("src.tools.online_play.yt_dlp.YoutubeDL", FakeYoutubeDL):
            candidates = online.search_youtube_songs("X Artist Love Song", limit=5)

        self.assertEqual([candidate["youtube_id"] for candidate in candidates], ["clean", "show"])
        self.assertEqual(candidates[0]["quality_label"], "clean_audio_match")
        self.assertEqual(candidates[1]["quality_label"], "noisy_media")

    def test_search_youtube_songs_uses_popularity_as_tiebreaker_for_clean_matches(self) -> None:
        """Verifies that search youtube songs uses popularity as tiebreaker for clean matches behaves as expected.

        Typical use: Use this in automated tests when guarding the search youtube songs uses popularity as tiebreaker for clean matches behavior against regressions.

        Example: test_search_youtube_songs_uses_popularity_as_tiebreaker_for_clean_matches() -> passes without assertion failures when the behavior remains correct.
        """
        FakeYoutubeDL.responses = [
            {
                "entries": [
                    {
                        "id": "lower",
                        "title": "X Artist - Love Song",
                        "channel": "Archive One",
                        "duration": 215,
                        "view_count": 800_000,
                        "webpage_url": "https://www.youtube.com/watch?v=lower",
                    },
                    {
                        "id": "higher",
                        "title": "X Artist - Love Song",
                        "channel": "Archive Two",
                        "duration": 215,
                        "view_count": 2_000_000,
                        "webpage_url": "https://www.youtube.com/watch?v=higher",
                    },
                ]
            }
        ]

        with patch("src.tools.online_play.yt_dlp.YoutubeDL", FakeYoutubeDL):
            candidates = online.search_youtube_songs("X Artist Love Song", limit=5)

        self.assertEqual([candidate["youtube_id"] for candidate in candidates], ["higher", "lower"])

    def test_search_youtube_songs_prioritizes_live_when_query_requests_live(self) -> None:
        """Verifies that search youtube songs prioritizes live when query requests live behaves as expected.

        Typical use: Use this in automated tests when guarding the search youtube songs prioritizes live when query requests live behavior against regressions.

        Example: test_search_youtube_songs_prioritizes_live_when_query_requests_live() -> passes without assertion failures when the behavior remains correct.
        """
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
        """Verifies that search youtube songs handles missing popularity fields behaves as expected.

        Typical use: Use this in automated tests when guarding the search youtube songs handles missing popularity fields behavior against regressions.

        Example: test_search_youtube_songs_handles_missing_popularity_fields() -> passes without assertion failures when the behavior remains correct.
        """
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

    def test_search_youtube_songs_skips_age_restricted_candidates(self) -> None:
        """Verifies that search youtube songs skips age restricted candidates behaves as expected.

        Typical use: Use this in automated tests when guarding the search youtube songs skips age restricted candidates behavior against regressions.

        Example: test_search_youtube_songs_skips_age_restricted_candidates() -> passes without assertion failures when the behavior remains correct.
        """
        FakeYoutubeDL.responses = [
            {
                "entries": [
                    {
                        "id": "age-restricted",
                        "title": "Sorry Official Video",
                        "artist": "Justin Bieber",
                        "channel": "Justin Bieber",
                        "duration": 200,
                        "age_limit": 18,
                        "webpage_url": "https://www.youtube.com/watch?v=age-restricted",
                    },
                    {
                        "id": "playable",
                        "title": "Justin Bieber - Sorry Official Audio",
                        "artist": "Justin Bieber",
                        "channel": "Justin Bieber",
                        "duration": 200,
                        "age_limit": 0,
                        "webpage_url": "https://www.youtube.com/watch?v=playable",
                    },
                ]
            }
        ]

        with patch("src.tools.online_play.yt_dlp.YoutubeDL", FakeYoutubeDL):
            candidates = online.search_youtube_songs("Justin Bieber Sorry", limit=5)

        self.assertEqual([candidate["youtube_id"] for candidate in candidates], ["playable"])

    def test_search_youtube_songs_skips_unavailable_candidates(self) -> None:
        """Verifies that search youtube songs skips unavailable candidates behaves as expected.

        Typical use: Use this in automated tests when guarding the search youtube songs skips unavailable candidates behavior against regressions.

        Example: test_search_youtube_songs_skips_unavailable_candidates() -> passes without assertion failures when the behavior remains correct.
        """
        FakeYoutubeDL.responses = [
            {
                "entries": [
                    {
                        "id": "unavailable",
                        "title": "Song Artist Official Video",
                        "artist": "Song Artist",
                        "channel": "Song Artist",
                        "duration": 200,
                        "availability": "unavailable",
                        "webpage_url": "https://www.youtube.com/watch?v=unavailable",
                    },
                    {
                        "id": "playable",
                        "title": "Song Artist Official Audio",
                        "artist": "Song Artist",
                        "channel": "Song Artist",
                        "duration": 200,
                        "availability": "public",
                        "webpage_url": "https://www.youtube.com/watch?v=playable",
                    },
                ]
            }
        ]

        with patch("src.tools.online_play.yt_dlp.YoutubeDL", FakeYoutubeDL):
            candidates = online.search_youtube_songs("Song Artist", limit=5)

        self.assertEqual([candidate["youtube_id"] for candidate in candidates], ["playable"])

    def test_download_youtube_candidate_writes_cache_item_and_audio_file(self) -> None:
        """Verifies that download youtube candidate writes cache item and audio file behaves as expected.

        Typical use: Use this in automated tests when guarding the download youtube candidate writes cache item and audio file behavior against regressions.

        Example: test_download_youtube_candidate_writes_cache_item_and_audio_file() -> passes without assertion failures when the behavior remains correct.
        """
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
        """Verifies that download youtube candidate reuses existing audio cache behaves as expected.

        Typical use: Use this in automated tests when guarding the download youtube candidate reuses existing audio cache behavior against regressions.

        Example: test_download_youtube_candidate_reuses_existing_audio_cache() -> passes without assertion failures when the behavior remains correct.
        """
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

    def test_download_youtube_candidate_skips_legacy_cache_for_selected_track(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "audio" / "youtube_abc123.webm"
            audio.parent.mkdir(parents=True)
            audio.write_bytes(b"legacy")
            upsert_cached_song(
                {
                    "provider": "youtube",
                    "cache_id": "youtube_abc123",
                    "youtube_id": "abc123",
                    "name": "Sorry",
                    "artist": "Wrong Artist",
                    "audio_path": str(audio),
                    "audio_ext": "webm",
                    "stream_url": str(audio),
                },
                cache_root=root,
            )
            FakeYoutubeDL.responses = [{
                "id": "abc123",
                "track": "Sorry",
                "artist": "Fang Datong",
                "webpage_url": "https://www.youtube.com/watch?v=abc123",
                "ext": "m4a",
            }]
            candidate = {
                "provider": "youtube",
                "id": "abc123",
                "youtube_id": "abc123",
                "cache_id": "youtube_abc123",
                "query": "Fang Datong Sorry",
                "name": "Sorry",
                "artist": "Fang Datong",
                "target_identity": {"title": "Sorry", "artist": "Fang Datong", "album": "The Dreamer"},
                "source_identity": {"title": "Sorry", "artist": "Fang Datong", "album": ""},
                "identity_match": True,
                "url": "https://www.youtube.com/watch?v=abc123",
                "webpage_url": "https://www.youtube.com/watch?v=abc123",
            }

            with patch("src.tools.online_play.yt_dlp.YoutubeDL", FakeYoutubeDL):
                item = online.download_youtube_candidate(candidate, cache_root=root)

            self.assertEqual(len(FakeYoutubeDL.calls), 1)
            self.assertEqual(item["source_identity"]["artist"], "Fang Datong")
            self.assertEqual(Path(item["audio_path"]).suffix, ".m4a")

    def test_download_youtube_candidate_reuses_identity_verified_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "audio" / "youtube_abc123.webm"
            audio.parent.mkdir(parents=True)
            audio.write_bytes(b"verified")
            identity = {"title": "Sorry", "artist": "Fang Datong", "album": "The Dreamer"}
            upsert_cached_song(
                {
                    "provider": "youtube",
                    "cache_id": "youtube_abc123",
                    "youtube_id": "abc123",
                    "name": "Sorry",
                    "artist": "Fang Datong",
                    "target_identity": identity,
                    "source_identity": identity,
                    "identity_match": True,
                    "audio_path": str(audio),
                    "audio_ext": "webm",
                },
                cache_root=root,
            )

            item = online.download_youtube_candidate(
                {
                    "provider": "youtube",
                    "cache_id": "youtube_abc123",
                    "target_identity": identity,
                    "url": "https://www.youtube.com/watch?v=abc123",
                },
                cache_root=root,
            )

            self.assertEqual(item["audio_path"], str(audio))
            self.assertEqual(FakeYoutubeDL.calls, [])

    def test_download_youtube_candidate_deletes_final_identity_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate = {
                "provider": "youtube",
                "id": "abc123",
                "youtube_id": "abc123",
                "cache_id": "youtube_abc123",
                "query": "Fang Datong Sorry",
                "name": "Sorry",
                "artist": "Fang Datong",
                "target_identity": {"title": "Sorry", "artist": "Fang Datong", "album": "The Dreamer"},
                "source_identity": {"title": "Sorry", "artist": "Fang Datong", "album": ""},
                "identity_match": True,
                "url": "https://www.youtube.com/watch?v=abc123",
                "webpage_url": "https://www.youtube.com/watch?v=abc123",
            }
            FakeYoutubeDL.responses = [{
                "id": "abc123",
                "track": "Sorry",
                "artist": "Wrong Artist",
                "webpage_url": "https://www.youtube.com/watch?v=abc123",
                "ext": "m4a",
            }]

            with patch("src.tools.online_play.yt_dlp.YoutubeDL", FakeYoutubeDL):
                with self.assertRaisesRegex(RuntimeError, "identity does not match"):
                    online.download_youtube_candidate(candidate, cache_root=root)

            self.assertEqual(list((root / "audio").glob("youtube_abc123.*")), [])
            self.assertFalse((root / "items" / "youtube_abc123.json").exists())

    def test_download_open_audio_candidate_rejects_identity_mismatch_before_fetch(self) -> None:
        candidate = {
            "provider": "jamendo",
            "id": "wrong",
            "cache_id": "jamendo_wrong",
            "name": "Sorry",
            "artist": "Fang Datong",
            "download_url": "https://audio.example/wrong.mp3",
            "target_identity": {"title": "Sorry", "artist": "Fang Datong", "album": "The Dreamer"},
            "source_identity": {"title": "Sorry", "artist": "Wrong Artist", "album": ""},
            "identity_match": False,
        }

        with patch("src.tools.online_play.urllib.request.urlopen") as urlopen:
            with self.assertRaisesRegex(RuntimeError, "identity does not match"):
                online.download_open_audio_candidate(candidate)

        urlopen.assert_not_called()

    def test_play_youtube_song_tries_next_candidate_after_final_identity_mismatch(self) -> None:
        candidates = [
            {"provider": "youtube", "cache_id": "youtube_wrong"},
            {"provider": "youtube", "cache_id": "youtube_right"},
        ]
        mismatch = ToolResult.fail(
            tool="play_youtube_song",
            message="Downloaded audio identity does not match the selected track.",
            error_code="ONLINE_AUDIO_IDENTITY_MISMATCH",
        ).to_dict()
        success = ToolResult.success(tool="play_youtube_song", message="playing", data={"cache_id": "youtube_right"}).to_dict()

        with patch("src.tools.online_play.online_audio_configured", return_value=False), \
             patch("src.tools.online_play.search_youtube_songs", return_value=candidates) as search, \
             patch("src.tools.online_play.play_youtube_candidate", side_effect=[mismatch, success]) as play:
            result = online.play_youtube_song(
                "Fang Datong Sorry",
                playback_metadata={"name": "Sorry", "artist": "Fang Datong"},
            )

        search.assert_called_once_with(
            "Fang Datong Sorry",
            limit=5,
            cache_root=None,
            playback_metadata={"name": "Sorry", "artist": "Fang Datong"},
        )
        self.assertEqual(play.call_count, 2)
        self.assertEqual(result["status"], "success")

    def test_play_youtube_song_returns_normalized_music_metadata(self) -> None:
        """Verifies that play youtube song returns normalized music metadata behaves as expected.

        Typical use: Use this in automated tests when guarding the play youtube song returns normalized music metadata behavior against regressions.

        Example: test_play_youtube_song_returns_normalized_music_metadata() -> passes without assertion failures when the behavior remains correct.
        """
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

    def test_play_youtube_song_uses_confirmed_spotify_metadata_for_youtube_and_caa(self) -> None:
        """Verifies that play youtube song uses confirmed spotify metadata for youtube and caa behaves as expected.

        Typical use: Use this in automated tests when guarding the play youtube song uses confirmed spotify metadata for youtube and caa behavior against regressions.

        Example: test_play_youtube_song_uses_confirmed_spotify_metadata_for_youtube_and_caa() -> passes without assertion failures when the behavior remains correct.
        """
        playback_metadata = {
            "metadata_source": "spotify",
            "original_query": "messy user query",
            "youtube_query": "Canonical Artist Canonical Song",
            "id": "spotify-track",
            "name": "Canonical Song",
            "title": "Canonical Song",
            "artist": "Canonical Artist",
            "artists": ["Canonical Artist"],
            "album": "Canonical Album",
            "duration_ms": 201000,
            "album_cover_url": "https://i.scdn.co/image/official",
            "spotify_url": "https://open.spotify.com/track/spotify-track",
            "uri": "spotify:track:spotify-track",
        }
        FakeYoutubeDL.responses = [
            {
                "entries": [
                    {
                        "id": "abc123",
                        "track": "Canonical Song",
                        "artist": "Canonical Artist",
                        "duration": 185,
                        "webpage_url": "https://www.youtube.com/watch?v=abc123",
                    }
                ]
            },
            {
                "id": "abc123",
                "track": "Canonical Song",
                "artist": "Canonical Artist",
                "album": "Canonical Album",
                "duration": 185,
                "thumbnail": "https://i.ytimg.com/vi/abc123/maxresdefault.jpg",
                "webpage_url": "https://www.youtube.com/watch?v=abc123",
                "url": "https://stream.example/audio.webm",
            },
        ]

        with tempfile.TemporaryDirectory() as tmp:
            with patch("src.tools.spotify_play.spotify_search") as spotify_search, \
                patch("src.tools.online_play.yt_dlp.YoutubeDL", FakeYoutubeDL), \
                patch("src.tools.cover_sources.lookup_cover_art_url", return_value="https://coverartarchive.org/release-group/mbid/front-500") as cover_lookup, \
                patch("src.tools.online_play.check_player", return_value=True), \
                patch("src.tools.online_play.is_player_allowed", return_value=True), \
                patch("src.tools.online_play.start_local_playback", side_effect=_playback_success):
                result = online.play_youtube_song(
                    "messy user query",
                    player="mpv",
                    cache_root=Path(tmp),
                    playback_metadata=playback_metadata,
                )

        self.assertEqual(result["status"], "success")
        spotify_search.assert_not_called()
        self.assertEqual(FakeYoutubeDL.calls[0]["target"], "ytsearch40:Canonical Artist Canonical Song")
        cover_lookup.assert_called_once_with(name="Canonical Song", artist="Canonical Artist", album="Canonical Album")
        data = result["data"]
        self.assertEqual(data["name"], "Canonical Song")
        self.assertEqual(data["artist"], "Canonical Artist")
        self.assertEqual(data["album"], "Canonical Album")
        self.assertEqual(data["duration_ms"], 201000)
        self.assertEqual(data["spotify_url"], "https://open.spotify.com/track/spotify-track")
        self.assertEqual(data["uri"], "spotify:track:spotify-track")
        self.assertEqual(data["metadata_source"], "spotify")
        self.assertEqual(data["youtube_query"], "Canonical Artist Canonical Song")
        self.assertEqual(data["original_query"], "messy user query")
        self.assertEqual(data["album_cover_url"], "https://coverartarchive.org/release-group/mbid/front-500")
        self.assertEqual(data["cover_source_type"], "cover_art_archive")

    def test_play_youtube_song_does_not_use_spotify_cover_when_caa_misses(self) -> None:
        """Verifies that play youtube song does not use spotify cover when caa misses behaves as expected.

        Typical use: Use this in automated tests when guarding the play youtube song does not use spotify cover when caa misses behavior against regressions.

        Example: test_play_youtube_song_does_not_use_spotify_cover_when_caa_misses() -> passes without assertion failures when the behavior remains correct.
        """
        playback_metadata = {
            "metadata_source": "spotify",
            "original_query": "messy user query",
            "youtube_query": "Canonical Artist Canonical Song",
            "name": "Canonical Song",
            "title": "Canonical Song",
            "artist": "Canonical Artist",
            "artists": ["Canonical Artist"],
            "album": "Canonical Album",
            "duration_ms": 201000,
            "album_cover_url": "https://i.scdn.co/image/official",
        }
        FakeYoutubeDL.responses = [
            {
                "entries": [
                    {
                        "id": "abc123",
                        "track": "Canonical Song",
                        "artist": "Canonical Artist",
                        "duration": 185,
                        "thumbnail": "https://i.ytimg.com/vi/abc123/maxresdefault.jpg",
                        "webpage_url": "https://www.youtube.com/watch?v=abc123",
                    }
                ]
            },
            {
                "id": "abc123",
                "track": "Canonical Song",
                "artist": "Canonical Artist",
                "duration": 185,
                "thumbnail": "https://i.ytimg.com/vi/abc123/maxresdefault.jpg",
                "webpage_url": "https://www.youtube.com/watch?v=abc123",
                "url": "https://stream.example/audio.webm",
            },
        ]

        with tempfile.TemporaryDirectory() as tmp:
            with patch("src.tools.spotify_play.spotify_search") as spotify_search, \
                patch("src.tools.online_play.yt_dlp.YoutubeDL", FakeYoutubeDL), \
                patch("src.tools.cover_sources.lookup_cover_art_url", return_value=None), \
                patch("src.tools.online_play.check_player", return_value=True), \
                patch("src.tools.online_play.is_player_allowed", return_value=True), \
                patch("src.tools.online_play.start_local_playback", side_effect=_playback_success):
                result = online.play_youtube_song(
                    "messy user query",
                    player="mpv",
                    cache_root=Path(tmp),
                    playback_metadata=playback_metadata,
                )

        self.assertEqual(result["status"], "success")
        spotify_search.assert_not_called()
        data = result["data"]
        self.assertEqual(data["name"], "Canonical Song")
        self.assertIsNone(data["album_cover_url"])
        self.assertIsNone(data["cover_url"])
        self.assertNotIn("cover_source", data)
        self.assertNotIn("provider_album_cover_url", data)
        self.assertNotIn("official_album_cover_url", data)

    def test_play_youtube_song_does_not_auto_lookup_spotify_and_uses_raw_query(self) -> None:
        """Verifies that play youtube song does not auto lookup spotify and uses raw query behaves as expected.

        Typical use: Use this in automated tests when guarding the play youtube song does not auto lookup spotify and uses raw query behavior against regressions.

        Example: test_play_youtube_song_does_not_auto_lookup_spotify_and_uses_raw_query() -> passes without assertion failures when the behavior remains correct.
        """
        FakeYoutubeDL.responses = [
            {
                "entries": [
                    {
                        "id": "abc123",
                        "title": "Raw Query Match",
                        "artist": "Uploader",
                        "duration": 185,
                        "webpage_url": "https://www.youtube.com/watch?v=abc123",
                    }
                ]
            },
            {
                "id": "abc123",
                "title": "Raw Query Match",
                "artist": "Uploader",
                "duration": 185,
                "webpage_url": "https://www.youtube.com/watch?v=abc123",
                "url": "https://stream.example/audio.webm",
            },
        ]

        with tempfile.TemporaryDirectory() as tmp:
            with patch("src.tools.spotify_play.spotify_search") as spotify_search, \
                patch("src.tools.online_play.yt_dlp.YoutubeDL", FakeYoutubeDL), \
                patch("src.tools.cover_sources.lookup_cover_art_url", return_value=None), \
                patch("src.tools.online_play.check_player", return_value=True), \
                patch("src.tools.online_play.is_player_allowed", return_value=True), \
                patch("src.tools.online_play.start_local_playback", side_effect=_playback_success):
                result = online.play_youtube_song("raw query", player="mpv", cache_root=Path(tmp))

        self.assertEqual(result["status"], "success")
        spotify_search.assert_not_called()
        self.assertEqual(FakeYoutubeDL.calls[0]["target"], "ytsearch8:raw query")
        data = result["data"]
        self.assertEqual(data["metadata_source"], "query_fallback")
        self.assertEqual(data["youtube_query"], "raw query")
        self.assertEqual(data["original_query"], "raw query")

    def test_play_youtube_song_falls_back_to_uploader_and_best_audio_format(self) -> None:
        """Verifies that play youtube song falls back to uploader and best audio format behaves as expected.

        Typical use: Use this in automated tests when guarding the play youtube song falls back to uploader and best audio format behavior against regressions.

        Example: test_play_youtube_song_falls_back_to_uploader_and_best_audio_format() -> passes without assertion failures when the behavior remains correct.
        """
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
        """Verifies that play youtube song returns failure when no audio stream is available behaves as expected.

        Typical use: Use this in automated tests when guarding the play youtube song returns failure when no audio stream is available behavior against regressions.

        Example: test_play_youtube_song_returns_failure_when_no_audio_stream_is_available() -> passes without assertion failures when the behavior remains correct.
        """
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

    def test_play_youtube_song_uses_open_audio_trace_before_youtube_unavailable_fallback(self) -> None:
        """Verifies that play youtube song uses open audio trace before youtube unavailable fallback behaves as expected.

        Typical use: Use this in automated tests when guarding the play youtube song uses open audio trace before youtube unavailable fallback behavior against regressions.

        Example: test_play_youtube_song_uses_open_audio_trace_before_youtube_unavailable_fallback() -> passes without assertion failures when the behavior remains correct.
        """
        config = online.OnlineAudioConfig(jamendo_client_id="jamendo-id", audius_api_key=None)
        youtube_candidate = {
            "provider": "youtube",
            "cache_id": "youtube_wYB9Vu282ZU",
            "id": "wYB9Vu282ZU",
            "youtube_id": "wYB9Vu282ZU",
            "query": "Artist Song",
            "name": "Artist Song",
            "artist": "Artist",
            "quality_label": "clean_audio_match",
            "similarity_score": 92,
            "webpage_url": "https://www.youtube.com/watch?v=wYB9Vu282ZU",
            "url": "https://www.youtube.com/watch?v=wYB9Vu282ZU",
        }
        FakeYoutubeDL.responses = [
            DownloadError("ERROR: [youtube] wYB9Vu282ZU: This video is not available")
        ]

        with tempfile.TemporaryDirectory() as tmp:
            with patch("src.tools.online_play.online_audio_config", return_value=config), \
                patch("src.tools.online_play.search_jamendo_audio_candidates", return_value=[]), \
                patch("src.tools.online_play.search_youtube_songs", return_value=[youtube_candidate]), \
                patch("src.tools.online_play.yt_dlp.YoutubeDL", FakeYoutubeDL), \
                patch("src.tools.online_play.start_local_playback") as launch:
                result = online.play_youtube_song("Artist Song", player="mpv", cache_root=Path(tmp))

        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["tool"], "play_online_audio")
        self.assertEqual(result["error_code"], "YOUTUBE_UNAVAILABLE")
        self.assertIn("Jamendo returned no credible matches", result["message"])
        self.assertIn("fell back to YouTube", result["message"])
        self.assertIn("Choose another candidate or refine", result["message"])
        self.assertNotIn("wYB9Vu282ZU", result["message"])
        self.assertEqual(result["data"]["source_attempts"][0]["provider"], "jamendo")
        launch.assert_not_called()

    def test_play_youtube_candidate_returns_age_restricted_failure_without_cookie_instructions(self) -> None:
        """Verifies that play youtube candidate returns age restricted failure without cookie instructions behaves as expected.

        Typical use: Use this in automated tests when guarding the play youtube candidate returns age restricted failure without cookie instructions behavior against regressions.

        Example: test_play_youtube_candidate_returns_age_restricted_failure_without_cookie_instructions() -> passes without assertion failures when the behavior remains correct.
        """
        candidate = {
            "provider": "youtube",
            "id": "AjKbw1Cqpt0",
            "youtube_id": "AjKbw1Cqpt0",
            "cache_id": "youtube_AjKbw1Cqpt0",
            "query": "Sorry",
            "name": "Sorry",
            "artist": "Artist",
            "album": "-",
            "duration_ms": 200000,
            "url": "https://www.youtube.com/watch?v=AjKbw1Cqpt0",
            "webpage_url": "https://www.youtube.com/watch?v=AjKbw1Cqpt0",
        }
        FakeYoutubeDL.responses = [
            RuntimeError(
                "ERROR: [youtube] AjKbw1Cqpt0: Sign in to confirm your age. "
                "This video may be inappropriate for some users. Use --cookies-from-browser or --cookies."
            )
        ]

        with tempfile.TemporaryDirectory() as tmp:
            with patch("src.tools.online_play.yt_dlp.YoutubeDL", FakeYoutubeDL), \
                patch("src.tools.online_play.start_local_playback") as launch:
                result = online.play_youtube_candidate(candidate, player="mpv", cache_root=Path(tmp))

        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["error_code"], "YOUTUBE_AGE_RESTRICTED")
        self.assertIn("age verification", result["message"])
        self.assertNotIn("--cookies", result["message"])
        self.assertNotIn("cookies-from-browser", result["message"])
        launch.assert_not_called()

    def test_play_youtube_candidate_returns_unavailable_failure_without_raw_extractor_error(self) -> None:
        """Verifies that play youtube candidate returns unavailable failure without raw extractor error behaves as expected.

        Typical use: Use this in automated tests when guarding the play youtube candidate returns unavailable failure without raw extractor error behavior against regressions.

        Example: test_play_youtube_candidate_returns_unavailable_failure_without_raw_extractor_error() -> passes without assertion failures when the behavior remains correct.
        """
        candidate = {
            "provider": "youtube",
            "id": "HvFB6bGCElU",
            "youtube_id": "HvFB6bGCElU",
            "cache_id": "youtube_HvFB6bGCElU",
            "query": "Other Song",
            "name": "Other Song",
            "artist": "Artist",
            "album": "-",
            "duration_ms": 200000,
            "url": "https://www.youtube.com/watch?v=HvFB6bGCElU",
            "webpage_url": "https://www.youtube.com/watch?v=HvFB6bGCElU",
        }
        FakeYoutubeDL.responses = [
            RuntimeError("ERROR: [youtube] HvFB6bGCElU: This video is not available")
        ]

        with tempfile.TemporaryDirectory() as tmp:
            with patch("src.tools.online_play.yt_dlp.YoutubeDL", FakeYoutubeDL), \
                patch("src.tools.online_play.start_local_playback") as launch:
                result = online.play_youtube_candidate(candidate, player="mpv", cache_root=Path(tmp))

        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["error_code"], "YOUTUBE_UNAVAILABLE")
        self.assertIn("not available", result["message"])
        self.assertNotIn("ERROR: [youtube]", result["message"])
        self.assertNotIn("HvFB6bGCElU", result["message"])
        launch.assert_not_called()

    def test_play_youtube_fallback_candidate_failure_names_open_audio_attempts(self) -> None:
        """Verifies that play youtube fallback candidate failure names open audio attempts behaves as expected.

        Typical use: Use this in automated tests when guarding the play youtube fallback candidate failure names open audio attempts behavior against regressions.

        Example: test_play_youtube_fallback_candidate_failure_names_open_audio_attempts() -> passes without assertion failures when the behavior remains correct.
        """
        candidate = {
            "provider": "youtube",
            "id": "age",
            "youtube_id": "age",
            "cache_id": "youtube_age",
            "query": "Artist Song",
            "name": "Artist Song",
            "artist": "Artist",
            "album": "-",
            "duration_ms": 200000,
            "url": "https://www.youtube.com/watch?v=age",
            "webpage_url": "https://www.youtube.com/watch?v=age",
            "fallback_provider": "youtube",
            "fallback_reason": "Jamendo returned no credible matches.",
            "source_attempts": [
                {
                    "provider": "jamendo",
                    "status": "no_credible_matches",
                    "candidate_count": 0,
                    "credible_count": 0,
                    "message": "Jamendo returned no credible matches.",
                }
            ],
        }
        FakeYoutubeDL.responses = [RuntimeError("confirm your age")]

        with tempfile.TemporaryDirectory() as tmp:
            with patch("src.tools.online_play.yt_dlp.YoutubeDL", FakeYoutubeDL), \
                patch("src.tools.online_play.start_local_playback") as launch:
                result = online.play_youtube_candidate(candidate, player="mpv", cache_root=Path(tmp))

        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["tool"], "play_online_audio")
        self.assertIn("Jamendo returned no credible matches", result["message"])
        self.assertIn("fell back to YouTube", result["message"])
        self.assertIn("YouTube failed", result["message"])
        self.assertEqual(result["data"]["source_attempts"], candidate["source_attempts"])
        launch.assert_not_called()

    def test_player_confirm_offers_mpv_and_vlc_backend_choices(self) -> None:
        """Verifies that player confirm offers mpv and vlc backend choices behaves as expected.

        Typical use: Use this in automated tests when guarding the player confirm offers mpv and vlc backend choices behavior against regressions.

        Example: test_player_confirm_offers_mpv_and_vlc_backend_choices() -> passes without assertion failures when the behavior remains correct.
        """
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
        self.assertIn("default", choices[0]["description"])
        self.assertIn("manual diagnostic", choices[1]["description"])

    def test_player_confirm_choice_selects_requested_backend(self) -> None:
        """Verifies that player confirm choice selects requested backend behaves as expected.

        Typical use: Use this in automated tests when guarding the player confirm choice selects requested backend behavior against regressions.

        Example: test_player_confirm_choice_selects_requested_backend() -> passes without assertion failures when the behavior remains correct.
        """
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
