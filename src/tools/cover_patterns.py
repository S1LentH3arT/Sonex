from __future__ import annotations

import hashlib
import io
import json
import time
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from PIL import Image, ImageFilter, UnidentifiedImageError

from src.log import sonex_home

COVER_PATTERN_SIZES = (36, 48, 64)
COVER_PATTERN_MAX_BYTES = 8 * 1024 * 1024
COVER_PATTERN_PALETTE = [
    "#0b0c10", "#1b1f2a", "#343946", "#575d6b", "#8d95a3", "#c5ccd6",
    "#f4f1e8", "#ffffff", "#4a1f24", "#7d2e37", "#b3434e", "#e65f65",
    "#f0a0a2", "#ffd2cf", "#4e2a18", "#7b4323", "#a86332", "#d4894a",
    "#f0b45f", "#f6d58a", "#5d4d1c", "#8a742d", "#b8a044", "#e3ce67",
    "#f4e9a6", "#1f4a2e", "#2d6a42", "#3f8f5a", "#67b77a", "#a8d9a8",
    "#123b4a", "#1f6372", "#2f8ca0", "#5db7c7", "#a9dce3", "#1c2f63",
    "#304d9a", "#4f74d9", "#8aa5ee", "#c2d0ff", "#35215f", "#5d3b94",
    "#8a5cc2", "#b88be0", "#dec2f0", "#5a234b", "#963a75", "#d2609d",
]


class CoverPatternError(RuntimeError):
    pass


def cover_pattern_cache_dir() -> Path:
    return sonex_home() / "cache" / "cover_patterns"


def _source_hash(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def cover_pattern_cache_path(source: str, *, cache_root: Path | None = None) -> Path:
    root = cache_root or cover_pattern_cache_dir()
    return root / f"{_source_hash(source)}.json"


def fetch_cover_pattern(source_url: str) -> dict[str, Any]:
    cached = _read_cached_pattern(source_url)
    if cached is not None:
        return _event_payload(source_url, cached)
    image_bytes = _download_cover(source_url)
    return generate_cover_pattern(source_url, image_bytes)


def generate_cover_pattern(
    source: str,
    image_bytes: bytes,
    *,
    cache_root: Path | None = None,
) -> dict[str, Any]:
    cached = _read_cached_pattern(source, cache_root=cache_root)
    if cached is not None:
        return _event_payload(source, cached)

    variants = _pattern_from_image_bytes(image_bytes)
    cached_payload = {
        "palette": COVER_PATTERN_PALETTE,
        "variants": variants,
        "source_hash": _source_hash(source),
        "generated_at": int(time.time()),
    }

    path = cover_pattern_cache_path(source, cache_root=cache_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cached_payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return _event_payload(source, cached_payload)


def _event_payload(source: str, cached: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "cover_pattern",
        "source_url": source,
        "palette": cached["palette"],
        "variants": cached["variants"],
        "source_hash": cached["source_hash"],
        "generated_at": cached["generated_at"],
    }


def _read_cached_pattern(source: str, *, cache_root: Path | None = None) -> dict[str, Any] | None:
    path = cover_pattern_cache_path(source, cache_root=cache_root)
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if _valid_cached_pattern(cached):
        return cached
    return None


def _valid_cached_pattern(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    if value.get("palette") != COVER_PATTERN_PALETTE:
        return False
    variants = value.get("variants")
    if not isinstance(variants, dict):
        return False
    for size in COVER_PATTERN_SIZES:
        grid = variants.get(str(size))
        if not _valid_grid(grid, size):
            return False
    return bool(value.get("source_hash")) and isinstance(value.get("generated_at"), int)


def _valid_grid(grid: Any, size: int) -> bool:
    if not isinstance(grid, list) or len(grid) != size:
        return False
    for row in grid:
        if not isinstance(row, list) or len(row) != size:
            return False
        if any(not isinstance(index, int) or index < 0 or index >= len(COVER_PATTERN_PALETTE) for index in row):
            return False
    return True


def _download_cover(source_url: str) -> bytes:
    request = Request(source_url, headers={"User-Agent": "Sonex/1.0"})
    try:
        with urlopen(request, timeout=6) as response:
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = response.read(64 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > COVER_PATTERN_MAX_BYTES:
                    raise CoverPatternError("Cover image response is too large.")
                chunks.append(chunk)
    except (OSError, URLError) as exc:
        raise CoverPatternError(f"Cover image download failed: {exc}") from exc
    return b"".join(chunks)


def _pattern_from_image_bytes(image_bytes: bytes) -> dict[str, list[list[int]]]:
    try:
        with Image.open(io.BytesIO(image_bytes)) as image:
            prepared = _prepare_image(image)
            return {
                str(size): _image_to_palette_indices(prepared.resize((size, size), Image.Resampling.BOX))
                for size in COVER_PATTERN_SIZES
            }
    except (UnidentifiedImageError, OSError) as exc:
        raise CoverPatternError("Cover image could not be decoded.") from exc


def _prepare_image(image: Image.Image) -> Image.Image:
    rgb = image.convert("RGB")
    width, height = rgb.size
    side = min(width, height)
    left = (width - side) // 2
    top = (height - side) // 2
    cropped = rgb.crop((left, top, left + side, top + side))
    if side > 256:
        cropped = cropped.resize((256, 256), Image.Resampling.LANCZOS)
    return cropped.filter(ImageFilter.MedianFilter(3)).filter(ImageFilter.GaussianBlur(0.35))


def _image_to_palette_indices(image: Image.Image) -> list[list[int]]:
    pixels = image.convert("RGB").load()
    width, height = image.size
    return [
        [_nearest_palette_index(pixels[x, y]) for x in range(width)]
        for y in range(height)
    ]


def _nearest_palette_index(rgb: tuple[int, int, int]) -> int:
    red, green, blue = rgb
    best_index = 0
    best_distance = float("inf")
    for index, hex_color in enumerate(COVER_PATTERN_PALETTE):
        pr = int(hex_color[1:3], 16)
        pg = int(hex_color[3:5], 16)
        pb = int(hex_color[5:7], 16)
        distance = ((red - pr) ** 2 * 0.30) + ((green - pg) ** 2 * 0.59) + ((blue - pb) ** 2 * 0.11)
        if distance < best_distance:
            best_distance = distance
            best_index = index
    return best_index
