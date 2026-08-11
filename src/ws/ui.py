"""Websocket UI adapter and event helpers for Sonex runtime."""

from __future__ import annotations

import asyncio
import json
import threading
import time
import uuid
from contextlib import suppress
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from src.agent.events import UiStatus
from src.api.builtin_commands import BuiltinCommand
from src.llm.transport import Usage
from src.tools.cover_patterns import CoverPatternError, fetch_cover_pattern, generate_cover_pattern
from src.tools.cover_sources import cover_bytes_for_source
from src.ws.types import AuthRuntimeState


class WebSocketUIAdapter:
    """Represents web socket ui adapter.

    Encapsulates web socket ui adapter data and behavior used by Sonex runtime flows.
    """
    def __init__(self, ws: WebSocket, *, session_id: str) -> None:
        """Prepares init for an internal Sonex flow.

        Typical use: Use this helper when nearby code needs init without duplicating the local rules.

        Example: __init__(ws=..., session_id=...) -> returns the value used by the surrounding Sonex flow.
        """
        self.ws = ws
        self.session_id = session_id
        self.closed = False
        self.transcript: list[dict[str, Any]] = []
        self.input_tokens = 0
        self.output_tokens = 0
        self._usage_lock = threading.Lock()
        self._event_loop = asyncio.get_running_loop()

    async def _send(self, payload: dict[str, Any]) -> None:
        """Prepares send for an internal Sonex flow.

        Typical use: Use this helper when nearby code needs send without duplicating the local rules.

        Example: await _send(payload=...) -> returns the value used by the surrounding Sonex flow.
        """
        if self.closed:
            return
        try:
            await self.ws.send_text(json.dumps(payload, ensure_ascii=False, default=str))
        except (RuntimeError, WebSocketDisconnect):
            self.closed = True

    async def send_session_state(self) -> None:
        """Send the canonical chat session identity for this connection."""
        await self._send(
            {
                "type": "session_state",
                "session_id": self.session_id,
            }
        )

    def record_token_usage(self, usage: Usage) -> None:
        """Accumulate provider-reported tokens and publish the session snapshot."""
        input_tokens = max(0, int(usage.prompt_tokens or 0))
        output_tokens = max(0, int(usage.completion_tokens or 0))
        with self._usage_lock:
            self.input_tokens += input_tokens
            self.output_tokens += output_tokens
            payload = {
                "type": "usage_state",
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
            }
            self._event_loop.call_soon_threadsafe(
                lambda: asyncio.create_task(self._send(payload))
            )

    async def send_agent_working_state(self, turn_id: str, *, active: bool) -> None:
        """Show or clear the Working indicator for one foreground Agent turn."""
        await self._send(
            {
                "type": "agent_working_state",
                "turn_id": turn_id,
                "active": active,
            }
        )

    async def append_user_message(self, text: str) -> None:
        """Coordinates append user message for the current Sonex flow.

        Typical use: Use this function when runtime code needs append user message as part of a Sonex command, playback, auth, llm, or ui path.

        Example: await append_user_message(text=...) -> returns the value used by the surrounding Sonex flow.
        """
        self.transcript.append({"role": "user", "content": text})
        await self._send({"type": "chat", "role": "user", "text": text})

    async def append_agent_message(
        self,
        text: str,
        *,
        segments: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
        document: dict[str, Any] | None = None,
        stream: bool = False,
    ) -> None:
        """Append an LLM answer or agent/tool-call explanation."""
        transcript_item: dict[str, Any] = {"role": "agent", "content": text}
        payload: dict[str, Any] = {"type": "chat", "role": "agent", "text": text}
        if segments:
            safe_segments = [dict(segment) for segment in segments]
            transcript_item["segments"] = safe_segments
            payload["segments"] = safe_segments
        if document:
            safe_document = dict(document)
            transcript_item["document"] = safe_document
            payload["document"] = safe_document
        if stream:
            payload["stream"] = True
        mode = getattr(self, "_spotify_mode", None)
        if isinstance(mode, dict) and mode.get("enabled"):
            transcript_item["theme"] = "spotify"
            payload["theme"] = "spotify"
        self.transcript.append(transcript_item)
        await self._send(payload)

    async def append_system_message(self, text: str) -> None:
        """Append a runtime or local-command notice rendered with the System subject."""
        self.transcript.append({"role": "agent", "content": text})
        await self._send(
            {
                "type": "chat",
                "role": "agent",
                "tone": "system",
                "text": text,
            }
        )

    async def append_warning_message(self, text: str) -> None:
        """Append a durable runtime warning using the existing Agent role."""
        self.transcript.append({"role": "agent", "content": text})
        await self._send(
            {
                "type": "chat",
                "role": "agent",
                "tone": "warning",
                "text": text,
            }
        )

    async def append_caution_message(self, text: str) -> None:
        """Append a durable runtime caution using the existing Agent role."""
        self.transcript.append({"role": "agent", "content": text})
        await self._send(
            {
                "type": "chat",
                "role": "agent",
                "tone": "error",
                "text": text,
            }
        )

    async def send_error(self, message: str) -> None:
        """Sends error to the active runtime client.

        Typical use: Use this function when runtime code needs send error as part of a Sonex command, playback, auth, llm, or ui path.

        Example: await send_error(message=...) -> returns the value used by the surrounding Sonex flow.
        """
        await self._send({"type": "error", "message": message, "recoverable": True})

    async def append_tool_message(self, text: str) -> None:
        """Coordinates append tool message for the current Sonex flow.

        Typical use: Use this function when runtime code needs append tool message as part of a Sonex command, playback, auth, llm, or ui path.

        Example: await append_tool_message(text=...) -> returns the value used by the surrounding Sonex flow.
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
        """Coordinates append activity for the current Sonex flow.

        Typical use: Use this function when runtime code needs append activity as part of a Sonex command, playback, auth, llm, or ui path.

        Example: await append_activity(kind=..., title=..., detail=..., status=..., activity_id=...) -> returns the value used by the surrounding Sonex flow.
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
        """Coordinates set status for the current Sonex flow.

        Typical use: Use this function when runtime code needs set status as part of a Sonex command, playback, auth, llm, or ui path.

        Example: set_status(status=...) -> returns the value used by the surrounding Sonex flow.
        """
        asyncio.create_task(
            self.send_status(status)
        )

    async def send_status(
        self,
        status: UiStatus,
        *,
        active: bool | None = None,
    ) -> None:
        """Sends status to the active runtime client.

        Typical use: Use this function when runtime code needs send status as part of a Sonex command, playback, auth, llm, or ui path.

        Example: await send_status(status=..., active=...) -> returns the value used by the surrounding Sonex flow.
        """
        payload = {
            "type": "status",
            "phase": status.phase,
            "message": status.message,
            "tool": status.tool_name,
            "step": status.step,
            "max_steps": status.max_steps,
        }
        if active is not None:
            payload["active"] = active
        await self._send(payload)

    async def send_input_state(self, disabled: bool, reason: str | None = None) -> None:
        """Sends input lock state to the active runtime client."""
        payload: dict[str, Any] = {
            "type": "input_state",
            "disabled": disabled,
        }
        if reason is not None:
            payload["reason"] = reason
        await self._send(payload)

    async def send_auth_state(self, state: AuthRuntimeState) -> None:
        """Sends auth state to the active runtime client.

        Typical use: Use this function when runtime code needs send auth state as part of a Sonex command, playback, auth, llm, or ui path.

        Example: await send_auth_state(state=...) -> returns the value used by the surrounding Sonex flow.
        """
        await self._send(state.to_event())

    async def send_cover(self, url: str) -> None:
        """Sends cover to the active runtime client.

        Typical use: Use this function when runtime code needs send cover as part of a Sonex command, playback, auth, llm, or ui path.

        Example: await send_cover(url=...) -> returns the value used by the surrounding Sonex flow.
        """
        await self._send({"type": "cover", "url": url})
        asyncio.create_task(_send_cover_pattern(self, url))

    async def ask_confirm(self, attached: dict[str, Any]) -> None:
        """Coordinates ask confirm for the current Sonex flow.

        Typical use: Use this function when runtime code needs ask confirm as part of a Sonex command, playback, auth, llm, or ui path.

        Example: await ask_confirm(attached=...) -> returns the value used by the surrounding Sonex flow.
        """
        await self._send(
            {
                "type": "confirm",
                "id": attached.get("id"),
                "tool_name": attached.get("tool_name"),
                "tool_args": attached.get("tool_args"),
                "message": attached.get("message"),
                "warning": attached.get("warning"),
                "hide_hint": attached.get("hide_hint"),
                "choices": attached.get("choices"),
                "variant": attached.get("variant"),
                "commands": attached.get("commands"),
                "page_index": attached.get("page_index"),
                "page_count": attached.get("page_count"),
            }
        )

    async def dismiss_confirm(self, confirm_id: str) -> None:
        """Dismiss one live confirmation without adding transcript output."""
        await self._send({"type": "confirm_dismiss", "id": confirm_id})

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
        """Sends spotify setup to the active runtime client.

        Typical use: Use this function when runtime code needs send spotify setup as part of a Sonex command, playback, auth, llm, or ui path.

        Example: await send_spotify_setup(step=..., title=..., message=..., prompt=..., mask=..., active=...) -> returns the value used by the surrounding Sonex flow.
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
        placeholder: str | None = None,
        help_text: str | None = None,
        mask: bool = False,
        active: bool = True,
        methods: list[dict[str, Any]] | None = None,
        providers: list[dict[str, Any]] | None = None,
        models: list[dict[str, Any]] | None = None,
    ) -> None:
        """Sends auth setup to the active runtime client.

        Typical use: Use this function when runtime code needs send auth setup as part of a Sonex command, playback, auth, llm, or ui path.

        Example: await send_auth_setup(provider=..., step=..., title=..., message=..., prompt=..., mask=..., active=..., methods=..., providers=..., models=...) -> returns the value used by the surrounding Sonex flow.
        """
        await self._send(
            {
                "type": "auth_setup",
                "provider": provider,
                "step": step,
                "title": title,
                "message": message,
                "prompt": prompt,
                "placeholder": placeholder,
                "help_text": help_text,
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
        """Sends help panel to the active runtime client.

        Typical use: Use this function when runtime code needs send help panel as part of a Sonex command, playback, auth, llm, or ui path.

        Example: await send_help_panel(commands=..., title=..., hint=...) -> returns the value used by the surrounding Sonex flow.
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
        """Coordinates close for the current Sonex flow.

        Typical use: Use this function when runtime code needs close as part of a Sonex command, playback, auth, llm, or ui path.

        Example: await close() -> returns the value used by the surrounding Sonex flow.
        """
        if self.closed:
            return
        self.closed = True
        with suppress(RuntimeError, WebSocketDisconnect):
            await self.ws.close()

