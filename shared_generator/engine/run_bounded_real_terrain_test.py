"""One bounded read-only real-terrain test for the sparse 10 m generator.

This is an engineering verification only. It does not regenerate hydrology,
change a source, rescore a settlement, or create a publishable map product.
"""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import shutil
import time
import tracemalloc

import numpy as np

from ten_m_tile_engine.cache import (
    ContentAddressedCache,
    ingest_recovery_bundle,
    read_recovery_manifest,
    write_tile_recovery_bundle,
)
from ten_m_tile_engine.engine import (
    GridSpec,
    ParentRasterWindow,
    TerrainRecipe,
    TileSpec,
    canonical_hash,
    refine_terrain,
)
from stage6c_terrain_authority import (
    EXPECTED_TRANSFORM,
    TerrainAuthorityReader,
    authority_root,
    identity_component,
    verify_authority,
)


OUT = Path(__file__).resolve().parent / "bounded_real_terrain_test_2026-08-28"

# A 1.6 x 1.6 km snapshot centred on an interior Titan reach near
# 1342.47 km east, 401.99 km south. The source read includes five 100 m
# parents of support on every side for the spline and 200 m fine halo.
CORE_ROW0 = 4012
CORE_COL0 = 13417
CORE_PARENTS = 16
SUPPORT_PARENTS = 5
HALO_FINE_CELLS = 20


def array_digest(arrays: dict[str, np.ndarray]) -> str:
    digest = sha256()
    for name in sorted(arrays):
        value = np.ascontiguousarray(arrays[name])
        digest.update(name.encode("utf-8"))
        digest.update(str(value.dtype).encode("ascii"))
        digest.update(np.asarray(value.shape, dtype=np.int64).tobytes())
        digest.update(value.tobytes())
    return digest.hexdigest()


