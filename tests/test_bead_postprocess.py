"""Exercise edge-aware bead-grid refinement and quality constraints."""

from __future__ import annotations

import unittest

import numpy as np
from PIL import Image

from src.tools.bead_colors import ciede2000
from src.tools.bead_palette import build_palette_mapping
from src.tools.bead_postprocess import BeadRefinementProfile, refine_bead_grid


class BeadPostprocessTests(unittest.TestCase):
    def test_mapping_limits_each_cell_to_deterministic_top_four_candidates(self) -> None:
        image = Image.new("RGB", (1, 1), (100, 100, 100))
        palette = np.array([
            [0, 0, 0],
            [80, 80, 80],
            [90, 90, 90],
            [110, 110, 110],
            [120, 120, 120],
            [255, 255, 255],
        ], dtype=np.uint8)

        mapping = build_palette_mapping(image, palette)

        self.assertEqual(mapping.candidate_indices.shape, (1, 1, 4))
        self.assertEqual(mapping.candidate_indices[0, 0].tolist(), [2, 3, 1, 4])
        self.assertEqual(mapping.indices.tolist(), [[2]])

    def test_flat_regions_form_larger_blocks_without_crossing_a_strong_edge(self) -> None:
        image = Image.new("RGB", (8, 6))
        pixels = image.load()
        for y in range(6):
            for x in range(8):
                base = 76 if x < 4 else 206
                jitter = 7 if (x + y) % 2 else -7
                pixels[x, y] = (base + jitter,) * 3
        palette = np.array([
            [68, 68, 68],
            [84, 84, 84],
            [198, 198, 198],
            [214, 214, 214],
            [140, 140, 140],
        ], dtype=np.uint8)
        mapping = build_palette_mapping(image, palette)

        result = refine_bead_grid(mapping, BeadRefinementProfile())

        self.assertLess(_color_jumps(result.indices), _color_jumps(mapping.indices))
        self.assertTrue(np.all(result.indices[:, :4] < 2))
        self.assertTrue(np.all((result.indices[:, 4:] >= 2) & (result.indices[:, 4:] <= 3)))

    def test_two_rounds_are_synchronous_and_deterministic(self) -> None:
        image = Image.new("RGB", (7, 1))
        image.putdata([(80, 80, 80), (86, 86, 86), (80, 80, 80), (86, 86, 86), (80, 80, 80), (86, 86, 86), (80, 80, 80)])
        palette = np.array([[80, 80, 80], [86, 86, 86], [180, 180, 180], [220, 220, 220]], dtype=np.uint8)
        mapping = build_palette_mapping(image, palette)
        profile = BeadRefinementProfile(island_max_size=0)

        first = refine_bead_grid(mapping, profile)
        second = refine_bead_grid(mapping, profile)

        self.assertEqual(len(first.round_change_counts), 2)
        self.assertGreater(first.round_change_counts[0], 0)
        self.assertEqual(first.indices.tolist(), second.indices.tolist())
        self.assertEqual(first.round_change_counts, second.round_change_counts)

    def test_equal_refinement_costs_resolve_by_candidate_order(self) -> None:
        image = Image.new("RGB", (3, 1), (83, 83, 83))
        palette = np.array([[80, 80, 80], [86, 86, 86], [180, 180, 180], [220, 220, 220]], dtype=np.uint8)
        mapping = build_palette_mapping(image, palette)
        tied_mapping = type(mapping)(
            indices=mapping.indices,
            source_lab=mapping.source_lab,
            palette_lab=mapping.palette_lab,
            candidate_indices=mapping.candidate_indices,
            candidate_distances=np.zeros_like(mapping.candidate_distances),
        )

        result = refine_bead_grid(
            tied_mapping,
            BeadRefinementProfile(smoothing_rounds=1, continuity_weight=0, island_max_size=0),
        )

        np.testing.assert_array_equal(result.indices, mapping.candidate_indices[..., 0])

    def test_low_delta_island_merges_but_high_contrast_detail_survives(self) -> None:
        low_image = Image.new("RGB", (5, 5), (100, 100, 100))
        low_image.putpixel((2, 2), (112, 112, 112))
        low_palette = np.array([[100, 100, 100], [112, 112, 112], [160, 160, 160], [220, 220, 220]], dtype=np.uint8)
        low_mapping = build_palette_mapping(low_image, low_palette)

        low_result = refine_bead_grid(low_mapping, BeadRefinementProfile(smoothing_rounds=0))

        self.assertEqual(low_result.indices[2, 2], 0)
        self.assertEqual(low_result.island_changes, 1)

        high_image = Image.new("RGB", (5, 5), (235, 235, 235))
        high_image.putpixel((2, 2), (20, 20, 20))
        high_palette = np.array([[235, 235, 235], [20, 20, 20], [130, 130, 130], [180, 180, 180]], dtype=np.uint8)
        high_mapping = build_palette_mapping(high_image, high_palette)

        high_result = refine_bead_grid(high_mapping, BeadRefinementProfile(smoothing_rounds=0))

        self.assertEqual(high_result.indices[2, 2], 1)
        self.assertEqual(high_result.island_changes, 0)

    def test_quality_gate_reduces_isolation_and_jumps_without_large_error_growth(self) -> None:
        image = Image.new("RGB", (24, 24))
        pixels = image.load()
        for y in range(24):
            for x in range(24):
                base = 72 if x < 12 else 188
                jitter = ((x * 17 + y * 11) % 17) - 8
                pixels[x, y] = (base + jitter, base + jitter, base + jitter)
        palette = np.array([
            [64, 64, 64],
            [76, 76, 76],
            [88, 88, 88],
            [176, 176, 176],
            [188, 188, 188],
            [200, 200, 200],
        ], dtype=np.uint8)
        mapping = build_palette_mapping(image, palette)

        result = refine_bead_grid(mapping, BeadRefinementProfile())

        before_islands = _isolated_cells(mapping.indices)
        after_islands = _isolated_cells(result.indices)
        self.assertLessEqual(after_islands, before_islands * 0.70)
        self.assertLessEqual(_color_jumps(result.indices), _color_jumps(mapping.indices) * 0.90)
        before_error = _mean_error(mapping, mapping.indices)
        after_error = _mean_error(mapping, result.indices)
        self.assertLessEqual(after_error, before_error * 1.10)


def _color_jumps(grid: np.ndarray) -> int:
    return int(np.count_nonzero(grid[:, 1:] != grid[:, :-1]) + np.count_nonzero(grid[1:, :] != grid[:-1, :]))


def _isolated_cells(grid: np.ndarray) -> int:
    same = np.zeros(grid.shape, dtype=np.int32)
    same[:, 1:] += grid[:, 1:] == grid[:, :-1]
    same[:, :-1] += grid[:, :-1] == grid[:, 1:]
    same[1:, :] += grid[1:, :] == grid[:-1, :]
    same[:-1, :] += grid[:-1, :] == grid[1:, :]
    return int(np.count_nonzero(same == 0))


def _mean_error(mapping: object, grid: np.ndarray) -> float:
    source_lab = mapping.source_lab
    palette_lab = mapping.palette_lab
    return float(np.mean(ciede2000(source_lab, palette_lab[grid])))


if __name__ == "__main__":
    unittest.main()
