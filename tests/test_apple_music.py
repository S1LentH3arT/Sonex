from __future__ import annotations

import base64
import importlib
import json
import os
import tempfile
import unittest
from unittest.mock import patch

apple_auth = importlib.import_module("src.auth.apple_music")
apple = importlib.import_module("src.tools.apple_music")
auth_store = importlib.import_module("src.auth.store")
auth_models = importlib.import_module("src.auth.models")


def _decode_jwt_part(value: str) -> dict:
    padding = "=" * (-len(value) % 4)
    return json.loads(base64.urlsafe_b64decode(value + padding).decode("utf-8"))


class AppleMusicAuthTests(unittest.TestCase):
    def setUp(self) -> None:
        apple_auth._DEVELOPER_TOKEN_CACHE.clear()
        apple.reset_recent_tracks()

    def _credentials_json(self) -> str:
        return json.dumps(
            {
                "team_id": "TEAM123",
                "key_id": "KEY123",
                "media_id": "media.example",
                "private_key": "-----BEGIN PRIVATE KEY-----\\nfake\\n-----END PRIVATE KEY-----",
            }
        )

    def test_developer_token_uses_apple_jwt_fields_and_cache(self) -> None:
        credentials = apple_auth.AppleMusicCredentials.from_dict(json.loads(self._credentials_json()))
        with patch.object(apple_auth, "_sign_es256", return_value=b"1" * 64) as sign:
            token = apple_auth.generate_developer_token(credentials, now=1000)
            cached = apple_auth.generate_developer_token(credentials, now=1100)

        self.assertEqual(token, cached)
        self.assertEqual(sign.call_count, 1)
        header, payload, signature = token.split(".")
        self.assertEqual(_decode_jwt_part(header), {"alg": "ES256", "kid": "KEY123", "typ": "JWT"})
        self.assertEqual(_decode_jwt_part(payload), {"exp": 2593000, "iat": 1000, "iss": "TEAM123"})
        self.assertTrue(signature)

    def test_credentials_preserve_music_user_token(self) -> None:
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {"SONEX_HOME": home}):
            auth_store.set_oauth_token("apple_music", auth_models.OAuthToken(access_token="user-token"))
            apple_auth.save_apple_music_credentials(self._credentials_json())

            provider = auth_store.get_provider_auth(auth_store.load_auth_store(), "apple_music")

        self.assertIsNotNone(provider)
        self.assertIsNotNone(provider.oauth)
        self.assertEqual(provider.oauth.access_token, "user-token")
        self.assertIn("TEAM123", provider.api_key)

    def test_missing_config_returns_setup_guidance(self) -> None:
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {"SONEX_HOME": home}):
            result = apple.apple_music_search("song")

        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["error_code"], "APPLE_MUSIC_CONFIG_MISSING")
        self.assertIn("sonex auth set-key apple_music", result["message"])


class AppleMusicToolTests(unittest.TestCase):
    def setUp(self) -> None:
        apple.reset_recent_tracks()

    def _song_payload(self, idx: int = 1) -> dict:
        return {
            "id": f"song-{idx}",
            "attributes": {
                "name": f"Song {idx}",
                "artistName": f"Artist {idx}",
                "albumName": f"Album {idx}",
                "durationInMillis": 181000,
                "url": f"https://music.apple.com/us/song/{idx}",
                "artwork": {"url": "https://img/{w}x{h}.jpg", "width": 300, "height": 300},
                "playParams": {"id": f"song-{idx}", "kind": "song"},
            },
        }

    def test_search_normalizes_catalog_tracks(self) -> None:
        payload = {"results": {"songs": {"data": [self._song_payload()]}}}
        with patch.object(apple, "_apple_music_request", return_value=payload):
            result = apple.apple_music_search("Song", limit=1, types="songs")

        self.assertEqual(result["status"], "success")
        track = result["data"]["tracks"][0]
        self.assertEqual(track["provider"], "apple_music")
        self.assertEqual(track["name"], "Song 1")
        self.assertEqual(track["artist"], "Artist 1")
        self.assertEqual(track["album_cover_url"], "https://img/300x300.jpg")
        self.assertEqual(track["uri"], "apple_music:song:song-1")

    def test_recent_queue_persists_dedupes_and_orders_newest_first(self) -> None:
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {"SONEX_HOME": home}):
            apple.reset_recent_tracks(clear_disk=True)
            with patch.object(apple, "_cache_cover", return_value=None):
                for idx in range(12):
                    apple.remember_recent_track(apple._normalize_song(self._song_payload(idx)))
                apple.remember_recent_track(apple._normalize_song(self._song_payload(5)))

            tracks = apple.recent_tracks_snapshot()
            cache_path = apple._recent_tracks_path()
            self.assertTrue(cache_path.exists())
            apple.reset_recent_tracks(reload_from_disk=True)
            reloaded = apple.recent_tracks_snapshot()

        self.assertEqual(len(tracks), 10)
        self.assertEqual(tracks[0]["uri"], "apple_music:song:song-5")
        self.assertEqual(reloaded[0]["uri"], "apple_music:song:song-5")
        self.assertNotIn("apple_music:song:song-0", {track["uri"] for track in tracks})

    def test_recent_tracks_requires_user_token(self) -> None:
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {"SONEX_HOME": home}):
            result = apple.apple_music_recent_tracks()

        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["error_code"], "APPLE_MUSIC_USER_TOKEN_REQUIRED")

    def test_playback_requires_subscription_before_bridge(self) -> None:
        account = {
            "status": "success",
            "data": {
                "logged_in": True,
                "subscription": {"canPlayCatalogContent": False},
                "capabilities": {"playback_control": False},
            },
        }
        with (
            patch.object(apple, "ensure_apple_music_user_token", return_value=object()),
            patch.object(apple, "apple_music_account", return_value=account),
        ):
            result = apple.apple_music_play(query="Song")

        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["error_code"], "APPLE_MUSIC_SUBSCRIPTION_REQUIRED")

    def test_playback_reports_missing_musickit_bridge(self) -> None:
        account = {
            "status": "success",
            "data": {
                "logged_in": True,
                "subscription": {"canPlayCatalogContent": True},
                "capabilities": {"playback_control": False},
            },
        }
        with (
            patch.object(apple, "ensure_apple_music_user_token", return_value=object()),
            patch.object(apple, "apple_music_account", return_value=account),
            patch.dict(os.environ, {}, clear=True),
        ):
            result = apple.apple_music_play(query="Song")

        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["error_code"], "APPLE_MUSIC_PLAYBACK_UNAVAILABLE")


if __name__ == "__main__":
    unittest.main()
