#!/usr/bin/env python3
"""Build the additive Stage 6C 100 m spatial-context successor to Province DB V3.

The inherited registry, names, coordinates and geometries are immutable.  This
builder evaluates every retained identity against one locked generation of the
editable 100 m Zarr terrain authority, exact surface topology, corrected V4.2
hydrology and approved non-terrain local overrides.  The old terrain TIFFs are
verified only as sealed generation-zero lineage and are never recomposed here.
It writes review-only analytical attributes; it does not promote canon or draw
settlement footprints.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import shutil
import sqlite3
import struct
import sys
import threading
import time
from collections import Counter, defaultdict, deque
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

import numpy as np
import rasterio
from rasterio.windows import Window
import shapely
from shapely.geometry import LineString, MultiLineString, MultiPolygon, Polygon, shape

import stage6c_rules as rules
import generation_runtime as runtime
import algorithm_policy
from source_catalogue import catalogue_path, generator_root, source_path
from stage6c_terrain_authority import (
    TerrainAuthorityReader,
    identity_component as terrain_authority_identity,
    verify_authority as verify_terrain_authority,
)
from verified_source_hash_cache import (
    SCHEMA as SOURCE_HASH_CACHE_SCHEMA,
    VerifiedSourceHashCache,
)


ROOT = generator_root()
DATE = "2026-08-30"
METHOD = "STAGE6C_100M_SPATIAL_CONTEXT_V2"
CANON_STATUS = "WORKING_PROPOSAL_REVIEW_ONLY_NOT_CANON"
GRID_NOTE = "LOCAL_KILOMETRE_GRID; MAP NORTH = DECREASING Y"
ANALYSIS_BLOCK_SIZE = 1_200  # 120 km; amortises tiled-raster I/O while retaining 5 km halos.
RASTER_PREFETCH_WORKERS = 4
RASTER_PREFETCH_DEPTH = 4
RASTER_PREFETCH_MEMORY_MIB = 1024
# Conservative prepared-group/transient-array allowance. This limits the
# prefetch buffers, not the independently resident source indexes or process.
RASTER_GROUP_ESTIMATED_BYTES = 128 * 1024 * 1024
WATER_INDEX_CHUNK_SEGMENTS = 16
WATER_QUERY_MODES = ("reference", "chunked", "reduced")
WATER_QUERY_DEFAULT = "reduced"

BASE_DB = source_path("stage6b_parent_sqlite")
BASE_GPKG = source_path("stage6b_province_gpkg")
BASE_DIR = BASE_DB.parent
OUT_DIR = ROOT / "generated_outputs/Diadem_Province_Database_V4_STAGE6C_100M_SPATIAL_CONTEXT_WORKING_2026-08-30"
OUT_DB = OUT_DIR / "Diadem_Province_Database_V4_STAGE6C_100M_SPATIAL_CONTEXT_WORKING_2026-08-30.sqlite"
OUT_GPKG = OUT_DIR / "Diadem_Province_Map_Layer_V4_STAGE6C_100M_SPATIAL_CONTEXT_WORKING_2026-08-30.gpkg"
EXPORT_DIR = OUT_DIR / "review_exports"
WORK_DIR = ROOT / "runtime_work/province_stage6c_100m_2026-08-30"
SOURCE_HASH_CACHE_PATH = ROOT / "runtime_work/source_hash_cache/stage6c_static_sources.json"

SOURCES: dict[str, dict[str, Any]] = {
    "stage6b_parent_sqlite": {
        "path": source_path("stage6b_parent_sqlite"),
        "sha256": "2d3b8b97966c033cbf80940f0886998f885fcac14e45137745f683302d7a4aad",
        "count": 31_271,
        "status": "VERIFIED_STAGE6B_WORKING_PARENT",
        "role": "IMMUTABLE_REGISTRY_PARENT",
    },
    "stage6b_parent_gpkg": {
        "path": source_path("stage6b_province_gpkg"),
        "sha256": "dd5e29ac5d85c74abb461a6a7249be94bf4da0ecdf2cf80d1af30d7454e9a37e",
        "status": "WORKING_PROPOSAL_REVIEW_ONLY_NOT_CANON",
        "role": "OPERATIONAL_JOIN_AND_GEOMETRY_PARENT",
    },
    "terrain_100m_sealed_lineage": {
        "path": source_path("terrain_d31_100m"),
        "sha256": "fbaa09175c039d68993a83dbf2df3cd5835b8128386d7bc981eb13958907f3a7",
        "status": "SEALED_LINEAGE_ONLY_NOT_OPENED_FOR_RUNTIME_TERRAIN",
        "role": "GENERATION_0_FULL_FRAME_TIFF_LINEAGE",
        "shape": (18_600, 22_000),
    },
    "stillklinge_terrain_100m_sealed_lineage": {
        "path": source_path("stillklinge_terrain_100m"),
        "sha256": "dc5af05d10e212c26daf15daf8781334bfa80b626b0f1217c84f2bbdaf0b581f",
        "status": "SEALED_LINEAGE_ONLY_ALREADY_COMPOSED_IN_TERRAIN_AUTHORITY",
        "role": "GENERATION_0_STILLKLINGE_TIFF_LINEAGE",
        "shape": (3_900, 1_550),
    },
    "obsidian_sea_mask": {
        "path": source_path("obsidian_sea_mask_100m"),
        "sha256": "83e09b5fe4f3007c1e9600eee4870e4d42242f0bdcf36046411987bfb90ff943",
        "status": "BOUND_H1_1_SEA_MASK",
        "role": "SEA_DOMAIN_MASK_100M",
        "shape": (18_600, 22_000),
    },
    "moorwandler_core_wetland": {
        "path": source_path("moorwandler_core_wetland_100m"),
        "sha256": "7d53543784a45a893eee7fab5f2b531f8d229fb3d30108524c48fa637e7a3a3f",
        "status": "CURRENT_PROTECTED_IRREGULAR_MASK_REVIEW_ONLY",
        "role": "MOORWANDLER_CORE_WETLAND_100M",
        "shape": (18_600, 22_000),
    },
    "serenakrone_water_mask": {
        "path": source_path("serenakrone_water_100m"),
        "sha256": "5271ca6aa9582682ccb88c56815371af213dc9180d1941db85a23278c2b0293c",
        "status": "CURRENT_IRREGULAR_LAGOON_MASK_REVIEW_ONLY",
        "role": "SERENAKRONE_SURFACE_WATER_100M",
        "shape": (18_600, 22_000),
    },
    "flood_candidates_100m": {
        "path": source_path("h22_flood_candidates_100m"),
        "sha256": "535a7165ba03ffb66e19c6aa1ad94ac21d10fbb5edc096d1c4649d1ecafc3e8e",
        "status": "H2_2_GEOMORPHIC_CANDIDATES_REVIEW_ONLY",
        "role": "FULL_FRAME_FLOOD_CONTEXT_100M",
        "shape": (18_600, 22_000),
    },
    "stillklinge_flood_override": {
        "path": source_path("stillklinge_flood_100m"),
        "sha256": "b2e1b76f5833c1d407e69ef57ab091488d35087358b8e3ace7ab0e145f201bde",
        "status": "APPROVED_AUTHORITATIVE_STILLKLINGE_REPLACEMENT_BY_APPROVAL_RECORD",
        "role": "LOCAL_FLOOD_OVERRIDE_100M",
        "shape": (3_900, 1_550),
    },
    "active_major": {
        "path": source_path("v42_active_major"),
        "sha256": "228f42f37599b6b99ce747c160e7a76574a0fe63623e8b791a7ff70c4a65eca3",
        "count": 30,
        "status": "V4_2_CURRENT_REVIEW_ONLY; STILLKLINGE_REPAIRED_AXES_INCLUDED",
        "role": "ACTIVE_MAJOR_RIVER_AXES",
    },
    "active_major_bed_profiles": {
        "path": source_path("v42_active_major_bed_profiles"),
        "sha256": "cb597ba4e4e6ceccc1efd3418f104b4cc2622fc301dea49dee4ca3e9b10d4dd4",
        "count": 30,
        "status": "V4_2_ACTIVE_MONOTONE_BED_PROFILES_REVIEW_ONLY_NOT_CANON",
        "role": "ACTIVE_MAJOR_RIVER_VERTICAL_CONTROL_BY_ROUTE_ID_AND_CHAINAGE",
    },
    "parent_minor_lineage": {
        "path": source_path("v42_active_minor"),
        "sha256": "707740a4a9dd488d954a2e6cbd7848f81b6fc7cbc525f59fc892c7c8986d2429",
        "count": 3_177,
        "status": "V4_2_PARENT_PRESERVING_LINEAGE_ONLY; NOT_DISTANCE_AUTHORITY",
        "role": "PARENT_MINOR_EXACT_CONTACT_LINEAGE; VECTOR_DISTANCE_AUTHORIZED_FALSE",
    },
    "d3_feeder_raw": {
        "path": source_path("v42_d3_raw"),
        "sha256": "78af082efd432e7e5408d01aec058ed1777743086ba88fd833ae033dab7c4a06",
        "count": 16_468,
        "defer_feature_count_to_runtime": True,
        "status": "SEALED_V4_2_RAW_D3_FEEDER_GEOMETRY_REVIEW_ONLY_NOT_CANON",
        "role": "V4_2_FEEDER_GEOMETRY; STILLKLINGE_ROWS_REPLACED_BY_LOCAL_112",
    },
    "d3_feeder_enriched": {
        "path": source_path("v42_d3_enriched"),
        "sha256": "f2c219f1ef738e512a7b49673b4005afe64659103eb4360629dea77cfc506337",
        "count": 16_468,
        "defer_feature_count_to_runtime": True,
        "status": "SEALED_V4_2_D3_CLASSIFICATION_REVIEW_ONLY_NOT_CANON",
        "role": "V4_2_FEEDER_PERSISTENCE_AND_STRAHLER_CLASSIFICATION",
    },
    "stillklinge_support": {
        "path": source_path("v42_stillklinge_local_112"),
        "sha256": "24e3509048bd791bdf0e6d10dd5a8df5051f8280d0df581251ba5cc27acd83f9",
        "count": 112,
        "status": "21_APPROVED_FLOOR_PLUS_91_REVIEW_ONLY_UNRESOLVED_PERSISTENCE",
        "role": "STILLKLINGE_SUPPORT_EVIDENCE_SUBSET",
    },
    "stillklinge_repaired_major_evidence": {
        "path": source_path("v42_stillklinge_repaired_major"),
        "sha256": "c44b15dbb855702230a7bb2bbf809c5f399792a23a9e589e4bce25c070f0d980",
        "count": 2,
        "status": "APPROVED_CANDIDATE_B_CORE_IN_REVIEW_ONLY_V4_2_ASSEMBLY",
        "role": "STILLKLINGE_REPAIRED_MAJOR_LINEAGE_EVIDENCE; GEOMETRY_IDENTICAL_TO_ACTIVE_MAJOR_SUBSET",
    },
    "special_controls": {
        "path": source_path("v42_active_special"),
        "sha256": "97453c76cb55a42dce7329e1c757d3f25c1d3bee29854fda94ee9287ea101b3c",
        "count": 10,
        "status": "V4_2_ACTIVE_SPECIAL_CONTROLS_REVIEW_ONLY",
        "role": "SPECIAL_WATER_GEOMETRY",
    },
    "coastline": {
        "path": source_path("coastline"),
        "sha256": "971ad37396b18c11b5287c854f3546c168e9bd09226b23948ee23cdf0479569e",
        "count": 1,
        "status": "BOUND_H1_1_COASTLINE",
        "role": "OBSIDIAN_SEA_COASTLINE",
    },
    "lake_permanent_l1": {
        "path": source_path("h22_active_l1_lakes"),
        "sha256": "084cb35aa4c35989c9b0428344ea8bdccc7544c3afb87b0cc4a6b4798e0b27d5",
        "count": 486,
        "status": "H2_2_RESOLVED_REVIEW_ONLY; MAXIMUM_SPILL_SILL_FOOTPRINT",
        "role": "PERMANENT_LAKE_CANDIDATES",
    },
    "lake_permanent_legacy": {
        "path": source_path("h22_active_legacy_c1_lakes"),
        "sha256": "0f9e7559df83dd27684a186a5303d849a87326f4de572dbf5e951d7119f89c8f",
        "count": 11,
        "status": "H2_2_RESOLVED_REVIEW_ONLY; MAXIMUM_SPILL_SILL_FOOTPRINT",
        "role": "PERMANENT_LEGACY_LAKE_CANDIDATES",
    },
    "lake_seasonal": {
        "path": source_path("h22_seasonal_l1_basins"),
        "sha256": "8b335adb410f356a7c3ab07dbdfb2e3835f5df8571b5566795fea44c9ca657a4",
        "count": 1_170,
        "status": "H2_2_SEASONAL_DISPLAY_REVIEW_ONLY",
        "role": "SEASONAL_LAKE_BASINS",
    },
    "moorwandler_transition": {
        "path": source_path("h22_moorwandler_transition"),
        "sha256": "bf60990287737240db0ecdf2fd0dab488bf36ca802c2f0d2a2c3661970c70b7c",
        "count": 158,
        "status": "H2_2_WETLAND_TRANSITION_REVIEW_ONLY",
        "role": "MOORWANDLER_TRANSITION_EVIDENCE",
    },
    "exact_surface_registry": {
        "path": source_path("exact_surface_registry"),
        "sha256": "1986ff3bba8d87ab1c89eb1491fca7b941c8ef4eae8a6e2e1d07d4647c34d808",
        "count": 2_494_913,
        "status": "FORMATION_AUTHORITY_REVIEW_ONLY_NOT_CANON",
        "role": "EXACT_POSITIVE_SURFACE_TOPOLOGY",
    },
    "fragment_barony_assignment": {
        "path": source_path("fragment_barony_id"),
        "sha256": "6a993b8d6670c1ab044854f94dbaa169daefbb7b6870b63655dd75c264637731",
        "count": 2_494_913,
        "status": "7318_BARONY_COMPLETE_REVIEW_CANDIDATE_NOT_CANON",
        "role": "EXACT_FRAGMENT_BARONY_MEMBERSHIP",
    },
}

SEALED_TERRAIN_LINEAGE_ROLES = frozenset({
    "terrain_100m_sealed_lineage",
    "stillklinge_terrain_100m_sealed_lineage",
})
SEALED_TERRAIN_LINEAGE_KEYS = {
    "terrain_100m_sealed_lineage": "terrain_d31_100m",
    "stillklinge_terrain_100m_sealed_lineage": "stillklinge_terrain_100m",
}

EXPECTED_STATUS_COUNTS = {
    "READY_2D_CURRENT": 29_808,
    "READY_2D_CONDITIONAL": 176,
    "DEFERRED_SPECIALIST_3D": 113,
    "NOT_APPLICABLE_NONSETTLEMENT": 1_172,
    "INACTIVE": 2,
}
QUARANTINED_STILL_IDS = {
    "D3-MIN-013654", "D3-MIN-013664", "D3-MIN-013676", "D3-MIN-013700",
    "D3-MIN-013701", "D3-MIN-013711", "D3-MIN-013712", "D3-MIN-013713",
}
SPECIAL_3D_DOMAINS = rules.SPECIALIST_3D_DOMAINS
WATER_DEPENDENT_FORMS = {
    "FISHERY_OR_LAKESHORE_SETTLEMENT",
    "FREIGHT_TRANSFER_OR_LANDING_SETTLEMENT",
    "RIVER_TERRACE_OR_WATERSIDE_SETTLEMENT",
    "SURFACE_LAGOON_SETTLEMENT",
    "WETLAND_EDGE_SETTLEMENT",
    "WETLAND_STILT_OR_CHANNEL_SETTLEMENT",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def source_hash_cache_namespace() -> str:
    """Bind reusable receipts to this method and the protected source catalogue."""

    return stable_hash(canonical_json({
        "consumer": METHOD,
        "cache_schema": SOURCE_HASH_CACHE_SCHEMA,
        "source_catalogue_sha256": sha256_file(catalogue_path()),
    }))


def source_fingerprint_identity(authority_descriptor: Mapping[str, Any]) -> dict[str, Any]:
    """Complete immutable/mutable source identity used by every site row."""

    return {
        "sealed_sources": {
            role: spec["sha256"] for role, spec in sorted(SOURCES.items())
        },
        "terrain_authority": terrain_authority_identity(authority_descriptor),
    }


def terrain_authority_source_manifest_row(
    authority: Mapping[str, Any],
) -> dict[str, Any]:
    """Explicit mutable-authority record retained in JSON, SQLite and CSV."""

    return {
        "source_role": "effective_terrain_100m_editable_zarr_authority",
        "source_path": "working_authorities/effective_terrain_100m",
        "sha256": authority["root_hash"],
        "source_version": (
            f"authority_id={authority['authority_id']};generation={authority['generation']}"
        ),
        "required": 1,
        "source_status": "ACTIVE_EDITABLE_WORKING_AUTHORITY",
        "feature_or_record_count": 18_600 * 22_000,
        "note": "Runtime terrain source; old full-frame and Stillklinge terrain TIFFs are sealed lineage only.",
        "authority_id": authority["authority_id"],
        "authority_generation": authority["generation"],
        "authority_root_hash": authority["root_hash"],
        "sealed_tiff_lineage_json": canonical_json(authority["sealed_tiff_lineage"]),
    }


def write_csv(path: Path, rows: Sequence[Mapping[str, Any]], columns: Sequence[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if columns is None:
        columns = list(rows[0]) if rows else []
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(columns), extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def read_geojson(path: Path) -> tuple[list[Any], list[dict[str, Any]]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    features = payload.get("features", [])
    return [shape(item["geometry"]) for item in features], [dict(item.get("properties", {})) for item in features]


def read_geojson_properties(path: Path) -> list[dict[str, Any]]:
    """Read only properties when another locked source owns exact geometry."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    return [dict(item.get("properties", {})) for item in payload.get("features", [])]


def gpkg_geometry_digest(connection: sqlite3.Connection, table: str, key: str) -> str:
    digest = hashlib.sha256()
    for identity, geometry in connection.execute(f'SELECT "{key}",geom FROM "{table}" ORDER BY CAST("{key}" AS TEXT)'):
        digest.update(str(identity).encode("utf-8"))
        digest.update(b"\0")
        digest.update(geometry or b"")
        digest.update(b"\n")
    return digest.hexdigest()


def gpkg_geometry_digests(path: Path) -> dict[str, str]:
    mapping = {
        "settlement": "settlement_id", "province": "barony_id", "county": "county_uid",
        "duchy": "duchy_uid", "stage6_selected_spatial_seats": "administrative_seat_id",
        "stage6_duftfaehrte_full_capital_caravan_anchors": "capital_decision_id",
    }
    with sqlite3.connect(path) as connection:
        return {table: gpkg_geometry_digest(connection, table, key) for table, key in mapping.items()}


