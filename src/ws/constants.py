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
    {"value": "openai::gpt-5.5", "label": "gpt-5.5", "provider": "OpenAI"},
    {"value": "anthropic::claude-fable-5", "label": "claude-fable-5", "provider": "Anthropic"},
    {"value": "gemini::gemini-3.5-flash", "label": "gemini-3.5-flash", "provider": "Gemini"},
    {"value": "deepseek::deepseek-v4-pro", "label": "deepseek-v4-pro", "provider": "Deepseek"},
    {"value": "ollama::Gemma4-31b:cloud", "label": "Gemma4-31b:cloud", "provider": "Ollama"},
]

LLM_MODEL_CHOICE_VALUES = {choice["value"].lower(): choice for choice in LLM_MODEL_CHOICES}
