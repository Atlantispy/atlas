#!/usr/bin/env python3
"""Build the bounded Stage 6C.5 10 m refinement for the 107 FT0/FT1 sites.

This is an additive, review-only successor to the certified Stage 6C database.
It preserves every inherited identity and official coordinate.  The new terrain
is a parent-conserving MODELLED_10M refinement of the 100 m authority; exact
surface/barony polygons and current hydrology vectors are sampled on the 10 m
grid.  It does not claim regenerated hydrology, observed 10 m terrain, final
settlement footprints, or specialist 3D capacity.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import shutil
import sqlite3
import sys
import tempfile
import time
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


ENGINE_DIR = Path(__file__).resolve().parent
for dependency_directory in (
    ENGINE_DIR / "zarr_deps",
    ENGINE_DIR / "generator_deps",
):
    text = str(dependency_directory)
    if text not in sys.path:
        sys.path.insert(0, text)

import numpy as np
import shapely
import zarr
import zstandard as zstd
from zarr.codecs import ZstdCodec

import build_stage6c_100m as s6c
import algorithm_policy
import stage6c_rules as rules
from ten_m_tile_engine.cache import read_recovery_manifest, write_tile_recovery_bundle
from ten_m_tile_engine.engine import GridSpec, ParentRasterWindow, TerrainRecipe, TileSpec
from stage6c5_fast_terrain import ADAPTER_VERSION, refine_terrain_safe
from stage6d_schema import install_stage6c5_stage6d_view
from generation_runtime import (
    bounded_map, file_identity, implementation_identity, load_receipt,
    save_receipt, semantic_identity, RuntimeStats,
)
from verified_source_hash_cache import windows_file_change_token
from source_catalogue import catalogue_path


DATE = "2026-08-30"
METHOD = "STAGE6C5_BOUNDED_10M_SETTLEMENT_REFINEMENT_V2"
CANON_STATUS = "WORKING_PROPOSAL_REVIEW_ONLY_NOT_CANON"
CANDIDATE_LIST_SHA256 = "d037b544cf02b716f2da823b2a87faddfff1513fd5d7d72db84757b675e17656"
EXPECTED_CANDIDATES = 107
EXPECTED_FT0 = 19
EXPECTED_FT1 = 88
EXPECTED_2D = 79
EXPECTED_3D = 28

CORE_PARENT_CELLS = 22       # 2.2 km square: guarantees the complete r=1 km circle.
CANDIDATE_PARENT_CELLS = 10  # 1 km x 1 km inherited coordinate-support window.
FINE_PER_PARENT = 10
FINE_CORE_CELLS = CORE_PARENT_CELLS * FINE_PER_PARENT
FINE_CELL_KM = 0.01
HALO_FINE_CELLS = 10         # 100 m; parent-aligned and valid for fast gradients/seams.
PARENT_SUPPORT_CELLS = 3     # Halo parent plus two-cell bicubic support ring.
HOT_CACHE_ZSTD_LEVEL = 3
PARENT_SCORE_CLEAR_GAP = 0.05
MIN_PARENT_VALID_FRACTION = 0.50
CELL_SCORE_CLEAR_GAP = 0.05

TERRAIN_RECIPE = TerrainRecipe(
    effective_resolution_m=100.0,
    elevation_scale_m=0.01,
    max_micro_relief_m=1.0,
    micro_relief_slope_fraction=0.20,
    minimum_micro_relief_m=0.0,
    max_conservation_correction_m=50.0,
    seed="diadem-stage6c5-terrain-10m-v1",
)

ROOT = s6c.ROOT
PARENT_DIR = ROOT / "generated_outputs/Diadem_Province_Database_V4_STAGE6C_100M_SPATIAL_CONTEXT_WORKING_2026-08-30"
PARENT_DB = PARENT_DIR / "Diadem_Province_Database_V4_STAGE6C_100M_SPATIAL_CONTEXT_WORKING_2026-08-30.sqlite"
PARENT_GPKG = PARENT_DIR / "Diadem_Province_Map_Layer_V4_STAGE6C_100M_SPATIAL_CONTEXT_WORKING_2026-08-30.gpkg"
# Keep the physical folder short enough for Zarr's temporary filenames on
# Windows; the artefacts inside retain their full descriptive release names.
DEFAULT_OUTPUT_DIR = ROOT / "generated_outputs/S6C5_10M_WORKING_V2_2026-08-30"
OUTPUT_DB_NAME = "Diadem_Province_Database_V5_STAGE6C5_BOUNDED_10M_REFINEMENT_WORKING_2026-08-30.sqlite"
OUTPUT_GPKG_NAME = "Diadem_Province_Map_Layer_V5_STAGE6C5_BOUNDED_10M_REFINEMENT_WORKING_2026-08-30.gpkg"

GRID = GridSpec(origin_x_m=0.0, origin_y_m=0.0)
SITE_MEMORY_ESTIMATE_BYTES = 64 * 1024 * 1024


def runtime_code_paths(extra_files: Iterable[Path] = ()) -> list[Path]:
    names = (
        "build_stage6c5_10m.py", "build_stage6c_100m.py", "stage6c_rules.py",
        "stage6c5_fast_terrain.py", "stage6d_schema.py", "source_catalogue.py",
        "stage6c_source_stack.py", "stage6c_terrain_authority.py",
        "zarr_authority.py", "verified_source_hash_cache.py", "generation_runtime.py", "algorithm_policy.py",
    )
    paths = [ENGINE_DIR / name for name in names]
    paths.extend(sorted((ENGINE_DIR / "ten_m_tile_engine").glob("*.py")))
    paths.extend(extra_files)
    return paths


def runtime_implementation(extra_files: Iterable[Path] = ()) -> dict[str, Any]:
    """Bind reuse to executable code and numerical runtime, not recipe labels."""
    return {
        "implementation": implementation_identity(runtime_code_paths(extra_files)),
        "libraries": {
            "numpy": np.__version__, "shapely": shapely.__version__,
            "zarr": zarr.__version__, "zstandard": zstd.__version__,
            "rasterio": s6c.rasterio.__version__,
            "gdal": s6c.rasterio.__gdal_version__,
            "geos": shapely.geos_version_string,
            "sqlite": sqlite3.sqlite_version,
        },
    }


def capture_source_guards(paths: Iterable[Path]) -> dict[str, Any]:
    """Cheap mid-run drift guard; content hashes still own persisted identities."""
    guards = {}
    for path in sorted(set(Path(value).resolve() for value in paths)):
        if path.suffix.lower() in {".db", ".sqlite", ".gpkg"}:
            for suffix in ("-wal", "-journal"):
                sidecar = path.with_name(path.name + suffix)
                if sidecar.exists() and sidecar.stat().st_size:
                    raise RuntimeError(f"SQLite source has live/uncheckpointed state: {sidecar}")
        with path.open("rb") as stream:
            token = windows_file_change_token(stream, path)
        info = path.stat()
        guards[str(path)] = token if token is not None else {
            "fallback_metadata": [info.st_dev, info.st_ino, info.st_size,
                                  info.st_mtime_ns, info.st_ctime_ns],
        }
    return guards


def require_source_guards(expected: Mapping[str, Any]) -> None:
    if capture_source_guards(Path(path) for path in expected) != expected:
        raise RuntimeError("Source or implementation changed during the run; commit refused")


def guarded_source_paths(parents: Iterable[Path], extra_code: Iterable[Path] = ()) -> list[Path]:
    return [
        *parents, catalogue_path(), *runtime_code_paths(extra_code),
        *(Path(spec["path"]) for role, spec in s6c.SOURCES.items()
          if role not in s6c.SEALED_TERRAIN_LINEAGE_ROLES),
    ]


def require_terrain_identity(expected: Mapping[str, Any]) -> None:
    current = s6c.verify_terrain_authority()
    keys = ("authority_id", "generation", "root_hash")
    if any(current[key] != expected[key] for key in keys):
        raise RuntimeError("Terrain authority changed during the run; commit refused")


def checkpoint_plan(items: Sequence[Any], loader: Any, *, reuse: bool) -> list[Any]:
    """Plan before acquiring heavy generation resources; never weaken readback."""
    return [loader(item) if reuse else None for item in items]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    payload = (canonical_json(value) + "\n").encode("utf-8")
    with temporary.open("wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sqlite_readonly(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def sqlite_backup(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    if temporary.exists():
        temporary.unlink()
    source_connection = sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)
    destination_connection = sqlite3.connect(temporary)
    try:
        source_connection.backup(destination_connection, pages=16_384)
        destination_connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        if destination_connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError(f"SQLite backup integrity failure: {destination}")
    finally:
        destination_connection.close()
        source_connection.close()
    os.replace(temporary, destination)


@dataclass(frozen=True)
class Candidate:
    index: int
    site: s6c.Site
    inherited: dict[str, Any]
    profile: dict[str, Any]
    disposition: str
    source_parent_row0: int
    source_parent_col0: int
    tile_parent_row0: int
    tile_parent_col0: int
    tile_id: str
    semantic_key: str


def terrain_recipe_identity() -> dict[str, Any]:
    return {
        **asdict(TERRAIN_RECIPE),
        "core_parent_cells": CORE_PARENT_CELLS,
        "candidate_parent_cells": CANDIDATE_PARENT_CELLS,
        "halo_fine_cells": HALO_FINE_CELLS,
        "fine_cell_m": 10,
        "method": METHOD,
        "fast_terrain_adapter_version": ADAPTER_VERSION,
    }


def load_candidates(
    connection: sqlite3.Connection,
    authority_descriptor: Mapping[str, Any],
) -> list[Candidate]:
    site_by_id = {site.settlement_id: site for site in s6c.load_sites(connection)}
    rows = connection.execute(
        """
        SELECT s.settlement_id, s.stage6b_functional_tier, a.*
        FROM settlement s
        JOIN stage6c_site_assessment a USING(settlement_id)
        WHERE s.stage6_active_settlement=1
          AND s.stage6b_functional_tier IN (
              'FT0_HAUS_PRINCIPAL_SITE','FT1_MAJOR_REGIONAL_HUB'
          )
        ORDER BY s.settlement_id
        """
    ).fetchall()
    ids = [str(row["settlement_id"]) for row in rows]
    digest = sha256_text(canonical_json(ids))
    if len(rows) != EXPECTED_CANDIDATES or digest != CANDIDATE_LIST_SHA256:
        raise RuntimeError(
            f"Stage 6C.5 candidate scope drifted: count={len(rows)} sha256={digest}"
        )
    tier_counts = Counter(str(row["stage6b_functional_tier"]) for row in rows)
    if tier_counts != Counter({
        "FT0_HAUS_PRINCIPAL_SITE": EXPECTED_FT0,
        "FT1_MAJOR_REGIONAL_HUB": EXPECTED_FT1,
    }):
        raise RuntimeError(f"Stage 6C.5 tier counts drifted: {tier_counts}")

    profiles = {
        str(row["profile_id"]): dict(row)
        for row in connection.execute("SELECT * FROM stage6c_profile_catalog")
    }
    source_identity = {
        "authority_id": authority_descriptor["authority_id"],
        "authority_generation": authority_descriptor["generation"],
        "authority_root_hash": authority_descriptor["root_hash"],
        "exact_surface_sha256": s6c.SOURCES["exact_surface_registry"]["sha256"],
        "barony_assignment_sha256": s6c.SOURCES["fragment_barony_assignment"]["sha256"],
        "hydrology_sha256": {
            role: s6c.SOURCES[role]["sha256"]
            for role in (
                "active_major", "d3_feeder_raw", "d3_feeder_enriched",
                "stillklinge_support", "special_controls", "coastline",
                "lake_permanent_l1", "lake_permanent_legacy", "lake_seasonal",
            )
        },
        "mask_sha256": {
            role: s6c.SOURCES[role]["sha256"]
            for role in (
                "obsidian_sea_mask", "moorwandler_core_wetland",
                "serenakrone_water_mask", "flood_candidates_100m",
                "stillklinge_flood_override",
            )
        },
    }
    recipe_identity = terrain_recipe_identity()
    candidates: list[Candidate] = []
    for index, row in enumerate(rows):
        inherited = dict(row)
        site = site_by_id[str(row["settlement_id"])]
        rr, cc = s6c.source_grid_window(site)
        source_row0, source_col0 = int(rr.min()), int(cc.min())
        # Six parent cells on each side of the inherited 10-parent candidate
        # square guarantee that a true one-kilometre-radius circle is complete
        # even when the official coordinate is not aligned to the 100 m grid.
        tile_row0 = min(max(source_row0 - 6, 0), 18_600 - CORE_PARENT_CELLS)
        tile_col0 = min(max(source_col0 - 6, 0), 22_000 - CORE_PARENT_CELLS)
        if not (
            tile_col0 * 0.1 <= site.x - 1.0
            and (tile_col0 + CORE_PARENT_CELLS) * 0.1 >= site.x + 1.0
            and tile_row0 * 0.1 <= site.y - 1.0
            and (tile_row0 + CORE_PARENT_CELLS) * 0.1 >= site.y + 1.0
        ):
            raise RuntimeError(
                f"Stage 6C.5 context does not contain the complete r=1 km circle: "
                f"{site.settlement_id}"
            )
        disposition = (
            "SURFACE_OR_INTERFACE_CONTEXT_ONLY_3D_DEFERRED"
            if inherited["analysis_status"] == "DEFERRED_SPECIALIST_3D"
            else "COMPLETE_2D_REFINEMENT"
        )
        tile_id = (
            f"S6C5-{site.settlement_id}-R{tile_row0:05d}-C{tile_col0:05d}"
        )
        semantic = {
            "record_type": "stage6c5.site-layer-bundle.v1",
            "settlement_id": site.settlement_id,
            "official_coordinate_km": [site.x, site.y],
            "barony_id": site.barony_id,
            "profile_id": inherited["profile_id"],
            "stage6c_input_fingerprint": inherited["input_fingerprint"],
            "window": [tile_row0, tile_col0, CORE_PARENT_CELLS, CORE_PARENT_CELLS],
            "source_identity": source_identity,
            "recipe": recipe_identity,
        }
        candidates.append(Candidate(
            index=index,
            site=site,
            inherited=inherited,
            profile=profiles[str(inherited["profile_id"])],
            disposition=disposition,
            source_parent_row0=source_row0,
            source_parent_col0=source_col0,
            tile_parent_row0=tile_row0,
            tile_parent_col0=tile_col0,
            tile_id=tile_id,
            semantic_key=sha256_text(canonical_json(semantic)),
        ))
    disposition_counts = Counter(candidate.disposition for candidate in candidates)
    if disposition_counts != Counter({
        "COMPLETE_2D_REFINEMENT": EXPECTED_2D,
        "SURFACE_OR_INTERFACE_CONTEXT_ONLY_3D_DEFERRED": EXPECTED_3D,
    }):
        raise RuntimeError(f"Stage 6C.5 disposition counts drifted: {disposition_counts}")
    return candidates


def rasterize_exact_surface_10m(
    topology: s6c.ExactSurfaceIndex,
    fine_row0: int,
    fine_col0: int,
    height: int,
    width: int,
) -> np.ndarray:
    """Cell-centre rasterisation of exact 1 km fragments onto the 10 m grid."""

    rows = np.arange(fine_row0, fine_row0 + height, dtype=np.int32)
    cols = np.arange(fine_col0, fine_col0 + width, dtype=np.int32)
    carrier_rows = np.clip(rows // 100, 0, 1_859)
    carrier_cols = np.clip(cols // 100, 0, 2_199)
    result = topology.carrier_baronies[np.ix_(carrier_rows, carrier_cols)].copy()
    min_cr, max_cr = int(carrier_rows.min()), int(carrier_rows.max())
    min_cc, max_cc = int(carrier_cols.min()), int(carrier_cols.max())
    for carrier_row in range(min_cr, max_cr + 1):
        for carrier_id in topology.partial_carriers_by_row.get(carrier_row, ()):
            carrier_col = carrier_id % 2_200
            if not min_cc <= carrier_col <= max_cc:
                continue
            global_row0 = max(fine_row0, carrier_row * 100)
            global_row1 = min(fine_row0 + height, (carrier_row + 1) * 100)
            global_col0 = max(fine_col0, carrier_col * 100)
            global_col1 = min(fine_col0 + width, (carrier_col + 1) * 100)
            lr0, lr1 = global_row0 - fine_row0, global_row1 - fine_row0
            lc0, lc1 = global_col0 - fine_col0, global_col1 - fine_col0
            xs, ys = np.meshgrid(
                np.arange(global_col0, global_col1, dtype=np.float64) * FINE_CELL_KM + 0.005,
                np.arange(global_row0, global_row1, dtype=np.float64) * FINE_CELL_KM + 0.005,
                indexing="xy",
            )
            classified = np.full(xs.shape, -1, dtype=np.int32)
            for barony_id, geometry in topology.explicit_by_carrier[carrier_id]:
                classified[shapely.intersects_xy(geometry, xs, ys)] = barony_id
            result[lr0:lr1, lc0:lc1] = classified
    return result.astype(np.int32, copy=False)


def repeat_parent(array: np.ndarray) -> np.ndarray:
    return np.repeat(np.repeat(np.asarray(array), FINE_PER_PARENT, axis=0), FINE_PER_PARENT, axis=1)


def candidate_points(candidate: Candidate) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    fine_row0 = candidate.source_parent_row0 * FINE_PER_PARENT
    fine_col0 = candidate.source_parent_col0 * FINE_PER_PARENT
    rows, cols = np.meshgrid(
        np.arange(fine_row0, fine_row0 + 100, dtype=np.int32),
        np.arange(fine_col0, fine_col0 + 100, dtype=np.int32),
        indexing="ij",
    )
    xs = cols.astype(np.float64) * FINE_CELL_KM + 0.005
    ys = rows.astype(np.float64) * FINE_CELL_KM + 0.005
    return rows, cols, xs, ys


def exact_water_evidence(
    vectors: s6c.VectorStack,
    candidate: Candidate,
) -> tuple[dict[str, np.ndarray], dict[str, float]]:
    _, _, xs, ys = candidate_points(candidate)
    points = shapely.points(xs.ravel(), ys.ravel())
    active = vectors.distances(vectors.active_index_tree, points)
    for polygon in vectors.coast_cover_polygons:
        active[np.asarray(shapely.covers(polygon, points), dtype=bool)] = 0.0
    perennial = vectors.distances(vectors.perennial_index_tree, points)
    distances: dict[str, np.ndarray] = {
        "active": active.reshape(100, 100),
        "perennial": perennial.reshape(100, 100),
    }
    if candidate.site.realised_form == "SURFACE_LAGOON_SETTLEMENT":
        distances["special"] = vectors.distances(
            vectors.managed_special_tree, points
        ).reshape(100, 100)
        distances["lake"] = vectors.distances(
            vectors.permanent_lake_tree, points
        ).reshape(100, 100)

    geometry = shapely.multipoints(points)
    minima = {
        "major": vectors.geometry_distance(vectors.major_index_tree, geometry),
        "minor": vectors.geometry_distance(vectors.minor_tree, geometry),
        "special": vectors.geometry_distance(vectors.special_tree, geometry),
        "lake": vectors.geometry_distance(vectors.permanent_lake_tree, geometry),
        "seasonal_lake": vectors.geometry_distance(vectors.seasonal_lake_tree, geometry),
        "coast": vectors.coast_geometry_distance(geometry),
    }
    return distances, {key: float(value) for key, value in minima.items()}


def parent_score_summary(
    scores: np.ndarray,
) -> tuple[int | None, float | None, float | None, float | None]:
    values = np.asarray(scores, dtype=np.float64).reshape(100, 100)
    blocks = values.reshape(10, 10, 10, 10).transpose(0, 2, 1, 3)
    valid = blocks >= 0
    counts = valid.sum(axis=(2, 3))
    sums = np.where(valid, blocks, 0.0).sum(axis=(2, 3))
    means = np.full((10, 10), np.nan, dtype=np.float64)
    eligible = counts >= int(math.ceil(100 * MIN_PARENT_VALID_FRACTION))
    means[eligible] = sums[eligible] / counts[eligible]
    flat = means.ravel()
    valid_indices = np.flatnonzero(np.isfinite(flat))
    if len(valid_indices) == 0:
        return None, None, None, None
    order = valid_indices[np.argsort(flat[valid_indices])[::-1]]
    best_index = int(order[0])
    best_value = float(flat[best_index])
    second = float(flat[int(order[1])]) if len(order) > 1 else None
    gap = best_value - second if second is not None else 1.0
    return best_index, best_value, second, float(gap)


def expansion_direction_10m(
    weights: np.ndarray,
    fine_row0: int,
    fine_col0: int,
    site: s6c.Site,
) -> tuple[str | None, dict[str, float]]:
    rows, cols = np.meshgrid(
        np.arange(fine_row0, fine_row0 + weights.shape[0]),
        np.arange(fine_col0, fine_col0 + weights.shape[1]),
        indexing="ij",
    )
    xs = cols * FINE_CELL_KM + 0.005
    ys = rows * FINE_CELL_KM + 0.005
    east = xs - site.x
    north = site.y - ys
    angles = (np.degrees(np.arctan2(north, east)) + 360.0) % 360.0
    names = np.array(["E", "NE", "N", "NW", "W", "SW", "S", "SE"], dtype=object)
    indices = ((angles + 22.5) // 45.0).astype(np.int32) % 8
    totals = {
        name: float(weights[indices == index].sum() * FINE_CELL_KM * FINE_CELL_KM)
        for index, name in enumerate(names.tolist())
    }
    total = sum(totals.values())
    if total <= 0:
        return None, {name: 0.0 for name in names.tolist()}
    fractions = {name: value / total for name, value in totals.items()}
    ordered = sorted(fractions.items(), key=lambda item: (-item[1], item[0]))
    direction = ordered[0][0] if ordered[0][1] - ordered[1][1] >= 0.03 else "MULTIPLE_EQUIVALENT"
    return direction, fractions


def zarr_arrays() -> dict[str, tuple[str, Any]]:
    return {
        "elevation_m": ("f4", np.nan),
        "slope_deg": ("f4", np.nan),
        "active_water_distance_km": ("f4", np.nan),
        "form_surface_water_distance_km": ("f4", np.nan),
        "perennial_water_distance_km": ("f4", np.nan),
        "flood_exposure": ("f4", np.nan),
        "site_score": ("f4", -1.0),
        "barony_id": ("i4", -1),
        "exact_surface": ("u1", 0),
        "valid_domain": ("u1", 0),
        "sea_mask_parent_projected": ("u1", 0),
        "wetland_mask_parent_projected": ("u1", 0),
    }


def evidence_slice_digest(arrays: Mapping[str, np.ndarray]) -> str:
    """Hash one site's canonical candidate-evidence slice."""

    digest = hashlib.sha256()
    for name in sorted(zarr_arrays()):
        array = np.ascontiguousarray(arrays[name])
        digest.update(
            canonical_json([name, array.dtype.str, list(array.shape)]).encode("utf-8")
        )
        digest.update(array.tobytes(order="C"))
    return digest.hexdigest()


