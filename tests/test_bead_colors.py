"""Exercise Lab conversion, CIEDE2000, and adaptive palette selection."""

from __future__ import annotations

import unittest

import numpy as np
from PIL import Image, ImageDraw

from src.tools.bead_catalogs import load_bead_catalog
from src.tools.bead_colors import ciede2000, pairwise_ciede2000, srgb_to_lab
from src.tools.bead_palette import (
    build_multiscale_samples,
    map_image_to_palette,
    select_shared_palette,
)


class BeadColorTests(unittest.TestCase):
    def test_srgb_to_lab_matches_d65_reference_colors(self) -> None:
        lab = srgb_to_lab(np.array([[255, 255, 255], [0, 0, 0], [255, 0, 0]], dtype=np.float64))
        np.testing.assert_allclose(lab[0], [100.0, 0.0, 0.0], atol=0.02)
        np.testing.assert_allclose(lab[1], [0.0, 0.0, 0.0], atol=0.02)
        np.testing.assert_allclose(lab[2], [53.2408, 80.0925, 67.2032], atol=0.03)

    def test_ciede2000_matches_published_sharma_reference_pairs(self) -> None:
        left = np.array([[50.0, 2.6772, -79.7751], [50.0, 3.1571, -77.2803]])
        right = np.array([[50.0, 0.0, -82.7485], [50.0, 0.0, -82.7485]])
        expected = np.array([2.0425, 2.8615])

        np.testing.assert_allclose(ciede2000(left, right), expected, atol=0.0001)
        matrix = pairwise_ciede2000(left, right)
        np.testing.assert_allclose(np.diag(matrix), expected, atol=0.0001)
        self.assertTrue(np.isfinite(matrix).all())
        self.assertTrue((matrix >= 0).all())

    def test_palette_selection_is_deterministic_uses_shared_32_to_72_colors_and_catalog_order_ties(self) -> None:
        sample_lab = np.repeat(np.array([[50.0, 0.0, 0.0]]), 40, axis=0)
        weights = np.ones(40)
        catalog_lab = np.vstack([np.array([[50.0, 0.0, 0.0], [50.0, 0.0, 0.0]]), np.arange(72 * 3).reshape(72, 3)])

        first = select_shared_palette(sample_lab, weights, catalog_lab, minimum_colors=32, maximum_colors=72)
        second = select_shared_palette(sample_lab, weights, catalog_lab, minimum_colors=32, maximum_colors=72)

        self.assertEqual(first, second)
        self.assertEqual(len(first), 32)
        self.assertEqual(first[0], 0)
        self.assertNotIn(1, first[:1])

    def test_multiscale_samples_give_non_review_scales_equal_total_weight_and_add_bounded_edge_weight(self) -> None:
        image = Image.new("RGB", (96, 96), "#101010")
        for x in range(48, 96):
            for y in range(96):
                image.putpixel((x, y), (240, 240, 240))

        samples = build_multiscale_samples(image, scales=(32, 48, 64))

        totals = [samples.weights[samples.scales == scale].sum() for scale in (32, 48, 64)]
        np.testing.assert_allclose(totals, np.ones(3), atol=1e-12)
        self.assertLessEqual(samples.edge_weights.max(), 0.5)
        self.assertGreater(samples.edge_weights.max(), 0.0)

    def test_high_resolution_multiscale_samples_are_supported(self) -> None:
        image = Image.new("RGB", (192, 192), "#101010")
        for x in range(96, 192):
            for y in range(192):
                image.putpixel((x, y), (240, 240, 240))

        scales = (32, 48, 64, 80, 96, 128, 160, 192)
        samples = build_multiscale_samples(image, scales=scales)

        totals = {scale: samples.weights[samples.scales == scale].sum() for scale in scales}
        self.assertAlmostEqual(totals[80], 1.75)
        self.assertAlmostEqual(totals[96], 1.75)
        np.testing.assert_allclose(
            [total for scale, total in totals.items() if scale not in (80, 96)],
            np.ones(len(scales) - 2),
            atol=1e-12,
        )
        self.assertEqual(set(samples.scales.tolist()), set(scales))

    def test_high_resolution_samples_weight_80_and_96_review_sizes_more_heavily(self) -> None:
        image = Image.new("RGB", (192, 192), "#101010")
        scales = (32, 48, 64, 80, 96, 128, 160, 192)

        samples = build_multiscale_samples(image, scales=scales)

        totals = {scale: samples.weights[samples.scales == scale].sum() for scale in scales}
        self.assertGreater(totals[80], totals[64])
        self.assertGreater(totals[96], totals[64])
        self.assertAlmostEqual(sum(totals.values()), len(scales) + 1.5)

    def test_mapping_uses_only_selected_palette_without_dithering(self) -> None:
        image = Image.new("RGB", (3, 1))
        image.putdata([(250, 5, 5), (5, 250, 5), (5, 5, 250)])
        palette_rgb = np.array([[255, 0, 0], [0, 255, 0]], dtype=np.uint8)

        mapped = map_image_to_palette(image, palette_rgb)

        self.assertEqual(mapped.tolist(), [[0, 1, 0]])

    def test_lab_greedy_objective_is_no_worse_than_same_size_rgb_greedy_baseline(self) -> None:
        catalog = load_bead_catalog("hama")
        catalog_rgb = np.asarray([color.rgb for color in catalog.colors], dtype=np.float64)
        catalog_lab = srgb_to_lab(catalog_rgb)
        fixtures = [
            _portrait_fixture(),
            _gradient_fixture(),
            Image.new("RGB", (96, 96), "#080b16"),
            _saturated_fixture(),
        ]

        for image in fixtures:
            samples = build_multiscale_samples(image, scales=(32, 48))
            selected = select_shared_palette(
                samples.lab,
                samples.weights,
                catalog_lab,
                minimum_colors=32,
                maximum_colors=32,
            )
            rgb_selected = _select_rgb_baseline(samples.rgb, samples.weights, catalog_rgb, count=32)
            distances = pairwise_ciede2000(samples.lab, catalog_lab)
            lab_error = float(samples.weights @ distances[:, selected].min(axis=1))
            rgb_error = float(samples.weights @ distances[:, rgb_selected].min(axis=1))
            self.assertLessEqual(lab_error, rgb_error + 1e-9)


