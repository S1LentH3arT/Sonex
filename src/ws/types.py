"""Runtime data types for Sonex websocket sessions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class PlayRequestParse:
    is_play_request: bool
    query: str | None
    confidence: str
    rewritten_input: str

@dataclass(frozen=True, slots=True)
class AuthRuntimeState:
    ready: bool
    provider: str
    model: str
    auth_type: str
    credential_source: str
    reason: str | None = None
    model_label: str | None = None

    def to_event(self) -> dict[str, Any]:
        return {
            "type": "auth_state",
            "ready": self.ready,
            "provider": self.provider,
            "model": self.model,
            "model_label": self.model_label,
            "auth_type": self.auth_type,
            "credential_source": self.credential_source,
            "reason": self.reason,
        }
