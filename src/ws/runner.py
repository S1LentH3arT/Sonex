"""Ws runner support for fastapi and websocket routing for the sonex runtime.

Implements the ws_runner module responsibilities used by Sonex runtime flows.
Key public entry points include search_youtube_songs, play_youtube_candidate, PlayRequestParse, AuthRuntimeState, WebSocketUIAdapter.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import queue
import random
import re
import sys
import threading
import time
import webbrowser
from collections import OrderedDict, deque
from contextlib import suppress
from contextvars import copy_context
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse
from urllib.parse import unquote

from fastapi import WebSocket, WebSocketDisconnect


logger = logging.getLogger(__name__)

from src.agent.core import agent_loop
from src.agent.chat_document import guard_agent_answer, normalize_agent_answer
from src.agent.events import RunnerEvent, UiStatus
from src.agent.interactions import (
    INTERRUPTED_INTERACTION_MESSAGE,
    clear_interrupted_interaction,
    has_interrupted_interaction,
    mark_interrupted_interaction,
)
from src.agent.tool_messages import (
    approved_commands_message,
    blocked_commands_message,
    format_tool_batch,
    rejected_commands_message,
)
from src.music.provider_mode import (
    ProviderMode,
    ProviderModeCoordinator,
    ProviderModeState,
    clear_provider_mode_intent,
    load_provider_mode_intent,
    save_provider_mode_intent,
)
from src.api.builtin_commands import CommandIntent, command_suggestions, format_help, parse_builtin_command
from src.api.music_intent import (
    MusicIntentDecision,
    MusicIntentRoute,
    classify_music_intent,
    classify_music_intent_fast,
)
from src.api.music_query import build_music_search_query_plan
from src.auth.browser_oauth import (
    BrowserOAuthPending,
    begin_browser_oauth,
    browser_oauth_requirements,
    browser_oauth_supported,
    complete_browser_oauth,
)
from src.auth.oauth import clear_oauth_access_cache, ensure_oauth_token_usable
from src.auth.providers import (
    get_provider_capability,
    normalize_provider,
    normalize_provider_model,
    provider_display_name,
)
from src.auth.secure_store import credential_storage_backend
from src.auth.spotify import (
    load_spotify_token,
    save_spotify_app_credentials,
    save_spotify_token_info,
    spotify_authorize_url,
    spotify_oauth_manager,
    spotify_redirect_uri,
)
from src.auth.store import (
    clear_default,
    get_provider_auth,
    load_auth_store,
    remove_provider,
    remove_provider_method,
    set_api_key,
    set_custom_profile,
    set_default,
    set_experimental_confirmation,
    set_managed_auth,
)
from src.llm.custom import (
    custom_profile_id,
    discover_custom_models,
    normalize_custom_base_url,
    test_custom_connection,
)
from src.llm.transport.codex_app_server import (
    CodexAppServer,
    codex_app_server_status,
    logout_chatgpt_subscription,
    start_chatgpt_device_login,
    wait_for_chatgpt_login,
)
from src.llm.models import model_choices_for_provider, model_display_name
from src.llm.transport import ChatRequest, sanitize_error_message
from src.llm.usage import reset_token_usage_observer, set_token_usage_observer
from src.log import sonex_home
from src.memory.memory import bind_memory_scope, memory_store
from src.memory.curator import (
    curate_completed_turn,
    explicit_memory_operation,
    memory_operation_message,
    safe_memory_content,
)
from src.music.connections import MusicConnectionManager
from src.music.netease_worker import NetEaseProviderWorker
from src.music.playback_coordinator import (
    MusicPlaybackCoordinator,
    ProviderReadiness,
    RecordingIdentity,
    SelectionStore,
    rank_authoritative_providers,
    recording_identity_matches,
)
from src.sandbox.tool import sandbox_manager
from src.thinking.config import ThinkingConfig
from src.tools import registry
from src.tools.agent_modify import complete_modify_confirmation
from src.tools.agent_surface import remember_local_track
from src.tools.track_refs import remember_track_reference, resolve_track_reference
from src.tools.up_next import (
    append_up_next_track,
    consume_up_next_head,
    fail_up_next_head,
    up_next_snapshot,
)
from src.tools.local_play import search_local_file
from src.tools.online_play import (
    ONLINE_AUDIO_SETUP_MESSAGE,
    OnlineAudioSetupRequired,
    online_audio_configured,
    play_online_audio_candidate,
    resolve_online_playback_metadata,
    search_spotify_track_candidates,
    search_online_audio_candidates,
)
from src.tools.playback_queue import playback_queue_snapshot, remember_playback_track
from src.tools.playlists import (
    LIKES_PLAYLIST,
    SPOTIFY_LIBRARY_EXTERNAL_ID,
    SPOTIFY_LIBRARY_PLAYLIST,
    list_playlist_tracks,
    list_playlists,
    playlist_choices,
    save_track_to_playlist,
    track_in_any_playlist,
    track_in_playlist,
    upsert_mirror_playlist,
)
from src.tools.spotify_library_sync import (
    SPOTIFY_LIBRARY_SYNC_FAILURE_BACKOFF_SECONDS,
    SpotifyLibrarySyncState,
    load_spotify_library_sync_state,
    retry_after_seconds,
    save_spotify_library_sync_state,
)
from src.tools.track_search import search_track_metadata_candidates
from src.ws.playback_feedback import (
    format_agent_playing_feedback,
    format_agent_selection_feedback,
    format_playing_feedback,
    format_player_feedback,
    format_song_candidate_feedback,
    metadata_provider_label as _metadata_provider_label,
)


# Backward-compatible runner patch points; these now resolve the unified online-audio layer.
def search_youtube_songs(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
    """Coordinates search youtube songs for the current Sonex flow.

    Typical use: Use this function when runtime code needs search youtube songs as part of a Sonex command, playback, auth, llm, or ui path.

    Example: search_youtube_songs() -> returns the value used by the surrounding Sonex flow.
    """
    return search_online_audio_candidates(*args, **kwargs)


def play_youtube_candidate(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Coordinates play youtube candidate for the current Sonex flow.

    Typical use: Use this function when runtime code needs play youtube candidate as part of a Sonex command, playback, auth, llm, or ui path.

    Example: play_youtube_candidate() -> returns the value used by the surrounding Sonex flow.
    """
    return play_online_audio_candidate(*args, **kwargs)


_LEGACY_SEARCH_ALIAS = search_youtube_songs
_LEGACY_PLAY_ALIAS = play_youtube_candidate


def _fixed_music_candidate_column(value: Any, width: int, truncate_at: int) -> str:
    text = str(value or "").strip() or "-"
    if len(text) > width:
        return f"{text[:truncate_at]}..."
    return text.ljust(width)


def _music_candidate_text(value: Any) -> str:
    return str(value or "").strip() or "-"


def music_candidate_display(artist: Any, album: Any, title: Any) -> dict[str, str]:
    return {
        "kind": "music_candidate",
        "artist": _music_candidate_text(artist),
        "album": _music_candidate_text(album),
        "title": _music_candidate_text(title),
    }


def format_music_candidate_label(artist: Any, album: Any, title: Any) -> str:
    artist_col = _fixed_music_candidate_column(artist, 24, 21)
    album_col = _fixed_music_candidate_column(album, 24, 21)
    title_text = str(title or "").strip() or "-"
    return f"{artist_col} {album_col} {title_text}"


def _search_online_audio_for_runner(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
    """Prepares search online audio for runner for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs search online audio for runner without duplicating the local rules.

    Example: _search_online_audio_for_runner() -> returns the value used by the surrounding Sonex flow.
    """
    if search_youtube_songs is not _LEGACY_SEARCH_ALIAS:
        return search_youtube_songs(*args, **kwargs)
    return search_online_audio_candidates(*args, **kwargs)


def _play_online_audio_for_runner(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Prepares play online audio for runner for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs play online audio for runner without duplicating the local rules.

    Example: _play_online_audio_for_runner() -> returns the value used by the surrounding Sonex flow.
    """
    if play_youtube_candidate is not _LEGACY_PLAY_ALIAS:
        return play_youtube_candidate(*args, **kwargs)
    return play_online_audio_candidate(*args, **kwargs)


from src.tools.player_permission import complete_player_confirm
from src.tools.playback_controller import (
    local_playback_status,
    start_local_playback,
)
from src.tools.spotify_play import (
    _product_is_known_non_premium,
    remember_recent_track,
    recent_tracks_snapshot as spotify_recent_tracks_snapshot,
    spotify_account,
    spotify_api_cooldown_remaining,
    spotify_current_playback,
    spotify_devices,
    spotify_playlist_tracks,
    spotify_playlists,
    spotify_queue,
    spotify_queue_add,
    spotify_recent_tracks,
    spotify_saved_tracks,
)
from src.tools.song_cache import (
    find_best_cached_song,
    resolve_cached_song,
    upsert_cached_song,
)
from src.ws.constants import (
    LLM_AUTH_PROVIDER_CHOICES,
    LLM_AUTH_PROVIDER_VALUES,
    LLM_MODEL_CHOICES,
    LOCAL_PLAYBACK_CHOICES,
    LOCAL_PLAYBACK_CONTROL_TOOLS,
    PLAYBACK_AGENT_TOOLS,
    RECOMMENDATION_TOOLS,
    SEARCH_RESULT_TOOLS,
    SPOTIFY_PLAYBACK_CONTROL_TOOLS,
    SPOTIFY_SETUP_TRIGGERS,
)
from src.ws.transcript import (
    _coerce_transcript_messages,
    _save_session_transcript,
    create_session_id,
)
from src.ws.types import AuthRuntimeState, PlayRequestParse
from src.ws.ui import WebSocketUIAdapter, _new_event_id, _timestamp_ms



def _player_debug(message: str) -> None:
    """Prepares player debug for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs player debug without duplicating the local rules.

    Example: _player_debug(message=...) -> returns the value used by the surrounding Sonex flow.
    """
    if os.environ.get("SONEX_PLAYER_DEBUG") == "1":
        print(f"[sonex-player-debug] {message}", file=sys.stderr)






















def _first_line(text: str, limit: int = 160) -> str:
    """Prepares first line for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs first line without duplicating the local rules.

    Example: _first_line(text=..., limit=...) -> returns the value used by the surrounding Sonex flow.
    """
    line = " ".join(str(text).strip().split())
    if len(line) <= limit:
        return line
    return f"{line[: limit - 1]}..."


def _preview(value: Any, max_lines: int = 3, max_chars: int = 420) -> str:
    """Prepares preview for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs preview without duplicating the local rules.

    Example: _preview(value=..., max_lines=..., max_chars=...) -> returns the value used by the surrounding Sonex flow.
    """
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False, indent=2, default=str)
    else:
        text = str(value)

    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    preview = "\n".join(lines[:max_lines])
    if len(lines) > max_lines:
        preview = f"{preview}\n... ({len(lines) - max_lines} lines hidden)"
    if len(preview) > max_chars:
        preview = f"{preview[: max_chars - 1]}..."
    return preview


def _format_args(args: Any) -> str:
    """Prepares format args for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs format args without duplicating the local rules.

    Example: _format_args(args=...) -> returns the value used by the surrounding Sonex flow.
    """
    if not args:
        return ""
    if isinstance(args, dict):
        parts = []
        for key, value in list(args.items())[:4]:
            normalized_key = str(key).casefold().replace("-", "_")
            sensitive = any(marker in normalized_key for marker in ("api_key", "secret", "token", "authorization", "password"))
            display_value = "[redacted]" if sensitive else sanitize_error_message(value, limit=80)
            parts.append(f"{key}={display_value}")
        suffix = ", ..." if len(args) > 4 else ""
        return ", ".join(parts) + suffix
    return _first_line(args)


def _format_tool_start(tool_name: str, args: dict[str, Any]) -> tuple[str, str | None]:
    """Prepares format tool start for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs format tool start without duplicating the local rules.

    Example: _format_tool_start(tool_name=..., args=...) -> returns the value used by the surrounding Sonex flow.
    """
    detail = _format_args(args)
    return f"Calling {tool_name}", detail or None


def _format_tool_result(tool_name: str, result: Any) -> tuple[str, str | None, str]:
    """Prepares format tool result for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs format tool result without duplicating the local rules.

    Example: _format_tool_result(tool_name=..., result=...) -> returns the value used by the surrounding Sonex flow.
    """
    status_value = "success"
    message = ""

    if isinstance(result, dict):
        status_value = str(result.get("status") or "success").lower()
        message = str(result.get("message") or "")
    elif result is not None:
        message = _first_line(result)

    title_status = "Finished" if status_value not in {"fail", "failure", "error"} else "Failed"
    activity_status = "error" if title_status == "Failed" else "success"
    title = f"{title_status} {tool_name}"
    detail = message or _preview(result)
    return title, detail or None, activity_status


def _is_failed_tool_result(result: Any) -> bool:
    """Prepares is failed tool result for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs is failed tool result without duplicating the local rules.

    Example: _is_failed_tool_result(result=...) -> returns the value used by the surrounding Sonex flow.
    """
    if not isinstance(result, dict):
        return False
    return str(result.get("status") or "").lower() in {"fail", "failure", "error"}


def _is_player_confirm_result(result: Any) -> bool:
    """Prepares is player confirm result for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs is player confirm result without duplicating the local rules.

    Example: _is_player_confirm_result(result=...) -> returns the value used by the surrounding Sonex flow.
    """
    return isinstance(result, dict) and result.get("status") == "requires_player_confirm"


def _is_play_selection_request_result(result: Any) -> bool:
    """Prepares is play selection request result for an internal Sonex flow."""
    return isinstance(result, dict) and result.get("status") == "requires_play_selection"


def _play_selection_query_from_result(result: Any) -> str | None:
    """Prepares play selection query from result for an internal Sonex flow."""
    if not isinstance(result, dict):
        return None
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    query = str(data.get("query") or result.get("query") or "").strip()
    return query or None


def _friendly_runtime_error_message(
    result: Any,
    *,
    fallback: str = "The operation could not be completed. Try again.",
) -> str:
    """Prepares friendly runtime error message for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs friendly runtime error message without duplicating the local rules.

    Example: _friendly_runtime_error_message(result=..., fallback=...) -> returns the value used by the surrounding Sonex flow.
    """
    if isinstance(result, dict):
        code = str(result.get("error_code") or "")
        message = str(result.get("message") or "").strip()
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        lowered = message.lower()
        if code == "SPOTIFY_PREMIUM_REQUIRED":
            return (
                "Spotify playback state requires a Premium account. "
                "I will stop polling Spotify playback for this session; search and local playback can still work."
            )
        if code == "SPOTIFY_RATE_LIMITED":
            retry_after = str(data.get("retry_after") or "").strip()
            if retry_after and retry_after not in message:
                message = f"{message} Spotify is rate limited; try again after {retry_after}."
        if code in {
            "SPOTIFY_PROXY_UNAVAILABLE",
            "SPOTIFY_CONNECT_TIMEOUT",
            "SPOTIFY_READ_TIMEOUT",
            "SPOTIFY_TLS_ERROR",
            "SPOTIFY_CONNECTION_ERROR",
        } and message:
            detail = sanitize_error_message(message)
            summary = sanitize_error_message(fallback)
            return summary if detail == summary else f"{summary} Technical detail: {detail}"
        if code == "SPOTIFY_API_ERROR" and (
            "httpsconnectionpool" in lowered
            or "ssleoferror" in lowered
            or "max retries exceeded" in lowered
        ):
            return "Spotify API request failed over the current network route. Existing local playlists remain available."
        if message:
            detail = sanitize_error_message(message)
            summary = sanitize_error_message(fallback)
            return summary if detail == summary else f"{summary} Technical detail: {detail}"
    return sanitize_error_message(fallback)


def _walk_dicts(value: Any) -> list[dict[str, Any]]:
    """Prepares walk dicts for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs walk dicts without duplicating the local rules.

    Example: _walk_dicts(value=...) -> returns the value used by the surrounding Sonex flow.
    """
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        found.append(value)
        for child in value.values():
            found.extend(_walk_dicts(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_walk_dicts(child))
    return found


def _extract_music_state(result: Any) -> tuple[dict[str, Any] | None, str | None]:
    """Prepares extract music state for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs extract music state without duplicating the local rules.

    Example: _extract_music_state(result=...) -> returns the value used by the surrounding Sonex flow.
    """
    for item in _walk_dicts(result):
        name = item.get("name") or item.get("title")
        artist = item.get("artist")
        album = item.get("album")
        duration_ms = item.get("duration_ms")
        progress_ms = item.get("progress_ms") or 0
        timestamp = item.get("timestamp") or item.get("started_at") or _timestamp_ms()
        is_playing = bool(item.get("is_playing")) if "is_playing" in item else False
        cover_url = item.get("cover_source") or item.get("album_cover_url") or item.get("image_url") or item.get("cover_url")
        if item.get("provider") == "youtube" and not item.get("cover_source_type") and _is_youtube_thumbnail(cover_url):
            cover_url = None

        if not (name or artist or album or duration_ms or cover_url):
            continue

        state = {
            "id": item.get("id"),
            "name": name or "-",
            "artist": artist or "-",
            "album": album or "-",
            "duration_ms": duration_ms or 0,
            "progress_ms": progress_ms,
            "timestamp": timestamp,
            "started_at": timestamp - progress_ms,
            "is_playing": is_playing,
            "playback_status": item.get("playback_status") or ("playing" if is_playing else "paused"),
            "paused_for_cache": bool(item.get("paused_for_cache")),
            "diagnostic_notice": item.get("diagnostic_notice"),
            "progress_source": item.get("progress_source"),
            "uri": item.get("uri"),
            "provider": item.get("provider"),
            "player": item.get("player"),
            "session_id": item.get("session_id"),
            "source": item.get("source"),
            "ended": item.get("ended"),
            "volume_percent": item.get("volume_percent"),
            "spotify_url": item.get("spotify_url"),
            "youtube_url": item.get("youtube_url") or (item.get("url") if item.get("provider") == "youtube" else None),
            "url": item.get("url"),
            "stream_url": item.get("stream_url"),
            "album_cover_url": cover_url,
        }
        return state, cover_url

    return None, None


def _spotify_starting_player_state(player_state: dict[str, Any]) -> dict[str, Any]:
    """Returns a non-authoritative Spotify player state while Web API playback catches up."""
    pending_state = dict(player_state)
    pending_state["progress_ms"] = 0
    pending_state["is_playing"] = False
    pending_state["playback_status"] = "starting"
    pending_state["progress_source"] = "spotify_pending"
    return pending_state


def _spotify_live_player_state(player_state: dict[str, Any]) -> dict[str, Any]:
    """Anchors an authoritative Spotify state to the local clock for UI projection."""
    live_state = dict(player_state)
    live_state["progress_source"] = "spotify_live"
    live_state["progress_anchor_ms"] = _timestamp_ms()
    return live_state


def _local_live_player_state(player_state: dict[str, Any]) -> dict[str, Any]:
    """Anchors an authoritative local-player state to the local clock."""
    live_state = dict(player_state)
    live_state["progress_source"] = "local_player"
    live_state["progress_anchor_ms"] = _timestamp_ms()
    live_state["progress_sync_lost"] = False
    if live_state.get("paused_for_cache"):
        live_state["playback_status"] = "buffering"
    return live_state


def _is_youtube_thumbnail(value: Any) -> bool:
    """Prepares is youtube thumbnail for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs is youtube thumbnail without duplicating the local rules.

    Example: _is_youtube_thumbnail(value=...) -> returns the value used by the surrounding Sonex flow.
    """
    return isinstance(value, str) and "ytimg.com/" in value


def _extract_tracks(result: Any) -> list[dict[str, Any]]:
    """Prepares extract tracks for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs extract tracks without duplicating the local rules.

    Example: _extract_tracks(result=...) -> returns the value used by the surrounding Sonex flow.
    """
    if not isinstance(result, dict):
        return []
    data = result.get("data") if isinstance(result.get("data"), dict) else result
    tracks = data.get("tracks") if isinstance(data, dict) else None
    if not isinstance(tracks, list):
        return []
    return [track for track in tracks if isinstance(track, dict)]


def _duration_text(ms: Any) -> str:
    """Prepares duration text for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs duration text without duplicating the local rules.

    Example: _duration_text(ms=...) -> returns the value used by the surrounding Sonex flow.
    """
    try:
        total_seconds = max(0, int(ms or 0) // 1000)
    except (TypeError, ValueError):
        total_seconds = 0
    minutes = total_seconds // 60
    seconds = total_seconds % 60
    return f"{minutes}:{seconds:02d}"


def _duration_ms_or_none(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _compact_count(value: Any) -> str | None:
    """Prepares compact count for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs compact count without duplicating the local rules.

    Example: _compact_count(value=...) -> returns the value used by the surrounding Sonex flow.
    """
    try:
        count = max(0, int(float(value or 0)))
    except (TypeError, ValueError):
        return None
    if count <= 0:
        return None
    if count >= 1_000_000_000:
        text = f"{count / 1_000_000_000:.1f}B"
    elif count >= 1_000_000:
        text = f"{count / 1_000_000:.1f}M"
    elif count >= 1_000:
        text = f"{count / 1_000:.1f}K"
    else:
        text = str(count)
    return text.replace(".0", "")


def _youtube_variant_label(value: Any) -> str:
    """Prepares youtube variant label for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs youtube variant label without duplicating the local rules.

    Example: _youtube_variant_label(value=...) -> returns the value used by the surrounding Sonex flow.
    """
    variant = str(value or "other")
    if variant == "official_original":
        return "Official"
    if variant == "live":
        return "Live"
    return "Others"


def _queue_payload() -> list[dict[str, Any]]:
    """Prepares queue payload for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs queue payload without duplicating the local rules.

    Example: _queue_payload() -> returns the value used by the surrounding Sonex flow.
    """
    try:
        tracks = up_next_snapshot()["items"]
    except Exception:
        tracks = []
    rows: list[dict[str, Any]] = []
    for index, track in enumerate(tracks, start=1):
        row: dict[str, Any] = {
            "index": f"{index:02d}",
            "title": f"{str(track.get('name') or '-').strip()}-{str(track.get('artist') or '-').strip()}",
            "name": str(track.get("name") or track.get("title") or "-"),
            "artist": str(track.get("artist") or ""),
            "duration": _duration_text(track.get("duration_ms")),
            "ref": str(track.get("ref") or ""),
            "provider": str(track.get("provider") or ""),
        }
        for key in (
            "album",
            "duration_ms",
            "uri",
            "url",
            "stream_url",
            "youtube_url",
            "spotify_url",
            "audio_path",
            "file_path",
            "path",
            "id",
            "playable",
        ):
            if track.get(key) is not None:
                row[key] = track.get(key)
        rows.append(row)
    return rows


def _track_panel_payload(panel: str, title: str, tracks: list[dict[str, Any]]) -> dict[str, Any]:
    """Prepares a track panel event payload."""
    return {
        "type": "track_panel",
        "panel": panel,
        "title": title,
        "tracks": tracks,
    }


def playlist_panel_tracks(
    playlist_name: str = LIKES_PLAYLIST,
    *,
    source_app: str = "Sonex",
    external_id: str | None = None,
) -> list[dict[str, str]]:
    """Formats persisted playlist tracks for the CLI track panel."""
    try:
        tracks = list_playlist_tracks(playlist_name, source_app=source_app, external_id=external_id)
    except Exception:
        tracks = []
    rows: list[dict[str, Any]] = []
    for index, track in enumerate(tracks, start=1):
        name = str(track.get("name") or track.get("title") or "-")
        row: dict[str, Any] = {
            "index": str(index),
            "title": name,
            "name": name,
            "artist": str(track.get("artist") or "-"),
            "duration": _duration_text(track.get("duration_ms")),
            "duration_ms": int(track.get("duration_ms") or 0),
        }
        for key in (
            "album",
            "provider",
            "source",
            "source_app",
            "cache_id",
            "uri",
            "url",
            "stream_url",
            "youtube_url",
            "spotify_url",
            "audio_path",
            "file_path",
            "path",
            "album_cover_url",
            "id",
        ):
            if track.get(key):
                row[key] = track.get(key)
        rows.append(row)
    return rows


def _search_results_payload(result: Any) -> list[dict[str, Any]]:
    """Prepares search results payload for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs search results payload without duplicating the local rules.

    Example: _search_results_payload(result=...) -> returns the value used by the surrounding Sonex flow.
    """
    tracks = _extract_tracks(result)
    payload: list[dict[str, Any]] = []
    for index, track in enumerate(tracks, start=1):
        payload.append(
            {
                "index": f"{index:02d}",
                "name": track.get("name") or "-",
                "title": track.get("name") or "-",
                "artist": track.get("artist") or "-",
                "album": track.get("album") or "-",
                "duration_ms": track.get("duration_ms") or 0,
                "duration": _duration_text(track.get("duration_ms")),
                "uri": track.get("uri"),
                "provider": track.get("provider") or "spotify",
                "spotify_url": track.get("spotify_url"),
                "url": track.get("url") or track.get("spotify_url"),
                "album_cover_url": track.get("album_cover_url"),
                "recommendation_reason": track.get("recommendation_reason"),
                "ref": track.get("ref"),
            }
        )
    return payload


def _player_sync_signature(state: dict[str, Any]) -> tuple[Any, ...]:
    """Prepares player sync signature for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs player sync signature without duplicating the local rules.

    Example: _player_sync_signature(state=...) -> returns the value used by the surrounding Sonex flow.
    """
    source = state.get("source") or state.get("provider")
    progress_bucket_ms = 1000 if source == "spotify" else 5000
    progress_bucket = int((state.get("progress_ms") or 0) / progress_bucket_ms)
    return (
        state.get("name"),
        state.get("artist"),
        state.get("album"),
        state.get("duration_ms"),
        bool(state.get("is_playing")),
        state.get("playback_status"),
        progress_bucket,
        state.get("volume_percent"),
        state.get("is_liked"),
        state.get("is_in_playlist"),
    )


def _decorate_player_state(state: dict[str, Any]) -> dict[str, Any]:
    """Adds derived, read-only playlist metadata to a player payload."""
    try:
        is_liked = track_in_playlist(state, playlist_name=LIKES_PLAYLIST)
    except Exception:
        is_liked = False
    try:
        is_in_playlist = is_liked or track_in_any_playlist(state)
    except Exception:
        is_in_playlist = False
    return {**state, "is_liked": is_liked, "is_in_playlist": is_in_playlist}


def _remember_actual_playback(player_state: dict[str, Any]) -> None:
    """Updates persisted queue state from accepted playback state."""
    remember_playback_track(player_state)
    remember_recent_track(player_state)


def _record_playback_behavior(
    ui: WebSocketUIAdapter,
    player_state: dict[str, Any],
    *,
    force: bool = False,
) -> None:
    """Records one real playback start, without counting status/control refreshes."""
    if not player_state.get("is_playing"):
        return
    name = str(player_state.get("name") or player_state.get("title") or "").strip()
    artist = str(player_state.get("artist") or "").strip()
    provider = str(player_state.get("provider") or player_state.get("source") or "").strip()
    if not name or name == "-":
        return
    behavior_key = (provider.casefold(), name.casefold(), artist.casefold())
    if not force and getattr(ui, "_last_playback_behavior_key", None) == behavior_key:
        return
    setattr(ui, "_last_playback_behavior_key", behavior_key)
    try:
        memory_store.record_behavior_signal("played", player_state)
    except Exception:
        logger.debug("Unable to persist playback behavior signal.", exc_info=True)


def _is_spotify_setup_request(text: str) -> bool:
    """Prepares is spotify setup request for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs is spotify setup request without duplicating the local rules.

    Example: _is_spotify_setup_request(text=...) -> returns the value used by the surrounding Sonex flow.
    """
    normalized = " ".join(text.strip().lower().split())
    return normalized in SPOTIFY_SETUP_TRIGGERS


def _rule_parse_play_request(text: str) -> PlayRequestParse:
    """Prepares rule parse play request for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs rule parse play request without duplicating the local rules.

    Example: _rule_parse_play_request(text=...) -> returns the value used by the surrounding Sonex flow.
    """
    stripped = text.strip()
    lowered = stripped.lower()

    en_patterns = (r"\bplay\b", r"\blisten to\b", r"\bdance\b",)
    zh_markers = ("放一首", "来一首", "放一下", "放首", "来首", "想听", "听点", "听首", "听一下", "听一首",
                   "来点", "放点", "听", "放")
    # Use regex to ensure direct-play intension for English prompt.
    for pattern in en_patterns:
        match = re.search(pattern, lowered)
        if not match:
            continue
        query = stripped[match.end():].strip(" \t\r\n,.!?:;")
        if query:
            return PlayRequestParse(True, query, "high", f"play {query}")

    # Use substring matching for Chinese prompt.
    for marker in zh_markers:
        idx = stripped.find(marker)
        if idx == -1:
            continue
        query = stripped[idx + len(marker):].strip(" \t\r\n,，.。!！?？:：;；")
        if query:
            return PlayRequestParse(True, query, "high", f"play {query}")

    return PlayRequestParse(False, None, "low", text)


def _optimize_play_prompt(text: str) -> PlayRequestParse:
    """Prepares optimize play prompt for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs optimize play prompt without duplicating the local rules.

    Example: _optimize_play_prompt(text=...) -> returns the value used by the surrounding Sonex flow.
    """
    prompt = (
        "Classify the user's music intent. Return JSON only with keys route, query, "
        "recommendation_index, confidence. route must be explicit_play, confirm_track_play, "
        "recommend, or general. "
        "Only classify intent; do not rewrite or optimize the user's input. "
        "Use explicit_play only if the user is clearly asking to play music. "
        "Use confirm_track_play if the user seems to want a specific track but is not explicit. "
        "Use recommend if the user is asking for song recommendations or broad music suggestions. "
        "Use general for lyrics, meaning, history, facts, or unclear requests. "
        "query should contain the original song/artist/topic if relevant, not a rewritten prompt. "
        "confidence is between 0 and 1.\n"
        f"user_input: {text.strip()}"
    )
    try:
        response = ThinkingConfig.get_client().generate(
            ChatRequest(
                model=ThinkingConfig.get_model(),
                messages=[
                    {
                        "role": "system",
                        "content": "You extract music playback intent. Only high confidence explicit playback requests pass.",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0,
                max_tokens=160,
            )
        )
        raw = str(getattr(response, "output_text", "") or "")
        data = json.loads(raw)
    except Exception:
        return PlayRequestParse(False, None, "low", text)
    return PlayRequestParse(
        bool(data.get("is_play_request")),
        str(data.get("query")).strip() if data.get("query") else None,
        "high" if data.get("confidence") == "high" else "low",
        str(data.get("rewritten_input") or text),
    )


def _is_local_search_hit(result: str) -> bool:
    """Prepares is local search hit for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs is local search hit without duplicating the local rules.

    Example: _is_local_search_hit(result=...) -> returns the value used by the surrounding Sonex flow.
    """
    return bool(result and not result.startswith("No local files found") and not result.startswith("Path outside user workspace"))


def _filename(path_text: str) -> str:
    """Prepares filename for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs filename without duplicating the local rules.

    Example: _filename(path_text=...) -> returns the value used by the surrounding Sonex flow.
    """
    return Path(path_text).name or path_text


def _default_provider_name() -> str:
    """Prepares default provider name for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs default provider name without duplicating the local rules.

    Example: _default_provider_name() -> returns the value used by the surrounding Sonex flow.
    """
    config_path = os.getenv("SONEX_CONFIG_PATH")
    if config_path:
        resolved_config_path = os.path.expanduser(config_path)
    else:
        resolved_config_path = str(sonex_home() / "thinking.json")

    file_provider = None
    try:
        with open(resolved_config_path, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        if isinstance(loaded, dict):
            file_provider = loaded.get("default_provider")
    except (OSError, json.JSONDecodeError):
        file_provider = None

    try:
        auth_provider = load_auth_store().default_provider
    except Exception:
        auth_provider = None

    return normalize_provider(
        os.getenv("SONEX_DEFAULT_PROVIDER")
        or os.getenv("SONEX_PROVIDER")
        or auth_provider
        or file_provider
        or "openai"
    )


def _default_model_name() -> str:
    """Prepares default model name for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs default model name without duplicating the local rules.

    Example: _default_model_name() -> returns the value used by the surrounding Sonex flow.
    """
    config_path = os.getenv("SONEX_CONFIG_PATH")
    if config_path:
        resolved_config_path = os.path.expanduser(config_path)
    else:
        resolved_config_path = str(sonex_home() / "thinking.json")

    file_model = None
    try:
        with open(resolved_config_path, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        if isinstance(loaded, dict):
            file_model = loaded.get("default_model")
    except (OSError, json.JSONDecodeError):
        file_model = None

    try:
        store = load_auth_store()
        auth_model = store.default_model
        provider_auth = get_provider_auth(store, _default_provider_name())
        provider_model = provider_auth.model if provider_auth else None
    except Exception:
        auth_model = None
        provider_model = None

    provider = _default_provider_name()
    model = (
        os.getenv("SONEX_DEFAULT_MODEL")
        or os.getenv("SONEX_MODEL")
        or provider_model
        or auth_model
        or file_model
        or get_provider_capability(provider).default_model
        or "gpt-5.5"
    )
    return str(normalize_provider_model(provider, str(model)) or model)


def _env_api_key_for_provider(provider: str) -> str | None:
    """Prepares env api key for provider for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs env api key for provider without duplicating the local rules.

    Example: _env_api_key_for_provider(provider=...) -> returns the value used by the surrounding Sonex flow.
    """
    name = normalize_provider(provider)
    value = os.getenv(f"SONEX_{name.upper()}_API_KEY")
    if value:
        return value
    if name == "openai":
        return os.getenv("SONEX_API_KEY") or None
    if name == "kimi_global":
        return os.getenv("SONEX_KIMI_API_KEY") or None
    if name == "minimax_global":
        return os.getenv("SONEX_MINIMAX_API_KEY") or None
    return None


def _provider_credentials_available(provider: str) -> bool:
    """Return local credential availability without making a network request."""
    name = normalize_provider(provider)
    store = load_auth_store()
    if name == "custom":
        return any(
            key.startswith("custom__") and not profile.needs_review
            for key, profile in store.providers.items()
        )
    auth = get_provider_auth(store, name)
    return bool(
        _env_api_key_for_provider(name)
        or auth and (auth.api_key or auth.oauth or auth.managed_auth)
    )


def _provider_has_saved_credentials(provider: str) -> bool:
    name = normalize_provider(provider)
    auth = get_provider_auth(load_auth_store(), name)
    return bool(auth and (auth.api_key or auth.oauth or auth.managed_auth))


def _set_runtime_default_provider(provider: str, model: str | None = None) -> None:
    """Prepares set runtime default provider for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs set runtime default provider without duplicating the local rules.

    Example: _set_runtime_default_provider(provider=..., model=...) -> returns the value used by the surrounding Sonex flow.
    """
    name = normalize_provider(provider)
    resolved_model = model or get_provider_capability(name).default_model
    set_default(name, resolved_model)
    os.environ["SONEX_DEFAULT_PROVIDER"] = name
    if resolved_model:
        os.environ["SONEX_DEFAULT_MODEL"] = resolved_model


def _resolved_provider_model() -> tuple[str, str]:
    """Prepares resolved provider model for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs resolved provider model without duplicating the local rules.

    Example: _resolved_provider_model() -> returns the value used by the surrounding Sonex flow.
    """
    try:
        ThinkingConfig.reload()
        provider = normalize_provider(ThinkingConfig.get_provider())
        config = ThinkingConfig.get_provider_config(provider)
        model = config.model or ThinkingConfig.get_model() or _default_model_name()
    except Exception:
        return _default_provider_name(), _default_model_name()
    return provider, str(model)


def _runtime_auth_state(
    ready: bool,
    provider: str,
    model: str,
    auth_type: str,
    credential_source: str,
    reason: str | None = None,
) -> AuthRuntimeState:
    return AuthRuntimeState(
        ready,
        provider,
        model,
        auth_type,
        credential_source,
        reason,
        model_display_name(provider, model),
    )


def _llm_auth_state() -> AuthRuntimeState:
    """Prepares llm auth state for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs llm auth state without duplicating the local rules.

    Example: _llm_auth_state() -> returns the value used by the surrounding Sonex flow.
    """
    provider, model = _resolved_provider_model()

    capability = get_provider_capability(provider)
    if not capability.requires_auth:
        return _runtime_auth_state(True, provider, model, "local", "local")

    if _env_api_key_for_provider(provider):
        return _runtime_auth_state(True, provider, model, "api_key", "env")

    try:
        store = load_auth_store()
        auth = get_provider_auth(store, provider)
    except Exception as exc:
        return _runtime_auth_state(
            False,
            provider,
            model,
            "none",
            "missing",
            sanitize_error_message(exc),
        )

    if auth and auth.auth_method in {"auto", "api_key"} and auth.api_key:
        return _runtime_auth_state(True, provider, auth.model or model, "api_key", "auth.json")
    if (
        auth
        and auth.auth_method == "oauth"
        and auth.managed_auth == "codex_app_server"
        and provider == "openai"
    ):
        available, reason = codex_app_server_status()
        return _runtime_auth_state(
            available,
            provider,
            auth.model or model,
            "oauth",
            "auth.json",
            reason,
        )
    if auth and auth.auth_method in {"auto", "oauth"} and auth.oauth:
        try:
            ensure_oauth_token_usable(provider, auth.oauth, project_id=auth.project_id)
        except Exception as exc:
            return _runtime_auth_state(False, provider, auth.model or model, "oauth", "auth.json", sanitize_error_message(exc))
        return _runtime_auth_state(True, provider, auth.model or model, "oauth", "auth.json")
    if (
        auth
        and provider.startswith("custom__")
        and auth.base_url
        and auth.model
        and not auth.needs_review
    ):
        return _runtime_auth_state(
            True,
            provider,
            auth.model,
            "api_key" if auth.api_key else "none",
            "auth.json",
        )

    return _runtime_auth_state(
        False,
        provider,
        model,
        "none",
        "missing",
        f"Provider '{provider}' needs credentials before Sonex can plan this turn.",
    )


def _display_working_directory(cwd: Path | None = None) -> str:
    """Return a home-relative display path for runtime status output."""
    path = (cwd or Path.cwd()).resolve()
    try:
        relative = path.relative_to(Path.home().resolve())
    except (OSError, ValueError):
        return str(path)
    if relative == Path("."):
        return "~"
    return str(Path("~") / relative)


def _format_runtime_info(state: AuthRuntimeState, cwd: Path | None = None) -> str:
    """Format current local runtime state without invoking the agent."""
    return "\n".join(
        (
            "Sonex runtime:",
            f"Model: {state.model_label or state.model}",
            f"Provider: {state.provider}",
            f"Auth: {state.auth_type}",
            f"CWD: {_display_working_directory(cwd)}",
        )
    )


def _llm_auth_ready() -> tuple[bool, str, str | None]:
    """Prepares llm auth ready for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs llm auth ready without duplicating the local rules.

    Example: _llm_auth_ready() -> returns the value used by the surrounding Sonex flow.
    """
    state = _llm_auth_state()
    return state.ready, state.provider, state.reason


def _auth_methods_for_provider(provider: str) -> list[dict[str, str]]:
    """Prepares auth methods for provider for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs auth methods for provider without duplicating the local rules.

    Example: _auth_methods_for_provider(provider=...) -> returns the value used by the surrounding Sonex flow.
    """
    capability = get_provider_capability(provider)
    name = normalize_provider(provider)
    auth = get_provider_auth(load_auth_store(), name)
    methods: list[dict[str, str]] = []
    if name == "custom":
        return [
            {"value": "none", "label": "No authentication"},
            {"value": "api_key", "label": "Bearer API key"},
        ]
    if name == "openai":
        available, reason = codex_app_server_status()
        label = "ChatGPT Subscription (Experimental)"
        if auth and auth.managed_auth == "codex_app_server":
            label += " — Connected"
        if available:
            methods.append({"value": "oauth", "label": label})
        else:
            methods.append({
                "value": "__unavailable_oauth__",
                "label": f"{label} — Unavailable",
                "description": reason or "Codex App Server is unavailable.",
            })
    elif capability.supports_oauth and browser_oauth_supported(provider):
        base_label = "Google OAuth (Preview)" if name == "gemini" else "OAuth"
        label = f"{base_label} — Connected" if auth and auth.oauth else base_label
        methods.append({"value": "oauth", "label": label})
    if capability.supports_api_key:
        api_key_connected = bool(_env_api_key_for_provider(name) or auth and auth.api_key)
        label = "API key — Connected" if api_key_connected else "API key"
        methods.append({"value": "api_key", "label": label})
    if auth and auth.managed_auth:
        methods.append({"value": "disconnect_oauth", "label": "Disconnect ChatGPT Subscription"})
    elif auth and auth.oauth:
        methods.append({"value": "disconnect_oauth", "label": "Disconnect OAuth"})
    if auth and auth.api_key:
        methods.append({"value": "disconnect_api_key", "label": "Disconnect API key"})
    return methods


def _provider_choices_with_status() -> list[dict[str, Any]]:
    """Build the /login provider picker with connection status."""
    active_provider = _default_provider_name()
    choices: list[dict[str, Any]] = []
    for choice in LLM_AUTH_PROVIDER_CHOICES:
        value = choice["value"]
        available = _provider_credentials_available(value)
        active = available and active_provider == value
        if value == "custom":
            active = available and active_provider.startswith("custom__")
        status = "active" if active else "saved" if available else "missing"
        suffix = {"active": "Active", "saved": "Saved", "missing": "Not connected"}[status]
        label = f"{choice['label']} — {suffix}"
        choices.append({
            **choice,
            "label": label,
            "connected": available,
            "connection_status": status,
        })
    return choices


_API_KEY_SIGNUP_URLS = {
    "openai": "https://platform.openai.com/api-keys",
    "gemini": "https://aistudio.google.com/app/apikey",
    "anthropic": "https://platform.claude.com/settings/keys",
    "deepseek": "https://platform.deepseek.com/",
    "openrouter": "https://openrouter.ai/keys",
    "zai": "https://z.ai/",
    "kimi_global": "https://platform.kimi.ai/",
    "kimi_cn": "https://platform.moonshot.cn/",
    "minimax_global": "https://platform.minimax.io/",
    "minimax_cn": "https://platform.minimaxi.com/",
    "xai": "https://console.x.ai/",
}


def _api_key_help_text(provider: str) -> str | None:
    signup_url = _API_KEY_SIGNUP_URLS.get(normalize_provider(provider))
    if not signup_url:
        return None
    return f"Haven't got an API Key? Get one at {signup_url}."


def _model_choices_for_provider(provider: str) -> list[dict[str, str]]:
    """Prepares model choices for provider for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs model choices for provider without duplicating the local rules.

    Example: _model_choices_for_provider(provider=...) -> returns the value used by the surrounding Sonex flow.
    """
    name = normalize_provider(provider)
    if name.startswith("custom__"):
        auth = get_provider_auth(load_auth_store(), name)
        if auth:
            label = auth.display_name or "Custom"
            return [
                {"value": f"{name}::{model}", "label": model, "provider": label}
                for model in auth.model_ids
            ]
    if name in {
        "openai", "anthropic", "gemini", "deepseek", "openrouter", "zai",
        "kimi_global", "kimi_cn", "minimax_global", "minimax_cn", "xai",
    }:
        ThinkingConfig.reload()
        config = ThinkingConfig.get_provider_config(name)
        return model_choices_for_provider(config)

    choices = [
        choice
        for choice in LLM_MODEL_CHOICES
        if normalize_provider(choice["value"].partition("::")[0]) == name
    ]
    if choices:
        return choices

    model = get_provider_capability(name).default_model
    if not model:
        return []
    return [{"value": f"{name}::{model}", "label": model, "provider": name}]


def _parse_model_choice(value: str, choices: list[dict[str, str]] | None = None) -> tuple[str, str] | None:
    """Prepares parse model choice for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs parse model choice without duplicating the local rules.

    Example: _parse_model_choice(value=..., choices=...) -> returns the value used by the surrounding Sonex flow.
    """
    normalized = value.strip()
    if not normalized:
        return None

    model_choices = choices or LLM_MODEL_CHOICES
    choice_values = {choice["value"].lower(): choice for choice in model_choices}
    choice = choice_values.get(normalized.lower())
    if choice:
        provider, _, model = choice["value"].partition("::")
        return normalize_provider(provider), model

    for candidate in model_choices:
        provider, _, model = candidate["value"].partition("::")
        aliases = {
            str(candidate["label"]).lower(),
            model.lower(),
            f"{provider} {model}".lower(),
            f"{candidate['provider']} {model}".lower(),
        }
        if normalized.lower() in aliases:
            return normalize_provider(provider), model
    return None


def _spotify_loopback_login_for_tui(authorize_url: str, expected_state: str) -> dict[str, Any]:
    """Prepares spotify loopback login for tui for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs spotify loopback login for tui without duplicating the local rules.

    Example: _spotify_loopback_login_for_tui(authorize_url=..., expected_state=...) -> returns the value used by the surrounding Sonex flow.
    """
    redirect = urlparse(spotify_redirect_uri())
    host = redirect.hostname or "127.0.0.1"
    port = redirect.port or 80
    callback_path = redirect.path or "/callback"
    received: dict[str, str] = {}

    class SpotifyCallbackHandler(BaseHTTPRequestHandler):
        """Represents spotify callback handler.

        Encapsulates spotify callback handler data and behavior used by Sonex runtime flows. Extends base h t t p request handler semantics.
        """
        def do_GET(self) -> None:
            """Coordinates do GET for the current Sonex flow.

            Typical use: Use this function when runtime code needs do GET as part of a Sonex command, playback, auth, llm, or ui path.

            Example: do_GET() -> returns the value used by the surrounding Sonex flow.
            """
            parsed = urlparse(self.path)
            params = parse_qs(parsed.query)
            if parsed.path != callback_path:
                self.send_response(404)
                self.end_headers()
                return

            if params.get("error"):
                received["error"] = params["error"][0]
            if params.get("code"):
                received["code"] = params["code"][0]
            if params.get("state"):
                received["state"] = params["state"][0]

            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"Spotify connected. You can return to Sonex.")

        def log_message(self, format: str, *args: object) -> None:
            """Coordinates log message for the current Sonex flow.

            Typical use: Use this function when runtime code needs log message as part of a Sonex command, playback, auth, llm, or ui path.

            Example: log_message(format=...) -> returns the value used by the surrounding Sonex flow.
            """
            return

    webbrowser.open(authorize_url)

    with HTTPServer((host, port), SpotifyCallbackHandler) as server:
        server.timeout = 180
        server.handle_request()

    if received.get("error"):
        raise RuntimeError(f"Spotify authorization failed: {received['error']}")
    if not received.get("code"):
        raise RuntimeError("Spotify authorization timed out or returned no code.")
    if received.get("state") != expected_state:
        raise RuntimeError("Spotify authorization state mismatch.")

    token_info = spotify_oauth_manager(state=expected_state).get_access_token(
        received["code"],
        as_dict=True,
        check_cache=False,
    )
    save_spotify_token_info(token_info)
    return spotify_account()


class SpotifySetupSession:
    """Represents spotify setup session.

    Encapsulates spotify setup session data and behavior used by Sonex runtime flows.
    """
    def __init__(
        self,
        ui: WebSocketUIAdapter,
        *,
        on_connected: Callable[[dict[str, Any]], Any] | None = None,
        on_completed: Callable[[dict[str, Any]], Any] | None = None,
        emit_feedback: bool = True,
    ) -> None:
        """Prepares init for an internal Sonex flow.

        Typical use: Use this helper when nearby code needs init without duplicating the local rules.

        Example: __init__(ui=...) -> returns the value used by the surrounding Sonex flow.
        """
        self.ui = ui
        self.client_id: str | None = None
        self.step = "client_id"
        self.oauth_task: asyncio.Task[None] | None = None
        self.browser_oauth_pending: BrowserOAuthPending | None = None
        self.codex_server: CodexAppServer | None = None
        self.on_connected = on_connected
        self.on_completed = on_completed
        self.emit_feedback = emit_feedback

    async def start(self) -> None:
        """Coordinates start for the current Sonex flow.

        Typical use: Use this function when runtime code needs start as part of a Sonex command, playback, auth, llm, or ui path.

        Example: await start() -> returns the value used by the surrounding Sonex flow.
        """
        redirect_uri = spotify_redirect_uri()
        message = (
            "Open https://developer.spotify.com/dashboard, create an app, and add this Redirect URI: "
            f"{redirect_uri}. Then paste the Client ID below."
        )
        if self.emit_feedback:
            await self.ui.append_activity(
                kind="status",
                title="Spotify setup",
                detail=message,
                status="pending",
            )
        await self.ui.send_spotify_setup(
            step="client_id",
            title="Spotify setup",
            message=message,
            prompt="Spotify Client ID",
        )

    async def start_reauthorization(self, missing_scopes: list[str]) -> None:
        """Starts OAuth again when an existing Spotify token lacks required scopes."""
        scopes = ", ".join(missing_scopes)
        message = (
            "Spotify authorization must be renewed for these permissions: "
            f"{scopes}. Continue in this chat, then approve access on the Spotify authorization page."
        )
        if self.emit_feedback:
            await self.ui.append_system_message(message)
        try:
            authorize_url, expected_state = spotify_authorize_url()
        except Exception:
            await self.start()
            return

        self.step = "oauth"
        if self.emit_feedback:
            await self.ui.append_activity(
                kind="status",
                title="Spotify reauthorization",
                detail="Opening Spotify authorization and waiting for the loopback callback.",
                status="pending",
            )
        await self.ui.send_spotify_setup(
            step="oauth",
            title="Authorize Spotify",
            message=(
                "Spotify scopes need updating. Approve access in the browser, then return here. "
                f"Authorization URL: {authorize_url}"
            ),
            active=False,
        )
        self.oauth_task = asyncio.create_task(self._finish_oauth(authorize_url, expected_state))

    async def handle_input(self, value: str) -> None:
        """Coordinates handle input for the current Sonex flow.

        Typical use: Use this function when runtime code needs handle input as part of a Sonex command, playback, auth, llm, or ui path.

        Example: await handle_input(value=...) -> returns the value used by the surrounding Sonex flow.
        """
        value = value.strip()
        if value.casefold() in {"__cancel__", "cancel"}:
            if self.oauth_task is not None:
                self.oauth_task.cancel()
            await self.ui.send_spotify_setup(
                step="cancelled",
                title="Spotify connection",
                message="Spotify connection was cancelled.",
                active=False,
            )
            setattr(self.ui, "_spotify_setup", None)
            await self._notify_completed(
                {
                    "status": "cancelled",
                    "provider": "spotify",
                    "reason": "user_cancelled",
                }
            )
            return
        if not value:
            await self.ui.send_spotify_setup(
                step=self.step,
                title="Spotify setup",
                message="Input cannot be empty.",
                prompt="Spotify Client ID" if self.step == "client_id" else "Spotify Client Secret",
                mask=self.step == "client_secret",
            )
            return

        if self.step == "client_id":
            self.client_id = value
            self.step = "client_secret"
            await self.ui.send_spotify_setup(
                step="client_secret",
                title="Spotify setup",
                message="Client ID received. Paste the Client Secret now.",
                prompt="Spotify Client Secret",
                mask=True,
            )
            return

        if self.step != "client_secret" or not self.client_id:
            return

        client_secret = value
        self.step = "oauth"
        try:
            save_spotify_app_credentials(self.client_id, client_secret)
            authorize_url, expected_state = spotify_authorize_url()
        except Exception as exc:
            self.step = "client_id"
            await self.ui.send_spotify_setup(
                step="client_id",
                title="Spotify setup failed",
                message=sanitize_error_message(exc),
                prompt="Spotify Client ID",
            )
            return

        if self.emit_feedback:
            await self.ui.append_activity(
                kind="status",
                title="Spotify credentials saved",
                detail="Opening Spotify authorization and waiting for the loopback callback.",
                status="pending",
            )
        await self.ui.send_spotify_setup(
            step="oauth",
            title="Authorize Spotify",
            message=(
                "I saved the app credentials and opened Spotify authorization. "
                "Approve access in the browser, then return here. "
                f"Authorization URL: {authorize_url}"
            ),
            active=False,
        )
        self.oauth_task = asyncio.create_task(self._finish_oauth(authorize_url, expected_state))

    async def _finish_oauth(self, authorize_url: str, expected_state: str) -> None:
        """Prepares finish oauth for an internal Sonex flow.

        Typical use: Use this helper when nearby code needs finish oauth without duplicating the local rules.

        Example: await _finish_oauth(authorize_url=..., expected_state=...) -> returns the value used by the surrounding Sonex flow.
        """
        try:
            account = await asyncio.to_thread(_spotify_loopback_login_for_tui, authorize_url, expected_state)
        except Exception as exc:
            await self._notify_completed(
                {
                    "status": "failed",
                    "provider": "spotify",
                    "reason": "authorization_failed",
                    "message": sanitize_error_message(exc),
                }
            )
            if self.emit_feedback:
                await self.ui.append_activity(
                    kind="error",
                    title="Spotify authorization failed",
                    detail=sanitize_error_message(exc),
                    status="error",
                )
            await self.ui.send_spotify_setup(
                step="done",
                title="Spotify setup failed",
                message=sanitize_error_message(exc),
                active=False,
            )
            return

        if _is_failed_tool_result(account):
            failure = _friendly_runtime_error_message(
                account,
                fallback="Spotify account verification could not complete.",
            )
            message = (
                "Spotify authorization was saved, but account verification could not complete. "
                f"{failure} Run /spotify again when Spotify is reachable."
            )
            if self.emit_feedback:
                await self.ui.append_activity(
                    kind="error",
                    title="Spotify verification pending",
                    detail=message,
                    status="error",
                )
            await self.ui.send_spotify_setup(
                step="done",
                title="Spotify authorized; verification pending",
                message=message,
                active=False,
            )
            await self._notify_completed(
                {
                    "status": "failed",
                    "provider": "spotify",
                    "reason": "health_check_failed",
                    "message": message,
                }
            )
            return

        data = account.get("data") if isinstance(account, dict) else {}
        product = data.get("product") if isinstance(data, dict) else "unknown"
        if self.on_connected is not None and isinstance(data, dict):
            callback_result = self.on_connected(data)
            if asyncio.iscoroutine(callback_result):
                await callback_result
        if self.emit_feedback:
            await self.ui.append_activity(
                kind="status",
                title="Spotify connected",
                detail=f"Account product: {product}",
                status="success",
            )
        await self.ui.send_spotify_setup(
            step="done",
            title="Spotify connected",
            message=f"Spotify is connected. Account product: {product}.",
            active=False,
        )
        await self._notify_completed(
            {
                "status": "connected",
                "provider": "spotify",
                "account_label": (
                    data.get("display_name")
                    or data.get("email")
                    or data.get("id")
                    or "Spotify account"
                ),
            }
        )

    async def _notify_completed(self, result: dict[str, Any]) -> None:
        if self.on_completed is None:
            return
        callback = self.on_completed
        self.on_completed = None
        callback_result = callback(result)
        if asyncio.iscoroutine(callback_result):
            await callback_result


class OpenAudioSetupSession:
    """Represents open audio setup session.

    Encapsulates open audio setup session data and behavior used by Sonex runtime flows.
    """
    def __init__(
        self,
        ui: WebSocketUIAdapter,
        provider: str,
        *,
        on_completed: Callable[[dict[str, Any]], Any] | None = None,
        emit_feedback: bool = True,
    ) -> None:
        """Prepares init for an internal Sonex flow.

        Typical use: Use this helper when nearby code needs init without duplicating the local rules.

        Example: __init__(ui=..., provider=...) -> returns the value used by the surrounding Sonex flow.
        """
        self.ui = ui
        self.provider = provider
        self.display_name = "Jamendo" if provider == "jamendo" else "Audius"
        self.on_completed = on_completed
        self.emit_feedback = emit_feedback

    def _prompt_label(self) -> str:
        """Prepares prompt label for an internal Sonex flow.

        Typical use: Use this helper when nearby code needs prompt label without duplicating the local rules.

        Example: _prompt_label() -> returns the value used by the surrounding Sonex flow.
        """
        return "Jamendo Client ID" if self.provider == "jamendo" else "Audius API key"

    def _setup_message(self) -> str:
        """Prepares setup message for an internal Sonex flow.

        Typical use: Use this helper when nearby code needs setup message without duplicating the local rules.

        Example: _setup_message() -> returns the value used by the surrounding Sonex flow.
        """
        if self.provider == "jamendo":
            return (
                "Open https://developer.jamendo.com, create or open your app, then paste the Client ID below. "
                "Jamendo does not need a Client Secret for Sonex online playback."
            )
        return (
            "Open https://developer.audius.co, create an Audius app if needed, then paste the API key below. "
            "Sonex uses this key for Audius online playback search and streaming metadata."
        )

    async def start(self) -> None:
        """Coordinates start for the current Sonex flow.

        Typical use: Use this function when runtime code needs start as part of a Sonex command, playback, auth, llm, or ui path.

        Example: await start() -> returns the value used by the surrounding Sonex flow.
        """
        label = self._prompt_label()
        message = self._setup_message()
        if self.emit_feedback:
            await self.ui.append_activity(
                kind="status",
                title=f"{self.display_name} setup",
                detail=message,
                status="pending",
            )
        await self.ui.send_auth_setup(
            provider=self.provider,
            step="api_key",
            title=f"{self.display_name} setup",
            message=message,
            prompt=label,
            mask=False,
        )

    async def handle_input(self, value: str) -> None:
        """Coordinates handle input for the current Sonex flow.

        Typical use: Use this function when runtime code needs handle input as part of a Sonex command, playback, auth, llm, or ui path.

        Example: await handle_input(value=...) -> returns the value used by the surrounding Sonex flow.
        """
        value = value.strip()
        if value.casefold() in {"__cancel__", "cancel"}:
            if self.oauth_task and not self.oauth_task.done():
                self.oauth_task.cancel()
            if self.codex_server:
                await asyncio.to_thread(self.codex_server.close)
                self.codex_server = None
            await self.ui.send_auth_setup(
                provider=self.provider,
                step="cancelled",
                title=f"{self.display_name} connection",
                message=f"{self.display_name} connection was cancelled.",
                active=False,
            )
            setattr(self.ui, "_auth_setup", None)
            await self._notify_completed(
                {
                    "status": "cancelled",
                    "provider": self.provider,
                    "reason": "user_cancelled",
                }
            )
            return
        if not value:
            await self.ui.send_auth_setup(
                provider=self.provider,
                step="api_key",
                title=f"{self.display_name} setup",
                message="Input cannot be empty.",
                prompt=self._prompt_label(),
                mask=False,
            )
            return
        try:
            set_api_key(self.provider, value)
        except Exception as exc:
            await self.ui.send_auth_setup(
                provider=self.provider,
                step="api_key",
                title=f"{self.display_name} setup",
                message=sanitize_error_message(exc),
                prompt=self._prompt_label(),
                mask=False,
            )
            return
        if self.emit_feedback:
            await self.ui.append_activity(
                kind="status",
                title=f"{self.display_name} configured",
                detail=f"{self.display_name} is configured for online playback.",
                status="success",
            )
        await self.ui.send_auth_setup(
            provider=self.provider,
            step="done",
            title=f"{self.display_name} configured",
            message=f"{self.display_name} is configured for online playback.",
            active=False,
        )
        setattr(self.ui, "_auth_setup", None)
        await self._notify_completed(
            {
                "status": "connected",
                "provider": self.provider,
                "account_label": f"{self.display_name} application",
            }
        )

    async def _notify_completed(self, result: dict[str, Any]) -> None:
        if self.on_completed is None:
            return
        callback = self.on_completed
        self.on_completed = None
        callback_result = callback(result)
        if asyncio.iscoroutine(callback_result):
            await callback_result



class ModelSelectionSession:
    """Represents model selection session.

    Encapsulates model selection session data and behavior used by Sonex runtime flows.
    """
    def __init__(self, ui: WebSocketUIAdapter) -> None:
        """Prepares init for an internal Sonex flow.

        Typical use: Use this helper when nearby code needs init without duplicating the local rules.

        Example: __init__(ui=...) -> returns the value used by the surrounding Sonex flow.
        """
        self.ui = ui
        self.provider = _default_provider_name()
        self.model_choices: list[dict[str, str]] = []

    async def start(self) -> None:
        """Coordinates start for the current Sonex flow.

        Typical use: Use this function when runtime code needs start as part of a Sonex command, playback, auth, llm, or ui path.

        Example: await start() -> returns the value used by the surrounding Sonex flow.
        """
        self.provider = _default_provider_name()
        if not _provider_credentials_available(self.provider):
            await self._append_not_connected_caution(self.provider)
            setattr(self.ui, "_model_setup", None)
            return
        provider_name = normalize_provider(self.provider)
        if provider_name in {
            "deepseek", "openrouter", "zai", "kimi_global", "kimi_cn",
            "minimax_global", "minimax_cn", "xai",
        }:
            self.model_choices = await asyncio.to_thread(_model_choices_for_provider, self.provider)
        else:
            self.model_choices = _model_choices_for_provider(self.provider)
        await self.ui.send_auth_setup(
            provider=self.provider,
            step="model",
            title="Switch model",
            message=f"Choose a {provider_display_name(self.provider)} model.",
            prompt="Model",
            models=self.model_choices,
        )

    async def handle_input(self, value: str) -> None:
        """Coordinates handle input for the current Sonex flow.

        Typical use: Use this function when runtime code needs handle input as part of a Sonex command, playback, auth, llm, or ui path.

        Example: await handle_input(value=...) -> returns the value used by the surrounding Sonex flow.
        """
        text = value.strip()
        if text.lower() in {"__cancel__", "cancel"}:
            setattr(self.ui, "_model_setup", None)
            return

        parsed = _parse_model_choice(text, self.model_choices)
        if parsed is None:
            await self.ui.send_auth_setup(
                provider=self.provider,
                step="model",
                title="Switch model",
                message="Choose one of the listed models.",
                prompt="Model",
                models=self.model_choices,
            )
            return

        provider, model = parsed
        if provider != normalize_provider(self.provider) or not _provider_credentials_available(provider):
            await self._append_not_connected_caution(provider)
            setattr(self.ui, "_model_setup", None)
            return
        _set_runtime_default_provider(provider, model)
        ThinkingConfig.reload()
        state = _llm_auth_state()
        selected_choice = next(
            (choice for choice in self.model_choices if choice.get("value") == f"{provider}::{model}"),
            None,
        )
        display_model = str((selected_choice or {}).get("label") or state.model_label or model)
        display_provider = str(
            (selected_choice or {}).get("provider") or provider_display_name(provider)
        )
        await self.ui.append_system_message(
            f"✔  Model has been switched to {display_provider}: {display_model.rstrip('.')}."
        )
        await self.ui.send_auth_state(state)
        await self.ui.send_auth_setup(
            provider=provider,
            step="model",
            title="Switch model",
            message="",
            active=False,
        )
        setattr(self.ui, "_model_setup", None)

    async def _append_not_connected_caution(self, provider: str) -> None:
        await self.ui.append_caution_message(
            f'✖  {provider_display_name(provider)} is not connected. Try "/login" to connect.'
        )

class AuthSetupSession:
    """Represents auth setup session.

    Encapsulates auth setup session data and behavior used by Sonex runtime flows.
    """
    def __init__(self, ui: WebSocketUIAdapter, provider: str, pending_input: str | None, runner: "WebSocketRunner") -> None:
        """Prepares init for an internal Sonex flow.

        Typical use: Use this helper when nearby code needs init without duplicating the local rules.

        Example: __init__(ui=..., provider=..., pending_input=..., runner=...) -> returns the value used by the surrounding Sonex flow.
        """
        self.ui = ui
        self.provider = normalize_provider(provider)
        self.pending_input = pending_input
        self.runner = runner
        self.step = "method"
        self.method: str | None = None
        self.oauth_task: asyncio.Task[None] | None = None
        self.custom_name: str | None = None
        self.custom_base_url: str | None = None
        self.custom_api_key: str | None = None
        self.custom_models: list[str] = []
        self.custom_allow_insecure_http = False
        self.custom_timeout: float | None = None
        self.google_project_id: str | None = None
        self.provider_base_url: str | None = None
        self.credential_fallback_warned = False

    async def start(self, reason: str | None = None) -> None:
        """Coordinates start for the current Sonex flow.

        Typical use: Use this function when runtime code needs start as part of a Sonex command, playback, auth, llm, or ui path.

        Example: await start(reason=...) -> returns the value used by the surrounding Sonex flow.
        """
        if self.pending_input is None:
            await self.ui.append_activity(
                kind="status",
                title="Choose model provider",
                detail=reason or "Select a model provider before entering Sonex.",
                status="pending",
            )
            await self._prompt_provider(reason)
            return

        await self.ui.append_activity(
            kind="status",
            title=f"{provider_display_name(self.provider)} sign-in required",
            detail=reason or f"Sign in to {provider_display_name(self.provider)} before chatting.",
            status="pending",
        )
        await self._continue_provider_auth(reason)

    async def _prompt_provider(self, reason: str | None = None) -> None:
        """Prepares prompt provider for an internal Sonex flow.

        Typical use: Use this helper when nearby code needs prompt provider without duplicating the local rules.

        Example: await _prompt_provider(reason=...) -> returns the value used by the surrounding Sonex flow.
        """
        self.step = "provider"
        await self.ui.send_auth_setup(
            provider=self.provider,
            step="provider",
            title="Connect Sonex",
            message=reason or "Choose a model provider.",
            prompt="Model provider",
            providers=_provider_choices_with_status(),
        )

    async def _continue_provider_auth(self, reason: str | None = None) -> None:
        """Prepares continue provider auth for an internal Sonex flow.

        Typical use: Use this helper when nearby code needs continue provider auth without duplicating the local rules.

        Example: await _continue_provider_auth(reason=...) -> returns the value used by the surrounding Sonex flow.
        """
        if self.provider == "custom":
            await self._prompt_custom_profiles(reason)
            return

        if self.pending_input is None and _provider_credentials_available(self.provider):
            is_active = _default_provider_name() == self.provider
            if not is_active or not _provider_has_saved_credentials(self.provider):
                await self._finish()
                return

        if (
            self.provider == "zai"
            and self.provider_base_url is None
            and not _provider_credentials_available(self.provider)
        ):
            await self._prompt_zai_service()
            return

        capability = get_provider_capability(self.provider)
        if not capability.requires_auth:
            await self._finish()
            return

        methods = _auth_methods_for_provider(self.provider)
        if len(methods) > 1:
            self.step = "method"
            await self.ui.send_auth_setup(
                provider=self.provider,
                step="method",
                title=f"Connect {provider_display_name(self.provider)}",
                message="Choose an authentication method. Type oauth or api_key.",
                prompt="oauth or api_key",
                methods=methods,
            )
            return

        if capability.supports_oauth and browser_oauth_supported(self.provider):
            self.method = "oauth"
            await self._start_browser_oauth()
            return

        if capability.supports_api_key:
            self.method = "api_key"
            await self._prompt_api_key()
            return

        await self.ui.send_auth_setup(
            provider=self.provider,
            step="done",
            title=f"{self.provider} auth unsupported",
            message=f"Provider '{self.provider}' cannot be configured interactively.",
            active=False,
        )

    async def handle_input(self, value: str) -> None:
        """Coordinates handle input for the current Sonex flow.

        Typical use: Use this function when runtime code needs handle input as part of a Sonex command, playback, auth, llm, or ui path.

        Example: await handle_input(value=...) -> returns the value used by the surrounding Sonex flow.
        """
        value = value.strip()
        if not value:
            await self._repeat("Input cannot be empty.")
            return
        if value.casefold() in {"__cancel__", "cancel"}:
            setattr(self.ui, "_auth_setup", None)
            return

        if self.step == "provider":
            normalized = normalize_provider(value)
            if normalized not in LLM_AUTH_PROVIDER_VALUES:
                await self._prompt_provider("Choose a listed model provider.")
                return
            self.provider = normalized
            self.method = None
            await self._continue_provider_auth()
            return

        if self.step == "zai_service":
            endpoints = {
                "api": "https://api.z.ai/api/paas/v4",
                "coding_plan": "https://api.z.ai/api/coding/paas/v4",
            }
            self.provider_base_url = endpoints.get(value)
            if self.provider_base_url is None:
                await self._prompt_zai_service("Choose API or Coding Plan.")
                return
            self.method = "api_key"
            await self._prompt_api_key()
            return

        if self.step == "custom_profile":
            if value == "__add_custom__":
                self.step = "custom_name"
                await self.ui.send_auth_setup(
                    provider="custom",
                    step="custom_name",
                    title="Add custom connection",
                    message="Enter a unique connection name.",
                    prompt="Connection name",
                )
                return
            if value.startswith("__disconnect_custom__:"):
                profile_id = value.partition(":")[2]
                auth = get_provider_auth(load_auth_store(), profile_id)
                if not auth or not profile_id.startswith("custom__"):
                    await self._prompt_custom_profiles("That Custom connection no longer exists.")
                    return
                remove_provider(profile_id)
                ThinkingConfig.reload()
                await self._prompt_custom_profiles(
                    f"{auth.display_name or profile_id} disconnected and removed."
                )
                return
            auth = get_provider_auth(load_auth_store(), value)
            if not value.startswith("custom__") or not auth or not auth.base_url or not auth.model:
                await self._prompt_custom_profiles("Choose a saved connection or Add custom connection.")
                return
            if auth.needs_review:
                await self._prompt_custom_profiles(
                    f"{auth.display_name or value} needs review before it can be used."
                )
                return
            self.provider = value
            await self._finish()
            return

        if self.step == "custom_name":
            try:
                profile_id = custom_profile_id(value)
            except ValueError as exc:
                await self._repeat(sanitize_error_message(exc))
                return
            if profile_id in load_auth_store().providers:
                await self._repeat("That Custom connection name already exists.")
                return
            self.provider = profile_id
            self.custom_name = value
            self.step = "custom_base_url"
            await self.ui.send_auth_setup(
                provider="custom",
                step="custom_base_url",
                title=f"Connect {value}",
                message="Enter an OpenAI-compatible base URL, for example http://127.0.0.1:11434/v1.",
                prompt="Base URL",
            )
            return

        if self.step == "custom_base_url":
            try:
                endpoint = normalize_custom_base_url(value)
            except ValueError as exc:
                await self._repeat(sanitize_error_message(exc))
                return
            self.custom_base_url = endpoint.base_url
            if endpoint.insecure_remote:
                self.step = "custom_insecure"
                await self.ui.send_auth_setup(
                    provider="custom",
                    step="method",
                    title="Insecure Custom endpoint",
                    message=(
                        "This remote endpoint uses plain HTTP. Credentials and prompts can be intercepted. "
                        "Continue only if you trust the network."
                    ),
                    prompt="Continue or go back",
                    methods=[
                        {"value": "continue_insecure", "label": "Continue insecurely"},
                        {"value": "back", "label": "Back"},
                    ],
                )
                return
            await self._prompt_custom_auth()
            return

        if self.step == "custom_insecure":
            if value == "back":
                self.step = "custom_base_url"
                await self.ui.send_auth_setup(
                    provider="custom",
                    step="custom_base_url",
                    title=f"Connect {self.custom_name or 'Custom'}",
                    message="Enter an HTTPS endpoint or a localhost HTTP endpoint.",
                    prompt="Base URL",
                )
                return
            if value != "continue_insecure":
                await self._repeat("Choose Continue insecurely or Back.")
                return
            self.custom_allow_insecure_http = True
            await self._prompt_custom_auth()
            return

        if self.step == "custom_auth":
            if value not in {"none", "api_key"}:
                await self._repeat("Choose No authentication or Bearer API key.")
                return
            self.method = value
            if value == "api_key":
                self.step = "custom_api_key"
                await self.ui.send_auth_setup(
                    provider="custom",
                    step="custom_api_key",
                    title=f"Authenticate {self.custom_name or 'Custom'}",
                    message="Enter the Bearer API key for this endpoint.",
                    prompt="API Key",
                    placeholder="paste your key here",
                    mask=True,
                )
                return
            self.custom_api_key = None
            await self._prompt_custom_timeout()
            return

        if self.step == "custom_api_key":
            self.custom_api_key = value
            await self._prompt_custom_timeout()
            return

        if self.step == "custom_timeout":
            if value.casefold() == "default":
                self.custom_timeout = None
            else:
                try:
                    timeout = float(value)
                except ValueError:
                    await self._repeat("Enter a timeout from 1 to 600 seconds, or type default.")
                    return
                if not 1 <= timeout <= 600:
                    await self._repeat("Enter a timeout from 1 to 600 seconds, or type default.")
                    return
                self.custom_timeout = timeout
            await self._discover_custom_models()
            return

        if self.step == "custom_model":
            if value == "__manual_model__":
                await self._prompt_custom_model()
                return
            if value not in self.custom_models:
                await self._repeat("Choose a discovered model or enter a Model ID.")
                return
            await self._save_custom_profile(value)
            return

        if self.step == "custom_model_manual":
            await self._save_custom_profile(value)
            return

        if self.step == "method":
            normalized = value.lower().replace("-", "_")
            if normalized == "__unavailable_oauth__":
                _available, reason = codex_app_server_status()
                await self._repeat(reason or "OpenAI ChatGPT Subscription is unavailable.")
                return
            if normalized in {"disconnect_oauth", "disconnect_api_key"}:
                method = normalized.removeprefix("disconnect_")
                try:
                    if self.provider == "openai" and method == "oauth":
                        await asyncio.to_thread(logout_chatgpt_subscription)
                    removed = remove_provider_method(self.provider, method)
                    if method == "oauth":
                        clear_oauth_access_cache(self.provider)
                    ThinkingConfig.reload()
                except Exception as exc:
                    await self._repeat(sanitize_error_message(exc))
                    return
                await self._continue_provider_auth(
                    f"{method.replace('_', ' ').title()} disconnected."
                    if removed
                    else "That authentication method was not connected."
                )
                return
            if normalized not in {"oauth", "api_key"}:
                await self._repeat("Type oauth or api_key.")
                return
            capability = get_provider_capability(self.provider)
            if normalized == "oauth" and not capability.supports_oauth:
                await self._repeat(browser_oauth_requirements(self.provider))
                return
            if normalized == "api_key" and not capability.supports_api_key:
                await self._repeat(f"{self.provider} does not support API key sign-in.")
                return
            self.method = normalized
            if normalized == "oauth":
                if self.provider == "openai":
                    auth = get_provider_auth(load_auth_store(), "openai")
                    if not auth or not auth.experimental_confirmed:
                        self.step = "openai_experimental_confirm"
                        await self.ui.send_auth_setup(
                            provider="openai",
                            step="method",
                            title="ChatGPT Subscription (Experimental)",
                            message=(
                                "This connection uses Sonex's isolated Codex App Server runtime. "
                                "It may change with upstream protocol updates and does not use API-key billing."
                            ),
                            prompt="Continue or go back",
                            methods=[
                                {"value": "continue_experimental", "label": "Continue"},
                                {"value": "back", "label": "Back"},
                            ],
                        )
                    else:
                        await self._start_openai_oauth()
                elif self.provider == "gemini":
                    configured_project = (
                        os.getenv("SONEX_GOOGLE_CLOUD_PROJECT")
                        or os.getenv("SONEX_GEMINI_PROJECT_ID")
                    )
                    if configured_project:
                        self.google_project_id = configured_project.strip()
                        await self._start_browser_oauth()
                    else:
                        self.step = "google_project"
                        await self.ui.send_auth_setup(
                            provider=self.provider,
                            step="google_project",
                            title="Google Cloud project",
                            message=(
                                "Enter the Google Cloud project ID that owns Gemini API access and billing. "
                                "Sonex will validate access but will not create a project or enable billing."
                            ),
                            prompt="Google Cloud project ID",
                        )
                else:
                    await self._start_browser_oauth()
            else:
                await self._prompt_api_key()
            return

        if self.step == "openai_experimental_confirm":
            if value == "back":
                self.step = "method"
                self.method = None
                await self._continue_provider_auth()
                return
            if value != "continue_experimental":
                await self._repeat("Choose Continue or Back.")
                return
            set_experimental_confirmation("openai")
            await self._start_openai_oauth()
            return

        if self.step == "google_project":
            if not re.fullmatch(r"[a-z][a-z0-9-]{4,28}[a-z0-9]", value):
                await self._repeat(
                    "Enter a valid Google Cloud project ID (6-30 lowercase letters, digits, or hyphens)."
                )
                return
            self.google_project_id = value
            await self._start_browser_oauth()
            return
        if self.step == "api_key":
            try:
                capability = get_provider_capability(self.provider)
                set_api_key(
                    self.provider,
                    value,
                    base_url=self.provider_base_url or capability.default_base_url,
                    custom_llm_provider=capability.default_custom_llm_provider,
                )
                _set_runtime_default_provider(self.provider)
                ThinkingConfig.reload()
            except Exception as exc:
                await self._repeat(sanitize_error_message(exc))
                return
            await self._finish()
            return

        if self.step == "oauth_wait":
            if value.lower().replace("-", "_") == "api_key":
                self.method = "api_key"
                await self._prompt_api_key()
                return
            await self._repeat("OAuth is already in progress. Finish the browser flow, or type api_key to use an API key.")
            return

        if self.step == "oauth_callback":
            if self.browser_oauth_pending is None:
                self.method = None
                self.step = "method"
                await self._repeat("OAuth session expired. Start OAuth again.")
                return
            try:
                await asyncio.to_thread(
                    complete_browser_oauth,
                    self.browser_oauth_pending,
                    value,
                    project_id=self.google_project_id,
                )
                _set_runtime_default_provider(self.provider)
                ThinkingConfig.reload()
            except Exception as exc:
                await self._repeat(sanitize_error_message(exc))
                return
            await self._finish()

    async def _prompt_custom_profiles(self, reason: str | None = None) -> None:
        self.step = "custom_profile"
        profiles = []
        for name, auth in sorted(load_auth_store().providers.items()):
            if not name.startswith("custom__"):
                continue
            status = "Needs review" if auth.needs_review else "Connected"
            profiles.append({
                "value": name,
                "label": f"{auth.display_name or name} — {status}",
            })
            profiles.append({
                "value": f"__disconnect_custom__:{name}",
                "label": f"Disconnect {auth.display_name or name}",
            })
        profiles.append({"value": "__add_custom__", "label": "Add custom connection"})
        await self.ui.send_auth_setup(
            provider="custom",
            step="provider",
            title="Custom connections",
            message=reason or "Choose a saved connection or add an OpenAI-compatible endpoint.",
            prompt="Custom connection",
            providers=profiles,
        )

    async def _prompt_custom_auth(self) -> None:
        self.step = "custom_auth"
        await self.ui.send_auth_setup(
            provider="custom",
            step="method",
            title=f"Authenticate {self.custom_name or 'Custom'}",
            message="Choose how this endpoint authenticates requests.",
            prompt="Authentication",
            methods=_auth_methods_for_provider("custom"),
        )

    async def _discover_custom_models(self) -> None:
        assert self.custom_base_url is not None
        try:
            self.custom_models = await asyncio.to_thread(
                discover_custom_models,
                self.custom_base_url,
                api_key=self.custom_api_key,
                timeout=self.custom_timeout or 15.0,
            )
        except Exception:
            self.custom_models = []
        if not self.custom_models:
            await self._prompt_custom_model()
            return
        self.step = "custom_model"
        await self.ui.send_auth_setup(
            provider="custom",
            step="model",
            title=f"Choose a model for {self.custom_name or 'Custom'}",
            message="Choose a discovered model or enter a Model ID manually.",
            prompt="Model",
            models=[
                {"value": model, "label": model, "provider": self.custom_name or "Custom"}
                for model in self.custom_models
            ] + [
                {"value": "__manual_model__", "label": "Enter Model ID manually", "provider": "Custom"}
            ],
        )

    async def _prompt_custom_model(self) -> None:
        self.step = "custom_model_manual"
        await self.ui.send_auth_setup(
            provider="custom",
            step="custom_model_manual",
            title=f"Configure {self.custom_name or 'Custom'}",
            message="Enter the exact model ID accepted by the endpoint.",
            prompt="Model ID",
        )

    async def _save_custom_profile(self, model: str) -> None:
        assert self.custom_base_url is not None
        try:
            await asyncio.to_thread(
                test_custom_connection,
                self.custom_base_url,
                model,
                api_key=self.custom_api_key,
                timeout=self.custom_timeout or 30.0,
            )
        except Exception as exc:
            self.step = "custom_model_manual"
            await self.ui.send_auth_setup(
                provider="custom",
                step="custom_model_manual",
                title="Custom connection failed",
                message=(
                    f"{sanitize_error_message(exc)} "
                    "Check the endpoint and Model ID; the connection was not saved."
                ),
                prompt="Model ID",
            )
            return
        set_custom_profile(
            self.provider,
            display_name=self.custom_name or "Custom",
            base_url=self.custom_base_url,
            model=model,
            api_key=self.custom_api_key,
            model_ids=[*self.custom_models, model],
            allow_insecure_http=self.custom_allow_insecure_http,
            timeout=self.custom_timeout,
        )
        await self._finish()

    async def _prompt_custom_timeout(self) -> None:
        self.step = "custom_timeout"
        await self.ui.send_auth_setup(
            provider="custom",
            step="custom_timeout",
            title=f"Configure {self.custom_name or 'Custom'}",
            message="Enter a request timeout in seconds, or type default to use Sonex defaults.",
            prompt="Timeout seconds or default",
        )

    async def _prompt_api_key(self) -> None:
        """Prepares prompt api key for an internal Sonex flow.

        Typical use: Use this helper when nearby code needs prompt api key without duplicating the local rules.

        Example: await _prompt_api_key() -> returns the value used by the surrounding Sonex flow.
        """
        self.step = "api_key"
        await self.ui.send_auth_setup(
            provider=self.provider,
            step="api_key",
            title=f"{provider_display_name(self.provider)} API key",
            message=f"Paste your {provider_display_name(self.provider)} API key. It will be saved to auth.json.",
            prompt="API Key",
            placeholder="paste your key here",
            help_text=_api_key_help_text(self.provider),
            mask=True,
            methods=_auth_methods_for_provider(self.provider),
        )

    async def _prompt_zai_service(self, message: str | None = None) -> None:
        self.step = "zai_service"
        await self.ui.send_auth_setup(
            provider="zai",
            step="method",
            title="Connect Z.AI",
            message=message or "Choose the Z.AI service attached to this API Key.",
            prompt="Service",
            methods=[
                {"value": "api", "label": "API"},
                {"value": "coding_plan", "label": "Coding Plan"},
            ],
        )

    async def _start_browser_oauth(self) -> None:
        """Prepares start browser oauth for an internal Sonex flow.

        Typical use: Use this helper when nearby code needs start browser oauth without duplicating the local rules.

        Example: await _start_browser_oauth() -> returns the value used by the surrounding Sonex flow.
        """
        if self.provider == "gemini" and credential_storage_backend() == "file":
            self.credential_fallback_warned = True
            await self.ui.append_system_message(
                "Warning: No usable system keyring is available. Continuing will store the Google OAuth "
                "refresh token in ~/.sonex/oauth-secrets.json with 0600 permissions."
            )
        try:
            self.browser_oauth_pending = begin_browser_oauth(self.provider)
        except Exception as exc:
            self.method = None
            self.step = "method"
            await self._repeat(sanitize_error_message(exc))
            return
        self.step = "oauth_callback"
        webbrowser.open(self.browser_oauth_pending.authorize_url)
        await self.ui.send_auth_setup(
            provider=self.provider,
            step="oauth_callback",
            title=f"Authorize {self.provider}",
            message=(
                "Open the authorization URL below. After Google redirects to localhost, "
                "copy the complete URL from the browser address bar and paste it here.\n"
                f"{self.browser_oauth_pending.authorize_url}"
            ),
            prompt="Full localhost callback URL",
            methods=_auth_methods_for_provider(self.provider),
        )

    async def _start_openai_oauth(self) -> None:
        """Start the official managed ChatGPT device-code flow."""
        self.step = "oauth_wait"
        try:
            server = await asyncio.to_thread(CodexAppServer, timeout=300)
            login = await asyncio.to_thread(start_chatgpt_device_login, server)
        except Exception as exc:
            self.step = "method"
            self.method = None
            await self._repeat(sanitize_error_message(exc))
            return
        self.codex_server = server
        await self.ui.send_auth_setup(
            provider="openai",
            step="oauth_wait",
            title="Connect ChatGPT Subscription",
            message=(
                "Open the verification URL and enter the device code.\n"
                f"{login['verificationUrl']}\n"
                f"Code: {login['userCode']}"
            ),
            active=True,
            methods=_auth_methods_for_provider("openai"),
        )
        self.oauth_task = asyncio.create_task(
            self._finish_openai_oauth(server, login["loginId"])
        )

    async def _finish_openai_oauth(
        self,
        server: CodexAppServer,
        login_id: str,
    ) -> None:
        try:
            await asyncio.to_thread(wait_for_chatgpt_login, server, login_id)
            set_managed_auth("openai", "codex_app_server")
            _set_runtime_default_provider("openai")
            ThinkingConfig.reload()
        except asyncio.CancelledError:
            return
        except Exception as exc:
            self.step = "method"
            self.method = None
            await self._repeat(sanitize_error_message(exc))
            return
        finally:
            await asyncio.to_thread(server.close)
            if self.codex_server is server:
                self.codex_server = None
        await self._finish()

    async def _repeat(self, message: str) -> None:
        """Prepares repeat for an internal Sonex flow.

        Typical use: Use this helper when nearby code needs repeat without duplicating the local rules.

        Example: await _repeat(message=...) -> returns the value used by the surrounding Sonex flow.
        """
        if self.step == "google_project":
            await self.ui.send_auth_setup(
                provider=self.provider,
                step="google_project",
                title="Google Cloud project",
                message=message,
                prompt="Google Cloud project ID",
            )
            return
        if self.step == "zai_service":
            await self._prompt_zai_service(message)
            return
        if self.step == "openai_experimental_confirm":
            await self.ui.send_auth_setup(
                provider="openai",
                step="method",
                title="ChatGPT Subscription (Experimental)",
                message=message,
                prompt="Continue or go back",
                methods=[
                    {"value": "continue_experimental", "label": "Continue"},
                    {"value": "back", "label": "Back"},
                ],
            )
            return
        if self.step == "custom_name":
            await self.ui.send_auth_setup(
                provider="custom",
                step="custom_name",
                title="Add custom connection",
                message=message,
                prompt="Connection name",
            )
            return
        if self.step == "custom_base_url":
            await self.ui.send_auth_setup(
                provider="custom",
                step="custom_base_url",
                title=f"Connect {self.custom_name or 'Custom'}",
                message=message,
                prompt="Base URL",
            )
            return
        if self.step == "custom_timeout":
            await self.ui.send_auth_setup(
                provider="custom",
                step="custom_timeout",
                title=f"Configure {self.custom_name or 'Custom'}",
                message=message,
                prompt="Timeout seconds or default",
            )
            return
        if self.step in {"custom_model", "custom_model_manual"}:
            await self._prompt_custom_model()
            return
        if self.step == "custom_auth":
            await self.ui.send_auth_setup(
                provider="custom",
                step="method",
                title=f"Authenticate {self.custom_name or 'Custom'}",
                message=message,
                prompt="Authentication",
                methods=_auth_methods_for_provider("custom"),
            )
            return
        if self.step == "custom_api_key":
            await self.ui.send_auth_setup(
                provider="custom",
                step="custom_api_key",
                title=f"Authenticate {self.custom_name or 'Custom'}",
                message=message,
                prompt="API Key",
                placeholder="paste your key here",
                mask=True,
            )
            return
        if self.method == "oauth" and self.step in {"oauth_wait", "oauth_callback"}:
            await self.ui.send_auth_setup(
                provider=self.provider,
                step="oauth_callback",
                title=f"Authorize {self.provider}",
                message=message,
                prompt="Full localhost callback URL",
                methods=_auth_methods_for_provider(self.provider),
            )
            return
        if self.method == "api_key" or self.step == "api_key":
            await self.ui.send_auth_setup(
                provider=self.provider,
                step="api_key",
                title=f"{provider_display_name(self.provider)} API key",
                message=message,
                prompt="API Key",
                placeholder="paste your key here",
                help_text=_api_key_help_text(self.provider),
                mask=True,
                methods=_auth_methods_for_provider(self.provider),
            )
            return
        await self.ui.send_auth_setup(
            provider=self.provider,
            step="method",
            title=f"Connect {provider_display_name(self.provider)}",
            message=message,
            prompt="oauth or api_key",
            methods=_auth_methods_for_provider(self.provider),
            providers=_provider_choices_with_status() if self.pending_input is None else None,
        )

    async def _finish(self) -> None:
        """Prepares finish for an internal Sonex flow.

        Typical use: Use this helper when nearby code needs finish without duplicating the local rules.

        Example: await _finish() -> returns the value used by the surrounding Sonex flow.
        """
        try:
            _set_runtime_default_provider(self.provider)
            ThinkingConfig.reload()
        except Exception as exc:
            await self._repeat(sanitize_error_message(exc))
            return
        state = _llm_auth_state()
        await self.ui.append_activity(
            kind="status",
            title=f"{provider_display_name(self.provider)} connected",
            detail="Continuing your message." if self.pending_input else "Sign-in complete.",
            status="success",
        )
        await self.ui.send_auth_state(state)
        if self.provider == "gemini" and self.method == "oauth":
            google_auth = get_provider_auth(load_auth_store(), "gemini")
            refresh_ref = (
                google_auth.oauth.refresh_token_ref
                if google_auth and google_auth.oauth
                else None
            )
            if (
                refresh_ref
                and refresh_ref.startswith("file://")
                and not self.credential_fallback_warned
            ):
                await self.ui.append_system_message(
                    "Warning: No usable system keyring is available. The Google OAuth refresh token is "
                    "stored in ~/.sonex/oauth-secrets.json with 0600 permissions."
                )
        await self.ui.send_auth_setup(
            provider=self.provider,
            step="done",
            title=f"{provider_display_name(self.provider)} connected",
            message="Sign-in complete. Continuing your message." if self.pending_input else "Sign-in complete.",
            active=False,
        )
        setattr(self.ui, "_auth_setup", None)
        if self.pending_input:
            self.runner._running_task = None
            await self.runner._handle_user_input(self.ui, self.pending_input, append_user_message=False)


class MusicIntentConfirmationSession:
    """Represents music intent confirmation session.

    Encapsulates music intent confirmation session data and behavior used by Sonex runtime flows.
    """
    def __init__(self, ui: WebSocketUIAdapter, runner: "WebSocketRunner", original_input: str, query: str) -> None:
        """Prepares init for an internal Sonex flow.

        Typical use: Use this helper when nearby code needs init without duplicating the local rules.

        Example: __init__(ui=..., runner=..., original_input=..., query=...) -> returns the value used by the surrounding Sonex flow.
        """
        self.ui = ui
        self.runner = runner
        self.original_input = original_input
        self.query = query
        self.confirm_id = _new_event_id("confirm")

    async def start(self) -> None:
        """Coordinates start for the current Sonex flow.

        Typical use: Use this function when runtime code needs start as part of a Sonex command, playback, auth, llm, or ui path.

        Example: await start() -> returns the value used by the surrounding Sonex flow.
        """
        await self.ui.ask_confirm(
            {
                "id": self.confirm_id,
                "tool_name": "music_intent",
                "tool_args": {"query": self.query},
                "message": f"Play \"{self.query}\" or discuss it first?",
                "choices": [
                    {"value": "play_track", "label": "Play track", "description": "choose a playback source and track"},
                    {"value": "discuss_track", "label": "Discuss track", "description": "continue without starting playback"},
                ],
            }
        )

    def owns_confirm(self, confirm_id: str) -> bool:
        """Coordinates owns confirm for the current Sonex flow.

        Typical use: Use this function when runtime code needs owns confirm as part of a Sonex command, playback, auth, llm, or ui path.

        Example: owns_confirm(confirm_id=...) -> returns the value used by the surrounding Sonex flow.
        """
        return confirm_id == self.confirm_id

    async def handle_choice(self, decision: Any) -> None:
        """Coordinates handle choice for the current Sonex flow.

        Typical use: Use this function when runtime code needs handle choice as part of a Sonex command, playback, auth, llm, or ui path.

        Example: await handle_choice(decision=...) -> returns the value used by the surrounding Sonex flow.
        """
        setattr(self.ui, "_music_intent_confirmation", None)
        if str(decision) == "play_track":
            session = PlaySelectionSession(self.ui, self.runner, self.query)
            setattr(self.ui, "_play_selection", session)
            await session.start()
            return

        ready, provider, reason = _llm_auth_ready()
        if not ready:
            setup = AuthSetupSession(self.ui, provider, self.original_input, self.runner)
            setattr(self.ui, "_auth_setup", setup)
            await setup.start(reason)
            return
        intent = CommandIntent(
            command="general",
            raw=self.original_input,
            args="",
            intent_prompt="Discuss the user's message in text only. Do not call tools or start playback.",
            allowed_tools=(),
        )
        self.runner._running_task = asyncio.create_task(
            self.runner._run_agent_turn(self.ui, self.original_input, command_intent=intent)
        )


class PlaySelectionSession:
    """Represents play selection session.

    Encapsulates play selection session data and behavior used by Sonex runtime flows.
    """
    def __init__(
        self,
        ui: WebSocketUIAdapter,
        runner: "WebSocketRunner",
        query: str,
        *,
        on_finish: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        """Prepares init for an internal Sonex flow.

        Typical use: Use this helper when nearby code needs init without duplicating the local rules.

        Example: __init__(ui=..., runner=..., query=...) -> returns the value used by the surrounding Sonex flow.
        """
        self.ui = ui
        self.runner = runner
        self.query = query.strip()
        self.local_file: str | None = None
        self.active_confirm_id: str | None = None
        self.pending_player_confirm_result: dict[str, Any] | None = None
        self.metadata_candidates: list[dict[str, Any]] = []
        self.native_candidates: list[dict[str, Any]] = []
        self.online_audio_candidates: list[dict[str, Any]] = []
        self.playback_source: str | None = None
        self.selected_playback_metadata: dict[str, Any] | None = None
        self.awaiting_metadata_refinement = False
        self.awaiting_native_refinement = False
        self.awaiting_online_refinement = False
        self._on_finish = on_finish
        self._finished = False

    async def start(self) -> None:
        """Coordinates start for the current Sonex flow.

        Typical use: Use this function when runtime code needs start as part of a Sonex command, playback, auth, llm, or ui path.

        Example: await start() -> returns the value used by the surrounding Sonex flow.
        """
        if not self.query:
            message = "Tell Sonex what you want to play, for example: play Space Oddity."
            await self.ui.append_activity(kind="error", title="Invalid play request", detail=message, status="error")
            await self.ui.append_agent_message(message)
            return

        local_result = search_local_file(self.query)
        if _is_local_search_hit(local_result):
            self.local_file = local_result
            await self._ask_local_choice(local_result)
            return

        await self._begin_source_selection()

    def owns_confirm(self, confirm_id: str) -> bool:
        """Coordinates owns confirm for the current Sonex flow.

        Typical use: Use this function when runtime code needs owns confirm as part of a Sonex command, playback, auth, llm, or ui path.

        Example: owns_confirm(confirm_id=...) -> returns the value used by the surrounding Sonex flow.
        """
        return bool(self.active_confirm_id and confirm_id == self.active_confirm_id)

    async def handle_choice(self, decision: Any) -> None:
        """Coordinates handle choice for the current Sonex flow.

        Typical use: Use this function when runtime code needs handle choice as part of a Sonex command, playback, auth, llm, or ui path.

        Example: await handle_choice(decision=...) -> returns the value used by the surrounding Sonex flow.
        """
        choice = str(decision or "cancel")
        if self.pending_player_confirm_result:
            await self._complete_player_confirmation(choice)
            return

        if choice in {"deny", "cancel"}:
            await self._finish("Playback canceled.", status="error")
            return
        if choice.startswith("playback_source:"):
            source = choice.partition(":")[2].strip().casefold()
            if source not in {"netease", "spotify", "online"}:
                await self._finish("Playback canceled.", status="error")
                return
            self.playback_source = source
            if source == "online":
                self.native_candidates = []
                await self._ask_metadata_candidates(self.query)
            else:
                await self._ask_native_candidates(source, self.query)
            return
        if choice == "choose_other_source":
            await self._begin_source_selection(exclude=self.playback_source)
            return
        if choice.startswith("refine_native_query:"):
            extra = unquote(choice.partition(":")[2]).strip()
            if not extra:
                await self.ui.append_activity(kind="error", title="Refine song search", detail="Search details cannot be empty.", status="error")
                return
            self.awaiting_native_refinement = False
            self.query = f"{self.query} {extra}".strip()
            await self._ask_native_candidates(self.playback_source or "", self.query)
            return
        if choice == "retry_native_query":
            await self._ask_native_candidates(self.playback_source or "", self.query)
            return
        if choice == "refine_native_query":
            self.awaiting_native_refinement = True
            await self.ui.append_activity(kind="status", title="Refine song search", detail="Send more song details to search again.", status="pending")
            return
        if choice.startswith("refine_spotify_query:") or choice.startswith("refine_song_metadata_query:"):
            extra = unquote(choice.partition(":")[2]).strip()
            if not extra:
                await self.ui.append_activity(
                    kind="error",
                    title="Refine song metadata search",
                    detail="Search details cannot be empty.",
                    status="error",
                )
                return
            self.awaiting_metadata_refinement = False
            self.query = f"{self.query} {extra}".strip()
            await self._ask_metadata_candidates(self.query)
            return
        if choice == "retry_metadata_query":
            await self._ask_metadata_candidates(self.query)
            return
        if choice in {"refine_spotify_query", "refine_song_metadata_query"}:
            self.awaiting_metadata_refinement = True
            await self.ui.append_activity(
                kind="status",
                title="Refine song metadata search",
                detail="Send more song details to search again.",
                status="pending",
            )
            return
        if choice.startswith("refine_query:"):
            extra = unquote(choice.partition(":")[2]).strip()
            if not extra:
                await self.ui.append_activity(
                    kind="error",
                    title="Refine online audio search",
                    detail="Search details cannot be empty.",
                    status="error",
                )
                return
            self.awaiting_online_refinement = False
            self.query = f"{self.query} {extra}".strip()
            await self._ask_online_audio_candidates(self.query, playback_metadata=self.selected_playback_metadata)
            return
        if choice == "retry_online_query":
            await self._ask_online_audio_candidates(self.query, playback_metadata=self.selected_playback_metadata)
            return
        if choice == "refine_query":
            self.awaiting_online_refinement = True
            await self.ui.append_activity(
                kind="status",
                title="Refine online audio search",
                detail="Send more song details to search again.",
                status="pending",
            )
            return
        if choice.startswith("spotify_candidate:") or choice.startswith("song_candidate:"):
            index_text = choice.partition(":")[2]
            try:
                index = int(index_text)
            except ValueError:
                index = -1
            source_candidates = self.native_candidates or self.metadata_candidates
            candidate = source_candidates[index] if 0 <= index < len(source_candidates) else None
            if candidate is None:
                await self._finish("Selected song metadata candidate expired.", status="error")
                return
            await self.ui.append_system_message(
                format_song_candidate_feedback(candidate)
            )
            self.selected_playback_metadata = dict(candidate)
            self.selected_playback_metadata.setdefault("original_query", self.query)
            if self.native_candidates:
                result = await self._play_native_candidate(candidate)
                if _is_failed_tool_result(result):
                    await self._finish("Playback failed.", status="error")
                else:
                    await self._finish("Playback selected.")
                return
            youtube_query = str(candidate.get("youtube_query") or f"{candidate.get('artist') or ''} {candidate.get('name') or ''}").strip()
            self.query = youtube_query or self.query
            await self._play_selected_metadata_candidate(self.query, self.selected_playback_metadata)
            return
        if choice.startswith("youtube_candidate:"):
            cache_id = choice.partition(":")[2]
            candidate = next(
                (item for item in self.online_audio_candidates if str(item.get("cache_id")) == cache_id),
                None,
            )
            if candidate is None:
                await self._finish("Selected online audio candidate expired.", status="error")
                return
            assessment = candidate.get("assessment")
            if isinstance(assessment, dict) and assessment.get("confidence") == "medium":
                candidate = {
                    **candidate,
                    "user_verified": True,
                    "user_verified_at": time.time(),
                }
            result = await self._play_online_audio_candidate(candidate)
            if _is_failed_tool_result(result):
                await self._finish("Online playback failed.", status="error")
            elif _is_player_confirm_result(result):
                return
            else:
                await self._finish("Online playback selected.")
            return
        if choice == "play_local":
            result = await self._invoke_playback("play_local_song", {"query": self.query, "player": "auto"})
            if _is_player_confirm_result(result):
                return
            if isinstance(result, dict) and result.get("status") == "success":
                await self.runner._handoff_previous_provider(self.ui, "local")
                setattr(self.ui, "_active_playback_provider", "local")
            await self._finish("Local playback selected.")
            return
        if choice == "skip_local":
            await self._begin_source_selection()
            return
        if choice == "online_play":
            # Compatibility for an in-flight client that still owns the removed
            # playback-method confirmation. New normal-mode sessions never emit it.
            self.playback_source = "online"
            await self._ask_metadata_candidates(self.query)
            return
        await self._finish("Unknown playback choice.", status="error")

    async def handle_refinement(self, text: str) -> bool:
        """Coordinates handle refinement for the current Sonex flow.

        Typical use: Use this function when runtime code needs handle refinement as part of a Sonex command, playback, auth, llm, or ui path.

        Example: await handle_refinement(text=...) -> returns the value used by the surrounding Sonex flow.
        """
        if self.awaiting_native_refinement:
            extra = text.strip()
            if not extra:
                await self.ui.append_activity(kind="error", title="Refine song search", detail="Search details cannot be empty.", status="error")
                return True
            self.awaiting_native_refinement = False
            self.query = f"{self.query} {extra}".strip()
            await self._ask_native_candidates(self.playback_source or "", self.query)
            return True
        if self.awaiting_metadata_refinement:
            extra = text.strip()
            if not extra:
                await self.ui.append_activity(
                    kind="error",
                    title="Refine song metadata search",
                    detail="Search details cannot be empty.",
                    status="error",
                )
                return True
            self.awaiting_metadata_refinement = False
            self.query = f"{self.query} {extra}".strip()
            await self._ask_metadata_candidates(self.query)
            return True
        if not self.awaiting_online_refinement:
            return False
        extra = text.strip()
        if not extra:
            await self.ui.append_activity(
                kind="error",
                title="Refine online audio search",
                detail="Search details cannot be empty.",
                status="error",
            )
            return True
        self.awaiting_online_refinement = False
        self.query = f"{self.query} {extra}".strip()
        await self._ask_online_audio_candidates(self.query, playback_metadata=self.selected_playback_metadata)
        return True

    async def _begin_source_selection(self, *, exclude: str | None = None) -> None:
        source = await self.runner._select_playback_source(
            self.ui,
            exclude=exclude,
        )
        if source is None:
            await self._finish("Playback canceled.", status="error")
            return
        self.playback_source = source
        if source == "online":
            self.native_candidates = []
            await self._ask_metadata_candidates(self.query)
        else:
            await self._ask_native_candidates(source, self.query)

    async def _ask_native_candidates(self, provider: str, query: str) -> None:
        self.native_candidates = []
        self.metadata_candidates = []
        try:
            self.native_candidates = await self.runner._search_authoritative_candidates(
                self.ui,
                provider,
                query,
            )
        except Exception as exc:
            message = sanitize_error_message(exc)
            await self.ui.append_activity(
                kind="error",
                title=f"{provider.title()} search",
                detail=message,
                status="error",
            )
            await self._ask_confirm(
                message=f"{provider.title()} search failed",
                choices=[
                    {"value": "retry_native_query", "label": "Retry"},
                    {"value": "refine_native_query", "label": "Type to supplement.", "input": {"placeholder": ""}},
                    {"value": "choose_other_source", "label": "Choose another source"},
                    {"value": "cancel", "label": "Cancel"},
                ],
                tool_args={"query": query, "stage": "authoritative_search_error", "provider": provider},
                tool_name="song_candidate",
            )
            return
        if not self.native_candidates:
            await self.ui.append_activity(
                kind="error",
                title=f"{provider.title()} search",
                detail=f"No playable {provider.title()} tracks found.",
                status="error",
            )
            await self._ask_confirm(
                message=f"No {provider.title()} tracks found",
                choices=[
                    {"value": "retry_native_query", "label": "Retry"},
                    {"value": "refine_native_query", "label": "Type to supplement.", "input": {"placeholder": ""}},
                    {"value": "choose_other_source", "label": "Choose another source"},
                    {"value": "cancel", "label": "Cancel"},
                ],
                tool_args={"query": query, "stage": "authoritative_candidates", "provider": provider},
                tool_name="song_candidate",
            )
            return
        choices = [
            self._metadata_candidate_choice(index, candidate)
            for index, candidate in enumerate(self.native_candidates[:5])
        ]
        choices.extend(
            [
                {"value": "refine_native_query", "label": "Not found? Type to supplement.", "input": {"placeholder": ""}},
                {"value": "choose_other_source", "label": "Choose another source"},
            ]
        )
        await self._ask_confirm(
            message=f"Choose a {provider.title()} track",
            choices=choices,
            tool_args={"query": query, "stage": "authoritative_candidates", "provider": provider},
            tool_name="song_candidate",
        )

    async def _play_native_candidate(self, candidate: dict[str, Any]) -> dict[str, Any]:
        provider = str(candidate.get("provider") or self.playback_source or "").casefold()
        if provider not in {"netease", "spotify"}:
            return {"status": "fail", "message": "Unsupported native playback source."}
        readiness = await self.runner._activate_authoritative_source(self.ui, provider)
        if readiness is None:
            return {"status": "fail", "message": f"{provider.title()} is no longer ready."}
        identity = RecordingIdentity(
            title=str(candidate.get("title") or candidate.get("name") or ""),
            artist=str(candidate.get("artist") or ""),
            album=str(candidate.get("album") or ""),
            duration_ms=_duration_ms_or_none(candidate.get("duration_ms")),
            metadata_source=provider,
        )
        result = await self.runner._try_selected_native_provider(
            self.ui,
            identity=identity,
            provider=provider,
            selected_candidate=candidate,
            readiness=readiness,
        )
        if result.get("status") == "playback_completed":
            setattr(self.ui, "_preferred_playback_provider", provider)
        return result

    async def _show_online_audio_setup_required(self) -> None:
        """Prepares show online audio setup required for an internal Sonex flow.

        Typical use: Use this helper when nearby code needs show online audio setup required without duplicating the local rules.

        Example: await _show_online_audio_setup_required() -> returns the value used by the surrounding Sonex flow.
        """
        await self.ui.append_activity(
            kind="error",
            title="Online audio setup required",
            detail=ONLINE_AUDIO_SETUP_MESSAGE,
            status="error",
        )
        await self.ui.append_agent_message(ONLINE_AUDIO_SETUP_MESSAGE)
        await self.ui.send_error(ONLINE_AUDIO_SETUP_MESSAGE)
        await self._finish("Online audio setup required.", status="error")

    async def _ask_local_choice(self, local_file: str) -> None:
        """Prepares ask local choice for an internal Sonex flow.

        Typical use: Use this helper when nearby code needs ask local choice without duplicating the local rules.

        Example: await _ask_local_choice(local_file=...) -> returns the value used by the surrounding Sonex flow.
        """
        await self._ask_confirm(
            message=f"Play local file {_filename(local_file)}?",
            choices=LOCAL_PLAYBACK_CHOICES,
            tool_args={"query": self.query, "file": local_file, "stage": "local_match"},
        )

    async def _ask_metadata_candidates(self, query: str) -> None:
        """Prepares ask metadata candidates for an internal Sonex flow.

        Typical use: Use this helper when nearby code needs ask metadata candidates without duplicating the local rules.

        Example: await _ask_metadata_candidates(query=...) -> returns the value used by the surrounding Sonex flow.
        """
        await self.ui.append_activity(
            kind="tool",
            title="Searching song metadata",
            detail=f"Finding song metadata for {query}.",
            status="pending",
        )
        self.native_candidates = []
        attempts: list[dict[str, Any]] = []
        search_failed = False
        try:
            result = await asyncio.to_thread(search_track_metadata_candidates, query, 5)
            if isinstance(result, dict):
                raw_candidates = result.get("candidates")
                attempts = result.get("source_attempts") if isinstance(result.get("source_attempts"), list) else []
                self.metadata_candidates = raw_candidates if isinstance(raw_candidates, list) else []
            elif isinstance(result, list):
                self.metadata_candidates = result
            else:
                self.metadata_candidates = []
        except Exception as exc:
            search_failed = True
            self.metadata_candidates = []
            attempts = [{
                "provider": "metadata",
                "status": "error",
                "candidate_count": 0,
                "credible_count": 0,
                "message": sanitize_error_message(exc),
            }]
        await self._append_metadata_attempts(attempts)
        self.metadata_candidates = self.metadata_candidates[:5]
        if not self.metadata_candidates:
            if search_failed:
                await self._ask_confirm(
                    message="Song metadata search failed",
                    choices=[
                        {"value": "retry_metadata_query", "label": "Retry"},
                        {"value": "refine_song_metadata_query", "label": "Type to supplement.", "input": {"placeholder": ""}},
                        {"value": "choose_other_source", "label": "Choose another source"},
                        {"value": "cancel", "label": "Cancel"},
                    ],
                    tool_args={"query": query, "stage": "song_metadata_search_error"},
                    tool_name="song_candidate",
                )
                return
            if attempts:
                message = "No song metadata candidates found. Searching online audio directly."
                await self.ui.append_agent_message(message)
                await self.ui.send_error(message)
            await self._ask_online_audio_candidates(query)
            return

        choices = [self._metadata_candidate_choice(index, item) for index, item in enumerate(self.metadata_candidates)]
        choices.append(
            {
                "value": "refine_song_metadata_query",
                "label": "Not found? Type to supplement.",
                "input": {"placeholder": ""},
            }
        )
        choices.append({"value": "choose_other_source", "label": "Choose another source"})
        await self._ask_confirm(
            message="Select the version to play",
            choices=choices,
            tool_args={"query": query, "stage": "song_metadata_candidates"},
            tool_name="song_candidate",
        )

    def _metadata_candidate_choice(self, index: int, candidate: dict[str, Any]) -> dict[str, Any]:
        """Prepares metadata candidate choice for an internal Sonex flow.

        Typical use: Use this helper when nearby code needs metadata candidate choice without duplicating the local rules.

        Example: _metadata_candidate_choice(index=..., candidate=...) -> returns the value used by the surrounding Sonex flow.
        """
        artist = candidate.get("artist")
        album = candidate.get("album")
        name = candidate.get("name") or candidate.get("title")
        parts: list[str] = []
        provider = str(candidate.get("provider") or candidate.get("metadata_source") or "").strip()
        if provider:
            parts.append(_metadata_provider_label(provider))
        return {
            "value": f"song_candidate:{index}",
            "label": format_music_candidate_label(artist, album, name),
            "display": music_candidate_display(artist, album, name),
            "description": " · ".join(part for part in parts if part),
        }

    async def _ask_online_audio_candidates(self, query: str, playback_metadata: dict[str, Any] | None = None) -> None:
        """Prepares ask online audio candidates for an internal Sonex flow.

        Typical use: Use this helper when nearby code needs ask online audio candidates without duplicating the local rules.

        Example: await _ask_online_audio_candidates(query=..., playback_metadata=...) -> returns the value used by the surrounding Sonex flow.
        """
        await self.ui.append_activity(
            kind="tool",
            title="Searching online audio",
            detail=f"Finding online matches for {query}.",
            status="pending",
        )
        try:
            if playback_metadata:
                metadata = dict(playback_metadata)
                metadata["youtube_query"] = query
                self.online_audio_candidates = await asyncio.to_thread(
                    _search_online_audio_for_runner,
                    query,
                    5,
                    playback_metadata=metadata,
                )
            else:
                self.online_audio_candidates = await asyncio.to_thread(_search_online_audio_for_runner, query, 5)
        except OnlineAudioSetupRequired:
            await self._show_online_audio_setup_required()
            return
        except Exception as exc:
            result = {
                "status": "fail",
                "tool": "play_online_audio",
                "message": sanitize_error_message(exc),
                "error_code": "ONLINE_AUDIO_RESOLVE_FAILED",
                "data": {"query": query, "provider": "online_audio", "method": "online_play"},
            }
            await self.runner._sync_tool_result_ui(self.ui, "play_online_audio", result)
            message = _friendly_runtime_error_message(result, fallback="Online audio search failed.")
            await self.ui.send_error(message)
            await self._ask_confirm(
                message="Online audio search failed",
                choices=[
                    {"value": "retry_online_query", "label": "Retry"},
                    {"value": "refine_query", "label": "Type to supplement.", "input": {"placeholder": ""}},
                    {"value": "choose_other_source", "label": "Choose another source"},
                    {"value": "cancel", "label": "Cancel"},
                ],
                tool_args={"query": query, "stage": "online_audio_search_error"},
                tool_name="online_audio_candidate",
            )
            return

        choices = [self._online_audio_candidate_choice(item) for item in self.online_audio_candidates]
        if not choices:
            choices.extend(
                [
                    {"value": "retry_online_query", "label": "Retry"},
                    {"value": "refine_query", "label": "Type to supplement.", "input": {"placeholder": ""}},
                    {"value": "choose_other_source", "label": "Choose another source"},
                    {"value": "cancel", "label": "Cancel"},
                ]
            )
        else:
            choices.append(
                {
                    "value": "refine_query",
                    "label": "Not found? Type to supplement.",
                    "input": {"placeholder": ""},
                }
            )
        if self.online_audio_candidates:
            choices.append({"value": "choose_other_source", "label": "Choose another source"})
        await self._ask_confirm(
            message="Choose an online audio match",
            choices=choices,
            tool_args={"query": query, "stage": "online_audio_candidates"},
            tool_name="online_audio_candidate",
        )

    async def _play_selected_metadata_candidate(self, query: str, playback_metadata: dict[str, Any]) -> None:
        """Prepares play selected metadata candidate for an internal Sonex flow.

        Typical use: Use this helper when nearby code needs play selected metadata candidate without duplicating the local rules.

        Example: await _play_selected_metadata_candidate(query=..., playback_metadata=...) -> returns the value used by the surrounding Sonex flow.
        """
        await self.ui.append_activity(
            kind="tool",
            title="Resolving online audio",
            detail=f"Checking available playable providers for {query}.",
            status="pending",
        )
        metadata = dict(playback_metadata)
        metadata["youtube_query"] = query
        cover_task = asyncio.create_task(
            asyncio.to_thread(resolve_online_playback_metadata, query, metadata)
        )
        audio_task = asyncio.create_task(
            asyncio.to_thread(
                _search_online_audio_for_runner,
                query,
                5,
                playback_metadata=metadata,
            )
        )
        try:
            candidates = await audio_task
        except Exception as exc:
            await self._send_cover_from_task(cover_task)
            result = {
                "status": "fail",
                "tool": "play_online_audio",
                "message": sanitize_error_message(exc),
                "error_code": "ONLINE_AUDIO_RESOLVE_FAILED",
                "data": {"query": query, "provider": "online_audio", "method": "online_play"},
            }
            await self.runner._sync_tool_result_ui(self.ui, "play_online_audio", result)
            message = _friendly_runtime_error_message(result, fallback="Online playback failed.")
            await self.ui.send_error(message)
            await self._finish("Online playback failed.", status="error")
            return

        await self._send_cover_from_task(cover_task)
        self.online_audio_candidates = list(candidates or [])
        agent_handoff = (
            self._on_finish is not None
            and self.selected_playback_metadata is not None
        )
        if agent_handoff:
            unresolved_candidates = list(self.online_audio_candidates)
            selected = RecordingIdentity(
                title=str(
                    self.selected_playback_metadata.get("name")
                    or self.selected_playback_metadata.get("title")
                    or ""
                ),
                artist=str(self.selected_playback_metadata.get("artist") or ""),
                album=str(self.selected_playback_metadata.get("album") or ""),
                duration_ms=_duration_ms_or_none(
                    self.selected_playback_metadata.get("duration_ms")
                ),
            )
            self.online_audio_candidates = [
                item
                for item in self.online_audio_candidates
                if recording_identity_matches(selected, item)
            ]
            if not self.online_audio_candidates and unresolved_candidates:
                alternative = unresolved_candidates[0]
                self.online_audio_candidates = [alternative]
                await self._ask_confirm(
                    message=(
                        "Alternative version: "
                        f"{alternative.get('title') or alternative.get('name') or '-'}"
                        f" — {alternative.get('artist') or '-'} · "
                        f"{alternative.get('provider') or 'community'} · "
                        f"{_duration_text(alternative.get('duration_ms'))}"
                    ),
                    choices=[
                        self._online_audio_candidate_choice(alternative),
                        {"value": "deny", "label": "Not now"},
                    ],
                    tool_args={
                        "query": query,
                        "stage": "alternative_version",
                    },
                    tool_name="online_audio_candidate",
                )
                return
        if not self.online_audio_candidates:
            message = "No valid online audio matches found."
            await self.ui.send_error(message)
            await self._finish("Online playback failed.", status="error")
            return

        candidate = self.online_audio_candidates[0]
        await self._append_source_attempts(candidate.get("source_attempts"))
        assessment = candidate.get("assessment")
        confidence = assessment.get("confidence") if isinstance(assessment, dict) else "high"
        if confidence == "medium" and not agent_handoff:
            choices = [
                self._online_audio_candidate_choice(item)
                for item in self.online_audio_candidates
                if isinstance(item.get("assessment"), dict)
                and item["assessment"].get("confidence") == "medium"
            ]
            choices.append(
                {
                    "value": "refine_query",
                    "label": "Not found? Type to supplement.",
                    "input": {"placeholder": ""},
                }
            )
            await self._ask_confirm(
                message="Choose an online audio match",
                choices=choices,
                tool_args={"query": query, "stage": "online_audio_candidates"},
                tool_name="online_audio_candidate",
            )
            return
        high_confidence_candidates = [
            item
            for item in self.online_audio_candidates
            if not isinstance(item.get("assessment"), dict)
            or item["assessment"].get("confidence") == "high"
        ]
        for index, candidate in enumerate(high_confidence_candidates):
            result = await self._play_online_audio_candidate(
                candidate,
                report_failure=index == len(high_confidence_candidates) - 1,
            )
            data = result.get("data") if isinstance(result, dict) and isinstance(result.get("data"), dict) else {}
            await self._append_source_attempts(data.get("source_attempts"))
            if _is_failed_tool_result(result):
                continue
            if _is_player_confirm_result(result):
                return
            if isinstance(result, dict) and result.get("status") == "success":
                await self.ui.append_system_message(
                    (
                        format_agent_playing_feedback
                        if self._on_finish is not None
                        else format_playing_feedback
                    )(
                        result,
                        self.selected_playback_metadata or {},
                    )
                )
            await self._finish("Online playback selected.")
            return
        await self._finish("Online playback failed.", status="error")

    async def _send_cover_from_task(self, cover_task: asyncio.Task[dict[str, Any]]) -> None:
        """Prepares send cover from task for an internal Sonex flow.

        Typical use: Use this helper when nearby code needs send cover from task without duplicating the local rules.

        Example: await _send_cover_from_task(cover_task=...) -> returns the value used by the surrounding Sonex flow.
        """
        try:
            metadata = await cover_task
        except Exception:
            return
        cover_url = (
            metadata.get("cover_source")
            or metadata.get("album_cover_url")
            or metadata.get("cover_url")
        )
        if cover_url and not _is_youtube_thumbnail(cover_url):
            await self.ui.send_cover(str(cover_url))

    async def _append_source_attempts(self, attempts: Any) -> None:
        """Prepares append source attempts for an internal Sonex flow.

        Typical use: Use this helper when nearby code needs append source attempts without duplicating the local rules.

        Example: await _append_source_attempts(attempts=...) -> returns the value used by the surrounding Sonex flow.
        """
        if not isinstance(attempts, list):
            return
        for attempt in attempts:
            if not isinstance(attempt, dict):
                continue
            provider = str(attempt.get("provider") or "online_audio")
            title = {"jamendo": "Jamendo", "audius": "Audius", "youtube": "YouTube"}.get(provider, provider.title())
            status = str(attempt.get("status") or "")
            activity_status = "success" if status == "success" else "error"
            await self.ui.append_activity(
                kind="tool",
                title=title,
                detail=str(attempt.get("message") or ""),
                status=activity_status,
            )

    async def _append_metadata_attempts(self, attempts: Any) -> None:
        """Prepares append metadata attempts for an internal Sonex flow.

        Typical use: Use this helper when nearby code needs append metadata attempts without duplicating the local rules.

        Example: await _append_metadata_attempts(attempts=...) -> returns the value used by the surrounding Sonex flow.
        """
        if not isinstance(attempts, list):
            return
        for attempt in attempts:
            if not isinstance(attempt, dict):
                continue
            provider = str(attempt.get("provider") or "metadata")
            status = str(attempt.get("status") or "")
            activity_status = "success" if status == "success" else "error"
            await self.ui.append_activity(
                kind="tool",
                title=_metadata_provider_label(provider),
                detail=str(attempt.get("message") or ""),
                status=activity_status,
            )

    def _online_audio_candidate_choice(self, candidate: dict[str, Any]) -> dict[str, Any]:
        """Prepares online audio candidate choice for an internal Sonex flow.

        Typical use: Use this helper when nearby code needs online audio candidate choice without duplicating the local rules.

        Example: _online_audio_candidate_choice(candidate=...) -> returns the value used by the surrounding Sonex flow.
        """
        name = str(candidate.get("name") or candidate.get("title") or "-")
        artist = str(candidate.get("artist") or "-")
        duration = _duration_text(candidate.get("duration_ms"))
        cached = "cached" if candidate.get("cached") else "not cached"
        provider = str(candidate.get("provider") or "online")
        if provider == "youtube" and candidate.get("fallback_provider") == "youtube":
            parts = ["YouTube fallback"]
            fallback_reason = str(candidate.get("fallback_reason") or "").strip()
            if fallback_reason:
                parts.append(fallback_reason)
        else:
            parts = [provider]
        variant_label = _youtube_variant_label(candidate.get("variant_type"))
        if variant_label:
            parts.append(variant_label)
        views = _compact_count(candidate.get("raw_view_count"))
        if views:
            parts.append(f"{views} views")
        assessment = candidate.get("assessment")
        if isinstance(assessment, dict) and assessment.get("confidence") == "medium":
            parts.append("Needs confirmation")
        parts.extend([duration, cached])
        return {
            "value": f"youtube_candidate:{candidate.get('cache_id')}",
            "label": f"{name} - {artist}",
            "description": " · ".join(parts),
        }

    async def _ask_confirm(
        self,
        *,
        message: str,
        choices: list[dict[str, Any]],
        tool_args: dict[str, Any],
        tool_name: str = "playback_choice",
    ) -> None:
        """Prepares ask confirm for an internal Sonex flow.

        Typical use: Use this helper when nearby code needs ask confirm without duplicating the local rules.

        Example: await _ask_confirm(message=..., choices=..., tool_args=..., tool_name=...) -> returns the value used by the surrounding Sonex flow.
        """
        confirm_id = _new_event_id("confirm")
        self.active_confirm_id = confirm_id
        await self.ui.append_activity(
            kind="confirm",
            title="Playback choice",
            detail=message,
            status="pending",
            activity_id=confirm_id,
        )
        await self.ui.ask_confirm(
            {
                "type": "confirm",
                "id": confirm_id,
                "tool_name": tool_name,
                "tool_args": tool_args,
                "message": message,
                "choices": choices,
            }
        )

    async def _invoke_playback(
        self,
        tool_name: str,
        args: dict[str, Any],
        *,
        cache_provider: str | None = None,
        pending_detail: str | None = None,
    ) -> dict[str, Any]:
        """Prepares invoke playback for an internal Sonex flow.

        Typical use: Use this helper when nearby code needs invoke playback without duplicating the local rules.

        Example: await _invoke_playback(tool_name=..., args=..., cache_provider=..., pending_detail=...) -> returns the value used by the surrounding Sonex flow.
        """
        if pending_detail:
            await self.ui.append_activity(
                kind="tool",
                title=f"Calling {tool_name}",
                detail=pending_detail,
                status="pending",
            )
        try:
            result = await asyncio.to_thread(registry.invoke_system, tool_name, args)
        except Exception as exc:
            result = {
                "status": "fail",
                "tool": tool_name,
                "message": sanitize_error_message(exc),
                "error_code": "PLAYBACK_FAILED",
                "data": args,
            }
        await self.runner._sync_tool_result_ui(self.ui, tool_name, result)
        if _is_player_confirm_result(result):
            await self._ask_player_confirm(result)
            return result
        if _is_failed_tool_result(result):
            message = _friendly_runtime_error_message(result, fallback="Playback failed.")
            await self.ui.send_error(message)
        if isinstance(result, dict) and result.get("status") == "success":
            data = dict(result.get("data") or {})
            if cache_provider:
                data.setdefault("provider", cache_provider)
            try:
                await asyncio.to_thread(upsert_cached_song, data)
            except Exception:
                pass
        return result

    async def _play_online_audio_candidate(
        self,
        candidate: dict[str, Any],
        *,
        report_failure: bool = True,
    ) -> dict[str, Any]:
        """Prepares play online audio candidate for an internal Sonex flow.

        Typical use: Use this helper when nearby code needs play online audio candidate without duplicating the local rules.

        Example: await _play_online_audio_candidate(candidate=...) -> returns the value used by the surrounding Sonex flow.
        """
        await self.ui.append_activity(
            kind="tool",
            title="Caching online audio",
            detail="Downloading selected audio before local playback.",
            status="pending",
        )
        try:
            result = await asyncio.to_thread(_play_online_audio_for_runner, candidate, player="auto")
        except Exception as exc:
            result = {
                "status": "fail",
                "tool": "play_online_audio",
                "message": sanitize_error_message(exc),
                "error_code": "PLAYBACK_FAILED",
                "data": candidate,
            }
        await self.runner._sync_tool_result_ui(self.ui, "play_online_audio", result)
        if _is_player_confirm_result(result):
            await self._ask_player_confirm(result)
            return result
        if _is_failed_tool_result(result) and report_failure:
            message = _friendly_runtime_error_message(result, fallback="Playback failed.")
            await self.ui.send_error(message)
        if isinstance(result, dict) and result.get("status") == "success":
            await self.runner._handoff_previous_provider(self.ui, "online")
            setattr(self.ui, "_active_playback_provider", "online")
            try:
                await asyncio.to_thread(upsert_cached_song, dict(result.get("data") or {}))
            except Exception:
                pass
        return result

    async def _ask_player_confirm(self, result: dict[str, Any]) -> None:
        """Prepares ask player confirm for an internal Sonex flow.

        Typical use: Use this helper when nearby code needs ask player confirm without duplicating the local rules.

        Example: await _ask_player_confirm(result=...) -> returns the value used by the surrounding Sonex flow.
        """
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        self.pending_player_confirm_result = result
        await self._ask_confirm(
            message=str(data.get("confirm_message") or result.get("message") or "Confirm player launch."),
            choices=data.get("choices") if isinstance(data.get("choices"), list) else [],
            tool_args={
                "query": self.query,
                "stage": "player_confirm",
                "tool": result.get("tool"),
                "player": data.get("player"),
                "player_label": data.get("player_label"),
            },
            tool_name=str(result.get("tool") or "player"),
        )

    async def _complete_player_confirmation(self, decision: Any) -> None:
        """Prepares complete player confirmation for an internal Sonex flow.

        Typical use: Use this helper when nearby code needs complete player confirmation without duplicating the local rules.

        Example: await _complete_player_confirmation(decision=...) -> returns the value used by the surrounding Sonex flow.
        """
        pending = self.pending_player_confirm_result
        self.pending_player_confirm_result = None
        if not pending:
            await self._finish("Player confirmation expired.", status="error")
            return
        tool_name = str(pending.get("tool") or "player")
        result = await asyncio.to_thread(complete_player_confirm, pending, decision)
        await self.runner._sync_tool_result_ui(self.ui, tool_name, result)
        if _is_failed_tool_result(result):
            message = _friendly_runtime_error_message(result, fallback="Playback failed.")
            await self.ui.send_error(message)
            await self._finish("Playback failed.", status="error")
            return
        if isinstance(result, dict) and result.get("status") == "success":
            provider = "online" if tool_name == "play_online_audio" else "local" if tool_name == "play_local_song" else None
            if provider is not None:
                await self.runner._handoff_previous_provider(self.ui, provider)
                setattr(self.ui, "_active_playback_provider", provider)
            try:
                await asyncio.to_thread(upsert_cached_song, dict(result.get("data") or {}))
            except Exception:
                pass
        if (
            isinstance(result, dict)
            and result.get("status") == "success"
            and self.selected_playback_metadata is not None
        ):
            data = result.get("data")
            result_data = data if isinstance(data, dict) else {}
            selected_player = result_data.get("player") or decision
            if self._on_finish is None:
                await self.ui.append_agent_message(
                    format_player_feedback(selected_player)
                )
            await self.ui.append_system_message(
                (
                    format_agent_playing_feedback
                    if self._on_finish is not None
                    else format_playing_feedback
                )(
                    result,
                    self.selected_playback_metadata,
                )
            )
        await self._finish("Online playback selected.")

    async def _finish(self, detail: str, *, status: str = "success") -> None:
        """Prepares finish for an internal Sonex flow.

        Typical use: Use this helper when nearby code needs finish without duplicating the local rules.

        Example: await _finish(detail=..., status=...) -> returns the value used by the surrounding Sonex flow.
        """
        setattr(self.ui, "_play_selection", None)
        if status == "success" and self.playback_source:
            setattr(self.ui, "_preferred_playback_provider", self.playback_source)
        await self.ui.append_activity(kind="status", title="Playback selection", detail=detail, status=status)
        if self._finished:
            return
        self._finished = True
        if self._on_finish is not None:
            self._on_finish(
                {
                    "status": (
                        "playback_completed"
                        if status == "success"
                        else "playback_cancelled"
                        if "cancel" in detail.casefold()
                        else "playback_failed"
                    ),
                    "message": detail,
                    "error_code": None,
                    "data": {},
                }
            )


class AgentPlaybackRouteConfirmationSession:
    """Own one temporary provider or community-source confirmation."""

    def __init__(
        self,
        ui: WebSocketUIAdapter,
        *,
        message: str,
        stage: str,
        provider: str,
    ) -> None:
        self.ui = ui
        self.message = message
        self.stage = stage
        self.provider = provider
        self.confirm_id = _new_event_id("agent_playback_route")
        self.result: asyncio.Future[bool] = asyncio.get_running_loop().create_future()

    async def start(self) -> bool:
        await self.ui.append_activity(
            kind="confirm",
            title="Playback route",
            detail=self.message,
            status="pending",
            activity_id=self.confirm_id,
        )
        await self.ui.ask_confirm(
            {
                "id": self.confirm_id,
                "tool_name": "playback_provider",
                "tool_args": {
                    "stage": self.stage,
                    "provider": self.provider,
                },
                "message": self.message,
                "choices": [
                    {"value": "allow_once", "label": "Continue"},
                    {"value": "deny", "label": "Not now"},
                ],
            }
        )
        return await self.result

    def owns_confirm(self, confirm_id: str) -> bool:
        return confirm_id == self.confirm_id

    async def handle_choice(self, decision: Any) -> None:
        allowed = str(decision or "deny") not in {"deny", "cancel", "false"}
        if getattr(self.ui, "_agent_playback_route_confirmation", None) is self:
            setattr(self.ui, "_agent_playback_route_confirmation", None)
        await self.ui.append_activity(
            kind="confirm",
            title="Playback route",
            detail="Confirmed." if allowed else "Rejected.",
            status="success" if allowed else "error",
            activity_id=self.confirm_id,
        )
        if not self.result.done():
            self.result.set_result(allowed)


class PlaybackSourceSelectionSession:
    """Choose the catalog that owns the next single-song search."""

    SOURCE_LABELS = {
        "netease": ("NetEase", "ncm-cli / mpv"),
        "spotify": ("Spotify", "Spotify Connect"),
        "online": ("Online", "Jamendo / Audius / YouTube"),
    }

    def __init__(
        self,
        ui: WebSocketUIAdapter,
        sources: list[str],
        *,
        exclude: str | None = None,
    ) -> None:
        self.ui = ui
        self.sources = [source for source in sources if source in self.SOURCE_LABELS]
        self.exclude = exclude
        self.confirm_id = _new_event_id("playback_source")
        self.result: asyncio.Future[str | None] = asyncio.get_running_loop().create_future()

    async def start(self) -> None:
        choices = []
        for source in self.sources:
            label, description = self.SOURCE_LABELS[source]
            choices.append(
                {
                    "value": f"playback_source:{source}",
                    "label": label,
                    "description": description,
                }
            )
        choices.append({"value": "cancel", "label": "Cancel"})
        await self.ui.append_activity(
            kind="confirm",
            title="Playback source",
            detail="Choose the source for this song search.",
            status="pending",
            activity_id=self.confirm_id,
        )
        await self.ui.ask_confirm(
            {
                "id": self.confirm_id,
                "tool_name": "playback_source",
                "tool_args": {
                    "stage": "playback_source",
                    "exclude": self.exclude,
                },
                "message": "Choose playback source",
                "choices": choices,
            }
        )

    def owns_confirm(self, confirm_id: str) -> bool:
        return confirm_id == self.confirm_id

    async def handle_choice(self, decision: Any) -> None:
        value = str(decision or "cancel")
        source = value.removeprefix("playback_source:").strip().casefold()
        if value in {"cancel", "deny", "false"} or source not in self.sources:
            source = None
        if getattr(self.ui, "_playback_source_selection", None) is self:
            setattr(self.ui, "_playback_source_selection", None)
        await self.ui.append_activity(
            kind="status",
            title="Playback source",
            detail=(
                f"{self.SOURCE_LABELS[source][0]} selected."
                if source
                else "Playback source selection canceled."
            ),
            status="success" if source else "error",
            activity_id=self.confirm_id,
        )
        if not self.result.done():
            self.result.set_result(source)


class NetEaseLoginOfferSession:
    """Ask whether an unlogged ncm-cli route should scan or yield."""

    def __init__(self, ui: WebSocketUIAdapter, *, fallback_online: bool) -> None:
        self.ui = ui
        self.fallback_online = fallback_online
        self.confirm_id = _new_event_id("netease_login_offer")
        self.result: asyncio.Future[str] = asyncio.get_running_loop().create_future()

    async def start(self) -> str:
        await self.ui.ask_confirm(
            {
                "id": self.confirm_id,
                "tool_name": "netease_login",
                "tool_args": {
                    "stage": "netease_login_offer",
                    "fallback_online": self.fallback_online,
                },
                "message": "NetEase is configured but not signed in.",
                "choices": [
                    {"value": "scan", "label": "Scan to connect NetEase"},
                    {
                        "value": "online" if self.fallback_online else "deny",
                        "label": "Play online" if self.fallback_online else "Cancel",
                    },
                ],
            }
        )
        return await self.result

    def owns_confirm(self, confirm_id: str) -> bool:
        return confirm_id == self.confirm_id

    async def handle_choice(self, decision: Any) -> None:
        value = str(decision or "deny").casefold()
        outcome = "scan" if value == "scan" else "online" if self.fallback_online else "cancel"
        if getattr(self.ui, "_netease_login_offer", None) is self:
            setattr(self.ui, "_netease_login_offer", None)
        if not self.result.done():
            self.result.set_result(outcome)


class NetEaseLoginSession:
    """Own one cancellable ncm-cli QR login subprocess and UI surface."""

    def __init__(
        self,
        ui: WebSocketUIAdapter,
        worker: NetEaseProviderWorker,
        *,
        on_completed: Callable[[dict[str, Any]], None] | None,
        fallback_online: bool,
        emit_feedback: bool,
    ) -> None:
        self.ui = ui
        self.worker = worker
        self.on_completed = on_completed
        self.fallback_online = fallback_online
        self.emit_feedback = emit_feedback
        self.cancel_event = threading.Event()
        self.task: asyncio.Task[None] | None = None
        self.result: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._output = ""
        self._done = False

    async def start(self) -> None:
        await self.ui.send_netease_login(
            title="Connect NetEase",
            output="Starting ncm-cli login...",
            status="waiting",
            active=True,
            fallback_online=self.fallback_online,
        )
        self.task = asyncio.create_task(self._run())

    async def cancel(self) -> None:
        if self._done:
            return
        self.cancel_event.set()
        self.worker.terminate_active()

    def _receive_output(self, output: str) -> None:
        loop = self.result.get_loop()
        loop.call_soon_threadsafe(
            lambda: asyncio.create_task(self._publish_output(output))
        )

    async def _publish_output(self, output: str) -> None:
        if self._done:
            return
        self._output = output
        await self.ui.send_netease_login(
            title="Connect NetEase",
            output=output,
            status="waiting",
            active=True,
            fallback_online=self.fallback_online,
        )

    async def _run(self) -> None:
        try:
            login = await asyncio.to_thread(
                self.worker.login,
                on_output=self._receive_output,
                cancel_event=self.cancel_event,
            )
        except Exception as exc:
            status = "failed"
            reason = sanitize_error_message(exc)
            output = self._output
        else:
            status = login.status
            reason = login.reason
            output = login.output or self._output
        if status == "success":
            try:
                health = await asyncio.to_thread(self.worker.health)
            except Exception as exc:
                health = None
                reason = sanitize_error_message(exc)
            if health is None or not health.ready:
                status = "failed"
                reason = reason or (health.reason if health is not None else None) or "NetEase login could not be verified."
        result = {
            "status": "connected" if status == "success" else status,
            "tool": "Connect",
            "message": (
                "NetEase connected · Ready, unverified playback."
                if status == "success"
                else reason or "NetEase login was cancelled."
            ),
            "data": {
                "provider": "netease",
                "reason": reason or status,
                "account_label": "ncm-cli" if status == "success" else None,
                "verification": "unverified_playback" if status == "success" else None,
            },
            "error_code": None if status in {"success", "cancelled"} else "CONNECTION_NOT_READY",
        }
        self._done = True
        if getattr(self.ui, "_netease_login_session", None) is self:
            setattr(self.ui, "_netease_login_session", None)
        await self.ui.send_netease_login(
            title="Connect NetEase",
            output=output,
            status=status,
            active=False,
            fallback_online=self.fallback_online,
        )
        if self.emit_feedback and status == "success":
            await self.ui.append_activity(
                kind="status",
                title="NetEase connection",
                detail=str(result["message"]),
                status="success",
            )
            await self.ui.append_system_message(str(result["message"]))
        if not self.result.done():
            self.result.set_result(result)
        if self.on_completed is not None:
            self.on_completed(result)


class AgentCandidateSelectionSession:
    """Suspend an Agent turn while the user chooses one safe track reference."""

    def __init__(
        self,
        ui: WebSocketUIAdapter,
        runner: "WebSocketRunner",
        query: str,
        *,
        interaction_id: str,
        turn_id: str,
        requested_provider: str | None,
        hard_provider: bool,
        complete: Callable[[dict[str, Any]], None],
        timeout_seconds: float = 60.0,
    ) -> None:
        self.ui = ui
        self.runner = runner
        self.query = query.strip()
        self.interaction_id = interaction_id
        self.turn_id = turn_id
        self.requested_provider = requested_provider
        self.hard_provider = hard_provider
        self.complete = complete
        self.timeout_seconds = timeout_seconds
        self.confirm_id = _new_event_id("agent_candidate")
        self.candidates: list[dict[str, Any]] = []
        self.playback_source: str | None = None
        self._done = False
        self._timeout_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        local_path = await asyncio.to_thread(search_local_file, self.query)
        if _is_local_search_hit(local_path):
            self.candidates.append(
                {
                    "provider": "local",
                    "name": Path(local_path).stem,
                    "artist": "Local file",
                    "album": str(Path(local_path).parent.name),
                    "ref": remember_local_track(local_path),
                    "playback_path": local_path,
                }
            )
        self.playback_source = await self.runner._select_playback_source(
            self.ui,
            requested_provider=self.requested_provider,
            hard_provider=self.hard_provider,
        )
        if self.playback_source is None:
            await self._complete(
                {
                    "status": "cancelled",
                    "tool": "Call",
                    "message": "Playback source selection was cancelled.",
                    "data": {"workflow": "playback.select", "reason": "source_cancelled", "query": self.query},
                    "error_code": None,
                }
            )
            return
        try:
            if self.playback_source in {"netease", "spotify"}:
                raw_candidates = await self.runner._search_authoritative_candidates(
                    self.ui,
                    self.playback_source,
                    self.query,
                )
                result = {"candidates": raw_candidates}
            else:
                result = await asyncio.to_thread(
                    search_track_metadata_candidates,
                    self.query,
                    5,
                )
        except Exception as exc:
            result = {
                "candidates": [],
                "source_attempts": [
                    {
                        "provider": "metadata",
                        "status": "error",
                        "message": sanitize_error_message(exc),
                    }
                ],
            }
        raw_candidates = result.get("candidates") if isinstance(result, dict) else result
        if isinstance(raw_candidates, list):
            self.candidates.extend(
                dict(candidate)
                for candidate in raw_candidates[:5]
                if isinstance(candidate, dict)
            )
        for candidate in self.candidates:
            candidate.setdefault("playback_source", self.playback_source)
        if not self.candidates:
            await self._complete(
                {
                    "status": "cancelled",
                    "tool": "Call",
                    "message": "No playback candidates were found.",
                    "data": {
                        "workflow": "playback.select",
                        "reason": "no_candidates",
                        "query": self.query,
                    },
                    "error_code": None,
                }
            )
            return
        choices = [
            {
                "value": f"agent_candidate:{index}",
                "label": format_music_candidate_label(
                    candidate.get("artist"),
                    candidate.get("album"),
                    candidate.get("name") or candidate.get("title"),
                ),
                "display": music_candidate_display(
                    candidate.get("artist"),
                    candidate.get("album"),
                    candidate.get("name") or candidate.get("title"),
                ),
                "description": _metadata_provider_label(
                    str(
                        candidate.get("provider")
                        or candidate.get("metadata_source")
                        or "metadata"
                    )
                ),
            }
            for index, candidate in enumerate(self.candidates)
        ]
        await self.ui.append_activity(
            kind="confirm",
            title="Playback selection",
            detail="Select a track for the Agent.",
            status="pending",
            activity_id=self.confirm_id,
        )
        await self.ui.ask_confirm(
            {
                "type": "confirm",
                "id": self.confirm_id,
                "tool_name": "song_candidate",
                "tool_args": {
                    "query": self.query,
                    "workflow": "playback.select",
                    "interaction_id": self.interaction_id,
                    "provider": self.playback_source,
                },
                "message": "Select the version",
                "choices": choices,
            }
        )
        self._timeout_task = asyncio.create_task(self._timeout())

    def owns_confirm(self, confirm_id: str) -> bool:
        return confirm_id == self.confirm_id

    async def handle_choice(self, decision: Any) -> None:
        value = str(decision or "deny")
        if value in {"deny", "cancel", "false"}:
            await self._complete(
                {
                    "status": "cancelled",
                    "tool": "Call",
                    "message": "Playback selection was cancelled.",
                    "data": {
                        "workflow": "playback.select",
                        "reason": "user_cancelled",
                        "query": self.query,
                    },
                    "error_code": None,
                }
            )
            return
        if not value.startswith("agent_candidate:"):
            await self._complete(
                {
                    "status": "cancelled",
                    "tool": "Call",
                    "message": "Playback selection returned an invalid choice.",
                    "data": {
                        "workflow": "playback.select",
                        "reason": "invalid_choice",
                        "query": self.query,
                    },
                    "error_code": None,
                }
            )
            return
        try:
            candidate = self.candidates[int(value.partition(":")[2])]
        except (ValueError, IndexError):
            candidate = {}
        if not candidate:
            await self.handle_choice("deny")
            return
        provider = str(
            candidate.get("provider")
            or candidate.get("metadata_source")
            or "metadata"
        )
        ref = str(candidate.get("ref") or candidate.get("uri") or candidate.get("id") or "")
        if ref and not ref.startswith(f"{provider}:"):
            ref = f"{provider}:ref:{ref}"
        metadata = {
            "provider": provider,
            "playback_source": candidate.get("playback_source") or self.playback_source,
            "ref": ref or None,
            "title": candidate.get("name") or candidate.get("title"),
            "artist": candidate.get("artist"),
            "artists": candidate.get("artists"),
            "album": candidate.get("album"),
            "duration_ms": candidate.get("duration_ms"),
            "encrypted_id": candidate.get("encrypted_id"),
            "original_id": candidate.get("original_id"),
            "uri": candidate.get("uri"),
            "native_source": candidate.get("native_source"),
        }
        self._done = True
        if self._timeout_task is not None:
            self._timeout_task.cancel()
        if getattr(self.ui, "_agent_candidate_selection", None) is self:
            setattr(self.ui, "_agent_candidate_selection", None)
        await self.ui.append_activity(
            kind="status",
            title="Playback selection",
            detail="Playback candidate selected.",
            status="success",
            activity_id=self.confirm_id,
        )
        await self.ui.append_system_message(format_agent_selection_feedback(candidate))
        identity = RecordingIdentity(
            title=str(metadata.get("title") or ""),
            artist=str(metadata.get("artist") or ""),
            album=str(metadata.get("album") or ""),
            duration_ms=_duration_ms_or_none(metadata.get("duration_ms")),
            metadata_source=provider,
        )
        selection_ref = self.runner._playback_coordinator.selections.issue(
            session_id=self.ui.session_id,
            turn_id=self.turn_id,
            identity=identity,
        )

        async def commit_selection() -> None:
            current_task = asyncio.current_task()
            setattr(self.ui, "_active_agent_provider_task", current_task)
            try:
                result = await self.runner._commit_agent_playback_selection(
                    self.ui,
                    selection_ref=selection_ref,
                    turn_id=self.turn_id,
                    query=self.query,
                    candidate=candidate,
                    requested_provider=self.requested_provider,
                    hard_provider=self.hard_provider,
                )
            except asyncio.CancelledError:
                result = {
                    "status": "playback_cancelled",
                    "message": "Playback interrupted.",
                    "data": {"reason": "user_interrupted"},
                    "error_code": None,
                }
            finally:
                if getattr(self.ui, "_active_agent_provider_task", None) is current_task:
                    setattr(self.ui, "_active_agent_provider_task", None)
            self.complete(result)

        task = asyncio.create_task(commit_selection())
        setattr(self.ui, "_active_agent_provider_task", task)

    async def _timeout(self) -> None:
        await asyncio.sleep(self.timeout_seconds)
        await self._complete(
            {
                "status": "cancelled",
                "tool": "Call",
                "message": "Playback selection timed out.",
                "data": {
                    "workflow": "playback.select",
                    "reason": "timeout",
                    "query": self.query,
                },
                "error_code": None,
            }
        )

    async def _complete(self, result: dict[str, Any]) -> None:
        if self._done:
            return
        self._done = True
        if self._timeout_task is not None and self._timeout_task is not asyncio.current_task():
            self._timeout_task.cancel()
        if getattr(self.ui, "_agent_candidate_selection", None) is self:
            setattr(self.ui, "_agent_candidate_selection", None)
        cancelled = result.get("status") == "cancelled"
        status = "error" if cancelled else "success"
        await self.ui.append_activity(
            kind="status",
            title="Playback selection",
            detail=str(result.get("message") or ""),
            status=status,
            activity_id=self.confirm_id,
        )
        if cancelled:
            result = {
                **result,
                "status": "playback_cancelled",
            }
        self.complete(result)


class PlaylistSaveSession:
    """Owns the playlist target picker for saving the current playback snapshot."""

    def __init__(self, ui: WebSocketUIAdapter, track: dict[str, Any]) -> None:
        self.ui = ui
        self.track = track
        self.confirm_id = _new_event_id("playlist_save")

    async def start(self, requested_playlist: str = "") -> None:
        target = requested_playlist.strip()
        if target:
            await self._save(target)
            return
        try:
            choices = playlist_choices()
        except Exception:
            choices = []
        if not choices:
            choices = [{"value": f"playlist:{LIKES_PLAYLIST}", "label": LIKES_PLAYLIST, "description": "0 saved tracks"}]
        await self.ui.ask_confirm(
            {
                "id": self.confirm_id,
                "tool_name": "playlist_save",
                "tool_args": {"track": self.track.get("name") or self.track.get("title") or "-", "default": LIKES_PLAYLIST},
                "message": "Save current song to playlist",
                "choices": choices,
            }
        )

    def owns_confirm(self, confirm_id: str) -> bool:
        return confirm_id == self.confirm_id

    async def handle_choice(self, decision: Any) -> None:
        value = str(decision or "")
        if value in {"deny", "cancel", "false"}:
            setattr(self.ui, "_playlist_save", None)
            await self.ui.append_activity(kind="status", title="Playlist save", detail="Canceled.", status="success")
            return
        playlist_name = value.removeprefix("playlist:").strip() or LIKES_PLAYLIST
        await self._save(playlist_name)

    async def _save(self, playlist_name: str) -> None:
        try:
            result = save_track_to_playlist(self.track, playlist_name=playlist_name or LIKES_PLAYLIST)
        except Exception as exc:
            message = sanitize_error_message(exc)
            await self.ui.append_activity(kind="error", title="Playlist save failed", detail=message, status="error")
            await self.ui.append_system_message(message)
            setattr(self.ui, "_playlist_save", None)
            return
        name = str(result.get("playlist", {}).get("name") or playlist_name or LIKES_PLAYLIST)
        added = bool(result.get("added"))
        message = f"Saved to {name}." if added else f"Already saved in {name}."
        player_state = _decorate_player_state(self.track)
        setattr(self.ui, "_last_player_state", player_state)
        await self.ui._send({"type": "player", "state": player_state})
        await self.ui.append_system_message(message)
        await self.ui.append_activity(kind="status", title="Playlist save", detail=message, status="success")
        await self.ui._send(_track_panel_payload("playlist", f"Playlist: {name}", playlist_panel_tracks(name)))
        setattr(self.ui, "_playlist_save", None)


class PlaylistBrowseSession:
    """Owns the local playlist browser for Sonex and imported read-only mirrors."""

    def __init__(self, ui: WebSocketUIAdapter, choices: list[dict[str, Any]]) -> None:
        self.ui = ui
        self.choices = choices
        self.confirm_id = _new_event_id("playlist_browse")

    async def start(self) -> None:
        await self.ui.append_activity(
            kind="confirm",
            title="Playlists",
            detail="Choose a playlist.",
            status="pending",
            activity_id=self.confirm_id,
        )
        await self.ui.ask_confirm(
            {
                "id": self.confirm_id,
                "tool_name": "playlist_browse",
                "tool_args": {"stage": "playlist_choice"},
                "message": "Choose playlist",
                "choices": self.choices,
            }
        )

    def owns_confirm(self, confirm_id: str) -> bool:
        return confirm_id == self.confirm_id

    async def handle_choice(self, decision: Any) -> None:
        setattr(self.ui, "_playlist_browse", None)
        value = str(decision or "cancel")
        if value in {"cancel", "deny", "false"}:
            await self.ui.append_activity(kind="status", title="Playlists", detail="Playlist browsing canceled.", status="success")
            return
        choice = next((item for item in self.choices if str(item.get("value") or "") == value), None)
        if not choice:
            await self.ui.append_activity(kind="error", title="Playlists", detail="Selected playlist is no longer available.", status="error")
            return
        name = str(choice.get("name") or choice.get("label") or LIKES_PLAYLIST)
        source = str(choice.get("source_app") or "Sonex")
        external_id = str(choice.get("external_id") or "") or None
        label = str(choice.get("label") or name)
        title = f"Playlist: {label}"
        await self.ui._send(
            _track_panel_payload(
                "playlist",
                title,
                playlist_panel_tracks(name, source_app=source, external_id=external_id),
            )
        )
        await self.ui.append_activity(kind="status", title="Playlist", detail=f"Showing playlist: {label}.", status="success")


SPOTIFY_MODE_REQUIRED_SCOPES = {
    "user-read-private",
    "user-read-playback-state",
    "user-modify-playback-state",
    "playlist-read-private",
    "playlist-read-collaborative",
    "user-library-read",
}

SPOTIFY_MODE_COMMANDS = {"bye", "connect", "exit", "info", "lang", "login", "logout", "memory", "model", "playlist", "queue", "random", "recommend", "sandbox", "spotify"}
SPOTIFY_MODE_CALL_TIMEOUT_SECONDS = 12.0
SPOTIFY_PLAYBACK_ACTIVE_POLL_SECONDS = 5.0
SPOTIFY_PLAYBACK_IDLE_POLL_SECONDS = 15.0
LOCAL_PLAYBACK_POLL_SECONDS = 1.0
SPOTIFY_SEARCH_CACHE_TTL_SECONDS = 120.0
SPOTIFY_QUEUE_CACHE_TTL_SECONDS = 5.0
SPOTIFY_RECENT_CACHE_TTL_SECONDS = 300.0
SPOTIFY_MODE_STATE_VERSION = 1


async def _send_provider_mode(
    ui: WebSocketUIAdapter,
    provider: ProviderMode,
    *,
    storefront: str | None = None,
    connection_status: str | None = None,
) -> None:
    await ui._send(
        {
            "type": "provider_mode",
            "provider": provider.value,
            "enabled": provider is not ProviderMode.NORMAL,
            "storefront": storefront,
            "connection_status": connection_status or ("ready" if provider is not ProviderMode.NORMAL else "off"),
        }
    )


@dataclass
class _SpotifyCacheEntry:
    """Stores one successful session response and its monotonic expiry."""

    value: Any
    expires_at: float


@dataclass
class SpotifySessionRequestCoordinator:
    """Coordinates cached and single-flight Spotify reads for one UI session."""

    cache: OrderedDict[str, _SpotifyCacheEntry] = field(default_factory=OrderedDict)
    inflight: dict[str, asyncio.Task[Any]] = field(default_factory=dict)
    playlist_sync_attempted: bool = False
    playlist_sync_succeeded: bool = False
    playlist_sync_message: str = "Spotify playlists have not been synchronized in this session."
    playlist_sync_task: asyncio.Task[tuple[bool, str]] | None = None

    async def get_or_fetch(
        self,
        key: str,
        *,
        ttl_seconds: float,
        fetch: Any,
        cacheable: Any,
    ) -> tuple[Any | None, str]:
        """Return a fresh/stale cached value or coalesce one remote fetch."""
        now = time.monotonic()
        entry = self.cache.get(key)
        if entry is not None and entry.expires_at > now:
            self.cache.move_to_end(key)
            return entry.value, "cache_hit"

        if spotify_api_cooldown_remaining() > 0:
            if entry is not None:
                self.cache.move_to_end(key)
                return entry.value, "stale_cache"
            return None, "cooldown"

        task = self.inflight.get(key)
        source = "single_flight"
        if task is None:
            task = asyncio.create_task(fetch())
            self.inflight[key] = task
            source = "network"
        try:
            value = await asyncio.shield(task)
        finally:
            if task.done() and self.inflight.get(key) is task:
                self.inflight.pop(key, None)

        if cacheable(value):
            self.cache[key] = _SpotifyCacheEntry(
                value=value,
                expires_at=time.monotonic() + max(0.0, ttl_seconds),
            )
            self.cache.move_to_end(key)
            self._trim_search_cache()
        return value, source

    def invalidate(self, key: str) -> None:
        """Invalidate a session read after a related Spotify write."""
        self.cache.pop(key, None)

    def _trim_search_cache(self) -> None:
        search_keys = [key for key in self.cache if key.startswith("search:")]
        while len(search_keys) > 32:
            oldest = search_keys.pop(0)
            self.cache.pop(oldest, None)


def _spotify_session_requests(ui: WebSocketUIAdapter) -> SpotifySessionRequestCoordinator:
    coordinator = getattr(ui, "_spotify_session_requests", None)
    if not isinstance(coordinator, SpotifySessionRequestCoordinator):
        coordinator = SpotifySessionRequestCoordinator()
        setattr(ui, "_spotify_session_requests", coordinator)
    return coordinator


def _spotify_sync_event(ui: WebSocketUIAdapter) -> asyncio.Event:
    event = getattr(ui, "_spotify_sync_event", None)
    if not isinstance(event, asyncio.Event):
        event = asyncio.Event()
        setattr(ui, "_spotify_sync_event", event)
    return event


def _request_spotify_sync(ui: WebSocketUIAdapter) -> None:
    """Wake the adaptive playback synchronizer after a Spotify state change."""
    _spotify_sync_event(ui).set()


async def _wait_for_local_playback_sync(_ui: WebSocketUIAdapter, timeout_seconds: float) -> None:
    """Wait until the next local-player status sample."""
    await asyncio.sleep(max(0.0, timeout_seconds))


async def _wait_for_spotify_sync(ui: WebSocketUIAdapter, timeout_seconds: float) -> None:
    """Wait for a requested sync or the next adaptive polling deadline."""
    event = _spotify_sync_event(ui)
    try:
        await asyncio.wait_for(event.wait(), timeout=max(0.0, timeout_seconds))
    except TimeoutError:
        pass
    finally:
        event.clear()


def _spotify_search_cache_key(query: str) -> str:
    normalized = " ".join(query.strip().casefold().split())
    return f"search:{normalized}"


def _spotify_success_result(value: Any) -> bool:
    return isinstance(value, dict) and value.get("status") == "success"


def _spotify_mode_path() -> Path:
    return sonex_home() / "spotify-mode.json"


def _spotify_token_expired(token: Any) -> bool:
    expires_at = getattr(token, "expires_at", None)
    if not expires_at:
        return False
    try:
        expires = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
    except ValueError:
        return True
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    return expires.timestamp() <= time.time() + 60


def _clear_persistent_spotify_mode() -> None:
    try:
        _spotify_mode_path().unlink()
    except FileNotFoundError:
        return
    except OSError:
        return


def _spotify_mode_state(device: dict[str, Any], scopes: set[str] | list[str] | None = None) -> dict[str, Any]:
    token = load_spotify_token()
    token_scopes = set(getattr(token, "scopes", []) or []) if token else set()
    mode_scopes = sorted(set(scopes or token_scopes))
    now = _timestamp_ms()
    return {
        "version": SPOTIFY_MODE_STATE_VERSION,
        "enabled": True,
        "device_id": device.get("id"),
        "device_name": device.get("name"),
        "entered_at": now,
        "updated_at": now,
        "token_expires_at": getattr(token, "expires_at", None) if token else None,
        "scopes": mode_scopes,
    }


def _persist_spotify_mode(mode: dict[str, Any]) -> None:
    if not mode.get("enabled"):
        _clear_persistent_spotify_mode()
        return
    payload = {
        "version": SPOTIFY_MODE_STATE_VERSION,
        "enabled": True,
        "device_id": mode.get("device_id"),
        "device_name": mode.get("device_name"),
        "entered_at": mode.get("entered_at"),
        "updated_at": _timestamp_ms(),
        "token_expires_at": mode.get("token_expires_at"),
        "scopes": sorted(str(scope) for scope in (mode.get("scopes") or []) if str(scope).strip()),
    }
    try:
        path = _spotify_mode_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)
    except OSError:
        return


def _load_persistent_spotify_mode() -> dict[str, Any] | None:
    path = _spotify_mode_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError):
        _clear_persistent_spotify_mode()
        return None
    if not isinstance(payload, dict) or not payload.get("enabled"):
        _clear_persistent_spotify_mode()
        return None

    token = load_spotify_token()
    if not token or not getattr(token, "access_token", None) or _spotify_token_expired(token):
        _clear_persistent_spotify_mode()
        return None
    token_scopes = set(getattr(token, "scopes", []) or [])
    if not SPOTIFY_MODE_REQUIRED_SCOPES <= token_scopes:
        _clear_persistent_spotify_mode()
        return None

    mode = {
        "version": SPOTIFY_MODE_STATE_VERSION,
        "enabled": True,
        "device_id": payload.get("device_id"),
        "device_name": payload.get("device_name"),
        "entered_at": payload.get("entered_at") or _timestamp_ms(),
        "updated_at": _timestamp_ms(),
        "token_expires_at": getattr(token, "expires_at", None),
        "scopes": sorted(token_scopes),
    }
    return mode


async def _send_spotify_mode(ui: WebSocketUIAdapter, mode: dict[str, Any] | None) -> None:
    await ui._send(
        {
            "type": "spotify_mode",
            "enabled": bool(mode and mode.get("enabled")),
            "device_id": (mode or {}).get("device_id"),
            "device_name": (mode or {}).get("device_name"),
        }
    )
    _request_spotify_sync(ui)


async def _run_spotify_mode_call(
    ui: WebSocketUIAdapter,
    *,
    func: Any,
    pending_detail: str,
    timeout_message: str,
    failure_title: str = "Spotify mode",
) -> Any | None:
    await ui.append_activity(kind="tool", title="Spotify mode", detail=pending_detail, status="pending")
    try:
        return await asyncio.wait_for(asyncio.to_thread(func), timeout=SPOTIFY_MODE_CALL_TIMEOUT_SECONDS)
    except TimeoutError:
        await ui.append_activity(kind="error", title=failure_title, detail=timeout_message, status="error")
        await ui.append_agent_message(timeout_message)
        return None
    except Exception as exc:
        message = sanitize_error_message(exc)
        await ui.append_activity(kind="error", title=failure_title, detail=message, status="error")
        await ui.append_agent_message(message)
        return None


async def _run_spotify_library_call(
    ui: WebSocketUIAdapter,
    *,
    func: Any,
    timeout_message: str,
) -> Any | None:
    try:
        return await asyncio.wait_for(asyncio.to_thread(func), timeout=SPOTIFY_MODE_CALL_TIMEOUT_SECONDS)
    except TimeoutError:
        await ui.append_activity(kind="error", title="Spotify playlists", detail=timeout_message, status="error")
        await ui.append_agent_message(timeout_message)
        return None
    except Exception as exc:
        message = sanitize_error_message(exc)
        await ui.append_activity(kind="error", title="Spotify playlists", detail=message, status="error")
        await ui.append_agent_message(message)
        return None


def _spotify_track_panel_tracks(tracks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, track in enumerate(tracks, start=1):
        name = str(track.get("name") or track.get("title") or "-")
        row: dict[str, Any] = {
            "index": str(index),
            "title": name,
            "name": name,
            "artist": str(track.get("artist") or "-"),
            "duration": _duration_text(track.get("duration_ms")),
            "duration_ms": int(track.get("duration_ms") or 0),
            "provider": "spotify",
            "source_app": "Spotify",
        }
        for key in ("album", "uri", "spotify_url", "album_cover_url", "id"):
            if track.get(key):
                row[key] = track.get(key)
        rows.append(row)
    return rows


async def _fetch_all_spotify_saved_tracks(
    ui: WebSocketUIAdapter | None = None,
    limit: int = 50,
    *,
    stop_at_added_at: str = "",
) -> tuple[bool, list[dict[str, Any]], Any]:
    """Load saved Spotify tracks, optionally stopping at an incremental cursor."""
    bounded_limit = min(50, max(1, int(limit or 50)))
    offset = 0
    tracks: list[dict[str, Any]] = []
    while True:
        if ui is None:
            result = await asyncio.to_thread(spotify_saved_tracks, bounded_limit, offset)
        else:
            result = await _run_spotify_library_call(
                ui,
                func=lambda: spotify_saved_tracks(bounded_limit, offset),
                timeout_message="Spotify Library sync timed out while loading saved tracks. Try /playlist again later.",
            )
            if result is None:
                return False, tracks, {"status": "fail", "message": "Spotify Library sync timed out while loading saved tracks."}
        if not isinstance(result, dict) or result.get("status") != "success":
            return False, tracks, result
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        page = [item for item in data.get("tracks") or [] if isinstance(item, dict)]
        reached_cursor = False
        for track in page:
            added_at = str(track.get("added_at") or "")
            if stop_at_added_at and added_at and added_at <= stop_at_added_at:
                reached_cursor = True
                break
            tracks.append(track)
        if reached_cursor:
            return True, tracks, result
        if len(page) < bounded_limit:
            return True, tracks, result
        offset += bounded_limit


def _merge_spotify_saved_tracks(
    fresh_tracks: list[dict[str, Any]],
    persisted_tracks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge incrementally loaded saved tracks ahead of the local mirror."""
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for track in [*fresh_tracks, *persisted_tracks]:
        key = str(track.get("uri") or track.get("spotify_url") or track.get("key") or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        merged.append(track)
    return merged


def _spotify_mirror_external_ids() -> set[str]:
    """Return external IDs for Spotify mirrors already available locally."""
    try:
        playlists = list_playlists()
    except OSError:
        return set()
    return {
        str(playlist.get("external_id") or "")
        for playlist in playlists
        if playlist.get("source_app") == "Spotify" and playlist.get("external_id")
    }


async def _fetch_all_spotify_playlist_tracks(playlist_id: str, ui: WebSocketUIAdapter | None = None, limit: int = 100) -> tuple[bool, list[dict[str, Any]], Any]:
    """Loads every available Spotify playlist track using paged API calls."""
    bounded_limit = min(100, max(1, int(limit or 100)))
    offset = 0
    tracks: list[dict[str, Any]] = []
    while True:
        if ui is None:
            result = await asyncio.to_thread(spotify_playlist_tracks, playlist_id, bounded_limit, offset)
        else:
            result = await _run_spotify_library_call(
                ui,
                func=lambda: spotify_playlist_tracks(playlist_id, bounded_limit, offset),
                timeout_message="Spotify Library sync timed out while loading playlist tracks. Try /playlist again later.",
            )
            if result is None:
                return False, tracks, {"status": "fail", "message": "Spotify Library sync timed out while loading playlist tracks."}
        if not isinstance(result, dict) or result.get("status") != "success":
            return False, tracks, result
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        page = [item for item in data.get("tracks") or [] if isinstance(item, dict)]
        tracks.extend(page)
        if len(page) < bounded_limit:
            return True, tracks, result
        offset += bounded_limit


async def _fetch_all_spotify_playlists(
    ui: WebSocketUIAdapter | None = None,
    limit: int = 50,
) -> tuple[bool, list[dict[str, Any]], Any]:
    """Load every available Spotify playlist using maximum-size pages."""
    bounded_limit = min(50, max(1, int(limit or 50)))
    offset = 0
    playlists: list[dict[str, Any]] = []
    while True:
        if ui is None:
            result = await asyncio.to_thread(spotify_playlists, bounded_limit, offset)
        else:
            result = await _run_spotify_library_call(
                ui,
                func=lambda: spotify_playlists(bounded_limit, offset),
                timeout_message="Spotify Library sync timed out while loading playlists. Try /playlist again later.",
            )
            if result is None:
                return False, playlists, {"status": "fail", "message": "Spotify Library sync timed out while loading playlists."}
        if not isinstance(result, dict) or result.get("status") != "success":
            return False, playlists, result
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        page = [item for item in data.get("playlists") or [] if isinstance(item, dict)]
        playlists.extend(page)
        if len(page) < bounded_limit:
            return True, playlists, result
        offset += bounded_limit


def _spotify_playlist_choice(index: int, playlist: dict[str, Any]) -> dict[str, Any]:
    count = _compact_count(playlist.get("track_count")) or "0"
    owner = str(playlist.get("owner") or "Spotify").strip()
    return {
        "value": f"spotify_playlist:{index}",
        "label": str(playlist.get("name") or "Untitled playlist"),
        "description": f"{count} tracks · {owner}",
    }


class SpotifyDeviceSelectionSession:
    """Owns the Spotify Connect device picker for mode entry."""

    def __init__(
        self,
        ui: WebSocketUIAdapter,
        devices: list[dict[str, Any]],
        on_selected: Any | None = None,
        on_cancel: Any | None = None,
    ) -> None:
        self.ui = ui
        self.devices = devices
        self.on_selected = on_selected
        self.on_cancel = on_cancel
        self.confirm_id = _new_event_id("spotify_device")

    async def start(self) -> None:
        choices = [
            {
                "value": f"spotify_device:{device.get('id')}",
                "label": str(device.get("name") or "Spotify device"),
                "description": str(device.get("type") or "Spotify Connect"),
            }
            for device in self.devices
            if device.get("id") and not device.get("is_restricted")
        ]
        choices.append({"value": "cancel", "label": "Cancel"})
        await self.ui.append_activity(
            kind="confirm",
            title="Spotify mode",
            detail="Choose a Spotify Connect device for this session.",
            status="pending",
            activity_id=self.confirm_id,
        )
        await self.ui.ask_confirm(
            {
                "id": self.confirm_id,
                "tool_name": "spotify_device",
                "tool_args": {"stage": "device_choice"},
                "message": "Choose Spotify device",
                "choices": choices,
            }
        )

    def owns_confirm(self, confirm_id: str) -> bool:
        return confirm_id == self.confirm_id

    async def handle_choice(self, decision: Any) -> None:
        setattr(self.ui, "_spotify_device_selection", None)
        value = str(decision or "cancel")
        if value in {"cancel", "deny", "false"}:
            await self.ui.append_activity(kind="status", title="Spotify mode", detail="Spotify mode canceled.", status="success")
            if self.on_cancel is not None:
                await self.on_cancel()
            return
        device_id = value.removeprefix("spotify_device:").strip()
        device = next((item for item in self.devices if str(item.get("id") or "") == device_id), None)
        if not device:
            message = "Selected Spotify device is no longer available."
            await self.ui.append_activity(kind="error", title="Spotify mode", detail=message, status="error")
            await self.ui.append_system_message(message)
            if self.on_cancel is not None:
                await self.on_cancel()
            return
        if self.on_selected is not None:
            await self.on_selected(device)
            return
        mode = _spotify_mode_state(device)
        setattr(self.ui, "_spotify_mode", mode)
        _persist_spotify_mode(mode)
        await _send_spotify_mode(self.ui, mode)
        message = f"Spotify mode on: {device.get('name') or 'selected device'}."
        await self.ui.append_activity(kind="status", title="Spotify mode", detail=message, status="success")
        await self.ui.append_system_message(message)


class SpotifyPlaySelectionSession:
    """Owns Spotify-only track candidate playback."""

    def __init__(self, ui: WebSocketUIAdapter, runner: "WebSocketRunner", query: str, tracks: list[dict[str, Any]]) -> None:
        self.ui = ui
        self.runner = runner
        self.query = query
        self.tracks = tracks[:5]
        self.confirm_id = _new_event_id("spotify_track")

    async def start(self) -> None:
        choices = [self._track_choice(index, track) for index, track in enumerate(self.tracks)]
        choices.append({"value": "cancel", "label": "Cancel"})
        await self.ui.append_activity(
            kind="confirm",
            title="Spotify tracks",
            detail=f"Choose a Spotify result for {self.query}.",
            status="pending",
            activity_id=self.confirm_id,
        )
        await self.ui.ask_confirm(
            {
                "id": self.confirm_id,
                "tool_name": "spotify_track",
                "tool_args": {"query": self.query, "stage": "spotify_track_candidates"},
                "message": "Choose Spotify track",
                "choices": choices,
            }
        )

    def owns_confirm(self, confirm_id: str) -> bool:
        return confirm_id == self.confirm_id

    def _track_choice(self, index: int, track: dict[str, Any]) -> dict[str, Any]:
        artist = track.get("artist")
        album = track.get("album")
        name = track.get("name") or track.get("title")
        return {
            "value": f"spotify_track:{index}",
            "label": format_music_candidate_label(artist, album, name),
            "display": music_candidate_display(artist, album, name),
            "description": "",
        }

    async def handle_choice(self, decision: Any) -> None:
        value = str(decision or "cancel")
        if value in {"cancel", "deny", "false"}:
            setattr(self.ui, "_spotify_play_selection", None)
            await self.ui.append_activity(kind="status", title="Spotify playback", detail="Playback canceled.", status="success")
            return
        try:
            index = int(value.removeprefix("spotify_track:").removeprefix("song_candidate:"))
        except ValueError:
            index = -1
        track = self.tracks[index] if 0 <= index < len(self.tracks) else None
        if not track or not track.get("uri"):
            message = "Selected Spotify track is no longer available."
            await self.ui.append_activity(kind="error", title="Spotify playback", detail=message, status="error")
            await self.ui.append_agent_message(message)
            return
        mode = getattr(self.ui, "_spotify_mode", {}) or {}
        args = {"uri": track["uri"]}
        if mode.get("device_id"):
            args["device_id"] = mode["device_id"]
        result = await asyncio.to_thread(registry.invoke_system, "spotify_play", args)
        await self.runner._sync_tool_result_ui(self.ui, "spotify_play", result)
        if _is_failed_tool_result(result):
            message = _friendly_runtime_error_message(result, fallback="Spotify playback failed.")
            await self.ui.append_agent_message(message)
            await self.ui.send_error(message)
        else:
            await self.runner._handoff_previous_provider(self.ui, "spotify")
            setattr(self.ui, "_active_playback_provider", "spotify")
            setattr(self.ui, "_preferred_playback_provider", "spotify")
            await self.ui.append_activity(kind="status", title="Spotify playback", detail="Spotify playback selected.", status="success")
        setattr(self.ui, "_spotify_play_selection", None)


class SpotifyPlaylistSelectionSession:
    """Owns Spotify playlist browsing inside Spotify mode."""

    def __init__(self, ui: WebSocketUIAdapter, playlists: list[dict[str, Any]]) -> None:
        self.ui = ui
        self.playlists = playlists[:50]
        self.confirm_id = _new_event_id("spotify_playlist")

    async def start(self) -> None:
        choices = [_spotify_playlist_choice(index, playlist) for index, playlist in enumerate(self.playlists)]
        choices.append({"value": "cancel", "label": "Cancel"})
        await self.ui.append_activity(
            kind="confirm",
            title="Spotify playlists",
            detail="Choose a Spotify playlist.",
            status="pending",
            activity_id=self.confirm_id,
        )
        await self.ui.ask_confirm(
            {
                "id": self.confirm_id,
                "tool_name": "spotify_playlist",
                "tool_args": {"stage": "spotify_playlist_choice"},
                "message": "Choose Spotify playlist",
                "choices": choices,
            }
        )

    def owns_confirm(self, confirm_id: str) -> bool:
        return confirm_id == self.confirm_id

    async def handle_choice(self, decision: Any) -> None:
        setattr(self.ui, "_spotify_playlist_selection", None)
        value = str(decision or "cancel")
        if value in {"cancel", "deny", "false"}:
            await self.ui.append_activity(kind="status", title="Spotify playlists", detail="Playlist browsing canceled.", status="success")
            return
        try:
            index = int(value.removeprefix("spotify_playlist:"))
        except ValueError:
            index = -1
        playlist = self.playlists[index] if 0 <= index < len(self.playlists) else None
        if not playlist or not playlist.get("id"):
            message = "Selected Spotify playlist is no longer available."
            await self.ui.append_activity(kind="error", title="Spotify playlists", detail=message, status="error")
            await self.ui.append_system_message(message)
            return
        ok, tracks, result = await _fetch_all_spotify_playlist_tracks(str(playlist["id"]))
        if not ok:
            message = _friendly_runtime_error_message(result, fallback="Spotify playlist tracks failed.")
            await self.ui.append_activity(kind="error", title="Spotify playlists", detail=message, status="error")
            await self.ui.append_system_message(message)
            return
        title = f"Spotify Playlist: {playlist.get('name') or 'Playlist'}"
        await self.ui._send(_track_panel_payload("playlist", title, _spotify_track_panel_tracks(tracks)))
        await self.ui.append_activity(kind="status", title="Spotify playlists", detail=f"Showing {title}.", status="success")


class ConnectionSelectionSession:
    """Own the interactive `/connect` provider chooser."""

    def __init__(
        self,
        ui: WebSocketUIAdapter,
        runner: "WebSocketRunner",
        manager: MusicConnectionManager,
    ) -> None:
        self.ui = ui
        self.runner = runner
        self.manager = manager
        self.confirm_id = _new_event_id("music_connection")
        self.busy_provider_id: str | None = None
        self.operation_task: asyncio.Task[None] | None = None
        self.closed = False

    @staticmethod
    def _providers() -> tuple[tuple[str, str], ...]:
        return (
            ("spotify", "Spotify"),
            ("netease", "NetEase Cloud Music"),
            ("jamendo", "Jamendo"),
            ("audius", "Audius"),
        )

    def _choices(self) -> list[dict[str, object]]:
        choices: list[dict[str, object]] = []
        for provider_id, label in self._providers():
            record = self.manager.record(provider_id)
            if self.busy_provider_id == provider_id:
                connection_status = "checking"
                description = "Checking connection..."
            elif record is not None and record.status != "connected":
                connection_status = "warning"
                description = "press Enter to retry"
            elif record is not None or provider_id in {"jamendo", "audius"}:
                connection_status = "connected"
                account_label = (
                    record.account_label
                    if record is not None and provider_id not in {"jamendo", "audius"}
                    else None
                )
                description = f"Connected · {account_label}" if account_label else "Connected"
            else:
                connection_status = "missing"
                description = "Not connected"
            choices.append(
                {
                    "value": provider_id,
                    "label": label,
                    "description": description,
                    "connection_status": connection_status,
                }
            )
        return choices

    async def _render(self, *, preserve_selection: bool) -> None:
        if self.closed:
            return
        await self.ui.ask_confirm(
            {
                "type": "confirm",
                "id": self.confirm_id,
                "tool_name": "music_connection",
                "tool_args": {
                    "stage": "music_connection_selection",
                    "hint": "↑/↓ to select · Enter to connect/check · Esc to close",
                    "preserve_selection": preserve_selection,
                    "busy_provider": self.busy_provider_id,
                },
                "message": "Music connections",
                "choices": self._choices(),
            }
        )

    async def start(self) -> None:
        await self._render(preserve_selection=False)

    def owns_confirm(self, confirm_id: str) -> bool:
        return confirm_id == self.confirm_id

    async def handle_choice(self, decision: Any) -> None:
        provider_id = str(decision or "deny").strip().casefold()
        if provider_id == "deny":
            await self.close()
            return
        if self.closed or self.busy_provider_id is not None:
            return
        if provider_id not in {provider for provider, _label in self._providers()}:
            return
        self.busy_provider_id = provider_id
        await self._render(preserve_selection=True)
        self.operation_task = asyncio.create_task(self._run_provider(provider_id))

    async def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        operation_task = self.operation_task
        if operation_task is not None and not operation_task.done():
            operation_task.cancel()
        netease_login = getattr(self.ui, "_netease_login_session", None)
        if netease_login is not None:
            await netease_login.cancel()
        self.busy_provider_id = None
        setattr(self.ui, "_music_connection_selection", None)
        await self.ui.dismiss_confirm(self.confirm_id)

    async def _run_provider(self, provider_id: str) -> None:
        def complete(result: dict[str, Any]) -> None:
            asyncio.create_task(self._complete_provider(provider_id, result))

        try:
            await self.runner._connect_music_provider(
                self.ui,
                provider_id,
                complete=complete,
                emit_feedback=False,
            )
        except asyncio.CancelledError:
            return
        except Exception as exc:
            await self._complete_provider(
                provider_id,
                {
                    "status": "failed",
                    "message": sanitize_error_message(exc),
                    "data": {"provider": provider_id, "reason": "connection_failed"},
                },
            )

    async def _complete_provider(self, provider_id: str, result: dict[str, Any]) -> None:
        if self.closed or self.busy_provider_id != provider_id:
            return
        status = str(result.get("status") or "failed").casefold()
        if status == "cancelled":
            await self.close()
            return
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        if status in {"connected", "success", "ok"}:
            if self.manager.record(provider_id) is None:
                self.manager.mark_connected(
                    provider_id,
                    account_label=data.get("account_label"),
                )
        else:
            technical_detail = sanitize_error_message(
                str(result.get("message") or data.get("reason") or "Connection failed.")
            )
            logger.warning(
                "Music connection check failed for %s: %s",
                provider_id,
                technical_detail,
            )
            self.manager.mark_unavailable(
                provider_id,
                reason="connection_failed",
            )
        self.busy_provider_id = None
        self.operation_task = None
        await self._render(preserve_selection=True)


class ProviderModeExitSession:
    """Confirm an explicit exit from the currently active provider mode."""

    def __init__(
        self,
        ui: WebSocketUIAdapter,
        runner: "WebSocketRunner",
        provider: str,
    ) -> None:
        self.ui = ui
        self.runner = runner
        self.provider = provider
        self.confirm_id = _new_event_id("provider_mode_exit")

    async def start(self) -> None:
        label = "Spotify"
        command = "/spotify"
        await self.ui.append_activity(
            kind="confirm",
            title=f"Exit {label} Mode?",
            detail=f"Running '{command}' will exit {label} Mode. Continue?",
            status="pending",
            activity_id=self.confirm_id,
        )
        await self.ui.ask_confirm(
            {
                "type": "confirm",
                "id": self.confirm_id,
                "tool_name": "provider_mode_exit",
                "tool_args": {"provider": self.provider},
                "message": f"Exit {label} Mode?",
                "warning": f"Running '{command}' will exit {label} Mode. Continue?",
                "hide_hint": True,
                "choices": [
                    {"value": "confirm_exit", "label": "Yes, I insist"},
                    {"value": "deny", "label": "No, return"},
                ],
            }
        )

    def owns_confirm(self, confirm_id: str) -> bool:
        return confirm_id == self.confirm_id

    async def handle_choice(self, decision: Any) -> None:
        if getattr(self.ui, "_provider_mode_exit", None) is self:
            setattr(self.ui, "_provider_mode_exit", None)
        if str(decision or "deny") != "confirm_exit":
            await self.ui.append_activity(
                kind="status",
                title="Provider mode",
                detail="Provider mode unchanged.",
                status="success",
                activity_id=self.confirm_id,
            )
            return
        await self.runner._exit_spotify_mode(self.ui)


class MemorySettingsSession:
    """Manage the structured memory browser and recoverable formatting flow."""

    def __init__(self, ui: WebSocketUIAdapter, store: Any) -> None:
        self.ui = ui
        self.store = store
        self.confirm_id = _new_event_id("memory_settings")
        self.stage = "settings"
        self.format_target = "all"

    async def start(self) -> None:
        await self.ui._send(
            {
                "type": "memory_panel",
                "view": "root",
                "title": "Memory",
                "hint": (
                    "b rebuild damaged metadata · Esc to hide"
                    if getattr(self.store, "_read_only_reason", None) == "metadata_corrupt"
                    else "Enter to select; Esc to hide"
                ),
                "read_only": bool(getattr(self.store, "_read_only", False)),
                "entries": [],
            }
        )

    async def show_sources(self) -> None:
        await self.ui._send(
            {
                "type": "memory_panel",
                "view": "sources",
                "title": "view memory entries",
                "hint": "Enter to open; Esc to return",
                "read_only": bool(getattr(self.store, "_read_only", False)),
                "entries": [],
            }
        )

    async def show_entries(self, target: str) -> None:
        if target == "dump":
            records = [
                {
                    **item["entry"],
                    "target": "dump",
                    "reason": item.get("reason"),
                    "forgotten_at": item.get("forgotten_at"),
                    "expires_at": item.get("expires_at"),
                }
                for item in self.store.dump_entries()
            ]
            title = "Memory Dump"
        else:
            records = [
                {
                    **self.store._entry_to_dict(entry),
                    "review_pending": bool(entry.review),
                }
                for entry in self.store.entries(target)
            ]
            title = "USER.md" if target == "user" else "MEMORY.md"
        await self.ui._send(
            {
                "type": "memory_panel",
                "view": "entries",
                "target": target,
                "title": title,
                "hint": "/ search · Enter details · a add · e edit · f forget · Esc return",
                "read_only": bool(getattr(self.store, "_read_only", False)),
                "entries": records,
            }
        )

    async def show_detail(self, target: str, entry_id: str) -> None:
        if target == "dump":
            item = next(
                (item for item in self.store.dump_entries() if item.get("entry", {}).get("entry_id") == entry_id),
                None,
            )
            records = [] if item is None else [{
                **item["entry"],
                "target": "dump",
                "reason": item.get("reason"),
                "forgotten_at": item.get("forgotten_at"),
                "expires_at": item.get("expires_at"),
            }]
            revisions: list[dict[str, Any]] = []
        else:
            entry = next((entry for entry in self.store.entries(target) if entry.entry_id == entry_id), None)
            records = [] if entry is None else [{
                **self.store._entry_to_dict(entry),
                "review_pending": bool(entry.review),
            }]
            revisions = self.store.revisions(entry_id)
        active_review = bool(records and records[0].get("review_pending"))
        await self.ui._send(
            {
                "type": "memory_panel",
                "view": "detail",
                "target": target,
                "title": "Memory details",
                "hint": (
                    "e edit · f forget · m move · y accept · n reject · v revisions · Esc return"
                    if target != "dump" and active_review
                    else "e edit · f forget · m move · v revisions · Esc return"
                    if target != "dump"
                    else "r recall · Esc return"
                ),
                "read_only": bool(getattr(self.store, "_read_only", False)),
                "entries": records,
                "settings": {"revisions": revisions},
            }
        )

    async def show_revisions(self, target: str, entry_id: str) -> None:
        entry = next((entry for entry in self.store.entries(target) if entry.entry_id == entry_id), None)
        revisions = self.store.revisions(entry_id) if entry is not None else []
        records = [
            {
                "entry_id": str(index),
                "target": target,
                "content": str(revision.get("before") or ""),
                "source": str(revision.get("actor") or "unknown"),
                "confidence": 1.0,
                "protected": True,
                "updated_at": revision.get("changed_at"),
            }
            for index, revision in enumerate(revisions)
        ]
        await self.ui._send(
            {
                "type": "memory_panel",
                "view": "revisions",
                "target": target,
                "title": "Memory revisions",
                "hint": "Enter to restore; Esc to return",
                "read_only": bool(getattr(self.store, "_read_only", False)),
                "entries": records,
                "settings": {"entry_id": entry_id},
            }
        )

    async def show_settings(self) -> None:
        await self.ui._send(
            {
                "type": "memory_panel",
                "view": "settings",
                "title": "Settings · Memory",
                "hint": "Enter to change; Esc to hide",
                "read_only": bool(getattr(self.store, "_read_only", False)),
                "entries": [],
                "settings": self.store.settings(),
            }
        )

    async def show_format_scopes(self) -> None:
        await self.ui._send(
            {
                "type": "memory_panel",
                "view": "format",
                "title": "reset memory",
                "hint": "select the memory to clear",
                "read_only": bool(getattr(self.store, "_read_only", False)),
                "entries": [],
            }
        )

    async def confirm_format(self, target: str) -> None:
        self.stage = "reset"
        self.format_target = target
        self.confirm_id = _new_event_id("memory_format")
        label = {"user": "USER.md", "memory": "MEMORY.md", "all": "all memory"}.get(target, "all memory")
        await self.ui.ask_confirm(
            {
                "id": self.confirm_id,
                "tool_name": "memory_settings",
                "tool_args": {"stage": "memory_format", "target": target},
                "message": f"Format {label}?",
                "warning": "Every active entry in this scope will move to Memory Dump.",
                "hide_hint": True,
                "choices": [
                    {"value": "confirm_reset", "label": f"Yes, format {label}"},
                    {"value": "deny", "label": "No, return"},
                ],
            }
        )

    def owns_confirm(self, confirm_id: str) -> bool:
        return confirm_id == self.confirm_id

    async def handle_choice(self, decision: Any) -> None:
        value = str(decision or "deny")
        if self.stage == "reset":
            setattr(self.ui, "_memory_settings", None)
            if value != "confirm_reset":
                return
            result = self.store.format_memory(self.format_target)
            if result.get("success"):
                await self.ui.append_system_message("Long-term memory reset.")
            else:
                await self.ui.append_warning_message(
                    str(result.get("error") or "Long-term memory could not be reset.")
                )
            return

        if value != "reset":
            setattr(self.ui, "_memory_settings", None)
            return

        self.stage = "reset"
        self.confirm_id = _new_event_id("memory_reset")
        await self.ui.ask_confirm(
            {
                "id": self.confirm_id,
                "tool_name": "memory_settings",
                "tool_args": {"stage": "memory_reset"},
                "message": "Reset long-term memory?",
                "warning": "This permanently clears every entry in USER.md and MEMORY.md.",
                "hide_hint": True,
                "choices": [
                    {"value": "confirm_reset", "label": "Yes, reset long-term memory"},
                    {"value": "deny", "label": "No, return"},
                ],
            }
        )


class WebSocketRunner:
    """Represents web socket runner.

    Encapsulates web socket runner data and behavior used by Sonex runtime flows.
    """
    def __init__(
        self,
        *,
        music_connection_manager_factory: Callable[[], MusicConnectionManager] = MusicConnectionManager,
    ) -> None:
        """Init for web socket runner.

        Coordinates the init method behavior while preserving web socket runner state and contracts.
        """
        self.tools = registry
        self.memory_store = memory_store
        self._running_task: asyncio.Task[None] | None = None
        self._confirm_queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.provider_modes = ProviderModeCoordinator()
        self._music_connection_manager_factory = music_connection_manager_factory
        self._music_connection_manager_instance: MusicConnectionManager | None = None
        self._playback_coordinator = MusicPlaybackCoordinator(SelectionStore())

    async def handle_ws(self, ws: WebSocket) -> None:
        """Coordinates handle ws for the current Sonex flow.

        Typical use: Use this function when runtime code needs handle ws as part of a Sonex command, playback, auth, llm, or ui path.

        Example: await handle_ws(ws=...) -> returns the value used by the surrounding Sonex flow.
        """
        await ws.accept()
        ui = WebSocketUIAdapter(ws, session_id=create_session_id())
        bind_memory_scope(ui.session_id)
        await ui.send_session_state()
        if has_interrupted_interaction():
            await ui.append_system_message(INTERRUPTED_INTERACTION_MESSAGE)
            clear_interrupted_interaction()
        await ui._send({"type": "queue", "tracks": _queue_payload()})
        await self._handle_startup_auth(ui)
        with suppress(OSError):
            if self.memory_store.consume_first_notice():
                await ui.append_system_message(
                    "Sonex stores stable music preferences locally. Use /memory to configure long-term memory."
                )
        with suppress(OSError, ValueError):
            forgotten = self.memory_store.run_maintenance()
            if forgotten:
                await ui.append_system_message(
                    f"{len(forgotten)} inactive Agent {'memory was' if len(forgotten) == 1 else 'memories were'} moved to Memory Dump."
                )
            for warning in self.memory_store.capacity_warnings():
                await ui.append_system_message(warning)
        ready, _provider, _reason = _llm_auth_ready()
        if ready and self.memory_store.long_term_enabled():
            asyncio.create_task(self._resume_pending_memory(ui))
        await self._restore_persistent_spotify_mode(ui)
        await self._restore_provider_mode(ui)
        playback_sync_task = asyncio.create_task(self._sync_spotify_playback(ui))
        local_playback_sync_task = asyncio.create_task(self._sync_local_playback(ui))

        unexpected_disconnect = False
        usage_observer_token = set_token_usage_observer(ui.record_token_usage)
        try:
            while True:
                raw = await ws.receive_text()
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError as exc:
                    message = f"Invalid client message: {sanitize_error_message(exc)}"
                    await ui.append_activity(
                        kind="error",
                        title="Client message error",
                        detail=message,
                        status="error",
                    )
                    await ui.send_error(message)
                    continue

                if data.get("type") == "user_input":
                    user_input = data.get("text") or data.get("content") or data.get("user_input") or ""
                    await self._handle_user_input(ui, user_input)

                elif data.get("type") == "internal_command":
                    command_text = data.get("text") or data.get("content") or ""
                    await self._handle_internal_command(ui, str(command_text))

                elif data.get("type") == "track_panel_action":
                    await self._handle_track_panel_action(ui, data)

                elif data.get("type") == "memory_panel_action":
                    await self._handle_memory_panel_action(ui, data)

                elif data.get("type") == "agent_turn_interrupt":
                    await self._handle_agent_turn_interrupt(
                        ui,
                        str(data.get("turn_id") or ""),
                    )

                elif data.get("type") == "setup_input":
                    spotify_setup = getattr(ui, "_spotify_setup", None)
                    if spotify_setup:
                        await spotify_setup.handle_input(str(data.get("value") or ""))

                elif data.get("type") == "auth_setup_input":
                    model_setup = getattr(ui, "_model_setup", None)
                    if model_setup:
                        await model_setup.handle_input(str(data.get("value") or ""))
                        continue
                    auth_setup = getattr(ui, "_auth_setup", None)
                    if auth_setup:
                        await auth_setup.handle_input(str(data.get("value") or ""))

                elif data.get("type") == "netease_login_input":
                    netease_login = getattr(ui, "_netease_login_session", None)
                    if netease_login:
                        await netease_login.cancel()

                elif data.get("type") == "confirm_result":
                    decision = data.get("decision")
                    if decision is None:
                        confirmed = data.get("confirmed")
                        if confirmed is None:
                            confirmed = data.get("ok")
                        decision = "allow_once" if confirmed else "deny"
                    confirm_id = str(data.get("id") or "")
                    if await self._handle_confirm_result(ui, confirm_id, decision):
                        continue
                    spotify_device = getattr(ui, "_spotify_device_selection", None)
                    if spotify_device and spotify_device.owns_confirm(confirm_id):
                        await spotify_device.handle_choice(decision)
                        continue
                    spotify_play = getattr(ui, "_spotify_play_selection", None)
                    if spotify_play and spotify_play.owns_confirm(confirm_id):
                        await spotify_play.handle_choice(decision)
                        continue
                    spotify_playlist = getattr(ui, "_spotify_playlist_selection", None)
                    if spotify_playlist and spotify_playlist.owns_confirm(confirm_id):
                        await spotify_playlist.handle_choice(decision)
                        continue
                    player_backend = getattr(ui, "_player_backend_selection", None)
                    if player_backend and player_backend.owns_confirm(confirm_id):
                        await player_backend.handle_choice(decision)
                        continue
                    self._confirm_queue.put((confirm_id, decision))

                elif data.get("type") == "bye":
                    messages = _coerce_transcript_messages(data.get("messages"))
                    reason = str(data.get("reason") or "bye")
                    await self._handle_bye(ui, messages=messages, reason=reason)
                    break

        except WebSocketDisconnect:
            unexpected_disconnect = True
        finally:
            agent_interaction_active = bool(
                getattr(ui, "_agent_candidate_selection", None)
                or getattr(ui, "_agent_connection_active", False)
            )
            if unexpected_disconnect and agent_interaction_active:
                with suppress(OSError):
                    mark_interrupted_interaction()
            spotify_setup = getattr(ui, "_spotify_setup", None)
            if spotify_setup and spotify_setup.oauth_task:
                spotify_setup.oauth_task.cancel()
            auth_setup = getattr(ui, "_auth_setup", None)
            if auth_setup and auth_setup.oauth_task:
                auth_setup.oauth_task.cancel()
            netease_login = getattr(ui, "_netease_login_session", None)
            if netease_login:
                await netease_login.cancel()
            playback_sync_task.cancel()
            local_playback_sync_task.cancel()
            with suppress(asyncio.CancelledError):
                if spotify_setup and spotify_setup.oauth_task:
                    await spotify_setup.oauth_task
            with suppress(asyncio.CancelledError):
                if auth_setup and auth_setup.oauth_task:
                    await auth_setup.oauth_task
            with suppress(asyncio.CancelledError):
                if netease_login and netease_login.task:
                    await netease_login.task
            with suppress(asyncio.CancelledError):
                await playback_sync_task
            with suppress(asyncio.CancelledError):
                await local_playback_sync_task
            self._confirm_queue.put(
                (
                    "",
                    {
                        "status": "cancelled",
                        "message": "Agent interaction was interrupted.",
                        "data": {"reason": "session_disconnected"},
                        "error_code": None,
                    },
                )
            )
            reset_token_usage_observer(usage_observer_token)

    async def _handle_confirm_result(self, ui: WebSocketUIAdapter, confirm_id: str, decision: Any) -> bool:
        memory_settings = getattr(ui, "_memory_settings", None)
        if memory_settings and memory_settings.owns_confirm(confirm_id):
            await memory_settings.handle_choice(decision)
            return True
        provider_mode_exit = getattr(ui, "_provider_mode_exit", None)
        if provider_mode_exit and provider_mode_exit.owns_confirm(confirm_id):
            await provider_mode_exit.handle_choice(decision)
            return True
        playback_route = getattr(ui, "_agent_playback_route_confirmation", None)
        if playback_route and playback_route.owns_confirm(confirm_id):
            await playback_route.handle_choice(decision)
            return True
        playback_source = getattr(ui, "_playback_source_selection", None)
        if playback_source and playback_source.owns_confirm(confirm_id):
            await playback_source.handle_choice(decision)
            return True
        netease_offer = getattr(ui, "_netease_login_offer", None)
        if netease_offer and netease_offer.owns_confirm(confirm_id):
            await netease_offer.handle_choice(decision)
            return True
        agent_candidate = getattr(ui, "_agent_candidate_selection", None)
        if agent_candidate and agent_candidate.owns_confirm(confirm_id):
            await agent_candidate.handle_choice(decision)
            return True
        music_confirmation = getattr(ui, "_music_intent_confirmation", None)
        if music_confirmation and music_confirmation.owns_confirm(confirm_id):
            await music_confirmation.handle_choice(decision)
            return True
        play_selection = getattr(ui, "_play_selection", None)
        if play_selection and play_selection.owns_confirm(confirm_id):
            await play_selection.handle_choice(decision)
            return True
        playlist_save = getattr(ui, "_playlist_save", None)
        if playlist_save and playlist_save.owns_confirm(confirm_id):
            await playlist_save.handle_choice(decision)
            return True
        playlist_browse = getattr(ui, "_playlist_browse", None)
        if playlist_browse and playlist_browse.owns_confirm(confirm_id):
            await playlist_browse.handle_choice(decision)
            return True
        music_connection = getattr(ui, "_music_connection_selection", None)
        if music_connection and music_connection.owns_confirm(confirm_id):
            await music_connection.handle_choice(decision)
            return True
        return False

    async def _handle_agent_turn_interrupt(
        self,
        ui: WebSocketUIAdapter,
        turn_id: str,
    ) -> bool:
        """Logically interrupt the matching foreground Agent turn."""
        if not turn_id or getattr(ui, "_active_agent_turn_id", None) != turn_id:
            return False
        interrupt_event = getattr(ui, "_agent_turn_interrupt_event", None)
        if isinstance(interrupt_event, threading.Event):
            interrupt_event.set()
        provider_task = getattr(ui, "_active_agent_provider_task", None)
        if isinstance(provider_task, asyncio.Task) and not provider_task.done():
            provider_task.cancel()
        worker = getattr(ui, "_active_netease_worker", None)
        if isinstance(worker, NetEaseProviderWorker):
            with suppress(Exception):
                worker.terminate_active()
        self._confirm_queue.put(
            (
                "",
                {
                    "status": "cancelled",
                    "message": "Agent turn interrupted.",
                    "data": {"reason": "user_interrupted", "turn_id": turn_id},
                    "error_code": None,
                },
            )
        )
        setattr(ui, "_active_agent_turn_id", None)
        await ui.send_agent_working_state(turn_id, active=False)
        await ui.append_system_message("Agent turn interrupted.")
        return True

    async def _handle_startup_auth(self, ui: WebSocketUIAdapter) -> None:
        """Prepares handle startup auth for an internal Sonex flow.

        Typical use: Use this helper when nearby code needs handle startup auth without duplicating the local rules.

        Example: await _handle_startup_auth(ui=...) -> returns the value used by the surrounding Sonex flow.
        """
        state = _llm_auth_state()
        await ui.send_auth_state(state)
        if state.ready:
            return
        setup = AuthSetupSession(ui, state.provider, None, self)
        setattr(ui, "_auth_setup", setup)
        await setup.start(state.reason)

    async def _sync_spotify_playback(self, ui: WebSocketUIAdapter) -> None:
        """Prepares sync spotify playback for an internal Sonex flow.

        Typical use: Use this helper when nearby code needs sync spotify playback without duplicating the local rules.

        Example: await _sync_spotify_playback(ui=...) -> returns the value used by the surrounding Sonex flow.
        """
        last_signature: tuple[Any, ...] | None = None
        last_cover_url: str | None = None
        reported_failures: set[str] = set()
        while not ui.closed:
            if not self._spotify_mode_enabled(ui):
                await _wait_for_spotify_sync(ui, SPOTIFY_PLAYBACK_IDLE_POLL_SECONDS)
                continue
            poll_seconds = SPOTIFY_PLAYBACK_IDLE_POLL_SECONDS
            try:
                _spotify_sync_event(ui).clear()
                result = await asyncio.to_thread(spotify_current_playback)
                if isinstance(result, dict) and result.get("status") == "success":
                    player_state, cover_url = _extract_music_state(result)
                    if player_state:
                        player_state = _spotify_live_player_state(player_state)
                        player_state = _decorate_player_state(player_state)
                        _remember_actual_playback(player_state)
                        _record_playback_behavior(ui, player_state)
                        signature = _player_sync_signature(player_state)
                        if signature != last_signature:
                            setattr(ui, "_last_player_state", player_state)
                            await ui._send({"type": "player", "state": player_state})
                            await ui._send({"type": "queue", "tracks": _queue_payload()})
                            last_signature = signature
                        if bool(player_state.get("is_playing")):
                            poll_seconds = SPOTIFY_PLAYBACK_ACTIVE_POLL_SECONDS
                        if cover_url and cover_url != last_cover_url:
                            await ui.send_cover(cover_url)
                            last_cover_url = cover_url
                elif isinstance(result, dict) and result.get("status") in {"fail", "error"}:
                    failure_key = str(result.get("error_code") or result.get("message") or "spotify_sync_failed")
                    if failure_key not in reported_failures:
                        reported_failures.add(failure_key)
                        await ui.append_agent_message(_friendly_runtime_error_message(result, fallback="Spotify playback sync failed."))
                    if failure_key in {
                        "SPOTIFY_AUTH_EXPIRED",
                        "SPOTIFY_LOGIN_REQUIRED",
                        "SPOTIFY_PREMIUM_REQUIRED",
                        "SPOTIFY_SCOPE_MISSING",
                    }:
                        return
            except Exception:
                pass
            cooldown = spotify_api_cooldown_remaining()
            await _wait_for_spotify_sync(ui, max(poll_seconds, cooldown))

    async def _sync_local_playback(self, ui: WebSocketUIAdapter) -> None:
        """Continuously publish authoritative local-player progress."""
        last_player_state: dict[str, Any] | None = None
        sync_lost = False
        while not ui.closed:
            if self._spotify_mode_enabled(ui):
                last_player_state = None
                sync_lost = False
                await _wait_for_local_playback_sync(ui, LOCAL_PLAYBACK_POLL_SECONDS)
                continue
            try:
                result = await asyncio.to_thread(local_playback_status)
                if isinstance(result, dict) and result.get("status") == "success":
                    player_state, _cover_url = _extract_music_state(result)
                    if player_state:
                        player_state = _local_live_player_state(player_state)
                        player_state = _decorate_player_state(player_state)
                        _record_playback_behavior(ui, player_state)
                        last_player_state = player_state
                        sync_lost = False
                        setattr(ui, "_last_player_state", player_state)
                        await ui._send({"type": "player", "state": player_state})
                elif (
                    isinstance(result, dict)
                    and result.get("error_code") == "PLAYBACK_STATUS_UNAVAILABLE"
                    and last_player_state
                    and not sync_lost
                ):
                    frozen_state = {
                        **last_player_state,
                        "playback_status": "syncing",
                        "progress_sync_lost": True,
                    }
                    setattr(ui, "_last_player_state", frozen_state)
                    await ui._send({"type": "player", "state": frozen_state})
                    sync_lost = True
                elif isinstance(result, dict) and result.get("error_code") == "NO_ACTIVE_PLAYBACK":
                    last_player_state = None
                    sync_lost = False
                    setattr(ui, "_last_playback_behavior_key", None)
            except Exception:
                pass
            await _wait_for_local_playback_sync(ui, LOCAL_PLAYBACK_POLL_SECONDS)

    async def _handle_user_input(
        self,
        ui: WebSocketUIAdapter,
        user_input: str,
        *,
        append_user_message: bool = True,
    ) -> None:
        """Prepares handle user input for an internal Sonex flow.

        Typical use: Use this helper when nearby code needs handle user input without duplicating the local rules.

        Example: await _handle_user_input(ui=..., user_input=..., append_user_message=...) -> returns the value used by the surrounding Sonex flow.
        """
        user_input = user_input.strip()
        if not user_input:
            return

        if append_user_message:
            await ui.append_user_message(user_input)

        active_agent_task = getattr(ui, "_agent_turn_task", None)
        if active_agent_task is not None and not active_agent_task.done():
            pending: deque[str] = getattr(ui, "_agent_input_queue", None)
            if pending is None:
                pending = deque()
                setattr(ui, "_agent_input_queue", pending)
            if len(pending) >= 10:
                await ui.append_warning_message(
                    "The Agent message queue is full. Please resend this message after the current turn."
                )
                return
            pending.append(user_input)
            if ui.transcript and ui.transcript[-1].get("role") == "user":
                ui.transcript[-1]["execution"] = "queued"
            await ui.append_activity(
                kind="status",
                title="Message queued",
                detail=f"Waiting behind {len(pending)} message(s).",
                status="pending",
            )
            return

        play_selection = getattr(ui, "_play_selection", None)
        if play_selection and await play_selection.handle_refinement(user_input):
            return

        parsed_command = parse_builtin_command(user_input)
        if parsed_command is not None:
            if parsed_command.known and parsed_command.command and not parsed_command.command.visible:
                await self._reject_internal_chat_command(ui, parsed_command.command.name)
                return

            if self._spotify_mode_enabled(ui) and parsed_command.command and parsed_command.command.name not in SPOTIFY_MODE_COMMANDS:
                message = f"Command '/{parsed_command.command.name}' is not available in Spotify mode."
                await ui.append_activity(kind="error", title="Spotify mode", detail=message, status="error")
                await ui.append_system_message(message)
                return

            command_intent = parsed_command.command_intent()
            if command_intent is None:
                await self._handle_builtin_command(ui, parsed_command)
                return
            if command_intent.command == "recommend":
                active_provider = "spotify" if self._spotify_mode_enabled(ui) else None
                if active_provider:
                    command_intent = replace(
                        command_intent,
                        intent_prompt=(
                            f"{command_intent.intent_prompt} "
                            f"Pass provider='{active_provider}' to Recommend because "
                            "that Provider Mode is active."
                        ),
                    )

            ready, provider, reason = _llm_auth_ready()
            if not ready:
                setup = AuthSetupSession(ui, provider, user_input, self)
                setattr(ui, "_auth_setup", setup)
                await setup.start(reason)
                return

            if command_intent.command == "recommend":
                setattr(ui, "_recommendation_turn_active", True)
            self._start_agent_turn(ui, user_input, command_intent)
            return

        decision = classify_music_intent_fast(user_input)
        if decision is None:
            decision = MusicIntentDecision(
                route=MusicIntentRoute.GENERAL,
                query=None,
                confidence=0.0,
            )

        ready, provider, reason = _llm_auth_ready()
        if not ready:
            setup = AuthSetupSession(ui, provider, user_input, self)
            setattr(ui, "_auth_setup", setup)
            await setup.start(reason)
            return

        provider_mode = "spotify" if self._spotify_mode_enabled(ui) else None
        command_intent = self._music_agent_intent(
            user_input,
            decision,
            provider_mode=provider_mode,
        )
        if command_intent.command == "recommend":
            setattr(ui, "_recommendation_turn_active", True)
        self._start_agent_turn(ui, user_input, command_intent)

    def _start_agent_turn(
        self,
        ui: WebSocketUIAdapter,
        user_input: str,
        command_intent: CommandIntent | None,
    ) -> asyncio.Task[None]:
        """Start one session-scoped Agent turn."""
        task = asyncio.create_task(
            self._run_agent_turn(ui, user_input, command_intent=command_intent)
        )
        setattr(ui, "_agent_turn_task", task)
        self._running_task = task
        return task

    async def _collect_turn_memory(
        self,
        ui: WebSocketUIAdapter,
        user_input: str,
        *,
        explicit: bool,
    ) -> None:
        """Run the bounded post-turn memory hook without failing the Agent answer."""
        try:
            operations = await asyncio.to_thread(
                curate_completed_turn,
                user_input,
                store=self.memory_store,
            )
        except Exception as exc:
            logger.warning("Memory Curator failed: %s", sanitize_error_message(exc))
            with suppress(Exception):
                self.memory_store.mark_memory_candidate_failure()
            if explicit and not ui.closed:
                await ui.append_warning_message("Long-term memory could not be updated.")
            return
        for operation in operations:
            if not ui.closed:
                await ui.append_system_message(memory_operation_message(operation))

    async def _resume_pending_memory(self, ui: WebSocketUIAdapter) -> None:
        """Best-effort replay of durable Curator candidates after startup."""
        try:
            candidates = await asyncio.to_thread(self.memory_store.pending_memory_candidates)
        except Exception as exc:
            logger.warning("Pending memory discovery failed: %s", sanitize_error_message(exc))
            return
        for candidate in candidates:
            if ui.closed or not self.memory_store.long_term_enabled():
                return
            bind_memory_scope(candidate["session_id"], candidate["turn_id"])
            await self._collect_turn_memory(
                ui,
                candidate["user_input"],
                explicit=explicit_memory_operation(candidate["user_input"]) is not None,
            )

    def _spotify_mode_enabled(self, ui: WebSocketUIAdapter) -> bool:
        mode = getattr(ui, "_spotify_mode", None)
        return isinstance(mode, dict) and bool(mode.get("enabled"))

    async def _restore_provider_mode(self, ui: WebSocketUIAdapter) -> None:
        intent = load_provider_mode_intent()
        if intent.provider is ProviderMode.SPOTIFY and self._spotify_mode_enabled(ui):
            await self.provider_modes.restore(ProviderModeState(provider=ProviderMode.SPOTIFY))
            await _send_provider_mode(ui, ProviderMode.SPOTIFY)
            return
        restored_provider = ProviderMode.SPOTIFY if self._spotify_mode_enabled(ui) else ProviderMode.NORMAL
        await self.provider_modes.restore(ProviderModeState(provider=restored_provider))
        await _send_provider_mode(
            ui,
            restored_provider,
        )

    async def _restore_persistent_spotify_mode(self, ui: WebSocketUIAdapter) -> None:
        mode = _load_persistent_spotify_mode()
        if not mode:
            setattr(ui, "_spotify_mode", None)
            return
        setattr(ui, "_spotify_mode", mode)
        setattr(ui, "_spotify_library_synced", False)
        await _send_spotify_mode(ui, mode)

    async def _clear_provider_modes_for_logout(self, ui: WebSocketUIAdapter) -> None:
        """Reset provider-mode state before ending an authenticated session."""
        setattr(ui, "_spotify_mode", None)
        setattr(ui, "_spotify_library_synced", False)
        setattr(ui, "_spotify_device_selection", None)
        setattr(ui, "_spotify_play_selection", None)
        setattr(ui, "_provider_mode_exit", None)
        setattr(ui, "_preferred_playback_provider", None)
        setattr(ui, "_active_playback_provider", None)
        _clear_persistent_spotify_mode()
        clear_provider_mode_intent()
        await self.provider_modes.restore(ProviderModeState())
        await _send_spotify_mode(ui, None)
        await _send_provider_mode(ui, ProviderMode.NORMAL)

    async def _handle_spotify_random_command(self, ui: WebSocketUIAdapter) -> None:
        try:
            async def fetch_recent() -> Any:
                return await _run_spotify_mode_call(
                    ui,
                    func=lambda: spotify_recent_tracks(50),
                    pending_detail="Choosing from recently played Spotify tracks.",
                    timeout_message=(
                        "Spotify recent tracks timed out. "
                        "Check your Spotify connection, then try /random again."
                    ),
                    failure_title="Spotify random",
                )

            result, source = await _spotify_session_requests(ui).get_or_fetch(
                "recent_tracks",
                ttl_seconds=SPOTIFY_RECENT_CACHE_TTL_SECONDS,
                fetch=fetch_recent,
                cacheable=_spotify_success_result,
            )
            tracks_payload = result.get("data", {}).get("tracks", []) if isinstance(result, dict) else []
            error_code = str(result.get("error_code") or "") if isinstance(result, dict) else ""
            fallback_allowed = source in {"cooldown", "stale_cache"} or result is None or error_code in {
                "SPOTIFY_API_ERROR",
                "SPOTIFY_PROXY_UNAVAILABLE",
                "SPOTIFY_RATE_LIMITED",
            }
            if not tracks_payload and fallback_allowed:
                tracks_payload = spotify_recent_tracks_snapshot()
                if tracks_payload:
                    await ui.append_activity(
                        kind="status",
                        title="Spotify random",
                        detail="Choosing from cached recent Spotify tracks while live history is unavailable.",
                        status="warning",
                    )
            if not tracks_payload and _is_failed_tool_result(result):
                await self._sync_tool_result_ui(ui, "spotify_recent_tracks", result)
                message = _friendly_runtime_error_message(result, fallback="Spotify recent tracks failed.")
                await ui.append_agent_message(message)
                return
            seen_uris: set[str] = set()
            playable_tracks: list[dict[str, Any]] = []
            for track in tracks_payload if isinstance(tracks_payload, list) else []:
                if not isinstance(track, dict):
                    continue
                uri = str(track.get("uri") or "")
                if not uri.startswith("spotify:track:") or uri in seen_uris:
                    continue
                seen_uris.add(uri)
                playable_tracks.append(track)

            if not playable_tracks:
                message = "No recently played Spotify tracks are available to play."
                await ui.append_activity(kind="error", title="Spotify random", detail=message, status="error")
                await ui.append_agent_message(message)
                return

            selected_track = random.choice(playable_tracks)
            uri = str(selected_track.get("uri") or "")
            mode = getattr(ui, "_spotify_mode", {}) or {}
            args: dict[str, Any] = {"uri": uri}
            if mode.get("device_id"):
                args["device_id"] = mode["device_id"]
            play_result = await _run_spotify_mode_call(
                ui,
                func=lambda: registry.invoke_system("spotify_play", args),
                pending_detail="Starting random Spotify playback.",
                timeout_message=(
                    "Spotify playback timed out. "
                    "Open Spotify on the selected device, then try /random again."
                ),
                failure_title="Spotify random",
            )
            if play_result is None:
                return
            await self._sync_tool_result_ui(ui, "spotify_play", play_result)
            if _is_failed_tool_result(play_result):
                message = _friendly_runtime_error_message(play_result, fallback="Spotify playback failed.")
                await ui.append_agent_message(message)
                await ui.send_error(message)
        finally:
            if self._running_task is asyncio.current_task():
                self._running_task = None
                await ui.send_status(UiStatus(phase="Idle", message="Idle..."), active=False)

    def _looks_like_spotify_playlist_request(self, user_input: str) -> bool:
        text = user_input.strip().lower()
        return "playlist" in text or "歌单" in text

    async def _start_spotify_track_selection(self, ui: WebSocketUIAdapter, query: str) -> None:
        query_plan = build_music_search_query_plan(query)
        search_query = query_plan.original_query or query.strip()

        async def fetch_tracks() -> list[dict[str, Any]]:
            await ui.append_activity(
                kind="tool",
                title="Searching Spotify",
                detail=f"Finding Spotify tracks for {search_query}.",
                status="pending",
            )
            return await asyncio.to_thread(
                search_spotify_track_candidates,
                search_query,
                5,
                query_variants=query_plan.variants,
            )

        try:
            tracks, source = await _spotify_session_requests(ui).get_or_fetch(
                _spotify_search_cache_key(search_query),
                ttl_seconds=SPOTIFY_SEARCH_CACHE_TTL_SECONDS,
                fetch=fetch_tracks,
                cacheable=lambda value: isinstance(value, list) and spotify_api_cooldown_remaining() <= 0,
            )
        except Exception as exc:
            message = sanitize_error_message(exc)
            await ui.append_activity(kind="error", title="Spotify search failed", detail=message, status="error")
            await ui.append_agent_message(message)
            return
        if source == "cooldown":
            retry_after = max(1, int(spotify_api_cooldown_remaining() + 0.999))
            message = f"Spotify is rate limited; try searching again after {retry_after} seconds."
            await ui.append_activity(kind="error", title="Spotify search", detail=message, status="error")
            await ui.append_agent_message(message)
            return
        if source == "stale_cache":
            await ui.append_activity(
                kind="status",
                title="Spotify search",
                detail="Showing cached Spotify search results during the rate-limit cooldown.",
                status="warning",
            )
        if not tracks:
            message = f"No Spotify tracks found for '{search_query}'."
            await ui.append_activity(kind="error", title="Spotify search", detail=message, status="error")
            await ui.append_agent_message(message)
            return
        session = SpotifyPlaySelectionSession(ui, self, search_query, tracks)
        setattr(ui, "_spotify_play_selection", session)
        await session.start()

    async def _reject_internal_chat_command(self, ui: WebSocketUIAdapter, command_name: str) -> None:
        message = f"/{command_name} is an internal playback command. Use the mini-player keyboard shortcut instead."
        await ui.append_activity(kind="error", title="Internal command", detail=message, status="error")
        await ui.append_system_message(message)

    async def _handle_internal_command(self, ui: WebSocketUIAdapter, command_text: str) -> None:
        parsed_command = parse_builtin_command(command_text)
        if parsed_command is None or not parsed_command.known:
            await ui.append_activity(
                kind="error",
                title="Internal command",
                detail="Unknown internal command.",
                status="error",
            )
            return
        if parsed_command.command_intent() is not None:
            await ui.append_activity(
                kind="error",
                title="Internal command",
                detail=f"/{parsed_command.command.name} is not an internal local command.",
                status="error",
            )
            return
        await self._handle_builtin_command(ui, parsed_command)

    async def _resolve_music_query(self, ui: WebSocketUIAdapter, decision: MusicIntentDecision) -> str | None:
        """Prepares resolve music query for an internal Sonex flow.

        Typical use: Use this helper when nearby code needs resolve music query without duplicating the local rules.

        Example: await _resolve_music_query(ui=..., decision=...) -> returns the value used by the surrounding Sonex flow.
        """
        if decision.recommendation_index is None:
            return decision.query
        tracks = list(getattr(ui, "_last_recommendation_tracks", []) or [])
        index = decision.recommendation_index
        if not tracks:
            await ui.append_agent_message("No recommendation list is available in this session. Request recommendations first.")
            return None
        if index < 1 or index > len(tracks):
            await ui.append_agent_message(f"Recommendation number is out of range. Choose a number from 1 to {len(tracks)}.")
            return None
        track = tracks[index - 1]
        name = str(track.get("name") or track.get("title") or "").strip()
        artist = str(track.get("artist") or "").strip()
        if not artist:
            artists = track.get("artists") or []
            if artists:
                artist = str(artists[0])
        return " ".join(part for part in (name, artist) if part).strip() or None

    def _music_agent_intent(
        self,
        user_input: str,
        decision: MusicIntentDecision,
        *,
        provider_mode: str | None = None,
    ) -> CommandIntent:
        """Prepares music agent intent for an internal Sonex flow.

        Typical use: Use this helper when nearby code needs music agent intent without duplicating the local rules.

        Example: _music_agent_intent(user_input=..., decision=...) -> returns the value used by the surrounding Sonex flow.
        """
        mode_guidance = ""
        if provider_mode == "spotify":
            mode_guidance = (
                " Spotify Mode is active: pass provider='spotify' to Recommend and preserve "
                "Spotify as the explicit provider for Query and playback workflows unless "
                "the user explicitly requests another provider."
            )
        if decision.route == MusicIntentRoute.RECOMMEND:
            return CommandIntent(
                command="recommend",
                raw=user_input,
                args=decision.query or user_input,
                intent_prompt=(
                    "Call Recommend exactly once. Use only its returned tracks when present. "
                    "If it returns text_only=true, recommend from general music knowledge "
                    "without claiming catalog availability or playability. Return a concise "
                    "numbered text list, and end with a normal text question about "
                    "what the user wants to hear. Do not start playback or modify a playlist "
                    f"or queue.{mode_guidance}"
                ),
                allowed_tools=("Recommend",),
                max_tool_calls=1,
            )
        allowed_tools = tuple(
            schema["function"]["name"]
            for schema in self.tools.agent_schemas()
        )
        play_guidance = ""
        if decision.route in {
            MusicIntentRoute.EXPLICIT_PLAY,
            MusicIntentRoute.CONFIRM_TRACK_PLAY,
        }:
            play_guidance = (
                " The user is requesting playback. Use Call with playback.select when "
                "candidate choice is needed; do not execute a System Tool directly. "
                "If the user explicitly names a provider, pass provider and "
                "provider_constraint='hard' to playback.select."
            )
        is_playback = decision.route in {
            MusicIntentRoute.EXPLICIT_PLAY,
            MusicIntentRoute.CONFIRM_TRACK_PLAY,
        }
        return CommandIntent(
            command="general",
            raw=user_input,
            args="",
            intent_prompt=(
                "Answer normally and use only the compact Agent Tool surface. "
                "Never name or call internal System Tools."
                f"{play_guidance}{mode_guidance}"
            ),
            allowed_tools=allowed_tools,
            playback=is_playback,
        )

    async def _handle_builtin_command(self, ui: WebSocketUIAdapter, parsed_command: Any) -> None:
        """Prepares handle builtin command for an internal Sonex flow.

        Typical use: Use this helper when nearby code needs handle builtin command without duplicating the local rules.

        Example: await _handle_builtin_command(ui=..., parsed_command=...) -> returns the value used by the surrounding Sonex flow.
        """
        if parsed_command.raw == "/" or not parsed_command.name:
            await ui.send_help_panel(command_suggestions())
            await ui.append_activity(
                kind="status",
                title="Slash commands",
                detail="Showing slash command panel.",
                status="success",
            )
            return

        if not parsed_command.known and not parsed_command.args:
            suggestions = format_help(parsed_command.name)
            if not suggestions.startswith("Unknown command."):
                await ui.append_system_message(suggestions)
                await ui.append_activity(
                    kind="status",
                    title="Slash commands",
                    detail=suggestions,
                    status="success",
                )
                return

        if not parsed_command.known:
            message = f"Unknown command: /{parsed_command.name}. Type /help to view available commands."
            await ui.append_activity(
                kind="error",
                title="Unknown command",
                detail=message,
                status="error",
            )
            await ui.append_system_message(message)
            return

        command_name = parsed_command.command.name
        args = parsed_command.args

        if command_name == "help":
            prefix = args if args.startswith("/") else args
            commands = command_suggestions(prefix)
            if not commands:
                await ui.append_system_message(format_help(prefix))
                await ui.append_activity(
                    kind="status",
                    title="Slash commands",
                    detail=format_help(prefix),
                    status="success",
                )
                return
            await ui.send_help_panel(commands)
            await ui.append_activity(
                kind="status",
                title="Slash commands",
                detail="Showing slash command panel.",
                status="success",
            )
            return

        if command_name == "keymap":
            message = "The /keymap command is handled by the TUI for this session."
            await ui.append_system_message(message)
            await ui.append_activity(kind="status", title="TUI keymap", detail=message, status="success")
            return

        if command_name == "lang":
            message = "The /lang command is handled by the TUI for this session."
            await ui.append_system_message(message)
            await ui.append_activity(kind="status", title="TUI language", detail=message, status="success")
            return

        if command_name == "info":
            await ui.append_system_message(_format_runtime_info(_llm_auth_state()))
            return

        if command_name == "memory":
            if args.strip():
                await ui.append_system_message("Usage: /memory")
                return
            session = MemorySettingsSession(ui, self.memory_store)
            setattr(ui, "_memory_settings", session)
            await session.start()
            return

        if command_name == "settings":
            if args.strip():
                await ui.append_system_message("Usage: /settings")
                return
            session = MemorySettingsSession(ui, self.memory_store)
            setattr(ui, "_memory_settings", session)
            await session.show_settings()
            return

        if command_name == "login":
            if args.strip():
                await ui.append_system_message("Usage: /login")
                return
            setup = AuthSetupSession(ui, _default_provider_name(), None, self)
            setattr(ui, "_auth_setup", setup)
            await setup.start("Choose a model provider to connect or switch.")
            return

        if command_name == "queue":
            if self._spotify_mode_enabled(ui):
                await self._show_spotify_queue(ui)
                return
            await ui._send(_track_panel_payload("queue", "Queue", _queue_payload()))
            await ui.append_activity(kind="status", title="Queue", detail="Showing playback queue.", status="success")
            return

        if command_name == "spotify":
            await self._handle_spotify_mode_command(ui, args)
            return

        if command_name == "connect":
            await self._handle_music_connect(ui, args)
            return

        if command_name == "playlist":
            if self._spotify_mode_enabled(ui):
                await self._show_spotify_playlists(ui)
                return
            await self._handle_playlist_command(ui, args)
            return

        if command_name == "model":
            setup = ModelSelectionSession(ui)
            setattr(ui, "_model_setup", setup)
            await setup.start()
            return

        if command_name == "sandbox":
            await self._handle_sandbox_command(ui, args)
            return

        if command_name == "logout":
            await self._handle_logout(ui, args)
            return

        if command_name in LOCAL_PLAYBACK_CONTROL_TOOLS or command_name in {"next", "previous"}:
            await self._handle_playback_control(ui, command_name)
            return

        if command_name == "volume":
            await self._handle_local_playback_volume(ui, args)
            return

        if command_name in {"bye", "exit"}:
            await self._handle_bye(ui, messages=ui.transcript, reason=command_name)
            return

        message = f"Command '/{command_name}' is handled by the agent."
        await ui.append_activity(kind="status", title="Agent command", detail=message, status="success")

    async def _handle_playlist_command(self, ui: WebSocketUIAdapter, args: str) -> None:
        parts = args.split(maxsplit=1)
        action = parts[0].casefold() if parts else ""
        rest = parts[1].strip() if len(parts) > 1 else ""
        if action == "save":
            await self._start_playlist_save(ui, rest)
            return
        if not args.strip():
            await self._show_playlist_browse(ui)
            return
        playlist_name = args.strip() or LIKES_PLAYLIST
        await ui._send(_track_panel_payload("playlist", f"Playlist: {playlist_name}", playlist_panel_tracks(playlist_name)))
        await ui.append_activity(
            kind="status",
            title="Playlist",
            detail=f"Showing playlist: {playlist_name}.",
            status="success",
        )

    async def _handle_memory_panel_action(self, ui: WebSocketUIAdapter, payload: dict[str, Any]) -> None:
        session = getattr(ui, "_memory_settings", None)
        if session is None:
            session = MemorySettingsSession(ui, self.memory_store)
            setattr(ui, "_memory_settings", session)
        action = str(payload.get("action") or "").strip()
        target = str(payload.get("target") or "").strip()
        entry_id = str(payload.get("entry_id") or "").strip()
        content = str(payload.get("content") or "")
        if action == "close":
            setattr(ui, "_memory_settings", None)
            return
        if action == "sources":
            await session.show_sources()
            return
        if action == "root":
            await session.start()
            return
        if action == "open" and target in {"user", "memory", "dump"}:
            await session.show_entries(target)
            return
        if action == "detail" and target in {"user", "memory", "dump"}:
            await session.show_detail(target, entry_id)
            return
        if action == "revisions" and target in {"user", "memory"}:
            await session.show_revisions(target, entry_id)
            return
        if action == "settings":
            await session.show_settings()
            return
        if action == "format_scopes":
            await session.show_format_scopes()
            return
        if action == "rebuild":
            result = self.memory_store.rebuild_internal_metadata()
            if not result.get("success"):
                await ui.append_warning_message(str(result.get("error") or "Memory metadata could not be rebuilt."))
                return
            await ui.append_system_message(str(result.get("message") or "Memory metadata rebuilt."))
            await session.start()
            return
        if action == "format_confirm" and target in {"user", "memory", "all"}:
            await session.confirm_format(target)
            return
        result: dict[str, Any]
        if action == "add" and target in {"user", "memory"}:
            result = self.memory_store.add(target, content, source="explicit")
        elif action == "edit" and target in {"user", "memory"}:
            found = self.memory_store._find_entry(entry_id)
            if found is None:
                result = {"success": False, "error": "Entry not found."}
            else:
                result = self.memory_store.update(
                    target,
                    content,
                    previous_content=found[2].content,
                    source="explicit",
                )
        elif action == "forget":
            result = self.memory_store.forget(entry_id, reason="user")
        elif action == "recall":
            result = self.memory_store.recall(entry_id)
        elif action == "move" and target in {"user", "memory"}:
            result = self.memory_store.move(entry_id, target)
        elif action == "review_accept":
            result = self.memory_store.resolve_review(entry_id, accept=True)
        elif action == "review_reject":
            result = self.memory_store.resolve_review(entry_id, accept=False)
        elif action == "restore_revision":
            result = self.memory_store.restore_revision(entry_id, int(payload.get("value") or 0))
        elif action == "setting":
            key = str(payload.get("entry_id") or "")
            result = self.memory_store.update_settings({key: payload.get("value")})
        else:
            result = {"success": False, "error": "Unsupported memory action."}
        if not result.get("success"):
            await ui.append_warning_message(str(result.get("error") or "Memory could not be updated."))
            return
        await ui.append_system_message(str(result.get("message") or "Memory updated."))
        if action == "setting":
            await session.show_settings()
            return
        if target in {"user", "memory", "dump"}:
            await session.show_entries(target)

    async def _handle_track_panel_action(self, ui: WebSocketUIAdapter, payload: dict[str, Any]) -> None:
        action = str(payload.get("action") or "").strip()
        track = payload.get("track") if isinstance(payload.get("track"), dict) else {}
        if not track:
            message = "Selected track is no longer available."
            await ui.append_activity(kind="error", title="Track panel", detail=message, status="error")
            await ui.send_error(message)
            return
        if action == "queue_add":
            provider = str(track.get("provider") or track.get("source") or "local")
            ref = str(track.get("ref") or "").strip()
            resolved = resolve_track_reference(ref) if ref else None
            if resolved is None:
                ref = remember_track_reference(
                    provider,
                    track,
                    playable=not bool(track.get("requires_resolution")),
                )
                resolved = resolve_track_reference(ref)
            assert resolved is not None
            append_up_next_track(resolved)
            await ui._send({"type": "queue", "tracks": _queue_payload()})
            title = str(track.get("name") or track.get("title") or "selected track")
            await ui.append_activity(kind="status", title="Playback queue", detail=f"Added to playback queue: {title}.", status="success")
            return
        if action == "play":
            if str(payload.get("panel") or "") == "queue":
                await self._play_up_next_from_selection(ui, track)
                return
            await self._play_track_panel_track(ui, track)
            return
        message = f"Unsupported track panel action: {action or '-'}."
        await ui.append_activity(kind="error", title="Track panel", detail=message, status="error")
        await ui.send_error(message)

    async def _play_up_next_from_selection(
        self,
        ui: WebSocketUIAdapter,
        selected: dict[str, Any],
    ) -> None:
        """Play a selected queue head, skipping failed heads without retry loops."""
        state = up_next_snapshot()
        selected_ref = str(selected.get("ref") or "").strip()
        if not state["items"] or str(state["items"][0].get("ref") or "") != selected_ref:
            await self._play_track_panel_track(ui, selected)
            return

        failures: list[str] = []
        while state["items"]:
            current = dict(state["items"][0])
            if current.get("requires_resolution"):
                query = " ".join(
                    part
                    for part in (
                        str(current.get("name") or current.get("title") or "").strip(),
                        str(current.get("artist") or "").strip(),
                    )
                    if part and part != "-"
                )

                async def settle_legacy(result: dict[str, Any]) -> None:
                    if result.get("status") == "playback_completed":
                        consume_up_next_head()
                    else:
                        fail_up_next_head(str(result.get("message") or "Playback failed."))
                    await ui._send({"type": "queue", "tracks": _queue_payload()})

                session = PlaySelectionSession(
                    ui,
                    self,
                    query,
                    on_finish=lambda result: asyncio.create_task(settle_legacy(result)),
                )
                setattr(ui, "_play_selection", session)
                await session.start()
                return
            started, reason = await self._play_track_panel_track(
                ui,
                current,
                report_failure=False,
            )
            if started:
                consume_up_next_head()
                await ui._send({"type": "queue", "tracks": _queue_payload()})
                if failures:
                    await ui.send_error(
                        "Playback continued after skipping "
                        f"{len(failures)} queued track(s). Technical detail: "
                        + " ".join(failures)
                    )
                return
            failures.append(reason)
            state = fail_up_next_head(reason)

        await ui._send({"type": "queue", "tracks": _queue_payload()})
        await ui.send_error(
            "Playback failed. Technical detail: "
            + (" ".join(failures) if failures else "No queued track could be played.")
        )

    async def _play_track_panel_track(
        self,
        ui: WebSocketUIAdapter,
        track: dict[str, Any],
        *,
        report_failure: bool = True,
    ) -> tuple[bool, str]:
        if track.get("requires_resolution"):
            query = " ".join(
                part
                for part in (
                    str(track.get("name") or track.get("title") or "").strip(),
                    str(track.get("artist") or "").strip(),
                )
                if part and part != "-"
            )
            session = PlaySelectionSession(ui, self, query)
            setattr(ui, "_play_selection", session)
            await session.start()
            return True, ""

        uri = str(track.get("uri") or "")
        if uri.startswith("spotify:track:"):
            mode = getattr(ui, "_spotify_mode", {}) or {}
            args: dict[str, Any] = {"uri": uri}
            if mode.get("device_id"):
                args["device_id"] = mode["device_id"]
            result = await asyncio.to_thread(registry.invoke_system, "spotify_play", args)
            await self._sync_tool_result_ui(ui, "spotify_play", result)
            if _is_failed_tool_result(result):
                message = _friendly_runtime_error_message(result, fallback="Spotify playback failed.")
                if report_failure:
                    await ui.send_error(message)
                return False, message
            else:
                await ui.append_activity(kind="status", title="Spotify playback", detail="Playing selected playlist track.", status="success")
            return True, ""

        if str(track.get("provider") or "") == "netease":
            encrypted_id, separator, original_id = str(track.get("id") or "").partition("|")
            if separator and encrypted_id and original_id:
                result = await asyncio.to_thread(
                    registry.invoke_system,
                    "netease_play",
                    {
                        "encrypted_id": encrypted_id,
                        "original_id": original_id,
                    },
                )
                await self._sync_tool_result_ui(ui, "netease_play", result)
                if not _is_failed_tool_result(result):
                    return True, ""
                message = _friendly_runtime_error_message(
                    result,
                    fallback="NetEase playback failed.",
                )
            else:
                message = "NetEase track reference is incomplete."
            if report_failure:
                await ui.send_error(message)
            return False, message

        source_url = str(
            track.get("audio_path")
            or track.get("file_path")
            or track.get("path")
            or track.get("stream_url")
            or track.get("url")
            or track.get("youtube_url")
            or ""
        )
        if source_url:
            metadata = {**track, "name": str(track.get("name") or track.get("title") or "-")}
            result = await asyncio.to_thread(
                start_local_playback,
                tool="track_panel_play",
                source_url=source_url,
                source=str(track.get("provider") or track.get("source") or "playlist"),
                metadata=metadata,
                success_message="Playing selected playlist track.",
            )
            await self._sync_tool_result_ui(ui, "track_panel_play", result)
            if _is_failed_tool_result(result):
                message = _friendly_runtime_error_message(
                    result,
                    fallback="Local playback failed.",
                )
                if report_failure:
                    await ui.send_error(message)
                return False, message
            return True, ""

        message = "Selected track has no playable source."
        await ui.append_activity(kind="error", title="Track panel", detail=message, status="error")
        if report_failure:
            await ui.send_error(message)
        return False, message

    async def _handle_spotify_mode_command(self, ui: WebSocketUIAdapter, args: str) -> None:
        action = args.strip().casefold()
        if action:
            message = "Usage: /spotify"
            await ui.append_activity(kind="error", title="Spotify mode", detail=message, status="error")
            await ui.append_system_message(message)
            return
        if self._spotify_mode_enabled(ui):
            session = ProviderModeExitSession(ui, self, "spotify")
            setattr(ui, "_provider_mode_exit", session)
            await session.start()
            return
        await self._enter_spotify_mode(ui)

    async def _show_playlist_browse(self, ui: WebSocketUIAdapter) -> None:
        try:
            choices = playlist_choices(writable_only=False)
        except Exception:
            choices = []
        if not choices:
            choices = [{"value": f"playlist:{LIKES_PLAYLIST}", "label": LIKES_PLAYLIST, "description": "0 saved tracks"}]
        session = PlaylistBrowseSession(ui, choices)
        setattr(ui, "_playlist_browse", session)
        await session.start()

    async def _enter_spotify_mode(self, ui: WebSocketUIAdapter) -> None:
        account = await _run_spotify_mode_call(
            ui,
            func=lambda: spotify_account(requests_timeout=1.5),
            pending_detail="Checking Spotify account.",
            timeout_message=(
                "Spotify did not respond while checking your account. "
                "Try /spotify again after confirming Spotify is reachable."
            ),
        )
        if account is None:
            return
        if _is_failed_tool_result(account):
            message = _friendly_runtime_error_message(account, fallback="Could not check Spotify account.")
            await ui.append_activity(kind="error", title="Spotify mode", detail=message, status="error")
            await ui.append_system_message(message)
            return
        data = account.get("data") if isinstance(account, dict) else {}
        if not isinstance(data, dict) or not data.get("logged_in"):
            _clear_persistent_spotify_mode()
            message = "Spotify sign-in is required. Run /connect first."
            await ui.append_activity(kind="error", title="Spotify mode", detail=message, status="error")
            await ui.append_system_message(message)
            return
        if _product_is_known_non_premium(data.get("product")):
            _clear_persistent_spotify_mode()
            message = "Spotify mode requires Spotify Premium."
            await ui.append_activity(kind="error", title="Spotify mode", detail=message, status="error")
            await ui.append_system_message(message)
            return
        scopes = set(data.get("scopes") or [])
        missing_scopes = sorted(SPOTIFY_MODE_REQUIRED_SCOPES - scopes)
        if missing_scopes:
            _clear_persistent_spotify_mode()
            await self._start_spotify_reauthorization(ui, missing_scopes)
            return

        devices_result = await _run_spotify_mode_call(
            ui,
            func=spotify_devices,
            pending_detail="Loading Spotify Connect devices.",
            timeout_message=(
                "Spotify did not respond while loading Connect devices. "
                "Open Spotify on desktop or mobile, then try /spotify again."
            ),
        )
        if devices_result is None:
            return
        if not isinstance(devices_result, dict) or devices_result.get("status") != "success":
            message = _friendly_runtime_error_message(devices_result, fallback="Could not load Spotify Connect devices.")
            await ui.append_activity(kind="error", title="Spotify mode", detail=message, status="error")
            await ui.append_system_message(message)
            return
        devices_data = devices_result.get("data") if isinstance(devices_result.get("data"), dict) else {}
        devices = [device for device in devices_data.get("devices") or [] if isinstance(device, dict)]
        usable_devices = [device for device in devices if device.get("id") and not device.get("is_restricted")]
        if not usable_devices:
            message = "No usable Spotify Connect device found. Open Spotify on desktop or mobile first."
            await ui.append_activity(kind="error", title="Spotify mode", detail=message, status="error")
            await ui.append_system_message(message)
            return
        active_device = next((device for device in usable_devices if device.get("is_active")), None)
        if active_device:
            await self._commit_spotify_mode(ui, active_device, scopes)
            return
        session = SpotifyDeviceSelectionSession(
            ui,
            usable_devices,
            on_selected=lambda device: self._commit_spotify_mode(ui, device, scopes),
        )
        setattr(ui, "_spotify_device_selection", session)
        await session.start()

    async def _commit_spotify_mode(
        self,
        ui: WebSocketUIAdapter,
        device: dict[str, Any],
        scopes: set[str] | list[str] | None = None,
        *,
        announce: bool = True,
    ) -> None:
        mode = _spotify_mode_state(device, scopes)
        async def prepare_spotify() -> None:
            return None

        async def pause_previous(_provider: ProviderMode) -> None:
            return None

        async def commit_spotify(_provider: ProviderMode) -> None:
            setattr(ui, "_spotify_mode", mode)
            setattr(ui, "_spotify_library_synced", False)
            _persist_spotify_mode(mode)
            save_provider_mode_intent(ProviderModeState(provider=ProviderMode.SPOTIFY))
            await _send_spotify_mode(ui, mode)
            await _send_provider_mode(ui, ProviderMode.SPOTIFY)

        try:
            await self.provider_modes.switch(
                ProviderMode.SPOTIFY,
                prepare=prepare_spotify,
                pause_previous=pause_previous,
                commit=commit_spotify,
            )
        except Exception as exc:
            message = f"Spotify mode was not activated. {sanitize_error_message(exc)}"
            await ui.append_activity(kind="error", title="Provider switch", detail=message, status="error")
            await ui.append_system_message(message)
            return
        message = f"Spotify mode on: {device.get('name') or 'selected device'}."
        await ui.append_activity(kind="status", title="Spotify mode", detail=message, status="success")
        if announce:
            await ui.append_system_message(message)

    async def _exit_spotify_mode(self, ui: WebSocketUIAdapter) -> None:
        if self._spotify_mode_enabled(ui) and self.provider_modes.state.provider is not ProviderMode.SPOTIFY:
            await self.provider_modes.restore(ProviderModeState(provider=ProviderMode.SPOTIFY))
        mode = getattr(ui, "_spotify_mode", {}) or {}
        device_id = str(mode.get("device_id") or "")

        async def pause_current(_provider: ProviderMode) -> None:
            result = await _run_spotify_mode_call(
                ui,
                func=lambda: registry.invoke_system("spotify_pause", {"device_id": device_id} if device_id else {}),
                pending_detail="Pausing Spotify before leaving Spotify mode.",
                timeout_message="Could not pause Spotify; Spotify mode remains active.",
                failure_title="Spotify mode",
            )
            if result is None or _is_failed_tool_result(result):
                raise RuntimeError("Spotify did not confirm pause.")

        async def commit_normal(_provider: ProviderMode) -> None:
            setattr(ui, "_spotify_mode", None)
            setattr(ui, "_spotify_library_synced", False)
            setattr(ui, "_spotify_device_selection", None)
            setattr(ui, "_spotify_play_selection", None)
            _clear_persistent_spotify_mode()
            clear_provider_mode_intent()
            await _send_spotify_mode(ui, None)
            await _send_provider_mode(ui, ProviderMode.NORMAL)

        try:
            await self.provider_modes.exit(
                pause_current=pause_current,
                commit=commit_normal,
            )
        except Exception as exc:
            detail = sanitize_error_message(exc)
            await ui.append_activity(kind="error", title="Spotify mode", detail=detail, status="error")
            await ui.append_system_message(detail)
            return
        message = "Spotify mode off."
        await ui.append_activity(kind="status", title="Spotify mode", detail=message, status="success")
        await ui.append_system_message(message)

    async def _start_spotify_reauthorization(self, ui: WebSocketUIAdapter, missing_scopes: list[str]) -> None:
        setup = SpotifySetupSession(ui)
        setattr(ui, "_spotify_setup", setup)
        await setup.start_reauthorization(missing_scopes)

    async def _show_spotify_playlists(self, ui: WebSocketUIAdapter) -> None:
        coordinator = _spotify_session_requests(ui)
        await self._show_playlist_browse(ui)
        browse_session = getattr(ui, "_playlist_browse", None)

        if coordinator.playlist_sync_attempted:
            return

        state = load_spotify_library_sync_state()
        now = time.time()
        if state.is_fresh(now=now) and _spotify_mirror_external_ids():
            coordinator.playlist_sync_attempted = True
            coordinator.playlist_sync_succeeded = True
            coordinator.playlist_sync_message = "Using recently synchronized Spotify playlists."
            setattr(ui, "_spotify_library_synced", True)
            return

        cooldown = spotify_api_cooldown_remaining()
        if cooldown > 0:
            state.next_retry_at = max(state.next_retry_at, now + cooldown)
            save_spotify_library_sync_state(state)
        if state.is_backing_off(now=now):
            coordinator.playlist_sync_attempted = True
            retry_after = max(1, int(state.next_retry_at - now + 0.999))
            coordinator.playlist_sync_message = (
                f"Using local playlists; Spotify synchronization will retry after {retry_after} seconds."
            )
            await ui.append_activity(
                kind="status",
                title="Spotify playlists",
                detail=coordinator.playlist_sync_message,
                status="warning",
            )
            return

        coordinator.playlist_sync_attempted = True
        state.last_attempt_at = now
        save_spotify_library_sync_state(state)
        await ui.append_activity(
            kind="tool",
            title="Spotify playlists",
            detail="Showing local playlists while Spotify mirrors refresh in the background.",
            status="pending",
        )
        coordinator.playlist_sync_task = asyncio.create_task(
            self._run_spotify_playlist_sync(ui, browse_session)
        )
        # Start the task before returning so fast local/test implementations
        # can complete, while real network I/O remains detached and responsive.
        await asyncio.sleep(0)

    async def _run_spotify_playlist_sync(
        self,
        ui: WebSocketUIAdapter,
        browse_session: Any,
    ) -> tuple[bool, str]:
        """Run one background mirror refresh without blocking local browsing."""
        coordinator = _spotify_session_requests(ui)
        try:
            synced, message = await self._sync_spotify_library_to_playlists(ui)
        except Exception:
            message = "Spotify playlist synchronization stopped unexpectedly."
            state = load_spotify_library_sync_state()
            self._record_spotify_sync_failure(state, {"error_code": "SPOTIFY_SYNC_ERROR"})
            synced = False

        coordinator.playlist_sync_succeeded = synced
        coordinator.playlist_sync_message = message
        setattr(ui, "_spotify_library_synced", synced)
        if synced:
            await ui.append_activity(kind="status", title="Spotify playlists", detail=message, status="success")
            if getattr(ui, "_playlist_browse", None) is browse_session:
                await self._show_playlist_browse(ui)
        else:
            await ui.append_activity(
                kind="status",
                title="Spotify playlists",
                detail=f"{message} Existing local playlists remain available.",
                status="warning",
            )
            if not _spotify_mirror_external_ids():
                await ui.append_agent_message(message)
        if coordinator.playlist_sync_task is asyncio.current_task():
            coordinator.playlist_sync_task = None
        return synced, message

    @staticmethod
    def _record_spotify_sync_failure(state: SpotifyLibrarySyncState, result: Any) -> None:
        """Persist a retry boundary so reconnects do not repeat a failed burst."""
        code = (
            str(result.get("error_code") or "SPOTIFY_SYNC_ERROR")
            if isinstance(result, dict)
            else "SPOTIFY_SYNC_ERROR"
        )
        delay = SPOTIFY_LIBRARY_SYNC_FAILURE_BACKOFF_SECONDS
        if code == "SPOTIFY_RATE_LIMITED":
            delay = retry_after_seconds(result, fallback_seconds=delay)
        state.last_error_code = code
        state.next_retry_at = max(state.next_retry_at, time.time() + delay)
        save_spotify_library_sync_state(state)

    async def _sync_spotify_library_to_playlists(self, ui: WebSocketUIAdapter) -> tuple[bool, str]:
        state = load_spotify_library_sync_state()
        now = time.time()
        mirror_ids = _spotify_mirror_external_ids()
        full_saved_sync = (
            SPOTIFY_LIBRARY_EXTERNAL_ID not in mirror_ids
            or state.needs_full_saved_tracks_reconcile(now=now)
        )
        saved_ok, saved_tracks, saved_result = await _fetch_all_spotify_saved_tracks(
            ui,
            stop_at_added_at="" if full_saved_sync else state.saved_tracks_cursor,
        )
        if not saved_ok:
            self._record_spotify_sync_failure(state, saved_result)
            return False, _friendly_runtime_error_message(saved_result, fallback="Spotify Library sync failed.")
        if full_saved_sync or saved_tracks:
            tracks_to_store = saved_tracks
            if not full_saved_sync:
                persisted_tracks = await asyncio.to_thread(
                    list_playlist_tracks,
                    SPOTIFY_LIBRARY_PLAYLIST,
                    source_app="Spotify",
                    external_id=SPOTIFY_LIBRARY_EXTERNAL_ID,
                )
                tracks_to_store = _merge_spotify_saved_tracks(saved_tracks, persisted_tracks)
            await asyncio.to_thread(
                upsert_mirror_playlist,
                source_app="Spotify",
                name=SPOTIFY_LIBRARY_PLAYLIST,
                external_id=SPOTIFY_LIBRARY_EXTERNAL_ID,
                tracks=tracks_to_store,
            )
        cursors = [str(track.get("added_at") or "") for track in saved_tracks if track.get("added_at")]
        if cursors:
            state.saved_tracks_cursor = max([state.saved_tracks_cursor, *cursors])
        if full_saved_sync:
            state.last_full_saved_tracks_at = now
        save_spotify_library_sync_state(state)

        playlists_ok, playlists, result = await _fetch_all_spotify_playlists(ui)
        if not playlists_ok:
            self._record_spotify_sync_failure(state, result)
            return False, _friendly_runtime_error_message(result, fallback="Spotify playlists failed.")
        failures: list[str] = []
        stop_codes = {
            "SPOTIFY_PROXY_UNAVAILABLE",
            "SPOTIFY_CONNECT_TIMEOUT",
            "SPOTIFY_READ_TIMEOUT",
            "SPOTIFY_TLS_ERROR",
            "SPOTIFY_CONNECTION_ERROR",
            "SPOTIFY_RATE_LIMITED",
        }
        for playlist in playlists:
            playlist_id = str(playlist.get("id") or "").strip()
            if not playlist_id:
                continue
            snapshot_id = str(playlist.get("snapshot_id") or "").strip()
            if (
                snapshot_id
                and playlist_id in mirror_ids
                and state.playlist_snapshots.get(playlist_id) == snapshot_id
            ):
                continue
            ok, tracks, tracks_result = await _fetch_all_spotify_playlist_tracks(playlist_id, ui)
            if not ok:
                failures.append(
                    _friendly_runtime_error_message(
                        tracks_result,
                        fallback="Spotify playlist tracks failed.",
                    )
                )
                self._record_spotify_sync_failure(state, tracks_result)
                code = str(tracks_result.get("error_code") or "") if isinstance(tracks_result, dict) else ""
                if code in stop_codes:
                    break
                continue
            await asyncio.to_thread(
                upsert_mirror_playlist,
                source_app="Spotify",
                name=str(playlist.get("name") or "Untitled playlist"),
                external_id=playlist_id,
                tracks=tracks,
            )
            mirror_ids.add(playlist_id)
            if snapshot_id:
                state.playlist_snapshots[playlist_id] = snapshot_id
            save_spotify_library_sync_state(state)
        if failures:
            return False, failures[0]
        state.last_success_at = time.time()
        state.next_retry_at = 0.0
        state.last_error_code = ""
        save_spotify_library_sync_state(state)
        return True, "Spotify playlists synced."

    async def _show_spotify_queue(self, ui: WebSocketUIAdapter) -> None:
        async def fetch_queue() -> Any:
            return await _run_spotify_mode_call(
                ui,
                func=lambda: spotify_queue(50),
                pending_detail="Loading Spotify playback queue.",
                timeout_message="Spotify queue timed out while loading playback state. Try /queue again later.",
                failure_title="Spotify queue",
            )

        result, source = await _spotify_session_requests(ui).get_or_fetch(
            "queue",
            ttl_seconds=SPOTIFY_QUEUE_CACHE_TTL_SECONDS,
            fetch=fetch_queue,
            cacheable=_spotify_success_result,
        )
        if source == "cooldown":
            retry_after = max(1, int(spotify_api_cooldown_remaining() + 0.999))
            message = f"Spotify is rate limited; try /queue again after {retry_after} seconds."
            await ui.append_activity(kind="error", title="Spotify queue", detail=message, status="error")
            await ui.append_system_message(message)
            return
        if result is None:
            return
        if source == "stale_cache":
            await ui.append_activity(
                kind="status",
                title="Spotify queue",
                detail="Showing the last known Spotify queue during the rate-limit cooldown.",
                status="warning",
            )
        if not isinstance(result, dict) or result.get("status") != "success":
            message = _friendly_runtime_error_message(result, fallback="Spotify queue failed.")
            await ui.append_activity(kind="error", title="Spotify queue", detail=message, status="error")
            await ui.append_system_message(message)
            return
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        tracks = [item for item in data.get("tracks") or [] if isinstance(item, dict)]
        await ui._send(_track_panel_payload("queue", "Spotify Queue", _spotify_track_panel_tracks(tracks)))
        detail = "Showing Spotify playback queue." if tracks else "Spotify playback queue is empty."
        await ui.append_activity(kind="status", title="Spotify queue", detail=detail, status="success")

    async def _start_playlist_save(self, ui: WebSocketUIAdapter, requested_playlist: str) -> None:
        track = getattr(ui, "_last_player_state", None)
        if not isinstance(track, dict) or not str(track.get("name") or track.get("title") or "").strip() or str(track.get("name") or track.get("title")).strip() == "-":
            message = "No current song is available to save."
            await ui.append_activity(kind="error", title="Playlist save", detail=message, status="error")
            await ui.append_system_message(message)
            return
        session = PlaylistSaveSession(ui, track)
        setattr(ui, "_playlist_save", session)
        await session.start(requested_playlist)

    async def _handle_playback_control(self, ui: WebSocketUIAdapter, command_name: str) -> None:
        """Routes internal playback controls to the active playback provider.

        Spotify pause/resume calls run off the event loop and target the mode's selected device.
        Other playback controls keep using the local playback controller.
        """
        if self._spotify_mode_enabled(ui) and command_name in SPOTIFY_PLAYBACK_CONTROL_TOOLS:
            tool_name = SPOTIFY_PLAYBACK_CONTROL_TOOLS[command_name]
            mode = getattr(ui, "_spotify_mode", None)
            device_id = str(mode.get("device_id") or "").strip() if isinstance(mode, dict) else ""
            args = {"device_id": device_id} if device_id else {}
            try:
                result = await _run_spotify_mode_call(
                    ui,
                    func=lambda: registry.invoke_system(tool_name, args),
                    pending_detail=f"{command_name.capitalize()} Spotify playback on the selected device.",
                    timeout_message=f"Spotify {command_name} timed out. Playback state will refresh automatically.",
                    failure_title="Spotify playback",
                )
                if result is not None:
                    await self._sync_tool_result_ui(ui, tool_name, result)
            finally:
                _request_spotify_sync(ui)
            return

        tool_name = LOCAL_PLAYBACK_CONTROL_TOOLS.get(command_name)
        if tool_name is None:
            await ui.append_system_message(f"/{command_name} is only available in a provider mode.")
            return
        try:
            result = registry.invoke_system(tool_name, {})
        except Exception as exc:
            result = {
                "status": "fail",
                "tool": tool_name,
                "message": sanitize_error_message(exc),
                "error_code": "PLAYBACK_CONTROL_FAILED",
                "data": {},
            }
        await self._sync_tool_result_ui(ui, tool_name, result)

    async def _handle_local_playback_volume(self, ui: WebSocketUIAdapter, args: str) -> None:
        """Prepares handle local playback volume for an internal Sonex flow.

        Typical use: Use this helper when nearby code needs handle local playback volume without duplicating the local rules.

        Example: await _handle_local_playback_volume(ui=..., args=...) -> returns the value used by the surrounding Sonex flow.
        """
        try:
            volume = int(args.strip())
            if not 0 <= volume <= 100:
                raise ValueError
        except ValueError:
            message = "Usage: /volume <0-100>"
            await ui.append_activity(kind="error", title="Invalid volume", detail=message, status="error")
            await ui.append_system_message(message)
            return

        tool_name = "local_playback_volume"
        try:
            result = registry.invoke_system(tool_name, {"volume_percent": volume})
        except Exception as exc:
            result = {
                "status": "fail",
                "tool": tool_name,
                "message": sanitize_error_message(exc),
                "error_code": "PLAYBACK_CONTROL_FAILED",
                "data": {},
            }
        await self._sync_tool_result_ui(ui, tool_name, result)

    async def _handle_music_connect(
        self,
        ui: WebSocketUIAdapter,
        args: str = "",
    ) -> None:
        if args.strip():
            message = "Usage: /connect"
            await ui.append_activity(
                kind="error",
                title="Music connections",
                detail=message,
                status="error",
            )
            await ui.append_system_message(message)
            return
        if self._music_connection_manager_instance is None:
            self._music_connection_manager_instance = self._music_connection_manager_factory()
        session = ConnectionSelectionSession(
            ui,
            self,
            self._music_connection_manager_instance,
        )
        setattr(ui, "_music_connection_selection", session)
        await session.start()

    async def _start_agent_connection_interaction(
        self,
        ui: WebSocketUIAdapter,
        request: dict[str, Any],
        *,
        complete: Callable[[dict[str, Any]], None],
    ) -> None:
        """Suspend the Agent until a provider connection reaches a terminal state."""
        data = request.get("data") if isinstance(request.get("data"), dict) else {}
        provider_id = str(data.get("provider") or "").strip().casefold()
        done = False
        timeout_task: asyncio.Task[None] | None = None
        setattr(ui, "_agent_connection_active", True)

        def finish(result: dict[str, Any]) -> None:
            nonlocal done
            if done:
                return
            done = True
            setattr(ui, "_agent_connection_active", False)
            if timeout_task is not None:
                timeout_task.cancel()
            complete(result)

        async def timeout() -> None:
            await asyncio.sleep(300)
            finish(
                {
                    "status": "cancelled",
                    "tool": "Connect",
                    "message": f"{provider_id} connection timed out.",
                    "data": {
                        "provider": provider_id,
                        "reason": "timeout",
                    },
                    "error_code": None,
                }
            )

        timeout_task = asyncio.create_task(timeout())
        await self._connect_music_provider(
            ui,
            provider_id,
            complete=finish,
        )

    async def _connect_music_provider(
        self,
        ui: WebSocketUIAdapter,
        provider_id: str,
        *,
        complete: Callable[[dict[str, Any]], None] | None = None,
        emit_feedback: bool = True,
    ) -> None:
        if self._music_connection_manager_instance is None:
            self._music_connection_manager_instance = self._music_connection_manager_factory()
        manager = self._music_connection_manager_instance
        if provider_id == "spotify":
            try:
                token = load_spotify_token()
            except Exception:
                token = None
            if token is None:
                async def remember_spotify(data: dict[str, Any]) -> None:
                    account_label = data.get("display_name")
                    manager.mark_connected("spotify", account_label=account_label)

                setup = SpotifySetupSession(
                    ui,
                    on_connected=remember_spotify,
                    on_completed=complete,
                    emit_feedback=emit_feedback,
                )
                setattr(ui, "_spotify_setup", setup)
                await setup.start()
                return
            account = await asyncio.to_thread(spotify_account, requests_timeout=1.5)
            if _is_failed_tool_result(account):
                message = _friendly_runtime_error_message(
                    account,
                    fallback="Spotify account check failed.",
                )
                if manager.record("spotify") is not None:
                    manager.mark_unavailable("spotify", reason=message)
                if emit_feedback:
                    await ui.append_activity(
                        kind="error",
                        title="Spotify connection",
                        detail=message,
                        status="error",
                    )
                    await ui.append_system_message(message)
                if complete is not None:
                    complete(
                        {
                            "status": "failed",
                            "tool": "Connect",
                            "message": message,
                            "data": {
                                "provider": "spotify",
                                "reason": "health_check_failed",
                            },
                            "error_code": "CONNECTION_FAILED",
                        }
                    )
                return
            data = account.get("data") if isinstance(account, dict) else {}
            if not isinstance(data, dict) or not data.get("logged_in"):
                setup = SpotifySetupSession(
                    ui,
                    on_completed=complete,
                    emit_feedback=emit_feedback,
                )
                setattr(ui, "_spotify_setup", setup)
                await setup.start()
                return
            account_label = data.get("display_name")
            manager.mark_connected("spotify", account_label=account_label)
            message = f"Spotify connected{f' · {account_label}' if account_label else ''}."
            if emit_feedback:
                await ui.append_activity(
                    kind="status",
                    title="Spotify connection",
                    detail=message,
                    status="success",
                )
                await ui.append_system_message(message)
            if complete is not None:
                complete(
                    {
                        "status": "connected",
                        "tool": "Connect",
                        "message": message,
                        "data": {
                            "provider": "spotify",
                            "account_label": account_label,
                        },
                        "error_code": None,
                    }
                )
            return

        if provider_id in {"jamendo", "audius"}:
            async def finish_open_audio(result: dict[str, Any]) -> None:
                if result.get("status") == "connected":
                    manager.mark_connected(
                        provider_id,
                        account_label=None,
                    )
                if complete is not None:
                    complete(
                        {
                            "status": str(result.get("status") or "failed"),
                            "tool": "Connect",
                            "message": (
                                f"{provider_id} is connected."
                                if result.get("status") == "connected"
                                else f"{provider_id} connection was cancelled."
                            ),
                            "data": {
                                "provider": provider_id,
                                "reason": result.get("reason"),
                            },
                            "error_code": (
                                None
                                if result.get("status") in {"connected", "cancelled"}
                                else "CONNECTION_FAILED"
                            ),
                        }
                    )

            setup = OpenAudioSetupSession(
                ui,
                provider_id,
                on_completed=finish_open_audio,
                emit_feedback=emit_feedback,
            )
            setattr(ui, "_auth_setup", setup)
            await setup.start()
            return

        if provider_id == "netease":
            worker = NetEaseProviderWorker()
            try:
                health = await asyncio.to_thread(worker.health)
            except Exception as exc:
                health = None
                message = sanitize_error_message(exc)
            else:
                message = health.reason or "NetEase is ready, with playback not yet verified."
            if health is not None and health.ready:
                manager.mark_connected("netease", account_label="ncm-cli")
                message = "NetEase connected · Ready, unverified playback."
                if emit_feedback:
                    await ui.append_activity(
                        kind="status",
                        title="NetEase connection",
                        detail=message,
                        status="success",
                    )
                    await ui.append_system_message(message)
                if complete is not None:
                    complete(
                        {
                            "status": "connected",
                            "tool": "Connect",
                            "message": message,
                            "data": {
                                "provider": "netease",
                                "verification": "unverified_playback",
                            },
                            "error_code": None,
                        }
                    )
                return
            if health is not None and health.login_available and not health.login_ready:
                def finish_netease(result: dict[str, Any]) -> None:
                    if result.get("status") == "connected":
                        manager.mark_connected("netease", account_label="ncm-cli")
                    if complete is not None:
                        complete(result)

                session = NetEaseLoginSession(
                    ui,
                    worker,
                    on_completed=finish_netease,
                    fallback_online=False,
                    emit_feedback=emit_feedback,
                )
                setattr(ui, "_netease_login_session", session)
                await session.start()
                return
            if emit_feedback:
                await ui.append_activity(
                    kind="error",
                    title="NetEase connection",
                    detail=message,
                    status="error",
                )
                await ui.append_system_message(message)
            if complete is not None:
                complete(
                    {
                        "status": "failed",
                        "tool": "Connect",
                        "message": message,
                        "data": {
                            "provider": "netease",
                            "reason": "worker_not_ready",
                        },
                        "error_code": "CONNECTION_NOT_READY",
                    }
                )
            return

        message = "Selected music connection is not available."
        if emit_feedback:
            await ui.append_activity(
                kind="error",
                title="Music connections",
                detail=message,
                status="error",
            )
            await ui.append_system_message(message)
        if complete is not None:
            complete(
                {
                    "status": "failed",
                    "tool": "Connect",
                    "message": message,
                    "data": {
                        "provider": provider_id,
                        "reason": "provider_unavailable",
                    },
                    "error_code": "PROVIDER_UNSUPPORTED",
                }
            )
    async def _handle_logout(self, ui: WebSocketUIAdapter, args: str = "") -> None:
        """Prepares handle logout for an internal Sonex flow.

        Typical use: Use this helper when nearby code needs handle logout without duplicating the local rules.

        Example: await _handle_logout(ui=...) -> returns the value used by the surrounding Sonex flow.
        """
        target = args.strip().casefold().replace("_", " ")
        if target:
            await ui.append_system_message("Usage: /logout")
            return

        netease_logged_out = await self._logout_netease(ui)
        state = _llm_auth_state()
        if not state.ready:
            if netease_logged_out:
                await self._clear_provider_modes_for_logout(ui)
                await ui.append_system_message("Signed out of NetEase.")
                await self._handle_bye(ui, messages=ui.transcript, reason="logout")
                return
            await ui.append_system_message("You are not logged in.")
            return

        if state.credential_source == "env":
            await ui.append_system_message(
                "Cannot clear environment variable credentials from the TUI. Remove the provider API key from your environment, then restart Sonex."
            )
            await self._clear_provider_modes_for_logout(ui)
            await self._handle_bye(ui, messages=ui.transcript, reason="logout")
            return

        if state.credential_source == "local" or state.auth_type == "local":
            await ui.append_system_message(f"Provider '{state.provider}' does not require login.")
            await self._clear_provider_modes_for_logout(ui)
            await self._handle_bye(ui, messages=ui.transcript, reason="logout")
            return

        if state.credential_source != "auth.json":
            await ui.append_system_message("You are not logged in.")
            return

        try:
            if state.provider == "openai" and state.auth_type == "oauth":
                await asyncio.to_thread(logout_chatgpt_subscription)
            if state.auth_type in {"api_key", "oauth"}:
                removed = remove_provider_method(state.provider, state.auth_type)
                if state.auth_type == "oauth":
                    clear_oauth_access_cache(state.provider)
            else:
                removed = True
            clear_default()
            os.environ.pop("SONEX_DEFAULT_PROVIDER", None)
            os.environ.pop("SONEX_DEFAULT_MODEL", None)
            ThinkingConfig._state = None
        except Exception as exc:
            await ui.append_system_message(sanitize_error_message(exc))
            return

        if not removed:
            await ui.append_system_message("You are not logged in.")
            return

        await self._clear_provider_modes_for_logout(ui)
        await ui.send_auth_state(_llm_auth_state())
        await ui.append_system_message(
            "Signed out of the active LLM connection. Other saved provider credentials were preserved."
        )
        await self._handle_bye(ui, messages=ui.transcript, reason="logout")

    async def _logout_netease(self, ui: WebSocketUIAdapter) -> bool:
        """Cancel QR login and clear NetEase session state and ncm-cli auth."""
        login_session = getattr(ui, "_netease_login_session", None)
        if login_session is not None:
            await login_session.cancel()
            task = getattr(login_session, "task", None)
            if isinstance(task, asyncio.Task):
                with suppress(asyncio.CancelledError):
                    await task
        setattr(ui, "_netease_login_session", None)
        setattr(ui, "_netease_login_offer", None)
        setattr(ui, "_netease_login_declined", False)
        setattr(ui, "_netease_verified_signature", None)
        if getattr(ui, "_preferred_playback_provider", None) == "netease":
            setattr(ui, "_preferred_playback_provider", None)
        if self._music_connection_manager_instance is None:
            self._music_connection_manager_instance = self._music_connection_manager_factory()
        manager = self._music_connection_manager_instance
        had_connection = manager.record("netease") is not None
        worker = NetEaseProviderWorker()
        logged_out = False
        try:
            if await asyncio.to_thread(worker.is_logged_in):
                logged_out = await asyncio.to_thread(worker.logout)
        except Exception as exc:
            logger.warning("NetEase logout check failed: %s", sanitize_error_message(exc))
        manager.remove("netease")
        return had_connection or logged_out

    async def _handle_bye(
        self,
        ui: WebSocketUIAdapter,
        *,
        messages: list[dict[str, Any]],
        reason: str,
    ) -> None:
        """Prepares handle bye for an internal Sonex flow.

        Typical use: Use this helper when nearby code needs handle bye without duplicating the local rules.

        Example: await _handle_bye(ui=..., messages=..., reason=...) -> returns the value used by the surrounding Sonex flow.
        """
        path = _save_session_transcript(
            messages,
            reason=reason,
            session_id=ui.session_id,
        )
        message = f"Session saved to {path}. Bye."
        await ui.append_activity(
            kind="status",
            title="Session saved",
            detail=str(path),
            status="success",
        )
        await ui.send_status(UiStatus(phase="Bye", message=message))
        await ui.append_system_message(message)
        await ui._send({"type": "bye", "path": str(path), "message": message})
        await ui.close()

    async def _handle_sandbox_command(self, ui: WebSocketUIAdapter, args: str) -> None:
        """Check and idempotently configure Sonex-owned sandbox resources."""
        if args.strip():
            message = "Usage: /sandbox"
            await ui.append_activity(
                kind="error",
                title="Sandbox",
                detail=message,
                status="error",
            )
            await ui.append_system_message(message)
            return
        report = await asyncio.to_thread(sandbox_manager().configure)
        if report.state.value == "ready":
            await ui.append_activity(
                kind="status",
                title="Sandbox",
                detail=report.message,
                status="success",
            )
            await ui.append_system_message(report.message)
            return
        message = report.message
        if report.missing:
            message = (
                f"{message} Missing requirement: {', '.join(report.missing)}. "
                "Install or enable it on the host, then run /sandbox again."
            )
        await ui.append_activity(
            kind="error",
            title="Sandbox",
            detail=message,
            status="error",
        )
        await ui.append_system_message(message)

    async def _sync_tool_result_ui(
        self,
        ui: WebSocketUIAdapter,
        tool_name: str,
        tool_result: Any,
        activity_id: str | None = None,
    ) -> None:
        """Prepares sync tool result ui for an internal Sonex flow.

        Typical use: Use this helper when nearby code needs sync tool result ui without duplicating the local rules.

        Example: await _sync_tool_result_ui(ui=..., tool_name=..., tool_result=..., activity_id=...) -> returns the value used by the surrounding Sonex flow.
        """
        title, detail, activity_status = _format_tool_result(tool_name, tool_result)
        await ui.append_activity(
            kind="tool",
            title=title,
            detail=detail,
            status=activity_status,
            activity_id=activity_id,
        )

        search_tracks = _search_results_payload(tool_result) if tool_name in SEARCH_RESULT_TOOLS else []
        if search_tracks:
            setattr(ui, "_last_search_tracks", search_tracks)
            if tool_name in RECOMMENDATION_TOOLS or getattr(ui, "_recommendation_turn_active", False):
                setattr(ui, "_last_recommendation_tracks", search_tracks)
            await ui._send({"type": "search_results", "tracks": search_tracks})

        result_status = str(tool_result.get("status") or "").lower() if isinstance(tool_result, dict) else ""
        player_state, cover_url = _extract_music_state(tool_result)
        is_control_tool = tool_name in set(LOCAL_PLAYBACK_CONTROL_TOOLS.values())
        is_spotify_play_tool = tool_name == "spotify_play"
        if result_status == "success" and is_spotify_play_tool and player_state:
            player_state = _spotify_starting_player_state(player_state)
        should_sync_player = result_status == "success" and bool(
            player_state and (player_state.get("is_playing") or is_control_tool or is_spotify_play_tool)
        )
        if should_sync_player and player_state:
            player_state = _decorate_player_state(player_state)
            setattr(ui, "_last_player_state", player_state)
            await ui._send({"type": "player", "state": player_state})
            if tool_name not in SEARCH_RESULT_TOOLS and player_state.get("playback_status") != "starting":
                _remember_actual_playback(player_state)
                if tool_name in PLAYBACK_AGENT_TOOLS:
                    _record_playback_behavior(ui, player_state, force=True)
                await ui._send({"type": "queue", "tracks": _queue_payload()})
        if should_sync_player and cover_url:
            await ui.send_cover(cover_url)
        if result_status == "success" and is_spotify_play_tool:
            _request_spotify_sync(ui)
    async def _commit_agent_playback_selection(
        self,
        ui: WebSocketUIAdapter,
        *,
        selection_ref: str,
        turn_id: str,
        query: str,
        candidate: dict[str, Any],
        requested_provider: str | None,
        hard_provider: bool,
    ) -> dict[str, Any]:
        """Route one selected recording without returning control to the LLM."""
        finished: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()

        def finish(result: dict[str, Any]) -> None:
            if not finished.done():
                finished.set_result(result)

        async def play_selected(identity: RecordingIdentity) -> dict[str, Any]:
            local_candidate = (
                dict(candidate)
                if candidate.get("provider") == "local"
                else await asyncio.to_thread(
                    self._verified_cached_recording,
                    identity,
                )
            )
            local_path = (
                local_candidate.get("playback_path")
                if isinstance(local_candidate, dict)
                else None
            )
            if isinstance(local_candidate, dict) and local_path:
                playback = PlaySelectionSession(
                    ui,
                    self,
                    query,
                    on_finish=finish,
                )
                playback.selected_playback_metadata = dict(local_candidate)
                setattr(ui, "_play_selection", playback)
                local_result = await playback._invoke_playback(
                    "play_local_song",
                    {"query": str(local_path), "player": "auto"},
                )
                if _is_failed_tool_result(local_result):
                    await playback._finish("Local playback failed.", status="error")
                    return await finished
                if _is_player_confirm_result(local_result):
                    return await finished
                await ui.append_system_message(
                    format_agent_playing_feedback(local_result, local_candidate)
                )
                await playback._finish("Local playback selected.")
                return await finished
            selected_source = str(
                candidate.get("playback_source")
                or candidate.get("native_source")
                or requested_provider
                or ""
            ).casefold()
            if selected_source in {"netease", "spotify"} and (
                candidate.get("encrypted_id")
                or candidate.get("uri")
            ):
                readiness = await self._activate_authoritative_source(ui, selected_source)
                if readiness is None:
                    message = f"{self._provider_label(selected_source)} is no longer ready."
                    await ui.send_error(message)
                    return {
                        "status": "playback_failed",
                        "message": message,
                        "error_code": "AUTHORITATIVE_PROVIDER_UNAVAILABLE",
                        "data": {"provider": selected_source},
                    }
                native_result = await self._try_selected_native_provider(
                    ui,
                    identity=identity,
                    provider=selected_source,
                    selected_candidate=candidate,
                    readiness=readiness,
                )
                if native_result.get("status") == "playback_completed":
                    setattr(ui, "_preferred_playback_provider", selected_source)
                return native_result
            if selected_source == "online":
                authoritative_result = {
                    "status": "playback_failed",
                    "data": {"online_allowed": True},
                }
            else:
                authoritative_result = await self._route_authoritative_provider(
                    ui,
                    identity=identity,
                    selected_candidate=candidate,
                    requested_provider=requested_provider,
                    hard_provider=hard_provider,
                )
            if authoritative_result.get("status") == "playback_completed":
                return authoritative_result
            if hard_provider and selected_source != "online":
                await ui.send_error(
                    str(
                        authoritative_result.get("message")
                        or "The requested provider could not play the selected recording."
                    )
                )
                return authoritative_result
            community_allowed = bool(
                isinstance(authoritative_result.get("data"), dict)
                and authoritative_result["data"].get("online_allowed")
            )
            if not community_allowed:
                community_allowed = await self._confirm_agent_playback_route(
                    ui,
                    message=(
                        "No authoritative provider is available. "
                        "Try community audio sources?"
                    ),
                    stage="community_audio",
                    provider="community",
                )
            if not community_allowed:
                message = "Playback stopped because no authoritative provider was available."
                await ui.send_error(message)
                return {
                    "status": "playback_cancelled",
                    "message": message,
                    "error_code": None,
                    "data": {"reason": "community_audio_rejected"},
                }
            playback = PlaySelectionSession(
                ui,
                self,
                query,
                on_finish=finish,
            )
            playback.playback_source = "online"
            playback.selected_playback_metadata = dict(candidate)
            playback.selected_playback_metadata.setdefault("original_query", query)
            setattr(ui, "_play_selection", playback)
            resolved_query = str(
                candidate.get("youtube_query")
                or f"{identity.artist} {identity.title}"
            ).strip()
            await playback._play_selected_metadata_candidate(
                resolved_query or query,
                playback.selected_playback_metadata,
            )
            return await finished

        return await self._playback_coordinator.play(
            selection_ref,
            session_id=ui.session_id,
            turn_id=turn_id,
            play_selected=play_selected,
        )

    @staticmethod
    def _verified_cached_recording(
        identity: RecordingIdentity,
    ) -> dict[str, Any] | None:
        """Resolve only a complete on-disk cache item for the selected identity."""
        summary = find_best_cached_song(
            f"{identity.artist} {identity.title}".strip()
        )
        if not isinstance(summary, dict) or not summary.get("cache_id"):
            return None
        try:
            item = resolve_cached_song(str(summary["cache_id"]))
        except (KeyError, OSError, ValueError):
            return None
        path_text = str(
            item.get("audio_path")
            or item.get("file_path")
            or item.get("path")
            or ""
        ).strip()
        if not path_text or not Path(path_text).expanduser().is_file():
            return None
        if not recording_identity_matches(identity, item):
            return None
        return {
            **item,
            "provider": "local",
            "playback_path": path_text,
            "cached": True,
        }

    async def _confirm_agent_playback_route(
        self,
        ui: WebSocketUIAdapter,
        *,
        message: str,
        stage: str,
        provider: str,
    ) -> bool:
        session = AgentPlaybackRouteConfirmationSession(
            ui,
            message=message,
            stage=stage,
            provider=provider,
        )
        setattr(ui, "_agent_playback_route_confirmation", session)
        return await session.start()

    async def _probe_authoritative_providers(
        self,
        ui: WebSocketUIAdapter,
    ) -> list[ProviderReadiness]:
        """Probe authoritative routes concurrently within a bounded budget."""

        async def spotify_probe() -> ProviderReadiness:
            started = time.monotonic()
            try:
                account, devices_result = await asyncio.wait_for(
                    asyncio.gather(
                        asyncio.to_thread(spotify_account, requests_timeout=1.5),
                        asyncio.to_thread(spotify_devices),
                    ),
                    timeout=4,
                )
                data = account.get("data") if isinstance(account, dict) else {}
                data = data if isinstance(data, dict) else {}
                devices_data = (
                    devices_result.get("data")
                    if isinstance(devices_result, dict)
                    and isinstance(devices_result.get("data"), dict)
                    else {}
                )
                devices = [
                    device
                    for device in devices_data.get("devices") or []
                    if isinstance(device, dict)
                    and device.get("id")
                    and not device.get("is_restricted")
                ]
                active_device = next(
                    (device for device in devices if device.get("is_active")),
                    None,
                )
                selected_device = active_device or (devices[0] if devices else None)
                capabilities = data.get("capabilities")
                capabilities = capabilities if isinstance(capabilities, dict) else {}
                logged_in = bool(data.get("logged_in"))
                subscribed = not _product_is_known_non_premium(data.get("product"))
                transport_ready = selected_device is not None
                return ProviderReadiness(
                    "spotify",
                    configured=logged_in,
                    logged_in=logged_in,
                    subscription_ready=subscribed
                    and bool(capabilities.get("playback_control")),
                    transport_ready=transport_ready,
                    active_mode=self._spotify_mode_enabled(ui),
                    verified_success_rate=float(
                        (getattr(ui, "_provider_route_success", {}) or {}).get(
                            "spotify",
                            0.0,
                        )
                    ),
                    startup_latency_ms=int((time.monotonic() - started) * 1000),
                    capability_score=sum(bool(value) for value in capabilities.values()),
                    preferred=getattr(ui, "_preferred_playback_provider", None) == "spotify",
                    reason=(
                        None
                        if transport_ready
                        else "No active Spotify Connect device is available."
                    ),
                    details={
                        "device": selected_device,
                        "active_device": active_device,
                        "devices": devices,
                        "scopes": set(data.get("scopes") or []),
                    },
                )
            except Exception as exc:
                return ProviderReadiness(
                    "spotify",
                    False,
                    False,
                    False,
                    False,
                    reason=sanitize_error_message(exc),
                )

        async def netease_probe() -> ProviderReadiness:
            started = time.monotonic()
            worker = NetEaseProviderWorker()
            try:
                health = await asyncio.wait_for(
                    asyncio.to_thread(worker.health),
                    timeout=4,
                )
                signature = self._netease_health_signature(worker, health.version)
                verified = getattr(ui, "_netease_verified_signature", None) == signature
                if getattr(ui, "_netease_verified_signature", None) not in {None, signature}:
                    setattr(ui, "_netease_verified_signature", None)
                return ProviderReadiness(
                    "netease",
                    configured=health.login_available or health.login_ready,
                    logged_in=health.login_ready,
                    subscription_ready=True,
                    transport_ready=health.mpv_ready and health.ready,
                    session_verified=verified,
                    verified_success_rate=1.0 if verified else 0.0,
                    startup_latency_ms=int((time.monotonic() - started) * 1000),
                    capability_score=2 if health.ready else 0,
                    preferred=getattr(ui, "_preferred_playback_provider", None) == "netease",
                    reason=health.reason,
                    details={
                        "worker": worker,
                        "signature": signature,
                        "version": health.version,
                        "health": health,
                    },
                )
            except Exception as exc:
                return ProviderReadiness(
                    "netease",
                    False,
                    False,
                    True,
                    False,
                    reason=sanitize_error_message(exc),
                    details={"worker": worker},
                )

        snapshots = list(
            await asyncio.gather(
                spotify_probe(),
                netease_probe(),
            )
        )
        for snapshot in snapshots:
            await ui.append_activity(
                kind="tool",
                title=f"{self._provider_label(snapshot.provider)} readiness",
                detail="Ready." if snapshot.ready else str(snapshot.reason or "Unavailable."),
                status="success" if snapshot.ready else "error",
            )
        return snapshots

    async def _select_playback_source(
        self,
        ui: WebSocketUIAdapter,
        *,
        requested_provider: str | None = None,
        hard_provider: bool = False,
        exclude: str | None = None,
    ) -> str | None:
        """Resolve the source that owns a single-song search before searching."""
        requested = str(requested_provider or "").strip().casefold()
        excluded = str(exclude or "").strip().casefold()
        if requested in {"online", "metadata", "online_audio"}:
            return None if excluded == "online" else "online"

        snapshots = await self._probe_authoritative_providers(ui)
        by_provider = {snapshot.provider: snapshot for snapshot in snapshots}
        if requested in {"netease", "spotify"}:
            snapshot = by_provider.get(requested)
            if snapshot is not None and snapshot.ready:
                return None if excluded == requested else requested
            recovered = await self._recover_explicit_provider(ui, requested, snapshot)
            if recovered is not None and recovered.ready and excluded != requested:
                return requested
            return None

        if self._spotify_mode_enabled(ui) and excluded != "spotify":
            snapshot = by_provider.get("spotify")
            if snapshot is not None and snapshot.ready:
                return "spotify"

        preferred = str(getattr(ui, "_preferred_playback_provider", None) or "").casefold()
        if preferred in {"netease", "spotify"} and preferred != excluded:
            snapshot = by_provider.get(preferred)
            if snapshot is not None and snapshot.ready:
                return preferred

        sources = [
            provider
            for provider in ("netease", "spotify")
            if provider != excluded
            and by_provider.get(provider) is not None
            and by_provider[provider].ready
        ]
        if excluded != "online":
            sources.append("online")
        if not sources:
            return None
        if not any(provider in {"netease", "spotify"} for provider in sources):
            return "online"

        session = PlaybackSourceSelectionSession(ui, sources, exclude=excluded or None)
        setattr(ui, "_playback_source_selection", session)
        await session.start()
        return await session.result

    async def _search_authoritative_candidates(
        self,
        ui: WebSocketUIAdapter,
        provider: str,
        query: str,
    ) -> list[dict[str, Any]]:
        """Search one authoritative catalog and keep its native references."""
        normalized_provider = str(provider or "").strip().casefold()
        label = PlaybackSourceSelectionSession.SOURCE_LABELS.get(
            normalized_provider,
            (normalized_provider.title(), normalized_provider),
        )[0]
        await ui.append_activity(
            kind="tool",
            title=f"Searching {label}",
            detail=f"Finding {label} tracks for {query}.",
            status="pending",
        )
        if normalized_provider == "netease":
            worker = NetEaseProviderWorker()
            tracks = await asyncio.wait_for(
                asyncio.to_thread(worker.search, query, limit=5),
                timeout=4,
            )
            candidates: list[dict[str, Any]] = []
            seen: set[str] = set()
            for track in tracks:
                if not isinstance(track, dict) or track.get("playable") is False:
                    continue
                encrypted_id = str(track.get("encrypted_id") or "").strip()
                original_id = str(track.get("original_id") or "").strip()
                if not encrypted_id or not original_id:
                    continue
                key = f"{encrypted_id}|{original_id}"
                if key in seen:
                    continue
                seen.add(key)
                title = track.get("title") or track.get("name")
                candidates.append(
                    {
                        **track,
                        "provider": "netease",
                        "metadata_source": "netease",
                        "name": title,
                        "title": title,
                        "native_source": "netease",
                    }
                )
            return candidates[:5]
        if normalized_provider == "spotify":
            query_plan = build_music_search_query_plan(query)
            tracks = await asyncio.to_thread(
                search_spotify_track_candidates,
                query_plan.original_query or query,
                5,
                query_variants=query_plan.variants,
            )
            return [
                {
                    **track,
                    "provider": "spotify",
                    "metadata_source": "spotify",
                    "native_source": "spotify",
                }
                for track in tracks[:5]
                if str(track.get("uri") or "").startswith("spotify:track:")
            ]
        raise ValueError(f"Unsupported authoritative playback provider: {provider}")

    async def _activate_authoritative_source(
        self,
        ui: WebSocketUIAdapter,
        provider: str,
    ) -> ProviderReadiness | None:
        snapshots = await self._probe_authoritative_providers(ui)
        readiness = next(
            (snapshot for snapshot in snapshots if snapshot.provider == provider),
            None,
        )
        if readiness is None or not readiness.ready:
            return None
        if provider == "spotify" and not readiness.details.get("active_device"):
            recovered = await self._recover_explicit_provider(ui, provider, readiness)
            if recovered is None:
                return None
            readiness = recovered
        if not await self._ensure_authoritative_mode(ui, readiness):
            return None
        return readiness

    async def _handoff_previous_provider(self, ui: WebSocketUIAdapter, new_provider: str) -> None:
        """Stop the previous Sonex-owned source after a new source starts."""
        previous = str(
            getattr(ui, "_active_playback_provider", None)
            or getattr(ui, "_preferred_playback_provider", None)
            or ""
        ).casefold()
        if not previous or previous == new_provider:
            return
        try:
            if previous == "spotify":
                mode = getattr(ui, "_spotify_mode", {}) or {}
                args = {"device_id": mode.get("device_id")} if mode.get("device_id") else {}
                await asyncio.to_thread(registry.invoke_system, "spotify_pause", args)
            elif previous == "netease":
                worker = getattr(ui, "_active_netease_worker", None)
                if not isinstance(worker, NetEaseProviderWorker):
                    worker = NetEaseProviderWorker()
                await asyncio.to_thread(worker.control, "stop")
            elif previous in {"online", "local"}:
                await asyncio.to_thread(registry.invoke_system, "local_playback_stop", {})
        except Exception as exc:
            await ui.append_activity(
                kind="warning",
                title="Playback handoff",
                detail=f"Previous {previous} playback could not be stopped: {sanitize_error_message(exc)}",
                status="warning",
            )

    @staticmethod
    def _netease_health_signature(
        worker: NetEaseProviderWorker,
        version: str | None,
    ) -> tuple[str, str | None, int | None]:
        try:
            config_mtime = worker.config_dir.stat().st_mtime_ns
        except OSError:
            config_mtime = None
        return (str(worker.executable or ""), version, config_mtime)

    @staticmethod
    def _provider_label(provider: str) -> str:
        return {
            "spotify": "Spotify",
            "netease": "NetEase",
        }.get(provider, provider)

    async def _route_authoritative_provider(
        self,
        ui: WebSocketUIAdapter,
        *,
        identity: RecordingIdentity,
        selected_candidate: dict[str, Any],
        requested_provider: str | None,
        hard_provider: bool,
    ) -> dict[str, Any]:
        requested = str(requested_provider or "").strip().casefold()
        snapshots = await self._probe_authoritative_providers(ui)
        ranked = rank_authoritative_providers(
            snapshots,
            requested_provider=requested if hard_provider else None,
        )
        if hard_provider and requested and not ranked:
            requested_snapshot = next(
                (
                    snapshot
                    for snapshot in snapshots
                    if snapshot.provider == requested
                ),
                None,
            )
            recovered = await self._recover_explicit_provider(
                ui,
                requested,
                requested_snapshot,
            )
            if recovered is not None:
                ranked = [recovered]
        failures: list[str] = []
        for snapshot in ranked:
            if not snapshot.active_mode and not snapshot.session_verified:
                label = self._provider_label(snapshot.provider)
                if snapshot.provider == "netease":
                    message = (
                        f"Use NetEase for this session and play "
                        f"{identity.artist} — {identity.title} via ncm-cli/mpv?"
                    )
                else:
                    message = (
                        f"Use {label} Mode and play "
                        f"{identity.artist} — {identity.title}?"
                    )
                allowed = await self._confirm_agent_playback_route(
                    ui,
                    message=message,
                    stage="authoritative_provider",
                    provider=snapshot.provider,
                )
                if not allowed:
                    failures.append(f"{label} was rejected.")
                    if hard_provider:
                        break
                    continue
            mode_ready = await self._ensure_authoritative_mode(ui, snapshot)
            if not mode_ready:
                failures.append(
                    snapshot.reason
                    or f"{self._provider_label(snapshot.provider)} Mode is unavailable."
                )
                if hard_provider:
                    break
                continue
            result = await self._try_selected_native_provider(
                ui,
                identity=identity,
                provider=snapshot.provider,
                selected_candidate=selected_candidate,
                readiness=snapshot,
            )
            if result.get("status") == "playback_completed":
                successes = dict(getattr(ui, "_provider_route_success", {}) or {})
                successes[snapshot.provider] = 1.0
                setattr(ui, "_provider_route_success", successes)
                if snapshot.provider == "netease":
                    setattr(
                        ui,
                        "_netease_verified_signature",
                        snapshot.details.get("signature"),
                    )
                setattr(ui, "_preferred_playback_provider", snapshot.provider)
                return result
            failures.append(str(result.get("message") or "Playback failed."))
            if snapshot.provider == "netease":
                setattr(ui, "_netease_verified_signature", None)
            if hard_provider:
                break
        if not hard_provider:
            netease_snapshot = next(
                (snapshot for snapshot in snapshots if snapshot.provider == "netease"),
                None,
            )
            health = (
                netease_snapshot.details.get("health")
                if netease_snapshot is not None
                else None
            )
            if (
                health is not None
                and health.login_available
                and not health.login_ready
                and not getattr(ui, "_netease_login_declined", False)
            ):
                recovered, outcome = await self._offer_netease_login(
                    ui,
                    fallback_online=True,
                    readiness=netease_snapshot,
                )
                if recovered is not None:
                    result = await self._try_selected_native_provider(
                        ui,
                        identity=identity,
                        provider="netease",
                        selected_candidate=selected_candidate,
                        readiness=recovered,
                    )
                    if result.get("status") == "playback_completed":
                        setattr(ui, "_preferred_playback_provider", "netease")
                        setattr(ui, "_netease_verified_signature", recovered.details.get("signature"))
                        return result
                    failures.append(str(result.get("message") or "NetEase playback failed."))
                if outcome in {"online", "cancelled", "failed", "timeout"}:
                    return {
                        "status": "playback_failed",
                        "message": "Continue with online playback.",
                        "error_code": "AUTHORITATIVE_PROVIDER_UNAVAILABLE",
                        "data": {"provider": None, "attempted": [item.provider for item in ranked], "online_allowed": True},
                    }
        message = (
            " ".join(dict.fromkeys(failures))
            if failures
            else (
                f"{self._provider_label(requested)} is not ready."
                if hard_provider and requested
                else "No authoritative provider is ready."
            )
        )
        return {
            "status": "playback_failed",
            "message": message,
            "error_code": "AUTHORITATIVE_PROVIDER_UNAVAILABLE",
            "data": {
                "provider": requested or None,
                "attempted": [snapshot.provider for snapshot in ranked],
            },
        }

    async def _recover_explicit_provider(
        self,
        ui: WebSocketUIAdapter,
        provider: str,
        readiness: ProviderReadiness | None,
        *,
        allow_setup: bool = True,
    ) -> ProviderReadiness | None:
        """Enter setup or Mode for an explicitly constrained provider."""
        if provider == "netease":
            health = readiness.details.get("health") if readiness is not None else None
            if health is None or not health.login_available or health.login_ready:
                return None
            recovered, outcome = await self._offer_netease_login(
                ui,
                fallback_online=False,
                readiness=readiness,
            )
            if outcome != "connected":
                setattr(ui, "_netease_login_declined", True)
            return recovered
        if provider != "spotify":
            return None
        if readiness is None or not readiness.configured or not readiness.logged_in:
            if not allow_setup:
                return None
            completed: asyncio.Future[dict[str, Any]] = (
                asyncio.get_running_loop().create_future()
            )

            def finish(result: dict[str, Any]) -> None:
                if not completed.done():
                    completed.set_result(result)

            setattr(ui, "_agent_connection_active", True)
            try:
                await self._connect_music_provider(
                    ui,
                    provider,
                    complete=finish,
                )
                connection = await completed
            finally:
                setattr(ui, "_agent_connection_active", False)
            if connection.get("status") != "connected":
                return None
            refreshed = await self._probe_authoritative_providers(ui)
            readiness = next(
                (
                    snapshot
                    for snapshot in refreshed
                    if snapshot.provider == provider
                ),
                None,
            )
            return await self._recover_explicit_provider(
                ui,
                provider,
                readiness,
                allow_setup=False,
            )

        devices = [
            device
            for device in readiness.details.get("devices") or []
            if isinstance(device, dict)
            and device.get("id")
            and not device.get("is_restricted")
        ]
        if not devices:
            await ui.append_activity(
                kind="error",
                title="Spotify readiness",
                detail=(
                    "Open Spotify on desktop or mobile, then retry this "
                    "explicit Spotify request."
                ),
                status="error",
            )
            return None
        selected: asyncio.Future[dict[str, Any] | None] = (
            asyncio.get_running_loop().create_future()
        )

        async def commit(device: dict[str, Any]) -> None:
            await self._commit_spotify_mode(
                ui,
                device,
                readiness.details.get("scopes"),
                announce=False,
            )
            if not selected.done():
                selected.set_result(device)

        async def cancel() -> None:
            if not selected.done():
                selected.set_result(None)

        session = SpotifyDeviceSelectionSession(
            ui,
            devices,
            on_selected=commit,
            on_cancel=cancel,
        )
        setattr(ui, "_spotify_device_selection", session)
        await session.start()
        device = await selected
        if not isinstance(device, dict) or not self._spotify_mode_enabled(ui):
            return None
        return replace(
            readiness,
            transport_ready=True,
            active_mode=True,
            details={
                **dict(readiness.details),
                "device": device,
            },
        )

    async def _offer_netease_login(
        self,
        ui: WebSocketUIAdapter,
        *,
        fallback_online: bool,
        readiness: ProviderReadiness,
    ) -> tuple[ProviderReadiness | None, str]:
        offer = NetEaseLoginOfferSession(ui, fallback_online=fallback_online)
        setattr(ui, "_netease_login_offer", offer)
        choice = await offer.start()
        if choice != "scan":
            setattr(ui, "_netease_login_declined", True)
            return None, choice
        worker = readiness.details.get("worker")
        if not isinstance(worker, NetEaseProviderWorker):
            worker = NetEaseProviderWorker()
        session = NetEaseLoginSession(
            ui,
            worker,
            on_completed=None,
            fallback_online=fallback_online,
            emit_feedback=False,
        )
        setattr(ui, "_netease_login_session", session)
        await session.start()
        connection = await session.result
        if connection.get("status") != "connected":
            setattr(ui, "_netease_login_declined", True)
            return None, str(connection.get("status") or "failed")
        if self._music_connection_manager_instance is None:
            self._music_connection_manager_instance = self._music_connection_manager_factory()
        self._music_connection_manager_instance.mark_connected("netease", account_label="ncm-cli")
        refreshed = await self._probe_authoritative_providers(ui)
        recovered = next(
            (snapshot for snapshot in refreshed if snapshot.provider == "netease" and snapshot.ready),
            None,
        )
        if recovered is None:
            return None, "failed"
        return replace(recovered, session_verified=True), "connected"

    async def _ensure_authoritative_mode(
        self,
        ui: WebSocketUIAdapter,
        readiness: ProviderReadiness,
    ) -> bool:
        if readiness.provider == "spotify":
            if self._spotify_mode_enabled(ui):
                return True
            device = readiness.details.get("device")
            if not isinstance(device, dict):
                return False
            await self._commit_spotify_mode(
                ui,
                device,
                readiness.details.get("scopes"),
                announce=False,
            )
            return self._spotify_mode_enabled(ui)
        return readiness.provider == "netease"

    async def _try_selected_native_provider(
        self,
        ui: WebSocketUIAdapter,
        *,
        identity: RecordingIdentity,
        provider: str,
        selected_candidate: dict[str, Any],
        readiness: ProviderReadiness | None = None,
    ) -> dict[str, Any]:
        """Try one native provider only after verifying the selected identity."""
        query = f"{identity.artist} {identity.title}".strip()
        if provider == "netease":
            worker = (
                readiness.details.get("worker")
                if readiness is not None
                else None
            )
            if not isinstance(worker, NetEaseProviderWorker):
                worker = NetEaseProviderWorker()
            setattr(ui, "_active_netease_worker", worker)
            try:
                if readiness is None:
                    health = await asyncio.to_thread(worker.health)
                    if not health.ready:
                        raise RuntimeError(health.reason or "NetEase is not ready.")
                exact = selected_candidate if selected_candidate.get("encrypted_id") and selected_candidate.get("original_id") else None
                if exact is None:
                    # Compatibility for legacy queue entries that predate native
                    # candidate references. New interactive searches never use
                    # this branch.
                    tracks = await asyncio.wait_for(
                        asyncio.to_thread(worker.search, query, limit=5),
                        timeout=4,
                    )
                    exact = next(
                        (
                            track
                            for track in tracks
                            if track.get("playable") is not False
                            and recording_identity_matches(identity, track)
                        ),
                        None,
                    )
                if exact is None or exact.get("playable") is False:
                    raise RuntimeError("NetEase selected track is not playable.")
                data = await asyncio.wait_for(
                    asyncio.to_thread(
                        worker.play,
                        encrypted_id=str(exact.get("encrypted_id") or ""),
                        original_id=str(exact.get("original_id") or ""),
                    ),
                    timeout=6,
                )
            except Exception as exc:
                return {
                    "status": "playback_failed",
                    "message": sanitize_error_message(exc),
                    "error_code": "NETEASE_PLAYBACK_FAILED",
                    "data": {"provider": "netease"},
                }
            finally:
                if getattr(ui, "_active_netease_worker", None) is worker:
                    setattr(ui, "_active_netease_worker", None)
            result = {
                "status": "success",
                "tool": "netease_play",
                "message": "NetEase playback started.",
                "error_code": None,
                "data": {
                    **data,
                    "name": identity.title,
                    "artist": identity.artist,
                },
            }
            await self._handoff_previous_provider(ui, "netease")
            setattr(ui, "_active_playback_provider", "netease")
            await self._sync_tool_result_ui(ui, "netease_play", result)
            await ui.append_system_message(
                format_agent_playing_feedback(result, selected_candidate)
            )
            return {
                "status": "playback_completed",
                "message": "NetEase playback started.",
                "error_code": None,
                "data": result["data"],
            }

        search_tool = "spotify_search"
        play_tool = "spotify_play"
        try:
            uri = selected_candidate.get("uri") or selected_candidate.get("spotify_uri")
            if not isinstance(uri, str) or not uri.startswith("spotify:track:"):
                # Compatibility for legacy queue entries. New interactive
                # Spotify candidates always carry their native URI.
                search_result = await asyncio.wait_for(
                    asyncio.to_thread(
                        registry.invoke_system,
                        search_tool,
                        {"query": query, "limit": 5},
                    ),
                    timeout=4,
                )
                tracks = _search_results_payload(search_result)
                exact = next(
                    (track for track in tracks if recording_identity_matches(identity, track)),
                    None,
                )
                if exact is None:
                    raise RuntimeError(
                        f"{provider} has no exact playable match for the selected recording."
                    )
                uri = exact.get("uri") or exact.get("ref")
            if not isinstance(uri, str) or not uri.startswith("spotify:track:"):
                raise RuntimeError("Spotify selected track has no playable URI.")
            play_result = await asyncio.wait_for(
                asyncio.to_thread(
                    registry.invoke_system,
                    play_tool,
                    {"uri": uri},
                ),
                timeout=6,
            )
        except Exception as exc:
            return {
                "status": "playback_failed",
                "message": sanitize_error_message(exc),
                "error_code": f"{provider.upper()}_PLAYBACK_FAILED",
                "data": {"provider": provider},
            }
        if _is_failed_tool_result(play_result):
            return {
                "status": "playback_failed",
                "message": str(play_result.get("message") or "Native provider playback failed."),
                "error_code": play_result.get("error_code"),
                "data": {"provider": provider},
            }
        await self._handoff_previous_provider(ui, "spotify")
        setattr(ui, "_active_playback_provider", "spotify")
        await self._sync_tool_result_ui(ui, play_tool, play_result)
        await ui.append_system_message(
            format_agent_playing_feedback(play_result, selected_candidate)
        )
        return {
            "status": "playback_completed",
            "message": str(play_result.get("message") or "Playback started."),
            "error_code": None,
            "data": dict(play_result.get("data") or {}),
        }

    async def _run_agent_turn(
        self,
        ui: WebSocketUIAdapter,
        user_input: str,
        command_intent: CommandIntent | None = None,
    ) -> None:
        """Prepares run agent turn for an internal Sonex flow.

        Typical use: Use this helper when nearby code needs run agent turn without duplicating the local rules.

        Example: await _run_agent_turn(ui=..., user_input=..., command_intent=...) -> returns the value used by the surrounding Sonex flow.
        """
        event_queue: asyncio.Queue[RunnerEvent] = asyncio.Queue()
        turn_id = _new_event_id("agent_turn")
        bind_memory_scope(ui.session_id, turn_id)
        interrupt_event = threading.Event()
        setattr(ui, "_active_agent_turn_id", turn_id)
        setattr(ui, "_agent_turn_interrupt_event", interrupt_event)
        await ui.send_agent_working_state(turn_id, active=True)
        self._confirm_queue = queue.Queue()
        tool_message_gate: queue.Queue[bool] = queue.Queue(maxsize=1)
        loop = asyncio.get_running_loop()
        tick_interval = 0.25
        current_phase = "Planning"
        current_message = "Planning..."
        planning_activity_id = _new_event_id("activity")
        planning_finished = False
        interaction_suspended = False
        completed_tool_results: list[Any] = []

        def emit(event: RunnerEvent) -> None:
            """Coordinates emit for the current Sonex flow.

            Typical use: Use this function when runtime code needs emit as part of a Sonex command, playback, auth, llm, or ui path.

            Example: emit(event=...) -> returns the value used by the surrounding Sonex flow.
            """
            if interrupt_event.is_set() and event.type != "done":
                return
            loop.call_soon_threadsafe(event_queue.put_nowait, event)

        def wait_for_confirm(confirm_id: str) -> Any:
            """Coordinates wait for confirm for the current Sonex flow.

            Typical use: Use this function when runtime code needs wait for confirm as part of a Sonex command, playback, auth, llm, or ui path.

            Example: wait_for_confirm(confirm_id=...) -> returns the value used by the surrounding Sonex flow.
            """
            while not interrupt_event.is_set():
                try:
                    incoming_id, decision = self._confirm_queue.get(timeout=0.1)
                except queue.Empty:
                    continue
                if not incoming_id or incoming_id == confirm_id:
                    return decision
            return {
                "status": "cancelled",
                "message": "Agent turn interrupted.",
                "data": {"reason": "user_interrupted", "turn_id": turn_id},
                "error_code": None,
            }

        def producer() -> None:
            """Coordinates producer for the current Sonex flow.

            Typical use: Use this function when runtime code needs producer as part of a Sonex command, playback, auth, llm, or ui path.

            Example: producer() -> returns the value used by the surrounding Sonex flow.
            """
            decision: Any = None
            try:
                if command_intent is None:
                    gen = agent_loop(user_input=user_input, tools=self.tools)
                else:
                    gen = agent_loop(user_input=user_input, tools=self.tools, command_intent=command_intent)
                while True:
                    if interrupt_event.is_set():
                        return
                    evt = gen.send(decision) if decision is not None else next(gen)
                    decision = None

                    if evt.type == "confirm":
                        confirm_id = _new_event_id("confirm")
                        confirm_payload = evt.args or {}
                        tool_args = confirm_payload.get("tool_args", confirm_payload)
                        emit(
                            RunnerEvent(
                                type="confirm",
                                data={
                                    "id": confirm_id,
                                    "tool_name": evt.tool,
                                    "tool_args": tool_args,
                                    "message": confirm_payload.get("message"),
                                    "warning": confirm_payload.get("warning"),
                                    "hide_hint": confirm_payload.get("hide_hint"),
                                    "choices": confirm_payload.get("choices"),
                                    "variant": confirm_payload.get("variant"),
                                    "commands": confirm_payload.get("commands"),
                                    "page_index": confirm_payload.get("page_index"),
                                    "page_count": confirm_payload.get("page_count"),
                                },
                            )
                        )
                        decision = wait_for_confirm(confirm_id)
                        emit(
                            RunnerEvent(
                                type="confirm_decision",
                                data={
                                    "id": confirm_id,
                                    "decision": decision,
                                    "variant": confirm_payload.get("variant"),
                                },
                            )
                        )
                        continue

                    if evt.type == "interaction":
                        request = (evt.args or {}).get("request")
                        interaction_id = _new_event_id("agent_interaction")
                        emit(
                            RunnerEvent(
                                type="interaction",
                                data={
                                    "id": interaction_id,
                                    "tool_name": evt.tool,
                                    "request": request,
                                },
                            )
                        )
                        decision = wait_for_confirm(interaction_id)
                        if (
                            isinstance(request, dict)
                            and request.get("status") == "requires_modify_confirmation"
                        ):
                            request_data = (
                                request.get("data")
                                if isinstance(request.get("data"), dict)
                                else {}
                            )
                            decision = complete_modify_confirmation(
                                str(request_data.get("confirmation_token") or ""),
                                decision,
                            )
                        continue

                    data: dict[str, Any] = {}
                    if evt.type == "status":
                        data = {"content": evt.content}
                    elif evt.type == "tool":
                        data = {
                            "tool_name": evt.tool,
                            "tool_args": evt.args or {},
                            "tool_result": evt.result,
                        }
                    elif evt.type == "tool_batch":
                        data = {"calls": evt.calls or []}
                    elif evt.type in {"tool_approved", "tool_rejected", "tool_blocked"}:
                        data = {
                            "calls": evt.calls or [],
                            **(evt.args or {}),
                        }
                    elif evt.type in {"error", "complete", "warning"}:
                        data = {"content": evt.content, "tool_name": evt.tool}

                    emit(RunnerEvent(type=evt.type, data=data))
                    if evt.type == "tool_batch":
                        if interrupt_event.is_set() or not tool_message_gate.get():
                            return
            except StopIteration:
                pass
            except Exception as exc:
                emit(
                    RunnerEvent(type="error", data={"content": sanitize_error_message(exc)})
                )
            finally:
                emit(RunnerEvent(type="done", data={}))

        async def send_current_status() -> None:
            """Sends current status to the active runtime client.

            Typical use: Use this function when runtime code needs send current status as part of a Sonex command, playback, auth, llm, or ui path.

            Example: await send_current_status() -> returns the value used by the surrounding Sonex flow.
            """
            await ui.send_status(
                UiStatus(phase=current_phase, message=current_message),
                active=True,
            )

        async def finish_planning(status: str, detail: str) -> None:
            """Coordinates finish planning for the current Sonex flow.

            Typical use: Use this function when runtime code needs finish planning as part of a Sonex command, playback, auth, llm, or ui path.

            Example: await finish_planning(status=..., detail=...) -> returns the value used by the surrounding Sonex flow.
            """
            nonlocal planning_finished
            if planning_finished:
                return
            planning_finished = True
            await ui.append_activity(
                kind="status",
                title="Planning",
                detail=detail,
                status=status,
                activity_id=planning_activity_id,
            )

        await send_current_status()
        await ui.append_activity(
            kind="status",
            title="Planning",
            detail=current_message,
            status="pending",
            activity_id=planning_activity_id,
        )

        producer_context = copy_context()
        producer_thread = threading.Thread(
            target=producer_context.run,
            args=(producer,),
            name="sonex-agent-turn",
            daemon=True,
        )
        producer_thread.start()
        active_tool_activity_id: str | None = None
        active_tool_name: str | None = None

        while True:
            try:
                event = await asyncio.wait_for(event_queue.get(), timeout=tick_interval)
            except asyncio.TimeoutError:
                if interrupt_event.is_set():
                    await finish_planning("error", "Agent turn interrupted.")
                    break
                if not interaction_suspended and not interrupt_event.is_set():
                    await send_current_status()
                continue

            if event.type == "done":
                await finish_planning(
                    "error" if interrupt_event.is_set() else "success",
                    "Agent turn interrupted." if interrupt_event.is_set() else "Planning complete.",
                )
                break

            if interrupt_event.is_set():
                if event.type == "tool_batch":
                    with suppress(queue.Full):
                        tool_message_gate.put_nowait(False)
                continue

            if event.type == "status":
                phase = event.data.get("content")
                current_phase = str(phase).title()
                current_message = f"{phase}..."
                await finish_planning("success", "Planning complete.")
                await send_current_status()
                if current_phase != "Planning":
                    await ui.append_activity(
                        kind="status",
                        title=current_phase,
                        detail=current_message,
                        status="pending",
                    )
                continue

            if event.type == "confirm":
                await finish_planning("success", "Planning complete.")
                tool_name = str(event.data.get("tool_name") or "tool")
                if event.data.get("variant") != "tool_call_review":
                    await ui.append_activity(
                        kind="confirm",
                        title=f"Confirm {tool_name}",
                        detail=event.data.get("message") or _format_args(event.data.get("tool_args")),
                        status="pending",
                        activity_id=str(event.data.get("id")),
                    )
                await ui.ask_confirm(event.data)
                continue

            if event.type == "confirm_decision":
                if event.data.get("variant") == "tool_call_review":
                    continue
                decision = str(event.data.get("decision") or "deny")
                confirmed = decision != "deny"
                await ui.append_activity(
                    kind="confirm",
                    title="Confirmed" if confirmed else "Rejected",
                    detail=decision,
                    status="success" if confirmed else "error",
                    activity_id=str(event.data.get("id")),
                )
                continue

            if event.type == "tool_approved":
                commands = event.data.get("commands") or []
                await ui.append_system_message(approved_commands_message(commands))
                continue

            if event.type == "tool_rejected":
                commands = event.data.get("commands") or []
                await ui.append_system_message(rejected_commands_message(commands))
                continue

            if event.type == "tool_blocked":
                commands = event.data.get("commands") or []
                rule_ids = event.data.get("rule_ids") or []
                command_rule_ids = event.data.get("command_rule_ids") or []
                await ui.append_system_message(
                    blocked_commands_message(
                        commands,
                        rule_ids,
                        command_rule_ids,
                    )
                )
                continue

            if event.type == "tool_batch":
                calls = event.data.get("calls") or []
                message = format_tool_batch(calls)
                delivered = False
                try:
                    if message.text:
                        await ui.append_agent_message(
                            message.text,
                            segments=message.segments,
                        )
                    delivered = not getattr(ui, "closed", False)
                finally:
                    tool_message_gate.put(delivered)
                continue

            if event.type == "interaction":
                interaction_suspended = True
                await finish_planning("success", "Planning complete.")
                await ui.send_status(
                    UiStatus(phase="Idle", message="Idle..."),
                    active=False,
                )
                interaction_id = str(event.data.get("id") or "")
                request = event.data.get("request")
                status = request.get("status") if isinstance(request, dict) else None

                def complete_interaction(result: dict[str, Any]) -> None:
                    self._confirm_queue.put((interaction_id, result))

                if status == "requires_play_selection":
                    data = request.get("data") if isinstance(request.get("data"), dict) else {}
                    query = str(data.get("query") or "").strip()
                    requested_provider = str(data.get("provider") or "").strip().casefold()
                    if requested_provider in {"", "current"}:
                        requested_provider = "spotify" if self._spotify_mode_enabled(ui) else ""
                    session = AgentCandidateSelectionSession(
                        ui,
                        self,
                        query,
                        interaction_id=interaction_id,
                        turn_id=turn_id,
                        requested_provider=requested_provider or None,
                        hard_provider=data.get("provider_constraint") == "hard",
                        complete=complete_interaction,
                        timeout_seconds=60,
                    )
                    setattr(ui, "_agent_candidate_selection", session)
                    await session.start()
                    continue
                if status == "requires_connection":
                    await self._start_agent_connection_interaction(
                        ui,
                        request,
                        complete=complete_interaction,
                    )
                    continue
                if status == "requires_modify_confirmation":
                    data = request.get("data") if isinstance(request.get("data"), dict) else {}
                    preview = data.get("preview") if isinstance(data.get("preview"), dict) else {}
                    operations = preview.get("operations") if isinstance(preview.get("operations"), list) else []
                    affected = int(preview.get("affected_tracks") or 0)
                    await ui.ask_confirm(
                        {
                            "id": interaction_id,
                            "variant": "modify_review",
                            "message": "Modify local music data",
                            "warning": (
                                f"This change affects {affected} track(s).\n"
                                + "\n".join(str(item) for item in operations)
                            ).strip(),
                            "choices": data.get("choices")
                            or [
                                {"value": "allow_once", "label": "Yes, apply changes"},
                                {"value": "deny", "label": "No"},
                            ],
                        }
                    )
                    continue
                complete_interaction(
                    {
                        "status": "failed",
                        "tool": str(event.data.get("tool_name") or "Agent Tool"),
                        "message": "Unknown suspended interaction.",
                        "data": {"reason": "unsupported_interaction"},
                        "error_code": "INTERACTION_UNSUPPORTED",
                    }
                )
                continue

            if event.type == "tool":
                interaction_suspended = False
                await finish_planning("success", "Planning complete.")
                tool_name = str(event.data.get("tool_name") or active_tool_name or "tool")
                tool_args = event.data.get("tool_args") or {}
                tool_result = event.data.get("tool_result")

                if tool_result is None and tool_args:
                    title, detail = _format_tool_start(tool_name, tool_args)
                    active_tool_name = tool_name
                    active_tool_activity_id = await ui.append_activity(
                        kind="tool",
                        title=title,
                        detail=detail,
                        status="pending",
                    )
                    continue

                await self._sync_tool_result_ui(ui, tool_name, tool_result, active_tool_activity_id)
                completed_tool_results.append(tool_result)
                if (
                    tool_name == "Recommend"
                    and isinstance(tool_result, dict)
                    and str(tool_result.get("status") or "").casefold() not in {"success", "ok"}
                ):
                    detail = str(
                        tool_result.get("message")
                        or "No credible recommendations are available."
                    )
                    await ui.send_error(f"Recommendation failed. Technical detail: {detail}")

                if _is_play_selection_request_result(tool_result):
                    query = _play_selection_query_from_result(tool_result)
                    if query:
                        session = PlaySelectionSession(ui, self, query)
                        setattr(ui, "_play_selection", session)
                        await session.start()

                active_tool_activity_id = None
                active_tool_name = None
                continue

            if event.type == "error":
                await finish_planning("error", str(event.data.get("content") or "Planning failed."))
                message = str(event.data.get("content") or "Agent failed.")
                friendly_message = _friendly_runtime_error_message(
                    {"message": message},
                    fallback="Agent failed.",
                )
                await ui.append_activity(
                    kind="error",
                    title="Agent error",
                    detail=friendly_message,
                    status="error",
                )
                await ui.append_agent_message(friendly_message)
                await ui.send_error(friendly_message)
                continue

            if event.type == "warning":
                await finish_planning("error", str(event.data.get("content") or "Agent warning."))
                message = str(event.data.get("content") or "Agent warning.")
                await ui.append_warning_message(message)
                continue

            if event.type == "complete":
                await finish_planning("success", "Planning complete.")
                content = str(event.data.get("content") or "")
                if content:
                    guarded = guard_agent_answer(content, completed_tool_results)
                    plain, document = normalize_agent_answer(guarded)
                    if isinstance(ui, WebSocketUIAdapter):
                        await ui.append_agent_message(plain, document=document, stream=True)
                    else:
                        await ui.append_agent_message(plain)
                if not isinstance(ui, WebSocketUIAdapter):
                    continue
                explicit_operation = explicit_memory_operation(user_input)
                explicit_memory = explicit_operation is not None
                memory_enabled = self.memory_store.long_term_enabled()
                if memory_enabled:
                    self.memory_store.enqueue_memory_candidate(user_input, turn_id)
                if explicit_memory:
                    if explicit_operation is not None and not safe_memory_content(explicit_operation.content):
                        await ui.append_warning_message("Sensitive information cannot be saved to long-term memory.")
                    elif memory_enabled:
                        await self._collect_turn_memory(ui, user_input, explicit=True)
                    else:
                        await ui.append_warning_message("Long-term memory is disabled.")
                else:
                    asyncio.create_task(
                        self._collect_turn_memory(ui, user_input, explicit=False)
                    )

        if producer_thread.is_alive() and not interrupt_event.is_set():
            await asyncio.to_thread(producer_thread.join)
        if getattr(ui, "_agent_turn_interrupt_event", None) is interrupt_event:
            setattr(ui, "_agent_turn_interrupt_event", None)
        setattr(ui, "_recommendation_turn_active", False)
        await ui.send_status(UiStatus(phase="Idle", message="Idle..."), active=False)
        queued: deque[str] = getattr(ui, "_agent_input_queue", deque())
        next_input = queued.popleft() if queued else None
        if getattr(ui, "_active_agent_turn_id", None) == turn_id:
            await ui.send_agent_working_state(turn_id, active=False)
            setattr(ui, "_active_agent_turn_id", None)
        setattr(ui, "_agent_turn_task", None)
        self._running_task = None
        if next_input is not None and not ui.closed:
            for item in ui.transcript:
                if (
                    item.get("role") == "user"
                    and item.get("content") == next_input
                    and item.get("execution") == "queued"
                ):
                    item["execution"] = "running"
                    break
            await self._handle_user_input(
                ui,
                next_input,
                append_user_message=False,
            )
