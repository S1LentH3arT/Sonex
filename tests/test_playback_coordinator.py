from __future__ import annotations

import unittest

from src.music.playback_coordinator import (
    MusicPlaybackCoordinator,
    ProviderReadiness,
    RecordingIdentity,
    SelectionStore,
    rank_authoritative_providers,
    recording_identity_matches,
)


class PlaybackCoordinatorTests(unittest.IsolatedAsyncioTestCase):
    async def test_selection_is_session_bound_one_use_and_not_returned_to_player(self) -> None:
        store = SelectionStore()
        coordinator = MusicPlaybackCoordinator(store)
        identity = RecordingIdentity("BB88", "方大同", "回到未来", 240_000, metadata_source="itunes")
        selection_ref = store.issue(session_id="s1", turn_id="t1", identity=identity)
        seen: list[RecordingIdentity] = []

        async def play(selected: RecordingIdentity) -> dict[str, object]:
            seen.append(selected)
            return {"status": "playback_completed", "data": {"provider": "local"}}

        result = await coordinator.play(
            selection_ref,
            session_id="s1",
            turn_id="t1",
            play_selected=play,
        )
        replay = await coordinator.play(
            selection_ref,
            session_id="s1",
            turn_id="t1",
            play_selected=play,
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
        result = await coordinator.play(
            selection_ref,
            session_id="s2",
            turn_id="t1",
            play_selected=lambda _: {"status": "playback_completed"},
        )
        self.assertEqual(result["error_code"], "SELECTION_EXPIRED")

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
        result = await coordinator.play(
            selection_ref,
            session_id="s1",
            turn_id="t1",
            play_selected=lambda _: {"status": "playback_completed"},
        )
        self.assertEqual(result["error_code"], "SELECTION_EXPIRED")

    def test_recording_identity_requires_exact_title_artist_and_duration_tolerance(self) -> None:
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

    def test_authoritative_provider_ranking_prefers_active_verified_experience(self) -> None:
        providers = [
            ProviderReadiness(
                "netease", True, True, True, True,
                session_verified=True, verified_success_rate=0.9,
                startup_latency_ms=250, capability_score=2,
            ),
            ProviderReadiness(
                "spotify", True, True, True, True,
                active_mode=True, verified_success_rate=0.6,
                startup_latency_ms=500, capability_score=3,
            ),
        ]

        ranked = rank_authoritative_providers(providers)

        self.assertEqual([item.provider for item in ranked], ["spotify", "netease"])

    def test_explicit_provider_is_a_hard_ranking_constraint(self) -> None:
        providers = [
            ProviderReadiness("spotify", True, True, True, True),
            ProviderReadiness("netease", True, True, True, True),
        ]

        ranked = rank_authoritative_providers(
            providers,
            requested_provider="netease",
        )

        self.assertEqual([item.provider for item in ranked], ["netease"])

    def test_recent_playback_context_precedes_default_provider_priority(self) -> None:
        providers = [
            ProviderReadiness("spotify", True, True, True, True),
            ProviderReadiness("netease", True, True, True, True, preferred=True),
        ]

        ranked = rank_authoritative_providers(providers)

        self.assertEqual([item.provider for item in ranked], ["netease", "spotify"])

    def test_spotify_precedes_netease_without_playback_context(self) -> None:
        providers = [
            ProviderReadiness(
                "netease", True, True, True, True,
                startup_latency_ms=1, capability_score=99,
            ),
            ProviderReadiness(
                "spotify", True, True, True, True,
                startup_latency_ms=999, capability_score=1,
            ),
        ]

        ranked = rank_authoritative_providers(providers)

        self.assertEqual([item.provider for item in ranked], ["spotify", "netease"])


if __name__ == "__main__":
    unittest.main()
