"""Provider catalog policy shared by the Agent's Query and Recommend tools.

This module owns provider/resource vocabulary and provider-independent result
normalization. External calls remain in ``agent_surface`` so this seam is
fully deterministic and easy to test.
"""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Iterable, Mapping
from typing import Any, Callable


QUERY_PROVIDERS = ("current", "spotify", "jamendo", "audius", "local")
QUERY_RESOURCES = (
    "catalog",
    "account",
    "playlists",
    "playlist_tracks",
    "saved_tracks",
    "queue",
    "recent",
    "devices",
    "playback",
)
RECOMMEND_PROVIDERS = ("spotify",)

_SENSITIVE_KEYS = {
    "access_token", "refresh_token", "authorization", "cookie", "cookies",
    "headers", "password", "secret", "token",
}
_EPHEMERAL_URL_KEYS = {
    "audio_url", "download_url", "file", "playback_source_url", "preview_url",
    "stream_url", "url",
}
SAFE_ITEM_KEYS = {
    "account_label", "album", "album_name", "artist", "artists", "capabilities",
    "description", "device_id", "duration_ms", "explicit", "id", "is_active",
    "is_playing", "label", "logged_in", "name", "played_at", "position_ms",
    "product", "provider", "recommendation_reason", "requires_resolution", "status",
    "title", "total", "track_number", "type", "uri",
}


TrackReferenceWriter = Callable[[str, dict[str, Any]], str]


def normalize_provider(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_")


def bounded_limit(value: int, *, maximum: int = 50, default: int = 10) -> int:
    return min(maximum, max(1, int(value or default)))


def safe_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): safe_value(item)
            for key, item in value.items()
            if str(key).casefold() not in _SENSITIVE_KEYS
            and str(key).casefold() not in _EPHEMERAL_URL_KEYS
        }
    if isinstance(value, (list, tuple)):
        return [safe_value(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def normalize_item(
    provider: str,
    item: dict[str, Any],
    remember_reference: TrackReferenceWriter,
) -> dict[str, Any]:
    normalized = {
        str(key): safe_value(value)
        for key, value in item.items()
        if str(key) in SAFE_ITEM_KEYS
    }
    normalized.setdefault("provider", provider)
    normalized["ref"] = remember_reference(provider, normalized)
    return normalized


def extract_items(data: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    for key in ("tracks", "songs", "playlists", "devices", "items", "results", "queue"):
        value = data.get(key)
        if isinstance(value, list):
            return [item for item in value[:limit] if isinstance(item, dict)]
    item = data.get("item")
    return [item] if isinstance(item, dict) else []


def recommendation_keys(track: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    for key in ("uri", "id", "url"):
        value = str(track.get(key) or "").strip()
        if value:
            keys.add(f"{key}:{value}")
    name = str(track.get("name") or track.get("title") or "").strip().casefold()
    artist = str(track.get("artist") or "").strip().casefold()
    if name or artist:
        keys.add(f"text:{name}|{artist}")
    return keys


@dataclass(frozen=True)
class ProviderCatalog:
    """Stable vocabulary and routing policy for catalog-backed tools."""

    query_providers: tuple[str, ...] = QUERY_PROVIDERS
    query_resources: tuple[str, ...] = QUERY_RESOURCES
    recommendation_providers: tuple[str, ...] = RECOMMEND_PROVIDERS

    def resolve_query_provider(
        self,
        provider: Any,
        current_provider: Callable[[], str | None],
    ) -> tuple[str | None, str | None]:
        normalized = normalize_provider(provider)
        if normalized not in self.query_providers:
            return None, "PROVIDER_UNSUPPORTED"
        if normalized != "current":
            return normalized, None
        resolved = current_provider()
        return (resolved, None) if resolved else (None, "CONNECTION_REQUIRED")

    @staticmethod
    def is_connected(provider: str, is_enabled: Callable[[str], bool]) -> bool:
        """Apply the local-provider exception to external readiness checks."""
        return provider == "local" or is_enabled(provider)

    @staticmethod
    def page(cursor: str | None, item_count: int, limit: int) -> dict[str, Any]:
        return {
            "cursor": str(int(cursor or 0) + item_count) if item_count else None,
            "has_more": item_count >= limit,
        }

    def merge_recommendations(
        self,
        provider_tracks: Mapping[str, Iterable[dict[str, Any]]],
        ordered_providers: Iterable[str],
        limit: int,
        normalize: Callable[[str, dict[str, Any]], dict[str, Any]],
    ) -> list[dict[str, Any]]:
        tracks: list[dict[str, Any]] = []
        seen: set[str] = set()
        for provider in ordered_providers:
            for item in provider_tracks.get(provider, ()):
                keys = recommendation_keys(item)
                if not keys or keys & seen:
                    continue
                seen.update(keys)
                tracks.append(normalize(provider, item))
                if len(tracks) >= limit:
                    return tracks
        return tracks

    def recommendation_order(self, requested: Any, current_provider: Callable[[], str | None]) -> tuple[str | None, str | None, list[str]]:
        normalized = normalize_provider(requested) or "current"
        allowed = ("current", *self.recommendation_providers)
        if normalized not in allowed:
            return None, "PROVIDER_UNSUPPORTED", list(allowed)
        preferred = current_provider() if normalized == "current" else normalized
        ordered = list(self.recommendation_providers)
        if preferred in ordered:
            ordered.remove(preferred)
            ordered.insert(0, preferred)
        return preferred, None, ordered

    def query_tool_and_args(
        self,
        provider: str,
        resource: str,
        *,
        query: str | None,
        ref: str | None,
        limit: int,
        cursor: str | None,
    ) -> tuple[str | None, dict[str, Any]]:
        offset = max(0, int(cursor)) if str(cursor or "").isdigit() else 0
        if provider == "spotify":
            mapping = {
                "catalog": ("spotify_search", {"query": query, "limit": limit}),
                "account": ("spotify_account", {}),
                "playlists": ("spotify_playlists", {"limit": limit, "offset": offset}),
                "playlist_tracks": ("spotify_playlist_tracks", {"playlist_id": self.decode_ref(provider, ref), "limit": limit, "offset": offset}),
                "saved_tracks": ("spotify_saved_tracks", {"limit": limit, "offset": offset}),
                "queue": ("spotify_queue", {"limit": limit}),
                "recent": ("spotify_recent_tracks", {"limit": limit}),
                "devices": ("spotify_devices", {}),
                "playback": ("spotify_current_playback", {}),
            }
            return mapping.get(resource, (None, {}))
        return None, {}

    @staticmethod
    def decode_ref(provider: str, ref: str | None) -> str | None:
        value = str(ref or "").strip()
        prefix = f"{provider}:"
        if value.startswith(prefix):
            parts = value.split(":", 2)
            return parts[2] if len(parts) == 3 else None
        return value or None


CATALOG = ProviderCatalog()
