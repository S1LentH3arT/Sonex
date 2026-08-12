"""Single-owner lifecycle coordination for persistent playback provider modes."""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Awaitable, Callable

from src.log import sonex_home

PROVIDER_MODE_STATE_VERSION = 1


class ProviderMode(StrEnum):
    NORMAL = "normal"
    SPOTIFY = "spotify"


@dataclass(frozen=True, slots=True)
class ProviderModeState:
    provider: ProviderMode = ProviderMode.NORMAL
    version: int = PROVIDER_MODE_STATE_VERSION

    @property
    def enabled(self) -> bool:
        return self.provider is not ProviderMode.NORMAL


class ProviderModeTransitionError(RuntimeError):
    """Raised when a target provider cannot be prepared or committed."""


PrepareTarget = Callable[[], Awaitable[None]]
PauseProvider = Callable[[ProviderMode], Awaitable[None]]
CommitTarget = Callable[[ProviderMode], Awaitable[None]]


class ProviderModeCoordinator:
    """Target-first coordinator that preserves the previous mode on failure."""

    def __init__(self, initial: ProviderModeState | None = None) -> None:
        self._state = initial or ProviderModeState()
        self._lock = asyncio.Lock()

    @property
    def state(self) -> ProviderModeState:
        return self._state

    async def restore(self, state: ProviderModeState) -> None:
        """Synchronize validated adapter state without running a transition."""
        async with self._lock:
            self._state = state

    async def switch(
        self,
        target: ProviderMode,
        *,
        prepare: PrepareTarget,
        pause_previous: PauseProvider,
        commit: CommitTarget,
    ) -> ProviderModeState:
        """Prepare the target before pausing and atomically publishing it."""
        async with self._lock:
            previous = self._state.provider
            if target is previous:
                return self._state
            try:
                await prepare()
            except Exception as exc:
                raise ProviderModeTransitionError(str(exc)) from exc

            paused = False
            try:
                if previous is not ProviderMode.NORMAL:
                    await pause_previous(previous)
                    paused = True
                await commit(target)
            except Exception as exc:
                detail = " after pausing the previous provider" if paused else ""
                raise ProviderModeTransitionError(
                    f"Could not commit provider mode{detail}: {exc}"
                ) from exc

            self._state = ProviderModeState(provider=target)
            return self._state

    async def exit(
        self,
        *,
        pause_current: PauseProvider,
        commit: CommitTarget,
    ) -> ProviderModeState:
        async with self._lock:
            current = self._state.provider
            if current is ProviderMode.NORMAL:
                return self._state
            await pause_current(current)
            await commit(ProviderMode.NORMAL)
            self._state = ProviderModeState()
            return self._state


def provider_mode_path() -> Path:
    return sonex_home() / "provider-mode.json"


def save_provider_mode_intent(state: ProviderModeState) -> None:
    path = provider_mode_path()
    if state.provider is ProviderMode.NORMAL:
        clear_provider_mode_intent()
        return
    payload = asdict(state)
    payload["provider"] = state.provider.value
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=True, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
    except OSError:
        return


def load_provider_mode_intent() -> ProviderModeState:
    path = provider_mode_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return ProviderModeState()
    if not isinstance(payload, dict) or payload.get("version") != PROVIDER_MODE_STATE_VERSION:
        clear_provider_mode_intent()
        return ProviderModeState()
    try:
        provider = ProviderMode(str(payload.get("provider") or "normal"))
    except ValueError:
        clear_provider_mode_intent()
        return ProviderModeState()
    return ProviderModeState(provider=provider)


def clear_provider_mode_intent() -> None:
    try:
        provider_mode_path().unlink()
    except (FileNotFoundError, OSError):
        return
