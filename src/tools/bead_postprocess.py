"""Refine nearest-color bead grids while preserving source-image edges."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray

from src.tools.bead_colors import ciede2000
from src.tools.bead_palette import PaletteMapping


@dataclass(frozen=True)
class BeadRefinementProfile:
    """Define the fixed construction-readability refinement parameters."""

    candidate_count: int = 6
    smoothing_rounds: int = 2
    continuity_weight: float = 2.0
    edge_scale: float = 10.0
    island_max_size: int = 2
    island_merge_delta_e_max: float = 14.0

    def as_dict(self) -> dict[str, int | float]:
        """Return a stable cache representation."""
        return {
            "candidate_count": self.candidate_count,
            "smoothing_rounds": self.smoothing_rounds,
            "continuity_weight": self.continuity_weight,
            "edge_scale": self.edge_scale,
            "island_max_size": self.island_max_size,
            "island_merge_delta_e_max": self.island_merge_delta_e_max,
        }


@dataclass(frozen=True)
class BeadRefinementResult:
    """Return the refined grid and cache-safe generation diagnostics."""

    indices: NDArray[np.int32]
    round_change_counts: tuple[int, ...]
    island_changes: int

    def diagnostics(self) -> dict[str, Any]:
        """Return JSON-compatible per-variant diagnostics."""
        return {
            "round_change_counts": list(self.round_change_counts),
            "island_changes": self.island_changes,
            "total_changes": int(sum(self.round_change_counts) + self.island_changes),
        }


def refine_bead_grid(
    mapping: PaletteMapping,
    profile: BeadRefinementProfile = BeadRefinementProfile(),
) -> BeadRefinementResult:
    """Apply synchronous edge-aware smoothing and bounded island cleanup."""
    _validate_mapping(mapping, profile)
    grid = mapping.indices.copy()
    affinities = _neighbor_affinities(mapping.source_lab, profile.edge_scale)
    round_changes: list[int] = []
    previous_previous: NDArray[np.int32] | None = None

    for _ in range(profile.smoothing_rounds):
        updated = _smooth_round(mapping, grid, affinities, profile.continuity_weight)
        if previous_previous is not None and np.array_equal(updated, previous_previous):
            round_changes.append(0)
            break
        round_changes.append(int(np.count_nonzero(updated != grid)))
        previous_previous = grid
        grid = updated

    while len(round_changes) < profile.smoothing_rounds:
        round_changes.append(0)

    island_changes = 0
    if profile.island_max_size > 0:
        grid, island_changes = _merge_small_islands(mapping, grid, profile)
    return BeadRefinementResult(
        indices=grid.astype(np.int32, copy=False),
        round_change_counts=tuple(round_changes),
        island_changes=island_changes,
    )


def _validate_mapping(mapping: PaletteMapping, profile: BeadRefinementProfile) -> None:
    if mapping.indices.ndim != 2:
        raise ValueError("Mapping grid must be two-dimensional.")
    if mapping.source_lab.shape != (*mapping.indices.shape, 3):
        raise ValueError("Source Lab grid does not match mapping dimensions.")
    if mapping.candidate_indices.shape[:2] != mapping.indices.shape:
        raise ValueError("Candidate grid does not match mapping dimensions.")
    if mapping.candidate_indices.shape != mapping.candidate_distances.shape:
        raise ValueError("Candidate indices and distances must have matching shapes.")
    if mapping.candidate_indices.shape[2] > profile.candidate_count:
        raise ValueError("Mapping exceeds the configured candidate limit.")
    if profile.smoothing_rounds < 0 or profile.island_max_size < 0:
        raise ValueError("Round and island limits cannot be negative.")
    if profile.edge_scale <= 0 or profile.continuity_weight < 0:
        raise ValueError("Edge scale must be positive and continuity weight non-negative.")


def _neighbor_affinities(source_lab: NDArray[np.float64], edge_scale: float) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    horizontal_delta = ciede2000(source_lab[:, 1:], source_lab[:, :-1])
    vertical_delta = ciede2000(source_lab[1:, :], source_lab[:-1, :])
    return np.exp(-((horizontal_delta / edge_scale) ** 2)), np.exp(-((vertical_delta / edge_scale) ** 2))


def _smooth_round(
    mapping: PaletteMapping,
    grid: NDArray[np.int32],
    affinities: tuple[NDArray[np.float64], NDArray[np.float64]],
    continuity_weight: float,
) -> NDArray[np.int32]:
    candidates = mapping.candidate_indices
    costs = mapping.candidate_distances.copy()
    horizontal, vertical = affinities

    costs[:, 1:] += continuity_weight * horizontal[..., None] * (candidates[:, 1:] != grid[:, :-1, None])
    costs[:, :-1] += continuity_weight * horizontal[..., None] * (candidates[:, :-1] != grid[:, 1:, None])
    costs[1:, :] += continuity_weight * vertical[..., None] * (candidates[1:, :] != grid[:-1, :, None])
    costs[:-1, :] += continuity_weight * vertical[..., None] * (candidates[:-1, :] != grid[1:, :, None])

    choices = np.argmin(costs, axis=2)
    return np.take_along_axis(candidates, choices[..., None], axis=2)[..., 0].astype(np.int32)


def _merge_small_islands(
    mapping: PaletteMapping,
    grid: NDArray[np.int32],
    profile: BeadRefinementProfile,
) -> tuple[NDArray[np.int32], int]:
    refined = grid.copy()
    height, width = refined.shape
    visited = np.zeros(refined.shape, dtype=bool)
    changes = 0

    for row in range(height):
        for column in range(width):
            if visited[row, column]:
                continue
            color = int(refined[row, column])
            component = _component(refined, visited, row, column, color)
            if len(component) > profile.island_max_size:
                continue
            neighbors = _boundary_colors(refined, component, color)
            for target, _count in sorted(neighbors.items(), key=lambda item: (-item[1], item[0])):
                delta = float(ciede2000(mapping.palette_lab[color], mapping.palette_lab[target]))
                if delta > profile.island_merge_delta_e_max:
                    continue
                if not all(target in mapping.candidate_indices[cell_row, cell_column] for cell_row, cell_column in component):
                    continue
                for cell_row, cell_column in component:
                    refined[cell_row, cell_column] = target
                changes += len(component)
                break
    return refined, changes


def _component(
    grid: NDArray[np.int32],
    visited: NDArray[np.bool_],
    start_row: int,
    start_column: int,
    color: int,
) -> list[tuple[int, int]]:
    height, width = grid.shape
    stack = [(start_row, start_column)]
    visited[start_row, start_column] = True
    cells: list[tuple[int, int]] = []
    while stack:
        row, column = stack.pop()
        cells.append((row, column))
        for next_row, next_column in ((row - 1, column), (row + 1, column), (row, column - 1), (row, column + 1)):
            if not (0 <= next_row < height and 0 <= next_column < width):
                continue
            if visited[next_row, next_column] or int(grid[next_row, next_column]) != color:
                continue
            visited[next_row, next_column] = True
            stack.append((next_row, next_column))
    return cells


def _boundary_colors(
    grid: NDArray[np.int32],
    component: list[tuple[int, int]],
    color: int,
) -> dict[int, int]:
    height, width = grid.shape
    counts: dict[int, int] = {}
    for row, column in component:
        for next_row, next_column in ((row - 1, column), (row + 1, column), (row, column - 1), (row, column + 1)):
            if not (0 <= next_row < height and 0 <= next_column < width):
                continue
            target = int(grid[next_row, next_column])
            if target != color:
                counts[target] = counts.get(target, 0) + 1
    return counts
