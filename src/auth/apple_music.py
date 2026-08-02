"""Apple music support for provider authentication and credential persistence.

Implements the apple_music module responsibilities used by Sonex runtime flows.
Key public entry points include AppleMusicAuthError, AppleMusicConfigMissingError, AppleMusicUserTokenRequiredError, AppleMusicCredentials, save_apple_music_credentials.
"""

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
APPLE_MUSIC_TOKEN_TTL_SECONDS = 15 * 60
_DEVELOPER_TOKEN_CACHE: dict[str, tuple[str, int]] = {}


class AppleMusicAuthError(RuntimeError):
    """Represents apple music auth error.

    Encapsulates apple music auth error data and behavior used by Sonex runtime flows. Extends runtime error semantics.
    """
    pass


class AppleMusicConfigMissingError(AppleMusicAuthError):
    """Represents apple music config missing error.

    Encapsulates apple music config missing error data and behavior used by Sonex runtime flows. Extends apple music auth error semantics.
    """
    pass


class AppleMusicUserTokenRequiredError(AppleMusicAuthError):
    """Represents apple music user token required error.

    Encapsulates apple music user token required error data and behavior used by Sonex runtime flows. Extends apple music auth error semantics.
    """
    pass


@dataclass(frozen=True, slots=True)
class AppleMusicCredentials:
    """Represents apple music credentials.

    Encapsulates apple music credentials data and behavior used by Sonex runtime flows.
    """
    team_id: str
    key_id: str
    media_id: str | None = None
    private_key: str | None = None
    private_key_path: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AppleMusicCredentials":
        """Coordinates from dict for the current Sonex flow.

        Typical use: Use this function when runtime code needs from dict as part of a Sonex command, playback, auth, llm, or ui path.

        Example: from_dict(data=...) -> returns the value used by the surrounding Sonex flow.
        """
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
        """Coordinates to json for the current Sonex flow.

        Typical use: Use this function when runtime code needs to json as part of a Sonex command, playback, auth, llm, or ui path.

        Example: to_json() -> returns the value used by the surrounding Sonex flow.
        """
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
        """Coordinates private key text for the current Sonex flow.

        Typical use: Use this function when runtime code needs private key text as part of a Sonex command, playback, auth, llm, or ui path.

        Example: private_key_text() -> returns the value used by the surrounding Sonex flow.
        """
        if self.private_key:
            return self.private_key.replace("\\n", "\n")
        if not self.private_key_path:
            raise AppleMusicConfigMissingError("Apple Music private key is missing.")
        try:
            return Path(self.private_key_path).expanduser().read_text(encoding="utf-8")
        except OSError as exc:
            raise AppleMusicConfigMissingError(f"Could not read Apple Music private key: {exc}") from exc


def _load_json_or_file(value: str) -> dict[str, Any]:
    """Prepares load json or file for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs load json or file without duplicating the local rules.

    Example: _load_json_or_file(value=...) -> returns the value used by the surrounding Sonex flow.
    """
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
    """Persists apple music credentials for later use.

    Typical use: Use this function when runtime code needs save apple music credentials as part of a Sonex command, playback, auth, llm, or ui path.

    Example: save_apple_music_credentials(value=...) -> returns the value used by the surrounding Sonex flow.
    """
    credentials = AppleMusicCredentials.from_dict(_load_json_or_file(value))
    return set_api_key(APPLE_MUSIC_PROVIDER, credentials.to_json())


def apple_music_credentials() -> AppleMusicCredentials:
    """Coordinates apple music credentials for the current Sonex flow.

    Typical use: Use this function when runtime code needs apple music credentials as part of a Sonex command, playback, auth, llm, or ui path.

    Example: apple_music_credentials() -> returns the value used by the surrounding Sonex flow.
    """
    provider = get_provider_auth(load_auth_store(), APPLE_MUSIC_PROVIDER)
    if not provider or not provider.api_key:
        raise AppleMusicConfigMissingError(
            "Apple Music developer credentials are missing. Open /apple to configure Apple Music."
        )
    return AppleMusicCredentials.from_dict(_load_json_or_file(provider.api_key))