def _timestamp_ms() -> int:
    """Prepares timestamp ms for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs timestamp ms without duplicating the local rules.

    Example: _timestamp_ms() -> returns the value used by the surrounding Sonex flow.
    """
    return int(time.time() * 1000)

def _new_event_id(prefix: str) -> str:
    """Prepares new event id for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs new event id without duplicating the local rules.

    Example: _new_event_id(prefix=...) -> returns the value used by the surrounding Sonex flow.
    """
    return f"{prefix}_{uuid.uuid4().hex[:12]}"

async def _send_cover_pattern(ui: WebSocketUIAdapter, source_url: str) -> None:
    """Prepares send cover pattern for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs send cover pattern without duplicating the local rules.

    Example: await _send_cover_pattern(ui=..., source_url=...) -> returns the value used by the surrounding Sonex flow.
    """
    try:
        image_bytes = cover_bytes_for_source(source_url)
        if image_bytes is not None:
            payload = await asyncio.to_thread(generate_cover_pattern, source_url, image_bytes)
        elif _is_http_cover_source(source_url):
            payload = await asyncio.to_thread(fetch_cover_pattern, source_url)
        else:
            return
    except CoverPatternError as exc:
        payload = {
            "type": "cover_pattern_unavailable",
            "source_url": source_url,
            "reason": exc.reason,
        }
    except Exception:
        payload = {
            "type": "cover_pattern_unavailable",
            "source_url": source_url,
            "reason": "generation_failed",
        }
    if not ui.closed:
        await ui._send(payload)

def _is_http_cover_source(source: str) -> bool:
    """Prepares is http cover source for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs is http cover source without duplicating the local rules.

    Example: _is_http_cover_source(source=...) -> returns the value used by the surrounding Sonex flow.
    """
    lowered = source.lower()
    return lowered.startswith("http://") or lowered.startswith("https://")
