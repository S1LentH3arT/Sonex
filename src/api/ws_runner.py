"""Ws runner support for fastapi and websocket routing for the sonex runtime.

Implements the ws_runner module responsibilities used by Sonex runtime flows.
Key public entry points include search_youtube_songs, play_youtube_candidate, PlayRequestParse, AuthRuntimeState, WebSocketUIAdapter.
"""

from __future__ import annotations

import asyncio
import json
import os
import queue
import sys
import threading
import time
import uuid
import webbrowser
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import unquote
from typing import Any
from urllib.parse import parse_qs, urlparse

from fastapi import WebSocket, WebSocketDisconnect

from src.agent.core import agent_loop
from src.agent.events import RunnerEvent, UiStatus
from src.api.builtin_commands import BuiltinCommand, CommandIntent, command_suggestions, format_help, parse_builtin_command
from src.api.music_intent import (
    MusicIntentDecision,
    MusicIntentRoute,
    classify_music_intent,
    classify_music_intent_fast,
)
from src.auth.apple_music import (
    apple_music_setup_message,
    save_apple_music_credentials,
    save_apple_music_user_token,
)
from src.auth.browser_oauth import (
    BrowserOAuthConfigError,
    browser_oauth_requirements,
    browser_oauth_supported,
    run_browser_oauth,
)
from src.auth.oauth import ensure_oauth_token_usable
from src.auth.providers import get_provider_capability, normalize_provider, normalize_provider_model
from src.auth.spotify import (
    save_spotify_app_credentials,
    save_spotify_token_info,
    spotify_authorize_url,
    spotify_oauth_manager,
    spotify_redirect_uri,
)
from src.auth.store import get_provider_auth, load_auth_store, remove_provider, set_api_key, set_default
from src.llm.transport import ChatRequest, sanitize_error_message
from src.llm.models import model_choices_for_provider
from src.log import sonex_home
from src.memory.memory import memory_store
from src.thinking.config import ThinkingConfig
from src.tools import registry
from src.tools.local_play import search_local_file
from src.tools.online_play import (
    ONLINE_AUDIO_SETUP_MESSAGE,
    OnlineAudioSetupRequired,
    online_audio_configured,
    play_online_audio_candidate,
    resolve_online_playback_metadata,
    search_online_audio_candidates,
)
from src.tools.track_search import search_track_metadata_candidates

