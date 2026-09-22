"""Process-wide proxy selection and persistent proxy configuration."""

from __future__ import annotations

import json
import os
import threading
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from src.log import sonex_home

PROXY_ENV = "SONEX_PROXY"
PROXY_FILE_NAME = "proxy.json"
SUPPORTED_SCHEMES = frozenset({"http", "socks5"})
DIRECT = "direct"
PROXY = "proxy"
CHECK_TIMEOUT_SECONDS = 5.0


class ProxyConfigError(ValueError):
    """Raised when proxy configuration is missing or invalid."""


@dataclass(frozen=True, slots=True)
class ProxyConfig:
    mode: str = DIRECT
    url: str | None = None
    source: str = "default"

    @property
    def enabled(self) -> bool:
        return self.mode == PROXY and bool(self.url)

    def to_dict(self) -> dict[str, str]:
        payload = {"mode": self.mode}
        if self.url:
            payload["url"] = self.url
        return payload


_lock = threading.RLock()
_active = ProxyConfig()
_original_proxy_env: dict[str, str | None] = {}


def proxy_path() -> Path:
    return sonex_home() / PROXY_FILE_NAME


def validate_proxy_url(value: str) -> str:
    text = str(value or "").strip()
    parsed = urllib.parse.urlsplit(text)
    if parsed.scheme.lower() not in SUPPORTED_SCHEMES:
        raise ProxyConfigError("Proxy URL must use http:// or socks5://.")
    if parsed.username or parsed.password:
        raise ProxyConfigError("Proxy authentication in the URL is not supported.")
    if parsed.path or parsed.query or parsed.fragment:
        raise ProxyConfigError("Proxy URL must contain only a host and port.")
    try:
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise ProxyConfigError("Proxy port must be a number from 1 to 65535.") from exc
    if not hostname:
        raise ProxyConfigError("Proxy URL must include a host.")
    if port is None or not 1 <= port <= 65535:
        raise ProxyConfigError("Proxy port must be a number from 1 to 65535.")
    host = hostname.lower()
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"{parsed.scheme.lower()}://{host}:{port}"


def _config_from_payload(payload: Any, *, source: str) -> ProxyConfig:
    if not isinstance(payload, dict):
        raise ProxyConfigError("proxy.json must contain a JSON object.")
    mode = str(payload.get("mode") or DIRECT).strip().lower()
    if mode not in {DIRECT, PROXY}:
        raise ProxyConfigError("Proxy mode must be 'proxy' or 'direct'.")
    raw_url = payload.get("url")
    if mode == PROXY:
        if not isinstance(raw_url, str) or not raw_url.strip():
            raise ProxyConfigError("Proxy mode requires a proxy URL.")
        return ProxyConfig(mode=PROXY, url=validate_proxy_url(raw_url), source=source)
    if raw_url is not None and not isinstance(raw_url, str):
        raise ProxyConfigError("Proxy URL must be a string.")
    return ProxyConfig(
        mode=DIRECT,
        url=validate_proxy_url(raw_url) if isinstance(raw_url, str) and raw_url.strip() else None,
        source=source,
    )


def load_saved_proxy() -> ProxyConfig:
    path = proxy_path()
    if not path.exists():
        return ProxyConfig()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise ProxyConfigError(f"Unable to read {path}: invalid JSON.") from exc
    return _config_from_payload(payload, source="file")


