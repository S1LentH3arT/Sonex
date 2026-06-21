"""Playback request routing tools for handing ambiguous LLM intent back to the runner."""

from __future__ import annotations

from typing import Any

from src.tools.registry import Params, registry
from src.tools.result import ToolResult


def request_playback_selection(query: str) -> dict[str, Any]:
    """Ask the runtime to enter the explicit playback selection flow for a query."""
    normalized = str(query or "").strip()
    if not normalized:
        return ToolResult.fail(
            tool="request_playback_selection",
            message="Playback query cannot be empty.",
            error_code="EMPTY_PLAYBACK_QUERY",
            data={"query": normalized},
        ).to_dict()
    return {
        "status": "requires_play_selection",
        "tool": "request_playback_selection",
        "message": f"Entering playback selection for {normalized}.",
        "data": {
            "query": normalized,
            "rewritten_input": f"play {normalized}",
        },
    }


registry.register(
    name="request_playback_selection",
    type="player",
    description=(
        "Use only when the user is asking Sonex to play music but the system router did not "
        "already enter playback mode. This does not start playback directly; it asks the UI to "
        "show the playback method and song-selection flow for the query."
    ),
    parameters=Params(
        type="object",
        properties={
            "query": {
                "type": "string",
                "description": "The song, artist, album, or natural-language music query to route into playback selection.",
            },
        },
        required=["query"],
    ),
    fn=request_playback_selection,
    enable=True,
    read_only=True,
)
