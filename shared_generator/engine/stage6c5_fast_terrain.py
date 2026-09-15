"""Fast, production-safe adapter for Stage 6C.5 terrain refinement.

The authoritative semantics remain :func:`ten_m_tile_engine.engine.refine_terrain`.
This module only replaces its hottest operation (270,400 scalar bicubic calls
for a 50 x 50 parent core plus a ten-cell halo) with a vectorised equivalent.

The adapter deliberately has a narrow fast-path contract:

* the fine window must begin and end on 100 m parent boundaries;
* every parent value in the two-cell interpolation support ring must be finite;
* the supplied parent window must contain that complete support ring.

Anything else is sent to the reference implementation.  Callers can also ask
for an independent reference calculation and fail closed to it if the fast
result is not equivalent.  No fast-path marker is written into the evidence
tile, so successful results retain the reference schema and lineage exactly.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping

import numpy as np
from algorithm_policy import use_optimized

from ten_m_tile_engine import engine as reference
from ten_m_tile_engine.engine import (
    CHILDREN_PER_PARENT,
    FINE_CELL_M,
    PARENT_CELL_M,
    EvidenceTile,
    ParentRasterWindow,
    TerrainRecipe,
    TileSpec,
)


ADAPTER_VERSION = "0.1.0"


@dataclass(frozen=True)
class FastPathEligibility:
    eligible: bool
    reason: str


@dataclass(frozen=True)
class TerrainComparison:
    passed: bool
    exact_array_match: bool
    arrays_within_tolerance: bool
    metadata_within_tolerance: bool
    differences: tuple[str, ...]
    array_max_abs_differences: Mapping[str, float]


def _covered_parent_bounds(spec: TileSpec) -> tuple[int, int, int, int]:
    """Return the parent cells touched by the complete fine window."""

    return reference._parent_bounds_for_tile(spec)


def fast_path_eligibility(parent: ParentRasterWindow, spec: TileSpec) -> FastPathEligibility:
    """Explain whether the vectorised path can preserve reference semantics."""

    if spec.fine_row0 % CHILDREN_PER_PARENT or spec.fine_col0 % CHILDREN_PER_PARENT:
        return FastPathEligibility(False, "fine window is not parent-grid aligned")
    if spec.fine_height % CHILDREN_PER_PARENT or spec.fine_width % CHILDREN_PER_PARENT:
        return FastPathEligibility(False, "fine dimensions are not complete parent blocks")

    row0, col0, row1, col1 = _covered_parent_bounds(spec)
    support_row0, support_col0 = row0 - 2, col0 - 2
    support_row1, support_col1 = row1 + 2, col1 + 2
    local_row0 = support_row0 - parent.global_parent_row0
    local_col0 = support_col0 - parent.global_parent_col0
    local_row1 = support_row1 - parent.global_parent_row0
    local_col1 = support_col1 - parent.global_parent_col0
    data = np.asarray(parent.data)
    if (
        local_row0 < 0
        or local_col0 < 0
        or local_row1 > data.shape[0]
        or local_col1 > data.shape[1]
    ):
        return FastPathEligibility(False, "complete two-parent-cell interpolation support is unavailable")

    support = np.asarray(data[local_row0:local_row1, local_col0:local_col1], dtype=np.float64)
    if not np.isfinite(support).all():
        return FastPathEligibility(False, "interpolation support contains non-finite values")
    nodata = parent.nodata
    if nodata is not None and np.isfinite(float(nodata)) and np.any(support == float(nodata)):
        return FastPathEligibility(False, "interpolation support contains the parent nodata sentinel")
    return FastPathEligibility(True, "complete finite parent-aligned support")


def _catmull_rom_array(
    p0: np.ndarray,
    p1: np.ndarray,
    p2: np.ndarray,
    p3: np.ndarray,
    t: float,
) -> np.ndarray:
    """Elementwise form of the reference Catmull-Rom value expression."""

    return 0.5 * (
        2 * p1
        + (-p0 + p2) * t
        + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t**2
        + (-p0 + 3 * p1 - 3 * p2 + p3) * t**3
    )


def _broad_blocks(parent: ParentRasterWindow, spec: TileSpec) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Vectorise the reference separable bicubic interpolation.

    Returns broad blocks before conservation, target elevations, and the parent
    X/Y gradients.  Shapes are ``(parent_rows, parent_cols, 10, 10)`` for the
    broad blocks and ``(parent_rows, parent_cols)`` for all other arrays.
    """

    row0, col0, row1, col1 = _covered_parent_bounds(spec)
    local_row0 = row0 - 2 - parent.global_parent_row0
    local_col0 = col0 - 2 - parent.global_parent_col0
    local_row1 = row1 + 2 - parent.global_parent_row0
    local_col1 = col1 + 2 - parent.global_parent_col0
    support = np.asarray(
        parent.data[local_row0:local_row1, local_col0:local_col1], dtype=np.float64
    )
    neighbourhoods = np.lib.stride_tricks.sliding_window_view(support, (5, 5))

    # First interpolate along columns for all five supporting rows.  The first
    # five fine centres use offsets [-2,-1,0,1]; the last five use
    # [-1,0,1,2], exactly as floor(parent + child_offset) in the reference.
    horizontal = np.empty((*neighbourhoods.shape[:3], CHILDREN_PER_PARENT), dtype=np.float64)
    for child_col in range(CHILDREN_PER_PARENT):
        start = 0 if child_col < 5 else 1
        t = 0.55 + child_col * 0.1 if child_col < 5 else 0.05 + (child_col - 5) * 0.1
        horizontal[..., child_col] = _catmull_rom_array(
            neighbourhoods[..., start],
            neighbourhoods[..., start + 1],
            neighbourhoods[..., start + 2],
            neighbourhoods[..., start + 3],
            t,
        )

    broad = np.empty(
        (*neighbourhoods.shape[:2], CHILDREN_PER_PARENT, CHILDREN_PER_PARENT),
        dtype=np.float64,
    )
    for child_row in range(CHILDREN_PER_PARENT):
        start = 0 if child_row < 5 else 1
        t = 0.55 + child_row * 0.1 if child_row < 5 else 0.05 + (child_row - 5) * 0.1
        broad[..., child_row, :] = _catmull_rom_array(
            horizontal[..., start, :],
            horizontal[..., start + 1, :],
            horizontal[..., start + 2, :],
            horizontal[..., start + 3, :],
            t,
        )

    target = neighbourhoods[..., 2, 2]
    gx = (neighbourhoods[..., 2, 3] - neighbourhoods[..., 2, 1]) / (2 * PARENT_CELL_M)
    gy = (neighbourhoods[..., 3, 2] - neighbourhoods[..., 1, 2]) / (2 * PARENT_CELL_M)
    return broad, target, gx, gy


