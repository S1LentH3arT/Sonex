"""Local Web session metadata alongside the existing transcript format."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.log import sonex_home
from src.session_id import create_session_id
from src.ws.transcript import _coerce_transcript_messages


class SessionStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or sonex_home() / "sessions").resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def directory(self, session_id: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", session_id):
            raise ValueError("Invalid session ID.")
        path = self.root / session_id
        if path.is_symlink() or path.resolve().parent != self.root:
            raise ValueError("Invalid session path.")
        return path

    def _file(self, session_id: str, name: str) -> Path:
        path = self.directory(session_id) / name
        if path.is_symlink():
            raise ValueError("Session files cannot be symbolic links.")
        return path

    def create(self) -> str:
        session_id = create_session_id()
        self.save(session_id, [])
        return session_id

    def read(self, session_id: str) -> list[dict[str, Any]]:
        path = self._file(session_id, "transcript.jsonl")
        if not path.exists():
            raise ValueError("Session not found.")
        messages = []
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                messages.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return _coerce_transcript_messages(messages)

    def save(self, session_id: str, messages: list[dict[str, Any]]) -> None:
        path = self._file(session_id, "transcript.jsonl")
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._file(session_id, "transcript.web.tmp")
        saved_at = datetime.now(timezone.utc).isoformat()
        content = "".join(json.dumps({**item, "session_id": session_id, "index": index, "saved_at": saved_at, "reason": "web"}, ensure_ascii=False) + "\n"
                          for index, item in enumerate(_coerce_transcript_messages(messages)))
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(path)

    def list(self) -> list[dict[str, Any]]:
        sessions = []
        for directory in self.root.iterdir():
            if not directory.is_dir() or directory.is_symlink():
                continue
            try:
                path = self._file(directory.name, "transcript.jsonl")
                if not path.exists():
                    continue
                sessions.append({"id": directory.name, "updated_at": path.stat().st_mtime})
            except (OSError, ValueError):
                continue
        # shortcut: first Web release lists the latest 100 sessions; add paginated
        # indexing when larger libraries need browsing beyond this window.
        sessions.sort(key=lambda item: item["updated_at"], reverse=True)
        for item in sessions[:100]:
            try:
                item["title"] = "New session"
                with self._file(item["id"], "transcript.jsonl").open(encoding="utf-8") as transcript:
                    for line in transcript:
                        try:
                            message = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if isinstance(message, dict) and message.get("role") == "user":
                            item["title"] = str(message.get("content") or "New session")[:60]
                            break
            except (OSError, ValueError):
                item["title"] = "Unable to read session"
        return sessions[:100]
