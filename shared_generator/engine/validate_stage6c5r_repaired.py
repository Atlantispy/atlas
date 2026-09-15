#!/usr/bin/env python3
"""Independent validation of the repaired Stage 6C.5R FT0 pilot.

This validator reads committed artefacts rather than trusting the builder's
summary.  It verifies hashes, the editable Zarr store, parent-cell
conservation, MFD routing, protected bed controls, route lineage, SQLite
integrity and a three-site shifted-support replay.  Production output is never
overwritten by the replay.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
from typing import Any, Mapping, Sequence


ENGINE_DIR = Path(__file__).resolve().parent
for dependency_directory in (ENGINE_DIR / "zarr_deps", ENGINE_DIR / "generator_deps"):
    value = str(dependency_directory)
    if value not in sys.path:
        sys.path.insert(0, value)

import numpy as np
import zarr

import build_stage6c_100m as s6c
import build_stage6c5_10m as s6c5
import build_stage6c5r_physical_10m as builder
from stage6c5r_hydrology import ActiveMajorBedProfiles, METHOD_VERSION as HYDROLOGY_METHOD
import stage6c5r_physical as physical
from stage6c5r_climate import C1MonthlyClimateReader


EXPECTED_METHOD = "STAGE6C5R_PROFILE_AWARE_10M_PHYSICAL_CONTEXT_V2_7_STABLE_FLOOD_REFERENCE"
EXPECTED_STATUS = "WORKING_PROPOSAL_REVIEW_ONLY_NOT_CANON"
EXPECTED_KERNEL = "S6C5R_PHYSICAL_KERNEL_2.0.1_REGISTERED_FLOOD_REFERENCE"
EXPECTED_PROFILE_SHA256 = "cb597ba4e4e6ceccc1efd3418f104b4cc2622fc301dea49dee4ca3e9b10d4dd4"
EXPECTED_FT0_SHA256 = "8721c4a66b32c14c0478f9d008afb3e421a1642b425b8fc7786b357c2e6f2612"
EXPECTED_SITES = 19
EXPECTED_SLOTS = 107
ROWS = COLS = 300
PARENT_FACTOR = 10
PARENT_TOLERANCE_M = 0.0051
CONDITIONING_LIMIT_M = 1.0
MASS_BALANCE_TOLERANCE = 1e-5
DERIVED_DELTA_TOLERANCE_M = 5e-4
PARENT_EDGE_MAX_M = 0.010
PARENT_EDGE_FLOOR_P99_M = 0.005

# Deliberately independent of builder.array_specs().  A production schema
# change must be reviewed here rather than silently accepted.
ARRAY_SPECS: dict[str, tuple[tuple[int, ...], str]] = {
    "base_broad_elevation_m": ((ROWS, COLS), "f4"),
    "conditioned_elevation_m": ((ROWS, COLS), "f4"),
    "terrain_conditioning_delta_m": ((ROWS, COLS), "f4"),
    "routing_elevation_m": ((ROWS, COLS), "f8"),
    "routing_fill_delta_m": ((ROWS, COLS), "f8"),
    "protected_channel_bed_elevation_m": ((ROWS, COLS), "f8"),
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
    "mfd_receiver_weights": ((8, ROWS, COLS), "f4"),
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

D8_BY_DELTA = {(dr, dc): code for code, (dr, dc, _) in enumerate(physical.D8)}
SHIFTED_REPLAY_IDS = (
    "S6-MOOR-CAPITAL-ANCHOR-01",
    "SITE4-A872A7A2208D1A55",
    "SITE4-26C9A4D994A0404E",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def canonical_json(value: Any) -> str:
    def fallback(item: Any) -> Any:
        if isinstance(item, Path):
            return str(item)
        if isinstance(item, np.generic):
            return item.item()
        raise TypeError(type(item).__name__)

    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=fallback
    )


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


def atomic_text(path: Path, text: str) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


class Audit:
    def __init__(self) -> None:
        self.checks: list[dict[str, Any]] = []

    def check(self, name: str, condition: bool, actual: Any, expected: Any, detail: str = "") -> None:
        self.checks.append({
            "name": name,
            "status": "PASS" if condition else "FAIL",
            "actual": actual,
            "expected": expected,
            "detail": detail,
        })

    def equal(self, name: str, actual: Any, expected: Any, detail: str = "") -> None:
        self.check(name, actual == expected, actual, expected, detail)

    def at_most(self, name: str, actual: float, maximum: float, detail: str = "") -> None:
        self.check(name, math.isfinite(actual) and actual <= maximum, actual, f"<= {maximum}", detail)

    @property
    def failed(self) -> list[dict[str, Any]]:
        return [item for item in self.checks if item["status"] == "FAIL"]


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_committed_arrays(group: zarr.Group, index: int) -> dict[str, np.ndarray]:
    return {name: np.asarray(group[name][index]) for name in ARRAY_SPECS}


def off_channel_parent_edge_metrics(delta: np.ndarray, protected: np.ndarray) -> dict[str, float | int]:
    protected_mask = protected > 0
    if np.any(protected_mask):
        # A cell is off-channel only when it is outside every class-specific
        # conditioning corridor.  Choosing only the nearest route is wrong when
        # a nearby narrow stream overlaps the wider corridor of a slightly more
        # distant major river.
        off_channel = np.ones(protected.shape, dtype=bool)
        for name, values in physical.CLASS_PARAMETERS.items():
            code = physical.CLASS_CODE[name]
            class_mask = protected == code
            if not np.any(class_mask):
                continue
            distance, _ = physical._chamfer_distance(class_mask)
            off_channel &= distance > np.float32(4.0 * float(values["sigma_cells"]))
    else:
        off_channel = np.ones(protected.shape, dtype=bool)

    boundary: list[np.ndarray] = []
    matched: list[np.ndarray] = []
    for position in range(PARENT_FACTOR, ROWS, PARENT_FACTOR):
        mask = off_channel[:, position - 1] & off_channel[:, position]
        boundary.append(np.abs(delta[:, position] - delta[:, position - 1])[mask])
        left = off_channel[:, position - 2] & off_channel[:, position - 1]
        right = off_channel[:, position] & off_channel[:, position + 1]
        matched.extend([
            np.abs(delta[:, position - 1] - delta[:, position - 2])[left],
            np.abs(delta[:, position + 1] - delta[:, position])[right],
        ])
        mask = off_channel[position - 1, :] & off_channel[position, :]
        boundary.append(np.abs(delta[position, :] - delta[position - 1, :])[mask])
        above = off_channel[position - 2, :] & off_channel[position - 1, :]
        below = off_channel[position, :] & off_channel[position + 1, :]
        matched.extend([
            np.abs(delta[position - 1, :] - delta[position - 2, :])[above],
            np.abs(delta[position + 1, :] - delta[position, :])[below],
        ])
    boundary_values = np.concatenate([item for item in boundary if item.size])
    matched_values = np.concatenate([item for item in matched if item.size])
    return {
        "sample_count": int(boundary_values.size),
        "maximum_m": float(np.max(boundary_values)) if boundary_values.size else 0.0,
        "p99_m": float(np.quantile(boundary_values, 0.99)) if boundary_values.size else 0.0,
        "matched_within_parent_p99_m": (
            float(np.quantile(matched_values, 0.99)) if matched_values.size else 0.0
        ),
    }


def route_checks(
    audit: Audit,
    route_path: Path,
    work: builder.SiteWork,
    arrays: Mapping[str, np.ndarray],
) -> dict[str, int]:
    data = read_json(route_path)
    inherited: dict[str, Mapping[str, Any]] = {}
    candidates: dict[str, Mapping[str, Any]] = {}
    for feature in data.get("features", []):
        properties = feature["properties"]
        part_id = str(properties["part_id"])
        if properties["geometry_role"] == "REGISTERED_V4_2_RASTERISED_10M_AXIS":
            inherited[part_id] = feature
        elif properties["geometry_role"] == "S6C5R_REGISTERED_AXIS_WITH_SEPARATE_BED_Z":
            candidates[part_id] = feature
    audit.equal(f"{work.candidate.site.settlement_id}: route geometry pairs", set(candidates), set(inherited))

    checked_edges = 0
    major_count = minor_count = 0
    weights = arrays["mfd_receiver_weights"]
    direction = arrays["d8_receiver_code"]
    routing = arrays["routing_elevation_m"]
    for part_id, feature in candidates.items():
        coordinates = feature["geometry"]["coordinates"]
        inherited_xy = inherited[part_id]["geometry"]["coordinates"]
        candidate_xy = [[point[0], point[1]] for point in coordinates]
        audit.equal(f"{work.candidate.site.settlement_id}:{part_id}: registered XY preserved", candidate_xy, inherited_xy)
        audit.check(
            f"{work.candidate.site.settlement_id}:{part_id}: 3D bed geometry",
            len(coordinates) >= 2 and all(len(point) == 3 for point in coordinates),
            len(coordinates),
            ">=2 three-dimensional points",
        )
        z = np.asarray([point[2] for point in coordinates], dtype=np.float64)
        monotone = bool(np.all(np.diff(z) <= 1e-9))
        audit.check(
            f"{work.candidate.site.settlement_id}:{part_id}: bed is downstream-monotone",
            monotone,
            float(np.max(np.diff(z))) if z.size > 1 else None,
            "<= 1e-9 m upward step",
        )
        properties = feature["properties"]
        if properties["source_kind"] == "major":
            major_count += 1
            audit.equal(
                f"{work.candidate.site.settlement_id}:{part_id}: major vertical authority",
                properties.get("vertical_control"),
                "NEW_REVIEW_CANDIDATE_FROM_ACTIVE_3D_MAJOR_PROFILE_WITH_TERRAIN_AUTHORITY_CEILING",
            )
            lineage = properties.get("bed_profile_lineage", {})
            audit.equal(
                f"{work.candidate.site.settlement_id}:{part_id}: source profile unchanged",
                lineage.get("source_profile_preserved_unchanged"),
                True,
            )
            audit.equal(
                f"{work.candidate.site.settlement_id}:{part_id}: reconciled bed is a new candidate",
                lineage.get("reconciled_profile_is_new_review_candidate"),
                True,
            )
        else:
            minor_count += 1
            vertical = str(properties.get("vertical_control", ""))
            audit.check(
                f"{work.candidate.site.settlement_id}:{part_id}: minor bed marked modelled",
                vertical.startswith("MODELLED_") and "NOT_OBSERVED_Z" in vertical,
                vertical,
                "MODELLED_*_NOT_OBSERVED_Z",
            )
        audit.equal(
            f"{work.candidate.site.settlement_id}:{part_id}: terrain rerouting disabled",
            properties.get("candidate_route_lineage", {}).get("terrain_rerouting_used"),
            False,
        )

        cells: list[tuple[int, int]] = []
        for x_km, y_km, _ in coordinates:
            global_col = int(math.floor(float(x_km) / 0.01 + 1e-7))
            global_row = int(math.floor(float(y_km) / 0.01 + 1e-7))
            cells.append((global_row - work.row0 * 10, global_col - work.col0 * 10))
        for source, target in zip(cells[:-1], cells[1:]):
            if not (
                0 <= source[0] < ROWS and 0 <= source[1] < COLS
                and 0 <= target[0] < ROWS and 0 <= target[1] < COLS
            ):
                continue
            delta = (target[0] - source[0], target[1] - source[1])
            code = D8_BY_DELTA.get(delta)
            if code is None:
                audit.check(
                    f"{work.candidate.site.settlement_id}:{part_id}: local protected edge",
                    False, delta, "one D8 cell",
                )
                continue
            checked_edges += 1
            total = float(np.sum(weights[:, source[0], source[1]], dtype=np.float64))
            good = (
                abs(total - 1.0) <= 1e-6
                and abs(float(weights[code, source[0], source[1]]) - 1.0) <= 1e-6
                and int(direction[source]) == code
                and float(routing[source]) > float(routing[target])
            )
            if not good:
                audit.check(
                    f"{work.candidate.site.settlement_id}:{part_id}: protected MFD edge",
                    False,
                    {
                        "source": source, "target": target, "weight_sum": total,
                        "selected_weight": float(weights[code, source[0], source[1]]),
                        "direction": int(direction[source]),
                        "drop_m": float(routing[source] - routing[target]),
                    },
                    "single unit-weight strictly-downhill edge",
                )
                break
    return {"major_routes": major_count, "minor_routes": minor_count, "protected_edges": checked_edges}


def shifted_work(work: builder.SiteWork) -> builder.SiteWork:
    row_shift = 1 if work.core_row_offset >= 1 and work.analysis_row0 + 1 <= 18_600 - 50 else -1
    col_shift = 1 if work.core_col_offset >= 1 and work.analysis_col0 + 1 <= 22_000 - 50 else -1
    semantic = sha256(f"{work.semantic_key}:shift:{row_shift}:{col_shift}".encode("utf-8")).hexdigest()
    return builder.SiteWork(
        work.candidate,
        work.row0,
        work.col0,
        work.analysis_row0 + row_shift,
        work.analysis_col0 + col_shift,
        work.core_row_offset - row_shift,
        work.core_col_offset - col_shift,
        semantic,
    )


def compare_shifted(
    audit: Audit,
    original: Mapping[str, np.ndarray],
    shifted: Mapping[str, np.ndarray],
    settlement_id: str,
) -> dict[str, Any]:
    exact_names = (
        "base_broad_elevation_m", "protected_channel_class", "inherited_current_channel_class",
        "exact_barony_id", "exact_surface", "land_mask", "sea_mask_parent_projected",
        "wetland_mask_parent_projected", "serenakrone_water_parent_projected",
        "registered_sink_mask",
    )
    exact_failures = []
    for name in exact_names:
        if not np.array_equal(original[name], shifted[name], equal_nan=True):
            exact_failures.append(name)
    audit.equal(f"{settlement_id}: shifted-support exact stable arrays", exact_failures, [])

    result: dict[str, Any] = {"settlement_id": settlement_id, "exact_failures": exact_failures}
    for name, p99_limit, max_limit in (
        ("terrain_conditioning_delta_m", 0.005, 0.010),
        ("conditioned_elevation_m", 0.005, 0.010),
        ("flood_susceptibility", 0.010, 0.050),
        ("wetness_potential", 0.010, 0.050),
    ):
        difference = np.abs(original[name].astype(np.float64) - shifted[name].astype(np.float64))
        finite = difference[np.isfinite(difference)]
        p99 = float(np.quantile(finite, 0.99)) if finite.size else 0.0
        maximum = float(np.max(finite)) if finite.size else 0.0
        result[name] = {"p99": p99, "maximum": maximum}
        audit.check(
            f"{settlement_id}: shifted-support {name}",
            p99 <= p99_limit and maximum <= max_limit,
            {"p99": p99, "maximum": maximum},
            {"p99_max": p99_limit, "absolute_max": max_limit},
        )
    return result


def run(output_dir: Path, *, shifted_replay: bool = True) -> dict[str, Any]:
    started = time.perf_counter()
    audit = Audit()
    summary_path = output_dir / "S6C5R_RUN_SUMMARY.json"
    summary = read_json(summary_path)
    audit.equal("run method", summary.get("method"), EXPECTED_METHOD)
    audit.equal("run summary schema", summary.get("schema"), "diadem.stage6c5r-run-summary.v3")
    audit.equal("run status", summary.get("status"), "PASS_REVIEW_ONLY")
    audit.equal("canon quarantine", summary.get("canon_status"), EXPECTED_STATUS)
    audit.equal("FT0 site count", summary.get("completed_site_count"), EXPECTED_SITES)
    audit.equal("FT0 scope digest", summary.get("ft0_scope_sha256"), EXPECTED_FT0_SHA256)
    audit.equal("route gate", summary.get("pilot_route_gate_pass"), True)
    audit.equal("quarantined routes", summary.get("quarantined_route_count"), 0)
    audit.equal("official coordinates unchanged", summary.get("official_coordinates_modified"), False)
    audit.equal("generated channels not promoted", summary.get("generated_channels_promoted"), False)
    audit.equal("kernel method", summary["recipe"]["physical"].get("kernel_method"), EXPECTED_KERNEL)
    audit.equal(
        "profile-aware hydrology method",
        summary["recipe"]["implementations"].get("profile_aware_hydrology"),
        HYDROLOGY_METHOD,
    )
    audit.equal(
        "major profile source digest in summary",
        summary["sources"]["hydrology"]["active_major_bed_profiles"].get("sha256"),
        EXPECTED_PROFILE_SHA256,
    )
    identity_payload = dict(summary)
    stored_identity = identity_payload.pop("result_identity_sha256")
    audit.equal("run summary identity", builder.digest_json(identity_payload), stored_identity)

    _, authority, _ = s6c.verify_sources()
    profile_path = Path(s6c.SOURCES["active_major_bed_profiles"]["path"])
    audit.equal("major profile source file SHA-256", sha256_file(profile_path), EXPECTED_PROFILE_SHA256)
    sources = builder.source_identity(authority)
    with s6c5.sqlite_readonly(s6c5.PARENT_DB) as connection:
        candidates = s6c5.load_candidates(connection, authority)
    selected = builder.scope_candidates(candidates, "FT0")
    work_items = builder.build_work(selected, sources)
    work_by_id = {item.candidate.site.settlement_id: item for item in work_items}
    audit.equal("current FT0 work count", len(work_items), EXPECTED_SITES)

    checkpoint_paths = sorted((output_dir / "checkpoints").glob("*.json"))
    checkpoints = [read_json(path) for path in checkpoint_paths]
    checkpoint_by_id = {item["settlement_id"]: item for item in checkpoints}
    audit.equal("checkpoint count", len(checkpoints), EXPECTED_SITES)
    audit.equal("checkpoint settlement IDs", set(checkpoint_by_id), set(work_by_id))
    audit.equal(
        "checkpoint schemas",
        {item.get("schema") for item in checkpoints},
        {"diadem.stage6c5r-site-checkpoint.v3"},
    )

    group = zarr.open_group(str(output_dir / "physical_context_10m.zarr"), mode="r")
    audit.equal("Zarr method", group.attrs.get("method"), EXPECTED_METHOD)
    audit.equal("Zarr schema", group.attrs.get("schema"), "diadem.stage6c5r-physical-context-zarr.v4")
    audit.equal("Zarr canon quarantine", group.attrs.get("canon_status"), EXPECTED_STATUS)
    audit.equal("Zarr site slot count", group.attrs.get("site_slot_count"), EXPECTED_SLOTS)
    audit.equal("Zarr array names", set(group.array_keys()), set(ARRAY_SPECS) | {"site_complete"})
    for name, (tail, dtype) in ARRAY_SPECS.items():
        audit.equal(f"Zarr {name} shape", tuple(group[name].shape), (EXPECTED_SLOTS, *tail))
        audit.equal(f"Zarr {name} dtype", np.dtype(group[name].dtype).str, np.dtype(dtype).str)

    completed_indices = set(np.flatnonzero(np.asarray(group["site_complete"])).tolist())
    checkpoint_indices = {int(item["zarr_index"]) for item in checkpoints}
    audit.equal("Zarr completed-site flags", completed_indices, checkpoint_indices)
    audit.equal("unique checkpoint indices", len(checkpoint_indices), EXPECTED_SITES)

    terrain = s6c.RasterStack(authority)
    site_metrics: list[dict[str, Any]] = []
    aggregate_boundary: list[dict[str, Any]] = []
    aggregate_multi = aggregate_active_nonprotected = 0
    total_major = total_minor = total_edges = 0
    try:
        for settlement_id in sorted(work_by_id):
            work = work_by_id[settlement_id]
            checkpoint = checkpoint_by_id[settlement_id]
            index = int(checkpoint["zarr_index"])
            arrays = load_committed_arrays(group, index)
            digest = arrays_digest(arrays)
            audit.equal(f"{settlement_id}: Zarr array digest", digest, checkpoint["array_digest"])
            summary_site = next(item for item in summary["sites"] if item["settlement_id"] == settlement_id)
            audit.equal(f"{settlement_id}: summary/checkpoint digest", summary_site["array_digest"], digest)

            route_path = output_dir / checkpoint["route_relative_path"]
            map_path = output_dir / checkpoint["review_map_relative_path"]
            audit.equal(f"{settlement_id}: route file hash", sha256_file(route_path), checkpoint["route_sha256"])
            audit.equal(f"{settlement_id}: review map hash", sha256_file(map_path), checkpoint["review_map_sha256"])
            manifest = s6c5.verified_bundle_manifest(output_dir / checkpoint["bundle_relative_path"])
            audit.equal(f"{settlement_id}: recovery bundle identity", manifest["bundle_id"], checkpoint["bundle_id"])

            parent = terrain.read_block(work.row0, work.col0, 30, 30)["terrain"].astype(np.float64)
            base_means = physical.parent_block_means(arrays["base_broad_elevation_m"].astype(np.float64))
            conditioned_means = physical.parent_block_means(arrays["conditioned_elevation_m"].astype(np.float64))
            base_parent_error = float(np.max(np.abs(base_means - parent)))
            conditioned_parent_error = float(np.max(np.abs(conditioned_means - parent)))
            audit.at_most(f"{settlement_id}: base parent-mean error", base_parent_error, PARENT_TOLERANCE_M)
            audit.at_most(
                f"{settlement_id}: conditioned parent-mean error",
                conditioned_parent_error,
                PARENT_TOLERANCE_M,
            )
            reconstructed_delta = (
                arrays["conditioned_elevation_m"].astype(np.float64)
                - arrays["base_broad_elevation_m"].astype(np.float64)
            )
            stored_delta_error = float(np.max(np.abs(
                reconstructed_delta - arrays["terrain_conditioning_delta_m"].astype(np.float64)
            )))
            audit.at_most(
                f"{settlement_id}: stored conditioning delta consistency",
                stored_delta_error,
                DERIVED_DELTA_TOLERANCE_M,
            )
            routing_reconstruction_error = float(np.max(np.abs(
                arrays["routing_elevation_m"].astype(np.float64)
                - arrays["conditioned_elevation_m"].astype(np.float64)
                - arrays["routing_fill_delta_m"].astype(np.float64)
            )))
            audit.at_most(
                f"{settlement_id}: stored routing-surface reconstruction",
                routing_reconstruction_error,
                1e-9,
            )
            max_conditioning = float(np.max(np.abs(arrays["terrain_conditioning_delta_m"])))
            audit.at_most(f"{settlement_id}: one-metre conditioning cap", max_conditioning, CONDITIONING_LIMIT_M + 1e-6)

            protected = arrays["protected_channel_class"] > 0
            bed = arrays["protected_channel_bed_elevation_m"]
            audit.check(
                f"{settlement_id}: protected bed finite on protected cells",
                bool(np.all(np.isfinite(bed[protected]))),
                int(np.count_nonzero(~np.isfinite(bed[protected]))),
                0,
            )
            audit.check(
                f"{settlement_id}: bed absent outside protected cells",
                bool(np.all(~np.isfinite(bed[~protected]))),
                int(np.count_nonzero(np.isfinite(bed[~protected]))),
                0,
            )
            bed_above_land = (
                bed[protected].astype(np.float64)
                - arrays["conditioned_elevation_m"][protected].astype(np.float64)
            )
            maximum_bed_above_land = (
                float(np.max(bed_above_land)) if bed_above_land.size else 0.0
            )
            audit.at_most(
                f"{settlement_id}: protected bed not above conditioned land",
                maximum_bed_above_land,
                1e-9,
            )
            audit.equal(
                f"{settlement_id}: full-support bed-above-land hard gate",
                int(checkpoint["metrics"]["protected_bed_above_conditioned_land_cell_count"]),
                0,
            )

            weights = arrays["mfd_receiver_weights"].astype(np.float64)
            weight_sums = weights.sum(axis=0)
            active = weight_sums > 0.0
            weight_error = float(np.max(np.abs(weight_sums[active] - 1.0))) if np.any(active) else 0.0
            audit.at_most(f"{settlement_id}: MFD weight-sum error", weight_error, 1e-6)
            audit.check(
                f"{settlement_id}: MFD weights nonnegative",
                bool(np.all(weights >= 0.0)), float(np.min(weights)), ">= 0",
            )
            dominant = np.argmax(weights, axis=0).astype(np.int8)
            direction = arrays["d8_receiver_code"]
            valid_direction = (~active) | ((direction >= 0) & (direction < 8))
            safe_direction = np.where(active, direction, 0).astype(np.int64)
            selected_weight = np.take_along_axis(
                weights,
                safe_direction[None, :, :],
                axis=0,
            )[0]
            # Float32 storage can turn a sub-ULP float64 lead into an exact tie.
            # Either tied maximum is a truthful dominant direction.
            direction_match = bool(
                np.all(valid_direction)
                and np.all(selected_weight[active] == np.max(weights, axis=0)[active])
            )
            audit.check(
                f"{settlement_id}: dominant direction agrees with MFD",
                direction_match,
                direction_match,
                True,
            )
            stored_flat_or_uphill_edges = 0
            for code, (dr, dc, _) in enumerate(physical.D8):
                row0 = max(0, -dr)
                row1 = min(ROWS, ROWS - dr)
                col0 = max(0, -dc)
                col1 = min(COLS, COLS - dc)
                selected = weights[code, row0:row1, col0:col1] > 0.0
                if not np.any(selected):
                    continue
                source_values = arrays["routing_elevation_m"][row0:row1, col0:col1]
                target_values = arrays["routing_elevation_m"][
                    row0 + dr:row1 + dr,
                    col0 + dc:col1 + dc,
                ]
                stored_flat_or_uphill_edges += int(np.count_nonzero(
                    selected & (source_values <= target_values)
                ))
            audit.equal(
                f"{settlement_id}: stored positive-weight edges are strictly downhill",
                stored_flat_or_uphill_edges,
                0,
            )
            receiver_count = np.count_nonzero(weights > 0.0, axis=0)
            nonprotected_active = active & ~protected
            aggregate_multi += int(np.count_nonzero((receiver_count > 1) & nonprotected_active))
            aggregate_active_nonprotected += int(np.count_nonzero(nonprotected_active))

            metrics = checkpoint["metrics"]
            audit.at_most(
                f"{settlement_id}: monthly mass-balance error",
                float(metrics["monthly_mass_balance_max_relative_error"]),
                MASS_BALANCE_TOLERANCE,
            )
            audit.equal(f"{settlement_id}: receiver cycle count", int(metrics["receiver_cycle_count"]), 0)
            audit.equal(f"{settlement_id}: route quarantine count", int(metrics["incomplete_quarantined_route_count"]), 0)
            audit.equal(f"{settlement_id}: unsupported channel promotions", int(metrics["unsupported_channel_promoted_count"]), 0)
            audit.equal(f"{settlement_id}: unapproved support corridors", int(metrics["unapproved_support_corridor_count"]), 0)
            audit.equal(f"{settlement_id}: official coordinate unchanged", checkpoint["official_coordinate_modified"], False)
            audit.equal(
                f"{settlement_id}: profile source lineage",
                checkpoint["lineage"]["source_lineage"].get("major_bed_profiles_sha256"),
                EXPECTED_PROFILE_SHA256,
            )

            routes = route_checks(audit, route_path, work, arrays)
            total_major += routes["major_routes"]
            total_minor += routes["minor_routes"]
            total_edges += routes["protected_edges"]
            boundary = off_channel_parent_edge_metrics(
                arrays["terrain_conditioning_delta_m"].astype(np.float64),
                arrays["protected_channel_class"],
            )
            aggregate_boundary.append({"settlement_id": settlement_id, **boundary})
            p99_limit = max(
                PARENT_EDGE_FLOOR_P99_M,
                3.0 * float(boundary["matched_within_parent_p99_m"]),
            )
            audit.check(
                f"{settlement_id}: off-channel parent-edge continuity",
                float(boundary["maximum_m"]) <= PARENT_EDGE_MAX_M
                and float(boundary["p99_m"]) <= p99_limit,
                boundary,
                {"maximum_m": PARENT_EDGE_MAX_M, "p99_m": p99_limit},
            )
            site_metrics.append({
                "settlement_id": settlement_id,
                "base_parent_mean_error_m": base_parent_error,
                "conditioned_parent_mean_error_m": conditioned_parent_error,
                "conditioning_delta_max_abs_m": max_conditioning,
                "maximum_bed_above_conditioned_land_m": maximum_bed_above_land,
                "mfd_weight_sum_max_error": weight_error,
                "stored_flat_or_uphill_mfd_edge_count": stored_flat_or_uphill_edges,
                "routing_reconstruction_max_error_m": routing_reconstruction_error,
                "monthly_mass_balance_max_relative_error": float(metrics["monthly_mass_balance_max_relative_error"]),
                "parent_edge": boundary,
                **routes,
            })
    finally:
        terrain.close()

    multi_fraction = aggregate_multi / max(aggregate_active_nonprotected, 1)
    audit.check(
        "MFD materially distributes non-protected flow",
        multi_fraction >= 0.10,
        multi_fraction,
        ">= 0.10 of active non-protected cells have multiple receivers",
    )

    database = output_dir / builder.OUTPUT_DB_NAME
    with sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True) as connection:
        audit.equal("SQLite integrity", connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        audit.equal(
            "SQLite Stage6C5R site rows",
            connection.execute("SELECT COUNT(*) FROM stage6c5r_site_physical_context").fetchone()[0],
            EXPECTED_SITES,
        )
        audit.equal(
            "SQLite Stage6C5R route rows",
            connection.execute("SELECT COUNT(*) FROM stage6c5r_route_context").fetchone()[0],
            total_major + total_minor,
        )
        audit.equal(
            "SQLite forbidden promoted/modified flags",
            connection.execute(
                "SELECT COUNT(*) FROM stage6c5r_site_physical_context "
                "WHERE official_coordinate_modified<>0 OR generated_channels_promoted<>0"
            ).fetchone()[0],
            0,
        )

    shifted_results: list[dict[str, Any]] = []
    if shifted_replay:
        topology = s6c.ExactSurfaceIndex(
            Path(s6c.SOURCES["exact_surface_registry"]["path"]),
            Path(s6c.SOURCES["fragment_barony_assignment"]["path"]),
        )
        vectors = s6c.VectorStack("reference")
        profiles = ActiveMajorBedProfiles(profile_path)
        profiles.validate_axes(zip(vectors.major_geoms, vectors.major_props))
        rasters = s6c.RasterStack(authority)
        try:
            with tempfile.TemporaryDirectory(prefix="s6c5r-shifted-validation-") as temp_value:
                temporary_output = Path(temp_value)
                for name in ("tile_cache", "routes", "review_maps", "failures"):
                    (temporary_output / name).mkdir(parents=True, exist_ok=True)
                with C1MonthlyClimateReader() as climate:
                    for settlement_id in SHIFTED_REPLAY_IDS:
                        original_work = work_by_id[settlement_id]
                        replay_work = shifted_work(original_work)
                        _, shifted_arrays = builder.site_result(
                            replay_work,
                            rasters,
                            topology,
                            vectors,
                            profiles,
                            climate,
                            temporary_output,
                            verify_reference=False,
                        )
                        original_arrays = load_committed_arrays(
                            group, int(checkpoint_by_id[settlement_id]["zarr_index"])
                        )
                        shifted_results.append(
                            compare_shifted(audit, original_arrays, shifted_arrays, settlement_id)
                        )
        finally:
            rasters.close()

    worst_boundary = max(aggregate_boundary, key=lambda item: float(item["maximum_m"]))
    report = {
        "schema": "diadem.stage6c5r-independent-validation-repaired.v1",
        "completed_utc": utc_now(),
        "status": "PASS_REVIEW_ONLY_WITH_DECLARED_LIMITATIONS" if not audit.failed else "FAIL_REVIEW_REQUIRED",
        "canon_status": EXPECTED_STATUS,
        "output_directory": str(output_dir),
        "runtime_seconds": time.perf_counter() - started,
        "checks_total": len(audit.checks),
        "checks_passed": len(audit.checks) - len(audit.failed),
        "checks_failed": len(audit.failed),
        "failed_checks": audit.failed,
        "checks": audit.checks,
        "aggregate_metrics": {
            "site_count": EXPECTED_SITES,
            "major_route_count": total_major,
            "minor_route_count": total_minor,
            "protected_route_edges_checked": total_edges,
            "nonprotected_active_mfd_cell_count": aggregate_active_nonprotected,
            "nonprotected_multi_receiver_cell_count": aggregate_multi,
            "nonprotected_multi_receiver_fraction": multi_fraction,
            "maximum_parent_mean_error_m": max(
                item["conditioned_parent_mean_error_m"] for item in site_metrics
            ),
            "maximum_conditioning_delta_abs_m": max(
                item["conditioning_delta_max_abs_m"] for item in site_metrics
            ),
            "maximum_monthly_mass_balance_relative_error": max(
                item["monthly_mass_balance_max_relative_error"] for item in site_metrics
            ),
            "worst_off_channel_parent_edge": worst_boundary,
        },
        "site_metrics": site_metrics,
        "shifted_support_replay": shifted_results,
        "declared_limitations": [
            "The 10 m surface is an analytical refinement of authoritative 100 m terrain, not surveyed 10 m topography.",
            "Minor-stream bed Z is graph-constrained and modelled, not observed.",
            "Generated drainage remains analytical potential and is not promoted to the approved network.",
            "Runoff, width, flood susceptibility and wetness are review-only model products.",
            "This report validates only the 19 FT0 pilot sites.",
        ],
    }
    builder.atomic_json(output_dir / "INDEPENDENT_VALIDATION_REPAIRED.json", report)
    lines = [
        "# Independent validation — repaired Stage 6C.5R FT0 pilot",
        "",
        "**WORKING PROPOSAL — REVIEW ONLY — NOT CANON**",
        "",
        f"Result: **{report['status']}**",
        f"Checks: **{report['checks_passed']}/{report['checks_total']} passed**; failures: **{report['checks_failed']}**.",
        f"Runtime: **{report['runtime_seconds']:.1f} seconds**.",
        "",
        "## Key measurements",
        "",
        f"- sites independently read and checked: **{EXPECTED_SITES}**;",
        f"- protected route parts: **{total_major} major + {total_minor} minor**;",
        f"- protected downstream edges checked: **{total_edges:,}**;",
        f"- maximum conditioned parent-mean error: **{report['aggregate_metrics']['maximum_parent_mean_error_m']:.9f} m**;",
        f"- maximum land-surface conditioning: **{report['aggregate_metrics']['maximum_conditioning_delta_abs_m']:.6f} m**;",
        f"- maximum monthly mass-balance relative error: **{report['aggregate_metrics']['maximum_monthly_mass_balance_relative_error']:.9g}**;",
        f"- non-protected active cells using more than one MFD receiver: **{multi_fraction:.1%}**;",
        f"- worst off-channel 100 m edge jump in conditioning delta: **{float(worst_boundary['maximum_m']):.6f} m** at `{worst_boundary['settlement_id']}`;",
        f"- shifted-support replays: **{len(shifted_results)}**.",
        "",
        "## Interpretation",
        "",
        "The validator does not treat smaller cells as new terrain evidence. It checks that the repaired model preserves every 100 m parent mean, keeps protected channel beds separate from the land surface, uses mass-conserving MFD flow, preserves registered route XY, and marks modelled minor-bed elevation honestly.",
        "",
        "## Declared limitations",
        "",
    ]
    lines.extend(f"- {item}" for item in report["declared_limitations"])
    if audit.failed:
        lines.extend(["", "## Failed checks", ""])
        lines.extend(f"- `{item['name']}`: actual `{item['actual']}`, expected `{item['expected']}`" for item in audit.failed)
    atomic_text(output_dir / "INDEPENDENT_VALIDATION_REPAIRED.md", "\n".join(lines) + "\n")
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=builder.DEFAULT_OUTPUT_DIR)
    parser.add_argument("--skip-shifted-replay", action="store_true")
    args = parser.parse_args(argv)
    report = run(args.output_dir.resolve(), shifted_replay=not args.skip_shifted_replay)
    print(canonical_json({
        "status": report["status"],
        "checks_total": report["checks_total"],
        "checks_failed": report["checks_failed"],
        "runtime_seconds": report["runtime_seconds"],
        "output_directory": report["output_directory"],
    }))
    return 0 if report["checks_failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
