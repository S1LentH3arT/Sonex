"""Build validated Sonex bead catalog resources from pinned MIT CSV inputs."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from src.tools.bead_catalogs import validate_catalog_data

SPECIAL_MATERIAL_TERMS = (
    "transparent", "translucent", "clear", "neon", "fluorescent",
    "glow", "gold", "silver", "bronze", "pearl", "glitter",
)

CATALOGS = {
    "hama": {
        "product_line": "Hama Midi",
        "official_url": "https://hama.dk/",
        "csv_name": "hama.csv",
    },
    "perler": {
        "product_line": "Perler Classic",
        "official_url": "https://perler.com/",
        "csv_name": "perler.csv",
    },
}


def build_catalog(brand: str, csv_path: Path) -> dict[str, object]:
    """Convert one pinned beadcolors CSV into Sonex's auditable schema."""
    colors = []
    with csv_path.open(newline="", encoding="utf-8") as handle:
        for code, name, red, green, blue, contributor in csv.reader(handle):
            if any(term in name.lower() for term in SPECIAL_MATERIAL_TERMS):
                continue
            colors.append({
                "code": code,
                "name": name,
                "rgb": [int(red), int(green), int(blue)],
                "material": "standard_opaque",
                "identity_source_id": "brand_reference",
                "rgb_source_id": "beadcolors_mit",
                "rgb_contributor": contributor,
            })
    details = CATALOGS[brand]
    return {
        "schema_version": 1,
        "brand": brand,
        "product_line": details["product_line"],
        "diameter_mm": 5,
        "version": "beadcolors-29229889-2026-06-13",
        "license": "MIT",
        "retrieved_at": "2026-06-13",
        "calibration_disclaimer": (
            "Community-maintained sRGB approximation; not official brand colorimetry "
            "or measured calibration data."
        ),
        "sources": {
            "brand_reference": {
                "url": details["official_url"],
                "license": "reference-only",
                "role": "brand identity and product-line reference",
            },
            "beadcolors_mit": {
                "url": "https://github.com/maxcleme/beadcolors/tree/29229889daab404fb30531d4bb785fd73f7f58e3",
                "license": "MIT",
                "role": "community color codes, names, and sRGB approximations",
            },
        },
        "colors": colors,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for brand, details in CATALOGS.items():
        payload = build_catalog(brand, args.input_dir / str(details["csv_name"]))
        validate_catalog_data(payload)
        (args.output_dir / f"{brand}.json").write_text(
            json.dumps(payload, ensure_ascii=True, indent=2) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
