"""Small, explicit tool surface exposed to the Sonex Agent."""

from __future__ import annotations

import hashlib
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass
from typing import Any, Callable

from src.memory.tool import search_context, search_memory
from src.log import sonex_home
from src.tools.agent_modify import Modify
from src.tools.local_play import search_local_file
from src.tools.playback_queue import playback_queue_snapshot
from src.tools.registry import Params, ToolRegistry, registry
from src.tools.result import ToolResult
from src.tools.spotify_play import spotify_recommend
from src.tools.track_refs import (
    remember_existing_track_reference,
    remember_track_reference,
)
from src.tools.up_next import up_next_snapshot

QUERY_PROVIDERS = (
    "current",
    "spotify",
    "netease",
    "jamendo",
    "audius",
    "local",
)
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
RECOMMEND_PROVIDERS = ("spotify", "netease")
RECOMMEND_TIMEOUT_SECONDS = 8.0
_MAX_LOCAL_REFS = 512
_LOCAL_REFS: OrderedDict[str, str] = OrderedDict()
_LOCAL_REFS_LOCK = threading.Lock()

_SENSITIVE_KEYS = {
    "access_token",
    "refresh_token",
    "authorization",
    "cookie",
    "cookies",
    "headers",
    "password",
    "secret",
    "token",
}
_EPHEMERAL_URL_KEYS = {
    "audio_url",
    "download_url",
    "file",
    "playback_source_url",
    "preview_url",
    "stream_url",
    "url",
}
_SAFE_ITEM_KEYS = {
    "account_label",
    "album",
    "album_name",
    "artist",
    "artists",
    "capabilities",
    "description",
    "device_id",
    "duration_ms",
    "explicit",
    "id",
    "is_active",
    "is_playing",
    "label",
    "logged_in",
    "name",
    "played_at",
    "position_ms",
    "product",
    "provider",
    "recommendation_reason",
    "requires_resolution",
    "status",
    "title",
    "total",
    "track_number",
    "type",
    "uri",
}


