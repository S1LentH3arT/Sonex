from src.ws.playback_feedback import (
    format_playing_feedback,
    format_player_feedback,
    format_song_candidate_feedback,
    metadata_provider_label,
)


def test_song_candidate_feedback_formats_four_lines() -> None:
    assert format_song_candidate_feedback(
        {
            "name": "Sorry",
            "artist": "方大同",
            "album": "未来",
            "provider": "itunes",
        }
    ) == (
        "track: Sorry\n"
        "artist: 方大同\n"
        "album: 未来\n"
        "source: iTunes"
    )


def test_song_candidate_feedback_uses_fallbacks_and_em_dash() -> None:
    assert format_song_candidate_feedback(
        {
            "title": "Fallback title",
            "artists": ["", "Fallback artist"],
            "metadata_source": "musicbrainz",
        }
    ) == (
        "track: Fallback title\n"
        "artist: Fallback artist\n"
        "album: —\n"
        "source: MusicBrainz"
    )


def test_song_candidate_feedback_uses_em_dash_for_missing_source() -> None:
    assert format_song_candidate_feedback({}).splitlines()[-1] == "source: —"


def test_feedback_collapses_embedded_line_separators_into_inline_spaces() -> None:
    candidate_feedback = format_song_candidate_feedback(
        {
            "name": "  Sorry\n  Live  ",
            "artist": "方大同\r\n  王菀之",
            "album": "未来\v精选\f版",
            "provider": "music\u2028brainz",
        }
    )

    assert candidate_feedback == (
        "track: Sorry Live\n"
        "artist: 方大同 王菀之\n"
        "album: 未来 精选 版\n"
        "source: Music Brainz"
    )
    assert len(candidate_feedback.splitlines()) == 4

    playing_feedback = format_playing_feedback(
        {"data": {"name": "  Sorry\r\nLive\u0085现场\u2029版  "}},
        {},
    )
    assert playing_feedback == "on playing: Sorry Live 现场 版"
    assert len(playing_feedback.splitlines()) == 1


def test_feedback_helpers_normalize_provider_player_and_playing_name() -> None:
    assert metadata_provider_label("deezer") == "Deezer"
    assert metadata_provider_label("") == "Metadata"
    assert format_player_feedback("mpv") == "player: mpv"
    assert format_player_feedback("cvlc") == "player: VLC"
    assert format_player_feedback("auto") == "player: auto"
    assert format_player_feedback(None) == "player: —"
    assert format_playing_feedback(
        {"data": {"name": "Result name"}},
        {"name": "Candidate name"},
    ) == "on playing: Result name"
    assert format_playing_feedback({}, {"title": "Candidate title"}) == (
        "on playing: Candidate title"
    )
    assert format_playing_feedback({}, {}) == "on playing: —"
