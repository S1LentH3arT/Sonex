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

from src.tools.bead_pipeline import BeadGenerationProfile, prepare_cover_image
from src.tools.cover_patterns import (
    COVER_PATTERN_ALGORITHM_VERSION,
    COVER_PATTERN_MAX_BYTES,
    COVER_PATTERN_SIZES,
    CoverPatternError,
    cover_pattern_cache_path,
    fetch_cover_pattern,
    generate_cover_pattern,
)

EXPECTED_COVER_PATTERN_SIZES = (32, 36, 40, 44, 48, 56, 64, 80, 96, 112, 128, 144, 160, 176, 192)
EXPECTED_COVER_PATTERN_VARIANTS = {str(size) for size in EXPECTED_COVER_PATTERN_SIZES}


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
    def test_previous_fixed_palette_cache_is_invalidated(self) -> None:
        """Verifies that previous 48 color cache is invalidated behaves as expected.

        Typical use: Use this in automated tests when guarding the previous 48 color cache is invalidated behavior against regressions.

        Example: test_previous_48_color_cache_is_invalidated() -> passes without assertion failures when the behavior remains correct.
        """
        with tempfile.TemporaryDirectory() as tempdir:
            source = "https://cdn.example.test/album/legacy-cover.jpg"
            cache_path = cover_pattern_cache_path(source, cache_root=Path(tempdir))
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps({
                "palette": ["#000000"] * 48,
                "variants": {
                    str(size): [[0 for _ in range(size)] for _ in range(size)]
                    for size in COVER_PATTERN_SIZES
                },
                "source_hash": "legacy",
                "generated_at": 1,
            }), encoding="utf-8")

            payload = generate_cover_pattern(source, _png_bytes(), cache_root=Path(tempdir))

        self.assertGreaterEqual(len(payload["palette"]), 32)
        self.assertLessEqual(len(payload["palette"]), 48)
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
            self.assertEqual(COVER_PATTERN_SIZES, EXPECTED_COVER_PATTERN_SIZES)
            self.assertEqual(set(payload["variants"]), EXPECTED_COVER_PATTERN_VARIANTS)
            self.assertGreaterEqual(len(payload["palette"]), 32)
            self.assertLessEqual(len(payload["palette"]), 48)
            self.assertEqual(payload["bead_catalog"]["brand"], "hama")
            self.assertEqual(payload["bead_catalog"]["algorithm_version"], COVER_PATTERN_ALGORITHM_VERSION)
            self.assertEqual(len(payload["bead_catalog"]["colors"]), len(payload["palette"]))

            for size_text, grid in payload["variants"].items():
                size = int(size_text)
                self.assertEqual(len(grid), size)
                self.assertTrue(all(len(row) == size for row in grid))
                self.assertTrue(all(0 <= index < len(payload["palette"]) for row in grid for index in row))
                usage = payload["bead_catalog"]["usage_by_variant"][size_text]
                self.assertEqual(sum(item["count"] for item in usage), size * size)

            cache_path = cover_pattern_cache_path(source, cache_root=Path(tempdir))
            self.assertTrue(cache_path.exists())
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            self.assertNotIn("source_url", cached)
            self.assertNotIn("image", cached)
            self.assertNotIn("bytes", cached)
            self.assertEqual(cached["variants"], payload["variants"])
            self.assertIn("generation_diagnostics", cached)
            self.assertNotIn("generation_diagnostics", payload)
            self.assertEqual(cached["generation_diagnostics"]["fallback_sizes"], [])
            self.assertEqual(cached["profile"]["algorithm_version"], "lab-ciede2000-edge-refine-v3")
            self.assertEqual(cached["profile"]["sizes"], list(EXPECTED_COVER_PATTERN_SIZES))
            self.assertEqual(cached["profile"]["sample_scales"], [32, 48, 64, 96, 128, 160, 192])
            self.assertEqual(cached["profile"]["refinement"], {
                "candidate_count": 4,
                "smoothing_rounds": 2,
                "continuity_weight": 2.5,
                "edge_scale": 12.0,
                "island_max_size": 2,
                "island_merge_delta_e_max": 18.0,
            })

            with patch("src.tools.cover_patterns.generate_bead_pattern", side_effect=AssertionError("cache missed")):
                second = generate_cover_pattern(source, b"not an image", cache_root=Path(tempdir))

            self.assertEqual(second["variants"], payload["variants"])

    def test_single_size_refinement_failure_falls_back_and_records_diagnostics(self) -> None:
        from src.tools.bead_postprocess import refine_bead_grid as real_refine

        def refine_or_fail(mapping: object, profile: object) -> object:
            if mapping.indices.shape == (44, 44):
                raise RuntimeError("synthetic refinement failure")
            return real_refine(mapping, profile)

        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            source = "https://cdn.example.test/album/refine-fallback.jpg"
            with patch("src.tools.bead_pipeline.refine_bead_grid", side_effect=refine_or_fail):
                payload = generate_cover_pattern(source, _png_bytes(), cache_root=root)

            cached = json.loads(cover_pattern_cache_path(source, cache_root=root).read_text(encoding="utf-8"))

        self.assertEqual(cached["generation_diagnostics"]["fallback_sizes"], [44])
        self.assertNotIn("generation_diagnostics", payload)
        self.assertEqual(len(payload["variants"]["44"]), 44)
        self.assertEqual(
            sum(item["count"] for item in payload["bead_catalog"]["usage_by_variant"]["44"]),
            44 * 44,
        )

    def test_previous_five_size_cache_is_invalidated(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            source = "https://cdn.example.test/album/five-size-cover.jpg"
            cache_path = cover_pattern_cache_path(source, cache_root=Path(tempdir))
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps({
                "palette": ["#000000"] * 32,
                "variants": {
                    str(size): [[0 for _ in range(size)] for _ in range(size)]
                    for size in (32, 48, 64, 80, 96)
                },
                "source_hash": "legacy-five-size",
                "generated_at": 1,
            }), encoding="utf-8")

            payload = generate_cover_pattern(source, _png_bytes(), cache_root=Path(tempdir))

        self.assertEqual(set(payload["variants"]), EXPECTED_COVER_PATTERN_VARIANTS)
        self.assertNotEqual(payload["source_hash"], "legacy-five-size")

    def test_brand_and_profile_changes_invalidate_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            source = "https://cdn.example.test/album/brand-switch.jpg"
            hama = generate_cover_pattern(source, _png_bytes(), cache_root=root, brand="hama")
            perler = generate_cover_pattern(source, _png_bytes(), cache_root=root, brand="perler")
            self.assertEqual(hama["bead_catalog"]["brand"], "hama")
            self.assertEqual(perler["bead_catalog"]["brand"], "perler")

            cache_path = cover_pattern_cache_path(source, cache_root=root)
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            cached["profile"]["algorithm_version"] = "legacy-rgb-v1"
            cached["source_hash"] = "legacy-profile"
            cache_path.write_text(json.dumps(cached), encoding="utf-8")
            regenerated = generate_cover_pattern(source, _png_bytes(), cache_root=root, brand="perler")
            self.assertNotEqual(regenerated["source_hash"], "legacy-profile")
            self.assertEqual(COVER_PATTERN_ALGORITHM_VERSION, "lab-ciede2000-edge-refine-v3")
            self.assertEqual(regenerated["bead_catalog"]["algorithm_version"], COVER_PATTERN_ALGORITHM_VERSION)

    def test_large_variant_payload_stays_under_half_megabyte(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            payload = generate_cover_pattern(
                "https://cdn.example.test/album/high-res-payload.jpg",
                _png_bytes((192, 192)),
                cache_root=Path(tempdir),
            )

        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

        self.assertLess(len(encoded), 500 * 1024)

    def test_preparation_composites_transparency_to_white_and_caps_square_at_640(self) -> None:
        image = Image.new("RGBA", (800, 700), (0, 0, 0, 0))
        profile = BeadGenerationProfile(
            algorithm_version=COVER_PATTERN_ALGORITHM_VERSION,
            sizes=COVER_PATTERN_SIZES,
        )

        prepared = prepare_cover_image(image, profile)

        self.assertEqual(prepared.size, (640, 640))
        self.assertEqual(prepared.getpixel((0, 0)), (255, 255, 255))

    def test_explicit_invalid_brand_fails_closed(self) -> None:
        with self.assertRaises(CoverPatternError) as raised:
            generate_cover_pattern("track-invalid", _png_bytes(), brand="generic")

        self.assertEqual(raised.exception.reason, "invalid_brand")

    def test_decode_failure_is_recoverable(self) -> None:
        """Verifies that decode failure is recoverable behaves as expected.

        Typical use: Use this in automated tests when guarding the decode failure is recoverable behavior against regressions.

        Example: test_decode_failure_is_recoverable() -> passes without assertion failures when the behavior remains correct.
        """
        with tempfile.TemporaryDirectory() as tempdir:
            with self.assertRaises(CoverPatternError) as raised:
                generate_cover_pattern("track-1", b"not an image", cache_root=Path(tempdir))

            self.assertEqual(raised.exception.reason, "decode_failed")

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