def _select_rgb_baseline(
    sample_rgb: np.ndarray,
    weights: np.ndarray,
    catalog_rgb: np.ndarray,
    *,
    count: int,
) -> list[int]:
    distances = np.sum((sample_rgb[:, None, :].astype(np.float64) - catalog_rgb[None, :, :]) ** 2, axis=2)
    selected: list[int] = []
    best = np.full(len(sample_rgb), np.inf)
    for _ in range(count):
        errors = np.full(len(catalog_rgb), np.inf)
        for index in range(len(catalog_rgb)):
            if index not in selected:
                errors[index] = float(weights @ np.minimum(best, distances[:, index]))
        next_index = int(np.argmin(errors))
        selected.append(next_index)
        best = np.minimum(best, distances[:, next_index])
    return selected


def _portrait_fixture() -> Image.Image:
    image = Image.new("RGB", (96, 96), "#2d4564")
    draw = ImageDraw.Draw(image)
    draw.ellipse((24, 12, 72, 68), fill="#d6a184")
    draw.rectangle((28, 60, 68, 96), fill="#6e2638")
    draw.ellipse((34, 34, 40, 40), fill="#2a1b1b")
    draw.ellipse((56, 34, 62, 40), fill="#2a1b1b")
    return image


def _gradient_fixture() -> Image.Image:
    image = Image.new("RGB", (96, 96))
    for x in range(96):
        color = (x * 255 // 95, 80, 255 - x * 255 // 95)
        for y in range(96):
            image.putpixel((x, y), color)
    return image


def _saturated_fixture() -> Image.Image:
    image = Image.new("RGB", (96, 96))
    colors = ("#ff0018", "#00f05a", "#005cff", "#ffdc00")
    draw = ImageDraw.Draw(image)
    for index, color in enumerate(colors):
        left = (index % 2) * 48
        top = (index // 2) * 48
        draw.rectangle((left, top, left + 47, top + 47), fill=color)
    return image


if __name__ == "__main__":
    unittest.main()
