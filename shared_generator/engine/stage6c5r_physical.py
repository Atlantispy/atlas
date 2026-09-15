"""Process-constrained 10 m terrain and drainage utilities for Stage 6C.5R.

The physical authority remains the approved 100 m terrain.  This module adds a
deterministic, parent-conserving 10 m analytical surface, a separate routing
surface, climate-forced flow accumulation, and review-only supporting drainage.
It never describes the resulting cells as surveyed 10 m evidence or the runoff
and widths as observations.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import heapq
import json
import math
from typing import Mapping, Sequence

import numpy as np
from algorithm_policy import use_optimized


METHOD_VERSION = "S6C5R_PHYSICAL_KERNEL_2.0.1_REGISTERED_FLOOD_REFERENCE"
CELL_SIZE_M = 10.0
PARENT_FACTOR = 10

D8 = (
    (-1, 0, 1.0),
    (-1, 1, math.sqrt(2.0)),
    (0, 1, 1.0),
    (1, 1, math.sqrt(2.0)),
    (1, 0, 1.0),
    (1, -1, math.sqrt(2.0)),
    (0, -1, 1.0),
    (-1, -1, math.sqrt(2.0)),
)

CLASS_CODE = {
    "none": 0,
    "generated_ephemeral": 1,
    "generated_intermittent": 2,
    "generated_perennial": 3,
    "tier1": 4,
    "tier2": 5,
    "major": 6,
    "titan": 7,
    "special": 8,
}

CLASS_PARAMETERS = {
    # The pilot freezes a one-metre *total* fine-conditioning budget.  These
    # are subtle valley-floor constraints, not attempts to manufacture banks
    # or channel depth from cartographic class.
    "tier1": {"depth_m": 0.12, "sigma_cells": 1.8, "max_extra_incision_m": 1.0},
    "tier2": {"depth_m": 0.20, "sigma_cells": 2.8, "max_extra_incision_m": 1.0},
    "major": {"depth_m": 0.32, "sigma_cells": 4.8, "max_extra_incision_m": 1.0},
    "titan": {"depth_m": 0.50, "sigma_cells": 7.5, "max_extra_incision_m": 1.0},
    "special": {"depth_m": 0.20, "sigma_cells": 3.0, "max_extra_incision_m": 1.0},
}


class PhysicalReconstructionError(RuntimeError):
    """Fail-closed physical reconstruction error."""


@dataclass(frozen=True)
class ChannelConstraint:
    feature_id: str
    route_class: str
    persistence: str
    path_cells: tuple[tuple[int, int], ...]
    contributing_area_prior_km2: float = 0.0
    boundary_inflow: bool = False
    source_kind: str = "current_vector"
    bed_elevations_m: tuple[float, ...] = ()
    vertical_control: str = "MODELLED_SEPARATE_CHANNEL_BED"
    receiver_id: str | None = None
    terrain_ceiling_reconciliation_allowed: bool = False


@dataclass(frozen=True)
class PhysicalRecipe:
    cell_size_m: float = CELL_SIZE_M
    parent_factor: int = PARENT_FACTOR
    parent_mean_tolerance_m: float = 0.0051
    # Strictly positive, but deliberately tiny: a wetland or very large river
    # may be almost flat.  The contract requires downstream order, not an
    # invented 0.2 m/km minimum gradient.
    minimum_channel_drop_m_per_cell: float = 0.0001
    maximum_parent_compensation_m: float = 1.0
    maximum_conditioning_delta_m: float = 1.0
    priority_flood_epsilon_m: float = 0.0001
    mfd_slope_exponent: float = 1.1
    generated_threshold_wet_km2: float = 0.30
    generated_threshold_dry_km2: float = 1.25
    wet_annual_runoff_mm: float = 700.0
    dry_annual_runoff_mm: float = 100.0
    status: str = "WORKING_PROPOSAL_REVIEW_ONLY_NOT_CANON"

    def identity(self) -> dict[str, object]:
        return {
            "kernel_method": METHOD_VERSION,
            "channel_class_parameters": CLASS_PARAMETERS,
            **asdict(self),
        }


@dataclass
class PhysicalContext:
    arrays: dict[str, np.ndarray]
    metrics: dict[str, object]
    lineage: dict[str, object]


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def array_digest(arrays: Mapping[str, np.ndarray]) -> str:
    digest = sha256()
    for name in sorted(arrays):
        value = np.ascontiguousarray(arrays[name])
        digest.update(canonical_json([name, value.dtype.str, list(value.shape)]).encode("utf-8"))
        digest.update(value.tobytes(order="C"))
    return digest.hexdigest()


def parent_block_means(array: np.ndarray, factor: int = PARENT_FACTOR) -> np.ndarray:
    rows, cols = array.shape
    if rows % factor or cols % factor:
        raise PhysicalReconstructionError("Fine grid is not aligned to complete parent blocks")
    return array.reshape(rows // factor, factor, cols // factor, factor).mean(axis=(1, 3))


def _deduplicate_path(path: Sequence[tuple[int, int]]) -> tuple[tuple[int, int], ...]:
    result: list[tuple[int, int]] = []
    for cell in path:
        item = (int(cell[0]), int(cell[1]))
        if not result or item != result[-1]:
            result.append(item)
    return tuple(result)


def _chamfer_distance_reference(mask: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Approximate Euclidean distance and nearest source index in cell units."""

    rows, cols = mask.shape
    distance = np.full((rows, cols), np.inf, dtype=np.float32)
    nearest = np.full((rows, cols), -1, dtype=np.int64)
    source_rows, source_cols = np.nonzero(mask)
    if not len(source_rows):
        return distance, nearest
    distance[source_rows, source_cols] = 0.0
    nearest[source_rows, source_cols] = source_rows.astype(np.int64) * cols + source_cols
    root2 = np.float32(math.sqrt(2.0))
    forward = ((-1, 0, 1.0), (0, -1, 1.0), (-1, -1, root2), (-1, 1, root2))
    backward = ((1, 0, 1.0), (0, 1, 1.0), (1, 1, root2), (1, -1, root2))
    for row in range(rows):
        for col in range(cols):
            for dr, dc, step in forward:
                rr, cc = row + dr, col + dc
                if 0 <= rr < rows and 0 <= cc < cols:
                    candidate = float(distance[rr, cc]) + float(step)
                    if candidate < float(distance[row, col]):
                        distance[row, col] = candidate
                        nearest[row, col] = nearest[rr, cc]
    for row in range(rows - 1, -1, -1):
        for col in range(cols - 1, -1, -1):
            for dr, dc, step in backward:
                rr, cc = row + dr, col + dc
                if 0 <= rr < rows and 0 <= cc < cols:
                    candidate = float(distance[rr, cc]) + float(step)
                    if candidate < float(distance[row, col]):
                        distance[row, col] = candidate
                        nearest[row, col] = nearest[rr, cc]
    return distance, nearest