def static_source_manifest_row(
    role: str,
    spec: Mapping[str, Any],
    authority: Mapping[str, Any],
    *,
    deep_lineage_audit: bool,
    hash_cache: VerifiedSourceHashCache | None,
    force_rehash: bool,
) -> dict[str, Any]:
    """Verify one static source, avoiding obsolete TIFF I/O during normal runs.

    The editable authority already hash-locks both generation-zero terrain
    TIFFs.  Normal analysis therefore records that exact sealed identity
    without opening either TIFF.  ``Run-Generator.ps1 -Task Validate`` remains
    the independent, full 32-source byte audit; ``deep_lineage_audit`` is also
    available for a direct builder audit.
    """

    path = Path(spec["path"])
    sealed_lineage_only = role in SEALED_TERRAIN_LINEAGE_ROLES
    verification_note = str(spec.get("role") or "")
    if sealed_lineage_only and not deep_lineage_audit:
        lineage_key = SEALED_TERRAIN_LINEAGE_KEYS[role]
        lineage = authority["sealed_tiff_lineage"].get(lineage_key)
        if not isinstance(lineage, Mapping) or lineage.get("sha256") != spec["sha256"]:
            raise ValueError(
                f"Terrain authority lineage mismatch for {role}: "
                f"{None if not isinstance(lineage, Mapping) else lineage.get('sha256')} "
                f"!= {spec['sha256']}"
            )
        actual_hash = spec["sha256"]
        observed_count: int | None = None
        verification_note += (
            "; RUNTIME_IDENTITY_FROM_VERIFIED_ZARR_AUTHORITY_LINEAGE; "
            "DEEP_BYTES_AUDITED_BY_RUN_GENERATOR_VALIDATE"
        )
    else:
        if not path.is_file():
            raise FileNotFoundError(f"Missing Stage 6C source {role}: {path}")
        if hash_cache is None:
            actual_hash = sha256_file(path)
        else:
            actual_hash = hash_cache.verify(
                logical_id=role,
                path=path,
                expected_sha256=str(spec["sha256"]),
                force_rehash=force_rehash,
            ).sha256
        if actual_hash != spec["sha256"]:
            raise ValueError(
                f"Source hash mismatch for {role}: {actual_hash} != {spec['sha256']}"
            )
        observed_count = None
        if (
            path.suffix.lower() in {".geojson", ".json"}
            and "count" in spec
            and not spec.get("defer_feature_count_to_runtime")
        ):
            observed_count = len(
                json.loads(path.read_text(encoding="utf-8")).get("features", [])
            )
            if observed_count != spec["count"]:
                raise ValueError(
                    f"Source feature count mismatch for {role}: {observed_count}"
                )
        elif spec.get("defer_feature_count_to_runtime"):
            observed_count = int(spec["count"])
            verification_note += "; FEATURE_COUNT_REVERIFIED_DURING_VECTORSTACK_LOAD"
        if path.suffix.lower() in {".tif", ".tiff"}:
            with rasterio.open(path) as dataset:
                if "shape" in spec and (dataset.height, dataset.width) != tuple(spec["shape"]):
                    raise ValueError(
                        f"Raster shape mismatch for {role}: {(dataset.height, dataset.width)}"
                    )
                if list(dataset.transform)[:6] not in (
                    [0.1, 0.0, 0.0, 0.0, 0.1, 0.0],
                    [0.1, 0.0, 910.0, 0.0, 0.1, 220.0],
                ):
                    raise ValueError(
                        f"Unexpected raster transform for {role}: {dataset.transform}"
                    )
        if sealed_lineage_only:
            verification_note += "; DEEP_SEALED_LINEAGE_BYTE_AUDIT_PASS"

    return {
        "source_role": role,
        "source_path": str(path.resolve()),
        "sha256": actual_hash,
        "source_version": spec.get("role"),
        "required": 1,
        "source_status": spec["status"],
        "feature_or_record_count": (
            observed_count if observed_count is not None else spec.get("count")
        ),
        "note": verification_note,
        "authority_id": None,
        "authority_generation": None,
        "authority_root_hash": None,
        "sealed_tiff_lineage_json": None,
    }


