"""Deterministic sparse 100 m -> 10 m evidence-tile engine.

The nominal 10 m grid is exactly nested in the parent grid (10 x 10 children
per parent).  A generated tile covers only a requested parent-aligned core plus
a fine-cell halo.  Nothing in this module implies that a modelled child field
contains genuine 10 m observations: ``effective_resolution_m`` and the two
review-status fields are mandatory metadata.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from hashlib import sha256
import json
import math
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

import numpy as np


ENGINE_VERSION = "0.1.0"
FINE_CELL_M = 10.0
PARENT_CELL_M = 100.0
CHILDREN_PER_PARENT = 10


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _jsonable(value[k]) for k in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, np.generic):
        return value.item()
    return value


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        _jsonable(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def canonical_hash(value: Any) -> str:
    return sha256(canonical_json(value)).hexdigest()


def hash_file(path: str | Path, block_size: int = 8 << 20) -> str:
    digest = sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(block_size):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class GridSpec:
    """Local grid anchored north-west, with raster Y increasing southward."""

    origin_x_m: float
    origin_y_m: float
    crs: str = "LOCAL_CARTESIAN_M_NO_EPSG"
    parent_cell_size_m: float = PARENT_CELL_M
    fine_cell_size_m: float = FINE_CELL_M

    def __post_init__(self) -> None:
        ratio = self.parent_cell_size_m / self.fine_cell_size_m
        if not math.isclose(ratio, CHILDREN_PER_PARENT, abs_tol=1e-12):
            raise ValueError("The prototype requires exact 100 m / 10 m nesting")

    def fine_center(self, global_row: np.ndarray, global_col: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        x = self.origin_x_m + (global_col + 0.5) * self.fine_cell_size_m
        y = self.origin_y_m + (global_row + 0.5) * self.fine_cell_size_m
        return x, y

    def fine_transform(self, fine_row0: int, fine_col0: int) -> tuple[float, float, float, float, float, float]:
        return (
            self.fine_cell_size_m,
            0.0,
            self.origin_x_m + fine_col0 * self.fine_cell_size_m,
            0.0,
            self.fine_cell_size_m,
            self.origin_y_m + fine_row0 * self.fine_cell_size_m,
        )


@dataclass(frozen=True)
class ParentRasterWindow:
    data: np.ndarray
    global_parent_row0: int
    global_parent_col0: int
    grid: GridSpec
    nodata: float | int | None = np.nan

    def __post_init__(self) -> None:
        if np.asarray(self.data).ndim != 2:
            raise ValueError("ParentRasterWindow.data must be two-dimensional")

    @property
    def shape(self) -> tuple[int, int]:
        return tuple(np.asarray(self.data).shape)  # type: ignore[return-value]

    def get(self, global_row: int, global_col: int) -> float:
        row = global_row - self.global_parent_row0
        col = global_col - self.global_parent_col0
        if row < 0 or col < 0 or row >= self.shape[0] or col >= self.shape[1]:
            return float("nan")
        return float(np.asarray(self.data)[row, col])


@dataclass(frozen=True)
class TileSpec:
    tile_id: str
    core_parent_row0: int
    core_parent_col0: int
    core_parent_height: int
    core_parent_width: int
    halo_cells: int = 0

    def __post_init__(self) -> None:
        if self.core_parent_height <= 0 or self.core_parent_width <= 0:
            raise ValueError("Tile core dimensions must be positive")
        if self.halo_cells < 0:
            raise ValueError("halo_cells cannot be negative")

    @property
    def fine_row0(self) -> int:
        return self.core_parent_row0 * CHILDREN_PER_PARENT - self.halo_cells

    @property
    def fine_col0(self) -> int:
        return self.core_parent_col0 * CHILDREN_PER_PARENT - self.halo_cells

    @property
    def fine_height(self) -> int:
        return self.core_parent_height * CHILDREN_PER_PARENT + 2 * self.halo_cells

    @property
    def fine_width(self) -> int:
        return self.core_parent_width * CHILDREN_PER_PARENT + 2 * self.halo_cells

    @property
    def core_slice(self) -> tuple[slice, slice]:
        h = self.halo_cells
        return (
            slice(h, h + self.core_parent_height * CHILDREN_PER_PARENT),
            slice(h, h + self.core_parent_width * CHILDREN_PER_PARENT),
        )

    def global_fine_indices(self) -> tuple[np.ndarray, np.ndarray]:
        rows = self.fine_row0 + np.arange(self.fine_height, dtype=np.int64)
        cols = self.fine_col0 + np.arange(self.fine_width, dtype=np.int64)
        return rows, cols


@dataclass(frozen=True)
class ContinuousRecipe:
    field_name: str
    residual_scale: float
    effective_resolution_m: float
    seed: str = "diadem-10m-v1"
    residual_amplitude: float = 0.0
    dtype: str = "int16"
    nodata_q: int = -32768

    def __post_init__(self) -> None:
        if self.residual_scale <= 0 or self.effective_resolution_m <= 0:
            raise ValueError("Scales and effective resolution must be positive")
        if self.dtype != "int16":
            raise ValueError("Prototype residual encoding is int16")


@dataclass(frozen=True)
class TerrainRecipe:
    effective_resolution_m: float
    elevation_scale_m: float = 0.01
    max_micro_relief_m: float = 1.0
    micro_relief_slope_fraction: float = 0.20
    minimum_micro_relief_m: float = 0.0
    max_conservation_correction_m: float = 50.0
    seed: str = "diadem-terrain-10m-v1"
    nodata_q: int = -32768

    def __post_init__(self) -> None:
        if self.effective_resolution_m <= 0 or self.elevation_scale_m <= 0:
            raise ValueError("Resolution and quantization scale must be positive")
        if (
            self.max_micro_relief_m < 0
            or self.micro_relief_slope_fraction < 0
            or self.max_conservation_correction_m <= 0
        ):
            raise ValueError("Micro-relief controls cannot be negative")


@dataclass(frozen=True)
class CategoricalRecipe:
    field_name: str
    effective_resolution_m: float
    nodata_class: int = -32768
    probability_tolerance: float = 1e-7
    max_projection_iterations: int = 500


@dataclass(frozen=True)
class PolygonFeature:
    feature_id: str
    class_id: int
    exterior_xy: tuple[tuple[float, float], ...]
    holes_xy: tuple[tuple[tuple[float, float], ...], ...] = ()
    priority: int = 0


@dataclass
class EvidenceTile:
    spec: TileSpec
    grid: GridSpec
    arrays: dict[str, np.ndarray]
    encoded_arrays: dict[str, np.ndarray]
    metadata: dict[str, Any]

    def save(self, directory: str | Path, compact: bool = True) -> tuple[Path, Path]:
        """Write a data-only bundle atomically; no visualization is embedded."""

        target = Path(directory)
        target.mkdir(parents=True, exist_ok=True)
        arrays = self.encoded_arrays if compact else self.arrays
        array_path = target / f"{self.spec.tile_id}.npz"
        meta_path = target / f"{self.spec.tile_id}.json"
        tmp_array = array_path.with_suffix(".npz.tmp")
        tmp_meta = meta_path.with_suffix(".json.tmp")
        with tmp_array.open("wb") as handle:
            np.savez_compressed(handle, **arrays)
            handle.flush()
        meta = dict(self.metadata)
        meta["stored_arrays"] = sorted(arrays)
        meta["compact_storage"] = bool(compact)
        meta["visualization_embedded"] = False
        tmp_meta.write_bytes(canonical_json(meta))
        tmp_array.replace(array_path)
        tmp_meta.replace(meta_path)
        return array_path, meta_path


def _status_metadata(
    spec: TileSpec,
    grid: GridSpec,
    recipe: Any,
    source_hashes: Mapping[str, str],
    effective_resolution_m: float,
) -> dict[str, Any]:
    recipe_value = asdict(recipe) if hasattr(recipe, "__dataclass_fields__") else dict(recipe)
    return {
        "schema": "diadem.sparse-evidence-tile/0.1",
        "engine_version": ENGINE_VERSION,
        "tile_id": spec.tile_id,
        "cell_size_m": FINE_CELL_M,
        "model_resolution_m": FINE_CELL_M,
        "physical_source_resolution_m": float(effective_resolution_m),
        "effective_evidence_resolution_m": float(effective_resolution_m),
        "effective_resolution_m": float(effective_resolution_m),
        "effective_resolution_definition": "Backward-compatible alias of effective_evidence_resolution_m; not the model grid spacing",
        "resolution_status": "MODELLED_10M",
        "review_status": "DERIVED_REVIEW_ONLY",
        "source_hashes": dict(sorted(source_hashes.items())),
        "recipe": recipe_value,
        "recipe_hash": canonical_hash(recipe_value),
        "halo_cells": spec.halo_cells,
        "core_parent_window": {
            "row0": spec.core_parent_row0,
            "col0": spec.core_parent_col0,
            "height": spec.core_parent_height,
            "width": spec.core_parent_width,
        },
        "fine_window": {
            "row0": spec.fine_row0,
            "col0": spec.fine_col0,
            "height": spec.fine_height,
            "width": spec.fine_width,
        },
        "transform": grid.fine_transform(spec.fine_row0, spec.fine_col0),
        "crs": grid.crs,
    }


def _is_nodata(value: float, nodata: float | int | None) -> bool:
    if not np.isfinite(value):
        return True
    return nodata is not None and np.isfinite(float(nodata)) and value == float(nodata)


def _parent_bounds_for_tile(spec: TileSpec) -> tuple[int, int, int, int]:
    row0 = math.floor(spec.fine_row0 / CHILDREN_PER_PARENT)
    col0 = math.floor(spec.fine_col0 / CHILDREN_PER_PARENT)
    row1 = math.ceil((spec.fine_row0 + spec.fine_height) / CHILDREN_PER_PARENT)
    col1 = math.ceil((spec.fine_col0 + spec.fine_width) / CHILDREN_PER_PARENT)
    return row0, col0, row1, col1


def _block_crop(
    spec: TileSpec, parent_row: int, parent_col: int
) -> tuple[slice, slice, slice, slice] | None:
    global_r0 = parent_row * CHILDREN_PER_PARENT
    global_c0 = parent_col * CHILDREN_PER_PARENT
    out_r0 = max(global_r0, spec.fine_row0)
    out_c0 = max(global_c0, spec.fine_col0)
    out_r1 = min(global_r0 + CHILDREN_PER_PARENT, spec.fine_row0 + spec.fine_height)
    out_c1 = min(global_c0 + CHILDREN_PER_PARENT, spec.fine_col0 + spec.fine_width)
    if out_r0 >= out_r1 or out_c0 >= out_c1:
        return None
    tile_rows = slice(out_r0 - spec.fine_row0, out_r1 - spec.fine_row0)
    tile_cols = slice(out_c0 - spec.fine_col0, out_c1 - spec.fine_col0)
    block_rows = slice(out_r0 - global_r0, out_r1 - global_r0)
    block_cols = slice(out_c0 - global_c0, out_c1 - global_c0)
    return tile_rows, tile_cols, block_rows, block_cols


def _seed_pair(seed: str, row: int, col: int) -> tuple[float, float]:
    digest = sha256(f"{seed}:{row}:{col}".encode("utf-8")).digest()
    a = int.from_bytes(digest[:8], "little") / (2**64 - 1)
    b = int.from_bytes(digest[8:16], "little") / (2**64 - 1)
    return 2.0 * a - 1.0, 2.0 * b - 1.0


def _zero_mean_basis(seed: str, row: int, col: int) -> np.ndarray:
    u = (np.arange(CHILDREN_PER_PARENT, dtype=np.float64) + 0.5) / CHILDREN_PER_PARENT
    uu, vv = np.meshgrid(u, u)
    # The u^2(1-u)^2 v^2(1-v)^2 envelope and its first derivative vanish
    # on every parent-cell edge.  Multiplication by an odd centred mode gives
    # a discrete zero mean without introducing value or gradient steps.
    envelope = uu**2 * (1 - uu) ** 2 * vv**2 * (1 - vv) ** 2
    b1 = envelope * (uu - 0.5)
    b2 = envelope * (vv - 0.5)
    a, b = _seed_pair(seed, row, col)
    result = a * b1 + b * b2
    result -= result.mean(dtype=np.float64)
    peak = float(np.max(np.abs(result)))
    return result / peak if peak > 0 else result


def _quantize_zero_mean(residual: np.ndarray, scale: float, nodata_q: int) -> np.ndarray:
    raw = np.asarray(residual, dtype=np.float64) / scale
    raw -= raw.mean(dtype=np.float64)
    q = np.rint(raw).astype(np.int64)
    q = np.clip(q, -32767, 32767)
    correction = -int(q.sum())
    if correction:
        error = raw - q
        order = np.argsort(-error if correction > 0 else error, axis=None, kind="stable")
        step = 1 if correction > 0 else -1
        remaining = abs(correction)
        cursor = 0
        while remaining:
            index = np.unravel_index(int(order[cursor % order.size]), q.shape)
            proposed = q[index] + step
            if -32767 <= proposed <= 32767:
                q[index] = proposed
                remaining -= 1
            cursor += 1
            if cursor > order.size * 65536:
                raise OverflowError("Unable to enforce a zero-sum quantized residual")
    if int(q.sum()) != 0:
        raise AssertionError("Quantized residual is not parent-conserving")
    result = q.astype(np.int16)
    if np.any(result == nodata_q):
        raise ValueError("Quantized values collide with nodata sentinel")
    return result


FineEvidenceProvider = Callable[[int, int, np.ndarray, np.ndarray, float], np.ndarray]


def refine_continuous(
    parent: ParentRasterWindow,
    spec: TileSpec,
    recipe: ContinuousRecipe,
    source_hashes: Mapping[str, str],
    evidence_provider: FineEvidenceProvider | None = None,
) -> EvidenceTile:
    shape = (spec.fine_height, spec.fine_width)
    base = np.full(shape, np.nan, dtype=np.float64)
    q_out = np.full(shape, recipe.nodata_q, dtype=np.int16)
    row0, col0, row1, col1 = _parent_bounds_for_tile(spec)
    for pr in range(row0, row1):
        for pc in range(col0, col1):
            crop = _block_crop(spec, pr, pc)
            if crop is None:
                continue
            value = parent.get(pr, pc)
            if _is_nodata(value, parent.nodata):
                continue
            global_rows = pr * 10 + np.arange(10)
            global_cols = pc * 10 + np.arange(10)
            rr, cc = np.meshgrid(global_rows, global_cols, indexing="ij")
            x, y = parent.grid.fine_center(rr, cc)
            if evidence_provider is None:
                raw = value + recipe.residual_amplitude * _zero_mean_basis(recipe.seed, pr, pc)
            else:
                raw = np.asarray(evidence_provider(pr, pc, x, y, value), dtype=np.float64)
                if raw.shape != (10, 10):
                    raise ValueError("Evidence provider must return a 10 x 10 block")
            residual = raw - raw.mean(dtype=np.float64)
            q = _quantize_zero_mean(residual, recipe.residual_scale, recipe.nodata_q)
            tr, tc, br, bc = crop
            base[tr, tc] = value
            q_out[tr, tc] = q[br, bc]
    decoded = base.astype(np.float64) + np.where(q_out == recipe.nodata_q, np.nan, q_out) * recipe.residual_scale
    core = spec.core_slice
    errors: list[float] = []
    core_data = decoded[core]
    for r in range(spec.core_parent_height):
        for c in range(spec.core_parent_width):
            block = core_data[r * 10 : (r + 1) * 10, c * 10 : (c + 1) * 10]
            target = parent.get(spec.core_parent_row0 + r, spec.core_parent_col0 + c)
            if np.isfinite(block).all() and np.isfinite(target):
                errors.append(abs(float(block.mean(dtype=np.float64)) - target))
    metadata = _status_metadata(spec, parent.grid, recipe, source_hashes, recipe.effective_resolution_m)
    metadata.update(
        {
            "layer_kind": "continuous",
            "encoding": {
                recipe.field_name: {
                    "logical_dtype": "float32",
                    "formula": f"{recipe.field_name}_parent_base_10m + {recipe.field_name}_residual_q * scale",
                    "scale": recipe.residual_scale,
                    "offset": 0.0,
                    "nodata": "NaN",
                },
                f"{recipe.field_name}_residual_q": {
                    "dtype": "int16",
                    "scale": recipe.residual_scale,
                    "offset": 0.0,
                    "nodata": recipe.nodata_q,
                },
                f"{recipe.field_name}_parent_base_10m": {
                    "dtype": "float64",
                    "scale": 1.0,
                    "offset": 0.0,
                    "nodata": "NaN",
                },
            },
            "qa": {
                "parent_aggregation_max_abs_error": max(errors, default=0.0),
                "parent_aggregation_blocks_checked": len(errors),
                "exact_grid_nesting": True,
            },
        }
    )
    name = recipe.field_name
    arrays = {
        name: decoded.astype(np.float32),
        f"{name}_parent_base_10m": base,
        f"{name}_residual_q": q_out,
    }
    encoded = {
        f"{name}_parent_base_10m": base,
        f"{name}_residual_q": q_out,
    }
    return EvidenceTile(spec, parent.grid, arrays, encoded, metadata)


def _parent_gradient(parent: ParentRasterWindow, row: int, col: int) -> tuple[float, float]:
    z = parent.get(row, col)
    west, east = parent.get(row, col - 1), parent.get(row, col + 1)
    north, south = parent.get(row - 1, col), parent.get(row + 1, col)
    if np.isfinite(west) and np.isfinite(east):
        gx = (east - west) / (2 * PARENT_CELL_M)
    elif np.isfinite(east):
        gx = (east - z) / PARENT_CELL_M
    elif np.isfinite(west):
        gx = (z - west) / PARENT_CELL_M
    else:
        gx = 0.0
    if np.isfinite(north) and np.isfinite(south):
        gy = (south - north) / (2 * PARENT_CELL_M)
    elif np.isfinite(north):
        gy = (z - north) / PARENT_CELL_M
    elif np.isfinite(south):
        gy = (south - z) / PARENT_CELL_M
    else:
        gy = 0.0
    return gx, gy


def _bilinear_parent_value(parent: ParentRasterWindow, row_pos: float, col_pos: float, fallback: float) -> float:
    r0, c0 = math.floor(row_pos), math.floor(col_pos)
    dr, dc = row_pos - r0, col_pos - c0
    values = np.array(
        [
            [parent.get(r0, c0), parent.get(r0, c0 + 1)],
            [parent.get(r0 + 1, c0), parent.get(r0 + 1, c0 + 1)],
        ],
        dtype=np.float64,
    )
    weights = np.array([[(1 - dr) * (1 - dc), (1 - dr) * dc], [dr * (1 - dc), dr * dc]])
    valid = np.isfinite(values)
    if not valid.any():
        return fallback
    return float((values[valid] * weights[valid]).sum() / weights[valid].sum())


def _bilinear_parent_gradient(parent: ParentRasterWindow, row_pos: float, col_pos: float) -> tuple[float, float]:
    r0, c0 = math.floor(row_pos), math.floor(col_pos)
    dr, dc = row_pos - r0, col_pos - c0
    gx = gy = total = 0.0
    for rr, wr in ((r0, 1 - dr), (r0 + 1, dr)):
        for cc, wc in ((c0, 1 - dc), (c0 + 1, dc)):
            weight = wr * wc
            px, py = _parent_gradient(parent, rr, cc)
            if np.isfinite(px) and np.isfinite(py):
                gx += px * weight
                gy += py * weight
                total += weight
    return (gx / total, gy / total) if total else (0.0, 0.0)


def _catmull_rom(values: Sequence[float], t: float) -> tuple[float, float]:
    p0, p1, p2, p3 = (float(v) for v in values)
    value = 0.5 * (
        2 * p1
        + (-p0 + p2) * t
        + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t**2
        + (-p0 + 3 * p1 - 3 * p2 + p3) * t**3
    )
    derivative = 0.5 * (
        (-p0 + p2)
        + 2 * (2 * p0 - 5 * p1 + 4 * p2 - p3) * t
        + 3 * (-p0 + 3 * p1 - 3 * p2 + p3) * t**2
    )
    return value, derivative


def _bicubic_parent_value_gradient(
    parent: ParentRasterWindow, row_pos: float, col_pos: float, fallback: float
) -> tuple[float, float, float]:
    """Catmull-Rom broad surface and analytic world-coordinate gradient."""

    r1, c1 = math.floor(row_pos), math.floor(col_pos)
    tr, tc = row_pos - r1, col_pos - c1
    samples = np.array(
        [[parent.get(rr, cc) for cc in range(c1 - 1, c1 + 3)] for rr in range(r1 - 1, r1 + 3)],
        dtype=np.float64,
    )
    if not np.isfinite(samples).all():
        value = _bilinear_parent_value(parent, row_pos, col_pos, fallback)
        gx, gy = _bilinear_parent_gradient(parent, row_pos, col_pos)
        return value, gx, gy
    row_values = np.empty(4, dtype=np.float64)
    row_dx = np.empty(4, dtype=np.float64)
    for index in range(4):
        row_values[index], row_dx[index] = _catmull_rom(samples[index], tc)
    value, dz_drow = _catmull_rom(row_values, tr)
    dz_dcol, _ = _catmull_rom(row_dx, tr)
    return value, dz_dcol / PARENT_CELL_M, dz_drow / PARENT_CELL_M


def _aspect_from_gradient(gx: np.ndarray, gy: np.ndarray) -> np.ndarray:
    # Raster Y is positive south.  Downslope east=-gx and north=+gy.
    return (np.degrees(np.arctan2(-gx, gy)) + 360.0) % 360.0


def refine_terrain(
    parent: ParentRasterWindow,
    spec: TileSpec,
    recipe: TerrainRecipe,
    source_hashes: Mapping[str, str],
) -> EvidenceTile:
    shape = (spec.fine_height, spec.fine_width)
    base = np.full(shape, np.nan, dtype=np.float64)
    q_out = np.full(shape, recipe.nodata_q, dtype=np.int16)
    broad_elevation = np.full(shape, np.nan, dtype=np.float64)
    u = (np.arange(10, dtype=np.float64) + 0.5) / 10
    uu, vv = np.meshgrid(u, u)
    # Compact C1 bubble: value and first derivative are zero at all cell edges.
    correction_weight = uu**2 * (1 - uu) ** 2 * vv**2 * (1 - vv) ** 2
    correction_weight /= correction_weight.mean(dtype=np.float64)
    conservation_corrections: list[float] = []
    row0, col0, row1, col1 = _parent_bounds_for_tile(spec)
    for pr in range(row0, row1):
        for pc in range(col0, col1):
            crop = _block_crop(spec, pr, pc)
            if crop is None:
                continue
            target = parent.get(pr, pc)
            if _is_nodata(target, parent.nodata):
                continue
            raw = np.empty((10, 10), dtype=np.float64)
            for sr in range(10):
                for sc in range(10):
                    # Parent centres are at integer coordinates; fine centres span +/-0.45.
                    rp = pr + (sr + 0.5) / 10 - 0.5
                    cp = pc + (sc + 0.5) / 10 - 0.5
                    raw[sr, sc], _, _ = _bicubic_parent_value_gradient(parent, rp, cp, target)
            # The compact bump corrects the parent mean while remaining zero on
            # theoretical parent-cell boundaries, avoiding a tile-boundary seam.
            conservation_correction = target - raw.mean(dtype=np.float64)
            if abs(conservation_correction) > recipe.max_conservation_correction_m:
                raise ValueError(
                    f"Conservation correction {conservation_correction:.3f} m exceeds fail-closed limit "
                    f"at parent ({pr}, {pc})"
                )
            conservation_corrections.append(abs(conservation_correction))
            raw += conservation_correction * correction_weight
            broad_block = raw.copy()
            parent_gx, parent_gy = _parent_gradient(parent, pr, pc)
            parent_slope = math.hypot(parent_gx, parent_gy)
            amplitude = min(
                recipe.max_micro_relief_m,
                max(recipe.minimum_micro_relief_m, parent_slope * 10.0 * recipe.micro_relief_slope_fraction),
            )
            raw += amplitude * _zero_mean_basis(recipe.seed, pr, pc)
            raw += target - raw.mean(dtype=np.float64)
            q = _quantize_zero_mean(raw - target, recipe.elevation_scale_m, recipe.nodata_q)
            tr, tc, br, bc = crop
            base[tr, tc] = target
            q_out[tr, tc] = q[br, bc]
            broad_elevation[tr, tc] = broad_block[br, bc]

    elevation = base.astype(np.float64) + np.where(q_out == recipe.nodata_q, np.nan, q_out) * recipe.elevation_scale_m
    # Both gradient families are derivatives of the actual stored surfaces.
    # Halo makes these finite differences valid throughout the parent-aligned core.
    broad_gx = np.gradient(broad_elevation, FINE_CELL_M, axis=1)
    broad_gy = np.gradient(broad_elevation, FINE_CELL_M, axis=0)
    local_gx = np.gradient(elevation, FINE_CELL_M, axis=1)
    local_gy = np.gradient(elevation, FINE_CELL_M, axis=0)
    broad_mag = np.hypot(broad_gx, broad_gy)
    local_mag = np.hypot(local_gx, local_gy)
    broad_aspect = _aspect_from_gradient(broad_gx, broad_gy)
    local_aspect = _aspect_from_gradient(local_gx, local_gy)

    core = spec.core_slice
    core_elevation = elevation[core]
    recovery_errors: list[float] = []
    broad_recovery_errors: list[float] = []
    broad_cosines: list[float] = []
    local_cosines: list[float] = []
    for r in range(spec.core_parent_height):
        for c in range(spec.core_parent_width):
            rs, cs = slice(r * 10, (r + 1) * 10), slice(c * 10, (c + 1) * 10)
            block = core_elevation[rs, cs]
            pr, pc = spec.core_parent_row0 + r, spec.core_parent_col0 + c
            target = parent.get(pr, pc)
            if np.isfinite(block).all() and np.isfinite(target):
                recovery_errors.append(abs(float(block.mean(dtype=np.float64)) - target))
            broad_block = broad_elevation[core][rs, cs]
            if np.isfinite(broad_block).all() and np.isfinite(target):
                broad_recovery_errors.append(abs(float(broad_block.mean(dtype=np.float64)) - target))
            px, py = _parent_gradient(parent, pr, pc)
            pmag = math.hypot(px, py)
            if pmag > 1e-10:
                bgx = float(np.nanmean(broad_gx[core][rs, cs]))
                bgy = float(np.nanmean(broad_gy[core][rs, cs]))
                lgx = float(np.nanmean(local_gx[core][rs, cs]))
                lgy = float(np.nanmean(local_gy[core][rs, cs]))
                bmag, lmag = math.hypot(bgx, bgy), math.hypot(lgx, lgy)
                if bmag > 1e-12:
                    broad_cosines.append((px * bgx + py * bgy) / (pmag * bmag))
                if lmag > 1e-12:
                    local_cosines.append((px * lgx + py * lgy) / (pmag * lmag))

    metadata = _status_metadata(spec, parent.grid, recipe, source_hashes, recipe.effective_resolution_m)
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
                "elevation_parent_base_10m": {"dtype": "float64", "scale": 1.0, "offset": 0.0, "nodata": "NaN"},
                "broad_elevation_10m": {"dtype": "float32", "scale": 1.0, "offset": 0.0, "nodata": "NaN"},
                "broad_gradient_x_10m": {"dtype": "float32", "scale": 1.0, "offset": 0.0, "nodata": "NaN", "units": "m/m"},
                "broad_gradient_y_10m": {"dtype": "float32", "scale": 1.0, "offset": 0.0, "nodata": "NaN", "units": "m/m"},
                "broad_gradient_magnitude_10m": {"dtype": "float32", "scale": 1.0, "offset": 0.0, "nodata": "NaN", "units": "m/m"},
                "broad_downslope_aspect_deg_10m": {"dtype": "float32", "scale": 1.0, "offset": 0.0, "nodata": "NaN", "units": "degrees_clockwise_from_north"},
                "local_gradient_x_10m": {"dtype": "float32", "scale": 1.0, "offset": 0.0, "nodata": "NaN", "units": "m/m"},
                "local_gradient_y_10m": {"dtype": "float32", "scale": 1.0, "offset": 0.0, "nodata": "NaN", "units": "m/m"},
                "local_gradient_magnitude_10m": {"dtype": "float32", "scale": 1.0, "offset": 0.0, "nodata": "NaN", "units": "m/m"},
                "local_downslope_aspect_deg_10m": {"dtype": "float32", "scale": 1.0, "offset": 0.0, "nodata": "NaN", "units": "degrees_clockwise_from_north"},
            },
            "qa": {
                "parent_aggregation_max_abs_error_m": max(recovery_errors, default=0.0),
                "parent_aggregation_blocks_checked": len(recovery_errors),
                "broad_parent_aggregation_max_abs_error_m": max(broad_recovery_errors, default=0.0),
                "max_prequantization_conservation_correction_m": max(conservation_corrections, default=0.0),
                "broad_gradient_direction_min_cosine": min(broad_cosines, default=1.0),
                "broad_gradient_direction_consistent_fraction": float(np.mean(np.asarray(broad_cosines) >= 0.0)) if broad_cosines else 1.0,
                "local_gradient_direction_min_cosine": min(local_cosines, default=1.0),
                "local_gradient_direction_consistent_fraction": float(np.mean(np.asarray(local_cosines) >= 0.0)) if local_cosines else 1.0,
                "exact_grid_nesting": True,
                "core_gradient_valid_with_halo": spec.halo_cells >= 1,
            },
        }
    )
    arrays = {
        "elevation_10m": elevation.astype(np.float32),
        "elevation_parent_base_10m": base,
        "elevation_residual_q": q_out,
        "broad_elevation_10m": broad_elevation.astype(np.float32),
        "broad_gradient_x_10m": broad_gx.astype(np.float32),
        "broad_gradient_y_10m": broad_gy.astype(np.float32),
        "broad_gradient_magnitude_10m": broad_mag.astype(np.float32),
        "broad_downslope_aspect_deg_10m": broad_aspect.astype(np.float32),
        "local_gradient_x_10m": local_gx.astype(np.float32),
        "local_gradient_y_10m": local_gy.astype(np.float32),
        "local_gradient_magnitude_10m": local_mag.astype(np.float32),
        "local_downslope_aspect_deg_10m": local_aspect.astype(np.float32),
    }
    encoded = {key: value for key, value in arrays.items() if key != "elevation_10m"}
    return EvidenceTile(spec, parent.grid, arrays, encoded, metadata)


def refine_parent_classes(
    parent: ParentRasterWindow,
    spec: TileSpec,
    recipe: CategoricalRecipe,
    source_hashes: Mapping[str, str],
) -> EvidenceTile:
    out = np.full((spec.fine_height, spec.fine_width), recipe.nodata_class, dtype=np.int32)
    row0, col0, row1, col1 = _parent_bounds_for_tile(spec)
    for pr in range(row0, row1):
        for pc in range(col0, col1):
            crop = _block_crop(spec, pr, pc)
            value = parent.get(pr, pc)
            if crop is None or _is_nodata(value, parent.nodata):
                continue
            tr, tc, _, _ = crop
            out[tr, tc] = int(value)
    metadata = _status_metadata(spec, parent.grid, recipe, source_hashes, recipe.effective_resolution_m)
    metadata.update(
        {
            "layer_kind": "categorical_parent_preserving",
            "encoding": {recipe.field_name: {"dtype": "int32", "scale": 1, "offset": 0, "nodata": recipe.nodata_class}},
            "qa": {"parent_class_repetition_exact": True, "exact_grid_nesting": True},
        }
    )
    return EvidenceTile(spec, parent.grid, {recipe.field_name: out}, {recipe.field_name: out}, metadata)


ProbabilityProvider = Callable[[int, int, np.ndarray, np.ndarray, np.ndarray], np.ndarray]


def _project_probability_block(raw: np.ndarray, target: np.ndarray, tolerance: float, max_iter: int) -> np.ndarray:
    raw = np.asarray(raw, dtype=np.float64)
    target = np.asarray(target, dtype=np.float64)
    if raw.ndim != 3 or raw.shape[1:] != (10, 10) or raw.shape[0] != target.size:
        raise ValueError("Raw probabilities must have shape (classes, 10, 10)")
    if np.any(target < 0) or not np.isclose(target.sum(), 1.0, atol=tolerance):
        raise ValueError("Parent probabilities must be non-negative and sum to one")
    matrix = np.maximum(raw.reshape(target.size, 100).T, 1e-15)
    matrix[:, target == 0] = 0.0
    column_target = target * 100.0
    for _ in range(max_iter):
        row_sum = matrix.sum(axis=1)
        if np.any(row_sum <= 0):
            matrix[row_sum <= 0] = target
            row_sum = matrix.sum(axis=1)
        matrix /= row_sum[:, None]
        column_sum = matrix.sum(axis=0)
        positive = column_target > 0
        matrix[:, positive] *= column_target[positive] / column_sum[positive]
        matrix[:, ~positive] = 0.0
        row_error = float(np.max(np.abs(matrix.sum(axis=1) - 1.0)))
        col_error = float(np.max(np.abs(matrix.sum(axis=0) - column_target)))
        if max(row_error, col_error) <= tolerance:
            break
    else:
        raise RuntimeError("Probability projection failed to converge")
    matrix /= matrix.sum(axis=1)[:, None]
    return matrix.T.reshape(target.size, 10, 10)


def refine_parent_probabilities(
    parent_probabilities: np.ndarray,
    parent_row0: int,
    parent_col0: int,
    grid: GridSpec,
    spec: TileSpec,
    recipe: CategoricalRecipe,
    source_hashes: Mapping[str, str],
    evidence_provider: ProbabilityProvider | None = None,
) -> EvidenceTile:
    parent_probabilities = np.asarray(parent_probabilities, dtype=np.float64)
    if parent_probabilities.ndim != 3:
        raise ValueError("parent_probabilities must have shape (classes, rows, cols)")
    classes = parent_probabilities.shape[0]
    out = np.full((classes, spec.fine_height, spec.fine_width), np.nan, dtype=np.float32)
    row0, col0, row1, col1 = _parent_bounds_for_tile(spec)
    errors: list[float] = []
    for pr in range(row0, row1):
        for pc in range(col0, col1):
            lr, lc = pr - parent_row0, pc - parent_col0
            if not (0 <= lr < parent_probabilities.shape[1] and 0 <= lc < parent_probabilities.shape[2]):
                continue
            target = parent_probabilities[:, lr, lc]
            global_rows = pr * 10 + np.arange(10)
            global_cols = pc * 10 + np.arange(10)
            rr, cc = np.meshgrid(global_rows, global_cols, indexing="ij")
            x, y = grid.fine_center(rr, cc)
            raw = np.broadcast_to(target[:, None, None], (classes, 10, 10)).copy()
            if evidence_provider is not None:
                raw = np.asarray(evidence_provider(pr, pc, x, y, target), dtype=np.float64)
            projected = _project_probability_block(
                raw, target, recipe.probability_tolerance, recipe.max_projection_iterations
            )
            errors.append(float(np.max(np.abs(projected.mean(axis=(1, 2)) - target))))
            crop = _block_crop(spec, pr, pc)
            if crop is not None:
                tr, tc, br, bc = crop
                out[:, tr, tc] = projected[:, br, bc]
    class_out = np.where(np.isfinite(out).all(axis=0), np.argmax(out, axis=0), recipe.nodata_class).astype(np.int32)
    metadata = _status_metadata(spec, grid, recipe, source_hashes, recipe.effective_resolution_m)
    metadata.update(
        {
            "layer_kind": "categorical_probability_parent_preserving",
            "class_count": classes,
            "encoding": {
                f"{recipe.field_name}_probability_10m": {"dtype": "float32", "scale": 1.0, "offset": 0.0, "nodata": "NaN"},
                f"{recipe.field_name}_class_10m": {"dtype": "int32", "scale": 1, "offset": 0, "nodata": recipe.nodata_class},
            },
            "qa": {
                "parent_probability_max_abs_error": max(errors, default=0.0),
                "pixel_simplex_max_abs_error": float(np.nanmax(np.abs(np.nansum(out, axis=0) - 1.0))),
                "exact_grid_nesting": True,
            },
        }
    )
    arrays = {f"{recipe.field_name}_probability_10m": out, f"{recipe.field_name}_class_10m": class_out}
    return EvidenceTile(spec, grid, arrays, dict(arrays), metadata)


def _points_in_ring(x: np.ndarray, y: np.ndarray, ring: Sequence[tuple[float, float]]) -> np.ndarray:
    if len(ring) < 3:
        return np.zeros_like(x, dtype=bool)
    inside = np.zeros_like(x, dtype=bool)
    xj, yj = ring[-1]
    for xi, yi in ring:
        crossing = ((yi > y) != (yj > y)) & (
            x < (xj - xi) * (y - yi) / ((yj - yi) if yj != yi else np.finfo(float).eps) + xi
        )
        inside ^= crossing
        xj, yj = xi, yi
    return inside


def rasterize_exact_vectors(
    grid: GridSpec,
    spec: TileSpec,
    features: Iterable[PolygonFeature],
    recipe: CategoricalRecipe,
    source_hashes: Mapping[str, str],
) -> EvidenceTile:
    rows, cols = spec.global_fine_indices()
    rr, cc = np.meshgrid(rows, cols, indexing="ij")
    x, y = grid.fine_center(rr, cc)
    out = np.full((spec.fine_height, spec.fine_width), recipe.nodata_class, dtype=np.int32)
    ordered = sorted(features, key=lambda f: (f.priority, f.feature_id, f.class_id))
    for feature in ordered:
        mask = _points_in_ring(x, y, feature.exterior_xy)
        for hole in feature.holes_xy:
            mask &= ~_points_in_ring(x, y, hole)
        out[mask] = feature.class_id
    metadata = _status_metadata(spec, grid, recipe, source_hashes, recipe.effective_resolution_m)
    metadata.update(
        {
            "layer_kind": "categorical_exact_vector_rasterization",
            "rasterization_rule": "10 m cell centre; higher priority overwrites; deterministic feature-id tie break",
            "encoding": {recipe.field_name: {"dtype": "int32", "scale": 1, "offset": 0, "nodata": recipe.nodata_class}},
            "qa": {"parent_aggregation": "NOT_APPLICABLE_VECTOR_AUTHORITY", "exact_grid_nesting": True},
        }
    )
    return EvidenceTile(spec, grid, {recipe.field_name: out}, {recipe.field_name: out}, metadata)


def decode_compact_tile(arrays: Mapping[str, np.ndarray], metadata: Mapping[str, Any]) -> dict[str, np.ndarray]:
    result = {key: np.asarray(value) for key, value in arrays.items()}
    encoding = metadata.get("encoding", {})
    for logical_name, info in encoding.items():
        formula = info.get("formula") if isinstance(info, Mapping) else None
        if not formula or logical_name in result:
            continue
        if logical_name == "elevation_10m":
            q = result["elevation_residual_q"]
            scale = float(info["scale"])
            nodata = int(encoding["elevation_residual_q"]["nodata"])
            result[logical_name] = (
                result["elevation_parent_base_10m"].astype(np.float64)
                + np.where(q == nodata, np.nan, q) * scale
            ).astype(np.float32)
        else:
            base_name, residual_name = formula.split(" + ")[0], formula.split(" + ")[1].split(" * ")[0]
            q = result[residual_name]
            q_info = encoding[residual_name]
            result[logical_name] = (
                result[base_name].astype(np.float64)
                + np.where(q == int(q_info["nodata"]), np.nan, q) * float(q_info["scale"])
            ).astype(np.float32)
    return result
