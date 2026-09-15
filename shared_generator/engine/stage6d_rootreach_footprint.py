#!/usr/bin/env python3
"""Conditional no-tree-clearance capacity model for Verfuehrschlund.

This is deliberately a sidecar, not a replacement for Stage 6D.  The source
database has local terrain/hydrology evidence but no mapped canopy gaps,
protected root plates, Red Walks, or crown buffers.  Consequently the model
turns those missing geometries into explicit, replaceable planning parameters
and labels every result as conditional rather than measured capacity.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import sqlite3
import statistics
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


METHOD_VERSION = "STAGE6D_ROOTREACH_NO_TREE_CLEARANCE_V2"
SCHEMA_VERSION = 1
WORKING_STATUS = "WORKING_PROPOSAL_REVIEW_ONLY_NOT_CANON"
EVIDENCE_STATUS = "INCOMPLETE_MODELLED_NO_CLEARANCE_PROXY"
MOTHERS_MOUTH_ID = "SITE4-31B6BD7011DEA612"
RECOGNISED_FORMS = (
    "FOREST_FLOOR_CROWN_ENCLAVE_SETTLEMENT",
    "SPECIES_SPECIFIC_OR_BONDED_SETTLEMENT",
)


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    natural_gap_fraction: float
    apparent_gap_exclusion_fraction: float
    crown_red_walk_allowance_ha: float
    paths_drainage_fraction: float
    public_service_fraction: float
    building_ground_m2_per_resident: float
    mother_paths_drainage_fraction: float
    mother_public_service_fraction: float


SCENARIOS: dict[str, Scenario] = {
    "LOW": Scenario("LOW", 0.04, 0.35, 0.20, 0.30, 0.25, 36.0, 0.35, 0.40),
    "CENTRAL": Scenario("CENTRAL", 0.08, 0.25, 0.12, 0.22, 0.20, 21.76, 0.28, 0.32),
    "HIGH": Scenario("HIGH", 0.15, 0.15, 0.08, 0.16, 0.15, 13.125, 0.22, 0.26),
}

# Formation is only a barony-scale proxy.  Missing formation evidence is
# neutral rather than silently classified.  Values adjust, but never replace,
# the scenario gap assumption.
FORMATION_GAP_MULTIPLIER: dict[int, float] = {
    4: 0.81,   # cold conifer forest
    5: 1.00,   # montane mixed forest
    6: 0.94,   # humid macroforest-capable
    # Barony-scale woodland/grassland labels cannot prove that a Rootreach's
    # actual crown neighbourhood is more open, so they receive no uplift.
    7: 1.00,   # mesic temperate forest/woodland
    9: 1.00,   # grassland-leading barony with an unmeasured local forest patch
}


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _number(row: Mapping[str, Any], key: str, default: float = 0.0) -> float:
    value = row.get(key)
    return default if value is None else float(value)


def formation_gap_fraction(row: Mapping[str, Any], scenario: Scenario) -> float:
    code = row.get("leading_formation_code")
    multiplier = FORMATION_GAP_MULTIPLIER.get(int(code), 1.0) if code is not None else 1.0
    return clamp(scenario.natural_gap_fraction * multiplier, 0.02, 0.18)


def adjusted_exclusion_fraction(row: Mapping[str, Any], scenario: Scenario) -> float:
    return clamp(
        scenario.apparent_gap_exclusion_fraction
        + 0.10 * _number(row, "wetland_fraction")
        + 0.05 * _number(row, "flood_exposure_index"),
        0.0,
        0.60,
    )


def adjusted_paths_fraction(row: Mapping[str, Any], scenario: Scenario) -> float:
    return clamp(
        scenario.paths_drainage_fraction + 0.08 * _number(row, "flood_exposure_index"),
        0.0,
        0.50,
    )


def site_capacity(
    row: Mapping[str, Any],
    scenario: Scenario,
    *,
    managed_envelope_share: float,
) -> dict[str, float | int]:
    """Return a conditional capacity from a modelled managed envelope.

    ``developable_area_r1_km2`` remains only an outer physical envelope.  The
    managed share is not interpreted as cleared land: it is the dispersed area
    within which existing gaps and between-tree construction are surveyed.
    """

    physical_outer_ha = _number(row, "developable_area_r1_km2") * 100.0
    managed_envelope_ha = physical_outer_ha * managed_envelope_share
    gap_fraction = formation_gap_fraction(row, scenario)
    exclusion_fraction = adjusted_exclusion_fraction(row, scenario)
    paths_fraction = adjusted_paths_fraction(row, scenario)
    apparent_gap_ha = managed_envelope_ha * gap_fraction
    safe_gap_ha = max(
        0.0,
        apparent_gap_ha * (1.0 - exclusion_fraction)
        - scenario.crown_red_walk_allowance_ha,
    )
    building_ground_ha = (
        safe_gap_ha
        * (1.0 - paths_fraction)
        * (1.0 - scenario.public_service_fraction)
    )
    capacity = math.floor(
        10_000.0 * building_ground_ha / scenario.building_ground_m2_per_resident
    )
    return {
        "physical_outer_ha": physical_outer_ha,
        "managed_envelope_ha": managed_envelope_ha,
        "natural_gap_fraction": gap_fraction,
        "apparent_gap_exclusion_fraction": exclusion_fraction,
        "paths_drainage_fraction": paths_fraction,
        "apparent_gap_ha": apparent_gap_ha,
        "net_safe_gap_ha": safe_gap_ha,
        "building_ground_ha": building_ground_ha,
        "capacity": max(0, capacity),
    }


def required_managed_envelope_ha(
    row: Mapping[str, Any], scenario: Scenario, population: int
) -> float:
    if population < 0:
        raise ValueError("population cannot be negative")
    gap_fraction = formation_gap_fraction(row, scenario)
    exclusion_fraction = adjusted_exclusion_fraction(row, scenario)
    paths_fraction = adjusted_paths_fraction(row, scenario)
    safe_gap_needed = (
        population
        * scenario.building_ground_m2_per_resident
        / 10_000.0
        / ((1.0 - paths_fraction) * (1.0 - scenario.public_service_fraction))
    )
    return (
        safe_gap_needed + scenario.crown_red_walk_allowance_ha
    ) / (gap_fraction * (1.0 - exclusion_fraction))


def mother_safe_gap_requirement_ha(population: int, scenario: Scenario) -> float:
    """Net safe existing gap needed after crater/root/tree exclusions.

    Gross basin requirement is intentionally not inferred because the crater,
    no-build buffer, liana fields and natural gaps have not been mapped.
    """

    return (
        population
        * scenario.building_ground_m2_per_resident
        / 10_000.0
        / (
            (1.0 - scenario.mother_paths_drainage_fraction)
            * (1.0 - scenario.mother_public_service_fraction)
        )
    )


def mother_site_capacity(
    row: Mapping[str, Any],
    scenario: Scenario,
    *,
    managed_envelope_share: float,
) -> dict[str, float | int]:
    """Conditional basin capacity for Mother's Mouth.

    The exclusion fraction is an explicit union proxy for the dormant crater,
    its complete no-build buffer, lianas/roots, protected trees and wet ground.
    It must eventually be replaced by mapped geometry.
    """

    physical_outer_ha = _number(row, "developable_area_r5_km2") * 100.0
    managed_envelope_ha = physical_outer_ha * managed_envelope_share
    gap_fraction = formation_gap_fraction(row, scenario)
    exclusion_fraction = adjusted_exclusion_fraction(row, scenario)
    apparent_gap_ha = managed_envelope_ha * gap_fraction
    safe_gap_ha = apparent_gap_ha * (1.0 - exclusion_fraction)
    building_ground_ha = (
        safe_gap_ha
        * (1.0 - scenario.mother_paths_drainage_fraction)
        * (1.0 - scenario.mother_public_service_fraction)
    )
    capacity = math.floor(
        10_000.0 * building_ground_ha / scenario.building_ground_m2_per_resident
    )
    return {
        "physical_outer_ha": physical_outer_ha,
        "managed_envelope_ha": managed_envelope_ha,
        "natural_gap_fraction": gap_fraction,
        "union_exclusion_fraction": exclusion_fraction,
        "apparent_gap_ha": apparent_gap_ha,
        "net_safe_gap_ha": safe_gap_ha,
        "building_ground_ha": building_ground_ha,
        "capacity": max(0, capacity),
    }


def attractiveness(row: Mapping[str, Any]) -> float:
    return clamp(
        0.35
        + 0.25 * _number(row, "capacity_support_score")
        + 0.25 * _number(row, "access_support_score")
        + 0.15 * _number(row, "seasonal_reliability_index"),
        0.25,
        1.0,
    )


def allocate_bounded(
    site_ids: Sequence[str],
    capacities: Mapping[str, int],
    weights: Mapping[str, float],
    total: int,
    *,
    minimum: int,
) -> dict[str, int]:
    """Deterministic capped proportional allocation with exact conservation."""

    if len(set(site_ids)) != len(site_ids):
        raise ValueError("site identifiers must be unique")
    if any(capacities[sid] < minimum for sid in site_ids):
        raise ValueError("one or more central capacities cannot support the minimum household")
    if total < minimum * len(site_ids):
        raise ValueError("total is below the minimum enclave population")
    if total > sum(capacities[sid] for sid in site_ids):
        raise ValueError("total exceeds summed central conditional capacity")

    def raw(scale: float) -> dict[str, float]:
        return {
            sid: min(
                float(capacities[sid]),
                minimum + scale * max(0.0, weights[sid]),
            )
            for sid in site_ids
        }

    lo, hi = 0.0, 1.0
    while sum(raw(hi).values()) < total:
        hi *= 2.0
    for _ in range(100):
        mid = (lo + hi) / 2.0
        if sum(raw(mid).values()) < total:
            lo = mid
        else:
            hi = mid

    values = raw(hi)
    allocated = {sid: math.floor(values[sid]) for sid in site_ids}
    remainder = total - sum(allocated.values())
    order = sorted(
        site_ids,
        key=lambda sid: (
            -(values[sid] - allocated[sid]),
            sid,
        ),
    )
    for sid in order:
        if remainder == 0:
            break
        if allocated[sid] < capacities[sid]:
            allocated[sid] += 1
            remainder -= 1
    if remainder:
        raise RuntimeError("integer apportionment did not conserve the requested total")
    return allocated


def percentile(values: Sequence[int], fraction: float) -> int:
    ordered = sorted(values)
    return ordered[round((len(ordered) - 1) * fraction)]


def load_sites(source_db: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    connection = sqlite3.connect(f"file:{source_db.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        rows = [
            dict(row)
            for row in connection.execute(
                """
                SELECT
                    d.source_site_id AS settlement_id,
                    d.membership_id,
                    d.barony_id,
                    d.county_uid,
                    d.duchy_uid,
                    d.display_x_km,
                    d.display_y_km,
                    d.stage6b_membership_realised_settlement_form AS settlement_form,
                    d.stage6b_membership_functional_tier AS functional_tier,
                    d.stage6b_membership_administrative_role AS administrative_role,
                    a.analysis_status,
                    a.developable_area_r1_km2,
                    a.developable_area_r5_km2,
                    a.capacity_support_score,
                    a.access_support_score,
                    a.water_access_index,
                    a.seasonal_reliability_index,
                    a.flood_exposure_index,
                    a.wetland_fraction,
                    a.evidence_confidence_score,
                    a.review_status,
                    a.input_fingerprint AS stage6c_input_fingerprint,
                    p.leading_formation_code,
                    p.leading_formation_name,
                    p.leading_formation_share
                FROM stage6_site_disposition d
                JOIN stage6c_site_assessment a
                    ON a.settlement_id = d.source_site_id
                LEFT JOIN province p ON p.barony_id = d.barony_id
                WHERE UPPER(d.haus) LIKE '%VERF%SCHLUND%'
                  AND d.stage6b_membership_realised_settlement_form IN (?, ?)
                ORDER BY d.source_site_id
                """,
                RECOGNISED_FORMS,
            )
        ]
        mother_row = connection.execute(
            """
            SELECT
                d.source_site_id AS settlement_id,
                d.membership_id,
                d.barony_id,
                d.county_uid,
                d.duchy_uid,
                d.display_x_km,
                d.display_y_km,
                d.stage6b_membership_realised_settlement_form AS settlement_form,
                d.stage6b_membership_functional_tier AS functional_tier,
                d.stage6b_membership_administrative_role AS administrative_role,
                a.analysis_status,
                a.developable_area_r1_km2,
                a.developable_area_r5_km2,
                a.capacity_support_score,
                a.access_support_score,
                a.water_access_index,
                a.seasonal_reliability_index,
                a.flood_exposure_index,
                a.wetland_fraction,
                a.evidence_confidence_score,
                a.review_status,
                a.input_fingerprint AS stage6c_input_fingerprint,
                p.leading_formation_code,
                p.leading_formation_name,
                p.leading_formation_share
            FROM stage6_site_disposition d
            JOIN stage6c_site_assessment a
                ON a.settlement_id = d.source_site_id
            LEFT JOIN province p ON p.barony_id = d.barony_id
            WHERE d.source_site_id = ?
            """,
            (MOTHERS_MOUTH_ID,),
        ).fetchone()
    finally:
        connection.close()
    if len(rows) != 611:
        raise ValueError(f"expected 611 recognised Rootreach ledgers, found {len(rows)}")
    if mother_row is None:
        raise ValueError("selected Mother's Mouth record is missing")
    return rows, dict(mother_row)


def build(
    source_db: Path,
    output_dir: Path,
    *,
    haus_population: int = 69_189,
    mother_population: int | None = None,
    managed_envelope_share: float = 0.035,
    minimum_enclave_population: int = 6,
    canon_sources: Sequence[Path] = (),
) -> dict[str, Any]:
    if not 0.0 < managed_envelope_share <= 1.0:
        raise ValueError("managed envelope share must lie in (0, 1]")
    output_dir.mkdir(parents=True, exist_ok=True)
    sites, mother = load_sites(source_db)
    mother_scenarios = {
        name: mother_site_capacity(
            mother, scenario, managed_envelope_share=managed_envelope_share
        )
        for name, scenario in SCENARIOS.items()
    }
    if mother_population is None:
        mother_population = int(mother_scenarios["CENTRAL"]["capacity"])
        mother_population_basis = "DERIVED_FROM_CENTRAL_CONDITIONAL_BASIN_PROXY"
    else:
        mother_population_basis = "EXPLICIT_WORKING_OVERRIDE"
    if not 0 <= mother_population < haus_population:
        raise ValueError("Mother's Mouth population must be below the Haus total")
    residual = haus_population - mother_population
    source_evidence = []
    for path in canon_sources:
        resolved = path.resolve(strict=True)
        data = resolved.read_bytes()
        source_evidence.append(
            {
                "path": str(resolved),
                "size_bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )

    per_site: dict[str, dict[str, Any]] = {}
    central_capacities: dict[str, int] = {}
    weights: dict[str, float] = {}
    for row in sites:
        sid = str(row["settlement_id"])
        scenario_results = {
            name: site_capacity(row, scenario, managed_envelope_share=managed_envelope_share)
            for name, scenario in SCENARIOS.items()
        }
        central = int(scenario_results["CENTRAL"]["capacity"])
        central_capacities[sid] = central
        attraction = attractiveness(row)
        weights[sid] = max(1.0, central - minimum_enclave_population) * attraction
        per_site[sid] = {
            "source": row,
            "scenarios": scenario_results,
            "attractiveness": attraction,
        }

    allocation = allocate_bounded(
        [str(row["settlement_id"]) for row in sites],
        central_capacities,
        weights,
        residual,
        minimum=minimum_enclave_population,
    )

    result_rows: list[dict[str, Any]] = []
    for row in sites:
        sid = str(row["settlement_id"])
        population = allocation[sid]
        scenarios = per_site[sid]["scenarios"]
        required = {
            name: required_managed_envelope_ha(row, scenario, population)
            for name, scenario in SCENARIOS.items()
        }
        limiting = [
            "NO_MEASURED_CANOPY_GAP_GEOMETRY",
            "NO_MAPPED_TREE_OR_ROOT_PROTECTION_UNION",
            "NO_MAPPED_CROWN_RED_WALK_GEOMETRY",
        ]
        if row.get("leading_formation_code") is None:
            limiting.append("BARONY_FORMATION_PROXY_UNAVAILABLE")
        if population > int(scenarios["LOW"]["capacity"]):
            limiting.append("LOW_STRESS_CAPACITY_FAILS")
        result_rows.append(
            {
                **row,
                "working_population": population,
                "bonded_humans": 1,
                "unbonded_humans_including_stage0": population - 1,
                "attractiveness": per_site[sid]["attractiveness"],
                "managed_envelope_share": managed_envelope_share,
                "modelled_managed_envelope_ha": scenarios["CENTRAL"]["managed_envelope_ha"],
                "capacity_low": scenarios["LOW"]["capacity"],
                "capacity_central": scenarios["CENTRAL"]["capacity"],
                "capacity_high": scenarios["HIGH"]["capacity"],
                "occupancy_of_central_capacity": population / max(1, int(scenarios["CENTRAL"]["capacity"])),
                "required_managed_envelope_low_ha": required["LOW"],
                "required_managed_envelope_central_ha": required["CENTRAL"],
                "required_managed_envelope_high_ha": required["HIGH"],
                "low_stress_pass": int(population <= int(scenarios["LOW"]["capacity"])),
                "central_conditional_pass": int(population <= int(scenarios["CENTRAL"]["capacity"])),
                "high_conditional_pass": int(population <= int(scenarios["HIGH"]["capacity"])),
                "evidence_status": EVIDENCE_STATUS,
                "limiting_factors_json": canonical_json(limiting),
                "canon_status": WORKING_STATUS,
            }
        )

    mother_requirements = {
        name: mother_safe_gap_requirement_ha(mother_population, scenario)
        for name, scenario in SCENARIOS.items()
    }
    populations = [int(row["working_population"]) for row in result_rows]
    capacity_totals = {
        name.lower(): sum(int(per_site[sid]["scenarios"][name]["capacity"]) for sid in per_site)
        for name in SCENARIOS
    }
    semantic_input = {
        "method_version": METHOD_VERSION,
        "source_rows": sites,
        "mother_row": mother,
        "canon_source_evidence": source_evidence,
        "scenarios": {key: asdict(value) for key, value in SCENARIOS.items()},
        "formation_gap_multiplier": FORMATION_GAP_MULTIPLIER,
        "managed_envelope_share": managed_envelope_share,
        "minimum_enclave_population": minimum_enclave_population,
        "haus_population": haus_population,
        "mother_population": mother_population,
        "mother_population_basis": mother_population_basis,
    }
    input_fingerprint = fingerprint(semantic_input)
    run_id = f"S6D-RF-{input_fingerprint[:20].upper()}"
    summary = {
        "run_id": run_id,
        "schema_version": SCHEMA_VERSION,
        "method_version": METHOD_VERSION,
        "source_database": str(source_db.resolve()),
        "canon_source_evidence": source_evidence,
        "input_fingerprint": input_fingerprint,
        "canon_status": WORKING_STATUS,
        "completion_state": "CONDITIONAL_PASS_CENTRAL_PROXY",
        "recognised_rootreach_ledgers": len(result_rows),
        "population_contexts": len(result_rows) + 1,
        "haus_population": haus_population,
        "mothers_mouth_population": mother_population,
        "mothers_mouth_population_basis": mother_population_basis,
        "rootreach_enclave_population": sum(populations),
        "bonded_humans": len(result_rows),
        "unbonded_humans_including_stage0": haus_population - len(result_rows),
        "managed_envelope_share": managed_envelope_share,
        "conditional_capacity_totals": capacity_totals,
        "central_capacity_headroom": capacity_totals["central"] - sum(populations),
        "central_occupancy_fraction": sum(populations) / capacity_totals["central"],
        "population_distribution": {
            "minimum": min(populations),
            "p05": percentile(populations, 0.05),
            "p25": percentile(populations, 0.25),
            "median": percentile(populations, 0.50),
            "p75": percentile(populations, 0.75),
            "p95": percentile(populations, 0.95),
            "maximum": max(populations),
            "mean": statistics.fmean(populations),
        },
        "low_stress_fail_site_count": sum(1 for row in result_rows if not row["low_stress_pass"]),
        "central_fail_site_count": sum(1 for row in result_rows if not row["central_conditional_pass"]),
        "mother_safe_existing_gap_requirement_ha": mother_requirements,
        "mother_conditional_capacity": {
            name.lower(): int(result["capacity"])
            for name, result in mother_scenarios.items()
        },
        "mother_central_modelled_managed_basin_envelope_ha": mother_scenarios["CENTRAL"]["managed_envelope_ha"],
        "mother_central_net_safe_gap_proxy_ha": mother_scenarios["CENTRAL"]["net_safe_gap_ha"],
        "mother_temporary_attendance_caps": {
            "low": round(mother_population * 0.25),
            "central": round(mother_population * 0.50),
            "high": round(mother_population * 1.00),
        },
        "hard_limitations": [
            "No site has measured canopy-gap geometry.",
            "No protected-tree/root, crown, Red Walk, or active-liana exclusion union is mapped.",
            "Mother's Mouth crater and complete no-build buffer are not mapped.",
            "The central pass is a conditional planning result, not a surveyed carrying capacity.",
        ],
    }

    _write_outputs(
        output_dir,
        result_rows,
        mother,
        mother_requirements,
        mother_scenarios,
        summary,
    )
    return summary


def _write_outputs(
    output_dir: Path,
    rows: Sequence[Mapping[str, Any]],
    mother: Mapping[str, Any],
    mother_requirements: Mapping[str, float],
    mother_scenarios: Mapping[str, Mapping[str, float | int]],
    summary: Mapping[str, Any],
) -> None:
    csv_path = output_dir / "Rootreach_Settlement_Footprint_and_Population_WORKING.csv"
    json_path = output_dir / "Rootreach_Footprint_Validation_WORKING.json"
    db_path = output_dir / "Diadem_Stage6D_Rootreach_Footprint_WORKING.sqlite"
    readme_path = output_dir / "README_FIRST.md"

    fieldnames = list(rows[0].keys())
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    temporary_db = db_path.with_suffix(".sqlite.partial")
    if temporary_db.exists():
        temporary_db.unlink()
    connection = sqlite3.connect(temporary_db)
    try:
        connection.executescript(
            """
            PRAGMA journal_mode=DELETE;
            PRAGMA synchronous=FULL;
            CREATE TABLE run_metadata (
                run_id TEXT PRIMARY KEY,
                schema_version INTEGER NOT NULL,
                method_version TEXT NOT NULL,
                input_fingerprint TEXT NOT NULL,
                canon_status TEXT NOT NULL,
                summary_json TEXT NOT NULL
            );
            CREATE TABLE scenario_parameter (
                scenario_id TEXT PRIMARY KEY,
                parameter_json TEXT NOT NULL
            );
            CREATE TABLE rootreach_site_capacity (
                settlement_id TEXT PRIMARY KEY,
                barony_id INTEGER,
                county_uid TEXT,
                duchy_uid TEXT,
                display_x_km REAL,
                display_y_km REAL,
                settlement_form TEXT NOT NULL,
                functional_tier TEXT,
                leading_formation_code INTEGER,
                leading_formation_name TEXT,
                developable_area_r1_km2 REAL NOT NULL,
                managed_envelope_share REAL NOT NULL,
                modelled_managed_envelope_ha REAL NOT NULL,
                working_population INTEGER NOT NULL,
                bonded_humans INTEGER NOT NULL,
                unbonded_humans_including_stage0 INTEGER NOT NULL,
                capacity_low INTEGER NOT NULL,
                capacity_central INTEGER NOT NULL,
                capacity_high INTEGER NOT NULL,
                occupancy_of_central_capacity REAL NOT NULL,
                required_managed_envelope_low_ha REAL NOT NULL,
                required_managed_envelope_central_ha REAL NOT NULL,
                required_managed_envelope_high_ha REAL NOT NULL,
                low_stress_pass INTEGER NOT NULL,
                central_conditional_pass INTEGER NOT NULL,
                high_conditional_pass INTEGER NOT NULL,
                evidence_status TEXT NOT NULL,
                limiting_factors_json TEXT NOT NULL,
                canon_status TEXT NOT NULL
            );
            CREATE TABLE mothers_mouth_requirement (
                settlement_id TEXT PRIMARY KEY,
                working_population INTEGER NOT NULL,
                bonded_humans INTEGER NOT NULL,
                safe_gap_low_ha REAL NOT NULL,
                safe_gap_central_ha REAL NOT NULL,
                safe_gap_high_ha REAL NOT NULL,
                modelled_managed_basin_envelope_ha REAL NOT NULL,
                conditional_capacity_low INTEGER NOT NULL,
                conditional_capacity_central INTEGER NOT NULL,
                conditional_capacity_high INTEGER NOT NULL,
                population_basis TEXT NOT NULL,
                gross_basin_capacity_status TEXT NOT NULL,
                evidence_status TEXT NOT NULL,
                source_row_json TEXT NOT NULL
            );
            """
        )
        connection.execute(
            "INSERT INTO run_metadata VALUES (?, ?, ?, ?, ?, ?)",
            (
                summary["run_id"],
                summary["schema_version"],
                summary["method_version"],
                summary["input_fingerprint"],
                summary["canon_status"],
                canonical_json(summary),
            ),
        )
        connection.executemany(
            "INSERT INTO scenario_parameter VALUES (?, ?)",
            [(key, canonical_json(asdict(value))) for key, value in SCENARIOS.items()],
        )
        columns = [
            "settlement_id", "barony_id", "county_uid", "duchy_uid", "display_x_km",
            "display_y_km", "settlement_form", "functional_tier",
            "leading_formation_code", "leading_formation_name", "developable_area_r1_km2",
            "managed_envelope_share", "modelled_managed_envelope_ha", "working_population",
            "bonded_humans", "unbonded_humans_including_stage0", "capacity_low",
            "capacity_central", "capacity_high", "occupancy_of_central_capacity",
            "required_managed_envelope_low_ha", "required_managed_envelope_central_ha",
            "required_managed_envelope_high_ha", "low_stress_pass",
            "central_conditional_pass", "high_conditional_pass", "evidence_status",
            "limiting_factors_json", "canon_status",
        ]
        connection.executemany(
            f"INSERT INTO rootreach_site_capacity ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
            [tuple(row.get(column) for column in columns) for row in rows],
        )
        connection.execute(
            "INSERT INTO mothers_mouth_requirement VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                MOTHERS_MOUTH_ID,
                summary["mothers_mouth_population"],
                0,
                mother_requirements["LOW"],
                mother_requirements["CENTRAL"],
                mother_requirements["HIGH"],
                mother_scenarios["CENTRAL"]["managed_envelope_ha"],
                mother_scenarios["LOW"]["capacity"],
                mother_scenarios["CENTRAL"]["capacity"],
                mother_scenarios["HIGH"]["capacity"],
                summary["mothers_mouth_population_basis"],
                "INCOMPLETE_UNTIL_CRATER_BUFFER_AND_NATURAL_GAPS_ARE_MAPPED",
                EVIDENCE_STATUS,
                canonical_json(mother),
            ),
        )
        connection.commit()
        check = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if check != "ok":
            raise RuntimeError(f"SQLite integrity check failed: {check}")
    finally:
        connection.close()
    os.replace(temporary_db, db_path)

    distribution = summary["population_distribution"]
    mother_gap = summary["mother_safe_existing_gap_requirement_ha"]
    readme = f"""# Stage 6D Rootreach forest-footprint sidecar