# Backward-compatible runner patch points; these now resolve the unified online-audio layer.
def search_youtube_songs(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
    """Search youtube songs.

    Coordinates search youtube songs logic for the surrounding Sonex flow.

    Args:
        args: Input value used by the search youtube songs operation.
        kwargs: Input value used by the search youtube songs operation.

    Returns:
        The computed result for search youtube songs.
    """
    return search_online_audio_candidates(*args, **kwargs)


def play_youtube_candidate(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Play youtube candidate.

    Coordinates play youtube candidate logic for the surrounding Sonex flow.

    Args:
        args: Input value used by the play youtube candidate operation.
        kwargs: Input value used by the play youtube candidate operation.

    Returns:
        The computed result for play youtube candidate.
    """
    return play_online_audio_candidate(*args, **kwargs)


_LEGACY_SEARCH_ALIAS = search_youtube_songs
_LEGACY_PLAY_ALIAS = play_youtube_candidate


def _search_online_audio_for_runner(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
    """Search online audio for runner.

    Coordinates search online audio for runner logic for the surrounding Sonex flow.

    Args:
        args: Input value used by the search online audio for runner operation.
        kwargs: Input value used by the search online audio for runner operation.

    Returns:
        The computed result for search online audio for runner.
    """
    if search_youtube_songs is not _LEGACY_SEARCH_ALIAS:
        return search_youtube_songs(*args, **kwargs)
    return search_online_audio_candidates(*args, **kwargs)


def _play_online_audio_for_runner(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Play online audio for runner.

    Coordinates play online audio for runner logic for the surrounding Sonex flow.

    Args:
        args: Input value used by the play online audio for runner operation.
        kwargs: Input value used by the play online audio for runner operation.

    Returns:
        The computed result for play online audio for runner.
    """
    if play_youtube_candidate is not _LEGACY_PLAY_ALIAS:
        return play_youtube_candidate(*args, **kwargs)
    return play_online_audio_candidate(*args, **kwargs)
from src.tools.playback_controller import controller as local_playback_controller
from src.tools.cover_patterns import CoverPatternError, fetch_cover_pattern, generate_cover_pattern
from src.tools.cover_sources import cover_bytes_for_source
from src.tools.player_permission import complete_player_confirm
from src.tools.apple_music import remember_recent_track as remember_apple_music_recent_track
from src.tools.spotify_play import remember_recent_track, recent_tracks_snapshot, spotify_current_playback, \
    spotify_account
from src.tools.song_cache import find_best_cached_song, recent_cached_songs, resolve_cached_song, upsert_cached_song

SEARCH_RESULT_TOOLS = {"spotify_search", "search_track", "spotify_recommend", "apple_music_search", "apple_music_recommend"}
RECOMMENDATION_TOOLS = {"spotify_recommend", "apple_music_recommend"}
PLAYBACK_AGENT_TOOLS = {"spotify_play", "apple_music_play", "play_youtube_song", "play_local_song"}
RECOMMEND_AGENT_TOOLS = (
    "spotify_recommend",
    "apple_music_recommend",
    "spotify_recent_tracks",
    "apple_music_recent_tracks",
    "spotify_search",
    "apple_music_search",
    "search_track",
    "search_memory",
    "search_context",
)
LOCAL_PLAYBACK_CONTROL_TOOLS = {
    "pause": "local_playback_pause",
    "resume": "local_playback_resume",
    "stop": "local_playback_stop",
    "progress": "local_playback_status",
}
LOCAL_PLAYBACK_SYNC_INTERVAL_SECONDS = 1.0
LOCAL_PLAYBACK_STATUS_PROBE_SECONDS = 15.0
LOCAL_PLAYBACK_BACKENDS = {"auto", "mpv", "cvlc"}
PLAYBACK_METHOD_CHOICES = [
    {
        "value": "spotify_play",
        "label": "🎧 Spotify 播放",
        "description": "需要 Premium 或可控制播放的订阅账号。",
    },
    {
        "value": "apple_music_play",
        "label": "🍎 Apple Music 播放",
        "description": "需要 Apple Music 订阅和本机 bridge。",
    },
    {
        "value": "online_play",
        "label": "🌐 在线播放",
        "description": "无订阅要求，使用在线音源和本地播放器。",
    },
    {"value": "cancel", "label": "取消"},
]
LOCAL_PLAYBACK_CHOICES = [
    {"value": "play_local", "label": "播放本地"},
    {"value": "skip_local", "label": "不播放本地，选择其他方式"},
    {"value": "cancel", "label": "取消"},
]


def _player_debug(message: str) -> None:
    """Player debug.

    Coordinates player debug logic for the surrounding Sonex flow.

    Args:
        message: Input value used by the player debug operation.

    Returns:
        The computed result for player debug.
    """
    if os.environ.get("SONEX_PLAYER_DEBUG") == "1":
        print(f"[sonex-player-debug] {message}", file=sys.stderr)


SPOTIFY_SETUP_TRIGGERS = {
    "spotify setup",
    "setup spotify",
    "connect spotify",
    "spotify connect",
    "接入 spotify",
    "连接 spotify",
    "配置 spotify",
}
APPLE_MUSIC_SETUP_TRIGGERS = {
    "apple music setup",
    "setup apple music",
    "connect apple music",
    "apple music connect",
    "接入 apple music",
    "连接 apple music",
    "配置 apple music",
    "接入苹果音乐",
    "连接苹果音乐",
    "配置苹果音乐",
}
LLM_AUTH_PROVIDER_CHOICES = [
    {"value": "openai", "label": "OpenAI"},
    {"value": "anthropic", "label": "Anthropic"},
    {"value": "gemini", "label": "Gemini"},
    {"value": "deepseek", "label": "Deepseek"},
    {"value": "ollama", "label": "Ollama"},
]
LLM_AUTH_PROVIDER_VALUES = {choice["value"] for choice in LLM_AUTH_PROVIDER_CHOICES}
LLM_MODEL_CHOICES = [
    {"value": "openai::gpt-5.2", "label": "GPT-5.2", "provider": "OpenAI"},
    {"value": "anthropic::claude-opus-4-1-20250805", "label": "Claude Opus 4.1", "provider": "Anthropic"},
    {"value": "gemini::gemini-3-flash-preview", "label": "Gemini 3 Flash Preview", "provider": "Gemini"},
    {"value": "deepseek::deepseek-v4-pro", "label": "DeepSeek V4 Pro", "provider": "DeepSeek"},
    {"value": "ollama::Gemma4-31b:cloud", "label": "Gemma4-31b:cloud", "provider": "Ollama"},
]
LLM_MODEL_CHOICE_VALUES = {choice["value"].lower(): choice for choice in LLM_MODEL_CHOICES}


@dataclass(frozen=True, slots=True)
class PlayRequestParse:
    """Represents play request parse.

    Encapsulates play request parse data and behavior used by Sonex runtime flows.
    """
    is_play_request: bool
    query: str | None
    confidence: str
    rewritten_input: str


@dataclass(frozen=True, slots=True)
class AuthRuntimeState:
    """Represents auth runtime state.

    Encapsulates auth runtime state data and behavior used by Sonex runtime flows.
    """
    ready: bool
    provider: str
    model: str
    auth_type: str
    credential_source: str
    reason: str | None = None

    def to_event(self) -> dict[str, Any]:
        """To event for auth runtime state.

        Coordinates the to event method behavior while preserving auth runtime state state and contracts.

        Returns:
            The computed result for to event.
        """
        return {
            "type": "auth_state",
            "ready": self.ready,
            "provider": self.provider,
            "model": self.model,
            "auth_type": self.auth_type,
            "credential_source": self.credential_source,
            "reason": self.reason,
        }


class WebSocketUIAdapter:
    """Represents web socket u i adapter.

    Encapsulates web socket u i adapter data and behavior used by Sonex runtime flows.
    """
    def __init__(self, ws: WebSocket) -> None:
        """Init for web socket u i adapter.

        Coordinates the init method behavior while preserving web socket u i adapter state and contracts.

        Args:
            ws: Input value used by the init operation.
        """
        self.ws = ws
        self.closed = False
        self.transcript: list[dict[str, str]] = []

    async def _send(self, payload: dict[str, Any]) -> None:
        """Send for web socket u i adapter.

        Coordinates the send method behavior while preserving web socket u i adapter state and contracts.

        Args:
            payload: Input value used by the send operation.

        Returns:
            The computed result for send.
        """
        if self.closed:
            return
        try:
            await self.ws.send_text(json.dumps(payload, ensure_ascii=False, default=str))
        except (RuntimeError, WebSocketDisconnect):
            self.closed = True

    async def append_user_message(self, text: str) -> None:
        """Append user message for web socket u i adapter.

        Coordinates the append user message method behavior while preserving web socket u i adapter state and contracts.

        Args:
            text: Input value used by the append user message operation.

        Returns:
            The computed result for append user message.
        """
        self.transcript.append({"role": "user", "content": text})
        await self._send({"type": "chat", "role": "user", "text": text})

    async def append_agent_message(self, text: str) -> None:
        """Append agent message for web socket u i adapter.

        Coordinates the append agent message method behavior while preserving web socket u i adapter state and contracts.

        Args:
            text: Input value used by the append agent message operation.

        Returns:
            The computed result for append agent message.
        """
        self.transcript.append({"role": "agent", "content": text})
        await self._send({"type": "chat", "role": "agent", "text": text})

    async def send_error(self, message: str) -> None:
        """Send error for web socket u i adapter.

        Coordinates the send error method behavior while preserving web socket u i adapter state and contracts.

        Args:
            message: Input value used by the send error operation.

        Returns:
            The computed result for send error.
        """
        await self._send({"type": "error", "message": message, "recoverable": True})

    async def append_tool_message(self, text: str) -> None:
        """Append tool message for web socket u i adapter.

        Coordinates the append tool message method behavior while preserving web socket u i adapter state and contracts.

        Args:
            text: Input value used by the append tool message operation.

        Returns:
            The computed result for append tool message.
        """
        await self.append_activity(
            kind="tool",
            title=text,
            status="success",
        )

    async def append_activity(
        self,
        *,
        kind: str,
        title: str,
        detail: str | None = None,
        status: str | None = None,
        activity_id: str | None = None,
    ) -> str:
        """Append activity for web socket u i adapter.

        Coordinates the append activity method behavior while preserving web socket u i adapter state and contracts.

        Args:
            kind: Input value used by the append activity operation.
            title: Input value used by the append activity operation.
            detail: Input value used by the append activity operation.
            status: Input value used by the append activity operation.
            activity_id: Input value used by the append activity operation.

        Returns:
            The computed result for append activity.
        """
        activity_id = activity_id or _new_event_id("activity")
        await self._send(
            {
                "type": "activity",
                "id": activity_id,
                "kind": kind,
                "title": title,
                "detail": detail,
                "status": status,
                "timestamp": _timestamp_ms(),
            }
        )
        return activity_id

    def set_status(self, status: UiStatus) -> None:
        """Set status for web socket u i adapter.

        Coordinates the set status method behavior while preserving web socket u i adapter state and contracts.

        Args:
            status: Input value used by the set status operation.

        Returns:
            The computed result for set status.
        """
        asyncio.create_task(
            self.send_status(status)
        )

    async def send_status(
        self,
        status: UiStatus,
        *,
        tokens: int | None = None,
        elapsed_ms: int | None = None,
        active: bool | None = None,
    ) -> None:
        """Send status for web socket u i adapter.

        Coordinates the send status method behavior while preserving web socket u i adapter state and contracts.

        Args:
            status: Input value used by the send status operation.
            tokens: Input value used by the send status operation.
            elapsed_ms: Input value used by the send status operation.
            active: Input value used by the send status operation.

        Returns:
            The computed result for send status.
        """
        payload = {
            "type": "status",
            "phase": status.phase,
            "message": status.message,
            "tokens": tokens,
            "elapsed_ms": elapsed_ms,
            "tool": status.tool_name,
            "step": status.step,
            "max_steps": status.max_steps,
        }
        if active is not None:
            payload["active"] = active
        await self._send(payload)

    async def send_auth_state(self, state: AuthRuntimeState) -> None:
        """Send auth state for web socket u i adapter.

        Coordinates the send auth state method behavior while preserving web socket u i adapter state and contracts.

        Args:
            state: Input value used by the send auth state operation.

        Returns:
            The computed result for send auth state.
        """
        await self._send(state.to_event())

    async def send_cover(self, url: str) -> None:
        """Send cover for web socket u i adapter.

        Coordinates the send cover method behavior while preserving web socket u i adapter state and contracts.

        Args:
            url: Input value used by the send cover operation.

        Returns:
            The computed result for send cover.
        """
        await self._send({"type": "cover", "url": url})
        asyncio.create_task(_send_cover_pattern(self, url))

    async def ask_confirm(self, attached: dict[str, Any]) -> None:
        """Ask confirm for web socket u i adapter.

        Coordinates the ask confirm method behavior while preserving web socket u i adapter state and contracts.

        Args:
            attached: Input value used by the ask confirm operation.

        Returns:
            The computed result for ask confirm.
        """
        await self._send(
            {
                "type": "confirm",
                "id": attached.get("id"),
                "tool_name": attached.get("tool_name"),
                "tool_args": attached.get("tool_args"),
                "message": attached.get("message"),
                "choices": attached.get("choices"),
            }
        )

    async def send_spotify_setup(
        self,
        *,
        step: str,
        title: str,
        message: str,
        prompt: str | None = None,
        mask: bool = False,
        active: bool = True,
    ) -> None:
        """Send spotify setup for web socket u i adapter.

        Coordinates the send spotify setup method behavior while preserving web socket u i adapter state and contracts.

        Args:
            step: Input value used by the send spotify setup operation.
            title: Input value used by the send spotify setup operation.
            message: Input value used by the send spotify setup operation.
            prompt: Input value used by the send spotify setup operation.
            mask: Input value used by the send spotify setup operation.
            active: Input value used by the send spotify setup operation.

        Returns:
            The computed result for send spotify setup.
        """
        await self._send(
            {
                "type": "spotify_setup",
                "step": step,
                "title": title,
                "message": message,
                "prompt": prompt,
                "mask": mask,
                "active": active,
            }
        )

    async def send_auth_setup(
        self,
        *,
        provider: str,
        step: str,
        title: str,
        message: str,
        prompt: str | None = None,
        mask: bool = False,
        active: bool = True,
        methods: list[dict[str, str]] | None = None,
        providers: list[dict[str, str]] | None = None,
        models: list[dict[str, str]] | None = None,
    ) -> None:
        """Send auth setup for web socket u i adapter.

        Coordinates the send auth setup method behavior while preserving web socket u i adapter state and contracts.

        Args:
            provider: Input value used by the send auth setup operation.
            step: Input value used by the send auth setup operation.
            title: Input value used by the send auth setup operation.
            message: Input value used by the send auth setup operation.
            prompt: Input value used by the send auth setup operation.
            mask: Input value used by the send auth setup operation.
            active: Input value used by the send auth setup operation.
            methods: Input value used by the send auth setup operation.
            providers: Input value used by the send auth setup operation.
            models: Input value used by the send auth setup operation.

        Returns:
            The computed result for send auth setup.
        """
        await self._send(
            {
                "type": "auth_setup",
                "provider": provider,
                "step": step,
                "title": title,
                "message": message,
                "prompt": prompt,
                "mask": mask,
                "active": active,
                "methods": methods,
                "providers": providers,
                "models": models,
            }
        )

    async def send_help_panel(
        self,
        commands: list[BuiltinCommand],
        *,
        title: str = "Slash commands",
        hint: str = "press Esc to hide",
    ) -> None:
        """Send help panel for web socket u i adapter.

        Coordinates the send help panel method behavior while preserving web socket u i adapter state and contracts.

        Args:
            commands: Input value used by the send help panel operation.
            title: Input value used by the send help panel operation.
            hint: Input value used by the send help panel operation.

        Returns:
            The computed result for send help panel.
        """
        await self._send(
            {
                "type": "help_panel",
                "title": title,
                "hint": hint,
                "commands": [
                    {
                        "name": command.name,
                        "usage": command.usage,
                        "description": command.description,
                    }
                    for command in commands
                ],
            }
        )

    async def close(self) -> None:
        """Close for web socket u i adapter.

        Coordinates the close method behavior while preserving web socket u i adapter state and contracts.

        Returns:
            The computed result for close.
        """
        if self.closed:
            return
        self.closed = True
        with suppress(RuntimeError, WebSocketDisconnect):
            await self.ws.close()


def _timestamp_ms() -> int:
    """Timestamp ms.

    Coordinates timestamp ms logic for the surrounding Sonex flow.

    Returns:
        The computed result for timestamp ms.
    """
    return int(time.time() * 1000)


def _new_event_id(prefix: str) -> str:
    """New event id.

    Coordinates new event id logic for the surrounding Sonex flow.

    Args:
        prefix: Input value used by the new event id operation.

    Returns:
        The computed result for new event id.
    """
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


async def _send_cover_pattern(ui: WebSocketUIAdapter, source_url: str) -> None:
    """Asynchronously send cover pattern.

    Coordinates non-blocking send cover pattern work for the surrounding Sonex flow.

    Args:
        ui: Input value used by the send cover pattern operation.
        source_url: Input value used by the send cover pattern operation.

    Returns:
        The computed result for send cover pattern.
    """
    try:
        image_bytes = cover_bytes_for_source(source_url)
        if image_bytes is not None:
            payload = await asyncio.to_thread(generate_cover_pattern, source_url, image_bytes)
        elif _is_http_cover_source(source_url):
            payload = await asyncio.to_thread(fetch_cover_pattern, source_url)
        else:
            return
    except CoverPatternError:
        return
    except Exception:
        return
    if not ui.closed:
        await ui._send(payload)


def _is_http_cover_source(source: str) -> bool:
    """Is http cover source.

    Coordinates is http cover source logic for the surrounding Sonex flow.

    Args:
        source: Input value used by the is http cover source operation.

    Returns:
        The computed result for is http cover source.
    """
    lowered = source.lower()
    return lowered.startswith("http://") or lowered.startswith("https://")


def _coerce_transcript_messages(messages: Any) -> list[dict[str, str]]:
    """Coerce transcript messages.

    Coordinates coerce transcript messages logic for the surrounding Sonex flow.

    Args:
        messages: Input value used by the coerce transcript messages operation.

    Returns:
        The computed result for coerce transcript messages.
    """
    if not isinstance(messages, list):
        return []

    transcript: list[dict[str, str]] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "").strip()
        content = str(message.get("content") or message.get("text") or "").strip()
        if role not in {"user", "agent"} or not content:
            continue
        transcript.append({"role": role, "content": content})
    return transcript


def _save_session_transcript(
    messages: list[dict[str, str]],
    *,
    reason: str,
) -> Path:
    """Save session transcript.

    Coordinates save session transcript logic for the surrounding Sonex flow.

    Args:
        messages: Input value used by the save session transcript operation.
        reason: Input value used by the save session transcript operation.

    Returns:
        The computed result for save session transcript.
    """
    now = datetime.now(timezone.utc)
    session_id = now.strftime("%Y%m%d%H%M%S%fZ")
    root = sonex_home() / "sessions" / session_id
    root.mkdir(parents=True, exist_ok=True)
    path = root / "transcript.jsonl"
    saved_at = now.isoformat()
    lines = [
        json.dumps(
            {
                "session_id": session_id,
                "saved_at": saved_at,
                "reason": reason,
                "index": index,
                "role": message["role"],
                "content": message["content"],
            },
            ensure_ascii=False,
            default=str,
        )
        for index, message in enumerate(messages)
    ]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return path


def _first_line(text: str, limit: int = 160) -> str:
    """First line.

    Coordinates first line logic for the surrounding Sonex flow.

    Args:
        text: Input value used by the first line operation.
        limit: Input value used by the first line operation.

    Returns:
        The computed result for first line.
    """
    line = " ".join(str(text).strip().split())
    if len(line) <= limit:
        return line
    return f"{line[: limit - 1]}..."


def _preview(value: Any, max_lines: int = 3, max_chars: int = 420) -> str:
    """Preview.

    Coordinates preview logic for the surrounding Sonex flow.

    Args:
        value: Input value used by the preview operation.
        max_lines: Input value used by the preview operation.
        max_chars: Input value used by the preview operation.

    Returns:
        The computed result for preview.
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
    """Format args.

    Coordinates format args logic for the surrounding Sonex flow.

    Args:
        args: Input value used by the format args operation.

    Returns:
        The computed result for format args.
    """
    if not args:
        return ""
    if isinstance(args, dict):
        parts = []
        for key, value in list(args.items())[:4]:
            parts.append(f"{key}={_first_line(value, limit=80)}")
        suffix = ", ..." if len(args) > 4 else ""
        return ", ".join(parts) + suffix
    return _first_line(args)


def _format_tool_start(tool_name: str, args: dict[str, Any]) -> tuple[str, str | None]:
    """Format tool start.

    Coordinates format tool start logic for the surrounding Sonex flow.

    Args:
        tool_name: Input value used by the format tool start operation.
        args: Input value used by the format tool start operation.

    Returns:
        The computed result for format tool start.
    """
    detail = _format_args(args)
    return f"Calling {tool_name}", detail or None


def _format_tool_result(tool_name: str, result: Any) -> tuple[str, str | None, str]:
    """Format tool result.

    Coordinates format tool result logic for the surrounding Sonex flow.

    Args:
        tool_name: Input value used by the format tool result operation.
        result: Input value used by the format tool result operation.

    Returns:
        The computed result for format tool result.
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
    """Is failed tool result.

    Coordinates is failed tool result logic for the surrounding Sonex flow.

    Args:
        result: Input value used by the is failed tool result operation.

    Returns:
        The computed result for is failed tool result.
    """
    if not isinstance(result, dict):
        return False
    return str(result.get("status") or "").lower() in {"fail", "failure", "error"}


def _is_player_confirm_result(result: Any) -> bool:
    """Is player confirm result.

    Coordinates is player confirm result logic for the surrounding Sonex flow.

    Args:
        result: Input value used by the is player confirm result operation.

    Returns:
        The computed result for is player confirm result.
    """
    return isinstance(result, dict) and result.get("status") == "requires_player_confirm"


def _friendly_runtime_error_message(result: Any, *, fallback: str = "Something went wrong.") -> str:
    """Friendly runtime error message.

    Coordinates friendly runtime error message logic for the surrounding Sonex flow.

    Args:
        result: Input value used by the friendly runtime error message operation.
        fallback: Input value used by the friendly runtime error message operation.

    Returns:
        The computed result for friendly runtime error message.
    """
    if isinstance(result, dict):
        code = str(result.get("error_code") or "")
        message = str(result.get("message") or "").strip()
        if code == "SPOTIFY_PREMIUM_REQUIRED":
            return (
                "Spotify playback state requires a Premium account. "
                "I will stop polling Spotify playback for this session; search and local playback can still work."
            )
        if message:
            return sanitize_error_message(message)
    return sanitize_error_message(fallback)


def _walk_dicts(value: Any) -> list[dict[str, Any]]:
    """Walk dicts.

    Coordinates walk dicts logic for the surrounding Sonex flow.

    Args:
        value: Input value used by the walk dicts operation.

    Returns:
        The computed result for walk dicts.
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
    """Extract music state.

    Coordinates extract music state logic for the surrounding Sonex flow.

    Args:
        result: Input value used by the extract music state operation.

    Returns:
        The computed result for extract music state.
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
            "uri": item.get("uri"),
            "provider": item.get("provider"),
            "player": item.get("player"),
            "session_id": item.get("session_id"),
            "source": item.get("source"),
            "ended": item.get("ended"),
            "volume_percent": item.get("volume_percent"),
            "spotify_url": item.get("spotify_url"),
            "apple_music_url": item.get("apple_music_url"),
            "youtube_url": item.get("youtube_url") or (item.get("url") if item.get("provider") == "youtube" else None),
            "url": item.get("url"),
            "stream_url": item.get("stream_url"),
            "album_cover_url": cover_url,
        }
        return state, cover_url

    return None, None


