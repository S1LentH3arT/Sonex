from __future__ import annotations

import unittest

from src.music.playback_coordinator import (
    MusicPlaybackCoordinator,
    PlaybackCandidateError,
    ProviderReadiness,
    RecordingIdentity,
    SelectionStore,
    rank_authoritative_providers,
    recording_identity_matches,
)


class PlaybackCoordinatorTests(unittest.IsolatedAsyncioTestCase):
    def playback_callbacks(self, seen: list[RecordingIdentity] | None = None) -> dict[str, object]:
        async def resolve_local(_identity: RecordingIdentity) -> None:
            return None

        async def play_local(_candidate: object) -> dict[str, object]:
            raise AssertionError("no local candidate was resolved")

        async def play_native(
            _provider: str,
            _identity: RecordingIdentity,
            _candidate: object,
        ) -> dict[str, object]:
            raise AssertionError("no native candidate was selected")

        async def route_authoritative(
            *_args: object,
        ) -> dict[str, object]:
            raise AssertionError("online selection should skip authoritative routing")

        async def confirm_community() -> bool:
            raise AssertionError("an online selection already permits community audio")

        async def play_community(
            identity: RecordingIdentity,
            _source: str,
            _candidate: object,
        ) -> dict[str, object]:
            if seen is not None:
                seen.append(identity)
            return {"status": "playback_completed", "data": {"provider": "local"}}

        async def report_error(_message: str) -> None:
            raise AssertionError("successful route should not report an error")

        return {
            "candidate": {"playback_source": "online"},
            "requested_provider": None,
            "hard_provider": False,
            "resolve_local": resolve_local,
            "play_local": play_local,
            "play_native": play_native,
            "route_authoritative": route_authoritative,
            "confirm_community": confirm_community,
            "play_community": play_community,
            "report_error": report_error,
        }

    async def test_resolve_native_candidate_keeps_trusted_uri_without_searching(self) -> None:
        coordinator = MusicPlaybackCoordinator()
        searched = False

        async def search(_query: str) -> list[dict[str, object]]:
            nonlocal searched
            searched = True
            return []

        candidate = {
            "uri": "spotify:track:123",
            "title": "BB88",
            "artist": "方大同",
        }
        resolved = await coordinator.resolve_native_candidate(
            RecordingIdentity("BB88", "方大同"),
            candidate,
            search_candidates=search,
        )

        self.assertEqual(resolved, candidate)
        self.assertFalse(searched)

    async def test_resolve_native_candidate_rejects_mismatched_search_result(self) -> None:
        coordinator = MusicPlaybackCoordinator()

        async def search(_query: str) -> list[dict[str, object]]:
            return [{"uri": "spotify:track:123", "title": "Other", "artist": "方大同"}]

        with self.assertRaisesRegex(PlaybackCandidateError, "exact"):
            await coordinator.resolve_native_candidate(
                RecordingIdentity("BB88", "方大同"),
                {"title": "BB88", "artist": "方大同"},
                search_candidates=search,
            )

    async def test_handoff_skips_stopping_when_provider_is_unchanged(self) -> None:
        coordinator = MusicPlaybackCoordinator()
        stopped = False

        async def stop(_provider: str) -> None:
            nonlocal stopped
            stopped = True

        await coordinator.handoff("spotify", "spotify", stop_previous=stop)

        self.assertFalse(stopped)

    async def test_handoff_reports_stop_failure_without_blocking_new_source(self) -> None:
        coordinator = MusicPlaybackCoordinator()
        failures: list[str] = []

        async def stop(_provider: str) -> None:
            raise RuntimeError("player unavailable")

        async def report(provider: str, error: Exception) -> None:
            failures.append(f"{provider}: {error}")

        await coordinator.handoff(
            "local",
            "spotify",
            stop_previous=stop,
            report_failure=report,
        )

        self.assertEqual(failures, ["local: player unavailable"])

    async def test_activate_source_recovers_missing_active_device_before_mode_activation(self) -> None:
        coordinator = MusicPlaybackCoordinator()
        initial = ProviderReadiness(
            "spotify", True, True, True, True, details={"active_device": None}
        )
        recovered = ProviderReadiness(
            "spotify", True, True, True, True, active_mode=True,
            details={"active_device": {"id": "device-1"}},
        )
        activated: list[str] = []

        async def probe() -> list[ProviderReadiness]:
            return [initial]

        async def recover(provider: str, _snapshot: ProviderReadiness | None) -> ProviderReadiness:
            self.assertEqual(provider, "spotify")
            return recovered

        async def ensure(snapshot: ProviderReadiness) -> bool:
            activated.append(snapshot.provider)
            return True

        result = await coordinator.activate_source(
            "spotify",
            probe=probe,
            recover=recover,
            ensure=ensure,
        )

        self.assertEqual(result, recovered)
        self.assertEqual(activated, ["spotify"])

    async def test_select_source_prefers_ready_current_provider_before_prompting(self) -> None:
        coordinator = MusicPlaybackCoordinator()
        prompted = False

        async def probe() -> list[ProviderReadiness]:
            return [ProviderReadiness("spotify", True, True, True, True)]

        async def recover(_provider: str, _snapshot: ProviderReadiness | None) -> None:
            return None

        async def choose(_sources: list[str], _exclude: str | None) -> str | None:
            nonlocal prompted
            prompted = True
            return "online"

        source = await coordinator.select_source(
            probe=probe,
            recover=recover,
            choose=choose,
            active_provider="spotify",
        )

        self.assertEqual(source, "spotify")
        self.assertFalse(prompted)

    async def test_select_source_uses_online_when_no_authoritative_route_is_ready(self) -> None:
        coordinator = MusicPlaybackCoordinator()

        async def probe() -> list[ProviderReadiness]:
            return []

        async def recover(_provider: str, _snapshot: ProviderReadiness | None) -> None:
            return None

        async def choose(_sources: list[str], _exclude: str | None) -> str | None:
            raise AssertionError("online fallback does not require a prompt")

        source = await coordinator.select_source(
            probe=probe,
            recover=recover,
            choose=choose,
        )

        self.assertEqual(source, "online")

    async def test_route_authoritative_retries_ranked_provider_after_failure(self) -> None:
        coordinator = MusicPlaybackCoordinator()
        snapshots = [
            ProviderReadiness("spotify", True, True, True, True, preferred=True),
            ProviderReadiness("backup", True, True, True, True),
        ]
        attempts: list[str] = []

        async def confirm(snapshot: ProviderReadiness) -> bool:
            return True

        async def activate(snapshot: ProviderReadiness) -> bool:
            return True

        async def play(snapshot: ProviderReadiness) -> dict[str, object]:
            attempts.append(snapshot.provider)
            return (
                {"status": "playback_failed", "message": "first route failed"}
                if snapshot.provider == "spotify"
                else {"status": "playback_completed", "data": {"provider": snapshot.provider}}
            )

        result = await coordinator.route_authoritative(
            snapshots,
            confirm_route=confirm,
            activate_route=activate,
            play_route=play,
        )

        self.assertEqual(attempts, ["spotify", "backup"])
        self.assertEqual(result["status"], "playback_completed")

    async def test_route_authoritative_respects_hard_provider_rejection(self) -> None:
        coordinator = MusicPlaybackCoordinator()
        snapshots = [ProviderReadiness("spotify", True, True, True, True)]
        played = False

        async def reject(_snapshot: ProviderReadiness) -> bool:
            return False

        async def activate(_snapshot: ProviderReadiness) -> bool:
            return True

        async def play(_snapshot: ProviderReadiness) -> dict[str, object]:
            nonlocal played
            played = True
            return {"status": "playback_completed"}

        result = await coordinator.route_authoritative(
            snapshots,
            requested_provider="spotify",
            hard_provider=True,
            confirm_route=reject,
            activate_route=activate,
            play_route=play,
        )

        self.assertEqual(result["status"], "playback_failed")
        self.assertEqual(result["data"]["attempted"], ["spotify"])
        self.assertFalse(played)

    async def test_selection_is_session_bound_one_use_and_not_returned_to_player(self) -> None:
        store = SelectionStore()
        coordinator = MusicPlaybackCoordinator(store)
        identity = RecordingIdentity("BB88", "方大同", "回到未来", 240_000, metadata_source="itunes")
        selection_ref = store.issue(session_id="s1", turn_id="t1", identity=identity)
        seen: list[RecordingIdentity] = []

        result = await coordinator.play_selected(
            selection_ref,
            session_id="s1",
            turn_id="t1",
            **self.playback_callbacks(seen),
        )
        replay = await coordinator.play_selected(
            selection_ref,
            session_id="s1",
            turn_id="t1",
            **self.playback_callbacks(seen),
        )

        self.assertEqual(result["status"], "playback_completed")
        self.assertEqual(seen, [identity])
        self.assertEqual(replay["error_code"], "SELECTION_EXPIRED")

    async def test_selection_cannot_cross_session_or_turn(self) -> None:
        store = SelectionStore()
        coordinator = MusicPlaybackCoordinator(store)
        selection_ref = store.issue(
            session_id="s1",
            turn_id="t1",
            identity=RecordingIdentity("BB88", "方大同"),
        )
        result = await coordinator.play_selected(
            selection_ref,
            session_id="s2",
            turn_id="t1",
            **self.playback_callbacks(),
        )
        self.assertEqual(result["error_code"], "SELECTION_EXPIRED")

    async def test_selected_playback_prefers_verified_local_cache_before_provider_route(self) -> None:
        store = SelectionStore()
        coordinator = MusicPlaybackCoordinator(store)
        identity = RecordingIdentity("BB88", "方大同")
        selection_ref = store.issue(session_id="s1", turn_id="t1", identity=identity)
        played: list[str] = []
        callbacks = self.playback_callbacks()
        callbacks["candidate"] = {"playback_source": "spotify", "uri": "spotify:track:123"}

        async def resolve_local(_identity: RecordingIdentity) -> dict[str, str]:
            return {"playback_path": "/cache/bb88.mp3"}

        async def play_local(candidate: object) -> dict[str, object]:
            played.append("local")
            self.assertEqual(candidate["playback_path"], "/cache/bb88.mp3")
            return {"status": "playback_completed", "data": {"provider": "local"}}

        async def play_native(*_args: object) -> dict[str, object]:
            played.append("spotify")
            return {"status": "playback_completed"}

        callbacks["resolve_local"] = resolve_local
        callbacks["play_local"] = play_local
        callbacks["play_native"] = play_native
        result = await coordinator.play_selected(
            selection_ref,
            session_id="s1",
            turn_id="t1",
            **callbacks,
        )

        self.assertEqual(result["status"], "playback_completed")
        self.assertEqual(played, ["local"])

    async def test_selection_expires_after_five_minutes(self) -> None:
        now = [100.0]
        store = SelectionStore(clock=lambda: now[0])
        coordinator = MusicPlaybackCoordinator(store)
        selection_ref = store.issue(
            session_id="s1",
            turn_id="t1",
            identity=RecordingIdentity("BB88", "方大同"),
        )
        now[0] += 301
        result = await coordinator.play_selected(
            selection_ref,
            session_id="s1",
            turn_id="t1",
            **self.playback_callbacks(),
        )
        self.assertEqual(result["error_code"], "SELECTION_EXPIRED")

    def test_recording_identity_preserves_edition_and_duration_constraints(self) -> None:
        selected = RecordingIdentity("BB88", "方大同", duration_ms=240_000)
        self.assertTrue(
            recording_identity_matches(
                selected,
                {"title": "BB88", "artist": "方大同", "duration_ms": 244_999},
            )
        )
        self.assertFalse(
            recording_identity_matches(
                selected,
                {"title": "BB88 (Live)", "artist": "方大同", "duration_ms": 240_000},
            )
        )
        self.assertFalse(
            recording_identity_matches(
                selected,
                {"title": "BB88", "artist": "方大同", "duration_ms": 245_001},
            )
        )

    def test_recording_identity_does_not_split_artist_group_names(self) -> None:
        self.assertFalse(
            recording_identity_matches(
                RecordingIdentity("The Sound of Silence", "Simon"),
                {"title": "The Sound of Silence", "artist": "Simon & Garfunkel"},
            )
        )
        self.assertFalse(
            recording_identity_matches(
                RecordingIdentity("Thunderstruck", "AC"),
                {"title": "Thunderstruck", "artist": "AC/DC"},
            )
        )

    def test_recording_identity_allows_feature_credit_with_same_primary_artist(self) -> None:
        selected = RecordingIdentity("爱不来", "方大同", duration_ms=280_195)

        self.assertTrue(
            recording_identity_matches(
                selected,
                {
                    "title": "爱不来 (feat. Miss Ko葛仲珊)",
                    "artist": "方大同, 葛仲珊",
                    "duration_ms": 280_195,
                },
            )
        )
        self.assertFalse(
            recording_identity_matches(
                selected,
                {
                    "title": "爱不来 (Live版)",
                    "artist": "方大同, 葛仲珊",
                    "duration_ms": 280_195,
                },
            )
        )
        self.assertFalse(
            recording_identity_matches(
                selected,
                {
                    "title": "爱不来 (feat. Miss Ko葛仲珊)",
                    "artist": "葛仲珊, 方大同",
                    "duration_ms": 280_195,
                },
            )
        )


if __name__ == "__main__":
    unittest.main()
