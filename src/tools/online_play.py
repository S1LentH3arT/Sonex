from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import yt_dlp

from src.tools.local_play import check_player
from src.tools.player_permission import (
    build_player_confirm_result,
    is_player_allowed,
    launch_player_command,
)
from src.tools.registry import registry, Params
from src.tools.result import ToolResult

# 默认缓存路径
def _cache_stream_dir() -> Path:
    return (Path.home() / "sonex" / ".cache" / "youtube_audio").expanduser()

# 在youtube上搜索歌曲并解析音频流
def search_and_resolve_song(query: str) -> str:
    options = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
    }

    with yt_dlp.YoutubeDL(options) as ydl:
        payload = ydl.extract_info(f"ytsearch1:{query}", download=False)

    if not isinstance(payload, dict):
        raise RuntimeError("Invalid response returned.")

    entries = payload.get("entries") or []
    if not entries or not isinstance(entries[0], dict):
        raise RuntimeError("No valid matches found.")
    first_entry = entries[0]

    video_id = first_entry.get("id")
    webpage_url = first_entry.get("webpage_url")

    if not webpage_url and video_id:
        webpage_url = f"https://www.youtube.com/watch?v={video_id}"

    if not webpage_url:
        raise RuntimeError("Unable to resolve a playable YouTube URL.")
    stream_opts = {
        "quiet": True,  # 减少控制台输出
        "no_warnings": True,  # 不打印warning日志信息
        "noplaylist": True,  # 搜索结果关联playlist取单条视频
        "format": "bestaudio/best",  # 优先最佳音频流
        "skip_download": True,  # 只解析不下载
    }

    with yt_dlp.YoutubeDL(stream_opts) as ydl:
        info = ydl.extract_info(webpage_url, download=False)

    stream_url = info.get("url")
    if not stream_url:
        formats = info.get("formats") or []
        # 筛选音频格式
        audio_formats = [
            f for f in formats
            if isinstance(f, dict)
               and f.get("url")
               and f.get("acodec") not in (None, "none")
               and f.get("vcodec") in (None, "none")
        ]
        if not audio_formats:
            raise RuntimeError("No playable audio-only format found.")

        # 按音频码率优先和总码率排序
        audio_formats.sort(key=lambda x: (x.get("abr") or 0, x.get("tbr") or 0), reverse=True)
        stream_url = audio_formats[0]["url"]
    return stream_url

def play_youtube_song(query: str, player: str = "vlc") -> dict[str, Any]:
    stream_url = search_and_resolve_song(query=query)

    # 检查vlc是否可用
    if not check_player(player):
        return ToolResult.error(
            tool="play_youtube_song",
            message=f"Player '{player}' is not ready.",
            error_code="PLAYER_MISSED",
            data={"query": query, "player": player, "method": "play_youtube_song"},
        )

    cmd = [player, "--play-and-exit", stream_url]
    data = {"query": query, "player": player, "method": "online_play"}
    success_message = f"Playing '{query}' online started."

    if not is_player_allowed(player):
        return build_player_confirm_result(
            tool="play_youtube_song",
            player=player,
            cmd=cmd,
            success_message=success_message,
            data=data,
        )

    return launch_player_command(
        tool="play_youtube_song",
        player=player,
        cmd=cmd,
        success_message=success_message,
        data=data,
    )

registry.register(
    name="play_youtube_song",
    type="player",
    description="Play a resolved audio extract from youtube via VLC music player.",
    parameters=Params(
        type="object",
        properties={
            "query": {"type": "string", "description": "The song name or related key words."},
        },
        required=["query"],
    ),
    fn=play_youtube_song,
    enable=True,
    read_only=False,
    required_confirm=False,
)
