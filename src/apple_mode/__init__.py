"""Apple Mode lifecycle, MusicKit companion, and token-provider boundaries."""

from src.apple_mode.companion import (
    AppleCompanionError,
    AppleCompanionSnapshot,
    AppleCompanionUnauthorized,
    MusicKitCompanion,
)
from src.apple_mode.matching import AppleCandidateDecision, rank_apple_candidates
from src.apple_mode.provider_mode import (
    ProviderMode,
    ProviderModeCoordinator,
    ProviderModeState,
    clear_provider_mode_intent,
    load_provider_mode_intent,
    save_provider_mode_intent,
)
from src.apple_mode.service import AppleEntryStart, AppleModeService
from src.apple_mode.token_provider import (
    DeveloperTokenLease,
    DeveloperTokenManager,
    DeveloperTokenProvider,
    developer_token_provider_from_env,
)

__all__ = [
    "AppleCandidateDecision",
    "AppleEntryStart",
    "AppleModeService",
    "AppleCompanionError",
    "AppleCompanionSnapshot",
    "AppleCompanionUnauthorized",
    "DeveloperTokenLease",
    "DeveloperTokenManager",
    "DeveloperTokenProvider",
    "MusicKitCompanion",
    "ProviderMode",
    "ProviderModeCoordinator",
    "ProviderModeState",
    "clear_provider_mode_intent",
    "developer_token_provider_from_env",
    "load_provider_mode_intent",
    "rank_apple_candidates",
    "save_provider_mode_intent",
]
