#!/usr/bin/env python3
"""Stage 6D source contract and normalized population sidecar schema.

This module is deliberately standard-library only.  Stage 6D remains a
WORKING_PROPOSAL_REVIEW_ONLY_NOT_CANON analytical layer: it never edits the
Stage 6C/6C.5/6C.5R source databases, never changes settlement identities or
coordinates, and never promotes population estimates to canon.

The sidecar separates realised population from scenario-dependent carrying
capacity.  In particular, bonded humans have one population number.  No bond
stage distribution is represented because bonded people may move freely among
stages.  Mobile pools may have many host anchors but are counted once.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


SCHEMA_VERSION = "diadem.stage6d-population-sidecar.v3"
METHOD_VERSION = "STAGE6D_POPULATION_AND_CARRYING_CAPACITY_V3"
CANON_STATUS = "WORKING_PROPOSAL_REVIEW_ONLY_NOT_CANON"
READINESS_STATES = ("FOUND", "PROVEN_ABSENT", "INCOMPLETE", "CONFLICT")
ROUTE_EVIDENCE_STATES = READINESS_STATES + ("WORKING_PROXY",)
SCENARIOS = (
    (
        "LOCAL_AUTARKIC",
        10,
        "Local/autarkic support only; inter-node food flows are prohibited.",
    ),
    (
        "NORMAL_TRADE",
        20,
        "Normal trade-supported capacity using only evidenced, conserved flows.",
    ),
    (
        "DISRUPTED_ROUTES",
        30,
        "Route-disruption stress case with explicitly reduced or unavailable flows.",
    ),
)

SCENARIO_PARAMETERS = {
    "LOCAL_AUTARKIC": {
        "inter_node_trade_allowed": False,
        "export_dispatch_fraction": 0.0,
        "route_reliability_multiplier": 0.0,
        "loss_floor": 0.0,
        "loss_access_penalty": 0.0,
        "route_evidence_mode": "NO_INTER_NODE_FLOW",
    },
    "NORMAL_TRADE": {
        "inter_node_trade_allowed": True,
        "export_dispatch_fraction": 1.0,
        "route_reliability_multiplier": 1.0,
        "loss_floor": 0.06,
        "loss_access_penalty": 0.18,
        "route_evidence_mode": "FOUND_OR_WORKING_PROXY",
    },
    "DISRUPTED_ROUTES": {
        "inter_node_trade_allowed": True,
        "export_dispatch_fraction": 0.35,
        "route_reliability_multiplier": 1.0,
        "loss_floor": 0.06,
        "loss_access_penalty": 0.18,
        "delivered_flow_fraction_of_normal": 0.35,
        "route_evidence_mode": "FOUND_OR_WORKING_PROXY",
    },
}


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def semantic_rows_sha256(rows: Iterable[Mapping[str, Any]]) -> str:
    """Hash ordered semantic rows without hashing an entire SQLite container."""

    digest = hashlib.sha256()
    for row in rows:
        payload = canonical_json(dict(row)).encode("utf-8")
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest()


def stage6d_source_select(*, refinement_join: str) -> str:
    """Return the one explicit Stage 6D site-source projection.

    ``JOIN`` gives the 107-row Stage 6C.5 compatibility view. ``LEFT JOIN``
    gives all active settlements for the Stage 6D sidecar.  The selected
    column names are stable and unique; neither ``*`` nor the removed
    ``stage6_population_model`` pseudo-column is permitted.
    """

    join = refinement_join.strip().upper()
    if join not in {"JOIN", "LEFT JOIN"}:
        raise ValueError(f"Unsupported refinement join: {refinement_join!r}")
    return f"""
        SELECT
            s.settlement_id AS settlement_id,
            s.barony_id AS barony_id,
            s.county_uid AS county_uid,
            s.duchy_uid AS duchy_uid,
            a.owner_haus_id AS owner_haus_id,
            CASE
                WHEN p.surface_fill_key = 'GREAT_FOREST_SHARED'
                    THEN 'GREAT_FOREST::' || a.owner_haus_id
                ELSE COALESCE(p.surface_fill_key, a.owner_haus_id, 'UNRESOLVED_NETWORK')
            END AS economic_network_id,
            s.stage6b_functional_tier AS functional_tier,
            s.stage6b_realised_settlement_form AS realised_settlement_form,
            s.stage6b_form_family AS form_family,
            s.stage6_ordinary_permanent_human_settlement AS ordinary_permanent_human_allowed,
            s.stage6_residency_semantics AS residency_semantics,
            s.stage6_entity_type AS entity_type,
            s.display_x_km AS display_x_km,
            s.display_y_km AS display_y_km,
            a.analysis_anchor_x_km AS analysis_anchor_x_km,
            a.analysis_anchor_y_km AS analysis_anchor_y_km,
            a.access_modes_json AS access_modes_json,
            a.analysis_status AS stage6c_analysis_status,
            a.profile_id AS stage6c_profile_id,
            a.effective_vertical_domain AS effective_vertical_domain,
            a.capacity_metric_kind AS capacity_metric_kind,
            a.morphology_class AS morphology_class,
            a.capacity_support_score_low AS capacity_support_score_100m_low,
            a.capacity_support_score AS capacity_support_score_100m,
            a.capacity_support_score_high AS capacity_support_score_100m_high,
            a.access_support_score_low AS access_support_score_100m_low,
            a.access_support_score AS access_support_score_100m,
            a.access_support_score_high AS access_support_score_100m_high,
            a.evidence_confidence_score AS evidence_confidence_score_100m,
            a.review_status AS stage6c_review_status,
            a.input_fingerprint AS stage6c_input_fingerprint,
            r.disposition AS stage6c5_disposition,
            r.selection_status AS stage6c5_selection_status,
            r.model_cell_size_m AS stage6c5_model_cell_size_m,
            r.terrain_effective_evidence_resolution_m AS terrain_effective_evidence_resolution_m,
            r.exact_vector_sampling_resolution_m AS exact_vector_sampling_resolution_m,
            r.developable_area_r1_km2_10m AS developable_area_r1_km2_10m,
            r.developable_area_r5_km2_inherited_100m AS developable_area_r5_km2_100m,
            r.land_access_cost_index_10m AS land_access_cost_index_10m,
            r.water_access_index_10m AS water_access_index_10m,
            r.seasonal_reliability_index_10m AS seasonal_reliability_index_10m,
            a.seasonal_reliability_index AS seasonal_reliability_index_100m,
            r.domain_fit_index_10m AS domain_fit_index_10m,
            r.terrain_support_score_10m AS terrain_support_score_10m,
            r.hydrology_support_score_10m AS hydrology_support_score_10m,
            r.flood_compatibility_score_10m AS flood_compatibility_score_10m,
            r.core_capacity_score_10m AS core_capacity_score_10m,
            r.capacity_support_score_10m AS capacity_support_score_10m,
            r.access_support_score_10m AS access_support_score_10m,
            r.score_uncertainty AS stage6c5_score_uncertainty,
            r.evidence_confidence_score AS evidence_confidence_score_10m,
            r.limiting_factors_json AS stage6c5_limiting_factors_json,
            r.review_status AS stage6c5_review_status,
            r.hydrology_status AS stage6c5_hydrology_status,
            r.terrain_status AS stage6c5_terrain_status,
            r.semantic_key AS stage6c5_semantic_key,
            r.method_version AS stage6c5_method_version,
            r.canon_status AS stage6c5_canon_status
        FROM settlement AS s
        JOIN stage6c_site_assessment AS a USING(settlement_id)
        LEFT JOIN province AS p ON p.barony_id = s.barony_id
        {join} stage6c5_site_refinement AS r USING(settlement_id)
        WHERE s.stage6_active_settlement = 1
    """.strip()


STAGE6C5_STAGE6D_VIEW_SELECT = stage6d_source_select(refinement_join="JOIN")
STAGE6D_ALL_ACTIVE_SOURCE_SELECT = stage6d_source_select(refinement_join="LEFT JOIN")


def install_stage6c5_stage6d_view(connection: sqlite3.Connection) -> None:
    """Install the fixed compatibility view in a writable Stage 6C.5 build."""

    connection.execute("DROP VIEW IF EXISTS stage6c5_stage6d_inputs")
    connection.execute(
        "CREATE VIEW stage6c5_stage6d_inputs AS " + STAGE6C5_STAGE6D_VIEW_SELECT
    )


SIDECAR_DDL = f"""
PRAGMA foreign_keys=ON;

