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
    image = Image.new("RGB", size, "#2448a8")
    for x in range(size[0] // 3, size[0]):
        for y in range(size[1] // 4, size[1]):
            image.putpixel((x, y), (226, 72, 88))
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


class CoverPatternTests(unittest.TestCase):
    def test_fixed_palette_contains_96_unique_rgb_colors(self) -> None:
        self.assertEqual(len(COVER_PATTERN_PALETTE), 96)
        self.assertEqual(len(set(COVER_PATTERN_PALETTE)), 96)
        self.assertTrue(all(
            len(color) == 7
            and color.startswith("#")
            and all(character in "0123456789abcdef" for character in color[1:])
            for color in COVER_PATTERN_PALETTE
        ))

    def test_previous_48_color_cache_is_invalidated(self) -> None:
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
        with tempfile.TemporaryDirectory() as tempdir:
            source = "https://cdn.example.test/album/cover-640.jpg"
            payload = generate_cover_pattern(source, _png_bytes(), cache_root=Path(tempdir))

            self.assertEqual(payload["source_url"], source)
            self.assertEqual(payload["palette"], COVER_PATTERN_PALETTE)
            self.assertEqual(set(payload["variants"]), {"36", "48", "64"})

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

    def test_decode_failure_is_recoverable(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            with self.assertRaises(CoverPatternError):
                generate_cover_pattern("track-1", b"not an image", cache_root=Path(tempdir))

            cache_path = cover_pattern_cache_path("track-1", cache_root=Path(tempdir))
            self.assertFalse(cache_path.exists())

    def test_download_failure_is_recoverable(self) -> None:
        with patch("src.tools.cover_patterns.urlopen", side_effect=URLError("offline")):
            with self.assertRaises(CoverPatternError):
                fetch_cover_pattern("https://cdn.example.test/missing.jpg")

    def test_oversized_response_is_recoverable(self) -> None:
        class OversizedResponse:
            def __enter__(self) -> "OversizedResponse":
                self.remaining = COVER_PATTERN_MAX_BYTES + 1
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            def read(self, size: int) -> bytes:
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
