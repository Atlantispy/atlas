#!/usr/bin/env python3
"""Independent fail-closed validation for the Stage 6C.5 10 m release."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any, Mapping, Sequence


ENGINE_DIR = Path(__file__).resolve().parent
for dependency_directory in (ENGINE_DIR / "zarr_deps", ENGINE_DIR / "generator_deps"):
    if str(dependency_directory) not in sys.path:
        sys.path.insert(0, str(dependency_directory))

import numpy as np
import zarr
import zstandard as zstd

import build_stage6c_100m as s6c
import build_stage6c5_10m as s6c5
import stage6d_schema as s6d_schema
from stage6c5_fast_terrain import compare_terrain_tiles, refine_terrain_fast
from ten_m_tile_engine.cache import read_recovery_manifest
from ten_m_tile_engine.engine import ParentRasterWindow, TileSpec, refine_terrain


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    payload = (canonical_json(value) + "\n").encode("utf-8")
    with temporary.open("wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


class Checks:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    def check(self, name: str, actual: Any, expected: Any, *, detail: str = "") -> None:
        passed = actual == expected
        self.rows.append({
            "name": name,
            "status": "PASS" if passed else "FAIL",
            "actual": actual,
            "expected": expected,
            "detail": detail,
        })

    def require(self, name: str, condition: bool, *, actual: Any = None, detail: str = "") -> None:
        self.rows.append({
            "name": name,
            "status": "PASS" if condition else "FAIL",
            "actual": actual if actual is not None else bool(condition),
            "expected": True,
            "detail": detail,
        })

    def warn(self, name: str, detail: str, actual: Any = None) -> None:
        self.rows.append({
            "name": name,
            "status": "WARN",
            "actual": actual,
            "expected": None,
            "detail": detail,
        })


def readonly(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def artifact_bytes(bundle: Path, artifact_path: str) -> bytes:
    manifest = read_recovery_manifest(bundle)
    descriptor = next(
        packet for packet in manifest["packets"]
        if packet.get("artifact_path") == artifact_path
    )
    frame = bundle / descriptor["frame_path"]
    payload = zstd.ZstdDecompressor().decompress(frame.read_bytes())
    if len(payload) != int(descriptor["raw_size"]):
        raise RuntimeError(f"Raw-size mismatch for {artifact_path}")
    if hashlib.sha256(payload).hexdigest() != descriptor["target_hash"]:
        raise RuntimeError(f"Content digest mismatch for {artifact_path}")
    return payload


def validate_bundles(
    checks: Checks,
    output_dir: Path,
    tile_rows: Sequence[sqlite3.Row],
) -> tuple[str, int, int]:
    aggregate = hashlib.sha256()
    total_frames = 0
    total_bytes = 0
    required_artifacts = {
        "metadata.json",
        "arrays/elevation_residual_q.npy",
        "arrays/broad_elevation_10m.npy",
        "arrays/local_gradient_magnitude_10m.npy",
        "arrays/exact_barony_id_10m_core.npy",
        "arrays/candidate_active_water_distance_km.npy",
        "arrays/candidate_site_score.npy",
    }
    decompressor = zstd.ZstdDecompressor()
    failures: list[str] = []
    for row in tile_rows:
        bundle = output_dir / str(row["bundle_relative_path"])
        try:
            manifest = read_recovery_manifest(bundle)
            if manifest["bundle_id"] != row["bundle_id"]:
                raise RuntimeError("bundle ID differs from SQLite manifest")
            artifacts = set()
            for packet in manifest["packets"]:
                artifact = packet.get("artifact_path") or ""
                if "/" in artifact:
                    artifact = artifact.split("/", 1)[1]
                artifacts.add(artifact)
                if packet["kind"] == "ref":
                    continue
                frame = bundle / packet["frame_path"]
                frame_bytes = frame.read_bytes()
                if len(frame_bytes) != int(packet["frame_size"]):
                    raise RuntimeError(f"frame size mismatch: {frame}")
                if hashlib.sha256(frame_bytes).hexdigest() != packet["frame_sha256"]:
                    raise RuntimeError(f"frame checksum mismatch: {frame}")
                raw = decompressor.decompress(frame_bytes)
                if len(raw) != int(packet["raw_size"]):
                    raise RuntimeError(f"payload size mismatch: {frame}")
                if hashlib.sha256(raw).hexdigest() != packet["target_hash"]:
                    raise RuntimeError(f"payload checksum mismatch: {frame}")
                total_frames += 1
                total_bytes += len(frame_bytes)
            missing = required_artifacts - artifacts
            if missing:
                raise RuntimeError("missing required artifacts: " + ",".join(sorted(missing)))
            aggregate.update(str(row["tile_id"]).encode("utf-8"))
            aggregate.update(manifest["bundle_id"].encode("ascii"))
        except Exception as error:
            failures.append(f"{row['tile_id']}: {type(error).__name__}: {error}")
    checks.check("bundle_count", len(tile_rows), s6c5.EXPECTED_CANDIDATES)
    checks.require("all_bundle_manifests_and_frames_valid", not failures, actual=failures[:10])
    checks.require("bundle_frame_count_positive", total_frames > 0, actual=total_frames)
    return aggregate.hexdigest(), total_frames, total_bytes


def deterministic_sample(
    checks: Checks,
    output_dir: Path,
    output_db: Path,
) -> dict[str, Any]:
    _, authority_descriptor, _ = s6c.verify_sources()
    connection = readonly(output_db)
    try:
        candidates = s6c5.load_candidates(connection, authority_descriptor)
        result_by_id = {
            str(row["settlement_id"]): dict(row)
            for row in connection.execute("SELECT * FROM stage6c5_site_refinement")
        }
    finally:
        connection.close()
    ordered = sorted(
        candidates,
        key=lambda item: hashlib.sha256(("S6C5-QA|" + item.site.settlement_id).encode()).hexdigest(),
    )
    selected: list[s6c5.Candidate] = []
    for predicate in (
        lambda item: item.disposition.startswith("SURFACE_OR_INTERFACE"),
        lambda item: item.site.realised_form == "SURFACE_LAGOON_SETTLEMENT",
    ):
        match = next((item for item in ordered if predicate(item)), None)
        if match is not None and match not in selected:
            selected.append(match)
    selected.extend(item for item in ordered if item not in selected)
    selected = selected[:5]
    evidence = zarr.open_group(str(output_dir / "candidate_evidence_10m.zarr"), mode="r")
    rasters = s6c.RasterStack(authority_descriptor)
    topology = s6c.ExactSurfaceIndex(
        Path(s6c.SOURCES["exact_surface_registry"]["path"]),
        Path(s6c.SOURCES["fragment_barony_assignment"]["path"]),
    )
    vectors = s6c.VectorStack("reduced")
    max_elevation_difference = 0.0
    max_slope_difference = 0.0
    max_hydrology_difference = 0.0
    max_score_difference = 0.0
    max_r1_difference = 0.0
    exact_layer_failures: list[str] = []
    result_failures: list[str] = []
    reference_comparison: dict[str, Any] | None = None
    try:
        for sample_index, candidate in enumerate(selected):
            spec = TileSpec(
                candidate.tile_id,
                candidate.tile_parent_row0,
                candidate.tile_parent_col0,
                s6c5.CORE_PARENT_CELLS,
                s6c5.CORE_PARENT_CELLS,
                halo_cells=s6c5.HALO_FINE_CELLS,
            )
            support_row0 = candidate.tile_parent_row0 - s6c5.PARENT_SUPPORT_CELLS
            support_col0 = candidate.tile_parent_col0 - s6c5.PARENT_SUPPORT_CELLS
            support_row1 = candidate.tile_parent_row0 + s6c5.CORE_PARENT_CELLS + s6c5.PARENT_SUPPORT_CELLS
            support_col1 = candidate.tile_parent_col0 + s6c5.CORE_PARENT_CELLS + s6c5.PARENT_SUPPORT_CELLS
            parent_data = rasters.terrain.read_block(
                support_row0, support_col0,
                support_row1 - support_row0, support_col1 - support_col0,
            )
            parent = ParentRasterWindow(parent_data, support_row0, support_col0, s6c5.GRID)
            hashes = {
                "terrain_authority_root": str(authority_descriptor["root_hash"]),
                "stage6c5_semantic_key": candidate.semantic_key,
            }
            fast = refine_terrain_fast(parent, spec, s6c5.TERRAIN_RECIPE, hashes)
            if sample_index == 0:
                trusted = refine_terrain(parent, spec, s6c5.TERRAIN_RECIPE, hashes)
                comparison = compare_terrain_tiles(trusted, fast)
                reference_comparison = {
                    "passed": comparison.passed,
                    "exact_array_match": comparison.exact_array_match,
                    "arrays_within_tolerance": comparison.arrays_within_tolerance,
                    "metadata_within_tolerance": comparison.metadata_within_tolerance,
                    "differences": list(comparison.differences),
                    "array_max_abs_differences": dict(comparison.array_max_abs_differences),
                }
            core = spec.core_slice
            elevation = fast.arrays["elevation_10m"][core]
            slope = np.degrees(
                np.arctan(fast.arrays["local_gradient_magnitude_10m"][core])
            ).astype(np.float32)
            ro = (candidate.source_parent_row0 - candidate.tile_parent_row0) * 10
            co = (candidate.source_parent_col0 - candidate.tile_parent_col0) * 10
            elevation = elevation[ro:ro + 100, co:co + 100]
            slope = slope[ro:ro + 100, co:co + 100]
            stored_elevation = np.asarray(evidence["elevation_m"][candidate.index])
            stored_slope = np.asarray(evidence["slope_deg"][candidate.index])
            max_elevation_difference = max(
                max_elevation_difference,
                float(np.nanmax(np.abs(elevation - stored_elevation))),
            )
            max_slope_difference = max(
                max_slope_difference,
                float(np.nanmax(np.abs(slope - stored_slope))),
            )

            # Recompute the non-terrain layers from source evidence instead of
            # trusting the persisted Zarr/SQLite products.
            fine_candidate_row0 = candidate.source_parent_row0 * s6c5.FINE_PER_PARENT
            fine_candidate_col0 = candidate.source_parent_col0 * s6c5.FINE_PER_PARENT
            barony = s6c5.rasterize_exact_surface_10m(
                topology, fine_candidate_row0, fine_candidate_col0, 100, 100
            )
            stored_barony = np.asarray(evidence["barony_id"][candidate.index])
            if not np.array_equal(barony, stored_barony):
                exact_layer_failures.append(candidate.site.settlement_id + ":barony")
            parent_candidate = rasters.read_block(
                candidate.source_parent_row0,
                candidate.source_parent_col0,
                s6c5.CANDIDATE_PARENT_CELLS,
                s6c5.CANDIDATE_PARENT_CELLS,
            )
            sea = s6c5.repeat_parent(parent_candidate["sea"]).astype(np.uint8)
            wetland = s6c5.repeat_parent(parent_candidate["wetland"]).astype(np.uint8)
            seren = s6c5.repeat_parent(parent_candidate["seren"]).astype(np.uint8)
            flood = s6c5.repeat_parent(parent_candidate["flood_exposure"]).astype(np.float64)
            distances, _ = s6c5.exact_water_evidence(vectors, candidate)
            form_water = distances["active"]
            if candidate.site.realised_form == "SURFACE_LAGOON_SETTLEMENT":
                form_water = np.minimum.reduce(
                    (distances["active"], distances["special"], distances["lake"])
                )
                form_water = np.where(seren > 0, 0.0, form_water)
            for layer, recomputed in (
                ("active_water_distance_km", distances["active"]),
                ("form_surface_water_distance_km", form_water),
                ("perennial_water_distance_km", distances["perennial"]),
            ):
                stored = np.asarray(evidence[layer][candidate.index])
                max_hydrology_difference = max(
                    max_hydrology_difference,
                    float(np.nanmax(np.abs(recomputed - stored))),
                )

            surface = barony > 0
            same_barony = (
                surface
                if candidate.site.barony_id is None
                else barony == candidate.site.barony_id
            )
            valid, domain_fit, ordinary_surface_fallback = s6c.domain_candidate_mask(
                candidate.site,
                same_barony.ravel(),
                surface.ravel(),
                sea.ravel(),
                wetland.ravel(),
                seren.ravel(),
                {key: value.ravel() for key, value in distances.items()},
            )
            valid = valid.reshape(100, 100)
            domain_fit = domain_fit.reshape(100, 100)
            if not np.array_equal(
                valid.astype(np.uint8),
                np.asarray(evidence["valid_domain"][candidate.index]),
            ):
                exact_layer_failures.append(candidate.site.settlement_id + ":domain")
            policy = s6c5.rules.score_policy(candidate.profile)
            scores = s6c.candidate_cell_scores(
                slope.ravel(),
                form_water.ravel(),
                flood.ravel(),
                domain_fit.ravel(),
                valid.ravel(),
                policy,
            ).reshape(100, 100)
            stored_scores = np.asarray(evidence["site_score"][candidate.index])
            max_score_difference = max(
                max_score_difference,
                float(np.max(np.abs(scores - stored_scores))),
            )

            parent_core = rasters.read_block(
                candidate.tile_parent_row0,
                candidate.tile_parent_col0,
                s6c5.CORE_PARENT_CELLS,
                s6c5.CORE_PARENT_CELLS,
            )
            full_fine_row0 = candidate.tile_parent_row0 * s6c5.FINE_PER_PARENT
            full_fine_col0 = candidate.tile_parent_col0 * s6c5.FINE_PER_PARENT
            full_barony = s6c5.rasterize_exact_surface_10m(
                topology,
                full_fine_row0,
                full_fine_col0,
                s6c5.FINE_CORE_CELLS,
                s6c5.FINE_CORE_CELLS,
            )
            full_sea = s6c5.repeat_parent(parent_core["sea"])
            full_wetland = s6c5.repeat_parent(parent_core["wetland"])
            full_seren = s6c5.repeat_parent(parent_core["seren"])
            full_flood = s6c5.repeat_parent(parent_core["flood_exposure"])
            full_elevation = fast.arrays["elevation_10m"][core]
            full_slope = np.degrees(
                np.arctan(fast.arrays["local_gradient_magnitude_10m"][core])
            ).astype(np.float32)
            resolved_policy, _ = s6c5.rules._resolved_policy(
                candidate.profile["realised_settlement_form"],
                candidate.profile["effective_vertical_domain"],
                candidate.profile["haus_id"],
            )
            slope_limit = float(policy["components"]["TERRAIN_SUPPORT"].get("p1") or 45.0)
            dev = s6c.developable_mask(
                candidate.site,
                full_barony,
                {
                    "slope": full_slope,
                    "sea": full_sea,
                    "seren": full_seren,
                    "wetland": full_wetland,
                    "flood_exposure": full_flood,
                },
                slope_limit,
                resolved_policy["flood_tolerance"],
                ordinary_surface_fallback,
            )
            fine_rows, fine_cols = np.meshgrid(
                np.arange(full_fine_row0, full_fine_row0 + s6c5.FINE_CORE_CELLS),
                np.arange(full_fine_col0, full_fine_col0 + s6c5.FINE_CORE_CELLS),
                indexing="ij",
            )
            circle = (
                (fine_cols * s6c5.FINE_CELL_KM + 0.005 - candidate.site.x) ** 2
                + (fine_rows * s6c5.FINE_CELL_KM + 0.005 - candidate.site.y) ** 2
                <= 1.0
            )
            develop_r1 = float((dev * circle).sum() * s6c5.FINE_CELL_KM ** 2)
            persisted = result_by_id[candidate.site.settlement_id]
            max_r1_difference = max(
                max_r1_difference,
                abs(develop_r1 - float(persisted["developable_area_r1_km2_10m"])),
            )
            direction, _ = s6c5.expansion_direction_10m(
                dev * circle, full_fine_row0, full_fine_col0, candidate.site
            )
            if direction != persisted["expansion_direction_r1_10m"]:
                result_failures.append(candidate.site.settlement_id + ":direction")

            best_parent, _, _, parent_gap = s6c5.parent_score_summary(scores)
            expected_anchor: tuple[float, float] | None = None
            if candidate.disposition.startswith("SURFACE_OR_INTERFACE"):
                expected_status = "SURFACE_OR_INTERFACE_CONTEXT_ONLY_3D_DEFERRED_NO_RELOCATION"
            elif best_parent is None:
                expected_status = "NO_VALID_10M_SUPPORT_OFFICIAL_COORDINATE_UNCHANGED"
            else:
                br, bc = divmod(best_parent, 10)
                block = scores[br * 10:(br + 1) * 10, bc * 10:(bc + 1) * 10]
                order = np.argsort(block.ravel())[::-1]
                first, second = float(block.ravel()[order[0]]), float(block.ravel()[order[1]])
                parent_clear = parent_gap is not None and parent_gap >= s6c5.PARENT_SCORE_CLEAR_GAP
                child_clear = first - second >= s6c5.CELL_SCORE_CLEAR_GAP
                if parent_clear and child_clear:
                    rr, cc = divmod(int(order[0]), 10)
                    expected_anchor = (
                        (candidate.source_parent_col0 * 10 + bc * 10 + cc) * s6c5.FINE_CELL_KM + 0.005,
                        (candidate.source_parent_row0 * 10 + br * 10 + rr) * s6c5.FINE_CELL_KM + 0.005,
                    )
                    expected_status = "MODELLED_10M_PREFERENCE_CLEAR_PARENT_SEPARATION_OFFICIAL_COORDINATE_UNCHANGED"
                elif parent_clear:
                    expected_status = "MODELLED_100M_PARENT_CLEAR_MULTIPLE_EQUIVALENT_10M_CELLS_OFFICIAL_COORDINATE_UNCHANGED"
                else:
                    expected_status = "MODELLED_10M_PREFERENCE_LOW_SEPARATION_OFFICIAL_COORDINATE_UNCHANGED"
            if expected_status != persisted["selection_status"]:
                result_failures.append(candidate.site.settlement_id + ":selection")
            actual_anchor = (
                None
                if persisted["modelled_preferred_x_km"] is None
                else (
                    float(persisted["modelled_preferred_x_km"]),
                    float(persisted["modelled_preferred_y_km"]),
                )
            )
            if expected_anchor != actual_anchor:
                result_failures.append(candidate.site.settlement_id + ":anchor")
    finally:
        rasters.close()
    checks.require(
        "real_source_fast_vs_reference_sample",
        bool(reference_comparison and reference_comparison["passed"]),
        actual=reference_comparison,
    )
    checks.require(
        "deterministic_elevation_sample",
        max_elevation_difference <= 5e-5,
        actual=max_elevation_difference,
    )
    checks.require(
        "deterministic_slope_sample",
        max_slope_difference <= 5e-5,
        actual=max_slope_difference,
    )
    checks.require(
        "deterministic_exact_layers_sample",
        not exact_layer_failures,
        actual=exact_layer_failures,
    )
    checks.require(
        "deterministic_hydrology_sample",
        max_hydrology_difference <= 5e-5,
        actual=max_hydrology_difference,
    )
    checks.require(
        "deterministic_score_sample",
        max_score_difference <= 5e-5,
        actual=max_score_difference,
    )
    checks.require(
        "deterministic_r1_sample",
        max_r1_difference <= 5e-8,
        actual=max_r1_difference,
    )
    checks.require(
        "deterministic_selection_sample",
        not result_failures,
        actual=result_failures,
    )
    return {
        "sample_ids": [candidate.site.settlement_id for candidate in selected],
        "max_elevation_abs_difference": max_elevation_difference,
        "max_slope_abs_difference": max_slope_difference,
        "max_hydrology_abs_difference": max_hydrology_difference,
        "max_score_abs_difference": max_score_difference,
        "max_r1_abs_difference_km2": max_r1_difference,
        "exact_layer_failures": exact_layer_failures,
        "result_failures": result_failures,
        "reference_comparison": reference_comparison,
    }


def validate(output_dir: Path, *, rerun_sample: bool = True) -> dict[str, Any]:
    checks = Checks()
    output_db = output_dir / s6c5.OUTPUT_DB_NAME
    output_gpkg = output_dir / s6c5.OUTPUT_GPKG_NAME
    evidence_path = output_dir / "candidate_evidence_10m.zarr"
    checks.require("output_sqlite_exists", output_db.is_file(), actual=str(output_db))
    checks.require("output_gpkg_exists", output_gpkg.is_file(), actual=str(output_gpkg))
    checks.require("candidate_zarr_exists", evidence_path.is_dir(), actual=str(evidence_path))
    if not (output_db.is_file() and output_gpkg.is_file() and evidence_path.is_dir()):
        raise RuntimeError("Stage 6C.5 output is incomplete")

    parent = readonly(s6c5.PARENT_DB)
    output = readonly(output_db)
    try:
        checks.check("output_sqlite_integrity", output.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        try:
            stage6d_view = s6d_schema.validate_view(
                output, expected_rows=s6c5.EXPECTED_CANDIDATES
            )
        except Exception as error:
            checks.require(
                "stage6c5_stage6d_inputs_contract",
                False,
                actual=f"{type(error).__name__}: {error}",
            )
        else:
            checks.require(
                "stage6c5_stage6d_inputs_contract",
                True,
                actual={
                    "row_count": stage6d_view["row_count"],
                    "column_count": stage6d_view["column_count"],
                },
            )
        for table in (
            "settlement", "stage6c_source_manifest", "stage6c_profile_catalog",
            "stage6c_site_assessment",
        ):
            checks.check(
                f"parent_table_parity_{table}",
                s6c.table_digest(output, table),
                s6c.table_digest(parent, table),
            )
        candidate_rows = output.execute(
            "SELECT * FROM stage6c5_candidate_registry ORDER BY settlement_id"
        ).fetchall()
        result_rows = output.execute(
            "SELECT * FROM stage6c5_site_refinement ORDER BY settlement_id"
        ).fetchall()
        tile_rows = output.execute(
            "SELECT * FROM stage6c5_tile_manifest ORDER BY settlement_id"
        ).fetchall()
        ids = [str(row["settlement_id"]) for row in candidate_rows]
        checks.check("candidate_count", len(candidate_rows), s6c5.EXPECTED_CANDIDATES)
        checks.check(
            "candidate_id_digest",
            hashlib.sha256(canonical_json(ids).encode("utf-8")).hexdigest(),
            s6c5.CANDIDATE_LIST_SHA256,
        )
        checks.check(
            "tier_counts",
            dict(Counter(row["functional_tier"] for row in candidate_rows)),
            {
                "FT0_HAUS_PRINCIPAL_SITE": s6c5.EXPECTED_FT0,
                "FT1_MAJOR_REGIONAL_HUB": s6c5.EXPECTED_FT1,
            },
        )
        checks.check(
            "disposition_counts",
            dict(Counter(row["disposition"] for row in candidate_rows)),
            {
                "COMPLETE_2D_REFINEMENT": s6c5.EXPECTED_2D,
                "SURFACE_OR_INTERFACE_CONTEXT_ONLY_3D_DEFERRED": s6c5.EXPECTED_3D,
            },
        )
        checks.check("result_count", len(result_rows), s6c5.EXPECTED_CANDIDATES)
        checks.check("tile_count", len(tile_rows), s6c5.EXPECTED_CANDIDATES)
        checks.check(
            "official_coordinates_unchanged",
            output.execute(
                """SELECT COUNT(*) FROM stage6c5_site_refinement r
                   JOIN settlement s USING(settlement_id)
                   WHERE r.official_coordinate_modified<>0
                      OR r.official_x_km<>s.display_x_km
                      OR r.official_y_km<>s.display_y_km"""
            ).fetchone()[0],
            0,
        )
        checks.check(
            "specialist_3d_has_no_model_anchor_or_new_capacity",
            output.execute(
                """SELECT COUNT(*) FROM stage6c5_site_refinement
                   WHERE disposition LIKE 'SURFACE_OR_INTERFACE%'
                     AND (modelled_preferred_x_km IS NOT NULL
                       OR modelled_preferred_y_km IS NOT NULL
                       OR capacity_support_score_10m IS NOT NULL
                       OR access_support_score_10m IS NOT NULL)"""
            ).fetchone()[0],
            0,
        )
        checks.check(
            "specialist_3d_count",
            output.execute(
                "SELECT COUNT(*) FROM stage6c5_site_refinement WHERE review_status='DEFERRED_SPECIALIST_3D'"
            ).fetchone()[0],
            s6c5.EXPECTED_3D,
        )
        checks.check(
            "resolution_labels",
            output.execute(
                """SELECT COUNT(*) FROM stage6c5_site_refinement
                   WHERE model_cell_size_m<>10
                      OR terrain_effective_evidence_resolution_m<>100
                      OR exact_vector_sampling_resolution_m<>10
                      OR terrain_status NOT LIKE 'MODELLED_10M%'
                      OR hydrology_status<>'CURRENT_CORRECTED_VECTOR_AXES_SAMPLED_AT_10M_NOT_REGENERATED'"""
            ).fetchone()[0],
            0,
        )
        checks.check(
            "metric_ranges",
            output.execute(
                """SELECT COUNT(*) FROM stage6c5_site_refinement
                   WHERE candidate_support_fraction NOT BETWEEN 0 AND 1
                      OR land_fraction_10m NOT BETWEEN 0 AND 1
                      OR wetland_fraction_10m NOT BETWEEN 0 AND 1
                      OR flood_exposure_10m NOT BETWEEN 0 AND 1
                      OR candidate_valid_cell_count NOT BETWEEN 0 AND candidate_cell_count
                      OR parent_score_clear_gap < 0""".replace("parent_score_clear_gap", "best_parent_score_gap")
            ).fetchone()[0],
            0,
        )
        checks.check(
            "tile_parent_aggregation",
            output.execute(
                """SELECT COUNT(*) FROM stage6c5_tile_manifest
                   WHERE parent_aggregation_max_abs_error_m>0.0051
                      OR broad_parent_aggregation_max_abs_error_m>1e-9
                      OR broad_gradient_direction_consistent_fraction<0.90
                      OR local_gradient_direction_consistent_fraction<0.90"""
            ).fetchone()[0],
            0,
        )
        checks.check(
            "complete_r1_context_and_dynamic_tile_size",
            output.execute(
                """SELECT COUNT(*) FROM stage6c5_tile_manifest t
                   JOIN settlement s USING(settlement_id)
                   WHERE t.core_parent_height<>?
                      OR t.core_parent_width<>?
                      OR t.fine_core_cell_count<>?
                      OR t.core_parent_col0*0.1>s.display_x_km-1.0
                      OR (t.core_parent_col0+t.core_parent_width)*0.1<s.display_x_km+1.0
                      OR t.core_parent_row0*0.1>s.display_y_km-1.0
                      OR (t.core_parent_row0+t.core_parent_height)*0.1<s.display_y_km+1.0""",
                (
                    s6c5.CORE_PARENT_CELLS,
                    s6c5.CORE_PARENT_CELLS,
                    s6c5.FINE_CORE_CELLS * s6c5.FINE_CORE_CELLS,
                ),
            ).fetchone()[0],
            0,
        )
        checks.check(
            "precise_anchor_only_when_both_separations_clear",
            output.execute(
                """SELECT COUNT(*) FROM stage6c5_site_refinement
                   WHERE (modelled_preferred_x_km IS NOT NULL
                       OR modelled_preferred_y_km IS NOT NULL)
                     AND selection_status<>'MODELLED_10M_PREFERENCE_CLEAR_PARENT_SEPARATION_OFFICIAL_COORDINATE_UNCHANGED'"""
            ).fetchone()[0],
            0,
        )
    finally:
        output.close()
        parent.close()

    gpkg = readonly(output_gpkg)
    try:
        checks.check("output_gpkg_integrity", gpkg.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        for table in (
            "stage6c5_candidate_registry", "stage6c5_tile_manifest", "stage6c5_site_refinement",
        ):
            checks.check(
                f"gpkg_{table}_count",
                gpkg.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0],
                s6c5.EXPECTED_CANDIDATES,
            )
            checks.check(
                f"gpkg_{table}_registered",
                gpkg.execute(
                    "SELECT data_type FROM gpkg_contents WHERE table_name=?", (table,)
                ).fetchone()[0],
                "attributes",
            )
    finally:
        gpkg.close()

    evidence = zarr.open_group(str(evidence_path), mode="r")
    checks.check("zarr_candidate_count", evidence.attrs["candidate_count"], s6c5.EXPECTED_CANDIDATES)
    checks.check("zarr_method", evidence.attrs["method"], s6c5.METHOD)
    checks.check("zarr_candidate_digest", evidence.attrs["candidate_list_sha256"], s6c5.CANDIDATE_LIST_SHA256)
    checks.check("zarr_site_complete", int(np.asarray(evidence["site_complete"][:]).sum()), s6c5.EXPECTED_CANDIDATES)
    for name in s6c5.zarr_arrays():
        checks.check(f"zarr_shape_{name}", tuple(evidence[name].shape), (s6c5.EXPECTED_CANDIDATES, 100, 100))

    output = readonly(output_db)
    try:
        tile_rows = output.execute(
            "SELECT * FROM stage6c5_tile_manifest ORDER BY settlement_id"
        ).fetchall()
        bundle_digest, frame_count, frame_bytes = validate_bundles(checks, output_dir, tile_rows)
        metric_mismatches: list[str] = []
        rows = output.execute(
            "SELECT * FROM stage6c5_site_refinement ORDER BY settlement_id"
        ).fetchall()
        index_by_id = {
            row["settlement_id"]: int(row["zarr_index"])
            for row in output.execute(
                "SELECT settlement_id,zarr_index FROM stage6c5_candidate_registry"
            )
        }
        for row in rows:
            index = index_by_id[row["settlement_id"]]
            valid = np.asarray(evidence["valid_domain"][index], dtype=bool)
            if not valid.any():
                valid = np.ones((100, 100), dtype=bool)
            comparisons = {
                "terrain_elevation_m_10m": float(np.median(np.asarray(evidence["elevation_m"][index], dtype=np.float64)[valid])),
                "terrain_slope_deg_10m": float(np.median(np.asarray(evidence["slope_deg"][index], dtype=np.float64)[valid])),
                "surface_water_distance_km_10m": float(np.median(np.asarray(evidence["form_surface_water_distance_km"][index], dtype=np.float64)[valid])),
                "perennial_distance_km_10m": float(np.median(np.asarray(evidence["perennial_water_distance_km"][index], dtype=np.float64)[valid])),
            }
            for field, actual in comparisons.items():
                if row[field] is None or not math.isclose(actual, float(row[field]), abs_tol=5e-5):
                    metric_mismatches.append(f"{row['settlement_id']}:{field}:{actual}!={row[field]}")
        checks.require("zarr_sqlite_metric_agreement", not metric_mismatches, actual=metric_mismatches[:10])
    finally:
        output.close()

    sample_report = deterministic_sample(checks, output_dir, output_db) if rerun_sample else None
    counts = Counter(row["status"] for row in checks.rows)
    report = {
        "schema": "diadem.stage6c5-independent-validation.v1",
        "validated_utc": utc_now(),
        "status": "PASS" if counts["FAIL"] == 0 else "FAIL",
        "counts": dict(counts),
        "bundle_aggregate_sha256": bundle_digest,
        "bundle_frame_count": frame_count,
        "bundle_frame_bytes": frame_bytes,
        "deterministic_sample": sample_report,
        "checks": checks.rows,
    }
    atomic_json(output_dir / "INDEPENDENT_VALIDATION.json", report)
    lines = [
        "STAGE 6C.5 INDEPENDENT VALIDATION",
        f"Status: {report['status']}",
        f"PASS={counts['PASS']} WARN={counts['WARN']} FAIL={counts['FAIL']}",
        "",
    ]
    lines.extend(
        f"[{row['status']}] {row['name']} actual={row['actual']} expected={row['expected']} {row['detail']}"
        for row in checks.rows
    )
    (output_dir / "INDEPENDENT_VALIDATION.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    manifest_files = [
        output_db,
        output_gpkg,
        output_dir / "BUILD_SUMMARY.json",
        output_dir / "STAGE6C5_CANDIDATE_MANIFEST.json",
        output_dir / "README_FIRST.md",
        output_dir / "STAGE6C5_METHOD_AND_LIMITS.md",
        output_dir / "INDEPENDENT_VALIDATION.json",
        output_dir / "INDEPENDENT_VALIDATION.txt",
    ]
    atomic_json(output_dir / "OUTPUT_MANIFEST.json", {
        "schema": "diadem.stage6c5-output-manifest.v1",
        "created_utc": utc_now(),
        "canon_status": s6c5.CANON_STATUS,
        "candidate_list_sha256": s6c5.CANDIDATE_LIST_SHA256,
        "bundle_aggregate_sha256": bundle_digest,
        "files": [
            {
                "relative_path": path.relative_to(output_dir).as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            for path in manifest_files if path.is_file()
        ],
        "zarr": {
            "relative_path": "candidate_evidence_10m.zarr",
            "shape": [s6c5.EXPECTED_CANDIDATES, 100, 100],
            "site_complete": int(np.asarray(evidence["site_complete"][:]).sum()),
        },
        "validation_status": report["status"],
    })
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=s6c5.DEFAULT_OUTPUT_DIR)
    parser.add_argument("--no-rerun-sample", action="store_true")
    args = parser.parse_args(argv)
    report = validate(args.output_dir.resolve(), rerun_sample=not args.no_rerun_sample)
    print(canonical_json({
        "status": report["status"],
        "counts": report["counts"],
        "report": str(args.output_dir.resolve() / "INDEPENDENT_VALIDATION.json"),
    }))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