def verified_bundle_manifest(bundle_path: Path) -> dict[str, Any]:
    """Verify every independently compressed FULL packet in a site bundle."""

    manifest = read_recovery_manifest(bundle_path)
    decompressor = zstd.ZstdDecompressor()
    for descriptor in manifest["packets"]:
        if descriptor["kind"] != "full":
            raise RuntimeError("Stage 6C.5 resume accepts FULL recovery packets only")
        frame = (bundle_path / descriptor["frame_path"]).read_bytes()
        if len(frame) != int(descriptor["frame_size"]):
            raise RuntimeError("Stage 6C.5 recovery-frame size mismatch")
        if hashlib.sha256(frame).hexdigest() != descriptor["frame_sha256"]:
            raise RuntimeError("Stage 6C.5 recovery-frame checksum mismatch")
        raw = decompressor.decompress(frame)
        if len(raw) != int(descriptor["raw_size"]):
            raise RuntimeError("Stage 6C.5 recovery-payload size mismatch")
        if hashlib.sha256(raw).hexdigest() != descriptor["target_hash"]:
            raise RuntimeError("Stage 6C.5 recovery-payload checksum mismatch")
    return manifest


def open_evidence_store(
    path: Path,
    candidates: Sequence[Candidate],
    authority_descriptor: Mapping[str, Any],
) -> zarr.Group:
    group = zarr.open_group(str(path), mode="a", zarr_format=3)
    if "site_complete" not in group:
        compressor = [ZstdCodec(level=HOT_CACHE_ZSTD_LEVEL, checksum=True)]
        for name, (dtype, fill) in zarr_arrays().items():
            group.create_array(
                name,
                shape=(len(candidates), 100, 100),
                chunks=(1, 100, 100),
                dtype=dtype,
                fill_value=fill,
                compressors=compressor,
            )
        group.create_array(
            "site_complete",
            shape=(len(candidates),),
            chunks=(len(candidates),),
            dtype="u1",
            fill_value=0,
            compressors=compressor,
        )
        group.attrs.update({
            "schema": "diadem.stage6c5-candidate-evidence-zarr.v1",
            "method": METHOD,
            "canon_status": CANON_STATUS,
            "cell_size_m": 10,
            "model_resolution_m": 10,
            "terrain_physical_source_resolution_m": 100,
            "terrain_effective_evidence_resolution_m": 100,
            "exact_vector_sampling_resolution_m": 10,
            "candidate_count": len(candidates),
            "candidate_list_sha256": CANDIDATE_LIST_SHA256,
            "authority_id": authority_descriptor["authority_id"],
            "authority_generation": authority_descriptor["generation"],
            "authority_root_hash": authority_descriptor["root_hash"],
            "compression": "ZSTD_LEVEL_3_CHECKSUMMED",
            "official_coordinates_modified": False,
            "hydrology_status": "CURRENT_CORRECTED_VECTOR_AXES_SAMPLED_AT_10M_NOT_REGENERATED",
        })
    if tuple(group["elevation_m"].shape) != (len(candidates), 100, 100):
        raise RuntimeError("Existing Stage 6C.5 evidence Zarr has an incompatible shape")
    return group


