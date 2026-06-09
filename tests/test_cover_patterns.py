"""Tests test cover patterns.

Contains pytest coverage for the test cover patterns behavior.
"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError

from PIL import Image

from src.tools.cover_patterns import (
    COVER_PATTERN_MAX_BYTES,
    COVER_PATTERN_PALETTE,
    COVER_PATTERN_SIZES,
    CoverPatternError,
    cover_pattern_cache_path,
    fetch_cover_pattern,
    generate_cover_pattern,
)


def _png_bytes(size: tuple[int, int] = (96, 80)) -> bytes:
    """Verifies that png bytes behaves as expected.

    Typical use: Use this in automated tests when guarding the png bytes behavior against regressions.

    Example: _png_bytes() -> passes without assertion failures when the behavior remains correct.
    """
    image = Image.new("RGB", size, "#2448a8")
    for x in range(size[0] // 3, size[0]):
        for y in range(size[1] // 4, size[1]):
            image.putpixel((x, y), (226, 72, 88))
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


class CoverPatternTests(unittest.TestCase):
    """Groups related cover pattern tests cases.

    Collects assertions that exercise cover pattern tests behavior without mixing unrelated fixtures.
    """
    def test_fixed_palette_contains_96_unique_rgb_colors(self) -> None:
        """Verifies that fixed palette contains 96 unique rgb colors behaves as expected.

        Typical use: Use this in automated tests when guarding the fixed palette contains 96 unique rgb colors behavior against regressions.

        Example: test_fixed_palette_contains_96_unique_rgb_colors() -> passes without assertion failures when the behavior remains correct.
        """
        self.assertEqual(len(COVER_PATTERN_PALETTE), 96)
        self.assertEqual(len(set(COVER_PATTERN_PALETTE)), 96)
        self.assertTrue(all(
            len(color) == 7
            and color.startswith("#")
            and all(character in "0123456789abcdef" for character in color[1:])
            for color in COVER_PATTERN_PALETTE
        ))

    def test_previous_48_color_cache_is_invalidated(self) -> None:
        """Verifies that previous 48 color cache is invalidated behaves as expected.

        Typical use: Use this in automated tests when guarding the previous 48 color cache is invalidated behavior against regressions.

        Example: test_previous_48_color_cache_is_invalidated() -> passes without assertion failures when the behavior remains correct.
        """
        with tempfile.TemporaryDirectory() as tempdir:
            source = "https://cdn.example.test/album/legacy-cover.jpg"
            cache_path = cover_pattern_cache_path(source, cache_root=Path(tempdir))
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps({
                "palette": COVER_PATTERN_PALETTE[:48],
                "variants": {
                    str(size): [[0 for _ in range(size)] for _ in range(size)]
                    for size in COVER_PATTERN_SIZES
                },
                "source_hash": "legacy",
                "generated_at": 1,
            }), encoding="utf-8")

            payload = generate_cover_pattern(source, _png_bytes(), cache_root=Path(tempdir))

        self.assertEqual(payload["palette"], COVER_PATTERN_PALETTE)
        self.assertNotEqual(payload["source_hash"], "legacy")

    def test_generate_cover_pattern_caches_expected_variants_without_source_bytes(self) -> None:
        """Verifies that generate cover pattern caches expected variants without source bytes behaves as expected.

        Typical use: Use this in automated tests when guarding the generate cover pattern caches expected variants without source bytes behavior against regressions.

        Example: test_generate_cover_pattern_caches_expected_variants_without_source_bytes() -> passes without assertion failures when the behavior remains correct.
        """
        with tempfile.TemporaryDirectory() as tempdir:
            source = "https://cdn.example.test/album/cover-640.jpg"
            payload = generate_cover_pattern(source, _png_bytes(), cache_root=Path(tempdir))

            self.assertEqual(payload["source_url"], source)
            self.assertEqual(payload["palette"], COVER_PATTERN_PALETTE)
            self.assertEqual(set(payload["variants"]), {"32", "48", "64", "80", "96"})

            for size_text, grid in payload["variants"].items():
                size = int(size_text)
                self.assertEqual(len(grid), size)
                self.assertTrue(all(len(row) == size for row in grid))
                self.assertTrue(all(0 <= index < 96 for row in grid for index in row))

            cache_path = cover_pattern_cache_path(source, cache_root=Path(tempdir))
            self.assertTrue(cache_path.exists())
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            self.assertNotIn("source_url", cached)
            self.assertNotIn("image", cached)
            self.assertNotIn("bytes", cached)
            self.assertEqual(cached["variants"], payload["variants"])

            with patch("src.tools.cover_patterns._pattern_from_image_bytes", side_effect=AssertionError("cache missed")):
                second = generate_cover_pattern(source, b"not an image", cache_root=Path(tempdir))

            self.assertEqual(second["variants"], payload["variants"])

    def test_previous_three_size_cache_is_invalidated(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            source = "https://cdn.example.test/album/three-size-cover.jpg"
            cache_path = cover_pattern_cache_path(source, cache_root=Path(tempdir))
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps({
                "palette": COVER_PATTERN_PALETTE,
                "variants": {
                    str(size): [[0 for _ in range(size)] for _ in range(size)]
                    for size in (32, 48, 64)
                },
                "source_hash": "legacy-three-size",
                "generated_at": 1,
            }), encoding="utf-8")

            payload = generate_cover_pattern(source, _png_bytes(), cache_root=Path(tempdir))

        self.assertEqual(set(payload["variants"]), {"32", "48", "64", "80", "96"})
        self.assertNotEqual(payload["source_hash"], "legacy-three-size")

    def test_decode_failure_is_recoverable(self) -> None:
        """Verifies that decode failure is recoverable behaves as expected.

        Typical use: Use this in automated tests when guarding the decode failure is recoverable behavior against regressions.

        Example: test_decode_failure_is_recoverable() -> passes without assertion failures when the behavior remains correct.
        """
        with tempfile.TemporaryDirectory() as tempdir:
            with self.assertRaises(CoverPatternError):
                generate_cover_pattern("track-1", b"not an image", cache_root=Path(tempdir))

            cache_path = cover_pattern_cache_path("track-1", cache_root=Path(tempdir))
            self.assertFalse(cache_path.exists())

    def test_download_failure_is_recoverable(self) -> None:
        """Verifies that download failure is recoverable behaves as expected.

        Typical use: Use this in automated tests when guarding the download failure is recoverable behavior against regressions.

        Example: test_download_failure_is_recoverable() -> passes without assertion failures when the behavior remains correct.
        """
        with patch("src.tools.cover_patterns.urlopen", side_effect=URLError("offline")):
            with self.assertRaises(CoverPatternError):
                fetch_cover_pattern("https://cdn.example.test/missing.jpg")

    def test_oversized_response_is_recoverable(self) -> None:
        """Verifies that oversized response is recoverable behaves as expected.

        Typical use: Use this in automated tests when guarding the oversized response is recoverable behavior against regressions.

        Example: test_oversized_response_is_recoverable() -> passes without assertion failures when the behavior remains correct.
        """
        class OversizedResponse:
            """Groups related oversized response cases.

            Collects assertions that exercise oversized response behavior without mixing unrelated fixtures.
            """
            def __enter__(self) -> "OversizedResponse":
                """Verifies that enter behaves as expected.

                Typical use: Use this in automated tests when guarding the enter behavior against regressions.

                Example: __enter__() -> passes without assertion failures when the behavior remains correct.
                """
                self.remaining = COVER_PATTERN_MAX_BYTES + 1
                return self

            def __exit__(self, *_args: object) -> None:
                """Verifies that exit behaves as expected.

                Typical use: Use this in automated tests when guarding the exit behavior against regressions.

                Example: __exit__() -> passes without assertion failures when the behavior remains correct.
                """
                return None

            def read(self, size: int) -> bytes:
                """Verifies that read behaves as expected.

                Typical use: Use this in automated tests when guarding the read behavior against regressions.

                Example: read() -> passes without assertion failures when the behavior remains correct.
                """
                if self.remaining <= 0:
                    return b""
                chunk = b"x" * min(size, self.remaining)
                self.remaining -= len(chunk)
                return chunk

        with patch("src.tools.cover_patterns.urlopen", return_value=OversizedResponse()):
            with self.assertRaises(CoverPatternError):
                fetch_cover_pattern("https://cdn.example.test/huge.jpg")


if __name__ == "__main__":
    unittest.main()
