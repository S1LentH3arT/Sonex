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
APPLE_MUSIC_TOKEN_TTL_SECONDS = 60 * 60 * 24 * 30
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
        """From dict for apple music credentials.

        Coordinates the from dict method behavior while preserving apple music credentials state and contracts.

        Args:
            data: Input value used by the from dict operation.

        Returns:
            The computed result for from dict.
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
        """To json for apple music credentials.

        Coordinates the to json method behavior while preserving apple music credentials state and contracts.

        Returns:
            The computed result for to json.
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
        """Private key text for apple music credentials.

        Coordinates the private key text method behavior while preserving apple music credentials state and contracts.

        Returns:
            The computed result for private key text.
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
    """Load json or file.

    Coordinates load json or file logic for the surrounding Sonex flow.

    Args:
        value: Input value used by the load json or file operation.

    Returns:
        The computed result for load json or file.
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
    """Save apple music credentials.

    Coordinates save apple music credentials logic for the surrounding Sonex flow.

    Args:
        value: Input value used by the save apple music credentials operation.

    Returns:
        The computed result for save apple music credentials.
    """
    credentials = AppleMusicCredentials.from_dict(_load_json_or_file(value))
    return set_api_key(APPLE_MUSIC_PROVIDER, credentials.to_json())


def apple_music_credentials() -> AppleMusicCredentials:
    """Apple music credentials.

    Coordinates apple music credentials logic for the surrounding Sonex flow.

    Returns:
        The computed result for apple music credentials.
    """
    provider = get_provider_auth(load_auth_store(), APPLE_MUSIC_PROVIDER)
    if not provider or not provider.api_key:
        raise AppleMusicConfigMissingError(
            "Apple Music developer credentials are missing. Run `sonex auth set-key apple_music --api-key '<json-or-path>'`."
        )
    return AppleMusicCredentials.from_dict(_load_json_or_file(provider.api_key))


def save_apple_music_user_token(token: str) -> Path:
    """Save apple music user token.

    Coordinates save apple music user token logic for the surrounding Sonex flow.

    Args:
        token: Input value used by the save apple music user token operation.

    Returns:
        The computed result for save apple music user token.
    """
    value = token.strip()
    if not value:
        raise AppleMusicUserTokenRequiredError("Apple Music user token cannot be empty.")
    return set_oauth_token(APPLE_MUSIC_PROVIDER, OAuthToken(access_token=value))


def load_apple_music_user_token() -> OAuthToken | None:
    """Load apple music user token.

    Coordinates load apple music user token logic for the surrounding Sonex flow.

    Returns:
        The computed result for load apple music user token.
    """
    provider = get_provider_auth(load_auth_store(), APPLE_MUSIC_PROVIDER)
    return provider.oauth if provider else None


def ensure_apple_music_user_token() -> OAuthToken:
    """Ensure apple music user token.

    Coordinates ensure apple music user token logic for the surrounding Sonex flow.

    Returns:
        The computed result for ensure apple music user token.
    """
    token = load_apple_music_user_token()
    if not token or not token.access_token:
        raise AppleMusicUserTokenRequiredError(
            "Apple Music user token is missing. Run `sonex auth login apple_music --access-token <music-user-token>`."
        )
    return token


def _b64url(data: bytes) -> str:
    """B64url.

    Coordinates b64url logic for the surrounding Sonex flow.

    Args:
        data: Input value used by the b64url operation.

    Returns:
        The computed result for b64url.
    """
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _sign_es256(payload: bytes, private_key_text: str) -> bytes:
    """Sign es256.

    Coordinates sign es256 logic for the surrounding Sonex flow.

    Args:
        payload: Input value used by the sign es256 operation.
        private_key_text: Input value used by the sign es256 operation.

    Returns:
        The computed result for sign es256.
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
    """Generate developer token.

    Coordinates generate developer token logic for the surrounding Sonex flow.

    Args:
        credentials: Input value used by the generate developer token operation.
        now: Input value used by the generate developer token operation.

    Returns:
        The computed result for generate developer token.
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
    """Apple music auth headers.

    Coordinates apple music auth headers logic for the surrounding Sonex flow.

    Args:
        user: Input value used by the apple music auth headers operation.

    Returns:
        The computed result for apple music auth headers.
    """
    headers = {"Authorization": f"Bearer {generate_developer_token()}"}
    if user:
        headers["Music-User-Token"] = ensure_apple_music_user_token().access_token
    return headers


def apple_music_setup_message() -> str:
    """Apple music setup message.

    Coordinates apple music setup message logic for the surrounding Sonex flow.

    Returns:
        The computed result for apple music setup message.
    """
    return (
        "Create an Apple Media ID and Media Services private key in Apple Developer, then run "
        "`sonex auth set-key apple_music --api-key '<json-or-path>'` with team_id, key_id, media_id, "
        "and private_key_path. Import a Music User Token with "
        "`sonex auth login apple_music --access-token <music-user-token>` for user library and playback capabilities."
    )


def is_apple_music_provider(provider: str) -> bool:
    """Is apple music provider.

    Coordinates is apple music provider logic for the surrounding Sonex flow.

    Args:
        provider: Input value used by the is apple music provider operation.

    Returns:
        The computed result for is apple music provider.
    """
    return normalize_provider(provider) == APPLE_MUSIC_PROVIDER