def write_evidence_slice(
    group: zarr.Group,
    index: int,
    arrays: Mapping[str, np.ndarray],
    *,
    mark_complete: bool = True,
) -> None:
    group["site_complete"][index] = np.uint8(0)
    for name in zarr_arrays():
        group[name][index, :, :] = np.asarray(arrays[name])
    if mark_complete:
        group["site_complete"][index] = np.uint8(1)


def load_checkpoint(
    checkpoint_path: Path,
    candidate: Candidate,
    evidence_group: zarr.Group,
    output_dir: Path,
    *,
    runtime_identity: str | None = None,
) -> dict[str, Any] | None:
    if not checkpoint_path.is_file() or int(evidence_group["site_complete"][candidate.index]) != 1:
        return None
    try:
        checkpoint = read_json(checkpoint_path)
        if runtime_identity is not None and checkpoint.get("runtime_identity") != runtime_identity:
            return None
        if checkpoint["semantic_key"] != candidate.semantic_key:
            return None
        arrays = {
            name: np.asarray(evidence_group[name][candidate.index, :, :])
            for name in zarr_arrays()
        }
        if evidence_slice_digest(arrays) != checkpoint["evidence_digest"]:
            return None
        manifest = verified_bundle_manifest(
            output_dir / checkpoint["bundle_relative_path"]
        )
        if manifest["bundle_id"] != checkpoint["bundle_id"]:
            return None
        return checkpoint
    except Exception:
        return None