def _micro_relief_bases(
    recipe: TerrainRecipe, row0: int, col0: int, height: int, width: int
) -> np.ndarray:
    """Generate the reference zero-mean basis once per parent cell."""

    u = (np.arange(CHILDREN_PER_PARENT, dtype=np.float64) + 0.5) / CHILDREN_PER_PARENT
    uu, vv = np.meshgrid(u, u)
    envelope = uu**2 * (1 - uu) ** 2 * vv**2 * (1 - vv) ** 2
    b1 = envelope * (uu - 0.5)
    b2 = envelope * (vv - 0.5)
    coefficients = np.empty((height, width, 2), dtype=np.float64)
    for row in range(height):
        for col in range(width):
            coefficients[row, col] = reference._seed_pair(recipe.seed, row0 + row, col0 + col)
    bases = (
        coefficients[..., 0, None, None] * b1
        + coefficients[..., 1, None, None] * b2
    )
    bases -= bases.reshape(height, width, -1).mean(axis=2)[..., None, None]
    peak = np.max(np.abs(bases), axis=(-2, -1))
    np.divide(bases, peak[..., None, None], out=bases, where=peak[..., None, None] > 0)
    return bases


def _blocks_to_raster(blocks: np.ndarray) -> np.ndarray:
    rows, cols = blocks.shape[:2]
    return blocks.transpose(0, 2, 1, 3).reshape(
        rows * CHILDREN_PER_PARENT, cols * CHILDREN_PER_PARENT
    )


