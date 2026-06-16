"""Shared constants for websocket runtime routing."""

from __future__ import annotations


SEARCH_RESULT_TOOLS = {"spotify_search", "search_track", "spotify_recommend", "apple_music_search", "apple_music_recommend"}

RECOMMENDATION_TOOLS = {"spotify_recommend", "apple_music_recommend"}

PLAYBACK_AGENT_TOOLS = {"spotify_play", "apple_music_play", "play_youtube_song", "play_local_song"}

PLAYBACK_ROUTER_TOOLS = {"request_playback_selection"}

RECOMMEND_AGENT_TOOLS = (
    "spotify_recommend",
    "apple_music_recommend",
    "spotify_recent_tracks",
    "apple_music_recent_tracks",
    "spotify_search",
    "apple_music_search",
    "search_track",
    "search_memory",
    "search_context",
)

LOCAL_PLAYBACK_CONTROL_TOOLS = {
    "pause": "local_playback_pause",
    "resume": "local_playback_resume",
    "stop": "local_playback_stop",
    "progress": "local_playback_status",
}

LOCAL_PLAYBACK_BACKENDS = {"auto", "mpv", "cvlc"}

PLAYBACK_METHOD_CHOICES = [
    {
        "value": "spotify_play",
        "label": "🎧 Spotify Play",
        "description": "Spotify Premium subscription and desktop/mobile Spotify apps required.",
    },
    {
        "value": "apple_music_play",
        "label": "🍎 Apple Music Play",
        "description": "Apple Music Subscription required. Play through Sonex internal player.",
    },
    {
        "value": "online_play",
        "label": "🌐 Sonex online Play",
        "description": "No subscription required. Play through Sonex internal player.",
    },
    {"value": "cancel", "label": "Cancel"},
]

LOCAL_PLAYBACK_CHOICES = [
    {"value": "play_local", "label": "播放本地"},
    {"value": "skip_local", "label": "不播放本地，选择其他方式"},
    {"value": "cancel", "label": "取消"},
]

SPOTIFY_SETUP_TRIGGERS = {
    "spotify setup",
    "setup spotify",
    "connect spotify",
    "spotify connect",
    "接入 spotify",
    "连接 spotify",
    "配置 spotify",
}

APPLE_MUSIC_SETUP_TRIGGERS = {
    "apple music setup",
    "setup apple music",
    "connect apple music",
    "apple music connect",
    "接入 apple music",
    "连接 apple music",
    "配置 apple music",
    "接入苹果音乐",
    "连接苹果音乐",
    "配置苹果音乐",
}

LLM_AUTH_PROVIDER_CHOICES = [
    {"value": "openai", "label": "OpenAI"},
    {"value": "anthropic", "label": "Anthropic"},
    {"value": "gemini", "label": "Gemini"},
    {"value": "deepseek", "label": "Deepseek"},
    {"value": "ollama", "label": "Ollama"},
]

LLM_AUTH_PROVIDER_VALUES = {choice["value"] for choice in LLM_AUTH_PROVIDER_CHOICES}

LLM_MODEL_CHOICES = [
    {"value": "openai::gpt-5.2", "label": "GPT-5.2", "provider": "OpenAI"},
    {"value": "anthropic::claude-opus-4-1-20250805", "label": "Claude Opus 4.1", "provider": "Anthropic"},
    {"value": "gemini::gemini-3-flash-preview", "label": "Gemini 3 Flash Preview", "provider": "Gemini"},
    {"value": "deepseek::deepseek-v4-pro", "label": "DeepSeek V4 Pro", "provider": "DeepSeek"},
    {"value": "ollama::Gemma4-31b:cloud", "label": "Gemma4-31b:cloud", "provider": "Ollama"},
]

LLM_MODEL_CHOICE_VALUES = {choice["value"].lower(): choice for choice in LLM_MODEL_CHOICES}
