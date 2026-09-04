from __future__ import annotations

from src.tools.diagnostics_policy import filter_audio_metadata, sanitize_diagnostic_text


def test_sanitize_diagnostic_text_redacts_urls_credentials_and_media_location() -> None:
    assert sanitize_diagnostic_text(
        "file.mp3 https://example.test/a token=secret",
        media_location="file.mp3",
    ) == "<media> <url> token=<redacted>"


def test_filter_audio_metadata_keeps_only_approved_fields() -> None:
    assert filter_audio_metadata({"cache_hit": True, "secret": "x"}) == {"cache_hit": True}
