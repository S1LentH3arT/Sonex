"""Local play support for tool implementations used by the planner and playback flows.

Implements the local_play module responsibilities used by Sonex runtime flows.
Key public entry points include search_local_file, check_player, play_local_song.
"""

import shutil
from pathlib import Path

from src.tools.player_permission import (
    build_player_confirm_result,
    is_player_allowed,
)
from src.tools.cover_sources import extract_embedded_cover
from src.tools.playback_controller import resolve_local_playback_backend, start_local_playback
from src.tools.registry import registry, Params
from src.tools.result import ToolResult
from src.workspace import WorkspaceBoundaryError, user_music_dir


# 搜索本地音乐文件
def search_local_file(query: str) -> str:
    """Coordinates search local file for the current Sonex flow.

    Typical use: Use this function when runtime code needs search local file as part of a Sonex command, playback, auth, llm, or ui path.

    Example: search_local_file(query=...) -> returns the value used by the surrounding Sonex flow.
    """
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
    """Coordinates check player for the current Sonex flow.

    Typical use: Use this function when runtime code needs check player as part of a Sonex command, playback, auth, llm, or ui path.

    Example: check_player(player=...) -> returns the value used by the surrounding Sonex flow.
    """
    return shutil.which(player) is not None

def _player_command(player: str, file: str) -> list[str] | None:
    """Prepares player command for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs player command without duplicating the local rules.

    Example: _player_command(player=..., file=...) -> returns the value used by the surrounding Sonex flow.
    """
    if player == "mpv":
        return ["mpv", "--no-video", file]
    return None

# 使用本地播放器播放音乐(默认策略为auto)
def play_local_song(query: str, player: str = "auto") -> dict:
    """Coordinates play local song for the current Sonex flow.

    Typical use: Use this function when runtime code needs play local song as part of a Sonex command, playback, auth, llm, or ui path.

    Example: play_local_song(query=..., player=...) -> returns the value used by the surrounding Sonex flow.
    """
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

    cmd = _player_command(player, file)
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

    if not is_player_allowed(player):
        return build_player_confirm_result(
            tool="play_local_song",
            player=player,
            cmd=cmd,
            success_message=success_message,
            data={
                **data,
                "playback_source_url": file,
                "playback_source": "local",
                "playback_metadata": data,
            },
        )

    return start_local_playback(
        tool="play_local_song",
        source_url=file,
        source="local",
        metadata=data,
        player=player,
        success_message=success_message,
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
