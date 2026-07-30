"""Concrete managed, command, and MPRIS Player Sink adapters."""

from __future__ import annotations

import re
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse

from src.music.player_sinks import (
    PlayerAsset,
    PlayerSinkDescriptor,
    PlayerSinkPlayback,
    PlayerSinkProbe,
    PlayerSinkValidation,
)


WhichExecutable = Callable[[str], str | None]


class ManagedPlayerSinkAdapter:
    """Expose an existing Sonex-managed playback backend as a Player Sink."""

    def __init__(
        self,
        *,
        backend: str,
        display_name: str,
        executable_names: tuple[str, ...],
        which: WhichExecutable = shutil.which,
        play_managed: Callable[[str, str, dict[str, object]], dict[str, object]],
        validate_managed: Callable[[str], bool] | None = None,
        control_managed: Callable[[str, str, int | None], dict[str, object]] | None = None,
        is_active: Callable[[str], bool] | None = None,
    ) -> None:
        self.backend = backend
        self.executable_names = executable_names
        self._which = which
        self._play_managed = play_managed
        self._validate_managed = validate_managed
        self._control_managed = control_managed
        self._is_active = is_active or (lambda _backend: False)
        self.descriptor = PlayerSinkDescriptor(
            sink_id=f"managed:{backend}",
            display_name=display_name,
            description="Managed playback with Sonex controls.",
        )

    def _executable(self) -> str | None:
        return next(
            (path for name in self.executable_names if (path := self._which(name))),
            None,
        )

    async def probe(self) -> PlayerSinkProbe:
        installed = self._executable() is not None
        running = installed and self._is_active(self.backend)
        return PlayerSinkProbe(
            installed=installed,
            running=running,
            controllable=installed,
            injectable=installed,
            accepted_asset_kinds=("file_uri", "public_http"),
            supported_uri_schemes=("file", "http", "https"),
        )

    async def validate(self) -> PlayerSinkValidation:
        if self._executable() is None:
            return PlayerSinkValidation.failed(
                f"{self.descriptor.display_name} is no longer available."
            )
        if self._is_active(self.backend):
            return PlayerSinkValidation.deferred(
                "The player is active. Sonex will validate it on the next playback."
            )
        if self._validate_managed is not None:
            valid = self._validate_managed(self.backend)
            if not valid:
                return PlayerSinkValidation.failed(
                    f"{self.descriptor.display_name} did not accept the validation probe."
                )
        return PlayerSinkValidation.succeeded(
            f"{self.descriptor.display_name} is ready as the default player."
        )

    async def play(self, asset: PlayerAsset, track: dict[str, object]) -> PlayerSinkPlayback:
        state = self._play_managed(self.backend, asset.uri, track)
        return PlayerSinkPlayback(sink_id=self.descriptor.sink_id, state=state)

    async def control(self, action: str, value: int | None = None) -> PlayerSinkPlayback:
        if self._control_managed is None:
            raise RuntimeError("Managed player controls are not configured.")
        state = self._control_managed(self.backend, action, value)
        return PlayerSinkPlayback(sink_id=self.descriptor.sink_id, state=state)


class CommandPlayerSinkAdapter:
    """Use a trusted application CLI for exact-target media injection."""

    def __init__(
        self,
        *,
        sink_id: str,
        display_name: str,
        description: str,
        executable_names: tuple[str, ...],
        build_play_command: Callable[[str, str], tuple[str, ...]],
        which: WhichExecutable = shutil.which,
        launch: Callable[[tuple[str, ...]], None],
        is_active: Callable[[], bool],
        validate_injection: Callable[[], bool],
        build_control_command: (
            Callable[[str, str, int | None], tuple[str, ...] | None] | None
        ) = None,
        can_control: bool = True,
    ) -> None:
        self.descriptor = PlayerSinkDescriptor(sink_id, display_name, description)
        self.executable_names = executable_names
        self._build_play_command = build_play_command
        self._which = which
        self._launch = launch
        self._is_active = is_active
        self._validate_injection = validate_injection
        self._build_control_command = build_control_command
        self._can_control = can_control
        self._last_state: dict[str, object] = {}

    def _executable(self) -> str | None:
        return next(
            (path for name in self.executable_names if (path := self._which(name))),
            None,
        )

    async def probe(self) -> PlayerSinkProbe:
        installed = self._executable() is not None
        running = installed and self._is_active()
        return PlayerSinkProbe(
            installed=installed,
            running=running,
            controllable=installed and self._can_control,
            injectable=installed,
            accepted_asset_kinds=("file_uri", "public_http"),
            supported_uri_schemes=("file", "http", "https"),
        )

    async def validate(self) -> PlayerSinkValidation:
        if self._executable() is None:
            return PlayerSinkValidation.failed(
                f"{self.descriptor.display_name} is no longer available."
            )
        if self._is_active():
            return PlayerSinkValidation.deferred(
                "The player is active. Sonex will validate it on the next playback."
            )
        if not self._validate_injection():
            return PlayerSinkValidation.failed(
                f"{self.descriptor.display_name} did not accept the validation probe."
            )
        return PlayerSinkValidation.succeeded(
            f"{self.descriptor.display_name} is ready as the default player."
        )

    async def play(self, asset: PlayerAsset, track: dict[str, object]) -> PlayerSinkPlayback:
        executable = self._executable()
        if executable is None:
            raise RuntimeError(f"{self.descriptor.display_name} is no longer available.")
        self._launch(self._build_play_command(executable, asset.uri))
        state = {
            "name": str(track.get("name") or track.get("title") or Path(asset.uri).name or "-"),
            "artist": str(track.get("artist") or "-"),
            "album": str(track.get("album") or "-"),
            "is_playing": True,
            "uri": asset.uri,
            "player": self.descriptor.display_name,
        }
        self._last_state = dict(state)
        return PlayerSinkPlayback(sink_id=self.descriptor.sink_id, state=state)

    async def control(self, action: str, value: int | None = None) -> PlayerSinkPlayback:
        executable = self._executable()
        if executable is None:
            raise RuntimeError(f"{self.descriptor.display_name} is no longer available.")
        if not self._can_control:
            raise RuntimeError(
                f"{self.descriptor.display_name} does not expose a supported control interface."
            )
        if action == "status":
            state = {
                "player": self.descriptor.display_name,
                **self._last_state,
            }
            state.setdefault("is_playing", False)
            return PlayerSinkPlayback(
                sink_id=self.descriptor.sink_id,
                state=state,
            )
        command = (
            self._build_control_command(executable, action, value)
            if self._build_control_command is not None
            else None
        )
        if not command:
            raise RuntimeError(
                f"{self.descriptor.display_name} does not support the {action} control."
            )
        self._launch(command)
        state: dict[str, object] = {"player": self.descriptor.display_name}
        if action == "pause":
            state["is_playing"] = False
        elif action == "resume":
            state["is_playing"] = True
        elif action == "stop":
            state.update(is_playing=False, ended=True)
        elif action == "volume":
            state["volume_percent"] = value
        self._last_state.update(state)
        return PlayerSinkPlayback(
            sink_id=self.descriptor.sink_id,
            state=state,
        )


