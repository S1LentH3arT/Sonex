from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.auth.models import OAuthToken
from src.auth.providers import normalize_provider
from src.auth.store import get_provider_auth, load_auth_store, set_api_key, set_oauth_token

APPLE_MUSIC_PROVIDER = "apple_music"
APPLE_MUSIC_TOKEN_TTL_SECONDS = 60 * 60 * 24 * 30
_DEVELOPER_TOKEN_CACHE: dict[str, tuple[str, int]] = {}


class AppleMusicAuthError(RuntimeError):
    pass


class AppleMusicConfigMissingError(AppleMusicAuthError):
    pass


class AppleMusicUserTokenRequiredError(AppleMusicAuthError):
    pass


@dataclass(frozen=True, slots=True)
class AppleMusicCredentials:
    team_id: str
    key_id: str
    media_id: str | None = None
    private_key: str | None = None
    private_key_path: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AppleMusicCredentials":
        team_id = str(data.get("team_id") or "").strip()
        key_id = str(data.get("key_id") or "").strip()
        media_id = str(data.get("media_id") or "").strip() or None
        private_key = str(data.get("private_key") or "").strip() or None
        private_key_path = str(data.get("private_key_path") or "").strip() or None
        if not team_id or not key_id or not (private_key or private_key_path):
            raise AppleMusicConfigMissingError(
                "Apple Music credentials require team_id, key_id, and private_key or private_key_path."
            )
        return cls(
            team_id=team_id,
            key_id=key_id,
            media_id=media_id,
            private_key=private_key,
            private_key_path=private_key_path,
        )

    def to_json(self) -> str:
        data = {
            "team_id": self.team_id,
            "key_id": self.key_id,
        }
        if self.media_id:
            data["media_id"] = self.media_id
        if self.private_key:
            data["private_key"] = self.private_key
        if self.private_key_path:
            data["private_key_path"] = self.private_key_path
        return json.dumps(data, ensure_ascii=True, sort_keys=True)

    def private_key_text(self) -> str:
        if self.private_key:
            return self.private_key.replace("\\n", "\n")
        if not self.private_key_path:
            raise AppleMusicConfigMissingError("Apple Music private key is missing.")
        try:
            return Path(self.private_key_path).expanduser().read_text(encoding="utf-8")
        except OSError as exc:
            raise AppleMusicConfigMissingError(f"Could not read Apple Music private key: {exc}") from exc


def _load_json_or_file(value: str) -> dict[str, Any]:
    text = value.strip()
    if not text:
        raise AppleMusicConfigMissingError("Apple Music credentials cannot be empty.")
    if not text.startswith("{"):
        candidate = Path(text).expanduser()
        if candidate.exists():
            text = candidate.read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AppleMusicConfigMissingError(
            "Apple Music credentials must be JSON or a path to a JSON file."
        ) from exc
    if not isinstance(data, dict):
        raise AppleMusicConfigMissingError("Apple Music credentials must be a JSON object.")
    return data


def save_apple_music_credentials(value: str) -> Path:
    credentials = AppleMusicCredentials.from_dict(_load_json_or_file(value))
    return set_api_key(APPLE_MUSIC_PROVIDER, credentials.to_json())


def apple_music_credentials() -> AppleMusicCredentials:
    provider = get_provider_auth(load_auth_store(), APPLE_MUSIC_PROVIDER)
    if not provider or not provider.api_key:
        raise AppleMusicConfigMissingError(
            "Apple Music developer credentials are missing. Run `sonex auth set-key apple_music --api-key '<json-or-path>'`."
        )
    return AppleMusicCredentials.from_dict(_load_json_or_file(provider.api_key))


def save_apple_music_user_token(token: str) -> Path:
    value = token.strip()
    if not value:
        raise AppleMusicUserTokenRequiredError("Apple Music user token cannot be empty.")
    return set_oauth_token(APPLE_MUSIC_PROVIDER, OAuthToken(access_token=value))


def load_apple_music_user_token() -> OAuthToken | None:
    provider = get_provider_auth(load_auth_store(), APPLE_MUSIC_PROVIDER)
    return provider.oauth if provider else None


def ensure_apple_music_user_token() -> OAuthToken:
    token = load_apple_music_user_token()
    if not token or not token.access_token:
        raise AppleMusicUserTokenRequiredError(
            "Apple Music user token is missing. Run `sonex auth login apple_music --access-token <music-user-token>`."
        )
    return token


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _sign_es256(payload: bytes, private_key_text: str) -> bytes:
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec, utils
    except ModuleNotFoundError as exc:
        raise AppleMusicConfigMissingError(
            "Apple Music developer token signing requires the `cryptography` package."
        ) from exc

    private_key = serialization.load_pem_private_key(private_key_text.encode("utf-8"), password=None)
    if not isinstance(private_key, ec.EllipticCurvePrivateKey):
        raise AppleMusicConfigMissingError("Apple Music private key must be an EC .p8 private key.")
    signature = private_key.sign(payload, ec.ECDSA(hashes.SHA256()))
    r, s = utils.decode_dss_signature(signature)
    return r.to_bytes(32, "big") + s.to_bytes(32, "big")


def generate_developer_token(credentials: AppleMusicCredentials | None = None, now: int | None = None) -> str:
    resolved = credentials or apple_music_credentials()
    issued_at = int(now or time.time())
    expires_at = issued_at + APPLE_MUSIC_TOKEN_TTL_SECONDS
    cache_key = resolved.to_json()
    cached = _DEVELOPER_TOKEN_CACHE.get(cache_key)
    if cached and cached[1] - issued_at > 300:
        return cached[0]

    header = {"alg": "ES256", "kid": resolved.key_id, "typ": "JWT"}
    payload = {"iss": resolved.team_id, "iat": issued_at, "exp": expires_at}
    signing_input = ".".join(
        [
            _b64url(json.dumps(header, separators=(",", ":"), sort_keys=True).encode("utf-8")),
            _b64url(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")),
        ]
    )
    signature = _sign_es256(signing_input.encode("ascii"), resolved.private_key_text())
    token = f"{signing_input}.{_b64url(signature)}"
    _DEVELOPER_TOKEN_CACHE[cache_key] = (token, expires_at)
    return token


def apple_music_auth_headers(*, user: bool = False) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {generate_developer_token()}"}
    if user:
        headers["Music-User-Token"] = ensure_apple_music_user_token().access_token
    return headers


def apple_music_setup_message() -> str:
    return (
        "Create an Apple Media ID and Media Services private key in Apple Developer, then run "
        "`sonex auth set-key apple_music --api-key '<json-or-path>'` with team_id, key_id, media_id, "
        "and private_key_path. Import a Music User Token with "
        "`sonex auth login apple_music --access-token <music-user-token>` for user library and playback capabilities."
    )


def is_apple_music_provider(provider: str) -> bool:
    return normalize_provider(provider) == APPLE_MUSIC_PROVIDER