CREATE TABLE stage6d_run (
    run_id TEXT PRIMARY KEY,
    created_utc TEXT NOT NULL,
    schema_version TEXT NOT NULL CHECK(schema_version = '{SCHEMA_VERSION}'),
    method_version TEXT NOT NULL,
    source_semantic_sha256 TEXT NOT NULL CHECK(length(source_semantic_sha256)=64),
    source_identity_json TEXT NOT NULL CHECK(json_valid(source_identity_json)),
    recipe_json TEXT NOT NULL CHECK(json_valid(recipe_json)),
    canon_status TEXT NOT NULL CHECK(canon_status = '{CANON_STATUS}'),
    completion_state TEXT NOT NULL CHECK(completion_state IN (
        'SCHEMA_READY','RUNNING','COMPLETE','FAILED','CANCELLED'
    ))
) WITHOUT ROWID;

CREATE TABLE stage6d_scenario (
    scenario_id TEXT PRIMARY KEY CHECK(scenario_id IN (
        'LOCAL_AUTARKIC','NORMAL_TRADE','DISRUPTED_ROUTES'
    )),
    scenario_order INTEGER NOT NULL UNIQUE,
    description TEXT NOT NULL,
    parameter_json TEXT NOT NULL CHECK(json_valid(parameter_json)),
    readiness_status TEXT NOT NULL CHECK(readiness_status IN {READINESS_STATES})
) WITHOUT ROWID;

CREATE TABLE stage6d_source_site (
    settlement_id TEXT PRIMARY KEY,
    barony_id INTEGER,
    county_uid TEXT,
    duchy_uid TEXT,
    owner_haus_id TEXT,
    economic_network_id TEXT NOT NULL,
    functional_tier TEXT,
    realised_settlement_form TEXT,
    form_family TEXT,
    ordinary_permanent_human_allowed INTEGER CHECK(
        ordinary_permanent_human_allowed IS NULL OR
        ordinary_permanent_human_allowed IN (0,1)
    ),
    residency_semantics TEXT,
    entity_type TEXT,
    display_x_km REAL,
    display_y_km REAL,
    analysis_anchor_x_km REAL,
    analysis_anchor_y_km REAL,
    access_modes_json TEXT CHECK(access_modes_json IS NULL OR json_valid(access_modes_json)),
    stage6c_analysis_status TEXT NOT NULL,
    stage6c_profile_id TEXT,
    effective_vertical_domain TEXT NOT NULL,
    capacity_metric_kind TEXT,
    morphology_class TEXT,
    capacity_support_score_100m_low REAL,
    capacity_support_score_100m REAL,
    capacity_support_score_100m_high REAL,
    access_support_score_100m_low REAL,
    access_support_score_100m REAL,
    access_support_score_100m_high REAL,
    evidence_confidence_score_100m REAL,
    stage6c_review_status TEXT NOT NULL,
    stage6c_input_fingerprint TEXT NOT NULL,
    stage6c5_disposition TEXT,
    stage6c5_selection_status TEXT,
    stage6c5_model_cell_size_m INTEGER,
    terrain_effective_evidence_resolution_m INTEGER,
    exact_vector_sampling_resolution_m INTEGER,
    developable_area_r1_km2_10m REAL,
    developable_area_r5_km2_100m REAL,
    land_access_cost_index_10m REAL,
    water_access_index_10m REAL,
    seasonal_reliability_index_10m REAL,
    seasonal_reliability_index_100m REAL,
    domain_fit_index_10m REAL,
    terrain_support_score_10m REAL,
    hydrology_support_score_10m REAL,
    flood_compatibility_score_10m REAL,
    core_capacity_score_10m REAL,
    capacity_support_score_10m REAL,
    access_support_score_10m REAL,
    stage6c5_score_uncertainty REAL,
    evidence_confidence_score_10m REAL,
    stage6c5_limiting_factors_json TEXT CHECK(
        stage6c5_limiting_factors_json IS NULL OR
        json_valid(stage6c5_limiting_factors_json)
    ),
    stage6c5_review_status TEXT,
    stage6c5_hydrology_status TEXT,
    stage6c5_terrain_status TEXT,
    stage6c5_semantic_key TEXT,
    stage6c5_method_version TEXT,
    stage6c5_canon_status TEXT,
    stage6c5r_semantic_key TEXT,
    stage6c5r_array_digest TEXT,
    stage6c5r_pilot_site_gate_pass INTEGER CHECK(
        stage6c5r_pilot_site_gate_pass IS NULL OR
        stage6c5r_pilot_site_gate_pass IN (0,1)
    ),
    stage6c5r_metrics_json TEXT CHECK(
        stage6c5r_metrics_json IS NULL OR json_valid(stage6c5r_metrics_json)
    ),
    stage6c5r_canon_status TEXT
) WITHOUT ROWID;

CREATE INDEX stage6d_source_site_barony_idx ON stage6d_source_site(barony_id);
CREATE INDEX stage6d_source_site_haus_idx ON stage6d_source_site(owner_haus_id);
CREATE INDEX stage6d_source_site_economic_network_idx ON stage6d_source_site(economic_network_id);
CREATE INDEX stage6d_source_site_tier_idx ON stage6d_source_site(functional_tier);

CREATE TABLE stage6d_population_profile (
    profile_id TEXT PRIMARY KEY,
    population_class TEXT NOT NULL CHECK(population_class IN (
        'UNBONDED_HUMAN','BONDED_HUMAN','RESIDENT_SPECIES',
        'WILD_RANGE_SPECIES','MOBILE_SHARED_POOL'
    )),
    biological_entity_id TEXT NOT NULL,
    counting_unit TEXT NOT NULL,
    residence_mode TEXT NOT NULL,
    food_demand_milliunits_per_counting_unit INTEGER CHECK(
        food_demand_milliunits_per_counting_unit IS NULL OR
        food_demand_milliunits_per_counting_unit >= 0
    ),
    composite_demand_json TEXT NOT NULL CHECK(json_valid(composite_demand_json)),
    evidence_status TEXT NOT NULL CHECK(evidence_status IN {READINESS_STATES}),
    rule_fingerprint TEXT NOT NULL,
    canon_status TEXT NOT NULL CHECK(canon_status = '{CANON_STATUS}'),
    CHECK(population_class <> 'BONDED_HUMAN' OR biological_entity_id = 'HUMAN')
) WITHOUT ROWID;

CREATE TABLE stage6d_population_pool (
    pool_id TEXT PRIMARY KEY,
    pool_kind TEXT NOT NULL CHECK(pool_kind IN (
        'SITE_RESIDENT','HAUS_SHARED','MOBILE_SHARED','WILD_RANGE','ADMINISTRATIVE_ONLY'
    )),
    primary_settlement_id TEXT REFERENCES stage6d_source_site(settlement_id),
    owner_haus_id TEXT,
    mobile_shared INTEGER NOT NULL CHECK(mobile_shared IN (0,1)),
    identity_fingerprint TEXT NOT NULL UNIQUE,
    evidence_status TEXT NOT NULL CHECK(evidence_status IN {READINESS_STATES}),
    basis_json TEXT NOT NULL CHECK(json_valid(basis_json)),
    CHECK((pool_kind = 'MOBILE_SHARED') = mobile_shared),
    CHECK(pool_kind <> 'MOBILE_SHARED' OR primary_settlement_id IS NULL)
) WITHOUT ROWID;