def main() -> int:
    expected_parent = Path(__file__).resolve().parent
    if OUT.parent.resolve() != expected_parent or OUT.name != "bounded_real_terrain_test_2026-08-28":
        raise RuntimeError("Refusing to clean an unexpected output path")
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    row0 = CORE_ROW0 - SUPPORT_PARENTS
    col0 = CORE_COL0 - SUPPORT_PARENTS
    size = CORE_PARENTS + 2 * SUPPORT_PARENTS

    authority = verify_authority()
    reader = TerrainAuthorityReader(authority, root=authority_root()).open()
    try:
        parent_data = reader.read_block(row0, col0, size, size)
    finally:
        reader.close()
    source_transform = EXPECTED_TRANSFORM

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
    authority_identity = identity_component(authority)
    source_hashes = {
        "editable_terrain_authority_root": authority["root_hash"],
        "sealed_d31_terrain_lineage": authority["sealed_tiff_lineage"]
        ["terrain_d31_100m"]["sha256"],
        "sealed_stillklinge_terrain_lineage": authority["sealed_tiff_lineage"]
        ["stillklinge_terrain_100m"]["sha256"],
        "source_window_sha256": sha256(parent_data.tobytes()).hexdigest(),
    }

    tracemalloc.start()
    started = time.perf_counter()
    tile = refine_terrain(parent, spec, recipe, source_hashes)
    first_seconds = time.perf_counter() - started
    _, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    rerun = refine_terrain(parent, spec, recipe, source_hashes)
    digest_first = array_digest(tile.arrays)
    digest_rerun = array_digest(rerun.arrays)

    bundle = write_tile_recovery_bundle(tile, OUT / "tile.zstbundle", compact=True)
    manifest = read_recovery_manifest(bundle)
    cache = ContentAddressedCache(OUT / "ingest_cache")
    ingest = ingest_recovery_bundle(bundle, cache)

    core = spec.core_slice
    elevation = tile.arrays["elevation_10m"][core]
    broad_elevation = tile.arrays["broad_elevation_10m"][core]
    broad_gradient = tile.arrays["broad_gradient_magnitude_10m"][core]
    local_gradient = tile.arrays["local_gradient_magnitude_10m"][core]
    raw_payload_bytes = int(sum(np.asarray(value).nbytes for value in tile.encoded_arrays.values()))
    bundle_bytes = int(sum(path.stat().st_size for path in bundle.rglob("*") if path.is_file()))
    core_x0_m = CORE_COL0 * 100.0
    core_y0_m = CORE_ROW0 * 100.0
    core_x1_m = (CORE_COL0 + CORE_PARENTS) * 100.0
    core_y1_m = (CORE_ROW0 + CORE_PARENTS) * 100.0

    result = {
        "status": "PASS" if not ingest.failed_sequences and digest_first == digest_rerun else "FAIL",
        "scope": "ONE_BOUNDED_REAL_TERRAIN_TILE_ENGINEERING_TEST_NO_HYDROLOGY_NO_PRODUCTION",
        "source": {
            "authority_relative_path": "working_authorities/effective_terrain_100m",
            "authority_identity": authority_identity,
            "window_sha256": source_hashes["source_window_sha256"],
            "source_transform": list(source_transform),
            "parent_window": {"row0": row0, "col0": col0, "height": size, "width": size},
            "parent_min_m": float(np.min(parent_data)),
            "parent_max_m": float(np.max(parent_data)),
        },
        "snapshot": {
            "tile_id": spec.tile_id,
            "core_bounds_m_positive_south": [core_x0_m, core_y0_m, core_x1_m, core_y1_m],
            "core_size_km": [CORE_PARENTS / 10.0, CORE_PARENTS / 10.0],
            "core_10m_cells": int(elevation.size),
            "halo_10m_cells_each_side": HALO_FINE_CELLS,
            "cell_size_m": tile.metadata["cell_size_m"],
            "model_resolution_m": tile.metadata["model_resolution_m"],
            "physical_source_resolution_m": tile.metadata["physical_source_resolution_m"],
            "effective_evidence_resolution_m": tile.metadata["effective_evidence_resolution_m"],
        },
        "terrain_metrics": {
            "elevation_min_m": float(np.nanmin(elevation)),
            "elevation_max_m": float(np.nanmax(elevation)),
            "elevation_range_m": float(np.nanmax(elevation) - np.nanmin(elevation)),
            "broad_elevation_range_m": float(np.nanmax(broad_elevation) - np.nanmin(broad_elevation)),
            "broad_gradient_mean": float(np.nanmean(broad_gradient)),
            "broad_gradient_max": float(np.nanmax(broad_gradient)),
            "local_gradient_mean": float(np.nanmean(local_gradient)),
            "local_gradient_max": float(np.nanmax(local_gradient)),
            **tile.metadata["qa"],
        },
        "determinism": {
            "first_array_digest": digest_first,
            "rerun_array_digest": digest_rerun,
            "byte_identical_arrays": digest_first == digest_rerun,
        },
        "zstd_delivery": {
            "format": "manifest_indexed_independent_zstd_frames",
            "bundle_id": manifest["bundle_id"],
            "packet_count": int(manifest["packet_count"]),
            "frames_applied": ingest.applied_sequences,
            "frames_failed": ingest.failed_sequences,
            "raw_encoded_payload_bytes": raw_payload_bytes,
            "bundle_bytes_including_manifests": bundle_bytes,
            "raw_to_bundle_ratio": float(raw_payload_bytes / bundle_bytes),
        },
        "performance": {
            "first_generation_seconds": first_seconds,
            "python_tracemalloc_peak_bytes": int(peak_bytes),
        },
        "lineage": {
            "tile_metadata_hash": canonical_hash(tile.metadata),
            "review_status": tile.metadata["review_status"],
            "resolution_status": tile.metadata["resolution_status"],
        },
    }
    (OUT / "BOUNDED_TEST_METRICS.json").write_text(
        json.dumps(result, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
