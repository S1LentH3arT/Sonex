"""Developer-token ports for the hosted broker and advanced local signing."""

from __future__ import annotations

import asyncio
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit

from src.auth.apple_music import apple_music_credentials, generate_developer_token
from src.auth.store import get_provider_auth, load_auth_store, set_provider_config

APPLE_DEVELOPER_TOKEN_TTL_SECONDS = 15 * 60
APPLE_DEVELOPER_TOKEN_REFRESH_WINDOW_SECONDS = 5 * 60
APPLE_DEVELOPER_TOKEN_REFRESH_RETRY_SECONDS = 60
APPLE_TOKEN_BROKER_TIMEOUT_SECONDS = 5
APPLE_TOKEN_BROKER_ENV = "SONEX_APPLE_TOKEN_BROKER_URL"
APPLE_TOKEN_SOURCE_ENV = "SONEX_APPLE_TOKEN_SOURCE"
APPLE_TOKEN_CONFIG_PROVIDER = "apple_mode"


class DeveloperTokenError(RuntimeError):
    """Normalized developer-token acquisition error."""


class DeveloperTokenNotConfiguredError(DeveloperTokenError):
    """Raised when Apple Mode has no developer-token source configured."""


@dataclass(frozen=True, slots=True)
class DeveloperTokenLease:
    token: str
    expires_at: int
    source: str

    def usable(self, now: int | None = None) -> bool:
        return bool(self.token and self.expires_at > int(now or time.time()))


class DeveloperTokenProvider(Protocol):
    async def fetch(self) -> DeveloperTokenLease:
        """Fetch a fresh token lease without persisting it."""


def normalize_apple_token_broker_url(value: str) -> str:
    """Validate and normalize a custom Apple developer-token broker URL."""
    broker_url = value.strip().rstrip("/")
    parsed = urlsplit(broker_url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise DeveloperTokenError(
            "Apple token service URL must be an http(s) URL without credentials, query parameters, or a fragment."
        )
    return broker_url


def save_apple_token_broker_url(value: str) -> None:
    """Persist a custom broker URL without persisting any developer token."""
    set_provider_config(
        APPLE_TOKEN_CONFIG_PROVIDER,
        base_url=normalize_apple_token_broker_url(value),
    )


def configured_apple_token_broker_url() -> str:
    """Resolve the broker URL from environment first, then local TUI configuration."""
    env_url = os.getenv(APPLE_TOKEN_BROKER_ENV, "").strip()
    if env_url:
        return normalize_apple_token_broker_url(env_url)
    provider = get_provider_auth(load_auth_store(), APPLE_TOKEN_CONFIG_PROVIDER)
    stored_url = str(provider.base_url or "").strip() if provider else ""
    if stored_url:
        return normalize_apple_token_broker_url(stored_url)
    return ""


class HttpDeveloperTokenProvider:
    def __init__(self, broker_url: str, timeout_seconds: float = APPLE_TOKEN_BROKER_TIMEOUT_SECONDS) -> None:
        self.broker_url = normalize_apple_token_broker_url(broker_url) if broker_url.strip() else ""
        self.timeout_seconds = timeout_seconds
        if not self.broker_url:
            raise DeveloperTokenNotConfiguredError(
                "Apple Mode token service is not configured. Run /connect or set "
                "SONEX_APPLE_TOKEN_BROKER_URL."
            )

    async def fetch(self) -> DeveloperTokenLease:
        return await asyncio.to_thread(self._fetch_sync)

    def _fetch_sync(self) -> DeveloperTokenLease:
        request = urllib.request.Request(
            f"{self.broker_url}/v1/apple-music/developer-token",
            headers={"Accept": "application/json", "User-Agent": "Sonex/1.0"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise DeveloperTokenError(f"Apple token service returned HTTP {exc.code}.") from exc
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise DeveloperTokenError("Apple token service is unavailable.") from exc
        if not isinstance(payload, dict):
            raise DeveloperTokenError("Apple token service returned an invalid response.")
        token = str(payload.get("token") or "").strip()
        try:
            expires_at = int(payload.get("expires_at") or 0)
        except (TypeError, ValueError):
            expires_at = 0
        lease = DeveloperTokenLease(token=token, expires_at=expires_at, source="broker")
        if not lease.usable():
            raise DeveloperTokenError("Apple token service returned an expired token.")
        return lease


class LocalSignerDeveloperTokenProvider:
    """Advanced development adapter; never selected unless explicitly enabled."""

    async def fetch(self) -> DeveloperTokenLease:
        issued_at = int(time.time())
        token = await asyncio.to_thread(generate_developer_token, apple_music_credentials(), issued_at)
        return DeveloperTokenLease(
            token=token,
            expires_at=issued_at + APPLE_DEVELOPER_TOKEN_TTL_SECONDS,
            source="local_signer",
        )


class DeveloperTokenManager:
    """Memory-only lease cache with safe refresh fallback."""

    def __init__(self, provider: DeveloperTokenProvider) -> None:
        self.provider = provider
        self._lease: DeveloperTokenLease | None = None
        self._retry_after = 0
        self._lock = asyncio.Lock()

    async def get(self, *, force_refresh: bool = False) -> DeveloperTokenLease:
        async with self._lock:
            now = int(time.time())
            lease = self._lease
            if (
                not force_refresh
                and lease is not None
                and lease.expires_at - now > APPLE_DEVELOPER_TOKEN_REFRESH_WINDOW_SECONDS
            ):
                return lease
            if (
                not force_refresh
                and lease is not None
                and lease.usable(now)
                and now < self._retry_after
            ):
                return lease
            last_error: Exception | None = None
            refreshed: DeveloperTokenLease | None = None
            for _attempt in range(2):
                try:
                    refreshed = await self.provider.fetch()
                    break
                except Exception as exc:
                    last_error = exc
            if refreshed is None:
                if lease is not None and lease.usable(now):
                    self._retry_after = now + min(
                        APPLE_DEVELOPER_TOKEN_REFRESH_RETRY_SECONDS,
                        max(1, lease.expires_at - now),
                    )
                    return lease
                assert last_error is not None
                raise last_error
            self._lease = refreshed
            self._retry_after = 0
            return refreshed

    def clear(self) -> None:
        self._lease = None
        self._retry_after = 0


def developer_token_provider_from_env() -> DeveloperTokenProvider:
    source = os.getenv(APPLE_TOKEN_SOURCE_ENV, "broker").strip().casefold()
    if source == "local":
        return LocalSignerDeveloperTokenProvider()
    if source not in {"", "broker"}:
        raise DeveloperTokenError(
            "SONEX_APPLE_TOKEN_SOURCE must be 'broker' or the advanced 'local' option."
        )
    return HttpDeveloperTokenProvider(configured_apple_token_broker_url())
