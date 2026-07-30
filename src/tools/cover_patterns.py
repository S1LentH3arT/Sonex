"""Download, cache, and expose versioned physical-bead cover patterns."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from src.log import sonex_home
from src.tools.bead_catalogs import BeadCatalog, CatalogValidationError, load_bead_catalog
from src.tools.bead_config import InvalidBeadBrand, SUPPORTED_BEAD_BRANDS, load_bead_brand
from src.tools.bead_pipeline import BeadGenerationProfile, BeadImageDecodeError, generate_bead_pattern

COVER_PATTERN_SIZES = (40, 48, 56, 64, 80, 96)
COVER_PATTERN_MAX_BYTES = 8 * 1024 * 1024
COVER_PATTERN_ALGORITHM_VERSION = "lab-ciede2000-original-crop-v5"

logger = logging.getLogger(__name__)


class CoverPatternError(RuntimeError):
    """Report a recoverable pattern failure with a stable reason and stage."""

    def __init__(self, message: str, *, reason: str = "generation_failed", stage: str = "generation") -> None:
        super().__init__(message)
        self.reason = reason
        self.stage = stage


def cover_pattern_cache_dir() -> Path:
    """Return the derived cover-pattern cache directory."""
    return sonex_home() / "cache" / "cover_patterns"


def _source_hash(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def cover_pattern_cache_path(source: str, *, cache_root: Path | None = None) -> Path:
    """Return the stable cache path for a cover source."""
    return (cache_root or cover_pattern_cache_dir()) / f"{_source_hash(source)}.json"


def _resolve_catalog(brand: str | None) -> BeadCatalog:
    if brand is not None and brand not in SUPPORTED_BEAD_BRANDS:
        exc = InvalidBeadBrand("beads.brand must be one of: hama, perler, mard.")
        logger.warning(
            "cover pattern failed brand=%r catalog=unresolved algorithm=%s stage=config error=%s",
            brand,
            COVER_PATTERN_ALGORITHM_VERSION,
            exc,
        )
        raise CoverPatternError(str(exc), reason="invalid_brand", stage="config") from exc
    try:
        resolved_brand = brand or load_bead_brand()
    except InvalidBeadBrand as exc:
        logger.warning(
            "cover pattern failed brand=%r catalog=unresolved algorithm=%s stage=config error=%s",
            brand,
            COVER_PATTERN_ALGORITHM_VERSION,
            exc,
        )
        raise CoverPatternError(str(exc), reason="invalid_brand", stage="config") from exc
    try:
        return load_bead_catalog(resolved_brand)
    except CatalogValidationError as exc:
        logger.warning(
            "cover pattern failed brand=%s catalog=invalid algorithm=%s stage=catalog error=%s",
            resolved_brand,
            COVER_PATTERN_ALGORITHM_VERSION,
            exc,
        )
        raise CoverPatternError(str(exc), reason="catalog_invalid", stage="catalog") from exc


def _profile(catalog: BeadCatalog) -> tuple[BeadGenerationProfile, dict[str, Any]]:
    profile = BeadGenerationProfile(algorithm_version=COVER_PATTERN_ALGORITHM_VERSION, sizes=COVER_PATTERN_SIZES)
    return profile, profile.as_dict(catalog)


def fetch_cover_pattern(source_url: str, *, brand: str | None = None) -> dict[str, Any]:
    """Return a cached pattern or download and generate one for an HTTP cover."""
    catalog = _resolve_catalog(brand)
    profile, profile_data = _profile(catalog)
    cached = _read_cached_pattern(source_url, profile_data=profile_data)
    if cached is not None:
        return _event_payload(source_url, cached)
    fallback_url = _caa_front_500_fallback(source_url)
    try:
        return generate_cover_pattern(source_url, _download_cover(source_url), brand=catalog.brand)
    except CoverPatternError as exc:
        if not fallback_url or exc.stage not in {"download", "decode"}:
            raise
    assert fallback_url is not None
    fallback_cached = _read_cached_pattern(fallback_url, profile_data=profile_data)
    if fallback_cached is not None:
        return _event_payload(fallback_url, fallback_cached)
    return generate_cover_pattern(fallback_url, _download_cover(fallback_url), brand=catalog.brand)


def generate_cover_pattern(
    source: str,
    image_bytes: bytes,
    *,
    cache_root: Path | None = None,
    brand: str | None = None,
) -> dict[str, Any]:
    """Generate and cache all bead variants without persisting source image bytes."""
    catalog = _resolve_catalog(brand)
    profile, profile_data = _profile(catalog)
    cached = _read_cached_pattern(source, cache_root=cache_root, profile_data=profile_data)
    if cached is not None:
        return _event_payload(source, cached)
    try:
        generated = generate_bead_pattern(image_bytes, catalog, profile)
    except BeadImageDecodeError as exc:
        _log_failure(catalog, "decode", exc)
        raise CoverPatternError(str(exc), reason="decode_failed", stage="decode") from exc
    except Exception as exc:
        _log_failure(catalog, "generation", exc)
        raise CoverPatternError(
            "Cover pattern generation failed.",
            reason="generation_failed",
            stage="generation",
        ) from exc

    cached_payload = {
        **generated,
        "profile": profile_data,
        "source_hash": _source_hash(source),
        "generated_at": int(time.time()),
    }
    path = cover_pattern_cache_path(source, cache_root=cache_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cached_payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return _event_payload(source, cached_payload)


def _log_failure(catalog: BeadCatalog, stage: str, exc: BaseException) -> None:
    logger.warning(
        "cover pattern failed brand=%s catalog=%s algorithm=%s stage=%s error=%s",
        catalog.brand,
        catalog.version,
        COVER_PATTERN_ALGORITHM_VERSION,
        stage,
        exc,
    )


def _caa_front_500_fallback(source_url: str) -> str | None:
    lowered = source_url.lower()
    if not lowered.startswith("https://coverartarchive.org/") or not lowered.endswith("/front"):
        return None
    return f"{source_url}-500"


def _event_payload(source: str, cached: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "cover_pattern",
        "source_url": source,
        "palette": cached["palette"],
        "variants": cached["variants"],
        "bead_catalog": cached.get("bead_catalog"),
        "source_hash": cached["source_hash"],
        "generated_at": cached["generated_at"],
    }


def _read_cached_pattern(
    source: str,
    *,
    cache_root: Path | None = None,
    profile_data: dict[str, Any],
) -> dict[str, Any] | None:
    path = cover_pattern_cache_path(source, cache_root=cache_root)
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return cached if _valid_cached_pattern(cached, profile_data) else None


def _valid_cached_pattern(value: Any, profile_data: dict[str, Any]) -> bool:
    if not isinstance(value, dict) or value.get("profile") != profile_data:
        return False
    palette = value.get("palette")
    if not isinstance(palette, list) or not 1 <= len(palette) <= 72 or len(set(palette)) != len(palette):
        return False
    if any(not isinstance(color, str) or len(color) != 7 or not color.startswith("#") for color in palette):
        return False
    variants = value.get("variants")
    if not isinstance(variants, dict):
        return False
    for size in COVER_PATTERN_SIZES:
        if not _valid_grid(variants.get(str(size)), size, len(palette)):
            return False
    metadata = value.get("bead_catalog")
    if not isinstance(metadata, dict) or metadata.get("brand") != profile_data["brand"]:
        return False
    colors = metadata.get("colors")
    usage = metadata.get("usage_by_variant")
    if not isinstance(colors, list) or len(colors) != len(palette) or not isinstance(usage, dict):
        return False
    for size in COVER_PATTERN_SIZES:
        entries = usage.get(str(size))
        if not isinstance(entries, list) or not all(isinstance(item, dict) for item in entries):
            return False
        if sum(item.get("count", 0) for item in entries) != size * size:
            return False
    diagnostics = value.get("generation_diagnostics")
    if not isinstance(diagnostics, dict):
        return False
    fallback_sizes = diagnostics.get("fallback_sizes")
    variant_diagnostics = diagnostics.get("variants")
    if not isinstance(fallback_sizes, list) or any(size not in COVER_PATTERN_SIZES for size in fallback_sizes):
        return False
    if not isinstance(variant_diagnostics, dict) or set(variant_diagnostics) != {str(size) for size in COVER_PATTERN_SIZES}:
        return False
    return bool(value.get("source_hash")) and isinstance(value.get("generated_at"), int)


def _valid_grid(grid: Any, size: int, palette_size: int) -> bool:
    if not isinstance(grid, list) or len(grid) != size:
        return False
    return all(
        isinstance(row, list)
        and len(row) == size
        and all(isinstance(index, int) and not isinstance(index, bool) and 0 <= index < palette_size for index in row)
        for row in grid
    )


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
                    raise CoverPatternError("Cover image response is too large.", stage="download")
                chunks.append(chunk)
    except CoverPatternError:
        raise
    except (OSError, URLError) as exc:
        raise CoverPatternError(f"Cover image download failed: {exc}", stage="download") from exc
    return b"".join(chunks)
