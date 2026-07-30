"""Runtime data types for Sonex websocket sessions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class PlayRequestParse:
    """Represents play request parse.

    Encapsulates play request parse data and behavior used by Sonex runtime flows.
    """
    is_play_request: bool
    query: str | None
    confidence: str
    rewritten_input: str

@dataclass(frozen=True, slots=True)
class AuthRuntimeState:
    """Represents auth runtime state.

    Encapsulates auth runtime state data and behavior used by Sonex runtime flows.
    """
    ready: bool
    provider: str
    model: str
    auth_type: str
    credential_source: str
    reason: str | None = None

    def to_event(self) -> dict[str, Any]:
        """Coordinates to event for the current Sonex flow.

        Typical use: Use this function when runtime code needs to event as part of a Sonex command, playback, auth, llm, or ui path.

        Example: to_event() -> returns the value used by the surrounding Sonex flow.
        """
        return {
            "type": "auth_state",
            "ready": self.ready,
            "provider": self.provider,
            "model": self.model,
            "auth_type": self.auth_type,
            "credential_source": self.credential_source,
            "reason": self.reason,
        }
