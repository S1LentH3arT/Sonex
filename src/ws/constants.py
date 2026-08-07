"""Shared constants for websocket runtime routing."""

from __future__ import annotations


SEARCH_RESULT_TOOLS = {"spotify_search", "search_track", "spotify_recommend", "Recommend"}

RECOMMENDATION_TOOLS = {"spotify_recommend", "Recommend"}

PLAYBACK_AGENT_TOOLS = {"spotify_play", "play_youtube_song", "play_local_song"}

PLAYBACK_ROUTER_TOOLS = {"request_playback_selection"}

RECOMMEND_AGENT_TOOLS = (
    "spotify_recommend",
    "spotify_recent_tracks",
    "spotify_search",
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

SPOTIFY_PLAYBACK_CONTROL_TOOLS = {
    "pause": "spotify_pause",
    "resume": "spotify_resume",
}

LOCAL_PLAYBACK_BACKENDS = {"auto", "mpv", "cvlc"}

LOCAL_PLAYBACK_CHOICES = [
    {"value": "play_local", "label": "Play local file"},
    {"value": "skip_local", "label": "Choose another source"},
    {"value": "cancel", "label": "Cancel"},
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

LLM_AUTH_PROVIDER_CHOICES = [
    {"value": "openai", "label": "OpenAI"},
    {"value": "gemini", "label": "Google Gemini"},
    {"value": "anthropic", "label": "Anthropic"},
    {"value": "deepseek", "label": "DeepSeek"},
    {"value": "openrouter", "label": "OpenRouter"},
    {"value": "zai", "label": "Z.AI"},
    {"value": "kimi_global", "label": "Kimi Global"},
    {"value": "kimi_cn", "label": "Kimi CN"},
    {"value": "minimax_global", "label": "MiniMax Global"},
    {"value": "minimax_cn", "label": "MiniMax CN"},
    {"value": "xai", "label": "xAI"},
    {"value": "custom", "label": "Custom"},
]

LLM_AUTH_PROVIDER_VALUES = {choice["value"] for choice in LLM_AUTH_PROVIDER_CHOICES}

LLM_MODEL_CHOICES = [
    {"value": "openai::gpt-5.5", "label": "GPT-5.5", "provider": "OpenAI"},
    {"value": "anthropic::claude-fable-5", "label": "Claude Fable 5", "provider": "Anthropic"},
    {"value": "gemini::gemini-3.5-flash", "label": "Gemini 3.5 Flash", "provider": "Google Gemini"},
    {"value": "deepseek::deepseek-v4-pro", "label": "DeepSeek-V4-Pro", "provider": "DeepSeek"},
]

LLM_MODEL_CHOICE_VALUES = {choice["value"].lower(): choice for choice in LLM_MODEL_CHOICES}