CREATE INDEX stage6d_population_pool_primary_site_idx
    ON stage6d_population_pool(primary_settlement_id);
CREATE INDEX stage6d_population_pool_haus_idx
    ON stage6d_population_pool(owner_haus_id);

CREATE TABLE stage6d_pool_anchor (
    pool_id TEXT NOT NULL REFERENCES stage6d_population_pool(pool_id) ON DELETE CASCADE,
    settlement_id TEXT NOT NULL REFERENCES stage6d_source_site(settlement_id),
    anchor_role TEXT NOT NULL,
    presence_weight REAL CHECK(presence_weight IS NULL OR presence_weight >= 0),
    PRIMARY KEY(pool_id, settlement_id, anchor_role)
) WITHOUT ROWID;

CREATE TABLE stage6d_population_assignment (
    run_id TEXT NOT NULL REFERENCES stage6d_run(run_id) ON DELETE CASCADE,
    pool_id TEXT NOT NULL REFERENCES stage6d_population_pool(pool_id) ON DELETE CASCADE,
    profile_id TEXT NOT NULL REFERENCES stage6d_population_profile(profile_id),
    evidence_status TEXT NOT NULL CHECK(evidence_status IN {READINESS_STATES}),
    assignment_basis_json TEXT NOT NULL CHECK(json_valid(assignment_basis_json)),
    assignment_fingerprint TEXT NOT NULL,
    PRIMARY KEY(run_id, pool_id, profile_id)
) WITHOUT ROWID;

CREATE TABLE stage6d_population_estimate (
    run_id TEXT NOT NULL,
    pool_id TEXT NOT NULL,
    profile_id TEXT NOT NULL,
    working_population INTEGER CHECK(working_population IS NULL OR working_population >= 0),
    population_low INTEGER CHECK(population_low IS NULL OR population_low >= 0),
    population_high INTEGER CHECK(population_high IS NULL OR population_high >= 0),
    evidence_status TEXT NOT NULL CHECK(evidence_status IN {READINESS_STATES}),
    completion_state TEXT NOT NULL CHECK(completion_state IN (
        'PENDING','COMPUTED','VALIDATED','BLOCKED'
    )),
    limiting_factor TEXT,
    explanation_json TEXT NOT NULL CHECK(json_valid(explanation_json)),
    input_fingerprint TEXT NOT NULL,
    rule_fingerprint TEXT NOT NULL,
    canon_status TEXT NOT NULL CHECK(canon_status = '{CANON_STATUS}'),
    PRIMARY KEY(run_id, pool_id, profile_id),
    FOREIGN KEY(run_id, pool_id, profile_id)
        REFERENCES stage6d_population_assignment(run_id, pool_id, profile_id)
        ON DELETE CASCADE,
    CHECK(population_low IS NULL OR working_population IS NOT NULL),
    CHECK(population_high IS NULL OR working_population IS NOT NULL),
    CHECK(population_low IS NULL OR population_low <= working_population),
    CHECK(population_high IS NULL OR working_population <= population_high),
    CHECK(evidence_status <> 'PROVEN_ABSENT' OR working_population = 0),
    CHECK(evidence_status <> 'FOUND' OR working_population IS NOT NULL),
    CHECK(completion_state NOT IN ('COMPUTED','VALIDATED') OR working_population IS NOT NULL)
) WITHOUT ROWID;

CREATE TABLE stage6d_capacity_result (
    run_id TEXT NOT NULL,
    scenario_id TEXT NOT NULL REFERENCES stage6d_scenario(scenario_id),
    pool_id TEXT NOT NULL,
    profile_id TEXT NOT NULL,
    capacity_low INTEGER CHECK(capacity_low IS NULL OR capacity_low >= 0),
    capacity_central INTEGER CHECK(capacity_central IS NULL OR capacity_central >= 0),
    capacity_high INTEGER CHECK(capacity_high IS NULL OR capacity_high >= 0),
    evidence_status TEXT NOT NULL CHECK(evidence_status IN {READINESS_STATES}),
    completion_state TEXT NOT NULL CHECK(completion_state IN (
        'PENDING','COMPUTED','VALIDATED','BLOCKED'
    )),
    limiting_factor TEXT,
    explanation_json TEXT NOT NULL CHECK(json_valid(explanation_json)),
    input_fingerprint TEXT NOT NULL,
    PRIMARY KEY(run_id, scenario_id, pool_id, profile_id),
    FOREIGN KEY(run_id, pool_id, profile_id)
        REFERENCES stage6d_population_assignment(run_id, pool_id, profile_id)
        ON DELETE CASCADE,
    CHECK(capacity_low IS NULL OR capacity_central IS NOT NULL),
    CHECK(capacity_high IS NULL OR capacity_central IS NOT NULL),
    CHECK(capacity_low IS NULL OR capacity_low <= capacity_central),
    CHECK(capacity_high IS NULL OR capacity_central <= capacity_high),
    CHECK(evidence_status <> 'PROVEN_ABSENT' OR capacity_central = 0),
    CHECK(evidence_status <> 'FOUND' OR capacity_central IS NOT NULL),
    CHECK(completion_state NOT IN ('COMPUTED','VALIDATED') OR capacity_central IS NOT NULL)
) WITHOUT ROWID;

CREATE INDEX stage6d_capacity_pool_idx
    ON stage6d_capacity_result(run_id, pool_id, profile_id, scenario_id);

CREATE TABLE stage6d_supply_node (
    node_id TEXT PRIMARY KEY,
    node_kind TEXT NOT NULL CHECK(node_kind IN (
        'BARONY','HAUS_SHARED','MOBILE_POOL','UNRESOLVED_SITE_CONTEXT','EXTERNAL_BOUNDARY'
    )),
    barony_id INTEGER,
    haus_id TEXT,
    economic_network_id TEXT NOT NULL,
    evidence_status TEXT NOT NULL CHECK(evidence_status IN {READINESS_STATES}),
    basis_json TEXT NOT NULL CHECK(json_valid(basis_json)),
    identity_fingerprint TEXT NOT NULL
) WITHOUT ROWID;

CREATE INDEX stage6d_supply_node_economic_network_idx
    ON stage6d_supply_node(economic_network_id);

CREATE TABLE stage6d_food_bundle (
    food_bundle_id TEXT PRIMARY KEY,
    bundle_name TEXT NOT NULL,
    unit_code TEXT NOT NULL CHECK(unit_code = 'MILLI_PERSON_YEAR'),
    component_json TEXT NOT NULL CHECK(json_valid(component_json)),
    evidence_status TEXT NOT NULL CHECK(evidence_status IN {READINESS_STATES}),
    rule_fingerprint TEXT NOT NULL
) WITHOUT ROWID;

