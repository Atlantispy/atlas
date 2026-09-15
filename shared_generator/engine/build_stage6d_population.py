#!/usr/bin/env python3
"""Build the Stage 6D population, food-support, and trade sidecar.

This is a transparent working-proposal model, not demographic canon.  It uses
the Stage 6C/6C.5 physical evidence without reopening terrain rasters, keeps
specialist three-dimensional capacities incomplete, counts mobile/shared
populations once, and conserves every unit of the human staple-food ledger.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sqlite3
from collections import defaultdict
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import stage6d_demographic_calibration as demographics
import stage6d_human_rules as human_rules
import stage6d_rules as rules
import stage6d_schema as schema
import stage6d_species_rules as species_rules
import stage6d_trade_solver as trade
import generation_runtime as runtime
import algorithm_policy


BUILDER_VERSION = "STAGE6D_FULL_REALM_BUILDER_V3"
FOOD_BUNDLE_ID = "HUMAN_STAPLE_PERSON_YEAR"
WORLD_ID = "DIADEM"
EXPLICIT_BREADBASKETS = frozenset({"EREMITENSCHALE", "MARIENHAIN"})
# Admission covers simultaneous parent/child batch objects and IPC copies, not
# the already-loaded complete realm model. A separate reserve covers each
# Python interpreter/import baseline. The fixture payload audit checks this
# estimate across every Haus; neither estimate is a hard process-RAM limit.
POPULATION_BATCH_SIZE = 64
POPULATION_BATCH_ESTIMATED_BYTES = 16 * 1024 * 1024
POPULATION_PROCESS_OVERHEAD_BYTES = 64 * 1024 * 1024
# Process startup lost at <=2,048 synthetic sites and won at 4,096; retain a
# conservative margin rather than switching at the measured crossover.
POPULATION_PROCESS_MIN_SITES = 8192


def _check_cancelled(cancel_event: Any) -> None:
    if cancel_event is not None:
        if not callable(getattr(cancel_event, "is_set", None)):
            raise TypeError("cancel_event must provide is_set()")
        if cancel_event.is_set():
            raise runtime.GenerationCancelled("Stage 6D generation cancelled")


def _validate_execution_options(workers: int, memory_budget_mb: int) -> None:
    if type(workers) is not int or workers < 1:
        raise ValueError("workers must be a positive integer")
    if type(memory_budget_mb) is not int or memory_budget_mb < 16:
        raise ValueError("memory_budget_mb must admit at least one 16 MiB population batch")


def _population_batches(items: Iterable[Any]) -> Iterable[tuple[Any, ...]]:
    batch: list[Any] = []
    for item in items:
        batch.append(item)
        if len(batch) == POPULATION_BATCH_SIZE:
            yield tuple(batch)
            batch = []
    if batch:
        yield tuple(batch)


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def combined_rule_fingerprint() -> str:
    executable_sources = {
        name: hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
        for name, module in (
            ("builder", __import__(__name__)),
            ("schema", schema),
            ("structural_rules", rules),
            ("human_catalogue", human_rules),
            ("demographic_calibration", demographics),
            ("species_catalogue", species_rules),
            ("trade_solver", trade),
        )
    }
    return fingerprint(
        {
            "builder_version": BUILDER_VERSION,
            "executable_source_sha256": executable_sources,
            "structural_rules": rules.rules_fingerprint(),
            "human_catalogue": human_rules.catalogue_fingerprint(),
            "demographic_calibration": demographics.calibration_fingerprint(),
            "species_catalogue": species_rules.catalogue_fingerprint(),
            "trade_solver": trade.METHOD_VERSION,
            "scenario_parameters": schema.SCENARIO_PARAMETERS,
            "breadbasket_exporters": sorted(EXPLICIT_BREADBASKETS),
        }
    )


def largest_remainder(
    total: int,
    weighted_keys: Sequence[tuple[str, int]],
) -> dict[str, int]:
    """Deterministically apportion ``total`` without losing an integer."""

    if total < 0:
        raise ValueError("apportionment total cannot be negative")
    ordered = sorted((str(key), int(weight)) for key, weight in weighted_keys)
    if any(weight < 0 for _, weight in ordered):
        raise ValueError("apportionment weights cannot be negative")
    denominator = sum(weight for _, weight in ordered)
    if not ordered:
        if total:
            raise ValueError("cannot apportion a positive total without recipients")
        return {}
    if denominator == 0:
        if total:
            raise ValueError("cannot apportion a positive total across zero weights")
        return {key: 0 for key, _ in ordered}
    if total > denominator:
        raise ValueError(f"capacity {total} exceeds population ceiling {denominator}")

    result: dict[str, int] = {}
    remainders: list[tuple[int, str]] = []
    allocated = 0
    for key, weight in ordered:
        quotient, remainder = divmod(total * weight, denominator)
        result[key] = quotient
        allocated += quotient
        remainders.append((remainder, key))
    for _, key in sorted(remainders, key=lambda item: (-item[0], item[1]))[: total - allocated]:
        result[key] += 1
    if sum(result.values()) != total:
        raise AssertionError("largest-remainder apportionment did not conserve total")
    if any(result[key] > weight for key, weight in ordered):
        raise AssertionError("largest-remainder apportionment exceeded a population weight")
    return result


def _row_fingerprint(site: Mapping[str, Any]) -> str:
    return fingerprint({key: site[key] for key in sorted(site)})


def _effective_xy(site: Mapping[str, Any]) -> tuple[float, float]:
    x = site.get("analysis_anchor_x_km")
    y = site.get("analysis_anchor_y_km")
    if x is None or y is None:
        x = site.get("display_x_km")
        y = site.get("display_y_km")
    if x is None or y is None:
        raise RuntimeError(f"site {site.get('settlement_id')} has no usable coordinates")
    return float(x), float(y)


def _node_id_for_site(site: Mapping[str, Any]) -> str:
    haus_id = str(site.get("owner_haus_id") or "").upper()
    if haus_id in EXPLICIT_BREADBASKETS:
        # One Haus-wide node ensures the breadbasket's complete resident demand
        # and bounded reserve are paid before any territorial surplus exports.
        return f"BREADBASKET::{haus_id}"
    if site.get("barony_id") is not None:
        network_id = str(site.get("economic_network_id") or "UNRESOLVED_NETWORK")
        if network_id.startswith("GREAT_FOREST::"):
            return f"BARONY::{int(site['barony_id'])}::NETWORK::{network_id}"
        return f"BARONY::{int(site['barony_id'])}"
    return f"UNRESOLVED::{site['settlement_id']}"


def _residence_type(
    haus_id: str,
    site: Mapping[str, Any],
    ordinary_gate: human_rules.SiteGateDecision,
    bonded_gate: human_rules.SiteGateDecision,
) -> str:
    form = str(site.get("realised_settlement_form") or "")
    if haus_id == "VERFUEHRSCHLUND" and (
        ordinary_gate.preference == "EMBEDDED_ONLY"
        or bonded_gate.preference == "EMBEDDED_ONLY"
    ):
        recognised = {
            "FOREST_FLOOR_CROWN_ENCLAVE_SETTLEMENT",
            "MOTHERS_MOUTH_CROWN_ENCLAVE",
            "EMBEDDED_NATIVE_ENCLAVE",
        }
        return form if form in recognised else "EMBEDDED_NATIVE_ENCLAVE"
    return form or demographics.calibration_for_haus(haus_id).default_residence_type


def _export_role(haus_id: str) -> str:
    if haus_id == "EREMITENSCHALE":
        return trade.EREMITENSCHALE_EXPORT_ROLE
    if haus_id == "MARIENHAIN":
        return trade.MARIENHAIN_EXPORT_ROLE
    return rules.policy_for_haus(haus_id).export_role


@dataclass
class SitePlan:
    site: dict[str, Any]
    pool_id: str
    node_id: str
    ordinary_gate: human_rules.SiteGateDecision
    bonded_gate: human_rules.SiteGateDecision
    residence_type: str
    structural_total: int | None
    structural_low: int | None
    structural_high: int | None
    structural_explanation: dict[str, Any]
    local_supply_milli: int
    local_supply_explanation: dict[str, Any]
    access_score: float
    x: float
    y: float
    import_priority: float
    storage_factor: float
    reserve_factor: float
    export_role: str
    economic_network_id: str
    within_network_redistribution_allowed: bool
    source_fingerprint: str
    working_total: int | None = None
    split: demographics.HumanSplit | None = None

    @property
    def settlement_id(self) -> str:
        return str(self.site["settlement_id"])

    @property
    def haus_id(self) -> str:
        return str(self.site["owner_haus_id"]).upper()


@dataclass
class NodeAccumulator:
    node_id: str
    node_kind: str
    barony_id: int | None
    haus_ids: set[str] = field(default_factory=set)
    plans: list[SitePlan] = field(default_factory=list)
    local_supply_milli: int = 0
    weighted_x: float = 0.0
    weighted_y: float = 0.0
    weighted_access: float = 0.0
    weighted_priority: float = 0.0
    coordinate_weight: int = 0
    storage_capacity_milli: int = 0
    reserve_factor: float = 1.0
    export_roles: set[str] = field(default_factory=set)
    economic_network_ids: set[str] = field(default_factory=set)
    within_network_permissions: set[bool] = field(default_factory=set)

    def add(self, plan: SitePlan) -> None:
        self.plans.append(plan)
        self.haus_ids.add(plan.haus_id)
        self.economic_network_ids.add(plan.economic_network_id)
        self.within_network_permissions.add(plan.within_network_redistribution_allowed)
        self.local_supply_milli += plan.local_supply_milli
        weight = max(1, int(plan.structural_total or 0))
        self.weighted_x += plan.x * weight
        self.weighted_y += plan.y * weight
        self.weighted_access += plan.access_score * weight
        self.weighted_priority += plan.import_priority * weight
        self.coordinate_weight += weight
        if plan.structural_total is not None:
            self.storage_capacity_milli += int(
                round(
                    plan.structural_total
                    * trade.MILLIUNITS_PER_PERSON_YEAR
                    * max(0.0, plan.storage_factor - 1.0)
                )
            )
        self.reserve_factor = max(self.reserve_factor, plan.reserve_factor)
        self.export_roles.add(plan.export_role)

    @property
    def x(self) -> float:
        return self.weighted_x / self.coordinate_weight

    @property
    def y(self) -> float:
        return self.weighted_y / self.coordinate_weight

    @property
    def access_score(self) -> float:
        return self.weighted_access / self.coordinate_weight

    @property
    def import_priority(self) -> float:
        return self.weighted_priority / self.coordinate_weight

    @property
    def export_role(self) -> str:
        cross_roles = self.export_roles & trade.ALLOWED_CROSS_NETWORK_SUPPORT_ROLES
        if len(cross_roles) > 1:
            raise RuntimeError(f"node {self.node_id} mixes two principal support roles")
        return next(iter(cross_roles), "ORDINARY_NETWORK")

    @property
    def economic_network_id(self) -> str:
        if len(self.economic_network_ids) != 1:
            raise RuntimeError(
                f"node {self.node_id} mixes economic networks: {sorted(self.economic_network_ids)}"
            )
        return next(iter(self.economic_network_ids))

    @property
    def within_network_redistribution_allowed(self) -> bool:
        return bool(self.within_network_permissions) and all(self.within_network_permissions)

    def demand(self, *, structural: bool) -> int:
        if structural:
            return sum(int(plan.structural_total or 0) for plan in self.plans)
        return sum(int(plan.working_total or 0) for plan in self.plans)

    def as_food_node(self, *, structural: bool) -> trade.FoodNode:
        return trade.FoodNode(
            node_id=self.node_id,
            local_supply_milli_person_years=self.local_supply_milli,
            working_demand_people=self.demand(structural=structural),
            access_score=self.access_score,
            x=self.x,
            y=self.y,
            export_role=self.export_role,
            economic_network_id=self.economic_network_id,
            within_network_redistribution_allowed=self.within_network_redistribution_allowed,
            reserve_factor=self.reserve_factor,
            storage_capacity_milli_person_years=self.storage_capacity_milli,
            import_priority=self.import_priority,
            opening_reserve_milli_person_years=0,
            reserve_evidence_status="INCOMPLETE",
        )


def _make_site_plans_serial(source_rows: Sequence[dict[str, Any]]) -> tuple[list[SitePlan], list[dict[str, Any]]]:
    plans: list[SitePlan] = []
    exceptions: list[dict[str, Any]] = []
    for site in source_rows:
        haus_id = str(site.get("owner_haus_id") or "").upper()
        if haus_id in {"DUFTFAEHRTE", "DUNKELHAUCH"}:
            continue
        rule = human_rules.rule_for_haus(haus_id)
        ordinary_gate = human_rules.gate_site(haus_id, human_rules.ORDINARY, site)
        bonded_gate = human_rules.gate_site(haus_id, human_rules.BONDED, site)
        if not ordinary_gate.allowed and not bonded_gate.allowed:
            exceptions.append(
                {
                    "subject_kind": "SETTLEMENT",
                    "subject_id": site["settlement_id"],
                    "severity": "INFO",
                    "exception_code": "NO_ELIGIBLE_HUMAN_RESIDENT_POOL",
                    "evidence_status": (
                        "PROVEN_ABSENT"
                        if ordinary_gate.evidence_status == bonded_gate.evidence_status == "PROVEN_ABSENT"
                        else "INCOMPLETE"
                    ),
                    "details": {
                        "ordinary_gate": vars(ordinary_gate),
                        "bonded_gate": vars(bonded_gate),
                        "haus_rule": rule.display_name,
                    },
                }
            )
            continue

        low, central, high, population_explanation = rules.structural_human_population_band(site)
        support_ratio, supply_explanation = rules.local_food_support_ratio(site)
        local_supply = (
            0
            if central is None
            else int(round(central * support_ratio * trade.MILLIUNITS_PER_PERSON_YEAR))
        )
        tier = rules.TIER_PRIORS.get(str(site.get("functional_tier") or ""))
        form_policy = rules.policy_for_form(site.get("realised_settlement_form"))
        haus_policy = rules.policy_for_haus(haus_id)
        x, y = _effective_xy(site)
        plan = SitePlan(
            site=site,
            pool_id=f"HUMAN_SITE::{site['settlement_id']}",
            node_id=_node_id_for_site(site),
            ordinary_gate=ordinary_gate,
            bonded_gate=bonded_gate,
            residence_type=_residence_type(haus_id, site, ordinary_gate, bonded_gate),
            structural_total=central,
            structural_low=low,
            structural_high=high,
            structural_explanation=population_explanation,
            local_supply_milli=local_supply,
            local_supply_explanation=supply_explanation,
            access_score=rules.effective_access_score(site),
            x=x,
            y=y,
            import_priority=(
                (0.7 if tier is None else tier.import_priority)
                * haus_policy.import_priority_factor
            ),
            storage_factor=form_policy.storage_factor,
            reserve_factor=haus_policy.export_reserve_factor,
            export_role=_export_role(haus_id),
            economic_network_id=str(site.get("economic_network_id") or haus_id),
            within_network_redistribution_allowed=(
                haus_policy.within_network_redistribution_allowed
            ),
            source_fingerprint=_row_fingerprint(site),
        )
        if central is None:
            exceptions.append(
                {
                    "subject_kind": "SETTLEMENT",
                    "subject_id": site["settlement_id"],
                    "severity": "WARN",
                    "exception_code": "SPECIALIST_3D_CAPACITY_WITHHELD",
                    "evidence_status": "INCOMPLETE",
                    "details": population_explanation,
                }
            )
        plans.append(plan)
    return plans, exceptions


def _make_site_plans(
    source_rows: Sequence[dict[str, Any]], *, workers: int = 1,
    memory_budget_mb: int = 1024, runtime_stats: runtime.RuntimeStats | None = None,
    cancel_event: Any = None,
) -> tuple[list[SitePlan], list[dict[str, Any]]]:
    """Prepare independent sites; preserve source order before node reductions.

    SQLite source rows contain scalar values. Their private dictionary copies
    are pulled on the coordinator, and no connection or cursor enters a worker.
    """
    _validate_execution_options(workers, memory_budget_mb)
    stats = runtime_stats or runtime.RuntimeStats()
    plans: list[SitePlan] = []
    exceptions: list[dict[str, Any]] = []
    batches = _population_batches(dict(row) for row in source_rows)
    with stats.measure("site_preparation_wall"), closing(runtime.bounded_map(
        _make_site_plans_serial, batches, workers=workers,
        memory_budget_bytes=memory_budget_mb * 1024 * 1024,
        estimated_task_bytes=POPULATION_BATCH_ESTIMATED_BYTES,
        cancel_event=cancel_event, stats=stats, phase="population_site_preparation",
    )) as prepared:
        for batch_plans, batch_exceptions in prepared:
            plans.extend(batch_plans)
            exceptions.extend(batch_exceptions)
            stats.increment("site_plans_prepared", len(batch_plans))
            del batch_plans, batch_exceptions
    return plans, exceptions


def _make_nodes(plans: Sequence[SitePlan]) -> dict[str, NodeAccumulator]:
    nodes: dict[str, NodeAccumulator] = {}
    for plan in plans:
        node = nodes.get(plan.node_id)
        if node is None:
            if plan.node_id.startswith("BREADBASKET::"):
                node_kind = "HAUS_SHARED"
                barony_id = None
            elif plan.site.get("barony_id") is not None:
                node_kind = "BARONY"
                barony_id = int(plan.site["barony_id"])
            else:
                node_kind = "UNRESOLVED_SITE_CONTEXT"
                barony_id = None
            node = NodeAccumulator(plan.node_id, node_kind, barony_id)
            nodes[plan.node_id] = node
        node.add(plan)
    return nodes


def _solve_structural_population(
    nodes: Mapping[str, NodeAccumulator],
) -> trade.ScenarioResult:
    food_nodes = [
        node.as_food_node(structural=True)
        for _, node in sorted(nodes.items())
        if node.demand(structural=True) > 0 or node.local_supply_milli > 0
    ]
    result = trade.solve_scenario(food_nodes, "NORMAL_TRADE")
    if not result.is_conserved():
        raise RuntimeError("preliminary normal-trade solve failed conservation")
    for balance in result.node_balances:
        node = nodes[balance.node_id]
        weighted = [
            (plan.pool_id, int(plan.structural_total or 0))
            for plan in node.plans
            if plan.structural_total is not None
        ]
        allocations = largest_remainder(balance.supported_human_capacity, weighted)
        for plan in node.plans:
            plan.working_total = (
                None if plan.structural_total is None else allocations[plan.pool_id]
            )
    return result


def _solve_final_scenarios(
    nodes: Mapping[str, NodeAccumulator],
) -> dict[str, trade.ScenarioResult]:
    # One fixed-point guard handles integer flooring without permitting a site
    # to exceed its structural prior.  In practice the first constrained pass
    # is already stable because only demand has fallen while supply is fixed.
    for _ in range(4):
        food_nodes = [
            node.as_food_node(structural=False)
            for _, node in sorted(nodes.items())
            if node.demand(structural=False) > 0 or node.local_supply_milli > 0
        ]
        normal = trade.solve_scenario(food_nodes, "NORMAL_TRADE")
        short_nodes = [
            balance
            for balance in normal.node_balances
            if balance.supported_human_capacity < nodes[balance.node_id].demand(structural=False)
        ]
        if not short_nodes:
            results = trade.solve_all_scenarios(food_nodes)
            if not all(result.is_conserved() for result in results.values()):
                raise RuntimeError("final scenario solve failed conservation")
            return results
        for balance in short_nodes:
            node = nodes[balance.node_id]
            weighted = [
                (plan.pool_id, int(plan.working_total or 0))
                for plan in node.plans
                if plan.working_total is not None
            ]
            allocations = largest_remainder(balance.supported_human_capacity, weighted)
            for plan in node.plans:
                if plan.working_total is not None:
                    plan.working_total = allocations[plan.pool_id]
    raise RuntimeError("normal-trade population constraint did not reach a stable fixed point")


def _resolve_splits(plans: Sequence[SitePlan]) -> None:
    for plan in plans:
        if plan.working_total is None:
            continue
        split = demographics.split_human_total(
            plan.haus_id, plan.working_total, plan.residence_type
        )
        if not plan.ordinary_gate.allowed and split.ordinary_unbonded:
            raise RuntimeError(
                f"{plan.settlement_id}: ordinary-human gate rejects nonzero calibrated remainder"
            )
        if not plan.bonded_gate.allowed and split.bonded:
            raise RuntimeError(
                f"{plan.settlement_id}: bonded-human gate rejects nonzero calibrated remainder"
            )
        plan.split = split


def _insert_profiles(connection: sqlite3.Connection) -> None:
    human_rows: list[dict[str, Any]] = []
    for haus_id in sorted(human_rules.HUMAN_RULES):
        for row in human_rules.profile_rows(human_rules.HUMAN_RULES[haus_id]):
            row = dict(row)
            if haus_id == "DUNKELHAUCH" and row["population_class"] == "BONDED_HUMAN":
                row["food_demand_milliunits_per_counting_unit"] = 0
                composite = json.loads(row["composite_demand_json"])
                composite["food_ledger_rule"] = (
                    "NO_REGULAR_FOOD_REQUIREMENT_USER_APPROVED; excluded from the routine staple ledger."
                )
                row["composite_demand_json"] = canonical_json(composite)
            human_rows.append(row)
    species_profile_rows = [
        species_rules.SPECIES_RULES[key].as_profile_row()
        for key in sorted(species_rules.SPECIES_RULES)
    ]
    rows = human_rows + species_profile_rows
    columns = (
        "profile_id", "population_class", "biological_entity_id", "counting_unit",
        "residence_mode", "food_demand_milliunits_per_counting_unit",
        "composite_demand_json", "evidence_status", "rule_fingerprint", "canon_status",
    )
    connection.executemany(
        f"INSERT INTO stage6d_population_profile ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
        [[row[column] for column in columns] for row in rows],
    )


def _pool_basis(plan: SitePlan) -> dict[str, Any]:
    return {
        "builder_version": BUILDER_VERSION,
        "settlement_id": plan.settlement_id,
        "haus_id": plan.haus_id,
        "residence_type": plan.residence_type,
        "embedded_native_host": (
            plan.ordinary_gate.preference == "EMBEDDED_ONLY"
            or plan.bonded_gate.preference == "EMBEDDED_ONLY"
        ),
        "ordinary_gate": vars(plan.ordinary_gate),
        "bonded_gate": vars(plan.bonded_gate),
        "source_fingerprint": plan.source_fingerprint,
    }


def _insert_pool(
    connection: sqlite3.Connection,
    *,
    pool_id: str,
    pool_kind: str,
    primary_settlement_id: str | None,
    owner_haus_id: str,
    mobile_shared: int,
    evidence_status: str,
    basis: Mapping[str, Any],
) -> None:
    identity = fingerprint(
        {
            "pool_id": pool_id,
            "pool_kind": pool_kind,
            "primary_settlement_id": primary_settlement_id,
            "owner_haus_id": owner_haus_id,
            "basis": basis,
        }
    )
    connection.execute(
        """
        INSERT INTO stage6d_population_pool
        (pool_id,pool_kind,primary_settlement_id,owner_haus_id,mobile_shared,
         identity_fingerprint,evidence_status,basis_json)
        VALUES (?,?,?,?,?,?,?,?)
        """,
        (
            pool_id, pool_kind, primary_settlement_id, owner_haus_id,
            mobile_shared, identity, evidence_status, canonical_json(dict(basis)),
        ),
    )


def _insert_assignment_and_estimate(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    pool_id: str,
    profile_id: str,
    working_population: int | None,
    evidence_status: str,
    completion_state: str,
    limiting_factor: str | None,
    explanation: Mapping[str, Any],
    source_fingerprint: str,
    rule_fingerprint: str,
) -> None:
    assignment_basis = {
        "builder_version": BUILDER_VERSION,
        "pool_id": pool_id,
        "profile_id": profile_id,
        "source_fingerprint": source_fingerprint,
        "explanation": dict(explanation),
    }
    assignment_fingerprint = fingerprint(assignment_basis)
    connection.execute(
        """
        INSERT INTO stage6d_population_assignment
        (run_id,pool_id,profile_id,evidence_status,assignment_basis_json,assignment_fingerprint)
        VALUES (?,?,?,?,?,?)
        """,
        (
            run_id, pool_id, profile_id, evidence_status,
            canonical_json(assignment_basis), assignment_fingerprint,
        ),
    )
    input_fingerprint = fingerprint(
        {
            "assignment": assignment_fingerprint,
            "working_population": working_population,
            "rule_fingerprint": rule_fingerprint,
        }
    )
    connection.execute(
        """
        INSERT INTO stage6d_population_estimate
        (run_id,pool_id,profile_id,working_population,population_low,population_high,
         evidence_status,completion_state,limiting_factor,explanation_json,
         input_fingerprint,rule_fingerprint,canon_status)
        VALUES (?,?,?,?,NULL,NULL,?,?,?,?,?,?,?)
        """,
        (
            run_id, pool_id, profile_id, working_population, evidence_status,
            completion_state, limiting_factor, canonical_json(dict(explanation)),
            input_fingerprint, rule_fingerprint, schema.CANON_STATUS,
        ),
    )


def _insert_attributions(connection: sqlite3.Connection, pool_id: str, site: Mapping[str, Any] | None, haus_id: str) -> None:
    values: list[tuple[str, str]] = []
    if site is not None:
        if site.get("barony_id") is not None:
            values.append(("BARONY", str(site["barony_id"])))
        if site.get("county_uid"):
            values.append(("COUNTY", str(site["county_uid"])))
        if site.get("duchy_uid"):
            values.append(("DUCHY", str(site["duchy_uid"])))
    values.extend((("HAUS", haus_id), ("WORLD", WORLD_ID)))
    for level, hierarchy_id in values:
        connection.execute(
            """
            INSERT INTO stage6d_population_attribution
            (pool_id,hierarchy_level,hierarchy_id,counting_role,basis_json)
            VALUES (?,?,?,'PRIMARY_COUNT',?)
            """,
            (
                pool_id, level, hierarchy_id,
                canonical_json(
                    {
                        "count_once": True,
                        "pool_id": pool_id,
                        "level": level,
                        "source": "SITE_IDENTITY" if site is not None else "HAUS_SHARED_IDENTITY",
                    }
                ),
            ),
        )


def _insert_site_populations_serial(
    connection: sqlite3.Connection,
    run_id: str,
    plans: Sequence[SitePlan],
) -> dict[tuple[str, str], int | None]:
    estimates: dict[tuple[str, str], int | None] = {}
    for plan in plans:
        basis = _pool_basis(plan)
        _insert_pool(
            connection,
            pool_id=plan.pool_id,
            pool_kind="SITE_RESIDENT",
            primary_settlement_id=plan.settlement_id,
            owner_haus_id=plan.haus_id,
            mobile_shared=0,
            evidence_status="INCOMPLETE",
            basis=basis,
        )
        connection.execute(
            "INSERT INTO stage6d_pool_anchor VALUES (?,?,?,?)",
            (plan.pool_id, plan.settlement_id, "PRIMARY_RESIDENCE_CONTEXT", 1.0),
        )
        _insert_attributions(connection, plan.pool_id, plan.site, plan.haus_id)
        haus_rule = human_rules.rule_for_haus(plan.haus_id)
        for role, gate in (
            (human_rules.ORDINARY, plan.ordinary_gate),
            (human_rules.BONDED, plan.bonded_gate),
        ):
            profile_id = haus_rule.profile_id(role)
            profile_rule = haus_rule.ordinary if role == human_rules.ORDINARY else haus_rule.bonded
            if plan.working_total is None:
                if gate.evidence_status == "PROVEN_ABSENT" or profile_rule.evidence_status == "PROVEN_ABSENT":
                    value: int | None = 0
                    evidence = "PROVEN_ABSENT"
                    completion = "VALIDATED"
                    limiting = gate.reason_code
                else:
                    value = None
                    evidence = "INCOMPLETE"
                    completion = "BLOCKED"
                    limiting = "CAPACITY_WITHHELD_3D"
            else:
                if plan.split is None:
                    raise AssertionError("resolved site total has no human split")
                value = (
                    plan.split.ordinary_unbonded
                    if role == human_rules.ORDINARY
                    else plan.split.bonded
                )
                evidence = "PROVEN_ABSENT" if not gate.allowed and value == 0 else "INCOMPLETE"
                completion = "VALIDATED"
                limiting = (
                    gate.reason_code
                    if evidence == "PROVEN_ABSENT"
                    else "ASSUMPTION_DOMINATED_DEMOGRAPHIC_CALIBRATION"
                )
            explanation = {
                "structural_population_low_review_only": plan.structural_low,
                "structural_population_central_before_food": plan.structural_total,
                "structural_population_high_review_only": plan.structural_high,
                "normal_trade_constrained_human_total": plan.working_total,
                "structural_explanation": plan.structural_explanation,
                "demographic_split": None if plan.split is None else vars(plan.split),
                "gate": vars(gate),
                "single_number_rule": role == human_rules.BONDED,
                "warning": "Working proposal, not census or canon.",
            }
            rule_fp = human_rules.rule_fingerprint(haus_rule, role)
            _insert_assignment_and_estimate(
                connection,
                run_id=run_id,
                pool_id=plan.pool_id,
                profile_id=profile_id,
                working_population=value,
                evidence_status=evidence,
                completion_state=completion,
                limiting_factor=limiting,
                explanation=explanation,
                source_fingerprint=plan.source_fingerprint,
                rule_fingerprint=rule_fp,
            )
            estimates[(plan.pool_id, profile_id)] = value
    return estimates


@dataclass
class _PopulationStatementBuffer:
    """Private worker output; deliberately has no SQLite handle or commit API."""

    statements: list[tuple[str, tuple[Any, ...]]] = field(default_factory=list)

    def execute(self, sql: str, parameters: Sequence[Any]) -> None:
        self.statements.append((sql, tuple(parameters)))


def _prepare_population_statements(
    task: tuple[str, tuple[SitePlan, ...]],
) -> tuple[list[tuple[str, tuple[Any, ...]]], dict[tuple[str, str], int | None]]:
    run_id, plans = task
    statements = _PopulationStatementBuffer()
    estimates = _insert_site_populations_serial(statements, run_id, plans)
    return statements.statements, estimates


def _insert_site_populations(
    connection: sqlite3.Connection, run_id: str, plans: Sequence[SitePlan], *,
    workers: int = 1, memory_budget_mb: int = 1024,
    runtime_stats: runtime.RuntimeStats | None = None, cancel_event: Any = None,
    preparation_backend: str = "auto",
) -> dict[tuple[str, str], int | None]:
    """Overlap private row/JSON/fingerprint preparation with ordered SQL writes.

    Each settled SitePlan belongs to exactly one admitted batch and is read-only
    throughout this phase. Only the coordinator can access the connection; SQL
    statements, parameters, row order and the enclosing transaction are unchanged.
    """
    _validate_execution_options(workers, memory_budget_mb)
    if preparation_backend not in {"auto", "thread", "process"}:
        raise ValueError("preparation_backend must be auto, thread or process")
    stats = runtime_stats or runtime.RuntimeStats()
    automatic = preparation_backend == "auto"
    backend = "process" if automatic else preparation_backend
    max_inflight = 1 if automatic and len(plans) < POPULATION_PROCESS_MIN_SITES else None
    if automatic:
        stats.maximum("population_row_preparation.serial_size_threshold", POPULATION_PROCESS_MIN_SITES)
    estimates: dict[tuple[str, str], int | None] = {}
    tasks = ((run_id, batch) for batch in _population_batches(plans))
    with stats.measure("population_rows_and_writes_wall"), closing(runtime.bounded_map(
        _prepare_population_statements, tasks, workers=workers,
        max_inflight=max_inflight,
        memory_budget_bytes=memory_budget_mb * 1024 * 1024,
        estimated_task_bytes=POPULATION_BATCH_ESTIMATED_BYTES,
        cancel_event=cancel_event, stats=stats, phase="population_row_preparation",
        backend=backend,
        worker_overhead_bytes=(POPULATION_PROCESS_OVERHEAD_BYTES if backend == "process" else 0),
    )) as prepared:
        for statements, batch_estimates in prepared:
            _check_cancelled(cancel_event)
            with stats.measure("population_sql_write_wall"):
                for sql, parameters in statements:
                    _check_cancelled(cancel_event)
                    connection.execute(sql, parameters)
            estimates.update(batch_estimates)
            stats.increment("population_statements_written", len(statements))
            del statements, batch_estimates
    return estimates


def _insert_shared_human_populations(
    connection: sqlite3.Connection,
    run_id: str,
    source_by_haus: Mapping[str, list[dict[str, Any]]],
    estimates: dict[tuple[str, str], int | None],
) -> dict[tuple[str, str], str]:
    allocation_nodes: dict[tuple[str, str], str] = {}

    # Duftfaehrte contains multiple caravans.  The capital caravan is distinct;
    # the remaining unregistered caravans stay as one unresolved placeholder
    # until a true caravan registry can replace it with one pool per caravan.
    haus_id = "DUFTFAEHRTE"
    haus_rule = human_rules.rule_for_haus(haus_id)
    anchors = sorted(source_by_haus[haus_id], key=lambda row: row["settlement_id"])
    caravan_placeholders = (
        (
            "HUMAN_MOBILE::DUFTFAEHRTE::CAPITAL_CARAVAN",
            "MOBILE::DUFTFAEHRTE::CAPITAL_CARAVAN",
            "CAPITAL_CARAVAN",
            anchors,
            "CAPITAL_CARAVAN_POPULATION_UNRESOLVED",
        ),
        (
            "HUMAN_MOBILE::DUFTFAEHRTE::OTHER_CARAVANS_UNRESOLVED",
            "MOBILE::DUFTFAEHRTE::OTHER_CARAVANS_UNRESOLVED",
            "OTHER_CARAVANS_REGISTRY_PLACEHOLDER",
            (),
            "OTHER_CARAVAN_COUNT_AND_POPULATIONS_UNRESOLVED",
        ),
    )
    for pool_id, node_id, caravan_role, pool_anchors, limiting_factor in caravan_placeholders:
        basis = {
            "shared_scope": caravan_role,
            "multiple_caravans_exist": True,
            "capital_caravan_is_sole_caravan": False,
            "capital_caravan_is_one_among_multiple_caravans": True,
            "anchor_count": len(pool_anchors),
            "ordinary_permanent_site_pools": False,
            "population_status": "INCOMPLETE",
            "registry_placeholder": caravan_role == "OTHER_CARAVANS_REGISTRY_PLACEHOLDER",
        }
        _insert_pool(
            connection, pool_id=pool_id, pool_kind="MOBILE_SHARED",
            primary_settlement_id=None, owner_haus_id=haus_id, mobile_shared=1,
            evidence_status="INCOMPLETE", basis=basis,
        )
        for site in pool_anchors:
            connection.execute(
                "INSERT INTO stage6d_pool_anchor VALUES (?,?,?,?)",
                (pool_id, site["settlement_id"], "CAPITAL_CARAVAN_SUPPORT_ANCHOR", None),
            )
        _insert_attributions(connection, pool_id, None, haus_id)
        for role in (human_rules.ORDINARY, human_rules.BONDED):
            profile_id = haus_rule.profile_id(role)
            rule_fp = human_rules.rule_fingerprint(haus_rule, role)
            _insert_assignment_and_estimate(
                connection,
                run_id=run_id, pool_id=pool_id, profile_id=profile_id,
                working_population=None, evidence_status="INCOMPLETE", completion_state="BLOCKED",
                limiting_factor=limiting_factor,
                explanation={
                    "count_once_per_actual_caravan": True,
                    "multiple_caravans_exist": True,
                    "caravan_role": caravan_role,
                    "no_ordinary_permanent_settlement_inference": True,
                    "calibration_available_only_after_caravan_total_is_known": demographics.calibration_for_haus(haus_id).as_dict(),
                },
                source_fingerprint=fingerprint([row["settlement_id"] for row in pool_anchors]),
                rule_fingerprint=rule_fp,
            )
            estimates[(pool_id, profile_id)] = None
            allocation_nodes[(pool_id, profile_id)] = node_id

    # Dunkelhauch has one approved approximately-fifty active bonded pool.
    haus_id = "DUNKELHAUCH"
    pool_id = "HUMAN_SHARED::DUNKELHAUCH"
    node_id = "HAUS::DUNKELHAUCH"
    anchors = sorted(source_by_haus[haus_id], key=lambda row: row["settlement_id"])
    primary = anchors[0]
    split = demographics.split_human_total(haus_id, 50)
    _insert_pool(
        connection, pool_id=pool_id, pool_kind="HAUS_SHARED",
        primary_settlement_id=primary["settlement_id"], owner_haus_id=haus_id,
        mobile_shared=0, evidence_status="FOUND",
        basis={
            "shared_scope": "ACTIVE_BLACKFLOOD_HEART_AND_INFRASTRUCTURE_SYSTEM",
            "approximately_fifty": True,
            "inactive_previous_locations": "WARTIME_FORTIFICATIONS_NO_ROUTINE_POPULATION",
            "regular_food_requirement": "NOT_APPLICABLE_USER_APPROVED",
        },
    )
    connection.execute(
        "INSERT INTO stage6d_pool_anchor VALUES (?,?,?,?)",
        (pool_id, primary["settlement_id"], "ACTIVE_INFRASTRUCTURE_ANCHOR", 1.0),
    )
    _insert_attributions(connection, pool_id, primary, haus_id)
    haus_rule = human_rules.rule_for_haus(haus_id)
    for role, value in (
        (human_rules.ORDINARY, split.ordinary_unbonded),
        (human_rules.BONDED, split.bonded),
    ):
        profile_id = haus_rule.profile_id(role)
        evidence = "PROVEN_ABSENT" if role == human_rules.ORDINARY else "FOUND"
        rule_fp = human_rules.rule_fingerprint(haus_rule, role)
        _insert_assignment_and_estimate(
            connection,
            run_id=run_id, pool_id=pool_id, profile_id=profile_id,
            working_population=value, evidence_status=evidence, completion_state="VALIDATED",
            limiting_factor=("NO_ORDINARY_POPULATION" if role == human_rules.ORDINARY else "FIXED_WORKING_INPUT_APPROXIMATELY_FIFTY"),
            explanation={
                "demographic_split": vars(split),
                "regular_staple_food_ledger": "NOT_APPLICABLE",
                "count_once": True,
            },
            source_fingerprint=_row_fingerprint(primary), rule_fingerprint=rule_fp,
        )
        estimates[(pool_id, profile_id)] = value
        allocation_nodes[(pool_id, profile_id)] = node_id

    return allocation_nodes


def _species_pool_kind(rule: species_rules.SpeciesCountingRule) -> tuple[str, int]:
    if rule.population_class == "MOBILE_SHARED_POOL":
        return "MOBILE_SHARED", 1
    if rule.population_class == "WILD_RANGE_SPECIES":
        return "WILD_RANGE", 0
    return "HAUS_SHARED", 0


def _insert_species_populations(
    connection: sqlite3.Connection,
    run_id: str,
    source_by_haus: Mapping[str, list[dict[str, Any]]],
    estimates: dict[tuple[str, str], int | None],
) -> dict[tuple[str, str], str]:
    allocation_nodes: dict[tuple[str, str], str] = {}
    for haus_id in sorted(species_rules.SPECIES_RULES):
        rule = species_rules.SPECIES_RULES[haus_id]
        pool_id = f"SPECIES_SHARED::{haus_id}"
        node_id = f"HAUS_SPECIES::{haus_id}"
        pool_kind, mobile = _species_pool_kind(rule)
        _insert_pool(
            connection,
            pool_id=pool_id, pool_kind=pool_kind, primary_settlement_id=None,
            owner_haus_id=haus_id, mobile_shared=mobile,
            evidence_status="FOUND" if rule.known_exact_count is not None else "INCOMPLETE",
            basis={
                "one_haus_species_pool": True,
                "deduplication_rule": rule.deduplication_rule,
                "hard_exclusions": list(rule.hard_exclusions),
                "residence_mode": rule.residence_mode,
                "numeric_status": rule.numeric_status,
            },
        )
        sites = sorted(source_by_haus[haus_id], key=lambda row: row["settlement_id"])
        ft0 = [site for site in sites if site.get("functional_tier") == "FT0_HAUS_PRINCIPAL_SITE"]
        anchors = sites if haus_id == "DUFTFAEHRTE" else (ft0[:1] or sites[:1])
        for site in anchors:
            connection.execute(
                "INSERT INTO stage6d_pool_anchor VALUES (?,?,?,?)",
                (pool_id, site["settlement_id"], "RANGE_REFERENCE_ANCHOR", None),
            )
        _insert_attributions(connection, pool_id, None, haus_id)
        value = rule.known_exact_count
        evidence = "FOUND" if value is not None else "INCOMPLETE"
        completion = "VALIDATED" if value is not None else "BLOCKED"
        _insert_assignment_and_estimate(
            connection,
            run_id=run_id, pool_id=pool_id, profile_id=rule.profile_id,
            working_population=value, evidence_status=evidence, completion_state=completion,
            limiting_factor=(None if value is not None else "SPECIES_NUMERIC_POPULATION_UNRESOLVED"),
            explanation={
                "known_exact_count": rule.known_exact_count,
                "numeric_status": rule.numeric_status,
                "food_demand_status": rule.food_demand_status,
                "deduplication_rule": rule.deduplication_rule,
                "hard_exclusions": list(rule.hard_exclusions),
                "warning": "No species population was inferred from human or settlement counts.",
            },
            source_fingerprint=fingerprint([site["settlement_id"] for site in anchors]),
            rule_fingerprint=species_rules.rule_fingerprint(rule),
        )
        estimates[(pool_id, rule.profile_id)] = value
        allocation_nodes[(pool_id, rule.profile_id)] = node_id
    return allocation_nodes


def _insert_supply_nodes(
    connection: sqlite3.Connection,
    nodes: Mapping[str, NodeAccumulator],
    extra_nodes: Mapping[str, tuple[str, str | None, Mapping[str, Any]]],
) -> None:
    for node_id, node in sorted(nodes.items()):
        haus_id = next(iter(node.haus_ids)) if len(node.haus_ids) == 1 else None
        basis = {
            "site_count": len(node.plans),
            "haus_ids": sorted(node.haus_ids),
            "coordinates_km": [node.x, node.y],
            "access_support_score": node.access_score,
            "access_role": "WORKING_PROXY_NOT_ROUTE_OR_TONNAGE_EVIDENCE",
            "breadbasket_pooling": node.node_kind == "HAUS_SHARED",
            "economic_network_id": node.economic_network_id,
            "within_network_redistribution_allowed": node.within_network_redistribution_allowed,
        }
        connection.execute(
            """
            INSERT INTO stage6d_supply_node
            (node_id,node_kind,barony_id,haus_id,economic_network_id,
             evidence_status,basis_json,identity_fingerprint)
            VALUES (?,?,?,?,?,?,?,?)
            """,
            (
                node_id, node.node_kind, node.barony_id, haus_id,
                node.economic_network_id, "INCOMPLETE",
                canonical_json(basis), fingerprint({"node_id": node_id, "basis": basis}),
            ),
        )
    for node_id, (node_kind, haus_id, basis) in sorted(extra_nodes.items()):
        if node_id in nodes:
            continue
        connection.execute(
            """
            INSERT INTO stage6d_supply_node
            (node_id,node_kind,barony_id,haus_id,economic_network_id,
             evidence_status,basis_json,identity_fingerprint)
            VALUES (?,?,NULL,?,?,'INCOMPLETE',?,?)
            """,
            (
                node_id, node_kind, haus_id, haus_id or "UNRESOLVED_NETWORK",
                canonical_json(dict(basis)),
                fingerprint({"node_id": node_id, "basis": basis}),
            ),
        )


def _insert_food_bundle(connection: sqlite3.Connection, rule_bundle_fp: str) -> None:
    connection.execute(
        """
        INSERT INTO stage6d_food_bundle
        (food_bundle_id,bundle_name,unit_code,component_json,evidence_status,rule_fingerprint)
        VALUES (?,?,'MILLI_PERSON_YEAR',?,'INCOMPLETE',?)
        """,
        (
            FOOD_BUNDLE_ID,
            "Human staple-food support equivalent",
            canonical_json(
                {
                    "definition": "One thousand milliunits support one human for one year.",
                    "calibration": "WORKING_SUPPORT_EQUIVALENT_NOT_CROP_YIELD_OR_RATION_CANON",
                    "accounting_scope": "NET_AGGREGATE_STAPLE_SUPPORT_EQUIVALENT",
                    "gross_food_product_trade_included": False,
                    "zero_dispatch_implies_no_food_exports": False,
                    "species_food_demand": "EXCLUDED_UNLESS_EXPLICITLY_QUANTIFIED",
                }
            ),
            rule_bundle_fp,
        ),
    )


def _insert_haus_food_support_policies(
    connection: sqlite3.Connection,
    rule_bundle_fp: str,
) -> None:
    rows = []
    for haus_id, policy in sorted(rules.HAUS_POLICIES.items()):
        evidence = {
            "notes": policy.notes,
            "source_pointers": list(policy.source_pointers),
            "calibration_status": "WORKING_NUMERIC_CALIBRATION_NOT_CANON_YIELD",
            "gross_product_quantities_status": "INCOMPLETE",
            "gross_trade_is_distinct_from_net_support": True,
            "zero_aggregate_flow_does_not_prove_no_food_trade": True,
        }
        rows.append(
            (
                haus_id,
                policy.food_support_class,
                policy.food_production_factor,
                policy.export_reserve_factor,
                policy.import_priority_factor,
                1 if policy.within_network_redistribution_allowed else 0,
                policy.gross_food_product_trade_status,
                policy.export_role,
                policy.food_policy_evidence_status,
                canonical_json(evidence),
                fingerprint(
                    {
                        "rule_bundle": rule_bundle_fp,
                        "haus_id": haus_id,
                        "policy": vars(policy),
                    }
                ),
                schema.CANON_STATUS,
            )
        )
    connection.executemany(
        """
        INSERT INTO stage6d_haus_food_support_policy
        (haus_id,food_support_class,food_production_factor,reserve_factor,
         import_priority_factor,within_network_redistribution_allowed,
         gross_food_product_trade_status,cross_network_net_support_role,
         evidence_status,evidence_json,rule_fingerprint,canon_status)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        rows,
    )