def compute_site_result(
    candidate: Candidate,
    rasters: s6c.RasterStack,
    topology: s6c.ExactSurfaceIndex,
    vectors: s6c.VectorStack,
    output_dir: Path,
) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
    site = candidate.site
    inherited = candidate.inherited
    profile = candidate.profile
    policy = rules.score_policy(profile)
    tile_spec = TileSpec(
        candidate.tile_id,
        candidate.tile_parent_row0,
        candidate.tile_parent_col0,
        CORE_PARENT_CELLS,
        CORE_PARENT_CELLS,
        halo_cells=HALO_FINE_CELLS,
    )
    support_row0 = max(0, candidate.tile_parent_row0 - PARENT_SUPPORT_CELLS)
    support_col0 = max(0, candidate.tile_parent_col0 - PARENT_SUPPORT_CELLS)
    support_row1 = min(
        18_600,
        candidate.tile_parent_row0 + CORE_PARENT_CELLS + PARENT_SUPPORT_CELLS,
    )
    support_col1 = min(
        22_000,
        candidate.tile_parent_col0 + CORE_PARENT_CELLS + PARENT_SUPPORT_CELLS,
    )
    parent_data = rasters.terrain.read_block(
        support_row0,
        support_col0,
        support_row1 - support_row0,
        support_col1 - support_col0,
    )
    parent = ParentRasterWindow(parent_data, support_row0, support_col0, GRID)
    tile = refine_terrain_safe(
        parent,
        tile_spec,
        TERRAIN_RECIPE,
        source_hashes={
            "terrain_authority_root": str(rasters.terrain.descriptor["root_hash"]),
            "stage6c5_semantic_key": candidate.semantic_key,
        },
        # One real production tile proves the accelerated path against the
        # trusted reference. Later tiles retain the same recipe/source contract.
        verify_reference=(candidate.index == 0),
    )
    core_slice = tile_spec.core_slice
    elevation_core = tile.arrays["elevation_10m"][core_slice].astype(np.float32, copy=False)
    slope_core = np.degrees(
        np.arctan(tile.arrays["local_gradient_magnitude_10m"][core_slice])
    ).astype(np.float32)
    broad_slope_core = np.degrees(
        np.arctan(tile.arrays["broad_gradient_magnitude_10m"][core_slice])
    ).astype(np.float32)

    parent_core = rasters.read_block(
        candidate.tile_parent_row0,
        candidate.tile_parent_col0,
        CORE_PARENT_CELLS,
        CORE_PARENT_CELLS,
    )
    fine_row0 = candidate.tile_parent_row0 * FINE_PER_PARENT
    fine_col0 = candidate.tile_parent_col0 * FINE_PER_PARENT
    barony_core = rasterize_exact_surface_10m(
        topology, fine_row0, fine_col0, FINE_CORE_CELLS, FINE_CORE_CELLS
    )
    sea_core = repeat_parent(parent_core["sea"]).astype(np.uint8, copy=False)
    wetland_core = repeat_parent(parent_core["wetland"]).astype(np.uint8, copy=False)
    seren_core = repeat_parent(parent_core["seren"]).astype(np.uint8, copy=False)
    flood_core = repeat_parent(parent_core["flood_exposure"]).astype(np.float32, copy=False)

    source_row_offset = (
        candidate.source_parent_row0 - candidate.tile_parent_row0
    ) * FINE_PER_PARENT
    source_col_offset = (
        candidate.source_parent_col0 - candidate.tile_parent_col0
    ) * FINE_PER_PARENT
    rs = slice(source_row_offset, source_row_offset + 100)
    cs = slice(source_col_offset, source_col_offset + 100)

    distances, class_minima = exact_water_evidence(vectors, candidate)
    candidate_barony = barony_core[rs, cs]
    candidate_surface = candidate_barony > 0
    same_barony = (
        candidate_surface
        if site.barony_id is None
        else candidate_barony == site.barony_id
    )
    candidate_sea = sea_core[rs, cs]
    candidate_wetland = wetland_core[rs, cs]
    candidate_seren = seren_core[rs, cs]
    candidate_flood = flood_core[rs, cs].astype(np.float64)
    candidate_elevation = elevation_core[rs, cs].astype(np.float64)
    candidate_slope = slope_core[rs, cs].astype(np.float64)
    candidate_broad_slope = broad_slope_core[rs, cs].astype(np.float64)

    form_water = distances["active"]
    if site.realised_form == "SURFACE_LAGOON_SETTLEMENT":
        form_water = np.minimum.reduce((
            distances["active"], distances["special"], distances["lake"],
        ))
        form_water = np.where(candidate_seren > 0, 0.0, form_water)
    valid, domain_fit_cells, ordinary_surface_fallback = s6c.domain_candidate_mask(
        site,
        same_barony.ravel(),
        candidate_surface.ravel(),
        candidate_sea.ravel(),
        candidate_wetland.ravel(),
        candidate_seren.ravel(),
        {key: value.ravel() for key, value in distances.items()},
    )
    valid = valid.reshape(100, 100)
    domain_fit_cells = domain_fit_cells.reshape(100, 100)
    valid_count = int(valid.sum())
    metric_mask = valid if valid_count else np.ones((100, 100), dtype=bool)

    scores = s6c.candidate_cell_scores(
        candidate_slope.ravel(),
        form_water.ravel(),
        candidate_flood.ravel(),
        domain_fit_cells.ravel(),
        valid.ravel(),
        policy,
    ).reshape(100, 100)
    best_parent_index, best_parent_score, second_parent_score, parent_gap = parent_score_summary(scores)
    best_score = None
    second_cell_score = None
    model_anchor_x = model_anchor_y = None
    best_parent_row = best_parent_col = None
    if best_parent_index is not None:
        best_parent_row, best_parent_col = divmod(best_parent_index, 10)
        block = scores[
            best_parent_row * 10 : (best_parent_row + 1) * 10,
            best_parent_col * 10 : (best_parent_col + 1) * 10,
        ]
        flat_order = np.argsort(block.ravel())[::-1]
        best_child = int(flat_order[0])
        child_row, child_col = divmod(best_child, 10)
        best_score = float(block.ravel()[best_child])
        second_cell_score = (
            float(block.ravel()[int(flat_order[1])]) if len(flat_order) > 1 else None
        )
        global_fine_row = (
            candidate.source_parent_row0 * 10 + best_parent_row * 10 + child_row
        )
        global_fine_col = (
            candidate.source_parent_col0 * 10 + best_parent_col * 10 + child_col
        )
        model_anchor_x = global_fine_col * FINE_CELL_KM + 0.005
        model_anchor_y = global_fine_row * FINE_CELL_KM + 0.005

    is_3d = candidate.disposition.startswith("SURFACE_OR_INTERFACE")
    parent_clear = parent_gap is not None and parent_gap >= PARENT_SCORE_CLEAR_GAP
    child_gap = (
        best_score - second_cell_score
        if best_score is not None and second_cell_score is not None
        else None
    )
    child_clear = child_gap is not None and child_gap >= CELL_SCORE_CLEAR_GAP
    if is_3d:
        selection_status = "SURFACE_OR_INTERFACE_CONTEXT_ONLY_3D_DEFERRED_NO_RELOCATION"
        model_anchor_x = model_anchor_y = None
    elif best_parent_index is None:
        selection_status = "NO_VALID_10M_SUPPORT_OFFICIAL_COORDINATE_UNCHANGED"
        model_anchor_x = model_anchor_y = None
    elif parent_clear and child_clear:
        selection_status = "MODELLED_10M_PREFERENCE_CLEAR_PARENT_SEPARATION_OFFICIAL_COORDINATE_UNCHANGED"
    elif parent_clear:
        selection_status = "MODELLED_100M_PARENT_CLEAR_MULTIPLE_EQUIVALENT_10M_CELLS_OFFICIAL_COORDINATE_UNCHANGED"
        model_anchor_x = model_anchor_y = None
    else:
        selection_status = "MODELLED_10M_PREFERENCE_LOW_SEPARATION_OFFICIAL_COORDINATE_UNCHANGED"
        model_anchor_x = model_anchor_y = None

    terrain_elevation = float(np.nanmedian(candidate_elevation[metric_mask]))
    terrain_slope = float(np.nanmedian(candidate_slope[metric_mask]))
    broad_slope = float(np.nanmedian(candidate_broad_slope[metric_mask]))
    slope_p90 = float(np.nanquantile(candidate_slope[metric_mask], 0.90))
    local_relief = float(
        np.nanquantile(candidate_elevation, 0.90)
        - np.nanquantile(candidate_elevation, 0.10)
    )
    water_distance = float(np.median(form_water[metric_mask]))
    perennial_distance = float(np.median(distances["perennial"][metric_mask]))
    flood_exposure = float(np.mean(candidate_flood[metric_mask]))
    land_fraction = float(np.mean(candidate_surface & (candidate_sea == 0)))
    wetland_fraction = float(np.mean(candidate_wetland > 0))
    seren_fraction = float(np.mean(candidate_seren > 0))
    domain_fit = float(np.mean(domain_fit_cells[metric_mask]))

    resolved_policy, _ = rules._resolved_policy(
        profile["realised_settlement_form"],
        profile["effective_vertical_domain"],
        profile["haus_id"],
    )
    slope_limit = float(policy["components"]["TERRAIN_SUPPORT"].get("p1") or 45.0)
    dev = s6c.developable_mask(
        site,
        barony_core,
        {
            "slope": slope_core,
            "sea": sea_core,
            "seren": seren_core,
            "wetland": wetland_core,
            "flood_exposure": flood_core,
        },
        slope_limit,
        resolved_policy["flood_tolerance"],
        ordinary_surface_fallback,
    )
    fine_rows, fine_cols = np.meshgrid(
        np.arange(fine_row0, fine_row0 + FINE_CORE_CELLS),
        np.arange(fine_col0, fine_col0 + FINE_CORE_CELLS),
        indexing="ij",
    )
    grid_x = fine_cols * FINE_CELL_KM + 0.005
    grid_y = fine_rows * FINE_CELL_KM + 0.005
    distance2 = (grid_x - site.x) ** 2 + (grid_y - site.y) ** 2
    circle1 = distance2 <= 1.0
    develop_r1 = float((dev * circle1).sum() * FINE_CELL_KM * FINE_CELL_KM)
    expansion_direction, expansion_weights = expansion_direction_10m(
        dev * circle1, fine_row0, fine_col0, site
    )

    land_access_cost = float(np.clip(
        0.60 * min(terrain_slope / 35.0, 1.0)
        + 0.25 * min(local_relief / 500.0, 1.0)
        + 0.15 * flood_exposure,
        0.0,
        1.0,
    ))
    water_access = float(1.0 / (1.0 + water_distance / 2.0))
    seasonal_reliability = float(np.clip(
        0.75 * math.exp(-perennial_distance / 10.0)
        + 0.25 * math.exp(-water_distance / 5.0),
        0.0,
        1.0,
    ))
    raw_metrics = {
        "terrain_slope_deg": terrain_slope,
        "corrected_surface_water_distance_km": water_distance,
        "flood_exposure_index": flood_exposure,
        "developable_area_r1_km2": develop_r1,
        "developable_area_r5_km2": inherited["developable_area_r5_km2"],
        "land_access_cost_index": land_access_cost,
        "water_access_index": water_access,
        "seasonal_reliability_index": seasonal_reliability,
        "domain_fit_index": domain_fit,
    }
    valid_scores = scores[scores >= 0]
    spread = float(np.std(valid_scores)) if len(valid_scores) else 0.20
    uncertainty = float(np.clip(
        0.10 + 0.80 * spread + (0.06 if inherited["provisional_anchor"] else 0.0),
        0.10,
        0.32,
    ))
    scored = None if is_3d else s6c.score_site_metrics(raw_metrics, profile, policy, uncertainty)

    limiting = set(json.loads(inherited["limiting_factors_json"]))
    limiting.add("MODELLED_10M_TERRAIN_NOT_OBSERVED_TEN_METRE_EVIDENCE")
    limiting.add("HYDROLOGY_AXES_INHERITED_CURRENT_CORRECTED_NOT_REGENERATED_IN_STAGE6C5")
    if selection_status.startswith("MODELLED_10M_PREFERENCE_CLEAR"):
        limiting.discard("HIGH_PRIORITY_SITE_HAS_EQUIVALENT_100M_CELLS")
    elif selection_status.startswith("MODELLED_100M_PARENT_CLEAR"):
        limiting.add("MULTIPLE_EQUIVALENT_10M_CELLS_NO_PRECISE_ANCHOR")
    elif not is_3d:
        limiting.add("TEN_METRE_PREFERENCE_REMAINS_LOW_SEPARATION")
    if inherited["horizontal_uncertainty_radius_km"] is None:
        limiting.add("COORDINATE_UNCERTAINTY_UNBOUNDED_FINE_LENS_REVIEW")
    if is_3d:
        limiting.add("SPECIALIST_3D_GEOMETRY_AND_CAPACITY_DEFERRED")
    if valid_count == 0 and not is_3d:
        limiting.add("NO_VALID_10M_SUPPORT_CELL")

    if is_3d:
        review_status = "DEFERRED_SPECIALIST_3D"
    elif valid_count == 0:
        review_status = "HARD_EXCEPTION"
    elif selection_status.startswith("MODELLED_10M_PREFERENCE_CLEAR"):
        review_status = "PASS_REFINED_REVIEW_ONLY"
    else:
        review_status = "REVIEW_PRIORITY_LOW_SEPARATION"

    candidate_arrays = {
        "elevation_m": candidate_elevation.astype(np.float32),
        "slope_deg": candidate_slope.astype(np.float32),
        "active_water_distance_km": distances["active"].astype(np.float32),
        "form_surface_water_distance_km": form_water.astype(np.float32),
        "perennial_water_distance_km": distances["perennial"].astype(np.float32),
        "flood_exposure": candidate_flood.astype(np.float32),
        "site_score": scores.astype(np.float32),
        "barony_id": candidate_barony.astype(np.int32),
        "exact_surface": candidate_surface.astype(np.uint8),
        "valid_domain": valid.astype(np.uint8),
        "sea_mask_parent_projected": candidate_sea.astype(np.uint8),
        "wetland_mask_parent_projected": candidate_wetland.astype(np.uint8),
    }
    evidence_digest = evidence_slice_digest(candidate_arrays)

    tile.encoded_arrays.update({
        "exact_barony_id_10m_core": barony_core,
        "sea_mask_parent_100m_projected_10m_core": sea_core,
        "wetland_mask_parent_100m_projected_10m_core": wetland_core,
        "serenakrone_mask_parent_100m_projected_10m_core": seren_core,
        "flood_exposure_parent_100m_projected_10m_core": flood_core,
        "candidate_active_water_distance_km": candidate_arrays["active_water_distance_km"],
        "candidate_perennial_water_distance_km": candidate_arrays["perennial_water_distance_km"],
        "candidate_valid_domain": candidate_arrays["valid_domain"],
        "candidate_site_score": candidate_arrays["site_score"],
    })
    tile.metadata["stage6c5"] = {
        "schema": "diadem.stage6c5-evidence-tile.v1",
        "semantic_key": candidate.semantic_key,
        "settlement_id": site.settlement_id,
        "disposition": candidate.disposition,
        "official_coordinate_km": [site.x, site.y],
        "official_coordinate_modified": False,
        "candidate_window_parent": [
            candidate.source_parent_row0,
            candidate.source_parent_col0,
            CANDIDATE_PARENT_CELLS,
            CANDIDATE_PARENT_CELLS,
        ],
        "context_window_parent": [
            candidate.tile_parent_row0,
            candidate.tile_parent_col0,
            CORE_PARENT_CELLS,
            CORE_PARENT_CELLS,
        ],
        "layer_resolution": {
            "terrain": "MODELLED_10M_FROM_100M_PARENT; EFFECTIVE_EVIDENCE_100M",
            "exact_surface_and_barony": "EXACT_VECTOR_RASTERISED_AT_10M_CELL_CENTRES",
            "hydrology_distance": "CURRENT_CORRECTED_VECTOR_GEOMETRY_SAMPLED_AT_10M; NOT_REGENERATED",
            "sea_wetland_lagoon_flood": "100M_PARENT_CLASSES_PROJECTED_TO_10M; EFFECTIVE_EVIDENCE_100M",
        },
        "canon_status": CANON_STATUS,
        "method": METHOD,
    }
    # The descriptive tile ID remains in metadata and the database.  A compact
    # physical name avoids Windows MAX_PATH failures in the bundle writer's
    # temporary frame directory.
    bundle_path = output_dir / "tile_cache" / f"t_{candidate.semantic_key[:20]}.zstbundle"
    if bundle_path.exists():
        shutil.rmtree(bundle_path)
    write_tile_recovery_bundle(
        tile,
        bundle_path,
        compact=True,
        compression_level=HOT_CACHE_ZSTD_LEVEL,
    )
    bundle_manifest = verified_bundle_manifest(bundle_path)

    component_scores = scored["component_scores"] if scored else {}
    row = {
        "settlement_id": site.settlement_id,
        "functional_tier": site.functional_tier,
        "disposition": candidate.disposition,
        "official_x_km": site.x,
        "official_y_km": site.y,
        "official_coordinate_modified": 0,
        "modelled_preferred_x_km": model_anchor_x,
        "modelled_preferred_y_km": model_anchor_y,
        "selection_status": selection_status,
        "best_parent_row_in_candidate": best_parent_row,
        "best_parent_col_in_candidate": best_parent_col,
        "best_parent_mean_score": best_parent_score,
        "second_parent_mean_score": second_parent_score,
        "best_parent_score_gap": parent_gap,
        "best_cell_score": best_score,
        "second_cell_score": second_cell_score,
        "model_cell_size_m": 10,
        "terrain_effective_evidence_resolution_m": 100,
        "exact_vector_sampling_resolution_m": 10,
        "candidate_cell_count": 10_000,
        "candidate_valid_cell_count": valid_count,
        "candidate_support_fraction": valid_count / 10_000.0,
        "terrain_elevation_m_100m": inherited["terrain_elevation_m"],
        "terrain_elevation_m_10m": terrain_elevation,
        "terrain_elevation_delta_m": terrain_elevation - inherited["terrain_elevation_m"],
        "terrain_slope_deg_100m": inherited["terrain_slope_deg"],
        "terrain_slope_deg_10m": terrain_slope,
        "terrain_slope_delta_deg": terrain_slope - inherited["terrain_slope_deg"],
        "broad_slope_deg_10m": broad_slope,
        "terrain_slope_p90_deg_10m": slope_p90,
        "local_relief_m_100m": inherited["local_relief_m"],
        "local_relief_m_10m": local_relief,
        "land_fraction_10m": land_fraction,
        "wetland_fraction_10m": wetland_fraction,
        "serenakrone_water_fraction_10m": seren_fraction,
        "surface_water_distance_km_100m": inherited["corrected_surface_water_distance_km"],
        "surface_water_distance_km_10m": water_distance,
        "surface_water_distance_delta_km": water_distance - inherited["corrected_surface_water_distance_km"],
        "perennial_distance_km_100m": inherited["corrected_perennial_channel_distance_km"],
        "perennial_distance_km_10m": perennial_distance,
        "perennial_distance_delta_km": perennial_distance - inherited["corrected_perennial_channel_distance_km"],
        "min_major_distance_km_10m": class_minima["major"],
        "min_minor_distance_km_10m": class_minima["minor"],
        "min_special_distance_km_10m": class_minima["special"],
        "min_permanent_lake_distance_km_10m": class_minima["lake"],
        "min_seasonal_lake_distance_km_10m": class_minima["seasonal_lake"],
        "min_coast_distance_km_10m": class_minima["coast"],
        "flood_exposure_100m": inherited["flood_exposure_index"],
        "flood_exposure_10m": flood_exposure,
        "developable_area_r1_km2_100m": inherited["developable_area_r1_km2"],
        "developable_area_r1_km2_10m": develop_r1,
        "developable_area_r5_km2_inherited_100m": inherited["developable_area_r5_km2"],
        "land_access_cost_index_10m": land_access_cost,
        "water_access_index_10m": water_access,
        "seasonal_reliability_index_10m": seasonal_reliability,
        "domain_fit_index_10m": domain_fit,
        "expansion_direction_r1_10m": expansion_direction,
        "expansion_sector_weights_r1_json": canonical_json(expansion_weights),
        "terrain_support_score_10m": component_scores.get("TERRAIN_SUPPORT"),
        "hydrology_support_score_10m": component_scores.get("HYDROLOGY_SUPPORT"),
        "flood_compatibility_score_10m": component_scores.get("FLOOD_COMPATIBILITY"),
        "core_capacity_score_10m": component_scores.get("CORE_CAPACITY"),
        "capacity_support_score_100m": inherited["capacity_support_score"],
        "capacity_support_score_10m": scored["capacity"] if scored else None,
        "access_support_score_100m": inherited["access_support_score"],
        "access_support_score_10m": scored["access"] if scored else None,
        "capacity_band_100m": inherited["capacity_band"],
        "capacity_band_10m": scored["capacity_band"] if scored else None,
        "score_uncertainty": uncertainty if scored else None,
        "evidence_confidence_score": inherited["evidence_confidence_score"],
        "limiting_factors_json": canonical_json(sorted(limiting)),
        "review_status": review_status,
        "hydrology_status": "CURRENT_CORRECTED_VECTOR_AXES_SAMPLED_AT_10M_NOT_REGENERATED",
        "terrain_status": "MODELLED_10M_DERIVED_REVIEW_ONLY_EFFECTIVE_EVIDENCE_100M",
        "semantic_key": candidate.semantic_key,
        "tile_id": candidate.tile_id,
        "bundle_id": bundle_manifest["bundle_id"],
        "method_version": METHOD,
        "canon_status": CANON_STATUS,
    }
    tile_row = {
        "tile_id": candidate.tile_id,
        "settlement_id": site.settlement_id,
        "core_parent_row0": candidate.tile_parent_row0,
        "core_parent_col0": candidate.tile_parent_col0,
        "core_parent_height": CORE_PARENT_CELLS,
        "core_parent_width": CORE_PARENT_CELLS,
        "fine_cell_size_m": 10,
        "fine_core_cell_count": FINE_CORE_CELLS * FINE_CORE_CELLS,
        "halo_fine_cells": HALO_FINE_CELLS,
        "bundle_relative_path": bundle_path.relative_to(output_dir).as_posix(),
        "bundle_id": bundle_manifest["bundle_id"],
        "packet_count": bundle_manifest["packet_count"],
        "parent_aggregation_max_abs_error_m": tile.metadata["qa"]["parent_aggregation_max_abs_error_m"],
        "broad_parent_aggregation_max_abs_error_m": tile.metadata["qa"]["broad_parent_aggregation_max_abs_error_m"],
        "broad_gradient_direction_consistent_fraction": tile.metadata["qa"]["broad_gradient_direction_consistent_fraction"],
        "local_gradient_direction_consistent_fraction": tile.metadata["qa"]["local_gradient_direction_consistent_fraction"],
        "semantic_key": candidate.semantic_key,
        "cache_status": "PINNED_THROUGH_STAGE6D_AND_FOOTPRINT_PASS",
    }
    candidate_row = {
        "settlement_id": site.settlement_id,
        "functional_tier": site.functional_tier,
        "inclusion_reason": "ACTIVE_FT0_OR_FT1_SETTLEMENT",
        "inherited_analysis_status": inherited["analysis_status"],
        "disposition": candidate.disposition,
        "official_x_km": site.x,
        "official_y_km": site.y,
        "horizontal_uncertainty_radius_km": inherited["horizontal_uncertainty_radius_km"],
        "provisional_anchor": inherited["provisional_anchor"],
        "zarr_index": candidate.index,
        "tile_id": candidate.tile_id,
        "semantic_key": candidate.semantic_key,
        "canon_status": CANON_STATUS,
    }
    return {
        "schema": "diadem.stage6c5-site-checkpoint.v1",
        "completed_utc": utc_now(),
        "semantic_key": candidate.semantic_key,
        "bundle_relative_path": bundle_path.relative_to(output_dir).as_posix(),
        "bundle_id": bundle_manifest["bundle_id"],
        "evidence_digest": evidence_digest,
        "candidate_row": candidate_row,
        "tile_row": tile_row,
        "result_row": row,
    }, candidate_arrays


