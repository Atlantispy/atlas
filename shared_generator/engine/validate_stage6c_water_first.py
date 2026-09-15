#!/usr/bin/env python3
"""Read-only validator for the Stage 6C adaptive water-first refinement.

The evidence database and any selectively merged Stage 6C database are opened
immutable/read-only.  Only JSON and text reports are written.  The validator
rebuilds the seven approved corridor classes from the pinned source geometries,
clips them to the exact surface, and independently derives the affected 1 km
settlement windows from 10 m sample centres.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from stage6c_source_stack import (  # noqa: E402
    EXACT_SURFACE_REGISTRY,
    H22_ACTIVE_L1_LAKES,
    H22_ACTIVE_LEGACY_C1_LAKES,
    H22_ACTIVE_LEGACY_CONNECTORS,
    SOURCE_SPECS,
    STILLKLINGE_QUARANTINED_D3_IDS,
    V42_ACTIVE_MAJOR,
    V42_ACTIVE_MINOR,
    V42_ACTIVE_SPECIAL,
    gpkg_wkb,
    read_geojson_geometries,
    sha256_file,
    verify_sources,
)


EXPECTED_SETTLEMENTS = 31_271
EXPECTED_STATUS_COUNTS = {
    "READY_2D_CURRENT": 29_808,
    "READY_2D_CONDITIONAL": 176,
    "DEFERRED_SPECIALIST_3D": 113,
    "NOT_APPLICABLE_NONSETTLEMENT": 1_172,
    "INACTIVE": 2,
}

# Widths are processing-corridor half-widths/radii, not channel widths.
CLASS_RULES: Mapping[str, Mapping[str, Any]] = {
    "TITAN_MAJOR": {"bit": 1, "width_m": 400.0, "count": 1},
    "OTHER_MAJOR": {"bit": 2, "width_m": 200.0, "count": 29},
    "TIER2_REGIONAL": {"bit": 4, "width_m": 100.0, "count": 907},
    "TIER1_STREAM": {"bit": 8, "width_m": 50.0, "count": 2_270},
    "LAKE_SHORE": {"bit": 16, "width_m": 100.0, "count": 497},
    "SPECIAL_SHORE": {"bit": 32, "width_m": 100.0, "count": 7},
    "AUXILIARY": {"bit": 64, "width_m": 50.0, "count": 14},
}

SOURCE_KEYS_REQUIRED = {
    "v42_active_major",
    "v42_active_minor",
    "v42_active_special",
    "h22_active_l1_lakes",
    "h22_active_legacy_c1_lakes",
    "h22_active_legacy_connectors",
    "exact_surface_registry",
    "fragment_barony_id",
    "terrain_d31_100m",
    "stillklinge_terrain_100m",
}

TABLE_ALIASES = {
    "source_lineage": ("source_lineage", "stage6c_adaptive_water_manifest", "stage6c_water_refinement_manifest"),
    "corridor_class": ("corridor_class", "stage6c_adaptive_water_corridor_class"),
    "corridor_union": ("corridor_union", "stage6c_adaptive_water_corridor_union"),
    "tile_registry": ("tile_registry", "stage6c_adaptive_water_tile_registry"),
    "tile_rle": ("tile_rle_evidence", "stage6c_adaptive_water_tile_rle_evidence"),
    "affected": ("affected_settlement", "stage6c_adaptive_water_affected", "stage6c_water_refinement_input"),
    "site_evidence": ("site_evidence", "stage6c_adaptive_water_evidence"),
    "merge_delta": ("stage6c_adaptive_water_delta", "water_refinement_delta", "merge_delta"),
}

COL_ALIASES = {
    "class": ("corridor_class", "class_code", "corridor_class_code", "class_name"),
    "bit": ("class_bit", "corridor_class_bit", "bit_value"),
    "width": ("half_width_m", "radius_m", "corridor_half_width_m", "buffer_m", "width_m"),
    "count": ("feature_count", "source_feature_count", "expected_feature_count"),
    "source_key": ("source_key", "source_role", "source_name", "source_id"),
    "sha256": ("sha256", "source_sha256", "expected_sha256", "input_sha256"),
    "settlement_id": ("settlement_id", "site_id"),
    "affected": ("affected", "is_affected", "refinement_affected", "window_intersects_corridor"),
    "x": ("original_display_x_km", "official_x_km", "display_x_km", "source_x_km"),
    "y": ("original_display_y_km", "official_y_km", "display_y_km", "source_y_km"),
    "reason": ("reason_code", "eligibility_basis", "activation_reason", "bounded_reason_code"),
    "status": ("status", "refinement_status", "review_status"),
    "class_mask": ("class_mask", "corridor_class_mask", "class_bits"),
    "processing_resolution": ("processing_resolution_m", "sampling_resolution_m", "grid_resolution_m"),
    "parent_resolution": ("terrain_parent_resolution_m", "physical_parent_resolution_m", "source_resolution_m"),
    "elevation_authority": ("elevation_authority", "terrain_elevation_authority", "vertical_authority"),
    "width_authority": ("channel_width_authority", "width_authority", "bankfull_width_authority"),
    "changed_fields": ("changed_fields_json", "changed_columns_json", "field_delta_json"),
    "baseline_fp": ("baseline_fingerprint", "baseline_input_fingerprint", "baseline_row_sha256"),
    "refined_fp": ("refined_fingerprint", "refined_input_fingerprint", "refined_row_sha256"),
    "merge_action": ("merge_action", "action"),
    "metric_mask": ("metric_mask_semantics", "metric_mask_basis"),
}

IMMUTABLE_ASSESSMENT_FIELDS = {
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
    "morphology_class",
    "capacity_metric_kind",
    "access_modes_json",
}

WATER_DISTANCE_FIELDS = {
    "corrected_surface_water_distance_km",
    "corrected_perennial_channel_distance_km",
    "min_major_distance_km",
    "min_minor_distance_km",
    "min_special_water_distance_km",
    "min_permanent_lake_distance_km",
    "min_seasonal_lake_distance_km",
    "min_coast_distance_km",
}

# The exact subset changed is declared per row; this is only the maximum legal
# envelope.  Terrain, topology, ownership, location, capacity-area and access-
# by-land fields are deliberately absent.
ALLOWED_REFINED_FIELDS = WATER_DISTANCE_FIELDS | {
    "hydrology_basis",
    "water_access_index",
    "seasonal_reliability_index",
    "hydrology_support_score",
    "water_access_score",
    "seasonal_reliability_score",
    "capacity_support_score_low",
    "capacity_support_score",
    "capacity_support_score_high",
    "access_support_score_low",
    "access_support_score",
    "access_support_score_high",
    "capacity_band",
    "limiting_factors_json",
    "evidence_confidence_score",
    "score_uncertainty_status",
    "data_basis_code",
    "priority_review",
    "review_status",
    "input_fingerprint",
    "method_version",
}

NUMERIC_WIDTH_FIELDS = re.compile(
    r"(?:^|_)(?:channel|bankfull|active_channel|bed|bank)_width_(?:m|km)$", re.I
)
FORBIDDEN_10M_ELEVATION_FIELDS = re.compile(
    r"(?:exact|authoritative).*(?:10m|10_m).*(?:elev|height)|"
    r"(?:10m|10_m).*(?:exact|authoritative).*(?:elev|height)|"
    r"(?:10m|10_m)_(?:elevation|terrain_elevation|bed_elevation)_m$",
    re.I,
)
FORBIDDEN_AUTHORITY_VALUE = re.compile(
    r"(?:EXACT|AUTHORITATIVE).*(?:10M|10_M).*(?:ELEVATION|HEIGHT)|"
    r"(?:CHANNEL|BANKFULL|BED|BANK)_WIDTH_(?:INFERRED|ESTIMATED|AUTHORITATIVE|EXACT)",
    re.I,
)


class Validation:
    def __init__(self) -> None:
        self.checks: list[dict[str, Any]] = []
        self.assumptions: list[str] = []
        self.digests: dict[str, Any] = {}

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
        return [row for row in self.checks if row["status"] == "FAIL"]


def connect_readonly(path: Path) -> sqlite3.Connection:
    uri = path.resolve().as_uri() + "?mode=ro&immutable=1"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def inventory(connection: sqlite3.Connection) -> dict[str, str]:
    return {
        str(row[0]): str(row[1])
        for row in connection.execute(
            "SELECT name,type FROM sqlite_master WHERE type IN ('table','view')"
        )
    }


def columns(connection: sqlite3.Connection, table: str) -> list[str]:
    return [str(row[1]) for row in connection.execute(f"PRAGMA table_info({quote(table)})")]


def quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def choose(options: Iterable[str], available: Iterable[str]) -> str | None:
    values = set(available)
    return next((name for name in options if name in values), None)


def resolve_table(connection: sqlite3.Connection, role: str, explicit: str | None = None) -> str | None:
    names = inventory(connection)
    if explicit:
        return explicit if explicit in names else None
    return choose(TABLE_ALIASES[role], names)


def scalar(connection: sqlite3.Connection, sql: str, params: Sequence[Any] = ()) -> Any:
    row = connection.execute(sql, params).fetchone()
    return None if row is None else row[0]


def canonical(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if math.isnan(value):
            return "NaN"
        if math.isinf(value):
            return "Infinity" if value > 0 else "-Infinity"
        return format(value, ".17g")
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"sha256": hashlib.sha256(bytes(value)).hexdigest(), "bytes": len(value)}
    return str(value)


def canonical_digest(connection: sqlite3.Connection, table: str, order_by: str | None = None) -> dict[str, Any]:
    cols = columns(connection, table)
    query = f"SELECT {','.join(quote(c) for c in cols)} FROM {quote(table)}"
    if order_by and order_by in cols:
        query += f" ORDER BY {quote(order_by)}"
    else:
        query += " ORDER BY " + ",".join(quote(c) for c in cols)
    digest = hashlib.sha256()
    count = 0
    for row in connection.execute(query):
        payload = json.dumps([canonical(v) for v in row], ensure_ascii=False, separators=(",", ":"))
        digest.update(payload.encode("utf-8"))
        digest.update(b"\n")
        count += 1
    return {"sha256": digest.hexdigest(), "row_count": count, "columns": cols}


def check_sqlite_health(validation: Validation, connection: sqlite3.Connection, prefix: str) -> None:
    quick = scalar(connection, "PRAGMA quick_check")
    validation.add(f"{prefix}.quick_check", quick == "ok", expected="ok", actual=quick)
    integrity = scalar(connection, "PRAGMA integrity_check")
    validation.add(f"{prefix}.integrity_check", integrity == "ok", expected="ok", actual=integrity)


def normalise_class(value: Any) -> str:
    text = re.sub(r"[^A-Z0-9]+", "_", str(value or "").upper()).strip("_")
    aliases = {
        "TITAN": "TITAN_MAJOR",
        "MAJOR_TITAN": "TITAN_MAJOR",
        "OTHER_MAJOR_RIVER": "OTHER_MAJOR",
        "MAJOR_OTHER": "OTHER_MAJOR",
        "TIER_2_REGIONAL": "TIER2_REGIONAL",
        "REGIONAL_TRIBUTARY": "TIER2_REGIONAL",
        "TIER_1_LOCAL": "TIER1_STREAM",
        "LOCAL_STREAM": "TIER1_STREAM",
        "LAKE_SHORELINE": "LAKE_SHORE",
        "SPECIAL_SHORELINE": "SPECIAL_SHORE",
        "AUX": "AUXILIARY",
    }
    return aliases.get(text, text)


def feature_id(properties: Mapping[str, Any], prefix: str, index: int) -> str:
    keys = (
        "route_id",
        "minor_id",
        "lake_entity_id",
        "lake_candidate_id",
        "candidate_id",
        "source_lake_seed_id",
        "lake_id",
        "feature",
        "id",
    )
    value = next((properties.get(key) for key in keys if properties.get(key) not in (None, "")), index)
    if prefix == "AUXILIARY" and "lake_id" in properties:
        value = f"{value}:{properties.get('connection_role','')}:{properties.get('receiver_id','')}:{index}"
    if prefix == "SPECIAL_SHORE" or (prefix == "AUXILIARY" and "feature" in properties):
        value = f"{properties.get('system','')}:{value}:{index}"
    return f"{prefix}:{value}"


def load_expected_features() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    try:
        from shapely import union_all  # type: ignore
        from shapely.geometry import shape  # type: ignore
    except ImportError as error:  # pragma: no cover - environment-specific
        raise RuntimeError("Shapely is required for water-first validation") from error

    expected: list[dict[str, Any]] = []

    def add(path: Path, classifier: Any) -> None:
        for index, (raw, props) in enumerate(
            read_geojson_geometries(path, include_properties=True)
        ):
            geom = shape(raw)
            class_code = classifier(geom, props)
            if class_code is None:
                continue
            expected.append(
                {
                    "feature_key": feature_id(props, class_code, index),
                    "class_code": class_code,
                    "class_bit": CLASS_RULES[class_code]["bit"],
                    "half_width_m": CLASS_RULES[class_code]["width_m"],
                    "geometry": geom,
                    "properties": props,
                    "source_path": str(path),
                    "source_geometry_sha256": hashlib.sha256(
                        json.dumps(raw, sort_keys=True, separators=(",", ":")).encode("utf-8")
                    ).hexdigest(),
                }
            )

    add(V42_ACTIVE_MAJOR, lambda _g, p: "TITAN_MAJOR" if p.get("system") == "Titan" else "OTHER_MAJOR")

    def minor_class(_g: Any, props: Mapping[str, Any]) -> str:
        tier = int(props.get("tier_code", 0))
        if tier == 2:
            return "TIER2_REGIONAL"
        if tier == 1:
            return "TIER1_STREAM"
        raise RuntimeError(f"Unclassified active minor feature: {props.get('minor_id')!r}")

    add(V42_ACTIVE_MINOR, minor_class)
    add(H22_ACTIVE_L1_LAKES, lambda _g, _p: "LAKE_SHORE")
    add(H22_ACTIVE_LEGACY_C1_LAKES, lambda _g, _p: "LAKE_SHORE")

    def special_class(geom: Any, _props: Mapping[str, Any]) -> str:
        return "SPECIAL_SHORE" if "Polygon" in geom.geom_type else "AUXILIARY"

    add(V42_ACTIVE_SPECIAL, special_class)
    add(H22_ACTIVE_LEGACY_CONNECTORS, lambda _g, _p: "AUXILIARY")

    counts = Counter(row["class_code"] for row in expected)
    duplicate_ids = sorted(key for key, count in Counter(row["feature_key"] for row in expected).items() if count > 1)
    summary = {
        "counts": dict(sorted(counts.items())),
        "duplicate_feature_keys": duplicate_ids,
        "total_features": len(expected),
    }
    return expected, summary


def build_expected_corridor(expected: Sequence[Mapping[str, Any]]) -> tuple[Any, dict[str, Any], Any, Any]:
    try:
        from measure_hydroscape_buffer_coverage import build_exact_surface_parts  # type: ignore
        from shapely import union_all  # type: ignore
    except ImportError as error:  # pragma: no cover
        raise RuntimeError("NumPy, Rasterio and Shapely are required for topology validation") from error

    by_class: dict[str, list[Any]] = defaultdict(list)
    for row in expected:
        by_class[str(row["class_code"])].append(row["geometry"])

    class_geometries: dict[str, Any] = {}
    for class_code, geometries in by_class.items():
        source_union = union_all(geometries)
        radius = float(CLASS_RULES[class_code]["width_m"]) / 1000.0
        if class_code in {"LAKE_SHORE", "SPECIAL_SHORE"}:
            source_union = source_union.boundary
        class_geometries[class_code] = source_union.buffer(radius, quad_segs=8)

    raw_corridor = union_all(list(class_geometries.values()))
    implicit_surface, explicit_surface, exact_area, exact_details = build_exact_surface_parts()
    clipped_parts = [
        raw_corridor.intersection(implicit_surface),
        raw_corridor.intersection(explicit_surface),
    ]
    clipped = union_all([part for part in clipped_parts if not part.is_empty])
    details = {
        "unclipped_area_km2": float(raw_corridor.area),
        "clipped_area_km2": float(clipped.area),
        "exact_surface_area_km2": exact_area,
        "exact_surface": exact_details,
        "per_class_unclipped_area_km2": {
            key: float(value.area) for key, value in sorted(class_geometries.items())
        },
    }
    return clipped, details, implicit_surface, explicit_surface


def validate_source_currentness(validation: Validation, connection: sqlite3.Connection) -> None:
    report = verify_sources(SOURCE_KEYS_REQUIRED)
    validation.add(
        "source.current_hashes",
        bool(report["ok"]),
        expected=sorted(SOURCE_KEYS_REQUIRED),
        actual={key: row["actual_sha256"] for key, row in report["results"].items()},
        details=report["failed_keys"],
    )

    table = resolve_table(connection, "source_lineage")
    validation.add("source.lineage_table", table is not None, expected="source lineage table", actual=table)
    if table is None:
        return
    cols = columns(connection, table)
    key_col = choose(COL_ALIASES["source_key"], cols)
    hash_col = choose(COL_ALIASES["sha256"], cols)
    validation.add("source.lineage_columns", key_col is not None and hash_col is not None, expected=["source_key", "sha256"], actual=cols)
    if key_col and hash_col:
        rows = {
            str(row[0]): str(row[1]).lower()
            for row in connection.execute(
                f"SELECT {quote(key_col)},{quote(hash_col)} FROM {quote(table)}"
            )
        }
        missing = sorted(key for key in SOURCE_KEYS_REQUIRED if key not in rows)
        mismatched = {
            key: {"expected": SOURCE_SPECS[key].sha256, "actual": rows.get(key)}
            for key in SOURCE_KEYS_REQUIRED
            if key in rows and rows[key] != SOURCE_SPECS[key].sha256
        }
        validation.add("source.lineage_required", not missing, expected=sorted(SOURCE_KEYS_REQUIRED), actual=sorted(rows), details=missing)
        validation.add("source.lineage_hashes", not mismatched, expected="exact pinned SHA-256", actual=mismatched)
        seasonal_names = {"h22_seasonal_l1_basins", "seasonal_l1_basins", "seasonal_basins"}
        seasonal = sorted(set(rows).intersection(seasonal_names))
        validation.add("source.seasonal_basins_excluded", not seasonal, expected=[], actual=seasonal)


def validate_expected_classification(validation: Validation, expected: Sequence[Mapping[str, Any]], summary: Mapping[str, Any]) -> None:
    expected_counts = {key: int(value["count"]) for key, value in CLASS_RULES.items()}
    validation.add("corridor.source_feature_counts", summary["counts"] == expected_counts, expected=expected_counts, actual=summary["counts"])
    validation.add("corridor.source_feature_ids_unique", not summary["duplicate_feature_keys"], expected=0, actual=len(summary["duplicate_feature_keys"]), details=summary["duplicate_feature_keys"][:20])

    major = [row for row in expected if row["class_code"] in {"TITAN_MAJOR", "OTHER_MAJOR"}]
    minors = [row for row in expected if row["class_code"] in {"TIER2_REGIONAL", "TIER1_STREAM"}]
    validation.add("corridor.titan_by_recorded_system", sum(row["class_code"] == "TITAN_MAJOR" for row in major) == 1, expected=1, actual=sum(row["class_code"] == "TITAN_MAJOR" for row in major))
    bad_tiers = [row["feature_key"] for row in minors if int(row["properties"].get("tier_code", 0)) not in (1, 2)]
    validation.add("corridor.minor_classified_only_by_tier_code", not bad_tiers, expected=[], actual=bad_tiers[:20])

    all_property_keys = {str(key).lower() for row in expected for key in row["properties"]}
    width_properties = sorted(key for key in all_property_keys if NUMERIC_WIDTH_FIELDS.search(key))
    validation.add("authority.no_source_channel_width", not width_properties, expected=[], actual=width_properties)


def validate_corridor_class_table(validation: Validation, connection: sqlite3.Connection, explicit: str | None) -> None:
    table = resolve_table(connection, "corridor_class", explicit)
    validation.add("corridor.class_table", table is not None, expected="corridor_class", actual=table)
    if table is None:
        return
    cols = columns(connection, table)
    class_col = choose(COL_ALIASES["class"], cols)
    bit_col = choose(COL_ALIASES["bit"], cols)
    width_col = choose(COL_ALIASES["width"], cols)
    count_col = choose(COL_ALIASES["count"], cols)
    required = {"class": class_col, "bit": bit_col, "width": width_col, "count": count_col}
    validation.add("corridor.class_columns", all(required.values()), expected=list(required), actual=required)
    if not all(required.values()):
        return
    rows: dict[str, dict[str, Any]] = {}
    duplicates: list[str] = []
    sql = f"SELECT {quote(class_col)},{quote(bit_col)},{quote(width_col)},{quote(count_col)} FROM {quote(table)}"
    for raw_class, bit, width, count in connection.execute(sql):
        class_code = normalise_class(raw_class)
        if class_code in rows:
            duplicates.append(class_code)
        rows[class_code] = {"bit": int(bit), "width_m": float(width), "count": int(count)}
    expected_rows = {
        key: {"bit": int(rule["bit"]), "width_m": float(rule["width_m"]), "count": int(rule["count"])}
        for key, rule in CLASS_RULES.items()
    }
    validation.add("corridor.class_rows_exact", rows == expected_rows and not duplicates, expected=expected_rows, actual=rows, details={"duplicates": duplicates, "extra": sorted(set(rows) - set(expected_rows))})


def database_text_hits(connection: sqlite3.Connection, needles: Iterable[str], limit: int = 50) -> list[dict[str, Any]]:
    wanted = tuple(str(value) for value in needles)
    hits: list[dict[str, Any]] = []
    for table, kind in inventory(connection).items():
        if kind != "table" or table.startswith("sqlite_"):
            continue
        text_cols = [row[1] for row in connection.execute(f"PRAGMA table_info({quote(table)})") if str(row[2]).upper() in {"TEXT", "", "JSON"}]
        for col in text_cols:
            for needle in wanted:
                count = scalar(
                    connection,
                    f"SELECT COUNT(*) FROM {quote(table)} WHERE instr(CAST({quote(str(col))} AS TEXT),?)>0",
                    (needle,),
                )
                if count:
                    hits.append({"table": table, "column": col, "needle": needle, "count": int(count)})
                    if len(hits) >= limit:
                        return hits
    return hits


def validate_quarantine_and_persistence(validation: Validation, connection: sqlite3.Connection) -> None:
    hits = database_text_hits(connection, STILLKLINGE_QUARANTINED_D3_IDS)
    validation.add("source.quarantined_stillklinge_absent", not hits, expected=[], actual=hits)

    unresolved = database_text_hits(connection, ("UNRESOLVED_AFTER_STILLKLINGE_SUPERSESSION",))
    # The source lineage may preserve a class-level note rather than 91 rows.
    validation.add(
        "source.persistence_uncertainty_preserved",
        bool(unresolved),
        expected="explicit unresolved-persistence lineage",
        actual=unresolved,
    )


def blob_to_geometry(blob: Any) -> Any:
    from shapely import from_wkb  # type: ignore

    raw = bytes(blob)
    if raw[:2] == b"GP":
        raw = gpkg_wkb(raw)
    return from_wkb(raw)


def load_corridor_geometry(connection: sqlite3.Connection, explicit: str | None) -> tuple[Any | None, dict[str, Any]]:
    try:
        from shapely import union_all  # type: ignore
    except ImportError as error:  # pragma: no cover
        raise RuntimeError("Shapely is required") from error
    table = resolve_table(connection, "corridor_union", explicit)
    if table is None:
        return None, {"table": None}
    info = list(connection.execute(f"PRAGMA table_info({quote(table)})"))
    candidate_cols = [str(row[1]) for row in info if "BLOB" in str(row[2]).upper() or any(token in str(row[1]).lower() for token in ("wkb", "geom"))]
    errors: list[str] = []
    for col in candidate_cols:
        geometries = []
        for row in connection.execute(f"SELECT {quote(col)} FROM {quote(table)} WHERE {quote(col)} IS NOT NULL"):
            try:
                geometries.append(blob_to_geometry(row[0]))
            except Exception as error:
                errors.append(f"{col}: {error!r}")
        if geometries:
            return union_all(geometries), {"table": table, "geometry_column": col, "row_count": len(geometries), "decode_errors": errors}
    return None, {"table": table, "candidate_columns": candidate_cols, "decode_errors": errors}


def deterministic_topology_samples(expected: Any, actual: Any, implicit: Any, explicit: Any) -> dict[str, Any]:
    from shapely.geometry import box  # type: ignore

    mismatches: list[dict[str, Any]] = []
    minx, miny, maxx, maxy = expected.bounds
    # Fixed lattice samples are reproducible and include boundaries and interior.
    for iy in range(25):
        y = miny + (maxy - miny) * (iy + 0.5) / 25.0
        for ix in range(25):
            x = minx + (maxx - minx) * (ix + 0.5) / 25.0
            expected_hit = bool(expected.covers_xy(x, y)) if hasattr(expected, "covers_xy") else bool(expected.covers(__import__("shapely").Point(x, y)))
            actual_hit = bool(actual.covers_xy(x, y)) if hasattr(actual, "covers_xy") else bool(actual.covers(__import__("shapely").Point(x, y)))
            if expected_hit != actual_hit:
                mismatches.append({"x": x, "y": y, "expected": expected_hit, "actual": actual_hit})

    # Exact-topology area samples: deterministic carrier cells at regular
    # intervals across the corridor bounds, with explicit boundary topology
    # naturally included through the exact clipped expected geometry.
    cell_mismatches: list[dict[str, Any]] = []
    x0, x1 = max(0, int(math.floor(minx))), min(2_200, int(math.ceil(maxx)))
    y0, y1 = max(0, int(math.floor(miny))), min(1_860, int(math.ceil(maxy)))
    span_x = max(1, x1 - x0)
    span_y = max(1, y1 - y0)
    sample_indices = sorted(
        {
            (x0 + (i * 104729) % span_x, y0 + (i * 130363) % span_y)
            for i in range(512)
        }
    )
    for col, row in sample_indices:
        carrier = box(col, row, col + 1, row + 1)
        expected_area = float(expected.intersection(carrier).area)
        actual_area = float(actual.intersection(carrier).area)
        if abs(expected_area - actual_area) > 1e-8:
            cell_mismatches.append({"row": row, "col": col, "expected_area": expected_area, "actual_area": actual_area})

    outside_implicit_explicit = float(actual.difference(implicit).difference(explicit).area)
    return {
        "point_sample_count": 625,
        "point_mismatches": mismatches[:50],
        "carrier_sample_count": len(sample_indices),
        "carrier_area_mismatches": cell_mismatches[:50],
        "outside_exact_surface_area_km2": outside_implicit_explicit,
    }


def validate_corridor_geometry(
    validation: Validation,
    connection: sqlite3.Connection,
    expected: Any,
    expected_details: Mapping[str, Any],
    implicit: Any,
    explicit: Any,
    explicit_table: str | None,
) -> Any | None:
    actual, actual_details = load_corridor_geometry(connection, explicit_table)
    validation.add("topology.corridor_geometry_present", actual is not None, expected="persisted exact-surface-clipped WKB", actual=actual_details)
    if actual is None:
        return None
    expected_area = float(expected.area)
    actual_area = float(actual.area)
    area_delta = abs(expected_area - actual_area)
    symmetric_delta = float(expected.symmetric_difference(actual).area)
    tolerance = max(1e-6, expected_area * 1e-9)
    validation.add("topology.corridor_area_exact", area_delta <= tolerance, expected=expected_area, actual=actual_area, details={"absolute_delta_km2": area_delta, "tolerance_km2": tolerance})
    validation.add("topology.corridor_symmetric_difference", symmetric_delta <= max(1e-5, tolerance * 10), expected=0.0, actual=symmetric_delta)
    validation.add("topology.corridor_valid", bool(actual.is_valid), expected=True, actual=bool(actual.is_valid))

    samples = deterministic_topology_samples(expected, actual, implicit, explicit)
    validation.add("topology.exact_point_samples", not samples["point_mismatches"], expected=0, actual=len(samples["point_mismatches"]), details=samples["point_mismatches"])
    validation.add("topology.exact_carrier_samples", not samples["carrier_area_mismatches"], expected=0, actual=len(samples["carrier_area_mismatches"]), details=samples["carrier_area_mismatches"])
    validation.add("topology.no_corridor_outside_exact_surface", samples["outside_exact_surface_area_km2"] <= 1e-8, expected=0.0, actual=samples["outside_exact_surface_area_km2"])
    validation.digests["expected_corridor"] = {
        "wkb_sha256": hashlib.sha256(bytes(expected.wkb)).hexdigest(),
        **dict(expected_details),
    }
    validation.digests["actual_corridor"] = {
        "wkb_sha256": hashlib.sha256(bytes(actual.wkb)).hexdigest(),
        "area_km2": actual_area,
        **actual_details,
    }
    return actual


def load_sites(connection: sqlite3.Connection) -> tuple[list[dict[str, Any]], str]:
    names = inventory(connection)
    if "stage6c_site_assessment" in names:
        table = "stage6c_site_assessment"
        cols = columns(connection, table)
        id_col = choose(COL_ALIASES["settlement_id"], cols)
        x_col = choose(("original_display_x_km", "display_x_km"), cols)
        y_col = choose(("original_display_y_km", "display_y_km"), cols)
    elif "settlement" in names:
        table = "settlement"
        cols = columns(connection, table)
        id_col = choose(COL_ALIASES["settlement_id"], cols)
        x_col = choose(("display_x_km", "original_display_x_km"), cols)
        y_col = choose(("display_y_km", "original_display_y_km"), cols)
    else:
        raise RuntimeError("Baseline has neither stage6c_site_assessment nor settlement")
    if not id_col or not x_col or not y_col:
        raise RuntimeError(f"Cannot identify site coordinates in {table}: {cols}")
    sql = f"SELECT {quote(id_col)},{quote(x_col)},{quote(y_col)} FROM {quote(table)} ORDER BY {quote(id_col)}"
    return [
        {"settlement_id": str(row[0]), "x": float(row[1]), "y": float(row[2])}
        for row in connection.execute(sql)
    ], table


def source_window_bounds(x: float, y: float) -> tuple[float, float, float, float]:
    col0 = min(max(int(math.floor((x - 0.5) / 0.1 + 1e-8)), 0), 22_000 - 10)
    row0 = min(max(int(math.floor((y - 0.5) / 0.1 + 1e-8)), 0), 18_600 - 10)
    return col0 * 0.1, row0 * 0.1, (col0 + 10) * 0.1, (row0 + 10) * 0.1


def derive_affected_sites(sites: Sequence[Mapping[str, Any]], corridor: Any) -> tuple[set[str], dict[str, int]]:
    import numpy as np  # type: ignore
    import shapely  # type: ignore
    from shapely import STRtree  # type: ignore
    from shapely.geometry import box  # type: ignore

    windows = np.array([box(*source_window_bounds(float(site["x"]), float(site["y"]))) for site in sites], dtype=object)
    candidate_indices = STRtree(windows).query(corridor, predicate="intersects")
    affected: set[str] = set()
    zero_centre_slivers = 0
    for index in sorted(int(value) for value in candidate_indices):
        site = sites[index]
        minx, miny, maxx, maxy = source_window_bounds(float(site["x"]), float(site["y"]))
        xs = minx + (np.arange(100, dtype=np.float64) + 0.5) * 0.01
        ys = miny + (np.arange(100, dtype=np.float64) + 0.5) * 0.01
        xx, yy = np.meshgrid(xs, ys, indexing="xy")
        if bool(np.any(shapely.intersects_xy(corridor, xx.ravel(), yy.ravel()))):
            affected.add(str(site["settlement_id"]))
        else:
            zero_centre_slivers += 1
    return affected, {"window_intersection_candidates": len(candidate_indices), "zero_10m_centre_slivers": zero_centre_slivers}


def actual_affected_rows(connection: sqlite3.Connection, explicit: str | None) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    table = resolve_table(connection, "affected", explicit)
    if table is None:
        return {}, {"table": None}
    cols = columns(connection, table)
    id_col = choose(COL_ALIASES["settlement_id"], cols)
    affected_col = choose(COL_ALIASES["affected"], cols)
    x_col = choose(COL_ALIASES["x"], cols)
    y_col = choose(COL_ALIASES["y"], cols)
    reason_col = choose(COL_ALIASES["reason"], cols)
    if id_col is None:
        return {}, {"table": table, "columns": cols, "error": "missing settlement_id"}
    selected = [id_col] + [name for name in (affected_col, x_col, y_col, reason_col) if name and name != id_col]
    sql = f"SELECT {','.join(quote(name) for name in selected)} FROM {quote(table)}"
    result: dict[str, dict[str, Any]] = {}
    duplicates: list[str] = []
    for row in connection.execute(sql):
        payload = dict(zip(selected, row))
        if affected_col and not bool(payload.get(affected_col)):
            continue
        settlement_id = str(payload[id_col])
        if settlement_id in result:
            duplicates.append(settlement_id)
        result[settlement_id] = payload
    return result, {"table": table, "columns": cols, "duplicates": sorted(set(duplicates))}


def validate_affected_completeness(
    validation: Validation,
    baseline: sqlite3.Connection,
    evidence: sqlite3.Connection,
    corridor: Any,
    explicit_table: str | None,
) -> set[str]:
    sites, source_table = load_sites(baseline)
    validation.add("affected.baseline_coverage", len(sites) == EXPECTED_SETTLEMENTS, expected=EXPECTED_SETTLEMENTS, actual=len(sites), details=source_table)
    expected_ids, derivation = derive_affected_sites(sites, corridor)
    actual_rows, actual_details = actual_affected_rows(evidence, explicit_table)
    actual_ids = set(actual_rows)
    validation.add("affected.table_present", actual_details.get("table") is not None, expected="affected_settlement", actual=actual_details)
    validation.add("affected.primary_key_unique", not actual_details.get("duplicates"), expected=[], actual=actual_details.get("duplicates"))
    missing = sorted(expected_ids - actual_ids)
    extras = sorted(actual_ids - expected_ids)

    # Extras are legal only for explicit, bounded special windows.  The normal
    # class corridor itself remains exact and unexpanded.
    reason_col = choose(COL_ALIASES["reason"], actual_details.get("columns", []))
    unexplained_extras = []
    for settlement_id in extras:
        reason = str(actual_rows[settlement_id].get(reason_col, "") if reason_col else "")
        if not reason or not re.search(r"(?:SPECIAL|BOUNDED|EXPLICIT).*(?:250|500|WINDOW)|(?:250|500).*(?:SPECIAL|BOUNDED|EXPLICIT|WINDOW)", reason, re.I):
            unexplained_extras.append({"settlement_id": settlement_id, "reason": reason})
    validation.add("affected.no_omissions", not missing, expected=0, actual=len(missing), details=missing[:100])
    validation.add("affected.extras_explicit_bounded_only", not unexplained_extras, expected=0, actual=len(unexplained_extras), details=unexplained_extras[:100])

    baseline_by_id = {str(site["settlement_id"]): site for site in sites}
    x_col = choose(COL_ALIASES["x"], actual_details.get("columns", []))
    y_col = choose(COL_ALIASES["y"], actual_details.get("columns", []))
    coordinate_errors = []
    if x_col and y_col:
        for settlement_id, row in actual_rows.items():
            if settlement_id not in baseline_by_id:
                coordinate_errors.append({"settlement_id": settlement_id, "error": "unknown"})
                continue
            baseline_row = baseline_by_id[settlement_id]
            if float(row[x_col]) != float(baseline_row["x"]) or float(row[y_col]) != float(baseline_row["y"]):
                coordinate_errors.append({"settlement_id": settlement_id, "expected": [baseline_row["x"], baseline_row["y"]], "actual": [row[x_col], row[y_col]]})
    else:
        coordinate_errors.append({"error": "affected table lacks immutable coordinate copies"})
    validation.add("affected.official_coordinates_immutable", not coordinate_errors, expected=0, actual=len(coordinate_errors), details=coordinate_errors[:100])

    site_table = resolve_table(evidence, "site_evidence")
    validation.add("affected.site_evidence_table", site_table is not None, expected="site_evidence", actual=site_table)
    if site_table:
        site_cols = columns(evidence, site_table)
        site_id_col = choose(COL_ALIASES["settlement_id"], site_cols)
        if site_id_col:
            evidence_ids = {str(row[0]) for row in evidence.execute(f"SELECT {quote(site_id_col)} FROM {quote(site_table)}")}
            validation.add("affected.site_evidence_pk_parity", evidence_ids == actual_ids, expected=len(actual_ids), actual=len(evidence_ids), details={"missing": sorted(actual_ids - evidence_ids)[:100], "extra": sorted(evidence_ids - actual_ids)[:100]})
        else:
            validation.add("affected.site_evidence_pk_parity", False, expected="settlement_id", actual=site_cols)

    validation.digests["affected_derivation"] = {
        "expected_count": len(expected_ids),
        "actual_count": len(actual_ids),
        "expected_id_sha256": hashlib.sha256(("\n".join(sorted(expected_ids)) + "\n").encode("utf-8")).hexdigest(),
        **derivation,
    }
    return actual_ids


def validate_tile_evidence(validation: Validation, connection: sqlite3.Connection) -> None:
    tile_table = resolve_table(connection, "tile_registry")
    rle_table = resolve_table(connection, "tile_rle")
    validation.add("tiles.registry_present", tile_table is not None, expected="tile_registry", actual=tile_table)
    validation.add("tiles.rle_present", rle_table is not None, expected="tile_rle_evidence", actual=rle_table)
    if tile_table:
        cols = columns(connection, tile_table)
        mask_col = choose(COL_ALIASES["class_mask"], cols)
        processing_col = choose(COL_ALIASES["processing_resolution"], cols)
        validation.add("tiles.class_mask_present", mask_col is not None, expected="class mask", actual=cols)
        if mask_col:
            bad = scalar(connection, f"SELECT COUNT(*) FROM {quote(tile_table)} WHERE {quote(mask_col)} IS NULL OR {quote(mask_col)}<1 OR {quote(mask_col)}>127")
            validation.add("tiles.class_mask_range", int(bad or 0) == 0, expected=0, actual=bad)
        if processing_col:
            values = [row[0] for row in connection.execute(f"SELECT DISTINCT {quote(processing_col)} FROM {quote(tile_table)}")]
            validation.add("tiles.processing_resolution_10m", values == [10] or values == [10.0], expected=[10], actual=values)
    if rle_table:
        count = int(scalar(connection, f"SELECT COUNT(*) FROM {quote(rle_table)}") or 0)
        validation.add("tiles.rle_nonempty", count > 0, expected=">0", actual=count)
        cols = columns(connection, rle_table)
        hash_cols = [col for col in cols if "sha256" in col.lower() or "hash" in col.lower()]
        validation.add("tiles.rle_hash_registered", bool(hash_cols), expected="RLE content hash", actual=hash_cols)
        if hash_cols:
            missing_hashes = sum(int(scalar(connection, f"SELECT COUNT(*) FROM {quote(rle_table)} WHERE {quote(col)} IS NULL OR length(trim(CAST({quote(col)} AS TEXT)))=0") or 0) for col in hash_cols)
            validation.add("tiles.rle_hash_complete", missing_hashes == 0, expected=0, actual=missing_hashes)


def validate_no_false_authority(validation: Validation, connection: sqlite3.Connection) -> None:
    numeric_violations = []
    forbidden_columns = []
    authority_values = []
    processing_values: set[Any] = set()
    parent_values: set[Any] = set()
    elevation_authorities: set[str] = set()
    width_authorities: set[str] = set()

    for table, kind in inventory(connection).items():
        if kind != "table" or table.startswith("sqlite_"):
            continue
        cols = columns(connection, table)
        for col in cols:
            lower = col.lower()
            if NUMERIC_WIDTH_FIELDS.search(lower):
                count = int(scalar(connection, f"SELECT COUNT(*) FROM {quote(table)} WHERE {quote(col)} IS NOT NULL") or 0)
                if count:
                    numeric_violations.append({"table": table, "column": col, "nonnull": count})
            if FORBIDDEN_10M_ELEVATION_FIELDS.search(lower):
                forbidden_columns.append({"table": table, "column": col})
        for role, accumulator in (
            ("processing_resolution", processing_values),
            ("parent_resolution", parent_values),
            ("elevation_authority", elevation_authorities),
            ("width_authority", width_authorities),
        ):
            col = choose(COL_ALIASES[role], cols)
            if col:
                accumulator.update(row[0] for row in connection.execute(f"SELECT DISTINCT {quote(col)} FROM {quote(table)} WHERE {quote(col)} IS NOT NULL"))
        text_cols = [str(row[1]) for row in connection.execute(f"PRAGMA table_info({quote(table)})") if str(row[2]).upper() in {"TEXT", "", "JSON"}]
        for col in text_cols:
            for (value,) in connection.execute(f"SELECT DISTINCT CAST({quote(col)} AS TEXT) FROM {quote(table)} WHERE {quote(col)} IS NOT NULL"):
                if FORBIDDEN_AUTHORITY_VALUE.search(str(value)):
                    authority_values.append({"table": table, "column": col, "value": str(value)[:300]})
                    if len(authority_values) >= 100:
                        break

    validation.add("authority.no_numeric_channel_widths", not numeric_violations, expected=[], actual=numeric_violations)
    validation.add("authority.no_authoritative_10m_elevation_fields", not forbidden_columns, expected=[], actual=forbidden_columns)
    validation.add("authority.no_false_claim_values", not authority_values, expected=[], actual=authority_values)
    validation.add("authority.processing_resolution_declared", any(float(v) == 10.0 for v in processing_values if isinstance(v, (int, float)) or str(v).replace('.', '', 1).isdigit()), expected=10, actual=sorted(map(str, processing_values)))
    validation.add("authority.parent_resolution_declared", any(float(v) == 100.0 for v in parent_values if isinstance(v, (int, float)) or str(v).replace('.', '', 1).isdigit()), expected=100, actual=sorted(map(str, parent_values)))
    allowed_elevation = all(not re.search(r"EXACT|AUTHORITATIVE_10M|10M_AUTHORITATIVE", str(value), re.I) for value in elevation_authorities)
    validation.add("authority.elevation_status_honest", bool(elevation_authorities) and allowed_elevation, expected="100m parent/interpolated decision support; not exact 10m authority", actual=sorted(map(str, elevation_authorities)))
    allowed_width = all(re.search(r"NOT_AVAILABLE|NOT_INFERRED|ABSENT|PROCESSING_CORRIDOR", str(value), re.I) for value in width_authorities)
    validation.add("authority.channel_width_status_honest", bool(width_authorities) and allowed_width, expected="NOT_AVAILABLE_NOT_INFERRED", actual=sorted(map(str, width_authorities)))

    canon_hits = database_text_hits(connection, ("REVIEW_ONLY", "NOT_CANON"))
    validation.add("authority.review_only_status_present", bool(canon_hits), expected="REVIEW_ONLY / NOT_CANON lineage", actual=canon_hits[:20])


def row_map(connection: sqlite3.Connection, table: str, id_col: str, common_cols: Sequence[str]) -> dict[str, tuple[Any, ...]]:
    sql = f"SELECT {','.join(quote(col) for col in common_cols)} FROM {quote(table)} ORDER BY {quote(id_col)}"
    id_index = common_cols.index(id_col)
    return {str(row[id_index]): tuple(canonical(value) for value in row) for row in connection.execute(sql)}


def parse_changed_fields(value: Any) -> set[str]:
    if value is None:
        return set()
    try:
        decoded = json.loads(str(value))
    except json.JSONDecodeError:
        return {item.strip() for item in str(value).split(",") if item.strip()}
    if isinstance(decoded, list):
        return {str(item) for item in decoded}
    if isinstance(decoded, dict):
        return {str(key) for key, state in decoded.items() if state not in (False, None, "UNCHANGED")}
    return set()


def validate_selective_merge(
    validation: Validation,
    baseline: sqlite3.Connection,
    merged: sqlite3.Connection | None,
    affected_ids: set[str],
    refined_table_override: str | None,
    delta_table_override: str | None,
) -> None:
    if merged is None:
        validation.warn("merge.not_supplied", "Evidence-only validation completed; pass --merged-db to test the selective replacement.")
        return
    names = inventory(merged)
    baseline_table = "stage6c_site_assessment"
    refined_table = refined_table_override or (
        "stage6c_site_assessment_water_refined"
        if "stage6c_site_assessment_water_refined" in names
        else "stage6c_site_assessment"
    )
    validation.add("merge.refined_table_present", refined_table in names, expected="stage6c_site_assessment_water_refined", actual=refined_table if refined_table in names else None)
    if baseline_table not in inventory(baseline) or refined_table not in names:
        return
    baseline_cols = columns(baseline, baseline_table)
    refined_cols = columns(merged, refined_table)
    common = [col for col in baseline_cols if col in refined_cols]
    id_col = choose(COL_ALIASES["settlement_id"], common)
    validation.add("merge.common_identity_column", id_col is not None, expected="settlement_id", actual=id_col)
    if id_col is None:
        return
    base_rows = row_map(baseline, baseline_table, id_col, common)
    final_rows = row_map(merged, refined_table, id_col, common)
    validation.add("merge.identity_coverage", set(base_rows) == set(final_rows) and len(final_rows) == EXPECTED_SETTLEMENTS, expected=EXPECTED_SETTLEMENTS, actual=len(final_rows), details={"missing": sorted(set(base_rows) - set(final_rows))[:50], "extra": sorted(set(final_rows) - set(base_rows))[:50]})

    col_index = {col: index for index, col in enumerate(common)}
    immutable = sorted(IMMUTABLE_ASSESSMENT_FIELDS.intersection(common))
    illegal: list[dict[str, Any]] = []
    unaffected_changed: list[str] = []
    actual_changes: dict[str, set[str]] = {}
    for settlement_id in sorted(set(base_rows).intersection(final_rows)):
        changed = {col for col in common if base_rows[settlement_id][col_index[col]] != final_rows[settlement_id][col_index[col]]}
        actual_changes[settlement_id] = changed
        if settlement_id not in affected_ids and changed:
            unaffected_changed.append(settlement_id)
        forbidden = changed - ALLOWED_REFINED_FIELDS
        immutable_changed = changed.intersection(immutable)
        if forbidden or immutable_changed:
            illegal.append({"settlement_id": settlement_id, "forbidden": sorted(forbidden), "immutable": sorted(immutable_changed)})
    validation.add("merge.unaffected_rows_identical", not unaffected_changed, expected=0, actual=len(unaffected_changed), details=unaffected_changed[:100])
    validation.add("merge.changed_fields_allowlisted", not illegal, expected=0, actual=len(illegal), details=illegal[:100])

    status_col = "analysis_status" if "analysis_status" in refined_cols else None
    if status_col:
        status_counts = {str(row[0]): int(row[1]) for row in merged.execute(f"SELECT {quote(status_col)},COUNT(*) FROM {quote(refined_table)} GROUP BY {quote(status_col)}")}
        validation.add("merge.analysis_status_counts_unchanged", status_counts == EXPECTED_STATUS_COUNTS, expected=EXPECTED_STATUS_COUNTS, actual=status_counts)

    missing_distance_cols = sorted(WATER_DISTANCE_FIELDS - set(refined_cols))
    validation.add("merge.eight_distance_fields_present", not missing_distance_cols, expected=sorted(WATER_DISTANCE_FIELDS), actual=sorted(WATER_DISTANCE_FIELDS.intersection(refined_cols)), details=missing_distance_cols)

    delta_table = delta_table_override or resolve_table(merged, "merge_delta")
    validation.add("merge.delta_table_present", delta_table is not None and delta_table in names, expected="stage6c_adaptive_water_delta", actual=delta_table)
    if delta_table and delta_table in names:
        delta_cols = columns(merged, delta_table)
        delta_id = choose(COL_ALIASES["settlement_id"], delta_cols)
        changed_col = choose(COL_ALIASES["changed_fields"], delta_cols)
        action_col = choose(COL_ALIASES["merge_action"], delta_cols)
        mask_col = choose(COL_ALIASES["metric_mask"], delta_cols)
        validation.add("merge.delta_required_columns", all((delta_id, changed_col, action_col, mask_col)), expected=["settlement_id", "changed_fields_json", "merge_action", "metric_mask_semantics"], actual={"id": delta_id, "changed": changed_col, "action": action_col, "mask": mask_col})
        if delta_id:
            delta_ids = {str(row[0]) for row in merged.execute(f"SELECT {quote(delta_id)} FROM {quote(delta_table)}")}
            validation.add("merge.delta_affected_parity", delta_ids == affected_ids, expected=len(affected_ids), actual=len(delta_ids), details={"missing": sorted(affected_ids - delta_ids)[:100], "extra": sorted(delta_ids - affected_ids)[:100]})
        if delta_id and changed_col:
            declared = {str(row[0]): parse_changed_fields(row[1]) for row in merged.execute(f"SELECT {quote(delta_id)},{quote(changed_col)} FROM {quote(delta_table)}")}
            mismatches = [
                {"settlement_id": settlement_id, "declared": sorted(declared.get(settlement_id, set())), "actual": sorted(actual_changes.get(settlement_id, set()))}
                for settlement_id in sorted(affected_ids)
                if declared.get(settlement_id, set()) != actual_changes.get(settlement_id, set())
            ]
            validation.add("merge.declared_fields_match_actual", not mismatches, expected=0, actual=len(mismatches), details=mismatches[:100])
        if action_col:
            actions = [row[0] for row in merged.execute(f"SELECT DISTINCT {quote(action_col)} FROM {quote(delta_table)}")]
            validation.add("merge.action_semantics", actions == ["REPLACE_WATER_METRICS_AND_RESCORE"], expected=["REPLACE_WATER_METRICS_AND_RESCORE"], actual=actions)
        if mask_col:
            masks = [row[0] for row in merged.execute(f"SELECT DISTINCT {quote(mask_col)} FROM {quote(delta_table)}")]
            validation.add("merge.metric_mask_fixed", masks == ["BASELINE_VALID_100M_METRIC_MASK_FIXED"], expected=["BASELINE_VALID_100M_METRIC_MASK_FIXED"], actual=masks)


def gpkg_geometry_digest(path: Path) -> dict[str, Any]:
    connection = connect_readonly(path)
    try:
        rows = list(connection.execute("SELECT table_name,column_name FROM gpkg_geometry_columns ORDER BY table_name"))
        result: dict[str, Any] = {}
        for table, geom_col in rows:
            cols = columns(connection, str(table))
            id_col = choose(COL_ALIASES["settlement_id"], cols) or choose(("barony_id", "county_id", "duchy_id", "fid"), cols)
            if id_col is None:
                continue
            digest = hashlib.sha256()
            count = 0
            for identity, blob in connection.execute(f"SELECT {quote(id_col)},{quote(str(geom_col))} FROM {quote(str(table))} ORDER BY {quote(id_col)}"):
                digest.update(str(identity).encode("utf-8")); digest.update(b"\0")
                digest.update(hashlib.sha256(bytes(blob or b"")).digest()); digest.update(b"\n")
                count += 1
            result[str(table)] = {"id_column": id_col, "geometry_column": str(geom_col), "row_count": count, "sha256": digest.hexdigest()}
        return result
    finally:
        connection.close()


def validate_gpkg_preservation(validation: Validation, baseline_gpkg: Path | None, refined_gpkg: Path | None) -> None:
    if refined_gpkg is None:
        validation.warn("gpkg.refined_not_supplied", "Pass --refined-gpkg to validate attribute registration and geometry preservation.")
        return
    refined = connect_readonly(refined_gpkg)
    try:
        check_sqlite_health(validation, refined, "gpkg.refined")
        registration = {
            str(row[0]): str(row[1])
            for row in refined.execute("SELECT table_name,data_type FROM gpkg_contents")
        }
        assessment_tables = [name for name in registration if "stage6c_site_assessment" in name]
        bad_registration = {name: registration[name] for name in assessment_tables if registration[name] != "attributes"}
        validation.add("gpkg.assessment_registered_attributes", bool(assessment_tables) and not bad_registration, expected="attributes", actual={name: registration[name] for name in assessment_tables})
    finally:
        refined.close()
    if baseline_gpkg is None:
        validation.warn("gpkg.baseline_not_supplied", "Pass --baseline-gpkg for byte-level geometry digest comparison.")
        return
    baseline_digest = gpkg_geometry_digest(baseline_gpkg)
    refined_digest = gpkg_geometry_digest(refined_gpkg)
    validation.add("gpkg.geometry_layers_preserved", baseline_digest == refined_digest, expected=baseline_digest, actual=refined_digest)


def validate_determinism(validation: Validation, evidence: sqlite3.Connection, reference: Path | None) -> None:
    selected = []
    names = inventory(evidence)
    for role in ("source_lineage", "corridor_class", "corridor_union", "tile_registry", "tile_rle", "affected", "site_evidence"):
        table = resolve_table(evidence, role)
        if table and table not in selected:
            selected.append(table)
    current = {table: canonical_digest(evidence, table, choose(COL_ALIASES["settlement_id"], columns(evidence, table))) for table in selected}
    validation.digests["evidence_tables"] = current
    if reference is None:
        validation.warn("determinism.reference_not_supplied", "Canonical table digests emitted; pass --reference-refinement-db for independent rerun equality.")
        return
    other = connect_readonly(reference)
    try:
        other_names = inventory(other)
        mismatches = {}
        for table, digest in current.items():
            if table not in other_names:
                mismatches[table] = {"error": "missing from reference"}
                continue
            comparison = canonical_digest(other, table, choose(COL_ALIASES["settlement_id"], columns(other, table)))
            if digest != comparison:
                mismatches[table] = {"current": digest, "reference": comparison}
        validation.add("determinism.evidence_table_digests", not mismatches, expected="identical canonical digests", actual=mismatches)
    finally:
        other.close()


def validate_manifest_file(validation: Validation, path: Path | None, database_path: Path) -> None:
    if path is None:
        candidates = sorted(database_path.parent.glob("*MANIFEST*.json")) + sorted(database_path.parent.glob("*manifest*.json"))
        path = candidates[0] if candidates else None
    validation.add("release.manifest_present", path is not None and path.is_file(), expected="manifest JSON", actual=None if path is None else str(path))
    if path is None or not path.is_file():
        return
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    text = json.dumps(payload, sort_keys=True)
    bad = [identifier for identifier in STILLKLINGE_QUARANTINED_D3_IDS if identifier in text]
    validation.add("release.manifest_quarantine_absent", not bad, expected=[], actual=bad)
    validation.add("release.manifest_database_hash", sha256_file(database_path) in text, expected=sha256_file(database_path), actual="present" if sha256_file(database_path) in text else "absent")


def render_text(report: Mapping[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "Diadem Stage 6C water-first independent validation",
        f"Overall: {report['overall_status']}",
        f"Checks: {summary['pass']} pass, {summary['warn']} warn, {summary['fail']} fail",
        "",
        "Stop criteria:",
    ]
    for key, value in report["stop_criteria"].items():
        lines.append(f"- {key}: {value}")
    failures = [row for row in report["checks"] if row["status"] != "PASS"]
    if failures:
        lines.extend(["", "Failures and warnings:"])
        for row in failures:
            lines.append(f"- [{row['status']}] {row['check_id']}")
            if row.get("actual") is not None:
                lines.append(f"  actual: {json.dumps(row['actual'], ensure_ascii=False, default=str)}")
            if row.get("details") is not None:
                lines.append(f"  details: {json.dumps(row['details'], ensure_ascii=False, default=str)}")
    return "\n".join(lines) + "\n"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-db", required=True, type=Path, help="Unrefined Stage 6C SQLite database")
    parser.add_argument("--refinement-db", required=True, type=Path, help="Adaptive water evidence SQLite database")
    parser.add_argument("--merged-db", type=Path, help="Optional selectively merged Stage 6C database")
    parser.add_argument("--baseline-gpkg", type=Path)
    parser.add_argument("--refined-gpkg", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--reference-refinement-db", type=Path)
    parser.add_argument("--corridor-class-table")
    parser.add_argument("--corridor-geometry-table")
    parser.add_argument("--affected-table")
    parser.add_argument("--refined-assessment-table")
    parser.add_argument("--delta-table")
    parser.add_argument("--json-report", type=Path)
    parser.add_argument("--text-report", type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    required = [args.baseline_db, args.refinement_db]
    optional = [args.merged_db, args.baseline_gpkg, args.refined_gpkg, args.manifest, args.reference_refinement_db]
    missing = [str(path) for path in required if not path.is_file()]
    supplied_missing = [str(path) for path in optional if path is not None and not path.is_file()]
    if missing or supplied_missing:
        print("Missing input: " + ", ".join(missing + supplied_missing), file=sys.stderr)
        return 2

    validation = Validation()
    validation.assumptions.extend(
        [
            "Corridor widths are half-width/radius processing rules, never inferred physical channel widths.",
            "10 m cells are sparse decision-support samples inherited from the approved 100 m physical parent.",
            "A site is affected when at least one 10 m centre in its fixed baseline 1 km source window intersects the exact-surface-clipped adaptive corridor.",
            "Lake and special-water interiors remain at parent resolution; only 100 m shoreline bands are refined by default.",
            "Evidence-only ADD_EVIDENCE_NO_AUTOMATIC_SCORE_OVERRIDE output is valid as an input product; a merged output must instead declare REPLACE_WATER_METRICS_AND_RESCORE.",
        ]
    )

    baseline = evidence = merged = None
    try:
        baseline = connect_readonly(args.baseline_db)
        evidence = connect_readonly(args.refinement_db)
        merged = connect_readonly(args.merged_db) if args.merged_db else None
        check_sqlite_health(validation, baseline, "baseline")
        check_sqlite_health(validation, evidence, "refinement")
        if merged:
            check_sqlite_health(validation, merged, "merged")

        validate_source_currentness(validation, evidence)
        expected_features, feature_summary = load_expected_features()
        validate_expected_classification(validation, expected_features, feature_summary)
        validate_corridor_class_table(validation, evidence, args.corridor_class_table)
        validate_quarantine_and_persistence(validation, evidence)
        expected_corridor, expected_details, implicit, explicit = build_expected_corridor(expected_features)
        actual_corridor = validate_corridor_geometry(
            validation,
            evidence,
            expected_corridor,
            expected_details,
            implicit,
            explicit,
            args.corridor_geometry_table,
        )
        affected_ids: set[str] = set()
        if actual_corridor is not None:
            affected_ids = validate_affected_completeness(
                validation,
                baseline,
                evidence,
                expected_corridor,
                args.affected_table,
            )
        validate_tile_evidence(validation, evidence)
        validate_no_false_authority(validation, evidence)
        validate_selective_merge(
            validation,
            baseline,
            merged,
            affected_ids,
            args.refined_assessment_table,
            args.delta_table,
        )
        validate_gpkg_preservation(validation, args.baseline_gpkg, args.refined_gpkg)
        validate_determinism(validation, evidence, args.reference_refinement_db)
        validate_manifest_file(validation, args.manifest, args.refinement_db)
    except Exception as error:
        validation.add("validator.unhandled_exception", False, details=repr(error))
    finally:
        for connection in (merged, evidence, baseline):
            if connection is not None:
                connection.close()

    counts = Counter(row["status"] for row in validation.checks)
    failures = {row["check_id"] for row in validation.failures}

    def clear(*prefixes: str) -> bool:
        return not any(any(check.startswith(prefix) for prefix in prefixes) for check in failures)

    stop = {
        "source_currentness": clear("source.", "release."),
        "adaptive_classes_and_widths": clear("corridor."),
        "exact_topology": clear("topology.", "tiles."),
        "affected_site_completeness": clear("affected."),
        "no_false_10m_or_width_authority": clear("authority."),
        "selective_merge_invariants": args.merged_db is not None and clear("merge."),
        "geometry_preservation": args.refined_gpkg is not None and clear("gpkg."),
        "deterministic_rerun_compared": args.reference_refinement_db is not None and clear("determinism."),
    }
    stop["evidence_ready"] = all(stop[key] for key in ("source_currentness", "adaptive_classes_and_widths", "exact_topology", "affected_site_completeness", "no_false_10m_or_width_authority"))
    stop["ready_for_handoff"] = all(stop.values())
    report = {
        "schema": "diadem-stage6c-water-first-independent-validation-1.0",
        "overall_status": "PASS" if not validation.failures else "FAIL",
        "inputs": {
            "baseline_db": str(args.baseline_db.resolve()),
            "refinement_db": str(args.refinement_db.resolve()),
            "merged_db": None if args.merged_db is None else str(args.merged_db.resolve()),
            "baseline_gpkg": None if args.baseline_gpkg is None else str(args.baseline_gpkg.resolve()),
            "refined_gpkg": None if args.refined_gpkg is None else str(args.refined_gpkg.resolve()),
            "manifest": None if args.manifest is None else str(args.manifest.resolve()),
            "reference_refinement_db": None if args.reference_refinement_db is None else str(args.reference_refinement_db.resolve()),
        },
        "summary": {"pass": counts.get("PASS", 0), "warn": counts.get("WARN", 0), "fail": counts.get("FAIL", 0)},
        "assumptions": validation.assumptions,
        "checks": validation.checks,
        "digests": validation.digests,
        "stop_criteria": stop,
    }
    json_path = args.json_report or args.refinement_db.with_suffix(".water_first_validation.json")
    text_path = args.text_report or args.refinement_db.with_suffix(".water_first_validation.txt")
    json_path.parent.mkdir(parents=True, exist_ok=True)
    text_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    text_path.write_text(render_text(report), encoding="utf-8")
    print(f"{report['overall_status']}: {counts.get('pass', 0)} passed, {counts.get('warn', 0)} warnings, {counts.get('fail', 0)} failed")
    print(f"JSON: {json_path}")
    print(f"Text: {text_path}")
    return 0 if report["overall_status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
