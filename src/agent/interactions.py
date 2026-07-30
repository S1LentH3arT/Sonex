"""Durable, non-secret recovery marker for interrupted Agent interactions."""

from __future__ import annotations

import json
import os
from pathlib import Path

from src.log import sonex_home

INTERRUPTED_INTERACTION_MESSAGE = (
    "The previous Agent interaction was interrupted before completion. "
    "Try the request again."
)


def marker_path() -> Path:
    return sonex_home() / "agent" / "interrupted-interaction.json"


def mark_interrupted_interaction(*, path: Path | None = None) -> None:
    target = path or marker_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps({"version": 1, "interrupted": True}, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    os.chmod(temporary, 0o600)
    temporary.replace(target)
    os.chmod(target, 0o600)


def has_interrupted_interaction(*, path: Path | None = None) -> bool:
    target = path or marker_path()
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return False
    return isinstance(payload, dict) and payload.get("interrupted") is True


def clear_interrupted_interaction(*, path: Path | None = None) -> None:
    target = path or marker_path()
    try:
        target.unlink()
    except OSError:
        return