def verify_sources(
    *,
    deep_lineage_audit: bool = False,
    use_hash_cache: bool = True,
    force_source_rehash: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    authority = verify_terrain_authority()
    hash_cache = (
        VerifiedSourceHashCache(
            SOURCE_HASH_CACHE_PATH,
            namespace=source_hash_cache_namespace(),
        )
        if use_hash_cache
        else None
    )
    rows = [
        static_source_manifest_row(
            role,
            spec,
            authority,
            deep_lineage_audit=deep_lineage_audit,
            hash_cache=hash_cache,
            force_rehash=(
                force_source_rehash
                or (deep_lineage_audit and role in SEALED_TERRAIN_LINEAGE_ROLES)
            ),
        )
        for role, spec in SOURCES.items()
    ]
    major_geoms, major_props = read_geojson(Path(SOURCES["active_major"]["path"]))
    minor_geoms, minor_props = read_geojson(Path(SOURCES["parent_minor_lineage"]["path"]))
    active_ids = {str(p.get("route_id") or p.get("minor_id")) for p in major_props + minor_props}
    if QUARANTINED_STILL_IDS & active_ids:
        raise ValueError(f"Quarantined Stillklinge IDs found in active hydrology: {sorted(QUARANTINED_STILL_IDS & active_ids)}")
    if len(major_geoms) != 30 or len(minor_geoms) != 3_177:
        raise AssertionError("Hydrology count changed after source verification")
    if hash_cache is not None:
        hash_cache.flush()
        cache_report = {"enabled": True, **hash_cache.report()}
    else:
        cache_report = {
            "enabled": False,
            "schema": SOURCE_HASH_CACHE_SCHEMA,
            "reason": "explicit_uncached_reference_path",
        }
    rows.append(terrain_authority_source_manifest_row(authority))
    return rows, authority, cache_report


def prepare_output() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in (OUT_DB, OUT_GPKG, OUT_DIR / "VALIDATION.json", OUT_DIR / "STAGE6C_SOURCE_MANIFEST.json"):
        if path.exists():
            path.unlink()
    if EXPORT_DIR.exists():
        shutil.rmtree(EXPORT_DIR)
    EXPORT_DIR.mkdir(parents=True)
    shutil.copy2(BASE_DB, OUT_DB)
    shutil.copy2(BASE_GPKG, OUT_GPKG)


@dataclass(frozen=True)
class Site:
    settlement_id: str
    x: float
    y: float
    barony_id: int | None
    active_location: int
    active_settlement: int
    added_identity: int
    conditionality: str | None
    functional_tier: str | None
    realised_form: str | None
    form_family: str | None
    vertical_domain: str
    ordinary_human: int


class ExactSurfaceIndex:
    """100 m centre lookup backed by exact 1 km positive-area fragment topology."""

    def __init__(self, registry_path: Path, assignment_path: Path) -> None:
        fragment_baronies = np.asarray(
            np.load(assignment_path, allow_pickle=False), dtype=np.int32
        )
        with np.load(registry_path, allow_pickle=False) as archive:
            offsets = np.asarray(archive["cell_offsets"], dtype=np.uint32)
            areas = np.asarray(archive["fragment_area_km2"], dtype=np.float64)
            if len(fragment_baronies) != len(areas):
                raise ValueError("Exact fragment/barony assignment length mismatch")
            counts = np.diff(offsets)
            nonempty = np.flatnonzero(counts)
            carrier = np.full(1_860 * 2_200, -1, dtype=np.int32)
            single = nonempty[counts[nonempty] == 1]
            single_fragment = offsets[single].astype(np.int64)
            carrier[single] = fragment_baronies[single_fragment]
            multiple = nonempty[counts[nonempty] > 1]
            for cell in multiple.tolist():
                start, end = int(offsets[cell]), int(offsets[cell + 1])
                local = int(np.argmax(areas[start:end])) + start
                carrier[cell] = int(fragment_baronies[local])
            self.carrier_baronies = carrier.reshape(1_860, 2_200)

            explicit_ids = np.asarray(archive["explicit_fragment_id"], dtype=np.int64)
            wkb_offsets = np.asarray(archive["boundary_wkb_offsets"], dtype=np.uint64)
            wkb_bytes = np.asarray(archive["boundary_wkb_bytes"], dtype=np.uint8)
            explicit_carriers = np.searchsorted(offsets, explicit_ids, side="right") - 1
            self.explicit_by_carrier: dict[int, list[tuple[int, Any]]] = defaultdict(list)
            raw = memoryview(wkb_bytes)
            for index, fragment_id in enumerate(explicit_ids.tolist()):
                start, end = int(wkb_offsets[index]), int(wkb_offsets[index + 1])
                geometry = shapely.from_wkb(bytes(raw[start:end]))
                self.explicit_by_carrier[int(explicit_carriers[index])].append(
                    (int(fragment_baronies[fragment_id]), geometry)
                )
        self.partial_carriers = set(self.explicit_by_carrier)
        self.partial_carriers_by_row: dict[int, list[int]] = defaultdict(list)
        for carrier_id in self.explicit_by_carrier:
            self.partial_carriers_by_row[carrier_id // 2_200].append(carrier_id)
        for carrier_ids in self.partial_carriers_by_row.values():
            carrier_ids.sort()

    def rasterize_window(self, row0: int, col0: int, height: int, width: int) -> np.ndarray:
        rows = np.arange(row0, row0 + height, dtype=np.int32)
        cols = np.arange(col0, col0 + width, dtype=np.int32)
        carrier_rows = np.clip(rows // 10, 0, 1_859)
        carrier_cols = np.clip(cols // 10, 0, 2_199)
        # Advanced indexing already returns a writable independent array.
        result = self.carrier_baronies[np.ix_(carrier_rows, carrier_cols)]

        min_carrier_row, max_carrier_row = int(carrier_rows.min()), int(carrier_rows.max())
        min_carrier_col, max_carrier_col = int(carrier_cols.min()), int(carrier_cols.max())
        for cr in range(min_carrier_row, max_carrier_row + 1):
            for carrier_id in self.partial_carriers_by_row.get(cr, ()):
                cc = carrier_id % 2_200
                if not (min_carrier_col <= cc <= max_carrier_col):
                    continue
                global_row0 = max(row0, cr * 10)
                global_row1 = min(row0 + height, (cr + 1) * 10)
                global_col0 = max(col0, cc * 10)
                global_col1 = min(col0 + width, (cc + 1) * 10)
                local_row0, local_row1 = global_row0 - row0, global_row1 - row0
                local_col0, local_col1 = global_col0 - col0, global_col1 - col0
                xs, ys = np.meshgrid(
                    np.arange(global_col0, global_col1, dtype=np.float64) * 0.1 + 0.05,
                    np.arange(global_row0, global_row1, dtype=np.float64) * 0.1 + 0.05,
                    indexing="xy",
                )
                classified = np.full(xs.shape, -1, dtype=np.int32)
                for barony_id, geometry in self.explicit_by_carrier[carrier_id]:
                    # Point/polygon intersection has the same interior-or-boundary
                    # semantics as polygon-covers-point without allocating Points.
                    classified[shapely.intersects_xy(geometry, xs, ys)] = barony_id
                result[local_row0:local_row1, local_col0:local_col1] = classified
        return result


def _coordinate_line_chunks(coordinates: Any, segment_limit: int) -> list[LineString]:
    values = np.asarray(coordinates, dtype=np.float64)
    if len(values) < 2:
        return []
    return [
        LineString(values[start : min(start + segment_limit, len(values) - 1) + 1])
        for start in range(0, len(values) - 1, segment_limit)
    ]


def _line_index_chunks(geometries: Sequence[Any], segment_limit: int) -> list[Any]:
    """Return an exact, unsimplified finer index representation of linework."""
    result: list[Any] = []
    for geometry in geometries:
        if isinstance(geometry, LineString):
            result.extend(_coordinate_line_chunks(geometry.coords, segment_limit))
        elif isinstance(geometry, MultiLineString):
            for line in geometry.geoms:
                result.extend(_coordinate_line_chunks(line.coords, segment_limit))
        else:
            result.append(geometry)
    return result


def _coast_index_parts(
    geometries: Sequence[Any], segment_limit: int
) -> tuple[list[Any], list[Any]]:
    """Build exact coast-boundary chunks and retain polygons for interior zeroes."""
    index_parts: list[Any] = []
    cover_polygons: list[Any] = []
    for geometry in geometries:
        polygons: Sequence[Any]
        if isinstance(geometry, Polygon):
            polygons = (geometry,)
        elif isinstance(geometry, MultiPolygon):
            polygons = tuple(geometry.geoms)
        else:
            index_parts.extend(_line_index_chunks((geometry,), segment_limit))
            continue
        for polygon in polygons:
            cover_polygons.append(polygon)
            index_parts.extend(
                _coordinate_line_chunks(polygon.exterior.coords, segment_limit)
            )
            for ring in polygon.interiors:
                index_parts.extend(_coordinate_line_chunks(ring.coords, segment_limit))
    return index_parts, cover_polygons


@dataclass(frozen=True)
class WaterDistanceBatch:
    """Exact distances retained by the Stage 6C downstream contract."""

    active_cells: np.ndarray
    perennial_cells: np.ndarray
    class_minima: Mapping[str, np.ndarray]
    lagoon_cells: Mapping[int, Mapping[str, np.ndarray]]


class VectorStack:
    def __init__(self, query_mode: str = "reference") -> None:
        if query_mode not in WATER_QUERY_MODES:
            raise ValueError(f"Unsupported water query mode: {query_mode}")
        self.query_mode = query_mode
        self.major_geoms, self.major_props = read_geojson(Path(SOURCES["active_major"]["path"]))
        local_minor_geoms, local_minor_props = read_geojson(
            Path(SOURCES["stillklinge_support"]["path"])
        )
        if len(local_minor_geoms) != 112:
            raise AssertionError("Expected exactly 112 corrected Stillklinge minor features")
        d3_raw_geoms, d3_raw_props = read_geojson(
            Path(SOURCES["d3_feeder_raw"]["path"])
        )
        d3_enriched_props = read_geojson_properties(
            Path(SOURCES["d3_feeder_enriched"]["path"])
        )
        if len(d3_raw_geoms) != 16_468 or len(d3_enriched_props) != 16_468:
            raise AssertionError("V4.2 D3 feeder source count changed")
        raw_ids = [str(item.get("minor_id")) for item in d3_raw_props]
        enriched_ids = [str(item.get("minor_id")) for item in d3_enriched_props]
        if raw_ids != enriched_ids:
            raise AssertionError("V4.2 D3 raw/enriched feature ordering mismatch")
        d3_outside_indices = [
            index
            for index, item in enumerate(d3_enriched_props)
            if item.get("system") != "Stillklinge"
        ]
        if len(d3_outside_indices) != 16_369:
            raise AssertionError("Expected exactly 16,369 non-Stillklinge D3 feeders")
        d3_outside_geoms = [d3_raw_geoms[index] for index in d3_outside_indices]
        d3_outside_props = [d3_enriched_props[index] for index in d3_outside_indices]
        if any(item.get("persistence") == "surface_interrupted" for item in d3_outside_props):
            raise AssertionError("A surface-interrupted D3 row leaked outside Stillklinge")

        # Match the sealed V4.2 runtime composition exactly. The 3,177-feature
        # parent-preserving candidate file is retained as lineage evidence but
        # is not rasterised by the controlling V4.2 builder. Runtime minor
        # hydrology is the 16,369 non-Stillklinge D3 reaches plus the corrected
        # 112-feature Stillklinge local composition.
        self.minor_geoms = d3_outside_geoms + local_minor_geoms
        self.minor_props = d3_outside_props + local_minor_props
        self.hydrology_composition = {
            "parent_minor_lineage_count": 3_177,
            "d3_total_count": len(d3_raw_geoms),
            "d3_non_stillklinge_count": len(d3_outside_geoms),
            "d3_stillklinge_excluded_count": len(d3_raw_geoms) - len(d3_outside_geoms),
            "corrected_stillklinge_local_count": len(local_minor_geoms),
            "combined_minor_count": len(self.minor_geoms),
        }
        if len(self.minor_geoms) != 16_481:
            raise AssertionError("Expected exact sealed V4.2 16,481-feature minor composition")
        all_special_geoms, all_special_props = read_geojson(
            Path(SOURCES["special_controls"]["path"])
        )
        special_by_name = {
            str(properties.get("feature")): (geometry, properties)
            for geometry, properties in zip(all_special_geoms, all_special_props)
        }
        if set(special_by_name) != {
            "highest_tarn", "high_lagoon_A", "high_lagoon_B", "lower_lagoon",
            "inland_outlet_lake", "inland_freshwater_peat_basin", "surface_loss",
            "capital_cavern_lake", "resurgence",
            "subsurface_loss_lake_resurgence_connector",
        }:
            raise AssertionError("V4.2 special-control feature set changed")
        strict_special_names = ("highest_tarn", "resurgence")
        managed_special_names = (
            "high_lagoon_A", "high_lagoon_B", "lower_lagoon", "inland_outlet_lake"
        )
        self.special_geoms = [special_by_name[name][0] for name in strict_special_names]
        self.special_props = [special_by_name[name][1] for name in strict_special_names]
        self.managed_special_geoms = [
            special_by_name[name][0] for name in managed_special_names
        ]
        self.managed_special_tree = shapely.STRtree(self.managed_special_geoms)
        self.hydrology_composition.update({
            "strict_surface_special_count": len(self.special_geoms),
            "managed_surface_overlay_count": len(self.managed_special_geoms),
            "non_surface_special_overlay_count": (
                len(all_special_geoms) - len(self.special_geoms) - len(self.managed_special_geoms)
            ),
        })
        self.coast_geoms, self.coast_props = read_geojson(Path(SOURCES["coastline"]["path"]))
        permanent_a, permanent_a_props = read_geojson(Path(SOURCES["lake_permanent_l1"]["path"]))
        permanent_b, permanent_b_props = read_geojson(Path(SOURCES["lake_permanent_legacy"]["path"]))
        self.permanent_lake_geoms = permanent_a + permanent_b
        self.permanent_lake_props = permanent_a_props + permanent_b_props
        self.seasonal_lake_geoms, self.seasonal_lake_props = read_geojson(Path(SOURCES["lake_seasonal"]["path"]))

        self.minor_tree = shapely.STRtree(self.minor_geoms)
        self.special_tree = shapely.STRtree(self.special_geoms)
        self.permanent_lake_tree = shapely.STRtree(self.permanent_lake_geoms)
        self.seasonal_lake_tree = shapely.STRtree(self.seasonal_lake_geoms)

        perennial_minor = [
            geometry
            for geometry, properties in zip(self.minor_geoms, self.minor_props)
            if (
                properties.get("persistence_preclassification") == "perennial"
                or properties.get("persistence") in {"perennial", "perennial_saturated"}
            )
            and not bool(properties.get("source_perennial_label_must_not_be_inherited_as_authoritative"))
        ]
        d3_perennial_count = sum(
            item.get("persistence") in {"perennial", "perennial_saturated"}
            for item in d3_outside_props
        )
        if d3_perennial_count != 15_193:
            raise AssertionError("Expected exactly 15,193 persistence-controlled D3 feeders")
        self.hydrology_composition["d3_perennial_count"] = d3_perennial_count
        self.hydrology_composition["combined_perennial_minor_count"] = len(perennial_minor)
        if len(perennial_minor) != 15_193:
            raise AssertionError(
                "A non-authoritative Stillklinge/local row leaked into perennial distance"
            )
        if query_mode == "reference":
            self.major_tree = shapely.STRtree(self.major_geoms)
            self.coast_tree = shapely.STRtree(self.coast_geoms)
            self.perennial_geoms = (
                self.major_geoms + perennial_minor + self.permanent_lake_geoms
            )
            self.perennial_tree = shapely.STRtree(self.perennial_geoms)

        if query_mode in {"chunked", "reduced"}:
            self.major_index_geoms = _line_index_chunks(
                self.major_geoms, WATER_INDEX_CHUNK_SEGMENTS
            )
            self.major_index_tree = shapely.STRtree(self.major_index_geoms)
            self.coast_index_geoms, self.coast_cover_polygons = _coast_index_parts(
                self.coast_geoms, WATER_INDEX_CHUNK_SEGMENTS
            )
            self.coast_index_tree = shapely.STRtree(self.coast_index_geoms)
            for polygon in self.coast_cover_polygons:
                shapely.prepare(polygon)
            self.perennial_minor_geoms = perennial_minor
            self.perennial_minor_tree = shapely.STRtree(self.perennial_minor_geoms)
            if query_mode == "reduced":
                self.active_index_geoms = (
                    self.major_index_geoms
                    + self.minor_geoms
                    + self.special_geoms
                    + self.coast_index_geoms
                    + self.permanent_lake_geoms
                    + self.seasonal_lake_geoms
                )
                self.active_index_tree = shapely.STRtree(self.active_index_geoms)
                self.perennial_index_geoms = (
                    self.major_index_geoms
                    + self.perennial_minor_geoms
                    + self.permanent_lake_geoms
                )
                self.perennial_index_tree = shapely.STRtree(
                    self.perennial_index_geoms
                )

    @staticmethod
    def distances(tree: Any, points: Any) -> np.ndarray:
        point_count = len(points)
        if point_count == 0:
            return np.empty(0, dtype=np.float64)
        result = np.full(point_count, np.inf, dtype=np.float64)
        if len(tree.geometries) == 0:
            return result
        indices, distances = tree.query_nearest(
            points, return_distance=True, all_matches=False
        )
        indices_array = np.asarray(indices)
        if indices_array.size:
            result[indices_array[0]] = np.asarray(distances, dtype=np.float64)
        return result

    def coast_distances(self, points: Any) -> np.ndarray:
        if self.query_mode == "reference":
            return self.distances(self.coast_tree, points)
        result = self.distances(self.coast_index_tree, points)
        for polygon in self.coast_cover_polygons:
            result[np.asarray(shapely.covers(polygon, points), dtype=bool)] = 0.0
        return result

    @staticmethod
    def geometry_distance(tree: Any, geometry: Any) -> float:
        if len(tree.geometries) == 0:
            return math.inf
        _, distances = tree.query_nearest(
            geometry, return_distance=True, all_matches=False
        )
        return float(np.asarray(distances, dtype=np.float64).reshape(-1)[0])

    def coast_geometry_distance(self, geometry: Any) -> float:
        for polygon in self.coast_cover_polygons:
            if bool(shapely.intersects(polygon, geometry)):
                return 0.0
        return self.geometry_distance(self.coast_index_tree, geometry)

    def candidate_distances(self, xs: np.ndarray, ys: np.ndarray) -> dict[str, np.ndarray]:
        if self.query_mode == "reduced":
            raise ValueError(
                "The reduced mode publishes a WaterDistanceBatch, not all class arrays"
            )
        points = shapely.points(xs, ys)
        major_tree = self.major_tree if self.query_mode == "reference" else self.major_index_tree
        major = self.distances(major_tree, points)
        minor = self.distances(self.minor_tree, points)
        special = self.distances(self.special_tree, points)
        coast = self.coast_distances(points)
        lake = self.distances(self.permanent_lake_tree, points)
        seasonal_lake = self.distances(self.seasonal_lake_tree, points)
        if self.query_mode == "reference":
            perennial = self.distances(self.perennial_tree, points)
        else:
            perennial_minor = self.distances(self.perennial_minor_tree, points)
            perennial = np.minimum.reduce((major, lake, perennial_minor))
        active = np.minimum.reduce((major, minor, special, coast, lake, seasonal_lake))
        return {
            "major": major, "minor": minor, "special": special, "coast": coast,
            "lake": lake, "seasonal_lake": seasonal_lake, "perennial": perennial,
            "active": active,
        }

    def candidate_distance_batch(
        self,
        xs: np.ndarray,
        ys: np.ndarray,
        sites: Sequence["Site"],
    ) -> WaterDistanceBatch:
        site_count = len(sites)
        if len(xs) != site_count * 100 or len(ys) != site_count * 100:
            raise ValueError("Each Stage 6C site must provide exactly 100 candidate cells")
        points = shapely.points(xs, ys)

        if self.query_mode != "reduced":
            distances = self.candidate_distances(xs, ys)
            cells = {
                key: values.reshape(site_count, 100)
                for key, values in distances.items()
            }
            class_minima = {
                key: np.min(cells[key], axis=1)
                for key in (
                    "major", "minor", "special", "coast", "lake", "seasonal_lake"
                )
            }
            lagoon_cells = {
                index: {
                    "special": self.distances(
                        self.managed_special_tree,
                        points[index * 100 : (index + 1) * 100],
                    ),
                    "lake": cells["lake"][index],
                }
                for index, site in enumerate(sites)
                if site.realised_form == "SURFACE_LAGOON_SETTLEMENT"
            }
            return WaterDistanceBatch(
                active_cells=cells["active"],
                perennial_cells=cells["perennial"],
                class_minima=class_minima,
                lagoon_cells=lagoon_cells,
            )

        active = self.distances(self.active_index_tree, points)
        for polygon in self.coast_cover_polygons:
            active[np.asarray(shapely.covers(polygon, points), dtype=bool)] = 0.0
        perennial = self.distances(self.perennial_index_tree, points)
        active_cells = active.reshape(site_count, 100)
        perennial_cells = perennial.reshape(site_count, 100)

        class_trees = {
            "major": self.major_index_tree,
            "minor": self.minor_tree,
            "special": self.special_tree,
            "lake": self.permanent_lake_tree,
            "seasonal_lake": self.seasonal_lake_tree,
        }
        class_minima = {
            key: np.empty(site_count, dtype=np.float64)
            for key in (
                "major", "minor", "special", "coast", "lake", "seasonal_lake"
            )
        }
        def site_summary(index: int) -> tuple[int, dict[str, float], dict[str, np.ndarray] | None]:
            site = sites[index]
            candidate_slice = slice(index * 100, (index + 1) * 100)
            site_points = points[candidate_slice]
            site_geometry = shapely.multipoints(site_points)
            minima = {
                key: self.geometry_distance(tree, site_geometry)
                for key, tree in class_trees.items()
            }
            minima["coast"] = self.coast_geometry_distance(site_geometry)
            lagoon = None
            if site.realised_form == "SURFACE_LAGOON_SETTLEMENT":
                lagoon = {
                    "special": self.distances(self.managed_special_tree, site_points),
                    "lake": self.distances(self.permanent_lake_tree, site_points),
                }
            return index, minima, lagoon

        site_results = [site_summary(index) for index in range(site_count)]
        site_results.sort(key=lambda item: item[0])
        lagoon_cells: dict[int, dict[str, np.ndarray]] = {}
        for index, minima, lagoon in site_results:
            for key, tree in class_trees.items():
                class_minima[key][index] = minima[key]
            class_minima["coast"][index] = minima["coast"]
            if lagoon is not None:
                lagoon_cells[index] = lagoon

        return WaterDistanceBatch(
            active_cells=active_cells,
            perennial_cells=perennial_cells,
            class_minima=class_minima,
            lagoon_cells=lagoon_cells,
        )


class RasterStack:
    def __init__(self, authority_descriptor: Mapping[str, Any]) -> None:
        # This is the only runtime terrain binding.  Opening it holds the
        # authority access lock for the complete analysis and proves that the
        # generation verified before the run did not change in between.
        self.terrain = TerrainAuthorityReader(authority_descriptor).open()
        self._local = threading.local()
        self._dataset_lock = threading.Lock()
        self._dataset_bundles: list[tuple[Any, Any, Any, Any, Any]] = []
        try:
            # Flood remains an independent approved local replacement.  It is
            # not part of the editable elevation authority.
            with rasterio.open(Path(SOURCES["stillklinge_flood_override"]["path"])) as metadata:
                self.still_global_row0 = int(round(metadata.transform.f / 0.1))
                self.still_global_col0 = int(round(metadata.transform.c / 0.1))
                self.still_height = int(metadata.height)
                self.still_width = int(metadata.width)
        except Exception:
            self.terrain.close()
            raise

    def _datasets(self) -> tuple[Any, Any, Any, Any, Any]:
        bundle = getattr(self._local, "datasets", None)
        if bundle is not None:
            return bundle
        opened: list[Any] = []
        try:
            # DatasetReader handles are not shared between outer workers.  Two
            # GTiff decode threads per handle was the measured bounded optimum.
            opened.append(rasterio.open(
                Path(SOURCES["obsidian_sea_mask"]["path"]), NUM_THREADS="2"
            ))
            opened.append(rasterio.open(
                Path(SOURCES["moorwandler_core_wetland"]["path"]), NUM_THREADS="2"
            ))
            opened.append(rasterio.open(
                Path(SOURCES["serenakrone_water_mask"]["path"]), NUM_THREADS="2"
            ))
            opened.append(rasterio.open(
                Path(SOURCES["flood_candidates_100m"]["path"]), NUM_THREADS="2"
            ))
            opened.append(rasterio.open(Path(SOURCES["stillklinge_flood_override"]["path"])))
        except Exception:
            for dataset in opened:
                dataset.close()
            raise
        bundle = tuple(opened)
        self._local.datasets = bundle
        with self._dataset_lock:
            self._dataset_bundles.append(bundle)
        return bundle

    def close(self) -> None:
        with self._dataset_lock:
            bundles = self._dataset_bundles
            self._dataset_bundles = []
        first_error: BaseException | None = None
        try:
            for bundle in bundles:
                for dataset in bundle:
                    try:
                        dataset.close()
                    except BaseException as exc:
                        if first_error is None:
                            first_error = exc
        finally:
            try:
                self.terrain.close()
            except BaseException as exc:
                if first_error is None:
                    first_error = exc
        if first_error is not None:
            raise first_error

    def read_block(self, row0: int, col0: int, height: int, width: int) -> dict[str, np.ndarray]:
        sea_ds, moor_ds, seren_ds, flood_ds, still_flood_ds = self._datasets()
        window = Window(col0, row0, width, height)
        terrain = self.terrain.read_block(row0, col0, height, width)
        sea = sea_ds.read(1, window=window).astype(np.uint8, copy=False)
        moor = moor_ds.read(1, window=window).astype(np.uint8, copy=False)
        seren = seren_ds.read(1, window=window).astype(np.uint8, copy=False)
        flood = flood_ds.read(1, window=window).astype(np.float32, copy=False)

        ir0 = max(row0, self.still_global_row0)
        ic0 = max(col0, self.still_global_col0)
        ir1 = min(row0 + height, self.still_global_row0 + self.still_height)
        ic1 = min(col0 + width, self.still_global_col0 + self.still_width)
        if ir0 < ir1 and ic0 < ic1:
            global_target = (slice(ir0 - row0, ir1 - row0), slice(ic0 - col0, ic1 - col0))
            local_window = Window(
                ic0 - self.still_global_col0,
                ir0 - self.still_global_row0,
                ic1 - ic0,
                ir1 - ir0,
            )
            # Replace, not merge: this explicitly removes the displaced pre-repair flood corridor.
            flood[global_target] = still_flood_ds.read(1, window=local_window)

        terrain64 = terrain.astype(np.float64)
        gy, gx = np.gradient(terrain64, 100.0, 100.0)
        del terrain64
        np.hypot(gx, gy, out=gx)
        del gy
        np.arctan(gx, out=gx)
        slope = np.empty(gx.shape, dtype=np.float32)
        np.degrees(gx, out=slope)
        flood_exposure = np.zeros(flood.shape, dtype=np.float32)
        flood_exposure[flood == 1] = 0.70
        flood_exposure[flood == 2] = 0.90
        flood_exposure[flood == 3] = 0.60
        flood_exposure[flood == 4] = 0.25
        wetland = ((moor > 0) | (flood == 2) | (flood == 3) | (flood == 4)).astype(np.uint8)
        return {
            "terrain": terrain, "slope": slope, "sea": sea, "moor": moor,
            "seren": seren, "flood": flood, "flood_exposure": flood_exposure,
            "wetland": wetland,
        }


def transform_score(value: float | None, rule: Mapping[str, Any]) -> float | None:
    if value is None or not math.isfinite(value) or rule["transform_code"] == "DEFERRED":
        return None
    code = rule["transform_code"]
    p0, p1, p2, p3 = (rule.get("p0"), rule.get("p1"), rule.get("p2"), rule.get("p3"))
    if code == "CONSTANT":
        return float(np.clip(p0, 0.0, 1.0))
    if code == "BINARY":
        return float(bool(value))
    if code == "HIGH_BETTER":
        if p1 == p0:
            return float(value >= p1)
        return float(np.clip((value - p0) / (p1 - p0), 0.0, 1.0))
    if code == "LOW_BETTER":
        if p1 == p0:
            return float(value <= p0)
        return float(np.clip(1.0 - (value - p0) / (p1 - p0), 0.0, 1.0))
    if code == "RANGE_TRAPEZOID":
        # Test the plateau first so a deliberately degenerate ramp (p0 == p1
        # or p2 == p3) includes its endpoint. This is required by low-flood
        # policies whose ideal range begins at exactly zero exposure.
        if p1 <= value <= p2:
            return 1.0
        if value <= p0 or value >= p3:
            return 0.0
        if value < p1:
            return float((value - p0) / max(p1 - p0, 1e-12))
        return float((p3 - value) / max(p3 - p2, 1e-12))
    raise ValueError(f"Unknown transform {code}")


def transform_score_self_check() -> dict[str, Any]:
    cases = (
        (0.0, {"transform_code": "RANGE_TRAPEZOID", "p0": 0.0, "p1": 0.0, "p2": 0.55, "p3": 1.0}, 1.0),
        (1.0, {"transform_code": "RANGE_TRAPEZOID", "p0": 0.0, "p1": 0.0, "p2": 0.55, "p3": 1.0}, 0.0),
        (1.0, {"transform_code": "RANGE_TRAPEZOID", "p0": 0.0, "p1": 0.45, "p2": 1.0, "p3": 1.0}, 1.0),
        (1.000001, {"transform_code": "RANGE_TRAPEZOID", "p0": 0.0, "p1": 0.45, "p2": 1.0, "p3": 1.0}, 0.0),
        (0.0, {"transform_code": "RANGE_TRAPEZOID", "p0": 0.0, "p1": 0.25, "p2": 5.0, "p3": 15.0}, 0.0),
        (0.25, {"transform_code": "RANGE_TRAPEZOID", "p0": 0.0, "p1": 0.25, "p2": 5.0, "p3": 15.0}, 1.0),
        (5.0, {"transform_code": "RANGE_TRAPEZOID", "p0": 0.0, "p1": 0.25, "p2": 5.0, "p3": 15.0}, 1.0),
        (15.0, {"transform_code": "RANGE_TRAPEZOID", "p0": 0.0, "p1": 0.25, "p2": 5.0, "p3": 15.0}, 0.0),
    )
    for value, rule, expected in cases:
        actual = transform_score(value, rule)
        if actual is None or not math.isclose(actual, expected, rel_tol=0.0, abs_tol=1e-12):
            raise AssertionError(
                f"Transform self-check failed for value={value}, rule={rule}: "
                f"expected {expected}, got {actual}"
            )
    return {"status": "PASS", "case_count": len(cases)}


def weighted_geomean(values: Mapping[str, float | None], weights: Mapping[str, float], components: Iterable[str]) -> float | None:
    available = [(max(float(values[key]), 1e-6), float(weights[key])) for key in components if values.get(key) is not None and weights[key] > 0]
    if not available:
        return None
    weight_sum = sum(weight for _, weight in available)
    return float(math.exp(sum(weight * math.log(value) for value, weight in available) / weight_sum))


def access_aggregate(values: Mapping[str, float | None], weights: Mapping[str, float], operator: str) -> float | None:
    components = ("LAND_ACCESS", "WATER_ACCESS", "SEASONAL_RELIABILITY")
    available = [(float(values[key]), float(weights[key])) for key in components if values.get(key) is not None and weights[key] > 0]
    if not available:
        return None
    if operator == "WEIGHTED_MAX":
        # Land and water are alternatives; seasonal reliability remains a common constraint.
        mode_scores = [values.get("LAND_ACCESS"), values.get("WATER_ACCESS")]
        best_mode = max(value for value in mode_scores if value is not None)
        seasonal = values.get("SEASONAL_RELIABILITY")
        return float(best_mode if seasonal is None else math.sqrt(max(best_mode, 1e-6) * max(seasonal, 1e-6)))
    return weighted_geomean(values, weights, components)


def capacity_band(score: float | None, profile: Mapping[str, Any]) -> str | None:
    if score is None:
        return None
    thresholds = [profile["band_t1"], profile["band_t2"], profile["band_t3"], profile["band_t4"]]
    labels = ["CB0_UNSUPPORTED", "CB1_CONSTRAINED", "CB2_MODERATE", "CB3_STRONG", "CB4_EXCEPTIONAL"]
    for index, threshold in enumerate(thresholds):
        if score < threshold:
            return labels[index]
    return labels[-1]


def load_sites(connection: sqlite3.Connection) -> list[Site]:
    query = """
    SELECT settlement_id, display_x_km, display_y_km, barony_id,
           stage6_active_location, stage6_active_settlement, stage6_added_identity,
           stage6b_conditionality_status, stage6b_functional_tier,
           stage6b_realised_settlement_form, stage6b_form_family,
           COALESCE(stage6_vertical_domain_class, vertical_domain_class, 'UNSPECIFIED'),
           stage6_ordinary_permanent_human_settlement
    FROM settlement
    ORDER BY settlement_id
    """
    return [
        Site(
            settlement_id=str(row[0]), x=float(row[1]), y=float(row[2]),
            barony_id=None if row[3] is None else int(row[3]),
            active_location=int(row[4]), active_settlement=int(row[5]), added_identity=int(row[6]),
            conditionality=row[7], functional_tier=row[8], realised_form=row[9], form_family=row[10],
            vertical_domain=str(row[11]), ordinary_human=int(row[12] or 0),
        )
        for row in connection.execute(query)
    ]


def source_grid_window(site: Site, size: int = 10) -> tuple[np.ndarray, np.ndarray]:
    half_km = size * 0.1 / 2.0
    col0 = int(math.floor((site.x - half_km) / 0.1 + 1e-8))
    row0 = int(math.floor((site.y - half_km) / 0.1 + 1e-8))
    col0 = min(max(col0, 0), 22_000 - size)
    row0 = min(max(row0, 0), 18_600 - size)
    rows, cols = np.meshgrid(
        np.arange(row0, row0 + size, dtype=np.int32),
        np.arange(col0, col0 + size, dtype=np.int32),
        indexing="ij",
    )
    return rows.ravel(), cols.ravel()


def window_for_radius(site: Site, radius_km: float) -> tuple[int, int, int, int]:
    col0 = max(0, int(math.floor((site.x - radius_km) / 0.1)))
    row0 = max(0, int(math.floor((site.y - radius_km) / 0.1)))
    col1 = min(22_000, int(math.ceil((site.x + radius_km) / 0.1)))
    row1 = min(18_600, int(math.ceil((site.y + radius_km) / 0.1)))
    return row0, col0, row1, col1


def site_scope(analysis_status: str) -> str:
    return {
        "READY_2D_CURRENT": "CURRENT_SETTLEMENT",
        "READY_2D_CONDITIONAL": "CONDITIONAL_SETTLEMENT",
        "DEFERRED_SPECIALIST_3D": "CURRENT_SETTLEMENT",
        "NOT_APPLICABLE_NONSETTLEMENT": "ACTIVE_NONSETTLEMENT",
        "INACTIVE": "INACTIVE",
    }[analysis_status]


def domain_candidate_mask(
    site: Site,
    same_barony: np.ndarray,
    surface: np.ndarray,
    sea: np.ndarray,
    wetland: np.ndarray,
    seren: np.ndarray,
    distances: Mapping[str, np.ndarray],
) -> tuple[np.ndarray, np.ndarray, bool]:
    if site.barony_id is None:
        land = surface & (sea == 0)
    else:
        land = same_barony & surface & (sea == 0)
    water_contact = (
        (distances["active"] <= 0.20)
        | (seren > 0)
        | (wetland > 0)
    )
    form = site.realised_form or ""
    ordinary_surface_fallback = False
    if form == "SURFACE_LAGOON_SETTLEMENT":
        valid = (seren > 0) | (distances["special"] <= 0.20) | (distances["lake"] <= 0.20) | (land & water_contact)
        domain_fit = np.where(valid, np.where(seren > 0, 1.0, 0.80), 0.0)
    elif form == "WETLAND_STILT_OR_CHANNEL_SETTLEMENT" or site.vertical_domain == "WETLAND_INTERIOR":
        platform_or_channel = (
            (wetland > 0)
            | (distances["active"] <= 0.50)
        )
        strict_valid = (land & platform_or_channel) | (water_contact & platform_or_channel)
        ordinary_surface_fallback = bool(site.ordinary_human and not strict_valid.any() and land.any())
        valid = land if ordinary_surface_fallback else strict_valid
        domain_fit = np.where(
            valid,
            np.where(
                strict_valid,
                np.where(wetland > 0, 1.0, 0.78),
                np.clip(0.55 - distances["active"] / 50.0, 0.25, 0.55),
            ),
            0.0,
        )
    elif form == "WETLAND_EDGE_SETTLEMENT":
        strict_valid = land & ((wetland > 0) | (distances["active"] <= 5.0))
        ordinary_surface_fallback = bool(site.ordinary_human and not strict_valid.any() and land.any())
        valid = land if ordinary_surface_fallback else strict_valid
        domain_fit = np.where(
            valid,
            np.where(
                strict_valid,
                np.where(wetland > 0, 1.0, np.clip(1.0 - distances["active"] / 8.0, 0.55, 0.95)),
                np.clip(0.55 - distances["active"] / 50.0, 0.25, 0.55),
            ),
            0.0,
        )
    elif form in WATER_DEPENDENT_FORMS:
        # The inherited label can mean a broad waterside/transfer role; proximity is
        # scored and audited, but ordinary land support is not erased by a label alone.
        valid = land
        domain_fit = np.where(valid, np.clip(1.0 - distances["active"] / 10.0, 0.45, 1.0), 0.0)
    else:
        valid = land
        if site.vertical_domain == "UNSPECIFIED":
            domain_fit = np.where(valid, 0.55, 0.0)
        elif site.vertical_domain in {"FOREST_CANOPY", "FOREST_FLOOR_ROOT"}:
            domain_fit = np.where(valid, 0.88, 0.0)
        elif site.vertical_domain == "NOMADIC_ROUTE_ANCHOR":
            domain_fit = np.where(valid, 0.70, 0.0)
        elif site.vertical_domain in SPECIAL_3D_DOMAINS:
            domain_fit = np.where(valid, 0.50, 0.0)
        else:
            domain_fit = np.where(valid, 1.0, 0.0)
    return valid.astype(bool), domain_fit.astype(np.float64), ordinary_surface_fallback


def developable_mask(
    site: Site,
    barony: np.ndarray,
    raster: Mapping[str, np.ndarray],
    slope_limit: float,
    flood_tolerance: str,
    ordinary_surface_fallback: bool = False,
) -> np.ndarray:
    surface = barony > 0
    same = surface if site.barony_id is None else barony == site.barony_id
    land = same & (raster["sea"] == 0)
    form = site.realised_form or ""
    if form == "SURFACE_LAGOON_SETTLEMENT":
        base = (raster["seren"] > 0) | (land & (raster["wetland"] > 0))
    elif form == "WETLAND_STILT_OR_CHANNEL_SETTLEMENT" or site.vertical_domain == "WETLAND_INTERIOR":
        base = land if ordinary_surface_fallback else land & (raster["wetland"] > 0)
    else:
        base = land
    terrain_ok = raster["slope"] <= max(float(slope_limit), 0.1)
    flood_factor = np.ones(raster["flood_exposure"].shape, dtype=np.float32)
    if flood_tolerance == "LOW":
        flood_factor = 1.0 - 0.55 * raster["flood_exposure"]
    elif flood_tolerance == "MODERATE":
        flood_factor = 1.0 - 0.25 * raster["flood_exposure"]
    return base.astype(np.float32) * terrain_ok.astype(np.float32) * flood_factor


def expansion_sectors(
    weights: np.ndarray,
    global_rows: np.ndarray,
    global_cols: np.ndarray,
    site: Site,
) -> tuple[str | None, dict[str, float]]:
    xs = global_cols.astype(np.float64) * 0.1 + 0.05
    ys = global_rows.astype(np.float64) * 0.1 + 0.05
    east = xs - site.x
    north = site.y - ys  # map north is decreasing source Y
    angle = (np.degrees(np.arctan2(north, east)) + 360.0) % 360.0
    names = np.array(["E", "NE", "N", "NW", "W", "SW", "S", "SE"], dtype=object)
    indices = ((angle + 22.5) // 45.0).astype(np.int32) % 8
    totals = {name: float(weights[indices == index].sum() * 0.01) for index, name in enumerate(names.tolist())}
    total = sum(totals.values())
    if total <= 0:
        return None, {name: 0.0 for name in names.tolist()}
    fractions = {name: value / total for name, value in totals.items()}
    ordered = sorted(fractions.items(), key=lambda item: (-item[1], item[0]))
    direction = ordered[0][0] if ordered[0][1] - ordered[1][1] >= 0.03 else "MULTIPLE_EQUIVALENT"
    return direction, fractions


def score_site_metrics(
    raw: Mapping[str, float | None],
    profile: Mapping[str, Any],
    policy: Mapping[str, Any],
    uncertainty: float,
) -> dict[str, Any]:
    raw_key = {
        "TERRAIN_SUPPORT": "terrain_slope_deg",
        "HYDROLOGY_SUPPORT": "corrected_surface_water_distance_km",
        "FLOOD_COMPATIBILITY": "flood_exposure_index",
        "CORE_CAPACITY": "developable_area_r1_km2",
        "EXPANSION_CAPACITY": "developable_area_r5_km2",
        "LAND_ACCESS": "land_access_cost_index",
        "WATER_ACCESS": "water_access_index",
        "SEASONAL_RELIABILITY": "seasonal_reliability_index",
        "DOMAIN_FIT": "domain_fit_index",
    }
    component_scores = {
        component: transform_score(raw.get(raw_key[component]), policy["components"][component])
        for component in rules.COMPONENT_CODES
    }
    capacity = weighted_geomean(component_scores, policy["weights"], rules.CAPACITY_COMPONENTS)
    access = access_aggregate(component_scores, policy["weights"], profile["access_operator"])
    if capacity is None:
        cap_low = cap_high = None
    else:
        cap_low = float(np.clip(capacity * (1.0 - uncertainty), 0.0, 1.0))
        cap_high = float(np.clip(capacity + (1.0 - capacity) * uncertainty, 0.0, 1.0))
    if access is None:
        access_low = access_high = None
    else:
        access_low = float(np.clip(access * (1.0 - uncertainty), 0.0, 1.0))
        access_high = float(np.clip(access + (1.0 - access) * uncertainty, 0.0, 1.0))
    return {
        "component_scores": component_scores,
        "capacity": capacity, "capacity_low": cap_low, "capacity_high": cap_high,
        "access": access, "access_low": access_low, "access_high": access_high,
        "capacity_band": capacity_band(capacity, profile),
    }


def _transform_scores_zero(values: np.ndarray, rule: Mapping[str, Any]) -> np.ndarray:
    """Apply the scalar transform recipe in bulk, with None/zero mapped to +0.

    Keep each arithmetic operation and RANGE_TRAPEZOID branch priority in the
    same order as transform_score. This is an execution optimisation, not a
    new scoring rule. Non-numeric/irregular inputs retain the scalar fallback.
    """
    values = np.asarray(values)
    if values.ndim != 1 or values.dtype.kind not in "bifu":
        return np.array([transform_score(float(value), rule) or 0.0 for value in values])
    values = values.astype(np.float64, copy=False)
    result = np.zeros(values.shape, dtype=np.float64)
    finite = np.isfinite(values)
    if not finite.any() or rule["transform_code"] == "DEFERRED":
        return result
    code = rule["transform_code"]
    p0, p1, p2, p3 = (rule.get("p0"), rule.get("p1"), rule.get("p2"), rule.get("p3"))
    if code == "CONSTANT":
        result[finite] = float(np.clip(p0, 0.0, 1.0))
    elif code == "BINARY":
        result[finite] = values[finite] != 0.0
    elif code == "HIGH_BETTER":
        if p1 == p0:
            result[finite] = values[finite] >= p1
        else:
            result[finite] = np.clip((values[finite] - p0) / (p1 - p0), 0.0, 1.0)
    elif code == "LOW_BETTER":
        if p1 == p0:
            result[finite] = values[finite] <= p0
        else:
            result[finite] = np.clip(1.0 - (values[finite] - p0) / (p1 - p0), 0.0, 1.0)
    elif code == "RANGE_TRAPEZOID":
        plateau = finite & (p1 <= values) & (values <= p2)
        result[plateau] = 1.0
        ramp = finite & ~plateau & ~((values <= p0) | (values >= p3))
        lower = ramp & (values < p1)
        upper = ramp & ~lower
        result[lower] = (values[lower] - p0) / max(p1 - p0, 1e-12)
        result[upper] = (p3 - values[upper]) / max(p3 - p2, 1e-12)
    else:
        raise ValueError(f"Unknown transform {code}")
    # The reference's `value or 0.0` also normalises negative zero.
    result[result == 0.0] = 0.0
    return result


def _candidate_cell_scores_reference(
    slope: np.ndarray,
    active_distance: np.ndarray,
    flood: np.ndarray,
    domain_fit: np.ndarray,
    valid: np.ndarray,
    policy: Mapping[str, Any],
) -> np.ndarray:
    terrain_rule = policy["components"]["TERRAIN_SUPPORT"]
    hydro_rule = policy["components"]["HYDROLOGY_SUPPORT"]
    flood_rule = policy["components"]["FLOOD_COMPATIBILITY"]
    terrain_score = np.array([transform_score(float(value), terrain_rule) or 0.0 for value in slope])
    hydro_score = np.array([transform_score(float(value), hydro_rule) or 0.0 for value in active_distance])
    flood_score = np.array([transform_score(float(value), flood_rule) or 0.0 for value in flood])
    scores = 0.35 * terrain_score + 0.25 * hydro_score + 0.15 * flood_score + 0.25 * domain_fit
    scores[~valid] = -1.0
    return scores


def candidate_cell_scores(
    slope: np.ndarray,
    active_distance: np.ndarray,
    flood: np.ndarray,
    domain_fit: np.ndarray,
    valid: np.ndarray,
    policy: Mapping[str, Any],
    *,
    algorithm: str | None = None,
) -> np.ndarray:
    """Score independent cells exactly; keep a directly callable reference path."""
    if algorithm is None:
        algorithm = "vectorized" if algorithm_policy.use_optimized("settlement_transforms") else "reference"
    if algorithm == "reference":
        return _candidate_cell_scores_reference(
            slope, active_distance, flood, domain_fit, valid, policy
        )
    if algorithm != "vectorized":
        raise ValueError(f"Unsupported candidate scoring algorithm: {algorithm}")
    terrain_score = _transform_scores_zero(slope, policy["components"]["TERRAIN_SUPPORT"])
    hydro_score = _transform_scores_zero(active_distance, policy["components"]["HYDROLOGY_SUPPORT"])
    flood_score = _transform_scores_zero(flood, policy["components"]["FLOOD_COMPATIBILITY"])
    scores = 0.35 * terrain_score + 0.25 * hydro_score + 0.15 * flood_score + 0.25 * domain_fit
    scores[~valid] = -1.0
    return scores


@dataclass(frozen=True)
class PreparedRasterGroup:
    """One ordered block's exact raster inputs, prepared off the scoring thread."""

    group_index: int
    block_row: int
    block_col: int
    group_sites: tuple[Site, ...]
    candidate_rows: tuple[np.ndarray, ...]
    candidate_cols: tuple[np.ndarray, ...]
    row0: int
    col0: int
    raster: dict[str, np.ndarray]
    barony_grid: np.ndarray


def prepare_raster_group(
    group_index: int,
    grouped_item: tuple[tuple[int, int], Sequence[Site]],
    site_profile_map: Mapping[str, Mapping[str, str]],
    rasters: RasterStack,
    topology: ExactSurfaceIndex,
) -> PreparedRasterGroup:
    """Read and derive the exact cells consumed by one analysis group."""

    (block_row, block_col), site_values = grouped_item
    group_sites = tuple(site_values)
    candidate_pairs = tuple(source_grid_window(site) for site in group_sites)
    candidate_rows = tuple(pair[0] for pair in candidate_pairs)
    candidate_cols = tuple(pair[1] for pair in candidate_pairs)

    # A 120 km grouping unit controls I/O call count; it is not a reason
    # to derive every cell in that unit.  Bound the actual read to the
    # union of consumed 1 km candidate windows and profiled 5 km
    # developability windows.  One extra terrain cell on each side
    # preserves np.gradient's exact neighbour values at every consumed
    # cell, including the one-sided behaviour at the global edge.
    needed_row0 = min(int(values.min()) for values in candidate_rows)
    needed_col0 = min(int(values.min()) for values in candidate_cols)
    needed_row1 = max(int(values.max()) + 1 for values in candidate_rows)
    needed_col1 = max(int(values.max()) + 1 for values in candidate_cols)
    for site in group_sites:
        if site.settlement_id not in site_profile_map:
            continue
        r5_row0, r5_col0, r5_row1, r5_col1 = window_for_radius(site, 5.0)
        needed_row0 = min(needed_row0, r5_row0)
        needed_col0 = min(needed_col0, r5_col0)
        needed_row1 = max(needed_row1, r5_row1)
        needed_col1 = max(needed_col1, r5_col1)
    row0 = max(0, needed_row0 - 1)
    col0 = max(0, needed_col0 - 1)
    row1 = min(18_600, needed_row1 + 1)
    col1 = min(22_000, needed_col1 + 1)
    raster = rasters.read_block(row0, col0, row1 - row0, col1 - col0)
    barony_grid = topology.rasterize_window(row0, col0, row1 - row0, col1 - col0)
    return PreparedRasterGroup(
        group_index=group_index,
        block_row=block_row,
        block_col=block_col,
        group_sites=group_sites,
        candidate_rows=candidate_rows,
        candidate_cols=candidate_cols,
        row0=row0,
        col0=col0,
        raster=raster,
        barony_grid=barony_grid,
    )


class RasterGroupPrefetcher:
    """Bounded ordered prefetch: parallel preparation, deterministic consumption."""

    def __init__(
        self,
        grouped_items: Sequence[tuple[tuple[int, int], Sequence[Site]]],
        site_profile_map: Mapping[str, Mapping[str, str]],
        rasters: RasterStack,
        topology: ExactSurfaceIndex,
        *,
        workers: int = RASTER_PREFETCH_WORKERS,
        depth: int = RASTER_PREFETCH_DEPTH,
        memory_mib: int = RASTER_PREFETCH_MEMORY_MIB,
    ) -> None:
        if workers < 1 or depth < 1 or memory_mib < 1:
            raise ValueError("Prefetch workers, depth and memory must be positive")
        slots = memory_mib * 1024 * 1024 // RASTER_GROUP_ESTIMATED_BYTES
        if slots < 2:
            raise ValueError("Prefetch memory needs at least 256 MiB for one pending and one consumed group")
        self.depth = min(depth, slots - 1)
        self.workers = min(workers, self.depth)
        self._items = iter(enumerate(grouped_items, 1))
        self._site_profile_map = site_profile_map
        self._rasters = rasters
        self._topology = topology
        self._executor = ThreadPoolExecutor(
            max_workers=self.workers,
            thread_name_prefix="stage6c-raster",
        )
        self._pending: deque[Future[PreparedRasterGroup]] = deque()
        self._replace_previous = False
        self._closed = False
        try:
            for _ in range(min(self.depth, len(grouped_items))):
                self._submit_one()
        except BaseException:
            # If submission fails after earlier work was accepted, wait for
            # that work before the caller is allowed to close shared sources.
            self.close()
            raise

    def _submit_one(self) -> None:
        try:
            group_index, grouped_item = next(self._items)
        except StopIteration:
            return
        self._pending.append(self._executor.submit(
            prepare_raster_group,
            group_index,
            grouped_item,
            self._site_profile_map,
            self._rasters,
            self._topology,
        ))

    def __iter__(self) -> "RasterGroupPrefetcher":
        return self

    def __next__(self) -> PreparedRasterGroup:
        if self._replace_previous:
            # Refill only after the caller has consumed the preceding result.
            # Pending futures remain capped at RASTER_PREFETCH_DEPTH; the
            # caller's current result is a separate, still-bounded reference.
            self._submit_one()
            self._replace_previous = False
        if not self._pending:
            raise StopIteration
        prepared = self._pending.popleft().result()
        self._replace_previous = True
        return prepared

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for future in self._pending:
            future.cancel()
        self._executor.shutdown(wait=True, cancel_futures=True)
        self._pending.clear()


@dataclass(frozen=True)
class AssessedGroup:
    """Private completed rows; public append/checkpoint ownership stays central."""

    block: tuple[int, int]
    payload: dict[str, Any]


def _check_assessment_cancelled(cancel_event: Any) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise runtime.GenerationCancelled("Stage 6C assessment cancelled")


def _assess_prepared_group(
    prepared: PreparedRasterGroup,
    vectors: VectorStack,
    profile_by_id: Mapping[str, Mapping[str, Any]],
    site_profile_map: Mapping[str, Mapping[str, str]],
    coordinate_by_id: Mapping[str, Mapping[str, Any]],
    complete_source_identity: Mapping[str, Any],
    cancel_event: Any = None,
) -> AssessedGroup:
    """Compute one group without readers, public writers or shared mutable state.

    Vector indexes/geometries and policy maps are constructed before dispatch
    and queried read-only. Each call owns its candidate arrays and result rows;
    numerical operations and site ordering are the sequential reference recipe.
    """
    _check_assessment_cancelled(cancel_event)
    assessments: list[dict[str, Any]] = []
    exceptions: list[dict[str, Any]] = []
    group_sites = prepared.group_sites
    candidate_rows = prepared.candidate_rows
    candidate_cols = prepared.candidate_cols
    row0, col0 = prepared.row0, prepared.col0
    raster = prepared.raster
    barony_grid = prepared.barony_grid

    all_rows = np.concatenate(candidate_rows)
    all_cols = np.concatenate(candidate_cols)
    all_xs = all_cols.astype(np.float64) * 0.1 + 0.05
    all_ys = all_rows.astype(np.float64) * 0.1 + 0.05
    distance_batch = vectors.candidate_distance_batch(
        all_xs, all_ys, group_sites
    )

    for local_index, site in enumerate(group_sites):
        _check_assessment_cancelled(cancel_event)
        coord = coordinate_by_id[site.settlement_id]
        status = rules.analysis_status_for(
            stage6_active_location=site.active_location,
            stage6_active_settlement=site.active_settlement,
            conditionality_status=site.conditionality,
            effective_vertical_domain=site.vertical_domain,
        )
        profile_link = site_profile_map.get(site.settlement_id)
        profile = profile_by_id[profile_link["profile_id"]] if profile_link else None
        policy = rules.score_policy(profile) if profile else None
        rr = candidate_rows[local_index]
        cc = candidate_cols[local_index]
        lr = rr - row0
        lc = cc - col0
        distances = {
            "active": distance_batch.active_cells[local_index],
            "perennial": distance_batch.perennial_cells[local_index],
            **distance_batch.lagoon_cells.get(local_index, {}),
        }
        class_minima = {
            key: float(values[local_index])
            for key, values in distance_batch.class_minima.items()
        }
        surface = barony_grid[lr, lc] > 0
        same = surface if site.barony_id is None else barony_grid[lr, lc] == site.barony_id
        sea = raster["sea"][lr, lc]
        wetland = raster["wetland"][lr, lc]
        seren = raster["seren"][lr, lc]
        candidate_slope = raster["slope"][lr, lc].astype(np.float64)
        candidate_elevation = raster["terrain"][lr, lc].astype(np.float64)
        candidate_flood = raster["flood_exposure"][lr, lc].astype(np.float64)
        form_water_distance_cells = distances["active"]
        if site.realised_form == "SURFACE_LAGOON_SETTLEMENT":
            form_water_distance_cells = np.minimum.reduce((
                distances["active"], distances["special"], distances["lake"]
            ))
            form_water_distance_cells = np.where(
                seren > 0, 0.0, form_water_distance_cells
            )
        valid, candidate_domain_fit, ordinary_surface_fallback = domain_candidate_mask(
            site, same, surface, sea, wetland, seren, distances
        )
        valid_count = int(valid.sum())
        valid_fraction = valid_count / 100.0
        metric_mask = valid if valid_count else np.ones(100, dtype=bool)

        base_row: dict[str, Any] = {
            "settlement_id": site.settlement_id,
            "scope_status": site_scope(status),
            "analysis_status": status,
            "owner_haus_id": profile_link["owner_haus_id"] if profile_link else None,
            "owner_assignment_basis": profile_link["owner_assignment_basis"] if profile_link else None,
            "profile_id": profile_link["profile_id"] if profile_link else None,
            "effective_vertical_domain": site.vertical_domain,
            **{key: coord[key] for key in (
                "original_display_x_km", "original_display_y_km", "coordinate_semantics_code",
                "coordinate_value_resolution_km", "coordinate_precision_basis", "anchor_status",
                "provisional_anchor", "horizontal_uncertainty_shape", "horizontal_uncertainty_radius_km",
                "vertical_uncertainty_status", "footprint_status",
            )},
            "source_resolution_m": 1000 if coord["coordinate_value_resolution_km"] in (None, 1.0) else int(round(coord["coordinate_value_resolution_km"] * 1000)),
            "source_window_cell_count": 100,
            "context_window_cell_count": 400,
            "context_ring_cell_count": 300,
            "candidate_valid_cell_count": valid_count,
            "candidate_support_fraction": valid_fraction,
            "morphology_class": profile["morphology_class"] if profile else None,
            "capacity_metric_kind": profile["capacity_metric_kind"] if profile else None,
            "access_modes_json": canonical_json([profile["primary_access_mode"]] + json.loads(profile["secondary_access_modes_json"])) if profile else None,
            "method_version": METHOD,
            "canon_status": CANON_STATUS,
        }

        if site.active_location == 0:
            base_row.update({
                "score_uncertainty_status": "NOT_APPLICABLE_INACTIVE",
                "analysis_anchor_selection_status": "NOT_APPLICABLE_INACTIVE",
                "limiting_factors_json": "[]",
                "data_basis_code": "IDENTITY_LINEAGE_ONLY",
                "priority_review": 0,
                "review_status": "NOT_APPLICABLE_INACTIVE",
                "input_fingerprint": stable_hash(canonical_json([
                    site.settlement_id, site.x, site.y, status,
                    complete_source_identity, METHOD,
                ])),
            })
            assessments.append(base_row)
            continue

        terrain_elevation = float(np.median(candidate_elevation[metric_mask]))
        terrain_slope = float(np.median(candidate_slope[metric_mask]))
        slope_p90 = float(np.quantile(candidate_slope[metric_mask], 0.90))
        local_relief = float(np.quantile(candidate_elevation, 0.90) - np.quantile(candidate_elevation, 0.10))
        water_distance = float(np.median(form_water_distance_cells[metric_mask]))
        perennial_distance = float(np.median(distances["perennial"][metric_mask]))
        flood_exposure = float(np.mean(candidate_flood[metric_mask]))
        land_fraction = float(np.mean(surface & (sea == 0)))
        wetland_fraction = float(np.mean(wetland > 0))
        seren_fraction = float(np.mean(seren > 0))

        develop_r1 = develop_r5 = None
        expansion_direction = None
        expansion_weights: dict[str, float] | None = None
        if profile is not None and policy is not None:
            slope_limit = float(policy["components"]["TERRAIN_SUPPORT"].get("p1") or 45.0)
            policy_basis = policy["policy_basis"]
            resolved_policy, _ = rules._resolved_policy(
                profile["realised_settlement_form"], profile["effective_vertical_domain"], profile["haus_id"]
            )
            flood_tolerance = resolved_policy["flood_tolerance"]
            r5_row0, r5_col0, r5_row1, r5_col1 = window_for_radius(site, 5.0)
            r5_lr = slice(r5_row0 - row0, r5_row1 - row0)
            r5_lc = slice(r5_col0 - col0, r5_col1 - col0)
            local_raster = {key: value[r5_lr, r5_lc] for key, value in raster.items()}
            local_barony = barony_grid[r5_lr, r5_lc]
            dev = developable_mask(
                site,
                local_barony,
                local_raster,
                slope_limit,
                flood_tolerance,
                ordinary_surface_fallback,
            )
            grid_rows, grid_cols = np.meshgrid(
                np.arange(r5_row0, r5_row1), np.arange(r5_col0, r5_col1), indexing="ij"
            )
            grid_x = grid_cols * 0.1 + 0.05
            grid_y = grid_rows * 0.1 + 0.05
            distance2 = (grid_x - site.x) ** 2 + (grid_y - site.y) ** 2
            circle5 = distance2 <= 25.0
            circle1 = distance2 <= 1.0
            develop_r1 = float((dev * circle1).sum() * 0.01)
            develop_r5 = float((dev * circle5).sum() * 0.01)
            expansion_direction, expansion_weights = expansion_sectors(
                (dev * circle5).ravel(), grid_rows.ravel(), grid_cols.ravel(), site
            )

        land_access_cost = float(np.clip(
            0.60 * min(terrain_slope / 35.0, 1.0)
            + 0.25 * min(local_relief / 500.0, 1.0)
            + 0.15 * flood_exposure,
            0.0, 1.0,
        ))
        water_access = float(1.0 / (1.0 + water_distance / 2.0))
        seasonal_reliability = float(np.clip(
            0.75 * math.exp(-perennial_distance / 10.0)
            + 0.25 * math.exp(-water_distance / 5.0), 0.0, 1.0
        ))
        domain_fit = float(np.mean(candidate_domain_fit[metric_mask]))

        analysis_anchor_x = analysis_anchor_y = None
        selection_status = "NO_VALID_CANDIDATE"
        best_gap = None
        cell_scores = np.full(100, -1.0)
        if profile is not None and policy is not None and status != "DEFERRED_SPECIALIST_3D":
            cell_scores = candidate_cell_scores(
                candidate_slope, form_water_distance_cells, candidate_flood,
                candidate_domain_fit, valid, policy,
            )
            valid_scores = cell_scores[cell_scores >= 0]
            if len(valid_scores):
                order = np.argsort(cell_scores)[::-1]
                best_index = int(order[0])
                second = float(cell_scores[order[1]]) if len(valid_scores) > 1 else -1.0
                best_gap = float(cell_scores[best_index] - second) if second >= 0 else 1.0
                if best_gap >= 0.05:
                    analysis_anchor_x = float(cc[best_index] * 0.1 + 0.05)
                    analysis_anchor_y = float(rr[best_index] * 0.1 + 0.05)
                    selection_status = "PROVISIONAL_INTERNAL_100M_CELL_DECISIVE"
                else:
                    selection_status = "MULTIPLE_EQUIVALENT_100M_CELLS_NO_RELOCATION"
        elif status == "DEFERRED_SPECIALIST_3D":
            selection_status = "SURFACE_CONTEXT_ONLY_SPECIALIST_3D_DEFERRED"
        elif profile is None:
            selection_status = "NOT_APPLICABLE_NONSETTLEMENT"

        raw_metrics = {
            "terrain_slope_deg": terrain_slope,
            "corrected_surface_water_distance_km": water_distance,
            "flood_exposure_index": flood_exposure,
            "developable_area_r1_km2": develop_r1,
            "developable_area_r5_km2": develop_r5,
            "land_access_cost_index": land_access_cost,
            "water_access_index": water_access,
            "seasonal_reliability_index": seasonal_reliability,
            "domain_fit_index": domain_fit,
        }

        scored: dict[str, Any] | None = None
        if profile is not None and policy is not None:
            physical_scores = cell_scores[cell_scores >= 0]
            spread = float(np.std(physical_scores)) if len(physical_scores) else 0.20
            uncertainty = float(np.clip(0.04 + 0.80 * spread + (0.06 if coord["provisional_anchor"] else 0.0), 0.04, 0.28))
            scored = score_site_metrics(raw_metrics, profile, policy, uncertainty)

        evidence_confidence = 0.92
        if coord["coordinate_value_resolution_km"] is None:
            evidence_confidence -= 0.14
        if coord["provisional_anchor"]:
            evidence_confidence -= 0.12
        if site.vertical_domain == "UNSPECIFIED":
            evidence_confidence -= 0.12
        if status == "DEFERRED_SPECIALIST_3D":
            evidence_confidence -= 0.18
        if class_minima["minor"] < class_minima["major"]:
            evidence_confidence -= 0.03
        evidence_confidence = float(np.clip(evidence_confidence, 0.25, 0.95))

        limiting: list[str] = []
        severity = None
        review_status = "PASS"
        if site.active_settlement and valid_count == 0 and site.vertical_domain not in SPECIAL_3D_DOMAINS:
            limiting.append("NO_VALID_100M_SUPPORT_CELL")
            severity, review_status = "HARD", "HARD_EXCEPTION"
        elif site.active_settlement and valid_count < 5 and site.vertical_domain not in SPECIAL_3D_DOMAINS:
            limiting.append("LESS_THAN_FIVE_VALID_100M_CELLS")
            severity, review_status = "HIGH", "HIGH_EXCEPTION"
        strict_water_threshold = 1.0 if site.realised_form in {
            "SURFACE_LAGOON_SETTLEMENT", "WETLAND_STILT_OR_CHANNEL_SETTLEMENT"
        } else 5.0
        water_role_requires_review = site.realised_form in WATER_DEPENDENT_FORMS and site.realised_form != "FREIGHT_TRANSFER_OR_LANDING_SETTLEMENT"
        active_minimum = float(np.min(form_water_distance_cells))
        if site.active_settlement and water_role_requires_review and active_minimum > strict_water_threshold:
            limiting.append(f"WATER_DEPENDENT_FORM_NO_ACTIVE_WATER_WITHIN_{strict_water_threshold:g}KM")
            severity = severity or "HIGH"
            review_status = "HIGH_EXCEPTION" if review_status == "PASS" else review_status
        if ordinary_surface_fallback:
            # Canon permits ordinary/unbonded humans to occupy supportable
            # surface ground even where an inherited Haus form label is
            # not physically supported at its retained coordinate. Keep
            # the inherited form and coordinate unchanged, assess the
            # available land, and retain the mismatch for human review.
            limiting.append("ORDINARY_HUMAN_SURFACE_FALLBACK_FOR_UNSUPPORTED_WETLAND_FORM")
            severity = severity or "HIGH"
            review_status = "HIGH_EXCEPTION" if review_status == "PASS" else review_status
        if site.barony_id is None:
            limiting.append("INHERITED_JURISDICTION_UNRESOLVED")
        if status == "DEFERRED_SPECIALIST_3D":
            limiting.append("SPECIALIST_3D_GEOMETRY_DEFERRED_TO_LATER_PASS")
            review_status = "DEFERRED_SPECIALIST_3D"
        elif not site.active_settlement:
            review_status = "NOT_APPLICABLE_NONSETTLEMENT"
        elif selection_status.startswith("MULTIPLE_EQUIVALENT") and site.functional_tier in {
            "FT0_HAUS_PRINCIPAL_SITE", "FT1_MAJOR_REGIONAL_HUB"
        }:
            limiting.append("HIGH_PRIORITY_SITE_HAS_EQUIVALENT_100M_CELLS")
            if review_status == "PASS":
                review_status = "REVIEW_PRIORITY_EQUIVALENT_CELLS"

        if scored:
            for component, value in scored["component_scores"].items():
                if value is not None and value < 0.35:
                    limiting.append(f"LOW_{component}")

        score_uncertainty = (
            "SURFACE_CONTEXT_ONLY_3D_DEFERRED" if status == "DEFERRED_SPECIALIST_3D"
            else "PARTIALLY_QUANTIFIED_1KM_WINDOW_ASSUMPTION" if coord["coordinate_value_resolution_km"] is None
            else "QUANTIFIED_1KM_SOURCE_WINDOW"
        )
        fingerprint = stable_hash(canonical_json([
            site.settlement_id, site.x, site.y, site.barony_id,
            profile_link["profile_id"] if profile_link else None,
            complete_source_identity, METHOD,
        ]))
        base_row.update({
            "score_uncertainty_status": score_uncertainty,
            "analysis_anchor_x_km": analysis_anchor_x,
            "analysis_anchor_y_km": analysis_anchor_y,
            "analysis_anchor_selection_status": selection_status,
            "best_second_score_gap": best_gap,
            "terrain_elevation_m": terrain_elevation,
            "terrain_slope_deg": terrain_slope,
            "terrain_slope_p90_deg": slope_p90,
            "local_relief_m": local_relief,
            "land_fraction": land_fraction,
            "wetland_fraction": wetland_fraction,
            "serenakrone_water_fraction": seren_fraction,
            "corrected_surface_water_distance_km": water_distance,
            "corrected_perennial_channel_distance_km": perennial_distance,
            "min_major_distance_km": class_minima["major"],
            "min_minor_distance_km": class_minima["minor"],
            "min_special_water_distance_km": class_minima["special"],
            "min_permanent_lake_distance_km": class_minima["lake"],
            "min_seasonal_lake_distance_km": class_minima["seasonal_lake"],
            "min_coast_distance_km": class_minima["coast"],
            "hydrology_basis": (
                "SEALED_V4_2_MAJOR_PLUS_D3_FEEDERS_PLUS_CORRECTED_STILLKLINGE_LOCAL_PLUS_"
                "STRICT_SPECIAL_PLUS_RESOLVED_LAKES_PLUS_COAST; NOT_MAJOR_ONLY"
                + (
                    "; LAGOON_FORM_ALSO_USES_MANAGED_SERENAKRONE_OVERLAY"
                    if site.realised_form == "SURFACE_LAGOON_SETTLEMENT" else ""
                )
            ),
            "flood_exposure_index": flood_exposure,
            "developable_area_r1_km2": develop_r1,
            "developable_area_r5_km2": develop_r5,
            "land_access_cost_index": land_access_cost,
            "water_access_index": water_access,
            "seasonal_reliability_index": seasonal_reliability,
            "domain_fit_index": domain_fit,
            "expansion_direction_8way": expansion_direction,
            "expansion_sector_weights_json": canonical_json(expansion_weights) if expansion_weights is not None else None,
            "terrain_support_score": scored["component_scores"]["TERRAIN_SUPPORT"] if scored else None,
            "hydrology_support_score": scored["component_scores"]["HYDROLOGY_SUPPORT"] if scored else None,
            "flood_compatibility_score": scored["component_scores"]["FLOOD_COMPATIBILITY"] if scored else None,
            "core_capacity_score": scored["component_scores"]["CORE_CAPACITY"] if scored else None,
            "expansion_capacity_score": scored["component_scores"]["EXPANSION_CAPACITY"] if scored else None,
            "land_access_score": scored["component_scores"]["LAND_ACCESS"] if scored else None,
            "water_access_score": scored["component_scores"]["WATER_ACCESS"] if scored else None,
            "seasonal_reliability_score": scored["component_scores"]["SEASONAL_RELIABILITY"] if scored else None,
            "domain_fit_score": scored["component_scores"]["DOMAIN_FIT"] if scored else None,
            "capacity_support_score_low": scored["capacity_low"] if scored else None,
            "capacity_support_score": scored["capacity"] if scored else None,
            "capacity_support_score_high": scored["capacity_high"] if scored else None,
            "access_support_score_low": scored["access_low"] if scored else None,
            "access_support_score": scored["access"] if scored else None,
            "access_support_score_high": scored["access_high"] if scored else None,
            "evidence_confidence_score": evidence_confidence,
            "capacity_band": scored["capacity_band"] if scored else None,
            "limiting_factors_json": canonical_json(sorted(set(limiting))),
            "data_basis_code": "EDITABLE_ZARR_TERRAIN_AUTHORITY+SEALED_D3_1_STILLKLINGE_LINEAGE+EXACT_SURFACE_BARONY+V4_2_HYDROLOGY+H2_2_MASKS",
            "priority_review": 0,
            "review_status": review_status,
            "input_fingerprint": fingerprint,
        })
        assessments.append(base_row)
        if severity is not None:
            exceptions.append({
                "exception_id": "S6C-E-" + stable_hash(site.settlement_id + "|" + "|".join(sorted(set(limiting))))[:20].upper(),
                "settlement_id": site.settlement_id,
                "severity": severity,
                "exception_code": ";".join(sorted(set(limiting))),
                "details_json": canonical_json({"valid_cells": valid_count, "water_min_km": active_minimum}),
                "review_status": "OPEN_AUTOMATED_REVIEW",
            })


    return AssessedGroup((prepared.block_row, prepared.block_col), {
        "schema": "diadem.stage6c-assessment-group.v1",
        "site_ids": [site.settlement_id for site in group_sites],
        "assessments": assessments,
        "exceptions": exceptions,
        "hydrology_composition": dict(vectors.hydrology_composition),
    })


def assess_all_sites(
    sites: Sequence[Site],
    profiles: Sequence[Mapping[str, Any]],
    site_profile_map: Mapping[str, Mapping[str, str]],
    coordinate_rows: Sequence[Mapping[str, Any]],
    authority_descriptor: Mapping[str, Any],
    *,
    sample_limit: int | None = None,
    water_query_mode: str = WATER_QUERY_DEFAULT,
    hydrology_composition_out: dict[str, int] | None = None,
    checkpoint_store: runtime.CheckpointStore | None = None,
    prefetch_workers: int = RASTER_PREFETCH_WORKERS,
    prefetch_depth: int = RASTER_PREFETCH_DEPTH,
    prefetch_memory_mib: int = RASTER_PREFETCH_MEMORY_MIB,
    runtime_stats: runtime.RuntimeStats | None = None,
    workers: int = 1,
    memory_budget_mb: int = 1024,
    cancel_event: Any = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    stats = runtime_stats or runtime.RuntimeStats()
    if type(workers) is not int or workers < 1:
        raise ValueError("Assessment workers must be a positive integer")
    if type(memory_budget_mb) is not int or memory_budget_mb < 256:
        raise ValueError("Assessment memory budget must be at least 256 MiB")
    if cancel_event is not None and not callable(getattr(cancel_event, "is_set", None)):
        raise TypeError("cancel_event must provide is_set()")
    _check_assessment_cancelled(cancel_event)
    if sample_limit is not None:
        sites = sites[:sample_limit]
    profile_by_id = {str(row["profile_id"]): dict(row) for row in profiles}
    coordinate_by_id = {str(row["settlement_id"]): dict(row) for row in coordinate_rows}
    complete_source_identity = source_fingerprint_identity(authority_descriptor)
    assessments: list[dict[str, Any]] = []
    exceptions: list[dict[str, Any]] = []

    grouped: dict[tuple[int, int], list[Site]] = defaultdict(list)
    for site in sites:
        row = min(18_599, max(0, int(site.y / 0.1)))
        col = min(21_999, max(0, int(site.x / 0.1)))
        grouped[(row // ANALYSIS_BLOCK_SIZE, col // ANALYSIS_BLOCK_SIZE)].append(site)

    ordered_groups = sorted(grouped.items())
    saved_groups: dict[tuple[int, int], Mapping[str, Any]] = {}
    group_keys: dict[tuple[int, int], str] = {}
    checkpoint_contract = stable_hash(canonical_json({
        "profiles": profiles, "sources": complete_source_identity,
        "water_query_mode": water_query_mode,
    })) if checkpoint_store is not None else None
    for block, group_sites in ordered_groups:
        _check_assessment_cancelled(cancel_event)
        if checkpoint_store is None:
            break
        key = stable_hash(canonical_json({
            "block": block, "sites": [asdict(site) for site in group_sites],
            "contract": checkpoint_contract,
            "profile_links": {site.settlement_id: site_profile_map.get(site.settlement_id) for site in group_sites},
            "coordinates": [coordinate_by_id[site.settlement_id] for site in group_sites],
        }))
        group_keys[block] = key
        with stats.measure("group_checkpoint_lookup"):
            saved = checkpoint_store.load(key)
        if _valid_group_checkpoint(saved, group_sites):
            saved_groups[block] = saved
    missing_groups = [item for item in ordered_groups if item[0] not in saved_groups]
    rasters: RasterStack | None = None
    if hydrology_composition_out is not None:
        hydrology_composition_out.clear()

    start_time = time.monotonic()
    prefetcher: RasterGroupPrefetcher | None = None
    results: Iterator[AssessedGroup] | None = None
    try:
        if missing_groups:
            # The allowance includes raster preparation/transients, candidate
            # geometry and private result rows. It is admission, not a promise
            # about total process RAM or separately resident source indexes.
            estimated_group_bytes = max(
                256 * 1024 * 1024,
                RASTER_GROUP_ESTIMATED_BYTES
                + max(len(group_sites) for _, group_sites in missing_groups) * 128 * 1024,
            )
            if estimated_group_bytes > memory_budget_mb * 1024 * 1024:
                raise ValueError("Assessment memory budget cannot admit one estimated group")
            # The serial reference may overlap raster preparation, but those
            # extra buffers must fit after reserving the current scoring group.
            prefetch_slots = (memory_budget_mb * 1024 * 1024 - estimated_group_bytes) // RASTER_GROUP_ESTIMATED_BYTES
            topology = ExactSurfaceIndex(
                Path(SOURCES["exact_surface_registry"]["path"]),
                Path(SOURCES["fragment_barony_assignment"]["path"]),
            )
            vectors = VectorStack(water_query_mode)
            rasters = RasterStack(authority_descriptor)

            def prepared_groups() -> Iterator[PreparedRasterGroup]:
                nonlocal prefetcher
                if workers == 1 and prefetch_slots:
                    # Preserve the accepted serial assessment/reference path's
                    # raster prefetch, capped by the shared admission budget.
                    prefetcher = RasterGroupPrefetcher(
                        missing_groups, site_profile_map, rasters, topology,
                        workers=prefetch_workers, depth=min(prefetch_depth, prefetch_slots),
                        memory_mib=prefetch_memory_mib,
                    )
                    yield from prefetcher
                    return
                # A single producer owns all raster/terrain readers. There is
                # no nested prefetch executor underneath assessment workers.
                for index, item in enumerate(missing_groups, 1):
                    _check_assessment_cancelled(cancel_event)
                    with stats.measure("group_prepare"):
                        prepared = prepare_raster_group(
                            index, item, site_profile_map, rasters, topology,
                        )
                    for array in (
                        *prepared.candidate_rows, *prepared.candidate_cols,
                        *prepared.raster.values(), prepared.barony_grid,
                    ):
                        array.setflags(write=False)
                    del array
                    yield prepared
                    del prepared

            def compute_group(prepared: PreparedRasterGroup) -> AssessedGroup:
                with stats.measure("group_compute"):
                    return _assess_prepared_group(
                        prepared, vectors, profile_by_id, site_profile_map,
                        coordinate_by_id, complete_source_identity, cancel_event,
                    )

            results = runtime.bounded_map(
                compute_group, prepared_groups(), workers=workers,
                memory_budget_bytes=memory_budget_mb * 1024 * 1024,
                estimated_task_bytes=estimated_group_bytes,
                cancel_event=cancel_event,
                stats=stats, phase="assessment_groups",
            )
        for group_index, (block, group_sites) in enumerate(ordered_groups, 1):
            _check_assessment_cancelled(cancel_event)
            saved = saved_groups.get(block)
            if saved is not None:
                stats.increment("groups_reused")
                assessments.extend(saved["assessments"])
                exceptions.extend(saved["exceptions"])
                if hydrology_composition_out is not None:
                    hydrology_composition_out.update(saved["hydrology_composition"])
                continue
            assert results is not None
            result = next(results)
            if result.block != block:
                raise RuntimeError("Assessment result order changed")
            _check_assessment_cancelled(cancel_event)
            with stats.measure("group_commit"):
                payload = result.payload
                if checkpoint_store is not None:
                    checkpoint_store.save(group_keys[block], payload)
                assessments.extend(payload["assessments"])
                exceptions.extend(payload["exceptions"])
                if hydrology_composition_out is not None:
                    hydrology_composition_out.update(payload["hydrology_composition"])
            del payload, result
            stats.increment("groups_generated")
            if group_index % 50 == 0 or group_index == len(grouped):
                elapsed = time.monotonic() - start_time
                print(f"ANALYSIS_PROGRESS blocks={group_index}/{len(grouped)} rows={len(assessments)} elapsed_s={elapsed:.1f}", flush=True)
    finally:
        try:
            # Close/join compute workers before closing the producer's readers,
            # including failures, cancellation and partially consumed results.
            if results is not None:
                results.close()
        finally:
            try:
                if prefetcher is not None:
                    prefetcher.close()
            finally:
                if rasters is not None:
                    rasters.close()
                stats.seconds["assessment_pipeline_wall"] = time.monotonic() - start_time
    return assessments, exceptions


def _valid_group_checkpoint(saved: Any, sites: Sequence[Site]) -> bool:
    if not isinstance(saved, dict) or saved.get("schema") != "diadem.stage6c-assessment-group.v1":
        return False
    ids = [site.settlement_id for site in sites]
    rows, exceptions = saved.get("assessments"), saved.get("exceptions")
    if saved.get("site_ids") != ids or not isinstance(rows, list) or not isinstance(exceptions, list):
        return False
    if any(not isinstance(row, dict) for row in rows + exceptions):
        return False
    if [row.get("settlement_id") for row in rows] != ids:
        return False
    if any(row.get("settlement_id") not in ids for row in exceptions):
        return False
    return isinstance(saved.get("hydrology_composition"), dict)


ASSESSMENT_COLUMNS = [
    "settlement_id", "scope_status", "analysis_status", "owner_haus_id", "owner_assignment_basis",
    "profile_id", "effective_vertical_domain", "original_display_x_km", "original_display_y_km",
    "coordinate_semantics_code", "coordinate_value_resolution_km", "coordinate_precision_basis",
    "anchor_status", "provisional_anchor", "horizontal_uncertainty_shape",
    "horizontal_uncertainty_radius_km", "vertical_uncertainty_status", "footprint_status",
    "score_uncertainty_status", "source_resolution_m", "source_window_cell_count",
    "context_window_cell_count", "context_ring_cell_count", "candidate_valid_cell_count",
    "candidate_support_fraction", "analysis_anchor_x_km", "analysis_anchor_y_km",
    "analysis_anchor_selection_status", "best_second_score_gap", "terrain_elevation_m",
    "terrain_slope_deg", "terrain_slope_p90_deg", "local_relief_m", "land_fraction",
    "wetland_fraction", "serenakrone_water_fraction", "corrected_surface_water_distance_km",
    "corrected_perennial_channel_distance_km", "min_major_distance_km", "min_minor_distance_km",
    "min_special_water_distance_km", "min_permanent_lake_distance_km",
    "min_seasonal_lake_distance_km", "min_coast_distance_km", "hydrology_basis",
    "flood_exposure_index", "developable_area_r1_km2", "developable_area_r5_km2",
    "land_access_cost_index", "water_access_index", "seasonal_reliability_index", "domain_fit_index",
    "morphology_class", "capacity_metric_kind", "access_modes_json", "expansion_direction_8way",
    "expansion_sector_weights_json", "terrain_support_score", "hydrology_support_score",
    "flood_compatibility_score", "core_capacity_score", "expansion_capacity_score",
    "land_access_score", "water_access_score", "seasonal_reliability_score", "domain_fit_score",
    "capacity_support_score_low", "capacity_support_score", "capacity_support_score_high",
    "access_support_score_low", "access_support_score", "access_support_score_high",
    "evidence_confidence_score", "capacity_band", "limiting_factors_json", "data_basis_code",
    "priority_review", "review_status", "input_fingerprint", "method_version", "canon_status",
]


def create_stage6c_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        PRAGMA foreign_keys=ON;
        CREATE TABLE stage6c_source_manifest (
            source_role TEXT PRIMARY KEY,
            source_path TEXT NOT NULL,
            sha256 TEXT NOT NULL CHECK(length(sha256)=64),
            source_version TEXT,
            required INTEGER NOT NULL CHECK(required IN (0,1)),
            source_status TEXT NOT NULL,
            feature_or_record_count INTEGER,
            note TEXT,
            authority_id TEXT,
            authority_generation INTEGER CHECK(authority_generation IS NULL OR authority_generation >= 0),
            authority_root_hash TEXT CHECK(authority_root_hash IS NULL OR length(authority_root_hash)=64),
            sealed_tiff_lineage_json TEXT
        ) WITHOUT ROWID;

        CREATE TABLE stage6c_coordinate_semantics_catalog (
            coordinate_semantics_code TEXT PRIMARY KEY,
            source_semantics_exact TEXT UNIQUE,
            selection_rule TEXT NOT NULL,
            value_resolution_km REAL,
            anchor_status TEXT NOT NULL,
            provisional_anchor INTEGER NOT NULL CHECK(provisional_anchor IN (0,1)),
            horizontal_uncertainty_shape TEXT NOT NULL,
            default_horizontal_uncertainty_radius_km REAL,
            vertical_uncertainty_status TEXT NOT NULL,
            footprint_status TEXT NOT NULL,
            basis TEXT NOT NULL
        ) WITHOUT ROWID;

        CREATE TABLE stage6c_profile_catalog (
            profile_id TEXT PRIMARY KEY,
            haus_id TEXT NOT NULL,
            realised_settlement_form TEXT NOT NULL,
            effective_vertical_domain TEXT NOT NULL,
            site_count INTEGER NOT NULL,
            morphology_class TEXT NOT NULL,
            capacity_metric_kind TEXT NOT NULL,
            primary_access_mode TEXT NOT NULL,
            secondary_access_modes_json TEXT NOT NULL CHECK(json_valid(secondary_access_modes_json)),
            capacity_operator TEXT NOT NULL,
            access_operator TEXT NOT NULL,
            footprint_recipe_family TEXT NOT NULL,
            band_t1 REAL NOT NULL,
            band_t2 REAL NOT NULL,
            band_t3 REAL NOT NULL,
            band_t4 REAL NOT NULL,
            profile_basis TEXT NOT NULL,
            method_version TEXT NOT NULL,
            canon_status TEXT NOT NULL,
            UNIQUE(haus_id, realised_settlement_form, effective_vertical_domain)
        ) WITHOUT ROWID;

        CREATE TABLE stage6c_profile_component (
            profile_id TEXT NOT NULL REFERENCES stage6c_profile_catalog(profile_id),
            component_code TEXT NOT NULL,
            component_group TEXT NOT NULL CHECK(component_group IN ('CAPACITY','ACCESS')),
            raw_metric_code TEXT NOT NULL,
            transform_code TEXT NOT NULL,
            p0 REAL, p1 REAL, p2 REAL, p3 REAL,
            weight REAL NOT NULL CHECK(weight BETWEEN 0.0 AND 1.0),
            required INTEGER NOT NULL CHECK(required IN (0,1)),
            missing_policy TEXT NOT NULL,
            PRIMARY KEY(profile_id, component_code)
        ) WITHOUT ROWID;

        CREATE TABLE stage6c_site_assessment (
            settlement_id TEXT PRIMARY KEY,
            scope_status TEXT NOT NULL,
            analysis_status TEXT NOT NULL,
            owner_haus_id TEXT,
            owner_assignment_basis TEXT,
            profile_id TEXT REFERENCES stage6c_profile_catalog(profile_id),
            effective_vertical_domain TEXT NOT NULL,
            original_display_x_km REAL NOT NULL,
            original_display_y_km REAL NOT NULL,
            coordinate_semantics_code TEXT NOT NULL REFERENCES stage6c_coordinate_semantics_catalog(coordinate_semantics_code),
            coordinate_value_resolution_km REAL,
            coordinate_precision_basis TEXT NOT NULL,
            anchor_status TEXT NOT NULL,
            provisional_anchor INTEGER NOT NULL CHECK(provisional_anchor IN (0,1)),
            horizontal_uncertainty_shape TEXT NOT NULL,
            horizontal_uncertainty_radius_km REAL,
            vertical_uncertainty_status TEXT NOT NULL,
            footprint_status TEXT NOT NULL,
            score_uncertainty_status TEXT NOT NULL,
            source_resolution_m INTEGER,
            source_window_cell_count INTEGER,
            context_window_cell_count INTEGER,
            context_ring_cell_count INTEGER,
            candidate_valid_cell_count INTEGER,
            candidate_support_fraction REAL,
            analysis_anchor_x_km REAL,
            analysis_anchor_y_km REAL,
            analysis_anchor_selection_status TEXT,
            best_second_score_gap REAL,
            terrain_elevation_m REAL,
            terrain_slope_deg REAL,
            terrain_slope_p90_deg REAL,
            local_relief_m REAL,
            land_fraction REAL,
            wetland_fraction REAL,
            serenakrone_water_fraction REAL,
            corrected_surface_water_distance_km REAL,
            corrected_perennial_channel_distance_km REAL,
            min_major_distance_km REAL,
            min_minor_distance_km REAL,
            min_special_water_distance_km REAL,
            min_permanent_lake_distance_km REAL,
            min_seasonal_lake_distance_km REAL,
            min_coast_distance_km REAL,
            hydrology_basis TEXT,
            flood_exposure_index REAL,
            developable_area_r1_km2 REAL,
            developable_area_r5_km2 REAL,
            land_access_cost_index REAL,
            water_access_index REAL,
            seasonal_reliability_index REAL,
            domain_fit_index REAL,
            morphology_class TEXT,
            capacity_metric_kind TEXT,
            access_modes_json TEXT CHECK(access_modes_json IS NULL OR json_valid(access_modes_json)),
            expansion_direction_8way TEXT,
            expansion_sector_weights_json TEXT CHECK(expansion_sector_weights_json IS NULL OR json_valid(expansion_sector_weights_json)),
            terrain_support_score REAL,
            hydrology_support_score REAL,
            flood_compatibility_score REAL,
            core_capacity_score REAL,
            expansion_capacity_score REAL,
            land_access_score REAL,
            water_access_score REAL,
            seasonal_reliability_score REAL,
            domain_fit_score REAL,
            capacity_support_score_low REAL,
            capacity_support_score REAL,
            capacity_support_score_high REAL,
            access_support_score_low REAL,
            access_support_score REAL,
            access_support_score_high REAL,
            evidence_confidence_score REAL,
            capacity_band TEXT,
            limiting_factors_json TEXT NOT NULL CHECK(json_valid(limiting_factors_json)),
            data_basis_code TEXT NOT NULL,
            priority_review INTEGER NOT NULL CHECK(priority_review IN (0,1)),
            review_status TEXT NOT NULL,
            input_fingerprint TEXT NOT NULL,
            method_version TEXT NOT NULL,
            canon_status TEXT NOT NULL
        ) WITHOUT ROWID;

        CREATE TABLE stage6c_exception_queue (
            exception_id TEXT PRIMARY KEY,
            settlement_id TEXT NOT NULL,
            severity TEXT NOT NULL,
            exception_code TEXT NOT NULL,
            details_json TEXT NOT NULL CHECK(json_valid(details_json)),
            review_status TEXT NOT NULL
        ) WITHOUT ROWID;

        CREATE TABLE stage6c_review_sample (
            sample_order INTEGER PRIMARY KEY,
            settlement_id TEXT NOT NULL UNIQUE,
            owner_haus_id TEXT NOT NULL,
            selection_reason TEXT NOT NULL,
            stable_selection_hash TEXT NOT NULL
        );

        CREATE INDEX stage6c_assessment_profile_idx ON stage6c_site_assessment(profile_id);
        CREATE INDEX stage6c_assessment_status_idx ON stage6c_site_assessment(analysis_status);
        CREATE INDEX stage6c_assessment_review_idx ON stage6c_site_assessment(priority_review, review_status);

        CREATE VIEW stage6c_population_inputs AS
        SELECT s.settlement_id, s.barony_id, s.stage6b_realised_settlement_form,
               s.stage6b_functional_tier, s.stage6_ordinary_permanent_human_settlement,
               a.*
        FROM settlement s
        JOIN stage6c_site_assessment a USING(settlement_id)
        WHERE s.stage6_active_settlement = 1;

        CREATE VIEW stage6c_review_exceptions AS
        SELECT * FROM stage6c_site_assessment
        WHERE review_status <> 'PASS'
           OR score_uncertainty_status NOT LIKE 'QUANTIFIED%'
           OR analysis_status LIKE 'DEFERRED%';

        CREATE VIEW stage6c_priority_review AS
        SELECT a.*
        FROM stage6c_site_assessment a
        JOIN settlement s USING(settlement_id)
        WHERE (
            s.stage6_active_settlement = 1
            AND (
                s.stage6b_functional_tier IN ('FT0_HAUS_PRINCIPAL_SITE','FT1_MAJOR_REGIONAL_HUB')
                OR s.stage6b_realised_settlement_form IN (
                    'SURFACE_FACING_SHAFT_OR_AIR_CAVERN_SETTLEMENT',
                    'SURFACE_LAGOON_SETTLEMENT',
                    'SUBMERGED_OR_CAVERN_SETTLEMENT',
                    'FULLY_SUBMERGED_NATIVE_SPECIALIST_SETTLEMENT',
                    'FREIGHT_TRANSFER_OR_LANDING_SETTLEMENT'
                )
            )
        )
        OR (
            s.stage6_active_location = 1
            AND s.stage6b_location_role = 'MOBILE_COURT_HOST_ANCHOR'
        )
        OR s.settlement_id IN (
            SELECT value
            FROM stage6b_unresolved_functional_assignment,
                 json_each(candidate_site_ids_json)
        );
        """
    )


def insert_rows(connection: sqlite3.Connection, table: str, rows: Sequence[Mapping[str, Any]], columns: Sequence[str]) -> None:
    placeholders = ",".join("?" for _ in columns)
    names = ",".join(f'"{column}"' for column in columns)
    connection.executemany(
        f'INSERT INTO "{table}" ({names}) VALUES ({placeholders})',
        [[row.get(column) for column in columns] for row in rows],
    )


def deterministic_review_sample(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    seed = "DIADEM_STAGE6C_REVIEW_V1"
    candidates = [dict(row) for row in connection.execute(
        """
        SELECT a.settlement_id, a.owner_haus_id, a.effective_vertical_domain,
               s.stage6b_functional_tier, s.stage6b_realised_settlement_form
        FROM stage6c_site_assessment a
        JOIN settlement s USING(settlement_id)
        WHERE a.analysis_status='READY_2D_CURRENT'
          AND s.stage6b_functional_tier NOT IN ('FT0_HAUS_PRINCIPAL_SITE','FT1_MAJOR_REGIONAL_HUB')
        ORDER BY a.settlement_id
        """
    )]
    for row in candidates:
        row["stable_hash"] = stable_hash(seed + "|" + row["settlement_id"])
    by_haus: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in candidates:
        by_haus[row["owner_haus_id"]].append(row)

    selected: list[tuple[dict[str, Any], str]] = []
    selected_ids: set[str] = set()
    for haus_id in sorted(by_haus):
        pool = sorted(by_haus[haus_id], key=lambda row: row["stable_hash"])
        covered: set[tuple[str, str]] = set()
        haus_selected: list[dict[str, Any]] = []
        for row in pool:
            stratum = (row["effective_vertical_domain"], row["stage6b_functional_tier"])
            if stratum not in covered:
                haus_selected.append(row)
                covered.add(stratum)
            if len(haus_selected) >= 15:
                break
        for row in pool:
            if len(haus_selected) >= 15:
                break
            if row["settlement_id"] not in {item["settlement_id"] for item in haus_selected}:
                haus_selected.append(row)
        for row in haus_selected:
            if row["settlement_id"] not in selected_ids:
                selected.append((row, "HAUS_DOMAIN_TIER_STRATIFIED"))
                selected_ids.add(row["settlement_id"])

    global_pool = sorted(candidates, key=lambda row: row["stable_hash"])
    for row in global_pool:
        if len(selected) >= 300:
            break
        if row["settlement_id"] not in selected_ids:
            selected.append((row, "GLOBAL_FILL_LEAST_AVAILABLE_STRATA"))
            selected_ids.add(row["settlement_id"])
    if len(selected) != 300:
        raise AssertionError(f"Review sample expected 300 sites, got {len(selected)}")
    return [
        {
            "sample_order": index,
            "settlement_id": row["settlement_id"],
            "owner_haus_id": row["owner_haus_id"],
            "selection_reason": reason,
            "stable_selection_hash": row["stable_hash"],
        }
        for index, (row, reason) in enumerate(selected, 1)
    ]


def table_digest(connection: sqlite3.Connection, table: str) -> str:
    columns = [row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')]
    encoded_rows: list[str] = []
    for row in connection.execute(f'SELECT * FROM "{table}"'):
        encoded_rows.append(canonical_json({column: row[index] for index, column in enumerate(columns)}))
    encoded_rows.sort()
    digest = hashlib.sha256()
    for encoded in encoded_rows:
        digest.update(encoded.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def build_database(
    source_manifest: Sequence[Mapping[str, Any]],
    profiles: Sequence[Mapping[str, Any]],
    components: Sequence[Mapping[str, Any]],
    coordinate_catalog: Sequence[Mapping[str, Any]],
    assessments: Sequence[Mapping[str, Any]],
    exceptions: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    with sqlite3.connect(OUT_DB) as connection:
        connection.row_factory = sqlite3.Row
        create_stage6c_schema(connection)
        insert_rows(connection, "stage6c_source_manifest", source_manifest, [
            "source_role", "source_path", "sha256", "source_version", "required",
            "source_status", "feature_or_record_count", "note", "authority_id",
            "authority_generation", "authority_root_hash", "sealed_tiff_lineage_json",
        ])
        insert_rows(connection, "stage6c_coordinate_semantics_catalog", coordinate_catalog, [
            "coordinate_semantics_code", "source_semantics_exact", "selection_rule", "value_resolution_km",
            "anchor_status", "provisional_anchor", "horizontal_uncertainty_shape",
            "default_horizontal_uncertainty_radius_km", "vertical_uncertainty_status", "footprint_status", "basis",
        ])
        insert_rows(connection, "stage6c_profile_catalog", profiles, [
            "profile_id", "haus_id", "realised_settlement_form", "effective_vertical_domain", "site_count",
            "morphology_class", "capacity_metric_kind", "primary_access_mode", "secondary_access_modes_json",
            "capacity_operator", "access_operator", "footprint_recipe_family", "band_t1", "band_t2", "band_t3",
            "band_t4", "profile_basis", "method_version", "canon_status",
        ])
        insert_rows(connection, "stage6c_profile_component", components, [
            "profile_id", "component_code", "component_group", "raw_metric_code", "transform_code",
            "p0", "p1", "p2", "p3", "weight", "required", "missing_policy",
        ])
        insert_rows(connection, "stage6c_site_assessment", assessments, ASSESSMENT_COLUMNS)
        insert_rows(connection, "stage6c_exception_queue", exceptions, [
            "exception_id", "settlement_id", "severity", "exception_code", "details_json", "review_status",
        ])
        review_sample = deterministic_review_sample(connection)
        insert_rows(connection, "stage6c_review_sample", review_sample, [
            "sample_order", "settlement_id", "owner_haus_id", "selection_reason", "stable_selection_hash",
        ])
        priority_count = connection.execute("SELECT COUNT(*) FROM stage6c_priority_review").fetchone()[0]
        if priority_count != 273:
            raise AssertionError(f"Expected 273 priority-review records, got {priority_count}")
        connection.execute(
            "UPDATE stage6c_site_assessment SET priority_review=1 WHERE settlement_id IN (SELECT settlement_id FROM stage6c_priority_review)"
        )
        connection.execute("INSERT OR REPLACE INTO metadata(key,value) VALUES('stage6c_method_version',?)", (METHOD,))
        connection.execute("INSERT OR REPLACE INTO metadata(key,value) VALUES('stage6c_canon_status',?)", (CANON_STATUS,))
        connection.execute("INSERT OR REPLACE INTO metadata(key,value) VALUES('stage6c_grid_note',?)", (GRID_NOTE,))
        connection.commit()
        status_counts = dict(connection.execute(
            "SELECT analysis_status,COUNT(*) FROM stage6c_site_assessment GROUP BY analysis_status"
        ))
        digests = {
            table: table_digest(connection, table)
            for table in (
                "stage6c_source_manifest", "stage6c_coordinate_semantics_catalog", "stage6c_profile_catalog",
                "stage6c_profile_component", "stage6c_site_assessment", "stage6c_exception_queue",
                "stage6c_review_sample",
            )
        }
    return {"status_counts": status_counts, "priority_count": priority_count, "review_sample_count": 300, "table_digests": digests}


def register_gpkg_attributes() -> dict[str, str]:
    before = gpkg_geometry_digests(OUT_GPKG)
    with sqlite3.connect(OUT_GPKG) as connection:
        connection.execute("ATTACH DATABASE ? AS stage6cdb", (str(OUT_DB),))
        # Qualify the destination schema explicitly. Without `main.`, SQLite may
        # resolve this name to the attached Stage 6C source database when the
        # GeoPackage has no existing copy, deleting the source table before the
        # following SELECT can copy it.
        connection.execute("DROP TABLE IF EXISTS main.stage6c_site_assessment")
        connection.execute("CREATE TABLE stage6c_site_assessment AS SELECT * FROM stage6cdb.stage6c_site_assessment")
        connection.execute("CREATE UNIQUE INDEX stage6c_site_assessment_id_idx ON stage6c_site_assessment(settlement_id)")
        connection.execute(
            """
            INSERT OR REPLACE INTO gpkg_contents(
                table_name,data_type,identifier,description,last_change,min_x,min_y,max_x,max_y,srs_id
            ) VALUES(
                'stage6c_site_assessment','attributes','stage6c_site_assessment',
                'Stage 6C 100 m review-only spatial context; join to settlement by settlement_id',
                ?,NULL,NULL,NULL,NULL,NULL
            )
            """,
            (utc_now(),),
        )
        connection.commit()
    after = gpkg_geometry_digests(OUT_GPKG)
    if before != after:
        raise AssertionError("Inherited GeoPackage geometry digest changed")
    return after


def export_review_tables(connection: sqlite3.Connection) -> list[Path]:
    exports: list[tuple[str, str]] = [
        ("STAGE6C_SITE_ASSESSMENTS.csv", "SELECT * FROM stage6c_site_assessment ORDER BY settlement_id"),
        ("STAGE6C_PROFILE_CATALOG.csv", "SELECT * FROM stage6c_profile_catalog ORDER BY profile_id"),
        ("STAGE6C_PROFILE_COMPONENTS.csv", "SELECT * FROM stage6c_profile_component ORDER BY profile_id,component_code"),
        ("STAGE6C_SOURCE_MANIFEST.csv", "SELECT * FROM stage6c_source_manifest ORDER BY source_role"),
        ("STAGE6C_PRIORITY_REVIEW.csv", "SELECT * FROM stage6c_priority_review ORDER BY settlement_id"),
        ("STAGE6C_REVIEW_SAMPLE.csv", "SELECT * FROM stage6c_review_sample ORDER BY sample_order"),
        ("STAGE6C_EXCEPTION_QUEUE.csv", "SELECT * FROM stage6c_exception_queue ORDER BY severity,settlement_id"),
        ("STAGE6C_POPULATION_INPUTS.csv", "SELECT * FROM stage6c_population_inputs ORDER BY settlement_id"),
    ]
    paths: list[Path] = []
    for filename, query in exports:
        cursor = connection.execute(query)
        columns = [item[0] for item in cursor.description]
        rows = [dict(zip(columns, row)) for row in cursor]
        path = EXPORT_DIR / filename
        write_csv(path, rows, columns)
        paths.append(path)
    return paths


def validate_release(database_summary: Mapping[str, Any], geometry_digests: Mapping[str, str]) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def check(name: str, actual: Any, expected: Any) -> None:
        checks.append({"check": name, "status": "PASS" if actual == expected else "FAIL", "actual": actual, "expected": expected})

    with sqlite3.connect(OUT_DB) as connection:
        check("sqlite_quick_check", connection.execute("PRAGMA quick_check").fetchone()[0], "ok")
        check("sqlite_integrity_check", connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        check("registry_count", connection.execute("SELECT COUNT(*) FROM settlement").fetchone()[0], 31_271)
        check("assessment_count", connection.execute("SELECT COUNT(*) FROM stage6c_site_assessment").fetchone()[0], 31_271)
        check("assessment_unique_ids", connection.execute("SELECT COUNT(DISTINCT settlement_id) FROM stage6c_site_assessment").fetchone()[0], 31_271)
        check("active_settlement_count", connection.execute("SELECT COUNT(*) FROM settlement WHERE stage6_active_settlement=1").fetchone()[0], 30_097)
        check("profile_count", connection.execute("SELECT COUNT(*) FROM stage6c_profile_catalog").fetchone()[0], 217)
        check("component_count", connection.execute("SELECT COUNT(*) FROM stage6c_profile_component").fetchone()[0], 1_953)
        check("coordinate_class_count", connection.execute("SELECT COUNT(*) FROM stage6c_coordinate_semantics_catalog").fetchone()[0], 21)
        check("review_sample_count", connection.execute("SELECT COUNT(*) FROM stage6c_review_sample").fetchone()[0], 300)
        check("priority_review_count", connection.execute("SELECT COUNT(*) FROM stage6c_priority_review").fetchone()[0], 273)
        check("coordinate_changes", connection.execute(
            """SELECT COUNT(*) FROM settlement s JOIN stage6c_site_assessment a USING(settlement_id)
               WHERE s.display_x_km<>a.original_display_x_km OR s.display_y_km<>a.original_display_y_km"""
        ).fetchone()[0], 0)
        check("missing_assessments", connection.execute(
            "SELECT COUNT(*) FROM settlement s LEFT JOIN stage6c_site_assessment a USING(settlement_id) WHERE a.settlement_id IS NULL"
        ).fetchone()[0], 0)
        check("active_settlements_without_owner_profile", connection.execute(
            """SELECT COUNT(*) FROM stage6c_site_assessment
               WHERE scope_status IN ('CURRENT_SETTLEMENT','CONDITIONAL_SETTLEMENT')
                 AND (owner_haus_id IS NULL OR profile_id IS NULL)"""
        ).fetchone()[0], 0)
        check("nonsettlement_profiles", connection.execute(
            """SELECT COUNT(*) FROM stage6c_site_assessment
               WHERE scope_status NOT IN ('CURRENT_SETTLEMENT','CONDITIONAL_SETTLEMENT') AND profile_id IS NOT NULL"""
        ).fetchone()[0], 0)
        check("status_counts", dict(connection.execute(
            "SELECT analysis_status,COUNT(*) FROM stage6c_site_assessment GROUP BY analysis_status"
        )), EXPECTED_STATUS_COUNTS)
        check("profile_weight_errors", connection.execute(
            """SELECT COUNT(*) FROM (
                SELECT profile_id,component_group,SUM(weight) total
                FROM stage6c_profile_component GROUP BY profile_id,component_group
                HAVING ABS(total-1.0)>1e-9)"""
        ).fetchone()[0], 0)
        score_columns = [
            "terrain_support_score", "hydrology_support_score", "flood_compatibility_score",
            "core_capacity_score", "expansion_capacity_score", "land_access_score", "water_access_score",
            "seasonal_reliability_score", "domain_fit_score", "capacity_support_score_low",
            "capacity_support_score", "capacity_support_score_high", "access_support_score_low",
            "access_support_score", "access_support_score_high", "evidence_confidence_score",
        ]
        bounds_clause = " OR ".join(f'("{column}" IS NOT NULL AND "{column}" NOT BETWEEN 0 AND 1)' for column in score_columns)
        check("score_bounds", connection.execute(f"SELECT COUNT(*) FROM stage6c_site_assessment WHERE {bounds_clause}").fetchone()[0], 0)
        check("uncertainty_order", connection.execute(
            """SELECT COUNT(*) FROM stage6c_site_assessment
               WHERE capacity_support_score_low>capacity_support_score
                  OR capacity_support_score>capacity_support_score_high
                  OR access_support_score_low>access_support_score
                  OR access_support_score>access_support_score_high"""
        ).fetchone()[0], 0)
        check("hydrology_major_only_rows", connection.execute(
            "SELECT COUNT(*) FROM stage6c_site_assessment WHERE hydrology_basis='MAJOR_ONLY'"
        ).fetchone()[0], 0)
        minor_contacts = connection.execute(
            "SELECT COUNT(*) FROM stage6c_site_assessment WHERE min_minor_distance_km<=0.5"
        ).fetchone()[0]
        checks.append({"check": "minor_network_material_contact", "status": "PASS" if minor_contacts > 0 else "FAIL", "actual": minor_contacts, "expected": ">0"})
        check("quarantined_source_references", connection.execute(
            "SELECT COUNT(*) FROM stage6c_source_manifest WHERE note LIKE '%D3-MIN-013654%'"
        ).fetchone()[0], 0)
        check("seelenwacht_conditional_count", connection.execute(
            "SELECT COUNT(*) FROM settlement WHERE stage6b_functional_tier='FTU_CONDITIONAL_FIELD_SITE'"
        ).fetchone()[0], 150)
        check("seelenwacht_unresolved_count", connection.execute(
            "SELECT COUNT(*) FROM settlement WHERE stage6b_functional_tier='FTU_PERMANENCE_UNRESOLVED'"
        ).fetchone()[0], 26)
        check("seren_lagoon_non_surface", connection.execute(
            """SELECT COUNT(*) FROM stage6c_site_assessment a JOIN settlement s USING(settlement_id)
               WHERE a.owner_haus_id='SERENAKRONE' AND s.stage6b_realised_settlement_form='SURFACE_LAGOON_SETTLEMENT'
                 AND a.effective_vertical_domain<>'SURFACE'"""
        ).fetchone()[0], 0)
        check("glanz_submerged_ordinary_humans", connection.execute(
            """SELECT COUNT(*) FROM stage6c_site_assessment a JOIN settlement s USING(settlement_id)
               WHERE a.owner_haus_id='GLANZGRUND'
                 AND a.effective_vertical_domain='FULLY_SUBMERGED_NATIVE_SPECIALIST_DOMAIN'
                 AND s.stage6_ordinary_permanent_human_settlement=1"""
        ).fetchone()[0], 0)
        check("wgf_unresolved_assignment_count", connection.execute(
            "SELECT COUNT(*) FROM stage6b_unresolved_functional_assignment"
        ).fetchone()[0], 1)
        hard_count = connection.execute("SELECT COUNT(*) FROM stage6c_exception_queue WHERE severity='HARD'").fetchone()[0]
        high_count = connection.execute("SELECT COUNT(*) FROM stage6c_exception_queue WHERE severity='HIGH'").fetchone()[0]
        checks.append({"check": "hard_exception_count", "status": "PASS" if hard_count == 0 else "FAIL", "actual": hard_count, "expected": 0})
        checks.append({"check": "high_exception_count", "status": "PASS" if high_count == 0 else "WARN", "actual": high_count, "expected": 0})
        check("foreign_key_check", len(connection.execute("PRAGMA foreign_key_check").fetchall()), 0)

    with sqlite3.connect(OUT_GPKG) as connection:
        check("gpkg_quick_check", connection.execute("PRAGMA quick_check").fetchone()[0], "ok")
        check("gpkg_assessment_count", connection.execute("SELECT COUNT(*) FROM stage6c_site_assessment").fetchone()[0], 31_271)
        check("gpkg_attribute_registration", connection.execute(
            "SELECT data_type FROM gpkg_contents WHERE table_name='stage6c_site_assessment'"
        ).fetchone()[0], "attributes")
    check("gpkg_geometry_digests_preserved", geometry_digests, gpkg_geometry_digests(BASE_GPKG))

    failures = [item for item in checks if item["status"] == "FAIL"]
    warnings = [item for item in checks if item["status"] == "WARN"]
    return {
        "schema": "diadem-stage6c-validation-1.0",
        "status": "PASS" if not failures else "FAIL",
        "canon_status": CANON_STATUS,
        "method_version": METHOD,
        "checks": checks,
        "failure_count": len(failures),
        "warning_count": len(warnings),
        "database_summary": database_summary,
    }


def write_method_notes() -> Path:
    path = OUT_DIR / "STAGE6C_METHOD_AND_RULES.md"
    text = f"""# Diadem Province Database V4 — Stage 6C 100 m Spatial Context

**Status:** WORKING PROPOSAL — REVIEW ONLY — NOT CANON  
**Method:** `{METHOD}`  
**Grid:** {GRID_NOTE}

## What this stage does

- Preserves all 31,271 inherited identity records and their official coordinates exactly.
- Evaluates each 1 km source anchor as one hundred underlying 100 m cells plus a 2 km context ring.
- Reads elevation only from one locked generation of the editable Zarr terrain authority. Its
  generation-zero D3.1 and Candidate-B Stillklinge TIFF parents remain sealed lineage, while the
  independent Candidate-B Stillklinge flood replacement remains active,
  exact positive-surface fragments and barony membership, the V4.2 major and special hydrology,
  all 16,369 non-Stillklinge D3 feeder geometries, and the corrected 112-feature Stillklinge
  local composition. The 3,177-feature parent-minor package is retained only as lineage evidence;
  it is not rasterised and is not authorised for Stage 6C vector-distance calculations.
  protected Moorwandler and Serenakrone masks, and resolved H2.2 lake/flood evidence.
- Stores raw evidence, nine separate component scores, low/central/high capacity and access support,
  morphology recipes, uncertainty and review flags.
- Does **not** turn point anchors into settlement footprints or change canon.

## Efficiency and accuracy

The calculation is rule-based but every site is evaluated independently. The rules differ by realised
settlement form, physical domain and Haus where canon requires it: 59 base form/domain recipes resolve
to 217 observed profiles. Hard domain gates are applied before scoring, so water, wetland, canopy,
surface and mobile-anchor forms are not treated as one generic settlement type.

Where a retained wetland-form label has no wetland or channel support at its unchanged coordinate,
ordinary-human settlements receive a deliberately low-fit surface fallback rather than being erased.
The inherited form and coordinate remain unchanged and the mismatch stays in the HIGH review queue.
This implements the approved distinction between bonded Moorwandler concentration in stilt villages
and ordinary or unbonded human residence on otherwise supportable inter-river ground.

The Stage 6C internal 100 m analysis cell is recorded only when the best cell is decisively better.
Equivalent cells remain explicitly equivalent; the inherited official coordinate is never moved.

## Deliberate deferrals

- 113 specialist 3D sites retain surface context but no false final 3D capacity.
- Stage 6C.5 will perform bounded high-resolution refinement for FT0/FT1 and selected unusual sites.
- Stage 6D will estimate population only after that refinement. It can use parallel ledgers for ordinary
  humans, bonded/resident species and wider wild/range species; those populations must use different
  carrying-capacity rules rather than one shared head-count model.
- Comprehensive military placement remains deferred until the Bannerhausen pass.
"""
    path.write_text(text, encoding="utf-8")
    return path


def write_readme(validation: Mapping[str, Any]) -> Path:
    path = OUT_DIR / "README_FIRST.md"
    path.write_text(
        f"""# START HERE — Diadem Province Database V4 Stage 6C

**Status:** WORKING PROPOSAL — REVIEW ONLY — NOT CANON

This release adds the full-frame 100 m settlement spatial-context pass to the verified V3 Stage 6B
database. It preserves all inherited IDs, points and province geometries. The main SQLite database is
the source of truth; the GeoPackage contains the same assessment as a joinable attribute table.

## Main files

- `{OUT_DB.name}` — cumulative database.
- `{OUT_GPKG.name}` — inherited map layers plus `stage6c_site_assessment` attributes.
- `Diadem_Province_Database_V4_STAGE6C_100M_SPATIAL_CONTEXT_WORKING_2026-08-30.xlsx` — readable workbook (built after database QA).
- `review_exports/` — CSV views for site assessment, profiles, population inputs and review queues.
- `STAGE6C_METHOD_AND_RULES.md` — method, authority and deferral boundaries.
- `VALIDATION.json` — automated integrity and canon-guard checks.

Validation status at database build: **{validation['status']}**.
""",
        encoding="utf-8",
    )
    return path


def canonical_table_hash_from_rows(rows: Sequence[Mapping[str, Any]], key: str) -> str:
    digest = hashlib.sha256()
    for row in sorted(rows, key=lambda item: str(item[key])):
        digest.update(canonical_json(row).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def select_smoke_sites(sites: Sequence[Site], limit: int) -> list[Site]:
    if limit >= len(sites):
        return list(sites)
    buckets: dict[tuple[Any, ...], list[Site]] = defaultdict(list)
    for site in sites:
        status = rules.analysis_status_for(
            stage6_active_location=site.active_location,
            stage6_active_settlement=site.active_settlement,
            conditionality_status=site.conditionality,
            effective_vertical_domain=site.vertical_domain,
        )
        buckets[(status, site.realised_form, site.vertical_domain)].append(site)
    selected: list[Site] = []
    selected_ids: set[str] = set()
    for key in sorted(buckets, key=lambda item: tuple(str(value) for value in item)):
        site = sorted(buckets[key], key=lambda item: stable_hash("SMOKE|" + item.settlement_id))[0]
        selected.append(site)
        selected_ids.add(site.settlement_id)
        if len(selected) >= limit:
            return selected
    remaining = sorted(
        (site for site in sites if site.settlement_id not in selected_ids),
        key=lambda item: stable_hash("SMOKE_FILL|" + item.settlement_id),
    )
    selected.extend(remaining[: limit - len(selected)])
    return selected


def generation_identity(
    source_manifest: Sequence[Mapping[str, Any]],
    authority_descriptor: Mapping[str, Any],
    *,
    smoke_limit: int | None,
    water_query_mode: str,
) -> str:
    """Conservative executable/schema closure; no source bytes are rehashed here."""
    engine = Path(__file__).resolve().parent
    code = sorted(engine.glob("*.py")) + sorted((engine / "ten_m_tile_engine").glob("*.py"))
    for name in ("ZARR_RUNTIME_DEPS_MANIFEST.json", "table-requirements-lock.txt"):
        if (engine / name).is_file():
            code.append(engine / name)
    return runtime.semantic_identity(
        "stage6c-assessment-and-release.v1",
        {"verified_sources": source_manifest, "terrain_authority": terrain_authority_identity(authority_descriptor),
         "catalogue": runtime.file_identity(catalogue_path())},
        {"method": METHOD, "canon_status": CANON_STATUS, "smoke_limit": smoke_limit,
         "water_query_mode": water_query_mode, "block_size": ANALYSIS_BLOCK_SIZE},
        runtime.implementation_identity(code),
    )


def main(argv: Sequence[str] | None = None) -> int:
    global OUT_DIR, OUT_DB, OUT_GPKG, EXPORT_DIR, WORK_DIR
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke-limit", type=int, default=None, help="Analyse the first N identities without writing outputs")
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--work-dir", type=Path, default=None, help="Runtime checkpoints; explicitly required to persist smoke work")
    parser.add_argument("--no-reuse", action="store_true", help="Run the original numerical path without reading or writing reuse records")
    parser.add_argument("--algorithm-mode", choices=("auto", "reference"), default="auto",
                        help="Use accepted exact-output algorithms or the preserved reference recipes")
    parser.add_argument("--workers", type=int, default=1,
                        help="Parallel assessment groups; 1 keeps the serial scoring reference")
    parser.add_argument("--memory-budget-mb", type=int, default=1024,
                        help="Estimated in-flight assessment budget, not total RAM; minimum 256 MiB")
    parser.add_argument("--prefetch-workers", type=int, default=RASTER_PREFETCH_WORKERS)
    parser.add_argument("--prefetch-depth", type=int, default=RASTER_PREFETCH_DEPTH)
    parser.add_argument("--prefetch-memory-mib", type=int, default=RASTER_PREFETCH_MEMORY_MIB,
                        help="Conservative prefetch-buffer budget, not total process RAM; minimum 256 MiB")
    parser.add_argument(
        "--deep-sealed-lineage-audit",
        action="store_true",
        help=(
            "Re-read/hash the two generation-zero terrain TIFFs. Normal runs "
            "bind their exact identity from the verified Zarr authority; the "
            "Validate task already byte-audits all 32 sealed sources."
        ),
    )
    parser.add_argument(
        "--no-source-hash-cache",
        action="store_true",
        help="Use the original uncached byte-hash path for every ordinary builder source.",
    )
    parser.add_argument(
        "--rehash-source-files",
        action="store_true",
        help="Force byte hashing of ordinary builder sources and refresh reusable receipts.",
    )
    parser.add_argument(
        "--water-query-mode",
        choices=WATER_QUERY_MODES,
        default=WATER_QUERY_DEFAULT,
        help=(
            "Select reduced production queries, chunked full arrays, or the "
            "original exact reference fallback."
        ),
    )
    args = parser.parse_args(argv)
    algorithm_policy.configure(args.algorithm_mode)
    stats = runtime.RuntimeStats()
    if args.workers < 1 or args.memory_budget_mb < 256:
        parser.error("Assessment workers must be positive and memory at least 256 MiB")
    if args.prefetch_workers < 1 or args.prefetch_depth < 1 or args.prefetch_memory_mib < 256:
        parser.error("Prefetch workers/depth must be positive and memory must be at least 256 MiB")
    if args.output_dir is not None:
        OUT_DIR = args.output_dir.resolve()
        OUT_DB = OUT_DIR / OUT_DB.name
        OUT_GPKG = OUT_DIR / OUT_GPKG.name
        EXPORT_DIR = OUT_DIR / "review_exports"
    if args.work_dir is not None:
        WORK_DIR = args.work_dir.resolve()
    elif args.smoke_limit is None:
        WORK_DIR = OUT_DIR / ".generation_runtime"
    if args.no_source_hash_cache and args.rehash_source_files:
        parser.error("--no-source-hash-cache and --rehash-source-files are mutually exclusive")

    print("CHECKPOINT_SOURCE_LOCK_START", flush=True)
    with stats.measure("source_verification"):
        source_manifest, authority_descriptor, source_hash_cache_report = verify_sources(
            deep_lineage_audit=args.deep_sealed_lineage_audit,
            use_hash_cache=not args.no_source_hash_cache,
            force_source_rehash=args.rehash_source_files,
        )
    print("CHECKPOINT_SOURCE_HASH_CACHE " + canonical_json(source_hash_cache_report), flush=True)
    reuse_enabled = not args.no_reuse and (args.smoke_limit is None or args.work_dir is not None)
    identity = generation_identity(
        source_manifest, authority_descriptor,
        smoke_limit=args.smoke_limit, water_query_mode=args.water_query_mode,
    ) if reuse_enabled else None
    receipt_path = WORK_DIR / "stage6c-release.receipt.json"
    if identity is not None and args.smoke_limit is None:
        receipt = runtime.load_receipt(receipt_path, identity, OUT_DIR)
        if receipt is not None:
            stats.increment("releases_reused")
            print("CHECKPOINT_STAGE6C_UNCHANGED " + canonical_json(receipt), flush=True)
            print("CHECKPOINT_STAGE6C_RUNTIME " + canonical_json(stats.snapshot()), flush=True)
            return int(receipt["return_code"])
    checkpoint_store = runtime.CheckpointStore(WORK_DIR / "assessment_groups", identity) if identity is not None else None
    transform_report = transform_score_self_check()
    rules_report = rules.self_check(BASE_DB)
    print(canonical_json({
        "source_count": len(source_manifest),
        "transform_self_check": transform_report,
        "rules": rules_report,
    }), flush=True)

    with sqlite3.connect(BASE_DB) as source_connection:
        source_connection.row_factory = sqlite3.Row
        profiles, components, site_profile_map = rules.build_profile_rows(source_connection)
        coordinate_catalog = rules.coordinate_catalog_rows(source_connection)
        coordinate_rows = rules.coordinate_semantics_assignment_rows(source_connection)
        sites = load_sites(source_connection)

    print("CHECKPOINT_RULE_CATALOG_COMPLETE profiles=217 components=1953 coordinate_classes=21", flush=True)
    analysis_sites = select_smoke_sites(sites, args.smoke_limit) if args.smoke_limit is not None else sites
    hydrology_composition: dict[str, int] = {}
    assessments, exceptions = assess_all_sites(
        analysis_sites,
        profiles,
        site_profile_map,
        coordinate_rows,
        authority_descriptor,
        sample_limit=None,
        water_query_mode=args.water_query_mode,
        hydrology_composition_out=hydrology_composition,
        checkpoint_store=checkpoint_store,
        workers=args.workers,
        memory_budget_mb=args.memory_budget_mb,
        prefetch_workers=args.prefetch_workers,
        prefetch_depth=args.prefetch_depth,
        prefetch_memory_mib=args.prefetch_memory_mib,
        runtime_stats=stats,
    )
    if args.smoke_limit is not None:
        print("CHECKPOINT_STAGE6C_RUNTIME " + canonical_json(stats.snapshot()), flush=True)
        print(canonical_json({
            "status": "SMOKE_PASS", "rows": len(assessments), "exceptions": len(exceptions),
            "analysis_status_counts": Counter(row["analysis_status"] for row in assessments),
            "assessment_hash": canonical_table_hash_from_rows(assessments, "settlement_id"),
            "exception_details": exceptions[:20],
        }))
        return 0

    if len(assessments) != 31_271:
        raise AssertionError(f"Expected 31,271 assessments, got {len(assessments)}")
    print("CHECKPOINT_FULL_ANALYSIS_COMPLETE rows=31271", flush=True)

    prepare_output()
    database_summary = build_database(
        source_manifest, profiles, components, coordinate_catalog, assessments, exceptions
    )
    geometry_digests = register_gpkg_attributes()
    with sqlite3.connect(OUT_DB) as connection:
        export_paths = export_review_tables(connection)
    validation = validate_release(database_summary, geometry_digests)
    (OUT_DIR / "VALIDATION.json").write_text(json.dumps(validation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT_DIR / "STAGE6C_SOURCE_MANIFEST.json").write_text(json.dumps({
        "schema": "diadem-stage6c-source-manifest-1.0",
        "canon_status": CANON_STATUS,
        "hydrology_composition": hydrology_composition,
        "sources": source_manifest,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    method_path = write_method_notes()
    readme_path = write_readme(validation)
    print(canonical_json({
        "status": validation["status"],
        "database": str(OUT_DB), "gpkg": str(OUT_GPKG),
        "assessment_rows": len(assessments), "exception_rows": len(exceptions),
        "exports": [str(path) for path in export_paths],
    }), flush=True)
    return_code = 0 if validation["status"] == "PASS" else 2
    if identity is not None and return_code == 0:
        runtime.save_receipt(receipt_path, identity, OUT_DIR, [
            OUT_DB, OUT_GPKG, OUT_DIR / "VALIDATION.json", OUT_DIR / "STAGE6C_SOURCE_MANIFEST.json",
            method_path, readme_path, *export_paths,
        ], {"return_code": return_code, "status": validation["status"],
            "assessment_rows": len(assessments), "exception_rows": len(exceptions)})
    print("CHECKPOINT_STAGE6C_RUNTIME " + canonical_json(stats.snapshot()), flush=True)
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