def _is_youtube_thumbnail(value: Any) -> bool:
    """Is youtube thumbnail.

    Coordinates is youtube thumbnail logic for the surrounding Sonex flow.

    Args:
        value: Input value used by the is youtube thumbnail operation.

    Returns:
        The computed result for is youtube thumbnail.
    """
    return isinstance(value, str) and "ytimg.com/" in value


def _extract_tracks(result: Any) -> list[dict[str, Any]]:
    """Extract tracks.

    Coordinates extract tracks logic for the surrounding Sonex flow.

    Args:
        result: Input value used by the extract tracks operation.

    Returns:
        The computed result for extract tracks.
    """
    if not isinstance(result, dict):
        return []
    data = result.get("data") if isinstance(result.get("data"), dict) else result
    tracks = data.get("tracks") if isinstance(data, dict) else None
    if not isinstance(tracks, list):
        return []
    return [track for track in tracks if isinstance(track, dict)]


def _duration_text(ms: Any) -> str:
    """Duration text.

    Coordinates duration text logic for the surrounding Sonex flow.

    Args:
        ms: Input value used by the duration text operation.

    Returns:
        The computed result for duration text.
    """
    try:
        total_seconds = max(0, int(ms or 0) // 1000)
    except (TypeError, ValueError):
        total_seconds = 0
    minutes = total_seconds // 60
    seconds = total_seconds % 60
    return f"{minutes}:{seconds:02d}"


def _metadata_provider_label(provider: Any) -> str:
    """Metadata provider label.

    Coordinates metadata provider label logic for the surrounding Sonex flow.

    Args:
        provider: Input value used by the metadata provider label operation.

    Returns:
        The computed result for metadata provider label.
    """
    normalized = str(provider or "").strip().lower()
    return {
        "itunes": "iTunes",
        "deezer": "Deezer",
        "musicbrainz": "MusicBrainz",
        "spotify": "Spotify",
    }.get(normalized, str(provider or "Metadata").title())


def _compact_count(value: Any) -> str | None:
    """Compact count.

    Coordinates compact count logic for the surrounding Sonex flow.

    Args:
        value: Input value used by the compact count operation.

    Returns:
        The computed result for compact count.
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
    """Youtube variant label.

    Coordinates youtube variant label logic for the surrounding Sonex flow.

    Args:
        value: Input value used by the youtube variant label operation.

    Returns:
        The computed result for youtube variant label.
    """
    variant = str(value or "other")
    if variant == "official_original":
        return "原音"
    if variant == "live":
        return "Live"
    return "其他"


def _queue_payload() -> list[dict[str, str]]:
    """Queue payload.

    Coordinates queue payload logic for the surrounding Sonex flow.

    Returns:
        The computed result for queue payload.
    """
    try:
        tracks = recent_cached_songs()
    except Exception:
        tracks = []
    if not tracks:
        tracks = recent_tracks_snapshot()
    return [
        {
            "index": f"{index:02d}",
            "title": str(track.get("name") or "-"),
            "artist": str(track.get("artist") or "-"),
            "duration": _duration_text(track.get("duration_ms")),
        }
        for index, track in enumerate(tracks, start=1)
    ]


def _search_results_payload(result: Any) -> list[dict[str, Any]]:
    """Search results payload.

    Coordinates search results payload logic for the surrounding Sonex flow.

    Args:
        result: Input value used by the search results payload operation.

    Returns:
        The computed result for search results payload.
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
                "apple_music_url": track.get("apple_music_url") or track.get("url"),
                "url": track.get("url") or track.get("spotify_url") or track.get("apple_music_url"),
                "album_cover_url": track.get("album_cover_url"),
                "recommendation_reason": track.get("recommendation_reason"),
            }
        )
    return payload


def _player_sync_signature(state: dict[str, Any]) -> tuple[Any, ...]:
    """Player sync signature.

    Coordinates player sync signature logic for the surrounding Sonex flow.

    Args:
        state: Input value used by the player sync signature operation.

    Returns:
        The computed result for player sync signature.
    """
    progress_bucket = int((state.get("progress_ms") or 0) / 5000)
    return (
        state.get("name"),
        state.get("artist"),
        state.get("album"),
        state.get("duration_ms"),
        bool(state.get("is_playing")),
        progress_bucket,
        state.get("volume_percent"),
    )


def _project_local_playback_state(state: dict[str, Any], now_ms: int) -> dict[str, Any]:
    """Project local playback state.

    Coordinates project local playback state logic for the surrounding Sonex flow.

    Args:
        state: Input value used by the project local playback state operation.
        now_ms: Input value used by the project local playback state operation.

    Returns:
        The computed result for project local playback state.
    """
    payload = dict(state)
    progress_ms = int(payload.get("progress_ms") or 0)
    duration_ms = int(payload.get("duration_ms") or 0)
    timestamp = int(payload.get("timestamp") or now_ms)
    is_playing = payload.get("is_playing") is True

    if is_playing:
        progress_ms += max(0, now_ms - timestamp)
        if duration_ms > 0:
            progress_ms = min(duration_ms, progress_ms)
            if progress_ms >= duration_ms:
                payload["is_playing"] = False
                payload["ended"] = True

    payload["progress_ms"] = progress_ms
    payload["timestamp"] = now_ms
    return payload


def _is_spotify_setup_request(text: str) -> bool:
    """Is spotify setup request.

    Coordinates is spotify setup request logic for the surrounding Sonex flow.

    Args:
        text: Input value used by the is spotify setup request operation.

    Returns:
        The computed result for is spotify setup request.
    """
    normalized = " ".join(text.strip().lower().split())
    return normalized in SPOTIFY_SETUP_TRIGGERS


def _is_apple_music_setup_request(text: str) -> bool:
    """Is apple music setup request.

    Coordinates is apple music setup request logic for the surrounding Sonex flow.

    Args:
        text: Input value used by the is apple music setup request operation.

    Returns:
        The computed result for is apple music setup request.
    """
    normalized = " ".join(text.strip().lower().split())
    return normalized in APPLE_MUSIC_SETUP_TRIGGERS


def _rule_parse_play_request(text: str) -> PlayRequestParse:
    """Rule parse play request.

    Coordinates rule parse play request logic for the surrounding Sonex flow.

    Args:
        text: Input value used by the rule parse play request operation.

    Returns:
        The computed result for rule parse play request.
    """
    stripped = text.strip()
    lowered = stripped.lower()
    prefixes = ("play ", "帮我放一首", "播放", "放一下", "放首", "来首", "来一首", "我想听", "想听", "听 ")
    for prefix in prefixes:
        if lowered.startswith(prefix):
            query = stripped[len(prefix):].strip()
            if query:
                return PlayRequestParse(True, query, "high", f"/play {query}")
    return PlayRequestParse(False, None, "low", stripped)


def _should_optimize_play_request(text: str) -> bool:
    """Should optimize play request.

    Coordinates should optimize play request logic for the surrounding Sonex flow.

    Args:
        text: Input value used by the should optimize play request operation.

    Returns:
        The computed result for should optimize play request.
    """
    lowered = text.strip().lower()
    if not lowered:
        return False
    english_cues = ("play", "listen to", "song", "track", "music")
    chinese_cues = ("播放", "放一", "放首", "来首", "来一首", "想听", "听歌", "歌曲", "音乐")
    return any(cue in lowered for cue in english_cues) or any(cue in text for cue in chinese_cues)


def _optimize_play_prompt(text: str) -> PlayRequestParse:
    """Optimize play prompt.

    Coordinates optimize play prompt logic for the surrounding Sonex flow.

    Args:
        text: Input value used by the optimize play prompt operation.

    Returns:
        The computed result for optimize play prompt.
    """
    prompt = (
        "Decide whether the user is clearly asking to play a song now.\n"
        "Return JSON only with keys: is_play_request boolean, query string or null, "
        "confidence high or low, rewritten_input string.\n"
        f"user_input: {text}"
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
    """Is local search hit.

    Coordinates is local search hit logic for the surrounding Sonex flow.

    Args:
        result: Input value used by the is local search hit operation.

    Returns:
        The computed result for is local search hit.
    """
    return bool(result and not result.startswith("No local files found") and not result.startswith("Path outside user workspace"))


def _filename(path_text: str) -> str:
    """Filename.

    Coordinates filename logic for the surrounding Sonex flow.

    Args:
        path_text: Input value used by the filename operation.

    Returns:
        The computed result for filename.
    """
    return Path(path_text).name or path_text


def _default_provider_name() -> str:
    """Default provider name.

    Coordinates default provider name logic for the surrounding Sonex flow.

    Returns:
        The computed result for default provider name.
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
    """Default model name.

    Coordinates default model name logic for the surrounding Sonex flow.

    Returns:
        The computed result for default model name.
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
        or "gpt-5.2"
    )
    return str(normalize_provider_model(provider, str(model)) or model)


def _env_api_key_for_provider(provider: str) -> str | None:
    """Env api key for provider.

    Coordinates env api key for provider logic for the surrounding Sonex flow.

    Args:
        provider: Input value used by the env api key for provider operation.

    Returns:
        The computed result for env api key for provider.
    """
    name = normalize_provider(provider)
    value = os.getenv(f"SONEX_{name.upper()}_API_KEY")
    if value:
        return value
    if name == "openai":
        return os.getenv("SONEX_API_KEY") or None
    return None


def _set_runtime_default_provider(provider: str, model: str | None = None) -> None:
    """Set runtime default provider.

    Coordinates set runtime default provider logic for the surrounding Sonex flow.

    Args:
        provider: Input value used by the set runtime default provider operation.
        model: Input value used by the set runtime default provider operation.

    Returns:
        The computed result for set runtime default provider.
    """
    name = normalize_provider(provider)
    resolved_model = model or get_provider_capability(name).default_model
    set_default(name, resolved_model)
    os.environ["SONEX_DEFAULT_PROVIDER"] = name
    if resolved_model:
        os.environ["SONEX_DEFAULT_MODEL"] = resolved_model


def _resolved_provider_model() -> tuple[str, str]:
    """Resolved provider model.

    Coordinates resolved provider model logic for the surrounding Sonex flow.

    Returns:
        The computed result for resolved provider model.
    """
    try:
        ThinkingConfig.reload()
        provider = normalize_provider(ThinkingConfig.get_provider())
        config = ThinkingConfig.get_provider_config(provider)
        model = config.model or ThinkingConfig.get_model() or _default_model_name()
    except Exception:
        return _default_provider_name(), _default_model_name()
    return provider, str(model)


def _llm_auth_state() -> AuthRuntimeState:
    """Llm auth state.

    Coordinates llm auth state logic for the surrounding Sonex flow.

    Returns:
        The computed result for llm auth state.
    """
    provider, model = _resolved_provider_model()

    capability = get_provider_capability(provider)
    if not capability.requires_auth:
        return AuthRuntimeState(True, provider, model, "local", "local")

    if _env_api_key_for_provider(provider):
        return AuthRuntimeState(True, provider, model, "api_key", "env")

    try:
        store = load_auth_store()
        auth = get_provider_auth(store, provider)
    except Exception as exc:
        return AuthRuntimeState(
            False,
            provider,
            model,
            "none",
            "missing",
            sanitize_error_message(exc),
        )

    if auth and auth.api_key:
        return AuthRuntimeState(True, provider, auth.model or model, "api_key", "auth.json")
    if auth and auth.oauth and auth.oauth.access_token:
        try:
            ensure_oauth_token_usable(provider, auth.oauth)
        except Exception as exc:
            return AuthRuntimeState(False, provider, auth.model or model, "oauth", "auth.json", sanitize_error_message(exc))
        return AuthRuntimeState(True, provider, auth.model or model, "oauth", "auth.json")

    return AuthRuntimeState(
        False,
        provider,
        model,
        "none",
        "missing",
        f"Provider '{provider}' needs credentials before Sonex can plan this turn.",
    )