def save_apple_music_user_token(token: str) -> Path:
    """Persists apple music user token for later use.

    Typical use: Use this function when runtime code needs save apple music user token as part of a Sonex command, playback, auth, llm, or ui path.

    Example: save_apple_music_user_token(token=...) -> returns the value used by the surrounding Sonex flow.
    """
    value = token.strip()
    if not value:
        raise AppleMusicUserTokenRequiredError("Apple Music user token cannot be empty.")
    return set_oauth_token(APPLE_MUSIC_PROVIDER, OAuthToken(access_token=value))


def load_apple_music_user_token() -> OAuthToken | None:
    """Loads apple music user token from persistent state.

    Typical use: Use this function when runtime code needs load apple music user token as part of a Sonex command, playback, auth, llm, or ui path.

    Example: load_apple_music_user_token() -> returns the value used by the surrounding Sonex flow.
    """
    provider = get_provider_auth(load_auth_store(), APPLE_MUSIC_PROVIDER)
    return provider.oauth if provider else None


def ensure_apple_music_user_token() -> OAuthToken:
    """Coordinates ensure apple music user token for the current Sonex flow.

    Typical use: Use this function when runtime code needs ensure apple music user token as part of a Sonex command, playback, auth, llm, or ui path.

    Example: ensure_apple_music_user_token() -> returns the value used by the surrounding Sonex flow.
    """
    token = load_apple_music_user_token()
    if not token or not token.access_token:
        raise AppleMusicUserTokenRequiredError(
            "Apple Music user token is missing. Open /apple to authorize Apple Music."
        )
    return token


def _b64url(data: bytes) -> str:
    """Prepares b64url for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs b64url without duplicating the local rules.

    Example: _b64url(data=...) -> returns the value used by the surrounding Sonex flow.
    """
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _sign_es256(payload: bytes, private_key_text: str) -> bytes:
    """Prepares sign es256 for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs sign es256 without duplicating the local rules.

    Example: _sign_es256(payload=..., private_key_text=...) -> returns the value used by the surrounding Sonex flow.
    """
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
    """Coordinates generate developer token for the current Sonex flow.

    Typical use: Use this function when runtime code needs generate developer token as part of a Sonex command, playback, auth, llm, or ui path.

    Example: generate_developer_token(credentials=..., now=...) -> returns the value used by the surrounding Sonex flow.
    """
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
    """Coordinates apple music auth headers for the current Sonex flow.

    Typical use: Use this function when runtime code needs apple music auth headers as part of a Sonex command, playback, auth, llm, or ui path.

    Example: apple_music_auth_headers(user=...) -> returns the value used by the surrounding Sonex flow.
    """
    headers = {"Authorization": f"Bearer {generate_developer_token()}"}
    if user:
        headers["Music-User-Token"] = ensure_apple_music_user_token().access_token
    return headers


def apple_music_setup_message() -> str:
    """Coordinates apple music setup message for the current Sonex flow.

    Typical use: Use this function when runtime code needs apple music setup message as part of a Sonex command, playback, auth, llm, or ui path.

    Example: apple_music_setup_message() -> returns the value used by the surrounding Sonex flow.
    """
    return (
        "Run /apple to authorize Apple Music in Sonex's local MusicKit companion. "
        "The Music User Token stays in that browser and must not be imported into Sonex. "
        "Advanced development can set SONEX_APPLE_TOKEN_SOURCE=local and configure local signing credentials."
    )


def is_apple_music_provider(provider: str) -> bool:
    """Checks whether is apple music provider is true for the supplied input.

    Typical use: Use this function when runtime code needs is apple music provider as part of a Sonex command, playback, auth, llm, or ui path.

    Example: is_apple_music_provider(provider=...) -> returns the value used by the surrounding Sonex flow.
    """
    return normalize_provider(provider) == APPLE_MUSIC_PROVIDER
