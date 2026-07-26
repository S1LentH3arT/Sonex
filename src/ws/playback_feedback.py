"""Formatting for playback-choice feedback shown in the Sonex chat."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

MISSING_FEEDBACK_VALUE = "—"

_METADATA_PROVIDER_LABELS = {
    "itunes": "iTunes",
    "deezer": "Deezer",
    "musicbrainz": "MusicBrainz",
    "spotify": "Spotify",
}

_PLAYER_FEEDBACK_LABELS = {
    "auto": "auto",
    "mpv": "mpv",
    "cvlc": "VLC",
    "vlc": "VLC",
}


def _text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split())


def _display(value: Any) -> str:
    return _text(value) or MISSING_FEEDBACK_VALUE


def metadata_provider_label(provider: Any) -> str:
    """Return the activity label for a metadata provider."""
    raw = _text(provider)
    if not raw:
        return "Metadata"
    return _METADATA_PROVIDER_LABELS.get(raw.lower(), raw.title())


def _candidate_artist(candidate: Mapping[str, Any]) -> str:
    artist = _text(candidate.get("artist"))
    if artist:
        return artist
    artists = candidate.get("artists")
    if isinstance(artists, Sequence) and not isinstance(artists, (str, bytes)):
        for value in artists:
            artist = _text(value)
            if artist:
                return artist
    return ""


def format_song_candidate_feedback(candidate: Mapping[str, Any]) -> str:
    """Format the selected song candidate for Agent feedback."""
    track = candidate.get("name") or candidate.get("title")
    provider = candidate.get("provider") or candidate.get("metadata_source")
    source = (
        metadata_provider_label(provider)
        if _text(provider)
        else MISSING_FEEDBACK_VALUE
    )
    return "\n".join(
        (
            f"track: {_display(track)}",
            f"artist: {_display(_candidate_artist(candidate))}",
            f"album: {_display(candidate.get('album'))}",
            f"source: {source}",
        )
    )


def player_feedback_label(player: Any) -> str:
    """Return the display label for a player backend."""
    raw = _text(player)
    if not raw:
        return MISSING_FEEDBACK_VALUE
    return _PLAYER_FEEDBACK_LABELS.get(raw.lower(), raw)


def format_player_feedback(player: Any) -> str:
    """Format a selected player backend for chat feedback."""
    return f"player: {player_feedback_label(player)}"


def format_playing_feedback(
    result: Mapping[str, Any],
    selected_candidate: Mapping[str, Any],
) -> str:
    """Format successful playback feedback using the best track name."""
    data = result.get("data")
    result_data = data if isinstance(data, Mapping) else {}
    track = (
        result_data.get("name")
        or result_data.get("title")
        or selected_candidate.get("name")
        or selected_candidate.get("title")
    )
    return f"on playing: {_display(track)}"
