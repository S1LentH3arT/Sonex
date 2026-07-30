"""Bounded MPRIS discovery and exact-target control via dbus-next."""

from __future__ import annotations

import asyncio
import tempfile
import wave
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from src.music.player_sink_adapters import MprisService


def _unwrap(value: Any) -> Any:
    return getattr(value, "value", value)


def _metadata_text(metadata: dict[str, Any], key: str, default: str = "-") -> str:
    value = _unwrap(metadata.get(key))
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    return str(value or default)


def _silent_probe_uri() -> str:
    path = Path(tempfile.gettempdir()) / "sonex-player-sink-probe.wav"
    if not path.exists():
        with wave.open(str(path), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(8_000)
            audio.writeframes(b"\x00\x00" * 8_000)
    return path.as_uri()


def _requested_uri_observed(
    observed_uri: str,
    requested_uri: str,
    playback_status: str = "Playing",
) -> bool:
    if playback_status.casefold() != "playing":
        return False
    if observed_uri == requested_uri:
        return True
    observed = urlsplit(observed_uri)
    requested = urlsplit(requested_uri)
    if observed.scheme.casefold() != requested.scheme.casefold():
        return False
    if observed.scheme.casefold() != "file":
        return False
    return Path(unquote(observed.path)).resolve() == Path(unquote(requested.path)).resolve()


class DbusNextMprisClient:
    """Use one short-lived session-bus connection per bounded operation."""

    def __init__(self, *, timeout_seconds: float = 2.0) -> None:
        self.timeout_seconds = timeout_seconds

    async def _connect(self) -> Any:
        try:
            from dbus_next.aio import MessageBus
        except ImportError as exc:
            raise RuntimeError("dbus-next is required for MPRIS discovery.") from exc
        return await asyncio.wait_for(MessageBus().connect(), timeout=self.timeout_seconds)

    async def _interfaces(self, bus: Any, bus_name: str) -> tuple[Any, Any, Any]:
        path = "/org/mpris/MediaPlayer2"
        introspection = await asyncio.wait_for(
            bus.introspect(bus_name, path),
            timeout=self.timeout_seconds,
        )
        proxy = bus.get_proxy_object(bus_name, path, introspection)
        return (
            proxy.get_interface("org.mpris.MediaPlayer2"),
            proxy.get_interface("org.mpris.MediaPlayer2.Player"),
            proxy.get_interface("org.freedesktop.DBus.Properties"),
        )

    async def list_services(self) -> tuple[MprisService, ...]:
        try:
            bus = await self._connect()
        except (RuntimeError, OSError, asyncio.TimeoutError):
            return ()
        services: list[MprisService] = []
        try:
            introspection = await asyncio.wait_for(
                bus.introspect("org.freedesktop.DBus", "/org/freedesktop/DBus"),
                timeout=self.timeout_seconds,
            )
            proxy = bus.get_proxy_object(
                "org.freedesktop.DBus",
                "/org/freedesktop/DBus",
                introspection,
            )
            dbus = proxy.get_interface("org.freedesktop.DBus")
            names = await asyncio.wait_for(
                dbus.call_list_names(),
                timeout=self.timeout_seconds,
            )
            for name in sorted(
                item for item in names if item.startswith("org.mpris.MediaPlayer2.")
            ):
                try:
                    root, player, properties = await self._interfaces(bus, name)
                    root_properties, player_properties = await asyncio.gather(
                        properties.call_get_all("org.mpris.MediaPlayer2"),
                        properties.call_get_all("org.mpris.MediaPlayer2.Player"),
                    )
                    services.append(
                        MprisService(
                            bus_name=name,
                            identity=str(_unwrap(root_properties.get("Identity")) or name),
                            can_control=bool(_unwrap(player_properties.get("CanControl"))),
                            has_open_uri=hasattr(player, "call_open_uri"),
                            supported_uri_schemes=tuple(
                                str(item)
                                for item in (_unwrap(root_properties.get("SupportedUriSchemes")) or ())
                            ),
                            playback_status=str(
                                _unwrap(player_properties.get("PlaybackStatus")) or "Stopped"
                            ),
                        )
                    )
                except (AttributeError, OSError, asyncio.TimeoutError):
                    continue
        finally:
            bus.disconnect()
        return tuple(services)

    async def _open_and_snapshot(self, bus_name: str, uri: str) -> dict[str, object]:
        bus = await self._connect()
        try:
            _root, player, properties = await self._interfaces(bus, bus_name)
            await asyncio.wait_for(player.call_open_uri(uri), timeout=self.timeout_seconds)
            deadline = asyncio.get_running_loop().time() + self.timeout_seconds
            player_properties: dict[str, Any] = {}
            while asyncio.get_running_loop().time() < deadline:
                player_properties = await properties.call_get_all(
                    "org.mpris.MediaPlayer2.Player"
                )
                metadata = _unwrap(player_properties.get("Metadata")) or {}
                observed_url = _metadata_text(metadata, "xesam:url", "")
                status = str(_unwrap(player_properties.get("PlaybackStatus")) or "Stopped")
                if _requested_uri_observed(observed_url, uri, status):
                    return {
                        "name": _metadata_text(metadata, "xesam:title", "External playback"),
                        "artist": _metadata_text(metadata, "xesam:artist"),
                        "album": _metadata_text(metadata, "xesam:album"),
                        "is_playing": status.casefold() == "playing",
                        "uri": uri,
                    }
                await asyncio.sleep(0.05)
            raise RuntimeError("MPRIS player did not confirm the requested URI.")
        finally:
            bus.disconnect()

    async def control(
        self,
        bus_name: str,
        action: str,
        value: int | None = None,
    ) -> dict[str, object]:
        bus = await self._connect()
        try:
            _root, player, properties = await self._interfaces(bus, bus_name)
            if action == "pause":
                await asyncio.wait_for(player.call_pause(), timeout=self.timeout_seconds)
            elif action == "resume":
                await asyncio.wait_for(player.call_play(), timeout=self.timeout_seconds)
            elif action == "stop":
                await asyncio.wait_for(player.call_stop(), timeout=self.timeout_seconds)
            elif action == "volume":
                if value is None or not 0 <= value <= 100:
                    raise ValueError("Volume must be an integer from 0 to 100.")
                from dbus_next import Variant

                await asyncio.wait_for(
                    properties.call_set(
                        "org.mpris.MediaPlayer2.Player",
                        "Volume",
                        Variant("d", value / 100),
                    ),
                    timeout=self.timeout_seconds,
                )
            elif action != "status":
                raise ValueError(f"Unsupported player control: {action}.")

            player_properties = await asyncio.wait_for(
                properties.call_get_all("org.mpris.MediaPlayer2.Player"),
                timeout=self.timeout_seconds,
            )
            metadata = _unwrap(player_properties.get("Metadata")) or {}
            status = str(_unwrap(player_properties.get("PlaybackStatus")) or "Stopped")
            volume = _unwrap(player_properties.get("Volume"))
            return {
                "name": _metadata_text(metadata, "xesam:title", "External playback"),
                "artist": _metadata_text(metadata, "xesam:artist"),
                "album": _metadata_text(metadata, "xesam:album"),
                "is_playing": status.casefold() == "playing",
                "volume_percent": (
                    round(float(volume) * 100)
                    if isinstance(volume, (float, int))
                    else None
                ),
                "player": bus_name.removeprefix("org.mpris.MediaPlayer2."),
            }
        finally:
            bus.disconnect()

    async def validate_open_uri(self, bus_name: str) -> bool:
        try:
            await self._open_and_snapshot(bus_name, _silent_probe_uri())
            bus = await self._connect()
            try:
                _root, player, _properties = await self._interfaces(bus, bus_name)
                await asyncio.wait_for(player.call_stop(), timeout=self.timeout_seconds)
            finally:
                bus.disconnect()
        except (RuntimeError, OSError, asyncio.TimeoutError):
            return False
        return True

    async def open_uri(self, bus_name: str, uri: str) -> dict[str, object]:
        return await self._open_and_snapshot(bus_name, uri)
