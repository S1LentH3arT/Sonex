"""Tests test cover sources.

Contains pytest coverage for the test cover sources behavior.
"""

from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mutagen.id3 import APIC, ID3
from PIL import Image

from src.tools.cover_patterns import generate_cover_pattern
from src.tools.cover_sources import (
    cover_bytes_for_source,
    extract_embedded_cover,
    resolve_online_cover,
)


def _png_bytes() -> bytes:
    """Verifies that png bytes behaves as expected.

    Typical use: Use this in automated tests when guarding the png bytes behavior against regressions.

    Example: _png_bytes() -> passes without assertion failures when the behavior remains correct.
    """
    image = Image.new("RGB", (80, 80), "#355f9f")
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


class CoverSourceTests(unittest.TestCase):
    """Groups related cover source tests cases.

    Collects assertions that exercise cover source tests behavior without mixing unrelated fixtures.
    """
    def test_extract_embedded_mp3_cover_registers_stable_source_bytes(self) -> None:
        """Verifies that extract embedded mp3 cover registers stable source bytes behaves as expected.

        Typical use: Use this in automated tests when guarding the extract embedded mp3 cover registers stable source bytes behavior against regressions.

        Example: test_extract_embedded_mp3_cover_registers_stable_source_bytes() -> passes without assertion failures when the behavior remains correct.
        """
        with tempfile.TemporaryDirectory() as tmp:
            audio_path = Path(tmp) / "song.mp3"
            audio_path.write_bytes(b"")
            image_bytes = _png_bytes()
            tags = ID3()
            tags.add(APIC(encoding=3, mime="image/png", type=3, desc="front", data=image_bytes))
            tags.save(audio_path)

            cover = extract_embedded_cover(audio_path)

            self.assertIsNotNone(cover)
            assert cover is not None
            self.assertEqual(cover["source_type"], "embedded")
            self.assertTrue(str(cover["cover_source"]).startswith("embedded:"))
            self.assertEqual(cover_bytes_for_source(str(cover["cover_source"])), image_bytes)
            pattern = generate_cover_pattern(str(cover["cover_source"]), image_bytes, cache_root=Path(tmp) / "patterns")
            self.assertEqual(pattern["source_url"], cover["cover_source"])

    def test_resolve_online_cover_prefers_provider_cover_without_musicbrainz_lookup(self) -> None:
        """Verifies that resolve online cover prefers provider cover without musicbrainz lookup behaves as expected.

        Typical use: Use this in automated tests when guarding the resolve online cover prefers provider cover without musicbrainz lookup behavior against regressions.

        Example: test_resolve_online_cover_prefers_provider_cover_without_musicbrainz_lookup() -> passes without assertion failures when the behavior remains correct.
        """
        with patch("src.tools.cover_sources.lookup_cover_art_url", side_effect=AssertionError("should not look up")):
            cover = resolve_online_cover(
                {
                    "provider": "spotify",
                    "name": "Song",
                    "artist": "Artist",
                    "album": "Album",
                    "album_cover_url": "https://images.example/official.jpg",
                }
            )

        self.assertEqual(cover["cover_source"], "https://images.example/official.jpg")
        self.assertEqual(cover["source_type"], "provider")

    def test_resolve_online_cover_uses_caa_when_provider_cover_missing(self) -> None:
        """Verifies that resolve online cover uses caa when provider cover missing behaves as expected.

        Typical use: Use this in automated tests when guarding the resolve online cover uses caa when provider cover missing behavior against regressions.

        Example: test_resolve_online_cover_uses_caa_when_provider_cover_missing() -> passes without assertion failures when the behavior remains correct.
        """
        with patch("src.tools.cover_sources.lookup_cover_art_url", return_value="https://coverartarchive.org/release-group/mbid/front-500"):
            cover = resolve_online_cover({"provider": "youtube", "name": "Song", "artist": "Artist", "album": "Album"})

        self.assertEqual(cover["cover_source"], "https://coverartarchive.org/release-group/mbid/front-500")
        self.assertEqual(cover["source_type"], "cover_art_archive")

    def test_resolve_online_cover_ignores_youtube_thumbnail(self) -> None:
        """Verifies that resolve online cover ignores youtube thumbnail behaves as expected.

        Typical use: Use this in automated tests when guarding the resolve online cover ignores youtube thumbnail behavior against regressions.

        Example: test_resolve_online_cover_ignores_youtube_thumbnail() -> passes without assertion failures when the behavior remains correct.
        """
        with patch("src.tools.cover_sources.lookup_cover_art_url", return_value=None):
            cover = resolve_online_cover(
                {
                    "provider": "youtube",
                    "name": "Song",
                    "artist": "Artist",
                    "album": "Album",
                    "thumbnail": "https://i.ytimg.com/vi/abc/maxresdefault.jpg",
                    "album_cover_url": "https://i.ytimg.com/vi/abc/maxresdefault.jpg",
                }
            )

        self.assertEqual(cover, {})


if __name__ == "__main__":
    unittest.main()