def save_proxy(config: ProxyConfig) -> Path:
    normalized = _config_from_payload(config.to_dict(), source="file")
    path = proxy_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(normalized.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    return path


def _environment_proxy() -> ProxyConfig | None:
    value = os.getenv(PROXY_ENV, "").strip()
    if not value:
        return None
    return ProxyConfig(mode=PROXY, url=validate_proxy_url(value), source="environment")


def resolve_startup_proxy(*, cli_proxy: str | None = None, cli_no_proxy: bool = False) -> ProxyConfig:
    if cli_proxy and cli_no_proxy:
        raise ProxyConfigError("--proxy and --no-proxy cannot be used together.")
    saved = load_saved_proxy()
    if cli_proxy:
        config = ProxyConfig(mode=PROXY, url=validate_proxy_url(cli_proxy), source="cli")
        save_proxy(config)
    elif cli_no_proxy:
        config = ProxyConfig(mode=DIRECT, url=saved.url, source="cli")
        save_proxy(config)
    else:
        config = saved
    environment = _environment_proxy()
    return environment or config


def active_proxy() -> ProxyConfig:
    with _lock:
        return _active


def _set_process_proxy_environment(config: ProxyConfig) -> None:
    global _original_proxy_env
    proxy_keys = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")
    no_proxy_keys = ("NO_PROXY", "no_proxy")
    if not _original_proxy_env:
        _original_proxy_env = {key: os.environ.get(key) for key in (*proxy_keys, *no_proxy_keys)}
    if config.enabled and config.url:
        for key in proxy_keys:
            os.environ[key] = config.url
        for key in no_proxy_keys:
            os.environ.pop(key, None)
    else:
        for key in proxy_keys:
            os.environ.pop(key, None)
        for key in no_proxy_keys:
            os.environ[key] = "*"


def apply_proxy(config: ProxyConfig) -> ProxyConfig:
    normalized = _config_from_payload(config.to_dict(), source=config.source)
    with _lock:
        global _active
        _active = normalized
        _set_process_proxy_environment(normalized)
        if normalized.enabled and normalized.url and normalized.url.startswith("http://"):
            urllib.request.install_opener(urllib.request.build_opener(urllib.request.ProxyHandler({"http": normalized.url, "https": normalized.url})))
        else:
            urllib.request.install_opener(urllib.request.build_opener(urllib.request.ProxyHandler({})))
    return normalized


def configure_startup_proxy(*, cli_proxy: str | None = None, cli_no_proxy: bool = False) -> ProxyConfig:
    return apply_proxy(resolve_startup_proxy(cli_proxy=cli_proxy, cli_no_proxy=cli_no_proxy))


def save_and_apply(mode: str, url: str | None = None) -> ProxyConfig:
    normalized_mode = str(mode or "").strip().lower()
    if normalized_mode == DIRECT and url is None:
        url = load_saved_proxy().url
    config = _config_from_payload({"mode": normalized_mode, "url": url}, source="panel")
    save_proxy(config)
    return apply_proxy(config)


def proxy_status() -> dict[str, Any]:
    current = active_proxy()
    environment = os.getenv(PROXY_ENV, "").strip()
    environment_override = False
    if environment:
        try:
            environment_override = not (current.enabled and current.url == validate_proxy_url(environment))
        except ProxyConfigError:
            environment_override = True
    return {
        "mode": current.mode,
        "url": current.url,
        "source": current.source,
        "environment_url": environment or None,
        "environment_override": environment_override,
    }


@contextmanager
def urlopen(request: Any, *, timeout: float | None = None) -> Iterator[Any]:
    """Open a URL through the active route, including SOCKS5 support."""
    current = active_proxy()
    if not current.enabled or not current.url or current.url.startswith("http://"):
        with urllib.request.urlopen(request, timeout=timeout) as response:
            yield response
        return
    try:
        import urllib3
        from urllib3.contrib.socks import SOCKSProxyManager
    except ImportError as exc:
        raise ProxyConfigError("SOCKS5 support requires the PySocks dependency.") from exc
    if isinstance(request, urllib.request.Request):
        url = request.full_url
        method = request.get_method()
        headers = dict(request.header_items())
        body = request.data
    else:
        url = str(request)
        method = "GET"
        headers = {}
        body = None
    manager = SOCKSProxyManager(current.url, num_pools=1, cert_reqs="CERT_REQUIRED")
    response = manager.request(method, url, body=body, headers=headers, preload_content=False, timeout=timeout or CHECK_TIMEOUT_SECONDS)
    try:
        yield response
    finally:
        response.release_conn()


@contextmanager
def direct_urlopen(request: Any, *, timeout: float | None = None) -> Iterator[Any]:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=timeout) as response:
        yield response


def check_proxy_target(url: str, *, proxy_url: str, timeout: float = CHECK_TIMEOUT_SECONDS) -> dict[str, Any]:
    try:
        normalized = validate_proxy_url(proxy_url)
        request = urllib.request.Request(url, method="GET")
        if normalized.startswith("http://"):
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({"http": normalized, "https": normalized}))
            response_context = opener.open(request, timeout=timeout)
        else:
            try:
                from urllib3.contrib.socks import SOCKSProxyManager
            except ImportError as exc:
                raise ProxyConfigError("SOCKS5 support requires the PySocks dependency.") from exc
            manager = SOCKSProxyManager(normalized, num_pools=1, cert_reqs="CERT_REQUIRED")
            response_context = manager.request("GET", request.full_url, preload_content=False, timeout=timeout)
        with response_context as response:
            status = int(getattr(response, "status", None) or getattr(response, "status_code", None) or 200)
        if status >= 400:
            return {"status": "failed", "phase": "target", "http_status": status, "message": f"Target returned HTTP {status}."}
        return {"status": "passed", "http_status": status}
    except urllib.error.HTTPError as exc:
        return {"status": "failed", "phase": "target", "http_status": int(exc.code), "message": f"Target returned HTTP {exc.code}."}
    except Exception as exc:
        return {"status": "failed", "phase": "proxy", "message": str(exc)[:240]}
