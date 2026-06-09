"""Cover patterns support for tool implementations used by the planner and playback flows.

Implements the cover_patterns module responsibilities used by Sonex runtime flows.
Key public entry points include CoverPatternError, cover_pattern_cache_dir, cover_pattern_cache_path, fetch_cover_pattern, generate_cover_pattern.
"""

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

COVER_PATTERN_SIZES = (32, 48, 64, 80, 96)
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
    "#15171d", "#272b34", "#454b58", "#707784", "#a8afba", "#dde1e6",
    "#3b2428", "#622a31", "#963842", "#cb4c57", "#ee7d82", "#f8b9b8",
    "#3b281d", "#61361f", "#904c27", "#bd6632", "#e29345", "#f4c574",
    "#443d20", "#716126", "#9e8734", "#ceb34b", "#ead97b", "#f8efbd",
    "#183824", "#255535", "#347849", "#4fa066", "#82c58f", "#c4e5c0",
    "#102f38", "#19505c", "#277789", "#41a1b2", "#7dcbd4", "#c9eef1",
    "#172446", "#263d78", "#3d5eb5", "#6685e3", "#a5b9f5", "#dce5ff",
    "#2a1c49", "#493078", "#7049a8", "#9e70ce", "#caa4e7", "#ead8f6",
]


class CoverPatternError(RuntimeError):
    """Represents cover pattern error.

    Encapsulates cover pattern error data and behavior used by Sonex runtime flows. Extends runtime error semantics.
    """
    pass


def cover_pattern_cache_dir() -> Path:
    """Coordinates cover pattern cache dir for the current Sonex flow.

    Typical use: Use this function when runtime code needs cover pattern cache dir as part of a Sonex command, playback, auth, llm, or ui path.

    Example: cover_pattern_cache_dir() -> returns the value used by the surrounding Sonex flow.
    """
    return sonex_home() / "cache" / "cover_patterns"


def _source_hash(source: str) -> str:
    """Prepares source hash for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs source hash without duplicating the local rules.

    Example: _source_hash(source=...) -> returns the value used by the surrounding Sonex flow.
    """
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def cover_pattern_cache_path(source: str, *, cache_root: Path | None = None) -> Path:
    """Coordinates cover pattern cache path for the current Sonex flow.

    Typical use: Use this function when runtime code needs cover pattern cache path as part of a Sonex command, playback, auth, llm, or ui path.

    Example: cover_pattern_cache_path(source=..., cache_root=...) -> returns the value used by the surrounding Sonex flow.
    """
    root = cache_root or cover_pattern_cache_dir()
    return root / f"{_source_hash(source)}.json"


def fetch_cover_pattern(source_url: str) -> dict[str, Any]:
    """Coordinates fetch cover pattern for the current Sonex flow.

    Typical use: Use this function when runtime code needs fetch cover pattern as part of a Sonex command, playback, auth, llm, or ui path.

    Example: fetch_cover_pattern(source_url=...) -> returns the value used by the surrounding Sonex flow.
    """
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
    """Coordinates generate cover pattern for the current Sonex flow.

    Typical use: Use this function when runtime code needs generate cover pattern as part of a Sonex command, playback, auth, llm, or ui path.

    Example: generate_cover_pattern(source=..., image_bytes=..., cache_root=...) -> returns the value used by the surrounding Sonex flow.
    """
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
    """Prepares event payload for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs event payload without duplicating the local rules.

    Example: _event_payload(source=..., cached=...) -> returns the value used by the surrounding Sonex flow.
    """
    return {
        "type": "cover_pattern",
        "source_url": source,
        "palette": cached["palette"],
        "variants": cached["variants"],
        "source_hash": cached["source_hash"],
        "generated_at": cached["generated_at"],
    }


def _read_cached_pattern(source: str, *, cache_root: Path | None = None) -> dict[str, Any] | None:
    """Prepares read cached pattern for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs read cached pattern without duplicating the local rules.

    Example: _read_cached_pattern(source=..., cache_root=...) -> returns the value used by the surrounding Sonex flow.
    """
    path = cover_pattern_cache_path(source, cache_root=cache_root)
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if _valid_cached_pattern(cached):
        return cached
    return None


def _valid_cached_pattern(value: Any) -> bool:
    """Prepares valid cached pattern for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs valid cached pattern without duplicating the local rules.

    Example: _valid_cached_pattern(value=...) -> returns the value used by the surrounding Sonex flow.
    """
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
    """Prepares valid grid for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs valid grid without duplicating the local rules.

    Example: _valid_grid(grid=..., size=...) -> returns the value used by the surrounding Sonex flow.
    """
    if not isinstance(grid, list) or len(grid) != size:
        return False
    for row in grid:
        if not isinstance(row, list) or len(row) != size:
            return False
        if any(not isinstance(index, int) or index < 0 or index >= len(COVER_PATTERN_PALETTE) for index in row):
            return False
    return True


def _download_cover(source_url: str) -> bytes:
    """Prepares download cover for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs download cover without duplicating the local rules.

    Example: _download_cover(source_url=...) -> returns the value used by the surrounding Sonex flow.
    """
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
    """Prepares pattern from image bytes for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs pattern from image bytes without duplicating the local rules.

    Example: _pattern_from_image_bytes(image_bytes=...) -> returns the value used by the surrounding Sonex flow.
    """
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
    """Prepares prepare image for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs prepare image without duplicating the local rules.

    Example: _prepare_image(image=...) -> returns the value used by the surrounding Sonex flow.
    """
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
    """Prepares image to palette indices for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs image to palette indices without duplicating the local rules.

    Example: _image_to_palette_indices(image=...) -> returns the value used by the surrounding Sonex flow.
    """
    pixels = image.convert("RGB").load()
    width, height = image.size
    return [
        [_nearest_palette_index(pixels[x, y]) for x in range(width)]
        for y in range(height)
    ]


def _nearest_palette_index(rgb: tuple[int, int, int]) -> int:
    """Prepares nearest palette index for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs nearest palette index without duplicating the local rules.

    Example: _nearest_palette_index(rgb=...) -> returns the value used by the surrounding Sonex flow.
    """
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