def _quantize_zero_mean_blocks(
    residual_blocks: np.ndarray, scale: float, nodata_q: int
) -> np.ndarray:
    """Batch the reference integer correction without changing its tie order.

    The common unsaturated case needs at most one adjustment per fine cell.
    It uses the same contiguous 100-value mean, stable error sort and integer
    correction as the scalar routine.  Saturated or exceptional blocks use
    that routine unchanged.  Batches bound transient arrays to 256 parents.
    """

    values = np.asarray(residual_blocks, dtype=np.float64)
    blocks = values.reshape(-1, CHILDREN_PER_PARENT * CHILDREN_PER_PARENT)
    result = np.empty(blocks.shape, dtype=np.int16)
    if not use_optimized("terrain_quantization"):
        for index, block in enumerate(blocks):
            result[index] = reference._quantize_zero_mean(
                block.reshape(CHILDREN_PER_PARENT, CHILDREN_PER_PARENT), scale, nodata_q
            ).ravel()
        return result.reshape(values.shape)
    for start in range(0, len(blocks), 256):
        stop = min(start + 256, len(blocks))
        source = blocks[start:stop]
        if not np.isfinite(scale) or scale == 0 or not np.isfinite(source).all():
            for offset, block in enumerate(source):
                result[start + offset] = reference._quantize_zero_mean(
                    block.reshape(CHILDREN_PER_PARENT, CHILDREN_PER_PARENT), scale, nodata_q
                ).ravel()
            continue
        raw = source / scale
        raw -= raw.mean(axis=1, dtype=np.float64)[:, None]
        eligible = np.all(np.abs(raw) <= 32766.5, axis=1)
        # Avoid converting unbounded values.  Their exact clipping/overflow
        # behaviour remains owned by the reference fallback below.
        selected = np.flatnonzero(eligible)
        if selected.size:
            selected_raw = raw[selected]
            quantized = np.rint(selected_raw).astype(np.int64)
            correction = -quantized.sum(axis=1)
            safe = np.abs(correction) <= quantized.shape[1]
            eligible[selected[~safe]] = False
            selected = selected[safe]
            quantized = quantized[safe]
            correction = correction[safe]
            selected_raw = selected_raw[safe]
            if selected.size:
                error = selected_raw - quantized
                order = np.argsort(
                    np.where(correction[:, None] > 0, -error, error), axis=1, kind="stable"
                )
                adjust = np.arange(quantized.shape[1])[None, :] < np.abs(correction)[:, None]
                adjustment_rows, adjustment_ranks = np.nonzero(adjust)
                quantized[adjustment_rows, order[adjustment_rows, adjustment_ranks]] += np.sign(
                    correction[adjustment_rows]
                )
                if np.any(quantized.sum(axis=1) != 0):
                    raise AssertionError("Quantized residual is not parent-conserving")
                # A collision must still fail at its original block position,
                # so leave colliding blocks to the scalar routine.
                collision = np.any(quantized == nodata_q, axis=1)
                eligible[selected[collision]] = False
                result[start + selected[~collision]] = quantized[~collision].astype(np.int16)
        for offset in np.flatnonzero(~eligible):
            result[start + offset] = reference._quantize_zero_mean(
                source[offset].reshape(CHILDREN_PER_PARENT, CHILDREN_PER_PARENT), scale, nodata_q
            ).ravel()
    return result.reshape(values.shape)


