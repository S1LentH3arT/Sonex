"""Application service composing token, companion, matching, and Apple queue state."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from src.apple_mode.companion import (
    AppleCompanionSnapshot,
    AppleCompanionUnauthorized,
    MusicKitCompanion,
)
from src.apple_mode.matching import RankedAppleCandidates, rank_apple_candidates
from src.apple_mode.token_provider import (
    DeveloperTokenManager,
    DeveloperTokenProvider,
    developer_token_provider_from_env,
)


@dataclass(frozen=True, slots=True)
class AppleEntryStart:
    url: str
    browser_opened: bool
    already_ready: bool


class AppleModeService:
    """Deep Apple Mode interface consumed by WebSocket orchestration."""

    def __init__(
        self,
        *,
        companion: MusicKitCompanion | None = None,
        token_provider_factory: Callable[[], DeveloperTokenProvider] = developer_token_provider_from_env,
    ) -> None:
        self.companion = companion or MusicKitCompanion()
        self._token_provider_factory = token_provider_factory
        self._token_manager: DeveloperTokenManager | None = None

    @property
    def snapshot(self) -> AppleCompanionSnapshot:
        return self.companion.snapshot

    async def begin_entry(self, *, open_browser: bool) -> AppleEntryStart:
        if self.snapshot.connected and self.snapshot.authorized and self.snapshot.can_play and self.snapshot.storefront:
            return AppleEntryStart(self.companion.launch_url, False, True)
        manager = self._token_manager
        if manager is None:
            manager = DeveloperTokenManager(self._token_provider_factory())
        lease = await manager.get()
        url = await self.companion.start(lease)
        self._token_manager = manager
        opened = await self.companion.open_browser() if open_browser else False
        return AppleEntryStart(url=url, browser_opened=opened, already_ready=False)

    async def complete_entry(self) -> AppleCompanionSnapshot:
        return await self.companion.wait_until_ready()

    async def search(
        self,
        query: str,
        limit: int = 10,
        *,
        match_query: str | None = None,
    ) -> RankedAppleCandidates:
        try:
            tracks = await self.companion.search(query, limit=limit)
        except AppleCompanionUnauthorized:
            await self.refresh_developer_token(force=True)
            tracks = await self.companion.search(query, limit=limit)
        return rank_apple_candidates(match_query or query, tracks)

    async def play(self, track: dict[str, Any]) -> AppleCompanionSnapshot:
        return await self.companion.play(track)

    async def queue_add(self, track: dict[str, Any]) -> AppleCompanionSnapshot:
        return await self.companion.queue_add(track)

    async def control(self, action: str) -> AppleCompanionSnapshot:
        return await self.companion.control(action)

    async def refresh_developer_token(self, *, force: bool = False) -> None:
        """Refresh and publish the in-memory developer-token lease if needed."""
        manager = self._token_manager
        if manager is None:
            return
        lease = await manager.get(force_refresh=force)
        await self.companion.update_developer_token(lease)

    async def exit_mode(self) -> None:
        await self.companion.deactivate()

    async def clear_queue(self) -> None:
        await self.companion.clear_queue()

    async def logout(self) -> None:
        await self.companion.logout()
        if self._token_manager is not None:
            self._token_manager.clear()

    def queue_tracks(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self.snapshot.queue]

    def player_state(self) -> dict[str, Any]:
        player = dict(self.snapshot.player)
        if not player:
            return {}
        player["provider"] = "apple_music"
        player["source"] = "apple_music"
        return player
