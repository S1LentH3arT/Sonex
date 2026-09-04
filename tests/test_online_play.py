"""Tests test online play.

Contains pytest coverage for the test online play behavior.
"""

from __future__ import annotations

import unittest
import tempfile
import urllib.parse
from pathlib import Path
from threading import Barrier, Event
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

    def test_provider_failure_code_accepts_stable_queue_error_code(self) -> None:
        self.assertEqual(
            online._provider_failure_code(RuntimeError("YOUTUBE_QUEUE_BUSY")),
            "youtube_queue_busy",
        )

    def test_managed_runtime_tool_error_maps_stable_codes(self) -> None:
        self.assertEqual(
            online._managed_runtime_tool_error("youtube_po_provider_unavailable"),
            ("YouTube playback is not configured. Open /extension to configure it.", "YOUTUBE_PO_PROVIDER_UNAVAILABLE"),
        )
        self.assertEqual(
            online._managed_runtime_tool_error("provider_error"),
            None,
        )
        self.assertEqual(
            online._friendly_youtube_failure_message("YOUTUBE_QUEUE_BUSY"),
            "Another YouTube request is still running. Try again shortly.",
        )

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

    def test_search_spotify_track_candidates_uses_one_zero_result_fallback(self) -> None:
        responses = [
            {
                "status": "success",
                "data": {"tracks": []},
            },
            {
                "status": "success",
                "data": {
                    "tracks": [
                        {
                            "id": "right",
                            "name": "因为你",
                            "artist": "方大同",
                            "artists": ["方大同"],
                            "album": "未来",
                            "duration_ms": 200000,
                            "uri": "spotify:track:right",
                        },
                        {
                            "id": "right-duplicate",
                            "name": "因为你",
                            "artist": "方大同",
                            "artists": ["方大同"],
                            "album": "未来",
                            "duration_ms": 200000,
                            "uri": "spotify:track:right",
                        },
                    ]
                },
            },
        ]

        with patch("src.tools.spotify_play.spotify_search", side_effect=responses) as spotify_search:
            candidates = online.search_spotify_track_candidates(
                "方大同的因为你",
                limit=3,
                query_variants=(
                    "方大同的因为你",
                    "track:因为你 artist:方大同",
                    "因为你 方大同",
                ),
            )

        self.assertEqual([candidate["uri"] for candidate in candidates], ["spotify:track:right"])
        self.assertEqual(
            [call.kwargs["query"] for call in spotify_search.call_args_list],
            ["方大同的因为你", "track:因为你 artist:方大同"],
        )

    def test_search_spotify_track_candidates_stops_after_rate_limit(self) -> None:
        failure = {"status": "fail", "error_code": "SPOTIFY_RATE_LIMITED", "data": {"retry_after": "30 seconds"}}
        with patch("src.tools.spotify_play.spotify_search", return_value=failure) as spotify_search:
            candidates = online.search_spotify_track_candidates(
                "query",
                limit=5,
                query_variants=("query", "fallback"),
            )

        self.assertEqual(candidates, [])
        spotify_search.assert_called_once_with(query="query", limit=5, types="track")

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

    def test_language_conflict_accepts_original_query_identity(self) -> None:
        candidate = online.normalize_jamendo_track(
            {
                "id": "jam-beautiful",
                "name": "忘了美丽",
                "artist_name": "方大同",
                "album_name": "未来",
                "audio": "https://audio.example/beautiful.mp3",
            },
            query="方大同 忘了美丽",
            playback_metadata={
                "metadata_source": "itunes",
                "original_query": "方大同 忘了美丽",
                "youtube_query": "Khalil Fong Beatiful",
                "name": "Beatiful",
                "artist": "Khalil Fong",
                "album": "Wonderland",
            },
        )

        self.assertIsNotNone(candidate)
        assert candidate is not None
        self.assertTrue(candidate["identity_match"])
        self.assertFalse(candidate["provider_identity_match"])
        self.assertTrue(candidate["query_identity_match"])
        self.assertEqual(candidate["identity_match_source"], "original_query")
        self.assertEqual(candidate["search_query_variant"], "original_query")
        self.assertGreaterEqual(candidate["query_identity_score"], 70)

    def test_cross_language_alias_accepts_provider_localized_identity(self) -> None:
        candidate = online.normalize_jamendo_track(
            {
                "id": "jam-beautiful",
                "name": "忘了美丽",
                "artist_name": "方大同",
                "album_name": "未来",
                "duration": "240",
                "audio": "https://audio.example/beautiful.mp3",
            },
            query="Khalil Fong Beautiful Wonderland",
            playback_metadata={
                "metadata_source": "itunes",
                "name": "Beautiful",
                "artist": "Khalil Fong",
                "album": "Wonderland",
                "duration_ms": 241000,
            },
        )

        self.assertIsNotNone(candidate)
        assert candidate is not None
        self.assertTrue(candidate["identity_match"])
        self.assertEqual(candidate["match_score"]["decision"], "accept")
        self.assertIn("title_alias", candidate["match_score"]["reasons"])
        self.assertIn("artist_alias", candidate["match_score"]["reasons"])

    def test_cross_language_alias_rejects_same_title_different_artist(self) -> None:
        candidate = online.normalize_jamendo_track(
            {
                "id": "jam-wrong",
                "name": "Beautiful",
                "artist_name": "Wrong Artist",
                "audio": "https://audio.example/wrong.mp3",
            },
            query="Khalil Fong Beautiful",
            playback_metadata={
                "metadata_source": "itunes",
                "name": "Beautiful",
                "artist": "Khalil Fong",
            },
        )

        self.assertIsNotNone(candidate)
        assert candidate is not None
        self.assertFalse(candidate["identity_match"])
        self.assertEqual(candidate["match_score"]["decision"], "reject")
        self.assertIn("artist_mismatch", candidate["match_score"]["hard_reject_reasons"])

    def test_review_match_score_is_not_auto_play_credible(self) -> None:
        review = {
            "provider": "jamendo",
            "id": "review",
            "name": "Beautiful",
            "artist": "-",
            "quality_label": "clean_audio_match",
            "similarity_score": 95,
            "match_score": {
                "decision": "review",
                "total_score": 45,
                "reasons": ["title_only_weak_evidence"],
                "hard_reject_reasons": [],
                "components": {"title": 45},
            },
        }

        self.assertEqual(online._credible_online_audio_candidates([review]), [])

    def test_language_conflict_rejects_wrong_original_query_title(self) -> None:
        candidate = online.normalize_jamendo_track(
            {
                "id": "jam-wrong-title",
                "name": "特别的人",
                "artist_name": "方大同",
                "audio": "https://audio.example/wrong-title.mp3",
            },
            query="方大同 忘了美丽",
            playback_metadata={
                "metadata_source": "itunes",
                "original_query": "方大同 忘了美丽",
                "youtube_query": "Khalil Fong Beatiful",
                "name": "Beatiful",
                "artist": "Khalil Fong",
            },
        )

        self.assertIsNotNone(candidate)
        assert candidate is not None
        self.assertFalse(candidate["identity_match"])
        self.assertFalse(candidate["query_identity_match"])

    def test_language_conflict_rejects_wrong_original_query_artist(self) -> None:
        candidate = online.normalize_jamendo_track(
            {
                "id": "jam-wrong-artist",
                "name": "忘了美丽",
                "artist_name": "其他歌手",
                "audio": "https://audio.example/wrong-artist.mp3",
            },
            query="方大同 忘了美丽",
            playback_metadata={
                "metadata_source": "itunes",
                "original_query": "方大同 忘了美丽",
                "youtube_query": "Khalil Fong Beatiful",
                "name": "Beatiful",
                "artist": "Khalil Fong",
            },
        )

        self.assertIsNotNone(candidate)
        assert candidate is not None
        self.assertFalse(candidate["identity_match"])
        self.assertFalse(candidate["query_identity_match"])

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

    def test_jamendo_limits_language_conflict_search_to_two_structured_queries(self) -> None:
        captured_urls: list[str] = []

        def fake_json_get(url: str, **_: object) -> dict[str, object]:
            captured_urls.append(url)
            return {
                "results": [{
                    "id": f"wrong-{len(captured_urls)}",
                    "name": "Beatiful",
                    "artist_name": "Wrong Artist",
                    "audio": f"https://audio.example/wrong-{len(captured_urls)}.mp3",
                }]
            }

        with patch("src.tools.online_play._json_get", side_effect=fake_json_get):
            candidates = online.search_jamendo_audio_candidates(
                "Khalil Fong Beatiful",
                client_id="client-id",
                playback_metadata={
                    "metadata_source": "itunes",
                    "original_query": "方大同 忘了美丽",
                    "youtube_query": "Khalil Fong Beatiful",
                    "name": "Beatiful",
                    "artist": "Khalil Fong",
                    "album": "Wonderland",
                },
            )

        self.assertEqual(candidates, [])
        self.assertEqual(len(captured_urls), 2)
        self.assertTrue(all("search" not in urllib.parse.parse_qs(urllib.parse.urlparse(url).query) for url in captured_urls))

    def test_identity_matching_ignores_display_suffixes_but_preserves_versions(self) -> None:
        target = {"title": "Ｓｏｒｒｙ!", "artist": "Fang-Datong"}

        self.assertTrue(online._identity_matches(target, {"title": "Sorry (Official Audio)", "artist": "Fang Datong feat. Guest"}))
        self.assertTrue(online._identity_matches(target, {"title": "Sorry [2011 Remastered]", "artist": "Fang Datong"}))
        self.assertTrue(online._identity_matches(target, {"title": "Fang Datong - Sorry Official Video", "artist": "Fang Datong"}))
        self.assertTrue(
            online._identity_matches(
                {"title": "愛不來 (feat. MISS KO)", "artist": "方大同"},
                {"title": "爱不来", "artist": "方大同"},
            )
        )
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

    def test_audius_requests_current_api_with_key_query_and_user_agent(self) -> None:
        captured_calls: list[tuple[str, dict[str, str]]] = []

        def fake_json_get(
            url: str,
            *,
            headers: dict[str, str] | None = None,
            **_: object,
        ) -> dict[str, object]:
            captured_calls.append((url, dict(headers or {})))
            return {
                "data": [
                    {
                        "id": "aud-1",
                        "title": "Canonical Song",
                        "user": {"name": "Canonical Artist"},
                    }
                ]
            }

        with patch("src.tools.online_play._json_get", side_effect=fake_json_get):
            candidates = online.search_audius_audio_candidates(
                "Canonical Artist Canonical Song",
                api_key="api-key",
            )

        self.assertEqual(len(captured_calls), 1)
        search_url, headers = captured_calls[0]
        parsed_search = urllib.parse.urlparse(search_url)
        search_params = urllib.parse.parse_qs(parsed_search.query)
        self.assertEqual(
            f"{parsed_search.scheme}://{parsed_search.netloc}{parsed_search.path}",
            "https://api.audius.co/v1/tracks/search",
        )
        self.assertEqual(search_params["api_key"], ["api-key"])
        self.assertEqual(search_params["app_name"], ["Sonex"])
        self.assertEqual(headers["User-Agent"], "Sonex/1.0")
        self.assertEqual(headers["Accept"], "application/json")
        self.assertNotIn("Authorization", headers)

        self.assertEqual(len(candidates), 1)
        parsed_stream = urllib.parse.urlparse(candidates[0]["stream_url"])
        stream_params = urllib.parse.parse_qs(parsed_stream.query)
        self.assertEqual(
            f"{parsed_stream.scheme}://{parsed_stream.netloc}{parsed_stream.path}",
            "https://api.audius.co/v1/tracks/aud-1/stream",
        )
        self.assertEqual(stream_params["api_key"], ["api-key"])
        self.assertEqual(stream_params["app_name"], ["Sonex"])

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

        self.assertEqual([candidate["id"] for candidate in candidates], ["right", "wrong"])
        self.assertEqual(candidates[0]["assessment"]["confidence"], "high")
        self.assertEqual(candidates[1]["assessment"]["confidence"], "medium")
        self.assertTrue(candidates[0]["identity_match"])

    def test_audius_searches_provider_and_original_query_on_language_conflict(self) -> None:
        captured_urls: list[str] = []

        def fake_json_get(url: str, **_: object) -> dict[str, object]:
            captured_urls.append(url)
            if len(captured_urls) == 1:
                return {"data": [{"id": "wrong", "title": "Beatiful", "user": {"name": "Wrong Artist"}}]}
            return {"data": [{"id": "right", "title": "忘了美丽", "user": {"name": "方大同"}}]}

        with patch("src.tools.online_play._json_get", side_effect=fake_json_get):
            candidates = online.search_audius_audio_candidates(
                "Khalil Fong Beatiful",
                api_key="api-key",
                playback_metadata={
                    "metadata_source": "itunes",
                    "original_query": "方大同 忘了美丽",
                    "youtube_query": "Khalil Fong Beatiful",
                    "name": "Beatiful",
                    "artist": "Khalil Fong",
                },
            )

        self.assertEqual([candidate["id"] for candidate in candidates], ["right", "wrong"])
        self.assertEqual(len(captured_urls), 2)
        queries = [
            urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["query"][0]
            for url in captured_urls
        ]
        self.assertEqual(queries, ["Khalil Fong Beatiful", "方大同 忘了美丽"])
        self.assertEqual(candidates[0]["identity_match_source"], "original_query")

    def test_audius_omits_album_and_stops_after_first_high_confidence_match(self) -> None:
        captured_urls: list[str] = []

        def fake_json_get(url: str, **_: object) -> dict[str, object]:
            captured_urls.append(url)
            return {
                "data": [{
                    "id": "right",
                    "title": "Special Person",
                    "user": {"name": "Khalil Fong"},
                }]
            }

        with patch("src.tools.online_play._json_get", side_effect=fake_json_get):
            candidates = online.search_audius_audio_candidates(
                "Khalil Fong Special Person",
                api_key="api-key",
                playback_metadata={
                    "metadata_source": "itunes",
                    "original_query": "方大同 特別的人",
                    "youtube_query": "Khalil Fong Special Person",
                    "name": "Special Person",
                    "artist": "Khalil Fong",
                    "album": "Dangerous World",
                },
            )

        self.assertEqual([candidate["id"] for candidate in candidates], ["right"])
        self.assertEqual(len(captured_urls), 1)
        query = urllib.parse.parse_qs(urllib.parse.urlparse(captured_urls[0]).query)["query"][0]
        self.assertEqual(query, "Khalil Fong Special Person")
        self.assertNotIn("Dangerous World", query)

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

    def test_youtube_searches_both_language_conflict_variants_and_dedupes(self) -> None:
        FakeYoutubeDL.responses = [
            {
                "entries": [
                    {
                        "id": "same",
                        "track": "Beatiful",
                        "artist": "Khalil Fong",
                        "webpage_url": "https://www.youtube.com/watch?v=same",
                    },
                    {
                        "id": "wrong",
                        "track": "Beatiful",
                        "artist": "Wrong Artist",
                        "webpage_url": "https://www.youtube.com/watch?v=wrong",
                    },
                ]
            },
            {
                "entries": [
                    {
                        "id": "same",
                        "track": "忘了美丽",
                        "artist": "方大同",
                        "webpage_url": "https://www.youtube.com/watch?v=same",
                    },
                    {
                        "id": "right",
                        "track": "忘了美丽",
                        "artist": "方大同",
                        "webpage_url": "https://www.youtube.com/watch?v=right",
                    },
                ]
            },
        ]

        with patch("src.tools.online_play.yt_dlp.YoutubeDL", FakeYoutubeDL):
            candidates = online.search_youtube_songs(
                "ignored",
                limit=5,
                playback_metadata={
                    "metadata_source": "itunes",
                    "original_query": "方大同 忘了美丽",
                    "youtube_query": "Khalil Fong Beatiful",
                    "name": "Beatiful",
                    "artist": "Khalil Fong",
                    "album": "Wonderland",
                },
            )

        self.assertEqual(
            [call["target"] for call in FakeYoutubeDL.calls],
            ["ytsearch20:Khalil Fong Beatiful official audio"],
        )
        self.assertEqual([candidate["cache_id"] for candidate in candidates], ["youtube_same"])
        self.assertEqual(candidates[0]["identity_match_source"], "provider_metadata")

    def test_youtube_progressively_expands_to_traditional_title_variant(self) -> None:
        FakeYoutubeDL.responses = [
            {"entries": []},
            {"entries": []},
            {
                "entries": [{
                    "id": "traditional",
                    "title": "方大同 - 愛愛愛",
                    "channel": "Archive",
                    "uploader": "Archive",
                    "webpage_url": "https://www.youtube.com/watch?v=traditional",
                }]
            },
            {"entries": []},
        ]

        with patch("src.tools.online_play.yt_dlp.YoutubeDL", FakeYoutubeDL):
            candidates = online.search_youtube_songs(
                "方大同 爱爱爱",
                playback_metadata={
                    "metadata_source": "itunes",
                    "original_query": "爱爱爱",
                    "youtube_query": "方大同 爱爱爱",
                    "name": "爱爱爱",
                    "artist": "方大同",
                },
            )

        self.assertEqual([candidate["youtube_id"] for candidate in candidates], ["traditional"])
        self.assertEqual(
            [call["target"] for call in FakeYoutubeDL.calls],
            [
                "ytsearch20:方大同 爱爱爱 official audio",
                "ytsearch20:爱爱爱",
                "ytsearch20:方大同 愛愛愛",
            ],
        )

    def test_youtube_accepts_official_channel_match_for_selected_cross_language_metadata(self) -> None:
        official_entry = {
            "id": "official",
            "title": "方大同 小小虫 Official MV",
            "channel": "Warner Music Taiwan",
            "uploader": "Warner Music Taiwan",
            "channel_is_verified": True,
            "webpage_url": "https://www.youtube.com/watch?v=official",
        }
        FakeYoutubeDL.responses = [{"entries": [official_entry]}, {"entries": [official_entry]}]

        with patch("src.tools.online_play.yt_dlp.YoutubeDL", FakeYoutubeDL):
            candidates = online.search_youtube_songs(
                "ignored",
                limit=5,
                playback_metadata={
                    "metadata_source": "itunes",
                    "original_query": "方大同 小小虫",
                    "youtube_query": "Khalil Fong 小小虫",
                    "name": "小小虫",
                    "artist": "Khalil Fong",
                    "album": "Orange Moon",
                },
            )

        self.assertEqual([candidate["youtube_id"] for candidate in candidates], ["official"])
        self.assertEqual(candidates[0]["identity_match_source"], "youtube_title_query")
        self.assertEqual(candidates[0]["source_identity"]["artist"], "")
        self.assertEqual(candidates[0]["channel"], "Warner Music Taiwan")

    def test_youtube_accepts_official_channel_match_for_selected_localized_metadata(self) -> None:
        official_entry = {
            "id": "official",
            "title": "方大同 小小虫 Official MV",
            "channel": "Warner Music Taiwan",
            "uploader": "Warner Music Taiwan",
            "channel_is_verified": True,
            "webpage_url": "https://www.youtube.com/watch?v=official",
        }
        FakeYoutubeDL.responses = [{"entries": [official_entry]}, {"entries": [official_entry]}]

        with patch("src.tools.online_play.yt_dlp.YoutubeDL", FakeYoutubeDL):
            candidates = online.search_youtube_songs(
                "ignored",
                limit=5,
                playback_metadata={
                    "metadata_source": "itunes",
                    "original_query": "方大同 小小虫",
                    "youtube_query": "方大同 小小虫",
                    "name": "小小虫",
                    "artist": "方大同",
                    "album": "橙月",
                },
            )

        self.assertEqual([candidate["youtube_id"] for candidate in candidates], ["official"])
        self.assertEqual(candidates[0]["identity_match_source"], "youtube_title_query")
        self.assertEqual(candidates[0]["source_identity"]["artist"], "")

    def test_youtube_infers_missing_artist_from_traditional_title_without_overwriting_source(self) -> None:
        FakeYoutubeDL.responses = [
            {
                "entries": [{
                    "id": "love",
                    "title": "方大同 - 愛愛愛【動態歌詞Lyrics】",
                    "channel": "Meteor Music",
                    "uploader": "Meteor Music",
                    "duration": 260,
                    "webpage_url": "https://www.youtube.com/watch?v=love",
                }]
            },
            {"entries": []},
            {"entries": []},
        ]

        with patch("src.tools.online_play.yt_dlp.YoutubeDL", FakeYoutubeDL):
            candidates = online.search_youtube_songs(
                "方大同 爱爱爱",
                playback_metadata={
                    "metadata_source": "itunes",
                    "original_query": "爱爱爱",
                    "youtube_query": "方大同 爱爱爱",
                    "name": "爱爱爱",
                    "artist": "方大同",
                    "album": "爱爱爱",
                    "duration_ms": 259000,
                },
            )

        self.assertEqual([candidate["youtube_id"] for candidate in candidates], ["love"])
        candidate = candidates[0]
        self.assertEqual(candidate["name"], "爱爱爱")
        self.assertEqual(candidate["artist"], "方大同")
        self.assertEqual(
            candidate["source_identity"],
            {
                "title": "方大同 - 愛愛愛【動態歌詞Lyrics】",
                "artist": "",
                "album": "",
            },
        )
        self.assertEqual(
            candidate["inferred_identity"],
            {
                "title": "爱爱爱",
                "artist": "方大同",
                "album": "爱爱爱",
                "provenance": "youtube_title",
            },
        )
        self.assertEqual(candidate["identity_match_source"], "youtube_title_query")
        self.assertEqual(candidate["assessment"]["confidence"], "medium")
        self.assertIn("traditional_simplified_normalized", candidate["assessment"]["evidence"])

    def test_youtube_infers_confirmed_identity_for_reported_regression_titles(self) -> None:
        cases = (
            ("公园", "方大同 - 公園"),
            ("爱爱爱", "方大同 - 愛愛愛"),
            ("三人游", "方大同 - 三人遊"),
        )

        for title, source_title in cases:
            with self.subTest(title=title):
                candidate = online._normalize_youtube_info(
                    f"方大同 {title}",
                    {
                        "id": title,
                        "title": source_title,
                        "channel": "Archive Channel",
                        "webpage_url": f"https://www.youtube.com/watch?v={title}",
                    },
                    playback_metadata={
                        "metadata_source": "itunes",
                        "name": title,
                        "artist": "方大同",
                    },
                )

                self.assertEqual(candidate["source_identity"]["title"], source_title)
                self.assertEqual(candidate["source_identity"]["artist"], "")
                self.assertEqual(candidate["inferred_identity"]["title"], title)
                self.assertEqual(candidate["inferred_identity"]["artist"], "方大同")
                self.assertEqual(candidate["assessment"]["confidence"], "medium")

    def test_youtube_requires_official_channel_for_title_inference_to_be_high_confidence(self) -> None:
        metadata = {
            "metadata_source": "itunes",
            "name": "Canonical Song",
            "artist": "Canonical Artist",
        }
        archive = online._normalize_youtube_info(
            "Canonical Artist Canonical Song",
            {
                "id": "archive",
                "title": "Canonical Artist - Canonical Song",
                "channel": "Archive Uploads",
            },
            playback_metadata=metadata,
        )
        topic = online._normalize_youtube_info(
            "Canonical Artist Canonical Song",
            {
                "id": "topic",
                "title": "Canonical Artist - Canonical Song",
                "channel": "Canonical Artist - Topic",
            },
            playback_metadata=metadata,
        )

        self.assertEqual(archive["assessment"]["confidence"], "medium")
        self.assertEqual(topic["assessment"]["confidence"], "high")

    def test_youtube_verified_channel_does_not_override_noisy_or_live_version(self) -> None:
        metadata = {
            "metadata_source": "itunes",
            "name": "爱爱爱",
            "artist": "方大同",
        }
        noisy = online._normalize_youtube_info(
            "方大同 爱爱爱 official audio",
            {
                "id": "tv-show",
                "title": "超经典 方大同《爱爱爱》纯享《异口同声》第2期【浙江卫视官方HD】",
                "channel": "浙江卫视音乐频道 ZJSTV Music Channel",
                "channel_is_verified": True,
            },
            playback_metadata=metadata,
        )
        live = online._normalize_youtube_info(
            "方大同 特別的人 official audio",
            {
                "id": "concert",
                "title": "《特別的人》方大同世界巡迴演唱會深圳站",
                "channel": "方大同 Official",
                "channel_is_verified": True,
            },
            playback_metadata={
                "metadata_source": "itunes",
                "name": "特別的人",
                "artist": "方大同",
            },
        )
        venue = online._normalize_youtube_info(
            "方大同 爱爱爱 official audio",
            {
                "id": "venue",
                "title": "方大同-爱爱爱@北京蜂巢剧场",
                "channel": "Archive Uploads",
            },
            playback_metadata=metadata,
        )

        self.assertEqual(noisy["assessment"]["confidence"], "low")
        self.assertIn("unrequested_version", noisy["assessment"]["conflicts"])
        self.assertEqual(live["assessment"]["confidence"], "low")
        self.assertIn("unrequested_version", live["assessment"]["conflicts"])
        self.assertEqual(venue["assessment"]["confidence"], "low")
        self.assertIn("unrequested_version", venue["assessment"]["conflicts"])

    def test_youtube_starts_with_official_audio_query_and_stops_on_high_confidence(self) -> None:
        FakeYoutubeDL.responses = [{
            "entries": [{
                "id": "official",
                "track": "Canonical Song",
                "artist": "Canonical Artist",
                "channel": "Canonical Artist - Topic",
                "webpage_url": "https://www.youtube.com/watch?v=official",
            }]
        }]

        with patch("src.tools.online_play.yt_dlp.YoutubeDL", FakeYoutubeDL):
            candidates = online.search_youtube_songs(
                "Canonical Artist Canonical Song",
                playback_metadata={
                    "metadata_source": "itunes",
                    "name": "Canonical Song",
                    "artist": "Canonical Artist",
                    "album": "Canonical Album",
                },
            )

        self.assertEqual([candidate["youtube_id"] for candidate in candidates], ["official"])
        self.assertEqual(
            [call["target"] for call in FakeYoutubeDL.calls],
            ["ytsearch20:Canonical Artist Canonical Song official audio"],
        )

    def test_youtube_returns_title_only_match_for_user_review(self) -> None:
        FakeYoutubeDL.responses = [
            {
                "entries": [{
                    "id": "review",
                    "title": "Canonical Song",
                    "channel": "Archive Channel",
                    "uploader": "Archive Channel",
                    "duration": 201,
                    "webpage_url": "https://www.youtube.com/watch?v=review",
                }]
            },
            {"entries": []},
        ]

        with patch("src.tools.online_play.yt_dlp.YoutubeDL", FakeYoutubeDL):
            candidates = online.search_youtube_songs(
                "Canonical Artist Canonical Song",
                playback_metadata={
                    "metadata_source": "itunes",
                    "name": "Canonical Song",
                    "artist": "Canonical Artist",
                    "duration_ms": 200000,
                },
            )

        self.assertEqual([candidate["youtube_id"] for candidate in candidates], ["review"])
        self.assertFalse(candidates[0]["identity_match"])
        self.assertEqual(candidates[0]["assessment"]["confidence"], "medium")
        self.assertIn("title_only_weak_evidence", candidates[0]["assessment"]["evidence"])

    def test_search_youtube_filters_low_confidence_even_when_legacy_identity_matches(self) -> None:
        entry = {"id": "legacy-match", "title": "Legacy Match"}
        FakeYoutubeDL.responses = [
            {"entries": [entry]},
            {"entries": [entry]},
        ]
        low_candidate = {
            "provider": "youtube",
            "cache_id": "youtube_legacy-match",
            "identity_match": True,
            "assessment": {
                "confidence": "low",
                "evidence": [],
                "conflicts": ["artist_mismatch"],
            },
        }

        with patch("src.tools.online_play.yt_dlp.YoutubeDL", FakeYoutubeDL), \
             patch("src.tools.online_play._should_keep_candidate", return_value=True), \
             patch("src.tools.online_play._normalize_youtube_info", return_value=low_candidate), \
             patch("src.tools.online_play._cached_audio_item", return_value=None):
            with self.assertRaises(online.AudioIdentityMismatch):
                online.search_youtube_songs(
                    "Canonical Artist Canonical Song",
                    playback_metadata={
                        "name": "Canonical Song",
                        "artist": "Canonical Artist",
                        "youtube_query": "Canonical Artist Canonical Song",
                    },
                )

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
                    "provider": "youtube",
                    "status": "success",
                    "candidate_count": 1,
                    "credible_count": 1,
                    "message": "YouTube returned 1 credible match.",
                },
            ],
        )
        self.assertNotIn("fallback_provider", candidates[0])

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
        self.assertIn("YouTube failed", message)
        self.assertIn("Selected YouTube result is not available", message)
        self.assertNotIn("ERROR: [youtube]", message)
        self.assertNotIn("wYB9Vu282ZU", message)

    def test_resolve_online_audio_cools_down_youtube_after_rate_limit(self) -> None:
        config = online.OnlineAudioConfig()
        online._youtube_search_cooldown_until = 0.0
        try:
            with patch(
                "src.tools.online_play.search_youtube_songs",
                side_effect=RuntimeError("HTTP Error 429: Too Many Requests"),
            ):
                with self.assertRaisesRegex(RuntimeError, "temporarily unavailable"):
                    online.resolve_online_audio_candidates("Artist Song", config=config)

            with patch("src.tools.online_play.search_youtube_songs") as youtube_search:
                with self.assertRaisesRegex(RuntimeError, "cooling down"):
                    online.resolve_online_audio_candidates("Artist Song", config=config)
            youtube_search.assert_not_called()
        finally:
            online._youtube_search_cooldown_until = 0.0

    def test_resolve_online_audio_failure_exposes_structured_trace(self) -> None:
        with patch(
            "src.tools.online_play.search_youtube_songs",
            side_effect=online.AudioIdentityMismatch("youtube", 2),
        ):
            with self.assertRaises(RuntimeError) as caught:
                online.resolve_online_audio_candidates(
                    "Canonical Artist Canonical Song",
                    config=online.OnlineAudioConfig(),
                )

        error = caught.exception
        self.assertEqual(error.search_trace["final_state"], "no_candidate")
        self.assertEqual(error.search_trace["confidence_counts"]["high"], 0)
        self.assertEqual(error.source_attempts[0]["provider"], "youtube")
        self.assertEqual(error.source_attempts[-1]["provider"], "audius")
        self.assertIn("youtube", error.search_trace["provider_elapsed_ms"])

    def test_resolve_online_audio_reports_youtube_identity_mismatch(self) -> None:
        wrong = {
            "id": "wrong",
            "track": "Sorry",
            "artist": "Wrong Artist",
            "webpage_url": "https://www.youtube.com/watch?v=wrong",
        }
        FakeYoutubeDL.responses = [
            {"entries": [wrong]},
            {"entries": [wrong]},
        ]

        with patch("src.tools.online_play.yt_dlp.YoutubeDL", FakeYoutubeDL):
            with self.assertRaisesRegex(RuntimeError, "YouTube rejected 2 identity mismatches"):
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

        jamendo_search.assert_not_called()
        audius_search.assert_not_called()
        youtube_search.assert_called_once()
        self.assertEqual(candidates[0]["cache_id"], "youtube_yt-1")
        self.assertNotIn("fallback_provider", candidates[0])

    def test_resolve_online_audio_unifies_configured_provider_candidates(self) -> None:
        config = online.OnlineAudioConfig(jamendo_client_id="jamendo-id", audius_api_key=None)
        jamendo_candidate = {
            "provider": "jamendo",
            "cache_id": "jamendo_jam-1",
            "id": "jam-1",
            "name": "Canonical Song",
            "artist": "Canonical Artist",
            "quality_label": "official_original",
            "similarity_score": 100,
            "identity_match": True,
            "match_score": {
                "decision": "accept",
                "total_score": 85,
                "reasons": ["title_exact", "artist_exact"],
                "hard_reject_reasons": [],
                "components": {"title": 45, "artist": 40},
            },
        }
        youtube_candidate = {
            "provider": "youtube",
            "cache_id": "youtube_yt-1",
            "id": "yt-1",
            "name": "Canonical Song",
            "artist": "Canonical Artist",
            "quality_label": "official_original",
            "similarity_score": 96,
            "identity_match": True,
            "assessment": {"confidence": "high", "evidence": [], "conflicts": []},
        }

        with patch(
            "src.tools.online_play.search_jamendo_audio_candidates",
            return_value=[jamendo_candidate],
        ) as jamendo_search, patch(
            "src.tools.online_play.search_youtube_songs",
            return_value=[youtube_candidate],
        ) as youtube_search:
            candidates = online.resolve_online_audio_candidates(
                "Canonical Artist Canonical Song",
                config=config,
            )

        jamendo_search.assert_not_called()
        youtube_search.assert_called_once()
        self.assertEqual(
            [candidate["cache_id"] for candidate in candidates],
            ["youtube_yt-1"],
        )
        self.assertTrue(all(candidate.get("source_attempts") for candidate in candidates))
        trace = candidates[0]["search_trace"]
        self.assertEqual(trace["id"], candidates[0]["search_trace_id"])
        self.assertEqual(trace["final_state"], "candidate_found")
        self.assertEqual(
            trace["provider_capabilities"],
            {
                "jamendo": "configured",
                "audius": "not_configured",
                "youtube": "configured",
            },
        )
        self.assertEqual(trace["confidence_counts"]["high"], 1)

    def test_resolve_online_audio_skips_youtube_when_open_audio_has_high_confidence(self) -> None:
        config = online.OnlineAudioConfig(jamendo_client_id="jamendo-id", audius_api_key="audius-key")
        jamendo_candidate = {
            "provider": "jamendo",
            "cache_id": "jamendo_high",
            "similarity_score": 100,
            "quality_label": "clean_audio_match",
            "assessment": {"confidence": "high", "evidence": [], "conflicts": []},
            "match_score": {
                "decision": "accept",
                "total_score": 85,
                "reasons": ["title_exact", "artist_exact"],
                "hard_reject_reasons": [],
            },
        }

        with patch("src.tools.online_play.search_jamendo_audio_candidates", return_value=[jamendo_candidate]), \
             patch("src.tools.online_play.search_audius_audio_candidates", return_value=[]), \
             patch("src.tools.online_play.search_youtube_songs", return_value=[]) as youtube_search:
            candidates = online.resolve_online_audio_candidates("Canonical Artist Canonical Song", config=config)

        youtube_search.assert_called_once()
        self.assertEqual([candidate["cache_id"] for candidate in candidates], ["jamendo_high"])
        self.assertEqual(candidates[0]["source_attempts"][0]["provider"], "youtube")
        self.assertEqual(candidates[0]["source_attempts"][1]["provider"], "jamendo")

    def test_resolve_online_audio_runs_open_stage_before_youtube_with_split_budget(self) -> None:
        config = online.OnlineAudioConfig(jamendo_client_id="jamendo-id", audius_api_key="audius-key")
        medium = {
            "provider": "audius",
            "cache_id": "audius_review",
            "similarity_score": 90,
            "quality_label": "clean_audio_match",
            "assessment": {"confidence": "medium", "evidence": ["audius_title_only"], "conflicts": []},
        }
        youtube = {
            "provider": "youtube",
            "cache_id": "youtube_high",
            "similarity_score": 95,
            "quality_label": "official_original",
            "assessment": {"confidence": "high", "evidence": ["youtube_official_channel"], "conflicts": []},
        }
        calls: list[tuple[tuple[str, ...], float]] = []

        def fake_run(
            jobs: dict[str, object],
            *,
            timeout: float,
        ) -> tuple[dict[str, list[dict[str, object]]], dict[str, Exception]]:
            calls.append((tuple(jobs), timeout))
            if "youtube" in jobs:
                return {"youtube": []}, {}
            return {"jamendo": [], "audius": [medium]}, {}

        with patch("src.tools.online_play._run_online_provider_searches", side_effect=fake_run):
            candidates = online.resolve_online_audio_candidates("Canonical Artist Canonical Song", config=config)

        self.assertEqual([providers for providers, _ in calls], [("youtube",), ("jamendo", "audius")])
        self.assertGreater(calls[0][1], 0.0)
        self.assertLessEqual(calls[0][1], 8.0)
        self.assertEqual(calls[1][1], 4.0)
        self.assertEqual([candidate["cache_id"] for candidate in candidates], ["audius_review"])

    def test_provider_searches_start_concurrently(self) -> None:
        barrier = Barrier(2)

        def search(provider: str) -> list[dict]:
            barrier.wait(timeout=1)
            return [{"provider": provider}]

        results, errors = online._run_online_provider_searches(
            {
                "jamendo": lambda: search("jamendo"),
                "youtube": lambda: search("youtube"),
            },
            timeout=1,
        )

        self.assertEqual(errors, {})
        self.assertEqual(results["jamendo"], [{"provider": "jamendo"}])
        self.assertEqual(results["youtube"], [{"provider": "youtube"}])

    def test_provider_search_timeout_returns_without_waiting_for_worker(self) -> None:
        release = Event()

        def blocked_search() -> list[dict]:
            release.wait(timeout=1)
            return []

        try:
            results, errors = online._run_online_provider_searches(
                {"youtube": blocked_search},
                timeout=0.01,
            )
        finally:
            release.set()

        self.assertEqual(results, {})
        self.assertIsInstance(errors["youtube"], TimeoutError)

    def test_resolve_online_audio_returns_provider_aware_youtube_fallback_with_attempt_trace(self) -> None:
        official_entry = {
            "id": "official",
            "title": "方大同 小小虫 Official MV",
            "channel": "Warner Music Taiwan",
            "uploader": "Warner Music Taiwan",
            "channel_is_verified": True,
            "webpage_url": "https://www.youtube.com/watch?v=official",
        }
        FakeYoutubeDL.responses = [{"entries": [official_entry]}, {"entries": [official_entry]}]
        config = online.OnlineAudioConfig(jamendo_client_id="jamendo-id", audius_api_key=None)

        with patch("src.tools.online_play.search_jamendo_audio_candidates", return_value=[]), \
             patch("src.tools.online_play.yt_dlp.YoutubeDL", FakeYoutubeDL):
            candidates = online.resolve_online_audio_candidates(
                "方大同 小小虫",
                config=config,
                playback_metadata={
                    "metadata_source": "itunes",
                    "original_query": "方大同 小小虫",
                    "youtube_query": "Khalil Fong 小小虫",
                    "name": "小小虫",
                    "artist": "Khalil Fong",
                    "album": "Orange Moon",
                },
            )

        self.assertEqual([candidate["youtube_id"] for candidate in candidates], ["official"])
        self.assertEqual(candidates[0]["identity_match_source"], "youtube_title_query")
        self.assertNotIn("fallback_provider", candidates[0])

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
        self.assertNotIn("fallback_provider", candidates[0])

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
            "assessment": {"confidence": "medium", "evidence": [], "conflicts": []},
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

        attempt = next(
            item for item in candidates[0]["source_attempts"] if item["provider"] == "jamendo"
        )
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
            "assessment": {"confidence": "medium", "evidence": [], "conflicts": []},
        }

        with patch("src.tools.online_play.search_jamendo_audio_candidates", side_effect=RuntimeError("token secret=abc123 failed")), \
             patch("src.tools.online_play.search_youtube_songs", return_value=[youtube_candidate]):
            candidates = online.resolve_online_audio_candidates("Artist Song", config=config)

        self.assertEqual(candidates[0]["cache_id"], "youtube_yt-1")
        self.assertEqual(candidates[0]["source_attempts"][1]["status"], "provider_error")
        self.assertIn("Jamendo failed:", candidates[0]["source_attempts"][1]["message"])
        self.assertNotIn("secret=abc123", candidates[0]["source_attempts"][1]["message"])

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

    def test_rank_online_audio_candidates_prefers_high_confidence_over_similarity(self) -> None:
        high = {
            "provider": "youtube",
            "cache_id": "youtube_high",
            "similarity_score": 80,
            "quality_label": "clean_audio_match",
            "assessment": {"confidence": "high", "evidence": [], "conflicts": []},
        }
        medium = {
            "provider": "youtube",
            "cache_id": "youtube_medium",
            "similarity_score": 100,
            "quality_label": "official_original",
            "assessment": {"confidence": "medium", "evidence": [], "conflicts": []},
        }

        ranked = online.rank_online_audio_candidates("Canonical Song", [medium, high])

        self.assertEqual(
            [candidate["cache_id"] for candidate in ranked],
            ["youtube_high", "youtube_medium"],
        )

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
        self.assertEqual(FakeYoutubeDL.calls[0]["target"], "ytsearch20:Song Artist")
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
        self.assertEqual(FakeYoutubeDL.calls[0]["target"], "ytsearch20:Canonical Artist Canonical Song official audio")
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

        self.assertEqual([candidate["youtube_id"] for candidate in candidates], ["official"])
        self.assertEqual(candidates[0]["variant_type"], "official_original")
        self.assertEqual(candidates[0]["quality_label"], "official_original")
        self.assertGreater(candidates[0]["similarity_score"], 0)
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

        self.assertEqual([candidate["youtube_id"] for candidate in candidates], ["clean"])
        self.assertEqual(candidates[0]["quality_label"], "clean_audio_match")

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

    def test_search_youtube_songs_continues_after_result_extraction_error(self) -> None:
        class ErrorAwareYoutubeDL(FakeYoutubeDL):
            def extract_info(self, target: str, download: bool = False) -> dict:
                if not self.options.get("ignoreerrors"):
                    raise DownloadError("ERROR: [youtube] blocked: This video is not available")
                return {
                    "entries": [
                        None,
                        {
                            "id": "playable",
                            "title": "Song Artist Official Audio",
                            "artist": "Song Artist",
                            "channel": "Song Artist",
                            "availability": "public",
                            "webpage_url": "https://www.youtube.com/watch?v=playable",
                        },
                    ]
                }

        with patch("src.tools.online_play.yt_dlp.YoutubeDL", ErrorAwareYoutubeDL):
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

    def test_download_youtube_candidate_reuses_original_query_identity_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "audio" / "youtube_abc123.webm"
            audio.parent.mkdir(parents=True)
            audio.write_bytes(b"verified")
            upsert_cached_song(
                {
                    "provider": "youtube",
                    "cache_id": "youtube_abc123",
                    "youtube_id": "abc123",
                    "name": "忘了美丽",
                    "artist": "方大同",
                    "target_identity": {"title": "Beatiful", "artist": "Khalil Fong", "album": "Wonderland"},
                    "source_identity": {"title": "忘了美丽", "artist": "方大同", "album": "未来"},
                    "identity_match": True,
                    "identity_match_source": "original_query",
                    "audio_path": str(audio),
                    "audio_ext": "webm",
                },
                cache_root=root,
            )

            item = online.download_youtube_candidate(
                {
                    "provider": "youtube",
                    "cache_id": "youtube_abc123",
                    "target_identity": {"title": "Beatiful", "artist": "Khalil Fong", "album": "Wonderland"},
                    "source_identity": {"title": "忘了美丽", "artist": "方大同", "album": "未来"},
                    "query": "方大同 忘了美丽",
                    "original_query": "方大同 忘了美丽",
                    "youtube_query": "Khalil Fong Beatiful",
                    "name": "Beatiful",
                    "artist": "Khalil Fong",
                    "metadata_source": "itunes",
                    "url": "https://www.youtube.com/watch?v=abc123",
                },
                cache_root=root,
            )

            self.assertEqual(item["audio_path"], str(audio))
            self.assertEqual(FakeYoutubeDL.calls, [])

    def test_download_youtube_candidate_accepts_provider_aware_channel_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            FakeYoutubeDL.responses = [{
                "id": "official",
                "title": "方大同 小小虫 Official MV",
                "channel": "Warner Music Taiwan",
                "uploader": "Warner Music Taiwan",
                "webpage_url": "https://www.youtube.com/watch?v=official",
                "ext": "m4a",
            }]

            with patch("src.tools.online_play.yt_dlp.YoutubeDL", FakeYoutubeDL):
                item = online.download_youtube_candidate(
                    {
                        "provider": "youtube",
                        "cache_id": "youtube_official",
                        "youtube_id": "official",
                        "target_identity": {"title": "小小虫", "artist": "Khalil Fong", "album": "Orange Moon"},
                        "source_identity": {"title": "方大同 小小虫 Official MV", "artist": "", "album": ""},
                        "identity_match": True,
                        "identity_match_source": "youtube_title_query",
                        "query_identity_match": True,
                        "query": "方大同 小小虫",
                        "original_query": "方大同 小小虫",
                        "youtube_query": "Khalil Fong 小小虫",
                        "name": "小小虫",
                        "artist": "Khalil Fong",
                        "album": "Orange Moon",
                        "metadata_source": "itunes",
                        "url": "https://www.youtube.com/watch?v=official",
                    },
                    cache_root=root,
                )

            self.assertEqual(item["identity_match_source"], "youtube_title_query")
            self.assertEqual(item["source_identity"]["artist"], "")
            self.assertEqual(Path(item["audio_path"]).suffix, ".m4a")

    def test_download_youtube_candidate_accepts_user_verified_video_container(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate = {
                "provider": "youtube",
                "id": "review",
                "youtube_id": "review",
                "cache_id": "youtube_review",
                "query": "Canonical Artist Canonical Song",
                "original_query": "Canonical Song",
                "youtube_query": "Canonical Artist Canonical Song",
                "name": "Canonical Song",
                "artist": "Canonical Artist",
                "target_identity": {
                    "title": "Canonical Song",
                    "artist": "Canonical Artist",
                    "album": "Canonical Album",
                },
                "source_identity": {
                    "title": "Canonical Song",
                    "artist": "",
                    "album": "",
                },
                "assessment": {
                    "confidence": "medium",
                    "evidence": ["title_only_weak_evidence"],
                    "conflicts": [],
                },
                "user_verified": True,
                "user_verified_at": 123.0,
                "webpage_url": "https://www.youtube.com/watch?v=review",
            }
            FakeYoutubeDL.responses = [{
                "id": "review",
                "title": "Canonical Song",
                "uploader": "Archive Channel",
                "duration": 201,
                "formats": [{
                    "url": "https://media.example/video.mp4",
                    "acodec": "mp4a",
                    "vcodec": "avc1",
                }],
                "webpage_url": "https://www.youtube.com/watch?v=review",
                "ext": "mp4",
            }]

            with patch("src.tools.online_play.yt_dlp.YoutubeDL", FakeYoutubeDL):
                item = online.download_youtube_candidate(candidate, cache_root=root)

            self.assertTrue(item["identity_match"])
            self.assertTrue(item["user_verified"])
            self.assertEqual(item["media"]["kind"], "video_container")
            self.assertTrue(item["media"]["playable"])
            self.assertTrue(item["media_fingerprint"])

    def test_download_youtube_candidate_ignores_stale_dual_identity_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "audio" / "youtube_abc123.webm"
            audio.parent.mkdir(parents=True)
            audio.write_bytes(b"stale")
            upsert_cached_song(
                {
                    "provider": "youtube",
                    "cache_id": "youtube_abc123",
                    "youtube_id": "abc123",
                    "name": "特别的人",
                    "artist": "方大同",
                    "target_identity": {"title": "Beatiful", "artist": "Khalil Fong", "album": "Wonderland"},
                    "source_identity": {"title": "特别的人", "artist": "方大同", "album": ""},
                    "identity_match": False,
                    "audio_path": str(audio),
                    "audio_ext": "webm",
                },
                cache_root=root,
            )
            FakeYoutubeDL.responses = [{
                "id": "abc123",
                "track": "忘了美丽",
                "artist": "方大同",
                "webpage_url": "https://www.youtube.com/watch?v=abc123",
                "ext": "m4a",
            }]

            with patch("src.tools.online_play.yt_dlp.YoutubeDL", FakeYoutubeDL):
                item = online.download_youtube_candidate(
                    {
                        "provider": "youtube",
                        "cache_id": "youtube_abc123",
                        "target_identity": {"title": "Beatiful", "artist": "Khalil Fong", "album": "Wonderland"},
                        "source_identity": {"title": "忘了美丽", "artist": "方大同", "album": "未来"},
                        "query": "方大同 忘了美丽",
                        "original_query": "方大同 忘了美丽",
                        "youtube_query": "Khalil Fong Beatiful",
                        "name": "Beatiful",
                        "artist": "Khalil Fong",
                        "metadata_source": "itunes",
                        "url": "https://www.youtube.com/watch?v=abc123",
                    },
                    cache_root=root,
                )

            self.assertEqual(len(FakeYoutubeDL.calls), 1)
            self.assertEqual(Path(item["audio_path"]).suffix, ".m4a")
            self.assertEqual(item["identity_match_source"], "original_query")

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

    def test_play_youtube_song_retries_candidate_failure_but_stops_after_two_attempts(self) -> None:
        candidates = [
            {"provider": "youtube", "cache_id": "youtube_first"},
            {"provider": "youtube", "cache_id": "youtube_second"},
            {"provider": "youtube", "cache_id": "youtube_third"},
        ]
        unavailable = ToolResult.fail(
            tool="play_youtube_song",
            message="Selected YouTube result is not available.",
            error_code="YOUTUBE_UNAVAILABLE",
        ).to_dict()
        success = ToolResult.success(
            tool="play_youtube_song",
            message="playing",
            data={"cache_id": "youtube_second"},
        ).to_dict()

        with patch("src.tools.online_play.online_audio_configured", return_value=False), \
             patch("src.tools.online_play.search_youtube_songs", return_value=candidates), \
             patch("src.tools.online_play.play_youtube_candidate", side_effect=[unavailable, success]) as play:
            result = online.play_youtube_song(
                "Fang Datong Sorry",
                playback_metadata={"name": "Sorry", "artist": "Fang Datong"},
            )

        self.assertEqual(play.call_count, 2)
        self.assertEqual(result["status"], "success")

    def test_play_youtube_song_cools_down_and_does_not_retry_bot_challenge(self) -> None:
        candidates = [
            {"provider": "youtube", "cache_id": "youtube_first"},
            {"provider": "youtube", "cache_id": "youtube_second"},
        ]
        blocked = ToolResult.fail(
            tool="play_youtube_song",
            message="Sign in to confirm you are not a bot.",
            error_code="YOUTUBE_TEMPORARILY_UNAVAILABLE",
        ).to_dict()
        online._youtube_search_cooldown_until = 0.0
        try:
            with patch("src.tools.online_play.online_audio_configured", return_value=False), \
                 patch("src.tools.online_play.search_youtube_songs", return_value=candidates), \
                 patch("src.tools.online_play.play_youtube_candidate", return_value=blocked) as play:
                result = online.play_youtube_song(
                    "Fang Datong Sorry",
                    playback_metadata={"name": "Sorry", "artist": "Fang Datong"},
                )

            self.assertEqual(play.call_count, 1)
            self.assertEqual(result["error_code"], "YOUTUBE_TEMPORARILY_UNAVAILABLE")
            self.assertGreater(online._youtube_search_cooldown_until, 0.0)
        finally:
            online._youtube_search_cooldown_until = 0.0

    def test_play_youtube_song_does_not_auto_play_medium_confidence_candidate(self) -> None:
        candidate = {
            "provider": "youtube",
            "cache_id": "youtube_review",
            "assessment": {
                "confidence": "medium",
                "evidence": ["title_only_weak_evidence"],
                "conflicts": [],
            },
        }

        with patch("src.tools.online_play.online_audio_configured", return_value=False), \
             patch("src.tools.online_play.search_youtube_songs", return_value=[candidate]), \
             patch("src.tools.online_play.play_youtube_candidate") as play:
            result = online.play_youtube_song("Canonical Song")

        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["error_code"], "ONLINE_AUDIO_REVIEW_REQUIRED")
        self.assertEqual(result["data"]["candidates"], [candidate])
        play.assert_not_called()

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
                        "title": "Artist Name - Song Title",
                        "artist": "Artist Name",
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
            with patch("src.tools.online_play.online_audio_configured", return_value=False), \
                patch("src.tools.online_play.yt_dlp.YoutubeDL", FakeYoutubeDL), \
                patch("src.tools.cover_sources.lookup_cover_art_url", return_value=None), \
                patch("src.tools.online_play.check_player", return_value=True), \
                patch("src.tools.online_play.is_player_allowed", return_value=True), \
                patch("src.tools.online_play.start_local_playback", side_effect=_playback_success):
                result = online.play_youtube_song(
                    "Song Artist",
                    player="mpv",
                    cache_root=Path(tmp),
                    playback_metadata={
                        "name": "Song Title",
                        "title": "Song Title",
                        "artist": "Artist Name",
                        "album": "Album Name",
                        "duration_ms": 185000,
                    },
                )

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
            with patch("src.tools.online_play.online_audio_configured", return_value=False), \
                patch("src.tools.spotify_play.spotify_search") as spotify_search, \
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
        self.assertEqual(FakeYoutubeDL.calls[0]["target"], "ytsearch20:Canonical Artist Canonical Song official audio")
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
            with patch("src.tools.online_play.online_audio_configured", return_value=False), \
                patch("src.tools.spotify_play.spotify_search") as spotify_search, \
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

    def test_play_youtube_song_raw_query_requires_candidate_review(self) -> None:
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
            with patch("src.tools.online_play.online_audio_configured", return_value=False), \
                patch("src.tools.spotify_play.spotify_search") as spotify_search, \
                patch("src.tools.online_play.yt_dlp.YoutubeDL", FakeYoutubeDL), \
                patch("src.tools.cover_sources.lookup_cover_art_url", return_value=None), \
                patch("src.tools.online_play.check_player", return_value=True), \
                patch("src.tools.online_play.is_player_allowed", return_value=True), \
                patch("src.tools.online_play.start_local_playback", side_effect=_playback_success):
                result = online.play_youtube_song("raw query", player="mpv", cache_root=Path(tmp))

        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["error_code"], "ONLINE_AUDIO_REVIEW_REQUIRED")
        spotify_search.assert_not_called()
        self.assertEqual(FakeYoutubeDL.calls[0]["target"], "ytsearch8:raw query")
        self.assertEqual(len(FakeYoutubeDL.calls), 1)

    def test_play_youtube_song_falls_back_to_uploader_and_best_audio_format(self) -> None:
        """Verifies that play youtube song falls back to uploader and best audio format behaves as expected.

        Typical use: Use this in automated tests when guarding the play youtube song falls back to uploader and best audio format behavior against regressions.

        Example: test_play_youtube_song_falls_back_to_uploader_and_best_audio_format() -> passes without assertion failures when the behavior remains correct.
        """
        FakeYoutubeDL.responses = [
            {
                "entries": [{
                    "id": "def456",
                    "title": "Uploader Artist - Fallback Song",
                    "artist": "Uploader Artist",
                }]
            },
            {
                "id": "def456",
                "title": "Uploader Artist - Fallback Song",
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
            with patch("src.tools.online_play.online_audio_configured", return_value=False), \
                patch("src.tools.online_play.yt_dlp.YoutubeDL", FakeYoutubeDL), \
                patch("src.tools.cover_sources.lookup_cover_art_url", return_value=None), \
                patch("src.tools.online_play.check_player", return_value=True), \
                patch("src.tools.online_play.is_player_allowed", return_value=True), \
                patch("src.tools.online_play.start_local_playback", side_effect=_playback_success):
                result = online.play_youtube_song(
                    "Fallback Song",
                    player="mpv",
                    cache_root=Path(tmp),
                    playback_metadata={
                        "name": "Fallback Song",
                        "title": "Fallback Song",
                        "artist": "Uploader Artist",
                        "duration_ms": 12400,
                    },
                )

            data = result["data"]
            self.assertEqual(data["url"], "https://www.youtube.com/watch?v=def456")
            self.assertEqual(data["artist"], "Uploader Artist")
            self.assertIsNone(data["album_cover_url"])
            self.assertTrue(Path(data["stream_url"]).exists())
            self.assertEqual(data["duration_ms"], 12400)

    def test_play_youtube_song_uses_video_container_when_no_audio_only_stream_is_available(self) -> None:
        """Verifies that playback can fall back to a video container with an audio stream.

        Typical use: Use this in automated tests when guarding the play youtube song returns failure when no audio stream is available behavior against regressions.

        Example: test_play_youtube_song_returns_failure_when_no_audio_stream_is_available() -> passes without assertion failures when the behavior remains correct.
        """
        FakeYoutubeDL.responses = [
            {
                "entries": [{
                    "id": "ghi789",
                    "title": "Test Artist - No Audio",
                    "artist": "Test Artist",
                }]
            },
            {
                "id": "ghi789",
                "title": "Test Artist - No Audio",
                "formats": [
                    {"url": "video.mp4", "acodec": "mp4a", "vcodec": "avc1"},
                ],
            },
        ]

        with tempfile.TemporaryDirectory() as tmp:
            with patch("src.tools.online_play.online_audio_configured", return_value=False), \
                patch("src.tools.online_play.yt_dlp.YoutubeDL", FakeYoutubeDL), \
                patch("src.tools.online_play.check_player", return_value=True), \
                patch("src.tools.online_play.is_player_allowed", return_value=True), \
                patch("src.tools.online_play.start_local_playback", side_effect=_playback_success) as launch:
                result = online.play_youtube_song(
                    "No Audio",
                    cache_root=Path(tmp),
                    playback_metadata={
                        "name": "No Audio",
                        "title": "No Audio",
                        "artist": "Test Artist",
                    },
                )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["data"]["media"]["kind"], "video_container")
        launch.assert_called_once()
        self.assertEqual(launch.call_args.kwargs["player"], "mpv")

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
        self.assertEqual(result["tool"], "play_youtube_song")
        self.assertEqual(result["error_code"], "YOUTUBE_UNAVAILABLE")
        self.assertIn("Selected YouTube result is not available", result["message"])
        self.assertIn("Choose another candidate or refine", result["message"])
        self.assertNotIn("wYB9Vu282ZU", result["message"])
        self.assertEqual(result["data"]["source_attempts"][0]["provider"], "youtube")
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

    def test_player_confirm_offers_only_mpv_and_cancel(self) -> None:
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
        self.assertEqual([choice["value"] for choice in choices], ["mpv", "deny"])
        self.assertIn("mpv", choices[0]["label"])
        self.assertIn("default", choices[0]["description"])

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