CREATE TABLE stage6d_haus_food_support_policy (
    haus_id TEXT PRIMARY KEY,
    food_support_class TEXT NOT NULL,
    food_production_factor REAL NOT NULL CHECK(food_production_factor >= 0),
    reserve_factor REAL NOT NULL CHECK(reserve_factor >= 1),
    import_priority_factor REAL NOT NULL CHECK(import_priority_factor >= 0),
    within_network_redistribution_allowed INTEGER NOT NULL CHECK(
        within_network_redistribution_allowed IN (0,1)
    ),
    gross_food_product_trade_status TEXT NOT NULL CHECK(
        gross_food_product_trade_status IN (
            'FOUND','POSSIBLE_NOT_QUANTIFIED','NOT_APPLICABLE'
        )
    ),
    cross_network_net_support_role TEXT NOT NULL,
    evidence_status TEXT NOT NULL CHECK(evidence_status IN {READINESS_STATES}),
    evidence_json TEXT NOT NULL CHECK(json_valid(evidence_json)),
    rule_fingerprint TEXT NOT NULL,
    canon_status TEXT NOT NULL CHECK(canon_status = '{CANON_STATUS}')
) WITHOUT ROWID;

CREATE TABLE stage6d_local_supply_source (
    supply_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES stage6d_run(run_id) ON DELETE CASCADE,
    node_id TEXT NOT NULL REFERENCES stage6d_supply_node(node_id),
    food_bundle_id TEXT NOT NULL REFERENCES stage6d_food_bundle(food_bundle_id),
    source_kind TEXT NOT NULL,
    amount_milli_person_years INTEGER NOT NULL CHECK(amount_milli_person_years >= 0),
    source_haus_id TEXT,
    evidence_status TEXT NOT NULL CHECK(evidence_status IN {READINESS_STATES}),
    evidence_json TEXT NOT NULL CHECK(json_valid(evidence_json)),
    input_fingerprint TEXT NOT NULL
) WITHOUT ROWID;

CREATE INDEX stage6d_local_supply_node_idx
    ON stage6d_local_supply_source(run_id, node_id, food_bundle_id);
CREATE INDEX stage6d_local_supply_haus_idx
    ON stage6d_local_supply_source(source_haus_id);

CREATE TABLE stage6d_trade_flow (
    flow_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES stage6d_run(run_id) ON DELETE CASCADE,
    scenario_id TEXT NOT NULL REFERENCES stage6d_scenario(scenario_id),
    food_bundle_id TEXT NOT NULL REFERENCES stage6d_food_bundle(food_bundle_id),
    source_node_id TEXT NOT NULL REFERENCES stage6d_supply_node(node_id),
    destination_node_id TEXT NOT NULL REFERENCES stage6d_supply_node(node_id),
    flow_scope TEXT NOT NULL CHECK(flow_scope IN (
        'WITHIN_ECONOMIC_NETWORK','CROSS_NETWORK_PRINCIPAL_STAPLE_SUPPORT'
    )),
    dispatched_milli_person_years INTEGER NOT NULL CHECK(dispatched_milli_person_years >= 0),
    delivered_milli_person_years INTEGER NOT NULL CHECK(delivered_milli_person_years >= 0),
    loss_milli_person_years INTEGER NOT NULL CHECK(loss_milli_person_years >= 0),
    route_evidence_status TEXT NOT NULL CHECK(route_evidence_status IN {ROUTE_EVIDENCE_STATES}),
    route_basis_json TEXT NOT NULL CHECK(json_valid(route_basis_json)),
    input_fingerprint TEXT NOT NULL,
    CHECK(source_node_id <> destination_node_id),
    CHECK(dispatched_milli_person_years =
          delivered_milli_person_years + loss_milli_person_years),
    CHECK(dispatched_milli_person_years = 0 OR
          route_evidence_status IN ('FOUND','WORKING_PROXY'))
) WITHOUT ROWID;

CREATE INDEX stage6d_trade_flow_source_idx
    ON stage6d_trade_flow(run_id, scenario_id, source_node_id, food_bundle_id);
CREATE INDEX stage6d_trade_flow_destination_idx
    ON stage6d_trade_flow(run_id, scenario_id, destination_node_id, food_bundle_id);

CREATE TABLE stage6d_food_reserve (
    run_id TEXT NOT NULL REFERENCES stage6d_run(run_id) ON DELETE CASCADE,
    scenario_id TEXT NOT NULL REFERENCES stage6d_scenario(scenario_id),
    node_id TEXT NOT NULL REFERENCES stage6d_supply_node(node_id),
    food_bundle_id TEXT NOT NULL REFERENCES stage6d_food_bundle(food_bundle_id),
    opening_stock_milli_person_years INTEGER NOT NULL CHECK(opening_stock_milli_person_years >= 0),
    reserve_draw_milli_person_years INTEGER NOT NULL CHECK(reserve_draw_milli_person_years >= 0),
    reserve_add_milli_person_years INTEGER NOT NULL CHECK(reserve_add_milli_person_years >= 0),
    closing_stock_milli_person_years INTEGER NOT NULL CHECK(closing_stock_milli_person_years >= 0),
    evidence_status TEXT NOT NULL CHECK(evidence_status IN {READINESS_STATES}),
    explanation_json TEXT NOT NULL CHECK(json_valid(explanation_json)),
    PRIMARY KEY(run_id, scenario_id, node_id, food_bundle_id),
    CHECK(opening_stock_milli_person_years + reserve_add_milli_person_years =
          closing_stock_milli_person_years + reserve_draw_milli_person_years)
) WITHOUT ROWID;

CREATE TABLE stage6d_food_balance (
    run_id TEXT NOT NULL REFERENCES stage6d_run(run_id) ON DELETE CASCADE,
    scenario_id TEXT NOT NULL REFERENCES stage6d_scenario(scenario_id),
    node_id TEXT NOT NULL REFERENCES stage6d_supply_node(node_id),
    food_bundle_id TEXT NOT NULL REFERENCES stage6d_food_bundle(food_bundle_id),
    local_supply_milli_person_years INTEGER NOT NULL CHECK(local_supply_milli_person_years >= 0),
    imports_milli_person_years INTEGER NOT NULL CHECK(imports_milli_person_years >= 0),
    reserve_draw_milli_person_years INTEGER NOT NULL CHECK(reserve_draw_milli_person_years >= 0),
    exports_milli_person_years INTEGER NOT NULL CHECK(exports_milli_person_years >= 0),
    consumption_milli_person_years INTEGER NOT NULL CHECK(consumption_milli_person_years >= 0),
    reserve_add_milli_person_years INTEGER NOT NULL CHECK(reserve_add_milli_person_years >= 0),
    local_loss_milli_person_years INTEGER NOT NULL CHECK(local_loss_milli_person_years >= 0),
    demand_milli_person_years INTEGER NOT NULL CHECK(demand_milli_person_years >= 0),
    unmet_demand_milli_person_years INTEGER NOT NULL CHECK(unmet_demand_milli_person_years >= 0),
    evidence_status TEXT NOT NULL CHECK(evidence_status IN {READINESS_STATES}),
    explanation_json TEXT NOT NULL CHECK(json_valid(explanation_json)),
    PRIMARY KEY(run_id, scenario_id, node_id, food_bundle_id),
    FOREIGN KEY(run_id, scenario_id, node_id, food_bundle_id)
        REFERENCES stage6d_food_reserve(run_id, scenario_id, node_id, food_bundle_id),
    CHECK(
        local_supply_milli_person_years + imports_milli_person_years +
        reserve_draw_milli_person_years
        =
        exports_milli_person_years + consumption_milli_person_years +
        reserve_add_milli_person_years + local_loss_milli_person_years
    ),
    CHECK(demand_milli_person_years =
          consumption_milli_person_years + unmet_demand_milli_person_years)
) WITHOUT ROWID;