def _insert_local_supply(
    connection: sqlite3.Connection,
    run_id: str,
    plans: Sequence[SitePlan],
) -> None:
    rows = []
    for plan in plans:
        if plan.local_supply_milli <= 0:
            continue
        evidence = {
            "site_id": plan.settlement_id,
            "working_support": plan.local_supply_explanation,
            "structural_population_basis": plan.structural_total,
            "resource_atlas_used_as_absolute_yield": False,
        }
        rows.append(
            (
                "SUPPLY-" + fingerprint({"run": run_id, "pool": plan.pool_id})[:24].upper(),
                run_id, plan.node_id, FOOD_BUNDLE_ID,
                "SITE_FORM_AND_PHYSICAL_SUPPORT_PROXY", plan.local_supply_milli,
                plan.haus_id, "INCOMPLETE", canonical_json(evidence),
                fingerprint({"source": plan.source_fingerprint, "evidence": evidence}),
            )
        )
    connection.executemany(
        """
        INSERT INTO stage6d_local_supply_source
        (supply_id,run_id,node_id,food_bundle_id,source_kind,
         amount_milli_person_years,source_haus_id,evidence_status,evidence_json,input_fingerprint)
        VALUES (?,?,?,?,?,?,?,?,?,?)
        """,
        rows,
    )


