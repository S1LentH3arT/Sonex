"""Browser oauth support for provider authentication and credential persistence.

Implements the browser_oauth module responsibilities used by Sonex runtime flows.
Key public entry points include BrowserOAuthError, BrowserOAuthUnsupportedError, BrowserOAuthConfigError, BrowserOAuthConfig, browser_oauth_supported.
"""

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
    """Represents browser o auth error.

    Encapsulates browser o auth error data and behavior used by Sonex runtime flows. Extends runtime error semantics.
    """
    pass


class BrowserOAuthUnsupportedError(BrowserOAuthError):
    """Represents browser o auth unsupported error.

    Encapsulates browser o auth unsupported error data and behavior used by Sonex runtime flows. Extends browser o auth error semantics.
    """
    pass


class BrowserOAuthConfigError(BrowserOAuthError):
    """Represents browser o auth config error.

    Encapsulates browser o auth config error data and behavior used by Sonex runtime flows. Extends browser o auth error semantics.
    """
    pass


@dataclass(frozen=True, slots=True)
class BrowserOAuthConfig:
    """Represents browser o auth config.

    Encapsulates browser o auth config data and behavior used by Sonex runtime flows.
    """
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
    """Browser oauth supported.

    Coordinates browser oauth supported logic for the surrounding Sonex flow.

    Args:
        provider: Input value used by the browser oauth supported operation.

    Returns:
        The computed result for browser oauth supported.
    """
    return normalize_provider(provider) == "gemini"


def browser_oauth_requirements(provider: str) -> str:
    """Browser oauth requirements.

    Coordinates browser oauth requirements logic for the surrounding Sonex flow.

    Args:
        provider: Input value used by the browser oauth requirements operation.

    Returns:
        The computed result for browser oauth requirements.
    """
    name = normalize_provider(provider)
    if name == "gemini":
        return (
            "Set SONEX_GEMINI_OAUTH_CLIENT_ID and optionally "
            "SONEX_GEMINI_OAUTH_CLIENT_SECRET, or add oauth_client_id/oauth_client_secret "
            "under providers.gemini in thinking.json."
        )
    return f"Provider '{name}' does not have browser OAuth wired in Sonex yet."


def run_browser_oauth(provider: str) -> None:
    """Run browser oauth.

    Coordinates run browser oauth logic for the surrounding Sonex flow.

    Args:
        provider: Input value used by the run browser oauth operation.

    Returns:
        The computed result for run browser oauth.
    """
    config = load_browser_oauth_config(provider)
    state = secrets.token_urlsafe(24)
    verifier = _pkce_verifier()
    challenge = _pkce_challenge(verifier)
    authorize_url = _authorize_url(config, state=state, challenge=challenge)
    code = _wait_for_authorization_code(config.redirect_uri, authorize_url, state)
    token_info = _exchange_code(config, code=code, verifier=verifier)
    _save_token_info(config.provider, token_info, config.scopes)


def load_browser_oauth_config(provider: str) -> BrowserOAuthConfig:
    """Load browser oauth config.

    Coordinates load browser oauth config logic for the surrounding Sonex flow.

    Args:
        provider: Input value used by the load browser oauth config operation.

    Returns:
        The computed result for load browser oauth config.
    """
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
    """Provider file config.

    Coordinates provider file config logic for the surrounding Sonex flow.

    Args:
        provider: Input value used by the provider file config operation.

    Returns:
        The computed result for provider file config.
    """
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
    """Coerce scopes.

    Coordinates coerce scopes logic for the surrounding Sonex flow.

    Args:
        value: Input value used by the coerce scopes operation.

    Returns:
        The computed result for coerce scopes.
    """
    if isinstance(value, str):
        return [item for item in value.replace(",", " ").split() if item]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _pkce_verifier() -> str:
    """Pkce verifier.

    Coordinates pkce verifier logic for the surrounding Sonex flow.

    Returns:
        The computed result for pkce verifier.
    """
    return secrets.token_urlsafe(64)[:128]


def _pkce_challenge(verifier: str) -> str:
    """Pkce challenge.

    Coordinates pkce challenge logic for the surrounding Sonex flow.

    Args:
        verifier: Input value used by the pkce challenge operation.

    Returns:
        The computed result for pkce challenge.
    """
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def _authorize_url(config: BrowserOAuthConfig, *, state: str, challenge: str) -> str:
    """Authorize url.

    Coordinates authorize url logic for the surrounding Sonex flow.

    Args:
        config: Input value used by the authorize url operation.
        state: Input value used by the authorize url operation.
        challenge: Input value used by the authorize url operation.

    Returns:
        The computed result for authorize url.
    """
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
    """Wait for authorization code.

    Coordinates wait for authorization code logic for the surrounding Sonex flow.

    Args:
        redirect_uri: Input value used by the wait for authorization code operation.
        authorize_url: Input value used by the wait for authorization code operation.
        expected_state: Input value used by the wait for authorization code operation.

    Returns:
        The computed result for wait for authorization code.
    """
    redirect = urlparse(redirect_uri)
    host = redirect.hostname or "127.0.0.1"
    port = redirect.port or 80
    callback_path = redirect.path or "/callback"
    received: dict[str, str] = {}

    class OAuthCallbackHandler(BaseHTTPRequestHandler):
        """Represents oauth callback handler.

        Encapsulates oauth callback handler data and behavior used by Sonex runtime flows. Extends base h t t p request handler semantics.
        """
        def do_GET(self) -> None:
            """Do get for oauth callback handler.

            Coordinates the do get method behavior while preserving oauth callback handler state and contracts.

            Returns:
                The computed result for do get.
            """
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
            """Log message for oauth callback handler.

            Coordinates the log message method behavior while preserving oauth callback handler state and contracts.

            Args:
                format: Input value used by the log message operation.
                args: Input value used by the log message operation.

            Returns:
                The computed result for log message.
            """
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
    """Exchange code.

    Coordinates exchange code logic for the surrounding Sonex flow.

    Args:
        config: Input value used by the exchange code operation.
        code: Input value used by the exchange code operation.
        verifier: Input value used by the exchange code operation.

    Returns:
        The computed result for exchange code.
    """
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
    """Save token info.

    Coordinates save token info logic for the surrounding Sonex flow.

    Args:
        provider: Input value used by the save token info operation.
        token_info: Input value used by the save token info operation.
        default_scopes: Input value used by the save token info operation.

    Returns:
        The computed result for save token info.
    """
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
