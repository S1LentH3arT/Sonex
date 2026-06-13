"""Build image samples and select one adaptive physical bead palette."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from PIL import Image

from src.tools.bead_colors import pairwise_ciede2000, srgb_to_lab


@dataclass(frozen=True)
class MultiscaleSamples:
    """Hold combined color samples and normalized per-scale weights."""

    rgb: NDArray[np.uint8]
    lab: NDArray[np.float64]
    weights: NDArray[np.float64]
    scales: NDArray[np.int32]
    edge_weights: NDArray[np.float64]


@dataclass(frozen=True)
class PaletteMapping:
    """Retain direct mapping inputs and deterministic per-cell candidates."""

    indices: NDArray[np.int32]
    source_lab: NDArray[np.float64]
    palette_lab: NDArray[np.float64]
    candidate_indices: NDArray[np.int32]
    candidate_distances: NDArray[np.float64]


def build_multiscale_samples(image: Image.Image, *, scales: tuple[int, ...] = (32, 48, 64, 96)) -> MultiscaleSamples:
    """Sample an image at multiple area-resampled scales with equal scale weight."""
    rgb_parts: list[NDArray[np.uint8]] = []
    weight_parts: list[NDArray[np.float64]] = []
    scale_parts: list[NDArray[np.int32]] = []
    edge_parts: list[NDArray[np.float64]] = []
    for scale in scales:
        resized = image.resize((scale, scale), Image.Resampling.BOX).convert("RGB")
        rgb = np.asarray(resized, dtype=np.uint8)
        lightness = srgb_to_lab(rgb)[..., 0]
        gx = np.zeros_like(lightness)
        gy = np.zeros_like(lightness)
        gx[:, 1:] = np.abs(np.diff(lightness, axis=1))
        gy[1:, :] = np.abs(np.diff(lightness, axis=0))
        edge = np.clip(np.hypot(gx, gy) / 100.0, 0.0, 0.5)
        weights = 1.0 + edge
        weights /= weights.sum()
        rgb_parts.append(rgb.reshape(-1, 3))
        weight_parts.append(weights.reshape(-1))
        scale_parts.append(np.full(scale * scale, scale, dtype=np.int32))
        edge_parts.append(edge.reshape(-1))
    combined_rgb = np.concatenate(rgb_parts)
    return MultiscaleSamples(
        rgb=combined_rgb,
        lab=srgb_to_lab(combined_rgb),
        weights=np.concatenate(weight_parts),
        scales=np.concatenate(scale_parts),
        edge_weights=np.concatenate(edge_parts),
    )


def select_shared_palette(
    sample_lab: NDArray[np.number],
    weights: NDArray[np.number],
    catalog_lab: NDArray[np.number],
    *,
    minimum_colors: int = 32,
    maximum_colors: int = 48,
    relative_improvement_threshold: float = 0.01,
) -> list[int]:
    """Greedily choose a deterministic shared palette minimizing weighted Delta E."""
    catalog = np.asarray(catalog_lab, dtype=np.float64)
    if not 1 <= minimum_colors <= maximum_colors <= len(catalog):
        raise ValueError("Palette limits must fit inside the catalog.")
    sample_values = np.asarray(sample_lab, dtype=np.float64)
    normalized_weights = np.asarray(weights, dtype=np.float64)
    if len(sample_values) != len(normalized_weights):
        raise ValueError("Sample colors and weights must have matching lengths.")
    sample_values, normalized_weights = _merge_duplicate_samples(sample_values, normalized_weights)
    normalized_weights = normalized_weights / normalized_weights.sum()
    distances = pairwise_ciede2000(sample_values, catalog)
    singleton_errors = normalized_weights @ distances
    selected = [int(np.argmin(singleton_errors))]
    selected_mask = np.zeros(len(catalog), dtype=bool)
    selected_mask[selected[0]] = True
    best_distances = distances[:, selected[0]].copy()
    current_error = float(normalized_weights @ best_distances)

    while len(selected) < maximum_colors:
        candidate_errors = normalized_weights @ np.minimum(best_distances[:, None], distances)
        candidate_errors[selected_mask] = np.inf
        next_index = int(np.argmin(candidate_errors))
        next_error = float(candidate_errors[next_index])
        improvement = 0.0 if current_error <= 0 else (current_error - next_error) / current_error
        if len(selected) >= minimum_colors and improvement < relative_improvement_threshold:
            break
        selected.append(next_index)
        selected_mask[next_index] = True
        best_distances = np.minimum(best_distances, distances[:, next_index])
        current_error = next_error
    return selected


def _merge_duplicate_samples(
    sample_lab: NDArray[np.float64],
    weights: NDArray[np.float64],
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    if len(sample_lab) == 0:
        return sample_lab, weights
    unique_lab, inverse = np.unique(sample_lab, axis=0, return_inverse=True)
    if len(unique_lab) == len(sample_lab):
        return sample_lab, weights
    return unique_lab, np.bincount(inverse, weights=weights, minlength=len(unique_lab)).astype(np.float64)


def build_palette_mapping(
    image: Image.Image,
    palette_rgb: NDArray[np.number],
    *,
    candidate_count: int = 4,
) -> PaletteMapping:
    """Build direct nearest-color mapping plus stable Top-K candidates."""
    rgb = np.asarray(image.convert("RGB"), dtype=np.uint8)
    palette = np.asarray(palette_rgb, dtype=np.uint8)
    if palette.ndim != 2 or palette.shape[1] != 3 or len(palette) == 0:
        raise ValueError("Palette must contain at least one RGB color.")
    if candidate_count < 1:
        raise ValueError("candidate_count must be positive.")
    source_lab = srgb_to_lab(rgb)
    palette_lab = srgb_to_lab(palette)
    flat_distances = pairwise_ciede2000(source_lab.reshape(-1, 3), palette_lab)
    count = min(candidate_count, len(palette))
    candidate_indices = np.argsort(flat_distances, axis=1, kind="stable")[:, :count].astype(np.int32)
    candidate_distances = np.take_along_axis(flat_distances, candidate_indices, axis=1)
    shape = (*rgb.shape[:2], count)
    return PaletteMapping(
        indices=candidate_indices[:, 0].reshape(rgb.shape[:2]),
        source_lab=source_lab,
        palette_lab=palette_lab,
        candidate_indices=candidate_indices.reshape(shape),
        candidate_distances=candidate_distances.reshape(shape),
    )


def map_image_to_palette(image: Image.Image, palette_rgb: NDArray[np.number]) -> NDArray[np.int32]:
    """Map each image pixel directly to the nearest selected Lab color without dithering."""
    return build_palette_mapping(image, palette_rgb).indices
