"""Browser operations on the shared Sonex Agent and playback runtime."""

from __future__ import annotations

import asyncio
import getpass
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from src.log import sonex_home
from src.memory.memory import bind_memory_scope
from src.tools.playback_controller import controller
from src.tools.cover_sources import cover_bytes_for_source
from src.tools.cover_patterns import fetch_cover_image, prepare_cover_png
from src.llm.transport import sanitize_error_message
from src.tools.up_next import commit_up_next_state, up_next_snapshot
from src.web.library import MusicLibrary
from src.web.runtime.sessions import SessionStore
from src.ws.runner import WebSocketRunner, _llm_auth_state
from src.ws.session_orchestration import session_context_for
from src.ws.ui import WebSocketUIAdapter


class WebUI(WebSocketUIAdapter):
    def __init__(self, connection: Any, store: SessionStore) -> None:
        self.store = store
        recent = store.list()
        session_id = recent[0]["id"] if recent else store.create()
        super().__init__(connection, session_id=session_id)
        self.transcript = store.read(session_id)
        self.pending: dict[str, dict[str, Any]] = {}
        self.latest: dict[str, dict[str, Any]] = {}
        self.persistence_lock = asyncio.Lock()
        self.on_track_end: Callable[[], Awaitable[None]] | None = None
        self.ended_playback_id: str | None = None
        self.auto_queue = True
        self.queue_advancing = False

    async def _send(self, payload: dict[str, Any]) -> None:
        kind = payload.get("type")
        active_turn = session_context_for(self).active_agent_turn
        if active_turn and (
            kind == "activity"
            or (kind == "chat" and payload.get("role") == "agent" and payload.get("stream"))
        ):
            payload["turn_id"] = active_turn.turn_id
        if kind == "cover_image" and payload.get("source_url") != self.latest.get("cover", {}).get("url"):
            return
        if kind == "cover":
            self.latest.pop("cover_image", None)
        if kind == "chat":
            async with self.persistence_lock:
                await asyncio.to_thread(self.store.save, self.session_id, list(self.transcript))
        if kind == "confirm":
            self.pending[payload["id"]] = payload
        elif kind == "confirm_dismiss":
            self.pending.pop(payload["id"], None)
        if kind in {"player", "cover", "cover_image", "auth_state", "auth_setup", "spotify_setup", "provider_mode", "agent_working_state", "activity"}:
            self.latest[str(kind)] = payload
        await super()._send({**payload, "session_id": self.session_id})
        if kind == "queue":
            await self.send_queue()
        if kind == "player":
            state = payload.get("state", {})
            if state.get("is_playing"):
                self.auto_queue = True
            playback_id = state.get("session_id")
            if (state.get("ended") and state.get("progress_source") == "local_player"
                    and playback_id and playback_id != self.ended_playback_id and self.on_track_end):
                self.ended_playback_id = playback_id
                session_context_for(self).tasks.create_task(self.on_track_end(), name="web-next-track")

    async def send_queue(self) -> None:
        await super()._send({"type": "web_queue", **up_next_snapshot()})

    async def send_cover(self, url: str) -> None:
        await self._send({"type": "cover", "url": url})
        async def load() -> None:
            try:
                data = cover_bytes_for_source(url)
                if data is None and url.startswith(("https://", "http://")):
                    data = await asyncio.to_thread(fetch_cover_image, url)
                if data:
                    png, width, height = await asyncio.to_thread(prepare_cover_png, data)
                    await self.send_cover_image(url, png, width=width, height=height)
            except (OSError, ValueError):
                pass
        # The browser needs an image, not the terminal's bead-pattern conversion.
        session_context_for(self).tasks.create_task(load(), name="web-cover")

    async def send_session_state(self) -> None:
        await super().send_session_state()
        await self.snapshot()

    async def snapshot(self) -> None:
        await self._send({"type": "web_snapshot", "messages": self.transcript,
                          "sessions": self.store.list(), "user": getpass.getuser(),
                          "home": str(sonex_home()), "protocol_version": 1})
        await self.send_queue()
        for payload in list(self.latest.values()):
            await super()._send({**payload, "session_id": self.session_id})
        for payload in list(self.pending.values()):
            await super()._send({**payload, "session_id": self.session_id})