def _insert_allocations_and_demands(
    connection: sqlite3.Connection,
    run_id: str,
    estimates: Mapping[tuple[str, str], int | None],
    site_plans: Sequence[SitePlan],
    extra_allocation_nodes: Mapping[tuple[str, str], str],
) -> dict[str, list[tuple[str, str, int]]]:
    allocation_nodes = dict(extra_allocation_nodes)
    for plan in site_plans:
        rule = human_rules.rule_for_haus(plan.haus_id)
        allocation_nodes[(plan.pool_id, rule.profile_id(human_rules.ORDINARY))] = plan.node_id
        allocation_nodes[(plan.pool_id, rule.profile_id(human_rules.BONDED))] = plan.node_id

    node_humans: dict[str, list[tuple[str, str, int]]] = defaultdict(list)
    for (pool_id, profile_id), node_id in sorted(allocation_nodes.items()):
        basis = {
            "single_node_allocation": True,
            "count_once": True,
            "node_id": node_id,
        }
        connection.execute(
            """
            INSERT INTO stage6d_pool_node_allocation
            (run_id,pool_id,profile_id,node_id,allocation_millionths,
             evidence_status,basis_json,identity_fingerprint)
            VALUES (?,?,?,?,1000000,'INCOMPLETE',?,?)
            """,
            (
                run_id, pool_id, profile_id, node_id, canonical_json(basis),
                fingerprint({"run": run_id, "pool": pool_id, "profile": profile_id, "node": node_id}),
            ),
        )
        profile = connection.execute(
            """
            SELECT population_class,food_demand_milliunits_per_counting_unit
            FROM stage6d_population_profile WHERE profile_id=?
            """,
            (profile_id,),
        ).fetchone()
        population_class, demand_per = profile
        population = estimates[(pool_id, profile_id)]
        excluded_reason: str | None = None
        if population_class not in {"UNBONDED_HUMAN", "BONDED_HUMAN"}:
            excluded_reason = "SPECIES_DEMAND_UNQUANTIFIED_OR_NOT_APPLICABLE"
        if pool_id == "HUMAN_SHARED::DUNKELHAUCH":
            excluded_reason = "NO_REGULAR_FOOD_REQUIREMENT_USER_APPROVED"
        if population is None or demand_per is None:
            excluded_reason = excluded_reason or "POPULATION_OR_DEMAND_INCOMPLETE"
        included = excluded_reason is None
        demand = None if not included else int(population) * int(demand_per)
        if included:
            node_humans[node_id].append((pool_id, profile_id, int(population)))
        for scenario_id, _, _ in schema.SCENARIOS:
            demand_basis = {
                "single_node_allocation": True,
                "included": included,
                "excluded_reason": excluded_reason,
                "population_is_fixed_across_scenarios": True,
            }
            connection.execute(
                """
                INSERT INTO stage6d_population_food_demand
                (run_id,scenario_id,pool_id,profile_id,node_id,food_bundle_id,
                 population_count_basis,demand_per_counting_unit,allocation_millionths,
                 demand_milli_person_years,included_in_balance,evidence_status,basis_json,input_fingerprint)
                VALUES (?,?,?,?,?,?, ?,?,1000000,?,?,?, ?,?)
                """,
                (
                    run_id, scenario_id, pool_id, profile_id, node_id, FOOD_BUNDLE_ID,
                    population if included else None,
                    demand_per if included else None,
                    demand,
                    1 if included else 0,
                    "INCOMPLETE",
                    canonical_json(demand_basis),
                    fingerprint(
                        {
                            "run": run_id, "scenario": scenario_id, "pool": pool_id,
                            "profile": profile_id, "population": population,
                            "demand_per": demand_per, "included": included,
                        }
                    ),
                ),
            )
    return node_humans


