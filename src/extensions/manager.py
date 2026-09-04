"""Lifecycle model for Sonex's built-in music extensions."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import platform
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Awaitable, Callable

from src.auth.spotify import load_spotify_token, spotify_user_client
from src.auth.store import get_provider_auth, load_auth_store, remove_provider_method, set_api_key
from src.log import sonex_home
from src.tools.online_play import online_audio_config
from src.tools.youtube_runtime import local_runtime_check, runtime_status

logger = logging.getLogger(__name__)

STATE_VERSION = 1
EXTENSION_IDS = ("audius", "jamendo", "spotify", "youtube")
EXTENSION_NAMES = {
    "audius": "Audius",
    "jamendo": "Jamendo",
    "spotify": "Spotify",
    "youtube": "YouTube",
}
EXTENSION_DESCRIPTIONS = {
    "audius": "search and stream music from Audius",
    "jamendo": "discover and stream independent music from Jamendo",
    "spotify": "search Spotify and play on connected devices",
    "youtube": "search and stream audio through YouTube",
}


class ExtensionStatus(StrEnum):
    ENABLED = "enabled"
    NOT_CONFIGURED = "not_configured"
    DISABLED = "disabled"
    UNAVAILABLE = "unavailable"
    UNAPPLIED = "unapplied"
    UNSUPPORTED = "unsupported"
    WAITING = "waiting"


@dataclass(frozen=True, slots=True)
class BuiltinExtension:
    extension_id: str
    name: str
    description: str
    tags: tuple[str, ...] = ("Search", "Stream")


@dataclass(frozen=True, slots=True)
class ExtensionView:
    extension_id: str
    name: str
    description: str
    status: ExtensionStatus
    enabled: bool
    configured: bool
    tags: tuple[str, ...]
    reset_available: bool
    setup_available: bool
    reason_code: str | None = None
    operation: str | None = None
    revision: int = 0

    @property
    def signal(self) -> str:
        if self.status in {ExtensionStatus.UNAVAILABLE}:
            return "red"
        if self.status in {ExtensionStatus.UNAPPLIED}:
            return "yellow"
        if self.status in {ExtensionStatus.NOT_CONFIGURED, ExtensionStatus.DISABLED, ExtensionStatus.UNSUPPORTED}:
            return "gray"
        if self.status is ExtensionStatus.WAITING:
            return "hollow"
        return "green"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.extension_id,
            "name": self.name,
            "description": self.description,
            "status": self.status.value,
            "enabled": self.enabled,
            "configured": self.configured,
            "tags": list(self.tags),
            "reset_available": self.reset_available,
            "setup_available": self.setup_available,
            "signal": self.signal,
            "reason_code": self.reason_code,
            "operation": self.operation,
            "revision": self.revision,
        }


def builtin_extensions() -> tuple[BuiltinExtension, ...]:
    """Return the stable alphabetical built-in extension order."""
    return tuple(
        BuiltinExtension(extension_id, EXTENSION_NAMES[extension_id], EXTENSION_DESCRIPTIONS[extension_id])
        for extension_id in EXTENSION_IDS
    )


class ExtensionActionError(RuntimeError):
    """Raised when a lifecycle action is invalid for the current snapshot."""


class ExtensionRevisionConflict(ExtensionActionError):
    """Raised when a state-changing action was based on an old snapshot."""


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        os.chmod(path.parent, 0o700)
    fd, raw_path = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    temporary = Path(raw_path)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        with contextlib.suppress(OSError):
            os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        with contextlib.suppress(OSError):
            os.chmod(path, 0o600)
    finally:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _supported_platform() -> bool:
    system = platform.system().lower()
    machine = platform.machine().lower()
    if system == "linux" and machine in {"x86_64", "amd64", "aarch64", "arm64"}:
        return True
    # WSL reports Linux in normal Python installations; keep this explicit for
    # callers/tests that expose the environment marker.
    return bool(os.environ.get("WSL_INTEROP")) and machine in {"x86_64", "amd64", "aarch64", "arm64"}


class ExtensionManager:
    """Own non-secret extension lifecycle state and serialized actions."""

    SETUP_TIMEOUT_SECONDS = 600.0

    def __init__(self, *, path: Path | None = None) -> None:
        self.path = path or sonex_home() / "extensions" / "state.json"
        self._state = self._load_state()
        self._operations: dict[str, asyncio.Task[None]] = {}
        self._operations_lock = asyncio.Lock()
        self._setup_drafts: dict[tuple[str, str], dict[str, str]] = {}
        self._setup_revisions: dict[tuple[str, str], int] = {}
        self._setup_deadlines: dict[tuple[str, str], float] = {}
        self._retire_legacy_connections()

    @property
    def state_path(self) -> Path:
        return self.path

    def _load_state(self) -> dict[str, Any]:
        payload = _read_json(self.path)
        if payload.get("version") != STATE_VERSION:
            return {"version": STATE_VERSION, "extensions": {}}
        extensions = payload.get("extensions")
        if not isinstance(extensions, dict):
            extensions = {}
        for entry in extensions.values():
            if isinstance(entry, dict):
                entry.pop("operation", None)
        return {"version": STATE_VERSION, "extensions": extensions}

    def _save_state(self) -> None:
        _write_json(self.path, self._state)

    def _retire_legacy_connections(self) -> None:
        """Remove only the retired legacy connections file."""
        legacy_path = sonex_home() / "music" / "connections.json"
        with contextlib.suppress(FileNotFoundError, OSError):
            legacy_path.unlink()

    def _entry(self, extension_id: str) -> dict[str, Any]:
        extensions = self._state.setdefault("extensions", {})
        entry = extensions.get(extension_id)
        if not isinstance(entry, dict):
            entry = {}
            extensions[extension_id] = entry
        return entry

    @staticmethod
    def _env_value(*names: str) -> str | None:
        for name in names:
            value = os.environ.get(name, "").strip()
            if value:
                return value
        return None

    def _credential_info(self, extension_id: str) -> tuple[bool, bool, str | None]:
        """Return configured, locally-stored, and stable reason code."""
        if extension_id == "youtube":
            status = runtime_status(probe_provider=False)
            runtime_state = str(status.get("status") or "setup_required")
            configured = runtime_state in {"ready", "restart_required", "degraded"}
            reason = {
                "restart_required": "restart_required",
                "degraded": "degraded",
            }.get(runtime_state)
            return configured, False, reason if configured else runtime_state

        if extension_id == "spotify":
            env_configured = bool(self._env_value("SPOTIFY_CLIENT_ID") and self._env_value("SPOTIFY_CLIENT_SECRET"))
            local = False
            with contextlib.suppress(Exception):
                auth = get_provider_auth(load_auth_store(), "spotify")
                local = bool(auth and (auth.api_key or auth.oauth or auth.managed_auth))
            app_configured = env_configured or local
            token_configured = bool(load_spotify_token())
            return app_configured and token_configured, local, "credentials_missing" if not app_configured else "account_not_connected" if not token_configured else None

        env_names = {
            "jamendo": ("SONEX_JAMENDO_CLIENT_ID", "JAMENDO_CLIENT_ID"),
            "audius": ("SONEX_AUDIUS_API_KEY", "AUDIUS_API_KEY"),
        }[extension_id]
        env_configured = bool(self._env_value(*env_names))
        local = False
        with contextlib.suppress(Exception):
            auth = get_provider_auth(load_auth_store(), extension_id)
            local = bool(auth and auth.api_key)
        return env_configured or local, local, None if env_configured or local else "credentials_missing"

    def _view(self, extension: BuiltinExtension) -> ExtensionView:
        entry = self._entry(extension.extension_id)
        enabled = entry.get("enabled", True) is not False
        configured, local, reason_code = self._credential_info(extension.extension_id)
        saved_health = str(entry.get("health") or "")
        if configured and saved_health == "unavailable":
            reason_code = str(entry.get("reason_code") or "check_failed")
        elif configured and saved_health == "healthy":
            reason_code = None
        operation = str(entry.get("operation") or "") or None
        if operation:
            status = ExtensionStatus.WAITING
        elif extension.extension_id == "youtube" and not _supported_platform():
            status = ExtensionStatus.UNSUPPORTED
        elif not enabled:
            status = ExtensionStatus.DISABLED
        elif extension.extension_id == "youtube" and reason_code == "degraded":
            status = ExtensionStatus.UNAVAILABLE
        elif extension.extension_id == "youtube" and reason_code == "restart_required":
            status = ExtensionStatus.UNAPPLIED
        elif configured and saved_health == "unavailable":
            status = ExtensionStatus.UNAVAILABLE
        elif configured:
            status = ExtensionStatus.ENABLED
        else:
            status = ExtensionStatus.NOT_CONFIGURED
        return ExtensionView(
            extension_id=extension.extension_id,
            name=extension.name,
            description=extension.description,
            status=status,
            enabled=enabled,
            configured=configured,
            tags=extension.tags,
            reset_available=local and extension.extension_id != "youtube",
            setup_available=extension.extension_id != "youtube" or _supported_platform(),
            reason_code=reason_code,
            operation=operation,
            revision=int(entry.get("revision") or 0),
        )

    def snapshot(self) -> list[ExtensionView]:
        return [self._view(extension) for extension in builtin_extensions()]

    def actions(self, extension_id: str, *, armed_action: str | None = None) -> tuple[str, ...]:
        """Return the ordered actions legal for the current extension snapshot."""
        view = self.get(extension_id)
        if view.status in {ExtensionStatus.WAITING, ExtensionStatus.UNSUPPORTED}:
            return ()
        if armed_action == "reset":
            return ("confirm_reset",)
        if armed_action == "restart":
            return ("confirm_restart",)
        action = {
            ExtensionStatus.ENABLED: "disable",
            ExtensionStatus.NOT_CONFIGURED: "setup",
            ExtensionStatus.DISABLED: "enable",
            ExtensionStatus.UNAVAILABLE: "repair",
            ExtensionStatus.UNAPPLIED: "prepare_restart",
        }.get(view.status)
        actions = ["quick_check"]
        if action:
            actions.append(action)
        if view.reset_available:
            actions.append("prepare_reset")
        return tuple(actions)

    def get(self, extension_id: str) -> ExtensionView:
        for view in self.snapshot():
            if view.extension_id == extension_id:
                return view
        raise ExtensionActionError(f"Unknown extension: {extension_id}")

    def _check_revision(self, view: ExtensionView, expected_revision: int) -> None:
        if view.revision != expected_revision:
            raise ExtensionRevisionConflict(
                f"Extension '{view.extension_id}' revision is {view.revision}, not {expected_revision}."
            )

    def require_revision(self, extension_id: str, expected_revision: int) -> ExtensionView:
        view = self.get(extension_id)
        self._check_revision(view, expected_revision)
        return view

    def set_enabled(self, extension_id: str, enabled: bool, *, expected_revision: int) -> ExtensionView:
        view = self.get(extension_id)
        self._check_revision(view, expected_revision)
        if view.status is ExtensionStatus.UNSUPPORTED:
            raise ExtensionActionError("Extension is unsupported on this platform.")
        entry = self._entry(extension_id)
        entry["enabled"] = enabled
        entry["revision"] = int(entry.get("revision") or 0) + 1
        entry["updated_at"] = time.time()
        self._save_state()
        return self.get(extension_id)

    def reset_credentials(self, extension_id: str, *, expected_revision: int) -> ExtensionView:
        view = self.get(extension_id)
        self._check_revision(view, expected_revision)
        if not view.reset_available:
            raise ExtensionActionError("This extension has no locally stored credentials to reset.")
        if extension_id == "spotify":
            remove_provider_method("spotify", "api_key")
            remove_provider_method("spotify", "oauth")
        else:
            remove_provider_method(extension_id, "api_key")
        entry = self._entry(extension_id)
        entry["revision"] = int(entry.get("revision") or 0) + 1
        entry["updated_at"] = time.time()
        self._save_state()
        return self.get(extension_id)

    def record_health(self, extension_id: str, *, healthy: bool, reason_code: str | None = None) -> ExtensionView:
        entry = self._entry(extension_id)
        entry["last_check_at"] = time.time()
        entry["health"] = "healthy" if healthy else "unavailable"
        entry["reason_code"] = reason_code
        entry["revision"] = int(entry.get("revision") or 0) + 1
        self._save_state()
        return self.get(extension_id)

    def clear_health(self, extension_id: str, *, expected_revision: int | None = None) -> None:
        view = self.get(extension_id)
        if expected_revision is not None:
            self._check_revision(view, expected_revision)
        entry = self._entry(extension_id)
        entry.pop("health", None)
        entry.pop("reason_code", None)
        entry["revision"] = int(entry.get("revision") or 0) + 1
        entry["updated_at"] = time.time()
        self._save_state()

    async def run_action(
        self,
        extension_id: str,
        action: str,
        *,
        expected_revision: int,
        on_update: Callable[[ExtensionView], Awaitable[None]] | None = None,
    ) -> ExtensionView:
        """Run a lightweight lifecycle action with per-extension serialization."""
        view = self.get(extension_id)
        self._check_revision(view, expected_revision)
        legal_actions = self.actions(extension_id)
        if action not in legal_actions and not (action == "reset" and view.reset_available):
            raise ExtensionActionError(f"Action '{action}' is not available for '{extension_id}'.")
        if action == "disable":
            return self.set_enabled(extension_id, False, expected_revision=expected_revision)
        if action == "enable":
            view = self.set_enabled(extension_id, True, expected_revision=expected_revision)
            return await self._run_check(extension_id, expected_revision=view.revision, on_update=on_update)
        if action in {"quick_check", "repair"}:
            return await self._run_check(extension_id, expected_revision=expected_revision, on_update=on_update)
        if action == "reset":
            return self.reset_credentials(extension_id, expected_revision=expected_revision)
        raise ExtensionActionError(f"Unsupported extension action: {action}")

    def begin_setup(self, session_id: str, extension_id: str) -> None:
        key = (session_id, extension_id)
        self._setup_revisions[key] = self.get(extension_id).revision
        self._setup_drafts[key] = {}
        self._setup_deadlines[key] = time.monotonic() + self.SETUP_TIMEOUT_SECONDS

    def _setup_active(self, key: tuple[str, str]) -> bool:
        deadline = self._setup_deadlines.get(key)
        if deadline is None:
            return False
        if time.monotonic() >= deadline:
            self.discard_setup(*key)
            return False
        return key in self._setup_drafts

    def update_setup_draft(self, session_id: str, extension_id: str, key: str, value: str) -> None:
        setup_key = (session_id, extension_id)
        draft = self._setup_drafts.get(setup_key)
        if draft is None or not self._setup_active(setup_key):
            raise ExtensionActionError("Extension setup is not active for this session.")
        normalized_key = str(key).strip()
        if not normalized_key or not str(value).strip():
            raise ExtensionActionError("Extension setup input cannot be empty.")
        draft[normalized_key] = str(value).strip()

    def setup_draft(self, session_id: str, extension_id: str) -> dict[str, str]:
        key = (session_id, extension_id)
        if not self._setup_active(key):
            return {}
        return dict(self._setup_drafts[key])

    def setup_revision(self, session_id: str, extension_id: str) -> int:
        key = (session_id, extension_id)
        if not self._setup_active(key):
            raise ExtensionActionError("Extension setup is not active for this session.")
        try:
            return self._setup_revisions[key]
        except KeyError as exc:
            raise ExtensionActionError("Extension setup is not active for this session.") from exc

    def discard_setup(self, session_id: str, extension_id: str) -> None:
        key = (session_id, extension_id)
        self._setup_drafts.pop(key, None)
        self._setup_revisions.pop(key, None)
        self._setup_deadlines.pop(key, None)

    async def _run_check(
        self,
        extension_id: str,
        *,
        expected_revision: int | None = None,
        on_update: Callable[[ExtensionView], Awaitable[None]] | None,
    ) -> ExtensionView:
        async with self._operations_lock:
            if expected_revision is not None:
                self.require_revision(extension_id, expected_revision)
            existing = self._operations.get(extension_id)
            if existing and not existing.done():
                with contextlib.suppress(asyncio.CancelledError):
                    await existing
                return self.get(extension_id)
            entry = self._entry(extension_id)
            entry["operation"] = "quick_check"
            entry["revision"] = int(entry.get("revision") or 0) + 1
            self._save_state()
            if on_update:
                await on_update(self.get(extension_id))
            task = asyncio.create_task(self._check_worker(extension_id, on_update))
            self._operations[extension_id] = task
        await task
        return self.get(extension_id)

    async def _check_worker(
        self,
        extension_id: str,
        on_update: Callable[[ExtensionView], Awaitable[None]] | None,
    ) -> None:
        try:
            configured, _local, reason = self._credential_info(extension_id)
            if not configured:
                self.record_health(extension_id, healthy=False, reason_code=reason)
            else:
                healthy, check_code = await asyncio.wait_for(self._perform_check_async(extension_id), timeout=15.0)
                self.record_health(extension_id, healthy=healthy, reason_code=check_code)
        except Exception:
            logger.exception("extension quick check failed: %s", extension_id)
            self.record_health(extension_id, healthy=False, reason_code="check_failed")
        finally:
            entry = self._entry(extension_id)
            entry.pop("operation", None)
            self._save_state()
            if on_update:
                await on_update(self.get(extension_id))

    async def _perform_check_async(self, extension_id: str) -> tuple[bool, str | None]:
        """Run a provider probe without leaving a non-daemon executor thread."""
        loop = asyncio.get_running_loop()
        result: asyncio.Future[tuple[bool, str | None]] = loop.create_future()

        def worker() -> None:
            try:
                value = self._perform_check(extension_id)
            except Exception as exc:  # pragma: no cover - defensive thread boundary
                value = (False, type(exc).__name__)
            loop.call_soon_threadsafe(
                lambda: None if result.done() else result.set_result(value),
            )

        threading.Thread(target=worker, name=f"sonex-extension-check-{extension_id}", daemon=True).start()
        return await result

    def _perform_check(self, extension_id: str) -> tuple[bool, str | None]:
        """Perform the provider-specific minimum read-only health check."""
        try:
            if extension_id == "spotify":
                client = spotify_user_client(required_scopes={"user-read-private"}, requests_timeout=12, retries=0)
                account = client.current_user()
                product = str(account.get("product") or "").lower() if isinstance(account, dict) else ""
                return (product == "premium", None if product == "premium" else "premium_required")
            if extension_id == "youtube":
                local = local_runtime_check()
                if not local.get("healthy"):
                    return False, str(local.get("reason") or "runtime_check_failed")
                query = urllib.parse.urlencode({"search_query": "sonex"})
                request = urllib.request.Request(
                    f"https://www.youtube.com/results?{query}",
                    headers={"Accept": "text/html", "User-Agent": "Sonex/1.0"},
                )
                with urllib.request.urlopen(request, timeout=12) as response:
                    body = response.read(256 * 1024)
                return (b"videoId" in body, None if b"videoId" in body else "search_parse_failed")
            if extension_id == "jamendo":
                config = online_audio_config()
                client_id = config.jamendo_client_id
                if not client_id:
                    return False, "credentials_missing"
                params = urllib.parse.urlencode({"client_id": client_id, "format": "json", "limit": 1, "audioformat": "mp32"})
                with urllib.request.urlopen(f"https://api.jamendo.com/v3.0/tracks/?{params}", timeout=12) as response:
                    payload = json.loads(response.read(64 * 1024).decode("utf-8"))
                return (isinstance(payload, dict) and "results" in payload, None if isinstance(payload, dict) and "results" in payload else "invalid_response")
            if extension_id == "audius":
                config = online_audio_config()
                if not config.audius_api_key:
                    return False, "credentials_missing"
                params = urllib.parse.urlencode({"query": "sonex", "limit": 1, "api_key": config.audius_api_key})
                request = urllib.request.Request(f"https://api.audius.co/v1/tracks/search?{params}", headers={"Accept": "application/json", "User-Agent": "Sonex/1.0"})
                with urllib.request.urlopen(request, timeout=12) as response:
                    payload = json.loads(response.read(64 * 1024).decode("utf-8"))
                return (isinstance(payload, dict) and "data" in payload, None if isinstance(payload, dict) and "data" in payload else "invalid_response")
        except Exception as exc:
            logger.info("extension health check failed: %s (%s)", extension_id, type(exc).__name__)
            return False, "check_failed"
        return False, "unsupported"
