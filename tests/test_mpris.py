from __future__ import annotations

from src.music.mpris import _requested_uri_observed


def test_requested_uri_requires_matching_identity() -> None:
    requested = "https://example.com/requested.mp3"

    assert _requested_uri_observed(requested, requested)
    assert not _requested_uri_observed(requested, requested, "Stopped")
    assert not _requested_uri_observed("", requested)
    assert not _requested_uri_observed("https://example.com/old.mp3", requested)


def test_requested_file_uri_accepts_equivalent_encoding() -> None:
    assert _requested_uri_observed(
        "file:///tmp/Sonex%20Probe.wav",
        "file:///tmp/Sonex Probe.wav",
    )
