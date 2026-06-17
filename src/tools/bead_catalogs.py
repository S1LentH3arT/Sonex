"""Load and validate versioned physical bead color catalogs."""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib.resources import files
from typing import Any

from src.tools.bead_config import SUPPORTED_BEAD_BRANDS

ALLOWED_CATALOG_LICENSES = frozenset({"MIT"})


class CatalogValidationError(ValueError):
    """Raised when bundled catalog data is incomplete or unsafe to publish."""


@dataclass(frozen=True)
class BeadColor:
    """Describe one standard opaque physical bead color."""

    code: str
    name: str
    rgb: tuple[int, int, int]
    material: str
    identity_source_id: str
    rgb_source_id: str

    @property
    def hex(self) -> str:
        """Return the catalog RGB approximation as a CSS hex color."""
        return "#" + "".join(f"{channel:02x}" for channel in self.rgb)


@dataclass(frozen=True)
class BeadCatalog:
    """Represent an auditable 5 mm brand catalog."""

    brand: str
    product_line: str
    diameter_mm: float
    version: str
    license: str
    retrieved_at: str
    calibration_disclaimer: str
    sources: dict[str, dict[str, str]]
    colors: tuple[BeadColor, ...]


def _required_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CatalogValidationError(f"Catalog field {field} must be non-empty text.")
    return value


def validate_catalog_data(data: Any) -> BeadCatalog:
    """Validate raw catalog JSON and return its immutable runtime model."""
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise CatalogValidationError("Unsupported bead catalog schema.")
    brand = _required_text(data.get("brand"), "brand")
    if brand not in SUPPORTED_BEAD_BRANDS:
        raise CatalogValidationError(f"Unsupported catalog brand: {brand}")
    license_name = _required_text(data.get("license"), "license")
    if license_name not in ALLOWED_CATALOG_LICENSES:
        raise CatalogValidationError(f"Catalog license is not approved: {license_name}")
    diameter = data.get("diameter_mm")
    if not isinstance(diameter, (int, float)) or float(diameter) != 5.0:
        raise CatalogValidationError("Catalog must describe a 5 mm product line.")
    sources = data.get("sources")
    if not isinstance(sources, dict) or not sources:
        raise CatalogValidationError("Catalog sources are required.")
    for source_id, source in sources.items():
        if not isinstance(source_id, str) or not isinstance(source, dict):
            raise CatalogValidationError("Catalog source entries are invalid.")
        _required_text(source.get("url"), f"sources.{source_id}.url")
        _required_text(source.get("license"), f"sources.{source_id}.license")

    raw_colors = data.get("colors")
    if not isinstance(raw_colors, list) or not raw_colors:
        raise CatalogValidationError("Catalog must contain colors.")
    colors: list[BeadColor] = []
    seen_codes: set[str] = set()
    for index, raw in enumerate(raw_colors):
        if not isinstance(raw, dict):
            raise CatalogValidationError(f"Color {index} must be an object.")
        code = _required_text(raw.get("code"), f"colors.{index}.code")
        if code in seen_codes:
            raise CatalogValidationError(f"Duplicate bead code: {code}")
        seen_codes.add(code)
        material = _required_text(raw.get("material"), f"colors.{index}.material")
        if material != "standard_opaque":
            raise CatalogValidationError(f"Unsupported bead material: {material}")
        rgb = raw.get("rgb")
        if (
            not isinstance(rgb, list)
            or len(rgb) != 3
            or any(
                not isinstance(channel, int)
                or isinstance(channel, bool)
                or not 0 <= channel <= 255
                for channel in rgb
            )
        ):
            raise CatalogValidationError(f"Invalid RGB value for {code}")
        identity_source_id = _required_text(raw.get("identity_source_id"), f"colors.{index}.identity_source_id")
        rgb_source_id = _required_text(raw.get("rgb_source_id"), f"colors.{index}.rgb_source_id")
        if identity_source_id not in sources or rgb_source_id not in sources:
            raise CatalogValidationError(f"Unknown source reference for {code}")
        colors.append(BeadColor(
            code=code,
            name=_required_text(raw.get("name"), f"colors.{index}.name"),
            rgb=(rgb[0], rgb[1], rgb[2]),
            material=material,
            identity_source_id=identity_source_id,
            rgb_source_id=rgb_source_id,
        ))

    return BeadCatalog(
        brand=brand,
        product_line=_required_text(data.get("product_line"), "product_line"),
        diameter_mm=float(diameter),
        version=_required_text(data.get("version"), "version"),
        license=license_name,
        retrieved_at=_required_text(data.get("retrieved_at"), "retrieved_at"),
        calibration_disclaimer=_required_text(data.get("calibration_disclaimer"), "calibration_disclaimer"),
        sources={str(key): {str(k): str(v) for k, v in value.items()} for key, value in sources.items()},
        colors=tuple(colors),
    )


def load_bead_catalog(brand: str) -> BeadCatalog:
    """Load a bundled, validated physical bead catalog resource."""
    if brand not in SUPPORTED_BEAD_BRANDS:
        raise CatalogValidationError(f"Unsupported catalog brand: {brand}")
    resource = files("src.tools.bead_catalog_data").joinpath(f"{brand}.json")
    try:
        data = json.loads(resource.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CatalogValidationError(f"Unable to load {brand} catalog: {exc}") from exc
    return validate_catalog_data(data)
