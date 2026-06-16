"""Manual review export for generated bead cover patterns."""

from __future__ import annotations

import csv
import io
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from PIL import Image, ImageDraw

from src.tools.bead_pipeline import BeadGenerationProfile, prepare_cover_image
from src.tools.cover_patterns import COVER_PATTERN_ALGORITHM_VERSION, COVER_PATTERN_SIZES, generate_cover_pattern
from src.tools.track_search import search_track_metadata_candidates


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REVIEW_ROOT = PROJECT_ROOT / "temp" / "bead-pattern-review"
REVIEW_SIZES = (32, 48, 64, 80, 96)
REVIEW_PRIMARY_SIZES = (80, 96)


def _review_cover_bytes() -> bytes:
    cover_path = os.environ.get("SONEX_REVIEW_COVER_PATH")
    if cover_path:
        return Path(cover_path).read_bytes()

    track_query = os.environ.get("SONEX_REVIEW_TRACK_QUERY")
    if track_query:
        metadata = _resolve_review_track_metadata(track_query)
        (REVIEW_ROOT / "track-search-selection.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return _download_review_cover(str(metadata["cover_url"]))

    size = 640
    image = Image.new("RGB", (size, size), "#181a33")
    draw = ImageDraw.Draw(image)
    for y in range(size):
        ratio = y / (size - 1)
        red = int(24 + ratio * 84)
        green = int(26 + ratio * 34)
        blue = int(51 + ratio * 94)
        draw.line([(0, y), (size, y)], fill=(red, green, blue))

    draw.ellipse((58, 54, 300, 296), fill="#f7d65f")
    draw.ellipse((92, 82, 270, 270), fill="#f17f5d")
    draw.ellipse((132, 118, 248, 238), fill="#26233d")
    draw.rectangle((84, 390, 560, 492), fill="#f3e9d2")
    draw.rectangle((84, 492, 560, 560), fill="#3d2145")
    draw.polygon([(350, 70), (580, 180), (452, 366)], fill="#62c6d4")
    draw.line((68, 352, 574, 116), fill="#fff3b0", width=20)
    draw.line((72, 362, 578, 126), fill="#2e2b54", width=6)
    for offset, color in ((0, "#f44363"), (56, "#48d597"), (112, "#5491f5"), (168, "#f7d65f")):
        draw.rounded_rectangle((114 + offset, 414, 156 + offset, 520), radius=12, fill=color)

    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _resolve_review_track_metadata(query: str) -> dict[str, Any]:
    result = search_track_metadata_candidates(query, limit=10)
    candidates = [item for item in result.get("candidates", []) if isinstance(item, dict)]
    with_cover = [
        item for item in candidates
        if item.get("album_cover_url") or item.get("cover_url") or item.get("image_url")
    ]
    if not with_cover:
        raise AssertionError(f"No cover candidate found for review query: {query}")

    preferred_album = os.environ.get("SONEX_REVIEW_ALBUM", "未来")
    selected = next(
        (item for item in with_cover if preferred_album and preferred_album in str(item.get("album") or "")),
        with_cover[0],
    )
    cover_url = str(selected.get("album_cover_url") or selected.get("cover_url") or selected.get("image_url"))
    return {
        "query": query,
        "preferred_album": preferred_album,
        "selected": selected,
        "source_attempts": result.get("source_attempts", []),
        "cover_url": _upgrade_itunes_artwork_url(cover_url),
    }


def _upgrade_itunes_artwork_url(url: str) -> str:
    if "mzstatic.com/" not in url:
        return url
    for marker in ("100x100", "60x60", "30x30"):
        url = url.replace(marker, "1200x1200")
    return url


def _download_review_cover(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": "Sonex/1.0"})
    with urlopen(request, timeout=10) as response:
        return response.read()


def _write_pattern_png(path: Path, grid: list[list[int]], palette: list[str], *, cell_size: int) -> None:
    size = len(grid)
    pixel_image = Image.new("RGB", (size, size), "white")
    for y, row in enumerate(grid):
        for x, palette_index in enumerate(row):
            pixel_image.putpixel((x, y), _hex_to_rgb(palette[palette_index]))
    pixel_image.resize((size * cell_size, size * cell_size), Image.Resampling.NEAREST).save(path)


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    return (
        int(hex_color[1:3], 16),
        int(hex_color[3:5], 16),
        int(hex_color[5:7], 16),
    )


def _ansi_truecolor(hex_color: str, *, foreground: bool) -> str:
    red = int(hex_color[1:3], 16)
    green = int(hex_color[3:5], 16)
    blue = int(hex_color[5:7], 16)
    slot = 38 if foreground else 48
    return f"\x1b[{slot};2;{red};{green};{blue}m"


def _write_half_block_preview(path: Path, grid: list[list[int]], palette: list[str]) -> None:
    lines: list[str] = []
    for y in range(0, len(grid), 2):
        upper = grid[y]
        lower = grid[y + 1] if y + 1 < len(grid) else upper
        line = "".join(
            f"{_ansi_truecolor(palette[upper[x]], foreground=True)}"
            f"{_ansi_truecolor(palette[lower[x]], foreground=False)}▀"
            for x in range(len(upper))
        )
        lines.append(f"{line}\x1b[0m")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_palette(path: Path, catalog: dict[str, Any]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["palette_index", "code", "name", "hex"])
        writer.writeheader()
        writer.writerows(catalog["colors"])


class BeadPatternPngRendererTests(unittest.TestCase):
    def test_review_png_uses_gapless_square_pixels(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "pattern.png"
            _write_pattern_png(path, [[0, 1], [1, 0]], ["#112233", "#aabbcc"], cell_size=3)
            image = Image.open(path).convert("RGB")

        self.assertEqual(image.size, (6, 6))
        self.assertEqual(image.getpixel((0, 0)), (17, 34, 51))
        self.assertEqual(image.getpixel((2, 2)), (17, 34, 51))
        self.assertEqual(image.getpixel((3, 0)), (170, 187, 204))
        self.assertEqual(image.getpixel((5, 2)), (170, 187, 204))
        self.assertEqual(image.getpixel((0, 3)), (170, 187, 204))
        self.assertEqual(image.getpixel((2, 5)), (170, 187, 204))


@unittest.skipUnless(
    os.environ.get("SONEX_WRITE_BEAD_REVIEW") == "1",
    "Set SONEX_WRITE_BEAD_REVIEW=1 to export bead pattern review files into temp/.",
)
class BeadPatternReviewExportTests(unittest.TestCase):
    def test_export_generated_bead_patterns_for_manual_review(self) -> None:
        shutil.rmtree(REVIEW_ROOT, ignore_errors=True)
        REVIEW_ROOT.mkdir(parents=True, exist_ok=True)
        cache_root = REVIEW_ROOT / "cache"

        image_bytes = _review_cover_bytes()
        (REVIEW_ROOT / "review-cover-source.png").write_bytes(image_bytes)
        payload = generate_cover_pattern(
            "manual-review-cover",
            image_bytes,
            cache_root=cache_root,
            brand=os.environ.get("SONEX_REVIEW_BEAD_BRAND", "hama"),
        )
        cached = json.loads(next((cache_root).glob("*.json")).read_text(encoding="utf-8"))
        prepared_image = Image.open(io.BytesIO(image_bytes))

        prepared = prepare_cover_image(
            prepared_image,
            BeadGenerationProfile(
                algorithm_version=COVER_PATTERN_ALGORITHM_VERSION,
                sizes=COVER_PATTERN_SIZES,
            ),
        )
        prepared.save(REVIEW_ROOT / "prepared-cover-input.png")

        (REVIEW_ROOT / "cover-pattern-payload.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        _write_palette(REVIEW_ROOT / "palette.csv", payload["bead_catalog"])
        (REVIEW_ROOT / "selected-cover-metadata.json").write_text(
            json.dumps({
                "source": "track-search" if os.environ.get("SONEX_REVIEW_TRACK_QUERY") else "synthetic",
                "track_query": os.environ.get("SONEX_REVIEW_TRACK_QUERY"),
                "cover_path": os.environ.get("SONEX_REVIEW_COVER_PATH"),
                "brand": payload["bead_catalog"]["brand"],
                "algorithm_version": payload["bead_catalog"]["algorithm_version"],
                "crop": cached["profile"]["crop"],
                "primary_review_sizes": list(REVIEW_PRIMARY_SIZES),
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        for size in REVIEW_SIZES:
            grid = payload["variants"][str(size)]
            cell_size = 10 if size <= 64 else 6 if size <= 128 else 4
            _write_pattern_png(REVIEW_ROOT / f"pattern-{size}.png", grid, payload["palette"], cell_size=cell_size)
            _write_half_block_preview(REVIEW_ROOT / f"pattern-{size}.ansi", grid, payload["palette"])

        self.assertTrue((REVIEW_ROOT / "prepared-cover-input.png").exists())
        self.assertTrue((REVIEW_ROOT / "pattern-80.png").exists())
        self.assertTrue((REVIEW_ROOT / "pattern-96.png").exists())
        self.assertTrue((REVIEW_ROOT / "selected-cover-metadata.json").exists())
        self.assertTrue((REVIEW_ROOT / "cover-pattern-payload.json").exists())
