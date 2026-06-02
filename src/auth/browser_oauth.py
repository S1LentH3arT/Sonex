from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
import webbrowser
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen

from src.auth.oauth import save_oauth_token
from src.auth.providers import normalize_provider
from src.log import sonex_home


class BrowserOAuthError(RuntimeError):
    pass


class BrowserOAuthUnsupportedError(BrowserOAuthError):
    pass


class BrowserOAuthConfigError(BrowserOAuthError):
    pass


@dataclass(frozen=True, slots=True)
class BrowserOAuthConfig:
    provider: str
    client_id: str
    client_secret: str | None
    auth_url: str
    token_url: str
    scopes: list[str]
    redirect_uri: str


GEMINI_DEFAULT_SCOPES = [
    "https://www.googleapis.com/auth/cloud-platform",
    "https://www.googleapis.com/auth/generative-language.retriever",
]


def browser_oauth_supported(provider: str) -> bool:
    return normalize_provider(provider) == "gemini"


def browser_oauth_requirements(provider: str) -> str:
    name = normalize_provider(provider)
    if name == "gemini":
        return (
            "Set SONEX_GEMINI_OAUTH_CLIENT_ID and optionally "
            "SONEX_GEMINI_OAUTH_CLIENT_SECRET, or add oauth_client_id/oauth_client_secret "
            "under providers.gemini in thinking.json."
        )
    return f"Provider '{name}' does not have browser OAuth wired in Sonex yet."


def run_browser_oauth(provider: str) -> None:
    config = load_browser_oauth_config(provider)
    state = secrets.token_urlsafe(24)
    verifier = _pkce_verifier()
    challenge = _pkce_challenge(verifier)
    authorize_url = _authorize_url(config, state=state, challenge=challenge)
    code = _wait_for_authorization_code(config.redirect_uri, authorize_url, state)
    token_info = _exchange_code(config, code=code, verifier=verifier)
    _save_token_info(config.provider, token_info, config.scopes)


def load_browser_oauth_config(provider: str) -> BrowserOAuthConfig:
    name = normalize_provider(provider)
    if name != "gemini":
        raise BrowserOAuthUnsupportedError(browser_oauth_requirements(name))

    provider_config = _provider_file_config(name)
    client_id = (
        os.getenv("SONEX_GEMINI_OAUTH_CLIENT_ID")
        or os.getenv("SONEX_GOOGLE_OAUTH_CLIENT_ID")
        or str(provider_config.get("oauth_client_id") or "")
    ).strip()
    client_secret = (
        os.getenv("SONEX_GEMINI_OAUTH_CLIENT_SECRET")
        or os.getenv("SONEX_GOOGLE_OAUTH_CLIENT_SECRET")
        or provider_config.get("oauth_client_secret")
    )
    if isinstance(client_secret, str):
        client_secret = client_secret.strip() or None

    if not client_id:
        raise BrowserOAuthConfigError(browser_oauth_requirements(name))

    scopes_raw = os.getenv("SONEX_GEMINI_OAUTH_SCOPES") or provider_config.get("oauth_scopes")
    scopes = _coerce_scopes(scopes_raw) or GEMINI_DEFAULT_SCOPES
    port = int(os.getenv("SONEX_GEMINI_OAUTH_PORT") or provider_config.get("oauth_port") or 9958)
    redirect_path = str(provider_config.get("oauth_redirect_path") or "/callback")

    return BrowserOAuthConfig(
        provider=name,
        client_id=client_id,
        client_secret=client_secret,
        auth_url="https://accounts.google.com/o/oauth2/v2/auth",
        token_url="https://oauth2.googleapis.com/token",
        scopes=scopes,
        redirect_uri=f"http://127.0.0.1:{port}{redirect_path}",
    )


def _provider_file_config(provider: str) -> dict[str, Any]:
    config_path = Path(os.getenv("SONEX_CONFIG_PATH") or (sonex_home() / "thinking.json")).expanduser()
    try:
        with config_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    providers = data.get("providers")
    if not isinstance(providers, dict):
        return {}
    value = providers.get(provider)
    return value if isinstance(value, dict) else {}


def _coerce_scopes(value: Any) -> list[str]:
    if isinstance(value, str):
        return [item for item in value.replace(",", " ").split() if item]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _pkce_verifier() -> str:
    return secrets.token_urlsafe(64)[:128]


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def _authorize_url(config: BrowserOAuthConfig, *, state: str, challenge: str) -> str:
    query = urlencode(
        {
            "client_id": config.client_id,
            "redirect_uri": config.redirect_uri,
            "response_type": "code",
            "scope": " ".join(config.scopes),
            "access_type": "offline",
            "include_granted_scopes": "true",
            "prompt": "consent",
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )
    return f"{config.auth_url}?{query}"


def _wait_for_authorization_code(redirect_uri: str, authorize_url: str, expected_state: str) -> str:
    redirect = urlparse(redirect_uri)
    host = redirect.hostname or "127.0.0.1"
    port = redirect.port or 80
    callback_path = redirect.path or "/callback"
    received: dict[str, str] = {}

    class OAuthCallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            params = parse_qs(parsed.query)
            if parsed.path != callback_path:
                self.send_response(404)
                self.end_headers()
                return

            if params.get("error"):
                received["error"] = params["error"][0]
            if params.get("code"):
                received["code"] = params["code"][0]
            if params.get("state"):
                received["state"] = params["state"][0]

            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"Sonex OAuth complete. You can return to the terminal.")

        def log_message(self, format: str, *args: object) -> None:
            return

    webbrowser.open(authorize_url)
    with HTTPServer((host, port), OAuthCallbackHandler) as server:
        server.timeout = 180
        server.handle_request()

    if received.get("error"):
        raise BrowserOAuthError(f"OAuth authorization failed: {received['error']}")
    if not received.get("code"):
        raise BrowserOAuthError("OAuth authorization timed out or returned no code.")
    if received.get("state") != expected_state:
        raise BrowserOAuthError("OAuth authorization state mismatch.")
    return received["code"]


def _exchange_code(config: BrowserOAuthConfig, *, code: str, verifier: str) -> dict[str, Any]:
    payload: dict[str, str] = {
        "client_id": config.client_id,
        "code": code,
        "code_verifier": verifier,
        "grant_type": "authorization_code",
        "redirect_uri": config.redirect_uri,
    }
    if config.client_secret:
        payload["client_secret"] = config.client_secret

    request = Request(
        config.token_url,
        data=urlencode(payload).encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:
            token_info = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise BrowserOAuthError(f"OAuth token exchange failed: {exc}") from exc
    if not isinstance(token_info, dict) or not token_info.get("access_token"):
        raise BrowserOAuthError("OAuth token exchange returned no access token.")
    return token_info


def _save_token_info(provider: str, token_info: dict[str, Any], default_scopes: list[str]) -> None:
    expires_in = token_info.get("expires_in")
    if expires_in not in (None, ""):
        expires_at_value = (
            datetime.fromtimestamp(time.time() + int(expires_in), timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )
    else:
        expires_at_value = None
    scope_value = token_info.get("scope")
    scopes = _coerce_scopes(scope_value) or default_scopes
    save_oauth_token(
        provider,
        access_token=str(token_info["access_token"]),
        refresh_token=token_info.get("refresh_token"),
        expires_at=expires_at_value,
        scopes=scopes,
    )
