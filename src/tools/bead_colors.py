"""Vectorized D65 sRGB, Lab, and CIEDE2000 color science."""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

FloatArray = NDArray[np.float64]


def srgb_to_lab(rgb: NDArray[np.number]) -> FloatArray:
    """Convert 8-bit D65 sRGB values to CIE Lab."""
    values = np.asarray(rgb, dtype=np.float64) / 255.0
    linear = np.where(values <= 0.04045, values / 12.92, ((values + 0.055) / 1.055) ** 2.4)
    xyz = linear @ np.array([
        [0.4124564, 0.3575761, 0.1804375],
        [0.2126729, 0.7151522, 0.0721750],
        [0.0193339, 0.1191920, 0.9503041],
    ]).T
    xyz /= np.array([0.95047, 1.0, 1.08883])
    delta = 6.0 / 29.0
    f = np.where(xyz > delta**3, np.cbrt(xyz), xyz / (3 * delta**2) + 4.0 / 29.0)
    return np.stack((116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])), axis=-1)


def ciede2000(left: NDArray[np.number], right: NDArray[np.number]) -> FloatArray:
    """Compute elementwise CIEDE2000 distance for broadcast-compatible Lab arrays."""
    lab1 = np.asarray(left, dtype=np.float64)
    lab2 = np.asarray(right, dtype=np.float64)
    l1, a1, b1 = np.moveaxis(lab1, -1, 0)
    l2, a2, b2 = np.moveaxis(lab2, -1, 0)
    c1 = np.hypot(a1, b1)
    c2 = np.hypot(a2, b2)
    c_bar = (c1 + c2) / 2
    g = 0.5 * (1 - np.sqrt((c_bar**7) / (c_bar**7 + 25.0**7)))
    ap1 = (1 + g) * a1
    ap2 = (1 + g) * a2
    cp1 = np.hypot(ap1, b1)
    cp2 = np.hypot(ap2, b2)
    hp1 = np.mod(np.degrees(np.arctan2(b1, ap1)), 360.0)
    hp2 = np.mod(np.degrees(np.arctan2(b2, ap2)), 360.0)
    hp1 = np.where(cp1 == 0, 0.0, hp1)
    hp2 = np.where(cp2 == 0, 0.0, hp2)

    dl = l2 - l1
    dc = cp2 - cp1
    dh_raw = hp2 - hp1
    dh = np.where(
        cp1 * cp2 == 0,
        0.0,
        np.where(dh_raw > 180, dh_raw - 360, np.where(dh_raw < -180, dh_raw + 360, dh_raw)),
    )
    dh_term = 2 * np.sqrt(cp1 * cp2) * np.sin(np.radians(dh / 2))
    l_bar = (l1 + l2) / 2
    cp_bar = (cp1 + cp2) / 2
    hp_sum = hp1 + hp2
    hp_bar = np.where(
        cp1 * cp2 == 0,
        hp_sum,
        np.where(np.abs(hp1 - hp2) <= 180, hp_sum / 2, np.where(hp_sum < 360, (hp_sum + 360) / 2, (hp_sum - 360) / 2)),
    )
    t = (
        1
        - 0.17 * np.cos(np.radians(hp_bar - 30))
        + 0.24 * np.cos(np.radians(2 * hp_bar))
        + 0.32 * np.cos(np.radians(3 * hp_bar + 6))
        - 0.20 * np.cos(np.radians(4 * hp_bar - 63))
    )
    sl = 1 + 0.015 * (l_bar - 50) ** 2 / np.sqrt(20 + (l_bar - 50) ** 2)
    sc = 1 + 0.045 * cp_bar
    sh = 1 + 0.015 * cp_bar * t
    delta_theta = 30 * np.exp(-((hp_bar - 275) / 25) ** 2)
    rc = 2 * np.sqrt((cp_bar**7) / (cp_bar**7 + 25.0**7))
    rt = -rc * np.sin(np.radians(2 * delta_theta))
    dl_term = dl / sl
    dc_term = dc / sc
    dh_scaled = dh_term / sh
    return np.sqrt(np.maximum(0.0, dl_term**2 + dc_term**2 + dh_scaled**2 + rt * dc_term * dh_scaled))


def pairwise_ciede2000(left: NDArray[np.number], right: NDArray[np.number]) -> FloatArray:
    """Return all CIEDE2000 distances between two Lab collections."""
    return ciede2000(np.asarray(left)[:, None, :], np.asarray(right)[None, :, :])
