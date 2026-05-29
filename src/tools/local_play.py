import shutil

from src.tools.player_permission import (
    build_player_confirm_result,
    is_player_allowed,
    launch_player_command,
)
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

def _player_command(player: str, file: str) -> list[str] | None:
    if player == "vlc":
        return ["vlc", "--play-and-exit", file]
    if player == "mpv":
        return ["mpv", "--no-video", file]
    return [player, file]

# 使用本地播放器播放音乐(默认播放器为vlc)
def play_local_song(query: str, player: str = "vlc") -> dict:
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

    # 检查本地是否有该播放器
    if not check_player(player):
        return ToolResult.fail(
            tool="play_local_song",
            message=f"{player} is not ready.",
            error_code="PLAYER_MISSED",
            data={"query": query},
        ).to_dict()

    cmd = _player_command(player, file)
    data = {"query": query, "file": file, "player": player, "method": "local_play"}
    success_message = f"Playing '{file}' started."

    if not is_player_allowed(player):
        return build_player_confirm_result(
            tool="play_local_song",
            player=player,
            cmd=cmd,
            success_message=success_message,
            data=data,
        )

    return launch_player_command(
        tool="play_local_song",
        player=player,
        cmd=cmd,
        success_message=success_message,
        data=data,
    )

registry.register(
    name="play_local_song",
    type="player",
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
    required_confirm=False,
)
