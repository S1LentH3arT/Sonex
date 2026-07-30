"""Persistent scheduling metadata for Spotify library mirror synchronization."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from src.log import sonex_home

SPOTIFY_LIBRARY_SYNC_STATE_VERSION = 1
SPOTIFY_LIBRARY_SYNC_TTL_SECONDS = 6 * 60 * 60
SPOTIFY_LIBRARY_SYNC_FAILURE_BACKOFF_SECONDS = 15 * 60
SPOTIFY_LIBRARY_FULL_RECONCILE_SECONDS = 7 * 24 * 60 * 60


@dataclass(slots=True)
class SpotifyLibrarySyncState:
    """Store durable Spotify mirror freshness and incremental-sync cursors."""

    version: int = SPOTIFY_LIBRARY_SYNC_STATE_VERSION
    last_attempt_at: float = 0.0
    last_success_at: float = 0.0
    next_retry_at: float = 0.0
    last_error_code: str = ""
    saved_tracks_cursor: str = ""
    last_full_saved_tracks_at: float = 0.0
    playlist_snapshots: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: Any) -> "SpotifyLibrarySyncState":
        """Create a validated state object from persisted JSON data."""
        if not isinstance(value, dict):
            return cls()
        snapshots = value.get("playlist_snapshots")
        if not isinstance(snapshots, dict):
            snapshots = {}
        return cls(
            last_attempt_at=_number(value.get("last_attempt_at")),
            last_success_at=_number(value.get("last_success_at")),
            next_retry_at=_number(value.get("next_retry_at")),
            last_error_code=str(value.get("last_error_code") or ""),
            saved_tracks_cursor=str(value.get("saved_tracks_cursor") or ""),
            last_full_saved_tracks_at=_number(value.get("last_full_saved_tracks_at")),
            playlist_snapshots={
                str(key): str(snapshot)
                for key, snapshot in snapshots.items()
                if str(key).strip() and str(snapshot).strip()
            },
        )

    def is_fresh(self, *, now: float | None = None) -> bool:
        """Return whether a successful mirror sync is still inside its TTL."""
        timestamp = time.time() if now is None else float(now)
        return self.last_success_at > 0 and timestamp - self.last_success_at < SPOTIFY_LIBRARY_SYNC_TTL_SECONDS

    def is_backing_off(self, *, now: float | None = None) -> bool:
        """Return whether a prior failure still suppresses another full sync."""
        timestamp = time.time() if now is None else float(now)
        return self.next_retry_at > timestamp

    def needs_full_saved_tracks_reconcile(self, *, now: float | None = None) -> bool:
        """Return whether saved tracks need a deletion-aware full reconciliation."""
        timestamp = time.time() if now is None else float(now)
        return (
            not self.saved_tracks_cursor
            or self.last_full_saved_tracks_at <= 0
            or timestamp - self.last_full_saved_tracks_at >= SPOTIFY_LIBRARY_FULL_RECONCILE_SECONDS
        )


def _number(value: Any) -> float:
    try:
        return max(0.0, float(value or 0))
    except (TypeError, ValueError):
        return 0.0


def spotify_library_sync_state_path() -> Path:
    """Return the application-owned Spotify library sync metadata path."""
    return sonex_home() / "cache" / "spotify" / "library_sync.json"


def load_spotify_library_sync_state(
    path: Path | None = None,
) -> SpotifyLibrarySyncState:
    """Load Spotify library synchronization metadata, tolerating corruption."""
    state_path = path or spotify_library_sync_state_path()
    try:
        value = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return SpotifyLibrarySyncState()
    return SpotifyLibrarySyncState.from_dict(value)


def save_spotify_library_sync_state(
    state: SpotifyLibrarySyncState,
    path: Path | None = None,
) -> None:
    """Atomically persist Spotify library synchronization metadata."""
    state_path = path or spotify_library_sync_state_path()
    try:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = state_path.with_suffix(".tmp")
        temporary_path.write_text(
            json.dumps(asdict(state), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary_path.replace(state_path)
    except OSError:
        # Freshness metadata is an optimization. Local playlist browsing must
        # remain usable when the cache directory is temporarily read-only.
        return


def retry_after_seconds(result: Any, *, fallback_seconds: float) -> float:
    """Extract a numeric Retry-After duration from a normalized tool result."""
    data = result.get("data") if isinstance(result, dict) else {}
    text = str((data or {}).get("retry_after") or "").strip().split(" ", 1)[0]
    try:
        return max(1.0, float(text))
    except ValueError:
        return max(1.0, float(fallback_seconds))