def _reference_style_metadata(
    parent: ParentRasterWindow,
    spec: TileSpec,
    recipe: TerrainRecipe,
    source_hashes: Mapping[str, str],
    elevation: np.ndarray,
    broad_elevation: np.ndarray,
    broad_gx: np.ndarray,
    broad_gy: np.ndarray,
    local_gx: np.ndarray,
    local_gy: np.ndarray,
    conservation_corrections: np.ndarray,
) -> dict[str, Any]:
    """Build metadata using the same calculations and field values as reference."""

    core = spec.core_slice
    core_elevation = elevation[core]
    recovery_errors: list[float] = []
    broad_recovery_errors: list[float] = []
    broad_cosines: list[float] = []
    local_cosines: list[float] = []
    core_broad = broad_elevation[core]
    core_bgx, core_bgy = broad_gx[core], broad_gy[core]
    core_lgx, core_lgy = local_gx[core], local_gy[core]
    for row in range(spec.core_parent_height):
        for col in range(spec.core_parent_width):
            rows = slice(row * 10, (row + 1) * 10)
            cols = slice(col * 10, (col + 1) * 10)
            parent_row = spec.core_parent_row0 + row
            parent_col = spec.core_parent_col0 + col
            target = parent.get(parent_row, parent_col)
            block = core_elevation[rows, cols]
            if np.isfinite(block).all() and np.isfinite(target):
                recovery_errors.append(abs(float(block.mean(dtype=np.float64)) - target))
            broad_block = core_broad[rows, cols]
            if np.isfinite(broad_block).all() and np.isfinite(target):
                broad_recovery_errors.append(
                    abs(float(broad_block.mean(dtype=np.float64)) - target)
                )
            px, py = reference._parent_gradient(parent, parent_row, parent_col)
            parent_magnitude = math.hypot(px, py)
            if parent_magnitude > 1e-10:
                bgx = float(np.nanmean(core_bgx[rows, cols]))
                bgy = float(np.nanmean(core_bgy[rows, cols]))
                lgx = float(np.nanmean(core_lgx[rows, cols]))
                lgy = float(np.nanmean(core_lgy[rows, cols]))
                broad_magnitude = math.hypot(bgx, bgy)
                local_magnitude = math.hypot(lgx, lgy)
                if broad_magnitude > 1e-12:
                    broad_cosines.append(
                        (px * bgx + py * bgy) / (parent_magnitude * broad_magnitude)
                    )
                if local_magnitude > 1e-12:
                    local_cosines.append(
                        (px * lgx + py * lgy) / (parent_magnitude * local_magnitude)
                    )

    metadata = reference._status_metadata(
        spec, parent.grid, recipe, source_hashes, recipe.effective_resolution_m
    )
    metadata.update(
        {
            "layer_kind": "terrain",
            "terrain_semantics": {
                "broad_elevation_10m": "Catmull-Rom parent-terrain surface plus C1 parent-mean conservation bubble, before local relief",
                "broad_gradient_10m": "Finite-difference gradient of the stored broad_elevation_10m band",
                "local_gradient_10m": "Finite-difference gradient of reconstructed modelled 10 m elevation, including constrained micro-relief",
                "downhill_direction": "negative elevation gradient in east/positive-south raster coordinates; aspects clockwise from north",
            },
            "encoding": {
                "elevation_10m": {
                    "logical_dtype": "float32",
                    "formula": "elevation_parent_base_10m + elevation_residual_q * scale",
                    "scale": recipe.elevation_scale_m,
                    "offset": 0.0,
                    "nodata": "NaN",
                },
                "elevation_residual_q": {
                    "dtype": "int16",
                    "scale": recipe.elevation_scale_m,
                    "offset": 0.0,
                    "nodata": recipe.nodata_q,
                },
                "elevation_parent_base_10m": {
                    "dtype": "float64",
                    "scale": 1.0,
                    "offset": 0.0,
                    "nodata": "NaN",
                },
                "broad_elevation_10m": {
                    "dtype": "float32",
                    "scale": 1.0,
                    "offset": 0.0,
                    "nodata": "NaN",
                },
                "broad_gradient_x_10m": {
                    "dtype": "float32",
                    "scale": 1.0,
                    "offset": 0.0,
                    "nodata": "NaN",
                    "units": "m/m",
                },
                "broad_gradient_y_10m": {
                    "dtype": "float32",
                    "scale": 1.0,
                    "offset": 0.0,
                    "nodata": "NaN",
                    "units": "m/m",
                },
                "broad_gradient_magnitude_10m": {
                    "dtype": "float32",
                    "scale": 1.0,
                    "offset": 0.0,
                    "nodata": "NaN",
                    "units": "m/m",
                },
                "broad_downslope_aspect_deg_10m": {
                    "dtype": "float32",
                    "scale": 1.0,
                    "offset": 0.0,
                    "nodata": "NaN",
                    "units": "degrees_clockwise_from_north",
                },
                "local_gradient_x_10m": {
                    "dtype": "float32",
                    "scale": 1.0,
                    "offset": 0.0,
                    "nodata": "NaN",
                    "units": "m/m",
                },
                "local_gradient_y_10m": {
                    "dtype": "float32",
                    "scale": 1.0,
                    "offset": 0.0,
                    "nodata": "NaN",
                    "units": "m/m",
                },
                "local_gradient_magnitude_10m": {
                    "dtype": "float32",
                    "scale": 1.0,
                    "offset": 0.0,
                    "nodata": "NaN",
                    "units": "m/m",
                },
                "local_downslope_aspect_deg_10m": {
                    "dtype": "float32",
                    "scale": 1.0,
                    "offset": 0.0,
                    "nodata": "NaN",
                    "units": "degrees_clockwise_from_north",
                },
            },
            "qa": {
                "parent_aggregation_max_abs_error_m": max(recovery_errors, default=0.0),
                "parent_aggregation_blocks_checked": len(recovery_errors),
                "broad_parent_aggregation_max_abs_error_m": max(
                    broad_recovery_errors, default=0.0
                ),
                "max_prequantization_conservation_correction_m": float(
                    np.max(np.abs(conservation_corrections), initial=0.0)
                ),
                "broad_gradient_direction_min_cosine": min(broad_cosines, default=1.0),
                "broad_gradient_direction_consistent_fraction": float(
                    np.mean(np.asarray(broad_cosines) >= 0.0)
                )
                if broad_cosines
                else 1.0,
                "local_gradient_direction_min_cosine": min(local_cosines, default=1.0),
                "local_gradient_direction_consistent_fraction": float(
                    np.mean(np.asarray(local_cosines) >= 0.0)
                )
                if local_cosines
                else 1.0,
                "exact_grid_nesting": True,
                "core_gradient_valid_with_halo": spec.halo_cells >= 1,
            },
        }
    )
    return metadata


