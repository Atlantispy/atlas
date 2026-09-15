#!/usr/bin/env python3
"""Validate the staged, location-independent Diadem generator.

This is read-only with respect to source inputs.  It verifies every catalogue
file by size and SHA-256, checks the active engine bindings, rejects historical
absolute source paths, and runs the Stage 6B rule catalogue self-check.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Sequence

import build_stage6c_100m as builder
from phase1_storage_policy import scan_workspace as scan_phase1_storage_policy
import stage6c_rules as rules
import stage6c_source_stack as stack
import stage6c_terrain_authority as terrain_authority
from source_catalogue import (
    generator_root,
    load_catalogue,
    source_path,
    verify_catalogue,
)


STACK_BINDINGS = {
    "terrain_d31_100m": "terrain_d31_100m",
    "obsidian_sea_mask_100m": "obsidian_sea_mask_100m",
    "stillklinge_terrain_100m": "stillklinge_terrain_100m",
    "stillklinge_flood_100m": "stillklinge_flood_100m",
    "moorwandler_core_wetland_100m": "moorwandler_core_wetland_100m",
    "serenakrone_water_100m": "serenakrone_water_100m",
    "h22_flood_candidates_100m": "h22_flood_candidates_100m",
    "h22_active_l1_lakes": "h22_active_l1_lakes",
    "h22_active_legacy_c1_lakes": "h22_active_legacy_c1_lakes",
    "h22_active_legacy_connectors": "h22_active_legacy_connectors",
    "h22_seasonal_l1_basins": "h22_seasonal_l1_basins",
    "h22_ordinary_floodplains": "h22_ordinary_floodplains",
    "h22_moorwandler_transition": "h22_moorwandler_transition",
    "v42_active_major": "v42_active_major",
    "v42_active_major_bed_profiles": "v42_active_major_bed_profiles",
    "v42_active_minor": "v42_active_minor",
    "v42_d3_raw": "v42_d3_raw",
    "v42_d3_enriched": "v42_d3_enriched",
    "v42_active_special": "v42_active_special",
    "v42_stillklinge_repaired_major": "v42_stillklinge_repaired_major",
    "v42_stillklinge_local_112": "v42_stillklinge_local_112",
    "exact_surface_registry": "exact_surface_registry",
    "fragment_barony_id": "fragment_barony_id",
    "stage6b_province_gpkg": "stage6b_province_gpkg",
    "political_haus_v11": "political_haus_v11",
    "political_county_v11": "political_county_v11",
    "political_duchy_v11": "political_duchy_v11",
}

BUILDER_BINDINGS = {
    "stage6b_parent_sqlite": "stage6b_parent_sqlite",
    "stage6b_parent_gpkg": "stage6b_province_gpkg",
    "terrain_100m_sealed_lineage": "terrain_d31_100m",
    "stillklinge_terrain_100m_sealed_lineage": "stillklinge_terrain_100m",
    "obsidian_sea_mask": "obsidian_sea_mask_100m",
    "moorwandler_core_wetland": "moorwandler_core_wetland_100m",
    "serenakrone_water_mask": "serenakrone_water_100m",
    "flood_candidates_100m": "h22_flood_candidates_100m",
    "stillklinge_flood_override": "stillklinge_flood_100m",
    "active_major": "v42_active_major",
    "active_major_bed_profiles": "v42_active_major_bed_profiles",
    "parent_minor_lineage": "v42_active_minor",
    "d3_feeder_raw": "v42_d3_raw",
    "d3_feeder_enriched": "v42_d3_enriched",
    "stillklinge_support": "v42_stillklinge_local_112",
    "stillklinge_repaired_major_evidence": "v42_stillklinge_repaired_major",
    "special_controls": "v42_active_special",
    "coastline": "coastline",
    "lake_permanent_l1": "h22_active_l1_lakes",
    "lake_permanent_legacy": "h22_active_legacy_c1_lakes",
    "lake_seasonal": "h22_seasonal_l1_basins",
    "moorwandler_transition": "h22_moorwandler_transition",
    "exact_surface_registry": "exact_surface_registry",
    "fragment_barony_assignment": "fragment_barony_id",
}

FORBIDDEN_ACTIVE_CODE_MARKERS = (
    "C:\\" + "Users\\" + "LOCAL_USER",
    "C:/" + "Users/" + "LOCAL_USER",
    "parents" + "[2]",
    "referenced-chatgpt-" + "conversation-this-is-untrusted",
    "DGB28" + "_STAGE",
    "One" + "Drive",
)


def _check(condition: bool, name: str, detail: Any = None) -> dict[str, Any]:
    return {"check": name, "ok": bool(condition), "detail": detail}


def _scan_active_code() -> list[dict[str, Any]]:
    engine = Path(__file__).resolve().parent
    findings: list[dict[str, Any]] = []
    excluded_parts = {
        "recovery_snapshots",
        "__pycache__",
        "generator_deps",
        "zarr_deps",
        "bounded_real_terrain_test_2026-08-28",
        "bounded_old_vs_new_same_location_2026-08-28",
        "bounded_zip_vs_zstd_ab_2026-08-28",
        "pilot_output",
    }
    for path in sorted((*engine.rglob("*.py"), *engine.rglob("*.mjs"))):
        relative = path.relative_to(engine)
        if excluded_parts.intersection(relative.parts):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for marker in FORBIDDEN_ACTIVE_CODE_MARKERS:
            if marker in text:
                findings.append({"file": relative.as_posix(), "marker": marker})
    return findings


def validate(*, full_hashes: bool = True) -> dict[str, Any]:
    root = generator_root().resolve()
    catalogue = load_catalogue()
    checks: list[dict[str, Any]] = []
    checks.append(_check(len(catalogue["sources"]) == 32, "catalogue.source_count", len(catalogue["sources"])))
    relative_ok = all(not Path(entry["relative_path"]).is_absolute() for entry in catalogue["sources"].values())
    checks.append(_check(relative_ok, "catalogue.paths_are_relative"))

    if full_hashes:
        source_report = verify_catalogue()
        checks.append(_check(source_report["ok"], "catalogue.all_32_hashes_and_sizes", source_report["failed_keys"]))
    else:
        source_report = verify_catalogue(
            ("stage6b_parent_sqlite", "terrain_d31_100m", "coastline", "v42_manifest", "stillklinge_approval")
        )
        checks.append(_check(source_report["ok"], "catalogue.quick_hash_sample", source_report["failed_keys"]))

    checks.append(_check(set(stack.SOURCE_SPECS) == set(STACK_BINDINGS), "source_stack.key_parity"))
    stack_path_mismatches = {
        key: {"actual": str(stack.SOURCE_SPECS[key].path), "expected": str(source_path(catalogue_key))}
        for key, catalogue_key in STACK_BINDINGS.items()
        if stack.SOURCE_SPECS[key].path.resolve() != source_path(catalogue_key).resolve()
    }
    checks.append(_check(not stack_path_mismatches, "source_stack.catalogue_paths", stack_path_mismatches))
    stack_hash_mismatches = {
        key: {"actual": stack.SOURCE_SPECS[key].sha256, "expected": catalogue["sources"][catalogue_key]["sha256"]}
        for key, catalogue_key in STACK_BINDINGS.items()
        if stack.SOURCE_SPECS[key].sha256 != catalogue["sources"][catalogue_key]["sha256"]
    }
    checks.append(_check(not stack_hash_mismatches, "source_stack.hash_parity", stack_hash_mismatches))

    checks.append(_check(set(builder.SOURCES) == set(BUILDER_BINDINGS), "builder.source_role_parity"))
    builder_path_mismatches = {
        role: {"actual": str(builder.SOURCES[role]["path"]), "expected": str(source_path(catalogue_key))}
        for role, catalogue_key in BUILDER_BINDINGS.items()
        if Path(builder.SOURCES[role]["path"]).resolve() != source_path(catalogue_key).resolve()
    }
    checks.append(_check(not builder_path_mismatches, "builder.catalogue_paths", builder_path_mismatches))
    builder_hash_mismatches = {
        role: {"actual": builder.SOURCES[role]["sha256"], "expected": catalogue["sources"][catalogue_key]["sha256"]}
        for role, catalogue_key in BUILDER_BINDINGS.items()
        if builder.SOURCES[role]["sha256"] != catalogue["sources"][catalogue_key]["sha256"]
    }
    checks.append(_check(not builder_hash_mismatches, "builder.hash_parity", builder_hash_mismatches))

    try:
        authority_descriptor = terrain_authority.verify_authority()
        authority_error = None
    except Exception as error:
        authority_descriptor = None
        authority_error = f"{type(error).__name__}: {error}"
    checks.append(_check(
        authority_descriptor is not None,
        "terrain_authority.runtime_gate",
        authority_error or authority_descriptor,
    ))
    if authority_descriptor is not None:
        expected_lineage = terrain_authority.expected_sealed_tiff_lineage()
        checks.append(_check(
            authority_descriptor["sealed_tiff_lineage"] == expected_lineage,
            "terrain_authority.sealed_tiff_lineage",
            authority_descriptor["sealed_tiff_lineage"],
        ))
        checks.append(_check(
            terrain_authority.authority_root().resolve()
            == (root / terrain_authority.DEFAULT_AUTHORITY_RELATIVE_PATH).resolve(),
            "terrain_authority.portable_default_root",
            str(terrain_authority.authority_root()),
        ))

    builder_code = Path(builder.__file__).read_text(encoding="utf-8")
    checks.append(_check(
        'rasterio.open(Path(SOURCES["terrain_100m' not in builder_code
        and "still_terrain" not in builder_code,
        "terrain_authority.no_tiff_runtime_fallback_or_recomposition",
    ))

    checks.append(_check(rules.DEFAULT_DB.resolve() == source_path("stage6b_parent_sqlite").resolve(), "rules.default_db_binding"))
    with sqlite3.connect(f"file:{source_path('stage6b_parent_sqlite').as_posix()}?mode=ro", uri=True) as connection:
        quick_check = connection.execute("PRAGMA quick_check").fetchone()[0]
    checks.append(_check(quick_check == "ok", "stage6b_parent_sqlite.quick_check", quick_check))

    rule_report = rules.self_check(source_path("stage6b_parent_sqlite"))
    checks.append(_check(rule_report.get("status") == "PASS", "stage6c_rules.self_check", rule_report))

    code_findings = _scan_active_code()
    checks.append(_check(not code_findings, "active_code.no_historical_source_paths_or_parents2", code_findings))

    storage_policy_report = scan_phase1_storage_policy(root.parent)
    checks.append(_check(
        storage_policy_report.get("status") == "PASS",
        "phase1_storage.no_new_zip_production_writers",
        storage_policy_report,
    ))

    outside_root = {
        key: str(source_path(key))
        for key in catalogue["sources"]
        if root not in source_path(key).parents
    }
    checks.append(_check(not outside_root, "catalogue.all_sources_inside_generator_root", outside_root))

    failed = [check["check"] for check in checks if not check["ok"]]
    return {
        "schema": "diadem-local-generator-validation-1.0",
        "status": "PASS" if not failed else "FAIL",
        "generator_root": str(root),
        "catalogue_source_count": len(catalogue["sources"]),
        "full_hashes": full_hashes,
        "failed_checks": failed,
        "checks": checks,
        "source_verification": source_report,
        "phase1_storage_policy": storage_policy_report,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quick", action="store_true", help="Hash a representative five-file subset instead of all 32 files")
    parser.add_argument("--report", type=Path, help="Optional JSON report path")
    args = parser.parse_args(argv)
    report = validate(full_hashes=not args.quick)
    output = args.report or generator_root() / "LOCAL_GENERATOR_VALIDATION.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "catalogue_source_count": report["catalogue_source_count"],
        "failed_checks": report["failed_checks"],
        "report": str(output),
    }, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