def _llm_auth_ready() -> tuple[bool, str, str | None]:
    """Llm auth ready.

    Coordinates llm auth ready logic for the surrounding Sonex flow.

    Returns:
        The computed result for llm auth ready.
    """
    state = _llm_auth_state()
    return state.ready, state.provider, state.reason


def _auth_methods_for_provider(provider: str) -> list[dict[str, str]]:
    """Auth methods for provider.

    Coordinates auth methods for provider logic for the surrounding Sonex flow.

    Args:
        provider: Input value used by the auth methods for provider operation.

    Returns:
        The computed result for auth methods for provider.
    """
    capability = get_provider_capability(provider)
    methods: list[dict[str, str]] = []
    if capability.supports_oauth and browser_oauth_supported(provider):
        methods.append({"value": "oauth", "label": "OAuth"})
    if capability.supports_api_key:
        methods.append({"value": "api_key", "label": "API key"})
    return methods


def _model_choices_for_provider(provider: str) -> list[dict[str, str]]:
    """Model choices for provider.

    Coordinates model choices for provider logic for the surrounding Sonex flow.

    Args:
        provider: Input value used by the model choices for provider operation.

    Returns:
        The computed result for model choices for provider.
    """
    name = normalize_provider(provider)
    if name in {"openai", "anthropic", "gemini", "deepseek"}:
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
    """Parse model choice.

    Coordinates parse model choice logic for the surrounding Sonex flow.

    Args:
        value: Input value used by the parse model choice operation.
        choices: Input value used by the parse model choice operation.

    Returns:
        The computed result for parse model choice.
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
    """Spotify loopback login for tui.

    Coordinates spotify loopback login for tui logic for the surrounding Sonex flow.

    Args:
        authorize_url: Input value used by the spotify loopback login for tui operation.
        expected_state: Input value used by the spotify loopback login for tui operation.

    Returns:
        The computed result for spotify loopback login for tui.
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
            """Do g e t for spotify callback handler.

            Coordinates the do g e t method behavior while preserving spotify callback handler state and contracts.

            Returns:
                The computed result for do g e t.
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
            """Log message for spotify callback handler.

            Coordinates the log message method behavior while preserving spotify callback handler state and contracts.

            Args:
                format: Input value used by the log message operation.
                args: Input value used by the log message operation.

            Returns:
                The computed result for log message.
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
    def __init__(self, ui: WebSocketUIAdapter) -> None:
        """Init for spotify setup session.

        Coordinates the init method behavior while preserving spotify setup session state and contracts.

        Args:
            ui: Input value used by the init operation.
        """
        self.ui = ui
        self.client_id: str | None = None
        self.step = "client_id"
        self.oauth_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Start for spotify setup session.

        Coordinates the start method behavior while preserving spotify setup session state and contracts.

        Returns:
            The computed result for start.
        """
        redirect_uri = spotify_redirect_uri()
        message = (
            "Open https://developer.spotify.com/dashboard, create an app, and add this Redirect URI: "
            f"{redirect_uri}. Then paste the Client ID below."
        )
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

    async def handle_input(self, value: str) -> None:
        """Handle input for spotify setup session.

        Coordinates the handle input method behavior while preserving spotify setup session state and contracts.

        Args:
            value: Input value used by the handle input operation.

        Returns:
            The computed result for handle input.
        """
        value = value.strip()
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
        """Finish oauth for spotify setup session.

        Coordinates the finish oauth method behavior while preserving spotify setup session state and contracts.

        Args:
            authorize_url: Input value used by the finish oauth operation.
            expected_state: Input value used by the finish oauth operation.

        Returns:
            The computed result for finish oauth.
        """
        try:
            account = await asyncio.to_thread(_spotify_loopback_login_for_tui, authorize_url, expected_state)
        except Exception as exc:
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

        data = account.get("data") if isinstance(account, dict) else {}
        product = data.get("product") if isinstance(data, dict) else "unknown"
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


class AppleMusicSetupSession:
    """Represents apple music setup session.

    Encapsulates apple music setup session data and behavior used by Sonex runtime flows.
    """
    def __init__(self, ui: WebSocketUIAdapter) -> None:
        """Init for apple music setup session.

        Coordinates the init method behavior while preserving apple music setup session state and contracts.

        Args:
            ui: Input value used by the init operation.
        """
        self.ui = ui
        self.step = "credentials"

    async def start(self) -> None:
        """Start for apple music setup session.

        Coordinates the start method behavior while preserving apple music setup session state and contracts.

        Returns:
            The computed result for start.
        """
        message = (
            f"{apple_music_setup_message()} Paste the Apple Music credentials JSON or a path to that JSON below."
        )
        await self.ui.append_activity(
            kind="status",
            title="Apple Music setup",
            detail=message,
            status="pending",
        )
        await self.ui.send_auth_setup(
            provider="apple_music",
            step="credentials",
            title="Apple Music setup",
            message=message,
            prompt="Apple Music credentials JSON or path",
            mask=True,
        )

    async def handle_input(self, value: str) -> None:
        """Handle input for apple music setup session.

        Coordinates the handle input method behavior while preserving apple music setup session state and contracts.

        Args:
            value: Input value used by the handle input operation.

        Returns:
            The computed result for handle input.
        """
        value = value.strip()
        if not value:
            await self._repeat("Input cannot be empty.")
            return

        if self.step == "credentials":
            try:
                save_apple_music_credentials(value)
            except Exception as exc:
                await self._repeat(sanitize_error_message(exc))
                return
            self.step = "user_token"
            await self.ui.append_activity(
                kind="status",
                title="Apple Music credentials saved",
                detail="Developer token credentials are saved. Music User Token is optional but required for user data and playback.",
                status="success",
            )
            await self.ui.send_auth_setup(
                provider="apple_music",
                step="user_token",
                title="Apple Music user token",
                message="Paste a Music User Token, or type skip to finish catalog-only setup.",
                prompt="Music User Token or skip",
                mask=True,
            )
            return

        if self.step == "user_token":
            if value.lower() == "skip":
                await self._finish("Apple Music catalog search is configured.")
                return
            try:
                save_apple_music_user_token(value)
            except Exception as exc:
                await self._repeat(sanitize_error_message(exc))
                return
            await self._finish("Apple Music developer credentials and user token are configured.")

    async def _repeat(self, message: str) -> None:
        """Repeat for apple music setup session.

        Coordinates the repeat method behavior while preserving apple music setup session state and contracts.

        Args:
            message: Input value used by the repeat operation.

        Returns:
            The computed result for repeat.
        """
        if self.step == "user_token":
            await self.ui.send_auth_setup(
                provider="apple_music",
                step="user_token",
                title="Apple Music user token",
                message=message,
                prompt="Music User Token or skip",
                mask=True,
            )
            return
        await self.ui.send_auth_setup(
            provider="apple_music",
            step="credentials",
            title="Apple Music setup",
            message=message,
            prompt="Apple Music credentials JSON or path",
            mask=True,
        )

    async def _finish(self, message: str) -> None:
        """Finish for apple music setup session.

        Coordinates the finish method behavior while preserving apple music setup session state and contracts.

        Args:
            message: Input value used by the finish operation.

        Returns:
            The computed result for finish.
        """
        await self.ui.append_activity(
            kind="status",
            title="Apple Music connected",
            detail=message,
            status="success",
        )
        await self.ui.send_auth_setup(
            provider="apple_music",
            step="done",
            title="Apple Music connected",
            message=message,
            active=False,
        )
        setattr(self.ui, "_apple_music_setup", None)


class OpenAudioSetupSession:
    """Represents open audio setup session.

    Encapsulates open audio setup session data and behavior used by Sonex runtime flows.
    """
    def __init__(self, ui: WebSocketUIAdapter, provider: str) -> None:
        """Init for open audio setup session.

        Coordinates the init method behavior while preserving open audio setup session state and contracts.

        Args:
            ui: Input value used by the init operation.
            provider: Input value used by the init operation.
        """
        self.ui = ui
        self.provider = provider
        self.display_name = "Jamendo" if provider == "jamendo" else "Audius"

    def _prompt_label(self) -> str:
        """Prompt label for open audio setup session.

        Coordinates the prompt label method behavior while preserving open audio setup session state and contracts.

        Returns:
            The computed result for prompt label.
        """
        return "Jamendo Client ID" if self.provider == "jamendo" else "Audius API key"

    def _setup_message(self) -> str:
        """Setup message for open audio setup session.

        Coordinates the setup message method behavior while preserving open audio setup session state and contracts.

        Returns:
            The computed result for setup message.
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
        """Start for open audio setup session.

        Coordinates the start method behavior while preserving open audio setup session state and contracts.

        Returns:
            The computed result for start.
        """
        label = self._prompt_label()
        message = self._setup_message()
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
        """Handle input for open audio setup session.

        Coordinates the handle input method behavior while preserving open audio setup session state and contracts.

        Args:
            value: Input value used by the handle input operation.

        Returns:
            The computed result for handle input.
        """
        value = value.strip()
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



class ModelSelectionSession:
    """Represents model selection session.

    Encapsulates model selection session data and behavior used by Sonex runtime flows.
    """
    def __init__(self, ui: WebSocketUIAdapter) -> None:
        """Init for model selection session.

        Coordinates the init method behavior while preserving model selection session state and contracts.

        Args:
            ui: Input value used by the init operation.
        """
        self.ui = ui
        self.provider = _default_provider_name()
        self.model_choices: list[dict[str, str]] = []

    async def start(self) -> None:
        """Start for model selection session.

        Coordinates the start method behavior while preserving model selection session state and contracts.

        Returns:
            The computed result for start.
        """
        self.provider = _default_provider_name()
        if normalize_provider(self.provider) == "deepseek":
            self.model_choices = await asyncio.to_thread(_model_choices_for_provider, self.provider)
        else:
            self.model_choices = _model_choices_for_provider(self.provider)
        await self.ui.append_activity(
            kind="status",
            title="Switch model",
            detail=f"Choose a {self.provider} model for the current session.",
            status="pending",
        )
        await self.ui.send_auth_setup(
            provider=self.provider,
            step="model",
            title="Switch model",
            message=f"Choose a {self.provider} model. Use Up/Down to see more options.",
            prompt="Model",
            models=self.model_choices,
        )

    async def handle_input(self, value: str) -> None:
        """Handle input for model selection session.

        Coordinates the handle input method behavior while preserving model selection session state and contracts.

        Args:
            value: Input value used by the handle input operation.

        Returns:
            The computed result for handle input.
        """
        parsed = _parse_model_choice(value, self.model_choices)
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
        _set_runtime_default_provider(provider, model)
        ThinkingConfig.reload()
        state = _llm_auth_state()
        ready_detail = f"Using {model} via {provider}."
        if not state.ready:
            ready_detail = f"Using {model} via {provider}. Credentials are needed before the next agent turn."
        await self.ui.append_activity(
            kind="status",
            title="Model switched",
            detail=ready_detail,
            status="success",
        )
        await self.ui.send_auth_state(state)
        await self.ui.send_auth_setup(
            provider=provider,
            step="done",
            title="Model switched",
            message=ready_detail,
            active=False,
        )
        setattr(self.ui, "_model_setup", None)

