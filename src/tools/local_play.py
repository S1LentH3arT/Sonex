"""Local play support for tool implementations used by the planner and playback flows.
"""

import shutil
from pathlib import Path

from src.tools.player_permission import (
    confirm_or_start_playback,
)
from src.tools.cover_sources import extract_embedded_cover
from src.tools.playback_controller import resolve_local_playback_backend, start_local_playback
from src.tools.registry import registry, Params
from src.tools.result import ToolResult
from src.workspace import WorkspaceBoundaryError, user_music_dir


# 搜索本地音乐文件
def search_local_file(query: str) -> str:
    query = query.strip()
    if not query:
        return "No local files found related to ''."
    try:
        music_dir = user_music_dir()
    except WorkspaceBoundaryError:
        return "Path outside user workspace."
    if not music_dir.exists():
        return f"No local files found related to '{query}'."

    needle = query.lower()
    for candidate in music_dir.rglob("*"):
        if candidate.is_file() and needle in candidate.name.lower():
            return str(candidate)
    return f"No local files found related to '{query}'."

# 检查本地播放器
def check_player(player: str) -> bool:
    return shutil.which(player) is not None

# 使用本地播放器播放音乐(默认策略为auto)
def play_local_song(query: str, player: str = "auto") -> dict:
    file = search_local_file(query)
    if file.startswith("Path outside user workspace"):
        return ToolResult.fail(
            tool="play_local_song",
            message="Local music search is outside the Sonex user workspace.",
            error_code="PATH_OUTSIDE_USER_WORKSPACE",
            data={"query": query},
        ).to_dict()
    if file.startswith("No local files found"):
        return ToolResult.fail(
            tool="play_local_song",
            message=f"No local audio files found for '{query}'.",
            error_code="NOT_FOUND",
            data={"query": query},
        ).to_dict()

    player = resolve_local_playback_backend(player)

    if not check_player(player):
        return ToolResult.fail(
            tool="play_local_song",
            message=f"{player} is not ready.",
            error_code="PLAYER_MISSED",
            data={"query": query},
        ).to_dict()

    data = {
        "query": query,
        "file": file,
        "name": Path(file).stem,
        "artist": "-",
        "album": "-",
        "provider": "local",
        "source": "local",
        "player": player,
        "method": "local_play",
    }
    try:
        cover = extract_embedded_cover(file)
    except RuntimeError:
        cover = None
    if cover:
        data["album_cover_url"] = cover["cover_source"]
        data["cover_source"] = cover["cover_source"]
        data["cover_source_type"] = cover["source_type"]
    success_message = f"Playing '{file}' started."

    return confirm_or_start_playback(
        tool="play_local_song",
        source_url=file,
        source="local",
        metadata=data,
        player=player,
        success_message=success_message,
        start=start_local_playback,
    )

registry.register(
    name="play_local_song",
    kind="system",
    domain="playback",
    description="Play local audio files via local system music player.",
    parameters=Params(
        type="object",
        properties={
            "query": {"type": "string", "description": "The song name or related key words."},
            "player": {"type": "string", "description": "The system player to play the audio"},
        },
        required=["query", "player"],
    ),
    fn=play_local_song,
    enable=True,
    read_only=False,
    required_confirm=False,
)
