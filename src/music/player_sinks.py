"""Capability-based discovery and selection of local Player Sinks."""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Awaitable, Callable
from typing import Protocol

from src.log import sonex_home


@dataclass(frozen=True, slots=True)
class PlayerSinkDescriptor:
    sink_id: str
    display_name: str
    description: str


@dataclass(frozen=True, slots=True)
class PlayerSinkProbe:
    installed: bool
    running: bool
    controllable: bool
    injectable: bool
    accepted_asset_kinds: tuple[str, ...] = ()
    supported_uri_schemes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PlayerSinkOption:
    sink_id: str
    label: str
    description: str
    installed: bool
    running: bool
    controllable: bool
    injectable: bool
    disabled: bool
    disabled_reason: str | None = None


@dataclass(frozen=True, slots=True)
class PlayerAsset:
    kind: str
    uri: str


@dataclass(frozen=True, slots=True)
class PlayerSinkPlayback:
    sink_id: str
    state: dict[str, object]


@dataclass(frozen=True, slots=True)
class PlayerSinkValidation:
    status: str
    message: str

    @classmethod
    def succeeded(cls, message: str = "Player validation succeeded.") -> "PlayerSinkValidation":
        return cls(status="succeeded", message=message)

    @classmethod
    def deferred(cls, message: str = "Validation deferred until the next playback.") -> "PlayerSinkValidation":
        return cls(status="deferred", message=message)

    @classmethod
    def failed(cls, message: str) -> "PlayerSinkValidation":
        return cls(status="failed", message=message)


@dataclass(frozen=True, slots=True)
class PlayerSelectionResult:
    status: str
    sink_id: str | None
    message: str
    previous_sink_id: str | None


class PlayerSinkAdapter(Protocol):
    descriptor: PlayerSinkDescriptor

    async def probe(self) -> PlayerSinkProbe: ...

    async def validate(self) -> PlayerSinkValidation: ...

    async def play(self, asset: PlayerAsset, track: dict[str, object]) -> PlayerSinkPlayback: ...

    async def control(self, action: str, value: int | None = None) -> PlayerSinkPlayback: ...


