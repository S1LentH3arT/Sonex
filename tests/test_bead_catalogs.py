"""Validate bundled Hama and Perler bead catalogs."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.tools.bead_catalogs import CatalogValidationError, load_bead_catalog, validate_catalog_data
from src.tools.bead_config import InvalidBeadBrand, load_bead_brand


class BeadCatalogTests(unittest.TestCase):
    def test_bundled_catalogs_are_auditable_standard_opaque_five_mm_lines(self) -> None:
        expected = {"hama": ("Hama Midi", 65), "perler": ("Perler Classic", 102)}

        for brand, (product_line, minimum_count) in expected.items():
            catalog = load_bead_catalog(brand)

            self.assertEqual(catalog.brand, brand)
            self.assertEqual(catalog.product_line, product_line)
            self.assertEqual(catalog.diameter_mm, 5.0)
            self.assertGreaterEqual(len(catalog.colors), minimum_count)
            self.assertEqual(len({color.code for color in catalog.colors}), len(catalog.colors))
            self.assertTrue(all(color.material == "standard_opaque" for color in catalog.colors))
            self.assertTrue(all(color.identity_source_id and color.rgb_source_id for color in catalog.colors))
            self.assertTrue(all(all(0 <= channel <= 255 for channel in color.rgb) for color in catalog.colors))
            self.assertEqual(catalog.license, "MIT")
            self.assertIn("approximation", catalog.calibration_disclaimer.lower())

    def test_catalog_validation_rejects_duplicate_codes_special_material_and_unknown_license(self) -> None:
        base = {
            "schema_version": 1,
            "brand": "hama",
            "product_line": "Hama Midi",
            "diameter_mm": 5,
            "version": "test",
            "license": "MIT",
            "retrieved_at": "2026-06-13",
            "calibration_disclaimer": "Community RGB approximation.",
            "sources": {
                "official": {"url": "https://hama.dk/", "license": "reference-only"},
                "rgb": {"url": "https://example.test/colors", "license": "MIT"},
            },
            "colors": [
                {
                    "code": "H01",
                    "name": "White",
                    "rgb": [255, 255, 255],
                    "material": "standard_opaque",
                    "identity_source_id": "official",
                    "rgb_source_id": "rgb",
                }
            ],
        }

        for mutate in (
            lambda data: data["colors"].append(dict(data["colors"][0])),
            lambda data: data["colors"][0].update(material="transparent"),
            lambda data: data.update(license="unknown"),
            lambda data: data["colors"][0].update(rgb=[256, 0, 0]),
            lambda data: data["colors"][0].update(rgb_source_id="missing"),
        ):
            payload = json.loads(json.dumps(base))
            mutate(payload)
            with self.assertRaises(CatalogValidationError):
                validate_catalog_data(payload)

    def test_brand_config_defaults_to_hama_and_rejects_explicit_invalid_value(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            config_path = Path(tempdir) / "thinking.json"
            self.assertEqual(load_bead_brand(config_path), "hama")

            config_path.write_text(json.dumps({"beads": {"brand": "perler"}}), encoding="utf-8")
            self.assertEqual(load_bead_brand(config_path), "perler")

            config_path.write_text(json.dumps({"beads": {"brand": "generic"}}), encoding="utf-8")
            with self.assertRaises(InvalidBeadBrand):
                load_bead_brand(config_path)

    def test_catalog_resources_load_from_importlib_package_data(self) -> None:
        with patch("src.tools.bead_catalogs.files") as package_files:
            package_files.return_value.joinpath.return_value.read_text.return_value = json.dumps({})
            with self.assertRaises(CatalogValidationError):
                load_bead_catalog("hama")
            package_files.assert_called_once_with("src.tools.bead_catalog_data")


if __name__ == "__main__":
    unittest.main()