This run models **constraints, not identical settlements**.  It distributes the
fixed 69,189-person Verfuehrschlund working total across 611 recognised
Rootreach enclave ledgers plus Mother's Mouth.  Each enclave has one active
Maw-Mother bond; Mother's Mouth creates no 612th bond.

## Working result

- Mother's Mouth permanent residents: **{summary['mothers_mouth_population']:,}**,
  derived from the central conditional basin proxy rather than rounded.
- Other enclave residents: **{summary['rootreach_enclave_population']:,}**.
- Ordinary enclave distribution: **{distribution['minimum']} minimum,
  {distribution['median']} median, {distribution['p95']} p95,
  {distribution['maximum']} maximum**.
- Central conditional capacity: **{summary['conditional_capacity_totals']['central']:,}**;
  occupancy **{summary['central_occupancy_fraction']:.1%}**.
- Low-stress failures: **{summary['low_stress_fail_site_count']} of 611**;
  central failures: **{summary['central_fail_site_count']}**.
- Mother's Mouth needs at least **{mother_gap['LOW']:.2f} / {mother_gap['CENTRAL']:.2f} /
  {mother_gap['HIGH']:.2f} ha** of net safe existing open ground under the
  low/central/high assumptions.  Its gross basin requirement is unresolved.

## What the model does

