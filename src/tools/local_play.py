import glob
import subprocess
from pathlib import Path

from src.tools.registry import registry, Params
from src.tools.result import ToolResult


# 搜索本地音乐文件
def search_local_file(query: str) -> str:
    music_dir = Path.home() / "Music"
    pattern = f"**/*{query}*.*"
    matches = glob.glob(str(music_dir / pattern), recursive=True)

    if not matches:
        return f"No local files found related to '{query}'."

    first = matches[0]
    return f"{first}"

# 检查本地播放器
def check_player(player: str) -> bool:
    cmd = f"command -v {player}"
    result = subprocess.run(["bash", "-lc", cmd], check=False)
    return result.returncode == 0

# 使用本地播放器播放音乐(默认播放器为vlc)
def play_local_song(query: str, player: str = "vlc") -> dict:
    file = search_local_file(query)
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

    cmd = list[str]
    if player == "vlc":
        cmd = ["vlc", "--play-and-exit", file]
    elif player == "mpv":
        cmd = ["mpv", "--no-video", file]
    subprocess.Popen(cmd)

    return ToolResult.success(
        tool="play_local_song",
        message=f"Playing '{file}' started.",
        data={"query": query, "file": file, "player": player},
    ).to_dict()

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
    enable=True
)