def site_result(
    candidate: Candidate,
    rasters: s6c.RasterStack,
    topology: s6c.ExactSurfaceIndex,
    vectors: s6c.VectorStack,
    output_dir: Path,
    evidence_group: zarr.Group,
) -> dict[str, Any]:
    """Retained serial entrypoint; the run coordinator uses the split directly."""
    checkpoint, arrays = compute_site_result(candidate, rasters, topology, vectors, output_dir)
    write_evidence_slice(evidence_group, candidate.index, arrays)
    return checkpoint


@dataclass(frozen=True)
class PreparedTerrain:
    values: np.ndarray
    row0: int
    col0: int
    descriptor: Mapping[str, Any]

    def read_block(self, row0: int, col0: int, height: int, width: int) -> np.ndarray:
        r, c = row0 - self.row0, col0 - self.col0
        if not (0 <= r < r + height <= self.values.shape[0] and
                0 <= c < c + width <= self.values.shape[1]):
            raise ValueError("Prepared terrain request exceeds its exact support window")
        return self.values[r:r + height, c:c + width].copy()


@dataclass(frozen=True)
class PreparedCandidateRasters:
    """Array-only worker input: no authority, GDAL or Zarr handles cross threads."""
    terrain: PreparedTerrain
    core_window: tuple[int, int, int, int]
    core: Mapping[str, np.ndarray]

    def read_block(self, row0: int, col0: int, height: int, width: int) -> dict[str, np.ndarray]:
        if (row0, col0, height, width) != self.core_window:
            raise ValueError("Unexpected prepared candidate raster window")
        return {key: value.copy() for key, value in self.core.items()}


