"""Deterministic playback handoff after a user selects recording metadata."""

from __future__ import annotations

import inspect
import secrets
import time
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Mapping, Sequence


SELECTION_TTL_SECONDS = 300.0


@dataclass(frozen=True)
class RecordingIdentity:
    title: str
    artist: str
    album: str = ""
    duration_ms: int | None = None
    edition: str = ""
    metadata_source: str = "metadata"


@dataclass(frozen=True, slots=True)
class ProviderReadiness:
    """A bounded health snapshot used to rank authoritative playback routes."""

    provider: str
    configured: bool
    logged_in: bool
    subscription_ready: bool
    transport_ready: bool
    active_mode: bool = False
    session_verified: bool = False
    verified_success_rate: float = 0.0
    startup_latency_ms: int = 0
    capability_score: int = 0
    preferred: bool = False
    reason: str | None = None
    details: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @property
    def ready(self) -> bool:
        return (
            self.configured
            and self.logged_in
            and self.subscription_ready
            and self.transport_ready
        )


def rank_authoritative_providers(
    snapshots: Sequence[ProviderReadiness],
    *,
    requested_provider: str | None = None,
) -> list[ProviderReadiness]:
    """Return ready providers in deterministic playback-experience order."""
    requested = _normalized(requested_provider)
    eligible = [
        snapshot
        for snapshot in snapshots
        if snapshot.ready
        and (not requested or _normalized(snapshot.provider) == requested)
    ]
    return sorted(
        eligible,
        key=lambda snapshot: (
            0 if snapshot.active_mode else 1,
            0 if snapshot.session_verified else 1,
            -max(0.0, min(1.0, snapshot.verified_success_rate)),
            max(0, snapshot.startup_latency_ms),
            -max(0, snapshot.capability_score),
            0 if snapshot.preferred else 1,
            _normalized(snapshot.provider),
        ),
    )


@dataclass
class _Selection:
    session_id: str
    turn_id: str
    identity: RecordingIdentity
    expires_at: float
    used: bool = False


class SelectionStore:
    """Keep opaque, session-bound, one-use recording selections in memory."""

    def __init__(
        self,
        *,
        ttl_seconds: float = SELECTION_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.ttl_seconds = ttl_seconds
        self.clock = clock
        self._items: dict[str, _Selection] = {}

    def issue(
        self,
        *,
        session_id: str,
        turn_id: str,
        identity: RecordingIdentity,
    ) -> str:
        selection_ref = f"selection_{secrets.token_urlsafe(18)}"
        self._items[selection_ref] = _Selection(
            session_id=session_id,
            turn_id=turn_id,
            identity=identity,
            expires_at=self.clock() + self.ttl_seconds,
        )
        return selection_ref

    def consume(
        self,
        selection_ref: str,
        *,
        session_id: str,
        turn_id: str,
    ) -> RecordingIdentity:
        selection = self._items.get(selection_ref)
        if (
            selection is None
            or selection.used
            or selection.session_id != session_id
            or selection.turn_id != turn_id
            or self.clock() > selection.expires_at
        ):
            self._items.pop(selection_ref, None)
            raise SelectionExpiredError("The playback selection expired.")
        selection.used = True
        self._items.pop(selection_ref, None)
        return selection.identity


class SelectionExpiredError(RuntimeError):
    error_code = "SELECTION_EXPIRED"


def _normalized(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return " ".join(text.split())


def recording_identity_matches(
    selected: RecordingIdentity,
    candidate: Mapping[str, Any],
    *,
    duration_tolerance_ms: int = 5_000,
) -> bool:
    """Require the selected title, primary artist, edition cues, and duration."""
    title = candidate.get("title") or candidate.get("name")
    artist = candidate.get("artist")
    if _normalized(title) != _normalized(selected.title):
        return False
    if _normalized(artist) != _normalized(selected.artist):
        return False
    if selected.edition and _normalized(selected.edition) not in _normalized(title):
        return False
    candidate_duration = candidate.get("duration_ms")
    if selected.duration_ms is not None and candidate_duration is not None:
        try:
            if abs(int(candidate_duration) - selected.duration_ms) > duration_tolerance_ms:
                return False
        except (TypeError, ValueError):
            return False
    return True


PlaySelected = Callable[[RecordingIdentity], Awaitable[dict[str, Any]] | dict[str, Any]]


class MusicPlaybackCoordinator:
    """Consume a selection exactly once and invoke trusted playback routing."""

    def __init__(self, selections: SelectionStore | None = None) -> None:
        self.selections = selections or SelectionStore()

    async def play(
        self,
        selection_ref: str,
        *,
        session_id: str,
        turn_id: str,
        play_selected: PlaySelected,
    ) -> dict[str, Any]:
        try:
            identity = self.selections.consume(
                selection_ref,
                session_id=session_id,
                turn_id=turn_id,
            )
        except SelectionExpiredError as exc:
            return {
                "status": "playback_failed",
                "message": str(exc),
                "error_code": exc.error_code,
                "data": {},
            }
        result = play_selected(identity)
        if inspect.isawaitable(result):
            result = await result
        return dict(result)
