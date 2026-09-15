#!/usr/bin/env python3
"""Independent fail-closed validation for Stage 6C.5R physical 10 m lenses.

The validator deliberately reads the committed artefacts rather than trusting
the builder's run summary.  It validates the frozen FT0 gate (and, later, the
full 107-site scope), every completed Zarr slice, every independent Zstandard
frame, the extended SQLite database, route-pair diagnostics, physical water
balance and review-only/canon quarantine.  A deterministic two-site replay is
performed in a temporary directory by default and never writes to production.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict, deque
from dataclasses import asdict
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
import json
import math
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from typing import Any, Iterable, Mapping, Sequence


ENGINE_DIR = Path(__file__).resolve().parent
for dependency_directory in (ENGINE_DIR / "zarr_deps", ENGINE_DIR / "generator_deps"):
    value = str(dependency_directory)
    if value not in sys.path:
        sys.path.insert(0, value)

import numpy as np
import zarr
import zstandard as zstd

import build_stage6c_100m as s6c
import build_stage6c5_10m as s6c5
import build_stage6c5r_physical_10m as builder
from stage6c5_fast_terrain import ADAPTER_VERSION
import stage6c5r_physical as physical
import stage6c5r_routes as routes
from stage6c5r_climate import (
    DEFAULT_ARCHIVE_SHA256,
    DEFAULT_MEMBERS,
    METHOD_VERSION as CLIMATE_METHOD_VERSION,
    RUNOFF_SEMANTICS,
)
from ten_m_tile_engine.cache import read_recovery_manifest


EXPECTED_METHOD = "STAGE6C5R_PROCESS_CONSTRAINED_10M_PHYSICAL_CONTEXT_V1_3"
EXPECTED_KERNEL = "S6C5R_PHYSICAL_KERNEL_1.1.2"
EXPECTED_ROUTER = "S6C5R_MONOTONIC_CORRIDOR_ROUTER_1.0.0"
EXPECTED_CLIMATE = "S6C5R_BOUNDED_C1_CLIMATE_ADAPTER_1.0.0"
EXPECTED_STATUS = "WORKING_PROPOSAL_REVIEW_ONLY_NOT_CANON"
EXPECTED_FT0_SHA256 = "8721c4a66b32c14c0478f9d008afb3e421a1642b425b8fc7786b357c2e6f2612"
EXPECTED_FT0 = 19
EXPECTED_ALL = 107
EXPECTED_FT0_2D = 12
EXPECTED_FT0_3D_CONTEXT = 7
ROWS = COLS = 300
PARENT_FACTOR = 10
PARENT_TOLERANCE_M = 0.0051
CONDITIONING_LIMIT_M = 1.0
MASS_BALANCE_TOLERANCE = 0.01
FLOAT_TOLERANCE = 1e-5
DERIVED_FLOAT32_DELTA_TOLERANCE_M = 5e-4


# This is intentionally duplicated from the production schema.  A production
# array added, removed or reshaped without an explicit validator update fails.
ARRAY_SPECS: dict[str, tuple[tuple[int, ...], str]] = {
    "base_broad_elevation_m": ((ROWS, COLS), "f4"),
    "conditioned_elevation_m": ((ROWS, COLS), "f4"),
    "terrain_conditioning_delta_m": ((ROWS, COLS), "f4"),
    "routing_elevation_m": ((ROWS, COLS), "f4"),
    "routing_fill_delta_m": ((ROWS, COLS), "f4"),
    "local_slope_m_per_m": ((ROWS, COLS), "f4"),
    "monthly_effective_runoff_low_mm": ((12, ROWS, COLS), "f4"),
    "monthly_effective_runoff_base_mm": ((12, ROWS, COLS), "f4"),
    "monthly_effective_runoff_high_mm": ((12, ROWS, COLS), "f4"),
    "monthly_accumulated_runoff_base_mm_km2": ((12, ROWS, COLS), "f4"),
    "accumulated_area_km2": ((ROWS, COLS), "f4"),
    "annual_accumulated_runoff_low_mm_km2": ((ROWS, COLS), "f4"),
    "annual_accumulated_runoff_base_mm_km2": ((ROWS, COLS), "f4"),
    "annual_accumulated_runoff_high_mm_km2": ((ROWS, COLS), "f4"),
    "inherited_current_channel_class": ((ROWS, COLS), "u1"),
    "protected_channel_class": ((ROWS, COLS), "u1"),
    "drainage_potential_or_protected_class": ((ROWS, COLS), "u1"),
    "channel_width_low_m": ((ROWS, COLS), "f4"),
    "channel_width_base_m": ((ROWS, COLS), "f4"),
    "channel_width_high_m": ((ROWS, COLS), "f4"),
    "d8_receiver_code": ((ROWS, COLS), "i1"),
    "nearest_channel_height_proxy_m": ((ROWS, COLS), "f4"),
    "flood_susceptibility": ((ROWS, COLS), "f4"),
    "wetness_potential": ((ROWS, COLS), "f4"),
    "exact_barony_id": ((ROWS, COLS), "i4"),
    "exact_surface": ((ROWS, COLS), "u1"),
    "land_mask": ((ROWS, COLS), "u1"),
    "sea_mask_parent_projected": ((ROWS, COLS), "u1"),
    "wetland_mask_parent_projected": ((ROWS, COLS), "u1"),
    "serenakrone_water_parent_projected": ((ROWS, COLS), "u1"),
    "protected_flood_evidence_parent_projected": ((ROWS, COLS), "f4"),
    "registered_sink_mask": ((ROWS, COLS), "u1"),
}

D8: tuple[tuple[int, int], ...] = (
    (-1, 0), (-1, 1), (0, 1), (1, 1),
    (1, 0), (1, -1), (0, -1), (-1, -1),
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def canonical_json(value: Any) -> str:
    def fallback(item: Any) -> Any:
        if isinstance(item, Path):
            return str(item)
        if isinstance(item, np.generic):
            return item.item()
        if isinstance(item, Mapping):
            return dict(item)
        raise TypeError(type(item).__name__)
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=fallback
    )


def digest_json(value: Any) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def arrays_digest(arrays: Mapping[str, np.ndarray]) -> str:
    digest = sha256()
    for name in sorted(ARRAY_SPECS):
        value = np.ascontiguousarray(arrays[name])
        digest.update(canonical_json([name, value.dtype.str, list(value.shape)]).encode("utf-8"))
        digest.update(value.tobytes(order="C"))
    return digest.hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    payload = (canonical_json(value) + "\n").encode("utf-8")
    with temporary.open("wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def readonly(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


class Checks:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    def require(self, name: str, condition: bool, *, actual: Any = None, detail: str = "") -> None:
        self.rows.append({
            "name": name,
            "status": "PASS" if condition else "FAIL",
            "actual": bool(condition) if actual is None else actual,
            "expected": True,
            "detail": detail,
        })

    def equal(self, name: str, actual: Any, expected: Any, *, detail: str = "") -> None:
        self.rows.append({
            "name": name,
            "status": "PASS" if actual == expected else "FAIL",
            "actual": actual,
            "expected": expected,
            "detail": detail,
        })


def expected_source_identity(authority: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "terrain_authority": {
            "authority_id": authority["authority_id"],
            "generation": authority["generation"],
            "root_hash": authority["root_hash"],
            "physical_source_resolution_m": 100,
        },
        "hydrology": {
            role: {"sha256": s6c.SOURCES[role]["sha256"], "status": s6c.SOURCES[role].get("status")}
            for role in (
                "active_major", "d3_feeder_raw", "d3_feeder_enriched",
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


def expected_recipe_identity() -> dict[str, Any]:
    return {
        "method": EXPECTED_METHOD,
        "terrain": {**asdict(builder.TERRAIN_RECIPE), "fast_adapter": ADAPTER_VERSION},
        "physical": physical.PhysicalRecipe().identity(),
        "implementations": {
            "climate_adapter": EXPECTED_CLIMATE,
            "route_reconstructor": EXPECTED_ROUTER,
        },
        "runoff_scenarios": builder.RUNOFF_SCENARIOS,
        "runoff_scenario_envelope": (
            "POINTWISE_MINIMUM_OF_THREE_PARAMETER_RUNS / BASE_PARAMETER_RUN / "
            "POINTWISE_MAXIMUM_OF_THREE_PARAMETER_RUNS"
        ),
        "window_parent_cells": 30,
        "fine_cell_m": 10,
        "canon_status": EXPECTED_STATUS,
    }


def window_origin(candidate: s6c5.Candidate) -> tuple[int, int]:
    centre_row = int(math.floor(candidate.site.y * 10.0))
    centre_col = int(math.floor(candidate.site.x * 10.0))
    return (
        min(max(centre_row - 15, 0), 18_600 - 30),
        min(max(centre_col - 15, 0), 22_000 - 30),
    )


def expected_semantic_key(
    candidate: s6c5.Candidate,
    sources: Mapping[str, Any],
) -> str:
    row0, col0 = window_origin(candidate)
    return digest_json({
        "record_type": "diadem.stage6c5r.site-physical-context.v1",
        "settlement_id": candidate.site.settlement_id,
        "official_coordinate_km": [candidate.site.x, candidate.site.y],
        "official_coordinate_modified": False,
        "parent_stage6c5_semantic_key": candidate.semantic_key,
        "window_parent": [row0, col0, 30, 30],
        "sources": sources,
        "recipe": expected_recipe_identity(),
    })


def receiver_from_direction(direction: np.ndarray) -> np.ndarray:
    values = np.asarray(direction, dtype=np.int16)
    rows, cols = values.shape
    receiver = np.full(rows * cols, -1, dtype=np.int64)
    rr, cc = np.indices((rows, cols), dtype=np.int64)
    for code, (dr, dc) in enumerate(D8):
        selected = values == code
        target_row = rr[selected] + dr
        target_col = cc[selected] + dc
        in_bounds = (
            (target_row >= 0) & (target_row < rows)
            & (target_col >= 0) & (target_col < cols)
        )
        source = (rr[selected] * cols + cc[selected])[in_bounds]
        receiver[source] = target_row[in_bounds] * cols + target_col[in_bounds]
    return receiver


def receiver_graph_is_acyclic(receiver: np.ndarray) -> bool:
    receiver = np.asarray(receiver, dtype=np.int64).ravel()
    indegree = np.zeros(receiver.size, dtype=np.int32)
    targets = receiver[receiver >= 0]
    np.add.at(indegree, targets, 1)
    queue = deque(np.flatnonzero(indegree == 0).tolist())
    visited = 0
    while queue:
        node = queue.popleft()
        visited += 1
        target = int(receiver[node])
        if target >= 0:
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)
    return visited == receiver.size


def independent_accumulated_runoff(
    routing_elevation: np.ndarray,
    receiver: np.ndarray,
    monthly_local_runoff: np.ndarray,
    boundary_seeds: Mapping[int, float],
) -> np.ndarray:
    """Independent topological accumulation used for low/high validation."""

    flat_local = np.asarray(monthly_local_runoff, dtype=np.float64).reshape(12, -1)
    load = flat_local * 0.0001
    for index, area in boundary_seeds.items():
        load[:, int(index)] += flat_local[:, int(index)] * float(area)
    order = np.argsort(-np.asarray(routing_elevation, dtype=np.float64).ravel(), kind="stable")
    for source in order.tolist():
        target = int(receiver[source])
        if target >= 0:
            load[:, target] += load[:, source]
    return load


def cells_from_coordinates(
    coordinates: Sequence[Sequence[float]], row0: int, col0: int
) -> tuple[tuple[int, int], ...]:
    y0, x0 = row0 * 0.1, col0 * 0.1
    result: list[tuple[int, int]] = []
    for coordinate in coordinates:
        x, y = float(coordinate[0]), float(coordinate[1])
        row = int(round((y - y0) / 0.01 - 0.5))
        col = int(round((x - x0) / 0.01 - 0.5))
        cell = (row, col)
        if not (0 <= row < ROWS and 0 <= col < COLS):
            raise ValueError(f"Route coordinate maps outside lens: {coordinate}")
        if not result or result[-1] != cell:
            result.append(cell)
    return tuple(result)


def paths_are_d8(paths: Iterable[Sequence[tuple[int, int]]]) -> bool:
    for path in paths:
        if len(path) < 2:
            return False
        for left, right in zip(path, path[1:]):
            dr, dc = abs(left[0] - right[0]), abs(left[1] - right[1])
            if max(dr, dc) != 1:
                return False
    return True


def validate_route_file(
    path: Path,
    checkpoint: Mapping[str, Any],
    row0: int,
    col0: int,
    protected_class: np.ndarray,
    conditioned_elevation: np.ndarray,
    routing_elevation: np.ndarray,
    receiver: np.ndarray,
) -> tuple[list[physical.ChannelConstraint], list[str], dict[str, Any]]:
    failures: list[str] = []
    constraints: list[physical.ChannelConstraint] = []
    metrics = {"parts": 0, "unresolved": 0, "maximum_divergence_m": 0.0}
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("type") != "FeatureCollection":
        failures.append("not a FeatureCollection")
    if document.get("canon_status") != EXPECTED_STATUS:
        failures.append("route status is not review-only")
    grouped: dict[str, dict[str, Mapping[str, Any]]] = defaultdict(dict)
    for feature in document.get("features", []):
        properties = feature.get("properties") or {}
        part_id = str(properties.get("part_id") or "")
        role = str(properties.get("geometry_role") or "")
        if not part_id or role in grouped[part_id]:
            failures.append("missing or duplicate route pair identity")
            continue
        geometry = feature.get("geometry") or {}
        if geometry.get("type") != "LineString" or len(geometry.get("coordinates") or []) < 2:
            failures.append(f"{part_id}: invalid LineString")
            continue
        grouped[part_id][role] = feature
    checkpoint_parts = {str(item["part_id"]): item for item in checkpoint.get("routes", [])}
    if set(grouped) != set(checkpoint_parts):
        failures.append("GeoJSON/checkpoint route part sets differ")
    class_codes = {"tier1": 4, "tier2": 5, "major": 6, "titan": 7, "special": 8}
    for part_id, pair in sorted(grouped.items()):
        expected_roles = {
            "INHERITED_V4_2_RASTERISED_10M_CORRIDOR_AXIS",
            "S6C5R_TERRAIN_ROUTED_CANDIDATE",
        }
        if set(pair) != expected_roles:
            failures.append(f"{part_id}: inherited/candidate pair incomplete")
            continue
        inherited_feature = pair["INHERITED_V4_2_RASTERISED_10M_CORRIDOR_AXIS"]
        candidate_feature = pair["S6C5R_TERRAIN_ROUTED_CANDIDATE"]
        properties = candidate_feature["properties"]
        if (
            properties.get("coordinate_reference") != "DIADEM_LOCAL_KM_X_EAST_Y_SOUTH"
            or inherited_feature["properties"].get("coordinate_reference")
            != "DIADEM_LOCAL_KM_X_EAST_Y_SOUTH"
        ):
            failures.append(f"{part_id}: coordinate reference missing or changed")
        accepted = (
            properties.get("route_status") == "PASS_PHYSICALLY_ADMISSIBLE_REVIEW_CANDIDATE"
            and properties.get("physical_route_accepted") is True
            and properties.get("route_failure_reason") is None
        )
        if not accepted:
            failures.append(
                f"{part_id}: quarantined physical route: "
                f"{properties.get('route_failure_reason') or properties.get('route_status')}"
            )
        if (
            properties.get("route_status") != "PASS_PHYSICALLY_ADMISSIBLE_REVIEW_CANDIDATE"
            or properties.get("physical_route_accepted") is not True
            or properties.get("route_failure_reason") is not None
        ):
            accepted = False
        edge_fraction = properties.get("interior_corridor_edge_fraction")
        if edge_fraction is None or float(edge_fraction) > 0.02 + 1e-12:
            failures.append(f"{part_id}: route rides the interior corridor edge")
        inherited = cells_from_coordinates(inherited_feature["geometry"]["coordinates"], row0, col0)
        candidate = cells_from_coordinates(candidate_feature["geometry"]["coordinates"], row0, col0)
        if not paths_are_d8((inherited, candidate)):
            failures.append(f"{part_id}: route path is not contiguous D8")
        if candidate[0] != inherited[0] or candidate[-1] != inherited[-1]:
            failures.append(f"{part_id}: frozen endpoints changed")
        boundary_oriented = list(candidate)
        if float(conditioned_elevation[boundary_oriented[0]]) < float(conditioned_elevation[boundary_oriented[-1]]):
            boundary_oriented.reverse()
        upstream = boundary_oriented[0]
        downstream = boundary_oriented[-1]
        upstream_on_boundary = (
            upstream[0] <= 1 or upstream[1] <= 1
            or upstream[0] >= ROWS - 2 or upstream[1] >= COLS - 2
        )
        if bool(properties.get("boundary_inflow")) != upstream_on_boundary:
            failures.append(f"{part_id}: boundary inflow is not upstream-boundary-only")
        downstream_on_boundary = (
            downstream[0] <= 1 or downstream[1] <= 1
            or downstream[0] >= ROWS - 2 or downstream[1] >= COLS - 2
        )
        if bool(properties.get("boundary_outflow")) != downstream_on_boundary:
            failures.append(f"{part_id}: boundary outflow flag differs from downstream endpoint")
        area_prior = float(properties.get("boundary_area_prior_km2") or 0.0)
        if (upstream_on_boundary and area_prior <= 0.0) or (not upstream_on_boundary and area_prior != 0.0):
            failures.append(f"{part_id}: boundary area prior does not match inlet semantics")
        route_class = str(properties.get("route_class"))
        try:
            corridor = routes.corridor_mask_from_cells(
                (ROWS, COLS), inherited, route_class, cell_size_m=10.0
            )
            if any(not corridor[cell] for cell in candidate):
                failures.append(f"{part_id}: candidate escaped class corridor")
            recomputed = routes.route_diagnostics(candidate, inherited, corridor, cell_size_m=10.0)
            stored = properties.get("candidate_route_metrics") or {}
            required = (
                "candidate_mean_divergence_m", "candidate_p95_divergence_m",
                "candidate_max_divergence_m", "symmetric_hausdorff_m",
                "corridor_edge_cell_count", "window_boundary_crossing_count",
            )
            for key in required:
                actual, expected = recomputed.get(key), stored.get(key)
                if isinstance(actual, float):
                    if expected is None or not math.isclose(actual, float(expected), rel_tol=1e-7, abs_tol=1e-6):
                        failures.append(f"{part_id}: route diagnostic {key} differs")
                elif actual != expected:
                    failures.append(f"{part_id}: route diagnostic {key} differs")
            radius = routes.corridor_radius_m(route_class)
            if float(stored.get("corridor_radius_m", -1.0)) != radius:
                failures.append(f"{part_id}: corridor radius differs from class rule")
            if float(stored.get("candidate_max_divergence_m", math.inf)) > radius + 15.0:
                failures.append(f"{part_id}: divergence exceeds corridor allowance")
            if bool(stored.get("inherited_axis_used_in_objective", True)):
                failures.append(f"{part_id}: inherited axis used as a cost reward")
            allowance = properties.get("preconditioning_search_uphill_allowance_m")
            if allowance not in {0, 0.0, 1, 1.0}:
                failures.append(f"{part_id}: unrecognised preconditioning search allowance")
            elif float(stored.get("maximum_uphill_step_m", math.inf)) > float(allowance) + 1e-9:
                failures.append(f"{part_id}: preconditioning route exceeds its frozen allowance")
            lineage = properties.get("candidate_route_lineage") or {}
            route_hash = sha256(np.asarray(candidate, dtype=np.int32).tobytes(order="C")).hexdigest()
            if lineage.get("route_cell_hash") != route_hash:
                failures.append(f"{part_id}: route cell hash differs")
            if lineage.get("method") != EXPECTED_ROUTER or bool(lineage.get("inherited_axis_used_in_objective", True)):
                failures.append(f"{part_id}: route lineage differs")
            metrics["maximum_divergence_m"] = max(
                float(metrics["maximum_divergence_m"]), float(stored.get("candidate_max_divergence_m", 0.0))
            )
        except Exception as error:
            failures.append(f"{part_id}: corridor diagnostics failed: {type(error).__name__}: {error}")
        code = class_codes.get(route_class)
        if accepted:
            if code is None or any(int(protected_class[cell]) < code for cell in candidate):
                failures.append(f"{part_id}: accepted route is not retained in protected class grid")
            oriented = list(candidate)
            if float(routing_elevation[oriented[0]]) < float(routing_elevation[oriented[-1]]):
                oriented.reverse()
            for source, target in zip(oriented, oriented[1:]):
                source_index = source[0] * COLS + source[1]
                target_index = target[0] * COLS + target[1]
                if int(receiver[source_index]) != target_index:
                    failures.append(f"{part_id}: final receiver graph does not retain accepted path")
                    break
        unresolved = bool(properties.get("source_label_must_not_be_promoted"))
        if unresolved:
            metrics["unresolved"] += 1
            if properties.get("persistence") != "UNRESOLVED_AFTER_STILLKLINGE_SUPERSESSION_DO_NOT_PROMOTE":
                failures.append(f"{part_id}: unresolved Stillklinge source label was promoted")
        if accepted:
            constraints.append(physical.ChannelConstraint(
                feature_id=part_id,
                route_class=route_class,
                persistence=str(properties.get("persistence")),
                path_cells=candidate,
                contributing_area_prior_km2=float(properties.get("boundary_area_prior_km2") or 0.0),
                boundary_inflow=bool(properties.get("boundary_inflow")),
                source_kind="VALIDATION_RECONSTRUCTION_FROM_COMMITTED_CANDIDATE_ROUTE",
            ))
        metrics["parts"] += 1
    if int(metrics["parts"]) != int(checkpoint.get("metrics", {}).get("route_record_count", -1)):
        failures.append("route part count differs from checkpoint")
    if int(metrics["unresolved"]) != int(checkpoint.get("metrics", {}).get("stillklinge_unresolved_feature_count", -1)):
        failures.append("unresolved Stillklinge count differs from checkpoint")
    return constraints, failures, metrics


def verify_bundle(
    bundle: Path,
    expected_bundle_id: str,
    expected_arrays: Mapping[str, np.ndarray],
    checkpoint: Mapping[str, Any],
) -> tuple[list[str], int, int]:
    failures: list[str] = []
    frame_count = frame_bytes = 0
    try:
        manifest = read_recovery_manifest(bundle)
    except Exception as error:
        return [f"bundle manifest: {type(error).__name__}: {error}"], 0, 0
    if manifest.get("bundle_id") != expected_bundle_id:
        failures.append("bundle ID differs from checkpoint")
    if not manifest.get("self_contained") or not manifest.get("authoritative_master"):
        failures.append("bundle is not a self-contained recovery master")
    packets = sorted(manifest.get("packets", []), key=lambda item: int(item.get("sequence", -1)))
    if [int(packet.get("sequence", -1)) for packet in packets] != list(range(len(packets))):
        failures.append("bundle packet order is not contiguous")
    recovered: dict[str, np.ndarray] = {}
    metadata: dict[str, Any] | None = None
    decompressor = zstd.ZstdDecompressor()
    for packet in packets:
        try:
            if packet.get("kind") != "full":
                raise ValueError("release bundle contains REF/PATCH rather than FULL frame")
            frame_path = bundle / str(packet["frame_path"])
            frame = frame_path.read_bytes()
            if len(frame) != int(packet["frame_size"]):
                raise ValueError("frame size mismatch")
            if sha256(frame).hexdigest() != packet["frame_sha256"]:
                raise ValueError("frame checksum mismatch")
            raw = decompressor.decompress(frame, max_output_size=int(packet["raw_size"]))
            if len(raw) != int(packet["raw_size"]):
                raise ValueError("raw size mismatch")
            if sha256(raw).hexdigest() != packet["target_hash"]:
                raise ValueError("raw target hash mismatch")
            frame_count += 1
            frame_bytes += len(frame)
            artifact = str(packet.get("artifact_path") or "")
            if artifact.endswith("/metadata.json"):
                metadata = json.loads(raw)
            elif "/arrays/" in artifact and artifact.endswith(".npy"):
                name = artifact.rsplit("/", 1)[-1][:-4]
                recovered[name] = np.load(BytesIO(raw), allow_pickle=False)
            else:
                raise ValueError(f"unknown bundle artifact {artifact}")
        except Exception as error:
            failures.append(f"packet {packet.get('sequence')}: {type(error).__name__}: {error}")
    if set(recovered) != set(ARRAY_SPECS):
        failures.append("bundle array set differs from frozen production schema")
    if metadata is None:
        failures.append("bundle metadata missing")
    else:
        for key, expected in (
            ("method", EXPECTED_METHOD),
            ("canon_status", EXPECTED_STATUS),
            ("semantic_key", checkpoint.get("semantic_key")),
            ("array_digest", checkpoint.get("array_digest")),
            ("generated_channels_promoted", False),
            ("official_coordinate_modified", False),
            ("not_surveyed_10m", True),
        ):
            if metadata.get(key) != expected:
                failures.append(f"bundle metadata {key} differs")
    if set(recovered) == set(ARRAY_SPECS):
        if arrays_digest(recovered) != checkpoint.get("array_digest"):
            failures.append("bundle array digest differs from checkpoint")
        for name in ARRAY_SPECS:
            if not np.array_equal(recovered[name], expected_arrays[name], equal_nan=True):
                failures.append(f"bundle/Zarr array mismatch: {name}")
                break
    return failures, frame_count, frame_bytes


def physical_site_checks(
    arrays: Mapping[str, np.ndarray],
    parent: np.ndarray,
    constraints: Sequence[physical.ChannelConstraint],
) -> tuple[list[str], dict[str, float]]:
    failures: list[str] = []
    base = arrays["base_broad_elevation_m"].astype(np.float64)
    conditioned = arrays["conditioned_elevation_m"].astype(np.float64)
    delta = arrays["terrain_conditioning_delta_m"].astype(np.float64)
    routing = arrays["routing_elevation_m"].astype(np.float64)
    routing_delta = arrays["routing_fill_delta_m"].astype(np.float64)
    parent64 = np.asarray(parent, dtype=np.float64)
    base_means = physical.parent_block_means(base)
    conditioned_means = physical.parent_block_means(conditioned)
    base_parent_error = float(np.max(np.abs(base_means - parent64)))
    conditioned_parent_error = float(np.max(np.abs(conditioned_means - parent64)))
    conditioning_max = float(np.max(np.abs(delta)))
    if base_parent_error > PARENT_TOLERANCE_M:
        failures.append(f"base parent recovery {base_parent_error:.8f} m")
    if conditioned_parent_error > PARENT_TOLERANCE_M:
        failures.append(f"conditioned parent recovery {conditioned_parent_error:.8f} m")
    if conditioning_max > CONDITIONING_LIMIT_M + 1e-6:
        failures.append(f"conditioning exceeds one metre: {conditioning_max:.8f}")
    if not np.allclose(
        conditioned - base, delta, rtol=0.0,
        atol=DERIVED_FLOAT32_DELTA_TOLERANCE_M, equal_nan=True,
    ):
        failures.append("conditioning delta does not reconstruct conditioned terrain")
    if not np.allclose(
        routing - conditioned, routing_delta, rtol=0.0,
        atol=DERIVED_FLOAT32_DELTA_TOLERANCE_M, equal_nan=True,
    ):
        failures.append("routing fill delta does not reconstruct routing surface")
    direction = arrays["d8_receiver_code"]
    if np.any((direction < -1) | (direction > 7)):
        failures.append("D8 receiver codes outside -1..7")
    receiver = receiver_from_direction(direction)
    if int(np.count_nonzero(direction >= 0)) != int(np.count_nonzero(receiver >= 0)):
        failures.append("D8 receiver code points outside the bounded lens")
    source = np.flatnonzero(receiver >= 0)
    target = receiver[source]
    flat = routing.ravel()
    minimum_drop = float(np.min(flat[source] - flat[target])) if source.size else math.inf
    if minimum_drop <= 0.0:
        failures.append(f"receiver graph contains non-downhill edge: {minimum_drop:.9g} m")
    if not receiver_graph_is_acyclic(receiver):
        failures.append("receiver graph contains a cycle")
    local_low = arrays["monthly_effective_runoff_low_mm"]
    local_base = arrays["monthly_effective_runoff_base_mm"]
    local_high = arrays["monthly_effective_runoff_high_mm"]
    if np.any(local_low > local_base + FLOAT_TOLERANCE) or np.any(local_base > local_high + FLOAT_TOLERANCE):
        failures.append("monthly low/base/high runoff order violated")
    load = arrays["monthly_accumulated_runoff_base_mm_km2"].astype(np.float64)
    annual_base = arrays["annual_accumulated_runoff_base_mm_km2"].astype(np.float64)
    if not np.allclose(load.sum(axis=0), annual_base, rtol=1e-5, atol=2e-3):
        failures.append("annual base accumulated runoff differs from monthly sum")
    annual_low = arrays["annual_accumulated_runoff_low_mm_km2"]
    annual_high = arrays["annual_accumulated_runoff_high_mm_km2"]
    if np.any(annual_low > annual_base + 2e-3) or np.any(annual_base > annual_high + 2e-3):
        failures.append("annual low/base/high accumulated runoff order violated")
    width_low = arrays["channel_width_low_m"]
    width_base = arrays["channel_width_base_m"]
    width_high = arrays["channel_width_high_m"]
    if np.any(width_low > width_base + 1e-5) or np.any(width_base > width_high + 1e-5):
        failures.append("channel low/base/high width order violated")
    protected = arrays["protected_channel_class"]
    drainage = arrays["drainage_potential_or_protected_class"]
    if np.any((protected > 0) & ((protected < 4) | (protected > 8))):
        failures.append("protected class grid contains generated class codes")
    if np.any((drainage >= 4) & (drainage != protected)):
        failures.append("protected route class changed in drainage potential grid")
    if np.any(width_base[protected == 0] != 0.0):
        failures.append("generated drainage received a current-network width")
    if np.any((protected > 0) & (width_base <= 0.0)):
        failures.append("protected channel has no width proxy")
    seeds = physical.boundary_inflow_seeds(constraints, conditioned)
    cell_area_km2 = 0.0001
    expected = local_base.reshape(12, -1).astype(np.float64).sum(axis=1) * cell_area_km2
    flat_monthly = local_base.reshape(12, -1).astype(np.float64)
    for index, area in seeds.items():
        expected += flat_monthly[:, int(index)] * float(area)
    sinks = receiver < 0
    actual = load.reshape(12, -1)[:, sinks].sum(axis=1)
    relative = np.abs(actual - expected) / np.maximum(np.abs(expected), 1e-9)
    mass_error = float(np.max(relative))
    if mass_error > MASS_BALANCE_TOLERANCE:
        failures.append(f"monthly water mass balance error {mass_error:.8g}")
    scenario_mass_errors = [mass_error]
    for scenario_name, local_name, annual_name in (
        ("low", "monthly_effective_runoff_low_mm", "annual_accumulated_runoff_low_mm_km2"),
        ("high", "monthly_effective_runoff_high_mm", "annual_accumulated_runoff_high_mm_km2"),
    ):
        local = arrays[local_name]
        scenario_load = independent_accumulated_runoff(routing, receiver, local, seeds)
        if not np.allclose(
            scenario_load.sum(axis=0).reshape(ROWS, COLS),
            arrays[annual_name], rtol=1e-5, atol=2e-3,
        ):
            failures.append(f"{scenario_name} accumulated runoff differs from independent replay")
        expected_scenario = local.reshape(12, -1).astype(np.float64).sum(axis=1) * cell_area_km2
        flat_scenario = local.reshape(12, -1).astype(np.float64)
        for index, area in seeds.items():
            expected_scenario += flat_scenario[:, int(index)] * float(area)
        actual_scenario = scenario_load[:, sinks].sum(axis=1)
        relative_scenario = (
            np.abs(actual_scenario - expected_scenario)
            / np.maximum(np.abs(expected_scenario), 1e-9)
        )
        scenario_error = float(np.max(relative_scenario))
        scenario_mass_errors.append(scenario_error)
        if scenario_error > MASS_BALANCE_TOLERANCE:
            failures.append(f"{scenario_name} monthly water mass balance error {scenario_error:.8g}")
    return failures, {
        "base_parent_error_m": base_parent_error,
        "conditioned_parent_error_m": conditioned_parent_error,
        "conditioning_max_abs_m": conditioning_max,
        "minimum_receiver_drop_m": minimum_drop,
        "monthly_mass_balance_max_relative_error": max(scenario_mass_errors),
    }


def deterministic_replay(
    candidates: Sequence[s6c5.Candidate],
    stored_checkpoints: Mapping[str, Mapping[str, Any]],
    authority: Mapping[str, Any],
    sources: Mapping[str, Any],
) -> tuple[list[str], dict[str, Any]]:
    selected: list[s6c5.Candidate] = []
    for disposition in (
        "COMPLETE_2D_REFINEMENT",
        "SURFACE_OR_INTERFACE_CONTEXT_ONLY_3D_DEFERRED",
    ):
        chosen = next(
            item for item in sorted(candidates, key=lambda value: value.site.settlement_id)
            if item.site.functional_tier == "FT0_HAUS_PRINCIPAL_SITE"
            and item.disposition == disposition
        )
        selected.append(chosen)
    failures: list[str] = []
    results: list[dict[str, Any]] = []
    topology = s6c.ExactSurfaceIndex(
        Path(s6c.SOURCES["exact_surface_registry"]["path"]),
        Path(s6c.SOURCES["fragment_barony_assignment"]["path"]),
    )
    vectors = s6c.VectorStack("reference")
    rasters = s6c.RasterStack(authority)
    try:
        from stage6c5r_climate import C1MonthlyClimateReader
        with tempfile.TemporaryDirectory(prefix="diadem-s6c5r-replay-") as temporary_name:
            temporary = Path(temporary_name)
            for name in ("tile_cache", "routes", "review_maps"):
                (temporary / name).mkdir(parents=True, exist_ok=True)
            with C1MonthlyClimateReader() as climate_reader:
                for candidate in selected:
                    row0, col0 = window_origin(candidate)
                    work = builder.SiteWork(
                        candidate, row0, col0, expected_semantic_key(candidate, sources)
                    )
                    replay_checkpoint, replay_arrays = builder.site_result(
                        work, rasters, topology, vectors, climate_reader, temporary,
                        verify_reference=False,
                    )
                    stored = stored_checkpoints[candidate.site.settlement_id]
                    replay_digest = arrays_digest(replay_arrays)
                    if replay_digest != stored["array_digest"]:
                        failures.append(f"{candidate.site.settlement_id}: replay array digest differs")
                    if replay_checkpoint.get("routes") != stored.get("routes"):
                        failures.append(f"{candidate.site.settlement_id}: replay route record differs")
                    results.append({
                        "settlement_id": candidate.site.settlement_id,
                        "disposition": candidate.disposition,
                        "stored_array_digest": stored["array_digest"],
                        "replay_array_digest": replay_digest,
                        "match": replay_digest == stored["array_digest"],
                    })
    except Exception as error:
        failures.append(f"replay execution: {type(error).__name__}: {error}")
    finally:
        rasters.close()
    return failures, {"site_count": len(selected), "sites": results}


def parent_table_row_counts(connection: sqlite3.Connection) -> dict[str, int]:
    tables = [
        str(row[0]) for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
        if not str(row[0]).startswith("stage6c5r_")
    ]
    return {table: int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]) for table in tables}


def finalise_report(
    checks: Checks,
    output_dir: Path,
    scope: str,
    metrics: Mapping[str, Any],
    replay: Mapping[str, Any] | None,
) -> dict[str, Any]:
    counts = Counter(row["status"] for row in checks.rows)
    status = "PASS" if counts["FAIL"] == 0 else "FAIL"
    report = {
        "schema": "diadem.stage6c5r-independent-validation.v1",
        "validated_utc": utc_now(),
        "method": EXPECTED_METHOD,
        "scope": scope,
        "status": status,
        "canon_status": EXPECTED_STATUS,
        "counts": dict(counts),
        "checks": checks.rows,
        "metrics": dict(metrics),
        "deterministic_replay": replay,
    }
    report["validation_identity_sha256"] = digest_json(report)
    atomic_json(output_dir / "INDEPENDENT_VALIDATION.json", report)
    lines = [
        "# Stage 6C.5R independent validation",
        "",
        "**WORKING PROPOSAL — REVIEW ONLY — NOT CANON**",
        "",
        f"Status: **{status}**  ",
        f"Scope: **{scope}**  ",
        f"Checks: **{counts['PASS']} PASS / {counts['FAIL']} FAIL**",
        "",
        "| Check | Status | Actual | Expected |",
        "|---|---:|---|---|",
    ]
    for row in checks.rows:
        actual = canonical_json(row["actual"]).replace("|", "\\|")
        expected = canonical_json(row["expected"]).replace("|", "\\|")
        lines.append(f"| {row['name']} | {row['status']} | `{actual}` | `{expected}` |")
    lines.extend(["", "This report is fail-closed: any failed critical check prevents promotion or continuation.", ""])
    (output_dir / "INDEPENDENT_VALIDATION.md").write_text("\n".join(lines), encoding="utf-8")
    return report


def validate(output_dir: Path, requested_scope: str = "AUTO", *, rerun: bool = True) -> dict[str, Any]:
    checks = Checks()
    output_db = output_dir / builder.OUTPUT_DB_NAME
    store_path = output_dir / "physical_context_10m.zarr"
    summary_path = output_dir / "S6C5R_RUN_SUMMARY.json"
    for name, path, kind in (
        ("output_sqlite_exists", output_db, "file"),
        ("physical_zarr_exists", store_path, "dir"),
        ("run_summary_exists", summary_path, "file"),
    ):
        checks.require(name, path.is_file() if kind == "file" else path.is_dir(), actual=str(path))
    if not output_db.is_file() or not store_path.is_dir() or not summary_path.is_file():
        return finalise_report(checks, output_dir, requested_scope, {}, None)

    checks.equal("builder_method_frozen", builder.METHOD, EXPECTED_METHOD)
    checks.equal("physical_kernel_frozen", physical.METHOD_VERSION, EXPECTED_KERNEL)
    checks.equal("corridor_router_frozen", routes.METHOD_VERSION, EXPECTED_ROUTER)
    checks.equal("climate_adapter_frozen", CLIMATE_METHOD_VERSION, EXPECTED_CLIMATE)
    try:
        _, authority, _ = s6c.verify_sources()
        checks.require("current_sources_verified", True)
    except Exception as error:
        checks.require("current_sources_verified", False, actual=f"{type(error).__name__}: {error}")
        return finalise_report(checks, output_dir, requested_scope, {}, None)
    sources = expected_source_identity(authority)

    source_connection = readonly(builder.SOURCE_STAGE6C5_DB)
    output_connection = readonly(output_db)
    try:
        checks.equal("source_stage6c5_sqlite_integrity", source_connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        checks.equal("output_sqlite_integrity", output_connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        checks.require("output_sqlite_foreign_keys", not output_connection.execute("PRAGMA foreign_key_check").fetchall())
        candidates = s6c5.load_candidates(source_connection, authority)
        checks.equal("frozen_all_candidate_count", len(candidates), EXPECTED_ALL)
        ft0 = sorted(
            (item for item in candidates if item.site.functional_tier == "FT0_HAUS_PRINCIPAL_SITE"),
            key=lambda item: item.site.settlement_id,
        )
        ft0_ids = [item.site.settlement_id for item in ft0]
        checks.equal("frozen_ft0_count", len(ft0_ids), EXPECTED_FT0)
        checks.equal("frozen_ft0_digest", digest_json(ft0_ids), EXPECTED_FT0_SHA256)
        ft0_dispositions = Counter(item.disposition for item in ft0)
        checks.equal("frozen_ft0_2d_count", ft0_dispositions["COMPLETE_2D_REFINEMENT"], EXPECTED_FT0_2D)
        checks.equal(
            "frozen_ft0_3d_surface_interface_count",
            ft0_dispositions["SURFACE_OR_INTERFACE_CONTEXT_ONLY_3D_DEFERRED"],
            EXPECTED_FT0_3D_CONTEXT,
        )
        metadata_rows = output_connection.execute("SELECT * FROM stage6c5r_run_metadata").fetchall()
        checks.equal("run_metadata_row_count", len(metadata_rows), 1)
        recorded_scope = str(metadata_rows[0]["scope"]) if metadata_rows else "UNKNOWN"
        scope = recorded_scope if requested_scope == "AUTO" else requested_scope
        checks.require("scope_is_ft0_or_all", scope in {"FT0", "ALL"}, actual=scope)
        checks.equal("requested_scope_matches_database", recorded_scope, scope)
        selected = ft0 if scope == "FT0" else list(candidates)
        checks.equal("scope_site_count", len(selected), EXPECTED_FT0 if scope == "FT0" else EXPECTED_ALL)
        if metadata_rows:
            metadata = metadata_rows[0]
            checks.equal("database_method", metadata["method"], EXPECTED_METHOD)
            checks.equal("database_canon_status", metadata["canon_status"], EXPECTED_STATUS)
            checks.equal("database_completed_count", int(metadata["completed_site_count"]), len(selected))
            checks.equal("database_pilot_route_gate", int(metadata["pilot_route_gate_pass"]), 1)
            checks.equal("database_quarantined_route_count", int(metadata["quarantined_route_count"]), 0)
            checks.equal("database_ft0_digest", metadata["ft0_scope_sha256"], EXPECTED_FT0_SHA256)
            checks.equal("database_generated_channels_not_promoted", int(metadata["generated_channels_promoted"]), 0)
            checks.equal("database_official_coordinates_not_modified", int(metadata["official_coordinates_modified"]), 0)
        site_rows = {
            str(row["settlement_id"]): dict(row)
            for row in output_connection.execute("SELECT * FROM stage6c5r_site_physical_context")
        }
        checks.equal("database_site_row_count", len(site_rows), len(selected))
        checks.equal("database_site_identity_set", sorted(site_rows), sorted(item.site.settlement_id for item in selected))
        route_row_count = int(output_connection.execute("SELECT COUNT(*) FROM stage6c5r_route_context").fetchone()[0])
        route_db_rows = {
            (str(row["settlement_id"]), str(row["part_id"])): dict(row)
            for row in output_connection.execute("SELECT * FROM stage6c5r_route_context")
        }
        parent_counts = parent_table_row_counts(source_connection)
        output_parent_counts = parent_table_row_counts(output_connection)
        checks.equal("copied_parent_table_row_counts", output_parent_counts, parent_counts)
        source_coordinate = {
            str(row["settlement_id"]): (float(row["official_x_km"]), float(row["official_y_km"]))
            for row in source_connection.execute(
                "SELECT settlement_id,official_x_km,official_y_km FROM stage6c5_candidate_registry"
            )
        }
        coordinate_failures = [
            settlement_id for settlement_id, row in site_rows.items()
            if source_coordinate.get(settlement_id) != (float(row["official_x_km"]), float(row["official_y_km"]))
            or int(row["official_coordinate_modified"]) != 0
        ]
        checks.require("official_coordinate_parity", not coordinate_failures, actual=coordinate_failures[:20])
    finally:
        source_connection.close()
        output_connection.close()

    if scope not in {"FT0", "ALL"}:
        return finalise_report(checks, output_dir, scope, {}, None)
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary_core = dict(summary)
    summary_identity = summary_core.pop("result_identity_sha256", None)
    checks.equal("summary_internal_identity", summary_identity, digest_json(summary_core))
    for name, actual, expected in (
        ("summary_scope", summary.get("scope"), scope),
        ("summary_method", summary.get("method"), EXPECTED_METHOD),
        ("summary_canon_status", summary.get("canon_status"), EXPECTED_STATUS),
        ("summary_completed_count", summary.get("completed_site_count"), len(selected)),
        ("summary_pilot_route_gate", summary.get("pilot_route_gate_pass"), True),
        ("summary_quarantined_route_count", summary.get("quarantined_route_count"), 0),
        ("summary_generated_channels_not_promoted", summary.get("generated_channels_promoted"), False),
        ("summary_official_coordinates_not_modified", summary.get("official_coordinates_modified"), False),
        ("summary_physical_source_resolution_m", summary.get("physical_source_resolution_m"), 100),
        ("summary_model_resolution_m", summary.get("model_resolution_m"), 10),
        ("summary_source_identity", summary.get("sources"), sources),
        ("summary_recipe_identity", summary.get("recipe"), expected_recipe_identity()),
    ):
        checks.equal(name, actual, expected)

    group = zarr.open_group(str(store_path), mode="r")
    checks.equal("zarr_array_set", sorted(set(group.array_keys()) - {"site_complete"}), sorted(ARRAY_SPECS))
    checks.equal("zarr_method", group.attrs.get("method"), EXPECTED_METHOD)
    checks.equal("zarr_schema", group.attrs.get("schema"), "diadem.stage6c5r-physical-context-zarr.v2")
    checks.equal("zarr_canon_status", group.attrs.get("canon_status"), EXPECTED_STATUS)
    checks.equal("zarr_slot_count", int(group.attrs.get("site_slot_count", -1)), EXPECTED_ALL)
    checks.equal("zarr_cell_size_m", int(group.attrs.get("cell_size_m", -1)), 10)
    checks.equal("zarr_physical_source_resolution_m", int(group.attrs.get("physical_source_resolution_m", -1)), 100)
    checks.equal("zarr_terrain_authority_root", group.attrs.get("terrain_authority_root_hash"), authority["root_hash"])
    checks.equal("zarr_compression_contract", group.attrs.get("compression"), "ZSTD_LEVEL_3_CHECKSUMMED")
    checks.equal("zarr_ft0_digest", group.attrs.get("ft0_scope_sha256"), EXPECTED_FT0_SHA256)
    checks.equal("zarr_generated_channels_not_promoted", group.attrs.get("generated_channels_promoted"), False)
    checks.equal("zarr_coordinates_not_modified", group.attrs.get("official_coordinates_modified"), False)
    for name, (tail, dtype) in ARRAY_SPECS.items():
        if name not in group:
            continue
        checks.equal(f"zarr_shape_{name}", tuple(group[name].shape), (EXPECTED_ALL, *tail))
        checks.equal(f"zarr_dtype_{name}", np.dtype(group[name].dtype).str, np.dtype(dtype).str)
        checks.equal(f"zarr_chunks_{name}", tuple(group[name].chunks), (1, *tail))
    complete = np.asarray(group["site_complete"][:], dtype=np.uint8)
    checks.equal("zarr_site_complete_shape", tuple(group["site_complete"].shape), (EXPECTED_ALL,))
    checks.equal("zarr_site_complete_dtype", np.dtype(group["site_complete"].dtype).str, np.dtype("u1").str)
    expected_complete = np.zeros(EXPECTED_ALL, dtype=np.uint8)
    for candidate in selected:
        expected_complete[candidate.index] = 1
    checks.require("zarr_completion_slots_exact", np.array_equal(complete, expected_complete), actual={
        "completed": np.flatnonzero(complete).tolist(),
        "expected": np.flatnonzero(expected_complete).tolist(),
    })

    topology = s6c.ExactSurfaceIndex(
        Path(s6c.SOURCES["exact_surface_registry"]["path"]),
        Path(s6c.SOURCES["fragment_barony_assignment"]["path"]),
    )
    rasters = s6c.RasterStack(authority)
    site_failures: list[str] = []
    bundle_failures: list[str] = []
    route_failures: list[str] = []
    semantic_failures: list[str] = []
    database_failures: list[str] = []
    exact_surface_failures: list[str] = []
    physical_failures: list[str] = []
    checkpoint_map: dict[str, Mapping[str, Any]] = {}
    frame_count = frame_bytes = 0
    maximums = {
        "base_parent_error_m": 0.0,
        "conditioned_parent_error_m": 0.0,
        "conditioning_max_abs_m": 0.0,
        "monthly_mass_balance_max_relative_error": 0.0,
        "maximum_route_divergence_m": 0.0,
    }
    expected_checkpoint_names = {item.site.settlement_id + ".json" for item in selected}
    actual_checkpoint_names = {path.name for path in (output_dir / "checkpoints").glob("*.json")}
    checks.equal("checkpoint_file_set", sorted(actual_checkpoint_names), sorted(expected_checkpoint_names))
    active_failure_names = sorted(
        path.name for path in (output_dir / "failures").glob("*.json")
        if path.stem in {item.site.settlement_id for item in selected}
    ) if (output_dir / "failures").is_dir() else []
    checks.require("no_selected_site_failure_artifacts", not active_failure_names, actual=active_failure_names)
    try:
        for position, candidate in enumerate(selected, 1):
            settlement_id = candidate.site.settlement_id
            try:
                checkpoint_path = output_dir / "checkpoints" / f"{settlement_id}.json"
                checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
                checkpoint_map[settlement_id] = checkpoint
                for key in ("route_relative_path", "review_map_relative_path", "bundle_relative_path"):
                    artifact = output_dir / str(checkpoint.get(key, ""))
                    if not artifact.exists():
                        site_failures.append(f"{settlement_id}: missing committed artifact {key}")
                route_artifact = output_dir / str(checkpoint.get("route_relative_path", ""))
                review_artifact = output_dir / str(checkpoint.get("review_map_relative_path", ""))
                if route_artifact.is_file() and sha256_file(route_artifact) != checkpoint.get("route_sha256"):
                    semantic_failures.append(f"{settlement_id}: route artefact hash")
                if review_artifact.is_file() and sha256_file(review_artifact) != checkpoint.get("review_map_sha256"):
                    semantic_failures.append(f"{settlement_id}: review-map artefact hash")
                expected_key = expected_semantic_key(candidate, sources)
                if checkpoint.get("semantic_key") != expected_key:
                    semantic_failures.append(f"{settlement_id}: checkpoint semantic key")
                if checkpoint.get("array_digest") != site_rows.get(settlement_id, {}).get("array_digest"):
                    database_failures.append(f"{settlement_id}: checkpoint/SQLite array digest")
                row0, col0 = window_origin(candidate)
                expected_checkpoint = {
                    "settlement_id": settlement_id,
                    "functional_tier": candidate.site.functional_tier,
                    "disposition": candidate.disposition,
                    "official_x_km": candidate.site.x,
                    "official_y_km": candidate.site.y,
                    "official_coordinate_modified": False,
                    "zarr_index": candidate.index,
                    "canon_status": EXPECTED_STATUS,
                }
                for key, expected in expected_checkpoint.items():
                    if checkpoint.get(key) != expected:
                        semantic_failures.append(f"{settlement_id}: checkpoint {key}")
                arrays = {name: np.asarray(group[name][candidate.index]) for name in ARRAY_SPECS}
                for name, (shape, dtype) in ARRAY_SPECS.items():
                    if arrays[name].shape != shape or arrays[name].dtype != np.dtype(dtype):
                        semantic_failures.append(f"{settlement_id}: array schema {name}")
                digest = arrays_digest(arrays)
                if digest != checkpoint.get("array_digest"):
                    semantic_failures.append(f"{settlement_id}: checkpoint/Zarr array digest")
                parent = rasters.terrain.read_block(row0, col0, 30, 30)
                local_receiver = receiver_from_direction(arrays["d8_receiver_code"])
                constraints, failures, route_metrics = validate_route_file(
                    output_dir / str(checkpoint["route_relative_path"]),
                    checkpoint, row0, col0, arrays["protected_channel_class"],
                    arrays["conditioned_elevation_m"], arrays["routing_elevation_m"],
                    local_receiver,
                )
                route_failures.extend(f"{settlement_id}: {item}" for item in failures)
                maximums["maximum_route_divergence_m"] = max(
                    maximums["maximum_route_divergence_m"], float(route_metrics["maximum_divergence_m"])
                )
                failures, physical_metrics = physical_site_checks(arrays, parent, constraints)
                physical_failures.extend(f"{settlement_id}: {item}" for item in failures)
                for key in (
                    "base_parent_error_m", "conditioned_parent_error_m",
                    "conditioning_max_abs_m", "monthly_mass_balance_max_relative_error",
                ):
                    maximums[key] = max(maximums[key], float(physical_metrics[key]))
                metrics = checkpoint.get("metrics") or {}
                if float(metrics.get("maximum_parent_mean_error_m", math.inf)) > PARENT_TOLERANCE_M:
                    physical_failures.append(f"{settlement_id}: checkpoint parent error")
                if float(metrics.get("conditioning_delta_max_abs_m", math.inf)) > CONDITIONING_LIMIT_M + 1e-6:
                    physical_failures.append(f"{settlement_id}: checkpoint conditioning limit")
                if float(metrics.get("monthly_mass_balance_max_relative_error", math.inf)) > MASS_BALANCE_TOLERANCE:
                    physical_failures.append(f"{settlement_id}: checkpoint mass balance")
                if float(metrics.get("strict_downhill_minimum_drop_m", -math.inf)) <= 0.0:
                    physical_failures.append(f"{settlement_id}: checkpoint downhill graph")
                if int(metrics.get("unsupported_channel_promoted_count", -1)) != 0:
                    physical_failures.append(f"{settlement_id}: generated channel promoted")
                if not bool(metrics.get("pilot_site_gate_pass")):
                    physical_failures.append(f"{settlement_id}: one or more inherited routes remain quarantined")
                if int(metrics.get("incomplete_quarantined_route_count", -1)) != 0:
                    physical_failures.append(f"{settlement_id}: incomplete route quarantine count is non-zero")
                lineage = checkpoint.get("lineage") or {}
                if (
                    lineage.get("canon_status") != EXPECTED_STATUS
                    or not lineage.get("not_a_surveyed_10m_dem")
                    or "NOT_ADDED_TO_CURRENT_NETWORK" not in str(lineage.get("generated_drainage_status"))
                    or "NOT_OBSERVED" not in str(lineage.get("width_status"))
                ):
                    semantic_failures.append(f"{settlement_id}: review-only lineage quarantine")
                climate_lineage = (lineage.get("source_lineage") or {}).get("climate") or {}
                if (
                    climate_lineage.get("archive_expected_sha256") != DEFAULT_ARCHIVE_SHA256
                    or climate_lineage.get("nominal_resolution_m") != 100
                    or climate_lineage.get("runoff_semantics") != RUNOFF_SEMANTICS
                    or climate_lineage.get("archive_hash_receipt_present") is not False
                ):
                    semantic_failures.append(f"{settlement_id}: climate provenance or receipt claim")
                exact = s6c5.rasterize_exact_surface_10m(
                    topology, row0 * 10, col0 * 10, ROWS, COLS
                )
                if not np.array_equal(exact, arrays["exact_barony_id"]):
                    exact_surface_failures.append(f"{settlement_id}: exact barony")
                if not np.array_equal((exact > 0).astype(np.uint8), arrays["exact_surface"]):
                    exact_surface_failures.append(f"{settlement_id}: exact surface")
                failures, frames, stored_bytes = verify_bundle(
                    output_dir / str(checkpoint["bundle_relative_path"]),
                    str(checkpoint["bundle_id"]), arrays, checkpoint,
                )
                bundle_failures.extend(f"{settlement_id}: {item}" for item in failures)
                frame_count += frames
                frame_bytes += stored_bytes
                if settlement_id in site_rows:
                    row = site_rows[settlement_id]
                    for key in (
                        "semantic_key", "bundle_relative_path", "route_relative_path",
                        "review_map_relative_path", "canon_status",
                    ):
                        if row.get(key) != checkpoint.get(key):
                            database_failures.append(f"{settlement_id}: SQLite/checkpoint {key}")
                    for column, metric_key in (
                        ("protected_feature_count", "protected_feature_count"),
                        ("boundary_inflow_feature_count", "boundary_inflow_feature_count"),
                        ("physically_admissible_route_count", "physically_admissible_route_count"),
                        ("incomplete_quarantined_route_count", "incomplete_quarantined_route_count"),
                        ("pilot_site_gate_pass", "pilot_site_gate_pass"),
                        ("maximum_parent_mean_error_m", "maximum_parent_mean_error_m"),
                        ("conditioning_delta_max_abs_m", "conditioning_delta_max_abs_m"),
                        ("monthly_mass_balance_max_relative_error", "monthly_mass_balance_max_relative_error"),
                        ("strict_downhill_minimum_drop_m", "strict_downhill_minimum_drop_m"),
                    ):
                        if float(row[column]) != float(metrics[metric_key]):
                            database_failures.append(f"{settlement_id}: SQLite/checkpoint {column}")
                for route_record in checkpoint.get("routes", []):
                    key = (settlement_id, str(route_record["part_id"]))
                    db_route = route_db_rows.get(key)
                    if db_route is None:
                        database_failures.append(f"{settlement_id}: SQLite route missing {key[1]}")
                        continue
                    expected_route_values = {
                        "feature_id": route_record["feature_id"],
                        "source_kind": route_record["source_kind"],
                        "route_class": route_record["route_class"],
                        "persistence": route_record["persistence"],
                        "receiver_id": route_record.get("receiver_id"),
                        "inherited_strahler_order": route_record.get("inherited_strahler_order"),
                        "boundary_inflow": int(bool(route_record["boundary_inflow"])),
                        "boundary_area_prior_km2": float(route_record["boundary_area_prior_km2"]),
                        "source_label_must_not_be_promoted": int(bool(route_record["source_label_must_not_be_promoted"])),
                        "route_status": route_record["route_status"],
                        "physical_route_accepted": int(bool(route_record["physical_route_accepted"])),
                        "route_failure_reason": route_record.get("route_failure_reason"),
                        "interior_corridor_edge_fraction": route_record.get("interior_corridor_edge_fraction"),
                    }
                    for column, expected in expected_route_values.items():
                        if db_route[column] != expected:
                            database_failures.append(f"{settlement_id}: SQLite route {key[1]} {column}")
                    for column, record_key in (
                        ("candidate_route_metrics_json", "candidate_route_metrics"),
                        ("candidate_route_lineage_json", "candidate_route_lineage"),
                    ):
                        if json.loads(str(db_route[column])) != route_record.get(record_key):
                            database_failures.append(f"{settlement_id}: SQLite route {key[1]} {column}")
                print(f"VALIDATE_6C5R_SITE {position}/{len(selected)} {settlement_id}", flush=True)
            except Exception as error:
                site_failures.append(f"{settlement_id}: {type(error).__name__}: {error}")
    finally:
        rasters.close()

    checks.require("all_site_validations_completed", not site_failures, actual=site_failures[:20])
    checks.require("semantic_checkpoint_and_array_digests", not semantic_failures, actual=semantic_failures[:20])
    checks.require("sqlite_checkpoint_agreement", not database_failures, actual=database_failures[:20])
    checks.require("exact_surface_and_barony_parity", not exact_surface_failures, actual=exact_surface_failures[:20])
    checks.require("physical_parent_conditioning_routing_and_mass_balance", not physical_failures, actual=physical_failures[:20])
    checks.require("route_pairs_corridors_and_stillklinge_quarantine", not route_failures, actual=route_failures[:20])
    checks.require("all_zstandard_bundle_frames_and_payloads", not bundle_failures, actual=bundle_failures[:20])
    checks.equal("bundle_count", len(checkpoint_map), len(selected))
    checks.require("bundle_frame_count_positive", frame_count > 0, actual=frame_count)
    checks.equal(
        "sqlite_route_row_count",
        route_row_count,
        sum(len(checkpoint.get("routes", [])) for checkpoint in checkpoint_map.values()),
    )

    replay_report: Mapping[str, Any] | None = None
    if rerun and not site_failures and len(checkpoint_map) == len(selected):
        replay_failures, replay_report = deterministic_replay(candidates, checkpoint_map, authority, sources)
        checks.require("deterministic_2d_and_3d_context_replay", not replay_failures, actual=replay_failures)
    elif rerun:
        checks.require("deterministic_2d_and_3d_context_replay", False, actual="blocked by incomplete committed sites")
    else:
        replay_report = {"status": "NOT_RUN_BY_EXPLICIT_FLAG"}

    metrics = {
        "validated_site_count": len(checkpoint_map),
        "validated_zstandard_frame_count": frame_count,
        "validated_zstandard_frame_bytes": frame_bytes,
        **maximums,
    }
    return finalise_report(checks, output_dir, scope, metrics, replay_report)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=builder.DEFAULT_OUTPUT_DIR)
    parser.add_argument("--scope", choices=("AUTO", "FT0", "ALL"), default="AUTO")
    parser.add_argument("--no-replay", action="store_true")
    args = parser.parse_args(argv)
    report = validate(
        args.output_dir.resolve(), args.scope, rerun=not args.no_replay
    )
    print(canonical_json({
        "status": report["status"],
        "scope": report["scope"],
        "counts": report["counts"],
        "report": str(args.output_dir.resolve() / "INDEPENDENT_VALIDATION.json"),
    }), flush=True)
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
