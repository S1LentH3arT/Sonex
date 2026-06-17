"""Read bead rendering configuration from Sonex's JSON config."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from src.log import sonex_home

SUPPORTED_BEAD_BRANDS = frozenset({"hama", "perler", "mard"})


class InvalidBeadBrand(ValueError):
    """Raised when an explicitly configured bead brand is unsupported."""


def bead_config_path() -> Path:
    """Return the shared Sonex JSON configuration path."""
    return Path(os.getenv("SONEX_CONFIG_PATH") or (sonex_home() / "thinking.json")).expanduser()


def load_bead_brand(config_path: Path | None = None) -> str:
    """Return the configured bead brand, defaulting to Hama when absent."""
    path = config_path or bead_config_path()
    try:
        payload: Any = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return "hama"
    except (OSError, json.JSONDecodeError) as exc:
        raise InvalidBeadBrand(f"Unable to read bead configuration: {exc}") from exc

    if not isinstance(payload, dict):
        raise InvalidBeadBrand("Sonex configuration must be a JSON object.")
    beads = payload.get("beads")
    if beads is None:
        return "hama"
    if not isinstance(beads, dict):
        raise InvalidBeadBrand("beads configuration must be a JSON object.")
    brand = beads.get("brand", "hama")
    if not isinstance(brand, str) or brand not in SUPPORTED_BEAD_BRANDS:
        raise InvalidBeadBrand("beads.brand must be one of: hama, perler, mard.")
    return brand
