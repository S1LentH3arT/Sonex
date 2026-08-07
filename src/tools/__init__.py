from src.tools.local_play import play_local_song
from src.tools.netease import netease_account, netease_play, netease_search
from src.tools.online_play import play_youtube_song
from src.tools.playback_controller import (
    local_playback_pause,
    local_playback_player,
    local_playback_resume,
    local_playback_status,
    local_playback_stop,
    local_playback_volume,
)
from src.tools.registry import ToolRegistry, registry
from src.tools.result import ToolResult
from src.tools.playback_request import request_playback_selection
from src.tools.spotify_play import (
    search_albums,
    search_artists,
    search_tracks,
    spotify_account,
    spotify_current_playback,
    spotify_devices,
    spotify_next,
    spotify_pause,
    spotify_play,
    spotify_playlist_tracks,
    spotify_playlists,
    spotify_previous,
    spotify_queue,
    spotify_recent_tracks,
    spotify_recommend,
    spotify_resume,
    spotify_search,
    spotify_transfer_playback,
)
from src.memory.tool import search_context, search_memory
from src.tools.agent_surface import Call, Connect, Modify, Query, Read, Recommend


__all__ = [
    "ToolRegistry",
    "ToolResult",
    "registry",
    "request_playback_selection",
    "play_local_song",
    "netease_account",
    "netease_search",
    "netease_play",
    "play_youtube_song",
    "local_playback_pause",
    "local_playback_player",
    "local_playback_resume",
    "local_playback_status",
    "local_playback_stop",
    "local_playback_volume",
    "search_tracks",
    "search_artists",
    "search_albums",
    "spotify_search",
    "spotify_account",
    "spotify_current_playback",
    "spotify_recent_tracks",
    "spotify_playlists",
    "spotify_playlist_tracks",
    "spotify_queue",
    "spotify_recommend",
    "spotify_devices",
    "spotify_transfer_playback",
    "spotify_play",
    "spotify_pause",
    "spotify_resume",
    "spotify_next",
    "spotify_previous",
    "search_context",
    "search_memory",
    "Read",
    "Query",
    "Recommend",
    "Modify",
    "Connect",
    "Call",
]
