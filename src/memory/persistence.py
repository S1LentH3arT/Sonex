"""Filesystem transaction primitives for local memory storage."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import fcntl


class MemoryPersistence:
    """Own atomic JSON/file transactions while the store owns memory rules."""

    @staticmethod
    def atomic_write(path: Path, text: str) -> None:
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(path)

    @staticmethod
    def read_json(path: Path, default: Any) -> Any:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return default

    @staticmethod
    def read_json_checked(path: Path, default: Any) -> tuple[Any, bool]:
        """Read JSON while distinguishing a missing file from damaged metadata."""
        if not path.exists():
            return default, True
        try:
            return json.loads(path.read_text(encoding="utf-8")), True
        except (OSError, json.JSONDecodeError):
            return default, False

    def commit(
        self,
        payloads: dict[Path, str],
        journal_path: Path,
    ) -> None:
        transaction_id = str(uuid.uuid4())
        staged: dict[str, str] = {}
        for path, text in payloads.items():
            temporary = path.with_name(f".{path.name}.{transaction_id}.tmp")
            temporary.write_text(text, encoding="utf-8")
            staged[str(path)] = str(temporary)
        self.atomic_write(
            journal_path,
            json.dumps({"version": 1, "staged": staged}, ensure_ascii=False, indent=2) + "\n",
        )
        for destination, temporary in staged.items():
            Path(temporary).replace(Path(destination))
        journal_path.unlink(missing_ok=True)

    def recover(self, journal_path: Path) -> bool:
        journal, valid = self.read_json_checked(journal_path, {})
        if not valid:
            return False
        staged = journal.get("staged") if isinstance(journal, dict) else None
        if not isinstance(staged, dict):
            return True
        for destination, temporary in staged.items():
            path = Path(str(temporary))
            if path.exists():
                path.replace(Path(str(destination)))
        journal_path.unlink(missing_ok=True)
        return True

    @staticmethod
    def acquire_lock(path: Path) -> tuple[Any, bool]:
        handle = path.open("a+")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return handle, False
        return handle, True
