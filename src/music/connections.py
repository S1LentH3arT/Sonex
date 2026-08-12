"""Non-secret music account connection registry."""

from __future__ import annotations

import json
import os
import re
import unicodedata
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from src.log import sonex_home


_ANSI_CSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_ANSI_OSC_RE = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
_WHITESPACE_RE = re.compile(r"\s+")
ACCOUNT_LABEL_MAX_DISPLAY_WIDTH = 64
_RETIRED_PROVIDER_IDS = frozenset({"apple_music"})


def _character_display_width(character: str) -> int:
    if unicodedata.combining(character):
        return 0
    if unicodedata.category(character).startswith("C"):
        return 0
    return 2 if unicodedata.east_asian_width(character) in {"F", "W"} else 1


def sanitize_account_label(value: object) -> str | None:
    """Return a single-line, terminal-safe account display label."""
    text = _ANSI_OSC_RE.sub("", str(value or ""))
    text = _ANSI_CSI_RE.sub("", text)
    text = "".join(
        character
        for character in text
        if not unicodedata.category(character).startswith("C") or character.isspace()
    )
    text = _WHITESPACE_RE.sub(" ", text).strip()
    if not text:
        return None

    width = 0
    cleaned: list[str] = []
    for character in text:
        character_width = _character_display_width(character)
        if width + character_width > ACCOUNT_LABEL_MAX_DISPLAY_WIDTH:
            break
        cleaned.append(character)
        width += character_width
    result = "".join(cleaned).rstrip()
    return result or None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True, slots=True)
class MusicConnectionRecord:
    provider_id: str
    status: str
    account_label: str | None
    connected_at: str
    checked_at: str
    reason: str | None = None


class MusicConnectionManager:
    """Persist provider identity and health without owning credentials."""

    def __init__(self, *, path: Path | None = None) -> None:
        self._path = path or sonex_home() / "music" / "connections.json"
        self._records: dict[str, MusicConnectionRecord] = {}
        self._preferred_provider_id: str | None = None
        self._load()

    @property
    def preferred_provider_id(self) -> str | None:
        return self._preferred_provider_id

    def record(self, provider_id: str) -> MusicConnectionRecord | None:
        return self._records.get(provider_id)

    def records(self) -> tuple[MusicConnectionRecord, ...]:
        return tuple(self._records[key] for key in sorted(self._records))

    def mark_connected(
        self,
        provider_id: str,
        *,
        account_label: str | None = None,
    ) -> MusicConnectionRecord:
        current = self._records.get(provider_id)
        checked_at = _now()
        record = MusicConnectionRecord(
            provider_id=provider_id,
            status="connected",
            account_label=sanitize_account_label(account_label),
            connected_at=current.connected_at if current else checked_at,
            checked_at=checked_at,
        )
        self._records[provider_id] = record
        if self._preferred_provider_id is None:
            self._preferred_provider_id = provider_id
        self._save()
        return record

    def mark_unavailable(self, provider_id: str, *, reason: str) -> MusicConnectionRecord:
        current = self._records.get(provider_id)
        checked_at = _now()
        record = MusicConnectionRecord(
            provider_id=provider_id,
            status="unavailable",
            account_label=current.account_label if current else None,
            connected_at=current.connected_at if current else checked_at,
            checked_at=checked_at,
            reason=reason,
        )
        self._records[provider_id] = record
        self._save()
        return record

    def remove(self, provider_id: str) -> None:
        """Forget one non-secret connection record and its preference."""
        self._records.pop(provider_id, None)
        if self._preferred_provider_id == provider_id:
            self._preferred_provider_id = None
        self._save()

    def _load(self) -> None:
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return
        if not isinstance(payload, dict) or payload.get("version") != 1:
            return
        preferred = payload.get("preferred_provider_id")
        self._preferred_provider_id = (
            preferred
            if isinstance(preferred, str) and preferred not in _RETIRED_PROVIDER_IDS
            else None
        )
        removed_retired_state = preferred in _RETIRED_PROVIDER_IDS
        records = payload.get("connections")
        if not isinstance(records, list):
            if removed_retired_state:
                self._save()
            return
        for item in records:
            if not isinstance(item, dict):
                continue
            try:
                record = MusicConnectionRecord(
                    provider_id=str(item["provider_id"]),
                    status=str(item["status"]),
                    account_label=(
                        sanitize_account_label(item["account_label"])
                        if item.get("account_label") is not None
                        else None
                    ),
                    connected_at=str(item["connected_at"]),
                    checked_at=str(item["checked_at"]),
                    reason=str(item["reason"]) if item.get("reason") is not None else None,
                )
            except KeyError:
                continue
            if record.provider_id in _RETIRED_PROVIDER_IDS:
                removed_retired_state = True
                continue
            self._records[record.provider_id] = record
        if removed_retired_state:
            self._save()

    def _save(self) -> None:
        payload: dict[str, object] = {
            "version": 1,
            "connections": [asdict(record) for record in self.records()],
        }
        if self._preferred_provider_id:
            payload["preferred_provider_id"] = self._preferred_provider_id
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=True, indent=2) + "\n",
            encoding="utf-8",
        )
        os.chmod(temporary, 0o600)
        temporary.replace(self._path)
        os.chmod(self._path, 0o600)
