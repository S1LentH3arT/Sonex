from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from src.music.player_sinks import (
    PlayerAsset,
    PlayerSinkDescriptor,
    PlayerSinkManager,
    PlayerSinkPlayback,
    PlayerSinkProbe,
    PlayerSinkValidation,
)


class _FakeSinkAdapter:
    def __init__(
        self,
        descriptor: PlayerSinkDescriptor,
        probe: PlayerSinkProbe,
        *,
        validation: PlayerSinkValidation | None = None,
        playback: PlayerSinkPlayback | None = None,
        probe_error: Exception | None = None,
        play_failures: int = 0,
    ) -> None:
        self.descriptor = descriptor
        self._probe = probe
        self._validation = validation or PlayerSinkValidation.succeeded()
        self._playback = playback or PlayerSinkPlayback(
            sink_id=descriptor.sink_id,
            state={"is_playing": True},
        )
        self._probe_error = probe_error
        self._play_failures = play_failures
        self.probe_calls = 0
        self.validate_calls = 0
        self.play_calls = 0
        self.control_calls: list[tuple[str, int | None]] = []
        self.launch_calls = 0

    async def probe(self) -> PlayerSinkProbe:
        self.probe_calls += 1
        if self._probe_error is not None:
            raise self._probe_error
        return self._probe

    async def validate(self) -> PlayerSinkValidation:
        self.validate_calls += 1
        return self._validation

    async def play(self, asset: PlayerAsset, track: dict[str, object]) -> PlayerSinkPlayback:
        self.play_calls += 1
        if self.play_calls <= self._play_failures:
            raise RuntimeError("player dispatch failed")
        return self._playback

    async def control(self, action: str, value: int | None = None) -> PlayerSinkPlayback:
        self.control_calls.append((action, value))
        return self._playback


class PlayerSinkManagerTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_candidate_probe_does_not_hide_other_players(self) -> None:
        with TemporaryDirectory() as temporary:
            broken = _FakeSinkAdapter(
                PlayerSinkDescriptor("mpris:broken", "Broken", "External player"),
                PlayerSinkProbe(False, True, True, True, ("file_uri",)),
                probe_error=RuntimeError("session bus disappeared"),
            )
            mpv = _FakeSinkAdapter(
                PlayerSinkDescriptor("managed:mpv", "mpv", "Managed playback"),
                PlayerSinkProbe(True, False, True, True, ("file_uri",)),
            )
            manager = PlayerSinkManager(
                adapters=(broken, mpv),
                preferences_path=Path(temporary) / "player-preferences.json",
            )

            options = await manager.options()

            self.assertEqual([option.sink_id for option in options], ["managed:mpv"])

    async def test_dynamic_discovery_runs_once_and_merges_stable_sink_ids(self) -> None:
        with TemporaryDirectory() as temporary:
            managed = _FakeSinkAdapter(
                PlayerSinkDescriptor("managed:mpv", "mpv", "Managed playback"),
                PlayerSinkProbe(True, False, True, True, ("file_uri",)),
            )
            duplicate = _FakeSinkAdapter(
                PlayerSinkDescriptor("managed:mpv", "Duplicate", "Should not replace managed"),
                PlayerSinkProbe(True, False, True, True, ("file_uri",)),
            )
            discovered = _FakeSinkAdapter(
                PlayerSinkDescriptor("mpris:amberol", "Amberol", "External media session"),
                PlayerSinkProbe(False, True, True, False),
            )
            discovery_calls = 0

            async def discover() -> tuple[_FakeSinkAdapter, ...]:
                nonlocal discovery_calls
                discovery_calls += 1
                return duplicate, discovered

            manager = PlayerSinkManager(
                adapters=(managed,),
                adapter_discovery=discover,
                preferences_path=Path(temporary) / "player-preferences.json",
            )

            first = await manager.options()
            second = await manager.options()

            self.assertEqual(discovery_calls, 1)
            self.assertEqual(first, second)
            self.assertEqual([option.sink_id for option in first], ["managed:mpv", "mpris:amberol"])
            self.assertEqual(first[0].label, "mpv")

    async def test_options_passively_cache_discovery_and_disable_remote_only_sinks(self) -> None:
        with TemporaryDirectory() as temporary:
            playable = _FakeSinkAdapter(
                PlayerSinkDescriptor(
                    sink_id="managed:mpv",
                    display_name="mpv",
                    description="Managed playback",
                ),
                PlayerSinkProbe(
                    installed=True,
                    running=False,
                    controllable=True,
                    injectable=True,
                    accepted_asset_kinds=("file_uri", "public_http"),
                ),
            )
            remote_only = _FakeSinkAdapter(
                PlayerSinkDescriptor(
                    sink_id="mpris:remote",
                    display_name="Remote",
                    description="External media session",
                ),
                PlayerSinkProbe(
                    installed=True,
                    running=True,
                    controllable=True,
                    injectable=False,
                ),
            )
            manager = PlayerSinkManager(
                adapters=(playable, remote_only),
                preferences_path=Path(temporary) / "player-preferences.json",
            )

            first = await manager.options()
            second = await manager.options()

            self.assertEqual(first, second)
            self.assertEqual(playable.probe_calls, 1)
            self.assertEqual(remote_only.probe_calls, 1)
            self.assertEqual(playable.launch_calls, 0)
            self.assertEqual(remote_only.launch_calls, 0)
            self.assertEqual(
                [(option.sink_id, option.disabled, option.disabled_reason) for option in first],
                [
                    ("managed:mpv", False, None),
                    ("mpris:remote", True, "Remote control only"),
                ],
            )

    async def test_options_disable_injectable_player_without_control_interface(self) -> None:
        with TemporaryDirectory() as temporary:
            adapter = _FakeSinkAdapter(
                PlayerSinkDescriptor(
                    sink_id="mpris:audacious",
                    display_name="Audacious",
                    description="External player",
                ),
                PlayerSinkProbe(
                    installed=True,
                    running=False,
                    controllable=False,
                    injectable=True,
                    accepted_asset_kinds=("file_uri", "public_http"),
                ),
            )
            manager = PlayerSinkManager(
                adapters=(adapter,),
                preferences_path=Path(temporary) / "player-preferences.json",
            )

            (option,) = await manager.options()
            result = await manager.select("mpris:audacious")

            self.assertTrue(option.disabled)
            self.assertEqual(option.disabled_reason, "Playback control unavailable")
            self.assertEqual(result.status, "failed")
            self.assertEqual(adapter.validate_calls, 0)

    async def test_select_persists_stable_default_only_after_validation_succeeds(self) -> None:
        with TemporaryDirectory() as temporary:
            preferences_path = Path(temporary) / "player-preferences.json"
            adapter = _FakeSinkAdapter(
                PlayerSinkDescriptor(
                    sink_id="mpris:clementine",
                    display_name="Clementine",
                    description="External player",
                ),
                PlayerSinkProbe(
                    installed=True,
                    running=False,
                    controllable=True,
                    injectable=True,
                    accepted_asset_kinds=("file_uri", "public_http"),
                ),
            )
            manager = PlayerSinkManager(
                adapters=(adapter,),
                preferences_path=preferences_path,
            )

            result = await manager.select("mpris:clementine")

            self.assertEqual(result.status, "selected")
            self.assertEqual(result.sink_id, "mpris:clementine")
            self.assertEqual(adapter.validate_calls, 1)
            self.assertEqual(manager.default_sink_id, "mpris:clementine")
            self.assertEqual(
                json.loads(preferences_path.read_text(encoding="utf-8")),
                {
                    "version": 1,
                    "default_sink_id": "mpris:clementine",
                },
            )

            controlled = await manager.control("pause")

            self.assertEqual(controlled.sink_id, "mpris:clementine")
            self.assertEqual(adapter.control_calls, [("pause", None)])

    async def test_status_control_does_not_repeat_the_adapter_probe(self) -> None:
        with TemporaryDirectory() as temporary:
            preferences_path = Path(temporary) / "player-preferences.json"
            preferences_path.write_text(
                json.dumps({"version": 1, "default_sink_id": "managed:mpv"}),
                encoding="utf-8",
            )
            adapter = _FakeSinkAdapter(
                PlayerSinkDescriptor(
                    sink_id="managed:mpv",
                    display_name="mpv",
                    description="Managed playback",
                ),
                PlayerSinkProbe(
                    installed=True,
                    running=True,
                    controllable=True,
                    injectable=True,
                    accepted_asset_kinds=("file_uri", "public_http"),
                ),
            )
            manager = PlayerSinkManager(
                adapters=(adapter,),
                preferences_path=preferences_path,
            )

            status = await manager.control("status")

            self.assertEqual(status.sink_id, "managed:mpv")
            self.assertEqual(adapter.probe_calls, 0)
            self.assertEqual(adapter.control_calls, [("status", None)])

    async def test_deferred_selection_promotes_only_after_first_real_playback_succeeds(self) -> None:
        with TemporaryDirectory() as temporary:
            preferences_path = Path(temporary) / "player-preferences.json"
            managed = _FakeSinkAdapter(
                PlayerSinkDescriptor(
                    sink_id="managed:mpv",
                    display_name="mpv",
                    description="Managed playback",
                ),
                PlayerSinkProbe(
                    installed=True,
                    running=False,
                    controllable=True,
                    injectable=True,
                    accepted_asset_kinds=("file_uri", "public_http"),
                ),
            )
            external = _FakeSinkAdapter(
                PlayerSinkDescriptor(
                    sink_id="mpris:clementine",
                    display_name="Clementine",
                    description="External player",
                ),
                PlayerSinkProbe(
                    installed=True,
                    running=True,
                    controllable=True,
                    injectable=True,
                    accepted_asset_kinds=("file_uri", "public_http"),
                ),
                validation=PlayerSinkValidation.deferred(),
            )
            manager = PlayerSinkManager(
                adapters=(managed, external),
                preferences_path=preferences_path,
            )
            await manager.select("managed:mpv")

            selection = await manager.select("mpris:clementine")

            self.assertEqual(selection.status, "deferred")
            self.assertEqual(manager.default_sink_id, "managed:mpv")
            self.assertEqual(manager.pending_sink_id, "mpris:clementine")

            playback = await manager.play(
                PlayerAsset(kind="file_uri", uri="file:///tmp/song.wav"),
                {"name": "Song"},
            )

            self.assertEqual(playback.sink_id, "mpris:clementine")
            self.assertEqual(external.play_calls, 1)
            self.assertEqual(managed.play_calls, 0)
            self.assertEqual(manager.default_sink_id, "mpris:clementine")
            self.assertIsNone(manager.pending_sink_id)
            self.assertEqual(
                json.loads(preferences_path.read_text(encoding="utf-8")),
                {
                    "version": 1,
                    "default_sink_id": "mpris:clementine",
                },
            )

    async def test_play_retries_the_same_sink_once_without_fallback(self) -> None:
        with TemporaryDirectory() as temporary:
            adapter = _FakeSinkAdapter(
                PlayerSinkDescriptor(
                    sink_id="mpris:clementine",
                    display_name="Clementine",
                    description="External player",
                ),
                PlayerSinkProbe(
                    installed=True,
                    running=False,
                    controllable=True,
                    injectable=True,
                    accepted_asset_kinds=("file_uri",),
                ),
                play_failures=2,
            )
            manager = PlayerSinkManager(
                adapters=(adapter,),
                preferences_path=Path(temporary) / "player-preferences.json",
            )
            await manager.select("mpris:clementine")

            with self.assertRaisesRegex(RuntimeError, "dispatch failed"):
                await manager.play(
                    PlayerAsset(kind="file_uri", uri="file:///tmp/song.wav"),
                    {"name": "Song"},
                )

            self.assertEqual(adapter.play_calls, 2)
            self.assertEqual(adapter.probe_calls, 3)


if __name__ == "__main__":
    unittest.main()