class PlayerSinkManager:
    """Hide Player Sink discovery, selection, persistence, and dispatch."""

    def __init__(
        self,
        *,
        adapters: tuple[PlayerSinkAdapter, ...],
        adapter_discovery: Callable[[], Awaitable[tuple[PlayerSinkAdapter, ...]]] | None = None,
        preferences_path: Path | None = None,
        probe_timeout_seconds: float = 2.0,
    ) -> None:
        self._adapters = list(adapters)
        self._adapter_discovery = adapter_discovery
        self._discovery_complete = False
        self._probe_timeout_seconds = probe_timeout_seconds
        self._preferences_path = preferences_path or sonex_home() / "music" / "player-preferences.json"
        self._options_cache: tuple[PlayerSinkOption, ...] | None = None
        self._default_sink_id: str | None = None
        self._pending_sink_id: str | None = None
        self._load_preferences()

    @property
    def default_sink_id(self) -> str | None:
        return self._default_sink_id

    @property
    def pending_sink_id(self) -> str | None:
        return self._pending_sink_id

    async def options(self, *, refresh: bool = False) -> tuple[PlayerSinkOption, ...]:
        if self._options_cache is not None and not refresh:
            return self._options_cache
        await self._ensure_discovered()

        options: list[PlayerSinkOption] = []
        for adapter in self._adapters:
            try:
                probe = await asyncio.wait_for(
                    adapter.probe(),
                    timeout=self._probe_timeout_seconds,
                )
            except (Exception, asyncio.TimeoutError):
                continue
            if not probe.installed and not probe.running:
                continue
            disabled_reason = None if probe.injectable else "Remote control only"
            options.append(
                PlayerSinkOption(
                    sink_id=adapter.descriptor.sink_id,
                    label=adapter.descriptor.display_name,
                    description=adapter.descriptor.description,
                    installed=probe.installed,
                    running=probe.running,
                    controllable=probe.controllable,
                    injectable=probe.injectable,
                    disabled=disabled_reason is not None,
                    disabled_reason=disabled_reason,
                )
            )
        self._options_cache = tuple(options)
        return self._options_cache

    async def select(self, sink_id: str) -> PlayerSelectionResult:
        await self._ensure_discovered()
        previous = self._default_sink_id
        adapter = next(
            (candidate for candidate in self._adapters if candidate.descriptor.sink_id == sink_id),
            None,
        )
        if adapter is None:
            return PlayerSelectionResult(
                status="failed",
                sink_id=None,
                message="The selected player is no longer available.",
                previous_sink_id=previous,
            )

        try:
            probe = await asyncio.wait_for(
                adapter.probe(),
                timeout=self._probe_timeout_seconds,
            )
        except (Exception, asyncio.TimeoutError):
            return PlayerSelectionResult(
                status="failed",
                sink_id=sink_id,
                message="The selected player could not be inspected.",
                previous_sink_id=previous,
            )
        if not probe.injectable:
            return PlayerSelectionResult(
                status="failed",
                sink_id=sink_id,
                message="This application can be controlled but cannot receive Sonex audio.",
                previous_sink_id=previous,
            )

        validation = await adapter.validate()
        if validation.status == "succeeded":
            self._default_sink_id = sink_id
            self._pending_sink_id = None
            self._save_preferences()
            return PlayerSelectionResult(
                status="selected",
                sink_id=sink_id,
                message=validation.message,
                previous_sink_id=previous,
            )
        if validation.status == "deferred":
            self._pending_sink_id = sink_id
            self._save_preferences()
            return PlayerSelectionResult(
                status="deferred",
                sink_id=sink_id,
                message=validation.message,
                previous_sink_id=previous,
            )
        return PlayerSelectionResult(
            status="failed",
            sink_id=sink_id,
            message=validation.message,
            previous_sink_id=previous,
        )

    async def play(self, asset: PlayerAsset, track: dict[str, object]) -> PlayerSinkPlayback:
        await self._ensure_discovered()
        sink_id = self._pending_sink_id or self._default_sink_id
        adapter = next(
            (candidate for candidate in self._adapters if candidate.descriptor.sink_id == sink_id),
            None,
        )
        if adapter is None:
            raise RuntimeError("No validated default player is available.")

        probe = await asyncio.wait_for(
            adapter.probe(),
            timeout=self._probe_timeout_seconds,
        )
        if asset.kind not in probe.accepted_asset_kinds:
            raise RuntimeError(
                f"{adapter.descriptor.display_name} cannot play {asset.kind.replace('_', ' ')} assets."
            )

        playback = await adapter.play(asset, track)
        if self._pending_sink_id == sink_id:
            self._default_sink_id = sink_id
            self._pending_sink_id = None
            self._save_preferences()
        return playback

    async def control(self, action: str, value: int | None = None) -> PlayerSinkPlayback:
        await self._ensure_discovered()
        adapter = next(
            (
                candidate
                for candidate in self._adapters
                if candidate.descriptor.sink_id == self._default_sink_id
            ),
            None,
        )
        if adapter is None:
            raise RuntimeError("No validated default player is available.")
        probe = await asyncio.wait_for(
            adapter.probe(),
            timeout=self._probe_timeout_seconds,
        )
        if not probe.controllable:
            raise RuntimeError(
                f"{adapter.descriptor.display_name} is not currently controllable."
            )
        return await adapter.control(action, value)

    async def _ensure_discovered(self) -> None:
        if self._discovery_complete or self._adapter_discovery is None:
            return
        try:
            discovered = await asyncio.wait_for(
                self._adapter_discovery(),
                timeout=self._probe_timeout_seconds,
            )
        except (Exception, asyncio.TimeoutError):
            self._discovery_complete = True
            return
        known_ids = {adapter.descriptor.sink_id for adapter in self._adapters}
        for adapter in discovered:
            if adapter.descriptor.sink_id in known_ids:
                continue
            self._adapters.append(adapter)
            known_ids.add(adapter.descriptor.sink_id)
        self._discovery_complete = True

    def _load_preferences(self) -> None:
        try:
            payload = json.loads(self._preferences_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return
        if not isinstance(payload, dict) or payload.get("version") != 1:
            return
        default_sink_id = payload.get("default_sink_id")
        pending_sink_id = payload.get("pending_sink_id")
        self._default_sink_id = default_sink_id if isinstance(default_sink_id, str) else None
        self._pending_sink_id = pending_sink_id if isinstance(pending_sink_id, str) else None

    def _save_preferences(self) -> None:
        payload: dict[str, object] = {"version": 1}
        if self._default_sink_id:
            payload["default_sink_id"] = self._default_sink_id
        if self._pending_sink_id:
            payload["pending_sink_id"] = self._pending_sink_id

        self._preferences_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._preferences_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
        os.chmod(temporary, 0o600)
        temporary.replace(self._preferences_path)
        os.chmod(self._preferences_path, 0o600)
