from typing import runtime_checkable, Protocol

from src.ui import UiStatus

"""Protocol that support interactive UI with backend agent endpoint.
Implemented in SonexApp, and called back in SonexRunner.
"""
@runtime_checkable
class UIAdapter(Protocol):
    async def append_user_message(self, text: str) -> None:
        ...

    async def append_agent_message(self, text: str) -> None:
        ...

    async def append_tool_message(self, text: str) -> None:
        ...

    def set_status(self, status: UiStatus) -> None:
        ...

    def set_input_enabled(self, enabled: bool) -> None:
        ...

    def render_cover_art(self, url: str) -> None:
        ...

    def update_player(self, state: dict) -> None:
        ...

    async def ask_confirm(self, attached: dict) -> bool:
        ...