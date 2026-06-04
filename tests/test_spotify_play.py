from __future__ import annotations

import unittest
import importlib
import os
import tempfile
from unittest.mock import patch

spotify = importlib.import_module("src.tools.spotify_play")
spotify_auth = importlib.import_module("src.auth.spotify")
auth_store = importlib.import_module("src.auth.store")
auth_models = importlib.import_module("src.auth.models")


class SpotifyToolTests(unittest.TestCase):
    def setUp(self) -> None:
        spotify.reset_recent_tracks()

    def _track(self, idx: int) -> dict:
        return {
            "id": f"track-{idx}",
            "name": f"Song {idx}",
            "duration_ms": 120000 + idx,
            "artist": f"Artist {idx}",
            "artists": [f"Artist {idx}"],
            "album": f"Album {idx}",
            "album_cover_url": f"cover-{idx}",
            "spotify_url": f"https://open.spotify.com/track/{idx}",
            "uri": f"spotify:track:{idx}",
        }

    def test_normalize_track_uses_largest_cover(self) -> None:
        track = spotify._normalize_track(
            {
                "id": "track-id",
                "name": "Song",
                "duration_ms": 123000,
                "artists": [{"name": "Artist A"}, {"name": "Artist B"}],
                "album": {
                    "name": "Album",
                    "images": [
                        {"url": "small", "width": 64, "height": 64},
                        {"url": "large", "width": 640, "height": 640},
                    ],
                },
                "external_urls": {"spotify": "https://open.spotify.com/track/track-id"},
                "uri": "spotify:track:track-id",
            }
        )

        self.assertEqual(track["artist"], "Artist A, Artist B")
        self.assertEqual(track["album_cover_url"], "large")
        self.assertEqual(track["uri"], "spotify:track:track-id")

    def test_current_playback_preserves_progress_and_state(self) -> None:
        playback = spotify._normalize_current_playback(
            {
                "progress_ms": 42000,
                "timestamp": 100000,
                "is_playing": True,
                "currently_playing_type": "track",
                "device": {"id": "device", "name": "Desktop", "type": "Computer", "is_active": True},
                "item": {
                    "type": "track",
                    "name": "Song",
                    "duration_ms": 200000,
                    "artists": [{"name": "Artist"}],
                    "album": {"name": "Album", "images": [{"url": "cover", "width": 300, "height": 300}]},
                    "uri": "spotify:track:track-id",
                },
            }
        )

        self.assertTrue(playback["is_playing"])
        self.assertEqual(playback["progress_ms"], 42000)
        self.assertEqual(playback["started_at"], 58000)
        self.assertEqual(playback["album_cover_url"], "cover")

    def test_free_account_disables_playback_control(self) -> None:
        capabilities = spotify._account_capabilities(
            "free",
            {"user-read-playback-state", "user-modify-playback-state"},
            True,
        )

        self.assertTrue(capabilities["search"])
        self.assertFalse(capabilities["current_playback"])
        self.assertFalse(capabilities["playback_control"])

    def test_current_playback_skips_player_endpoint_for_free_account(self) -> None:
        with (
            patch.object(
                spotify,
                "spotify_account",
                return_value={
                    "status": "success",
                    "data": {
                        "logged_in": True,
                        "product": "free",
                        "capabilities": {"current_playback": False},
                    },
                },
            ),
            patch.object(spotify, "spotify_user_client", side_effect=AssertionError("should not call /me/player")),
        ):
            result = spotify.spotify_current_playback()

        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["error_code"], "SPOTIFY_PREMIUM_REQUIRED")

    def test_find_device_matches_partial_name(self) -> None:
        class Client:
            def devices(self) -> dict:
                return {
                    "devices": [
                        {"id": "phone", "name": "Pixel Phone", "type": "Smartphone"},
                        {"id": "desktop", "name": "Studio Desktop", "type": "Computer"},
                    ]
                }

        device = spotify._find_device(Client(), device_name="studio")

        self.assertIsNotNone(device)
        self.assertEqual(device["id"], "desktop")

    def test_recent_queue_caps_dedupes_and_orders_newest_first(self) -> None:
        with patch.object(spotify, "_cache_cover", return_value=None):
            for idx in range(12):
                spotify.remember_recent_track(self._track(idx))
            spotify.remember_recent_track(self._track(5))

        tracks = spotify.recent_tracks_snapshot()

        self.assertEqual(len(tracks), 10)
        self.assertEqual(tracks[0]["uri"], "spotify:track:5")
        self.assertEqual(len({track["uri"] for track in tracks}), 10)
        self.assertNotIn("spotify:track:0", {track["uri"] for track in tracks})

    def test_recent_tracks_persist_and_reload_from_cache(self) -> None:
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {"SONEX_HOME": home}):
            spotify.reset_recent_tracks(clear_disk=True)
            with patch.object(spotify, "_cache_cover", return_value=None):
                spotify.remember_recent_track(self._track(1))

            cache_path = spotify._recent_tracks_path()
            self.assertTrue(cache_path.exists())

            spotify.reset_recent_tracks(reload_from_disk=True)
            tracks = spotify.recent_tracks_snapshot()

        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[0]["uri"], "spotify:track:1")

    def test_recent_track_cover_cache_failure_is_non_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {"SONEX_HOME": home}):
            spotify.reset_recent_tracks(clear_disk=True)
            with patch.object(spotify.urllib.request, "urlopen", side_effect=OSError("offline")):
                tracks = spotify.remember_recent_track(self._track(1))

        self.assertEqual(tracks[0]["uri"], "spotify:track:1")

    def test_spotify_play_uses_cached_uri_before_searching(self) -> None:
        class Client:
            def devices(self) -> dict:
                return {"devices": [{"id": "desktop", "is_active": True}]}

            def start_playback(self, device_id: str | None = None, uris: list[str] | None = None) -> None:
                self.device_id = device_id
                self.uris = uris

        client = Client()
        with (
            patch.object(spotify, "_cache_cover", return_value=None),
            patch.object(spotify, "_require_premium_control", return_value=None),
            patch.object(spotify, "spotify_user_client", return_value=client),
            patch.object(spotify, "spotify_search", side_effect=AssertionError("search should be skipped")),
        ):
            spotify.remember_recent_track(self._track(7))
            result = spotify.spotify_play(query="Song 7 Artist 7")

        self.assertEqual(result["status"], "success")
        self.assertTrue(result["data"]["cache_hit"])
        self.assertEqual(result["data"]["uri"], "spotify:track:7")
        self.assertEqual(client.uris, ["spotify:track:7"])

    def test_spotify_play_falls_back_to_search_when_cache_misses(self) -> None:
        class Client:
            def devices(self) -> dict:
                return {"devices": [{"id": "desktop", "is_active": True}]}

            def start_playback(self, device_id: str | None = None, uris: list[str] | None = None) -> None:
                self.uris = uris

        track = self._track(8)
        client = Client()
        with (
            patch.object(spotify, "_cache_cover", return_value=None),
            patch.object(spotify, "_require_premium_control", return_value=None),
            patch.object(spotify, "spotify_user_client", return_value=client),
            patch.object(
                spotify,
                "spotify_search",
                return_value={"status": "success", "data": {"tracks": [track]}},
            ) as search,
        ):
            result = spotify.spotify_play(query="unseen song")

        self.assertEqual(result["status"], "success")
        self.assertFalse(result["data"]["cache_hit"])
        self.assertEqual(client.uris, ["spotify:track:8"])
        search.assert_called_once()

    def test_spotify_app_credentials_preserve_oauth_token(self) -> None:
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {"SONEX_HOME": home}):
            token = auth_models.OAuthToken(access_token="access", refresh_token="refresh", scopes=["user-read-private"])
            auth_store.set_oauth_token("spotify", token)

            spotify_auth.save_spotify_app_credentials("client", "secret")

            provider = auth_store.get_provider_auth(auth_store.load_auth_store(), "spotify")

        self.assertIsNotNone(provider)
        self.assertEqual(provider.api_key, "client:secret")
        self.assertIsNotNone(provider.oauth)
        self.assertEqual(provider.oauth.access_token, "access")

    def test_spotify_play_requires_login(self) -> None:
        with patch.object(
            spotify,
            "spotify_account",
            return_value={"status": "success", "data": {"logged_in": False, "product": "unknown"}},
        ):
            result = spotify.spotify_play(query="Song")

        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["error_code"], "SPOTIFY_LOGIN_REQUIRED")

    def test_spotify_transfer_requires_device(self) -> None:
        with patch.object(spotify, "_require_premium_control", return_value=None):
            result = spotify.spotify_transfer_playback()

        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["error_code"], "SPOTIFY_DEVICE_REQUIRED")

    def test_spotify_recent_tracks_normalizes_and_updates_queue(self) -> None:
        class Client:
            def current_user_recently_played(self, limit: int) -> dict:
                return {
                    "items": [
                        {
                            "played_at": "2026-05-27T00:00:00Z",
                            "track": {
                                "id": "recent",
                                "name": "Recent Song",
                                "duration_ms": 180000,
                                "artists": [{"name": "Recent Artist"}],
                                "album": {
                                    "name": "Recent Album",
                                    "images": [
                                        {"url": "small", "width": 64, "height": 64},
                                        {"url": "large", "width": 640, "height": 640},
                                    ],
                                },
                                "external_urls": {"spotify": "https://open.spotify.com/track/recent"},
                                "uri": "spotify:track:recent",
                            },
                        }
                    ]
                }

        with patch.object(spotify, "spotify_user_client", return_value=Client()):
            result = spotify.spotify_recent_tracks(limit=10)

        self.assertEqual(result["status"], "success")
        track = result["data"]["tracks"][0]
        self.assertEqual(track["artist"], "Recent Artist")
        self.assertEqual(track["album_cover_url"], "large")
        self.assertEqual(spotify.recent_tracks_snapshot()[0]["uri"], "spotify:track:recent")

    def test_spotify_recent_tracks_reports_missing_scope(self) -> None:
        with patch.object(
            spotify,
            "spotify_user_client",
            side_effect=spotify.SpotifyScopeMissingError({"user-read-recently-played"}),
        ):
            result = spotify.spotify_recent_tracks(limit=10)

        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["error_code"], "SPOTIFY_SCOPE_MISSING")

    def test_spotify_recommend_uses_only_candidate_tracks(self) -> None:
        candidates = [self._track(1), self._track(2)]
        with (
            patch.object(spotify, "_user_preferences_text", return_value=""),
            patch.object(spotify, "_spotify_candidate_tracks", return_value=candidates),
            patch.object(
                spotify,
                "_rank_candidates_with_llm",
                return_value=[
                    {"uri": "spotify:track:2", "reason": "Closer to your recent plays."},
                    {"uri": "spotify:track:missing", "reason": "Should be ignored."},
                ],
            ),
        ):
            result = spotify.spotify_recommend(query="推荐一些歌", limit=2)

        self.assertEqual(result["status"], "success")
        tracks = result["data"]["tracks"]
        self.assertEqual([track["uri"] for track in tracks], ["spotify:track:2", "spotify:track:1"])
        self.assertEqual(tracks[0]["recommendation_reason"], "Closer to your recent plays.")

    def test_spotify_recommend_handles_empty_user_memory(self) -> None:
        with (
            patch.object(spotify, "_user_preferences_text", return_value=""),
            patch.object(spotify, "_spotify_candidate_tracks", return_value=[self._track(3)]),
            patch.object(spotify, "_rank_candidates_with_llm", side_effect=RuntimeError("llm unavailable")),
        ):
            result = spotify.spotify_recommend(query="推荐", limit=1)

        self.assertEqual(result["status"], "success")
        self.assertFalse(result["data"]["user_memory_loaded"])
        self.assertEqual(result["data"]["tracks"][0]["uri"], "spotify:track:3")

    def test_spotify_search_maps_app_premium_error(self) -> None:
        with patch.object(
            spotify,
            "_search_payload",
            side_effect=spotify.SpotifyAppPremiumRequiredError("premium required"),
        ):
            result = spotify.spotify_search(query="Song")

        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["error_code"], "SPOTIFY_APP_PREMIUM_REQUIRED")


if __name__ == "__main__":
    unittest.main()
