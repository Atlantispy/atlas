"""Bounded old-vs-new terrain comparison on the existing Titan test window.

This is diagnostic only.  It reads the approved 100 m parent terrain and writes
one JSON metrics report.  It does not regenerate hydrology or production data.

The preserved old executable had no 10 m generator.  Accordingly this report
keeps two old-side measurements distinct:

* historical_old_100m: the exact terrain/slope calculation used by the old
  Stage 6C builder;
* legacy_bilinear_10m_counterfactual: ordinary bilinear interpolation onto the
  identical 10 m grid, included solely as an equal-grid performance baseline.
"""

from __future__ import annotations

import gc
from hashlib import sha256
import io
import json
from pathlib import Path
import statistics
import time
import tracemalloc

import numpy as np
import rasterio
from rasterio.windows import Window

from ten_m_tile_engine.engine import (
    GridSpec,
    ParentRasterWindow,
    TerrainRecipe,
    TileSpec,
    refine_terrain,
)
from source_catalogue import source_entry, source_path


ROOT = Path(__file__).resolve().parent
TERRAIN = source_path("terrain_d31_100m")
TERRAIN_SHA256 = str(source_entry("terrain_d31_100m")["sha256"])
OLD_BUILDER = (
    ROOT
    / "recovery_snapshots"
    / "2026-08-27_pre_hydrology_revamp"
    / "build_stage6c_100m.py"
)
ENGINE = ROOT / "ten_m_tile_engine" / "engine.py"
OUT = ROOT / "bounded_old_vs_new_same_location_2026-08-28"

# Identical constants to run_bounded_real_terrain_test.py.
CORE_ROW0 = 4012
CORE_COL0 = 13417
CORE_PARENTS = 16
SUPPORT_PARENTS = 5
HALO_FINE_CELLS = 20


def file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def old_100m_terrain_branch(parent_data: np.ndarray) -> dict[str, np.ndarray]:
    """Exact terrain/slope branch from the preserved old RasterStack."""
    terrain = parent_data.astype(np.float32, copy=False)
    gy, gx = np.gradient(terrain.astype(np.float64), 100.0, 100.0)
    slope = np.degrees(np.arctan(np.hypot(gx, gy))).astype(np.float32)
    core = slice(SUPPORT_PARENTS, SUPPORT_PARENTS + CORE_PARENTS)
    return {
        "elevation_100m": terrain[core, core].copy(),
        "slope_deg_100m": slope[core, core].copy(),
    }


def legacy_bilinear_10m(parent_data: np.ndarray) -> dict[str, np.ndarray]:
    """Simple equal-grid interpolation baseline; not a historical executable."""
    fine_size = CORE_PARENTS * 10 + 2 * HALO_FINE_CELLS
    # Fine centres for the tile with its 200 m halo, expressed in source-array
    # parent-centre coordinates.  This is the same grid sampled by the new tile.
    first_global_parent = CORE_ROW0 - HALO_FINE_CELLS / 10.0
    first_global_col = CORE_COL0 - HALO_FINE_CELLS / 10.0
    source_row0 = CORE_ROW0 - SUPPORT_PARENTS
    source_col0 = CORE_COL0 - SUPPORT_PARENTS
    rows = first_global_parent + (np.arange(fine_size) + 0.5) / 10.0 - 0.5 - source_row0
    cols = first_global_col + (np.arange(fine_size) + 0.5) / 10.0 - 0.5 - source_col0

    parent_axis = np.arange(parent_data.shape[1], dtype=np.float64)
    horizontal = np.empty((parent_data.shape[0], fine_size), dtype=np.float64)
    for row in range(parent_data.shape[0]):
        horizontal[row] = np.interp(cols, parent_axis, parent_data[row])
    elevation = np.empty((fine_size, fine_size), dtype=np.float64)
    row_axis = np.arange(parent_data.shape[0], dtype=np.float64)
    for col in range(fine_size):
        elevation[:, col] = np.interp(rows, row_axis, horizontal[:, col])

    gx = np.gradient(elevation, 10.0, axis=1)
    gy = np.gradient(elevation, 10.0, axis=0)
    magnitude = np.hypot(gx, gy)
    aspect = (np.degrees(np.arctan2(-gx, gy)) + 360.0) % 360.0
    return {
        "elevation_10m": elevation.astype(np.float32),
        "gradient_x_10m": gx.astype(np.float32),
        "gradient_y_10m": gy.astype(np.float32),
        "gradient_magnitude_10m": magnitude.astype(np.float32),
        "downslope_aspect_deg_10m": aspect.astype(np.float32),
    }


def benchmark(function, repeats: int, warmups: int = 1) -> tuple[dict, list[float]]:
    value = None
    for _ in range(warmups):
        value = function()
    times: list[float] = []
    for _ in range(repeats):
        started = time.perf_counter()
        value = function()
        times.append(time.perf_counter() - started)
    assert value is not None
    return value, times


