"""Custom OpenAI-compatible connection validation and model discovery."""

from __future__ import annotations

import ipaddress
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from src.llm.transport import LLMTransportError, sanitize_error_message


_PROFILE_SLUG = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True, slots=True)
class CustomEndpoint:
    base_url: str
    insecure_remote: bool


def custom_profile_id(display_name: str) -> str:
    slug = _PROFILE_SLUG.sub("_", display_name.strip().lower()).strip("_")
    if not slug:
        raise ValueError("Connection name must contain a letter or number.")
    return f"custom__{slug}"


def normalize_custom_base_url(value: str) -> CustomEndpoint:
    text = value.strip().rstrip("/")
    parsed = urllib.parse.urlsplit(text)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Base URL must start with http:// or https:// and include a host.")
    if parsed.username or parsed.password:
        raise ValueError("Base URL must not contain a username or password.")
    if parsed.query or parsed.fragment:
        raise ValueError("Base URL must not contain query parameters or a fragment.")
    path = parsed.path.rstrip("/")
    if path.endswith("/chat/completions"):
        path = path[: -len("/chat/completions")]
    if not path:
        path = "/v1"
    normalized = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))
    return CustomEndpoint(
        base_url=normalized,
        insecure_remote=parsed.scheme == "http" and not _is_loopback(parsed.hostname),
    )


def discover_custom_models(
    base_url: str,
    *,
    api_key: str | None = None,
    timeout: float = 10,
) -> list[str]:
    request = urllib.request.Request(f"{base_url.rstrip('/')}/models", method="GET")
    if api_key:
        request.add_header("Authorization", f"Bearer {api_key}")
    data = _read_json(request, timeout)
    raw = data.get("data") if isinstance(data, dict) else None
    if not isinstance(raw, list):
        return []
    return sorted({
        str(item.get("id") or "").strip()
        for item in raw
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    })


def test_custom_connection(
    base_url: str,
    model: str,
    *,
    api_key: str | None = None,
    timeout: float = 20,
) -> None:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "Reply with OK."}],
        "max_tokens": 4,
        "temperature": 0,
    }
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
    )
    request.add_header("Content-Type", "application/json")
    if api_key:
        request.add_header("Authorization", f"Bearer {api_key}")
    data = _read_json(request, timeout)
    if not isinstance(data, dict) or not isinstance(data.get("choices"), list):
        raise LLMTransportError("Custom connection test returned an invalid Chat Completions response.")


def _read_json(request: urllib.request.Request, timeout: float) -> Any:
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise LLMTransportError(
            f"Custom connection request failed: {sanitize_error_message(detail)}"
        ) from exc
    except Exception as exc:
        raise LLMTransportError(
            f"Custom connection request failed: {sanitize_error_message(exc)}"
        ) from exc


def _is_loopback(hostname: str) -> bool:
    if hostname.casefold() == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False
