"""Secure persistence for OAuth refresh tokens."""

from __future__ import annotations

import json
import os
from pathlib import Path

from src.log import sonex_home

_SERVICE_NAME = "sonex.oauth"


def _fallback_path() -> Path:
    return sonex_home() / "oauth-secrets.json"


def _keyring_backend() -> object | None:
    try:
        import keyring

        backend = keyring.get_keyring()
        priority = getattr(backend, "priority", 0)
        if callable(priority):
            priority = priority()
        if float(priority) <= 0:
            return None
        return keyring
    except Exception:
        return None


def credential_storage_backend() -> str:
    """Return the refresh-token storage backend available on this machine."""
    return "keyring" if _keyring_backend() is not None else "file"


def store_refresh_token(provider: str, refresh_token: str) -> str:
    """Store a provider refresh token and return its opaque reference."""
    reference = f"refresh:{provider}"
    keyring = _keyring_backend()
    if keyring is not None:
        try:
            keyring.set_password(_SERVICE_NAME, reference, refresh_token)
            return f"keyring://{reference}"
        except Exception:
            pass

    path = _fallback_path()
    data: dict[str, str] = {}
    try:
        with path.open("r", encoding="utf-8") as stream:
            raw = json.load(stream)
            if isinstance(raw, dict):
                data = {str(key): str(value) for key, value in raw.items()}
    except (OSError, json.JSONDecodeError):
        pass
    data[reference] = refresh_token
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    with temp.open("w", encoding="utf-8") as stream:
        json.dump(data, stream, indent=2, ensure_ascii=True)
        stream.write("\n")
    os.chmod(temp, 0o600)
    temp.replace(path)
    os.chmod(path, 0o600)
    return f"file://{reference}"


def load_refresh_token(reference: str | None) -> str | None:
    """Resolve an opaque refresh-token reference."""
    if not reference:
        return None
    scheme, separator, key = reference.partition("://")
    if not separator or not key:
        return None
    if scheme == "keyring":
        keyring = _keyring_backend()
        if keyring is None:
            return None
        try:
            return keyring.get_password(_SERVICE_NAME, key)
        except Exception:
            return None
    if scheme != "file":
        return None
    try:
        with _fallback_path().open("r", encoding="utf-8") as stream:
            data = json.load(stream)
    except (OSError, json.JSONDecodeError):
        return None
    value = data.get(key) if isinstance(data, dict) else None
    return str(value) if value else None


def delete_refresh_token(reference: str | None) -> None:
    """Delete a stored refresh token if it exists."""
    if not reference:
        return
    scheme, separator, key = reference.partition("://")
    if not separator or not key:
        return
    if scheme == "keyring":
        keyring = _keyring_backend()
        if keyring is None:
            return
        try:
            keyring.delete_password(_SERVICE_NAME, key)
        except Exception:
            pass
        return
    if scheme != "file":
        return
    path = _fallback_path()
    try:
        with path.open("r", encoding="utf-8") as stream:
            data = json.load(stream)
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(data, dict) or data.pop(key, None) is None:
        return
    temp = path.with_suffix(".tmp")
    with temp.open("w", encoding="utf-8") as stream:
        json.dump(data, stream, indent=2, ensure_ascii=True)
        stream.write("\n")
    os.chmod(temp, 0o600)
    temp.replace(path)
    os.chmod(path, 0o600)