@dataclass(frozen=True, slots=True)
class MprisService:
    bus_name: str
    identity: str
    can_control: bool
    has_open_uri: bool
    supported_uri_schemes: tuple[str, ...]
    playback_status: str


class MprisClient(Protocol):
    async def list_services(self) -> tuple[MprisService, ...]: ...

    async def validate_open_uri(self, bus_name: str) -> bool: ...

    async def open_uri(self, bus_name: str, uri: str) -> dict[str, object]: ...

    async def control(
        self,
        bus_name: str,
        action: str,
        value: int | None = None,
    ) -> dict[str, object]: ...


class MprisPlayerSinkAdapter:
    """Target one exact MPRIS service discovered on the session bus."""

    def __init__(self, client: MprisClient, service: MprisService) -> None:
        self._client = client
        self._service = service
        suffix = self._stable_suffix(service.bus_name)
        self.descriptor = PlayerSinkDescriptor(
            sink_id=f"mpris:{suffix}",
            display_name=service.identity or suffix,
            description="External MPRIS player.",
        )

    @staticmethod
    def _stable_suffix(bus_name: str) -> str:
        suffix = bus_name.removeprefix("org.mpris.MediaPlayer2.").casefold()
        return re.sub(r"\.instance\d+$", "", suffix)

    async def _refresh_service(self) -> None:
        expected = self.descriptor.sink_id.removeprefix("mpris:")
        services = await self._client.list_services()
        replacement = next(
            (
                service
                for service in services
                if self._stable_suffix(service.bus_name) == expected
            ),
            None,
        )
        if replacement is not None:
            self._service = replacement

    async def probe(self) -> PlayerSinkProbe:
        schemes = tuple(scheme.casefold() for scheme in self._service.supported_uri_schemes)
        accepted: list[str] = []
        if self._service.has_open_uri and "file" in schemes:
            accepted.append("file_uri")
        if self._service.has_open_uri and {"http", "https"}.intersection(schemes):
            accepted.append("public_http")
        return PlayerSinkProbe(
            installed=False,
            running=True,
            controllable=self._service.can_control,
            injectable=bool(accepted),
            accepted_asset_kinds=tuple(accepted),
            supported_uri_schemes=schemes,
        )

    async def validate(self) -> PlayerSinkValidation:
        if self._service.playback_status.casefold() != "stopped":
            return PlayerSinkValidation.deferred(
                "The player is active. Sonex will validate it on the next playback."
            )
        if not self._service.has_open_uri:
            return PlayerSinkValidation.failed(
                "This application can be controlled but cannot receive Sonex audio."
            )
        if not await self._client.validate_open_uri(self._service.bus_name):
            return PlayerSinkValidation.failed(
                f"{self.descriptor.display_name} did not accept the validation probe."
            )
        return PlayerSinkValidation.succeeded(
            f"{self.descriptor.display_name} is ready as the default player."
        )

    async def play(self, asset: PlayerAsset, track: dict[str, object]) -> PlayerSinkPlayback:
        scheme = urlparse(asset.uri).scheme.casefold()
        if scheme not in {item.casefold() for item in self._service.supported_uri_schemes}:
            raise RuntimeError(
                f"{self.descriptor.display_name} does not support {scheme or 'local'} URIs."
            )
        try:
            state = await self._client.open_uri(self._service.bus_name, asset.uri)
        except Exception:
            await self._refresh_service()
            raise
        return PlayerSinkPlayback(
            sink_id=self.descriptor.sink_id,
            state={**track, **state},
        )

    async def control(self, action: str, value: int | None = None) -> PlayerSinkPlayback:
        state = await self._client.control(self._service.bus_name, action, value)
        return PlayerSinkPlayback(sink_id=self.descriptor.sink_id, state=state)


async def discover_mpris_adapters(client: MprisClient) -> tuple[MprisPlayerSinkAdapter, ...]:
    services = await client.list_services()
    return tuple(
        MprisPlayerSinkAdapter(client, service)
        for service in services
        if service.can_control
    )
