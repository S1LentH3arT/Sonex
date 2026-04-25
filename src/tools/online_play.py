from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import yt_dlp
from anyio.streams import file

from src.tools.local_play import check_player
from src.tools.result import ToolResult


def _cache_stream_dir() -> Path:
    return (Path.home() / "sonex" / ".cache" / "youtube_audio").expanduser()

# 在youtube上搜索歌曲
def search_youtube_song(query: str) -> str:
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
    if not entries or not isinstance(entries[0], list):
        raise RuntimeError("No valid matches found.")
    first_entry = entries[0]

    video_id = first_entry.get("id")
    webpage_url = first_entry.get("webpage_url")

    if not webpage_url and video_id:
        webpage_url = f"https://www.youtube.com/watch?v={video_id}"

    if not webpage_url:
        raise RuntimeError("Unable to resolve a playable YouTube URL.")
    return webpage_url

# 解析youtube音频
def resolve_audio_stream_url(video_url: str) -> str:
    opts = {
        "quiet": True, # 减少控制台输出
        "no_warnings": True, # 不打印warning日志信息
        "noplaylist": True, # 搜索结果关联playlist取单条视频
        "format": "bestaudio/best", # 优先最佳音频流
        "skip_download": True, # 只解析不下载
    }

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(video_url, download=False)

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

def play_youtube_song(query: str, stream_url: str, player: str = "vlc") -> dict[str, Any]:
    # 检查vlc是否可用
    if not check_player(player):
        return ToolResult.error(
            tool="play_youtube_song",
            message=f"Player '{player}' is not ready.",
            error_code="PLAYER_MISSED",
            data={"query": query, "player": player, "method": "play_youtube_song"},
        )

    cmd = [player, "--play-and-exit", stream_url]

    try:
        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        return ToolResult.failure(
            tool="play_youtube_song",
            message=f"Failed to launch player '{player}': {exc}",
            error_code=exc.errno,
            data={"query": query, "player": player, "method": "online_play"},
        ).to_dict()

    return ToolResult.success(
        tool="play_youtube_song",
        message=f"Playing '{query}' online started.",
        data={"query": query, "file": file, "player": player, "method": "online_play"},
    ).to_dict()