def _failure(
    tool: str,
    message: str,
    error_code: str,
    *,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return ToolResult.fail(
        tool=tool,
        message=message,
        error_code=error_code,
        data=data or {},
    ).to_dict()


def _normalize_provider(value: str) -> str:
    return str(value or "").strip().lower().replace("-", "_")


def _bounded_limit(value: int) -> int:
    return min(50, max(1, int(value or 10)))


def _safe_value(value: Any) -> Any:
    if isinstance(value, dict):
        safe: dict[str, Any] = {}
        for key, item in value.items():
            normalized_key = str(key).casefold()
            if normalized_key in _SENSITIVE_KEYS or normalized_key in _EPHEMERAL_URL_KEYS:
                continue
            safe[str(key)] = _safe_value(item)
        return safe
    if isinstance(value, list):
        return [_safe_value(item) for item in value]
    if isinstance(value, tuple):
        return [_safe_value(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _opaque_ref(provider: str, item: dict[str, Any]) -> str | None:
    for key in ("uri", "id", "device_id"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return f"{provider}:{key}:{value.strip()}"
    return None


def remember_local_track(path: str) -> str:
    """Return an opaque process-local reference without exposing a host path."""
    normalized = str(path)
    digest = hashlib.sha256(normalized.encode("utf-8", errors="replace")).hexdigest()[:24]
    ref = f"local:track:{digest}"
    with _LOCAL_REFS_LOCK:
        _LOCAL_REFS[ref] = normalized
        _LOCAL_REFS.move_to_end(ref)
        while len(_LOCAL_REFS) > _MAX_LOCAL_REFS:
            _LOCAL_REFS.popitem(last=False)
    return ref


def _resolve_local_track(ref: str) -> str | None:
    with _LOCAL_REFS_LOCK:
        path = _LOCAL_REFS.get(ref)
        if path is not None:
            _LOCAL_REFS.move_to_end(ref)
        return path


def _normalize_item(provider: str, item: dict[str, Any]) -> dict[str, Any]:
    normalized = {
        str(key): _safe_value(value)
        for key, value in item.items()
        if str(key) in _SAFE_ITEM_KEYS
    }
    normalized.setdefault("provider", provider)
    ref = remember_track_reference(
        provider,
        normalized,
        playable=provider in {"spotify", "netease", "local"},
    )
    normalized["ref"] = ref
    return normalized


def _normalize_persisted_track(item: dict[str, Any]) -> dict[str, Any]:
    provider = _normalize_provider(str(item.get("provider") or "unknown"))
    normalized = {
        str(key): _safe_value(value)
        for key, value in item.items()
        if str(key) in _SAFE_ITEM_KEYS or str(key) in {"ref", "playable"}
    }
    ref = str(item.get("ref") or "").strip()
    if ref:
        internal = dict(normalized)
        local_path = str(
            item.get("audio_path")
            or item.get("file_path")
            or item.get("path")
            or ""
        ).strip()
        if provider == "local" and local_path:
            with _LOCAL_REFS_LOCK:
                _LOCAL_REFS[ref] = local_path
                _LOCAL_REFS.move_to_end(ref)
                while len(_LOCAL_REFS) > _MAX_LOCAL_REFS:
                    _LOCAL_REFS.popitem(last=False)
            internal["audio_path"] = local_path
        remember_existing_track_reference(
            ref,
            provider,
            internal,
            playable=bool(item.get("playable")),
        )
        normalized["ref"] = ref
    normalized["provider"] = provider
    return normalized


def _normalize_recent_track(item: dict[str, Any]) -> dict[str, Any]:
    provider = _normalize_provider(
        str(item.get("provider") or item.get("source") or "unknown")
    )
    local_path = str(
        item.get("audio_path")
        or item.get("file_path")
        or item.get("path")
        or ""
    ).strip()
    if provider == "local" and local_path:
        ref = remember_local_track(local_path)
        normalized = {
            str(key): _safe_value(value)
            for key, value in item.items()
            if str(key) in _SAFE_ITEM_KEYS
        }
        normalized["provider"] = provider
        normalized["ref"] = ref
        remember_existing_track_reference(
            ref,
            provider,
            {**normalized, "audio_path": local_path},
            playable=True,
        )
        return normalized
    return _normalize_item(provider, item)


def _extract_items(data: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    for key in (
        "tracks",
        "songs",
        "playlists",
        "devices",
        "items",
        "results",
        "queue",
    ):
        value = data.get(key)
        if isinstance(value, list):
            return [item for item in value[:limit] if isinstance(item, dict)]
    item = data.get("item")
    if isinstance(item, dict):
        return [item]
    return []


def Read(query: str, source: str = "auto", limit: int = 8) -> dict[str, Any]:
    """Retrieve relevant structured context, user preferences, or memory."""
    normalized_query = str(query or "").strip()
    normalized_source = str(source or "auto").strip().casefold()
    if not normalized_query:
        return _failure("Read", "Read query cannot be empty.", "INVALID_ARGUMENT")
    if normalized_source not in {"auto", "context", "user", "memory"}:
        return _failure(
            "Read",
            "Read source must be auto, context, user, or memory.",
            "INVALID_ARGUMENT",
        )
    bounded = min(20, max(1, int(limit or 8)))
    snippets: list[dict[str, Any]] = []
    if normalized_source in {"auto", "context"}:
        snippets.extend(search_context(normalized_query, target="auto", limit=bounded))
    if normalized_source in {"auto", "user"}:
        snippets.extend(search_memory(normalized_query, target="user", limit=bounded))
    if normalized_source in {"auto", "memory"}:
        snippets.extend(search_memory(normalized_query, target="memory", limit=bounded))
    return ToolResult.success(
        tool="Read",
        message=f"Retrieved {min(len(snippets), bounded)} relevant snippet(s).",
        data={
            "source": normalized_source,
            "query": normalized_query,
            "snippets": _safe_value(snippets[:bounded]),
        },
    ).to_dict()


def _resolve_query_provider(provider: str) -> tuple[str | None, dict[str, Any] | None]:
    normalized = _normalize_provider(provider)
    if normalized not in QUERY_PROVIDERS:
        return None, _failure(
            "Query",
            f"Unknown music provider: {provider}.",
            "PROVIDER_UNSUPPORTED",
            data={"providers": list(QUERY_PROVIDERS)},
        )
    if normalized != "current":
        return normalized, None
    current = _current_extension_provider()
    if current is None:
        return None, _failure(
            "Query",
            "No current music provider is connected.",
            "CONNECTION_REQUIRED",
        )
    return current, None


def _current_extension_provider() -> str | None:
    """Return the first enabled built-in provider without legacy state."""
    from src.extensions import ExtensionManager, ExtensionStatus

    manager = ExtensionManager()
    for provider in ("spotify", "jamendo", "audius", "youtube"):
        if manager.get(provider).status is ExtensionStatus.ENABLED:
            return provider
    return None


def _query_tool_and_args(
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
            "playlist_tracks": (
                "spotify_playlist_tracks",
                {"playlist_id": _decode_ref(provider, ref), "limit": limit, "offset": offset},
            ),
            "saved_tracks": ("spotify_saved_tracks", {"limit": limit, "offset": offset}),
            "queue": ("spotify_queue", {"limit": limit}),
            "recent": ("spotify_recent_tracks", {"limit": limit}),
            "devices": ("spotify_devices", {}),
            "playback": ("spotify_current_playback", {}),
        }
        return mapping.get(resource, (None, {}))
    if provider == "netease":
        mapping = {
            "catalog": ("netease_search", {"query": query, "limit": limit}),
            "account": ("netease_account", {}),
        }
        return mapping.get(resource, (None, {}))
    if provider == "local":
        return None, {}
    return None, {}


def _decode_ref(provider: str, ref: str | None) -> str | None:
    value = str(ref or "").strip()
    prefix = f"{provider}:"
    if value.startswith(prefix):
        parts = value.split(":", 2)
        return parts[2] if len(parts) == 3 else None
    return value or None


def _provider_connected(provider: str) -> bool:
    if provider == "local":
        return True
    if provider == "netease":
        return False
    try:
        from src.extensions import ExtensionManager, ExtensionStatus

        return ExtensionManager().get(provider).status is ExtensionStatus.ENABLED
    except Exception:
        return False


def Query(
    provider: str,
    resource: str,
    query: str | None = None,
    ref: str | None = None,
    limit: int = 10,
    cursor: str | None = None,
) -> dict[str, Any]:
    """Read one normalized music resource from one explicit provider."""
    resolved_provider, error = _resolve_query_provider(provider)
    if error is not None:
        return error
    assert resolved_provider is not None
    normalized_resource = str(resource or "").strip().casefold()
    if normalized_resource not in QUERY_RESOURCES:
        return _failure(
            "Query",
            f"Unknown music resource: {resource}.",
            "RESOURCE_UNSUPPORTED",
            data={"resources": list(QUERY_RESOURCES)},
        )
    normalized_query = str(query or "").strip() or None
    normalized_ref = str(ref or "").strip() or None
    if normalized_resource == "catalog" and normalized_query is None:
        return _failure("Query", "Catalog queries require query.", "INVALID_ARGUMENT")
    if normalized_resource == "playlist_tracks" and normalized_ref is None:
        return _failure("Query", "Playlist tracks require ref.", "INVALID_ARGUMENT")
    if not _provider_connected(resolved_provider):
        return _failure(
            "Query",
            f"{resolved_provider} is not connected.",
            "CONNECTION_REQUIRED",
            data={"provider": resolved_provider},
        )

    bounded = _bounded_limit(limit)
    if resolved_provider == "local":
        if normalized_resource == "catalog":
            path = search_local_file(normalized_query or "")
            local_ref = (
                remember_local_track(path)
                if path
                and not path.startswith("No local files found")
                and path != "Path outside user workspace."
                else None
            )
            if local_ref:
                remember_existing_track_reference(
                    local_ref,
                    "local",
                    {
                        "provider": "local",
                        "title": normalized_query,
                        "name": normalized_query,
                        "audio_path": path,
                    },
                    playable=True,
                )
            items = (
                [
                    {
                        "provider": "local",
                        "title": normalized_query,
                        "name": normalized_query,
                        "ref": local_ref,
                    }
                ]
                if local_ref
                else []
            )
        elif normalized_resource == "queue":
            items = [
                _normalize_persisted_track(item)
                for item in up_next_snapshot()["items"][:bounded]
            ]
        elif normalized_resource == "recent":
            items = [
                _normalize_recent_track(item)
                for item in playback_queue_snapshot()[:bounded]
            ]
        elif normalized_resource == "playback":
            raw = registry.invoke_system("local_playback_status", {})
            data = raw.get("data") if isinstance(raw, dict) else {}
            return ToolResult.success(
                tool="Query",
                message="Local playback loaded.",
                data={
                    "provider": "local",
                    "resource": normalized_resource,
                    "value": _safe_value(data),
                    "items": [],
                    "capabilities": {"playback": True},
                    "page": {"cursor": None, "has_more": False},
                },
            ).to_dict()
        else:
            return _failure(
                "Query",
                f"{normalized_resource} is not supported by local.",
                "RESOURCE_UNSUPPORTED",
                data={"provider": "local"},
            )
        return ToolResult.success(
            tool="Query",
            message=f"Loaded {len(items)} local item(s).",
            data={
                "provider": "local",
                "resource": normalized_resource,
                "items": items,
                "capabilities": {
                    "catalog": True,
                    "queue": True,
                    "recent": True,
                    "playback": True,
                },
                "page": {"cursor": None, "has_more": False},
            },
        ).to_dict()

    tool_name, args = _query_tool_and_args(
        resolved_provider,
        normalized_resource,
        query=normalized_query,
        ref=normalized_ref,
        limit=bounded,
        cursor=cursor,
    )
    if tool_name is None:
        return _failure(
            "Query",
            f"{normalized_resource} is not supported by {resolved_provider}.",
            "RESOURCE_UNSUPPORTED",
            data={"provider": resolved_provider, "resource": normalized_resource},
        )
    raw = registry.invoke_system(
        tool_name,
        {key: value for key, value in args.items() if value is not None},
    )
    if not isinstance(raw, dict):
        return _failure("Query", "Provider returned an invalid result.", "PROVIDER_ERROR")
    if str(raw.get("status") or "").casefold() not in {"success", "ok"}:
        error_code = str(raw.get("error_code") or "PROVIDER_ERROR")
        return _failure(
            "Query",
            str(raw.get("message") or "Provider query failed."),
            error_code,
            data={"provider": resolved_provider, "resource": normalized_resource},
        )
    raw_data = raw.get("data") if isinstance(raw.get("data"), dict) else {}
    items = [
        _normalize_item(resolved_provider, item)
        for item in _extract_items(raw_data, bounded)
    ]
    capabilities = raw_data.get("capabilities")
    page = {
        "cursor": str(int(cursor or 0) + len(items)) if items else None,
        "has_more": len(items) >= bounded,
    }
    return ToolResult.success(
        tool="Query",
        message=str(raw.get("message") or f"Loaded {len(items)} item(s)."),
        data={
            "provider": resolved_provider,
            "resource": normalized_resource,
            "items": items,
            "value": _safe_value(raw_data) if not items else None,
            "capabilities": _safe_value(capabilities or {}),
            "page": page,
        },
    ).to_dict()


def _recommendation_keys(track: dict[str, Any]) -> set[str]:
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


def _recommendation_preferences() -> str:
    try:
        return (sonex_home() / "USER.md").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def Recommend(
    query: str = "",
    provider: str = "current",
    limit: int = 5,
) -> dict[str, Any]:
    """Aggregate one bounded recommendation request across connected authorities."""
    taste = str(query or "").strip()
    bounded = min(10, max(1, int(limit or 5)))
    requested = _normalize_provider(provider) or "current"
    if requested not in {"current", *RECOMMEND_PROVIDERS}:
        return _failure(
            "Recommend",
            f"Unknown recommendation provider: {provider}.",
            "PROVIDER_UNSUPPORTED",
            data={"providers": ["current", *RECOMMEND_PROVIDERS]},
        )

    from src.extensions import ExtensionManager, ExtensionStatus

    manager = ExtensionManager()
    preferred = (
        _current_extension_provider()
        if requested == "current"
        else requested
    )
    ordered = list(RECOMMEND_PROVIDERS)
    if preferred in ordered:
        ordered.remove(preferred)
        ordered.insert(0, preferred)

    recent_tracks = playback_queue_snapshot()
    preferences = _recommendation_preferences()
    skipped: list[dict[str, str]] = []
    connected: list[str] = []
    for provider_id in ordered:
        if provider_id == "netease":
            skipped.append(
                {
                    "provider": provider_id,
                    "reason": "recommendation_capability_unavailable",
                }
            )
            continue
        if manager.get(provider_id).status is not ExtensionStatus.ENABLED:
            skipped.append(
                {"provider": provider_id, "reason": "not_connected"}
            )
            continue
        connected.append(provider_id)

    calls: dict[str, Callable[..., dict[str, Any]]] = {
        "spotify": spotify_recommend,
    }
    executor = ThreadPoolExecutor(
        max_workers=max(1, len(connected)),
        thread_name_prefix="sonex-recommend",
    )
    futures = {
        executor.submit(
            calls[provider_id],
            query=taste,
            limit=bounded,
            recent_tracks=recent_tracks,
            preferences=preferences,
        ): provider_id
        for provider_id in connected
    }
    done, pending = wait(futures, timeout=RECOMMEND_TIMEOUT_SECONDS)
    failed: list[dict[str, str]] = []
    provider_tracks: dict[str, list[dict[str, Any]]] = {}
    for future in done:
        provider_id = futures[future]
        try:
            result = future.result()
        except Exception as exc:
            failed.append(
                {"provider": provider_id, "reason": str(exc) or "provider_failed"}
            )
            continue
        if not isinstance(result, dict) or str(result.get("status") or "").casefold() not in {
            "success",
            "ok",
        }:
            failed.append(
                {
                    "provider": provider_id,
                    "reason": str(
                        result.get("message")
                        if isinstance(result, dict)
                        else "invalid_provider_result"
                    ),
                }
            )
            continue
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        provider_tracks[provider_id] = [
            item
            for item in data.get("tracks", [])
            if isinstance(item, dict)
        ]
    for future in pending:
        provider_id = futures[future]
        future.cancel()
        failed.append({"provider": provider_id, "reason": "timed_out"})
    executor.shutdown(wait=False, cancel_futures=True)

    tracks: list[dict[str, Any]] = []
    seen: set[str] = set()
    for provider_id in ordered:
        for item in provider_tracks.get(provider_id, []):
            keys = _recommendation_keys(item)
            if not keys or keys & seen:
                continue
            seen.update(keys)
            tracks.append(_normalize_item(provider_id, item))
            if len(tracks) >= bounded:
                break
        if len(tracks) >= bounded:
            break

    data = {
        "query": taste,
        "tracks": tracks,
        "skipped": skipped,
        "failed": failed,
        "providers": ordered,
    }
    if not tracks:
        return ToolResult.success(
            tool="Recommend",
            message=(
                "No catalog-backed tracks are available. "
                "Continue with text-only music recommendations."
            ),
            data={**data, "text_only": True},
        ).to_dict()
    return ToolResult.success(
        tool="Recommend",
        message=f"Recommended {len(tracks)} track(s).",
        data=data,
    ).to_dict()


@dataclass(frozen=True)
class Workflow:
    name: str
    handler: Callable[[dict[str, Any]], dict[str, Any]]


class WorkflowRegistry:
    """Allowlist stable public workflows without exposing Python names."""

    def __init__(self) -> None:
        self._workflows: dict[str, Workflow] = {}

    def register(self, workflow: Workflow) -> None:
        if workflow.name in self._workflows:
            raise ValueError(f"Workflow '{workflow.name}' is already registered.")
        self._workflows[workflow.name] = workflow

    def invoke(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        workflow = self._workflows.get(name)
        if workflow is None:
            return _failure(
                "Call",
                f"Workflow '{name}' is not allowed.",
                "WORKFLOW_NOT_ALLOWED",
            )
        return workflow.handler(dict(arguments or {}))


def _select_workflow(arguments: dict[str, Any]) -> dict[str, Any]:
    query = str(arguments.get("query") or "").strip()
    if not query:
        return _failure("Call", "playback.select requires query.", "INVALID_ARGUMENT")
    return {
        "status": "requires_play_selection",
        "tool": "Call",
        "message": f"Select a playback candidate for {query}.",
        "data": {
            "workflow": "playback.select",
            "query": query,
            "provider": _normalize_provider(str(arguments.get("provider") or "current")),
            "provider_constraint": str(
                arguments.get("provider_constraint") or "preference"
            ).strip().casefold(),
            "timeout_seconds": 60,
        },
        "error_code": None,
    }


def _play_workflow(arguments: dict[str, Any]) -> dict[str, Any]:
    provider = _normalize_provider(str(arguments.get("provider") or "current"))
    if provider == "current":
        provider = _current_extension_provider() or "local"
    query = str(arguments.get("query") or "").strip()
    ref = str(arguments.get("ref") or "").strip()
    if not query and not ref:
        return _failure(
            "Call",
            "playback.play requires query or ref.",
            "INVALID_ARGUMENT",
        )
    if provider == "spotify":
        return registry.invoke_system(
            "spotify_play",
            {"query": query or None, "uri": _decode_ref("spotify", ref)},
        )
    if provider == "local":
        if ref:
            local_path = _resolve_local_track(ref)
            if local_path is None:
                return _failure(
                    "Call",
                    "The local track reference is invalid or expired.",
                    "INVALID_REF",
                )
            query = local_path
        return registry.invoke_system(
            "play_local_song",
            {"query": query, "player": "auto"},
        )
    if provider in {"jamendo", "audius"}:
        return registry.invoke_system("play_youtube_song", {"query": query or ref})
    if provider == "netease":
        netease_ref = _decode_ref("netease", ref) or ""
        encrypted_id, separator, original_id = netease_ref.partition("|")
        if not separator or not encrypted_id or not original_id:
            return _failure(
                "Call",
                "NetEase playback requires a selected encrypted and original track ID.",
                "INVALID_REF",
            )
        return registry.invoke_system(
            "netease_play",
            {"encrypted_id": encrypted_id, "original_id": original_id},
        )
    return _failure(
        "Call",
        f"Playback is not supported for {provider}.",
        "WORKFLOW_UNAVAILABLE",
    )


def _control_workflow(arguments: dict[str, Any]) -> dict[str, Any]:
    provider = _normalize_provider(str(arguments.get("provider") or "current"))
    if provider == "current":
        provider = _current_extension_provider() or "local"
    command = str(arguments.get("command") or "").strip().casefold()
    mapping = {
        ("spotify", "pause"): "spotify_pause",
        ("spotify", "resume"): "spotify_resume",
        ("spotify", "next"): "spotify_next",
        ("spotify", "previous"): "spotify_previous",
        ("local", "pause"): "local_playback_pause",
        ("local", "resume"): "local_playback_resume",
        ("local", "stop"): "local_playback_stop",
    }
    tool_name = mapping.get((provider, command))
    if tool_name is None:
        return _failure(
            "Call",
            f"Playback control '{command}' is not supported for {provider}.",
            "WORKFLOW_UNAVAILABLE",
        )
    return registry.invoke_system(tool_name, {})


workflows = WorkflowRegistry()
workflows.register(Workflow("playback.select", _select_workflow))
workflows.register(Workflow("playback.play", _play_workflow))
workflows.register(Workflow("playback.control", _control_workflow))


def Call(workflow: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    """Invoke one stable, allowlisted Sonex workflow."""
    return workflows.invoke(str(workflow or "").strip(), arguments)


def register_agent_surface(tool_registry: ToolRegistry = registry) -> None:
    """Register the non-Bash Agent Tools on the unified catalog."""
    tool_registry.register(
        name="Read",
        kind="agent",
        domain="knowledge",
        description=(
            "Retrieve relevant Sonex context, user preferences, or long-term memory. "
            "This tool cannot read arbitrary filesystem paths."
        ),
        parameters=Params(
            type="object",
            properties={
                "query": {"type": "string", "description": "What information is needed."},
                "source": {
                    "type": "string",
                    "enum": ["auto", "context", "user", "memory"],
                },
                "limit": {"type": "integer", "minimum": 1, "maximum": 20},
            },
            required=["query"],
        ),
        fn=Read,
        read_only=True,
        confirm_required=False,
    )
    tool_registry.register(
        name="Query",
        kind="agent",
        domain="music",
        description=(
            "Read one normalized music resource from one provider. "
            "Use separate calls when the user explicitly requests multiple providers."
        ),
        parameters=Params(
            type="object",
            properties={
                "provider": {"type": "string", "enum": list(QUERY_PROVIDERS)},
                "resource": {"type": "string", "enum": list(QUERY_RESOURCES)},
                "query": {"type": "string"},
                "ref": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                "cursor": {"type": "string"},
            },
            required=["provider", "resource"],
        ),
        fn=Query,
        read_only=True,
        confirm_required=False,
    )
    tool_registry.register(
        name="Recommend",
        kind="agent",
        domain="music",
        description=(
            "Recommend catalog-backed tracks once using recent listening context and "
            "connected providers, or return text-only context when none are available. "
            "This tool never starts playback or modifies queues."
        ),
        parameters=Params(
            type="object",
            properties={
                "query": {"type": "string"},
                "provider": {
                    "type": "string",
                    "enum": ["current", *RECOMMEND_PROVIDERS],
                },
                "limit": {"type": "integer", "minimum": 1, "maximum": 10},
            },
            required=[],
        ),
        fn=Recommend,
        read_only=True,
        confirm_required=False,
    )
    tool_registry.register(
        name="Modify",
        kind="agent",
        domain="music",
        description=(
            "Apply one idempotent transaction to Sonex local playlists or up next. "
            "Use one call with all requested operations. Destructive actions are previewed "
            "and confirmed by the runtime."
        ),
        parameters=Params(
            type="object",
            properties={
                "operations": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "properties": {
                            "target": {
                                "type": "string",
                                "enum": ["playlist", "up_next"],
                            },
                            "action": {
                                "type": "string",
                                "enum": [
                                    "create",
                                    "add",
                                    "remove",
                                    "move",
                                    "reorder",
                                    "rename",
                                    "clear",
                                    "delete",
                                    "replace",
                                ],
                            },
                            "name": {"type": "string"},
                            "new_name": {"type": "string"},
                            "refs": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "ref": {"type": "string"},
                            "index": {"type": "integer", "minimum": 0},
                        },
                        "required": ["target", "action"],
                    },
                },
                "idempotency_key": {
                    "type": "string",
                    "description": (
                        "A unique key for this user turn. Reuse it only when retrying "
                        "the exact same operation batch."
                    ),
                },
            },
            required=["operations", "idempotency_key"],
        ),
        fn=Modify,
        read_only=False,
        confirm_required=False,
    )
    tool_registry.register(
        name="Call",
        kind="agent",
        domain="workflow",
        description=(
            "Invoke a stable Sonex workflow: playback.select, playback.play, or "
            "playback.control. Never pass Python function or System Tool names."
        ),
        parameters=Params(
            type="object",
            properties={
                "workflow": {
                    "type": "string",
                    "enum": [
                        "playback.select",
                        "playback.play",
                        "playback.control",
                    ],
                },
                "arguments": {"type": "object"},
            },
            required=["workflow"],
        ),
        fn=Call,
        read_only=False,
        confirm_required=False,
    )


register_agent_surface()
