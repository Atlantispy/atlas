#!/usr/bin/env python3
"""Deterministic Stage 6D human-food and trade reference solver.

This standard-library-only module operates on already-aggregated supply nodes.
It deliberately treats straight-line proximity and Stage 6C access as a
WORKING_PROXY allocation aid, not evidence of a road, route, or tonnage.

Quantities are integer milli-person-years.  One supported human requires
exactly 1,000 units.  Demand is the fixed working population: shortages become
unmet demand and never create food or revise the population identity.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Iterable, Mapping

from stage6d_schema import SCENARIO_PARAMETERS


METHOD_VERSION = "STAGE6D_HUMAN_FOOD_TRADE_REFERENCE_V2"
MILLIUNITS_PER_PERSON_YEAR = 1_000
ROUTE_EVIDENCE_STATUS = "WORKING_PROXY"

# These two roles are the only canon-supported sources of cross-network net
# staple support.  Ordinary nodes may still redistribute a conserved residual
# inside their own political-economic network.
EREMITENSCHALE_EXPORT_ROLE = "EREMITENSCHALE_BREADBASKET_EXPORTER"
MARIENHAIN_EXPORT_ROLE = "MARIENHAIN_BREADBASKET_EXPORTER"
ALLOWED_CROSS_NETWORK_SUPPORT_ROLES = frozenset(
    {EREMITENSCHALE_EXPORT_ROLE, MARIENHAIN_EXPORT_ROLE}
)

WITHIN_ECONOMIC_NETWORK = "WITHIN_ECONOMIC_NETWORK"
CROSS_NETWORK_PRINCIPAL_STAPLE_SUPPORT = "CROSS_NETWORK_PRINCIPAL_STAPLE_SUPPORT"


@dataclass(frozen=True)
class FoodNode:
    node_id: str
    local_supply_milli_person_years: int
    working_demand_people: int
    access_score: float
    x: float
    y: float
    export_role: str = "ORDINARY_NETWORK"
    economic_network_id: str = "UNRESOLVED_NETWORK"
    within_network_redistribution_allowed: bool = True
    # A factor of 1.25 means a target addition of 25% of annual demand.
    reserve_factor: float = 1.0
    storage_capacity_milli_person_years: int = 0
    import_priority: float = 1.0
    # Opening reserve is usable only when its evidence is explicitly FOUND.
    opening_reserve_milli_person_years: int = 0
    reserve_evidence_status: str = "INCOMPLETE"


@dataclass(frozen=True)
class TradeFlow:
    flow_id: str
    scenario_id: str
    source_node_id: str
    destination_node_id: str
    dispatched_milli_person_years: int
    delivered_milli_person_years: int
    loss_milli_person_years: int
    loss_fraction: float
    flow_scope: str
    route_evidence_status: str = ROUTE_EVIDENCE_STATUS
    route_basis: str = (
        "Stage 6C access and straight-line proximity allocation proxy; "
        "not an exact route or tonnage claim."
    )


@dataclass(frozen=True)
class NodeBalance:
    scenario_id: str
    node_id: str
    demand_milli_person_years: int
    local_supply_milli_person_years: int
    imports_milli_person_years: int
    reserve_draw_milli_person_years: int
    exports_milli_person_years: int
    consumption_milli_person_years: int
    reserve_add_milli_person_years: int
    local_loss_milli_person_years: int
    unmet_demand_milli_person_years: int
    opening_reserve_milli_person_years: int
    closing_reserve_milli_person_years: int
    supported_human_capacity: int

    def is_conserved(self) -> bool:
        resources_in = (
            self.local_supply_milli_person_years
            + self.imports_milli_person_years
            + self.reserve_draw_milli_person_years
        )
        resources_out = (
            self.exports_milli_person_years
            + self.consumption_milli_person_years
            + self.reserve_add_milli_person_years
            + self.local_loss_milli_person_years
        )
        return (
            resources_in == resources_out
            and self.demand_milli_person_years
            == self.consumption_milli_person_years
            + self.unmet_demand_milli_person_years
            and self.opening_reserve_milli_person_years
            + self.reserve_add_milli_person_years
            == self.closing_reserve_milli_person_years
            + self.reserve_draw_milli_person_years
        )


@dataclass(frozen=True)
class ScenarioResult:
    scenario_id: str
    node_balances: tuple[NodeBalance, ...]
    flows: tuple[TradeFlow, ...]
    supported_human_capacity: int
    total_demand_people: int
    route_evidence_status: str

    def balance_for(self, node_id: str) -> NodeBalance:
        for balance in self.node_balances:
            if balance.node_id == node_id:
                return balance
        raise KeyError(node_id)

    def is_conserved(self) -> bool:
        if not all(balance.is_conserved() for balance in self.node_balances):
            return False
        dispatched = sum(flow.dispatched_milli_person_years for flow in self.flows)
        delivered = sum(flow.delivered_milli_person_years for flow in self.flows)
        losses = sum(flow.loss_milli_person_years for flow in self.flows)
        exports = sum(b.exports_milli_person_years for b in self.node_balances)
        imports = sum(b.imports_milli_person_years for b in self.node_balances)
        return dispatched == delivered + losses and exports == dispatched and imports == delivered


def _as_node(value: FoodNode | Mapping[str, object]) -> FoodNode:
    if isinstance(value, FoodNode):
        return value
    return FoodNode(**value)  # type: ignore[arg-type]


def _validate_nodes(nodes: Iterable[FoodNode | Mapping[str, object]]) -> tuple[FoodNode, ...]:
    result = tuple(_as_node(node) for node in nodes)
    ids: set[str] = set()
    for node in result:
        if not node.node_id or node.node_id in ids:
            raise ValueError(f"node_id must be unique and non-empty: {node.node_id!r}")
        ids.add(node.node_id)
        for name in (
            "local_supply_milli_person_years",
            "working_demand_people",
            "storage_capacity_milli_person_years",
            "opening_reserve_milli_person_years",
        ):
            value = getattr(node, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"{node.node_id}.{name} must be a non-negative integer")
        for name in ("access_score", "x", "y", "reserve_factor", "import_priority"):
            value = float(getattr(node, name))
            if not math.isfinite(value):
                raise ValueError(f"{node.node_id}.{name} must be finite")
        if not 0.0 <= node.access_score <= 1.0:
            raise ValueError(f"{node.node_id}.access_score must be between 0 and 1")
        if node.reserve_factor < 1.0:
            raise ValueError(f"{node.node_id}.reserve_factor must be at least 1.0")
        if node.import_priority < 0.0:
            raise ValueError(f"{node.node_id}.import_priority must be non-negative")
        if not isinstance(node.economic_network_id, str) or not node.economic_network_id.strip():
            raise ValueError(f"{node.node_id}.economic_network_id must be non-empty")
        if not isinstance(node.within_network_redistribution_allowed, bool):
            raise ValueError(
                f"{node.node_id}.within_network_redistribution_allowed must be boolean"
            )
    return tuple(sorted(result, key=lambda node: node.node_id))


def _round_fraction(amount: int, fraction: float) -> int:
    """Deterministic half-up multiplication for non-negative integers."""

    return min(amount, max(0, int(math.floor(amount * fraction + 0.5))))


def _loss_fraction(source: FoodNode, destination: FoodNode, scenario_id: str) -> float:
    parameters = SCENARIO_PARAMETERS[scenario_id]
    # The weaker endpoint controls the conservative access proxy.
    access = min(source.access_score, destination.access_score)
    result = float(parameters["loss_floor"]) + float(
        parameters["loss_access_penalty"]
    ) * (1.0 - access)
    return min(0.75, max(0.0, result))


def _delivery(dispatched: int, loss_fraction: float) -> tuple[int, int]:
    loss = _round_fraction(dispatched, loss_fraction)
    return dispatched - loss, loss


def _largest_dispatch_not_overdelivering(
    available: int, needed_delivery: int, loss_fraction: float
) -> int:
    """Largest dispatch whose rounded delivery does not exceed recipient need."""

    low, high = 0, available
    while low < high:
        middle = (low + high + 1) // 2
        delivered, _ = _delivery(middle, loss_fraction)
        if delivered <= needed_delivery:
            low = middle
        else:
            high = middle - 1
    return low


def _flow_id(
    scenario_id: str,
    source_node_id: str,
    destination_node_id: str,
    flow_scope: str,
    ordinal: int,
) -> str:
    payload = json.dumps(
        [
            METHOD_VERSION,
            scenario_id,
            source_node_id,
            destination_node_id,
            flow_scope,
            ordinal,
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return "S6D-FLOW-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20].upper()


def solve_scenario(
    nodes: Iterable[FoodNode | Mapping[str, object]], scenario_id: str
) -> ScenarioResult:
    """Solve one conserved food scenario using deterministic greedy allocation."""

    if scenario_id not in SCENARIO_PARAMETERS:
        raise ValueError(f"unknown scenario_id: {scenario_id}")
    ordered = _validate_nodes(nodes)
    parameters = SCENARIO_PARAMETERS[scenario_id]

    state: dict[str, dict[str, int]] = {}
    export_available: dict[str, int] = {}
    for node in ordered:
        demand = node.working_demand_people * MILLIUNITS_PER_PERSON_YEAR
        local_consumption = min(node.local_supply_milli_person_years, demand)
        local_remainder = node.local_supply_milli_person_years - local_consumption

        opening = (
            node.opening_reserve_milli_person_years
            if node.reserve_evidence_status == "FOUND"
            else 0
        )
        reserve_draw = min(opening, demand - local_consumption)
        consumption = local_consumption + reserve_draw

        target_add = _round_fraction(demand, node.reserve_factor - 1.0)
        available_storage = max(0, node.storage_capacity_milli_person_years - opening)
        reserve_add = min(local_remainder, target_add, available_storage)
        local_remainder -= reserve_add

        scenario_export = 0
        if parameters["inter_node_trade_allowed"] and (
            node.within_network_redistribution_allowed
            or node.export_role in ALLOWED_CROSS_NETWORK_SUPPORT_ROLES
        ):
            scenario_export = _round_fraction(
                local_remainder,
                float(parameters["export_dispatch_fraction"])
                * float(parameters["route_reliability_multiplier"]),
            )
        export_available[node.node_id] = scenario_export
        state[node.node_id] = {
            "demand": demand,
            "imports": 0,
            "reserve_draw": reserve_draw,
            "exports": 0,
            "consumption": consumption,
            "reserve_add": reserve_add,
            "local_remainder": local_remainder,
            "opening": opening,
        }

    flows: list[TradeFlow] = []
    if parameters["inter_node_trade_allowed"]:
        recipients = tuple(sorted(
            ordered,
            key=lambda node: (
                -node.import_priority,
                -node.access_score,
                -(state[node.node_id]["demand"] - state[node.node_id]["consumption"]),
                node.node_id,
            ),
        ))
        ordinal = 0
        phases = (
            (
                WITHIN_ECONOMIC_NETWORK,
                lambda source, recipient: (
                    source.within_network_redistribution_allowed
                    and source.economic_network_id == recipient.economic_network_id
                ),
            ),
            (
                CROSS_NETWORK_PRINCIPAL_STAPLE_SUPPORT,
                lambda source, recipient: (
                    source.export_role in ALLOWED_CROSS_NETWORK_SUPPORT_ROLES
                    and source.economic_network_id != recipient.economic_network_id
                ),
            ),
        )
        # Complete the internal redistribution phase for every recipient before
        # any principal breadbasket support crosses an economic-network border.
        for flow_scope, source_is_eligible in phases:
            for recipient in recipients:
                recipient_state = state[recipient.node_id]
                needed = recipient_state["demand"] - recipient_state["consumption"]
                if needed <= 0:
                    continue
                nearest = sorted(
                    (
                        source
                        for source in ordered
                        if source.node_id != recipient.node_id
                        and export_available[source.node_id] > 0
                        and source_is_eligible(source, recipient)
                    ),
                    key=lambda source: (
                        math.hypot(source.x - recipient.x, source.y - recipient.y),
                        -source.access_score,
                        source.node_id,
                    ),
                )
                for source in nearest:
                    available = export_available[source.node_id]
                    if available <= 0 or needed <= 0:
                        continue
                    loss_fraction = _loss_fraction(source, recipient, scenario_id)
                    dispatch = _largest_dispatch_not_overdelivering(
                        available, needed, loss_fraction
                    )
                    delivered, loss = _delivery(dispatch, loss_fraction)
                    if dispatch <= 0 or delivered <= 0:
                        continue
                    export_available[source.node_id] -= dispatch
                    state[source.node_id]["exports"] += dispatch
                    recipient_state["imports"] += delivered
                    recipient_state["consumption"] += delivered
                    needed -= delivered
                    ordinal += 1
                    flows.append(
                        TradeFlow(
                            flow_id=_flow_id(
                                scenario_id,
                                source.node_id,
                                recipient.node_id,
                                flow_scope,
                                ordinal,
                            ),
                            scenario_id=scenario_id,
                            source_node_id=source.node_id,
                            destination_node_id=recipient.node_id,
                            dispatched_milli_person_years=dispatch,
                            delivered_milli_person_years=delivered,
                            loss_milli_person_years=loss,
                            loss_fraction=loss_fraction,
                            flow_scope=flow_scope,
                        )
                    )

    balances: list[NodeBalance] = []
    for node in ordered:
        item = state[node.node_id]
        # Anything locally produced but neither consumed, stored, nor dispatched
        # is explicitly accounted as local loss/unallocated surplus.
        local_loss = item["local_remainder"] - item["exports"]
        unmet = item["demand"] - item["consumption"]
        closing = item["opening"] - item["reserve_draw"] + item["reserve_add"]
        balance = NodeBalance(
            scenario_id=scenario_id,
            node_id=node.node_id,
            demand_milli_person_years=item["demand"],
            local_supply_milli_person_years=node.local_supply_milli_person_years,
            imports_milli_person_years=item["imports"],
            reserve_draw_milli_person_years=item["reserve_draw"],
            exports_milli_person_years=item["exports"],
            consumption_milli_person_years=item["consumption"],
            reserve_add_milli_person_years=item["reserve_add"],
            local_loss_milli_person_years=local_loss,
            unmet_demand_milli_person_years=unmet,
            opening_reserve_milli_person_years=item["opening"],
            closing_reserve_milli_person_years=closing,
            supported_human_capacity=item["consumption"] // MILLIUNITS_PER_PERSON_YEAR,
        )
        if not balance.is_conserved():
            raise AssertionError(f"internal conservation defect at {node.node_id}")
        balances.append(balance)

    result = ScenarioResult(
        scenario_id=scenario_id,
        node_balances=tuple(balances),
        flows=tuple(flows),
        supported_human_capacity=sum(b.supported_human_capacity for b in balances),
        total_demand_people=sum(node.working_demand_people for node in ordered),
        route_evidence_status=(
            ROUTE_EVIDENCE_STATUS if flows else "PROVEN_ABSENT"
        ),
    )
    if not result.is_conserved():
        raise AssertionError("internal global conservation defect")
    return result


def solve_all_scenarios(
    nodes: Iterable[FoodNode | Mapping[str, object]],
) -> dict[str, ScenarioResult]:
    """Return all canonical scenarios and enforce disruption monotonicity."""

    materialized = tuple(nodes)
    results = {
        scenario_id: solve_scenario(materialized, scenario_id)
        for scenario_id in ("LOCAL_AUTARKIC", "NORMAL_TRADE", "DISRUPTED_ROUTES")
    }
    if (
        results["DISRUPTED_ROUTES"].supported_human_capacity
        > results["NORMAL_TRADE"].supported_human_capacity
    ):
        raise AssertionError("disrupted capacity exceeded normal-trade capacity")
    return results