def _insert_scenario_ledgers(
    connection: sqlite3.Connection,
    run_id: str,
    results: Mapping[str, trade.ScenarioResult],
) -> None:
    for scenario_id, result in sorted(results.items()):
        for balance in result.node_balances:
            reserve_explanation = {
                "opening_reserve_evidence": "INCOMPLETE",
                "opening_reserve_used": False,
                "reserve_add_is_bounded": True,
            }
            connection.execute(
                """
                INSERT INTO stage6d_food_reserve
                (run_id,scenario_id,node_id,food_bundle_id,opening_stock_milli_person_years,
                 reserve_draw_milli_person_years,reserve_add_milli_person_years,
                 closing_stock_milli_person_years,evidence_status,explanation_json)
                VALUES (?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    run_id, scenario_id, balance.node_id, FOOD_BUNDLE_ID,
                    balance.opening_reserve_milli_person_years,
                    balance.reserve_draw_milli_person_years,
                    balance.reserve_add_milli_person_years,
                    balance.closing_reserve_milli_person_years,
                    "INCOMPLETE", canonical_json(reserve_explanation),
                ),
            )
            connection.execute(
                """
                INSERT INTO stage6d_food_balance
                (run_id,scenario_id,node_id,food_bundle_id,local_supply_milli_person_years,
                 imports_milli_person_years,reserve_draw_milli_person_years,
                 exports_milli_person_years,consumption_milli_person_years,
                 reserve_add_milli_person_years,local_loss_milli_person_years,
                 demand_milli_person_years,unmet_demand_milli_person_years,
                 evidence_status,explanation_json)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    run_id, scenario_id, balance.node_id, FOOD_BUNDLE_ID,
                    balance.local_supply_milli_person_years,
                    balance.imports_milli_person_years,
                    balance.reserve_draw_milli_person_years,
                    balance.exports_milli_person_years,
                    balance.consumption_milli_person_years,
                    balance.reserve_add_milli_person_years,
                    balance.local_loss_milli_person_years,
                    balance.demand_milli_person_years,
                    balance.unmet_demand_milli_person_years,
                    "INCOMPLETE",
                    canonical_json(
                        {
                            "solver": trade.METHOD_VERSION,
                            "person_year_ledger": True,
                            "local_loss_semantics": "UNALLOCATED_SUPPORT_RESIDUAL_OR_MODELLED_LOSS_NOT_PROOF_OF_PHYSICAL_WASTE",
                            "route_and_yield_claim_ceiling": "WORKING_PROXY",
                        }
                    ),
                ),
            )
        for flow in result.flows:
            route_basis = {
                "solver_flow_id": flow.flow_id,
                "loss_fraction": flow.loss_fraction,
                "flow_scope": flow.flow_scope,
                "basis": flow.route_basis,
                "warning": "Access and proximity allocation proxy, not an exact road, route, or tonnage claim.",
            }
            flow_id = "FLOW-" + fingerprint(
                {"run": run_id, "bundle": FOOD_BUNDLE_ID, "solver_flow": flow.flow_id}
            )[:28].upper()
            connection.execute(
                """
                INSERT INTO stage6d_trade_flow
                (flow_id,run_id,scenario_id,food_bundle_id,source_node_id,
                 destination_node_id,flow_scope,dispatched_milli_person_years,
                 delivered_milli_person_years,loss_milli_person_years,
                 route_evidence_status,route_basis_json,input_fingerprint)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    flow_id, run_id, scenario_id, FOOD_BUNDLE_ID,
                    flow.source_node_id, flow.destination_node_id,
                    flow.flow_scope,
                    flow.dispatched_milli_person_years,
                    flow.delivered_milli_person_years,
                    flow.loss_milli_person_years,
                    flow.route_evidence_status,
                    canonical_json(route_basis),
                    fingerprint({"flow": vars(flow), "run": run_id}),
                ),
            )


def _insert_capacity_results(
    connection: sqlite3.Connection,
    run_id: str,
    results: Mapping[str, trade.ScenarioResult],
    estimates: Mapping[tuple[str, str], int | None],
    node_humans: Mapping[str, list[tuple[str, str, int]]],
) -> None:
    assigned: set[tuple[str, str, str]] = set()
    for scenario_id, result in sorted(results.items()):
        for balance in result.node_balances:
            members = node_humans.get(balance.node_id, [])
            capacity = largest_remainder(
                balance.supported_human_capacity,
                [(f"{pool_id}\0{profile_id}", population) for pool_id, profile_id, population in members],
            )
            for pool_id, profile_id, _ in members:
                key = f"{pool_id}\0{profile_id}"
                value = capacity[key]
                connection.execute(
                    """
                    INSERT INTO stage6d_capacity_result
                    (run_id,scenario_id,pool_id,profile_id,capacity_low,capacity_central,
                     capacity_high,evidence_status,completion_state,limiting_factor,
                     explanation_json,input_fingerprint)
                    VALUES (?,?,?,?,NULL,?,NULL,'INCOMPLETE','VALIDATED',?,?,?)
                    """,
                    (
                        run_id, scenario_id, pool_id, profile_id, value,
                        "FOOD_SUPPORT_AND_CONSERVED_TRADE",
                        canonical_json(
                            {
                                "node_id": balance.node_id,
                                "node_supported_capacity": balance.supported_human_capacity,
                                "apportionment": "HAMILTON_LARGEST_REMAINDER_BY_WORKING_POPULATION",
                            }
                        ),
                        fingerprint(
                            {"run": run_id, "scenario": scenario_id, "pool": pool_id, "profile": profile_id, "capacity": value}
                        ),
                    ),
                )
                assigned.add((scenario_id, pool_id, profile_id))

    for (pool_id, profile_id), population in sorted(estimates.items()):
        for scenario_id, _, _ in schema.SCENARIOS:
            if (scenario_id, pool_id, profile_id) in assigned:
                continue
            profile_class = connection.execute(
                "SELECT population_class FROM stage6d_population_profile WHERE profile_id=?",
                (profile_id,),
            ).fetchone()[0]
            if pool_id == "HUMAN_SHARED::DUNKELHAUCH":
                if profile_class == "UNBONDED_HUMAN":
                    value = 0
                    evidence = "PROVEN_ABSENT"
                    completion = "VALIDATED"
                    limiting = "NO_ORDINARY_POPULATION"
                else:
                    # The known approximately-fifty population is not itself a
                    # proof of Blackflood's specialist 3D carrying capacity.
                    value = None
                    evidence = "INCOMPLETE"
                    completion = "BLOCKED"
                    limiting = "SPECIALIST_3D_CAPACITY_WITHHELD_NO_ROUTINE_FOOD_LEDGER"
            elif population == 0 and profile_class in {"UNBONDED_HUMAN", "BONDED_HUMAN"}:
                value = 0
                evidence = "PROVEN_ABSENT"
                completion = "VALIDATED"
                limiting = "POPULATION_COMPONENT_PROVEN_ABSENT"
            else:
                value = None
                evidence = "INCOMPLETE"
                completion = "BLOCKED"
                limiting = (
                    "SPECIES_CAPACITY_NOT_MODELLED"
                    if profile_class not in {"UNBONDED_HUMAN", "BONDED_HUMAN"}
                    else "POPULATION_OR_PHYSICAL_CAPACITY_INCOMPLETE"
                )
            connection.execute(
                """
                INSERT INTO stage6d_capacity_result
                (run_id,scenario_id,pool_id,profile_id,capacity_low,capacity_central,
                 capacity_high,evidence_status,completion_state,limiting_factor,
                 explanation_json,input_fingerprint)
                VALUES (?,?,?,?,NULL,?,NULL,?,?,?,?,?)
                """,
                (
                    run_id, scenario_id, pool_id, profile_id, value, evidence,
                    completion, limiting,
                    canonical_json(
                        {
                            "food_ledger_included": False,
                            "population": population,
                            "scenario": scenario_id,
                        }
                    ),
                    fingerprint(
                        {"run": run_id, "scenario": scenario_id, "pool": pool_id, "profile": profile_id, "capacity": value, "excluded": True}
                    ),
                ),
            )


def _insert_exceptions(
    connection: sqlite3.Connection,
    run_id: str,
    exceptions: Sequence[dict[str, Any]],
) -> None:
    global_exceptions = [
        {
            "subject_kind": "RUN",
            "subject_id": run_id,
            "severity": "WARN",
            "exception_code": "RESOURCE_ATLAS_NOT_ABSOLUTE_YIELD_EVIDENCE",
            "evidence_status": "INCOMPLETE",
            "details": {"resource_modifier": 1.0, "reason": "Natural-potential surfaces cannot establish yields, reserves, ownership, production, or trade."},
        },
        {
            "subject_kind": "RUN",
            "subject_id": run_id,
            "severity": "WARN",
            "exception_code": "TRADE_NETWORK_IS_WORKING_PROXY",
            "evidence_status": "INCOMPLETE",
            "details": {"basis": "Stage 6C access and straight-line proximity; no exact road graph or freight tonnage."},
        },
        {
            "subject_kind": "HAUS",
            "subject_id": "EREMITENSCHALE",
            "severity": "INFO",
            "exception_code": "FOOD_EXPORT_ROLE_FROM_DIRECT_USER_AUTHORITY",
            "evidence_status": "FOUND",
            "details": {"role": trade.EREMITENSCHALE_EXPORT_ROLE, "domestic_demand_and_bounded_reserve_paid_first": True},
        },
        {
            "subject_kind": "HAUS",
            "subject_id": "MARIENHAIN",
            "severity": "INFO",
            "exception_code": "MARIENBIEN_SPELLING_NORMALISED_TO_CURRENT_CANON",
            "evidence_status": "FOUND",
            "details": {"input_wording": "Marienbien", "canonical_haus": "Haus von Marienhain", "canonical_species": "Marienbiene"},
        },
    ]
    for ordinal, item in enumerate(list(exceptions) + global_exceptions, start=1):
        exception_id = "EXC-" + fingerprint(
            {"run": run_id, "ordinal": ordinal, "code": item["exception_code"], "subject": item["subject_id"]}
        )[:28].upper()
        connection.execute(
            """
            INSERT INTO stage6d_exception
            (exception_id,run_id,subject_kind,subject_id,severity,exception_code,
             evidence_status,details_json,review_status)
            VALUES (?,?,?,?,?,?,?,?,?)
            """,
            (
                exception_id, run_id, item["subject_kind"], str(item["subject_id"]),
                item["severity"], item["exception_code"], item["evidence_status"],
                canonical_json(item["details"]), "OPEN_FOR_LATER_REVIEW",
            ),
        )


def _validate_builder_invariants(connection: sqlite3.Connection, run_id: str) -> dict[str, Any]:
    accounting = schema.validate_accounting(connection)
    human_identity_failures = connection.execute(
        """
        WITH components AS (
            SELECT e.pool_id,
                   SUM(CASE WHEN p.population_class='UNBONDED_HUMAN' THEN e.working_population ELSE 0 END) ordinary,
                   SUM(CASE WHEN p.population_class='BONDED_HUMAN' THEN e.working_population ELSE 0 END) bonded,
                   SUM(CASE WHEN p.population_class IN ('UNBONDED_HUMAN','BONDED_HUMAN') THEN e.working_population ELSE 0 END) total
            FROM stage6d_population_estimate e
            JOIN stage6d_population_profile p USING(profile_id)
            WHERE e.run_id=? AND e.working_population IS NOT NULL
            GROUP BY e.pool_id
        )
        SELECT pool_id FROM components WHERE ordinary + bonded <> total LIMIT 10
        """,
        (run_id,),
    ).fetchall()
    if human_identity_failures:
        raise RuntimeError(f"human total identity failures: {human_identity_failures}")

    dunk = connection.execute(
        "SELECT ordinary_unbonded_humans,bonded_humans,human_total FROM stage6d_hierarchy_human_population WHERE run_id=? AND hierarchy_level='HAUS' AND hierarchy_id='DUNKELHAUCH'",
        (run_id,),
    ).fetchone()
    dunk_values = None if dunk is None else tuple(dunk)
    if dunk_values != (0, 50, 50):
        raise RuntimeError(f"Dunkelhauch exact pool mismatch: {dunk_values}")

    autarkic = connection.execute(
        "SELECT COUNT(*) FROM stage6d_trade_flow WHERE run_id=? AND scenario_id='LOCAL_AUTARKIC'",
        (run_id,),
    ).fetchone()[0]
    if autarkic:
        raise RuntimeError("autarkic scenario contains trade")

    invalid_internal_flows = connection.execute(
        """
        SELECT COUNT(*)
        FROM stage6d_trade_flow f
        JOIN stage6d_supply_node src ON src.node_id=f.source_node_id
        JOIN stage6d_supply_node dst ON dst.node_id=f.destination_node_id
        WHERE f.run_id=? AND f.flow_scope='WITHIN_ECONOMIC_NETWORK'
          AND src.economic_network_id <> dst.economic_network_id
        """,
        (run_id,),
    ).fetchone()[0]
    if invalid_internal_flows:
        raise RuntimeError(f"within-network flow scope defects: {invalid_internal_flows}")

    invalid_cross_flows = connection.execute(
        """
        SELECT COUNT(*)
        FROM stage6d_trade_flow f
        JOIN stage6d_supply_node src ON src.node_id=f.source_node_id
        JOIN stage6d_supply_node dst ON dst.node_id=f.destination_node_id
        WHERE f.run_id=?
          AND f.flow_scope='CROSS_NETWORK_PRINCIPAL_STAPLE_SUPPORT'
          AND (
              src.haus_id NOT IN ('EREMITENSCHALE','MARIENHAIN')
              OR src.economic_network_id = dst.economic_network_id
          )
        """,
        (run_id,),
    ).fetchone()[0]
    if invalid_cross_flows:
        raise RuntimeError(f"cross-network flow scope defects: {invalid_cross_flows}")

    export_rows = connection.execute(
        """
        SELECT n.haus_id,SUM(f.dispatched_milli_person_years)
        FROM stage6d_trade_flow f
        JOIN stage6d_supply_node n ON n.node_id=f.source_node_id
        WHERE f.run_id=? AND f.scenario_id='NORMAL_TRADE'
          AND f.flow_scope='CROSS_NETWORK_PRINCIPAL_STAPLE_SUPPORT'
          AND n.haus_id IN ('EREMITENSCHALE','MARIENHAIN')
        GROUP BY n.haus_id
        """,
        (run_id,),
    ).fetchall()
    exports = {haus: amount for haus, amount in export_rows}
    missing = [haus for haus in sorted(EXPLICIT_BREADBASKETS) if exports.get(haus, 0) <= 0]
    if missing:
        raise RuntimeError(f"principal cross-network support not positive: {missing}")

    policy_count = connection.execute(
        "SELECT COUNT(*) FROM stage6d_haus_food_support_policy"
    ).fetchone()[0]
    if policy_count != 20:
        raise RuntimeError(f"expected 20 Haus food-support policies, found {policy_count}")

    missing_policy_hausen = connection.execute(
        """
        SELECT haus_id
        FROM (
            SELECT haus_id FROM stage6d_supply_node WHERE haus_id IS NOT NULL
            UNION
            SELECT source_haus_id AS haus_id
            FROM stage6d_local_supply_source
            WHERE source_haus_id IS NOT NULL
        ) AS used
        WHERE NOT EXISTS (
            SELECT 1 FROM stage6d_haus_food_support_policy AS policy
            WHERE policy.haus_id=used.haus_id
        )
        ORDER BY haus_id
        """
    ).fetchall()
    if missing_policy_hausen:
        raise RuntimeError(
            f"food-support policy missing for used Hausen: {missing_policy_hausen}"
        )

    normal_capacity = connection.execute(
        "SELECT SUM(capacity_central) FROM stage6d_capacity_result WHERE run_id=? AND scenario_id='NORMAL_TRADE'",
        (run_id,),
    ).fetchone()[0]
    disrupted_capacity = connection.execute(
        "SELECT SUM(capacity_central) FROM stage6d_capacity_result WHERE run_id=? AND scenario_id='DISRUPTED_ROUTES'",
        (run_id,),
    ).fetchone()[0]
    if disrupted_capacity > normal_capacity:
        raise RuntimeError("disrupted capacity exceeds normal capacity")

    return {
        **accounting,
        "principal_cross_network_support_milli_person_years": exports,
        "within_network_flow_count": connection.execute(
            "SELECT COUNT(*) FROM stage6d_trade_flow WHERE run_id=? AND flow_scope='WITHIN_ECONOMIC_NETWORK'",
            (run_id,),
        ).fetchone()[0],
        "cross_network_principal_flow_count": connection.execute(
            "SELECT COUNT(*) FROM stage6d_trade_flow WHERE run_id=? AND flow_scope='CROSS_NETWORK_PRINCIPAL_STAPLE_SUPPORT'",
            (run_id,),
        ).fetchone()[0],
        "haus_food_support_policy_count": policy_count,
        "normal_capacity": normal_capacity,
        "disrupted_capacity": disrupted_capacity,
    }


def _write_summary(connection: sqlite3.Connection, run_id: str, path: Path, validation: Mapping[str, Any]) -> dict[str, Any]:
    scenario_rows = connection.execute(
        """
        SELECT scenario_id,
               SUM(demand_milli_person_years),SUM(consumption_milli_person_years),
               SUM(unmet_demand_milli_person_years),SUM(imports_milli_person_years),
               SUM(exports_milli_person_years),SUM(local_loss_milli_person_years)
        FROM stage6d_food_balance WHERE run_id=? GROUP BY scenario_id ORDER BY scenario_id
        """,
        (run_id,),
    ).fetchall()
    populations = connection.execute(
        """
        SELECT p.population_class,SUM(e.working_population),COUNT(*)
        FROM stage6d_population_estimate e JOIN stage6d_population_profile p USING(profile_id)
        WHERE e.run_id=? AND e.working_population IS NOT NULL
        GROUP BY p.population_class ORDER BY p.population_class
        """,
        (run_id,),
    ).fetchall()
    summary = {
        "status": "PASS",
        "run_id": run_id,
        "builder_version": BUILDER_VERSION,
        "canon_status": schema.CANON_STATUS,
        "working_population_by_class": {
            population_class: {"count": total, "estimate_rows": rows}
            for population_class, total, rows in populations
        },
        "scenarios": {
            scenario_id: {
                "demand_milli_person_years": demand,
                "consumption_milli_person_years": consumption,
                "unmet_milli_person_years": unmet,
                "imports_milli_person_years": imports,
                "exports_milli_person_years": exports,
                "unallocated_support_residual_milli_person_years": local_loss,
            }
            for scenario_id, demand, consumption, unmet, imports, exports, local_loss in scenario_rows
        },
        "specialist_3d_incomplete_site_count": connection.execute(
            "SELECT COUNT(*) FROM stage6d_exception WHERE run_id=? AND exception_code='SPECIALIST_3D_CAPACITY_WITHHELD'",
            (run_id,),
        ).fetchone()[0],
        "validation": dict(validation),
        "warnings": [
            "All numerical populations except explicit fixed counts are working proposals, not canon.",
            "Trade uses an access/proximity proxy, not a complete route or freight network.",
            "Species headcounts and food demands remain incomplete unless explicitly evidenced.",
            "Ordinary residual support is redistributed only inside its political-economic network.",
            "Only Eremitenschale and Marienhain dispatch cross-network net staple support after resident demand and bounded reserves.",
            "Gross food-product trade is outside this single-bundle ledger; zero aggregate flow never proves that a Haus exports no food products.",
        ],
    }
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)
    return summary


def _write_review_csv(connection: sqlite3.Connection, run_id: str, path: Path) -> None:
    # Materialise three compact keyed lookups once.  This avoids making SQLite
    # repeatedly expand aggregate views while joining the 30k-site review set.
    pool_for_site = {
        settlement_id: pool_id
        for settlement_id, pool_id in connection.execute(
            """
            SELECT primary_settlement_id,pool_id FROM stage6d_population_pool
            WHERE pool_kind='SITE_RESIDENT' AND primary_settlement_id IS NOT NULL
            """
        )
    }
    human_components: dict[str, dict[str, int | None]] = defaultdict(dict)
    for pool_id, population_class, value in connection.execute(
        """
        SELECT e.pool_id,p.population_class,e.working_population
        FROM stage6d_population_estimate e
        JOIN stage6d_population_profile p USING(profile_id)
        WHERE e.run_id=? AND p.population_class IN ('UNBONDED_HUMAN','BONDED_HUMAN')
        """,
        (run_id,),
    ):
        human_components[pool_id][population_class] = value
    capacity_components: dict[tuple[str, str], dict[str, int | None]] = defaultdict(dict)
    for pool_id, scenario_id, population_class, value in connection.execute(
        """
        SELECT c.pool_id,c.scenario_id,p.population_class,c.capacity_central
        FROM stage6d_capacity_result c
        JOIN stage6d_population_profile p USING(profile_id)
        WHERE c.run_id=? AND p.population_class IN ('UNBONDED_HUMAN','BONDED_HUMAN')
        """,
        (run_id,),
    ):
        capacity_components[(pool_id, scenario_id)][population_class] = value

    def human_values(pool_id: str | None) -> tuple[int | None, int | None, int | None]:
        if pool_id is None:
            return None, None, None
        values = human_components.get(pool_id, {})
        ordinary = values.get("UNBONDED_HUMAN")
        bonded = values.get("BONDED_HUMAN")
        total = None if ordinary is None or bonded is None else ordinary + bonded
        return ordinary, bonded, total

    def capacity_value(pool_id: str | None, scenario_id: str) -> int | None:
        if pool_id is None:
            return None
        values = capacity_components.get((pool_id, scenario_id), {})
        ordinary = values.get("UNBONDED_HUMAN")
        bonded = values.get("BONDED_HUMAN")
        return None if ordinary is None or bonded is None else ordinary + bonded

    source_rows = connection.execute(
        """
        SELECT settlement_id,owner_haus_id,barony_id,county_uid,duchy_uid,
               functional_tier,realised_settlement_form,stage6c_analysis_status
        FROM stage6d_source_site
        ORDER BY owner_haus_id,functional_tier,settlement_id
        """
    )
    header = [
        "settlement_id", "owner_haus_id", "barony_id", "county_uid", "duchy_uid",
        "functional_tier", "realised_settlement_form", "population_pool_id",
        "ordinary_unbonded_humans", "bonded_humans", "human_total",
        "capacity_local_autarkic", "capacity_normal_trade", "capacity_disrupted_routes",
        "review_status",
    ]
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        for (
            settlement_id, owner_haus_id, barony_id, county_uid, duchy_uid,
            functional_tier, realised_form, analysis_status,
        ) in source_rows:
            pool_id = pool_for_site.get(settlement_id)
            ordinary, bonded, total = human_values(pool_id)
            writer.writerow(
                (
                    settlement_id, owner_haus_id, barony_id, county_uid, duchy_uid,
                    functional_tier, realised_form, pool_id,
                    ordinary, bonded, total,
                    capacity_value(pool_id, "LOCAL_AUTARKIC"),
                    capacity_value(pool_id, "NORMAL_TRADE"),
                    capacity_value(pool_id, "DISRUPTED_ROUTES"),
                    "INCOMPLETE_3D" if analysis_status == "DEFERRED_SPECIALIST_3D" else "WORKING_PROPOSAL",
                )
            )
    os.replace(temporary, path)


def _build_complete_database(
    source_database: Path,
    output_database: Path,
    *,
    expected_active_sites: int = 30_097,
    expected_source_identity: Mapping[str, Any] | None = None,
    workers: int = 1,
    memory_budget_mb: int = 1024,
    runtime_stats: runtime.RuntimeStats | None = None,
    cancel_event: Any = None,
) -> dict[str, Any]:
    _validate_execution_options(workers, memory_budget_mb)
    _check_cancelled(cancel_event)
    stats = runtime_stats or runtime.RuntimeStats()
    source_database = source_database.resolve()
    output_database = output_database.resolve()
    output_database.parent.mkdir(parents=True, exist_ok=True)
    candidate = output_database.with_name(f".{output_database.name}.building.{os.getpid()}")
    if candidate.exists():
        candidate.unlink()
    rule_bundle_fp = combined_rule_fingerprint()
    schema_result = schema.create_sidecar(
        source_database,
        candidate,
        expected_active_sites=expected_active_sites,
        rule_bundle_fingerprint=rule_bundle_fp,
    )
    run_id = schema_result["run_id"]
    connection = sqlite3.connect(candidate)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA synchronous=NORMAL")
    try:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "UPDATE stage6d_run SET completion_state='RUNNING' WHERE run_id=?", (run_id,)
        )
        source_rows = [dict(row) for row in connection.execute("SELECT * FROM stage6d_source_site ORDER BY settlement_id")]
        source_by_haus: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in source_rows:
            source_by_haus[str(row["owner_haus_id"]).upper()].append(row)
        if set(source_by_haus) != set(human_rules.EXPECTED_HAUS_IDS):
            raise RuntimeError(
                f"source Haus coverage mismatch: {sorted(source_by_haus)}"
            )

        _insert_profiles(connection)
        plans, exceptions = _make_site_plans(
            # This small Python-only phase measured slower with threads;
            # process startup would also dwarf its work. The sizeable SQL-row
            # preparation phase below uses processes to bypass the GIL.
            source_rows, workers=1, memory_budget_mb=memory_budget_mb,
            runtime_stats=stats, cancel_event=cancel_event,
        )
        dunk_site = source_by_haus["DUNKELHAUCH"][0]
        if dunk_site["stage6c_analysis_status"] == "DEFERRED_SPECIALIST_3D":
            exceptions.append(
                {
                    "subject_kind": "SETTLEMENT",
                    "subject_id": dunk_site["settlement_id"],
                    "severity": "WARN",
                    "exception_code": "SPECIALIST_3D_CAPACITY_WITHHELD",
                    "evidence_status": "INCOMPLETE",
                    "details": {
                        "population_working_input": 50,
                        "population_is_not_capacity_proof": True,
                        "routine_food_ledger": "NOT_APPLICABLE",
                        "reason": "Blackflood's specialist 3D operational capacity remains deferred.",
                    },
                }
            )
        # These reductions and the coupled fixed-point solver must see exactly
        # the original order. Parallel preparation does not divide the ledger.
        _check_cancelled(cancel_event)
        with stats.measure("coupled_population_solver_wall"):
            nodes = _make_nodes(plans)
            preliminary = _solve_structural_population(nodes)
            _check_cancelled(cancel_event)
            results = _solve_final_scenarios(nodes)
            _resolve_splits(plans)

        estimates = _insert_site_populations(
            connection, run_id, plans, workers=workers,
            memory_budget_mb=memory_budget_mb, runtime_stats=stats,
            cancel_event=cancel_event,
        )
        shared_nodes = _insert_shared_human_populations(
            connection, run_id, source_by_haus, estimates
        )
        species_nodes = _insert_species_populations(
            connection, run_id, source_by_haus, estimates
        )
        extra_allocation_nodes = {**shared_nodes, **species_nodes}
        extra_nodes: dict[str, tuple[str, str | None, Mapping[str, Any]]] = {}
        for node_id in sorted(set(extra_allocation_nodes.values())):
            if node_id.startswith("MOBILE::"):
                haus_id = node_id.split("::")[1]
                extra_nodes[node_id] = (
                    "MOBILE_POOL", haus_id,
                    {"role": "ONE_OF_MULTIPLE_MOBILE_CARAVAN_CONTEXTS", "routine_food_ledger": "INCOMPLETE"},
                )
            elif node_id.startswith("HAUS_SPECIES::"):
                haus_id = node_id.split("::", 1)[1]
                extra_nodes[node_id] = (
                    "HAUS_SHARED", haus_id,
                    {"role": "SPECIES_COUNTING_CONTEXT", "food_ledger": "EXCLUDED_UNLESS_QUANTIFIED"},
                )
            else:
                haus_id = node_id.split("::", 1)[1]
                extra_nodes[node_id] = (
                    "HAUS_SHARED", haus_id,
                    {"role": "HAUS_SHARED_HUMAN_CONTEXT", "routine_food_ledger": "NOT_APPLICABLE"},
                )
        _insert_supply_nodes(connection, nodes, extra_nodes)
        _insert_food_bundle(connection, rule_bundle_fp)
        _insert_haus_food_support_policies(connection, rule_bundle_fp)
        _insert_local_supply(connection, run_id, plans)
        node_humans = _insert_allocations_and_demands(
            connection, run_id, estimates, plans, extra_allocation_nodes
        )
        _insert_scenario_ledgers(connection, run_id, results)
        _insert_capacity_results(connection, run_id, results, estimates, node_humans)
        _insert_exceptions(connection, run_id, exceptions)
        _check_cancelled(cancel_event)
        connection.execute(
            "UPDATE stage6d_run SET completion_state='COMPLETE' WHERE run_id=?", (run_id,)
        )
        validation = _validate_builder_invariants(connection, run_id)
        connection.commit()
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"final Stage 6D integrity failure: {integrity}")
        _check_cancelled(cancel_event)
    except BaseException:
        connection.rollback()
        connection.close()
        if candidate.exists():
            candidate.unlink()
        raise
    else:
        connection.close()
        _install_complete_database(candidate, output_database, source_database, expected_source_identity)

    return {
        "status": "PASS",
        "run_id": run_id,
        "source_site_count": len(source_rows),
        "site_pool_count": len(plans),
        "preliminary_normal_supported_humans": preliminary.supported_human_capacity,
        "output_database": str(output_database),
    }


def _install_complete_database(
    candidate: Path,
    output_database: Path,
    source_database: Path,
    expected_source_identity: Mapping[str, Any] | None,
) -> None:
    """Install only after validation; source drift must retain the prior release."""
    if expected_source_identity is not None:
        try:
            schema._assert_checkpointed_source(source_database)
            if runtime.file_identity(source_database) != expected_source_identity:
                raise RuntimeError("Stage 6D source changed during computation; prior output was retained")
        except BaseException:
            candidate.unlink(missing_ok=True)
            raise
    os.replace(candidate, output_database)


def _export_complete_database(
    output_database: Path,
    database_result: Mapping[str, Any],
    summary_path: Path,
    review_path: Path,
) -> dict[str, Any]:
    """Finalisation may restart, but the coupled population solver never splits."""
    run_id = str(database_result["run_id"])
    reopened = sqlite3.connect(f"file:{output_database.as_posix()}?mode=ro", uri=True)
    try:
        if reopened.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("Completed Stage 6D database failed integrity readback")
        reopened_validation = _validate_builder_invariants(reopened, run_id)
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        review_path.parent.mkdir(parents=True, exist_ok=True)
        summary = _write_summary(reopened, run_id, summary_path, reopened_validation)
        _write_review_csv(reopened, run_id, review_path)
    finally:
        reopened.close()

    return {
        **database_result,
        "summary_json": str(summary_path),
        "review_csv": str(review_path),
        "validation": reopened_validation,
        "summary": summary,
    }


def build(
    source_database: Path,
    output_database: Path,
    *,
    summary_json: Path | None = None,
    review_csv: Path | None = None,
    expected_active_sites: int = 30_097,
    reuse: bool = True,
    work_dir: Path | None = None,
    runtime_stats: runtime.RuntimeStats | None = None,
    workers: int = 1,
    memory_budget_mb: int = 1024,
    cancel_event: Any = None,
) -> dict[str, Any]:
    _validate_execution_options(workers, memory_budget_mb)
    _check_cancelled(cancel_event)
    stats = runtime_stats or runtime.RuntimeStats()
    source_database, output_database = source_database.resolve(), output_database.resolve()
    if source_database == output_database:
        raise ValueError("Stage 6D source and output databases must be distinct")
    summary_path = (summary_json or output_database.with_suffix(".summary.json")).resolve()
    review_path = (review_csv or output_database.with_suffix(".review.csv")).resolve()
    if len({source_database, output_database, summary_path, review_path}) != 4:
        raise ValueError("Stage 6D source, database and export paths must be distinct")
    if not reuse:
        with stats.measure("database_compute"):
            database_result = _build_complete_database(
                source_database, output_database, expected_active_sites=expected_active_sites,
                workers=workers, memory_budget_mb=memory_budget_mb,
                runtime_stats=stats, cancel_event=cancel_event,
            )
        stats.increment("databases_generated")
        _check_cancelled(cancel_event)
        with stats.measure("export_finalisation"):
            result = _export_complete_database(output_database, database_result, summary_path, review_path)
        _check_cancelled(cancel_event)
        return result

    # A main-file hash cannot describe uncheckpointed WAL content.
    schema._assert_checkpointed_source(source_database)
    source_binding = runtime.file_identity(source_database)
    release_root = Path(os.path.commonpath([output_database.parent, summary_path.parent, review_path.parent]))
    engine = Path(__file__).resolve().parent
    implementation = runtime.implementation_identity(sorted(engine.glob("*.py")))
    data_identity = runtime.semantic_identity(
        "stage6d-complete-database.v1",
        {"source_database": source_binding},
        {"builder_version": BUILDER_VERSION, "expected_active_sites": expected_active_sites,
         "output_role": "population_sidecar", "output_filename": output_database.name,
         "rule_bundle": combined_rule_fingerprint()},
        implementation,
    )
    identity = runtime.semantic_identity(
        "stage6d-release.v1", {"database_identity": data_identity},
        {"summary_path": summary_path.relative_to(release_root).as_posix(),
         "review_path": review_path.relative_to(release_root).as_posix()}, implementation,
    )
    work = (work_dir or output_database.parent / ".generation_runtime" / output_database.name).resolve()
    data_receipt = work / "complete-database.receipt.json"
    final_receipt = work / "release.receipt.json"
    with stats.measure("release_verification"):
        saved = runtime.load_receipt(final_receipt, identity, release_root)
    if saved is not None:
        _check_cancelled(cancel_event)
        stats.increment("releases_reused")
        return saved
    with stats.measure("database_checkpoint_verification"):
        database_result = runtime.load_receipt(data_receipt, data_identity, output_database.parent)
    if database_result is None:
        with stats.measure("database_compute"):
            database_result = _build_complete_database(
                source_database, output_database, expected_active_sites=expected_active_sites,
                expected_source_identity=source_binding,
                workers=workers, memory_budget_mb=memory_budget_mb,
                runtime_stats=stats, cancel_event=cancel_event,
            )
        stats.increment("databases_generated")
        runtime.save_receipt(data_receipt, data_identity, output_database.parent,
                             [output_database], database_result)
    else:
        stats.increment("databases_reused")
    _check_cancelled(cancel_event)
    with stats.measure("export_finalisation"):
        result = _export_complete_database(output_database, database_result, summary_path, review_path)
    _check_cancelled(cancel_event)
    runtime.save_receipt(final_receipt, identity, release_root,
                         [output_database, summary_path, review_path], result)
    return result


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary-json", type=Path)
    parser.add_argument("--review-csv", type=Path)
    parser.add_argument("--expected-active-sites", type=int, default=30_097)
    parser.add_argument("--no-reuse", action="store_true", help="Rebuild without reading or writing reuse records")
    parser.add_argument("--work-dir", type=Path, default=None)
    parser.add_argument("--workers", type=int, default=1,
                        help="Bounded large-workset population preparation processes; small worksets and 1 worker stay serial")
    parser.add_argument("--memory-budget-mb", type=int, default=1024,
                        help="Estimated admitted preparation memory, including 64 MiB per process; not total RAM (minimum 16 MiB)")
    parser.add_argument("--algorithm-mode", choices=("auto", "reference"), default="auto")
    args = parser.parse_args(list(argv) if argv is not None else None)
    algorithm_policy.configure(args.algorithm_mode)
    stats = runtime.RuntimeStats()
    result = build(
        args.source,
        args.output,
        summary_json=args.summary_json,
        review_csv=args.review_csv,
        expected_active_sites=args.expected_active_sites,
        reuse=not args.no_reuse,
        work_dir=args.work_dir,
        runtime_stats=stats,
        workers=args.workers,
        memory_budget_mb=args.memory_budget_mb,
    )
    print("CHECKPOINT_STAGE6D_RUNTIME " + canonical_json(stats.snapshot()))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