def traced_peak(function) -> int:
    gc.collect()
    tracemalloc.start()
    value = function()
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    del value
    gc.collect()
    return int(peak)


def timing_summary(values: list[float]) -> dict[str, float | int]:
    ordered = sorted(values)
    return {
        "repeats": len(values),
        "median_seconds": float(statistics.median(ordered)),
        "minimum_seconds": float(ordered[0]),
        "maximum_seconds": float(ordered[-1]),
    }


def array_bytes(arrays: dict[str, np.ndarray]) -> int:
    return int(sum(np.asarray(value).nbytes for value in arrays.values()))


def zip_bytes(arrays: dict[str, np.ndarray]) -> int:
    buffer = io.BytesIO()
    np.savez_compressed(buffer, **arrays)
    return len(buffer.getvalue())


def parent_means(fine_core: np.ndarray) -> np.ndarray:
    return fine_core.reshape(CORE_PARENTS, 10, CORE_PARENTS, 10).mean(axis=(1, 3))


def terrain_summary(elevation: np.ndarray, slope_deg: np.ndarray) -> dict[str, float]:
    return {
        "median_elevation_m": float(np.nanmedian(elevation)),
        "relief_m": float(np.nanmax(elevation) - np.nanmin(elevation)),
        "median_slope_deg": float(np.nanmedian(slope_deg)),
        "slope_p90_deg": float(np.nanpercentile(slope_deg, 90)),
        "maximum_slope_deg": float(np.nanmax(slope_deg)),
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    output_path = OUT / "OLD_VS_NEW_SAME_LOCATION_METRICS.json"
    row0 = CORE_ROW0 - SUPPORT_PARENTS
    col0 = CORE_COL0 - SUPPORT_PARENTS
    size = CORE_PARENTS + 2 * SUPPORT_PARENTS
    read_started = time.perf_counter()
    with rasterio.open(TERRAIN) as source:
        parent_data = source.read(1, window=Window(col0, row0, size, size)).astype(np.float32)
    read_seconds = time.perf_counter() - read_started

    grid = GridSpec(origin_x_m=0.0, origin_y_m=0.0)
    parent = ParentRasterWindow(parent_data, row0, col0, grid, nodata=np.nan)
    spec = TileSpec(
        "TITAN-INTERIOR-REAL-TERRAIN-TEST-001",
        CORE_ROW0,
        CORE_COL0,
        CORE_PARENTS,
        CORE_PARENTS,
        halo_cells=HALO_FINE_CELLS,
    )
    recipe = TerrainRecipe(
        effective_resolution_m=100.0,
        elevation_scale_m=0.01,
        max_micro_relief_m=1.0,
        micro_relief_slope_fraction=0.20,
        seed="diadem-bounded-real-terrain-test-v1",
    )
    source_hashes = {
        "approved_d31_terrain_100m": TERRAIN_SHA256,
        "source_window_sha256": sha256(parent_data.tobytes()).hexdigest(),
    }

    def new_branch():
        return refine_terrain(parent, spec, recipe, source_hashes)

    old_result, old_times = benchmark(lambda: old_100m_terrain_branch(parent_data), 2000, 2)
    legacy_result, legacy_times = benchmark(lambda: legacy_bilinear_10m(parent_data), 100, 2)
    new_tile, new_times = benchmark(new_branch, 3, 1)

    old_peak = traced_peak(lambda: old_100m_terrain_branch(parent_data))
    legacy_peak = traced_peak(lambda: legacy_bilinear_10m(parent_data))
    new_peak = traced_peak(new_branch)

    fine_core = spec.core_slice
    parent_core = old_result["elevation_100m"].astype(np.float64)
    legacy_core = legacy_result["elevation_10m"][fine_core].astype(np.float64)
    new_core = new_tile.arrays["elevation_10m"][fine_core].astype(np.float64)
    new_broad_core = new_tile.arrays["broad_elevation_10m"][fine_core].astype(np.float64)
    legacy_parent = parent_means(legacy_core)
    new_parent = parent_means(new_core)
    new_broad_parent = parent_means(new_broad_core)

    legacy_slope = np.degrees(
        np.arctan(legacy_result["gradient_magnitude_10m"][fine_core].astype(np.float64))
    )
    new_local_slope = np.degrees(
        np.arctan(new_tile.arrays["local_gradient_magnitude_10m"][fine_core].astype(np.float64))
    )
    new_broad_slope = np.degrees(
        np.arctan(new_tile.arrays["broad_gradient_magnitude_10m"][fine_core].astype(np.float64))
    )

    new_common_arrays = {
        "elevation_10m": new_tile.arrays["elevation_10m"],
        "gradient_x_10m": new_tile.arrays["local_gradient_x_10m"],
        "gradient_y_10m": new_tile.arrays["local_gradient_y_10m"],
        "gradient_magnitude_10m": new_tile.arrays["local_gradient_magnitude_10m"],
        "downslope_aspect_deg_10m": new_tile.arrays["local_downslope_aspect_deg_10m"],
    }

    old_median = statistics.median(old_times)
    legacy_median = statistics.median(legacy_times)
    new_median = statistics.median(new_times)
    result = {
        "status": "PASS",
        "scope": "SAME_TITAN_LOCATION_OLD_VS_NEW_DIAGNOSTIC_NO_HYDROLOGY_NO_PRODUCTION",
        "comparison_contract": {
            "historical_old_100m": "Exact executable terrain and slope branch preserved from Stage 6C; it never generated 10 m terrain.",
            "legacy_bilinear_10m_counterfactual": "Ordinary bilinear interpolation on the identical 10 m grid; equal-grid baseline only, not a recovered historical implementation.",
            "new_10m": "Current parent-conserving sparse 10 m terrain generator.",
            "timing_scope": "Compute only after one shared source read; warm-up excluded.",
            "memory_scope": "Python tracemalloc incremental peak; comparable between branches but not whole-process RSS.",
        },
        "location": {
            "tile_id": spec.tile_id,
            "core_bounds_m_positive_south": [1341700.0, 401200.0, 1343300.0, 402800.0],
            "core_size_km": [1.6, 1.6],
            "core_parent_cells_100m": 256,
            "core_cells_10m": 25600,
            "halo_10m_cells_each_side": HALO_FINE_CELLS,
            "source_window": {"row0": row0, "col0": col0, "height": size, "width": size},
        },
        "source": {
            "path": str(TERRAIN),
            "expected_sha256": TERRAIN_SHA256,
            "window_sha256": source_hashes["source_window_sha256"],
            "shared_read_seconds": read_seconds,
            "old_builder_sha256": file_sha256(OLD_BUILDER),
            "new_engine_sha256": file_sha256(ENGINE),
        },
        "performance": {
            "historical_old_100m": {
                "timing": timing_summary(old_times),
                "tracemalloc_peak_bytes": old_peak,
                "raw_output_bytes": array_bytes(old_result),
                "zip_output_bytes": zip_bytes(old_result),
            },
            "legacy_bilinear_10m_counterfactual": {
                "timing": timing_summary(legacy_times),
                "tracemalloc_peak_bytes": legacy_peak,
                "raw_common_five_band_bytes": array_bytes(legacy_result),
                "zip_common_five_band_bytes": zip_bytes(legacy_result),
            },
            "new_10m": {
                "timing": timing_summary(new_times),
                "tracemalloc_peak_bytes": new_peak,
                "raw_common_five_band_bytes": array_bytes(new_common_arrays),
                "zip_common_five_band_bytes": zip_bytes(new_common_arrays),
                "raw_all_logical_arrays_bytes": array_bytes(new_tile.arrays),
                "raw_compact_encoded_arrays_bytes": array_bytes(new_tile.encoded_arrays),
            },
            "ratios": {
                "new_vs_historical_old_compute_time": float(new_median / old_median),
                "new_vs_equal_grid_bilinear_compute_time": float(new_median / legacy_median),
                "new_vs_equal_grid_bilinear_tracemalloc_peak": float(new_peak / legacy_peak),
            },
        },
        "terrain_equivalence_and_added_detail": {
            "new_parent_mean_max_abs_error_m": float(np.max(np.abs(new_parent - parent_core))),
            "new_broad_parent_mean_max_abs_error_m": float(np.max(np.abs(new_broad_parent - parent_core))),
            "legacy_bilinear_parent_mean_max_abs_error_m": float(np.max(np.abs(legacy_parent - parent_core))),
            "new_vs_legacy_elevation_rmse_m": float(np.sqrt(np.mean((new_core - legacy_core) ** 2))),
            "historical_old_100m": terrain_summary(
                old_result["elevation_100m"], old_result["slope_deg_100m"]
            ),
            "legacy_bilinear_10m": terrain_summary(legacy_core, legacy_slope),
            "new_broad_10m": terrain_summary(new_broad_core, new_broad_slope),
            "new_local_10m": terrain_summary(new_core, new_local_slope),
        },
        "interpretation_guardrails": [
            "The historical old branch is much cheaper because it evaluates 256 parent cells and produces no 10 m model.",
            "The equal-grid bilinear baseline is the fairest compute comparison, but it lacks parent-mean conservation, constrained local relief, dual broad/local gradients, encoding metadata, and recovery semantics.",
            "Both 10 m results remain modelled from the same 100 m physical evidence.",
            "This one smooth interior Titan window does not establish whole-project scaling.",
        ],
    }
    output_path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
