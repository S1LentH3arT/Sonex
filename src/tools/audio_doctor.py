"""Explicit, read-only diagnostics for the online-audio runtime."""

from __future__ import annotations

import importlib.metadata
import importlib.util
import json
import os
import sqlite3
import time
import urllib.request
from pathlib import Path
from typing import Any

import yt_dlp

from src.log import sonex_home
from src.tools.online_provider_health import provider_cooldown
from src.tools.youtube_runtime import runtime_status, update_state

UPDATE_CHECK_TTL_SECONDS = 24 * 60 * 60


def _installed_version() -> str:
    try:
        return importlib.metadata.version("yt-dlp")
    except importlib.metadata.PackageNotFoundError:
        return str(getattr(getattr(yt_dlp, "version", None), "__version__", "unknown"))


def _latest_version() -> str | None:
    request = urllib.request.Request(
        "https://pypi.org/pypi/yt-dlp/json",
        headers={"Accept": "application/json", "User-Agent": "Sonex/1.0"},
    )
    with urllib.request.urlopen(request, timeout=3) as response:
        payload = json.load(response)
    info = payload.get("info") if isinstance(payload, dict) else None
    version = info.get("version") if isinstance(info, dict) else None
    return str(version) if version else None


def _cached_latest_version(cache_root: Path) -> str | None:
    path = cache_root / "yt-dlp-update-check.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if time.time() - float(payload.get("checked_at", 0)) < UPDATE_CHECK_TTL_SECONDS:
            version = payload.get("latest_version")
            return str(version) if version else None
    except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError):
        pass
    return None


def _save_latest_version(cache_root: Path, version: str | None) -> None:
    try:
        cache_root.mkdir(parents=True, exist_ok=True)
        (cache_root / "yt-dlp-update-check.json").write_text(
            json.dumps({"checked_at": time.time(), "latest_version": version}),
            encoding="utf-8",
        )
    except OSError:
        pass


def audio_doctor_report(*, check_updates: bool = True) -> dict[str, Any]:
    home = sonex_home()
    cache_root = home / "cache" / "songs"
    report: dict[str, Any] = {
        "yt_dlp_version": _installed_version(),
        "worker_module": importlib.util.find_spec("src.tools.yt_dlp_worker") is not None,
        "storage_path": str(cache_root),
        "storage_writable": os.access(cache_root if cache_root.exists() else home, os.W_OK),
        "cooldown": None,
        "latest_version": None,
        "update_available": False,
        "youtube_runtime": runtime_status(),
        "youtube_update": update_state(),
    }
    try:
        report["cooldown"] = provider_cooldown("youtube")
    except (OSError, PermissionError, sqlite3.Error):
        report["cooldown_error"] = "Audio state database is not writable."
    if check_updates:
        try:
            latest = _cached_latest_version(cache_root)
            if latest is None:
                latest = _latest_version()
                _save_latest_version(cache_root, latest)
            report["latest_version"] = latest
            report["update_available"] = bool(latest and latest != report["yt_dlp_version"])
        except Exception as exc:
            report["update_error"] = type(exc).__name__
    return report