CREATE TABLE stage6d_pool_node_allocation (
    run_id TEXT NOT NULL,
    pool_id TEXT NOT NULL,
    profile_id TEXT NOT NULL,
    node_id TEXT NOT NULL REFERENCES stage6d_supply_node(node_id),
    allocation_millionths INTEGER NOT NULL CHECK(
        allocation_millionths > 0 AND allocation_millionths <= 1000000
    ),
    evidence_status TEXT NOT NULL CHECK(evidence_status IN {READINESS_STATES}),
    basis_json TEXT NOT NULL CHECK(json_valid(basis_json)),
    identity_fingerprint TEXT NOT NULL UNIQUE,
    PRIMARY KEY(run_id, pool_id, profile_id, node_id),
    FOREIGN KEY(run_id, pool_id, profile_id)
        REFERENCES stage6d_population_assignment(run_id, pool_id, profile_id)
        ON DELETE CASCADE
) WITHOUT ROWID;

CREATE TABLE stage6d_population_food_demand (
    run_id TEXT NOT NULL,
    scenario_id TEXT NOT NULL REFERENCES stage6d_scenario(scenario_id),
    pool_id TEXT NOT NULL,
    profile_id TEXT NOT NULL,
    node_id TEXT NOT NULL,
    food_bundle_id TEXT NOT NULL REFERENCES stage6d_food_bundle(food_bundle_id),
    population_count_basis INTEGER CHECK(
        population_count_basis IS NULL OR population_count_basis >= 0
    ),
    demand_per_counting_unit INTEGER CHECK(
        demand_per_counting_unit IS NULL OR demand_per_counting_unit >= 0
    ),
    allocation_millionths INTEGER NOT NULL CHECK(
        allocation_millionths > 0 AND allocation_millionths <= 1000000
    ),
    demand_milli_person_years INTEGER CHECK(
        demand_milli_person_years IS NULL OR demand_milli_person_years >= 0
    ),
    included_in_balance INTEGER NOT NULL CHECK(included_in_balance IN (0,1)),
    evidence_status TEXT NOT NULL CHECK(evidence_status IN {READINESS_STATES}),
    basis_json TEXT NOT NULL CHECK(json_valid(basis_json)),
    input_fingerprint TEXT NOT NULL,
    PRIMARY KEY(run_id, scenario_id, pool_id, profile_id, node_id, food_bundle_id),
    FOREIGN KEY(run_id, pool_id, profile_id, node_id)
        REFERENCES stage6d_pool_node_allocation(run_id, pool_id, profile_id, node_id)
        ON DELETE CASCADE,
    CHECK(
        (included_in_balance = 1 AND population_count_basis IS NOT NULL AND
         demand_per_counting_unit IS NOT NULL AND demand_milli_person_years IS NOT NULL)
        OR
        (included_in_balance = 0 AND demand_milli_person_years IS NULL)
    )
) WITHOUT ROWID;

CREATE TABLE stage6d_population_attribution (
    pool_id TEXT NOT NULL REFERENCES stage6d_population_pool(pool_id) ON DELETE CASCADE,
    hierarchy_level TEXT NOT NULL CHECK(hierarchy_level IN (
        'BARONY','COUNTY','DUCHY','HAUS','WORLD'
    )),
    hierarchy_id TEXT NOT NULL,
    counting_role TEXT NOT NULL CHECK(counting_role = 'PRIMARY_COUNT'),
    basis_json TEXT NOT NULL CHECK(json_valid(basis_json)),
    PRIMARY KEY(pool_id, hierarchy_level)
) WITHOUT ROWID;

CREATE INDEX stage6d_attribution_hierarchy_idx
    ON stage6d_population_attribution(hierarchy_level, hierarchy_id);

CREATE TABLE stage6d_exception (
    exception_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES stage6d_run(run_id) ON DELETE CASCADE,
    subject_kind TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    severity TEXT NOT NULL CHECK(severity IN ('INFO','WARN','HIGH','BLOCKING')),
    exception_code TEXT NOT NULL,
    evidence_status TEXT NOT NULL CHECK(evidence_status IN {READINESS_STATES}),
    details_json TEXT NOT NULL CHECK(json_valid(details_json)),
    review_status TEXT NOT NULL
) WITHOUT ROWID;

CREATE TRIGGER stage6d_bonded_single_number_insert
BEFORE INSERT ON stage6d_population_estimate
WHEN (SELECT population_class FROM stage6d_population_profile
      WHERE profile_id = NEW.profile_id) = 'BONDED_HUMAN'
     AND (NEW.population_low IS NOT NULL OR NEW.population_high IS NOT NULL)
BEGIN
    SELECT RAISE(ABORT, 'bonded humans use one population number; stage bands are prohibited');
END;

CREATE TRIGGER stage6d_bonded_single_number_update
BEFORE UPDATE OF profile_id, population_low, population_high
ON stage6d_population_estimate
WHEN (SELECT population_class FROM stage6d_population_profile
      WHERE profile_id = NEW.profile_id) = 'BONDED_HUMAN'
     AND (NEW.population_low IS NOT NULL OR NEW.population_high IS NOT NULL)
BEGIN
    SELECT RAISE(ABORT, 'bonded humans use one population number; stage bands are prohibited');
END;

CREATE TRIGGER stage6d_autarky_no_flow_insert
BEFORE INSERT ON stage6d_trade_flow
WHEN NEW.scenario_id = 'LOCAL_AUTARKIC'
BEGIN
    SELECT RAISE(ABORT, 'LOCAL_AUTARKIC prohibits inter-node trade flows');
END;

CREATE TRIGGER stage6d_autarky_no_flow_update
BEFORE UPDATE OF scenario_id ON stage6d_trade_flow
WHEN NEW.scenario_id = 'LOCAL_AUTARKIC'
BEGIN
    SELECT RAISE(ABORT, 'LOCAL_AUTARKIC prohibits inter-node trade flows');
END;

CREATE VIEW stage6d_hierarchy_population_ledger AS
SELECT
    e.run_id,
    a.hierarchy_level,
    a.hierarchy_id,
    p.population_class,
    p.biological_entity_id,
    p.counting_unit,
    SUM(e.working_population) AS working_population,
    COUNT(*) AS contributing_pool_count
FROM stage6d_population_estimate AS e
JOIN stage6d_population_profile AS p USING(profile_id)
JOIN stage6d_population_attribution AS a USING(pool_id)
WHERE e.working_population IS NOT NULL
GROUP BY e.run_id, a.hierarchy_level, a.hierarchy_id,
         p.population_class, p.biological_entity_id, p.counting_unit;

CREATE VIEW stage6d_settlement_population_ledger AS
SELECT
    e.run_id,
    pool.primary_settlement_id AS settlement_id,
    p.population_class,
    p.biological_entity_id,
    p.counting_unit,
    SUM(e.working_population) AS working_population,
    COUNT(*) AS contributing_pool_count
FROM stage6d_population_estimate AS e
JOIN stage6d_population_profile AS p USING(profile_id)
JOIN stage6d_population_pool AS pool USING(pool_id)
WHERE e.working_population IS NOT NULL
  AND pool.primary_settlement_id IS NOT NULL
GROUP BY e.run_id, pool.primary_settlement_id,
         p.population_class, p.biological_entity_id, p.counting_unit;

CREATE VIEW stage6d_settlement_human_population AS
SELECT
    e.run_id,
    pool.primary_settlement_id AS settlement_id,
    SUM(CASE WHEN p.population_class='UNBONDED_HUMAN'
             THEN e.working_population ELSE 0 END) AS ordinary_unbonded_humans,
    SUM(CASE WHEN p.population_class='BONDED_HUMAN'
             THEN e.working_population ELSE 0 END) AS bonded_humans,
    SUM(e.working_population) AS human_total
FROM stage6d_population_estimate AS e
JOIN stage6d_population_profile AS p USING(profile_id)
JOIN stage6d_population_pool AS pool USING(pool_id)
WHERE e.working_population IS NOT NULL
  AND p.population_class IN ('UNBONDED_HUMAN','BONDED_HUMAN')
  AND pool.primary_settlement_id IS NOT NULL
