#!/usr/bin/env python3
"""Independent, read-only validator for the Diadem Stage 6C release.

The validator never writes to either SQLite input.  It emits compact JSON and
plain-text reports next to the Stage 6C database unless explicit report paths
are supplied.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sqlite3
import struct
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from source_catalogue import source_path

EXPECTED_REGISTRY_COUNT = 31_271
EXPECTED_ACTIVE_LOCATION_COUNT = 31_269
EXPECTED_ACTIVE_SETTLEMENT_COUNT = 30_097
EXPECTED_PROFILE_COUNT = 217
EXPECTED_COMPONENT_COUNT = 1_953
EXPECTED_PRIORITY_REVIEW_COUNT = 273
EXPECTED_COORDINATE_SEMANTICS_COUNT = 21

EXPECTED_COMPONENT_CODES = {
    "TERRAIN_SUPPORT",
    "HYDROLOGY_SUPPORT",
    "FLOOD_COMPATIBILITY",
    "CORE_CAPACITY",
    "EXPANSION_CAPACITY",
    "LAND_ACCESS",
    "WATER_ACCESS",
    "SEASONAL_RELIABILITY",
    "DOMAIN_FIT",
}

EXPECTED_COMPONENT_GROUPS = {
    "TERRAIN_SUPPORT": "CAPACITY",
    "HYDROLOGY_SUPPORT": "CAPACITY",
    "FLOOD_COMPATIBILITY": "CAPACITY",
    "CORE_CAPACITY": "CAPACITY",
    "EXPANSION_CAPACITY": "CAPACITY",
    "DOMAIN_FIT": "CAPACITY",
    "LAND_ACCESS": "ACCESS",
    "WATER_ACCESS": "ACCESS",
    "SEASONAL_RELIABILITY": "ACCESS",
}

SPECIALIST_3D_DOMAINS = {
    "SUBSURFACE",
    "AERIAL_VERTICAL",
    "SURFACE_FACING_DRY_OR_AIR_CAVERN_DISTRICTS",
    "SURFACE_CLIFF_TERRACE_VERTICAL",
    "FULLY_SUBMERGED_NATIVE_SPECIALIST_DOMAIN",
    "SUBMERGED_OR_FLOODED_CAVERN",
}

EXPECTED_STATUS_COUNTS = {
    "READY_2D_CURRENT": 29_808,
    "READY_2D_CONDITIONAL": 176,
    "DEFERRED_SPECIALIST_3D": 113,
    "NOT_APPLICABLE_NONSETTLEMENT": 1_172,
    "INACTIVE": 2,
}

EXPECTED_SOURCES = {
    "stage6b_parent_sqlite": {
        "sha256": "2d3b8b97966c033cbf80940f0886998f885fcac14e45137745f683302d7a4aad",
        "count": 31_271,
    },
    "terrain_100m": {
        "sha256": "fbaa09175c039d68993a83dbf2df3cd5835b8128386d7bc981eb13958907f3a7",
        "width": 22_000,
        "height": 18_600,
        "transform": [0.1, 0.0, 0.0, 0.0, 0.1, 0.0],
    },
    "stage6b_parent_gpkg": {
        "sha256": "dd5e29ac5d85c74abb461a6a7249be94bf4da0ecdf2cf80d1af30d7454e9a37e",
    },
    "stillklinge_terrain_override": {
        "sha256": "dc5af05d10e212c26daf15daf8781334bfa80b626b0f1217c84f2bbdaf0b581f",
    },
    "obsidian_sea_mask": {
        "sha256": "83e09b5fe4f3007c1e9600eee4870e4d42242f0bdcf36046411987bfb90ff943",
    },
    "moorwandler_core_wetland": {
        "sha256": "7d53543784a45a893eee7fab5f2b531f8d229fb3d30108524c48fa637e7a3a3f",
    },
    "serenakrone_water_mask": {
        "sha256": "5271ca6aa9582682ccb88c56815371af213dc9180d1941db85a23278c2b0293c",
    },
    "flood_candidates_100m": {
        "sha256": "535a7165ba03ffb66e19c6aa1ad94ac21d10fbb5edc096d1c4649d1ecafc3e8e",
    },
    "stillklinge_flood_override": {
        "sha256": "b2e1b76f5833c1d407e69ef57ab091488d35087358b8e3ace7ab0e145f201bde",
    },
    "active_major": {
        "sha256": "228f42f37599b6b99ce747c160e7a76574a0fe63623e8b791a7ff70c4a65eca3",
        "count": 30,
    },
    "parent_minor_lineage": {
        "sha256": "707740a4a9dd488d954a2e6cbd7848f81b6fc7cbc525f59fc892c7c8986d2429",
        "count": 3_177,
    },
    "d3_feeder_raw": {
        "sha256": "78af082efd432e7e5408d01aec058ed1777743086ba88fd833ae033dab7c4a06",
        "count": 16_468,
    },
    "d3_feeder_enriched": {
        "sha256": "f2c219f1ef738e512a7b49673b4005afe64659103eb4360629dea77cfc506337",
        "count": 16_468,
    },
    "stillklinge_support": {
        "sha256": "24e3509048bd791bdf0e6d10dd5a8df5051f8280d0df581251ba5cc27acd83f9",
        "count": 112,
    },
    "special_controls": {
        "sha256": "97453c76cb55a42dce7329e1c757d3f25c1d3bee29854fda94ee9287ea101b3c",
        "count": 10,
    },
    "coastline": {
        "sha256": "971ad37396b18c11b5287c854f3546c168e9bd09226b23948ee23cdf0479569e",
        "count": 1,
    },
    "lake_permanent_l1": {
        "sha256": "084cb35aa4c35989c9b0428344ea8bdccc7544c3afb87b0cc4a6b4798e0b27d5",
        "count": 486,
    },
    "lake_permanent_legacy": {
        "sha256": "0f9e7559df83dd27684a186a5303d849a87326f4de572dbf5e951d7119f89c8f",
        "count": 11,
    },
    "lake_seasonal": {
        "sha256": "8b335adb410f356a7c3ab07dbdfb2e3835f5df8571b5566795fea44c9ca657a4",
        "count": 1_170,
    },
    "moorwandler_transition": {
        "sha256": "bf60990287737240db0ecdf2fd0dab488bf36ca802c2f0d2a2c3661970c70b7c",
        "count": 158,
    },
    "exact_surface_registry": {
        "sha256": "1986ff3bba8d87ab1c89eb1491fca7b941c8ef4eae8a6e2e1d07d4647c34d808",
        "count": 2_494_913,
    },
    "fragment_barony_assignment": {
        "sha256": "6a993b8d6670c1ab044854f94dbaa169daefbb7b6870b63655dd75c264637731",
        "count": 2_494_913,
    },
}

EXPECTED_HYDROLOGY_COMPOSITION = {
    "parent_minor_lineage_count": 3_177,
    "d3_total_count": 16_468,
    "d3_non_stillklinge_count": 16_369,
    "d3_stillklinge_excluded_count": 99,
    "corrected_stillklinge_local_count": 112,
    "combined_minor_count": 16_481,
    "strict_surface_special_count": 2,
    "managed_surface_overlay_count": 4,
    "non_surface_special_overlay_count": 4,
    "d3_perennial_count": 15_193,
    "combined_perennial_minor_count": 15_193,
}

REQUIRED_OBJECTS = {
    "stage6c_source_manifest": "table",
    "stage6c_coordinate_semantics_catalog": "table",
    "stage6c_profile_catalog": "table",
    "stage6c_profile_component": "table",
    "stage6c_site_assessment": "table",
    "stage6c_exception_queue": "table",
    "stage6c_review_sample": "table",
    "stage6c_population_inputs": "view",
    "stage6c_review_exceptions": "view",
    "stage6c_priority_review": "view",
}

ASSESSMENT_REQUIRED_COLUMNS = {
    "settlement_id",
    "scope_status",
    "analysis_status",
    "owner_haus_id",
    "owner_assignment_basis",
    "profile_id",
    "effective_vertical_domain",
    "original_display_x_km",
    "original_display_y_km",
    "coordinate_semantics_code",
    "coordinate_value_resolution_km",
    "coordinate_precision_basis",
    "anchor_status",
    "provisional_anchor",
    "horizontal_uncertainty_shape",
    "horizontal_uncertainty_radius_km",
    "vertical_uncertainty_status",
    "footprint_status",
    "score_uncertainty_status",
    "terrain_elevation_m",
    "terrain_slope_deg",
    "local_relief_m",
    "corrected_surface_water_distance_km",
    "corrected_perennial_channel_distance_km",
    "flood_exposure_index",
    "developable_area_r1_km2",
    "developable_area_r5_km2",
    "land_access_cost_index",
    "water_access_index",
    "seasonal_reliability_index",
    "domain_fit_index",
    "morphology_class",
    "capacity_metric_kind",
    "access_modes_json",
    "expansion_direction_8way",
    "expansion_sector_weights_json",
    "terrain_support_score",
    "hydrology_support_score",
    "flood_compatibility_score",
    "core_capacity_score",
    "expansion_capacity_score",
    "land_access_score",
    "water_access_score",
    "seasonal_reliability_score",
    "domain_fit_score",
    "capacity_support_score_low",
    "capacity_support_score",
    "capacity_support_score_high",
    "access_support_score_low",
    "access_support_score",
    "access_support_score_high",
    "evidence_confidence_score",
    "capacity_band",
    "limiting_factors_json",
    "data_basis_code",
    "priority_review",
    "review_status",
    "input_fingerprint",
    "method_version",
    "canon_status",
}

SCORE_COLUMNS = (
    "terrain_support_score",
    "hydrology_support_score",
    "flood_compatibility_score",
    "core_capacity_score",
    "expansion_capacity_score",
    "land_access_score",
    "water_access_score",
    "seasonal_reliability_score",
    "domain_fit_score",
    "capacity_support_score_low",
    "capacity_support_score",
    "capacity_support_score_high",
    "access_support_score_low",
    "access_support_score",
    "access_support_score_high",
    "evidence_confidence_score",
)

FORBIDDEN_SOURCE_MARKERS = (
    "FAILED_INCOMPLETE_DO_NOT_USE",
    "OPTIONAL_PENDING_EVIDENCE",
)

HEX64_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def sha256_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def connect_readonly(path: Path) -> sqlite3.Connection:
    uri = "file:" + path.resolve().as_posix() + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def table_columns(connection: sqlite3.Connection, table: str) -> list[str]:
    return [row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')]


def object_inventory(connection: sqlite3.Connection) -> dict[str, str]:
    return {
        row[0]: row[1]
        for row in connection.execute(
            "SELECT name, type FROM sqlite_master WHERE type IN ('table','view')"
        )
    }


def scalar(connection: sqlite3.Connection, sql: str, params: Sequence[Any] = ()) -> Any:
    row = connection.execute(sql, params).fetchone()
    return None if row is None else row[0]


def rows_as_dicts(connection: sqlite3.Connection, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
    return [dict(row) for row in connection.execute(sql, params)]


def canonical_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            return {"__nonfinite_float__": repr(value)}
        return {"__float__": format(value, ".17g")}
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"__blob__": bytes(value).hex()}
    if isinstance(value, str):
        stripped = value.strip()
        if stripped[:1] in ("{", "["):
            try:
                return canonical_value(json.loads(stripped))
            except json.JSONDecodeError:
                pass
        return value
    if isinstance(value, Mapping):
        return {str(key): canonical_value(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [canonical_value(item) for item in value]
    return str(value)


def canonical_table_digest(
    connection: sqlite3.Connection,
    table: str,
    columns: Sequence[str] | None = None,
) -> dict[str, Any]:
    info = list(connection.execute(f'PRAGMA table_info("{table}")'))
    available = [row[1] for row in info]
    selected = list(columns) if columns is not None else available
    missing = sorted(set(selected) - set(available))
    if missing:
        raise ValueError(f"{table} lacks columns required for digest: {missing}")
    query = "SELECT " + ",".join(f'"{column}"' for column in selected) + f' FROM "{table}"'
    encoded_rows: list[str] = []
    for row in connection.execute(query):
        payload = {selected[index]: canonical_value(row[index]) for index in range(len(selected))}
        encoded_rows.append(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    # Sorting the full canonical row avoids depending on insertion order or collation.
    encoded_rows.sort()
    digest = hashlib.sha256()
    digest.update(json.dumps(selected, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    digest.update(b"\n")
    for encoded in encoded_rows:
        digest.update(encoded.encode("utf-8"))
        digest.update(b"\n")
    return {
        "table": table,
        "row_count": len(encoded_rows),
        "columns": selected,
        "sha256": digest.hexdigest(),
    }

def recursive_hashes(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, Mapping):
        for key, child in value.items():
            if str(key).lower() in ("sha256", "hash", "checksum") and isinstance(child, str) and HEX64_RE.fullmatch(child):
                found.add(child.lower())
            found.update(recursive_hashes(child))
    elif isinstance(value, list):
        for child in value:
            found.update(recursive_hashes(child))
    elif isinstance(value, str) and HEX64_RE.fullmatch(value):
        found.add(value.lower())
    return found


def discover_manifest(db_path: Path) -> Path | None:
    preferred = (
        "STAGE6C_SOURCE_MANIFEST.json",
        "stage6c_source_manifest.json",
        "SOURCE_MANIFEST.json",
        "RELEASE_MANIFEST.json",
    )
    for name in preferred:
        candidate = db_path.parent / name
        if candidate.exists():
            return candidate
    candidates = sorted(db_path.parent.glob("*manifest*.json"), key=lambda item: item.name.lower())
    return candidates[0] if candidates else None


def resolve_source_file(row: Mapping[str, Any], source_root: Path | None) -> Path | None:
    path_keys = (
        "resolved_path",
        "absolute_path",
        "source_path",
        "file_path",
        "relative_path",
        "path",
    )
    for key in path_keys:
        value = row.get(key)
        if not isinstance(value, str) or not value.strip():
            continue
        candidate = Path(value)
        possibilities = [candidate]
        if source_root is not None and not candidate.is_absolute():
            possibilities.insert(0, source_root / candidate)
        for possibility in possibilities:
            if possibility.exists() and possibility.is_file():
                return possibility.resolve()
    return None


def geojson_feature_count(path: Path) -> int | None:
    if path.suffix.lower() not in (".json", ".geojson"):
        return None
    try:
        with path.open("r", encoding="utf-8") as stream:
            payload = json.load(stream)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    features = payload.get("features") if isinstance(payload, dict) else None
    return len(features) if isinstance(features, list) else None


def geojson_shapes(path: Path, shape_function: Any) -> list[Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    features = payload.get("features", []) if isinstance(payload, dict) else []
    return [shape_function(feature["geometry"]) for feature in features if feature.get("geometry")]


def candidate_grid_centres(source_x: float, source_y: float) -> tuple[list[float], list[float]]:
    col0 = min(max(math.floor((source_x - 0.5) / 0.1 + 1e-8), 0), 21_990)
    row0 = min(max(math.floor((source_y - 0.5) / 0.1 + 1e-8), 0), 18_590)
    xs: list[float] = []
    ys: list[float] = []
    for row in range(row0, row0 + 10):
        for column in range(col0, col0 + 10):
            xs.append(column * 0.1 + 0.05)
            ys.append(row * 0.1 + 0.05)
    return xs, ys


def decode_gpkg_point(blob: Any) -> tuple[float, float] | None:
    if blob is None:
        return None
    raw = bytes(blob)
    if len(raw) < 29 or raw[:2] != b"GP":
        return None
    flags = raw[3]
    envelope_code = (flags >> 1) & 0b111
    envelope_bytes = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}.get(envelope_code)
    if envelope_bytes is None:
        return None
    offset = 8 + envelope_bytes
    if len(raw) < offset + 21:
        return None
    wkb_little = raw[offset] == 1
    endian = "<" if wkb_little else ">"
    geom_type = struct.unpack_from(endian + "I", raw, offset + 1)[0]
    base_type = geom_type & 0xFF
    if base_type != 1:
        return None
    x, y = struct.unpack_from(endian + "dd", raw, offset + 5)
    return float(x), float(y)


class Validation:
    def __init__(self) -> None:
        self.checks: list[dict[str, Any]] = []
        self.assumptions: list[str] = []
        self.table_digests: dict[str, dict[str, Any]] = {}
        self.review_selection: dict[str, Any] = {}

    def add(
        self,
        check_id: str,
        passed: bool,
        *,
        expected: Any = None,
        actual: Any = None,
        details: Any = None,
        failure_status: str = "FAIL",
    ) -> None:
        self.checks.append(
            {
                "check_id": check_id,
                "status": "PASS" if passed else failure_status,
                "expected": expected,
                "actual": actual,
                "details": details,
            }
        )

    def warn(self, check_id: str, details: Any) -> None:
        self.add(check_id, False, details=details, failure_status="WARN")

    @property
    def failures(self) -> list[dict[str, Any]]:
        return [check for check in self.checks if check["status"] == "FAIL"]

    @property
    def warnings(self) -> list[dict[str, Any]]:
        return [check for check in self.checks if check["status"] == "WARN"]


def validate_database(
    validation: Validation,
    db_path: Path,
    source_root: Path | None,
    manifest_path: Path | None,
) -> sqlite3.Connection:
    connection = connect_readonly(db_path)
    inventory = object_inventory(connection)

    quick = scalar(connection, "PRAGMA quick_check")
    validation.add("db.quick_check", quick == "ok", expected="ok", actual=quick)
    integrity = scalar(connection, "PRAGMA integrity_check")
    validation.add("db.integrity_check", integrity == "ok", expected="ok", actual=integrity)
    foreign_issues = rows_as_dicts(connection, "PRAGMA foreign_key_check")
    validation.add("db.foreign_key_check", not foreign_issues, expected=0, actual=len(foreign_issues), details=foreign_issues[:20])

    for name, expected_type in REQUIRED_OBJECTS.items():
        validation.add(
            f"schema.object.{name}",
            inventory.get(name) == expected_type,
            expected=expected_type,
            actual=inventory.get(name),
        )

    if "stage6c_site_assessment" not in inventory:
        return connection

    assessment_columns = set(table_columns(connection, "stage6c_site_assessment"))
    missing_assessment = sorted(ASSESSMENT_REQUIRED_COLUMNS - assessment_columns)
    validation.add(
        "schema.assessment_required_columns",
        not missing_assessment,
        expected="all required Stage 6C columns",
        actual={"missing": missing_assessment},
    )

    required_subsets = {
        "stage6c_source_manifest": {"source_role", "sha256"},
        "stage6c_coordinate_semantics_catalog": {"coordinate_semantics_code", "source_semantics_exact"},
        "stage6c_profile_catalog": {
            "profile_id", "haus_id", "realised_settlement_form", "effective_vertical_domain",
            "morphology_class", "capacity_metric_kind", "capacity_operator", "access_operator",
            "band_t1", "band_t2", "band_t3", "band_t4",
        },
        "stage6c_profile_component": {
            "profile_id", "component_code", "component_group", "raw_metric_code",
            "transform_code", "p0", "p1", "p2", "p3", "weight", "required",
            "missing_policy",
        },
        "stage6c_exception_queue": {
            "exception_id", "settlement_id", "severity", "exception_code",
            "details_json", "review_status",
        },
        "stage6c_review_sample": {
            "sample_order", "settlement_id", "owner_haus_id", "selection_reason",
            "stable_selection_hash",
        },
    }
    for table, required in required_subsets.items():
        if table not in inventory:
            continue
        present = set(table_columns(connection, table))
        missing = sorted(required - present)
        validation.add(
            f"schema.required_columns.{table}",
            not missing,
            expected=sorted(required),
            actual={"missing": missing},
        )

    expected_counts = {
        "settlement": EXPECTED_REGISTRY_COUNT,
        "stage6c_site_assessment": EXPECTED_REGISTRY_COUNT,
        "stage6c_coordinate_semantics_catalog": EXPECTED_COORDINATE_SEMANTICS_COUNT,
        "stage6c_profile_catalog": EXPECTED_PROFILE_COUNT,
        "stage6c_profile_component": EXPECTED_COMPONENT_COUNT,
        "stage6c_population_inputs": EXPECTED_ACTIVE_SETTLEMENT_COUNT,
        "stage6c_priority_review": EXPECTED_PRIORITY_REVIEW_COUNT,
        "stage6c_review_sample": 300,
    }
    for table, expected in expected_counts.items():
        if table not in inventory:
            continue
        actual = scalar(connection, f'SELECT COUNT(*) FROM "{table}"')
        validation.add(f"count.{table}", actual == expected, expected=expected, actual=actual)

    registry_unique = scalar(connection, "SELECT COUNT(DISTINCT settlement_id) FROM settlement")
    assessment_unique = scalar(connection, "SELECT COUNT(DISTINCT settlement_id) FROM stage6c_site_assessment")
    validation.add("coverage.registry_unique", registry_unique == EXPECTED_REGISTRY_COUNT, expected=EXPECTED_REGISTRY_COUNT, actual=registry_unique)
    validation.add("coverage.assessment_unique", assessment_unique == EXPECTED_REGISTRY_COUNT, expected=EXPECTED_REGISTRY_COUNT, actual=assessment_unique)
    missing_context = scalar(
        connection,
        "SELECT COUNT(*) FROM settlement s LEFT JOIN stage6c_site_assessment c USING(settlement_id) WHERE c.settlement_id IS NULL",
    )
    extra_context = scalar(
        connection,
        "SELECT COUNT(*) FROM stage6c_site_assessment c LEFT JOIN settlement s USING(settlement_id) WHERE s.settlement_id IS NULL",
    )
    validation.add("coverage.missing_assessments", missing_context == 0, expected=0, actual=missing_context)
    validation.add("coverage.extra_assessments", extra_context == 0, expected=0, actual=extra_context)

    active_locations = scalar(connection, "SELECT COUNT(*) FROM settlement WHERE stage6_active_location=1")
    active_settlements = scalar(connection, "SELECT COUNT(*) FROM settlement WHERE stage6_active_settlement=1")
    validation.add("count.active_locations", active_locations == EXPECTED_ACTIVE_LOCATION_COUNT, expected=EXPECTED_ACTIVE_LOCATION_COUNT, actual=active_locations)
    validation.add("count.active_settlements", active_settlements == EXPECTED_ACTIVE_SETTLEMENT_COUNT, expected=EXPECTED_ACTIVE_SETTLEMENT_COUNT, actual=active_settlements)

    if {"original_display_x_km", "original_display_y_km"}.issubset(assessment_columns):
        coordinate_changes = scalar(
            connection,
            """
            SELECT COUNT(*)
            FROM settlement s JOIN stage6c_site_assessment c USING(settlement_id)
            WHERE ABS(s.display_x_km-c.original_display_x_km)>1e-9
               OR ABS(s.display_y_km-c.original_display_y_km)>1e-9
            """,
        )
        validation.add("coordinates.original_immutable", coordinate_changes == 0, expected=0, actual=coordinate_changes)

    if {"analysis_anchor_x_km", "analysis_anchor_y_km"}.issubset(assessment_columns):
        invalid_analysis_anchors: list[dict[str, Any]] = []
        for row in connection.execute(
            """
            SELECT settlement_id, original_display_x_km, original_display_y_km,
                   analysis_anchor_x_km, analysis_anchor_y_km
            FROM stage6c_site_assessment
            WHERE analysis_anchor_x_km IS NOT NULL OR analysis_anchor_y_km IS NOT NULL
            """
        ):
            site_id, source_x, source_y, anchor_x, anchor_y = row
            valid = anchor_x is not None and anchor_y is not None
            if valid:
                col0 = min(max(math.floor((float(source_x) - 0.5) / 0.1 + 1e-8), 0), 21_990)
                row0 = min(max(math.floor((float(source_y) - 0.5) / 0.1 + 1e-8), 0), 18_590)
                col = round((float(anchor_x) - 0.05) / 0.1)
                grid_row = round((float(anchor_y) - 0.05) / 0.1)
                valid = (
                    abs(float(anchor_x) - (col * 0.1 + 0.05)) <= 1e-8
                    and abs(float(anchor_y) - (grid_row * 0.1 + 0.05)) <= 1e-8
                    and col0 <= col < col0 + 10
                    and row0 <= grid_row < row0 + 10
                )
            if not valid and len(invalid_analysis_anchors) < 21:
                invalid_analysis_anchors.append(
                    {"settlement_id": site_id, "source": [source_x, source_y], "analysis_anchor": [anchor_x, anchor_y]}
                )
        validation.add(
            "coordinates.analysis_anchor_inside_source_window",
            not invalid_analysis_anchors,
            expected="paired 100 m cell centre inside immutable 1 km source window",
            actual=len(invalid_analysis_anchors),
            details=invalid_analysis_anchors[:20],
        )

    if "coordinate_value_resolution_km" in assessment_columns:
        invalid_resolution = scalar(
            connection,
            "SELECT COUNT(*) FROM stage6c_site_assessment WHERE coordinate_value_resolution_km IS NOT NULL AND coordinate_value_resolution_km<=0",
        )
        validation.add("coordinates.resolution_positive", invalid_resolution == 0, expected=0, actual=invalid_resolution)
    if "provisional_anchor" in assessment_columns:
        invalid_provisional = scalar(
            connection,
            "SELECT COUNT(*) FROM stage6c_site_assessment WHERE provisional_anchor NOT IN (0,1) OR provisional_anchor IS NULL",
        )
        provisional_count = scalar(
            connection,
            "SELECT COUNT(*) FROM stage6c_site_assessment WHERE provisional_anchor=1",
        )
        validation.add("coordinates.provisional_boolean", invalid_provisional == 0, expected=0, actual=invalid_provisional)
        validation.add("coordinates.provisional_exact_count", provisional_count == 1_714, expected=1_714, actual=provisional_count)
    if "horizontal_uncertainty_radius_km" in assessment_columns:
        invalid_uncertainty = scalar(
            connection,
            "SELECT COUNT(*) FROM stage6c_site_assessment WHERE horizontal_uncertainty_radius_km IS NOT NULL AND horizontal_uncertainty_radius_km<0",
        )
        validation.add("coordinates.uncertainty_nonnegative", invalid_uncertainty == 0, expected=0, actual=invalid_uncertainty)

    optional_cell_checks = {
        "source_window_cell_count": ("=", 100),
        "context_window_cell_count": ("=", 400),
        "context_ring_cell_count": ("=", 300),
    }
    for column, (_, expected) in optional_cell_checks.items():
        if column not in assessment_columns:
            continue
        invalid = scalar(
            connection,
            f'SELECT COUNT(*) FROM stage6c_site_assessment WHERE "{column}" IS NULL OR "{column}"<>?',
            (expected,),
        )
        validation.add(f"coordinates.one_km_window.{column}", invalid == 0, expected=0, actual=invalid)

    if "candidate_valid_cell_count" in assessment_columns:
        invalid_candidates = scalar(
            connection,
            """
            SELECT COUNT(*) FROM stage6c_site_assessment
            WHERE analysis_status IN ('READY_2D_CURRENT','READY_2D_CONDITIONAL')
              AND candidate_valid_cell_count<=0
            """,
        )
        validation.add("candidate.ready_has_valid_cell", invalid_candidates == 0, expected=0, actual=invalid_candidates)
        if "source_window_cell_count" in assessment_columns:
            invalid_candidate_counts = scalar(
                connection,
                """
                SELECT COUNT(*) FROM stage6c_site_assessment
                WHERE candidate_valid_cell_count IS NOT NULL
                  AND (candidate_valid_cell_count<0
                    OR source_window_cell_count IS NULL
                    OR candidate_valid_cell_count>source_window_cell_count)
                """,
            )
            validation.add("candidate.valid_cells_within_source_window", invalid_candidate_counts == 0, expected=0, actual=invalid_candidate_counts)
    if "candidate_support_fraction" in assessment_columns:
        invalid_fraction = scalar(
            connection,
            "SELECT COUNT(*) FROM stage6c_site_assessment WHERE candidate_support_fraction IS NOT NULL AND (candidate_support_fraction<0 OR candidate_support_fraction>1)",
        )
        validation.add("candidate.support_fraction_bounds", invalid_fraction == 0, expected=0, actual=invalid_fraction)
        if {"candidate_valid_cell_count", "source_window_cell_count"}.issubset(assessment_columns):
            inconsistent_fraction = scalar(
                connection,
                """
                SELECT COUNT(*) FROM stage6c_site_assessment
                WHERE candidate_support_fraction IS NOT NULL
                  AND source_window_cell_count>0
                  AND ABS(candidate_support_fraction-
                      (1.0*candidate_valid_cell_count/source_window_cell_count))>1e-9
                """,
            )
            validation.add("candidate.support_fraction_reconciles", inconsistent_fraction == 0, expected=0, actual=inconsistent_fraction)
    selection_column = next((name for name in ("analysis_anchor_selection_status", "selection_status") if name in assessment_columns), None)
    gap_column = next((name for name in ("best_second_score_gap", "best_second_gap") if name in assessment_columns), None)
    if selection_column and gap_column:
        premature_selection = scalar(
            connection,
            f"""
            SELECT COUNT(*) FROM stage6c_site_assessment
            WHERE "{gap_column}"<0.05
              AND UPPER("{selection_column}") IN (
                'SELECTED','UNIQUE_SELECTED','UNIQUE_DOMINANT',
                'PROVISIONAL_INTERNAL_100M_CELL_DECISIVE'
              )
            """,
        )
        validation.add("candidate.no_selection_below_margin", premature_selection == 0, expected=0, actual=premature_selection)
        inconsistent_selection = scalar(
            connection,
            f"""
            SELECT COUNT(*) FROM stage6c_site_assessment
            WHERE ("{selection_column}"='PROVISIONAL_INTERNAL_100M_CELL_DECISIVE'
                   AND ("{gap_column}"<0.05 OR analysis_anchor_x_km IS NULL OR analysis_anchor_y_km IS NULL))
               OR ("{selection_column}"='MULTIPLE_EQUIVALENT_100M_CELLS_NO_RELOCATION'
                   AND ("{gap_column}">=0.05 OR analysis_anchor_x_km IS NOT NULL OR analysis_anchor_y_km IS NOT NULL))
            """,
        )
        validation.add("candidate.selection_margin_and_anchor_reconcile", inconsistent_selection == 0, expected=0, actual=inconsistent_selection)

    if "analysis_status" in assessment_columns:
        actual_statuses = {
            row[0]: row[1]
            for row in connection.execute(
                "SELECT analysis_status, COUNT(*) FROM stage6c_site_assessment GROUP BY analysis_status"
            )
        }
        validation.add(
            "status.analysis_exact_counts",
            actual_statuses == EXPECTED_STATUS_COUNTS,
            expected=EXPECTED_STATUS_COUNTS,
            actual=actual_statuses,
        )
        domains = sorted(SPECIALIST_3D_DOMAINS)
        placeholders = ",".join("?" for _ in domains)
        status_identity_mismatches = rows_as_dicts(
            connection,
            f"""
            SELECT s.settlement_id, c.analysis_status,
                   CASE
                     WHEN s.stage6_active_location=0 THEN 'INACTIVE'
                     WHEN s.stage6_active_settlement=0 THEN 'NOT_APPLICABLE_NONSETTLEMENT'
                     WHEN c.effective_vertical_domain IN ({placeholders}) THEN 'DEFERRED_SPECIALIST_3D'
                     WHEN s.stage6b_conditionality_status IN (
                       'CONDITIONAL_FIELD_SITE','WORK_SITE_PERMANENCE_UNRESOLVED'
                     ) THEN 'READY_2D_CONDITIONAL'
                     ELSE 'READY_2D_CURRENT'
                   END AS expected_status
            FROM settlement s JOIN stage6c_site_assessment c USING(settlement_id)
            WHERE c.analysis_status<>CASE
                    WHEN s.stage6_active_location=0 THEN 'INACTIVE'
                    WHEN s.stage6_active_settlement=0 THEN 'NOT_APPLICABLE_NONSETTLEMENT'
                    WHEN c.effective_vertical_domain IN ({placeholders}) THEN 'DEFERRED_SPECIALIST_3D'
                    WHEN s.stage6b_conditionality_status IN (
                      'CONDITIONAL_FIELD_SITE','WORK_SITE_PERMANENCE_UNRESOLVED'
                    ) THEN 'READY_2D_CONDITIONAL'
                    ELSE 'READY_2D_CURRENT'
                  END
            LIMIT 21
            """,
            tuple(domains) + tuple(domains),
        )
        scope_mismatches = rows_as_dicts(
            connection,
            """
            SELECT settlement_id, analysis_status, scope_status
            FROM stage6c_site_assessment
            WHERE scope_status<>CASE analysis_status
              WHEN 'READY_2D_CURRENT' THEN 'CURRENT_SETTLEMENT'
              WHEN 'READY_2D_CONDITIONAL' THEN 'CONDITIONAL_SETTLEMENT'
              WHEN 'DEFERRED_SPECIALIST_3D' THEN 'CURRENT_SETTLEMENT'
              WHEN 'NOT_APPLICABLE_NONSETTLEMENT' THEN 'ACTIVE_NONSETTLEMENT'
              WHEN 'INACTIVE' THEN 'INACTIVE'
            END
            LIMIT 21
            """,
        )
        validation.add("status.identity_assignment_exact", not status_identity_mismatches, expected=0, actual=len(status_identity_mismatches), details=status_identity_mismatches[:20])
        validation.add("status.scope_reconciles", not scope_mismatches, expected=0, actual=len(scope_mismatches), details=scope_mismatches[:20])

    if "stage6c_population_inputs" in inventory:
        population_columns = table_columns(connection, "stage6c_population_inputs")
        if "settlement_id" in population_columns:
            pop_missing = scalar(
                connection,
                """
                SELECT COUNT(*) FROM settlement s
                LEFT JOIN stage6c_population_inputs p USING(settlement_id)
                WHERE s.stage6_active_settlement=1 AND p.settlement_id IS NULL
                """,
            )
            pop_extra = scalar(
                connection,
                """
                SELECT COUNT(*) FROM stage6c_population_inputs p
                LEFT JOIN settlement s USING(settlement_id)
                WHERE COALESCE(s.stage6_active_settlement,0)<>1
                """,
            )
            validation.add("population_view.missing_active_settlements", pop_missing == 0, expected=0, actual=pop_missing)
            validation.add("population_view.extra_nonactive_settlements", pop_extra == 0, expected=0, actual=pop_extra)

    if "stage6c_priority_review" in inventory:
        priority_columns = table_columns(connection, "stage6c_priority_review")
        if "settlement_id" in priority_columns:
            priority_duplicates = scalar(
                connection,
                "SELECT COUNT(*) FROM (SELECT settlement_id FROM stage6c_priority_review GROUP BY settlement_id HAVING COUNT(*)<>1)",
            )
            priority_orphans = scalar(
                connection,
                "SELECT COUNT(*) FROM stage6c_priority_review p LEFT JOIN settlement s USING(settlement_id) WHERE s.settlement_id IS NULL",
            )
            validation.add("priority_review.unique", priority_duplicates == 0, expected=0, actual=priority_duplicates)
            validation.add("priority_review.no_orphans", priority_orphans == 0, expected=0, actual=priority_orphans)
            if "priority_review" in assessment_columns:
                priority_set_mismatch = scalar(
                    connection,
                    """
                    SELECT COUNT(*) FROM (
                      SELECT settlement_id FROM stage6c_priority_review
                      EXCEPT SELECT settlement_id FROM stage6c_site_assessment WHERE priority_review=1
                      UNION ALL
                      SELECT settlement_id FROM stage6c_site_assessment WHERE priority_review=1
                      EXCEPT SELECT settlement_id FROM stage6c_priority_review
                    )
                    """,
                )
                validation.add("priority_review.flag_set_exact", priority_set_mismatch == 0, expected=0, actual=priority_set_mismatch)

    if "stage6c_exception_queue" in inventory:
        exception_orphans = scalar(
            connection,
            "SELECT COUNT(*) FROM stage6c_exception_queue e LEFT JOIN settlement s USING(settlement_id) WHERE s.settlement_id IS NULL",
        )
        invalid_exception_json = scalar(
            connection,
            "SELECT COUNT(*) FROM stage6c_exception_queue WHERE json_valid(details_json)<>1",
        )
        validation.add("exception_queue.no_orphans", exception_orphans == 0, expected=0, actual=exception_orphans)
        validation.add("exception_queue.valid_json", invalid_exception_json == 0, expected=0, actual=invalid_exception_json)

    if "stage6c_review_sample" in inventory:
        sample_orphans = scalar(
            connection,
            "SELECT COUNT(*) FROM stage6c_review_sample r LEFT JOIN stage6c_site_assessment a USING(settlement_id) WHERE a.settlement_id IS NULL",
        )
        sample_order_errors = scalar(
            connection,
            "SELECT COUNT(*) FROM stage6c_review_sample WHERE sample_order<1 OR sample_order>300",
        )
        sample_haus_counts = {
            str(row[0]): int(row[1])
            for row in connection.execute(
                "SELECT owner_haus_id, COUNT(*) FROM stage6c_review_sample GROUP BY owner_haus_id"
            )
        }
        eligible_sample_hauses = {
            str(row[0]) for row in connection.execute(
                """
                SELECT DISTINCT a.owner_haus_id
                FROM stage6c_site_assessment a JOIN settlement s USING(settlement_id)
                WHERE a.analysis_status='READY_2D_CURRENT'
                  AND s.stage6b_functional_tier NOT IN ('FT0_HAUS_PRINCIPAL_SITE','FT1_MAJOR_REGIONAL_HUB')
                """
            )
        }
        sample_hash_errors = scalar(
            connection,
            """
            SELECT COUNT(*) FROM stage6c_review_sample
            WHERE LENGTH(stable_selection_hash)<>64
               OR LOWER(stable_selection_hash) GLOB '*[^0-9a-f]*'
            """,
        )
        validation.add("review_sample.no_orphans", sample_orphans == 0, expected=0, actual=sample_orphans)
        validation.add("review_sample.order_1_to_300", sample_order_errors == 0, expected=0, actual=sample_order_errors)
        validation.add("review_sample.all_eligible_hauses_covered", set(sample_haus_counts) == eligible_sample_hauses, expected=sorted(eligible_sample_hauses), actual=sample_haus_counts)
        validation.add("review_sample.valid_stable_hash", sample_hash_errors == 0, expected=0, actual=sample_hash_errors)

    validate_profiles(validation, connection, assessment_columns, inventory)
    validate_scores(validation, connection, assessment_columns)
    validate_json_and_lineage(validation, connection, assessment_columns)
    validate_canon_guards(validation, connection, assessment_columns, inventory)
    validate_sources(validation, connection, source_root, manifest_path, inventory)
    build_review_selection(validation, connection, assessment_columns, inventory)

    digest_targets = [
        "stage6c_source_manifest",
        "stage6c_coordinate_semantics_catalog",
        "stage6c_profile_catalog",
        "stage6c_profile_component",
        "stage6c_site_assessment",
        "stage6c_exception_queue",
        "stage6c_review_sample",
        "stage6c_population_inputs",
        "stage6c_review_exceptions",
        "stage6c_priority_review",
    ]
    for table in digest_targets:
        if table in inventory:
            try:
                validation.table_digests[table] = canonical_table_digest(connection, table)
            except Exception as error:  # report rather than hide deterministic-evidence failure
                validation.add(f"digest.{table}", False, details=repr(error))
    return connection


def build_review_selection(
    validation: Validation,
    connection: sqlite3.Connection,
    assessment_columns: set[str],
    inventory: Mapping[str, str],
) -> None:
    """Emit deterministic machine-review cohorts without changing the release."""

    sample_rows = rows_as_dicts(
        connection,
        """
        SELECT settlement_id, owner_haus_id, profile_id, analysis_status
        FROM stage6c_site_assessment
        WHERE profile_id IS NOT NULL
        """,
    )
    best_by_profile: dict[str, tuple[str, str]] = {}
    best_by_haus_status: dict[str, tuple[str, str]] = {}
    for row in sample_rows:
        site_id = str(row["settlement_id"])
        rank = hashlib.sha256((site_id + "|STAGE6C_VALIDATOR_SAMPLE_V1").encode("utf-8")).hexdigest()
        profile_key = str(row["profile_id"])
        haus_status_key = f"{row['owner_haus_id']}|{row['analysis_status']}"
        if profile_key not in best_by_profile or rank < best_by_profile[profile_key][0]:
            best_by_profile[profile_key] = (rank, site_id)
        if haus_status_key not in best_by_haus_status or rank < best_by_haus_status[haus_status_key][0]:
            best_by_haus_status[haus_status_key] = (rank, site_id)

    profile_sample = [value[1] for _, value in sorted(best_by_profile.items())]
    haus_status_sample = [value[1] for _, value in sorted(best_by_haus_status.items())]
    combined_sample = sorted(set(profile_sample) | set(haus_status_sample))
    sample_digest = hashlib.sha256(("\n".join(combined_sample) + "\n").encode("utf-8")).hexdigest()
    validation.add("sample.one_per_profile", len(profile_sample) == EXPECTED_PROFILE_COUNT, expected=EXPECTED_PROFILE_COUNT, actual=len(profile_sample))

    priority_ids: list[str] = []
    if "stage6c_priority_review" in inventory and "settlement_id" in table_columns(connection, "stage6c_priority_review"):
        priority_ids = [str(row[0]) for row in connection.execute("SELECT settlement_id FROM stage6c_priority_review ORDER BY settlement_id")]

    exception_summary: dict[str, Any] = {
        "queue_count": 0, "view_count": 0, "by_severity": {}, "examples": []
    }
    if "stage6c_exception_queue" in inventory:
        severity_counts = {
            str(row[0]): int(row[1])
            for row in connection.execute(
                "SELECT severity, COUNT(*) FROM stage6c_exception_queue GROUP BY severity ORDER BY severity"
            )
        }
        exception_summary.update(
            queue_count=int(scalar(connection, "SELECT COUNT(*) FROM stage6c_exception_queue") or 0),
            by_severity=severity_counts,
            examples=rows_as_dicts(connection, "SELECT * FROM stage6c_exception_queue ORDER BY severity, settlement_id LIMIT 100"),
        )
    if "stage6c_review_exceptions" in inventory:
        exception_summary["view_count"] = int(scalar(connection, "SELECT COUNT(*) FROM stage6c_review_exceptions") or 0)

    outlier_predicates: list[str] = []
    if "candidate_valid_cell_count" in assessment_columns:
        outlier_predicates.append("candidate_valid_cell_count<5")
    if "evidence_confidence_score" in assessment_columns:
        outlier_predicates.append("evidence_confidence_score<0.50")
    if "capacity_support_score" in assessment_columns:
        outlier_predicates.append("capacity_support_score<0.10")
    if "access_support_score" in assessment_columns:
        outlier_predicates.append("access_support_score<0.10")
    outlier_ids: list[str] = []
    if outlier_predicates:
        outlier_ids = [
            str(row[0]) for row in connection.execute(
                "SELECT settlement_id FROM stage6c_site_assessment "
                "WHERE analysis_status IN ('READY_2D_CURRENT','READY_2D_CONDITIONAL') AND ("
                + " OR ".join(outlier_predicates) + ") ORDER BY settlement_id"
            )
        ]
    outlier_digest = hashlib.sha256(("\n".join(outlier_ids) + "\n").encode("utf-8")).hexdigest()

    validation.review_selection = {
        "policy": "DETERMINISTIC_HASH_STRATIFICATION_V1; AUTOMATED_FIRST; MANUAL_ONLY_FOR_UNRESOLVED_HARD_OR_CANON_EXCEPTIONS",
        "profile_stratified_sample": {
            "count": len(profile_sample),
            "settlement_ids": profile_sample,
        },
        "haus_status_stratified_sample": {
            "count": len(haus_status_sample),
            "settlement_ids": haus_status_sample,
        },
        "combined_sample": {
            "count": len(combined_sample),
            "sha256": sample_digest,
            "settlement_ids": combined_sample,
        },
        "priority_review": {
            "count": len(priority_ids),
            "sha256": hashlib.sha256(("\n".join(priority_ids) + "\n").encode("utf-8")).hexdigest(),
            "settlement_ids": priority_ids,
        },
        "automatic_outliers": {
            "count": len(outlier_ids),
            "sha256": outlier_digest,
            "examples": outlier_ids[:100],
        },
        "review_exceptions": exception_summary,
    }


def validate_profiles(
    validation: Validation,
    connection: sqlite3.Connection,
    assessment_columns: set[str],
    inventory: Mapping[str, str],
) -> None:
    if "stage6c_profile_catalog" not in inventory or "stage6c_profile_component" not in inventory:
        return
    profile_columns = set(table_columns(connection, "stage6c_profile_catalog"))
    component_columns = set(table_columns(connection, "stage6c_profile_component"))

    duplicate_profiles = scalar(
        connection,
        """
        SELECT COUNT(*) FROM (
          SELECT haus_id, realised_settlement_form, effective_vertical_domain
          FROM stage6c_profile_catalog
          GROUP BY haus_id, realised_settlement_form, effective_vertical_domain
          HAVING COUNT(*)<>1
        )
        """,
    )
    validation.add("profiles.unique_haus_form_domain", duplicate_profiles == 0, expected=0, actual=duplicate_profiles)

    distinct_profile_hauses = scalar(
        connection,
        "SELECT COUNT(DISTINCT haus_id) FROM stage6c_profile_catalog",
    )
    validation.add("profiles.twenty_owner_hauses", distinct_profile_hauses == 20, expected=20, actual=distinct_profile_hauses)

    component_profile_orphans = scalar(
        connection,
        """
        SELECT COUNT(*) FROM stage6c_profile_component pc
        LEFT JOIN stage6c_profile_catalog p USING(profile_id)
        WHERE p.profile_id IS NULL
        """,
    )
    validation.add("components.no_profile_orphans", component_profile_orphans == 0, expected=0, actual=component_profile_orphans)

    wrong_component_counts = rows_as_dicts(
        connection,
        """
        SELECT p.profile_id, COUNT(pc.component_code) AS component_count
        FROM stage6c_profile_catalog p
        LEFT JOIN stage6c_profile_component pc USING(profile_id)
        GROUP BY p.profile_id
        HAVING COUNT(pc.component_code)<>9
        """,
    )
    validation.add("components.nine_per_profile", not wrong_component_counts, expected=0, actual=len(wrong_component_counts), details=wrong_component_counts[:20])

    duplicate_components = scalar(
        connection,
        """
        SELECT COUNT(*) FROM (
          SELECT profile_id, component_code FROM stage6c_profile_component
          GROUP BY profile_id, component_code HAVING COUNT(*)<>1
        )
        """,
    )
    validation.add("components.unique_profile_component", duplicate_components == 0, expected=0, actual=duplicate_components)

    actual_component_codes = {
        row[0] for row in connection.execute(
            "SELECT DISTINCT component_code FROM stage6c_profile_component"
        )
    }
    validation.add(
        "components.exact_code_set",
        actual_component_codes == EXPECTED_COMPONENT_CODES,
        expected=sorted(EXPECTED_COMPONENT_CODES),
        actual=sorted(actual_component_codes),
    )
    component_group_errors = rows_as_dicts(
        connection,
        "SELECT DISTINCT component_code, component_group FROM stage6c_profile_component",
    )
    component_group_errors = [
        row for row in component_group_errors
        if EXPECTED_COMPONENT_GROUPS.get(row["component_code"]) != row["component_group"]
    ]
    validation.add(
        "components.exact_group_assignment",
        not component_group_errors,
        expected=EXPECTED_COMPONENT_GROUPS,
        actual=component_group_errors[:20],
    )

    if "required" in component_columns:
        invalid_required = scalar(
            connection,
            "SELECT COUNT(*) FROM stage6c_profile_component WHERE required NOT IN (0,1) OR required IS NULL",
        )
        validation.add("components.required_boolean", invalid_required == 0, expected=0, actual=invalid_required)
    if "missing_policy" in component_columns:
        missing_policy = scalar(
            connection,
            "SELECT COUNT(*) FROM stage6c_profile_component WHERE COALESCE(missing_policy,'')=''",
        )
        validation.add("components.missing_policy_present", missing_policy == 0, expected=0, actual=missing_policy)

    weight_column = next((name for name in ("weight", "component_weight") if name in component_columns), None)
    if weight_column:
        invalid_weights = scalar(
            connection,
            f'SELECT COUNT(*) FROM stage6c_profile_component WHERE "{weight_column}" IS NULL OR "{weight_column}"<0 OR "{weight_column}">1',
        )
        validation.add("components.weight_bounds", invalid_weights == 0, expected=0, actual=invalid_weights)
        bad_group_sums = rows_as_dicts(
            connection,
            f"""
            SELECT profile_id, component_group, SUM("{weight_column}") AS weight_sum
            FROM stage6c_profile_component
            GROUP BY profile_id, component_group
            HAVING ABS(SUM("{weight_column}")-1.0)>1e-9
            """,
        )
        validation.add(
            "components.weight_sum_per_profile_group",
            not bad_group_sums,
            expected=1.0,
            actual=len(bad_group_sums),
            details=bad_group_sums[:20],
        )

    if {"owner_haus_id", "profile_id"}.issubset(assessment_columns):
        profiled_site_count = scalar(
            connection,
            "SELECT COUNT(*) FROM stage6c_site_assessment WHERE profile_id IS NOT NULL",
        )
        validation.add("assessment.profiled_active_settlement_count", profiled_site_count == EXPECTED_ACTIVE_SETTLEMENT_COUNT, expected=EXPECTED_ACTIVE_SETTLEMENT_COUNT, actual=profiled_site_count)
        blank_owner_or_profile = scalar(
            connection,
            """
            SELECT COUNT(*) FROM stage6c_site_assessment
            WHERE analysis_status IN ('READY_2D_CURRENT','READY_2D_CONDITIONAL','DEFERRED_SPECIALIST_3D')
              AND (COALESCE(owner_haus_id,'')='' OR COALESCE(profile_id,'')='')
            """,
        )
        validation.add("assessment.active_owner_and_profile_present", blank_owner_or_profile == 0, expected=0, actual=blank_owner_or_profile)
        out_of_scope_profile = scalar(
            connection,
            """
            SELECT COUNT(*) FROM stage6c_site_assessment
            WHERE analysis_status IN ('NOT_APPLICABLE_NONSETTLEMENT','INACTIVE')
              AND (owner_haus_id IS NOT NULL OR profile_id IS NOT NULL)
            """,
        )
        validation.add("assessment.no_profile_for_out_of_scope_identity", out_of_scope_profile == 0, expected=0, actual=out_of_scope_profile)
        used_owner_count = scalar(
            connection,
            "SELECT COUNT(DISTINCT owner_haus_id) FROM stage6c_site_assessment WHERE profile_id IS NOT NULL",
        )
        used_profile_count = scalar(
            connection,
            "SELECT COUNT(DISTINCT profile_id) FROM stage6c_site_assessment WHERE profile_id IS NOT NULL",
        )
        validation.add("assessment.twenty_owner_hauses", used_owner_count == 20, expected=20, actual=used_owner_count)
        validation.add("assessment.all_profiles_used", used_profile_count == EXPECTED_PROFILE_COUNT, expected=EXPECTED_PROFILE_COUNT, actual=used_profile_count)
        owner_basis_counts = {
            str(row[0]): int(row[1])
            for row in connection.execute(
                """
                SELECT owner_assignment_basis, COUNT(*)
                FROM stage6c_site_assessment
                WHERE profile_id IS NOT NULL
                GROUP BY owner_assignment_basis
                """
            )
        }
        expected_owner_basis = {"SETTLEMENT_MEMBERSHIP": 28_400, "ADDED_TARGET_HAUS": 1_697}
        validation.add("assessment.owner_basis_exact_counts", owner_basis_counts == expected_owner_basis, expected=expected_owner_basis, actual=owner_basis_counts)
        profile_orphans = scalar(
            connection,
            "SELECT COUNT(*) FROM stage6c_site_assessment a LEFT JOIN stage6c_profile_catalog p USING(profile_id) WHERE a.profile_id IS NOT NULL AND p.profile_id IS NULL",
        )
        validation.add("assessment.no_profile_orphans", profile_orphans == 0, expected=0, actual=profile_orphans)
        owner_profile_mismatch = scalar(
            connection,
            """
            SELECT COUNT(*) FROM stage6c_site_assessment a
            JOIN stage6c_profile_catalog p USING(profile_id)
            WHERE a.profile_id IS NOT NULL AND a.owner_haus_id<>p.haus_id
            """,
        )
        validation.add("assessment.owner_matches_profile", owner_profile_mismatch == 0, expected=0, actual=owner_profile_mismatch)

        if "stage6c_coordinate_semantics_catalog" in inventory and "coordinate_semantics_code" in assessment_columns:
            semantics_orphans = scalar(
                connection,
                """
                SELECT COUNT(*) FROM stage6c_site_assessment a
                LEFT JOIN stage6c_coordinate_semantics_catalog c USING(coordinate_semantics_code)
                WHERE c.coordinate_semantics_code IS NULL
                """,
            )
            validation.add("assessment.no_coordinate_semantics_orphans", semantics_orphans == 0, expected=0, actual=semantics_orphans)
            used_semantics = scalar(
                connection,
                "SELECT COUNT(DISTINCT coordinate_semantics_code) FROM stage6c_site_assessment",
            )
            semantics_mismatches = rows_as_dicts(
                connection,
                """
                SELECT a.settlement_id, a.coordinate_semantics_code
                FROM stage6c_site_assessment a
                JOIN stage6c_coordinate_semantics_catalog c USING(coordinate_semantics_code)
                WHERE COALESCE(a.coordinate_value_resolution_km,-1)<>COALESCE(c.value_resolution_km,-1)
                   OR a.anchor_status<>c.anchor_status
                   OR a.provisional_anchor<>c.provisional_anchor
                   OR a.horizontal_uncertainty_shape<>c.horizontal_uncertainty_shape
                   OR COALESCE(a.horizontal_uncertainty_radius_km,-1)<>
                      COALESCE(c.default_horizontal_uncertainty_radius_km,-1)
                   OR a.vertical_uncertainty_status<>c.vertical_uncertainty_status
                   OR a.footprint_status<>c.footprint_status
                LIMIT 21
                """,
            )
            validation.add("assessment.all_coordinate_semantics_used", used_semantics == EXPECTED_COORDINATE_SEMANTICS_COUNT, expected=EXPECTED_COORDINATE_SEMANTICS_COUNT, actual=used_semantics)
            validation.add("assessment.coordinate_catalog_fields_reconcile", not semantics_mismatches, expected=0, actual=len(semantics_mismatches), details=semantics_mismatches[:20])

        if "stage6_hauses_json" in table_columns(connection, "settlement"):
            owner_not_membership = rows_as_dicts(
                connection,
                """
                SELECT a.settlement_id, a.owner_haus_id, a.owner_assignment_basis
                FROM stage6c_site_assessment a JOIN settlement s USING(settlement_id)
                WHERE a.owner_haus_id IS NOT NULL AND NOT EXISTS (
                    SELECT 1
                    FROM json_each(s.stage6_hauses_json) h
                    JOIN haus catalog_haus ON catalog_haus.haus_name=h.value
                    WHERE catalog_haus.haus_id=a.owner_haus_id
                )
                """,
            )
            # Explicit administrative/fallback ownership may be valid, but it must be visible.
            unexplained = [
                row for row in owner_not_membership
                if row.get("owner_assignment_basis") != "ADDED_TARGET_HAUS"
            ]
            validation.add("assessment.owner_membership_or_explained", not unexplained, expected=0, actual=len(unexplained), details=unexplained[:20])

        catalog_site_count = scalar(connection, "SELECT SUM(site_count) FROM stage6c_profile_catalog")
        profile_count_mismatches = rows_as_dicts(
            connection,
            """
            SELECT p.profile_id, p.site_count, COUNT(a.settlement_id) AS assessment_count
            FROM stage6c_profile_catalog p
            LEFT JOIN stage6c_site_assessment a USING(profile_id)
            GROUP BY p.profile_id
            HAVING p.site_count<>COUNT(a.settlement_id)
            """,
        )
        validation.add("assessment.catalog_site_count_total", catalog_site_count == EXPECTED_ACTIVE_SETTLEMENT_COUNT, expected=EXPECTED_ACTIVE_SETTLEMENT_COUNT, actual=catalog_site_count)
        validation.add("assessment.profile_site_counts_reconcile", not profile_count_mismatches, expected=0, actual=len(profile_count_mismatches), details=profile_count_mismatches[:20])

    exact_match_pairs = (
        ("effective_vertical_domain", "effective_vertical_domain"),
        ("morphology_class", "morphology_class"),
        ("capacity_metric_kind", "capacity_metric_kind"),
    )
    for assessment_column, profile_column in exact_match_pairs:
        if assessment_column not in assessment_columns or profile_column not in profile_columns:
            continue
        mismatches = scalar(
            connection,
            f"""
            SELECT COUNT(*) FROM stage6c_site_assessment a
            JOIN stage6c_profile_catalog p USING(profile_id)
            WHERE a.profile_id IS NOT NULL
              AND COALESCE(a."{assessment_column}",'')<>COALESCE(p."{profile_column}",'')
            """,
        )
        validation.add(f"assessment.profile_match.{assessment_column}", mismatches == 0, expected=0, actual=mismatches)


def validate_scores(
    validation: Validation,
    connection: sqlite3.Connection,
    assessment_columns: set[str],
) -> None:
    available_scores = [column for column in SCORE_COLUMNS if column in assessment_columns]
    validation.add(
        "scores.expected_columns_present",
        len(available_scores) == len(SCORE_COLUMNS),
        expected=list(SCORE_COLUMNS),
        actual=available_scores,
    )
    for column in available_scores:
        invalid = scalar(
            connection,
            f'SELECT COUNT(*) FROM stage6c_site_assessment WHERE "{column}" IS NOT NULL AND ("{column}"<0 OR "{column}">1)',
        )
        validation.add(f"scores.bounds.{column}", invalid == 0, expected=0, actual=invalid)

    if available_scores:
        ready_missing_scores = scalar(
            connection,
            "SELECT COUNT(*) FROM stage6c_site_assessment "
            "WHERE analysis_status IN ('READY_2D_CURRENT','READY_2D_CONDITIONAL') AND ("
            + " OR ".join(f'"{column}" IS NULL' for column in available_scores)
            + ")",
        )
        validation.add("scores.ready_2d_complete", ready_missing_scores == 0, expected=0, actual=ready_missing_scores)

    raw_ready_columns = [
        column for column in (
            "terrain_elevation_m",
            "terrain_slope_deg",
            "local_relief_m",
            "corrected_surface_water_distance_km",
            "corrected_perennial_channel_distance_km",
            "flood_exposure_index",
            "developable_area_r1_km2",
            "developable_area_r5_km2",
            "land_access_cost_index",
            "water_access_index",
            "seasonal_reliability_index",
        ) if column in assessment_columns
    ]
    if raw_ready_columns:
        ready_missing_metrics = scalar(
            connection,
            "SELECT COUNT(*) FROM stage6c_site_assessment "
            "WHERE analysis_status IN ('READY_2D_CURRENT','READY_2D_CONDITIONAL') AND ("
            + " OR ".join(f'"{column}" IS NULL' for column in raw_ready_columns)
            + ")",
        )
        validation.add("metrics.ready_2d_complete", ready_missing_metrics == 0, expected=0, actual=ready_missing_metrics)

    triples = (
        ("capacity_support_score_low", "capacity_support_score", "capacity_support_score_high"),
        ("access_support_score_low", "access_support_score", "access_support_score_high"),
    )
    for low, central, high in triples:
        if {low, central, high}.issubset(assessment_columns):
            invalid_order = scalar(
                connection,
                f"""
                SELECT COUNT(*) FROM stage6c_site_assessment
                WHERE "{low}" IS NOT NULL AND "{central}" IS NOT NULL AND "{high}" IS NOT NULL
                  AND ("{low}">"{central}"+1e-12 OR "{central}">"{high}"+1e-12)
                """,
            )
            validation.add(f"scores.order.{central}", invalid_order == 0, expected=0, actual=invalid_order)

    if {
        "stage6c_profile_component",
        "stage6c_profile_catalog",
        "stage6c_site_assessment",
    }.issubset(object_inventory(connection)) and {
        "capacity_support_score",
        "access_support_score",
    }.issubset(assessment_columns) and "weight" in table_columns(connection, "stage6c_profile_component"):
        component_rules: dict[str, dict[str, dict[str, Any]]] = {}
        for row in connection.execute(
            """
            SELECT profile_id, component_code, component_group, raw_metric_code,
                   transform_code, p0, p1, p2, p3, weight
            FROM stage6c_profile_component
            """
        ):
            component_rules.setdefault(str(row[0]), {})[str(row[1])] = {
                "group": str(row[2]), "raw_metric_code": str(row[3]),
                "transform_code": str(row[4]), "p0": row[5], "p1": row[6],
                "p2": row[7], "p3": row[8], "weight": float(row[9]),
            }
        operators = {
            str(row[0]): (str(row[1]), str(row[2]))
            for row in connection.execute(
                "SELECT profile_id, capacity_operator, access_operator FROM stage6c_profile_catalog"
            )
        }
        score_fields = {code: code.lower() + "_score" for code in EXPECTED_COMPONENT_CODES}
        raw_metric_fields = sorted({
            str(rule["raw_metric_code"])
            for profile_rules in component_rules.values()
            for rule in profile_rules.values()
        })
        missing_raw_metric_fields = sorted(set(raw_metric_fields) - assessment_columns)
        validation.add("scores.raw_metric_fields_present", not missing_raw_metric_fields, expected=raw_metric_fields, actual={"missing": missing_raw_metric_fields})
        selected_fields = list(dict.fromkeys(
            ["settlement_id", "profile_id", "capacity_support_score", "access_support_score"]
            + list(score_fields.values()) + [field for field in raw_metric_fields if field in assessment_columns]
        ))
        aggregate_mismatches: list[dict[str, Any]] = []
        component_mismatches: list[dict[str, Any]] = []
        unknown_operators: set[str] = set()
        unknown_transforms: set[str] = set()

        def geometric(values: list[tuple[float, float]]) -> float | None:
            usable = [(max(value, 1e-6), weight) for value, weight in values if weight > 0]
            if not usable:
                return None
            total = sum(weight for _, weight in usable)
            return math.exp(sum(weight * math.log(value) for value, weight in usable) / total)

        def transformed(value: Any, rule: Mapping[str, Any]) -> float | None:
            code = str(rule["transform_code"])
            if code == "DEFERRED":
                return None
            if value is None:
                return None
            number = float(value)
            p0, p1, p2, p3 = (rule.get("p0"), rule.get("p1"), rule.get("p2"), rule.get("p3"))
            if code == "CONSTANT":
                result = float(p0)
            elif code == "BINARY":
                result = float(bool(number))
            elif code == "HIGH_BETTER":
                result = float(number >= p1) if p1 == p0 else (number - p0) / (p1 - p0)
            elif code == "LOW_BETTER":
                result = float(number <= p0) if p1 == p0 else 1.0 - (number - p0) / (p1 - p0)
            elif code == "RANGE_TRAPEZOID":
                # The plateau owns its endpoints. This preserves deliberately
                # degenerate ramps such as p0 == p1 at zero flood exposure.
                if p1 <= number <= p2:
                    result = 1.0
                elif number <= p0 or number >= p3:
                    result = 0.0
                elif number < p1:
                    result = (number - p0) / max(p1 - p0, 1e-12)
                else:
                    result = (p3 - number) / max(p3 - p2, 1e-12)
            else:
                unknown_transforms.add(code)
                return None
            return min(1.0, max(0.0, float(result)))

        query = (
            "SELECT " + ",".join(f'"{field}"' for field in selected_fields)
            + " FROM stage6c_site_assessment WHERE analysis_status IN ('READY_2D_CURRENT','READY_2D_CONDITIONAL')"
        )
        for sql_row in connection.execute(query):
            row = dict(zip(selected_fields, sql_row))
            profile_id = str(row["profile_id"])
            rules_for_profile = component_rules.get(profile_id, {})
            capacity_values: list[tuple[float, float]] = []
            access_values: list[tuple[float, float]] = []
            for code, rule in rules_for_profile.items():
                value = row.get(score_fields[code])
                if value is None:
                    continue
                expected_component = transformed(row.get(rule["raw_metric_code"]), rule)
                if (
                    expected_component is None
                    or abs(float(value) - expected_component) > 1e-8
                ) and len(component_mismatches) < 21:
                    component_mismatches.append(
                        {
                            "settlement_id": row["settlement_id"],
                            "component_code": code,
                            "actual": value,
                            "expected": expected_component,
                        }
                    )
                target = capacity_values if rule["group"] == "CAPACITY" else access_values
                target.append((float(value), float(rule["weight"])))
            capacity_operator, access_operator = operators.get(profile_id, ("", ""))
            if capacity_operator not in ("WEIGHTED_GEOMEAN", "REQUIRED_WEIGHTED_GEOMEAN"):
                unknown_operators.add(capacity_operator)
            expected_capacity = geometric(capacity_values)
            if access_operator == "WEIGHTED_MAX":
                land = float(row["land_access_score"])
                water = float(row["water_access_score"])
                seasonal = float(row["seasonal_reliability_score"])
                expected_access = math.sqrt(max(max(land, water), 1e-6) * max(seasonal, 1e-6))
            elif access_operator in ("WEIGHTED_GEOMEAN", "REQUIRED_WEIGHTED_GEOMEAN"):
                expected_access = geometric(access_values)
            else:
                unknown_operators.add(access_operator)
                expected_access = None
            mismatch = (
                expected_capacity is None
                or expected_access is None
                or abs(float(row["capacity_support_score"]) - expected_capacity) > 1e-8
                or abs(float(row["access_support_score"]) - expected_access) > 1e-8
            )
            if mismatch and len(aggregate_mismatches) < 21:
                aggregate_mismatches.append(
                    {
                        "settlement_id": row["settlement_id"],
                        "actual_capacity": row["capacity_support_score"],
                        "expected_capacity": expected_capacity,
                        "actual_access": row["access_support_score"],
                        "expected_access": expected_access,
                    }
                )
        validation.add("scores.known_aggregation_operators", not unknown_operators, expected="known operators", actual=sorted(unknown_operators))
        validation.add("scores.known_component_transforms", not unknown_transforms, expected="known transforms", actual=sorted(unknown_transforms))
        validation.add(
            "scores.component_transforms_reconcile",
            not component_mismatches,
            expected=0,
            actual=len(component_mismatches),
            details=component_mismatches[:20],
        )
        validation.add(
            "scores.weighted_aggregate_reconciles",
            not aggregate_mismatches,
            expected=0,
            actual=len(aggregate_mismatches),
            details=aggregate_mismatches[:20],
        )

    if "capacity_band" in assessment_columns and "stage6c_profile_catalog" in object_inventory(connection):
        bad_bands = rows_as_dicts(
            connection,
            """
            SELECT a.settlement_id, a.capacity_support_score, a.capacity_band,
                   CASE
                     WHEN a.capacity_support_score<p.band_t1 THEN 'CB0_UNSUPPORTED'
                     WHEN a.capacity_support_score<p.band_t2 THEN 'CB1_CONSTRAINED'
                     WHEN a.capacity_support_score<p.band_t3 THEN 'CB2_MODERATE'
                     WHEN a.capacity_support_score<p.band_t4 THEN 'CB3_STRONG'
                     ELSE 'CB4_EXCEPTIONAL'
                   END AS expected_band
            FROM stage6c_site_assessment a JOIN stage6c_profile_catalog p USING(profile_id)
            WHERE a.capacity_support_score IS NOT NULL
              AND a.capacity_band<>CASE
                    WHEN a.capacity_support_score<p.band_t1 THEN 'CB0_UNSUPPORTED'
                    WHEN a.capacity_support_score<p.band_t2 THEN 'CB1_CONSTRAINED'
                    WHEN a.capacity_support_score<p.band_t3 THEN 'CB2_MODERATE'
                    WHEN a.capacity_support_score<p.band_t4 THEN 'CB3_STRONG'
                    ELSE 'CB4_EXCEPTIONAL'
                  END
            LIMIT 21
            """,
        )
        validation.add("scores.capacity_band_reconciles", not bad_bands, expected=0, actual=len(bad_bands), details=bad_bands[:20])

    raw_bounded = (
        "flood_exposure_index",
        "land_access_cost_index",
        "water_access_index",
        "seasonal_reliability_index",
    )
    for column in raw_bounded:
        if column not in assessment_columns:
            continue
        invalid = scalar(
            connection,
            f'SELECT COUNT(*) FROM stage6c_site_assessment WHERE "{column}" IS NOT NULL AND ("{column}"<0 OR "{column}">1)',
        )
        validation.add(f"metrics.bounds.{column}", invalid == 0, expected=0, actual=invalid)

    nonnegative = (
        "corrected_surface_water_distance_km",
        "corrected_perennial_channel_distance_km",
        "terrain_slope_deg",
        "local_relief_m",
        "developable_area_r1_km2",
        "developable_area_r5_km2",
    )
    for column in nonnegative:
        if column not in assessment_columns:
            continue
        invalid = scalar(
            connection,
            f'SELECT COUNT(*) FROM stage6c_site_assessment WHERE "{column}" IS NOT NULL AND "{column}"<0',
        )
        validation.add(f"metrics.nonnegative.{column}", invalid == 0, expected=0, actual=invalid)

    if {"developable_area_r1_km2", "developable_area_r5_km2"}.issubset(assessment_columns):
        invalid_area_order = scalar(
            connection,
            """
            SELECT COUNT(*) FROM stage6c_site_assessment
            WHERE developable_area_r1_km2 IS NOT NULL AND developable_area_r5_km2 IS NOT NULL
              AND developable_area_r1_km2>developable_area_r5_km2+1e-12
            """,
        )
        validation.add("metrics.developable_area_radius_order", invalid_area_order == 0, expected=0, actual=invalid_area_order)

    if {"corrected_surface_water_distance_km", "corrected_perennial_channel_distance_km"}.issubset(assessment_columns):
        invalid_water_order = scalar(
            connection,
            """
            SELECT COUNT(*) FROM stage6c_site_assessment
            WHERE corrected_surface_water_distance_km IS NOT NULL
              AND corrected_perennial_channel_distance_km IS NOT NULL
              AND corrected_surface_water_distance_km>corrected_perennial_channel_distance_km+1e-9
            """,
        )
        validation.add("metrics.any_water_not_farther_than_perennial", invalid_water_order == 0, expected=0, actual=invalid_water_order)

    hydro_min_columns = [
        column for column in (
            "min_major_distance_km",
            "min_minor_distance_km",
            "min_special_water_distance_km",
            "min_permanent_lake_distance_km",
            "min_seasonal_lake_distance_km",
            "min_coast_distance_km",
        ) if column in assessment_columns
    ]
    for column in hydro_min_columns:
        invalid = scalar(
            connection,
            f'SELECT COUNT(*) FROM stage6c_site_assessment WHERE "{column}" IS NOT NULL AND "{column}"<0',
        )
        validation.add(f"hydrology.nonnegative.{column}", invalid == 0, expected=0, actual=invalid)
    if len(hydro_min_columns) == 6 and "corrected_surface_water_distance_km" in assessment_columns:
        min_expression = "MIN(" + ",".join(hydro_min_columns) + ")"
        impossible_median = scalar(
            connection,
            f"""
            SELECT COUNT(*) FROM stage6c_site_assessment
            WHERE corrected_surface_water_distance_km IS NOT NULL
              AND COALESCE(hydrology_basis,'') NOT LIKE '%LAGOON_FORM_ALSO_USES_MANAGED_SERENAKRONE_OVERLAY%'
              AND corrected_surface_water_distance_km+1e-9 < {min_expression}
            """,
        )
        validation.add("hydrology.median_not_below_candidate_minimum", impossible_median == 0, expected=0, actual=impossible_median)
    if "hydrology_basis" in assessment_columns:
        base_basis = (
            "SEALED_V4_2_MAJOR_PLUS_D3_FEEDERS_PLUS_CORRECTED_STILLKLINGE_LOCAL_PLUS_"
            "STRICT_SPECIAL_PLUS_RESOLVED_LAKES_PLUS_COAST; NOT_MAJOR_ONLY"
        )
        lagoon_basis = base_basis + "; LAGOON_FORM_ALSO_USES_MANAGED_SERENAKRONE_OVERLAY"
        wrong_basis = scalar(
            connection,
            """
            SELECT COUNT(*) FROM stage6c_site_assessment
            WHERE analysis_status<>'INACTIVE'
              AND COALESCE(hydrology_basis,'') NOT IN (?,?)
            """,
            (base_basis, lagoon_basis),
        )
        validation.add("hydrology.full_corrected_stack_declared", wrong_basis == 0, expected=0, actual=wrong_basis)
        lagoon_basis_rows = scalar(
            connection,
            "SELECT COUNT(*) FROM stage6c_site_assessment WHERE hydrology_basis=?",
            (lagoon_basis,),
        )
        validation.add(
            "hydrology.managed_lagoon_basis_declared",
            lagoon_basis_rows == 11,
            expected=11,
            actual=lagoon_basis_rows,
        )

    derived_metric_requirements = {
        "water_access_index",
        "seasonal_reliability_index",
        "land_access_cost_index",
        "corrected_surface_water_distance_km",
        "corrected_perennial_channel_distance_km",
        "terrain_slope_deg",
        "local_relief_m",
        "flood_exposure_index",
    }
    if derived_metric_requirements.issubset(assessment_columns):
        derived_mismatches = rows_as_dicts(
            connection,
            """
            SELECT settlement_id, water_access_index, seasonal_reliability_index,
                   land_access_cost_index
            FROM stage6c_site_assessment
            WHERE corrected_surface_water_distance_km IS NOT NULL
              AND (
                ABS(water_access_index-(1.0/(1.0+corrected_surface_water_distance_km/2.0)))>1e-9
                OR ABS(seasonal_reliability_index-
                    MIN(1.0, MAX(0.0,
                      0.75*EXP(-corrected_perennial_channel_distance_km/10.0)
                      +0.25*EXP(-corrected_surface_water_distance_km/5.0))))>1e-9
                OR ABS(land_access_cost_index-
                    MIN(1.0, MAX(0.0,
                      0.60*MIN(terrain_slope_deg/35.0,1.0)
                      +0.25*MIN(local_relief_m/500.0,1.0)
                      +0.15*flood_exposure_index)))>1e-9
              )
            LIMIT 21
            """,
        )
        validation.add(
            "metrics.derived_indices_reconcile",
            not derived_mismatches,
            expected=0,
            actual=len(derived_mismatches),
            details=derived_mismatches[:20],
        )


def validate_json_and_lineage(
    validation: Validation,
    connection: sqlite3.Connection,
    assessment_columns: set[str],
) -> None:
    json_columns = [
        column for column in (
            "access_modes_json",
            "expansion_sector_weights_json",
            "limiting_factors_json",
        ) if column in assessment_columns
    ]
    for column in json_columns:
        invalid = scalar(
            connection,
            f'SELECT COUNT(*) FROM stage6c_site_assessment WHERE "{column}" IS NOT NULL AND json_valid("{column}")<>1',
        )
        validation.add(f"json.valid.{column}", invalid == 0, expected=0, actual=invalid)

    if "input_fingerprint" in assessment_columns:
        bad_fingerprints = scalar(
            connection,
            """
            SELECT COUNT(*) FROM stage6c_site_assessment
            WHERE input_fingerprint IS NULL
               OR LENGTH(input_fingerprint)<>64
               OR LOWER(input_fingerprint) GLOB '*[^0-9a-f]*'
            """,
        )
        validation.add("lineage.input_fingerprint_sha256", bad_fingerprints == 0, expected=0, actual=bad_fingerprints)
    if "method_version" in assessment_columns:
        missing_method = scalar(connection, "SELECT COUNT(*) FROM stage6c_site_assessment WHERE COALESCE(method_version,'')='' ")
        validation.add("lineage.method_version_present", missing_method == 0, expected=0, actual=missing_method)
    if "canon_status" in assessment_columns:
        promoted = rows_as_dicts(
            connection,
            """
            SELECT settlement_id, canon_status FROM stage6c_site_assessment
            WHERE UPPER(canon_status) IN ('CANON','APPROVED_CANON','LOCKED_CANON')
               OR UPPER(canon_status) LIKE '%CANON_APPROVED%'
            LIMIT 20
            """,
        )
        validation.add("canon.no_silent_promotion", not promoted, expected=0, actual=len(promoted), details=promoted)
    if "footprint_status" in assessment_columns:
        final_footprints = rows_as_dicts(
            connection,
            """
            SELECT settlement_id, footprint_status FROM stage6c_site_assessment
            WHERE UPPER(footprint_status) IN ('FINAL_FOOTPRINT','GENERATED_FINAL','OCCUPIED_POLYGON')
               OR UPPER(footprint_status) LIKE '%FINAL_POLYGON%'
            LIMIT 20
            """,
        )
        validation.add("scope.no_final_settlement_footprints", not final_footprints, expected=0, actual=len(final_footprints), details=final_footprints)


def validate_canon_guards(
    validation: Validation,
    connection: sqlite3.Connection,
    assessment_columns: set[str],
    inventory: Mapping[str, str],
) -> None:
    no_ordinary_hauses = {
        "Duftfaehrte": ("Duftfährte", "Duftf�hrte"),
        "Dunkelhauch": ("Dunkelhauch",),
        "Laubraunen": ("Laubraunen",),
        "Verfuehrschlund": ("Verführschlund", "Verf�hrschlund"),
    }
    for haus_label, aliases in no_ordinary_hauses.items():
        placeholders = ",".join("?" for _ in aliases)
        count = scalar(
            connection,
            f"""
            SELECT COUNT(DISTINCT s.settlement_id)
            FROM settlement s, json_each(s.stage6_hauses_json) h
            WHERE h.value IN ({placeholders}) AND s.stage6_ordinary_permanent_human_settlement=1
            """,
            aliases,
        )
        validation.add(f"canon.no_ordinary_human.{haus_label}", count == 0, expected=0, actual=count)

    dunk_active = scalar(
        connection,
        """
        SELECT COUNT(DISTINCT s.settlement_id)
        FROM settlement s, json_each(s.stage6_hauses_json) h
        WHERE h.value='Dunkelhauch' AND s.stage6_active_settlement=1
        """,
    )
    validation.add("canon.dunkelhauch_one_active_settlement", dunk_active == 1, expected=1, actual=dunk_active)

    glanz_submerged = scalar(
        connection,
        """
        SELECT COUNT(DISTINCT s.settlement_id)
        FROM settlement s, json_each(s.stage6_hauses_json) h
        WHERE h.value='Glanzgrund'
          AND COALESCE(s.stage6_vertical_domain_class,s.vertical_domain_class)='FULLY_SUBMERGED_NATIVE_SPECIALIST_DOMAIN'
        """,
    )
    glanz_submerged_human = scalar(
        connection,
        """
        SELECT COUNT(DISTINCT s.settlement_id)
        FROM settlement s, json_each(s.stage6_hauses_json) h
        WHERE h.value='Glanzgrund'
          AND COALESCE(s.stage6_vertical_domain_class,s.vertical_domain_class)='FULLY_SUBMERGED_NATIVE_SPECIALIST_DOMAIN'
          AND s.stage6_ordinary_permanent_human_settlement=1
        """,
    )
    validation.add("canon.glanzgrund_two_submerged_native_sites", glanz_submerged == 2, expected=2, actual=glanz_submerged)
    validation.add("canon.glanzgrund_no_submerged_ordinary_humans", glanz_submerged_human == 0, expected=0, actual=glanz_submerged_human)

    seren_submerged = scalar(
        connection,
        """
        SELECT COUNT(DISTINCT s.settlement_id)
        FROM settlement s, json_each(s.stage6_hauses_json) h
        WHERE h.value='Serenakrone'
          AND UPPER(COALESCE(s.stage6_vertical_domain_class,s.vertical_domain_class,'')) LIKE '%SUBMERG%'
        """,
    )
    validation.add("canon.serenakrone_not_submerged", seren_submerged == 0, expected=0, actual=seren_submerged)

    seelen_counts = {
        row[0]: row[1]
        for row in connection.execute(
            """
            SELECT s.stage6b_functional_tier, COUNT(DISTINCT s.settlement_id)
            FROM settlement s, json_each(s.stage6_hauses_json) h
            WHERE h.value='Seelenwacht' AND s.stage6b_functional_tier LIKE 'FTU%'
            GROUP BY s.stage6b_functional_tier
            """
        )
    }
    expected_seelen = {
        "FTU_CONDITIONAL_FIELD_SITE": 150,
        "FTU_PERMANENCE_UNRESOLVED": 26,
    }
    validation.add("canon.seelenwacht_unresolved_preserved", seelen_counts == expected_seelen, expected=expected_seelen, actual=seelen_counts)

    if "stage6b_unresolved_functional_assignment" in inventory:
        hospital_rows = rows_as_dicts(
            connection,
            """
            SELECT assignment_status, candidate_site_ids_json
            FROM stage6b_unresolved_functional_assignment
            WHERE assignment_id='S6B-WGF-RIVER-PORT-HOSPITAL-SITE-SELECTION'
            """,
        )
        expected_candidates = sorted(
            [
                "SITE4-D675A0DB5FCE17B0",
                "SITE4-6A84A771DFE3E676",
                "SITE4-F3EE103FC3BC072A",
            ]
        )
        hospital_ok = False
        if len(hospital_rows) == 1:
            try:
                actual_candidates = sorted(json.loads(hospital_rows[0]["candidate_site_ids_json"]))
            except (TypeError, json.JSONDecodeError):
                actual_candidates = []
            hospital_ok = (
                hospital_rows[0]["assignment_status"] == "CANON_ROLE_APPROVED_EXACT_SITE_UNSELECTED"
                and actual_candidates == expected_candidates
            )
        validation.add("canon.wgf_hospital_unselected", hospital_ok, expected={"status": "CANON_ROLE_APPROVED_EXACT_SITE_UNSELECTED", "candidates": expected_candidates}, actual=hospital_rows)

    if "stage6_capital_decision" in inventory:
        duft_fixed = scalar(
            connection,
            "SELECT COUNT(*) FROM stage6_capital_decision WHERE haus IN ('Duftfährte','Duftf�hrte') AND fixed_capital_winner=1",
        )
        validation.add("canon.duftfaehrte_no_fixed_capital", duft_fixed == 0, expected=0, actual=duft_fixed)

        selected_expectations = {
            "Moorwandler": "S6-MOOR-CAPITAL-ANCHOR-01",
            "Stillklinge": "SITE4-5C8B1C2829C19843",
            "Serenakrone": "SITE4-BB29BFB4F83D4C02",
        }
        for haus, expected_site in selected_expectations.items():
            selected = [
                row[0]
                for row in connection.execute(
                    "SELECT site_id_or_nonspatial FROM stage6_capital_decision WHERE haus=? AND winner_selected=1 AND COALESCE(site_id_or_nonspatial,'')<>''",
                    (haus,),
                )
            ]
            validation.add(f"canon.selected_capital.{haus}", selected == [expected_site], expected=[expected_site], actual=selected)

        if "analysis_status" in assessment_columns:
            still_status = scalar(
                connection,
                "SELECT analysis_status FROM stage6c_site_assessment WHERE settlement_id='SITE4-5C8B1C2829C19843'",
            )
            seren_status = scalar(
                connection,
                "SELECT analysis_status FROM stage6c_site_assessment WHERE settlement_id='SITE4-BB29BFB4F83D4C02'",
            )
            validation.add("canon.stillklinge_3d_deferred", still_status == "DEFERRED_SPECIALIST_3D", expected="DEFERRED_SPECIALIST_3D", actual=still_status)
            validation.add("canon.serenakrone_surface_lagoon_current", seren_status == "READY_2D_CURRENT", expected="READY_2D_CURRENT", actual=seren_status)
        contact_columns = {
            "min_major_distance_km", "min_minor_distance_km", "min_special_water_distance_km",
            "min_permanent_lake_distance_km", "min_seasonal_lake_distance_km", "min_coast_distance_km",
        }
        if contact_columns.issubset(assessment_columns):
            for site_id, label in (
                ("S6-MOOR-CAPITAL-ANCHOR-01", "moorwandler"),
                ("SITE4-5C8B1C2829C19843", "stillklinge"),
                ("SITE4-BB29BFB4F83D4C02", "serenakrone"),
            ):
                distance = scalar(
                    connection,
                    """
                    SELECT MIN(min_major_distance_km,min_minor_distance_km,
                               min_special_water_distance_km,min_permanent_lake_distance_km,
                               min_seasonal_lake_distance_km,min_coast_distance_km)
                    FROM stage6c_site_assessment WHERE settlement_id=?
                    """,
                    (site_id,),
                )
                validation.add(
                    f"canon.selected_capital_surface_water_contact.{label}",
                    distance is not None and float(distance) <= 0.10,
                    expected="active water geometry within one 100 m cell",
                    actual=distance,
                )
        if "wetland_fraction" in assessment_columns:
            moor_wetland_fraction = scalar(
                connection,
                "SELECT wetland_fraction FROM stage6c_site_assessment WHERE settlement_id='S6-MOOR-CAPITAL-ANCHOR-01'",
            )
            validation.add(
                "canon.moorwandler_capital_deep_wetland_context",
                moor_wetland_fraction is not None and float(moor_wetland_fraction) >= 0.50,
                expected=">=0.50 candidate-window wetland fraction",
                actual=moor_wetland_fraction,
            )


def validate_sources(
    validation: Validation,
    connection: sqlite3.Connection,
    source_root: Path | None,
    manifest_path: Path | None,
    inventory: Mapping[str, str],
) -> None:
    if "stage6c_source_manifest" not in inventory:
        return
    source_rows = rows_as_dicts(connection, "SELECT * FROM stage6c_source_manifest ORDER BY source_role")
    validation.add("source_manifest.nonempty", bool(source_rows), expected=">0", actual=len(source_rows))
    invalid_sha_rows = [row for row in source_rows if not HEX64_RE.fullmatch(str(row.get("sha256") or ""))]
    validation.add("source_manifest.valid_sha256", not invalid_sha_rows, expected=0, actual=len(invalid_sha_rows), details=invalid_sha_rows[:20])

    forbidden_rows = [
        row for row in source_rows
        if any(marker in json.dumps(row, ensure_ascii=False).upper() for marker in FORBIDDEN_SOURCE_MARKERS)
    ]
    validation.add("source_manifest.no_forbidden_inputs", not forbidden_rows, expected=0, actual=len(forbidden_rows), details=forbidden_rows[:20])

    manifest_payload: Any = None
    if manifest_path is not None:
        try:
            manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            validation.add("sidecar_manifest.parse", True, actual=str(manifest_path))
        except Exception as error:
            validation.add("sidecar_manifest.parse", False, details=repr(error), actual=str(manifest_path))
    if isinstance(manifest_payload, Mapping):
        actual_composition = manifest_payload.get("hydrology_composition")
        validation.add(
            "sidecar_manifest.hydrology_composition",
            actual_composition == EXPECTED_HYDROLOGY_COMPOSITION,
            expected=EXPECTED_HYDROLOGY_COMPOSITION,
            actual=actual_composition,
        )
    sidecar_hash_set = recursive_hashes(manifest_payload) if manifest_payload is not None else set()
    table_hash_set = {str(row.get("sha256") or "").lower() for row in source_rows}
    available_hashes = table_hash_set | sidecar_hash_set

    for role, expected in EXPECTED_SOURCES.items():
        expected_hash = expected["sha256"]
        validation.add(
            f"source.current.{role}",
            expected_hash in available_hashes,
            expected=expected_hash,
            actual="present" if expected_hash in available_hashes else "missing",
        )

        matching_rows = [row for row in source_rows if str(row.get("sha256") or "").lower() == expected_hash]
        expected_count = expected.get("count")
        if matching_rows and expected_count is not None:
            count_keys = (
                "feature_count", "record_count", "row_count", "feature_or_record_count",
                "expected_count", "count",
            )
            recorded = None
            for key in count_keys:
                if key in matching_rows[0] and matching_rows[0][key] not in (None, ""):
                    try:
                        recorded = int(matching_rows[0][key])
                    except (TypeError, ValueError):
                        recorded = None
                    break
            if recorded is not None:
                validation.add(f"source.count.{role}", recorded == expected_count, expected=expected_count, actual=recorded)

        if role == "terrain_100m" and matching_rows:
            terrain_row = matching_rows[0]
            for key, expected_value in (("width", expected.get("width")), ("height", expected.get("height"))):
                aliases = (key, f"raster_{key}", f"grid_{key}")
                recorded_value = next((terrain_row.get(alias) for alias in aliases if terrain_row.get(alias) not in (None, "")), None)
                if recorded_value is not None and expected_value is not None:
                    try:
                        actual_value = int(recorded_value)
                    except (TypeError, ValueError):
                        actual_value = recorded_value
                    validation.add(f"source.grid.{key}", actual_value == expected_value, expected=expected_value, actual=actual_value)
            transform_value = next(
                (terrain_row.get(key) for key in ("transform_json", "grid_transform_json", "transform") if terrain_row.get(key) not in (None, "")),
                None,
            )
            if transform_value is not None:
                try:
                    actual_transform = json.loads(transform_value) if isinstance(transform_value, str) else list(transform_value)
                except (TypeError, ValueError, json.JSONDecodeError):
                    actual_transform = transform_value
                validation.add("source.grid.transform", actual_transform == expected["transform"], expected=expected["transform"], actual=actual_transform)

    resolved_count = 0
    resolved_by_hash: dict[str, Path] = {}
    for row in source_rows:
        source_file = resolve_source_file(row, source_root)
        if source_file is None:
            continue
        resolved_count += 1
        expected_hash = str(row.get("sha256") or "").lower()
        resolved_by_hash[expected_hash] = source_file
        actual_hash = sha256_file(source_file)
        validation.add(
            f"source.file_hash.{row.get('source_role')}",
            actual_hash == expected_hash,
            expected=expected_hash,
            actual=actual_hash,
            details=str(source_file),
        )
        expected = next((spec for spec in EXPECTED_SOURCES.values() if spec["sha256"] == expected_hash), None)
        if expected and expected.get("count") is not None:
            actual_count = geojson_feature_count(source_file)
            if actual_count is not None:
                validation.add(
                    f"source.file_feature_count.{row.get('source_role')}",
                    actual_count == expected["count"],
                    expected=expected["count"],
                    actual=actual_count,
                )
    if resolved_count == 0:
        validation.warn(
            "source.files_not_resolved",
            "Source currentness was validated from recorded hashes, but no physical source paths were resolvable. Pass --source-root for direct file hashing.",
        )
    else:
        validation.add("source.files_resolved", True, actual=resolved_count)

    quarantined = {
        "D3-MIN-013654", "D3-MIN-013664", "D3-MIN-013676", "D3-MIN-013700",
        "D3-MIN-013701", "D3-MIN-013711", "D3-MIN-013712", "D3-MIN-013713",
    }
    parent_minor_path = resolved_by_hash.get(EXPECTED_SOURCES["parent_minor_lineage"]["sha256"])
    d3_raw_path = resolved_by_hash.get(EXPECTED_SOURCES["d3_feeder_raw"]["sha256"])
    d3_enriched_path = resolved_by_hash.get(EXPECTED_SOURCES["d3_feeder_enriched"]["sha256"])
    still_support_path = resolved_by_hash.get(EXPECTED_SOURCES["stillklinge_support"]["sha256"])
    if parent_minor_path is not None:
        try:
            lineage_features = json.loads(parent_minor_path.read_text(encoding="utf-8-sig")).get("features", [])
            lineage_ids = {str((feature.get("properties") or {}).get("minor_id") or "") for feature in lineage_features}
            present_quarantine = sorted(lineage_ids & quarantined)
            validation.add("hydrology.parent_minor_lineage_quarantine_absent", not present_quarantine, expected=[], actual=present_quarantine)
        except Exception as error:
            validation.add("hydrology.parent_minor_lineage_parse", False, details=repr(error))
    if d3_raw_path is not None and d3_enriched_path is not None:
        try:
            raw_features = json.loads(d3_raw_path.read_text(encoding="utf-8-sig")).get("features", [])
            enriched_features = json.loads(d3_enriched_path.read_text(encoding="utf-8-sig")).get("features", [])
            raw_ids = [str((feature.get("properties") or {}).get("minor_id") or "") for feature in raw_features]
            enriched_props = [dict(feature.get("properties") or {}) for feature in enriched_features]
            enriched_ids = [str(item.get("minor_id") or "") for item in enriched_props]
            outside = [item for item in enriched_props if item.get("system") != "Stillklinge"]
            perennial = [item for item in outside if item.get("persistence") in {"perennial", "perennial_saturated"}]
            validation.add("hydrology.d3_raw_enriched_order", raw_ids == enriched_ids, expected="identical 16,468-ID order", actual={"raw": len(raw_ids), "enriched": len(enriched_ids)})
            validation.add("hydrology.d3_non_stillklinge_count", len(outside) == 16_369, expected=16_369, actual=len(outside))
            validation.add("hydrology.d3_perennial_count", len(perennial) == 15_193, expected=15_193, actual=len(perennial))
        except Exception as error:
            validation.add("hydrology.d3_composition_parse", False, details=repr(error))
    if still_support_path is not None:
        try:
            support_features = json.loads(still_support_path.read_text(encoding="utf-8-sig")).get("features", [])
            properties = [dict(feature.get("properties") or {}) for feature in support_features]
            ids = {str(item.get("minor_id") or "") for item in properties}
            approved_floor = [item for item in properties if not item.get("authority_status")]
            unresolved = [item for item in properties if item.get("authority_status") == "NOT_APPROVED_GEOMETRY_CANDIDATE"]
            unresolved_semantics_ok = all(
                item.get("persistence_authority") == "UNRESOLVED_AFTER_STILLKLINGE_SUPERSESSION"
                and item.get("source_perennial_label_must_not_be_inherited_as_authoritative") is True
                and float(item.get("recommended_interim_ecological_weight_ceiling", 999)) <= 0.35
                and float(item.get("recommended_interim_domestic_weight_ceiling", 999)) <= 0.15
                for item in unresolved
            )
            review_13681 = [item for item in properties if item.get("minor_id") == "D3-MIN-013681"]
            authoritative_local_perennial = [
                item
                for item in properties
                if item.get("persistence_preclassification") == "perennial"
                and not bool(item.get("source_perennial_label_must_not_be_inherited_as_authoritative"))
            ]
            validation.add("hydrology.stillklinge_support_112", len(properties) == 112, expected=112, actual=len(properties))
            validation.add("hydrology.stillklinge_support_21_plus_91", len(approved_floor) == 21 and len(unresolved) == 91, expected={"approved_floor": 21, "unresolved_capped": 91}, actual={"approved_floor": len(approved_floor), "unresolved_capped": len(unresolved)})
            validation.add("hydrology.stillklinge_unresolved_caps_preserved", unresolved_semantics_ok, expected=True, actual=unresolved_semantics_ok)
            validation.add("hydrology.stillklinge_quarantine_absent", not (ids & quarantined), expected=[], actual=sorted(ids & quarantined))
            validation.add(
                "hydrology.combined_perennial_minor_count",
                15_193 + len(authoritative_local_perennial) == 15_193,
                expected=15_193,
                actual=15_193 + len(authoritative_local_perennial),
            )
            validation.add(
                "hydrology.stillklinge_013681_review_flag",
                len(review_13681) == 1 and bool(review_13681[0].get("local_review_detail")),
                expected="one explicitly flagged reach",
                actual=review_13681,
            )
        except Exception as error:
            validation.add("hydrology.stillklinge_support_semantics_parse", False, details=repr(error))

    validate_vector_hydrology_spotcheck(validation, connection, resolved_by_hash)
    validate_raster_spotcheck(validation, connection, resolved_by_hash)
    validate_topology_candidate_spotcheck(validation, connection, resolved_by_hash)

    feeder_regression_ids = (
        "C4BSITE-1A2C4BB86D150B6774",
        "S6-MOOR-GH-0417A87CB94F93B4",
        "S6-MOOR-GH-41B8DACF64F3CAC4",
        "S6-MOOR-GH-A0146E8A6DB35E3F",
        "S6-MOOR-GH-B195C7674A215C35",
        "S6-MOOR-GH-B46F8B7D968A1240",
        "S6-MOOR-GH-E3CABE7120703769",
    )
    placeholders = ",".join("?" for _ in feeder_regression_ids)
    feeder_rows = rows_as_dicts(
        connection,
        "SELECT settlement_id,candidate_valid_cell_count,min_minor_distance_km "
        f"FROM stage6c_site_assessment WHERE settlement_id IN ({placeholders})",
        feeder_regression_ids,
    )
    feeder_failures = [
        row for row in feeder_rows if int(row.get("candidate_valid_cell_count") or 0) <= 0
    ]
    validation.add(
        "hydrology.d3_feeder_gate_regression",
        len(feeder_rows) == 7 and not feeder_failures,
        expected={"rows": 7, "zero_valid_windows": 0},
        actual={"rows": len(feeder_rows), "zero_valid_windows": len(feeder_failures)},
        details=feeder_failures,
    )


def validate_vector_hydrology_spotcheck(
    validation: Validation,
    connection: sqlite3.Connection,
    resolved_by_hash: Mapping[str, Path],
) -> None:
    source_roles = (
        "active_major", "d3_feeder_raw", "d3_feeder_enriched",
        "stillklinge_support", "special_controls", "coastline",
        "lake_permanent_l1", "lake_permanent_legacy", "lake_seasonal",
    )
    missing = [role for role in source_roles if EXPECTED_SOURCES[role]["sha256"] not in resolved_by_hash]
    if missing:
        validation.warn("hydrology.vector_sample_recomputed", {"reason": "unresolved source files", "missing": missing})
        return
    try:
        import shapely  # type: ignore
        from shapely.geometry import shape as shapely_shape  # type: ignore
    except Exception as error:
        validation.warn("hydrology.vector_sample_recomputed", {"reason": "Shapely unavailable", "error": repr(error)})
        return

    ordinary_roles = (
        "active_major", "coastline", "lake_permanent_l1",
        "lake_permanent_legacy", "lake_seasonal",
    )
    geometries = {
        role: geojson_shapes(resolved_by_hash[EXPECTED_SOURCES[role]["sha256"]], shapely_shape)
        for role in ordinary_roles
    }
    d3_raw_payload = json.loads(
        resolved_by_hash[EXPECTED_SOURCES["d3_feeder_raw"]["sha256"]].read_text(encoding="utf-8-sig")
    ).get("features", [])
    d3_enriched_payload = json.loads(
        resolved_by_hash[EXPECTED_SOURCES["d3_feeder_enriched"]["sha256"]].read_text(encoding="utf-8-sig")
    ).get("features", [])
    if len(d3_raw_payload) != len(d3_enriched_payload):
        validation.add("hydrology.vector_sample_recomputed", False, details="D3 raw/enriched count mismatch")
        return
    outside_indices = [
        index
        for index, feature in enumerate(d3_enriched_payload)
        if (feature.get("properties") or {}).get("system") != "Stillklinge"
    ]
    minor_geometries = [
        shapely_shape(d3_raw_payload[index]["geometry"])
        for index in outside_indices
    ]
    minor_geometries.extend(
        geojson_shapes(
            resolved_by_hash[EXPECTED_SOURCES["stillklinge_support"]["sha256"]],
            shapely_shape,
        )
    )
    special_payload = json.loads(
        resolved_by_hash[EXPECTED_SOURCES["special_controls"]["sha256"]].read_text(encoding="utf-8-sig")
    ).get("features", [])
    strict_special_geometries = [
        shapely_shape(feature["geometry"])
        for feature in special_payload
        if (feature.get("properties") or {}).get("feature") in {"highest_tarn", "resurgence"}
    ]
    managed_special_count = sum(
        (feature.get("properties") or {}).get("feature")
        in {"high_lagoon_A", "high_lagoon_B", "lower_lagoon", "inland_outlet_lake"}
        for feature in special_payload
    )
    validation.add(
        "hydrology.exact_minor_runtime_count",
        len(minor_geometries) == 16_481,
        expected=16_481,
        actual=len(minor_geometries),
    )
    validation.add(
        "hydrology.special_partition",
        len(strict_special_geometries) == 2 and managed_special_count == 4 and len(special_payload) == 10,
        expected={"strict_surface": 2, "managed_surface": 4, "other_overlay": 4},
        actual={
            "strict_surface": len(strict_special_geometries),
            "managed_surface": managed_special_count,
            "other_overlay": len(special_payload) - len(strict_special_geometries) - managed_special_count,
        },
    )
    trees = {
        "min_major_distance_km": shapely.STRtree(geometries["active_major"]),
        "min_minor_distance_km": shapely.STRtree(minor_geometries),
        "min_special_water_distance_km": shapely.STRtree(strict_special_geometries),
        "min_coast_distance_km": shapely.STRtree(geometries["coastline"]),
        "min_permanent_lake_distance_km": shapely.STRtree(
            geometries["lake_permanent_l1"] + geometries["lake_permanent_legacy"]
        ),
        "min_seasonal_lake_distance_km": shapely.STRtree(geometries["lake_seasonal"]),
    }
    fields = list(trees)
    rows = rows_as_dicts(
        connection,
        "SELECT settlement_id, owner_haus_id, original_display_x_km, original_display_y_km, "
        + ",".join(fields)
        + " FROM stage6c_site_assessment WHERE analysis_status IN ('READY_2D_CURRENT','READY_2D_CONDITIONAL')",
    )
    by_haus: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for row in rows:
        rank = hashlib.sha256((str(row["settlement_id"]) + "|HYDRO_VECTOR_RECHECK_V1").encode("utf-8")).hexdigest()
        by_haus.setdefault(str(row["owner_haus_id"]), []).append((rank, row))
    sample = [item[1] for haus in sorted(by_haus) for item in sorted(by_haus[haus])[:2]]
    mismatches: list[dict[str, Any]] = []
    for row in sample:
        xs, ys = candidate_grid_centres(float(row["original_display_x_km"]), float(row["original_display_y_km"]))
        points = shapely.points(xs, ys)
        for field, tree in trees.items():
            _, distances = tree.query_nearest(points, return_distance=True, all_matches=False)
            expected = float(min(distances))
            actual = row[field]
            if actual is None or abs(float(actual) - expected) > 1e-8:
                mismatches.append(
                    {"settlement_id": row["settlement_id"], "metric": field, "actual": actual, "expected": expected}
                )
                if len(mismatches) >= 21:
                    break
        if len(mismatches) >= 21:
            break
    validation.add(
        "hydrology.vector_sample_recomputed",
        len(sample) >= 20 and not mismatches,
        expected={"minimum_sample": 20, "mismatches": 0},
        actual={"sample_count": len(sample), "mismatches": len(mismatches)},
        details={"sample_ids": [row["settlement_id"] for row in sample], "mismatches": mismatches[:20]},
    )


def validate_raster_spotcheck(
    validation: Validation,
    connection: sqlite3.Connection,
    resolved_by_hash: Mapping[str, Path],
) -> None:
    roles = ("terrain_100m", "stillklinge_terrain_override", "flood_candidates_100m", "stillklinge_flood_override")
    missing = [role for role in roles if EXPECTED_SOURCES[role]["sha256"] not in resolved_by_hash]
    if missing:
        validation.warn("hydrology.raster_sample_recomputed", {"reason": "unresolved source files", "missing": missing})
        return
    try:
        import numpy as np  # type: ignore
        import rasterio  # type: ignore
        from rasterio.windows import Window  # type: ignore
    except Exception as error:
        validation.warn("hydrology.raster_sample_recomputed", {"reason": "Rasterio/NumPy unavailable", "error": repr(error)})
        return

    candidates = rows_as_dicts(
        connection,
        """
        SELECT settlement_id, original_display_x_km, original_display_y_km,
               terrain_elevation_m, terrain_slope_deg, local_relief_m, flood_exposure_index
        FROM stage6c_site_assessment
        WHERE analysis_status IN ('READY_2D_CURRENT','READY_2D_CONDITIONAL')
          AND candidate_valid_cell_count=100
          AND terrain_elevation_m IS NOT NULL
          AND original_display_x_km BETWEEN 1.0 AND 2199.0
          AND original_display_y_km BETWEEN 1.0 AND 1859.0
        """,
    )
    ranked = sorted(
        candidates,
        key=lambda row: hashlib.sha256((str(row["settlement_id"]) + "|RASTER_RECHECK_V1").encode("utf-8")).hexdigest(),
    )
    sample = ranked[:25]
    mismatches: list[dict[str, Any]] = []
    terrain_path = resolved_by_hash[EXPECTED_SOURCES["terrain_100m"]["sha256"]]
    still_terrain_path = resolved_by_hash[EXPECTED_SOURCES["stillklinge_terrain_override"]["sha256"]]
    flood_path = resolved_by_hash[EXPECTED_SOURCES["flood_candidates_100m"]["sha256"]]
    still_flood_path = resolved_by_hash[EXPECTED_SOURCES["stillklinge_flood_override"]["sha256"]]

    with rasterio.open(terrain_path) as terrain, rasterio.open(still_terrain_path) as still_terrain, rasterio.open(flood_path) as flood, rasterio.open(still_flood_path) as still_flood:
        full_grid_ok = (
            terrain.width == flood.width == 22_000
            and terrain.height == flood.height == 18_600
            and abs(float(terrain.transform.a) - 0.1) <= 1e-12
            and abs(float(terrain.transform.e) - 0.1) <= 1e-12
            and abs(float(terrain.transform.c)) <= 1e-12
            and abs(float(terrain.transform.f)) <= 1e-12
            and tuple(terrain.transform) == tuple(flood.transform)
        )
        local_grid_ok = (
            still_terrain.width == still_flood.width == 1_550
            and still_terrain.height == still_flood.height == 3_900
            and tuple(still_terrain.transform) == tuple(still_flood.transform)
            and abs(float(still_terrain.transform.a) - 0.1) <= 1e-12
            and abs(float(still_terrain.transform.e) - 0.1) <= 1e-12
        )
        validation.add("hydrology.raster_full_grid_alignment", full_grid_ok, expected={"shape": [18_600, 22_000], "resolution_km": 0.1, "origin": [0.0, 0.0]}, actual={"terrain_shape": [terrain.height, terrain.width], "flood_shape": [flood.height, flood.width], "terrain_transform": tuple(terrain.transform), "flood_transform": tuple(flood.transform)})
        validation.add("hydrology.stillklinge_raster_override_alignment", local_grid_ok, expected={"shape": [3_900, 1_550], "resolution_km": 0.1, "terrain_flood_same_transform": True}, actual={"terrain_shape": [still_terrain.height, still_terrain.width], "flood_shape": [still_flood.height, still_flood.width], "terrain_transform": tuple(still_terrain.transform), "flood_transform": tuple(still_flood.transform)})
        still_row0 = int(round(still_terrain.transform.f / 0.1))
        still_col0 = int(round(still_terrain.transform.c / 0.1))

        def overlay(block: Any, local_dataset: Any, row0: int, col0: int, height: int, width: int) -> None:
            ir0 = max(row0, still_row0)
            ic0 = max(col0, still_col0)
            ir1 = min(row0 + height, still_row0 + local_dataset.height)
            ic1 = min(col0 + width, still_col0 + local_dataset.width)
            if ir0 < ir1 and ic0 < ic1:
                block[ir0-row0:ir1-row0, ic0-col0:ic1-col0] = local_dataset.read(
                    1,
                    window=Window(ic0-still_col0, ir0-still_row0, ic1-ic0, ir1-ir0),
                )

        for row in sample:
            x = float(row["original_display_x_km"])
            y = float(row["original_display_y_km"])
            col0 = min(max(math.floor((x - 0.5) / 0.1 + 1e-8), 1), 21_989)
            row0 = min(max(math.floor((y - 0.5) / 0.1 + 1e-8), 1), 18_589)
            terrain_block = terrain.read(1, window=Window(col0-1, row0-1, 12, 12)).astype(np.float64)
            flood_block = flood.read(1, window=Window(col0-1, row0-1, 12, 12)).astype(np.float64)
            overlay(terrain_block, still_terrain, row0-1, col0-1, 12, 12)
            overlay(flood_block, still_flood, row0-1, col0-1, 12, 12)
            gy, gx = np.gradient(terrain_block, 100.0, 100.0)
            slope = np.degrees(np.arctan(np.hypot(gx, gy)))[1:11, 1:11]
            elevation = terrain_block[1:11, 1:11]
            flood_classes = flood_block[1:11, 1:11]
            exposure = np.zeros(flood_classes.shape, dtype=np.float64)
            exposure[flood_classes == 1] = 0.70
            exposure[flood_classes == 2] = 0.90
            exposure[flood_classes == 3] = 0.60
            exposure[flood_classes == 4] = 0.25
            expected_values = {
                "terrain_elevation_m": float(np.median(elevation)),
                "terrain_slope_deg": float(np.median(slope)),
                "local_relief_m": float(np.quantile(elevation, 0.90) - np.quantile(elevation, 0.10)),
                "flood_exposure_index": float(np.mean(exposure)),
            }
            for field, expected in expected_values.items():
                actual = row[field]
                if actual is None or abs(float(actual) - expected) > 2e-5:
                    mismatches.append(
                        {"settlement_id": row["settlement_id"], "metric": field, "actual": actual, "expected": expected}
                    )
                    if len(mismatches) >= 21:
                        break
            if len(mismatches) >= 21:
                break
    validation.add(
        "hydrology.raster_sample_recomputed",
        len(sample) >= 20 and not mismatches,
        expected={"minimum_sample": 20, "mismatches": 0},
        actual={"sample_count": len(sample), "mismatches": len(mismatches)},
        details={"sample_ids": [row["settlement_id"] for row in sample], "mismatches": mismatches[:20]},
    )


def validate_topology_candidate_spotcheck(
    validation: Validation,
    connection: sqlite3.Connection,
    resolved_by_hash: Mapping[str, Path],
) -> None:
    roles = ("exact_surface_registry", "fragment_barony_assignment", "obsidian_sea_mask")
    missing = [role for role in roles if EXPECTED_SOURCES[role]["sha256"] not in resolved_by_hash]
    if missing:
        validation.warn("topology.candidate_sample_recomputed", {"reason": "unresolved source files", "missing": missing})
        return
    try:
        import numpy as np  # type: ignore
        import rasterio  # type: ignore
        import shapely  # type: ignore
        from rasterio.windows import Window  # type: ignore
        from stage6c_source_stack import ExactSurfaceLookup  # type: ignore
    except Exception as error:
        validation.warn("topology.candidate_sample_recomputed", {"reason": "spatial dependencies unavailable", "error": repr(error)})
        return

    water_dependent_forms = {
        "FISHERY_OR_LAKESHORE_SETTLEMENT",
        "FREIGHT_TRANSFER_OR_LANDING_SETTLEMENT",
        "RIVER_TERRACE_OR_WATERSIDE_SETTLEMENT",
        "SURFACE_LAGOON_SETTLEMENT",
        "WETLAND_EDGE_SETTLEMENT",
        "WETLAND_STILT_OR_CHANNEL_SETTLEMENT",
    }
    placeholders = ",".join("?" for _ in water_dependent_forms)
    candidates = rows_as_dicts(
        connection,
        f"""
        SELECT a.settlement_id, a.owner_haus_id, a.original_display_x_km,
               a.original_display_y_km, a.candidate_valid_cell_count,
               a.effective_vertical_domain, s.barony_id,
               s.stage6b_realised_settlement_form
        FROM stage6c_site_assessment a JOIN settlement s USING(settlement_id)
        WHERE a.analysis_status IN ('READY_2D_CURRENT','READY_2D_CONDITIONAL')
          AND s.barony_id IS NOT NULL
          AND a.effective_vertical_domain<>'WETLAND_INTERIOR'
          AND s.stage6b_realised_settlement_form NOT IN ({placeholders})
        """,
        tuple(sorted(water_dependent_forms)),
    )
    by_haus: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for row in candidates:
        rank = hashlib.sha256((str(row["settlement_id"]) + "|TOPOLOGY_RECHECK_V1").encode("utf-8")).hexdigest()
        by_haus.setdefault(str(row["owner_haus_id"]), []).append((rank, row))
    sample = [item[1] for haus in sorted(by_haus) for item in sorted(by_haus[haus])[:2]]
    mismatches: list[dict[str, Any]] = []
    geometry_cache: dict[int, Any] = {}
    carrier_cache: dict[tuple[int, int], list[tuple[int, Any | None, float]]] = {}

    registry_path = resolved_by_hash[EXPECTED_SOURCES["exact_surface_registry"]["sha256"]]
    assignment_path = resolved_by_hash[EXPECTED_SOURCES["fragment_barony_assignment"]["sha256"]]
    sea_path = resolved_by_hash[EXPECTED_SOURCES["obsidian_sea_mask"]["sha256"]]
    with ExactSurfaceLookup(registry_path, assignment_path) as lookup, rasterio.open(sea_path) as sea:
        for row in sample:
            x = float(row["original_display_x_km"])
            y = float(row["original_display_y_km"])
            col0 = min(max(math.floor((x - 0.5) / 0.1 + 1e-8), 0), 21_990)
            row0 = min(max(math.floor((y - 0.5) / 0.1 + 1e-8), 0), 18_590)
            sea_values = sea.read(1, window=Window(col0, row0, 10, 10)).reshape(-1)
            classified: list[int] = []
            index = 0
            for grid_row in range(row0, row0 + 10):
                for grid_col in range(col0, col0 + 10):
                    carrier = (grid_row // 10, grid_col // 10)
                    if carrier not in carrier_cache:
                        records: list[tuple[int, Any | None, float]] = []
                        for record in lookup.fragment_records_for_carrier(*carrier):
                            fragment_id = int(record["fragment_id"])
                            raw = lookup.boundary_wkb(fragment_id)
                            geometry = None
                            if raw is not None:
                                geometry = geometry_cache.setdefault(fragment_id, shapely.from_wkb(raw))
                            records.append((int(record["barony_id"]), geometry, float(record["area_km2"])))
                        carrier_cache[carrier] = records
                    records = carrier_cache[carrier]
                    explicit = [(barony, geometry) for barony, geometry, _ in records if geometry is not None]
                    if explicit:
                        assigned = -1
                        point = shapely.Point(grid_col * 0.1 + 0.05, grid_row * 0.1 + 0.05)
                        for barony, geometry in explicit:
                            if shapely.covers(geometry, point):
                                assigned = barony
                    elif records:
                        assigned = max(records, key=lambda item: item[2])[0]
                    else:
                        assigned = -1
                    classified.append(assigned)
                    index += 1
            barony = int(row["barony_id"])
            expected_valid = int(sum(
                assigned == barony and int(sea_values[position]) == 0
                for position, assigned in enumerate(classified)
            ))
            actual = int(row["candidate_valid_cell_count"])
            if actual != expected_valid:
                mismatches.append(
                    {"settlement_id": row["settlement_id"], "actual": actual, "expected": expected_valid}
                )
                if len(mismatches) >= 21:
                    break
    validation.add(
        "topology.candidate_sample_recomputed",
        len(sample) >= 20 and not mismatches,
        expected={"minimum_sample": 20, "mismatches": 0},
        actual={"sample_count": len(sample), "mismatches": len(mismatches)},
        details={"sample_ids": [row["settlement_id"] for row in sample], "mismatches": mismatches[:20]},
    )


def geometry_blob_digest(connection: sqlite3.Connection, table: str, id_column: str, geom_column: str) -> dict[str, Any]:
    digest = hashlib.sha256()
    count = 0
    for row in connection.execute(
        f'SELECT "{id_column}", "{geom_column}" FROM "{table}" ORDER BY "{id_column}"'
    ):
        digest.update(str(row[0]).encode("utf-8"))
        digest.update(b"\0")
        digest.update(bytes(row[1]) if row[1] is not None else b"<NULL>")
        digest.update(b"\n")
        count += 1
    return {"row_count": count, "sha256": digest.hexdigest()}


def validate_gpkg(
    validation: Validation,
    gpkg_path: Path,
    db_connection: sqlite3.Connection,
    parent_gpkg: Path | None,
) -> None:
    connection = connect_readonly(gpkg_path)
    try:
        quick = scalar(connection, "PRAGMA quick_check")
        validation.add("gpkg.quick_check", quick == "ok", expected="ok", actual=quick)
        inventory = object_inventory(connection)
        required_gpkg_tables = {"gpkg_contents", "gpkg_geometry_columns", "settlement", "stage6c_site_assessment"}
        missing = sorted(required_gpkg_tables - set(inventory))
        validation.add("gpkg.required_tables", not missing, expected=sorted(required_gpkg_tables), actual={"missing": missing})
        if missing:
            return

        assessment_registration = connection.execute(
            "SELECT data_type FROM gpkg_contents WHERE table_name='stage6c_site_assessment'"
        ).fetchone()
        validation.add(
            "gpkg.assessment_registered_attributes",
            assessment_registration is not None and assessment_registration[0] == "attributes",
            expected="attributes",
            actual=None if assessment_registration is None else assessment_registration[0],
        )
        assessment_geometry = scalar(
            connection,
            "SELECT COUNT(*) FROM gpkg_geometry_columns WHERE table_name='stage6c_site_assessment'",
        )
        validation.add("gpkg.assessment_has_no_geometry", assessment_geometry == 0, expected=0, actual=assessment_geometry)

        new_stage6c_geometry = scalar(
            connection,
            "SELECT COUNT(*) FROM gpkg_geometry_columns WHERE LOWER(table_name) LIKE 'stage6c%'",
        )
        validation.add("gpkg.no_new_stage6c_geometry", new_stage6c_geometry == 0, expected=0, actual=new_stage6c_geometry)

        settlement_geometry = connection.execute(
            "SELECT column_name, geometry_type_name, srs_id FROM gpkg_geometry_columns WHERE table_name='settlement'"
        ).fetchone()
        settlement_geometry_ok = settlement_geometry is not None and str(settlement_geometry[1]).upper() == "POINT"
        validation.add(
            "gpkg.settlement_point_registration",
            settlement_geometry_ok,
            expected={"geometry_type": "POINT"},
            actual=None if settlement_geometry is None else dict(zip(("column", "geometry_type", "srs_id"), settlement_geometry)),
        )
        gpkg_settlement_count = scalar(connection, "SELECT COUNT(*) FROM settlement")
        gpkg_assessment_count = scalar(connection, "SELECT COUNT(*) FROM stage6c_site_assessment")
        validation.add("gpkg.settlement_count", gpkg_settlement_count == EXPECTED_REGISTRY_COUNT, expected=EXPECTED_REGISTRY_COUNT, actual=gpkg_settlement_count)
        validation.add("gpkg.assessment_count", gpkg_assessment_count == EXPECTED_REGISTRY_COUNT, expected=EXPECTED_REGISTRY_COUNT, actual=gpkg_assessment_count)

        db_assessment_columns = table_columns(db_connection, "stage6c_site_assessment")
        gpkg_assessment_columns = table_columns(connection, "stage6c_site_assessment")
        missing_attributes = sorted(set(db_assessment_columns) - set(gpkg_assessment_columns))
        validation.add("gpkg.assessment_attribute_columns", not missing_attributes, expected="all DB assessment columns", actual={"missing": missing_attributes})
        if not missing_attributes:
            db_digest = canonical_table_digest(db_connection, "stage6c_site_assessment", db_assessment_columns)
            gpkg_digest = canonical_table_digest(connection, "stage6c_site_assessment", db_assessment_columns)
            validation.add("gpkg.assessment_attribute_digest", db_digest["sha256"] == gpkg_digest["sha256"], expected=db_digest, actual=gpkg_digest)

        if settlement_geometry_ok:
            geom_column = settlement_geometry[0]
            settlement_columns = set(table_columns(connection, "settlement"))
            id_column = "settlement_id" if "settlement_id" in settlement_columns else None
            if id_column:
                geometry_digest = geometry_blob_digest(connection, "settlement", id_column, geom_column)
                validation.table_digests["gpkg_settlement_geometry"] = geometry_digest

                db_coords = {
                    row[0]: (float(row[1]), float(row[2]))
                    for row in db_connection.execute(
                        "SELECT settlement_id, display_x_km, display_y_km FROM settlement"
                    )
                }
                decode_failures: list[str] = []
                coordinate_mismatches: list[dict[str, Any]] = []
                for row in connection.execute(
                    f'SELECT "{id_column}", "{geom_column}" FROM settlement'
                ):
                    site_id = row[0]
                    point = decode_gpkg_point(row[1])
                    expected = db_coords.get(site_id)
                    if point is None:
                        decode_failures.append(site_id)
                    elif expected is None or abs(point[0] - expected[0]) > 1e-8 or abs(point[1] - expected[1]) > 1e-8:
                        coordinate_mismatches.append({"settlement_id": site_id, "geometry": point, "database": expected})
                validation.add("gpkg.point_geometry_decodable", not decode_failures, expected=0, actual=len(decode_failures), details=decode_failures[:20])
                validation.add("gpkg.point_coordinates_match_registry", not coordinate_mismatches, expected=0, actual=len(coordinate_mismatches), details=coordinate_mismatches[:20])

                if parent_gpkg is not None and parent_gpkg.exists():
                    parent = connect_readonly(parent_gpkg)
                    try:
                        parent_geometry_row = parent.execute(
                            "SELECT column_name FROM gpkg_geometry_columns WHERE table_name='settlement'"
                        ).fetchone()
                        parent_digest = None
                        if parent_geometry_row is not None:
                            parent_digest = geometry_blob_digest(parent, "settlement", "settlement_id", parent_geometry_row[0])
                        validation.add(
                            "gpkg.settlement_geometry_preserved_from_parent",
                            parent_digest == geometry_digest,
                            expected=parent_digest,
                            actual=geometry_digest,
                            details=str(parent_gpkg),
                        )
                    finally:
                        parent.close()
                else:
                    validation.warn("gpkg.parent_not_available", "Parent GPKG was unavailable; registry coordinates and geometry digest were still validated.")
    finally:
        connection.close()


def compare_reference_database(validation: Validation, reference_path: Path) -> None:
    reference = connect_readonly(reference_path)
    try:
        reference_inventory = object_inventory(reference)
        for table, digest in validation.table_digests.items():
            if table.startswith("gpkg_"):
                continue
            if table not in reference_inventory:
                validation.add(f"determinism.reference_object.{table}", False, expected="present", actual="missing")
                continue
            reference_digest = canonical_table_digest(reference, table, digest["columns"])
            validation.add(
                f"determinism.digest.{table}",
                reference_digest["sha256"] == digest["sha256"],
                expected=reference_digest,
                actual=digest,
            )
    finally:
        reference.close()


def render_text_report(report: Mapping[str, Any]) -> str:
    lines = [
        "DIADEM STAGE 6C INDEPENDENT VALIDATION",
        f"Overall status: {report['overall_status']}",
        f"Checks: {report['summary']['pass']} PASS / {report['summary']['warn']} WARN / {report['summary']['fail']} FAIL",
        f"Ready for handoff: {report['stop_criteria']['ready_for_handoff']}",
        "",
        "Assumptions:",
    ]
    lines.extend(f"- {item}" for item in report.get("assumptions", []))
    lines.append("")
    for check in report["checks"]:
        lines.append(f"[{check['status']}] {check['check_id']}")
        if check["status"] != "PASS":
            if check.get("expected") is not None:
                lines.append(f"  expected: {json.dumps(check['expected'], ensure_ascii=False, default=str)}")
            if check.get("actual") is not None:
                lines.append(f"  actual:   {json.dumps(check['actual'], ensure_ascii=False, default=str)}")
            if check.get("details") is not None:
                lines.append(f"  details:  {json.dumps(check['details'], ensure_ascii=False, default=str)}")
    lines.extend(["", "Canonical table digests:"])
    for table, digest in report.get("table_digests", {}).items():
        lines.append(f"- {table}: {digest['sha256']} ({digest['row_count']} rows)")
    lines.extend(["", "Stop criteria:"])
    for key, value in report.get("stop_criteria", {}).items():
        lines.append(f"- {key}: {value}")
    selection = report.get("review_selection", {})
    if selection:
        lines.extend(
            [
                "",
                "Deterministic review selection:",
                f"- combined stratified sample: {selection['combined_sample']['count']}",
                f"- priority review: {selection['priority_review']['count']}",
                f"- automatic outliers: {selection['automatic_outliers']['count']}",
                f"- hard/high exception queue: {selection['review_exceptions']['queue_count']}",
                f"- broad review-exceptions view: {selection['review_exceptions']['view_count']}",
            ]
        )
    return "\n".join(lines) + "\n"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path, help="Stage 6C SQLite database")
    parser.add_argument("--gpkg", required=True, type=Path, help="Stage 6C GeoPackage")
    parser.add_argument("--source-root", type=Path, help="Optional root used to resolve source-manifest paths")
    parser.add_argument("--manifest", type=Path, help="Optional source/release manifest JSON; inferred from DB directory when omitted")
    parser.add_argument("--parent-gpkg", type=Path, help="Optional Stage 6B GeoPackage for byte-exact geometry comparison")
    parser.add_argument("--reference-db", type=Path, help="Optional independently rebuilt Stage 6C DB for deterministic digest comparison")
    parser.add_argument("--json-report", type=Path, help="Output JSON report")
    parser.add_argument("--text-report", type=Path, help="Output text report")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    db_path = args.db.resolve()
    gpkg_path = args.gpkg.resolve()
    if not db_path.exists() or not gpkg_path.exists():
        missing = [str(path) for path in (db_path, gpkg_path) if not path.exists()]
        print("Missing required input: " + ", ".join(missing), file=sys.stderr)
        return 2

    manifest_path = args.manifest.resolve() if args.manifest else discover_manifest(db_path)
    source_root = args.source_root.resolve() if args.source_root else None

    inferred_parent = source_path("stage6b_province_gpkg")
    parent_gpkg = args.parent_gpkg.resolve() if args.parent_gpkg else (inferred_parent if inferred_parent.exists() else None)

    validation = Validation()
    validation.assumptions.extend(
        [
            "Stage 6C is additive and preserves all 31,271 Stage 6B settlement identities and original display coordinates.",
            "The 100 m layer is an analysis surface; recorded anchors are not silently promoted to 100 m-precise settlement locations.",
            "stage6c_site_assessment is an attributes table in the GeoPackage, not a new geometry layer.",
            "Container byte identity is not required; deterministic evidence uses canonical sorted table digests.",
            "Specialist 3D geometry remains a valid deferral rather than a Stage 6C failure.",
        ]
    )

    db_connection: sqlite3.Connection | None = None
    try:
        db_connection = validate_database(validation, db_path, source_root, manifest_path)
        validate_gpkg(validation, gpkg_path, db_connection, parent_gpkg)
        if args.reference_db:
            compare_reference_database(validation, args.reference_db.resolve())
        else:
            validation.warn(
                "determinism.reference_db_not_supplied",
                "Canonical digests were emitted. Pass --reference-db from an independent rebuild for direct deterministic equality testing.",
            )
    except Exception as error:
        validation.add("validator.unhandled_exception", False, details=repr(error))
    finally:
        if db_connection is not None:
            db_connection.close()

    counts = Counter(check["status"] for check in validation.checks)
    failure_ids = {check["check_id"] for check in validation.failures}

    def prefix_clear(*prefixes: str) -> bool:
        return not any(any(check_id.startswith(prefix) for prefix in prefixes) for check_id in failure_ids)

    direct_source_hashes = sum(
        check["status"] == "PASS" and check["check_id"].startswith("source.file_hash.")
        for check in validation.checks
    )
    deterministic_checks = [
        check for check in validation.checks if check["check_id"].startswith("determinism.digest.")
    ]
    check_status = {check["check_id"]: check["status"] for check in validation.checks}
    exception_severity = (
        validation.review_selection.get("review_exceptions", {}).get("by_severity", {})
        if validation.review_selection else {}
    )
    hard_exceptions = int(exception_severity.get("HARD", 0) or 0)
    stop_criteria = {
        "all_hard_checks_pass": not validation.failures,
        "source_currentness_pass": prefix_clear("source.") and direct_source_hashes >= len(EXPECTED_SOURCES),
        "hydrology_consistency_pass": (
            prefix_clear("hydrology.", "metrics.derived_indices_reconcile")
            and check_status.get("hydrology.vector_sample_recomputed") == "PASS"
            and check_status.get("hydrology.raster_sample_recomputed") == "PASS"
        ),
        "topology_candidate_recheck_pass": (
            prefix_clear("topology.")
            and check_status.get("topology.candidate_sample_recomputed") == "PASS"
        ),
        "canon_guards_pass": prefix_clear("canon."),
        "coverage_and_scoring_pass": prefix_clear("coverage.", "assessment.", "profiles.", "components.", "scores.", "candidate.", "coordinates."),
        "gpkg_geometry_and_attributes_pass": prefix_clear("gpkg."),
        "no_open_hard_spatial_exception": hard_exceptions == 0,
        "deterministic_rebuild_compared": bool(deterministic_checks) and all(check["status"] == "PASS" for check in deterministic_checks),
    }
    stop_criteria["ready_for_handoff"] = all(stop_criteria.values())
    report = {
        "schema": "diadem-stage6c-independent-validation-1.0",
        "overall_status": "PASS" if not validation.failures else "FAIL",
        "inputs": {
            "db": str(db_path),
            "gpkg": str(gpkg_path),
            "source_root": None if source_root is None else str(source_root),
            "manifest": None if manifest_path is None else str(manifest_path),
            "parent_gpkg": None if parent_gpkg is None else str(parent_gpkg),
            "reference_db": None if args.reference_db is None else str(args.reference_db.resolve()),
        },
        "summary": {
            "pass": counts.get("PASS", 0),
            "warn": counts.get("WARN", 0),
            "fail": counts.get("FAIL", 0),
        },
        "assumptions": validation.assumptions,
        "checks": validation.checks,
        "table_digests": validation.table_digests,
        "review_selection": validation.review_selection,
        "stop_criteria": stop_criteria,
    }

    json_report = args.json_report or db_path.with_suffix(".stage6c_validation.json")
    text_report = args.text_report or db_path.with_suffix(".stage6c_validation.txt")
    json_report.parent.mkdir(parents=True, exist_ok=True)
    text_report.parent.mkdir(parents=True, exist_ok=True)
    json_report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    text_report.write_text(render_text_report(report), encoding="utf-8")

    print(f"{report['overall_status']}: {counts.get('PASS',0)} passed, {counts.get('WARN',0)} warnings, {counts.get('FAIL',0)} failed")
    print(f"JSON: {json_report}")
    print(f"Text: {text_report}")
    return 0 if report["overall_status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
