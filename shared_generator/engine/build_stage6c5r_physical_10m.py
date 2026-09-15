#!/usr/bin/env python3
"""Build profile-aware 10 m terrain/hydrology context for Stage 6C.5R.

This is an additive, fail-closed successor to Stage 6C.5.  It first gates the
nineteen FT0 principal sites, then can resume the same immutable 107-slot store
for the eighty-eight FT1 sites.  The result is a physically coherent analytical
model constrained by the active 100 m terrain, current V4.2 water graph and
bounded C1 climate—not surveyed 10 m geography or canon.
"""

from __future__ import annotations

import argparse
from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import time
from typing import Any, Iterable, Iterator, Mapping, Sequence


ENGINE_DIR = Path(__file__).resolve().parent
for dependency_directory in (ENGINE_DIR / "zarr_deps", ENGINE_DIR / "generator_deps"):
    value = str(dependency_directory)
    if value not in sys.path:
        sys.path.insert(0, value)

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from rasterio.windows import Window
import shapely
from shapely.geometry import LineString, MultiLineString, Point, box, mapping
import zarr
from zarr.codecs import ZstdCodec

import build_stage6c_100m as s6c
import algorithm_policy
import build_stage6c5_10m as s6c5
from stage6c5_fast_terrain import (
    ADAPTER_VERSION,
    _blocks_to_raster as terrain_blocks_to_raster,
    _broad_blocks as terrain_broad_blocks,
    refine_terrain_safe,
)
from stage6c5r_climate import (
    C1MonthlyClimateReader,
    DEFAULT_ARCHIVE_PATH,
    DEFAULT_ARCHIVE_SHA256,
    DEFAULT_MEMBERS,
    METHOD_VERSION as CLIMATE_METHOD_VERSION,
    RUNOFF_SEMANTICS,
    effective_runoff_proxy,
)
import stage6c5r_physical as physical
from stage6c5r_hydrology import (
    ActiveMajorBedProfiles,
    METHOD_VERSION as HYDROLOGY_METHOD_VERSION,
    downstream_order,
    make_minor_bed_profile,
)
from ten_m_tile_engine.cache import write_tile_recovery_bundle
from ten_m_tile_engine.engine import EvidenceTile, GridSpec, ParentRasterWindow, TerrainRecipe, TileSpec
from generation_runtime import bounded_map, file_identity, load_receipt, save_receipt, semantic_identity, RuntimeStats
from verified_source_hash_cache import windows_file_change_token


DATE = "2026-08-30"
METHOD = "STAGE6C5R_PROFILE_AWARE_10M_PHYSICAL_CONTEXT_V2_7_STABLE_FLOOD_REFERENCE"
CANON_STATUS = "WORKING_PROPOSAL_REVIEW_ONLY_NOT_CANON"
FT0_LIST_SHA256 = "8721c4a66b32c14c0478f9d008afb3e421a1642b425b8fc7786b357c2e6f2612"
EXPECTED_FT0 = 19
EXPECTED_ALL = 107
WINDOW_PARENT_CELLS = 30
FINE_FACTOR = 10
FINE_CELLS = WINDOW_PARENT_CELLS * FINE_FACTOR
SUPPORT_PARENT_HALO = 10
ANALYSIS_PARENT_CELLS = WINDOW_PARENT_CELLS + 2 * SUPPORT_PARENT_HALO
ANALYSIS_FINE_CELLS = ANALYSIS_PARENT_CELLS * FINE_FACTOR
HALO_FINE_CELLS = 10
PARENT_SUPPORT_CELLS = 3
FINE_CELL_KM = 0.01
HOT_CACHE_ZSTD_LEVEL = 3
# Includes preloaded inputs, the full 500x500 hydrology working set, and retained
# cropped results while an earlier site is committed. Admission is not a process
# RAM cap: source indexes, the interpreter and codecs remain additional memory.
SITE_MEMORY_ESTIMATE_BYTES = 512 * 1024 * 1024

ROOT = s6c.ROOT
DEFAULT_OUTPUT_DIR = ROOT / "generated_outputs/S6C5R_PHYSICAL_10M_REPAIRED_V7_WORKING_2026-08-30"
SOURCE_STAGE6C5_DIR = s6c5.DEFAULT_OUTPUT_DIR
SOURCE_STAGE6C5_DB = SOURCE_STAGE6C5_DIR / s6c5.OUTPUT_DB_NAME
OUTPUT_DB_NAME = "Diadem_Stage6C5R_Physical_Context_WORKING_2026-08-30.sqlite"

GRID = GridSpec(origin_x_m=0.0, origin_y_m=0.0)
TERRAIN_RECIPE = TerrainRecipe(
    effective_resolution_m=100.0,
    elevation_scale_m=0.01,
    max_micro_relief_m=0.0,
    micro_relief_slope_fraction=0.0,
    minimum_micro_relief_m=0.0,
    max_conservation_correction_m=50.0,
    seed="diadem-stage6c5r-broad-terrain-v1",
)
PHYSICAL_RECIPE = physical.PhysicalRecipe()
RUNOFF_SCENARIOS: dict[str, dict[str, float]] = {
    "low": {"pet_multiplier": 1.15, "melt_factor": 20.0, "delivery_fraction": 0.45},
    "base": {"pet_multiplier": 1.00, "melt_factor": 30.0, "delivery_fraction": 0.65},
    "high": {"pet_multiplier": 0.85, "melt_factor": 45.0, "delivery_fraction": 0.85},
}


def climate_change_identity() -> Mapping[str, Any] | None:
    """Change guard only, never a claim that the 33 GB climate archive was hashed."""
    with DEFAULT_ARCHIVE_PATH.open("rb") as stream:
        return windows_file_change_token(stream, DEFAULT_ARCHIVE_PATH)


def require_unchanged_climate(expected: Mapping[str, Any] | None) -> None:
    if expected is not None and climate_change_identity() != expected:
        raise RuntimeError("Climate archive changed during the run; no site/final commit is safe")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def canonical_json(value: Any) -> str:
    def fallback(item: Any) -> Any:
        if isinstance(item, Mapping):
            return dict(item)
        if isinstance(item, Path):
            return str(item)
        if isinstance(item, np.generic):
            return item.item()
        if isinstance(item, (set, frozenset)):
            return sorted(item)
        raise TypeError(f"Cannot serialise {type(item).__name__}")
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=fallback
    )


def digest_json(value: Any) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


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