GROUP BY e.run_id, pool.primary_settlement_id;

CREATE VIEW stage6d_hierarchy_human_population AS
SELECT
    e.run_id,
    a.hierarchy_level,
    a.hierarchy_id,
    SUM(CASE WHEN p.population_class='UNBONDED_HUMAN'
             THEN e.working_population ELSE 0 END) AS ordinary_unbonded_humans,
    SUM(CASE WHEN p.population_class='BONDED_HUMAN'
             THEN e.working_population ELSE 0 END) AS bonded_humans,
    SUM(e.working_population) AS human_total,
    COUNT(DISTINCT e.pool_id) AS contributing_pool_count
FROM stage6d_population_estimate AS e
JOIN stage6d_population_profile AS p USING(profile_id)
JOIN stage6d_population_attribution AS a USING(pool_id)
WHERE e.working_population IS NOT NULL
  AND p.population_class IN ('UNBONDED_HUMAN','BONDED_HUMAN')
GROUP BY e.run_id, a.hierarchy_level, a.hierarchy_id;
"""


def _rows_as_dicts(connection: sqlite3.Connection, query: str) -> list[dict[str, Any]]:
    cursor = connection.execute(query)
    names = [description[0] for description in cursor.description]
    if len(names) != len(set(names)):
        raise RuntimeError(f"Duplicate source-projection columns: {names}")
    return [dict(zip(names, row)) for row in cursor]


def _table_exists(connection: sqlite3.Connection, name: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def _source_identity(
    connection: sqlite3.Connection,
    *,
    source_rows: list[dict[str, Any]],
    physical_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    identity: dict[str, Any] = {
        "contract": "STAGE6D_EXPLICIT_SITE_PROJECTION_V3",
        "source_projection": {
            "row_count": len(source_rows),
            "semantic_sha256": semantic_rows_sha256(source_rows),
        },
        "stage6c5r_physical_context": {
            "row_count": len(physical_rows),
            "semantic_sha256": semantic_rows_sha256(physical_rows),
        },
    }
    if _table_exists(connection, "stage6c5_run_metadata"):
        connection.row_factory = sqlite3.Row
        row = connection.execute("SELECT * FROM stage6c5_run_metadata").fetchone()
        if row is not None:
            values = dict(row)
            identity["stage6c5"] = {
                key: values[key]
                for key in ("method_version", "canon_status")
                if key in values
            }
    if _table_exists(connection, "stage6c5r_run_metadata"):
        connection.row_factory = sqlite3.Row
        row = connection.execute("SELECT * FROM stage6c5r_run_metadata").fetchone()
        if row is not None:
            values = dict(row)
            identity["stage6c5r"] = {
                key: values[key]
                for key in ("method", "scope", "canon_status")
                if key in values
            }
    return identity


def _assert_checkpointed_source(source_database: Path) -> None:
    """Reject a source that may still carry committed or live WAL state."""

    companions = [
        Path(str(source_database) + "-wal"),
        Path(str(source_database) + "-shm"),
    ]
    present = [str(path) for path in companions if path.exists()]
    if present:
        raise RuntimeError(
            "Stage 6D requires a closed, checkpointed source database; "
            f"remove no files manually, close/checkpoint the writer first: {present}"
        )


def create_sidecar(
    source_database: Path,
    destination: Path,
    *,
    expected_active_sites: int | None = None,
    rule_bundle_fingerprint: str | None = None,
) -> dict[str, Any]:
    """Create an atomic Stage 6D schema-ready sidecar from a read-only source."""

    source_database = source_database.resolve()
    destination = destination.resolve()
    _assert_checkpointed_source(source_database)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    if temporary.exists():
        temporary.unlink()

    source = sqlite3.connect(f"file:{source_database.as_posix()}?mode=ro", uri=True)
    source.execute("PRAGMA query_only=ON")
    source.execute("BEGIN")
    output = sqlite3.connect(temporary)
    try:
        source_rows = _rows_as_dicts(
            source,
            "SELECT * FROM (" + STAGE6D_ALL_ACTIVE_SOURCE_SELECT + ") ORDER BY settlement_id",
        )
        if expected_active_sites is not None and len(source_rows) != expected_active_sites:
            raise RuntimeError(
                f"Active-site count mismatch: {len(source_rows)} != {expected_active_sites}"
            )
        physical_rows: list[dict[str, Any]] = []
        if _table_exists(source, "stage6c5r_site_physical_context"):
            physical_rows = _rows_as_dicts(
                source,
                """
                SELECT settlement_id, semantic_key, array_digest,
                       pilot_site_gate_pass, metrics_json, canon_status
                FROM stage6c5r_site_physical_context
                ORDER BY settlement_id
                """,
            )
        source_identity = _source_identity(
            source, source_rows=source_rows, physical_rows=physical_rows
        )
        source_semantic_sha256 = sha256_text(canonical_json(source_identity))
        recipe = {
            "method_version": METHOD_VERSION,
            "population_is_distinct_from_capacity": True,
            "bonded_human_population_columns": ["working_population"],
            "bond_stage_distribution_modelled": False,
            "mobile_anchor_populations_counted_once": True,
            "food_ledger_unit": "MILLI_PERSON_YEAR",
            "trade_flow_conservation_required": True,
            "scenarios": SCENARIO_PARAMETERS,
            "rule_bundle_fingerprint": rule_bundle_fingerprint,
        }
        run_id = "S6D-" + sha256_text(
            canonical_json({"source": source_identity, "recipe": recipe})
        )[:24].upper()

        output.executescript(SIDECAR_DDL)
        output.execute(
            """
            INSERT INTO stage6d_run (
                run_id, created_utc, schema_version, method_version,
                source_semantic_sha256, source_identity_json, recipe_json,
                canon_status, completion_state
            ) VALUES (?,?,?,?,?,?,?,?,?)
            """,
            (
                run_id,
                utc_now(),
                SCHEMA_VERSION,
                METHOD_VERSION,
                source_semantic_sha256,
                canonical_json(source_identity),
                canonical_json(recipe),
                CANON_STATUS,
                "SCHEMA_READY",
            ),
        )
        output.executemany(
            """
            INSERT INTO stage6d_scenario (
                scenario_id, scenario_order, description,
                parameter_json, readiness_status
            ) VALUES (?,?,?,?,?)
            """,
            [
                (
                    scenario_id,
                    order,
                    description,
                    canonical_json(SCENARIO_PARAMETERS[scenario_id]),
                    "INCOMPLETE",
                )
                for scenario_id, order, description in SCENARIOS
            ],
        )

        columns = list(source_rows[0]) if source_rows else []
        if columns:
            placeholders = ",".join("?" for _ in columns)
            output.executemany(
                f"INSERT INTO stage6d_source_site ({','.join(columns)}) VALUES ({placeholders})",
                [[row[column] for column in columns] for row in source_rows],
            )

        physical_count = 0
        if physical_rows:
            output.executemany(
                """
                UPDATE stage6d_source_site
                SET stage6c5r_semantic_key=?, stage6c5r_array_digest=?,
                    stage6c5r_pilot_site_gate_pass=?, stage6c5r_metrics_json=?,
                    stage6c5r_canon_status=?
                WHERE settlement_id=?
                """,
                [
                    (
                        row["semantic_key"], row["array_digest"],
                        row["pilot_site_gate_pass"], row["metrics_json"],
                        row["canon_status"], row["settlement_id"],
                    )
                    for row in physical_rows
                ],
            )
            physical_count = len(physical_rows)

        foreign_key_failures = output.execute("PRAGMA foreign_key_check").fetchall()
        if foreign_key_failures:
            raise RuntimeError(f"Foreign-key failures: {foreign_key_failures[:10]}")
        integrity = output.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"Sidecar integrity failure: {integrity}")
        output.commit()
    except Exception:
        output.close()
        source.close()
        if temporary.exists():
            temporary.unlink()
        raise
    else:
        output.close()
        source.close()
        os.replace(temporary, destination)

    return {
        "status": "PASS",
        "run_id": run_id,
        "schema_version": SCHEMA_VERSION,
        "canon_status": CANON_STATUS,
        "source_site_count": len(source_rows),
        "stage6c5_refined_site_count": sum(
            row["stage6c5_semantic_key"] is not None for row in source_rows
        ),
        "stage6c5r_physical_site_count": physical_count,
        "scenario_count": len(SCENARIOS),
        "destination": str(destination),
    }


def validate_view(connection: sqlite3.Connection, *, expected_rows: int | None = None) -> dict[str, Any]:
    """Fail-closed validation for the Stage 6C.5 compatibility view."""

    sql_row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type='view' AND name='stage6c5_stage6d_inputs'"
    ).fetchone()
    if sql_row is None:
        raise RuntimeError("stage6c5_stage6d_inputs view is missing")
    sql = str(sql_row[0])
    if "stage6_population_model" in sql or "*" in sql:
        raise RuntimeError("Stage 6D view contains a removed or ambiguous projection")
    cursor = connection.execute("SELECT * FROM stage6c5_stage6d_inputs LIMIT 0")
    columns = [description[0] for description in cursor.description]
    if len(columns) != len(set(columns)):
        raise RuntimeError(f"Stage 6D view contains duplicate columns: {columns}")
    expected_cursor = connection.execute(
        "SELECT * FROM (" + STAGE6C5_STAGE6D_VIEW_SELECT + ") LIMIT 0"
    )
    expected_columns = [description[0] for description in expected_cursor.description]
    if columns != expected_columns:
        raise RuntimeError(
            "Stage 6D view differs from the explicit source contract: "
            f"{columns} != {expected_columns}"
        )
    count = int(connection.execute("SELECT COUNT(*) FROM stage6c5_stage6d_inputs").fetchone()[0])
    if expected_rows is not None and count != expected_rows:
        raise RuntimeError(f"Stage 6D view row count {count} != {expected_rows}")
    return {"row_count": count, "column_count": len(columns), "columns": columns}


def validate_accounting(connection: sqlite3.Connection) -> dict[str, Any]:
    """Validate the sidecar's anti-duplication and food-conservation rules."""

    failures: list[str] = []
    foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
    if foreign_keys:
        failures.append(f"foreign_key_check={foreign_keys[:10]}")

    scenarios = {
        row[0] for row in connection.execute("SELECT scenario_id FROM stage6d_scenario")
    }
    expected_scenarios = {row[0] for row in SCENARIOS}
    if scenarios != expected_scenarios:
        failures.append(
            f"scenario_set={sorted(scenarios)} expected={sorted(expected_scenarios)}"
        )

    schema_objects = connection.execute(
        """
        SELECT name, type FROM sqlite_master
        WHERE name LIKE 'stage6d_%' AND type IN ('table','view')
        ORDER BY name
        """
    ).fetchall()
    for object_name, _ in schema_objects:
        columns = [
            str(row[1]).lower()
            for row in connection.execute(f"PRAGMA table_info({object_name})")
        ]
        prohibited = [name for name in columns if "bond_stage" in name]
        if prohibited:
            failures.append(f"{object_name}: prohibited bond-stage columns {prohibited}")

    bonded_bands = connection.execute(
        """
        SELECT COUNT(*)
        FROM stage6d_population_estimate AS e
        JOIN stage6d_population_profile AS p USING(profile_id)
        WHERE p.population_class='BONDED_HUMAN'
          AND (e.population_low IS NOT NULL OR e.population_high IS NOT NULL)
        """
    ).fetchone()[0]
    if bonded_bands:
        failures.append(f"bonded_population_band_rows={bonded_bands}")

    autarkic_flows = connection.execute(
        "SELECT COUNT(*) FROM stage6d_trade_flow WHERE scenario_id='LOCAL_AUTARKIC'"
    ).fetchone()[0]
    if autarkic_flows:
        failures.append(f"autarkic_trade_flows={autarkic_flows}")

    unbalanced_flows = connection.execute(
        """
        SELECT COUNT(*) FROM stage6d_trade_flow
        WHERE dispatched_milli_person_years <>
              delivered_milli_person_years + loss_milli_person_years
        """
    ).fetchone()[0]
    if unbalanced_flows:
        failures.append(f"unbalanced_trade_flows={unbalanced_flows}")

    invalid_internal_scope = connection.execute(
        """
        SELECT COUNT(*)
        FROM stage6d_trade_flow AS f
        JOIN stage6d_supply_node AS source
          ON source.node_id=f.source_node_id
        JOIN stage6d_supply_node AS destination
          ON destination.node_id=f.destination_node_id
        WHERE f.flow_scope='WITHIN_ECONOMIC_NETWORK'
          AND source.economic_network_id <> destination.economic_network_id
        """
    ).fetchone()[0]
    if invalid_internal_scope:
        failures.append(f"invalid_within_network_flow_scope={invalid_internal_scope}")

    invalid_cross_scope = connection.execute(
        """
        SELECT COUNT(*)
        FROM stage6d_trade_flow AS f
        JOIN stage6d_supply_node AS source
          ON source.node_id=f.source_node_id
        JOIN stage6d_supply_node AS destination
          ON destination.node_id=f.destination_node_id
        WHERE f.flow_scope='CROSS_NETWORK_PRINCIPAL_STAPLE_SUPPORT'
          AND (
              source.economic_network_id = destination.economic_network_id
              OR source.haus_id NOT IN ('EREMITENSCHALE','MARIENHAIN')
          )
        """
    ).fetchone()[0]
    if invalid_cross_scope:
        failures.append(f"invalid_cross_network_flow_scope={invalid_cross_scope}")

    balance_count = int(
        connection.execute("SELECT COUNT(*) FROM stage6d_food_balance").fetchone()[0]
    )
    ledger_mismatches = connection.execute(
        """
        WITH local AS (
            SELECT run_id, node_id, food_bundle_id,
                   SUM(amount_milli_person_years) AS amount
            FROM stage6d_local_supply_source
            GROUP BY run_id, node_id, food_bundle_id
        ), imported AS (
            SELECT run_id, scenario_id, destination_node_id AS node_id,
                   food_bundle_id, SUM(delivered_milli_person_years) AS amount
            FROM stage6d_trade_flow
            GROUP BY run_id, scenario_id, destination_node_id, food_bundle_id
        ), exported AS (
            SELECT run_id, scenario_id, source_node_id AS node_id,
                   food_bundle_id, SUM(dispatched_milli_person_years) AS amount
            FROM stage6d_trade_flow
            GROUP BY run_id, scenario_id, source_node_id, food_bundle_id
        )
        SELECT b.run_id, b.scenario_id, b.node_id, b.food_bundle_id
        FROM stage6d_food_balance AS b
        LEFT JOIN local AS l USING(run_id, node_id, food_bundle_id)
        LEFT JOIN imported AS i USING(run_id, scenario_id, node_id, food_bundle_id)
        LEFT JOIN exported AS e USING(run_id, scenario_id, node_id, food_bundle_id)
        WHERE b.local_supply_milli_person_years <> COALESCE(l.amount,0)
           OR b.imports_milli_person_years <> COALESCE(i.amount,0)
           OR b.exports_milli_person_years <> COALESCE(e.amount,0)
        LIMIT 10
        """
    ).fetchall()
    if ledger_mismatches:
        failures.append(f"food_ledger_mismatches={ledger_mismatches}")

    reserve_mismatches = connection.execute(
        """
        SELECT b.run_id, b.scenario_id, b.node_id, b.food_bundle_id
        FROM stage6d_food_balance AS b
        JOIN stage6d_food_reserve AS r
          USING(run_id, scenario_id, node_id, food_bundle_id)
        WHERE b.reserve_draw_milli_person_years <> r.reserve_draw_milli_person_years
           OR b.reserve_add_milli_person_years <> r.reserve_add_milli_person_years
        LIMIT 10
        """
    ).fetchall()
    if reserve_mismatches:
        failures.append(f"reserve_ledger_mismatches={reserve_mismatches}")

    allocation_mismatches = connection.execute(
        """
        SELECT run_id, pool_id, profile_id, SUM(allocation_millionths)
        FROM stage6d_pool_node_allocation
        GROUP BY run_id, pool_id, profile_id
        HAVING SUM(allocation_millionths) <> 1000000
        LIMIT 10
        """
    ).fetchall()
    if allocation_mismatches:
        failures.append(f"pool_node_allocation_mismatches={allocation_mismatches}")

    demand_formula_mismatches = connection.execute(
        """
        SELECT d.run_id, d.scenario_id, d.pool_id, d.profile_id, d.node_id
        FROM stage6d_population_food_demand AS d
        JOIN stage6d_population_profile AS p USING(profile_id)
        JOIN stage6d_population_estimate AS e
          ON e.run_id=d.run_id AND e.pool_id=d.pool_id AND e.profile_id=d.profile_id
        JOIN stage6d_pool_node_allocation AS a
          ON a.run_id=d.run_id AND a.pool_id=d.pool_id
         AND a.profile_id=d.profile_id AND a.node_id=d.node_id
        WHERE d.allocation_millionths <> a.allocation_millionths
           OR (d.included_in_balance=1 AND (
                d.population_count_basis <> e.working_population OR
                d.demand_per_counting_unit <> p.food_demand_milliunits_per_counting_unit OR
                d.demand_milli_person_years <>
                    ((d.population_count_basis * d.demand_per_counting_unit *
                      d.allocation_millionths + 500000) / 1000000)
              ))
        LIMIT 10
        """
    ).fetchall()
    if demand_formula_mismatches:
        failures.append(f"population_demand_formula_mismatches={demand_formula_mismatches}")

    node_demand_mismatches = connection.execute(
        """
        WITH demand AS (
            SELECT run_id, scenario_id, node_id, food_bundle_id,
                   SUM(demand_milli_person_years) AS amount
            FROM stage6d_population_food_demand
            WHERE included_in_balance=1
            GROUP BY run_id, scenario_id, node_id, food_bundle_id
        )
        SELECT b.run_id, b.scenario_id, b.node_id, b.food_bundle_id
        FROM stage6d_food_balance AS b
        LEFT JOIN demand AS d USING(run_id, scenario_id, node_id, food_bundle_id)
        WHERE b.demand_milli_person_years <> COALESCE(d.amount,0)
        LIMIT 10
        """
    ).fetchall()
    if node_demand_mismatches:
        failures.append(f"node_demand_mismatches={node_demand_mismatches}")

    capacity_consumption_mismatches = connection.execute(
        """
        WITH capacity_consumption AS (
            SELECT c.run_id, c.scenario_id, a.node_id, d.food_bundle_id,
                   SUM((c.capacity_central * a.allocation_millionths + 500000) /
                       1000000) AS capacity_people
            FROM stage6d_capacity_result AS c
            JOIN stage6d_pool_node_allocation AS a
              ON a.run_id=c.run_id AND a.pool_id=c.pool_id
             AND a.profile_id=c.profile_id
            JOIN stage6d_population_food_demand AS d
              ON d.run_id=c.run_id AND d.scenario_id=c.scenario_id
             AND d.pool_id=c.pool_id AND d.profile_id=c.profile_id
             AND d.node_id=a.node_id
            WHERE c.capacity_central IS NOT NULL AND d.included_in_balance=1
            GROUP BY c.run_id, c.scenario_id, a.node_id, d.food_bundle_id
        )
        SELECT b.run_id, b.scenario_id, b.node_id, b.food_bundle_id
        FROM stage6d_food_balance AS b
        LEFT JOIN capacity_consumption AS c
          USING(run_id, scenario_id, node_id, food_bundle_id)
        WHERE (b.consumption_milli_person_years / 1000) <>
              COALESCE(c.capacity_people,0)
        LIMIT 10
        """
    ).fetchall()
    if capacity_consumption_mismatches:
        failures.append(
            f"capacity_consumption_mismatches={capacity_consumption_mismatches}"
        )

    global_conservation_mismatches = connection.execute(
        """
        WITH losses AS (
            SELECT run_id, scenario_id, food_bundle_id,
                   SUM(loss_milli_person_years) AS amount
            FROM stage6d_trade_flow
            GROUP BY run_id, scenario_id, food_bundle_id
        ), totals AS (
            SELECT run_id, scenario_id, food_bundle_id,
                   SUM(local_supply_milli_person_years) AS local_supply,
                   SUM(reserve_draw_milli_person_years) AS reserve_draw,
                   SUM(consumption_milli_person_years) AS consumption,
                   SUM(reserve_add_milli_person_years) AS reserve_add,
                   SUM(local_loss_milli_person_years) AS local_loss
            FROM stage6d_food_balance
            GROUP BY run_id, scenario_id, food_bundle_id
        )
        SELECT t.run_id, t.scenario_id, t.food_bundle_id
        FROM totals AS t
        LEFT JOIN losses AS l USING(run_id, scenario_id, food_bundle_id)
        WHERE t.local_supply + t.reserve_draw <>
              t.consumption + t.reserve_add + t.local_loss + COALESCE(l.amount,0)
        LIMIT 10
        """
    ).fetchall()
    if global_conservation_mismatches:
        failures.append(
            f"global_food_conservation_mismatches={global_conservation_mismatches}"
        )

    orphan_flow_balances = connection.execute(
        """
        SELECT COUNT(*)
        FROM stage6d_trade_flow AS f
        LEFT JOIN stage6d_food_balance AS source_balance
          ON source_balance.run_id=f.run_id
         AND source_balance.scenario_id=f.scenario_id
         AND source_balance.node_id=f.source_node_id
         AND source_balance.food_bundle_id=f.food_bundle_id
        LEFT JOIN stage6d_food_balance AS destination_balance
          ON destination_balance.run_id=f.run_id
         AND destination_balance.scenario_id=f.scenario_id
         AND destination_balance.node_id=f.destination_node_id
         AND destination_balance.food_bundle_id=f.food_bundle_id
        WHERE source_balance.node_id IS NULL OR destination_balance.node_id IS NULL
        """
    ).fetchone()[0]
    if orphan_flow_balances:
        failures.append(f"flows_without_two_node_balances={orphan_flow_balances}")

    integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    if integrity != "ok":
        failures.append(f"integrity_check={integrity}")
    if failures:
        raise RuntimeError("; ".join(failures))
    return {
        "status": "PASS",
        "scenario_count": len(scenarios),
        "food_balance_count": balance_count,
        "trade_flow_count": connection.execute(
            "SELECT COUNT(*) FROM stage6d_trade_flow"
        ).fetchone()[0],
        "population_estimate_count": connection.execute(
            "SELECT COUNT(*) FROM stage6d_population_estimate"
        ).fetchone()[0],
    }


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-active-sites", type=int)
    args = parser.parse_args(list(argv) if argv is not None else None)
    result = create_sidecar(
        args.source,
        args.output,
        expected_active_sites=args.expected_active_sites,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
