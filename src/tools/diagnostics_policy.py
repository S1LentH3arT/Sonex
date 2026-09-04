"""Privacy and payload policy shared by local audio diagnostics."""

from __future__ import annotations

import re
from typing import Any


SAFE_MPV_FIELDS = {
    "progress_ms",
    "wall_ms",
    "media_wall_ratio",
    "is_playing",
    "paused_for_cache",
    "current_ao",
    "ipc_ok",
    "error",
    "burst",
}
ALLOWED_AUDIO_METADATA = {
    "cache_hit",
    "candidate_count",
    "confidence_counts",
    "failure_class",
    "fallback_provider",
    "provider_elapsed_ms",
    "stable_30s",
    "started",
    "yt_dlp_version",
}
_URL_RE = re.compile(r"https?://[^\s\"']+", re.IGNORECASE)
_CREDENTIAL_RE = re.compile(
    r"(?i)(authorization|bearer|token|api[_-]?key|password|secret)([=: ]+)([^\s,;]+)"
)


def sanitize_diagnostic_text(value: str, *, media_location: str = "") -> str:
    sanitized = value.replace(media_location, "<media>") if media_location else value
    sanitized = _URL_RE.sub("<url>", sanitized)
    return _CREDENTIAL_RE.sub(r"\1\2<redacted>", sanitized)


def filter_audio_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in metadata.items()
        if key in ALLOWED_AUDIO_METADATA
    }
