"""Orchestrate image preparation and physical bead pattern generation."""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter, ImageOps, UnidentifiedImageError

from src.tools.bead_catalogs import BeadCatalog
from src.tools.bead_colors import srgb_to_lab
from src.tools.bead_palette import build_multiscale_samples, build_palette_mapping, select_shared_palette
from src.tools.bead_postprocess import BeadRefinementProfile, refine_bead_grid


class BeadImageDecodeError(ValueError):
    """Raised when source bytes cannot be decoded as an image."""


@dataclass(frozen=True)
class BeadGenerationProfile:
    """Describe every input that changes generated cache output."""

    algorithm_version: str
    sizes: tuple[int, ...]
    sample_scales: tuple[int, ...] = (32, 40, 48, 56, 64, 80, 96, 128, 160, 192)
    crop_ratio: float = 0.825
    contrast: float = 1.06
    unsharp_radius: float = 1.1
    unsharp_percent: int = 75
    unsharp_threshold: int = 3
    minimum_colors: int = 32
    maximum_colors: int = 72
    relative_improvement_threshold: float = 0.01
    refinement: BeadRefinementProfile = field(default_factory=BeadRefinementProfile)

    def as_dict(self, catalog: BeadCatalog) -> dict[str, Any]:
        """Return the stable cache identity for this generation profile."""
        return {
            "brand": catalog.brand,
            "product_line": catalog.product_line,
            "catalog_version": catalog.version,
            "algorithm_version": self.algorithm_version,
            "sizes": list(self.sizes),
            "sample_scales": list(self.sample_scales),
            "crop": {
                "mode": "center",
                "ratio": self.crop_ratio,
            },
            "enhancement": {
                "contrast": self.contrast,
                "unsharp_radius": self.unsharp_radius,
                "unsharp_percent": self.unsharp_percent,
                "unsharp_threshold": self.unsharp_threshold,
            },
            "color_budget": {
                "minimum": self.minimum_colors,
                "maximum": self.maximum_colors,
                "relative_improvement_threshold": self.relative_improvement_threshold,
            },
            "refinement": self.refinement.as_dict(),
        }


def prepare_cover_image(image: Image.Image, profile: BeadGenerationProfile) -> Image.Image:
    """Orient, composite, crop, resize, and conservatively enhance cover art."""
    oriented = ImageOps.exif_transpose(image)
    rgba = oriented.convert("RGBA")
    white = Image.new("RGBA", rgba.size, "white")
    rgb = Image.alpha_composite(white, rgba).convert("RGB")
    width, height = rgb.size
    side = min(width, height)
    left = (width - side) // 2
    top = (height - side) // 2
    cropped = rgb.crop((left, top, left + side, top + side))
    crop_ratio = max(0.0, min(1.0, profile.crop_ratio))
    if 0.0 < crop_ratio < 1.0:
        crop_side = max(1, int(round(side * crop_ratio)))
        crop_left = (side - crop_side) // 2
        crop_top = (side - crop_side) // 2
        cropped = cropped.crop((crop_left, crop_top, crop_left + crop_side, crop_top + crop_side))
        side = crop_side
    if side > 640:
        cropped = cropped.resize((640, 640), Image.Resampling.LANCZOS)
    contrasted = ImageEnhance.Contrast(cropped).enhance(profile.contrast)
    return contrasted.filter(ImageFilter.UnsharpMask(
        radius=profile.unsharp_radius,
        percent=profile.unsharp_percent,
        threshold=profile.unsharp_threshold,
    ))


def generate_bead_pattern(image_bytes: bytes, catalog: BeadCatalog, profile: BeadGenerationProfile) -> dict[str, Any]:
    """Generate all variants from one shared adaptive catalog subset."""
    try:
        with Image.open(io.BytesIO(image_bytes)) as image:
            prepared = prepare_cover_image(image, profile)
    except (UnidentifiedImageError, OSError) as exc:
        raise BeadImageDecodeError("Cover image could not be decoded.") from exc

    samples = build_multiscale_samples(prepared, scales=profile.sample_scales)
    catalog_rgb = np.asarray([color.rgb for color in catalog.colors], dtype=np.uint8)
    maximum_colors = min(profile.maximum_colors, len(catalog_rgb))
    selected_catalog_indices = select_shared_palette(
        samples.lab,
        samples.weights,
        srgb_to_lab(catalog_rgb),
        minimum_colors=profile.minimum_colors,
        maximum_colors=maximum_colors,
        relative_improvement_threshold=profile.relative_improvement_threshold,
    )
    selected_rgb = catalog_rgb[selected_catalog_indices]
    variants: dict[str, list[list[int]]] = {}
    usage_by_variant: dict[str, list[dict[str, int]]] = {}
    fallback_sizes: list[int] = []
    variant_diagnostics: dict[str, dict[str, Any]] = {}
    for size in profile.sizes:
        resized = prepared.resize((size, size), Image.Resampling.BOX)
        mapping = build_palette_mapping(
            resized,
            selected_rgb,
            candidate_count=profile.refinement.candidate_count,
        )
        try:
            refinement = refine_bead_grid(mapping, profile.refinement)
            mapped = refinement.indices
            variant_diagnostics[str(size)] = refinement.diagnostics()
        except Exception:
            mapped = mapping.indices
            fallback_sizes.append(size)
            variant_diagnostics[str(size)] = {
                "round_change_counts": [],
                "island_changes": 0,
                "total_changes": 0,
                "fallback": True,
            }
        variants[str(size)] = mapped.tolist()
        counts = np.bincount(mapped.reshape(-1), minlength=len(selected_catalog_indices))
        usage_by_variant[str(size)] = [
            {"palette_index": index, "count": int(count)}
            for index, count in enumerate(counts)
            if count
        ]

    selected_colors = [catalog.colors[index] for index in selected_catalog_indices]
    return {
        "palette": [color.hex for color in selected_colors],
        "variants": variants,
        "bead_catalog": {
            "brand": catalog.brand,
            "product_line": catalog.product_line,
            "diameter_mm": catalog.diameter_mm,
            "version": catalog.version,
            "algorithm_version": profile.algorithm_version,
            "colors": [
                {
                    "palette_index": palette_index,
                    "code": color.code,
                    "name": color.name,
                    "hex": color.hex,
                }
                for palette_index, color in enumerate(selected_colors)
            ],
            "usage_by_variant": usage_by_variant,
        },
        "generation_diagnostics": {
            "fallback_sizes": fallback_sizes,
            "variants": variant_diagnostics,
        },
    }