def _refine_vectorised(
    parent: ParentRasterWindow,
    spec: TileSpec,
    recipe: TerrainRecipe,
    source_hashes: Mapping[str, str],
) -> EvidenceTile:
    broad_raw, targets, parent_gx, parent_gy = _broad_blocks(parent, spec)
    u = (np.arange(CHILDREN_PER_PARENT, dtype=np.float64) + 0.5) / CHILDREN_PER_PARENT
    uu, vv = np.meshgrid(u, u)
    correction_weight = uu**2 * (1 - uu) ** 2 * vv**2 * (1 - vv) ** 2
    correction_weight /= correction_weight.mean(dtype=np.float64)

    conservation = targets - broad_raw.reshape(*targets.shape, -1).mean(axis=2)
    maximum_correction = float(np.max(np.abs(conservation), initial=0.0))
    if maximum_correction > recipe.max_conservation_correction_m:
        raise ValueError(
            f"Conservation correction {maximum_correction:.3f} m exceeds fail-closed limit"
        )
    broad_blocks = broad_raw + conservation[..., None, None] * correction_weight

    row0, col0, _, _ = _covered_parent_bounds(spec)
    bases = _micro_relief_bases(recipe, row0, col0, *targets.shape)
    parent_slope = np.hypot(parent_gx, parent_gy)
    amplitude = np.minimum(
        recipe.max_micro_relief_m,
        np.maximum(
            recipe.minimum_micro_relief_m,
            parent_slope * 10.0 * recipe.micro_relief_slope_fraction,
        ),
    )
    model_blocks = broad_blocks + amplitude[..., None, None] * bases
    model_blocks += (
        targets - model_blocks.reshape(*targets.shape, -1).mean(axis=2)
    )[..., None, None]

    quantized = _quantize_zero_mean_blocks(
        model_blocks - targets[..., None, None],
        recipe.elevation_scale_m,
        recipe.nodata_q,
    )

    base = _blocks_to_raster(
        np.broadcast_to(targets[..., None, None], model_blocks.shape)
    ).copy()
    q_out = _blocks_to_raster(quantized)
    broad_elevation = _blocks_to_raster(broad_blocks)
    elevation = base + q_out.astype(np.float64) * recipe.elevation_scale_m

    broad_gx = np.gradient(broad_elevation, FINE_CELL_M, axis=1)
    broad_gy = np.gradient(broad_elevation, FINE_CELL_M, axis=0)
    local_gx = np.gradient(elevation, FINE_CELL_M, axis=1)
    local_gy = np.gradient(elevation, FINE_CELL_M, axis=0)
    broad_magnitude = np.hypot(broad_gx, broad_gy)
    local_magnitude = np.hypot(local_gx, local_gy)
    broad_aspect = reference._aspect_from_gradient(broad_gx, broad_gy)
    local_aspect = reference._aspect_from_gradient(local_gx, local_gy)

    metadata = _reference_style_metadata(
        parent,
        spec,
        recipe,
        source_hashes,
        elevation,
        broad_elevation,
        broad_gx,
        broad_gy,
        local_gx,
        local_gy,
        conservation,
    )
    arrays = {
        "elevation_10m": elevation.astype(np.float32),
        "elevation_parent_base_10m": base,
        "elevation_residual_q": q_out,
        "broad_elevation_10m": broad_elevation.astype(np.float32),
        "broad_gradient_x_10m": broad_gx.astype(np.float32),
        "broad_gradient_y_10m": broad_gy.astype(np.float32),
        "broad_gradient_magnitude_10m": broad_magnitude.astype(np.float32),
        "broad_downslope_aspect_deg_10m": broad_aspect.astype(np.float32),
        "local_gradient_x_10m": local_gx.astype(np.float32),
        "local_gradient_y_10m": local_gy.astype(np.float32),
        "local_gradient_magnitude_10m": local_magnitude.astype(np.float32),
        "local_downslope_aspect_deg_10m": local_aspect.astype(np.float32),
    }
    encoded = {key: value for key, value in arrays.items() if key != "elevation_10m"}
    return EvidenceTile(spec, parent.grid, arrays, encoded, metadata)