def window_origin(candidate: s6c5.Candidate) -> tuple[int, int]:
    centre_row = int(math.floor(candidate.site.y * 10.0))
    centre_col = int(math.floor(candidate.site.x * 10.0))
    row0 = min(max(centre_row - WINDOW_PARENT_CELLS // 2, 0), 18_600 - WINDOW_PARENT_CELLS)
    col0 = min(max(centre_col - WINDOW_PARENT_CELLS // 2, 0), 22_000 - WINDOW_PARENT_CELLS)
    return row0, col0


def scope_candidates(candidates: Sequence[s6c5.Candidate], scope: str) -> list[s6c5.Candidate]:
    ft0 = sorted(
        (candidate for candidate in candidates if candidate.site.functional_tier == "FT0_HAUS_PRINCIPAL_SITE"),
        key=lambda candidate: candidate.site.settlement_id,
    )
    ids = [candidate.site.settlement_id for candidate in ft0]
    if len(ids) != EXPECTED_FT0 or digest_json(ids) != FT0_LIST_SHA256:
        raise RuntimeError("Frozen FT0 pilot scope changed")
    return ft0 if scope == "FT0" else list(candidates)


def source_identity(authority: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "terrain_authority": {
            "authority_id": authority["authority_id"],
            "generation": authority["generation"],
            "root_hash": authority["root_hash"],
            "physical_source_resolution_m": 100,
        },
        "hydrology": {
            role: {
                "sha256": s6c.SOURCES[role]["sha256"],
                "status": s6c.SOURCES[role].get("status"),
            }
            for role in (
                "active_major", "active_major_bed_profiles", "d3_feeder_raw", "d3_feeder_enriched",
                "stillklinge_support", "special_controls", "lake_permanent_l1",
                "lake_permanent_legacy", "lake_seasonal", "coastline",
            )
        },
        "protected_masks": {
            role: s6c.SOURCES[role]["sha256"]
            for role in (
                "obsidian_sea_mask", "moorwandler_core_wetland",
                "serenakrone_water_mask", "flood_candidates_100m",
                "stillklinge_flood_override",
            )
        },
        "exact_surface": {
            "registry_sha256": s6c.SOURCES["exact_surface_registry"]["sha256"],
            "assignment_sha256": s6c.SOURCES["fragment_barony_assignment"]["sha256"],
        },
        "climate": {
            "archive_sha256": DEFAULT_ARCHIVE_SHA256,
            "member_sha256": {member.key: member.sha256 for member in DEFAULT_MEMBERS},
            "status": "PILOT_BOUND_REVIEW_SOURCE_NOT_PROMOTED_TO_ACTIVE_CATALOGUE",
            "runoff_semantics": RUNOFF_SEMANTICS,
        },
    }


def recipe_identity() -> dict[str, Any]:
    return {
        "method": METHOD,
        "terrain": {
            **asdict(TERRAIN_RECIPE),
            "fast_adapter": ADAPTER_VERSION,
            "parent_conservation": "CONTINUOUS_INTERPOLATED_RESIDUAL_PLUS_TINY_INTERIOR_CLOSURE",
            "interior_closure_bubble_used": True,
        },
        "physical": PHYSICAL_RECIPE.identity(),
        "implementations": {
            "climate_adapter": CLIMATE_METHOD_VERSION,
            "registered_axis_and_bed_control": HYDROLOGY_METHOD_VERSION,
            "profile_aware_hydrology": HYDROLOGY_METHOD_VERSION,
            "registered_axis_rasterisation": "GLOBAL_10M_GRID_VERTEX_SEGMENT_BRESENHAM_V1",
        },
        "mfd": {
            "direction_deltas_row_col": [[int(dr), int(dc)] for dr, dc, _ in physical.D8],
            "slope_exponent": PHYSICAL_RECIPE.mfd_slope_exponent,
            "dominant_direction_array": "d8_receiver_code",
            "dominant_direction_semantics": "ARGMAX_DIAGNOSTIC_ONLY_FULL_GRAPH_IS_MFD_RECEIVER_WEIGHTS",
        },
        "runoff_scenarios": RUNOFF_SCENARIOS,
        "runoff_scenario_envelope": (
            "POINTWISE_MINIMUM_OF_THREE_PARAMETER_RUNS / BASE_PARAMETER_RUN / "
            "POINTWISE_MAXIMUM_OF_THREE_PARAMETER_RUNS"
        ),
        "window_parent_cells": WINDOW_PARENT_CELLS,
        "analysis_window_parent_cells": ANALYSIS_PARENT_CELLS,
        "support_halo_parent_cells": SUPPORT_PARENT_HALO,
        "fine_cell_m": 10,
        "canon_status": CANON_STATUS,
    }


@dataclass(frozen=True)
class SiteWork:
    candidate: s6c5.Candidate
    row0: int
    col0: int
    analysis_row0: int
    analysis_col0: int
    core_row_offset: int
    core_col_offset: int
    semantic_key: str

    @property
    def core_slice(self) -> tuple[slice, slice]:
        row0 = self.core_row_offset * FINE_FACTOR
        col0 = self.core_col_offset * FINE_FACTOR
        return (slice(row0, row0 + FINE_CELLS), slice(col0, col0 + FINE_CELLS))


def build_work(candidates: Sequence[s6c5.Candidate], sources: Mapping[str, Any]) -> list[SiteWork]:
    result: list[SiteWork] = []
    for candidate in candidates:
        row0, col0 = window_origin(candidate)
        analysis_row0 = min(max(row0 - SUPPORT_PARENT_HALO, 0), 18_600 - ANALYSIS_PARENT_CELLS)
        analysis_col0 = min(max(col0 - SUPPORT_PARENT_HALO, 0), 22_000 - ANALYSIS_PARENT_CELLS)
        core_row_offset = row0 - analysis_row0
        core_col_offset = col0 - analysis_col0
        semantic = {
            "record_type": "diadem.stage6c5r.site-physical-context.v3",
            "settlement_id": candidate.site.settlement_id,
            "official_coordinate_km": [candidate.site.x, candidate.site.y],
            "official_coordinate_modified": False,
            "parent_stage6c5_semantic_key": candidate.semantic_key,
            "window_parent": [row0, col0, WINDOW_PARENT_CELLS, WINDOW_PARENT_CELLS],
            "analysis_window_parent": [
                analysis_row0, analysis_col0, ANALYSIS_PARENT_CELLS, ANALYSIS_PARENT_CELLS
            ],
            "sources": sources,
            "recipe": recipe_identity(),
        }
        result.append(SiteWork(
            candidate, row0, col0, analysis_row0, analysis_col0,
            core_row_offset, core_col_offset, digest_json(semantic)
        ))
    return result


def array_specs() -> dict[str, tuple[tuple[int, ...], str, Any]]:
    spatial = (FINE_CELLS, FINE_CELLS)
    return {
        "base_broad_elevation_m": (spatial, "f4", np.nan),
        "conditioned_elevation_m": (spatial, "f4", np.nan),
        "terrain_conditioning_delta_m": (spatial, "f4", np.nan),
        "routing_elevation_m": (spatial, "f8", np.nan),
        "routing_fill_delta_m": (spatial, "f8", np.nan),
        "protected_channel_bed_elevation_m": (spatial, "f8", np.nan),
        "local_slope_m_per_m": (spatial, "f4", np.nan),
        "monthly_effective_runoff_low_mm": ((12, *spatial), "f4", np.nan),
        "monthly_effective_runoff_base_mm": ((12, *spatial), "f4", np.nan),
        "monthly_effective_runoff_high_mm": ((12, *spatial), "f4", np.nan),
        "monthly_accumulated_runoff_base_mm_km2": ((12, *spatial), "f4", np.nan),
        "accumulated_area_km2": (spatial, "f4", np.nan),
        "annual_accumulated_runoff_low_mm_km2": (spatial, "f4", np.nan),
        "annual_accumulated_runoff_base_mm_km2": (spatial, "f4", np.nan),
        "annual_accumulated_runoff_high_mm_km2": (spatial, "f4", np.nan),
        "inherited_current_channel_class": (spatial, "u1", 0),
        "protected_channel_class": (spatial, "u1", 0),
        "drainage_potential_or_protected_class": (spatial, "u1", 0),
        "channel_width_low_m": (spatial, "f4", 0.0),
        "channel_width_base_m": (spatial, "f4", 0.0),
        "channel_width_high_m": (spatial, "f4", 0.0),
        "d8_receiver_code": (spatial, "i1", -1),
        "mfd_receiver_weights": ((8, *spatial), "f4", 0.0),
        "nearest_channel_height_proxy_m": (spatial, "f4", np.nan),
        "flood_susceptibility": (spatial, "f4", np.nan),
        "wetness_potential": (spatial, "f4", np.nan),
        "exact_barony_id": (spatial, "i4", -1),
        "exact_surface": (spatial, "u1", 0),
        "land_mask": (spatial, "u1", 0),
        "sea_mask_parent_projected": (spatial, "u1", 0),
        "wetland_mask_parent_projected": (spatial, "u1", 0),
        "serenakrone_water_parent_projected": (spatial, "u1", 0),
        "protected_flood_evidence_parent_projected": (spatial, "f4", 0.0),
        "registered_sink_mask": (spatial, "u1", 0),
    }


def open_store(path: Path, candidates: Sequence[s6c5.Candidate], authority: Mapping[str, Any]) -> zarr.Group:
    group = zarr.open_group(str(path), mode="a", zarr_format=3)
    compressor = [ZstdCodec(level=HOT_CACHE_ZSTD_LEVEL, checksum=True)]
    for name, (tail, dtype, fill) in array_specs().items():
        expected_shape = (len(candidates), *tail)
        if name not in group:
            group.create_array(
                name,
                shape=expected_shape,
                chunks=(1, *tail),
                dtype=dtype,
                fill_value=fill,
                compressors=compressor,
            )
        elif tuple(group[name].shape) != expected_shape:
            raise RuntimeError(f"Existing Stage 6C.5R Zarr array {name} has incompatible shape")
    if "site_complete" not in group:
        group.create_array(
            "site_complete", shape=(len(candidates),), chunks=(len(candidates),),
            dtype="u1", fill_value=0, compressors=compressor,
        )
    elif tuple(group["site_complete"].shape) != (len(candidates),):
        raise RuntimeError("Existing Stage 6C.5R completion array is incompatible")
    group.attrs.update({
        "schema": "diadem.stage6c5r-physical-context-zarr.v4",
        "method": METHOD,
        "canon_status": CANON_STATUS,
        "site_slot_count": len(candidates),
        "ft0_scope_sha256": FT0_LIST_SHA256,
        "cell_size_m": 10,
        "physical_source_resolution_m": 100,
        "terrain_authority_root_hash": authority["root_hash"],
        "compression": "ZSTD_LEVEL_3_CHECKSUMMED",
        "official_coordinates_modified": False,
        "generated_channels_promoted": False,
        "registered_axes_and_separate_bed_controls_stored": True,
        "mfd_direction_deltas_row_col": [[int(dr), int(dc)] for dr, dc, _ in physical.D8],
        "mfd_slope_exponent": PHYSICAL_RECIPE.mfd_slope_exponent,
        "d8_receiver_code_semantics": "DOMINANT_MFD_DIRECTION_ARGMAX_ONLY",
    })
    if tuple(group["base_broad_elevation_m"].shape) != (len(candidates), FINE_CELLS, FINE_CELLS):
        raise RuntimeError("Existing Stage 6C.5R Zarr shape is incompatible")
    group.attrs["method"] = METHOD
    return group


def arrays_digest(arrays: Mapping[str, np.ndarray]) -> str:
    digest = sha256()
    for name in sorted(array_specs()):
        value = np.ascontiguousarray(arrays[name])
        digest.update(canonical_json([name, value.dtype.str, list(value.shape)]).encode("utf-8"))
        digest.update(value.tobytes(order="C"))
    return digest.hexdigest()


def write_store_slice(group: zarr.Group, index: int, arrays: Mapping[str, np.ndarray]) -> str:
    for name in array_specs():
        group[name][index] = np.asarray(arrays[name])
    readback = {name: np.asarray(group[name][index]) for name in array_specs()}
    return arrays_digest(readback)


def _line_parts(geometry: Any) -> list[LineString]:
    if geometry.is_empty:
        return []
    if geometry.geom_type == "LineString":
        return [geometry]
    if geometry.geom_type == "MultiLineString":
        return list(geometry.geoms)
    if hasattr(geometry, "geoms"):
        result: list[LineString] = []
        for item in geometry.geoms:
            result.extend(_line_parts(item))
        return result
    return []


def _bresenham(start: tuple[int, int], end: tuple[int, int]) -> list[tuple[int, int]]:
    row0, col0 = start
    row1, col1 = end
    dr, dc = abs(row1 - row0), abs(col1 - col0)
    sr = 1 if row0 < row1 else -1
    sc = 1 if col0 < col1 else -1
    error = dc - dr
    result: list[tuple[int, int]] = []
    while True:
        result.append((row0, col0))
        if row0 == row1 and col0 == col1:
            return result
        doubled = 2 * error
        if doubled > -dr:
            error -= dr
            col0 += sc
        if doubled < dc:
            error += dc
            row0 += sr


def sample_line_cells(
    geometry: Any,
    window_geometry: Any,
    fine_row0: int,
    fine_col0: int,
    fine_rows: int = ANALYSIS_FINE_CELLS,
    fine_cols: int = ANALYSIS_FINE_CELLS,
) -> list[tuple[tuple[int, int], ...]]:
    """Rasterise registered geometry on the global 10 m grid, then crop it.

    Rasterising a line only after clipping it to a moving support window changes
    Bresenham phase and can move interior channel cells when the halo shifts.
    Original vector vertices provide fixed global segment endpoints, so the same
    geographical segment now always occupies the same 10 m cells.
    """

    del window_geometry  # The fixed global cell bounds below define the crop.
    result: list[tuple[tuple[int, int], ...]] = []
    row1 = fine_row0 + fine_rows
    col1 = fine_col0 + fine_cols
    for part in _line_parts(geometry):
        if part.length <= 0.0:
            continue
        coordinates = list(part.coords)
        current: list[tuple[int, int]] = []
        for first, second in zip(coordinates[:-1], coordinates[1:]):
            start = (
                int(math.floor(float(first[1]) / FINE_CELL_KM)),
                int(math.floor(float(first[0]) / FINE_CELL_KM)),
            )
            end = (
                int(math.floor(float(second[1]) / FINE_CELL_KM)),
                int(math.floor(float(second[0]) / FINE_CELL_KM)),
            )
            for global_row, global_col in _bresenham(start, end):
                if fine_row0 <= global_row < row1 and fine_col0 <= global_col < col1:
                    local = (global_row - fine_row0, global_col - fine_col0)
                    if not current or current[-1] != local:
                        current.append(local)
                elif current:
                    if len(current) >= 2:
                        result.append(tuple(current))
                    current = []
        if len(current) >= 2:
            result.append(tuple(current))
    return result


def _route_class(properties: Mapping[str, Any], major: bool) -> str:
    if major:
        return "titan" if properties.get("route_id") == "BC-001-R1" else "major"
    return "tier2" if int(properties.get("tier_code") or 1) >= 2 else "tier1"


def _persistence(properties: Mapping[str, Any]) -> str:
    if bool(properties.get("source_perennial_label_must_not_be_inherited_as_authoritative")):
        return "UNRESOLVED_AFTER_STILLKLINGE_SUPERSESSION_DO_NOT_PROMOTE"
    return str(
        properties.get("persistence")
        or properties.get("persistence_preclassification")
        or properties.get("persistence_authority")
        or "UNSPECIFIED_RETAIN_SOURCE_CLASS"
    )


def _major_area_priors(vectors: s6c.VectorStack) -> dict[str, float]:
    result: dict[str, float] = {}
    for properties in vectors.minor_props:
        receiver = str(properties.get("receiver_id") or "")
        if not receiver.startswith("BC-"):
            continue
        area = float(
            properties.get("outlet_contributing_area_km2")
            or properties.get("contributing_area_km2")
            or 0.0
        )
        result[receiver] = max(result.get(receiver, 0.0), area)
    return result


def channel_constraints(
    vectors: s6c.VectorStack,
    work: SiteWork,
    base_elevation: np.ndarray,
    major_profiles: ActiveMajorBedProfiles,
) -> tuple[list[physical.ChannelConstraint], list[dict[str, Any]]]:
    fine_row0, fine_col0 = work.analysis_row0 * 10, work.analysis_col0 * 10
    x0, y0 = work.analysis_col0 * 0.1, work.analysis_row0 * 0.1
    window_km = ANALYSIS_PARENT_CELLS * 0.1
    window_geometry = box(x0, y0, x0 + window_km, y0 + window_km)
    priors = _major_area_priors(vectors)
    constraints: list[physical.ChannelConstraint] = []
    records: list[dict[str, Any]] = []
    def near_analysis_boundary(cell: tuple[int, int]) -> bool:
        return (
            cell[0] <= 1
            or cell[1] <= 1
            or cell[0] >= ANALYSIS_FINE_CELLS - 2
            or cell[1] >= ANALYSIS_FINE_CELLS - 2
        )
    groups = (
        (vectors.major_tree, vectors.major_geoms, vectors.major_props, True),
        (vectors.minor_tree, vectors.minor_geoms, vectors.minor_props, False),
    )
    for tree, geometries, properties_list, major in groups:
        indices = np.asarray(tree.query(window_geometry, predicate="intersects"), dtype=np.int64)
        for index in sorted(indices.tolist()):
            geometry = geometries[index]
            properties = properties_list[index]
            feature_id = str(properties.get("route_id") or properties.get("minor_id"))
            route_class = _route_class(properties, major)
            persistence = _persistence(properties)
            area = float(
                properties.get("contributing_area_km2")
                or properties.get("outlet_contributing_area_km2")
                or priors.get(feature_id, 0.0)
            )
            if major and feature_id in priors:
                station = float(geometry.project(window_geometry.centroid, normalized=True))
                area = max(1.0, priors[feature_id] * max(0.10, min(station, 1.0)))
            for part_index, path in enumerate(
                sample_line_cells(geometry, window_geometry, fine_row0, fine_col0)
            ):
                cell_xy = [
                    (
                        (fine_col0 + cell[1] + 0.5) * FINE_CELL_KM,
                        (fine_row0 + cell[0] + 0.5) * FINE_CELL_KM,
                    )
                    for cell in path
                ]
                if major:
                    bed = major_profiles.sample_z(feature_id, cell_xy)
                    path, bed_values = downstream_order(path, bed)
                    vertical_control = (
                        "NEW_REVIEW_CANDIDATE_FROM_ACTIVE_3D_MAJOR_PROFILE_"
                        "WITH_TERRAIN_AUTHORITY_CEILING"
                    )
                    bed_lineage: Mapping[str, Any] = dict(major_profiles.properties(feature_id))
                else:
                    # Preserve D3 source-to-receiver geometry.  Correct a
                    # reversed clipped part by its chainage on the complete raw
                    # geometry, never by broad land-surface endpoint ranking.
                    first = geometry.project(Point(cell_xy[0]))
                    last = geometry.project(Point(cell_xy[-1]))
                    if first > last:
                        path = tuple(reversed(path))
                    path, bed_values, bed_lineage = make_minor_bed_profile(
                        path,
                        base_elevation,
                        nominal_depth_m=float(physical.CLASS_PARAMETERS[route_class]["depth_m"]),
                        median_slope_m_per_km=(
                            None if properties.get("median_slope_m_per_km") is None
                            else float(properties["median_slope_m_per_km"])
                        ),
                        minimum_drop_m_per_cell=PHYSICAL_RECIPE.minimum_channel_drop_m_per_cell,
                    )
                    vertical_control = str(bed_lineage["vertical_control"])
                boundary_inflow = near_analysis_boundary(path[0])
                boundary_outflow = near_analysis_boundary(path[-1])
                part_id = feature_id if part_index == 0 else f"{feature_id}#part{part_index + 1}"
                constraint = physical.ChannelConstraint(
                    feature_id=part_id,
                    route_class=route_class,
                    persistence=persistence,
                    path_cells=path,
                    contributing_area_prior_km2=area,
                    boundary_inflow=boundary_inflow,
                    source_kind=(
                        "V4_2_ACTIVE_MAJOR_AXIS_WITH_3D_BED_PROFILE"
                        if major else "V4_2_D3_CONNECTED_ROUTING_GRAPH"
                    ),
                    bed_elevations_m=tuple(float(value) for value in bed_values),
                    vertical_control=vertical_control,
                    receiver_id=(
                        None if properties.get("receiver_id") is None
                        else str(properties.get("receiver_id"))
                    ),
                    terrain_ceiling_reconciliation_allowed=True,
                )
                unresolved_stillklinge = bool(
                    properties.get("source_perennial_label_must_not_be_inherited_as_authoritative")
                )
                if not unresolved_stillklinge:
                    constraints.append(constraint)
                records.append({
                    "feature_id": feature_id,
                    "part_id": part_id,
                    "source_kind": "major" if major else "minor",
                    "route_class": route_class,
                    "persistence": persistence,
                    "inherited_tier": properties.get("tier"),
                    "inherited_tier_code": properties.get("tier_code"),
                    "inherited_strahler_order": properties.get("strahler_order"),
                    "receiver_id": properties.get("receiver_id") or properties.get("receiver"),
                    "vertical_control": vertical_control,
                    "bed_profile_lineage": dict(bed_lineage),
                    "boundary_inflow": boundary_inflow,
                    "boundary_outflow": boundary_outflow,
                    "boundary_area_prior_km2": area if boundary_inflow else 0.0,
                    "path_cell_count": len(path),
                    "path_cells": [list(cell) for cell in path],
                    "bed_elevations_m": [float(value) for value in bed_values],
                    "bed_elevation_start_m": float(bed_values[0]),
                    "bed_elevation_end_m": float(bed_values[-1]),
                    "bed_elevation_min_m": float(min(bed_values)),
                    "bed_elevation_max_m": float(max(bed_values)),
                    "requires_physical_gate": not unresolved_stillklinge,
                    "source_label_must_not_be_promoted": bool(
                        properties.get("source_perennial_label_must_not_be_inherited_as_authoritative")
                    ),
                })
    # At 10 m, a tributary and its receiver can occupy the same raster cell for
    # one or two steps even though their exact vectors only meet once.  End the
    # tributary at its first registered-receiver contact so the receiver owns
    # the downstream cell edge; this preserves the source reach graph and avoids
    # manufacturing a cell-level braid or cycle.
    by_base_id: dict[str, list[physical.ChannelConstraint]] = {}
    for constraint in constraints:
        by_base_id.setdefault(constraint.feature_id.split("#", 1)[0], []).append(constraint)
    record_by_part = {str(record["part_id"]): record for record in records}
    reconciled: list[physical.ChannelConstraint] = []
    for constraint in constraints:
        receiver_parts = by_base_id.get(str(constraint.receiver_id or ""), [])
        receiver_cells = {
            cell for receiver_part in receiver_parts for cell in receiver_part.path_cells
        }
        contacts = [
            index for index, cell in enumerate(constraint.path_cells) if cell in receiver_cells
        ]
        # Some raw reach geometries are stored receiver-to-source.  Where the
        # registered receiver is present in this support lens, it is definitive
        # orientation evidence.  Put that contact at the downstream end and
        # reconstruct the modelled minor bed in the corrected order.
        if (
            contacts
            and constraint.route_class in {"tier1", "tier2"}
            and min(contacts) < (len(constraint.path_cells) - 1 - max(contacts))
        ):
            reversed_path = tuple(reversed(constraint.path_cells))
            record = record_by_part[constraint.feature_id]
            reversed_path, reversed_bed, bed_lineage = make_minor_bed_profile(
                reversed_path,
                base_elevation,
                nominal_depth_m=float(
                    physical.CLASS_PARAMETERS[constraint.route_class]["depth_m"]
                ),
                median_slope_m_per_km=(
                    record["bed_profile_lineage"].get(
                        "d3_median_slope_diagnostic_m_per_km"
                    )
                ),
                minimum_drop_m_per_cell=PHYSICAL_RECIPE.minimum_channel_drop_m_per_cell,
            )
            constraint = physical.ChannelConstraint(
                **{
                    **asdict(constraint),
                    "path_cells": reversed_path,
                    "bed_elevations_m": reversed_bed,
                    "boundary_inflow": near_analysis_boundary(reversed_path[0]),
                }
            )
            record["path_cells"] = [list(cell) for cell in reversed_path]
            record["bed_elevations_m"] = list(reversed_bed)
            record["bed_profile_lineage"] = dict(bed_lineage)
            record["bed_elevation_start_m"] = float(reversed_bed[0])
            record["bed_elevation_end_m"] = float(reversed_bed[-1])
            record["bed_elevation_min_m"] = float(min(reversed_bed))
            record["bed_elevation_max_m"] = float(max(reversed_bed))
            record["boundary_inflow"] = constraint.boundary_inflow
            record["orientation_reconciled_from_receiver_contact"] = True
            contacts = [
                index for index, cell in enumerate(constraint.path_cells)
                if cell in receiver_cells
            ]
        if contacts and constraint.receiver_id:
            contact_index = min(contacts)
            if contact_index >= 1 and contact_index < len(constraint.path_cells) - 1:
                constraint = physical.ChannelConstraint(
                    **{
                        **asdict(constraint),
                        "path_cells": constraint.path_cells[: contact_index + 1],
                        "bed_elevations_m": constraint.bed_elevations_m[: contact_index + 1],
                    }
                )
                record = record_by_part[constraint.feature_id]
                record["path_cells"] = [list(cell) for cell in constraint.path_cells]
                record["bed_elevations_m"] = list(constraint.bed_elevations_m)
                record["bed_elevation_end_m"] = float(constraint.bed_elevations_m[-1])
                record["bed_elevation_min_m"] = float(min(constraint.bed_elevations_m))
                record["receiver_contact_cell"] = list(constraint.path_cells[-1])
                record["receiver_contact_reconciled_at_10m"] = True
                record["boundary_outflow"] = near_analysis_boundary(constraint.path_cells[-1])
        reconciled.append(constraint)
    constraints = reconciled
    constraints.sort(key=lambda item: item.feature_id)
    records.sort(key=lambda item: item["part_id"])
    return constraints, records


def rasterize_polygons(
    geometries: Sequence[Any],
    tree: Any,
    work: SiteWork,
) -> np.ndarray:
    x0, y0 = work.analysis_col0 * 0.1, work.analysis_row0 * 0.1
    window_km = ANALYSIS_PARENT_CELLS * 0.1
    window_geometry = box(x0, y0, x0 + window_km, y0 + window_km)
    indices = np.asarray(tree.query(window_geometry, predicate="intersects"), dtype=np.int64)
    if not len(indices):
        return np.zeros((ANALYSIS_FINE_CELLS, ANALYSIS_FINE_CELLS), dtype=bool)
    xs, ys = np.meshgrid(
        x0 + (np.arange(ANALYSIS_FINE_CELLS, dtype=np.float64) + 0.5) * FINE_CELL_KM,
        y0 + (np.arange(ANALYSIS_FINE_CELLS, dtype=np.float64) + 0.5) * FINE_CELL_KM,
        indexing="xy",
    )
    result = np.zeros(xs.shape, dtype=bool)
    for index in indices.tolist():
        geometry = geometries[int(index)]
        if geometry.geom_type in {"Polygon", "MultiPolygon"}:
            result |= np.asarray(shapely.intersects_xy(geometry, xs, ys), dtype=bool)
    return result


def special_sink_mask(vectors: s6c.VectorStack, work: SiteWork) -> np.ndarray:
    x0, y0 = work.analysis_col0 * 0.1, work.analysis_row0 * 0.1
    window_km = ANALYSIS_PARENT_CELLS * 0.1
    result = np.zeros((ANALYSIS_FINE_CELLS, ANALYSIS_FINE_CELLS), dtype=bool)
    for geometry in [*vectors.special_geoms, *vectors.managed_special_geoms]:
        if geometry.geom_type in {"Polygon", "MultiPolygon"}:
            tree = shapely.STRtree([geometry])
            result |= rasterize_polygons([geometry], tree, work)
        elif geometry.geom_type == "Point" and x0 <= geometry.x < x0 + window_km and y0 <= geometry.y < y0 + window_km:
            row = int(math.floor((geometry.y - y0) / FINE_CELL_KM))
            col = int(math.floor((geometry.x - x0) / FINE_CELL_KM))
            result[
                max(row - 1, 0): min(row + 2, ANALYSIS_FINE_CELLS),
                max(col - 1, 0): min(col + 2, ANALYSIS_FINE_CELLS),
            ] = True
    return result


def terrain_tile(
    work: SiteWork,
    rasters: s6c.RasterStack,
    verify_reference: bool,
) -> tuple[np.ndarray, np.ndarray]:
    tile_spec = TileSpec(
        f"S6C5R-{work.candidate.site.settlement_id}",
        work.analysis_row0, work.analysis_col0, ANALYSIS_PARENT_CELLS, ANALYSIS_PARENT_CELLS,
        halo_cells=HALO_FINE_CELLS,
    )
    support_row0 = max(0, work.analysis_row0 - PARENT_SUPPORT_CELLS)
    support_col0 = max(0, work.analysis_col0 - PARENT_SUPPORT_CELLS)
    support_row1 = min(
        18_600, work.analysis_row0 + ANALYSIS_PARENT_CELLS + PARENT_SUPPORT_CELLS
    )
    support_col1 = min(
        22_000, work.analysis_col0 + ANALYSIS_PARENT_CELLS + PARENT_SUPPORT_CELLS
    )
    parent_data = rasters.terrain.read_block(
        support_row0, support_col0, support_row1 - support_row0, support_col1 - support_col0
    )
    parent_window = ParentRasterWindow(parent_data, support_row0, support_col0, GRID)
    tile = refine_terrain_safe(
        parent_window,
        tile_spec,
        TERRAIN_RECIPE,
        source_hashes={
            "terrain_authority_root": str(rasters.terrain.descriptor["root_hash"]),
            "stage6c5r_semantic_key": work.semantic_key,
        },
        verify_reference=verify_reference,
    )
    # Reuse the verified Catmull-Rom interpolation, but replace the old
    # independent per-parent conservation bubble.  That bubble recovered means
    # exactly yet stamped a repeated 100 m motif into slope and runoff.  The
    # continuous residual field below retains exact parent means without those
    # hard block-local shapes.
    raw_blocks, targets, _, _ = terrain_broad_blocks(parent_window, tile_spec)
    broad_raw = terrain_blocks_to_raster(raw_blocks)
    broad_smooth, _, _ = physical._smooth_parent_mean_compensation(
        broad_raw, targets
    )
    broad = broad_smooth[tile_spec.core_slice].astype(np.float32)
    parent = rasters.terrain.read_block(
        work.analysis_row0, work.analysis_col0, ANALYSIS_PARENT_CELLS, ANALYSIS_PARENT_CELLS
    )
    return broad, parent.astype(np.float32)


@dataclass(frozen=True)
class PreparedPhysicalClimate:
    """One private array-only climate window; never a GDAL/archive handle."""

    climate: Any
    window: Window

    def read_window(self, window: Window) -> Any:
        if window != self.window:
            raise ValueError("Unexpected prepared physical climate window")
        return self.climate


def prepare_physical_inputs(
    work: SiteWork, rasters: s6c.RasterStack, climate_reader: C1MonthlyClimateReader,
) -> tuple[s6c5.PreparedCandidateRasters, PreparedPhysicalClimate]:
    """Read source handles on the coordinator before bounded worker admission."""
    row0 = max(0, work.analysis_row0 - PARENT_SUPPORT_CELLS)
    col0 = max(0, work.analysis_col0 - PARENT_SUPPORT_CELLS)
    row1 = min(18_600, work.analysis_row0 + ANALYSIS_PARENT_CELLS + PARENT_SUPPORT_CELLS)
    col1 = min(22_000, work.analysis_col0 + ANALYSIS_PARENT_CELLS + PARENT_SUPPORT_CELLS)
    values = rasters.terrain.read_block(row0, col0, row1 - row0, col1 - col0)
    core_window = (work.analysis_row0, work.analysis_col0,
                   ANALYSIS_PARENT_CELLS, ANALYSIS_PARENT_CELLS)
    prepared = s6c5.PreparedCandidateRasters(
        s6c5.PreparedTerrain(values, row0, col0, dict(rasters.terrain.descriptor)),
        core_window, rasters.read_block(*core_window),
    )
    window = Window(work.analysis_col0, work.analysis_row0,
                    ANALYSIS_PARENT_CELLS, ANALYSIS_PARENT_CELLS)
    return prepared, PreparedPhysicalClimate(climate_reader.read_window(window), window)


class PhysicalSiteComputationError(RuntimeError):
    """Worker failure with its private diagnostic available to the coordinator."""

    def __init__(self, work: SiteWork, private_dir: Path, error: Exception):
        super().__init__(f"Physical site {work.candidate.site.settlement_id}: {error}")
        self.work = work
        self.private_dir = private_dir


def physical_site_results(
    pending: Sequence[tuple[int, SiteWork]], rasters: s6c.RasterStack,
    topology: s6c.ExactSurfaceIndex, vectors: s6c.VectorStack,
    major_profiles: ActiveMajorBedProfiles, climate_reader: C1MonthlyClimateReader,
    output_dir: Path, *, workers: int, memory_budget_mb: int,
    stats: RuntimeStats, cancel_event: Any = None,
) -> Iterator[tuple[int, SiteWork, dict[str, Any], dict[str, np.ndarray], Path]]:
    """Ordered private results, with active workers joined before scratch removal.

    Topology, vector geometries/properties and bed profiles are fully loaded,
    read-only indexes. All mutable raster and climate inputs belong to one job.
    Each job keeps its existing terrain -> constraints -> flow sequence intact.
    No worker receives a public output store or opens shared source handles.
    Callers must close this iterator when abandoning it before exhaustion.
    """
    # Recovery bundles have long atomic-temporary member names. Worker staging
    # must not reduce the output-path length supported by the serial builder.
    # Keep extended Windows names private: checkpoint paths remain relative.
    private_parent = str(output_dir.resolve())
    if os.name == "nt" and not private_parent.startswith("\\\\?\\"):
        private_parent = ("\\\\?\\UNC\\" + private_parent[2:] if private_parent.startswith("\\\\")
                          else "\\\\?\\" + private_parent)
    with tempfile.TemporaryDirectory(prefix=".physical-", dir=private_parent) as private:
        def jobs() -> Iterable[Any]:
            for ordinal, (position, work) in enumerate(pending):
                private_dir = Path(private) / str(work.candidate.index)
                private_dir.mkdir()
                with stats.measure("physical_source_window_preload"):
                    prepared, climate = prepare_physical_inputs(work, rasters, climate_reader)
                yield position, work, prepared, climate, private_dir, ordinal == 0
                # A suspended input generator must not retain the previous
                # arrays while the next job is being loaded.
                del prepared, climate

        def compute(job: Any) -> Any:
            position, work, prepared, climate, private_dir, verify_reference = job
            try:
                with stats.measure("site_compute_and_private_artifacts"):
                    checkpoint, arrays = site_result(
                        work, prepared, topology, vectors, major_profiles, climate,
                        private_dir, verify_reference=verify_reference,
                    )
            except Exception as error:
                raise PhysicalSiteComputationError(work, private_dir, error) from error
            return position, work, checkpoint, arrays, private_dir

        results = bounded_map(
            compute, jobs(), workers=workers,
            memory_budget_bytes=memory_budget_mb * 1024 * 1024,
            estimated_task_bytes=SITE_MEMORY_ESTIMATE_BYTES,
            cancel_event=cancel_event, stats=stats, phase="physical_sites",
        )
        try:
            with closing(results):
                for result in results:
                    yield result
                    del result
        except PhysicalSiteComputationError as error:
            # The pool has joined: only this coordinator publishes a diagnostic.
            name = f"{error.work.candidate.site.settlement_id}.json"
            diagnostic = error.private_dir / "failures" / name
            if diagnostic.is_file():
                atomic_json(output_dir / "failures" / name, read_json(diagnostic))
            raise


def install_private_site(output_dir: Path, private_dir: Path, checkpoint: Mapping[str, Any]) -> None:
    """Coordinator-only publication, preserving each replaced predecessor."""
    artefacts = []
    for path_key, digest_key in (("route_relative_path", "route_sha256"),
                                 ("review_map_relative_path", "review_map_sha256")):
        relative = Path(checkpoint[path_key])
        source = (private_dir / relative).resolve()
        target = (output_dir / relative).resolve()
        if not source.is_relative_to(private_dir.resolve()) or not target.is_relative_to(output_dir.resolve()):
            raise ValueError("Physical artefact escaped its owned directory")
        if s6c5.sha256_file(source) != checkpoint[digest_key]:
            raise RuntimeError("Private physical artefact checksum mismatch")
        artefacts.append((relative, source, target))
    s6c5.install_private_bundle(output_dir, private_dir, checkpoint)
    for relative, source, target in artefacts:
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            predecessor = output_dir / "predecessor_artifacts" / str(time.time_ns()) / relative
            predecessor.parent.mkdir(parents=True, exist_ok=False)
            os.replace(target, predecessor)
            try:
                os.replace(source, target)
            except BaseException:
                os.replace(predecessor, target)
                raise
        else:
            os.replace(source, target)


def runoff_scenarios(climate: Any, land_mask: np.ndarray) -> dict[str, np.ndarray]:
    raw: dict[str, np.ndarray] = {}
    for name, parameters in RUNOFF_SCENARIOS.items():
        proxy = effective_runoff_proxy(
            climate.precipitation_mm,
            climate.pet_mm * np.float32(parameters["pet_multiplier"]),
            climate.snowfall_we_mm,
            climate.temperature_c,
            land_mask=climate.land_mask,
            melt_factor_mm_per_degree_c_month=parameters["melt_factor"],
        )
        parent = np.nan_to_num(proxy.monthly_effective_runoff_mm, nan=0.0)
        parent *= np.float32(parameters["delivery_fraction"])
        fine = np.repeat(np.repeat(parent, FINE_FACTOR, axis=1), FINE_FACTOR, axis=2)
        fine[:, ~land_mask] = 0.0
        raw[name] = fine.astype(np.float32)
    # Snow-release timing can make a nominally drier parameter set exceed the
    # base set in an individual cold month even when its annual climate is no
    # wetter.  Preserve those three physical parameter runs, but publish an
    # ordered uncertainty envelope: pointwise minimum, central/base run, and
    # pointwise maximum.  This avoids falsely labelling a timing permutation as
    # a monotonic low/base/high quantity.
    stack = np.stack([raw[name] for name in ("low", "base", "high")], axis=0)
    result = {
        "low": np.min(stack, axis=0).astype(np.float32),
        "base": raw["base"],
        "high": np.max(stack, axis=0).astype(np.float32),
    }
    annual = {name: values.sum(axis=0) for name, values in result.items()}
    if (
        np.any(result["low"] > result["base"] + 1e-5)
        or np.any(result["base"] > result["high"] + 1e-5)
        or np.any(annual["low"] > annual["base"] + 1e-5)
        or np.any(annual["base"] > annual["high"] + 1e-5)
    ):
        raise RuntimeError("Runoff scenario ordering failed")
    return result


def receiver_from_direction(direction: np.ndarray) -> np.ndarray:
    rows, cols = direction.shape
    receiver = np.full(rows * cols, -1, dtype=np.int64)
    rr, cc = np.indices((rows, cols), dtype=np.int64)
    for code, (dr, dc, _) in enumerate(physical.D8):
        selected = direction == code
        target_row = rr[selected] + dr
        target_col = cc[selected] + dc
        valid = (target_row >= 0) & (target_row < rows) & (target_col >= 0) & (target_col < cols)
        sources = np.flatnonzero(selected.ravel())
        receiver[sources[valid]] = target_row[valid] * cols + target_col[valid]
    return receiver


def mass_balance_metrics(
    monthly_runoff: np.ndarray,
    monthly_load: np.ndarray,
    direction: np.ndarray,
    boundary_seeds: Mapping[int, float],
) -> dict[str, Any]:
    receiver = receiver_from_direction(direction)
    sinks = receiver < 0
    cell_area = (10.0 / 1000.0) ** 2
    local_input = monthly_runoff.reshape(12, -1).sum(axis=1) * cell_area
    boundary_input = np.zeros(12, dtype=np.float64)
    flat = monthly_runoff.reshape(12, -1)
    for index, area in boundary_seeds.items():
        boundary_input += flat[:, int(index)] * float(area)
    expected = local_input + boundary_input
    actual = monthly_load.reshape(12, -1)[:, sinks].sum(axis=1)
    relative = np.abs(actual - expected) / np.maximum(np.abs(expected), 1e-9)
    return {
        "monthly_input_mm_km2": expected.tolist(),
        "monthly_sink_outflow_mm_km2": actual.tolist(),
        "monthly_mass_balance_max_relative_error": float(np.max(relative)),
        "monthly_mass_balance_pass": bool(float(np.max(relative)) <= 0.01),
    }


def mass_balance_metrics_mfd(
    monthly_runoff: np.ndarray,
    monthly_load: np.ndarray,
    receiver_weight: np.ndarray,
    boundary_seeds: Mapping[int, float],
) -> dict[str, Any]:
    sinks = np.asarray(receiver_weight, dtype=np.float64).sum(axis=0) <= 0.0
    cell_area = (10.0 / 1000.0) ** 2
    local_input = monthly_runoff.reshape(12, -1).sum(axis=1) * cell_area
    boundary_input = np.zeros(12, dtype=np.float64)
    flat = monthly_runoff.reshape(12, -1)
    for index, area in boundary_seeds.items():
        boundary_input += flat[:, int(index)] * float(area)
    expected = local_input + boundary_input
    actual = monthly_load.reshape(12, -1)[:, sinks].sum(axis=1)
    relative = np.abs(actual - expected) / np.maximum(np.abs(expected), 1e-9)
    return {
        "monthly_input_mm_km2": expected.tolist(),
        "monthly_sink_outflow_mm_km2": actual.tolist(),
        "monthly_mass_balance_max_relative_error": float(np.max(relative)),
        "monthly_mass_balance_pass": bool(float(np.max(relative)) <= 0.01),
    }


def _normalise_image(array: np.ndarray, *, diverging: bool = False, log: bool = False) -> np.ndarray:
    value = np.asarray(array, dtype=np.float64)
    if log:
        value = np.log1p(np.maximum(value, 0.0))
    finite = np.isfinite(value)
    if not np.any(finite):
        return np.zeros((*value.shape, 3), dtype=np.uint8)
    if diverging:
        maximum = float(np.percentile(np.abs(value[finite]), 99.0)) or 1.0
        scaled = np.clip(value / maximum, -1.0, 1.0)
        red = np.where(scaled >= 0, 255, 255 * (1 + scaled))
        blue = np.where(scaled <= 0, 255, 255 * (1 - scaled))
        green = 255 * (1 - np.abs(scaled))
        return np.stack((red, green, blue), axis=-1).astype(np.uint8)
    low, high = np.percentile(value[finite], (2.0, 98.0))
    scaled = np.clip((value - low) / max(float(high - low), 1e-9), 0.0, 1.0)
    red = 35 + 200 * scaled
    green = 45 + 170 * np.sqrt(scaled)
    blue = 110 + 100 * (1 - scaled)
    rgb = np.stack((red, green, blue), axis=-1)
    rgb[~finite] = 0
    return rgb.astype(np.uint8)


def _panel(
    array: np.ndarray,
    label: str,
    *,
    overlay: np.ndarray | None = None,
    inherited_overlay: np.ndarray | None = None,
    diverging: bool = False,
    log: bool = False,
) -> Image.Image:
    rgb = _normalise_image(array, diverging=diverging, log=log)
    if inherited_overlay is not None:
        selected = np.asarray(inherited_overlay) > 0
        rgb[selected] = np.array([255, 145, 20], dtype=np.uint8)
    if overlay is not None:
        selected = np.asarray(overlay) > 0
        rgb[selected] = np.array([20, 225, 255], dtype=np.uint8)
    image = Image.fromarray(rgb, mode="RGB").resize((330, 330), Image.Resampling.NEAREST)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 330, 24), fill=(0, 0, 0))
    draw.text((6, 5), label, fill=(255, 255, 255), font=ImageFont.load_default())
    return image


def write_review_map(path: Path, work: SiteWork, arrays: Mapping[str, np.ndarray], metrics: Mapping[str, Any]) -> None:
    parent = physical.parent_block_means(arrays["base_broad_elevation_m"])
    parent_repeat = np.repeat(np.repeat(parent, 10, axis=0), 10, axis=1)
    overlay = arrays["protected_channel_class"]
    inherited = arrays["inherited_current_channel_class"]
    panels = [
        _panel(parent_repeat, "100 m authority (repeated for comparison)", overlay=overlay, inherited_overlay=inherited),
        _panel(arrays["base_broad_elevation_m"], "Broad parent-conserving 10 m model", overlay=overlay, inherited_overlay=inherited),
        _panel(arrays["conditioned_elevation_m"], "Conditioned physical 10 m model", overlay=overlay, inherited_overlay=inherited),
        _panel(arrays["terrain_conditioning_delta_m"], "Physical conditioning delta (<=1 m)", diverging=True),
        _panel(arrays["routing_fill_delta_m"], "Separate analytical routing fill", diverging=True),
        _panel(arrays["annual_accumulated_runoff_base_mm_km2"], "Base accumulated runoff proxy", overlay=overlay, inherited_overlay=inherited, log=True),
        _panel(arrays["channel_width_base_m"], "Supported-channel width proxy", log=True),
        _panel(arrays["flood_susceptibility"], "Geomorphic susceptibility (not flood extent)", overlay=overlay, inherited_overlay=inherited),
        _panel(arrays["wetness_potential"], "Wetness potential", overlay=overlay, inherited_overlay=inherited),
    ]
    canvas = Image.new("RGB", (1010, 1085), (242, 242, 242))
    for index, panel in enumerate(panels):
        canvas.paste(panel, (5 + (index % 3) * 335, 70 + (index // 3) * 335))
    draw = ImageDraw.Draw(canvas)
    draw.text((8, 8), f"Stage 6C.5R — {work.candidate.site.settlement_id}", fill=(0, 0, 0))
    draw.text((8, 27), "WORKING PROPOSAL — REVIEW ONLY — NOT CANON; physical source remains 100 m", fill=(120, 0, 0))
    draw.text(
        (8, 46),
        f"protected registered={metrics['physically_admissible_route_count']}  quarantined={metrics['incomplete_quarantined_route_count']}  parent error={metrics['maximum_parent_mean_error_m']:.6f} m  mass balance={metrics['monthly_mass_balance_max_relative_error']:.3g}",
        fill=(0, 0, 0),
    )
    draw.text((690, 46), "orange=registered evidence  cyan=protected axis", fill=(0, 0, 0))
    site_row = int(round((work.candidate.site.y - work.row0 * 0.1) / FINE_CELL_KM))
    site_col = int(round((work.candidate.site.x - work.col0 * 0.1) / FINE_CELL_KM))
    for panel_row in range(3):
        for panel_col in range(3):
            cx = 5 + panel_col * 335 + int(site_col * 330 / FINE_CELLS)
            cy = 70 + panel_row * 335 + int(site_row * 330 / FINE_CELLS)
            draw.line((cx - 5, cy, cx + 5, cy), fill=(255, 0, 255), width=2)
            draw.line((cx, cy - 5, cx, cy + 5), fill=(255, 0, 255), width=2)
    path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(path, format="PNG", optimize=True)


def site_result(
    work: SiteWork,
    rasters: s6c.RasterStack,
    topology: s6c.ExactSurfaceIndex,
    vectors: s6c.VectorStack,
    major_profiles: ActiveMajorBedProfiles,
    climate_reader: C1MonthlyClimateReader,
    output_dir: Path,
    verify_reference: bool,
) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
    base, parent = terrain_tile(work, rasters, verify_reference)
    parent_context = rasters.read_block(
        work.analysis_row0,
        work.analysis_col0,
        ANALYSIS_PARENT_CELLS,
        ANALYSIS_PARENT_CELLS,
    )
    exact_barony = s6c5.rasterize_exact_surface_10m(
        topology,
        work.analysis_row0 * 10,
        work.analysis_col0 * 10,
        ANALYSIS_FINE_CELLS,
        ANALYSIS_FINE_CELLS,
    )
    exact_surface = exact_barony > 0
    sea = s6c5.repeat_parent(parent_context["sea"]).astype(bool)
    wetland = s6c5.repeat_parent(parent_context["wetland"]).astype(bool)
    seren = s6c5.repeat_parent(parent_context["seren"]).astype(bool)
    inherited_flood = s6c5.repeat_parent(parent_context["flood_exposure"]).astype(np.float32)

    climate = climate_reader.read_window(Window(
        work.analysis_col0,
        work.analysis_row0,
        ANALYSIS_PARENT_CELLS,
        ANALYSIS_PARENT_CELLS,
    ))
    climate_land = np.repeat(np.repeat(climate.land_mask, 10, axis=0), 10, axis=1)
    land = exact_surface & ~sea & climate_land
    scenarios = runoff_scenarios(climate, land)
    lake = rasterize_polygons(vectors.permanent_lake_geoms, vectors.permanent_lake_tree, work)
    registered_sinks = sea | seren | lake | special_sink_mask(vectors, work)

    constraints, route_records = channel_constraints(vectors, work, base, major_profiles)
    # The repair preserves the registered current axes and uses their separate
    # vertical controls.  It no longer asks A* to invent a replacement river
    # from broad land elevation inside a cropped corridor.
    constraint_by_id = {constraint.feature_id: constraint for constraint in constraints}
    inherited_channel_class = np.zeros(
        (ANALYSIS_FINE_CELLS, ANALYSIS_FINE_CELLS), dtype=np.uint8
    )
    for record in route_records:
        path = tuple(tuple(cell) for cell in record.pop("path_cells"))
        record["inherited_path_cells"] = [list(cell) for cell in path]
        code = physical.CLASS_CODE[str(record["route_class"])]
        for row, col in path:
            inherited_channel_class[row, col] = max(int(inherited_channel_class[row, col]), code)
        protected = constraint_by_id.get(str(record["part_id"]))
        if protected is None:
            record["candidate_path_cells"] = []
            record["route_status"] = "INCOMPLETE_STILLKLINGE_REVIEW_CORRIDOR_NOT_PROTECTED"
            record["physical_route_accepted"] = False
            record["route_failure_reason"] = "NOT_APPROVED_GEOMETRY_CANDIDATE"
        else:
            record["candidate_path_cells"] = [list(cell) for cell in protected.path_cells]
            record["route_status"] = "PASS_REGISTERED_TOPOLOGY_WITH_SEPARATE_BED_CONTROL"
            record["physical_route_accepted"] = True
            record["route_failure_reason"] = None
        record["candidate_route_metrics"] = {
            "path_cell_count": len(record["candidate_path_cells"]),
            "path_changed_from_registered_axis": False,
        }
        record["candidate_route_lineage"] = {
            "method": HYDROLOGY_METHOD_VERSION,
            "terrain_rerouting_used": False,
        }
        record["preconditioning_search_uphill_allowance_m"] = None
        record["interior_corridor_edge_fraction"] = 0.0 if protected is not None else None
    try:
        context = physical.build_physical_context(
            base,
            parent,
            scenarios["base"],
            constraints,
            land,
            registered_sinks,
            inherited_flood,
            wetland.astype(np.float32),
            recipe=PHYSICAL_RECIPE,
            source_lineage={
                "climate": dict(climate.source_lineage),
                "site_semantic_key": work.semantic_key,
                "major_bed_profiles_sha256": s6c.SOURCES["active_major_bed_profiles"]["sha256"],
                "major_vertical_control": (
                    "NEW_REVIEW_CANDIDATE_FROM_ACTIVE_PROFILE_WITH_CONDITIONED_"
                    "TERRAIN_CEILING; ORIGINAL_PROFILE_UNCHANGED"
                ),
                "minor_vertical_control": (
                    "REGISTERED_D3_GRAPH_WITH_MODELLED_SEPARATE_MONOTONE_BED_NOT_SLOPE_SCALAR"
                ),
                "analysis_support_km": ANALYSIS_PARENT_CELLS * 0.1,
                "published_core_km": WINDOW_PARENT_CELLS * 0.1,
            },
        )
    except Exception as error:
        atomic_json(
            output_dir / "failures" / f"{work.candidate.site.settlement_id}.json",
            {
                "status": "FAIL_CLOSED",
                "settlement_id": work.candidate.site.settlement_id,
                "error": f"{type(error).__name__}: {error}",
                "semantic_key": work.semantic_key,
                "routes": route_records,
                "canon_status": CANON_STATUS,
            },
        )
        raise

    # Publish the new terrain-authority-compatible bed candidate, not the
    # conflicting source Z. The hash-locked source profile remains untouched
    # and is retained in lineage; this is an explicit derived candidate.
    final_bed_grid = context.arrays["protected_channel_bed_elevation_m"]
    conditioned_land = context.arrays["conditioned_elevation_m"]
    for record in route_records:
        candidate_path = [tuple(cell) for cell in record["candidate_path_cells"]]
        if not candidate_path:
            continue
        source_bed = np.asarray(record["bed_elevations_m"], dtype=np.float64)
        final_bed = np.asarray([final_bed_grid[cell] for cell in candidate_path], dtype=np.float64)
        if len(source_bed) != len(final_bed) or not np.all(np.isfinite(final_bed)):
            raise RuntimeError(
                f"Reconciled bed publication mismatch for {record['part_id']}"
            )
        downward = source_bed - final_bed
        clearance = np.asarray(
            [conditioned_land[cell] for cell in candidate_path], dtype=np.float64
        ) - final_bed
        if np.any(clearance < -1e-9):
            raise RuntimeError(
                f"CONFLICT_PROFILE_ABOVE_TERRAIN remained for {record['part_id']}"
            )
        record["source_bed_elevation_start_m"] = float(source_bed[0])
        record["source_bed_elevation_end_m"] = float(source_bed[-1])
        record["source_bed_elevation_min_m"] = float(np.min(source_bed))
        record["source_bed_elevation_max_m"] = float(np.max(source_bed))
        record["bed_elevations_m"] = [float(value) for value in final_bed]
        record["bed_elevation_start_m"] = float(final_bed[0])
        record["bed_elevation_end_m"] = float(final_bed[-1])
        record["bed_elevation_min_m"] = float(np.min(final_bed))
        record["bed_elevation_max_m"] = float(np.max(final_bed))
        record["route_status"] = (
            "PASS_REGISTERED_TOPOLOGY_WITH_RECONCILED_SEPARATE_BED_CANDIDATE"
        )
        lineage = dict(record["bed_profile_lineage"])
        lineage.update({
            "reconciled_profile_is_new_review_candidate": True,
            "terrain_authority_precedence": True,
            "reconciliation_method": (
                "ONE_SIDED_CONSTRAINED_MONOTONE_FIT_TO_CONDITIONED_TERRAIN_CEILING"
            ),
            "terrain_ceiling_reconciled_cell_count": int(
                np.count_nonzero(downward > 1e-9)
            ),
            "maximum_downward_reconciliation_m": float(
                max(float(np.max(downward)), 0.0)
            ),
            "minimum_reconciled_bed_clearance_m": float(np.min(clearance)),
        })
        if record["source_kind"] == "major":
            lineage.update({
                "source_profile_preserved_unchanged": True,
                "source_profile_sha256": (
                    s6c.SOURCES["active_major_bed_profiles"]["sha256"]
                ),
            })
        else:
            lineage["pre_reconciliation_modelled_bed_retained_in_lineage"] = True
        record["bed_profile_lineage"] = lineage
        record["candidate_route_lineage"].update({
            "bed_candidate_reconciled_to_terrain_authority": True,
        })
        if record["source_kind"] == "major":
            record["candidate_route_lineage"]["source_profile_preserved_unchanged"] = True

    direction = context.arrays["d8_receiver_code"].astype(np.int8, copy=False)
    receiver = context.arrays["mfd_receiver_indices"].astype(np.int64, copy=False)
    receiver_weight = context.arrays["mfd_receiver_weights"].astype(np.float32, copy=False)
    boundary_seeds = physical.boundary_inflow_seeds(
        constraints, context.arrays["conditioned_elevation_m"]
    )
    # The graph is identical for low/high runoff. Batch its traversal while
    # preserving each scenario's independent arithmetic and reduction order.
    (_, _, annual_low, low_metrics), (_, _, annual_high, high_metrics) = physical.accumulate_flow_mfd_scenarios(
        context.arrays["routing_elevation_m"], receiver, receiver_weight,
        (scenarios["low"], scenarios["high"]), boundary_seeds
    )
    protected = context.arrays["protected_channel_class"]
    slope = context.arrays["local_slope_m_per_m"]
    width_low = physical.derive_width_proxy(protected, annual_low, slope)
    width_base = context.arrays["channel_width_proxy_m"]
    width_high = physical.derive_width_proxy(protected, annual_high, slope)

    base_load = context.arrays["monthly_accumulated_runoff_proxy_mm_km2"]
    balance = mass_balance_metrics_mfd(
        scenarios["base"], base_load, receiver_weight, boundary_seeds
    )
    active_edge = (receiver >= 0) & (receiver_weight > 0.0)
    edge_source, edge_code = np.nonzero(active_edge.T)
    edge_target = receiver[edge_code, edge_source]
    routed_flat = context.arrays["routing_elevation_m"].ravel()
    downhill_minimum = (
        float(np.min(routed_flat[edge_source] - routed_flat[edge_target]))
        if len(edge_source) else math.inf
    )
    if downhill_minimum <= 0.0:
        raise RuntimeError("Stage 6C.5R receiver graph contains a non-downhill edge")
    metrics = {
        **context.metrics,
        **balance,
        "strict_downhill_minimum_drop_m": downhill_minimum,
        "official_coordinate_modified": False,
        "surface_or_interface_context_only": work.candidate.disposition.startswith("SURFACE_OR_INTERFACE"),
        "route_record_count": len(route_records),
        "physically_admissible_route_count": len(constraints),
        "incomplete_quarantined_route_count": sum(
            bool(record["requires_physical_gate"]) and not bool(record["physical_route_accepted"])
            for record in route_records
        ),
        "unapproved_support_corridor_count": sum(
            not bool(record["requires_physical_gate"]) for record in route_records
        ),
        "boundary_inflow_feature_count": sum(
            bool(record["boundary_inflow"]) and bool(record["physical_route_accepted"])
            for record in route_records
        ),
        "inherited_boundary_inflow_feature_count": sum(
            bool(record["boundary_inflow"]) for record in route_records
        ),
        "boundary_outflow_feature_count": sum(
            bool(record["boundary_outflow"]) for record in route_records
        ),
        "boundary_inflow_seed_count": len(boundary_seeds),
        "boundary_area_anchor_max_relative_error": 0.0,
        "stillklinge_unresolved_feature_count": sum(
            bool(record["source_label_must_not_be_promoted"]) for record in route_records
        ),
        "unsupported_channel_promoted_count": 0,
        "pilot_site_gate_pass": all(
            bool(record["physical_route_accepted"])
            for record in route_records if bool(record["requires_physical_gate"])
        ),
        "low_flow_graph_sha256": low_metrics["receiver_graph_sha256"],
        "high_flow_graph_sha256": high_metrics["receiver_graph_sha256"],
    }
    if not balance["monthly_mass_balance_pass"]:
        raise RuntimeError("Stage 6C.5R monthly water balance failed")

    core = work.core_slice
    crop2 = lambda value: np.asarray(value)[core]
    crop3 = lambda value: np.asarray(value)[:, core[0], core[1]]
    arrays = {
        "base_broad_elevation_m": crop2(base),
        "conditioned_elevation_m": crop2(context.arrays["conditioned_elevation_m"]),
        "terrain_conditioning_delta_m": crop2(context.arrays["terrain_conditioning_delta_m"]),
        "routing_elevation_m": crop2(context.arrays["routing_elevation_m"]),
        "routing_fill_delta_m": crop2(context.arrays["routing_fill_delta_m"]),
        "protected_channel_bed_elevation_m": crop2(
            context.arrays["protected_channel_bed_elevation_m"]
        ),
        "local_slope_m_per_m": crop2(context.arrays["local_slope_m_per_m"]),
        "monthly_effective_runoff_low_mm": crop3(scenarios["low"]),
        "monthly_effective_runoff_base_mm": crop3(scenarios["base"]),
        "monthly_effective_runoff_high_mm": crop3(scenarios["high"]),
        "monthly_accumulated_runoff_base_mm_km2": crop3(base_load),
        "accumulated_area_km2": crop2(context.arrays["accumulated_area_km2"]),
        "annual_accumulated_runoff_low_mm_km2": crop2(annual_low),
        "annual_accumulated_runoff_base_mm_km2": crop2(
            context.arrays["annual_accumulated_runoff_proxy_mm_km2"]
        ),
        "annual_accumulated_runoff_high_mm_km2": crop2(annual_high),
        "inherited_current_channel_class": crop2(inherited_channel_class),
        "protected_channel_class": crop2(protected),
        "drainage_potential_or_protected_class": crop2(
            context.arrays["drainage_potential_or_protected_class"]
        ),
        "channel_width_low_m": crop2(width_low),
        "channel_width_base_m": crop2(width_base),
        "channel_width_high_m": crop2(width_high),
        "d8_receiver_code": crop2(direction).astype(np.int8),
        "mfd_receiver_weights": crop3(
            receiver_weight.reshape(8, ANALYSIS_FINE_CELLS, ANALYSIS_FINE_CELLS)
        ),
        "nearest_channel_height_proxy_m": crop2(
            context.arrays["nearest_channel_height_proxy_m"]
        ),
        "flood_susceptibility": crop2(context.arrays["flood_potential"]),
        "wetness_potential": crop2(context.arrays["wetness_potential"]),
        "exact_barony_id": crop2(exact_barony).astype(np.int32),
        "exact_surface": crop2(exact_surface).astype(np.uint8),
        "land_mask": crop2(land).astype(np.uint8),
        "sea_mask_parent_projected": crop2(sea).astype(np.uint8),
        "wetland_mask_parent_projected": crop2(wetland).astype(np.uint8),
        "serenakrone_water_parent_projected": crop2(seren).astype(np.uint8),
        "protected_flood_evidence_parent_projected": crop2(inherited_flood),
        "registered_sink_mask": crop2(registered_sinks).astype(np.uint8),
    }
    arrays = {
        name: np.asarray(arrays[name], dtype=np.dtype(array_specs()[name][1]))
        for name in array_specs()
    }
    final_digest = arrays_digest(arrays)
    lineage_safe = json.loads(canonical_json(context.lineage))
    metadata = {
        "schema": "diadem.stage6c5r-site-physical-context.v3",
        "method": METHOD,
        "canon_status": CANON_STATUS,
        "settlement_id": work.candidate.site.settlement_id,
        "functional_tier": work.candidate.site.functional_tier,
        "disposition": work.candidate.disposition,
        "official_coordinate_km": [work.candidate.site.x, work.candidate.site.y],
        "official_coordinate_modified": False,
        "window_parent": [work.row0, work.col0, WINDOW_PARENT_CELLS, WINDOW_PARENT_CELLS],
        "analysis_window_parent": [
            work.analysis_row0,
            work.analysis_col0,
            ANALYSIS_PARENT_CELLS,
            ANALYSIS_PARENT_CELLS,
        ],
        "published_core_offset_parent": [work.core_row_offset, work.core_col_offset],
        "cell_size_m": 10,
        "physical_source_resolution_m": 100,
        "not_surveyed_10m": True,
        "generated_channels_promoted": False,
        "width_status": "MODELLED_UNCALIBRATED_LOW_BASE_HIGH_ENSEMBLE",
        "flood_status": "MODELLED_GEOMORPHIC_SUSCEPTIBILITY_NOT_EXTENT_DEPTH_OR_RETURN_PERIOD",
        "semantic_key": work.semantic_key,
        "array_digest": final_digest,
        "metrics": metrics,
        "lineage": lineage_safe,
    }
    tile_spec = TileSpec(
        f"S6C5R-{work.candidate.site.settlement_id}",
        work.row0, work.col0, WINDOW_PARENT_CELLS, WINDOW_PARENT_CELLS,
    )
    tile = EvidenceTile(tile_spec, GRID, arrays, arrays, metadata)
    bundle_path = output_dir / "tile_cache" / f"t_{work.semantic_key[:20]}.zstbundle"
    if bundle_path.exists():
        shutil.rmtree(bundle_path)
    write_tile_recovery_bundle(tile, bundle_path, compact=True, compression_level=HOT_CACHE_ZSTD_LEVEL)
    bundle_manifest = s6c5.verified_bundle_manifest(bundle_path)

    route_path = output_dir / "routes" / f"{work.candidate.site.settlement_id}.geojson"
    route_path.parent.mkdir(parents=True, exist_ok=True)
    route_features = []
    for record in route_records:
        inherited_coordinates = [
            [
                (work.analysis_col0 * 10 + cell[1] + 0.5) * FINE_CELL_KM,
                (work.analysis_row0 * 10 + cell[0] + 0.5) * FINE_CELL_KM,
            ]
            for cell in record["inherited_path_cells"]
        ]
        candidate_coordinates = [
            [
                (work.analysis_col0 * 10 + cell[1] + 0.5) * FINE_CELL_KM,
                (work.analysis_row0 * 10 + cell[0] + 0.5) * FINE_CELL_KM,
                float(record["bed_elevations_m"][index]),
            ]
            for index, cell in enumerate(record["candidate_path_cells"])
        ]
        properties = {
            key: value for key, value in record.items()
            if key not in {"inherited_path_cells", "candidate_path_cells", "bed_elevations_m"}
        }
        route_features.append({
            "type": "Feature",
            "geometry": mapping(LineString(inherited_coordinates)),
            "properties": {
                **properties,
                "geometry_role": "REGISTERED_V4_2_RASTERISED_10M_AXIS",
                "coordinate_reference": "DIADEM_LOCAL_KM_X_EAST_Y_SOUTH",
            },
        })
        if len(candidate_coordinates) >= 2:
            route_features.append({
                "type": "Feature",
                "geometry": mapping(LineString(candidate_coordinates)),
                "properties": {
                    **properties,
                    "geometry_role": "S6C5R_REGISTERED_AXIS_WITH_SEPARATE_BED_Z",
                    "coordinate_reference": "DIADEM_LOCAL_KM_X_EAST_Y_SOUTH",
                },
            })
    atomic_json(route_path, {
        "type": "FeatureCollection",
        "name": "stage6c5r_supported_route_context_review_only",
        "canon_status": CANON_STATUS,
        "features": route_features,
    })
    review_map_path = output_dir / "review_maps" / f"{work.candidate.site.settlement_id}.png"
    write_review_map(review_map_path, work, arrays, metrics)
    checkpoint = {
        "schema": "diadem.stage6c5r-site-checkpoint.v3",
        "completed_utc": utc_now(),
        "settlement_id": work.candidate.site.settlement_id,
        "functional_tier": work.candidate.site.functional_tier,
        "disposition": work.candidate.disposition,
        "official_x_km": work.candidate.site.x,
        "official_y_km": work.candidate.site.y,
        "official_coordinate_modified": False,
        "zarr_index": work.candidate.index,
        "semantic_key": work.semantic_key,
        "window_parent": [work.row0, work.col0, WINDOW_PARENT_CELLS, WINDOW_PARENT_CELLS],
        "analysis_window_parent": [
            work.analysis_row0, work.analysis_col0,
            ANALYSIS_PARENT_CELLS, ANALYSIS_PARENT_CELLS,
        ],
        "published_core_offset_parent": [work.core_row_offset, work.core_col_offset],
        "array_digest": final_digest,
        "bundle_relative_path": bundle_path.relative_to(output_dir).as_posix(),
        "bundle_id": bundle_manifest["bundle_id"],
        "route_relative_path": route_path.relative_to(output_dir).as_posix(),
        "route_sha256": s6c5.sha256_file(route_path),
        "review_map_relative_path": (Path("review_maps") / f"{work.candidate.site.settlement_id}.png").as_posix(),
        "review_map_sha256": s6c5.sha256_file(review_map_path),
        "metrics": metrics,
        "lineage": lineage_safe,
        "routes": [
            {
                key: value for key, value in record.items()
                if key not in {"inherited_path_cells", "candidate_path_cells", "bed_elevations_m"}
            }
            for record in route_records
        ],
        "canon_status": CANON_STATUS,
    }
    (output_dir / "failures" / f"{work.candidate.site.settlement_id}.json").unlink(missing_ok=True)
    return checkpoint, arrays


def load_checkpoint(
    path: Path, work: SiteWork, group: zarr.Group, output_dir: Path,
    *, runtime_identity: str | None = None,
) -> dict[str, Any] | None:
    if not path.is_file() or int(group["site_complete"][work.candidate.index]) != 1:
        return None
    try:
        checkpoint = read_json(path)
        if runtime_identity is not None and checkpoint.get("runtime_identity") != runtime_identity:
            return None
        if checkpoint["semantic_key"] != work.semantic_key:
            return None
        arrays = {name: np.asarray(group[name][work.candidate.index]) for name in array_specs()}
        if arrays_digest(arrays) != checkpoint["array_digest"]:
            return None
        manifest = s6c5.verified_bundle_manifest(output_dir / checkpoint["bundle_relative_path"])
        if manifest["bundle_id"] != checkpoint["bundle_id"]:
            return None
        route_path = output_dir / checkpoint["route_relative_path"]
        review_map_path = output_dir / checkpoint["review_map_relative_path"]
        if s6c5.sha256_file(route_path) != checkpoint["route_sha256"]:
            return None
        if s6c5.sha256_file(review_map_path) != checkpoint["review_map_sha256"]:
            return None
        return checkpoint
    except Exception:
        return None


def build_database(output_dir: Path, checkpoints: Sequence[Mapping[str, Any]], scope: str) -> Path:
    if not SOURCE_STAGE6C5_DB.is_file():
        raise FileNotFoundError(SOURCE_STAGE6C5_DB)
    output = output_dir / OUTPUT_DB_NAME
    temporary = output.with_name(f".{output.name}.{os.getpid()}.build")
    if temporary.exists():
        temporary.unlink()
    s6c5.sqlite_backup(SOURCE_STAGE6C5_DB, temporary)
    connection = sqlite3.connect(temporary)
    try:
        connection.executescript(
            """
            PRAGMA foreign_keys=ON;
            DROP TABLE IF EXISTS stage6c5r_route_context;
            DROP TABLE IF EXISTS stage6c5r_site_physical_context;
            DROP TABLE IF EXISTS stage6c5r_run_metadata;
            CREATE TABLE stage6c5r_run_metadata (
                method TEXT PRIMARY KEY,
                scope TEXT NOT NULL,
                completed_site_count INTEGER NOT NULL,
                pilot_route_gate_pass INTEGER NOT NULL,
                quarantined_route_count INTEGER NOT NULL,
                canon_status TEXT NOT NULL,
                generated_channels_promoted INTEGER NOT NULL CHECK(generated_channels_promoted=0),
                official_coordinates_modified INTEGER NOT NULL CHECK(official_coordinates_modified=0),
                ft0_scope_sha256 TEXT NOT NULL,
                recipe_json TEXT NOT NULL
            );
            CREATE TABLE stage6c5r_site_physical_context (
                settlement_id TEXT PRIMARY KEY REFERENCES settlement(settlement_id),
                functional_tier TEXT NOT NULL,
                disposition TEXT NOT NULL,
                official_x_km REAL NOT NULL,
                official_y_km REAL NOT NULL,
                official_coordinate_modified INTEGER NOT NULL CHECK(official_coordinate_modified=0),
                zarr_index INTEGER NOT NULL UNIQUE,
                semantic_key TEXT NOT NULL UNIQUE,
                array_digest TEXT NOT NULL,
                bundle_relative_path TEXT NOT NULL,
                route_relative_path TEXT NOT NULL,
                review_map_relative_path TEXT NOT NULL,
                protected_feature_count INTEGER NOT NULL,
                boundary_inflow_feature_count INTEGER NOT NULL,
                physically_admissible_route_count INTEGER NOT NULL,
                incomplete_quarantined_route_count INTEGER NOT NULL,
                pilot_site_gate_pass INTEGER NOT NULL,
                maximum_parent_mean_error_m REAL NOT NULL,
                conditioning_delta_max_abs_m REAL NOT NULL,
                monthly_mass_balance_max_relative_error REAL NOT NULL,
                strict_downhill_minimum_drop_m REAL NOT NULL,
                generated_channels_promoted INTEGER NOT NULL CHECK(generated_channels_promoted=0),
                metrics_json TEXT NOT NULL,
                lineage_json TEXT NOT NULL,
                canon_status TEXT NOT NULL
            );
            CREATE TABLE stage6c5r_route_context (
                settlement_id TEXT NOT NULL REFERENCES stage6c5r_site_physical_context(settlement_id),
                part_id TEXT NOT NULL,
                feature_id TEXT NOT NULL,
                source_kind TEXT NOT NULL,
                route_class TEXT NOT NULL,
                persistence TEXT NOT NULL,
                receiver_id TEXT,
                inherited_strahler_order INTEGER,
                boundary_inflow INTEGER NOT NULL,
                boundary_outflow INTEGER NOT NULL,
                boundary_area_prior_km2 REAL NOT NULL,
                source_label_must_not_be_promoted INTEGER NOT NULL,
                route_status TEXT NOT NULL,
                physical_route_accepted INTEGER NOT NULL,
                route_failure_reason TEXT,
                vertical_control TEXT NOT NULL,
                bed_profile_lineage_json TEXT NOT NULL,
                interior_corridor_edge_fraction REAL,
                candidate_route_metrics_json TEXT,
                candidate_route_lineage_json TEXT,
                PRIMARY KEY(settlement_id, part_id)
            );
            CREATE INDEX stage6c5r_site_tier_idx ON stage6c5r_site_physical_context(functional_tier);
            CREATE INDEX stage6c5r_route_feature_idx ON stage6c5r_route_context(feature_id);
            """
        )
        connection.execute(
            "INSERT INTO stage6c5r_run_metadata VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                METHOD, scope, len(checkpoints),
                int(all(bool(item["metrics"]["pilot_site_gate_pass"]) for item in checkpoints)),
                sum(int(item["metrics"]["incomplete_quarantined_route_count"]) for item in checkpoints),
                CANON_STATUS, 0, 0,
                FT0_LIST_SHA256, canonical_json(recipe_identity()),
            ),
        )
        for checkpoint in checkpoints:
            metrics = checkpoint["metrics"]
            connection.execute(
                """
                INSERT INTO stage6c5r_site_physical_context VALUES
                (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    checkpoint["settlement_id"], checkpoint["functional_tier"],
                    checkpoint["disposition"], checkpoint["official_x_km"],
                    checkpoint["official_y_km"], 0, checkpoint["zarr_index"],
                    checkpoint["semantic_key"], checkpoint["array_digest"],
                    checkpoint["bundle_relative_path"], checkpoint["route_relative_path"],
                    checkpoint["review_map_relative_path"], metrics["protected_feature_count"],
                    metrics["boundary_inflow_feature_count"],
                    metrics["physically_admissible_route_count"],
                    metrics["incomplete_quarantined_route_count"],
                    int(bool(metrics["pilot_site_gate_pass"])),
                    metrics["maximum_parent_mean_error_m"],
                    metrics["conditioning_delta_max_abs_m"],
                    metrics["monthly_mass_balance_max_relative_error"],
                    metrics["strict_downhill_minimum_drop_m"], 0,
                    canonical_json(metrics), canonical_json(checkpoint["lineage"]),
                    CANON_STATUS,
                ),
            )
            for route in checkpoint["routes"]:
                connection.execute(
                    """
                    INSERT INTO stage6c5r_route_context VALUES
                    (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        checkpoint["settlement_id"], route["part_id"], route["feature_id"],
                        route["source_kind"], route["route_class"], route["persistence"],
                        route.get("receiver_id"), route.get("inherited_strahler_order"),
                        int(bool(route["boundary_inflow"])), int(bool(route["boundary_outflow"])),
                        route["boundary_area_prior_km2"],
                        int(bool(route["source_label_must_not_be_promoted"])),
                        route["route_status"], int(bool(route["physical_route_accepted"])),
                        route.get("route_failure_reason"),
                        route["vertical_control"],
                        canonical_json(route.get("bed_profile_lineage")),
                        route.get("interior_corridor_edge_fraction"),
                        canonical_json(route.get("candidate_route_metrics")),
                        canonical_json(route.get("candidate_route_lineage")),
                    ),
                )
        connection.commit()
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("Stage 6C.5R output database integrity failure")
    finally:
        connection.close()
    os.replace(temporary, output)
    return output


def write_reports(
    output_dir: Path,
    checkpoints: Sequence[Mapping[str, Any]],
    scope: str,
    sources: Mapping[str, Any],
    runtime_s: float,
) -> None:
    quarantined_route_count = sum(
        int(item["metrics"]["incomplete_quarantined_route_count"]) for item in checkpoints
    )
    pilot_route_gate_pass = all(
        bool(item["metrics"]["pilot_site_gate_pass"]) for item in checkpoints
    )
    summary = {
        "schema": "diadem.stage6c5r-run-summary.v3",
        "method": METHOD,
        "status": (
            "PASS_REVIEW_ONLY"
            if pilot_route_gate_pass
            else "INCOMPLETE_ROUTE_QUARANTINE_REVIEW_ONLY"
        ),
        "scope": scope,
        "completed_site_count": len(checkpoints),
        "pilot_route_gate_pass": pilot_route_gate_pass,
        "quarantined_route_count": quarantined_route_count,
        "ft0_scope_sha256": FT0_LIST_SHA256,
        "canon_status": CANON_STATUS,
        "runtime_seconds": runtime_s,
        "physical_source_resolution_m": 100,
        "model_resolution_m": 10,
        "official_coordinates_modified": False,
        "generated_channels_promoted": False,
        "sources": sources,
        "recipe": recipe_identity(),
        "sites": [
            {
                "settlement_id": item["settlement_id"],
                "functional_tier": item["functional_tier"],
                "array_digest": item["array_digest"],
                "pilot_site_gate_pass": item["metrics"]["pilot_site_gate_pass"],
                "physically_admissible_route_count": item["metrics"]["physically_admissible_route_count"],
                "incomplete_quarantined_route_count": item["metrics"]["incomplete_quarantined_route_count"],
                "protected_feature_count": item["metrics"]["protected_feature_count"],
                "maximum_parent_mean_error_m": item["metrics"]["maximum_parent_mean_error_m"],
                "conditioning_delta_max_abs_m": item["metrics"]["conditioning_delta_max_abs_m"],
                "monthly_mass_balance_max_relative_error": item["metrics"]["monthly_mass_balance_max_relative_error"],
            }
            for item in checkpoints
        ],
    }
    summary["result_identity_sha256"] = digest_json(summary)
    atomic_json(output_dir / "S6C5R_RUN_SUMMARY.json", summary)
    rows = [
        "# Stage 6C.5R profile-aware registered-topology 10 m physical context",
        "",
        "**WORKING PROPOSAL — REVIEW ONLY — NOT CANON**",
        "",
        f"Scope: `{scope}`; completed sites: **{len(checkpoints)}**; last invocation runtime: **{runtime_s:.1f} s**.",
        f"Registered-route support and vertical-control gate: **{'PASS' if pilot_route_gate_pass else 'INCOMPLETE'}**; quarantined route parts: **{quarantined_route_count}**.",
        "",
        "This is a drainage-conditioned analytical refinement with preserved registered waterway planforms, not a simple increase in cell count and not a terrain-driven reroute. The active 100 m terrain remains physical authority. Fine elevation, runoff, width and susceptibility are modelled and must not be described as surveyed, observed or authoritative 10 m evidence.",
        "",
        "## What changed physically",
        "",
        "- broad 10 m terrain is reconstructed from the active 100 m authority without hash-random microrelief;",
        "- registered route XY and graph contacts are preserved exactly; no terrain-driven A* rerouting is used;",
        "- active major waterways receive their route-ID-matched 3D source profiles by chainage; because those profiles are review-only while terrain is physical authority, any profile-above-terrain conflict creates a separately identified, one-sided constrained bed candidate while the source profile remains unchanged; minor waterways retain the D3 graph and receive an explicitly modelled local-surface bed;",
        "- unresolved Stillklinge support geometry remains unapproved and is never silently protected or promoted;",
        "- each protected registered route conditions the fine land surface within a frozen one-metre budget while retaining a separate bed elevation;",
        "- a 5 km support solve is cropped to the central 3 km published lens to reduce boundary artefacts;",
        "- monthly C1 precipitation, PET, snowfall and temperature drive low/base/high effective-runoff scenarios;",
        "- boundary contributing-area priors prevent settlement lenses from pretending that major rivers begin at the tile edge;",
        "- flow is accumulated with slope-weighted multiple-flow-direction routing; each protected route edge has one exact unit-weight downstream receiver; `d8_receiver_code` stores only the dominant MFD direction;",
        "- width is an uncalibrated low/base/high ensemble; generated drainage remains analytical potential only;",
        "- flood/wetness uses the registered protected network plus inherited flood/wetland evidence; window-local generated drainage remains a separate analytical-potential layer;",
        "- flood output is geomorphic susceptibility, never return-period extent or depth.",
        "",
        "## Storage",
        "",
        "`physical_context_10m.zarr` is the hot editable store. Each completed site also has an independently recoverable, checksummed Zstandard bundle, paired registered-2D-axis and 3D-bed-control GeoJSON, a review panel and a checkpoint. The SQLite database extends a copied Stage 6C.5 database; neither parent database nor parent Zarr was modified.",
    ]
    (output_dir / "README.md").write_text("\n".join(rows) + "\n", encoding="utf-8")


def run(
    output_dir: Path, scope: str, *, workers: int = 1,
    memory_budget_mb: int = 1024, reuse: bool = True, cancel_event: Any = None,
) -> dict[str, Any]:
    if type(workers) is not int or not 1 <= workers <= 64:
        raise ValueError("workers must be an integer between 1 and 64")
    if type(memory_budget_mb) is not int or memory_budget_mb < 512:
        raise ValueError("memory-budget-mb must be at least 512 for one physical site")
    started = time.perf_counter()
    stats = RuntimeStats()
    output_dir.mkdir(parents=True, exist_ok=True)
    for name in ("checkpoints", "tile_cache", "routes", "review_maps"):
        (output_dir / name).mkdir(exist_ok=True)
    extra_code = [Path(__file__), ENGINE_DIR / "stage6c5r_climate.py",
                  ENGINE_DIR / "stage6c5r_physical.py", ENGINE_DIR / "stage6c5r_hydrology.py"]
    guards = s6c5.capture_source_guards(s6c5.guarded_source_paths(
        (s6c5.PARENT_DB, SOURCE_STAGE6C5_DB), extra_code,
    ))
    parent_identity = {"parent_database": file_identity(s6c5.PARENT_DB),
                       "stage6c5_database": file_identity(SOURCE_STAGE6C5_DB)}
    print("CHECKPOINT_6C5R_SOURCE_LOCK_START", flush=True)
    with stats.measure("source_verification"):
        source_manifest, authority, source_hash_report = s6c.verify_sources()
    del source_hash_report
    with s6c5.sqlite_readonly(s6c5.PARENT_DB) as connection:
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("Stage 6C parent database integrity failure")
        candidates = s6c5.load_candidates(connection, authority)
    if len(candidates) != EXPECTED_ALL:
        raise RuntimeError("Stage 6C.5 candidate count changed")
    selected = scope_candidates(candidates, scope)
    sources = source_identity(authority)
    work_items = build_work(selected, sources)
    climate_token = climate_change_identity()
    # Without a strong change token, never trust an old computation merely
    # because the archive still has the same size or expected hash label.
    can_reuse = reuse and climate_token is not None
    runtime_id = semantic_identity(
        "stage6c5r-runtime-v1",
        inputs={"sources": source_manifest, "physical_sources": sources,
                "climate_change_token": climate_token,
                **parent_identity},
        parameters={"recipe": recipe_identity()},
        implementation=s6c5.runtime_implementation(extra_code),
    )
    s6c5.require_source_guards(guards)
    group = open_store(output_dir / "physical_context_10m.zarr", candidates, authority)
    with stats.measure("checkpoint_validation"):
        checkpoints = s6c5.checkpoint_plan(
            work_items,
            lambda work: load_checkpoint(
                output_dir / "checkpoints" / f"{work.candidate.site.settlement_id}.json",
                work, group, output_dir, runtime_identity=runtime_id,
            ), reuse=can_reuse,
        )
    pending = [(position, work) for position, work in enumerate(work_items)
               if checkpoints[position] is None]
    generated, reused = 0, len(work_items) - len(pending)
    stats.increment("sites_reused", reused)
    if pending:
        topology = s6c.ExactSurfaceIndex(
            Path(s6c.SOURCES["exact_surface_registry"]["path"]),
            Path(s6c.SOURCES["fragment_barony_assignment"]["path"]),
        )
        vectors = s6c.VectorStack("reference")
        major_profiles = ActiveMajorBedProfiles(
            Path(s6c.SOURCES["active_major_bed_profiles"]["path"])
        )
        profile_axis_metrics = major_profiles.validate_axes(zip(vectors.major_geoms, vectors.major_props))
        print("CHECKPOINT_6C5R_PROFILE_LOCK_PASS " + canonical_json(profile_axis_metrics), flush=True)
        rasters = s6c.RasterStack(authority)
        try:
            # Raster/archive handles and every public commit remain coordinator-owned.
            with C1MonthlyClimateReader() as climate_reader:
                with closing(physical_site_results(
                    pending, rasters, topology, vectors, major_profiles, climate_reader,
                    output_dir, workers=workers, memory_budget_mb=memory_budget_mb,
                    stats=stats, cancel_event=cancel_event,
                )) as results:
                    for position, work, checkpoint, arrays, private_dir in results:
                        require_unchanged_climate(climate_token)
                        s6c5.require_source_guards(guards)
                        group["site_complete"][work.candidate.index] = np.uint8(0)
                        install_private_site(output_dir, private_dir, checkpoint)
                        digest = write_store_slice(group, work.candidate.index, arrays)
                        if digest != checkpoint["array_digest"]:
                            raise RuntimeError("Zarr readback digest mismatch")
                        checkpoint["runtime_identity"] = runtime_id
                        checkpoint_path = output_dir / "checkpoints" / f"{work.candidate.site.settlement_id}.json"
                        atomic_json(checkpoint_path, checkpoint)
                        group["site_complete"][work.candidate.index] = np.uint8(1)
                        (output_dir / "failures" / f"{work.candidate.site.settlement_id}.json").unlink(missing_ok=True)
                        generated += 1
                        stats.increment("sites_generated")
                        checkpoints[position] = checkpoint
                        print(f"CHECKPOINT_6C5R_SITES generated={generated}/{len(pending)} reused={reused}", flush=True)
                        del arrays
        finally:
            rasters.close()
    require_unchanged_climate(climate_token)
    s6c5.require_source_guards(guards)
    s6c5.require_terrain_identity(authority)
    receipt_id = semantic_identity(
        "stage6c5r-final-outputs-v1", inputs={"runtime": runtime_id, "checkpoints": checkpoints},
        parameters={"scope": scope}, implementation={},
    )
    receipt_path = output_dir / "S6C5R_OUTPUT_RECEIPT.json"
    previous = load_receipt(receipt_path, receipt_id, output_dir) if can_reuse and not generated else None
    if previous is not None:
        result = {**previous, "generated": 0, "reused": reused,
                  "final_outputs_reused": True, "runtime_seconds": time.perf_counter() - started,
                  "runtime_statistics": stats.snapshot(),
                  "site_worker_limit": min(workers, memory_budget_mb // 512)}
        print(canonical_json(result), flush=True)
        return result
    output_database = build_database(output_dir, checkpoints, scope)
    runtime_s = time.perf_counter() - started
    write_reports(output_dir, checkpoints, scope, sources, runtime_s)
    route_gate_pass = all(
        bool(item["metrics"]["pilot_site_gate_pass"]) for item in checkpoints
    )
    result = {
        "status": (
            "BUILD_COMPLETE_REVIEW_ONLY"
            if route_gate_pass
            else "BUILD_COMPLETE_WITH_INCOMPLETE_ROUTE_QUARANTINE"
        ),
        "scope": scope,
        "completed_site_count": len(checkpoints),
        "generated": generated,
        "reused": reused,
        "pilot_route_gate_pass": route_gate_pass,
        "quarantined_route_count": sum(
            int(item["metrics"]["incomplete_quarantined_route_count"]) for item in checkpoints
        ),
        "runtime_seconds": runtime_s,
        "output_database": str(output_database),
        "output_directory": str(output_dir),
        "final_outputs_reused": False,
        "reuse_disabled_without_climate_change_token": reuse and climate_token is None,
        "runtime_statistics": stats.snapshot(),
        "site_worker_limit": min(workers, memory_budget_mb // 512),
    }
    require_unchanged_climate(climate_token)
    s6c5.require_source_guards(guards)
    s6c5.require_terrain_identity(authority)
    save_receipt(receipt_path, receipt_id, output_dir, [
        output_database, output_dir / "S6C5R_RUN_SUMMARY.json", output_dir / "README.md",
    ], result)
    print(canonical_json(result), flush=True)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--scope", choices=("FT0", "ALL"), default="FT0")
    parser.add_argument("--workers", type=int, default=1,
                        help="Independent physical sites; 1 retains the sequential reference")
    parser.add_argument("--memory-budget-mb", type=int, default=1024,
                        help="Estimated admitted site memory (512 MiB/site), not total process RAM")
    parser.add_argument("--no-reuse", action="store_true", help="Recompute sites and final outputs")
    parser.add_argument("--algorithm-mode", choices=("auto", "reference"), default="auto")
    args = parser.parse_args(argv)
    algorithm_policy.configure(args.algorithm_mode)
    if not 1 <= args.workers <= 64:
        parser.error("--workers must be between 1 and 64")
    if args.memory_budget_mb < 512:
        parser.error("--memory-budget-mb must be at least 512 for one physical site")
    run(args.output_dir.resolve(), args.scope, workers=args.workers,
        memory_budget_mb=args.memory_budget_mb, reuse=not args.no_reuse)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
