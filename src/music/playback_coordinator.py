"""Deterministic playback handoff after a user selects recording metadata."""

from __future__ import annotations

import inspect
import re
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
            0 if snapshot.preferred else 1,
            0 if snapshot.active_mode else 1,
            0 if snapshot.session_verified else 1,
            0 if _normalized(snapshot.provider) == "spotify" else 1,
            -max(0.0, min(1.0, snapshot.verified_success_rate)),
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


class PlaybackCandidateError(RuntimeError):
    error_code = "NATIVE_CANDIDATE_INVALID"


def _normalized(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return " ".join(text.split())


_FEATURE_TITLE_SUFFIX_RE = re.compile(
    r"\s*[\(\[（【](?:feat\.?|ft\.?|featuring)\s+[^\)\]）】]+[\)\]）】]\s*$",
    re.IGNORECASE,
)
_PRIMARY_ARTIST_SEPARATOR_RE = re.compile(
    r"\s*(?:,|，|、|;|；|\bfeat\.?\b|\bft\.?\b|\bfeaturing\b)\s*",
    re.IGNORECASE,
)


def _recording_title(value: Any) -> str:
    """Normalize only featured-artist title suffixes, preserving edition cues."""
    return _normalized(_FEATURE_TITLE_SUFFIX_RE.sub("", str(value or "")))


def _primary_artist(value: Any) -> str:
    """Return the first credited artist for cross-catalog identity matching."""
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    return _normalized(_PRIMARY_ARTIST_SEPARATOR_RE.split(text, maxsplit=1)[0])


def recording_identity_matches(
    selected: RecordingIdentity,
    candidate: Mapping[str, Any],
    *,
    duration_tolerance_ms: int = 5_000,
) -> bool:
    """Require the selected title, primary artist, edition cues, and duration."""
    title = candidate.get("title") or candidate.get("name")
    artist = candidate.get("artist")
    if _recording_title(title) != _recording_title(selected.title):
        return False
    if _primary_artist(artist) != _primary_artist(selected.artist):
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
RouteCallback = Callable[[ProviderReadiness], Awaitable[Any] | Any]
RecoverCallback = Callable[[str, ProviderReadiness | None], Awaitable[ProviderReadiness | None] | ProviderReadiness | None]
SourceProbe = Callable[[], Awaitable[Sequence[ProviderReadiness]] | Sequence[ProviderReadiness]]
SourceChooser = Callable[[list[str], str | None], Awaitable[str | None] | str | None]
StopCallback = Callable[[str], Awaitable[Any] | Any]
FailureCallback = Callable[[str, Exception], Awaitable[Any] | Any]
CandidateSearch = Callable[[str], Awaitable[Sequence[Mapping[str, Any]]] | Sequence[Mapping[str, Any]]]


class MusicPlaybackCoordinator:
    """Own playback selection consumption and authoritative route decisions."""

    def __init__(self, selections: SelectionStore | None = None) -> None:
        self.selections = selections or SelectionStore()

    async def select_source(
        self,
        *,
        requested_provider: str | None = None,
        hard_provider: bool = False,
        exclude: str | None = None,
        probe: SourceProbe,
        recover: RecoverCallback,
        choose: SourceChooser,
        active_provider: str | None = None,
        preferred_provider: str | None = None,
    ) -> str | None:
        """Resolve the catalog for the next search before any catalog query."""
        requested = _normalized(requested_provider)
        excluded = _normalized(exclude)
        if requested in {"online", "metadata", "online_audio"}:
            return None if excluded == "online" else "online"

        snapshots = probe()
        if inspect.isawaitable(snapshots):
            snapshots = await snapshots
        by_provider = {
            _normalized(snapshot.provider): snapshot
            for snapshot in snapshots
        }
        if requested == "spotify":
            snapshot = by_provider.get(requested)
            if snapshot is not None and snapshot.ready:
                return None if excluded == requested else requested
            recovered = recover(requested, snapshot)
            if inspect.isawaitable(recovered):
                recovered = await recovered
            if recovered is not None and recovered.ready and excluded != requested:
                return requested
            return None

        current = _normalized(active_provider)
        if current and current != excluded:
            snapshot = by_provider.get(current)
            if snapshot is not None and snapshot.ready:
                return current

        preferred = _normalized(preferred_provider)
        if preferred and preferred != excluded:
            snapshot = by_provider.get(preferred)
            if snapshot is not None and snapshot.ready:
                return preferred

        sources = [
            provider
            for provider in ("spotify",)
            if provider != excluded
            and by_provider.get(provider) is not None
            and by_provider[provider].ready
        ]
        if excluded != "online":
            sources.append("online")
        if not sources:
            return None
        if "spotify" not in sources:
            return "online"
        selected = choose(sources, excluded or None)
        if inspect.isawaitable(selected):
            selected = await selected
        return selected

    async def activate_source(
        self,
        provider: str,
        *,
        probe: SourceProbe,
        recover: RecoverCallback,
        ensure: RouteCallback,
    ) -> ProviderReadiness | None:
        """Resolve one provider's current readiness and activate its mode."""
        normalized = _normalized(provider)
        snapshots = probe()
        if inspect.isawaitable(snapshots):
            snapshots = await snapshots
        readiness = next(
            (snapshot for snapshot in snapshots if _normalized(snapshot.provider) == normalized),
            None,
        )
        if readiness is None or not readiness.ready:
            return None
        if normalized == "spotify" and not readiness.details.get("active_device"):
            recovered = recover(normalized, readiness)
            if inspect.isawaitable(recovered):
                recovered = await recovered
            if recovered is None:
                return None
            readiness = recovered
        mode_ready = ensure(readiness)
        if inspect.isawaitable(mode_ready):
            mode_ready = await mode_ready
        return readiness if mode_ready else None

    async def handoff(
        self,
        previous_provider: str | None,
        new_provider: str | None,
        *,
        stop_previous: StopCallback,
        report_failure: FailureCallback | None = None,
    ) -> None:
        """Stop a different active source, without blocking the new source."""
        previous = _normalized(previous_provider)
        new = _normalized(new_provider)
        if not previous or previous == new:
            return
        try:
            stopped = stop_previous(previous)
            if inspect.isawaitable(stopped):
                await stopped
        except Exception as exc:
            if report_failure is None:
                return
            try:
                reported = report_failure(previous, exc)
                if inspect.isawaitable(reported):
                    await reported
            except Exception:
                return

    async def resolve_native_candidate(
        self,
        identity: RecordingIdentity,
        candidate: Mapping[str, Any],
        *,
        search_candidates: CandidateSearch,
        native_uri_prefix: str = "spotify:track:",
    ) -> dict[str, Any]:
        """Return a playable native candidate or reject an unverifiable match."""
        direct_uri = candidate.get("uri") or candidate.get("spotify_uri")
        if isinstance(direct_uri, str) and direct_uri.startswith(native_uri_prefix):
            return dict(candidate)
        query = f"{identity.artist} {identity.title}".strip()
        matches = search_candidates(query)
        if inspect.isawaitable(matches):
            matches = await matches
        exact = next(
            (item for item in matches if recording_identity_matches(identity, item)),
            None,
        )
        if exact is None:
            raise PlaybackCandidateError(
                "The selected recording has no exact playable native match."
            )
        uri = exact.get("uri") or exact.get("ref")
        if not isinstance(uri, str) or not uri.startswith(native_uri_prefix):
            raise PlaybackCandidateError("The native match has no playable URI.")
        return dict(exact)

    async def route_authoritative(
        self,
        snapshots: Sequence[ProviderReadiness],
        *,
        requested_provider: str | None = None,
        hard_provider: bool = False,
        confirm_route: RouteCallback,
        activate_route: RouteCallback,
        play_route: RouteCallback,
        recover_route: RecoverCallback | None = None,
        provider_label: Callable[[str], str] | None = None,
    ) -> dict[str, Any]:
        """Try ranked ready routes while keeping fallback policy behind one seam."""
        label_for = provider_label or (lambda provider: provider.title())
        requested = _normalized(requested_provider)
        ranked = rank_authoritative_providers(
            snapshots,
            requested_provider=requested if hard_provider else None,
        )
        if hard_provider and requested and not ranked and recover_route:
            requested_snapshot = next(
                (snapshot for snapshot in snapshots if _normalized(snapshot.provider) == requested),
                None,
            )
            recovered = recover_route(requested, requested_snapshot)
            if inspect.isawaitable(recovered):
                recovered = await recovered
            if recovered is not None:
                ranked = [recovered]
        failures: list[str] = []
        for snapshot in ranked:
            label = label_for(snapshot.provider)
            if not snapshot.active_mode and not snapshot.session_verified:
                allowed = confirm_route(snapshot)
                if inspect.isawaitable(allowed):
                    allowed = await allowed
                if not allowed:
                    failures.append(f"{label} was rejected.")
                    if hard_provider:
                        break
                    continue
            mode_ready = activate_route(snapshot)
            if inspect.isawaitable(mode_ready):
                mode_ready = await mode_ready
            if not mode_ready:
                failures.append(snapshot.reason or f"{label} Mode is unavailable.")
                if hard_provider:
                    break
                continue
            result = play_route(snapshot)
            if inspect.isawaitable(result):
                result = await result
            result = dict(result) if isinstance(result, Mapping) else {
                "status": "playback_failed",
                "message": f"{label} playback failed.",
                "data": {"provider": snapshot.provider},
            }
            if result.get("status") == "playback_completed":
                return result
            failures.append(str(result.get("message") or "Playback failed."))
            if hard_provider:
                break
        message = (
            " ".join(dict.fromkeys(failures))
            if failures
            else (
                f"{label_for(requested)} is not ready."
                if hard_provider and requested
                else "No authoritative provider is ready."
            )
        )
        return {
            "status": "playback_failed",
            "message": message,
            "error_code": "AUTHORITATIVE_PROVIDER_UNAVAILABLE",
            "data": {
                "provider": requested or None,
                "attempted": [snapshot.provider for snapshot in ranked],
            },
        }

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