def _circular_max_difference(left: np.ndarray, right: np.ndarray) -> float:
    delta = np.abs(np.asarray(left, dtype=np.float64) - np.asarray(right, dtype=np.float64))
    delta = np.minimum(delta, 360.0 - delta)
    return float(np.nanmax(delta, initial=0.0))


def _compare_metadata(
    left: Any,
    right: Any,
    path: str,
    differences: list[str],
    *,
    atol: float,
    rtol: float,
) -> None:
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        if set(left) != set(right):
            differences.append(f"{path}: mapping keys differ")
            return
        for key in sorted(left):
            _compare_metadata(
                left[key], right[key], f"{path}.{key}", differences, atol=atol, rtol=rtol
            )
        return
    if isinstance(left, (list, tuple)) and isinstance(right, (list, tuple)):
        if len(left) != len(right):
            differences.append(f"{path}: sequence lengths differ")
            return
        for index, (left_item, right_item) in enumerate(zip(left, right)):
            _compare_metadata(
                left_item,
                right_item,
                f"{path}[{index}]",
                differences,
                atol=atol,
                rtol=rtol,
            )
        return
    numeric = (
        isinstance(left, (int, float, np.number))
        and not isinstance(left, (bool, np.bool_))
        and isinstance(right, (int, float, np.number))
        and not isinstance(right, (bool, np.bool_))
    )
    if numeric:
        if not math.isclose(float(left), float(right), abs_tol=atol, rel_tol=rtol):
            differences.append(f"{path}: {left!r} != {right!r}")
    elif left != right:
        differences.append(f"{path}: {left!r} != {right!r}")