def prepare_candidate_rasters(candidate: Candidate, rasters: s6c.RasterStack) -> PreparedCandidateRasters:
    row0 = max(0, candidate.tile_parent_row0 - PARENT_SUPPORT_CELLS)
    col0 = max(0, candidate.tile_parent_col0 - PARENT_SUPPORT_CELLS)
    row1 = min(18_600, candidate.tile_parent_row0 + CORE_PARENT_CELLS + PARENT_SUPPORT_CELLS)
    col1 = min(22_000, candidate.tile_parent_col0 + CORE_PARENT_CELLS + PARENT_SUPPORT_CELLS)
    values = rasters.terrain.read_block(row0, col0, row1 - row0, col1 - col0)
    core_window = (candidate.tile_parent_row0, candidate.tile_parent_col0,
                   CORE_PARENT_CELLS, CORE_PARENT_CELLS)
    core = rasters.read_block(*core_window)
    return PreparedCandidateRasters(
        PreparedTerrain(values, row0, col0, dict(rasters.terrain.descriptor)), core_window, core
    )


def install_private_bundle(output_dir: Path, private_dir: Path, checkpoint: Mapping[str, Any]) -> None:
    """Only the coordinator replaces public bundles; retain a replaced predecessor."""
    relative = Path(checkpoint["bundle_relative_path"])
    source = (private_dir / relative).resolve()
    target = (output_dir / relative).resolve()
    if not source.is_relative_to(private_dir.resolve()) or not target.is_relative_to(output_dir.resolve()):
        raise ValueError("Recovery bundle path escaped its owned directory")
    if verified_bundle_manifest(source)["bundle_id"] != checkpoint["bundle_id"]:
        raise RuntimeError("Private recovery bundle identity mismatch")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        predecessor = output_dir / "predecessor_bundles" / str(time.time_ns()) / target.name
        predecessor.parent.mkdir(parents=True, exist_ok=False)
        os.replace(target, predecessor)
        try:
            os.replace(source, target)
        except BaseException:
            os.replace(predecessor, target)
            raise
    else:
        os.replace(source, target)


