from __future__ import annotations

import unittest

from src.music.player_sink_adapters import (
    CommandPlayerSinkAdapter,
    ManagedPlayerSinkAdapter,
    MprisService,
    discover_mpris_adapters,
)
from src.music.player_sinks import PlayerAsset


class _FakeMprisClient:
    def __init__(self, services: tuple[MprisService, ...]) -> None:
        self.services = services
        self.opened: list[tuple[str, str]] = []
        self.controlled: list[tuple[str, str, int | None]] = []

    async def list_services(self) -> tuple[MprisService, ...]:
        return self.services

    async def validate_open_uri(self, bus_name: str) -> bool:
        return True

    async def open_uri(self, bus_name: str, uri: str) -> dict[str, object]:
        self.opened.append((bus_name, uri))
        return {"is_playing": True, "name": "External playback"}

    async def control(
        self,
        bus_name: str,
        action: str,
        value: int | None = None,
    ) -> dict[str, object]:
        self.controlled.append((bus_name, action, value))
        return {"is_playing": action == "resume"}


class PlayerSinkAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_managed_probe_is_passive_and_play_uses_exact_backend(self) -> None:
        commands: list[tuple[str, str]] = []
        validations: list[str] = []

        def play(backend: str, uri: str, track: dict[str, object]) -> dict[str, object]:
            commands.append((backend, uri))
            return {"player": backend, **track}

        adapter = ManagedPlayerSinkAdapter(
            backend="mpv",
            display_name="mpv",
            executable_names=("mpv",),
            which=lambda executable: f"/usr/bin/{executable}",
            play_managed=play,
            validate_managed=lambda backend: validations.append(backend) or True,
        )

        probe = await adapter.probe()
        validation = await adapter.validate()
        playback = await adapter.play(
            PlayerAsset(kind="file_uri", uri="file:///music/song.flac"),
            {"name": "Song"},
        )

        self.assertTrue(probe.injectable)
        self.assertEqual(validation.status, "succeeded")
        self.assertEqual(validations, ["mpv"])
        self.assertEqual(commands, [("mpv", "file:///music/song.flac")])
        self.assertEqual(playback.sink_id, "managed:mpv")

    async def test_known_command_adapter_never_launches_during_probe(self) -> None:
        launches: list[tuple[str, ...]] = []
        adapter = CommandPlayerSinkAdapter(
            sink_id="mpris:rhythmbox",
            display_name="Rhythmbox",
            description="External player",
            executable_names=("rhythmbox-client",),
            build_play_command=lambda executable, uri: (executable, "--play-uri", uri),
            which=lambda executable: f"/usr/bin/{executable}",
            launch=lambda command: launches.append(command),
            is_active=lambda: False,
            validate_injection=lambda: True,
        )

        probe = await adapter.probe()
        self.assertTrue(probe.installed)
        self.assertEqual(launches, [])

        validation = await adapter.validate()
        await adapter.play(
            PlayerAsset(kind="public_http", uri="https://example.com/song.mp3"),
            {"name": "Song"},
        )

        self.assertEqual(validation.status, "succeeded")
        self.assertEqual(
            launches,
            [("/usr/bin/rhythmbox-client", "--play-uri", "https://example.com/song.mp3")],
        )

    async def test_active_command_adapter_defers_validation_without_mutation(self) -> None:
        validation_calls = 0

        def validate() -> bool:
            nonlocal validation_calls
            validation_calls += 1
            return True

        adapter = CommandPlayerSinkAdapter(
            sink_id="mpris:audacious",
            display_name="Audacious",
            description="External player",
            executable_names=("audacious",),
            build_play_command=lambda executable, uri: (executable, uri),
            which=lambda executable: f"/usr/bin/{executable}",
            launch=lambda command: None,
            is_active=lambda: True,
            validate_injection=validate,
        )

        validation = await adapter.validate()

        self.assertEqual(validation.status, "deferred")
        self.assertEqual(validation_calls, 0)

    async def test_mpris_discovery_classifies_open_uri_and_remote_only_services(self) -> None:
        client = _FakeMprisClient(
            (
                MprisService(
                    bus_name="org.mpris.MediaPlayer2.clementine",
                    identity="Clementine",
                    can_control=True,
                    has_open_uri=True,
                    supported_uri_schemes=("file", "http", "https"),
                    playback_status="Paused",
                ),
                MprisService(
                    bus_name="org.mpris.MediaPlayer2.remote",
                    identity="Remote",
                    can_control=True,
                    has_open_uri=False,
                    supported_uri_schemes=(),
                    playback_status="Playing",
                ),
            )
        )

        adapters = await discover_mpris_adapters(client)
        probes = [await adapter.probe() for adapter in adapters]

        self.assertEqual(
            [adapter.descriptor.sink_id for adapter in adapters],
            ["mpris:clementine", "mpris:remote"],
        )
        self.assertTrue(probes[0].injectable)
        self.assertFalse(probes[1].injectable)

        playback = await adapters[0].play(
            PlayerAsset(kind="public_http", uri="https://example.com/song.mp3"),
            {"name": "Song"},
        )
        self.assertEqual(
            client.opened,
            [("org.mpris.MediaPlayer2.clementine", "https://example.com/song.mp3")],
        )
        self.assertEqual(playback.sink_id, "mpris:clementine")

        controlled = await adapters[0].control("pause")
        self.assertEqual(
            client.controlled,
            [("org.mpris.MediaPlayer2.clementine", "pause", None)],
        )
        self.assertEqual(controlled.sink_id, "mpris:clementine")


if __name__ == "__main__":
    unittest.main()