def compare_terrain_tiles(
    trusted: EvidenceTile,
    candidate: EvidenceTile,
    *,
    float_atol: float = 1e-5,
    float_rtol: float = 1e-6,
    aspect_atol_degrees: float = 1e-3,
    metadata_atol: float = 1e-10,
    metadata_rtol: float = 1e-10,
) -> TerrainComparison:
    """Compare a candidate tile against the reference with explicit rules.

    Integer/quantised arrays, shapes, dtypes, keys, the grid and tile spec must
    be exact.  Floating bands use the stated numerical tolerance; aspect uses
    circular degrees.  Metadata structure and non-numeric values are exact,
    while numeric QA values use the metadata tolerance.
    """

    differences: list[str] = []
    if trusted.spec != candidate.spec:
        differences.append("spec differs")
    if trusted.grid != candidate.grid:
        differences.append("grid differs")
    array_keys_match = set(trusted.arrays) == set(candidate.arrays)
    encoded_keys_match = set(trusted.encoded_arrays) == set(candidate.encoded_arrays)
    if not array_keys_match:
        differences.append("array keys differ")
    if not encoded_keys_match:
        differences.append("encoded array keys differ")

    exact_arrays = True
    within_tolerance = True
    maxima: dict[str, float] = {}
    for name in sorted(set(trusted.arrays) & set(candidate.arrays)):
        left, right = np.asarray(trusted.arrays[name]), np.asarray(candidate.arrays[name])
        if left.shape != right.shape or left.dtype != right.dtype:
            differences.append(
                f"array {name}: shape/dtype {left.shape}/{left.dtype} != {right.shape}/{right.dtype}"
            )
            exact_arrays = False
            within_tolerance = False
            continue
        is_exact = bool(np.array_equal(left, right, equal_nan=True))
        exact_arrays &= is_exact
        if np.issubdtype(left.dtype, np.integer):
            maximum = float(np.max(np.abs(left.astype(np.int64) - right.astype(np.int64)), initial=0))
            maxima[name] = maximum
            if not is_exact:
                differences.append(f"array {name}: integer values differ (max {maximum:g})")
                within_tolerance = False
            continue
        if "aspect_deg" in name:
            maximum = _circular_max_difference(left, right)
            equivalent = maximum <= aspect_atol_degrees and np.array_equal(
                np.isnan(left), np.isnan(right)
            )
        else:
            delta = np.abs(left.astype(np.float64) - right.astype(np.float64))
            maximum = float(np.nanmax(delta, initial=0.0))
            equivalent = bool(
                np.allclose(left, right, atol=float_atol, rtol=float_rtol, equal_nan=True)
            )
        maxima[name] = maximum
        if not equivalent:
            differences.append(f"array {name}: outside tolerance (max {maximum:g})")
            within_tolerance = False

    metadata_differences: list[str] = []
    _compare_metadata(
        trusted.metadata,
        candidate.metadata,
        "metadata",
        metadata_differences,
        atol=metadata_atol,
        rtol=metadata_rtol,
    )
    differences.extend(metadata_differences)
    metadata_ok = not metadata_differences
    passed = (
        within_tolerance
        and metadata_ok
        and array_keys_match
        and encoded_keys_match
        and trusted.spec == candidate.spec
        and trusted.grid == candidate.grid
    )
    return TerrainComparison(
        passed,
        exact_arrays,
        within_tolerance,
        metadata_ok,
        tuple(differences),
        maxima,
    )


def refine_terrain_fast(
    parent: ParentRasterWindow,
    spec: TileSpec,
    recipe: TerrainRecipe,
    source_hashes: Mapping[str, str],
) -> EvidenceTile:
    """Use the vectorised path when safe, otherwise use the reference path."""

    if not fast_path_eligibility(parent, spec).eligible:
        return reference.refine_terrain(parent, spec, recipe, source_hashes)
    return _refine_vectorised(parent, spec, recipe, source_hashes)


def refine_terrain_safe(
    parent: ParentRasterWindow,
    spec: TileSpec,
    recipe: TerrainRecipe,
    source_hashes: Mapping[str, str],
    *,
    verify_reference: bool = False,
    fallback_on_mismatch: bool = True,
) -> EvidenceTile:
    """Production entry point with optional independent reference verification.

    ``verify_reference`` is intended for a first tile, a deterministic sample,
    or a new recipe/source version.  Recomputing every tile would deliberately
    discard the speed gain.  If verification fails, the default is to return
    the trusted reference result; disabling fallback raises ``ValueError``.
    """

    eligibility = fast_path_eligibility(parent, spec)
    if not eligibility.eligible:
        return reference.refine_terrain(parent, spec, recipe, source_hashes)
    candidate = _refine_vectorised(parent, spec, recipe, source_hashes)
    if not verify_reference:
        return candidate
    trusted = reference.refine_terrain(parent, spec, recipe, source_hashes)
    comparison = compare_terrain_tiles(trusted, candidate)
    if comparison.passed:
        return candidate
    if fallback_on_mismatch:
        return trusted
    raise ValueError("Fast terrain result failed reference comparison: " + "; ".join(comparison.differences))


__all__ = [
    "ADAPTER_VERSION",
    "FastPathEligibility",
    "TerrainComparison",
    "compare_terrain_tiles",
    "fast_path_eligibility",
    "refine_terrain_fast",
    "refine_terrain_safe",
]