def create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        PRAGMA foreign_keys=ON;
        DROP TABLE IF EXISTS stage6c5_cache_object;
        DROP TABLE IF EXISTS stage6c5_site_refinement;
        DROP TABLE IF EXISTS stage6c5_tile_manifest;
        DROP TABLE IF EXISTS stage6c5_candidate_registry;
        DROP TABLE IF EXISTS stage6c5_run_metadata;
        DROP VIEW IF EXISTS stage6c5_stage6d_inputs;
        DROP VIEW IF EXISTS stage6c5_review_queue;

        CREATE TABLE stage6c5_run_metadata (
            run_id TEXT PRIMARY KEY,
            created_utc TEXT NOT NULL,
            method_version TEXT NOT NULL,
            canon_status TEXT NOT NULL,
            candidate_list_sha256 TEXT NOT NULL CHECK(length(candidate_list_sha256)=64),
            candidate_count INTEGER NOT NULL,
            recipe_json TEXT NOT NULL CHECK(json_valid(recipe_json)),
            source_identity_json TEXT NOT NULL CHECK(json_valid(source_identity_json)),
            storage_policy TEXT NOT NULL,
            hydrology_status TEXT NOT NULL
        ) WITHOUT ROWID;

        CREATE TABLE stage6c5_candidate_registry (
            settlement_id TEXT PRIMARY KEY REFERENCES settlement(settlement_id),
            functional_tier TEXT NOT NULL,
            inclusion_reason TEXT NOT NULL,
            inherited_analysis_status TEXT NOT NULL,
            disposition TEXT NOT NULL,
            official_x_km REAL NOT NULL,
            official_y_km REAL NOT NULL,
            horizontal_uncertainty_radius_km REAL,
            provisional_anchor INTEGER NOT NULL CHECK(provisional_anchor IN (0,1)),
            zarr_index INTEGER NOT NULL UNIQUE,
            tile_id TEXT NOT NULL UNIQUE,
            semantic_key TEXT NOT NULL CHECK(length(semantic_key)=64),
            canon_status TEXT NOT NULL
        ) WITHOUT ROWID;

        CREATE TABLE stage6c5_tile_manifest (
            tile_id TEXT PRIMARY KEY,
            settlement_id TEXT NOT NULL UNIQUE REFERENCES stage6c5_candidate_registry(settlement_id),
            core_parent_row0 INTEGER NOT NULL,
            core_parent_col0 INTEGER NOT NULL,
            core_parent_height INTEGER NOT NULL,
            core_parent_width INTEGER NOT NULL,
            fine_cell_size_m INTEGER NOT NULL,
            fine_core_cell_count INTEGER NOT NULL,
            halo_fine_cells INTEGER NOT NULL,
            bundle_relative_path TEXT NOT NULL,
            bundle_id TEXT NOT NULL CHECK(length(bundle_id)=64),
            packet_count INTEGER NOT NULL,
            parent_aggregation_max_abs_error_m REAL NOT NULL,
            broad_parent_aggregation_max_abs_error_m REAL NOT NULL,
            broad_gradient_direction_consistent_fraction REAL NOT NULL,
            local_gradient_direction_consistent_fraction REAL NOT NULL,
            semantic_key TEXT NOT NULL CHECK(length(semantic_key)=64),
            cache_status TEXT NOT NULL
        ) WITHOUT ROWID;

        CREATE TABLE stage6c5_site_refinement (
            settlement_id TEXT PRIMARY KEY REFERENCES stage6c5_candidate_registry(settlement_id),
            functional_tier TEXT NOT NULL,
            disposition TEXT NOT NULL,
            official_x_km REAL NOT NULL,
            official_y_km REAL NOT NULL,
            official_coordinate_modified INTEGER NOT NULL CHECK(official_coordinate_modified=0),
            modelled_preferred_x_km REAL,
            modelled_preferred_y_km REAL,
            selection_status TEXT NOT NULL,
            best_parent_row_in_candidate INTEGER,
            best_parent_col_in_candidate INTEGER,
            best_parent_mean_score REAL,
            second_parent_mean_score REAL,
            best_parent_score_gap REAL,
            best_cell_score REAL,
            second_cell_score REAL,
            model_cell_size_m INTEGER NOT NULL,
            terrain_effective_evidence_resolution_m INTEGER NOT NULL,
            exact_vector_sampling_resolution_m INTEGER NOT NULL,
            candidate_cell_count INTEGER NOT NULL,
            candidate_valid_cell_count INTEGER NOT NULL,
            candidate_support_fraction REAL NOT NULL,
            terrain_elevation_m_100m REAL,
            terrain_elevation_m_10m REAL,
            terrain_elevation_delta_m REAL,
            terrain_slope_deg_100m REAL,
            terrain_slope_deg_10m REAL,
            terrain_slope_delta_deg REAL,
            broad_slope_deg_10m REAL,
            terrain_slope_p90_deg_10m REAL,
            local_relief_m_100m REAL,
            local_relief_m_10m REAL,
            land_fraction_10m REAL,
            wetland_fraction_10m REAL,
            serenakrone_water_fraction_10m REAL,
            surface_water_distance_km_100m REAL,
            surface_water_distance_km_10m REAL,
            surface_water_distance_delta_km REAL,
            perennial_distance_km_100m REAL,
            perennial_distance_km_10m REAL,
            perennial_distance_delta_km REAL,
            min_major_distance_km_10m REAL,
            min_minor_distance_km_10m REAL,
            min_special_distance_km_10m REAL,
            min_permanent_lake_distance_km_10m REAL,
            min_seasonal_lake_distance_km_10m REAL,
            min_coast_distance_km_10m REAL,
            flood_exposure_100m REAL,
            flood_exposure_10m REAL,
            developable_area_r1_km2_100m REAL,
            developable_area_r1_km2_10m REAL,
            developable_area_r5_km2_inherited_100m REAL,
            land_access_cost_index_10m REAL,
            water_access_index_10m REAL,
            seasonal_reliability_index_10m REAL,
            domain_fit_index_10m REAL,
            expansion_direction_r1_10m TEXT,
            expansion_sector_weights_r1_json TEXT NOT NULL CHECK(json_valid(expansion_sector_weights_r1_json)),
            terrain_support_score_10m REAL,
            hydrology_support_score_10m REAL,
            flood_compatibility_score_10m REAL,
            core_capacity_score_10m REAL,
            capacity_support_score_100m REAL,
            capacity_support_score_10m REAL,
            access_support_score_100m REAL,
            access_support_score_10m REAL,
            capacity_band_100m TEXT,
            capacity_band_10m TEXT,
            score_uncertainty REAL,
            evidence_confidence_score REAL,
            limiting_factors_json TEXT NOT NULL CHECK(json_valid(limiting_factors_json)),
            review_status TEXT NOT NULL,
            hydrology_status TEXT NOT NULL,
            terrain_status TEXT NOT NULL,
            semantic_key TEXT NOT NULL CHECK(length(semantic_key)=64),
            tile_id TEXT NOT NULL REFERENCES stage6c5_tile_manifest(tile_id),
            bundle_id TEXT NOT NULL CHECK(length(bundle_id)=64),
            method_version TEXT NOT NULL,
            canon_status TEXT NOT NULL
        ) WITHOUT ROWID;

        CREATE TABLE stage6c5_cache_object (
            cache_object_id TEXT PRIMARY KEY,
            tile_id TEXT NOT NULL REFERENCES stage6c5_tile_manifest(tile_id),
            artifact_path TEXT,
            content_sha256 TEXT NOT NULL CHECK(length(content_sha256)=64),
            raw_size_bytes INTEGER NOT NULL,
            frame_size_bytes INTEGER NOT NULL,
            cache_status TEXT NOT NULL
        ) WITHOUT ROWID;

        CREATE INDEX stage6c5_refinement_status_idx
            ON stage6c5_site_refinement(review_status, selection_status);
        CREATE INDEX stage6c5_refinement_tier_idx
            ON stage6c5_site_refinement(functional_tier);

        CREATE VIEW stage6c5_review_queue AS
        SELECT * FROM stage6c5_site_refinement
        WHERE review_status <> 'PASS_REFINED_REVIEW_ONLY';
        """
    )
    install_stage6c5_stage6d_view(connection)


def insert_dicts(
    connection: sqlite3.Connection,
    table: str,
    rows: Sequence[Mapping[str, Any]],
) -> None:
    if not rows:
        return
    columns = list(rows[0])
    placeholders = ",".join("?" for _ in columns)
    connection.executemany(
        f"INSERT INTO {table} ({','.join(columns)}) VALUES ({placeholders})",
        [[row.get(column) for column in columns] for row in rows],
    )


def cache_rows(output_dir: Path, tile_rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for tile in tile_rows:
        manifest = read_recovery_manifest(output_dir / str(tile["bundle_relative_path"]))
        for packet in manifest["packets"]:
            rows.append({
                "cache_object_id": sha256_text(
                    str(tile["tile_id"]) + "|" + str(packet["sequence"]) + "|" + packet["target_hash"]
                ),
                "tile_id": tile["tile_id"],
                "artifact_path": packet.get("artifact_path"),
                "content_sha256": packet["target_hash"],
                "raw_size_bytes": packet["raw_size"],
                "frame_size_bytes": packet["frame_size"],
                "cache_status": "PINNED_THROUGH_STAGE6D_AND_FOOTPRINT_PASS",
            })
    return rows


def build_database(
    output_dir: Path,
    checkpoints: Sequence[Mapping[str, Any]],
    authority_descriptor: Mapping[str, Any],
) -> tuple[Path, Path]:
    output_db = output_dir / OUTPUT_DB_NAME
    output_gpkg = output_dir / OUTPUT_GPKG_NAME
    sqlite_backup(PARENT_DB, output_db)
    candidate_rows = [dict(item["candidate_row"]) for item in checkpoints]
    tile_rows = [dict(item["tile_row"]) for item in checkpoints]
    result_rows = [dict(item["result_row"]) for item in checkpoints]
    object_rows = cache_rows(output_dir, tile_rows)
    with sqlite3.connect(output_db) as connection:
        create_schema(connection)
        source_identity = {
            "parent_stage6c_sqlite_sha256": sha256_file(PARENT_DB),
            "authority_id": authority_descriptor["authority_id"],
            "authority_generation": authority_descriptor["generation"],
            "authority_root_hash": authority_descriptor["root_hash"],
            "stage6c_source_manifest_digest": s6c.table_digest(connection, "stage6c_source_manifest"),
        }
        connection.execute(
            "INSERT INTO stage6c5_run_metadata VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                "S6C5-" + sha256_text(canonical_json([METHOD, CANDIDATE_LIST_SHA256, source_identity]))[:20].upper(),
                utc_now(), METHOD, CANON_STATUS, CANDIDATE_LIST_SHA256,
                len(checkpoints), canonical_json(terrain_recipe_identity()),
                canonical_json(source_identity),
                "PER_SITE_INDEPENDENT_ZSTD_L3_FRAMES_PLUS_CANDIDATE_ZARR_V3",
                "CURRENT_CORRECTED_VECTOR_AXES_SAMPLED_AT_10M_NOT_REGENERATED",
            ),
        )
        insert_dicts(connection, "stage6c5_candidate_registry", candidate_rows)
        insert_dicts(connection, "stage6c5_tile_manifest", tile_rows)
        insert_dicts(connection, "stage6c5_site_refinement", result_rows)
        insert_dicts(connection, "stage6c5_cache_object", object_rows)
        connection.execute("ANALYZE")
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("Final Stage 6C.5 SQLite integrity check failed")

    sqlite_backup(PARENT_GPKG, output_gpkg)
    with sqlite3.connect(output_gpkg) as gpkg:
        gpkg.execute("ATTACH DATABASE ? AS s6c5db", (str(output_db),))
        for table in (
            "stage6c5_candidate_registry",
            "stage6c5_tile_manifest",
            "stage6c5_site_refinement",
        ):
            gpkg.execute(f"DROP TABLE IF EXISTS main.{table}")
            gpkg.execute(f"CREATE TABLE main.{table} AS SELECT * FROM s6c5db.{table}")
            gpkg.execute(
                f"CREATE UNIQUE INDEX {table}_id_idx ON {table}({ 'tile_id' if table == 'stage6c5_tile_manifest' else 'settlement_id' })"
            )
            gpkg.execute(
                "DELETE FROM gpkg_contents WHERE table_name=?", (table,)
            )
            gpkg.execute(
                """INSERT INTO gpkg_contents
                   (table_name,data_type,identifier,description,last_change,srs_id)
                   VALUES (?,?,?,?,?,NULL)""",
                (
                    table,
                    "attributes",
                    table,
                    "Stage 6C.5 review-only bounded 10 m analytical attributes",
                    utc_now(),
                ),
            )
        # Commit the copied attribute tables before detaching the source database.
        # SQLite can otherwise keep the attached database locked until the context
        # manager commits at block exit.
        gpkg.commit()
        gpkg.execute("DETACH DATABASE s6c5db")
        if gpkg.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("Final Stage 6C.5 GeoPackage integrity check failed")
    return output_db, output_gpkg


def write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = list(rows[0]) if rows else []
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_documentation(
    output_dir: Path,
    checkpoints: Sequence[Mapping[str, Any]],
    runtime_s: float,
    source_hash_cache_report: Mapping[str, Any],
) -> None:
    candidate_rows = [dict(item["candidate_row"]) for item in checkpoints]
    result_rows = [dict(item["result_row"]) for item in checkpoints]
    tile_rows = [dict(item["tile_row"]) for item in checkpoints]
    write_csv(output_dir / "review_exports/STAGE6C5_CANDIDATE_REGISTRY.csv", candidate_rows)
    write_csv(output_dir / "review_exports/STAGE6C5_SITE_REFINEMENTS.csv", result_rows)
    write_csv(output_dir / "review_exports/STAGE6C5_TILE_MANIFEST.csv", tile_rows)
    atomic_json(output_dir / "STAGE6C5_CANDIDATE_MANIFEST.json", {
        "schema": "diadem.stage6c5-candidate-manifest.v1",
        "candidate_count": len(candidate_rows),
        "candidate_list_sha256": CANDIDATE_LIST_SHA256,
        "selection_rule": "stage6_active_settlement=1 AND stage6b_functional_tier IN (FT0,FT1)",
        "counts": {
            "FT0": sum(row["functional_tier"] == "FT0_HAUS_PRINCIPAL_SITE" for row in candidate_rows),
            "FT1": sum(row["functional_tier"] == "FT1_MAJOR_REGIONAL_HUB" for row in candidate_rows),
            "complete_2d": sum(row["disposition"] == "COMPLETE_2D_REFINEMENT" for row in candidate_rows),
            "specialist_3d_surface_or_interface_only": sum(row["disposition"].startswith("SURFACE_OR_INTERFACE") for row in candidate_rows),
        },
        "rows": candidate_rows,
    })
    summary = {
        "schema": "diadem.stage6c5-build-summary.v1",
        "status": "BUILD_COMPLETE_PENDING_INDEPENDENT_VALIDATION",
        "completed_utc": utc_now(),
        "method": METHOD,
        "canon_status": CANON_STATUS,
        "candidate_count": len(result_rows),
        "review_status_counts": dict(Counter(row["review_status"] for row in result_rows)),
        "selection_status_counts": dict(Counter(row["selection_status"] for row in result_rows)),
        "runtime_seconds": runtime_s,
        "source_hash_cache": dict(source_hash_cache_report),
        "tile_cache": {
            "bundle_count": len(tile_rows),
            "codec": "independent checksummed Zstandard frames",
            "compression_level": HOT_CACHE_ZSTD_LEVEL,
            "retention": "PINNED_THROUGH_STAGE6D_AND_FOOTPRINT_PASS",
        },
    }
    atomic_json(output_dir / "BUILD_SUMMARY.json", summary)
    (output_dir / "README_FIRST.md").write_text(
        f"""# Diadem Stage 6C.5 bounded 10 m refinement

**Status: WORKING PROPOSAL — REVIEW ONLY — NOT CANON**

This release refines the **107 active FT0/FT1 settlement candidates** inside
their complete 2.2 km context squares. It contains **79 complete 2D local
assessments** and **28 surface/interface-only assessments** whose specialist
3D settlement geometry remains deliberately deferred.

What is genuinely finer:

- exact surface and barony geometry sampled at 10 m cell centres;
- current corrected river/lake/coast vectors queried at 10 m cell centres;
- a deterministic, parent-conserving modelled 10 m terrain surface with broad
  and local gradients.

What is not claimed:

- the modelled 10 m terrain is not observed 10 m evidence; its effective
  physical evidence resolution remains 100 m;
- current river axes were sampled more finely but were **not regenerated from
  runoff** in this stage;
- official settlement coordinates were not changed;
- no final occupied footprint, population allocation, cavern volume,
  submerged interior, passage network or vertical carrying capacity was made.