class AuthSetupSession:
    """Represents auth setup session.

    Encapsulates auth setup session data and behavior used by Sonex runtime flows.
    """
    def __init__(self, ui: WebSocketUIAdapter, provider: str, pending_input: str | None, runner: "WebSocketRunner") -> None:
        """Init for auth setup session.

        Coordinates the init method behavior while preserving auth setup session state and contracts.

        Args:
            ui: Input value used by the init operation.
            provider: Input value used by the init operation.
            pending_input: Input value used by the init operation.
            runner: Input value used by the init operation.
        """
        self.ui = ui
        self.provider = normalize_provider(provider)
        self.pending_input = pending_input
        self.runner = runner
        self.step = "method"
        self.method: str | None = None
        self.oauth_task: asyncio.Task[None] | None = None

    async def start(self, reason: str | None = None) -> None:
        """Start for auth setup session.

        Coordinates the start method behavior while preserving auth setup session state and contracts.

        Args:
            reason: Input value used by the start operation.

        Returns:
            The computed result for start.
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
            title=f"{self.provider} login required",
            detail=reason or f"Configure {self.provider} before chatting.",
            status="pending",
        )
        await self._continue_provider_auth(reason)

    async def _prompt_provider(self, reason: str | None = None) -> None:
        """Prompt provider for auth setup session.

        Coordinates the prompt provider method behavior while preserving auth setup session state and contracts.

        Args:
            reason: Input value used by the prompt provider operation.

        Returns:
            The computed result for prompt provider.
        """
        self.step = "provider"
        await self.ui.send_auth_setup(
            provider=self.provider,
            step="provider",
            title="Connect Sonex",
            message=reason or "Choose a model provider. Type openai, anthropic, gemini, deepseek, or ollama.",
            prompt="Model provider",
            providers=LLM_AUTH_PROVIDER_CHOICES,
        )

    async def _continue_provider_auth(self, reason: str | None = None) -> None:
        """Continue provider auth for auth setup session.

        Coordinates the continue provider auth method behavior while preserving auth setup session state and contracts.

        Args:
            reason: Input value used by the continue provider auth operation.

        Returns:
            The computed result for continue provider auth.
        """
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
                title=f"Connect {self.provider}",
                message="Choose an auth method. Type oauth or api_key.",
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
        """Handle input for auth setup session.

        Coordinates the handle input method behavior while preserving auth setup session state and contracts.

        Args:
            value: Input value used by the handle input operation.

        Returns:
            The computed result for handle input.
        """
        value = value.strip()
        if not value:
            await self._repeat("Input cannot be empty.")
            return

        if self.step == "provider":
            normalized = normalize_provider(value)
            if normalized not in LLM_AUTH_PROVIDER_VALUES:
                await self._prompt_provider("Type one of: openai, anthropic, gemini, deepseek, or ollama.")
                return
            self.provider = normalized
            self.method = None
            try:
                _set_runtime_default_provider(self.provider)
                ThinkingConfig.reload()
            except Exception as exc:
                await self._prompt_provider(sanitize_error_message(exc))
                return
            await self._continue_provider_auth()
            return

        if self.step == "method":
            normalized = value.lower().replace("-", "_")
            if normalized not in {"oauth", "api_key"}:
                await self._repeat("Type oauth or api_key.")
                return
            capability = get_provider_capability(self.provider)
            if normalized == "oauth" and not capability.supports_oauth:
                await self._repeat(browser_oauth_requirements(self.provider))
                return
            if normalized == "api_key" and not capability.supports_api_key:
                await self._repeat(f"{self.provider} does not support API key login.")
                return
            self.method = normalized
            if normalized == "oauth":
                await self._start_browser_oauth()
            else:
                await self._prompt_api_key()
            return

        if self.step == "api_key":
            try:
                set_api_key(self.provider, value)
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

    async def _prompt_api_key(self) -> None:
        """Prompt api key for auth setup session.

        Coordinates the prompt api key method behavior while preserving auth setup session state and contracts.

        Returns:
            The computed result for prompt api key.
        """
        self.step = "api_key"
        await self.ui.send_auth_setup(
            provider=self.provider,
            step="api_key",
            title=f"{self.provider} API key",
            message=f"Paste your {self.provider} API key. It will be saved to auth.json.",
            prompt=f"{self.provider} API key",
            mask=True,
            methods=_auth_methods_for_provider(self.provider),
        )

    async def _start_browser_oauth(self) -> None:
        """Start browser oauth for auth setup session.

        Coordinates the start browser oauth method behavior while preserving auth setup session state and contracts.

        Returns:
            The computed result for start browser oauth.
        """
        self.step = "oauth_wait"
        await self.ui.send_auth_setup(
            provider=self.provider,
            step="oauth_wait",
            title=f"Authorize {self.provider}",
            message="Opening browser OAuth. Approve access in the browser, then return to Sonex.",
            active=False,
            methods=_auth_methods_for_provider(self.provider),
        )
        self.oauth_task = asyncio.create_task(self._finish_browser_oauth())

    async def _finish_browser_oauth(self) -> None:
        """Finish browser oauth for auth setup session.

        Coordinates the finish browser oauth method behavior while preserving auth setup session state and contracts.

        Returns:
            The computed result for finish browser oauth.
        """
        try:
            await asyncio.to_thread(run_browser_oauth, self.provider)
            _set_runtime_default_provider(self.provider)
            ThinkingConfig.reload()
        except BrowserOAuthConfigError as exc:
            self.step = "method"
            self.method = None
            await self._repeat(sanitize_error_message(exc))
            return
        except Exception as exc:
            self.step = "method"
            self.method = None
            await self._repeat(sanitize_error_message(exc))
            return
        await self._finish()

    async def _repeat(self, message: str) -> None:
        """Repeat for auth setup session.

        Coordinates the repeat method behavior while preserving auth setup session state and contracts.

        Args:
            message: Input value used by the repeat operation.

        Returns:
            The computed result for repeat.
        """
        if self.method == "oauth" and self.step == "oauth_wait":
            await self.ui.send_auth_setup(
                provider=self.provider,
                step="method",
                title=f"Connect {self.provider}",
                message=message,
                prompt="oauth or api_key",
                methods=_auth_methods_for_provider(self.provider),
            )
            return
        if self.method == "api_key" or self.step == "api_key":
            await self.ui.send_auth_setup(
                provider=self.provider,
                step="api_key",
                title=f"{self.provider} API key",
                message=message,
                prompt=f"{self.provider} API key",
                mask=True,
                methods=_auth_methods_for_provider(self.provider),
            )
            return
        await self.ui.send_auth_setup(
            provider=self.provider,
            step="method",
            title=f"Connect {self.provider}",
            message=message,
            prompt="oauth or api_key",
            methods=_auth_methods_for_provider(self.provider),
            providers=LLM_AUTH_PROVIDER_CHOICES if self.pending_input is None else None,
        )

    async def _finish(self) -> None:
        """Finish for auth setup session.

        Coordinates the finish method behavior while preserving auth setup session state and contracts.

        Returns:
            The computed result for finish.
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
            title=f"{self.provider} connected",
            detail="Continuing your message." if self.pending_input else "Login complete.",
            status="success",
        )
        await self.ui.send_auth_state(state)
        await self.ui.send_auth_setup(
            provider=self.provider,
            step="done",
            title=f"{self.provider} connected",
            message="Login complete. Continuing your message." if self.pending_input else "Login complete.",
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
        """Init for music intent confirmation session.

        Coordinates the init method behavior while preserving music intent confirmation session state and contracts.

        Args:
            ui: Input value used by the init operation.
            runner: Input value used by the init operation.
            original_input: Input value used by the init operation.
            query: Input value used by the init operation.
        """
        self.ui = ui
        self.runner = runner
        self.original_input = original_input
        self.query = query
        self.confirm_id = _new_event_id("confirm")

    async def start(self) -> None:
        """Start for music intent confirmation session.

        Coordinates the start method behavior while preserving music intent confirmation session state and contracts.

        Returns:
            The computed result for start.
        """
        await self.ui.ask_confirm(
            {
                "id": self.confirm_id,
                "tool_name": "music_intent",
                "tool_args": {"query": self.query},
                "message": f"你是想播放《{self.query}》，还是先聊聊这首歌？",
                "choices": [
                    {"value": "play_track", "label": "播放这首", "description": "进入播放来源和歌曲选择。"},
                    {"value": "discuss_track", "label": "暂不播放，聊聊这首歌", "description": "只进行文字交流。"},
                ],
            }
        )

    def owns_confirm(self, confirm_id: str) -> bool:
        """Owns confirm for music intent confirmation session.

        Coordinates the owns confirm method behavior while preserving music intent confirmation session state and contracts.

        Args:
            confirm_id: Input value used by the owns confirm operation.

        Returns:
            The computed result for owns confirm.
        """
        return confirm_id == self.confirm_id

    async def handle_choice(self, decision: Any) -> None:
        """Handle choice for music intent confirmation session.

        Coordinates the handle choice method behavior while preserving music intent confirmation session state and contracts.

        Args:
            decision: Input value used by the handle choice operation.

        Returns:
            The computed result for handle choice.
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
    def __init__(self, ui: WebSocketUIAdapter, runner: "WebSocketRunner", query: str) -> None:
        """Init for play selection session.

        Coordinates the init method behavior while preserving play selection session state and contracts.

        Args:
            ui: Input value used by the init operation.
            runner: Input value used by the init operation.
            query: Input value used by the init operation.
        """
        self.ui = ui
        self.runner = runner
        self.query = query.strip()
        self.local_file: str | None = None
        self.cache_hit: dict[str, Any] | None = None
        self.active_confirm_id: str | None = None
        self.pending_player_confirm_result: dict[str, Any] | None = None
        self.metadata_candidates: list[dict[str, Any]] = []
        self.online_audio_candidates: list[dict[str, Any]] = []
        self.selected_playback_metadata: dict[str, Any] | None = None
        self.awaiting_metadata_refinement = False
        self.awaiting_online_refinement = False

    async def start(self) -> None:
        """Start for play selection session.

        Coordinates the start method behavior while preserving play selection session state and contracts.

        Returns:
            The computed result for start.
        """
        if not self.query:
            message = "Usage: /play <query>"
            await self.ui.append_activity(kind="error", title="Invalid play request", detail=message, status="error")
            await self.ui.append_agent_message(message)
            return

        local_result = search_local_file(self.query)
        if _is_local_search_hit(local_result):
            self.local_file = local_result
            await self._ask_local_choice(local_result)
            return

        self.cache_hit = find_best_cached_song(self.query)
        await self._ask_method_choice()

    def owns_confirm(self, confirm_id: str) -> bool:
        """Owns confirm for play selection session.

        Coordinates the owns confirm method behavior while preserving play selection session state and contracts.

        Args:
            confirm_id: Input value used by the owns confirm operation.

        Returns:
            The computed result for owns confirm.
        """
        return bool(self.active_confirm_id and confirm_id == self.active_confirm_id)

    async def handle_choice(self, decision: Any) -> None:
        """Handle choice for play selection session.

        Coordinates the handle choice method behavior while preserving play selection session state and contracts.

        Args:
            decision: Input value used by the handle choice operation.

        Returns:
            The computed result for handle choice.
        """
        choice = str(decision or "cancel")
        if self.pending_player_confirm_result:
            await self._complete_player_confirmation(choice)
            return

        if choice in {"deny", "cancel"}:
            await self._finish("Playback cancelled.", status="error")
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
            candidate = self.metadata_candidates[index] if 0 <= index < len(self.metadata_candidates) else None
            if candidate is None:
                await self._finish("Selected song metadata candidate expired.", status="error")
                return
            self.selected_playback_metadata = dict(candidate)
            self.selected_playback_metadata.setdefault("original_query", self.query)
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
            await self._finish("Local playback selected.")
            return
        if choice == "skip_local":
            self.cache_hit = find_best_cached_song(self.query)
            await self._ask_method_choice()
            return
        if choice == "spotify_play":
            await self._play_from_provider("spotify_play", "spotify")
            return
        if choice == "apple_music_play":
            await self._play_from_provider("apple_music_play", "apple_music")
            return
        if choice == "online_play":
            await self._ask_metadata_candidates(self.query)
            return
        await self._finish("Unknown playback choice.", status="error")

    async def handle_refinement(self, text: str) -> bool:
        """Handle refinement for play selection session.

        Coordinates the handle refinement method behavior while preserving play selection session state and contracts.

        Args:
            text: Input value used by the handle refinement operation.

        Returns:
            The computed result for handle refinement.
        """
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

    async def _ensure_online_audio_setup(self) -> bool:
        """Ensure online audio setup for play selection session.

        Coordinates the ensure online audio setup method behavior while preserving play selection session state and contracts.

        Returns:
            The computed result for ensure online audio setup.
        """
        if online_audio_configured():
            return True
        await self._show_online_audio_setup_required()
        return False

    async def _show_online_audio_setup_required(self) -> None:
        """Show online audio setup required for play selection session.

        Coordinates the show online audio setup required method behavior while preserving play selection session state and contracts.

        Returns:
            The computed result for show online audio setup required.
        """
        await self.ui.append_activity(
            kind="error",
            title="Online audio setup required",
            detail=ONLINE_AUDIO_SETUP_MESSAGE,
            status="error",
        )
        await self.ui.append_agent_message(ONLINE_AUDIO_SETUP_MESSAGE)
        await self.ui.send_error(ONLINE_AUDIO_SETUP_MESSAGE)
        await self._ask_method_choice()

    async def _ask_local_choice(self, local_file: str) -> None:
        """Ask local choice for play selection session.

        Coordinates the ask local choice method behavior while preserving play selection session state and contracts.

        Args:
            local_file: Input value used by the ask local choice operation.

        Returns:
            The computed result for ask local choice.
        """
        await self._ask_confirm(
            message=f"💾 播放本地文件 {_filename(local_file)}?",
            choices=LOCAL_PLAYBACK_CHOICES,
            tool_args={"query": self.query, "file": local_file, "stage": "local_match"},
        )

    async def _ask_method_choice(self) -> None:
        """Ask method choice for play selection session.

        Coordinates the ask method choice method behavior while preserving play selection session state and contracts.

        Returns:
            The computed result for ask method choice.
        """
        tool_args: dict[str, Any] = {"query": self.query, "stage": "method_choice"}
        if self.cache_hit:
            tool_args["cache_id"] = self.cache_hit.get("cache_id")
            tool_args["cached_song"] = self.cache_hit
        await self._ask_confirm(
            message="选择播放方式",
            choices=PLAYBACK_METHOD_CHOICES,
            tool_args=tool_args,
        )

    async def _ask_metadata_candidates(self, query: str) -> None:
        """Ask metadata candidates for play selection session.

        Coordinates the ask metadata candidates method behavior while preserving play selection session state and contracts.

        Args:
            query: Input value used by the ask metadata candidates operation.

        Returns:
            The computed result for ask metadata candidates.
        """
        await self.ui.append_activity(
            kind="tool",
            title="Searching song metadata",
            detail=f"Finding song metadata for {query}.",
            status="pending",
        )
        attempts: list[dict[str, Any]] = []
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
                "label": "没有想听的歌曲",
                "input": {"placeholder": "试试补充更多歌曲信息"},
            }
        )
        await self._ask_confirm(
            message="选择歌曲候选",
            choices=choices,
            tool_args={"query": query, "stage": "song_metadata_candidates"},
            tool_name="song_candidate",
        )

    def _metadata_candidate_choice(self, index: int, candidate: dict[str, Any]) -> dict[str, Any]:
        """Metadata candidate choice for play selection session.

        Coordinates the metadata candidate choice method behavior while preserving play selection session state and contracts.

        Args:
            index: Input value used by the metadata candidate choice operation.
            candidate: Input value used by the metadata candidate choice operation.

        Returns:
            The computed result for metadata candidate choice.
        """
        artist = str(candidate.get("artist") or "-")
        album = str(candidate.get("album") or "-")
        name = str(candidate.get("name") or candidate.get("title") or "-")
        parts = [_duration_text(candidate.get("duration_ms"))]
        provider = str(candidate.get("provider") or candidate.get("metadata_source") or "").strip()
        if provider:
            parts.append(_metadata_provider_label(provider))
        return {
            "value": f"song_candidate:{index}",
            "label": f"{artist}-{album}--{name}",
            "description": " · ".join(part for part in parts if part),
        }

    async def _ask_online_audio_candidates(self, query: str, playback_metadata: dict[str, Any] | None = None) -> None:
        """Ask online audio candidates for play selection session.

        Coordinates the ask online audio candidates method behavior while preserving play selection session state and contracts.

        Args:
            query: Input value used by the ask online audio candidates operation.
            playback_metadata: Input value used by the ask online audio candidates operation.

        Returns:
            The computed result for ask online audio candidates.
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
            await self.ui.append_agent_message(message)
            await self.ui.send_error(message)
            await self._finish("Online playback failed.", status="error")
            return

        choices = [self._online_audio_candidate_choice(item) for item in self.online_audio_candidates]
        choices.append(
            {
                "value": "refine_query",
                "label": "没有想听的歌曲",
                "input": {"placeholder": "试试补充更多信息"},
            }
        )
        await self._ask_confirm(
            message="选择在线音源候选歌曲",
            choices=choices,
            tool_args={"query": query, "stage": "online_audio_candidates"},
            tool_name="online_audio_candidate",
        )

    async def _play_selected_metadata_candidate(self, query: str, playback_metadata: dict[str, Any]) -> None:
        """Play selected metadata candidate for play selection session.

        Coordinates the play selected metadata candidate method behavior while preserving play selection session state and contracts.

        Args:
            query: Input value used by the play selected metadata candidate operation.
            playback_metadata: Input value used by the play selected metadata candidate operation.

        Returns:
            The computed result for play selected metadata candidate.
        """
        await self.ui.append_activity(
            kind="tool",
            title="Resolving online audio",
            detail=f"Trying Jamendo, Audius, then YouTube for {query}.",
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
                1,
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
            await self.ui.append_agent_message(message)
            await self.ui.send_error(message)
            await self._finish("Online playback failed.", status="error")
            return

        await self._send_cover_from_task(cover_task)
        self.online_audio_candidates = list(candidates or [])
        if not self.online_audio_candidates:
            message = "No valid online audio matches found."
            await self.ui.append_agent_message(message)
            await self.ui.send_error(message)
            await self._finish("Online playback failed.", status="error")
            return

        candidate = self.online_audio_candidates[0]
        await self._append_source_attempts(candidate.get("source_attempts"))
        result = await self._play_online_audio_candidate(candidate)
        data = result.get("data") if isinstance(result, dict) and isinstance(result.get("data"), dict) else {}
        await self._append_source_attempts(data.get("source_attempts"))
        if _is_failed_tool_result(result):
            await self._finish("Online playback failed.", status="error")
        elif _is_player_confirm_result(result):
            return
        else:
            await self._finish("Online playback selected.")

    async def _send_cover_from_task(self, cover_task: asyncio.Task[dict[str, Any]]) -> None:
        """Send cover from task for play selection session.

        Coordinates the send cover from task method behavior while preserving play selection session state and contracts.

        Args:
            cover_task: Input value used by the send cover from task operation.

        Returns:
            The computed result for send cover from task.
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
        """Append source attempts for play selection session.

        Coordinates the append source attempts method behavior while preserving play selection session state and contracts.

        Args:
            attempts: Input value used by the append source attempts operation.

        Returns:
            The computed result for append source attempts.
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
        """Append metadata attempts for play selection session.

        Coordinates the append metadata attempts method behavior while preserving play selection session state and contracts.

        Args:
            attempts: Input value used by the append metadata attempts operation.

        Returns:
            The computed result for append metadata attempts.
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
        """Online audio candidate choice for play selection session.

        Coordinates the online audio candidate choice method behavior while preserving play selection session state and contracts.

        Args:
            candidate: Input value used by the online audio candidate choice operation.

        Returns:
            The computed result for online audio candidate choice.
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
        """Ask confirm for play selection session.

        Coordinates the ask confirm method behavior while preserving play selection session state and contracts.

        Args:
            message: Input value used by the ask confirm operation.
            choices: Input value used by the ask confirm operation.
            tool_args: Input value used by the ask confirm operation.
            tool_name: Input value used by the ask confirm operation.

        Returns:
            The computed result for ask confirm.
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

    async def _play_from_provider(self, tool_name: str, provider: str) -> None:
        """Play from provider for play selection session.

        Coordinates the play from provider method behavior while preserving play selection session state and contracts.

        Args:
            tool_name: Input value used by the play from provider operation.
            provider: Input value used by the play from provider operation.

        Returns:
            The computed result for play from provider.
        """
        args: dict[str, Any] = {"query": self.query}
        cached_item = self._cached_item_for_provider(provider)
        if cached_item and cached_item.get("uri"):
            args = {"uri": cached_item["uri"], "query": self.query}
        result = await self._invoke_playback(tool_name, args, cache_provider=provider)
        if _is_player_confirm_result(result):
            return
        await self._finish(f"{provider.replace('_', ' ').title()} playback selected.")

    def _cached_item_for_provider(self, provider: str) -> dict[str, Any] | None:
        """Cached item for provider for play selection session.

        Coordinates the cached item for provider method behavior while preserving play selection session state and contracts.

        Args:
            provider: Input value used by the cached item for provider operation.

        Returns:
            The computed result for cached item for provider.
        """
        if not self.cache_hit:
            return None
        try:
            full = resolve_cached_song(str(self.cache_hit["cache_id"]))
        except Exception:
            return None
        providers = full.get("providers")
        if isinstance(providers, dict) and isinstance(providers.get(provider), dict):
            return providers[provider]
        if full.get("provider") == provider:
            return full
        return None

    async def _invoke_playback(
        self,
        tool_name: str,
        args: dict[str, Any],
        *,
        cache_provider: str | None = None,
        pending_detail: str | None = None,
    ) -> dict[str, Any]:
        """Invoke playback for play selection session.

        Coordinates the invoke playback method behavior while preserving play selection session state and contracts.

        Args:
            tool_name: Input value used by the invoke playback operation.
            args: Input value used by the invoke playback operation.
            cache_provider: Input value used by the invoke playback operation.
            pending_detail: Input value used by the invoke playback operation.

        Returns:
            The computed result for invoke playback.
        """
        if pending_detail:
            await self.ui.append_activity(
                kind="tool",
                title=f"Calling {tool_name}",
                detail=pending_detail,
                status="pending",
            )
        try:
            result = await asyncio.to_thread(registry.invoke, tool_name, args)
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
            await self.ui.append_agent_message(message)
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

    async def _play_online_audio_candidate(self, candidate: dict[str, Any]) -> dict[str, Any]:
        """Play online audio candidate for play selection session.

        Coordinates the play online audio candidate method behavior while preserving play selection session state and contracts.

        Args:
            candidate: Input value used by the play online audio candidate operation.

        Returns:
            The computed result for play online audio candidate.
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
        if _is_failed_tool_result(result):
            message = _friendly_runtime_error_message(result, fallback="Playback failed.")
            await self.ui.append_agent_message(message)
            await self.ui.send_error(message)
        if isinstance(result, dict) and result.get("status") == "success":
            try:
                await asyncio.to_thread(upsert_cached_song, dict(result.get("data") or {}))
            except Exception:
                pass
        return result

    async def _ask_player_confirm(self, result: dict[str, Any]) -> None:
        """Ask player confirm for play selection session.

        Coordinates the ask player confirm method behavior while preserving play selection session state and contracts.

        Args:
            result: Input value used by the ask player confirm operation.

        Returns:
            The computed result for ask player confirm.
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
        """Complete player confirmation for play selection session.

        Coordinates the complete player confirmation method behavior while preserving play selection session state and contracts.

        Args:
            decision: Input value used by the complete player confirmation operation.

        Returns:
            The computed result for complete player confirmation.
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
            await self.ui.append_agent_message(message)
            await self.ui.send_error(message)
            await self._finish("Playback failed.", status="error")
            return
        if isinstance(result, dict) and result.get("status") == "success":
            try:
                await asyncio.to_thread(upsert_cached_song, dict(result.get("data") or {}))
            except Exception:
                pass
        await self._finish("Online playback selected.")

    async def _finish(self, detail: str, *, status: str = "success") -> None:
        """Finish for play selection session.

        Coordinates the finish method behavior while preserving play selection session state and contracts.

        Args:
            detail: Input value used by the finish operation.
            status: Input value used by the finish operation.

        Returns:
            The computed result for finish.
        """
        setattr(self.ui, "_play_selection", None)
        await self.ui.append_activity(kind="status", title="Playback selection", detail=detail, status=status)


class WebSocketRunner:
    """Represents web socket runner.

    Encapsulates web socket runner data and behavior used by Sonex runtime flows.
    """
    def __init__(self) -> None:
        """Init for web socket runner.

        Coordinates the init method behavior while preserving web socket runner state and contracts.
        """
        self.tools = registry
        self.memory_store = memory_store
        self._running_task: asyncio.Task[None] | None = None
        self._confirm_queue: queue.Queue[tuple[str, Any]] = queue.Queue()

    async def handle_ws(self, ws: WebSocket) -> None:
        """Handle ws for web socket runner.

        Coordinates the handle ws method behavior while preserving web socket runner state and contracts.

        Args:
            ws: Input value used by the handle ws operation.

        Returns:
            The computed result for handle ws.
        """
        await ws.accept()
        ui = WebSocketUIAdapter(ws)
        await ui._send({"type": "queue", "tracks": _queue_payload()})
        await self._handle_startup_auth(ui)
        playback_sync_task = asyncio.create_task(self._sync_spotify_playback(ui))
        local_playback_sync_task = asyncio.create_task(self._sync_local_playback(ui))

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

                elif data.get("type") == "setup_input":
                    spotify_setup = getattr(ui, "_spotify_setup", None)
                    if spotify_setup:
                        await spotify_setup.handle_input(str(data.get("value") or ""))
                        continue
                    apple_music_setup = getattr(ui, "_apple_music_setup", None)
                    if apple_music_setup:
                        await apple_music_setup.handle_input(str(data.get("value") or ""))

                elif data.get("type") == "auth_setup_input":
                    model_setup = getattr(ui, "_model_setup", None)
                    if model_setup:
                        await model_setup.handle_input(str(data.get("value") or ""))
                        continue
                    auth_setup = getattr(ui, "_auth_setup", None)
                    if auth_setup:
                        await auth_setup.handle_input(str(data.get("value") or ""))
                        continue
                    apple_music_setup = getattr(ui, "_apple_music_setup", None)
                    if apple_music_setup:
                        await apple_music_setup.handle_input(str(data.get("value") or ""))

                elif data.get("type") == "confirm_result":
                    decision = data.get("decision")
                    if decision is None:
                        confirmed = data.get("confirmed")
                        if confirmed is None:
                            confirmed = data.get("ok")
                        decision = "allow_once" if confirmed else "deny"
                    confirm_id = str(data.get("id") or "")
                    music_confirmation = getattr(ui, "_music_intent_confirmation", None)
                    if music_confirmation and music_confirmation.owns_confirm(confirm_id):
                        await music_confirmation.handle_choice(decision)
                        continue
                    play_selection = getattr(ui, "_play_selection", None)
                    if play_selection and play_selection.owns_confirm(confirm_id):
                        await play_selection.handle_choice(decision)
                        continue
                    self._confirm_queue.put((confirm_id, decision))

                elif data.get("type") == "bye":
                    messages = _coerce_transcript_messages(data.get("messages"))
                    reason = str(data.get("reason") or "bye")
                    await self._handle_bye(ui, messages=messages, reason=reason)
                    break

        except WebSocketDisconnect:
            pass
        finally:
            spotify_setup = getattr(ui, "_spotify_setup", None)
            if spotify_setup and spotify_setup.oauth_task:
                spotify_setup.oauth_task.cancel()
            auth_setup = getattr(ui, "_auth_setup", None)
            if auth_setup and auth_setup.oauth_task:
                auth_setup.oauth_task.cancel()
            apple_music_setup = getattr(ui, "_apple_music_setup", None)
            playback_sync_task.cancel()
            local_playback_sync_task.cancel()
            with suppress(asyncio.CancelledError):
                if spotify_setup and spotify_setup.oauth_task:
                    await spotify_setup.oauth_task
            with suppress(asyncio.CancelledError):
                if auth_setup and auth_setup.oauth_task:
                    await auth_setup.oauth_task
            with suppress(asyncio.CancelledError):
                await playback_sync_task
            with suppress(asyncio.CancelledError):
                await local_playback_sync_task
            self._confirm_queue.put(("", False))

    async def _handle_startup_auth(self, ui: WebSocketUIAdapter) -> None:
        """Handle startup auth for web socket runner.

        Coordinates the handle startup auth method behavior while preserving web socket runner state and contracts.

        Args:
            ui: Input value used by the handle startup auth operation.

        Returns:
            The computed result for handle startup auth.
        """
        state = _llm_auth_state()
        await ui.send_auth_state(state)
        if state.ready:
            return
        setup = AuthSetupSession(ui, state.provider, None, self)
        setattr(ui, "_auth_setup", setup)
        await setup.start(state.reason)

    async def _sync_spotify_playback(self, ui: WebSocketUIAdapter) -> None:
        """Sync spotify playback for web socket runner.

        Coordinates the sync spotify playback method behavior while preserving web socket runner state and contracts.

        Args:
            ui: Input value used by the sync spotify playback operation.

        Returns:
            The computed result for sync spotify playback.
        """
        last_signature: tuple[Any, ...] | None = None
        last_cover_url: str | None = None
        reported_failures: set[str] = set()
        while not ui.closed:
            try:
                result = await asyncio.to_thread(spotify_current_playback)
                if isinstance(result, dict) and result.get("status") == "success":
                    player_state, cover_url = _extract_music_state(result)
                    if player_state:
                        remember_recent_track(player_state)
                        signature = _player_sync_signature(player_state)
                        if signature != last_signature:
                            await ui._send({"type": "player", "state": player_state})
                            await ui._send({"type": "queue", "tracks": _queue_payload()})
                            last_signature = signature
                        if cover_url and cover_url != last_cover_url:
                            await ui.send_cover(cover_url)
                            last_cover_url = cover_url
                elif isinstance(result, dict) and result.get("status") in {"fail", "error"}:
                    failure_key = str(result.get("error_code") or result.get("message") or "spotify_sync_failed")
                    if failure_key not in reported_failures:
                        reported_failures.add(failure_key)
                        await ui.append_agent_message(_friendly_runtime_error_message(result, fallback="Spotify playback sync failed."))
                    if failure_key == "SPOTIFY_PREMIUM_REQUIRED":
                        return
            except Exception:
                pass
            await asyncio.sleep(2)

    async def _sync_local_playback(self, ui: WebSocketUIAdapter) -> None:
        """Sync local playback for web socket runner.

        Coordinates the sync local playback method behavior while preserving web socket runner state and contracts.

        Args:
            ui: Input value used by the sync local playback operation.

        Returns:
            The computed result for sync local playback.
        """
        last_signature: tuple[Any, ...] | None = None
        last_payload: dict[str, Any] | None = None
        next_status_probe_at = 0.0
        while not ui.closed:
            try:
                now = time.monotonic()
                should_probe = now >= next_status_probe_at
                if should_probe:
                    probe_started = time.monotonic()
                    state = await asyncio.to_thread(local_playback_controller.status)
                    _player_debug(f"local playback status probe {int((time.monotonic() - probe_started) * 1000)}ms")
                    payload = state.to_dict()
                    next_status_probe_at = now + LOCAL_PLAYBACK_STATUS_PROBE_SECONDS
                else:
                    payload = _project_local_playback_state(last_payload, _timestamp_ms()) if last_payload else None
                if payload is None:
                    await asyncio.sleep(LOCAL_PLAYBACK_SYNC_INTERVAL_SECONDS)
                    continue
                signature = _player_sync_signature(payload)
                if signature != last_signature:
                    await ui._send({"type": "player", "state": payload})
                    last_signature = signature
                last_payload = payload
            except Exception:
                last_payload = None
                next_status_probe_at = time.monotonic() + LOCAL_PLAYBACK_STATUS_PROBE_SECONDS
            await asyncio.sleep(LOCAL_PLAYBACK_SYNC_INTERVAL_SECONDS)

    async def _handle_user_input(
        self,
        ui: WebSocketUIAdapter,
        user_input: str,
        *,
        append_user_message: bool = True,
    ) -> None:
        """Handle user input for web socket runner.

        Coordinates the handle user input method behavior while preserving web socket runner state and contracts.

        Args:
            ui: Input value used by the handle user input operation.
            user_input: Input value used by the handle user input operation.
            append_user_message: Input value used by the handle user input operation.

        Returns:
            The computed result for handle user input.
        """
        user_input = user_input.strip()
        if not user_input:
            return

        if append_user_message:
            await ui.append_user_message(user_input)

        play_selection = getattr(ui, "_play_selection", None)
        if play_selection and await play_selection.handle_refinement(user_input):
            return

        parsed_command = parse_builtin_command(user_input)
        if parsed_command is not None:
            if parsed_command.known and parsed_command.command and parsed_command.command.name == "play":
                if self._running_task and not self._running_task.done():
                    ui.set_status(UiStatus(phase="Busy", message="Remixing..."))
                    return
                session = PlaySelectionSession(ui, self, parsed_command.args)
                setattr(ui, "_play_selection", session)
                await session.start()
                return

            command_intent = parsed_command.command_intent()
            if command_intent is None:
                await self._handle_builtin_command(ui, parsed_command)
                return

            if self._running_task and not self._running_task.done():
                ui.set_status(UiStatus(phase="Busy", message="Remixing..."))
                return

            ready, provider, reason = _llm_auth_ready()
            if not ready:
                setup = AuthSetupSession(ui, provider, user_input, self)
                setattr(ui, "_auth_setup", setup)
                await setup.start(reason)
                return

            if command_intent.command == "recommend":
                setattr(ui, "_recommendation_turn_active", True)
            self._running_task = asyncio.create_task(
                self._run_agent_turn(ui, user_input, command_intent=command_intent)
            )
            return

        if _is_spotify_setup_request(user_input):
            setup = SpotifySetupSession(ui)
            await setup.start()
            setattr(ui, "_spotify_setup", setup)
            return

        if _is_apple_music_setup_request(user_input):
            setup = AppleMusicSetupSession(ui)
            await setup.start()
            setattr(ui, "_apple_music_setup", setup)
            return

        if self._running_task and not self._running_task.done():
            ui.set_status(UiStatus(phase="Busy", message="Remixing..."))
            return

        decision = classify_music_intent_fast(user_input)
        if decision is None:
            decision = await asyncio.to_thread(classify_music_intent, user_input)
        if decision.route == MusicIntentRoute.EXPLICIT_PLAY:
            query = await self._resolve_music_query(ui, decision)
            if query is None:
                return
            session = PlaySelectionSession(ui, self, query)
            setattr(ui, "_play_selection", session)
            await session.start()
            return

        if decision.route == MusicIntentRoute.CONFIRM_TRACK_PLAY and decision.query:
            confirmation = MusicIntentConfirmationSession(ui, self, user_input, decision.query)
            setattr(ui, "_music_intent_confirmation", confirmation)
            await confirmation.start()
            return

        ready, provider, reason = _llm_auth_ready()
        if not ready:
            setup = AuthSetupSession(ui, provider, user_input, self)
            setattr(ui, "_auth_setup", setup)
            await setup.start(reason)
            return

        command_intent = self._music_agent_intent(user_input, decision)
        if command_intent.command == "recommend":
            setattr(ui, "_recommendation_turn_active", True)
        self._running_task = asyncio.create_task(
            self._run_agent_turn(ui, user_input, command_intent=command_intent)
        )

    async def _resolve_music_query(self, ui: WebSocketUIAdapter, decision: MusicIntentDecision) -> str | None:
        """Resolve music query for web socket runner.

        Coordinates the resolve music query method behavior while preserving web socket runner state and contracts.

        Args:
            ui: Input value used by the resolve music query operation.
            decision: Input value used by the resolve music query operation.

        Returns:
            The computed result for resolve music query.
        """
        if decision.recommendation_index is None:
            return decision.query
        tracks = list(getattr(ui, "_last_recommendation_tracks", []) or [])
        index = decision.recommendation_index
        if not tracks:
            await ui.append_agent_message("当前会话还没有可引用的推荐列表。请先让我推荐几首歌。")
            return None
        if index < 1 or index > len(tracks):
            await ui.append_agent_message(f"推荐序号超出范围，请选择 1-{len(tracks)}。")
            return None
        track = tracks[index - 1]
        name = str(track.get("name") or track.get("title") or "").strip()
        artist = str(track.get("artist") or "").strip()
        if not artist:
            artists = track.get("artists") or []
            if artists:
                artist = str(artists[0])
        return " ".join(part for part in (name, artist) if part).strip() or None

    def _music_agent_intent(self, user_input: str, decision: MusicIntentDecision) -> CommandIntent:
        """Music agent intent for web socket runner.

        Coordinates the music agent intent method behavior while preserving web socket runner state and contracts.

        Args:
            user_input: Input value used by the music agent intent operation.
            decision: Input value used by the music agent intent operation.

        Returns:
            The computed result for music agent intent.
        """
        if decision.route == MusicIntentRoute.RECOMMEND:
            return CommandIntent(
                command="recommend",
                raw=user_input,
                args=decision.query or user_input,
                intent_prompt=(
                    "Recommend music using only the allowed read-only tools. Return a concise numbered text list "
                    "and end with a normal text question about what the user wants to hear. Do not start playback."
                ),
                allowed_tools=RECOMMEND_AGENT_TOOLS,
            )
        allowed_tools = tuple(
            name for name, spec in self.tools.tools.items()
            if spec.enabled and name not in PLAYBACK_AGENT_TOOLS
        )
        return CommandIntent(
            command="general",
            raw=user_input,
            args="",
            intent_prompt="Answer normally. Do not start music playback; playback is owned by the system router.",
            allowed_tools=allowed_tools,
        )

    async def _handle_builtin_command(self, ui: WebSocketUIAdapter, parsed_command: Any) -> None:
        """Handle builtin command for web socket runner.

        Coordinates the handle builtin command method behavior while preserving web socket runner state and contracts.

        Args:
            ui: Input value used by the handle builtin command operation.
            parsed_command: Input value used by the handle builtin command operation.

        Returns:
            The computed result for handle builtin command.
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
                await ui.append_agent_message(suggestions)
                await ui.append_activity(
                    kind="status",
                    title="Slash commands",
                    detail=suggestions,
                    status="success",
                )
                return

        if not parsed_command.known:
            message = f"Unknown command '/{parsed_command.name}'. Type /help to see available commands."
            await ui.append_activity(
                kind="error",
                title="Unknown command",
                detail=message,
                status="error",
            )
            await ui.append_agent_message(message)
            return

        command_name = parsed_command.command.name
        args = parsed_command.args

        if command_name == "help":
            prefix = args if args.startswith("/") else args
            commands = command_suggestions(prefix)
            if not commands:
                await ui.append_agent_message(format_help(prefix))
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

        if command_name == "model":
            setup = ModelSelectionSession(ui)
            setattr(ui, "_model_setup", setup)
            await setup.start()
            return

        if command_name == "setup":
            await self._start_builtin_setup(ui, args)
            return

        if command_name == "logout":
            await self._handle_logout(ui)
            return

        if command_name in LOCAL_PLAYBACK_CONTROL_TOOLS:
            await self._handle_local_playback_control(ui, command_name)
            return

        if command_name == "volume":
            await self._handle_local_playback_volume(ui, args)
            return

        if command_name == "player":
            await self._handle_local_playback_player(ui, args)
            return

        if command_name in {"bye", "quit"}:
            await self._handle_bye(ui, messages=ui.transcript, reason=command_name)
            return

        message = f"Command '/{command_name}' is handled by the agent."
        await ui.append_activity(kind="status", title="Agent command", detail=message, status="success")

    async def _handle_local_playback_control(self, ui: WebSocketUIAdapter, command_name: str) -> None:
        """Handle local playback control for web socket runner.

        Coordinates the handle local playback control method behavior while preserving web socket runner state and contracts.

        Args:
            ui: Input value used by the handle local playback control operation.
            command_name: Input value used by the handle local playback control operation.

        Returns:
            The computed result for handle local playback control.
        """
        tool_name = LOCAL_PLAYBACK_CONTROL_TOOLS[command_name]
        try:
            result = registry.invoke(tool_name, {})
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
        """Handle local playback volume for web socket runner.

        Coordinates the handle local playback volume method behavior while preserving web socket runner state and contracts.

        Args:
            ui: Input value used by the handle local playback volume operation.
            args: Input value used by the handle local playback volume operation.

        Returns:
            The computed result for handle local playback volume.
        """
        try:
            volume = int(args.strip())
            if not 0 <= volume <= 100:
                raise ValueError
        except ValueError:
            message = "Usage: /volume <0-100>"
            await ui.append_activity(kind="error", title="Invalid volume", detail=message, status="error")
            await ui.append_agent_message(message)
            return

        tool_name = "local_playback_volume"
        try:
            result = registry.invoke(tool_name, {"volume_percent": volume})
        except Exception as exc:
            result = {
                "status": "fail",
                "tool": tool_name,
                "message": sanitize_error_message(exc),
                "error_code": "PLAYBACK_CONTROL_FAILED",
                "data": {},
            }
        await self._sync_tool_result_ui(ui, tool_name, result)

    async def _handle_local_playback_player(self, ui: WebSocketUIAdapter, args: str) -> None:
        """Handle local playback player for web socket runner.

        Coordinates the handle local playback player method behavior while preserving web socket runner state and contracts.

        Args:
            ui: Input value used by the handle local playback player operation.
            args: Input value used by the handle local playback player operation.

        Returns:
            The computed result for handle local playback player.
        """
        backend = args.strip().lower()
        if backend not in LOCAL_PLAYBACK_BACKENDS:
            message = "Usage: /player <auto|mpv|cvlc>"
            await ui.append_activity(kind="error", title="Invalid player backend", detail=message, status="error")
            await ui.append_agent_message(message)
            return

        tool_name = "local_playback_player"
        try:
            result = registry.invoke(tool_name, {"backend": backend})
        except Exception as exc:
            result = {
                "status": "fail",
                "tool": tool_name,
                "message": sanitize_error_message(exc),
                "error_code": "PLAYBACK_CONTROL_FAILED",
                "data": {},
            }
        await self._sync_tool_result_ui(ui, tool_name, result)

    async def _handle_logout(self, ui: WebSocketUIAdapter) -> None:
        """Handle logout for web socket runner.

        Coordinates the handle logout method behavior while preserving web socket runner state and contracts.

        Args:
            ui: Input value used by the handle logout operation.

        Returns:
            The computed result for handle logout.
        """
        state = _llm_auth_state()
        if not state.ready:
            await ui.append_agent_message("You are not logged in.")
            return

        if state.credential_source == "env":
            await ui.append_agent_message(
                "Cannot clear environment variable credentials from the TUI. Remove the provider API key from your environment, then restart Sonex."
            )
            await self._handle_bye(ui, messages=ui.transcript, reason="logout")
            return

        if state.credential_source == "local" or state.auth_type == "local":
            await ui.append_agent_message(f"Provider '{state.provider}' does not require login.")
            await self._handle_bye(ui, messages=ui.transcript, reason="logout")
            return

        if state.credential_source != "auth.json":
            await ui.append_agent_message("You are not logged in.")
            return

        try:
            removed = remove_provider(state.provider)
            os.environ.pop("SONEX_DEFAULT_PROVIDER", None)
            os.environ.pop("SONEX_DEFAULT_MODEL", None)
            ThinkingConfig._state = None
        except Exception as exc:
            await ui.append_agent_message(sanitize_error_message(exc))
            return

        if not removed:
            await ui.append_agent_message("You are not logged in.")
            return

        await ui.send_auth_state(_llm_auth_state())
        await ui.append_agent_message("Successfully log out.")
        await self._handle_bye(ui, messages=ui.transcript, reason="logout")

    async def _handle_bye(
        self,
        ui: WebSocketUIAdapter,
        *,
        messages: list[dict[str, str]],
        reason: str,
    ) -> None:
        """Handle bye for web socket runner.

        Coordinates the handle bye method behavior while preserving web socket runner state and contracts.

        Args:
            ui: Input value used by the handle bye operation.
            messages: Input value used by the handle bye operation.
            reason: Input value used by the handle bye operation.

        Returns:
            The computed result for handle bye.
        """
        path = _save_session_transcript(messages, reason=reason)
        message = f"Session saved to {path}. Bye."
        await ui.append_activity(
            kind="status",
            title="Session saved",
            detail=str(path),
            status="success",
        )
        await ui.send_status(UiStatus(phase="Bye", message=message))
        await ui.append_agent_message(message)
        await ui._send({"type": "bye", "path": str(path), "message": message})
        await ui.close()

    async def _start_builtin_setup(self, ui: WebSocketUIAdapter, args: str) -> None:
        """Start builtin setup for web socket runner.

        Coordinates the start builtin setup method behavior while preserving web socket runner state and contracts.

        Args:
            ui: Input value used by the start builtin setup operation.
            args: Input value used by the start builtin setup operation.

        Returns:
            The computed result for start builtin setup.
        """
        provider = (args or "spotify").strip().lower().replace("-", "_")
        if provider in {"spotify", "sp"}:
            setup = SpotifySetupSession(ui)
            await setup.start()
            setattr(ui, "_spotify_setup", setup)
            return
        if provider in {"apple", "apple_music", "applemusic"}:
            setup = AppleMusicSetupSession(ui)
            await setup.start()
            setattr(ui, "_apple_music_setup", setup)
            return
        if provider in {"jamendo", "audius"}:
            setup = OpenAudioSetupSession(ui, provider)
            setattr(ui, "_auth_setup", setup)
            await setup.start()
            return

        message = "Unknown setup provider. Use /setup spotify, /setup apple_music, /setup jamendo, or /setup audius."
        await ui.append_activity(kind="error", title="Unknown setup provider", detail=message, status="error")
        await ui.append_agent_message(message)

    async def _sync_tool_result_ui(
        self,
        ui: WebSocketUIAdapter,
        tool_name: str,
        tool_result: Any,
        activity_id: str | None = None,
    ) -> None:
        """Sync tool result ui for web socket runner.

        Coordinates the sync tool result ui method behavior while preserving web socket runner state and contracts.

        Args:
            ui: Input value used by the sync tool result ui operation.
            tool_name: Input value used by the sync tool result ui operation.
            tool_result: Input value used by the sync tool result ui operation.
            activity_id: Input value used by the sync tool result ui operation.

        Returns:
            The computed result for sync tool result ui.
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
        should_sync_player = result_status == "success" and bool(
            player_state and (player_state.get("is_playing") or is_control_tool)
        )
        if should_sync_player and player_state:
            await ui._send({"type": "player", "state": player_state})
            if tool_name not in SEARCH_RESULT_TOOLS:
                if player_state.get("provider") == "apple_music":
                    remember_apple_music_recent_track(player_state)
                else:
                    remember_recent_track(player_state)
                await ui._send({"type": "queue", "tracks": _queue_payload()})
        if should_sync_player and cover_url:
            await ui.send_cover(cover_url)

    async def _run_agent_turn(
        self,
        ui: WebSocketUIAdapter,
        user_input: str,
        command_intent: CommandIntent | None = None,
    ) -> None:
        """Run agent turn for web socket runner.

        Coordinates the run agent turn method behavior while preserving web socket runner state and contracts.

        Args:
            ui: Input value used by the run agent turn operation.
            user_input: Input value used by the run agent turn operation.
            command_intent: Input value used by the run agent turn operation.

        Returns:
            The computed result for run agent turn.
        """
        event_queue: asyncio.Queue[RunnerEvent] = asyncio.Queue()
        self._confirm_queue = queue.Queue()
        loop = asyncio.get_running_loop()
        turn_started = time.monotonic()
        tick_interval = 0.25
        current_phase = "Planning"
        current_message = "Planning..."
        latest_tokens = 0
        planning_activity_id = _new_event_id("activity")
        planning_finished = False

        def elapsed_ms() -> int:
            """Elapsed ms.

            Coordinates elapsed ms logic for the surrounding Sonex flow.

            Returns:
                The computed result for elapsed ms.
            """
            return int((time.monotonic() - turn_started) * 1000)

        def emit(event: RunnerEvent) -> None:
            """Emit.

            Coordinates emit logic for the surrounding Sonex flow.

            Args:
                event: Input value used by the emit operation.

            Returns:
                The computed result for emit.
            """
            loop.call_soon_threadsafe(event_queue.put_nowait, event)

        def wait_for_confirm(confirm_id: str) -> Any:
            """Wait for confirm.

            Coordinates wait for confirm logic for the surrounding Sonex flow.

            Args:
                confirm_id: Input value used by the wait for confirm operation.

            Returns:
                The computed result for wait for confirm.
            """
            while True:
                incoming_id, decision = self._confirm_queue.get()
                if not incoming_id or incoming_id == confirm_id:
                    return decision

        def producer() -> None:
            """Producer.

            Coordinates producer logic for the surrounding Sonex flow.

            Returns:
                The computed result for producer.
            """
            decision: Any = None
            try:
                if command_intent is None:
                    gen = agent_loop(user_input=user_input, tools=self.tools)
                else:
                    gen = agent_loop(user_input=user_input, tools=self.tools, command_intent=command_intent)
                while True:
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
                                    "choices": confirm_payload.get("choices"),
                                },
                            )
                        )
                        decision = wait_for_confirm(confirm_id)
                        emit(
                            RunnerEvent(
                                type="confirm_decision",
                                data={"id": confirm_id, "decision": decision},
                            )
                        )
                        continue

                    data: dict[str, Any] = {}
                    if evt.type == "status":
                        data = {"content": evt.content, "tokens": evt.tokens}
                    elif evt.type == "tool":
                        data = {
                            "tool_name": evt.tool,
                            "tool_args": evt.args or {},
                            "tool_result": evt.result,
                        }
                    elif evt.type in {"error", "complete"}:
                        data = {"content": evt.content, "tool_name": evt.tool}

                    emit(RunnerEvent(type=evt.type, data=data))
            except StopIteration:
                pass
            except Exception as exc:
                emit(
                    RunnerEvent(type="error", data={"content": sanitize_error_message(exc)})
                )
            finally:
                emit(RunnerEvent(type="done", data={}))

        async def send_current_status() -> None:
            """Asynchronously send current status.

            Coordinates non-blocking send current status work for the surrounding Sonex flow.

            Returns:
                The computed result for send current status.
            """
            await ui.send_status(
                UiStatus(phase=current_phase, message=current_message),
                tokens=latest_tokens,
                elapsed_ms=elapsed_ms(),
                active=True,
            )

        async def finish_planning(status: str, detail: str) -> None:
            """Asynchronously finish planning.

            Coordinates non-blocking finish planning work for the surrounding Sonex flow.

            Args:
                status: Input value used by the finish planning operation.
                detail: Input value used by the finish planning operation.

            Returns:
                The computed result for finish planning.
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

        producer_thread = threading.Thread(target=producer, name="sonex-agent-turn", daemon=True)
        producer_thread.start()
        active_tool_activity_id: str | None = None
        active_tool_name: str | None = None

        while True:
            try:
                event = await asyncio.wait_for(event_queue.get(), timeout=tick_interval)
            except asyncio.TimeoutError:
                await send_current_status()
                continue

            if event.type == "done":
                await finish_planning("success", "Planning complete.")
                break

            if event.type == "status":
                phase = event.data.get("content")
                current_phase = str(phase).title()
                current_message = f"{phase}..."
                if isinstance(event.data.get("tokens"), int):
                    latest_tokens = int(event.data["tokens"])
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

            if event.type == "tool":
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

            if event.type == "complete":
                await finish_planning("success", "Planning complete.")
                content = str(event.data.get("content") or "")
                if content:
                    await ui.append_agent_message(content)

        if producer_thread.is_alive():
            producer_thread.join(timeout=1)
        setattr(ui, "_recommendation_turn_active", False)
        await ui.send_status(UiStatus(phase="Idle", message="Snoozing..."), active=False)
        self._running_task = None