class WebRunner(WebSocketRunner):
    def __init__(self, store: SessionStore | None = None) -> None:
        super().__init__()
        self.store = store or SessionStore()
        self.library = MusicLibrary()

    def _create_ui(self, ws: Any) -> WebUI:
        ui = WebUI(ws, self.store)
        ui.on_track_end = lambda: self._advance_queue(ui)
        return ui

    async def _advance_queue(self, ui: WebUI) -> None:
        while not ui.closed and ui.auto_queue and not controller.current_session_id and not self._spotify_mode_enabled(ui):
            try:
                self._require_idle(ui)
            except ValueError:
                await asyncio.sleep(0.5)
                continue
            tracks = up_next_snapshot()["items"]
            if tracks:
                ui.queue_advancing = True
                try:
                    await self._play_up_next_from_selection(ui, tracks[0])
                finally:
                    ui.queue_advancing = False
            return

    async def _handle_playback_control(self, ui: WebUI, command_name: str) -> None:
        if command_name == "stop":
            ui.auto_queue = False
        elif command_name == "resume":
            ui.auto_queue = True
        await super()._handle_playback_control(ui, command_name)

    def _additional_routes(self, ui: WebUI) -> dict[str, Any]:
        return {"web": lambda data: self.handle_web(ui, data)}

    def _require_idle(self, ui: WebUI) -> None:
        if ui.queue_advancing:
            raise ValueError("A track is starting. Please wait.")
        context = session_context_for(ui)
        if (context.running_task and not context.running_task.done()) or context.agent_interaction_active:
            raise ValueError("Wait for or stop the active Agent task first.")
        if ui.pending or any(ui.latest.get(key, {}).get("active") for key in ("auth_setup", "spotify_setup")):
            raise ValueError("Finish or cancel the pending confirmation or setup first.")

    async def _switch(self, ui: WebUI, session_id: str) -> None:
        if session_id == ui.session_id:
            return
        self._require_idle(ui)
        messages = self.store.read(session_id)
        context = session_context_for(ui)
        # Playback and provider state belong to the application, not the viewed chat.
        retained = {key: value for key, value in context.values.items() if key in {
            "_spotify_mode", "_spotify_session_requests", "_spotify_sync_event",
            "_local_playback_sync_event", "_last_player_state", "_last_playback_behavior_key",
            "_active_playback_provider", "_preferred_playback_provider", "_spotify_library_synced",
        }}
        context.values.clear()
        context.values.update(retained)
        context.confirm_registry.clear()
        context.agent_input_queue = None
        ui.session_id = session_id
        ui.transcript = messages
        ui.input_tokens = ui.output_tokens = 0
        ui.latest.pop("agent_working_state", None)
        bind_memory_scope(session_id)
        await ui.send_session_state()

    async def _handle_confirm_result(self, ui: WebUI, confirm_id: str, decision: Any) -> bool:
        ui.pending.pop(confirm_id, None)
        return await super()._handle_confirm_result(ui, confirm_id, decision)

    async def _handle_bye(self, ui: WebUI, *, messages: list[dict[str, Any]], reason: str) -> None:
        self.store.save(ui.session_id, ui.transcript)
        await ui.send_auth_state(_llm_auth_state())
        await ui.snapshot()

    async def handle_web(self, ui: WebUI, data: dict[str, Any]) -> None:
        try:
            action = data.get("action")
            if not isinstance(action, str) or ("command" in data and not isinstance(data["command"], str)):
                raise ValueError("Web action and command must be strings.")
            if action == "snapshot":
                await ui.snapshot()
            elif action == "library":
                await self._send_library(ui)
            elif action == "library_set_path":
                await asyncio.to_thread(self.library.set_root, str(data.get("path") or ""))
                await self._send_library(ui)
            elif action == "library_play":
                path = await asyncio.to_thread(self.library.track_path, str(data.get("path") or ""))
                await self._player(ui, {"command": "open_file", "path": str(path)})
            elif action == "sessions":
                await ui._send({"type": "web_sessions", "sessions": self.store.list()})
            elif action == "read_session":
                session_id = str(data.get("session_id") or "")
                await ui._send({"type": "web_history", "viewed_session_id": session_id,
                                "messages": self.store.read(session_id)})
            elif action == "new_session":
                self._require_idle(ui)
                await self._switch(ui, self.store.create())
            elif action == "chat":
                self._require_idle(ui)
                if not isinstance(data.get("text"), str):
                    raise ValueError("Message must be text.")
                text = data["text"].strip()
                if not text or len(text) > 32000:
                    raise ValueError("Message length must be between 1 and 32,000 characters.")
                await self._switch(ui, str(data.get("session_id") or ui.session_id))
                await self._handle_user_input(ui, text)
            elif action == "command":
                self._require_idle(ui)
                command = data.get("command")
                if command == "/library":
                    await self._send_library(ui)
                    return
                if command not in {"/playlist", "/memory", "/extension", "/login", "/model", "/connect", "/proxy", "/help", "/spotify"}:
                    raise ValueError("Unsupported web command.")
                await self._handle_user_input(ui, command)
            elif action == "player":
                await self._player(ui, data)
            elif action == "queue":
                await self._queue(ui, data)
            else:
                raise ValueError("Unsupported web action.")
        except (ValueError, OSError, RuntimeError) as exc:
            await ui.send_error(sanitize_error_message(exc))
            if data.get("action") == "queue":
                await ui.send_queue()

    async def _send_library(self, ui: WebUI) -> None:
        payload = await asyncio.to_thread(self.library.tracks)
        payload["title"] = "Library"
        await ui._send(payload)

    async def _player(self, ui: WebUI, data: dict[str, Any]) -> None:
        command = data.get("command")
        spotify = self._spotify_mode_enabled(ui)
        if command == "open_file":
            self._require_idle(ui)
            path = Path(str(data.get("path") or "")).expanduser().resolve()
            if not path.is_file() or path.suffix.lower() not in {".mp3", ".flac", ".wav", ".m4a", ".aac", ".ogg", ".opus", ".aiff"}:
                raise ValueError("Choose a readable local audio file.")
            if spotify:
                await self._exit_spotify_mode(ui)
            ui.auto_queue = True
            await self._play_track_panel_track(ui, {"provider": "local", "name": path.stem, "file_path": str(path), "artist": "Local music"})
        elif command in {"pause", "resume", "stop", "previous"}:
            await self._handle_playback_control(ui, command)
        elif command == "next":
            ui.auto_queue = True
            if spotify:
                await self._handle_playback_control(ui, "next")
            else:
                self._require_idle(ui)
                tracks = up_next_snapshot()["items"]
                if not tracks:
                    raise ValueError("The playback queue is empty.")
                await self._play_up_next_from_selection(ui, tracks[0])
        elif command in {"seek", "volume"}:
            if spotify:
                raise ValueError("Adjust playback position and volume in Spotify.")
            value = data.get("value")
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError("Player value must be an integer.")
            if command == "volume" and not 0 <= value <= 100:
                raise ValueError("Volume must be between 0 and 100.")
            state = await asyncio.to_thread(controller.seek if command == "seek" else controller.set_volume, value)
            await ui._send({"type": "player", "state": state.to_dict()})
        else:
            raise ValueError("Unsupported playback command.")

    async def _queue(self, ui: WebUI, data: dict[str, Any]) -> None:
        state = up_next_snapshot()
        revision = data.get("revision")
        if type(revision) is not int or revision != state["revision"]:
            raise ValueError("The queue changed. Refresh and try again.")
        entry_id = data.get("entry_id")
        index = next((i for i, item in enumerate(state["items"]) if item.get("entry_id") == entry_id), None)
        if index is None:
            raise ValueError("That queue entry no longer exists.")
        command = data.get("command")
        if command == "play":
            self._require_idle(ui)
            # Shared queue playback settles the head by its enqueue-instance ID.
            if index:
                state["items"].insert(0, state["items"].pop(index))
                commit_up_next_state(state, expected_revision=revision)
                await ui.send_queue()
            ui.auto_queue = True
            await self._play_up_next_from_selection(ui, state["items"][0])
            return
        if command == "remove":
            state["items"].pop(index)
        elif command == "move":
            destination = data.get("destination")
            if type(destination) is not int or not 0 <= destination < len(state["items"]):
                raise ValueError("Invalid queue position.")
            state["items"].insert(destination, state["items"].pop(index))
        else:
            raise ValueError("Unsupported queue command.")
        commit_up_next_state(state, expected_revision=revision)
        await ui.send_queue()
