"""Tests test spotify play.

Contains pytest coverage for the test spotify play behavior.
"""

from __future__ import annotations

import unittest
import importlib
import os
import requests
import ssl
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

from spotipy import SpotifyException

spotify = importlib.import_module("src.tools.spotify_play")
spotify_auth = importlib.import_module("src.auth.spotify")
spotify_sync = importlib.import_module("src.tools.spotify_library_sync")
auth_store = importlib.import_module("src.auth.store")
auth_models = importlib.import_module("src.auth.models")


class SpotifyToolTests(unittest.TestCase):
    """Groups related spotify tool tests cases.

    Collects assertions that exercise spotify tool tests behavior without mixing unrelated fixtures.
    """
    def setUp(self) -> None:
        """Verifies that setUp behaves as expected.

        Typical use: Use this in automated tests when guarding the setUp behavior against regressions.

        Example: setUp() -> passes without assertion failures when the behavior remains correct.
        """
        spotify.reset_recent_tracks()
        spotify.reset_spotify_api_request_gate()

    def test_request_gate_paces_calls_and_honors_retry_after(self) -> None:
        clock = [100.0]
        sleeps: list[float] = []
        gate = spotify.SpotifyApiRequestGate(min_interval_seconds=0.25)

        def advance(seconds: float) -> None:
            sleeps.append(seconds)
            clock[0] += seconds

        rate_limit = SpotifyException(429, -1, "Too Many Requests", headers={"Retry-After": "7"})
        with patch.object(spotify.time, "monotonic", side_effect=lambda: clock[0]), patch.object(
            spotify.time,
            "sleep",
            side_effect=advance,
        ):
            self.assertEqual(gate.run(lambda: "first"), "first")
            self.assertEqual(gate.run(lambda: "second"), "second")
            with self.assertRaises(SpotifyException):
                gate.run(lambda: (_ for _ in ()).throw(rate_limit))
            with self.assertRaises(spotify.SpotifyRateLimitCooldownError) as cooldown:
                gate.run(lambda: "blocked")

        self.assertEqual(sleeps, [0.25, 0.25])
        self.assertEqual(cooldown.exception.headers["Retry-After"], "7")

    def test_spotify_user_client_disables_all_http_retries(self) -> None:
        token = auth_models.OAuthToken(
            access_token="token",
            refresh_token="refresh",
            expires_at="2100-01-01T00:00:00+00:00",
            scopes=["user-library-read"],
        )

        with patch.object(spotify_auth, "ensure_spotify_token", return_value=token), patch.object(
            spotify_auth.spotipy,
            "Spotify",
            return_value=object(),
        ) as client:
            spotify_auth.spotify_user_client(
                {"user-library-read"},
                requests_timeout=5,
                retries=0,
            )

        client.assert_called_once_with(
            auth="token",
            requests_timeout=5,
            retries=0,
            status_retries=0,
            requests_session=False,
        )

    def test_non_retrying_spotify_client_preserves_retry_after_header(self) -> None:
        token = auth_models.OAuthToken(
            access_token="token",
            refresh_token="refresh",
            expires_at="2100-01-01T00:00:00+00:00",
            scopes=["user-library-read"],
        )
        response = Mock()
        response.status_code = 429
        response.url = "https://api.spotify.com/v1/me/tracks"
        response.headers = {"Retry-After": "62861"}
        response.text = "Too Many Requests"
        response.json.return_value = {"error": {"message": "Too Many Requests"}}
        response.raise_for_status.side_effect = requests.exceptions.HTTPError(response=response)

        with patch.object(spotify_auth, "ensure_spotify_token", return_value=token), patch(
            "requests.api.request",
            return_value=response,
        ):
            client = spotify_auth.spotify_user_client(
                {"user-library-read"},
                requests_timeout=5,
                retries=0,
            )
            with self.assertRaises(SpotifyException) as error:
                client._internal_call("GET", "https://api.spotify.com/v1/me/tracks", None, {})

        self.assertEqual(error.exception.http_status, 429)
        self.assertEqual(error.exception.headers["Retry-After"], "62861")

    def test_request_gate_uses_fallback_for_invalid_retry_after(self) -> None:
        clock = [50.0]
        gate = spotify.SpotifyApiRequestGate(
            min_interval_seconds=0,
            fallback_cooldown_seconds=12,
        )
        rate_limit = SpotifyException(429, -1, "Too Many Requests", headers={"Retry-After": "invalid"})
        with patch.object(spotify.time, "monotonic", side_effect=lambda: clock[0]):
            with self.assertRaises(SpotifyException):
                gate.run(lambda: (_ for _ in ()).throw(rate_limit))
            with self.assertRaises(spotify.SpotifyRateLimitCooldownError) as cooldown:
                gate.run(lambda: "blocked")

        self.assertEqual(cooldown.exception.headers["Retry-After"], "12")

    def test_spotify_account_stops_on_rate_limit_and_recovers_after_cooldown(self) -> None:
        """Account verification must not hide a 429 behind an unknown product."""
        clock = [100.0]
        token = auth_models.OAuthToken(
            access_token="token",
            refresh_token="refresh",
            expires_at="2100-01-01T00:00:00+00:00",
            scopes=["user-read-private"],
        )
        client = Mock()
        client.current_user.side_effect = [
            SpotifyException(429, -1, "Too Many Requests", headers={"Retry-After": "30"}),
            {"id": "listener", "display_name": "Listener", "product": "premium"},
        ]

        with patch.object(spotify, "load_spotify_token", return_value=token), patch.object(
            spotify,
            "spotify_user_client",
            return_value=client,
        ), patch.object(spotify.time, "monotonic", side_effect=lambda: clock[0]):
            limited = spotify.spotify_account(requests_timeout=1.5)
            cooling_down = spotify.spotify_account(requests_timeout=1.5)
            clock[0] += 30.1
            recovered = spotify.spotify_account(requests_timeout=1.5)

        self.assertEqual(limited["status"], "fail")
        self.assertEqual(limited["error_code"], "SPOTIFY_RATE_LIMITED")
        self.assertEqual(limited["data"]["retry_after"], "30 seconds")
        self.assertEqual(cooling_down["status"], "fail")
        self.assertEqual(cooling_down["error_code"], "SPOTIFY_RATE_LIMITED")
        self.assertEqual(client.current_user.call_count, 2)
        self.assertEqual(recovered["status"], "success")
        self.assertEqual(recovered["data"]["product"], "premium")

    def _track(self, idx: int) -> dict:
        """Verifies that track behaves as expected.

        Typical use: Use this in automated tests when guarding the track behavior against regressions.

        Example: _track() -> passes without assertion failures when the behavior remains correct.
        """
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
        """Verifies that normalize track uses largest cover behaves as expected.

        Typical use: Use this in automated tests when guarding the normalize track uses largest cover behavior against regressions.

        Example: test_normalize_track_uses_largest_cover() -> passes without assertion failures when the behavior remains correct.
        """
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
        """Verifies that current playback preserves progress and state behaves as expected.

        Typical use: Use this in automated tests when guarding the current playback preserves progress and state behavior against regressions.

        Example: test_current_playback_preserves_progress_and_state() -> passes without assertion failures when the behavior remains correct.
        """
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
        """Verifies that free account disables playback control behaves as expected.

        Typical use: Use this in automated tests when guarding the free account disables playback control behavior against regressions.

        Example: test_free_account_disables_playback_control() -> passes without assertion failures when the behavior remains correct.
        """
        capabilities = spotify._account_capabilities(
            "free",
            {"user-read-playback-state", "user-modify-playback-state"},
            True,
        )

        self.assertTrue(capabilities["search"])
        self.assertFalse(capabilities["current_playback"])
        self.assertFalse(capabilities["playback_control"])

    def test_default_spotify_scopes_include_playlist_reads(self) -> None:
        self.assertIn("playlist-read-private", spotify_auth.DEFAULT_SPOTIFY_SCOPES)
        self.assertIn("playlist-read-collaborative", spotify_auth.DEFAULT_SPOTIFY_SCOPES)
        self.assertIn("user-library-read", spotify_auth.DEFAULT_SPOTIFY_SCOPES)

    def test_current_playback_maps_premium_error_without_account_preflight(self) -> None:
        """Verifies that current playback skips player endpoint for free account behaves as expected.

        Typical use: Use this in automated tests when guarding the current playback skips player endpoint for free account behavior against regressions.

        Example: test_current_playback_skips_player_endpoint_for_free_account() -> passes without assertion failures when the behavior remains correct.
        """
        client = Mock()
        client.current_playback.side_effect = SpotifyException(403, -1, "Premium account required")
        with patch.object(spotify, "spotify_account", side_effect=AssertionError("should not call /me")), patch.object(
            spotify,
            "spotify_user_client",
            return_value=client,
        ):
            result = spotify.spotify_current_playback()

        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["error_code"], "SPOTIFY_PREMIUM_REQUIRED")

    def test_current_playback_does_not_preblock_unknown_product_with_playback_scope(self) -> None:
        class Client:
            def current_playback(self) -> dict:
                return {
                    "progress_ms": 1000,
                    "timestamp": 2000,
                    "is_playing": True,
                    "item": {"name": "Song", "duration_ms": 120000, "artists": [{"name": "Artist"}]},
                }

        with (
            patch.object(spotify, "spotify_account", side_effect=AssertionError("should not call /me")),
            patch.object(spotify, "spotify_user_client", return_value=Client()),
        ):
            result = spotify.spotify_current_playback()

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["data"]["name"], "Song")

    def test_find_device_matches_partial_name(self) -> None:
        """Verifies that find device matches partial name behaves as expected.

        Typical use: Use this in automated tests when guarding the find device matches partial name behavior against regressions.

        Example: test_find_device_matches_partial_name() -> passes without assertion failures when the behavior remains correct.
        """
        class Client:
            """Groups related client cases.

            Collects assertions that exercise client behavior without mixing unrelated fixtures.
            """
            def devices(self) -> dict:
                """Verifies that devices behaves as expected.

                Typical use: Use this in automated tests when guarding the devices behavior against regressions.

                Example: devices() -> passes without assertion failures when the behavior remains correct.
                """
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
        """Verifies that recent queue caps dedupes and orders newest first behaves as expected.

        Typical use: Use this in automated tests when guarding the recent queue caps dedupes and orders newest first behavior against regressions.

        Example: test_recent_queue_caps_dedupes_and_orders_newest_first() -> passes without assertion failures when the behavior remains correct.
        """
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
        """Verifies that recent tracks persist and reload from cache behaves as expected.

        Typical use: Use this in automated tests when guarding the recent tracks persist and reload from cache behavior against regressions.

        Example: test_recent_tracks_persist_and_reload_from_cache() -> passes without assertion failures when the behavior remains correct.
        """
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
        """Verifies that recent track cover cache failure is non blocking behaves as expected.

        Typical use: Use this in automated tests when guarding the recent track cover cache failure is non blocking behavior against regressions.

        Example: test_recent_track_cover_cache_failure_is_non_blocking() -> passes without assertion failures when the behavior remains correct.
        """
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {"SONEX_HOME": home}):
            spotify.reset_recent_tracks(clear_disk=True)
            with patch.object(spotify.urllib.request, "urlopen", side_effect=OSError("offline")):
                tracks = spotify.remember_recent_track(self._track(1))

        self.assertEqual(tracks[0]["uri"], "spotify:track:1")

    def test_spotify_play_uses_cached_uri_before_searching(self) -> None:
        """Verifies that spotify play uses cached uri before searching behaves as expected.

        Typical use: Use this in automated tests when guarding the spotify play uses cached uri before searching behavior against regressions.

        Example: test_spotify_play_uses_cached_uri_before_searching() -> passes without assertion failures when the behavior remains correct.
        """
        class Client:
            """Groups related client cases.

            Collects assertions that exercise client behavior without mixing unrelated fixtures.
            """
            def devices(self) -> dict:
                """Verifies that devices behaves as expected.

                Typical use: Use this in automated tests when guarding the devices behavior against regressions.

                Example: devices() -> passes without assertion failures when the behavior remains correct.
                """
                return {"devices": [{"id": "desktop", "is_active": True}]}

            def start_playback(self, device_id: str | None = None, uris: list[str] | None = None) -> None:
                """Verifies that start playback behaves as expected.

                Typical use: Use this in automated tests when guarding the start playback behavior against regressions.

                Example: start_playback() -> passes without assertion failures when the behavior remains correct.
                """
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
        """Verifies that spotify play falls back to search when cache misses behaves as expected.

        Typical use: Use this in automated tests when guarding the spotify play falls back to search when cache misses behavior against regressions.

        Example: test_spotify_play_falls_back_to_search_when_cache_misses() -> passes without assertion failures when the behavior remains correct.
        """
        class Client:
            """Groups related client cases.

            Collects assertions that exercise client behavior without mixing unrelated fixtures.
            """
            def devices(self) -> dict:
                """Verifies that devices behaves as expected.

                Typical use: Use this in automated tests when guarding the devices behavior against regressions.

                Example: devices() -> passes without assertion failures when the behavior remains correct.
                """
                return {"devices": [{"id": "desktop", "is_active": True}]}

            def start_playback(self, device_id: str | None = None, uris: list[str] | None = None) -> None:
                """Verifies that start playback behaves as expected.

                Typical use: Use this in automated tests when guarding the start playback behavior against regressions.

                Example: start_playback() -> passes without assertion failures when the behavior remains correct.
                """
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

    def test_spotify_play_uses_validated_device_id_without_listing_devices(self) -> None:
        class Client:
            def devices(self) -> dict:
                raise AssertionError("validated device id must not trigger device discovery")

            def start_playback(self, device_id: str | None = None, uris: list[str] | None = None) -> None:
                self.device_id = device_id
                self.uris = uris

        client = Client()
        with patch.object(spotify, "_require_premium_control", return_value=None), patch.object(
            spotify,
            "spotify_user_client",
            return_value=client,
        ):
            result = spotify.spotify_play(uri="spotify:track:direct", device_id="desktop")

        self.assertEqual(result["status"], "success")
        self.assertEqual(client.device_id, "desktop")
        self.assertEqual(client.uris, ["spotify:track:direct"])

    def test_spotify_app_credentials_preserve_oauth_token(self) -> None:
        """Verifies that spotify app credentials preserve oauth token behaves as expected.

        Typical use: Use this in automated tests when guarding the spotify app credentials preserve oauth token behavior against regressions.

        Example: test_spotify_app_credentials_preserve_oauth_token() -> passes without assertion failures when the behavior remains correct.
        """
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
        """Verifies that spotify play requires login behaves as expected.

        Typical use: Use this in automated tests when guarding the spotify play requires login behavior against regressions.

        Example: test_spotify_play_requires_login() -> passes without assertion failures when the behavior remains correct.
        """
        with patch.object(
            spotify,
            "ensure_spotify_token",
            side_effect=spotify.SpotifyLoginRequiredError("login required"),
        ):
            result = spotify.spotify_play(query="Song")

        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["error_code"], "SPOTIFY_LOGIN_REQUIRED")

    def test_playback_control_gate_uses_local_token_without_account_request(self) -> None:
        with patch.object(spotify, "ensure_spotify_token", return_value=object()) as ensure, patch.object(
            spotify,
            "spotify_account",
            side_effect=AssertionError("playback control must not request /me"),
        ):
            result = spotify._require_premium_control("spotify_play")

        self.assertIsNone(result)
        ensure.assert_called_once_with(spotify.SPOTIFY_MODIFY_PLAYBACK_SCOPES)

    def test_spotify_transfer_requires_device(self) -> None:
        """Verifies that spotify transfer requires device behaves as expected.

        Typical use: Use this in automated tests when guarding the spotify transfer requires device behavior against regressions.

        Example: test_spotify_transfer_requires_device() -> passes without assertion failures when the behavior remains correct.
        """
        with patch.object(spotify, "_require_premium_control", return_value=None):
            result = spotify.spotify_transfer_playback()

        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["error_code"], "SPOTIFY_DEVICE_REQUIRED")

    def test_spotify_recent_tracks_normalizes_and_updates_queue(self) -> None:
        """Verifies that spotify recent tracks normalizes and updates queue behaves as expected.

        Typical use: Use this in automated tests when guarding the spotify recent tracks normalizes and updates queue behavior against regressions.

        Example: test_spotify_recent_tracks_normalizes_and_updates_queue() -> passes without assertion failures when the behavior remains correct.
        """
        class Client:
            """Groups related client cases.

            Collects assertions that exercise client behavior without mixing unrelated fixtures.
            """
            def current_user_recently_played(self, limit: int) -> dict:
                """Verifies that current user recently played behaves as expected.

                Typical use: Use this in automated tests when guarding the current user recently played behavior against regressions.

                Example: current_user_recently_played() -> passes without assertion failures when the behavior remains correct.
                """
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
        """Verifies that spotify recent tracks reports missing scope behaves as expected.

        Typical use: Use this in automated tests when guarding the spotify recent tracks reports missing scope behavior against regressions.

        Example: test_spotify_recent_tracks_reports_missing_scope() -> passes without assertion failures when the behavior remains correct.
        """
        with patch.object(
            spotify,
            "spotify_user_client",
            side_effect=spotify.SpotifyScopeMissingError({"user-read-recently-played"}),
        ):
            result = spotify.spotify_recent_tracks(limit=10)

        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["error_code"], "SPOTIFY_SCOPE_MISSING")

    def test_spotify_saved_tracks_normalizes_current_user_library(self) -> None:
        class Client:
            def current_user_saved_tracks(self, limit: int, offset: int) -> dict:
                self.limit = limit
                self.offset = offset
                return {
                    "items": [
                        {
                            "added_at": "2026-06-21T00:00:00Z",
                            "track": {
                                "id": "saved-track",
                                "name": "Saved Song",
                                "duration_ms": 123000,
                                "artists": [{"name": "Saved Artist"}],
                                "album": {
                                    "name": "Saved Album",
                                    "images": [{"url": "cover", "width": 640, "height": 640}],
                                },
                                "external_urls": {"spotify": "https://open.spotify.com/track/saved-track"},
                                "uri": "spotify:track:saved-track",
                                "type": "track",
                            },
                        }
                    ]
                }

        with patch.object(spotify, "spotify_user_client", return_value=Client()) as user_client:
            result = spotify.spotify_saved_tracks(limit=20)

        user_client.assert_called_once_with(spotify.SPOTIFY_LIBRARY_READ_SCOPES, requests_timeout=5, retries=0)
        self.assertEqual(result["status"], "success")
        track = result["data"]["tracks"][0]
        self.assertEqual(track["name"], "Saved Song")
        self.assertEqual(track["artist"], "Saved Artist")
        self.assertEqual(track["added_at"], "2026-06-21T00:00:00Z")
        self.assertEqual(track["provider"], "spotify")

    def test_spotify_playlists_normalizes_current_user_playlists(self) -> None:
        class Client:
            def current_user_playlists(self, limit: int, offset: int) -> dict:
                self.limit = limit
                self.offset = offset
                return {
                    "items": [
                        {
                            "id": "playlist-1",
                            "name": "Road",
                            "description": "Driving",
                            "owner": {"display_name": "Me"},
                            "tracks": {"total": 2},
                            "external_urls": {"spotify": "https://open.spotify.com/playlist/playlist-1"},
                            "uri": "spotify:playlist:playlist-1",
                            "public": False,
                            "collaborative": True,
                        }
                    ]
                }

        with patch.object(spotify, "spotify_user_client", return_value=Client()) as user_client:
            result = spotify.spotify_playlists(limit=20)

        user_client.assert_called_once_with(spotify.SPOTIFY_PLAYLIST_READ_SCOPES, requests_timeout=5, retries=0)
        self.assertEqual(result["status"], "success")
        playlist = result["data"]["playlists"][0]
        self.assertEqual(playlist["id"], "playlist-1")
        self.assertEqual(playlist["name"], "Road")
        self.assertEqual(playlist["track_count"], 2)
        self.assertTrue(playlist["collaborative"])

    def test_spotify_playlist_tracks_normalizes_compact_tracks(self) -> None:
        class Client:
            def playlist_items(self, playlist_id: str, fields: str, limit: int, offset: int, additional_types: tuple[str]) -> dict:
                self.playlist_id = playlist_id
                self.fields = fields
                self.limit = limit
                self.offset = offset
                self.additional_types = additional_types
                return {
                    "items": [
                        {
                            "track": {
                                "id": "track-1",
                                "name": "Song",
                                "duration_ms": 123000,
                                "artists": [{"name": "Artist"}],
                                "album": {
                                    "name": "Album",
                                    "images": [{"url": "cover", "width": 640, "height": 640}],
                                },
                                "external_urls": {"spotify": "https://open.spotify.com/track/track-1"},
                                "uri": "spotify:track:track-1",
                                "type": "track",
                            }
                        },
                        {"track": {"type": "episode", "name": "Podcast"}},
                    ]
                }

        with patch.object(spotify, "spotify_user_client", return_value=Client()) as user_client:
            result = spotify.spotify_playlist_tracks(playlist_id="playlist-1", limit=50)

        user_client.assert_called_once_with(spotify.SPOTIFY_PLAYLIST_READ_SCOPES, requests_timeout=5, retries=0)
        self.assertEqual(result["status"], "success")
        self.assertEqual(len(result["data"]["tracks"]), 1)
        track = result["data"]["tracks"][0]
        self.assertEqual(track["name"], "Song")
        self.assertEqual(track["artist"], "Artist")
        self.assertEqual(track["uri"], "spotify:track:track-1")

    def test_spotify_queue_normalizes_current_and_queued_tracks(self) -> None:
        class Client:
            def queue(self) -> dict:
                return {
                    "currently_playing": {
                        "id": "current",
                        "name": "Current Song",
                        "duration_ms": 180000,
                        "artists": [{"name": "Current Artist"}],
                        "album": {"name": "Now", "images": [{"url": "current-cover", "width": 300, "height": 300}]},
                        "external_urls": {"spotify": "https://open.spotify.com/track/current"},
                        "uri": "spotify:track:current",
                        "type": "track",
                    },
                    "queue": [
                        {
                            "id": "queued-1",
                            "name": "Queued Song",
                            "duration_ms": 123000,
                            "artists": [{"name": "Queued Artist"}],
                            "album": {"name": "Next", "images": [{"url": "queued-cover", "width": 640, "height": 640}]},
                            "external_urls": {"spotify": "https://open.spotify.com/track/queued-1"},
                            "uri": "spotify:track:queued-1",
                            "type": "track",
                        },
                        {"type": "episode", "name": "Podcast", "uri": "spotify:episode:1"},
                        {"type": "track", "name": "Missing URI"},
                    ],
                }

        with patch.object(spotify, "spotify_user_client", return_value=Client()) as user_client:
            result = spotify.spotify_queue(limit=10)

        user_client.assert_called_once_with(spotify.SPOTIFY_READ_PLAYBACK_SCOPES, requests_timeout=5, retries=0)
        self.assertEqual(result["status"], "success")
        tracks = result["data"]["tracks"]
        self.assertEqual([track["name"] for track in tracks], ["Current Song", "Queued Song"])
        self.assertEqual(result["data"]["currently_playing"]["uri"], "spotify:track:current")
        self.assertEqual(result["data"]["queue"][0]["uri"], "spotify:track:queued-1")

    def test_spotify_queue_reports_unavailable_loopback_proxy(self) -> None:
        with (
            patch.object(
                spotify,
                "spotify_user_client",
                side_effect=ConnectionRefusedError(111, "Connection refused"),
            ),
            patch.dict("os.environ", {"HTTPS_PROXY": "http://127.0.0.1:7897"}, clear=True),
        ):
            result = spotify.spotify_queue(limit=10)

        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["error_code"], "SPOTIFY_PROXY_UNAVAILABLE")
        self.assertIn("local proxy http://127.0.0.1:7897", result["message"])
        self.assertIn("start the proxy", result["message"])
        self.assertIn("HTTPS_PROXY/HTTP_PROXY/https_proxy/http_proxy/all_proxy/ALL_PROXY", result["message"])

    def test_spotify_queue_reports_loopback_proxy_tls_eof(self) -> None:
        ssl_error = ssl.SSLError(ssl.SSL_ERROR_EOF, "EOF occurred in violation of protocol")

        with (
            patch.object(spotify, "spotify_user_client", side_effect=ssl_error),
            patch.dict("os.environ", {"https_proxy": "http://127.0.0.1:7897"}, clear=True),
        ):
            result = spotify.spotify_queue(limit=10)

        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["error_code"], "SPOTIFY_PROXY_UNAVAILABLE")
        self.assertIn("local proxy http://127.0.0.1:7897", result["message"])
        self.assertIn("TLS connection closed unexpectedly", result["message"])

    def test_spotify_saved_tracks_classifies_read_timeout(self) -> None:
        with patch.object(
            spotify,
            "spotify_user_client",
            side_effect=requests.exceptions.ReadTimeout("read timeout"),
        ):
            result = spotify.spotify_saved_tracks(limit=10)

        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["error_code"], "SPOTIFY_READ_TIMEOUT")
        self.assertEqual(result["message"], "Spotify did not respond before the request timeout.")

    def test_spotify_pause_targets_selected_device(self) -> None:
        client = Mock()
        with patch.object(spotify, "_require_premium_control", return_value=None), patch.object(
            spotify,
            "spotify_user_client",
            return_value=client,
        ):
            result = spotify.spotify_pause(device_id="desktop")

        client.pause_playback.assert_called_once_with(device_id="desktop")
        self.assertEqual(result["status"], "success")
        self.assertNotIn("device_id", result["data"])

    def test_spotify_resume_targets_selected_device(self) -> None:
        client = Mock()
        with patch.object(spotify, "_require_premium_control", return_value=None), patch.object(
            spotify,
            "spotify_user_client",
            return_value=client,
        ):
            result = spotify.spotify_resume(device_id="desktop")

        client.start_playback.assert_called_once_with(device_id="desktop")
        self.assertEqual(result["status"], "success")
        self.assertNotIn("device_id", result["data"])

    def test_spotify_pause_and_resume_keep_no_device_calls_compatible(self) -> None:
        client = Mock()
        with patch.object(spotify, "_require_premium_control", return_value=None), patch.object(
            spotify,
            "spotify_user_client",
            return_value=client,
        ):
            pause_result = spotify.spotify_pause()
            resume_result = spotify.spotify_resume()

        client.pause_playback.assert_called_once_with()
        client.start_playback.assert_called_once_with()
        self.assertEqual(pause_result["status"], "success")
        self.assertEqual(resume_result["status"], "success")

    def test_spotify_pause_maps_login_and_timeout_errors(self) -> None:
        with patch.object(spotify, "_require_premium_control", return_value=None), patch.object(
            spotify,
            "spotify_user_client",
            side_effect=spotify.SpotifyLoginRequiredError("login required"),
        ):
            login_result = spotify.spotify_pause(device_id="desktop")

        client = Mock()
        client.pause_playback.side_effect = requests.exceptions.ReadTimeout("read timeout")
        with patch.object(spotify, "_require_premium_control", return_value=None), patch.object(
            spotify,
            "spotify_user_client",
            return_value=client,
        ):
            timeout_result = spotify.spotify_pause(device_id="desktop")

        self.assertEqual(login_result["error_code"], "SPOTIFY_LOGIN_REQUIRED")
        self.assertEqual(timeout_result["error_code"], "SPOTIFY_READ_TIMEOUT")

    def test_spotify_pause_and_resume_schemas_accept_optional_device_id(self) -> None:
        for tool_name in ("spotify_pause", "spotify_resume"):
            tool = spotify.registry.get(tool_name)
            self.assertIsNotNone(tool)
            assert tool is not None
            self.assertIn("device_id", tool.parameters.properties)
            self.assertNotIn("device_id", tool.parameters.required)

    def test_spotify_library_sync_state_round_trip_and_freshness(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "library-sync.json"
            state = spotify_sync.SpotifyLibrarySyncState(
                last_attempt_at=90,
                last_success_at=100,
                next_retry_at=150,
                last_error_code="SPOTIFY_RATE_LIMITED",
                saved_tracks_cursor="2026-07-12T00:00:00Z",
                last_full_saved_tracks_at=80,
                playlist_snapshots={"playlist-1": "snapshot-1"},
            )
            spotify_sync.save_spotify_library_sync_state(state, path)
            loaded = spotify_sync.load_spotify_library_sync_state(path)

        self.assertEqual(loaded.playlist_snapshots, {"playlist-1": "snapshot-1"})
        self.assertTrue(loaded.is_fresh(now=101))
        self.assertTrue(loaded.is_backing_off(now=149))
        self.assertFalse(loaded.is_backing_off(now=151))

    def test_spotify_queue_scope_missing_uses_stable_error_code(self) -> None:
        with patch.object(
            spotify,
            "spotify_user_client",
            side_effect=spotify.SpotifyScopeMissingError({"user-read-playback-state"}),
        ):
            result = spotify.spotify_queue(limit=10)

        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["error_code"], "SPOTIFY_SCOPE_MISSING")

    def test_spotify_queue_add_calls_client_with_device_id(self) -> None:
        class Client:
            def __init__(self) -> None:
                self.calls: list[tuple[str, str | None]] = []

            def add_to_queue(self, uri: str, device_id: str | None = None) -> None:
                self.calls.append((uri, device_id))

        client = Client()
        with patch.object(spotify, "_require_premium_control", return_value=None), patch.object(
            spotify,
            "spotify_user_client",
            return_value=client,
        ) as user_client:
            result = spotify.spotify_queue_add("spotify:track:track-1", device_id="desktop")

        user_client.assert_called_once_with(
            spotify.SPOTIFY_MODIFY_PLAYBACK_SCOPES | spotify.SPOTIFY_READ_PLAYBACK_SCOPES,
            requests_timeout=5,
            retries=0,
        )
        self.assertEqual(client.calls, [("spotify:track:track-1", "desktop")])
        self.assertEqual(result["status"], "success")

    def test_spotify_queue_add_rejects_invalid_uri(self) -> None:
        with patch.object(spotify, "_require_premium_control") as require:
            result = spotify.spotify_queue_add("spotify:episode:episode-1")

        require.assert_not_called()
        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["error_code"], "SPOTIFY_TRACK_URI_REQUIRED")

    def test_spotify_queue_add_requires_active_device_without_device_id(self) -> None:
        with patch.object(spotify, "_require_premium_control", return_value=None), patch.object(
            spotify,
            "spotify_user_client",
            return_value=object(),
        ), patch.object(
            spotify,
            "_has_active_device",
            return_value=False,
        ):
            result = spotify.spotify_queue_add("spotify:track:track-1")

        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["error_code"], "SPOTIFY_DEVICE_REQUIRED")

    def test_spotify_queue_add_maps_scope_missing(self) -> None:
        with patch.object(
            spotify,
            "_require_premium_control",
            return_value={
                "status": "fail",
                "message": "Spotify playback control scope is missing. Open /spotify to reconnect.",
                "error_code": "SPOTIFY_SCOPE_MISSING",
            },
        ):
            result = spotify.spotify_queue_add("spotify:track:track-1", device_id="desktop")

        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["error_code"], "SPOTIFY_SCOPE_MISSING")

    def test_spotify_queue_add_maps_spotify_api_errors(self) -> None:
        class Client:
            def add_to_queue(self, uri: str, device_id: str | None = None) -> None:
                raise SpotifyException(http_status=500, code=-1, msg="server error")

        with patch.object(spotify, "_require_premium_control", return_value=None), patch.object(
            spotify,
            "spotify_user_client",
            return_value=Client(),
        ):
            result = spotify.spotify_queue_add("spotify:track:track-1", device_id="desktop")

        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["error_code"], "SPOTIFY_API_ERROR")

    def test_spotify_recommend_uses_only_candidate_tracks(self) -> None:
        """Verifies that spotify recommend uses only candidate tracks behaves as expected.

        Typical use: Use this in automated tests when guarding the spotify recommend uses only candidate tracks behavior against regressions.

        Example: test_spotify_recommend_uses_only_candidate_tracks() -> passes without assertion failures when the behavior remains correct.
        """
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

    def test_spotify_recommend_uses_supplied_recent_tracks(self) -> None:
        recent_tracks = [{"name": "Recent Song", "artist": "Recent Artist"}]
        with (
            patch.object(spotify, "_user_preferences_text", return_value=""),
            patch.object(spotify, "recent_tracks_snapshot", side_effect=AssertionError("should use supplied context")),
            patch.object(spotify, "_spotify_candidate_tracks", return_value=[self._track(1)]),
            patch.object(spotify, "_rank_candidates_with_llm", return_value=[]) as rank,
        ):
            result = spotify.spotify_recommend(query="", limit=1, recent_tracks=recent_tracks)

        self.assertEqual(result["status"], "success")
        self.assertEqual(rank.call_args.kwargs["recent_tracks"], recent_tracks)

    def test_spotify_candidate_tracks_use_supplied_recent_without_remote_history(self) -> None:
        recent_tracks = [self._track(4)]
        with patch.object(spotify, "spotify_recent_tracks") as remote_recent, patch.object(
            spotify,
            "spotify_search",
        ) as search, patch.object(spotify, "spotify_user_client") as user_client:
            candidates = spotify._spotify_candidate_tracks("", 1, recent_tracks=recent_tracks)

        self.assertEqual([track["uri"] for track in candidates], ["spotify:track:4"])
        remote_recent.assert_not_called()
        search.assert_not_called()
        user_client.assert_not_called()

    def test_spotify_recommend_handles_empty_user_memory(self) -> None:
        """Verifies that spotify recommend handles empty user memory behaves as expected.

        Typical use: Use this in automated tests when guarding the spotify recommend handles empty user memory behavior against regressions.

        Example: test_spotify_recommend_handles_empty_user_memory() -> passes without assertion failures when the behavior remains correct.
        """
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
        """Verifies that spotify search maps app premium error behaves as expected.

        Typical use: Use this in automated tests when guarding the spotify search maps app premium error behavior against regressions.

        Example: test_spotify_search_maps_app_premium_error() -> passes without assertion failures when the behavior remains correct.
        """
        with patch.object(
            spotify,
            "_search_payload",
            side_effect=spotify.SpotifyAppPremiumRequiredError("premium required"),
        ):
            result = spotify.spotify_search(query="Song")

        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["error_code"], "SPOTIFY_APP_PREMIUM_REQUIRED")

    def test_spotify_search_sanitizes_premium_owner_search_error(self) -> None:
        """Verifies that spotify search sanitizes premium owner search error behaves as expected.

        Typical use: Use this in automated tests when guarding the spotify search sanitizes premium owner search error behavior against regressions.

        Example: test_spotify_search_sanitizes_premium_owner_search_error() -> passes without assertion failures when the behavior remains correct.
        """
        error = SpotifyException(
            403,
            -1,
            "https://api.spotify.com/v1/search?q=secret&limit=1&offset=0&type=track:\n"
            " Active premium subscription required for the owner of the app.",
        )

        with patch.object(spotify, "_search_payload", side_effect=error):
            result = spotify.spotify_search(query="Song")

        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["error_code"], "SPOTIFY_APP_PREMIUM_REQUIRED")
        self.assertIn("Spotify app search requires", result["message"])
        self.assertNotIn("api.spotify.com/v1/search", result["message"])
        self.assertNotIn("secret", result["message"])

    def test_spotify_429_maps_to_rate_limited_message(self) -> None:
        error = SpotifyException(
            429,
            -1,
            "https://api.spotify.com/v1/me/player: Too Many Requests",
            headers={"Retry-After": "30"},
        )

        with patch.object(spotify, "spotify_user_client", side_effect=error):
            result = spotify.spotify_devices()

        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["error_code"], "SPOTIFY_RATE_LIMITED")
        self.assertIn("Spotify says Too Many Requests", result["message"])
        self.assertIn("Requests are too frequent", result["message"])
        self.assertIn("try again later", result["message"])
        self.assertIn("30", result.get("data", {}).get("retry_after", ""))


if __name__ == "__main__":
    unittest.main()