For each enclave, the Stage 6C 1-km physically suitable area is only an outer
envelope.  The model treats {summary['managed_envelope_share']:.1%} of it as a
dispersed surveyed management envelope, retains only scenario-specific natural
gaps, subtracts apparent tree/root/wet exclusions and a crown/Red Walk
allowance, then reserves ground for drainage, paths and shared services.

The central assumptions are 8% natural gaps before formation adjustment, 25%
further exclusion within apparent gaps, 0.12 ha for the crown/Red Walk,
22% paths/drainage, 20% public/service ground and 21.76 m2 effective building
ground per permanent resident.  Population is then apportioned within the
resulting site-specific capacities using terrain capacity, access and seasonal
reliability.  This produces varied settlements rather than one repeated size.

## Hard limitation

No current project layer maps canopy gaps, protected mature trees/root plates,
Rootreach tissue, Red Walks or the Mother's Mouth crater buffer.  Every capacity
therefore remains `INCOMPLETE_MODELLED_NO_CLEARANCE_PROXY`.  Replace the proxy
fields with surveyed polygons when those geometries exist; never reinterpret
the result as permission to clear mature forest.

Run ID: `{summary['run_id']}`  
Input fingerprint: `{summary['input_fingerprint']}`  
Method: `{METHOD_VERSION}`
"""
    readme_path.write_text(readme, encoding="utf-8")

    manifest: dict[str, Any] = {
        "run_id": summary["run_id"],
        "files": [],
    }
    for path in (csv_path, json_path, db_path, readme_path):
        data = path.read_bytes()
        manifest["files"].append(
            {
                "path": path.name,
                "size_bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
    (output_dir / "MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-db", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--haus-population", type=int, default=69_189)
    parser.add_argument("--mother-population", type=int)
    parser.add_argument("--managed-envelope-share", type=float, default=0.035)
    parser.add_argument("--minimum-enclave-population", type=int, default=6)
    parser.add_argument("--canon-source", type=Path, action="append", default=[])
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    summary = build(
        args.source_db,
        args.output_dir,
        haus_population=args.haus_population,
        mother_population=args.mother_population,
        managed_envelope_share=args.managed_envelope_share,
        minimum_enclave_population=args.minimum_enclave_population,
        canon_sources=args.canon_source,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
