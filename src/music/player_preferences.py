"""Versioned persistence for the selected local Player Sink."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


PREFERENCES_VERSION = 1


@dataclass(frozen=True, slots=True)
class PlayerSinkPreferences:
    default_sink_id: str | None = None
    pending_sink_id: str | None = None

    @property
    def configured(self) -> bool:
        return self.default_sink_id is not None or self.pending_sink_id is not None

    @classmethod
    def from_payload(cls, payload: object) -> "PlayerSinkPreferences":
        if not isinstance(payload, dict) or payload.get("version") != PREFERENCES_VERSION:
            return cls()
        default = payload.get("default_sink_id")
        pending = payload.get("pending_sink_id")
        return cls(
            default_sink_id=default if isinstance(default, str) else None,
            pending_sink_id=pending if isinstance(pending, str) else None,
        )

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {"version": PREFERENCES_VERSION}
        if self.default_sink_id:
            payload["default_sink_id"] = self.default_sink_id
        if self.pending_sink_id:
            payload["pending_sink_id"] = self.pending_sink_id
        return payload


def read_player_preferences(path: Path) -> PlayerSinkPreferences:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return PlayerSinkPreferences()
    return PlayerSinkPreferences.from_payload(payload)


def write_player_preferences(path: Path, preferences: PlayerSinkPreferences) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(preferences.to_payload(), ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )
    os.chmod(temporary, 0o600)
    temporary.replace(path)
    os.chmod(path, 0o600)