def _chamfer_distance_wavefront(mask: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Evaluate the unchanged two-pass metric in dependency-safe wavefronts.

    Cells with the same ``2 * row + col`` do not depend on one another in
    the forward pass, including the up-right neighbour.  The reverse pass
    uses mirrored coordinates.  Each neighbour is still applied in the
    reference order, with a Float64 comparison followed by a Float32 store;
    equal-distance source selection and rounding therefore remain unchanged.
    """

    rows, cols = mask.shape
    distance = np.full((rows, cols), np.inf, dtype=np.float32)
    nearest = np.full((rows, cols), -1, dtype=np.int64)
    source_rows, source_cols = np.nonzero(mask)
    if not len(source_rows):
        return distance, nearest
    distance[source_rows, source_cols] = 0.0
    nearest[source_rows, source_cols] = source_rows.astype(np.int64) * cols + source_cols
    root2 = np.float32(math.sqrt(2.0))
    neighbours = ((-1, 0, 1.0), (0, -1, 1.0), (-1, -1, root2), (-1, 1, root2))
    for reverse in (False, True):
        # Views mirror the reverse scan, including nearest-source identities.
        current_distance = distance[::-1, ::-1] if reverse else distance
        current_nearest = nearest[::-1, ::-1] if reverse else nearest
        for wave in range(2 * (rows - 1) + cols):
            first_row = max(0, (wave - cols + 2) // 2)
            last_row = min(rows - 1, wave // 2)
            rr = np.arange(first_row, last_row + 1, dtype=np.intp)
            cc = wave - 2 * rr
            for dr, dc, step in neighbours:
                neighbour_rows, neighbour_cols = rr + dr, cc + dc
                valid = (
                    (neighbour_rows >= 0)
                    & (neighbour_rows < rows)
                    & (neighbour_cols >= 0)
                    & (neighbour_cols < cols)
                )
                selected_rows, selected_cols = rr[valid], cc[valid]
                neighbour_rows, neighbour_cols = neighbour_rows[valid], neighbour_cols[valid]
                candidate = current_distance[neighbour_rows, neighbour_cols].astype(np.float64) + float(step)
                better = candidate < current_distance[selected_rows, selected_cols]
                selected_rows, selected_cols = selected_rows[better], selected_cols[better]
                current_distance[selected_rows, selected_cols] = candidate[better]
                current_nearest[selected_rows, selected_cols] = current_nearest[
                    neighbour_rows[better], neighbour_cols[better]
                ]
    return distance, nearest


def _chamfer_distance(mask: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Select bounded wavefront work only when its batch overhead is justified."""

    rows, cols = mask.shape
    # A 256-cell minimum side clears measured setup overhead conservatively;
    # small or narrow windows keep the unchanged direct scan.
    if not use_optimized("chamfer_wavefront") or min(rows, cols) < 256:
        return _chamfer_distance_reference(mask)
    return _chamfer_distance_wavefront(mask)


def _interpolate_parent_field(parent_values: np.ndarray, factor: int = PARENT_FACTOR) -> np.ndarray:
    """Continuously interpolate parent-centred values to fine-cell centres."""

    parent = np.asarray(parent_values, dtype=np.float64)
    parent_rows, parent_cols = parent.shape
    fine_rows, fine_cols = parent_rows * factor, parent_cols * factor
    parent_x = np.arange(parent_cols, dtype=np.float64) * factor + (factor - 1.0) / 2.0
    parent_y = np.arange(parent_rows, dtype=np.float64) * factor + (factor - 1.0) / 2.0
    fine_x = np.arange(fine_cols, dtype=np.float64)
    fine_y = np.arange(fine_rows, dtype=np.float64)
    horizontal = np.empty((parent_rows, fine_cols), dtype=np.float64)
    for row in range(parent_rows):
        horizontal[row] = np.interp(fine_x, parent_x, parent[row])
    result = np.empty((fine_rows, fine_cols), dtype=np.float64)
    for col in range(fine_cols):
        result[:, col] = np.interp(fine_y, parent_y, horizontal[:, col])
    return result


def _smooth_parent_mean_compensation(
    provisional: np.ndarray,
    target_parent_means: np.ndarray,
    *,
    factor: int = PARENT_FACTOR,
) -> tuple[np.ndarray, np.ndarray, float]:
    """Restore exact parent means without blockwise constant discontinuities."""

    result = np.asarray(provisional, dtype=np.float64).copy()
    compensation = np.zeros(result.shape, dtype=np.float64)
    # Repeated continuous interpolation removes almost all parent residual while
    # keeping the correction continuous across 100 m edges.
    for _ in range(32):
        residual = target_parent_means - parent_block_means(result, factor)
        if float(np.max(np.abs(residual))) <= 1e-8:
            break
        addition = _interpolate_parent_field(residual, factor)
        result += addition
        compensation += addition
    # A small C1-style interior bubble closes the final numerical residual.  It
    # approaches zero at parent boundaries, unlike the old constant-per-block
    # compensation that created visible 100 m steps.
    residual = target_parent_means - parent_block_means(result, factor)
    axis = np.sin(
        np.pi * (np.arange(factor, dtype=np.float64) + 0.5) / factor
    ) ** 2
    bubble = np.outer(axis, axis)
    bubble /= float(bubble.mean())
    for parent_row in range(target_parent_means.shape[0]):
        row0 = parent_row * factor
        for parent_col in range(target_parent_means.shape[1]):
            col0 = parent_col * factor
            addition = float(residual[parent_row, parent_col]) * bubble
            result[row0 : row0 + factor, col0 : col0 + factor] += addition
            compensation[row0 : row0 + factor, col0 : col0 + factor] += addition
    return result, compensation, float(np.max(np.abs(compensation)))


def condition_terrain(
    base_elevation_m: np.ndarray,
    parent_elevation_m: np.ndarray,
    constraints: Sequence[ChannelConstraint],
    recipe: PhysicalRecipe,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict[str, object]]:
    """Carve bounded vector-supported valleys and restore every parent mean."""

    base = np.asarray(base_elevation_m, dtype=np.float64)
    if parent_elevation_m.shape != (base.shape[0] // 10, base.shape[1] // 10):
        raise PhysicalReconstructionError("Parent/fine elevation shape mismatch")
    class_grid = np.zeros(base.shape, dtype=np.uint8)
    class_masks = {name: np.zeros(base.shape, dtype=bool) for name in CLASS_PARAMETERS}
    valid_constraints: list[ChannelConstraint] = []
    for constraint in constraints:
        if constraint.route_class not in CLASS_PARAMETERS:
            raise PhysicalReconstructionError(f"Unknown protected channel class {constraint.route_class}")
        path = _deduplicate_path(constraint.path_cells)
        in_bounds = tuple(
            (row, col)
            for row, col in path
            if 0 <= row < base.shape[0] and 0 <= col < base.shape[1]
        )
        if len(in_bounds) < 2:
            continue
        selected = ChannelConstraint(
            feature_id=constraint.feature_id,
            route_class=constraint.route_class,
            persistence=constraint.persistence,
            path_cells=in_bounds,
            contributing_area_prior_km2=constraint.contributing_area_prior_km2,
            boundary_inflow=constraint.boundary_inflow,
            source_kind=constraint.source_kind,
            bed_elevations_m=constraint.bed_elevations_m,
            vertical_control=constraint.vertical_control,
            receiver_id=constraint.receiver_id,
        )
        valid_constraints.append(selected)
        code = CLASS_CODE[constraint.route_class]
        for row, col in in_bounds:
            class_masks[constraint.route_class][row, col] = True
            class_grid[row, col] = max(int(class_grid[row, col]), code)

    burn = np.zeros(base.shape, dtype=np.float64)
    for route_class, mask in class_masks.items():
        if not np.any(mask):
            continue
        parameters = CLASS_PARAMETERS[route_class]
        distance, _ = _chamfer_distance(mask)
        local = float(parameters["depth_m"]) * np.exp(
            -np.square(distance.astype(np.float64) / float(parameters["sigma_cells"]))
        )
        burn = np.maximum(burn, local)
    provisional = base - burn
    conditioned, compensation, maximum_compensation = _smooth_parent_mean_compensation(
        provisional, np.asarray(parent_elevation_m, dtype=np.float64)
    )
    if maximum_compensation > recipe.maximum_parent_compensation_m:
        raise PhysicalReconstructionError(
            f"Smooth parent compensation exceeds bound: {maximum_compensation:.3f} m"
        )

    error = np.abs(parent_block_means(conditioned) - parent_elevation_m)
    maximum_parent_error = float(np.max(error)) if error.size else 0.0
    if maximum_parent_error > recipe.parent_mean_tolerance_m:
        raise PhysicalReconstructionError(
            f"Conditioned terrain violates parent means by {maximum_parent_error:.6f} m"
        )
    delta = conditioned - base
    maximum_conditioning_delta = float(np.max(np.abs(delta))) if delta.size else 0.0
    if maximum_conditioning_delta > recipe.maximum_conditioning_delta_m + 1e-7:
        raise PhysicalReconstructionError(
            "Fine terrain conditioning exceeds frozen one-metre budget: "
            f"{maximum_conditioning_delta:.6f} m"
        )
    metrics = {
        "protected_feature_count": len(valid_constraints),
        "protected_centreline_cell_count": int(np.count_nonzero(class_grid)),
        "maximum_parent_mean_error_m": maximum_parent_error,
        "maximum_parent_compensation_m": maximum_compensation,
        "maximum_monotonic_extra_incision_m": 0.0,
        "minimum_final_protected_drop_m": None,
        "land_surface_monotonic_channel_incision_disabled": True,
        "channel_bed_is_separate_from_land_surface": True,
        "nominal_channel_burn_max_m": float(np.max(burn)) if burn.size else 0.0,
        "smooth_parent_compensation_max_abs_m": maximum_compensation,
        "conditioning_delta_min_m": float(np.min(delta)) if delta.size else 0.0,
        "conditioning_delta_max_m": float(np.max(delta)) if delta.size else 0.0,
        "conditioning_delta_max_abs_m": maximum_conditioning_delta,
        "conditioning_delta_p95_abs_m": float(np.percentile(np.abs(delta), 95.0)),
    }
    return conditioned.astype(np.float32), delta.astype(np.float32), class_grid, metrics


def prepare_channel_beds(
    land_elevation_m: np.ndarray,
    constraints: Sequence[ChannelConstraint],
    recipe: PhysicalRecipe,
) -> tuple[list[ChannelConstraint], np.ndarray, dict[str, object]]:
    """Rasterise separate protected beds and make every registered edge strict."""

    land = np.asarray(land_elevation_m, dtype=np.float64)
    rows, cols = land.shape
    prepared: list[ChannelConstraint] = []
    adjustment_max = 0.0
    terrain_ceiling_correction_max = 0.0
    terrain_ceiling_correction_cells = 0
    for constraint in constraints:
        original_path = _deduplicate_path(constraint.path_cells)
        paired = [
            (index, cell)
            for index, cell in enumerate(original_path)
            if 0 <= cell[0] < rows and 0 <= cell[1] < cols
        ]
        if len(paired) < 2:
            continue
        path = tuple(cell for _, cell in paired)
        if constraint.bed_elevations_m:
            if len(constraint.bed_elevations_m) != len(original_path):
                raise PhysicalReconstructionError(
                    f"Protected bed/path length mismatch for {constraint.feature_id}"
                )
            bed = np.asarray(
                [constraint.bed_elevations_m[index] for index, _ in paired], dtype=np.float64
            )
        else:
            depth = float(CLASS_PARAMETERS[constraint.route_class]["depth_m"])
            bed = np.asarray([land[cell] - depth for cell in path], dtype=np.float64)
        if not bool(np.all(np.isfinite(bed))):
            raise PhysicalReconstructionError(f"Invalid protected bed values for {constraint.feature_id}")
        if float(bed[0]) < float(bed[-1]):
            path = tuple(reversed(path))
            bed = bed[::-1]
        # The active 100 m terrain remains vertical authority.  Major 3D bed
        # profiles are review-only targets: retain their Z where physically
        # admissible, but derive a new candidate below the conditioned land
        # wherever a profile would otherwise float above it.  The source file
        # is never edited or silently relabelled as reconciled authority.
        depth = float(CLASS_PARAMETERS[constraint.route_class]["depth_m"])
        ceiling = np.asarray([land[cell] - depth for cell in path], dtype=np.float64)
        ceiling_correction = np.maximum(bed - ceiling, 0.0)
        if (
            np.any(ceiling_correction > 1e-9)
            and not constraint.terrain_ceiling_reconciliation_allowed
        ):
            raise PhysicalReconstructionError(
                f"CONFLICT_PROFILE_ABOVE_TERRAIN:{constraint.feature_id}:"
                f"{float(np.max(ceiling_correction)):.6f}m"
            )
        terrain_ceiling_correction_cells += int(np.count_nonzero(ceiling_correction > 1e-9))
        terrain_ceiling_correction_max = max(
            terrain_ceiling_correction_max,
            float(np.max(ceiling_correction)) if ceiling_correction.size else 0.0,
        )
        bed = np.minimum(bed, ceiling)
        original = bed.copy()
        for index in range(1, len(bed)):
            bed[index] = min(
                float(bed[index]),
                float(bed[index - 1]) - recipe.minimum_channel_drop_m_per_cell,
            )
        adjustment_max = max(adjustment_max, float(np.max(original - bed)))
        prepared.append(ChannelConstraint(
            feature_id=constraint.feature_id,
            route_class=constraint.route_class,
            persistence=constraint.persistence,
            path_cells=path,
            contributing_area_prior_km2=constraint.contributing_area_prior_km2,
            boundary_inflow=constraint.boundary_inflow,
            source_kind=constraint.source_kind,
            bed_elevations_m=tuple(float(value) for value in bed),
            vertical_control=constraint.vertical_control,
            receiver_id=constraint.receiver_id,
            terrain_ceiling_reconciliation_allowed=(
                constraint.terrain_ceiling_reconciliation_allowed
            ),
        ))

    bed_grid = np.full(land.shape, np.nan, dtype=np.float64)
    outgoing: dict[int, int] = {}
    for constraint in prepared:
        for cell, value in zip(constraint.path_cells, constraint.bed_elevations_m):
            previous = bed_grid[cell]
            bed_grid[cell] = float(value) if not np.isfinite(previous) else min(float(previous), float(value))
        for source, target in zip(constraint.path_cells[:-1], constraint.path_cells[1:]):
            source_index = source[0] * cols + source[1]
            target_index = target[0] * cols + target[1]
            previous_target = outgoing.get(source_index)
            if previous_target is not None and previous_target != target_index:
                raise PhysicalReconstructionError(f"Conflicting protected bed edges at {source}")
            outgoing[source_index] = target_index
    # Confluences can contribute a lower value to a shared cell.  Re-relax the
    # complete registered graph until all shared-cell edges are strictly down.
    for _ in range(max(len(outgoing), 1)):
        changed = False
        for source_index, target_index in outgoing.items():
            source = divmod(source_index, cols)
            target = divmod(target_index, cols)
            permitted = float(bed_grid[source]) - recipe.minimum_channel_drop_m_per_cell
            if float(bed_grid[target]) > permitted + 1e-12:
                bed_grid[target] = permitted
                changed = True
        if not changed:
            break
    else:
        raise PhysicalReconstructionError("Protected bed graph failed to converge")
    final_prepared: list[ChannelConstraint] = []
    for constraint in prepared:
        final_prepared.append(ChannelConstraint(
            **{
                **asdict(constraint),
                "bed_elevations_m": tuple(float(bed_grid[cell]) for cell in constraint.path_cells),
            }
        ))
    finite = np.isfinite(bed_grid)
    above_land = finite & (bed_grid > land + 1e-9)
    if np.any(above_land):
        raise PhysicalReconstructionError(
            "Protected bed remains above conditioned terrain after authority reconciliation"
        )
    metrics = {
        "protected_bed_cell_count": int(np.count_nonzero(finite)),
        "protected_bed_feature_count": len(final_prepared),
        "protected_bed_strictness_adjustment_max_m": adjustment_max,
        "protected_bed_terrain_ceiling_correction_max_m": terrain_ceiling_correction_max,
        "protected_bed_terrain_ceiling_correction_cell_count": terrain_ceiling_correction_cells,
        "protected_bed_above_conditioned_land_cell_count": int(np.count_nonzero(above_land)),
        "protected_bed_minimum_land_clearance_m": (
            float(np.min(land[finite] - bed_grid[finite])) if np.any(finite) else None
        ),
        "protected_bed_min_elevation_m": float(np.nanmin(bed_grid)) if np.any(finite) else None,
        "protected_bed_max_elevation_m": float(np.nanmax(bed_grid)) if np.any(finite) else None,
    }
    return final_prepared, bed_grid.astype(np.float64), metrics


def priority_flood_surface(
    elevation_m: np.ndarray,
    sink_mask: np.ndarray,
    epsilon_m: float,
    protected_bed_elevation_m: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray, dict[str, object]]:
    """Create a strictly draining analytical routing surface.

    The returned fill is not physical terrain and is kept as an explicit
    conditioning delta.  Boundaries are flood seeds, while sea and registered
    lake cells are explicit sinks.  A high boundary cell is intentionally not
    forced to be an outlet: a protected river may enter the bounded lens there.
    """

    elevation = np.asarray(elevation_m, dtype=np.float64)
    rows, cols = elevation.shape
    if sink_mask.shape != elevation.shape:
        raise PhysicalReconstructionError("Routing sink mask shape mismatch")
    visited = np.zeros(elevation.shape, dtype=bool)
    routed = elevation.copy()
    queue: list[tuple[float, int]] = []
    seeds = np.asarray(sink_mask, dtype=bool).copy()
    seeds[[0, -1], :] = True
    seeds[:, [0, -1]] = True
    protected = np.zeros(elevation.shape, dtype=bool)
    if protected_bed_elevation_m is not None:
        bed = np.asarray(protected_bed_elevation_m, dtype=np.float64)
        if bed.shape != elevation.shape:
            raise PhysicalReconstructionError("Protected bed shape mismatch")
        protected = np.isfinite(bed)
        routed[protected] = bed[protected]
        seeds |= protected
    for index in np.flatnonzero(seeds.ravel()):
        visited.ravel()[index] = True
        heapq.heappush(queue, (float(routed.ravel()[index]), int(index)))
    while queue:
        level, index = heapq.heappop(queue)
        row, col = divmod(index, cols)
        for dr, dc, _ in D8:
            rr, cc = row + dr, col + dc
            if rr < 0 or rr >= rows or cc < 0 or cc >= cols or visited[rr, cc]:
                continue
            visited[rr, cc] = True
            original = float(routed[rr, cc])
            new_level = max(original, level + epsilon_m)
            routed[rr, cc] = new_level
            heapq.heappush(queue, (new_level, rr * cols + cc))
    if not bool(np.all(visited)):
        raise PhysicalReconstructionError("Priority flood did not visit every cell")
    delta = routed - elevation
    metrics = {
        "routing_fill_max_m": float(np.max(delta)) if delta.size else 0.0,
        "routing_fill_p95_m": float(np.percentile(delta, 95.0)),
        "routing_fill_positive_fraction": float(np.mean(delta > 1e-7)),
        "routing_sink_seed_count": int(np.count_nonzero(seeds)),
        "routing_protected_bed_seed_count": int(np.count_nonzero(protected)),
    }
    # Preserve float64 internally: the frozen 0.1 mm ordering epsilon can be
    # smaller than one float32 ULP at high mountain elevations.
    return routed.astype(np.float64), delta.astype(np.float64), metrics


def d8_receivers(routing_elevation_m: np.ndarray, sink_mask: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Vectorised steepest-descent D8 receivers and compact direction codes."""

    elevation = np.asarray(routing_elevation_m, dtype=np.float64)
    rows, cols = elevation.shape
    padded = np.pad(elevation, 1, mode="constant", constant_values=np.inf)
    slopes = []
    for dr, dc, distance in D8:
        neighbour = padded[1 + dr : 1 + dr + rows, 1 + dc : 1 + dc + cols]
        slopes.append((elevation - neighbour) / (distance * CELL_SIZE_M))
    stack = np.stack(slopes, axis=0)
    direction = np.argmax(stack, axis=0).astype(np.int8)
    best = np.take_along_axis(stack, direction[None, :, :], axis=0)[0]
    receiver = np.full(rows * cols, -1, dtype=np.int64)
    rr, cc = np.indices((rows, cols), dtype=np.int64)
    for code, (dr, dc, _) in enumerate(D8):
        selected = (direction == code) & (best > 0.0)
        target_row = rr[selected] + dr
        target_col = cc[selected] + dc
        receiver[np.flatnonzero(selected.ravel())] = target_row * cols + target_col
    # Do not force every boundary cell to be a sink.  The priority flood uses
    # the boundary as a set of possible outlets, but clipped rivers can also
    # enter the bounded lens there.  A boundary cell with a lower in-window
    # neighbour must therefore be allowed to receive an ordinary downhill D8
    # edge.  True sea/lake cells remain explicit sinks.
    forced_sinks = np.asarray(sink_mask, dtype=bool).copy()
    receiver[forced_sinks.ravel()] = -1
    direction[receiver.reshape(rows, cols) < 0] = -1
    return receiver, direction


def constrain_protected_receivers(
    routing_elevation_m: np.ndarray,
    receiver: np.ndarray,
    direction: np.ndarray,
    constraints: Sequence[ChannelConstraint],
) -> tuple[np.ndarray, np.ndarray, dict[str, object]]:
    """Force supported route cells through their ordered registered path.

    This closes the gap between a separately preserved vector/class mask and
    the receiver graph: a lower lateral neighbour can no longer silently pull
    protected flow away from the registered route.  Conflicting overlaps,
    non-neighbour jumps, uphill edges and cycles remain fail-closed.
    """

    elevation = np.asarray(routing_elevation_m, dtype=np.float64)
    rows, cols = elevation.shape
    output_receiver = np.asarray(receiver, dtype=np.int64).copy()
    output_direction = np.asarray(direction, dtype=np.int8).copy()
    forced: dict[int, int] = {}
    feature_edges = 0
    for constraint in constraints:
        path = list(_deduplicate_path(constraint.path_cells))
        path = [cell for cell in path if 0 <= cell[0] < rows and 0 <= cell[1] < cols]
        if len(path) < 2:
            continue
        if elevation[path[0]] < elevation[path[-1]]:
            path.reverse()
        for source, target in zip(path[:-1], path[1:]):
            dr, dc = target[0] - source[0], target[1] - source[1]
            if max(abs(dr), abs(dc)) != 1:
                raise PhysicalReconstructionError(
                    f"Protected route {constraint.feature_id} contains a non-D8 jump"
                )
            if not float(elevation[source]) > float(elevation[target]):
                raise PhysicalReconstructionError(
                    f"Protected route {constraint.feature_id} is not strictly downhill"
                )
            source_index = source[0] * cols + source[1]
            target_index = target[0] * cols + target[1]
            previous = forced.get(source_index)
            if previous is not None and previous != target_index:
                raise PhysicalReconstructionError(
                    f"Conflicting protected receivers at cell {source}"
                )
            forced[source_index] = target_index
            feature_edges += 1
    code_by_delta = {(dr, dc): code for code, (dr, dc, _) in enumerate(D8)}
    for source_index, target_index in forced.items():
        source = divmod(source_index, cols)
        target = divmod(target_index, cols)
        output_receiver[source_index] = target_index
        output_direction[source] = np.int8(
            code_by_delta[(target[0] - source[0], target[1] - source[1])]
        )
    metrics = {
        "protected_forced_receiver_cell_count": len(forced),
        "protected_feature_edge_count_before_overlap_deduplication": feature_edges,
        "protected_receiver_conflict_count": 0,
    }
    return output_receiver, output_direction, metrics


def mfd_receivers(
    routing_elevation_m: np.ndarray,
    sink_mask: np.ndarray,
    *,
    slope_exponent: float = 1.1,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return deterministic slope-weighted multiple-flow-direction edges.

    Unlike single-receiver D8, MFD does not force broad smooth hillslopes into
    artificial eight-direction herringbones.  Every edge is still a local D8
    neighbour and strictly downhill on the analytical routing surface.
    """

    elevation = np.asarray(routing_elevation_m, dtype=np.float64)
    rows, cols = elevation.shape
    if sink_mask.shape != elevation.shape:
        raise PhysicalReconstructionError("MFD sink mask shape mismatch")
    count = rows * cols
    rr, cc = np.indices((rows, cols), dtype=np.int64)
    receiver = np.full((8, count), -1, dtype=np.int64)
    raw_weight = np.zeros((8, rows, cols), dtype=np.float64)
    padded = np.pad(elevation, 1, mode="constant", constant_values=np.inf)
    for code, (dr, dc, distance) in enumerate(D8):
        neighbour = padded[1 + dr : 1 + dr + rows, 1 + dc : 1 + dc + cols]
        slope = np.maximum((elevation - neighbour) / (distance * CELL_SIZE_M), 0.0)
        valid = slope > 0.0
        target_row = rr[valid] + dr
        target_col = cc[valid] + dc
        sources = np.flatnonzero(valid.ravel())
        receiver[code, sources] = target_row * cols + target_col
        raw_weight[code, valid] = np.power(slope[valid], float(slope_exponent))
    raw_weight[:, np.asarray(sink_mask, dtype=bool)] = 0.0
    total = raw_weight.sum(axis=0)
    weight = np.divide(
        raw_weight,
        total[None, :, :],
        out=np.zeros_like(raw_weight),
        where=total[None, :, :] > 0.0,
    ).reshape(8, count)
    receiver[weight <= 0.0] = -1
    direction = np.full((rows, cols), -1, dtype=np.int8)
    active = total > 0.0
    direction[active] = np.argmax(raw_weight[:, active], axis=0).astype(np.int8)
    return receiver, weight.astype(np.float32), direction


def constrain_protected_mfd(
    routing_elevation_m: np.ndarray,
    receiver: np.ndarray,
    weight: np.ndarray,
    direction: np.ndarray,
    constraints: Sequence[ChannelConstraint],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict[str, object]]:
    """Override registered channel cells with one exact downstream edge."""

    elevation = np.asarray(routing_elevation_m, dtype=np.float64)
    rows, cols = elevation.shape
    output_receiver = np.asarray(receiver, dtype=np.int64).copy()
    output_weight = np.asarray(weight, dtype=np.float32).copy()
    output_direction = np.asarray(direction, dtype=np.int8).copy()
    forced: dict[int, int] = {}
    for constraint in constraints:
        path = [
            cell for cell in _deduplicate_path(constraint.path_cells)
            if 0 <= cell[0] < rows and 0 <= cell[1] < cols
        ]
        if len(path) < 2:
            continue
        for source, target in zip(path[:-1], path[1:]):
            dr, dc = target[0] - source[0], target[1] - source[1]
            if max(abs(dr), abs(dc)) != 1:
                raise PhysicalReconstructionError(
                    f"Protected route {constraint.feature_id} contains a non-D8 jump"
                )
            if not float(elevation[source]) > float(elevation[target]):
                raise PhysicalReconstructionError(
                    f"Protected route {constraint.feature_id} is not strictly downhill on its bed"
                )
            source_index = source[0] * cols + source[1]
            target_index = target[0] * cols + target[1]
            previous = forced.get(source_index)
            if previous is not None and previous != target_index:
                raise PhysicalReconstructionError(f"Conflicting protected MFD receivers at {source}")
            forced[source_index] = target_index
    code_by_delta = {(dr, dc): code for code, (dr, dc, _) in enumerate(D8)}
    for source_index, target_index in forced.items():
        source = divmod(source_index, cols)
        target = divmod(target_index, cols)
        code = code_by_delta[(target[0] - source[0], target[1] - source[1])]
        output_receiver[:, source_index] = -1
        output_weight[:, source_index] = 0.0
        output_receiver[code, source_index] = target_index
        output_weight[code, source_index] = 1.0
        output_direction[source] = np.int8(code)
    return output_receiver, output_weight, output_direction, {
        "protected_forced_receiver_cell_count": len(forced),
        "protected_receiver_weight_sum_min": 1.0 if forced else None,
        "protected_receiver_weight_sum_max": 1.0 if forced else None,
        "protected_receiver_conflict_count": 0,
    }


def accumulate_flow_mfd(
    routing_elevation_m: np.ndarray,
    receiver: np.ndarray,
    weight: np.ndarray,
    monthly_runoff_mm: np.ndarray,
    boundary_seeds: Mapping[int, float],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict[str, object]]:
    """Mass-conserving accumulation across the weighted MFD graph."""

    rows, cols = routing_elevation_m.shape
    count = rows * cols
    if receiver.shape != (8, count) or weight.shape != (8, count):
        raise PhysicalReconstructionError("MFD graph shape mismatch")
    if monthly_runoff_mm.shape != (12, rows, cols):
        raise PhysicalReconstructionError("Monthly runoff must be 12 x rows x cols")
    active = (receiver >= 0) & (weight > 0.0)
    sums = np.asarray(weight, dtype=np.float64).sum(axis=0)
    if np.any(np.abs(sums[(sums > 0.0)] - 1.0) > 1e-6):
        raise PhysicalReconstructionError("MFD receiver weights do not sum to one")
    elevation = np.asarray(routing_elevation_m, dtype=np.float64).ravel()
    for code in range(8):
        selected = active[code]
        if np.any(elevation[selected] <= elevation[receiver[code, selected]]):
            raise PhysicalReconstructionError("MFD graph contains a non-downhill edge")
    area = np.full(count, (CELL_SIZE_M / 1000.0) ** 2, dtype=np.float64)
    monthly = monthly_runoff_mm.reshape(12, -1).astype(np.float64)
    load = monthly * area[None, :]
    seeded_area = 0.0
    for index, prior_area in boundary_seeds.items():
        if not 0 <= int(index) < count or prior_area <= 0.0:
            continue
        value = float(prior_area)
        area[int(index)] += value
        load[:, int(index)] += monthly[:, int(index)] * value
        seeded_area += value
    indegree = np.zeros(count, dtype=np.int32)
    for code in range(8):
        np.add.at(indegree, receiver[code, active[code]], 1)
    queue = list(np.flatnonzero(indegree == 0))
    position = 0
    processed = 0
    while position < len(queue):
        index = int(queue[position])
        position += 1
        processed += 1
        for code in range(8):
            downstream = int(receiver[code, index])
            fraction = float(weight[code, index])
            if downstream < 0 or fraction <= 0.0:
                continue
            area[downstream] += area[index] * fraction
            load[:, downstream] += load[:, index] * fraction
            indegree[downstream] -= 1
            if indegree[downstream] == 0:
                queue.append(downstream)
    if processed != count:
        raise PhysicalReconstructionError(
            f"MFD graph contains a cycle involving {int(np.count_nonzero(indegree > 0))} cells"
        )
    annual = load.sum(axis=0)
    edge_source, edge_code = np.nonzero(active.T)
    edge_target = receiver[edge_code, edge_source]
    edge_payload = np.column_stack((edge_source, edge_target, edge_code)).astype(np.int64)
    return (
        area.reshape(rows, cols).astype(np.float32),
        load.reshape(12, rows, cols).astype(np.float32),
        annual.reshape(rows, cols).astype(np.float32),
        {
            "receiver_edge_count": int(edge_payload.shape[0]),
            "receiver_graph_sha256": sha256(edge_payload.tobytes()).hexdigest(),
            "boundary_seed_count": len(boundary_seeds),
            "boundary_seed_area_km2": seeded_area,
            "topologically_processed_cell_count": processed,
            "receiver_cycle_count": 0,
            "mfd_mass_fraction_max_error": float(
                np.max(np.abs(sums[sums > 0.0] - 1.0)) if np.any(sums > 0.0) else 0.0
            ),
            "accumulated_area_max_km2": float(np.max(area)) if area.size else 0.0,
            "accumulated_runoff_proxy_max_mm_km2_y": float(np.max(annual)) if annual.size else 0.0,
        },
    )


def accumulate_flow_mfd_scenarios(
    routing_elevation_m: np.ndarray,
    receiver: np.ndarray,
    weight: np.ndarray,
    monthly_runoff_scenarios: Sequence[np.ndarray],
    boundary_seeds: Mapping[int, float],
) -> tuple[tuple[np.ndarray, np.ndarray, np.ndarray, dict[str, object]], ...]:
    """Accumulate two independent forcing scenarios in one ordered traversal.

    Sharing graph validation, the queue and area arithmetic does not couple
    the scenarios.  Each month still receives exactly the original ordered
    sequence of Float64 additions/multiplications; annual reductions retain
    their original twelve-row slices.  Other scenario counts and windows
    above 512-by-512 cells use the unchanged reference implementation.

    The combined Float64 load is at most 48 MiB.  Initialisation uses one
    twelve-month temporary at a time, released before graph traversal; no
    combined copy of input runoff is retained.  Returned arrays never alias.
    """

    scenarios = tuple(monthly_runoff_scenarios)
    rows, cols = routing_elevation_m.shape
    count = rows * cols
    if (
        not use_optimized("mfd_scenario_batch")
        or len(scenarios) != 2
        or count > 512 * 512
        or any(scenario.shape != (12, rows, cols) for scenario in scenarios)
    ):
        return tuple(
            accumulate_flow_mfd(routing_elevation_m, receiver, weight, scenario, boundary_seeds)
            for scenario in scenarios
        )
    if receiver.shape != (8, count) or weight.shape != (8, count):
        raise PhysicalReconstructionError("MFD graph shape mismatch")
    active = (receiver >= 0) & (weight > 0.0)
    sums = np.asarray(weight, dtype=np.float64).sum(axis=0)
    if np.any(np.abs(sums[(sums > 0.0)] - 1.0) > 1e-6):
        raise PhysicalReconstructionError("MFD receiver weights do not sum to one")
    elevation = np.asarray(routing_elevation_m, dtype=np.float64).ravel()
    for code in range(8):
        selected = active[code]
        if np.any(elevation[selected] <= elevation[receiver[code, selected]]):
            raise PhysicalReconstructionError("MFD graph contains a non-downhill edge")
    area = np.full(count, (CELL_SIZE_M / 1000.0) ** 2, dtype=np.float64)
    load = np.empty((24, count), dtype=np.float64)
    for scenario_index, scenario in enumerate(scenarios):
        monthly = scenario.reshape(12, -1).astype(np.float64)
        scenario_load = load[scenario_index * 12 : (scenario_index + 1) * 12]
        np.multiply(monthly, area[None, :], out=scenario_load)
        for index, prior_area in boundary_seeds.items():
            if not 0 <= int(index) < count or prior_area <= 0.0:
                continue
            scenario_load[:, int(index)] += monthly[:, int(index)] * float(prior_area)
        del monthly, scenario_load
    seeded_area = 0.0
    for index, prior_area in boundary_seeds.items():
        if not 0 <= int(index) < count or prior_area <= 0.0:
            continue
        value = float(prior_area)
        area[int(index)] += value
        seeded_area += value
    indegree = np.zeros(count, dtype=np.int32)
    for code in range(8):
        np.add.at(indegree, receiver[code, active[code]], 1)
    queue = list(np.flatnonzero(indegree == 0))
    position = 0
    processed = 0
    while position < len(queue):
        index = int(queue[position])
        position += 1
        processed += 1
        for code in range(8):
            downstream = int(receiver[code, index])
            fraction = float(weight[code, index])
            if downstream < 0 or fraction <= 0.0:
                continue
            area[downstream] += area[index] * fraction
            load[:, downstream] += load[:, index] * fraction
            indegree[downstream] -= 1
            if indegree[downstream] == 0:
                queue.append(downstream)
    if processed != count:
        raise PhysicalReconstructionError(
            f"MFD graph contains a cycle involving {int(np.count_nonzero(indegree > 0))} cells"
        )
    edge_source, edge_code = np.nonzero(active.T)
    edge_target = receiver[edge_code, edge_source]
    edge_payload = np.column_stack((edge_source, edge_target, edge_code)).astype(np.int64)
    common_metrics = {
        "receiver_edge_count": int(edge_payload.shape[0]),
        "receiver_graph_sha256": sha256(edge_payload.tobytes()).hexdigest(),
        "boundary_seed_count": len(boundary_seeds),
        "boundary_seed_area_km2": seeded_area,
        "topologically_processed_cell_count": processed,
        "receiver_cycle_count": 0,
        "mfd_mass_fraction_max_error": float(
            np.max(np.abs(sums[sums > 0.0] - 1.0)) if np.any(sums > 0.0) else 0.0
        ),
        "accumulated_area_max_km2": float(np.max(area)) if area.size else 0.0,
    }
    results = []
    for scenario_index in range(2):
        scenario_load = load[scenario_index * 12 : (scenario_index + 1) * 12]
        annual = scenario_load.sum(axis=0)
        metrics = dict(common_metrics)
        metrics["accumulated_runoff_proxy_max_mm_km2_y"] = float(np.max(annual)) if annual.size else 0.0
        results.append((
            area.reshape(rows, cols).astype(np.float32),
            scenario_load.reshape(12, rows, cols).astype(np.float32),
            annual.reshape(rows, cols).astype(np.float32),
            metrics,
        ))
    return tuple(results)


def accumulate_flow(
    routing_elevation_m: np.ndarray,
    receiver: np.ndarray,
    monthly_runoff_mm: np.ndarray,
    boundary_seeds: Mapping[int, float],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict[str, object]]:
    """Accumulate local area and monthly effective-runoff proxy downstream."""

    rows, cols = routing_elevation_m.shape
    if receiver.shape != (rows * cols,):
        raise PhysicalReconstructionError("Receiver shape mismatch")
    if monthly_runoff_mm.shape != (12, rows, cols):
        raise PhysicalReconstructionError("Monthly runoff must be 12 x rows x cols")
    area = np.full(rows * cols, (CELL_SIZE_M / 1000.0) ** 2, dtype=np.float64)
    monthly = monthly_runoff_mm.reshape(12, -1).astype(np.float64)
    load = monthly * area[None, :]
    seeded_area = 0.0
    for index, prior_area in boundary_seeds.items():
        if not 0 <= int(index) < rows * cols or prior_area <= 0.0:
            continue
        value = float(prior_area)
        area[int(index)] += value
        load[:, int(index)] += monthly[:, int(index)] * value
        seeded_area += value
    # Accumulate in an explicitly validated topological order.  Sorting by
    # elevation is insufficient when a protected or virtual edge has equal
    # numerical height, and can conceal a cycle.
    indegree = np.zeros(rows * cols, dtype=np.int32)
    valid_edges = receiver >= 0
    np.add.at(indegree, receiver[valid_edges], 1)
    queue = list(np.flatnonzero(indegree == 0))
    position = 0
    processed = 0
    while position < len(queue):
        index = int(queue[position])
        position += 1
        processed += 1
        downstream = int(receiver[index])
        if downstream >= 0:
            area[downstream] += area[index]
            load[:, downstream] += load[:, index]
            indegree[downstream] -= 1
            if indegree[downstream] == 0:
                queue.append(downstream)
    if processed != rows * cols:
        cyclic = int(np.count_nonzero(indegree > 0))
        raise PhysicalReconstructionError(
            f"Receiver graph contains a cycle involving {cyclic} cells"
        )
    annual = load.sum(axis=0)
    edge_pairs = np.column_stack((np.flatnonzero(receiver >= 0), receiver[receiver >= 0])).astype(np.int64)
    metrics = {
        "receiver_edge_count": int(edge_pairs.shape[0]),
        "receiver_graph_sha256": sha256(edge_pairs.tobytes()).hexdigest(),
        "boundary_seed_count": len(boundary_seeds),
        "boundary_seed_area_km2": seeded_area,
        "topologically_processed_cell_count": processed,
        "receiver_cycle_count": 0,
        "accumulated_area_max_km2": float(np.max(area)) if area.size else 0.0,
        "accumulated_runoff_proxy_max_mm_km2_y": float(np.max(annual)) if annual.size else 0.0,
    }
    return (
        area.reshape(rows, cols).astype(np.float32),
        load.reshape(12, rows, cols).astype(np.float32),
        annual.reshape(rows, cols).astype(np.float32),
        metrics,
    )


def boundary_inflow_seeds(
    constraints: Sequence[ChannelConstraint],
    conditioned_elevation_m: np.ndarray,
) -> dict[int, float]:
    """Bind each clipped inlet to its frozen coarse/D3 area prior.

    The values are drainage-area boundary states, not newly measured flow.
    Multiple constraints entering the same fine cell use the largest applicable
    prior so a duplicated clipped geometry cannot double-count an inlet.
    """

    elevation = np.asarray(conditioned_elevation_m)
    rows, cols = elevation.shape
    result: dict[int, float] = {}
    for constraint in constraints:
        if not constraint.boundary_inflow or constraint.contributing_area_prior_km2 <= 0.0:
            continue
        path = _deduplicate_path(constraint.path_cells)
        in_bounds = [
            (row, col)
            for row, col in path
            if 0 <= row < rows and 0 <= col < cols
        ]
        if not in_bounds:
            continue
        # Prepared constraints are explicitly stored source-to-receiver using
        # their separate bed control.  Do not reorient them from broad land
        # elevation, which is a different physical quantity.
        upstream = in_bounds[0]
        index = upstream[0] * cols + upstream[1]
        result[index] = max(
            result.get(index, 0.0),
            float(constraint.contributing_area_prior_km2),
        )
    return result


def _generated_channel_threshold(annual_runoff_mm: np.ndarray, recipe: PhysicalRecipe) -> float:
    finite = annual_runoff_mm[np.isfinite(annual_runoff_mm) & (annual_runoff_mm >= 0.0)]
    mean = float(np.median(finite)) if finite.size else recipe.dry_annual_runoff_mm
    fraction = np.clip(
        (mean - recipe.dry_annual_runoff_mm)
        / max(recipe.wet_annual_runoff_mm - recipe.dry_annual_runoff_mm, 1e-9),
        0.0,
        1.0,
    )
    return float(
        recipe.generated_threshold_dry_km2
        + fraction * (recipe.generated_threshold_wet_km2 - recipe.generated_threshold_dry_km2)
    )


def _channel_proximity_mask(protected: np.ndarray) -> np.ndarray:
    """Exact predicate for reference chamfer distance at most 1.5 cells.

    Direct orthogonal/diagonal neighbours cost 1 and sqrt(2), respectively;
    every path of two or more steps costs at least 2.  The predicate therefore
    needs only a bounded 3-by-3 Boolean dilation, not a full distance field.
    The metric, threshold and registered-network basis are unchanged.
    """

    if not use_optimized("channel_proximity"):
        distance, _ = _chamfer_distance(protected)
        return distance <= 1.5
    rows, cols = protected.shape
    near = np.asarray(protected, dtype=bool).copy()
    for dr, dc, _ in D8:
        source_rows = slice(max(0, -dr), rows - max(0, dr))
        source_cols = slice(max(0, -dc), cols - max(0, dc))
        target_rows = slice(max(0, dr), rows - max(0, -dr))
        target_cols = slice(max(0, dc), cols - max(0, -dc))
        near[target_rows, target_cols] |= protected[source_rows, source_cols]
    return near


def classify_channels(
    protected_class: np.ndarray,
    accumulated_area_km2: np.ndarray,
    monthly_load: np.ndarray,
    annual_local_runoff_mm: np.ndarray,
    land_mask: np.ndarray,
    sink_mask: np.ndarray,
    recipe: PhysicalRecipe,
) -> tuple[np.ndarray, np.ndarray, dict[str, object]]:
    threshold = _generated_channel_threshold(annual_local_runoff_mm, recipe)
    protected = protected_class > 0
    near_protected = _channel_proximity_mask(protected)
    generated = (
        (accumulated_area_km2 >= threshold)
        & np.asarray(land_mask, dtype=bool)
        & ~np.asarray(sink_mask, dtype=bool)
        & ~protected
        & ~near_protected
    )
    result = protected_class.astype(np.uint8, copy=True)
    monthly = monthly_load.astype(np.float64)
    annual = monthly.sum(axis=0)
    mean_month = annual / 12.0
    dry_ratio = np.divide(
        monthly.min(axis=0),
        np.maximum(mean_month, 1e-9),
        out=np.zeros_like(mean_month),
        where=mean_month > 0.0,
    )
    result[generated & (dry_ratio < 0.03)] = CLASS_CODE["generated_ephemeral"]
    result[generated & (dry_ratio >= 0.03) & (dry_ratio < 0.15)] = CLASS_CODE[
        "generated_intermittent"
    ]
    result[generated & (dry_ratio >= 0.15)] = CLASS_CODE["generated_perennial"]
    metrics = {
        "generated_channel_threshold_km2": threshold,
        "generated_channel_cell_count": int(np.count_nonzero(generated)),
        "generated_ephemeral_cell_count": int(np.count_nonzero(result == 1)),
        "generated_intermittent_cell_count": int(np.count_nonzero(result == 2)),
        "generated_perennial_cell_count": int(np.count_nonzero(result == 3)),
        "protected_channel_cell_count": int(np.count_nonzero(protected)),
    }
    return result, dry_ratio.astype(np.float32), metrics


def derive_width_proxy(
    channel_class: np.ndarray,
    annual_load_mm_km2: np.ndarray,
    slope_m_per_m: np.ndarray,
) -> np.ndarray:
    """Return explicitly uncalibrated review-only channel-width proxy."""

    q_proxy = np.maximum(annual_load_mm_km2.astype(np.float64) / 31_557.6, 1e-8)
    confinement = np.clip(1.0 / (1.0 + 2.5 * np.maximum(slope_m_per_m, 0.0)), 0.58, 1.0)
    width = 4.2 * np.power(q_proxy, 0.46) * confinement
    lower = np.zeros(channel_class.shape, dtype=np.float64)
    upper = np.zeros(channel_class.shape, dtype=np.float64)
    ranges = {
        1: (0.25, 4.0),
        2: (0.35, 8.0),
        3: (0.5, 15.0),
        4: (0.35, 20.0),
        5: (0.5, 60.0),
        6: (8.0, 250.0),
        7: (30.0, 800.0),
        8: (0.5, 80.0),
    }
    for code, (lo, hi) in ranges.items():
        selected = channel_class == code
        lower[selected] = lo
        upper[selected] = hi
    active = channel_class > 0
    result = np.zeros(channel_class.shape, dtype=np.float32)
    result[active] = np.clip(width[active], lower[active], upper[active]).astype(np.float32)
    return result


def derive_wetness_context(
    elevation_m: np.ndarray,
    channel_class: np.ndarray,
    slope_m_per_m: np.ndarray,
    annual_local_runoff_mm: np.ndarray,
    inherited_flood: np.ndarray,
    inherited_wetland: np.ndarray,
    channel_bed_elevation_m: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict[str, object]]:
    channel = channel_class > 0
    distance_cells, nearest = _chamfer_distance(channel)
    if np.any(channel):
        flat = np.asarray(elevation_m, dtype=np.float64).ravel()
        reference = flat.copy()
        if channel_bed_elevation_m is not None:
            bed = np.asarray(channel_bed_elevation_m, dtype=np.float64).ravel()
            protected = np.isfinite(bed)
            reference[protected] = bed[protected]
        nearest_elevation = np.where(nearest >= 0, reference[np.maximum(nearest, 0)], np.nan)
        hand = np.maximum(np.asarray(elevation_m, dtype=np.float64) - nearest_elevation, 0.0)
    else:
        hand = np.full(elevation_m.shape, np.nan, dtype=np.float64)
    finite_runoff = annual_local_runoff_mm[np.isfinite(annual_local_runoff_mm)]
    low, high = (
        np.percentile(finite_runoff, (10.0, 90.0)) if finite_runoff.size else (0.0, 1.0)
    )
    moisture = np.clip(
        (annual_local_runoff_mm - low) / max(float(high - low), 1e-6), 0.0, 1.0
    )
    distance_m = distance_cells.astype(np.float64) * CELL_SIZE_M
    flood = (
        np.exp(-distance_m / 180.0)
        * np.exp(-np.nan_to_num(hand, nan=1000.0) / 5.0)
        * np.exp(-np.maximum(slope_m_per_m, 0.0) / 0.12)
    )
    flood = np.maximum(flood, np.clip(inherited_flood.astype(np.float64) / 4.0, 0.0, 1.0))
    wetness = np.maximum(
        0.65 * flood + 0.35 * moisture,
        np.asarray(inherited_wetland, dtype=np.float64),
    )
    metrics = {
        "hand_status": "ANALYTICAL_NEAREST_CHANNEL_PROXY_NOT_CATCHMENT_HAND",
        "flood_status": "GEOMORPHIC_POTENTIAL_NOT_RETURN_PERIOD_INUNDATION",
        "hand_median_m": None if not np.any(np.isfinite(hand)) else float(np.nanmedian(hand)),
        "flood_potential_mean": float(np.nanmean(flood)),
        "wetness_potential_mean": float(np.nanmean(wetness)),
    }
    return (
        hand.astype(np.float32),
        np.clip(flood, 0.0, 1.0).astype(np.float32),
        np.clip(wetness, 0.0, 1.0).astype(np.float32),
        metrics,
    )


def build_physical_context(
    base_elevation_m: np.ndarray,
    parent_elevation_m: np.ndarray,
    monthly_runoff_mm: np.ndarray,
    constraints: Sequence[ChannelConstraint],
    land_mask: np.ndarray,
    sea_or_lake_sink_mask: np.ndarray,
    inherited_flood: np.ndarray,
    inherited_wetland: np.ndarray,
    recipe: PhysicalRecipe | None = None,
    source_lineage: Mapping[str, object] | None = None,
) -> PhysicalContext:
    recipe = recipe or PhysicalRecipe()
    conditioned, conditioning_delta, protected_class, terrain_metrics = condition_terrain(
        base_elevation_m, parent_elevation_m, constraints, recipe
    )
    prepared_constraints, protected_bed, bed_metrics = prepare_channel_beds(
        conditioned, constraints, recipe
    )
    routing, routing_delta, flood_metrics = priority_flood_surface(
        conditioned,
        sea_or_lake_sink_mask,
        recipe.priority_flood_epsilon_m,
        protected_bed,
    )
    receiver, receiver_weight, direction = mfd_receivers(
        routing,
        sea_or_lake_sink_mask,
        slope_exponent=recipe.mfd_slope_exponent,
    )
    receiver, receiver_weight, direction, protected_receiver_metrics = constrain_protected_mfd(
        routing, receiver, receiver_weight, direction, prepared_constraints
    )
    rows, cols = conditioned.shape
    boundary_seeds = boundary_inflow_seeds(prepared_constraints, conditioned)
    accumulated_area, monthly_load, annual_load, flow_metrics = accumulate_flow_mfd(
        routing, receiver, receiver_weight, monthly_runoff_mm, boundary_seeds
    )
    annual_local = monthly_runoff_mm.sum(axis=0).astype(np.float32)
    drainage_potential_class, dry_ratio, channel_metrics = classify_channels(
        protected_class,
        accumulated_area,
        monthly_load,
        annual_local,
        land_mask,
        sea_or_lake_sink_mask,
        recipe,
    )
    gradient_row, gradient_col = np.gradient(conditioned.astype(np.float64), CELL_SIZE_M)
    slope = np.hypot(gradient_row, gradient_col)
    # Width is estimated only for already-supported network cells.  Generated
    # drainage is retained as analytical potential and is never promoted into
    # the current network by this stage.
    width = derive_width_proxy(protected_class, annual_load, slope)
    hand, flood_potential, wetness_potential, wetness_metrics = derive_wetness_context(
        conditioned,
        protected_class,
        slope,
        annual_local,
        inherited_flood,
        inherited_wetland,
        protected_bed,
    )
    sink_count = int(np.count_nonzero(receiver_weight.sum(axis=0) <= 0.0))
    arrays = {
        "base_elevation_m": np.asarray(base_elevation_m, dtype=np.float32),
        "conditioned_elevation_m": conditioned,
        "terrain_conditioning_delta_m": conditioning_delta,
        "routing_elevation_m": routing,
        "routing_fill_delta_m": routing_delta,
        "protected_channel_bed_elevation_m": protected_bed,
        "local_gradient_row": gradient_row.astype(np.float32),
        "local_gradient_col": gradient_col.astype(np.float32),
        "local_slope_m_per_m": slope.astype(np.float32),
        "monthly_effective_runoff_proxy_mm": np.asarray(monthly_runoff_mm, dtype=np.float32),
        "annual_effective_runoff_proxy_mm": annual_local,
        "d8_receiver_code": direction.astype(np.int8),
        "mfd_receiver_indices": receiver.astype(np.int64),
        "mfd_receiver_weights": receiver_weight.astype(np.float32),
        "accumulated_area_km2": accumulated_area,
        "monthly_accumulated_runoff_proxy_mm_km2": monthly_load,
        "annual_accumulated_runoff_proxy_mm_km2": annual_load,
        "protected_channel_class": protected_class,
        "drainage_potential_or_protected_class": drainage_potential_class,
        "channel_dry_month_ratio": dry_ratio,
        "channel_width_proxy_m": width,
        "nearest_channel_height_proxy_m": hand,
        "flood_potential": flood_potential,
        "wetness_potential": wetness_potential,
    }
    metrics = {
        **terrain_metrics,
        **bed_metrics,
        **flood_metrics,
        **flow_metrics,
        **protected_receiver_metrics,
        **channel_metrics,
        **wetness_metrics,
        "flood_wetness_channel_basis": "REGISTERED_PROTECTED_NETWORK_ONLY",
        "generated_drainage_excluded_from_flood_wetness_reference": True,
        "routing_total_sink_count_including_boundary_and_registered_water": sink_count,
        "channel_width_proxy_min_m": (
            float(np.min(width[protected_class > 0]))
            if np.any(protected_class > 0) else None
        ),
        "channel_width_proxy_max_m": float(np.max(width)) if width.size else 0.0,
        "array_digest": array_digest(arrays),
    }
    lineage = {
        "method": METHOD_VERSION,
        "recipe": recipe.identity(),
        "cell_size_m": 10,
        "model_resolution_m": 10,
        "terrain_physical_source_resolution_m": 100,
        "terrain_effective_evidence_resolution_m": 100,
        "runoff_physical_source_resolution_m": 100,
        "runoff_status": "SOIL_FREE_CLIMATE_FORCED_REVIEW_ONLY_PROXY_NOT_OBSERVED_RUNOFF",
        "width_status": "UNCALIBRATED_REVIEW_ONLY_PROXY_NOT_OBSERVED_WIDTH",
        "routing_surface_status": "ANALYTICAL_CONDITIONING_SURFACE_NOT_PHYSICAL_TERRAIN",
        "current_vectors_status": "PROTECTED_TOPOLOGY_AND_CLASS_EVIDENCE_CONDITIONING_INPUT",
        "channel_bed_status": (
            "SEPARATE_VERTICAL_CONTROL_MAJOR_PROFILE_TERRAIN_CEILING_RECONCILED_MINOR_GRAPH_CONSTRAINED_MODELLED"
        ),
        "flow_routing_status": "SLOPE_WEIGHTED_MFD_WITH_UNIT_WEIGHT_PROTECTED_EDGES",
        "generated_drainage_status": (
            "ANALYTICAL_POTENTIAL_ONLY_NOT_ADDED_TO_CURRENT_NETWORK_OR_SETTLEMENT_SCORING"
        ),
        "flood_wetness_channel_basis": (
            "REGISTERED_PROTECTED_NETWORK_PLUS_INHERITED_FLOOD_WETLAND_EVIDENCE"
        ),
        "not_a_surveyed_10m_dem": True,
        "canon_status": recipe.status,
        "source_lineage": dict(source_lineage or {}),
    }
    return PhysicalContext(arrays=arrays, metrics=metrics, lineage=lineage)