The main SQLite file is cumulative. `candidate_evidence_10m.zarr` is the fast
random-access 1 km candidate evidence store. `tile_cache` holds resumable,
independently checksummed Zstandard frames for the complete 2.2 km local tiles.
The cache is pinned for Stage 6D and the later footprint pass.
""",
        encoding="utf-8",
    )
    (output_dir / "STAGE6C5_METHOD_AND_LIMITS.md").write_text(
        f"""# Stage 6C.5 method and limits

**Method:** `{METHOD}`  
**Status:** WORKING PROPOSAL — REVIEW ONLY — NOT CANON

## Frozen scope

- 107 active FT0/FT1 settlement identities; list hash `{CANDIDATE_LIST_SHA256}`.
- 2.2 km x 2.2 km parent-aligned context per site, nested to 10 m.
- Original 1 km x 1 km coordinate-support square retained as the candidate grid.
- 100 m parent-aligned numerical halo and two further 100 m bicubic support cells.
- Broader r5 developability remains inherited from Stage 6C at 100 m.

## Cache policy

Each site is committed independently to checksummed Zstandard level-3 frames.
The cache key binds site identity, official coordinate, profile, window,
terrain-authority identity, exact surface/barony identities, corrected
hydrology identities, mask identities, recipe and method version. Timestamps,
filenames, compression level and visual styling are deliberately excluded from
geographical identity. Raw parent windows and rendered imagery are not cached.

## Precision and authority

The 10 m terrain is a deterministic constrained model which aggregates back to
the 100 m authority. Exact boundaries and hydrology vectors retain their own
vector authority when sampled on the 10 m grid. Repeated sea/wetland/flood
classes remain effective 100 m evidence. All preferred cells are analytical
proposals separate from unchanged official coordinates.
""",
        encoding="utf-8",
    )


def run(
    output_dir: Path,
    *,
    limit: int | None = None,
    workers: int = 1,
    memory_budget_mb: int = 1024,
    reuse: bool = True,
    cancel_event: Any = None,
) -> dict[str, Any]:
    if workers < 1 or memory_budget_mb < 64:
        raise ValueError("workers must be positive and memory-budget-mb at least 64")
    started = time.perf_counter()
    stats = RuntimeStats()
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "checkpoints").mkdir(exist_ok=True)
    (output_dir / "tile_cache").mkdir(exist_ok=True)
    guards = capture_source_guards(guarded_source_paths((PARENT_DB, PARENT_GPKG)))
    parent_identity = {"parent_database": file_identity(PARENT_DB),
                       "parent_geopackage": file_identity(PARENT_GPKG)}

    print("CHECKPOINT_6C5_SOURCE_LOCK_START", flush=True)
    with stats.measure("source_verification"):
        source_manifest, authority_descriptor, source_hash_cache_report = s6c.verify_sources()
    with sqlite_readonly(PARENT_DB) as connection:
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("Stage 6C parent integrity check failed")
        candidates = load_candidates(connection, authority_descriptor)
    selected = candidates if limit is None else candidates[:limit]
    runtime_id = semantic_identity(
        "stage6c5-runtime-v1",
        inputs={"sources": source_manifest, "authority": authority_descriptor,
                **parent_identity},
        parameters={"recipe": terrain_recipe_identity()}, implementation=runtime_implementation(),
    )
    require_source_guards(guards)
    evidence_path = output_dir / "candidate_evidence_10m.zarr"
    evidence_group = open_evidence_store(evidence_path, candidates, authority_descriptor)

    with stats.measure("checkpoint_validation"):
        checkpoints = checkpoint_plan(
            selected,
            lambda candidate: load_checkpoint(
                output_dir / "checkpoints" / f"{candidate.site.settlement_id}.json",
                candidate, evidence_group, output_dir, runtime_identity=runtime_id,
            ),
            reuse=reuse,
        )
    pending = [(position, candidate) for position, candidate in enumerate(selected)
               if checkpoints[position] is None]
    generated, reused = 0, len(selected) - len(pending)
    stats.increment("sites_reused", reused)
    if pending:
        topology = s6c.ExactSurfaceIndex(
            Path(s6c.SOURCES["exact_surface_registry"]["path"]),
            Path(s6c.SOURCES["fragment_barony_assignment"]["path"]),
        )
        vectors = s6c.VectorStack("reduced")
        rasters = s6c.RasterStack(authority_descriptor)
        try:
            with tempfile.TemporaryDirectory(prefix=".s6c5-private-", dir=output_dir) as private:
                def jobs() -> Iterable[Any]:
                    # bounded_map advances this iterator in the coordinator only.
                    for position, candidate in pending:
                        private_dir = Path(private) / str(candidate.index)
                        (private_dir / "tile_cache").mkdir(parents=True)
                        with stats.measure("source_window_preload"):
                            prepared = prepare_candidate_rasters(candidate, rasters)
                        yield position, candidate, prepared, private_dir

                def compute(job: Any) -> Any:
                    position, candidate, prepared, private_dir = job
                    with stats.measure("site_compute_and_private_bundle"):
                        checkpoint, arrays = compute_site_result(
                            candidate, prepared, topology, vectors, private_dir
                        )
                    return position, candidate, checkpoint, arrays, private_dir

                results = bounded_map(
                    compute, jobs(), workers=workers,
                    memory_budget_bytes=memory_budget_mb * 1024 * 1024,
                    estimated_task_bytes=SITE_MEMORY_ESTIMATE_BYTES,
                    cancel_event=cancel_event, stats=stats, phase="refinement_sites",
                )
                try:
                    for position, candidate, checkpoint, arrays, private_dir in results:
                        # All public bundle/Zarr/checkpoint writes stay in this thread.
                        require_source_guards(guards)
                        evidence_group["site_complete"][candidate.index] = np.uint8(0)
                        install_private_bundle(output_dir, private_dir, checkpoint)
                        write_evidence_slice(evidence_group, candidate.index, arrays, mark_complete=False)
                        readback = {name: np.asarray(evidence_group[name][candidate.index, :, :])
                                    for name in zarr_arrays()}
                        if evidence_slice_digest(readback) != checkpoint["evidence_digest"]:
                            raise RuntimeError("Stage 6C.5 Zarr readback digest mismatch")
                        checkpoint["runtime_identity"] = runtime_id
                        atomic_json(output_dir / "checkpoints" / f"{candidate.site.settlement_id}.json", checkpoint)
                        evidence_group["site_complete"][candidate.index] = np.uint8(1)
                        checkpoints[position] = checkpoint
                        generated += 1
                        stats.increment("sites_generated")
                        print(f"CHECKPOINT_6C5_SITES generated={generated}/{len(pending)} reused={reused}", flush=True)
                        del arrays, readback
                finally:
                    results.close()
        finally:
            rasters.close()

    receipt_id = semantic_identity(
        "stage6c5-final-outputs-v1", inputs={"runtime": runtime_id, "checkpoints": checkpoints},
        parameters={"limit": limit}, implementation={},
    )
    require_source_guards(guards)
    require_terrain_identity(authority_descriptor)
    receipt_path = output_dir / "STAGE6C5_OUTPUT_RECEIPT.json"
    previous = load_receipt(receipt_path, receipt_id, output_dir) if reuse and not generated and limit is None else None
    if previous is not None:
        summary = {**previous, "generated": 0, "reused": reused,
                   "final_outputs_reused": True, "runtime_seconds": time.perf_counter() - started,
                   "runtime_statistics": stats.snapshot()}
        print(canonical_json(summary), flush=True)
        return summary

    if limit is None:
        print("CHECKPOINT_6C5_DATABASE_START", flush=True)
        output_db, output_gpkg = build_database(
            output_dir, checkpoints, authority_descriptor
        )
        runtime_s = time.perf_counter() - started
        write_documentation(
            output_dir, checkpoints, runtime_s, source_hash_cache_report
        )
        summary = {
            "status": "BUILD_COMPLETE",
            "candidate_count": len(checkpoints),
            "generated": generated,
            "reused": reused,
            "runtime_seconds": runtime_s,
            "output_database": str(output_db),
            "output_geopackage": str(output_gpkg),
            "output_directory": str(output_dir),
            "final_outputs_reused": False,
            "runtime_statistics": stats.snapshot(),
            "site_worker_limit": min(workers, memory_budget_mb // 64),
        }
        require_source_guards(guards)
        require_terrain_identity(authority_descriptor)
        save_receipt(receipt_path, receipt_id, output_dir, [
            output_db, output_gpkg, output_dir / "BUILD_SUMMARY.json",
            output_dir / "README_FIRST.md", output_dir / "STAGE6C5_METHOD_AND_LIMITS.md",
            output_dir / "STAGE6C5_CANDIDATE_MANIFEST.json",
            *(output_dir / "review_exports" / name for name in (
                "STAGE6C5_CANDIDATE_REGISTRY.csv", "STAGE6C5_SITE_REFINEMENTS.csv",
                "STAGE6C5_TILE_MANIFEST.csv")),
        ], summary)
    else:
        summary = {
            "status": "SMOKE_COMPLETE",
            "candidate_count": len(checkpoints),
            "generated": generated,
            "reused": reused,
            "runtime_seconds": time.perf_counter() - started,
            "output_directory": str(output_dir),
            "runtime_statistics": stats.snapshot(),
            "site_worker_limit": min(workers, memory_budget_mb // 64),
        }
    print(canonical_json(summary), flush=True)
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--smoke-limit", type=int, default=None)
    parser.add_argument("--workers", type=int, default=1,
                        help="Independent-site compute; direct invocation defaults to the serial reference")
    parser.add_argument("--memory-budget-mb", type=int, default=1024,
                        help="Admission budget for in-flight site work, excluding shared source indexes")
    parser.add_argument("--no-reuse", action="store_true", help="Recompute sites and final outputs")
    parser.add_argument("--algorithm-mode", choices=("auto", "reference"), default="auto")
    args = parser.parse_args(argv)
    algorithm_policy.configure(args.algorithm_mode)
    if args.smoke_limit is not None and not 1 <= args.smoke_limit <= EXPECTED_CANDIDATES:
        parser.error("--smoke-limit must be between 1 and 107")
    if args.workers < 1 or args.memory_budget_mb < 64:
        parser.error("--workers must be positive and --memory-budget-mb at least 64")
    run(args.output_dir.resolve(), limit=args.smoke_limit, workers=args.workers,
        memory_budget_mb=args.memory_budget_mb, reuse=not args.no_reuse)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
