"""Actual land-food-to-network execution with one explicit commodity and year.

This local callable integration does not select settlement sites, canon totals,
roads, crop coefficients or accepted water pools. All those inputs are explicit.
No compatibility with the protected production launcher is implied.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
import math

from .agroclimate import number, provenance
from .land_food import allocate_land_food
from .transport import Node, solve_transport


@dataclass(frozen=True)
class Settlement:
    node_id: str
    fixed_population: int
    evidence: str

    def __post_init__(self):
        if type(self.node_id) is not str or not self.node_id.strip():
            raise ValueError("explicit settlement/node ID required")
        if type(self.fixed_population) is not int or self.fixed_population < 0:
            raise ValueError("fixed population is a nonnegative integer, never inferred from food")
        if type(self.evidence) is not str or not self.evidence.strip():
            raise ValueError("settlement population evidence required")


def food_transport_snapshot(parcels, options, water_pools, *, settlements,
                            parcel_to_node, links, frame_id, snapshot_id,
                            annual_period_seconds, annual_energy_kcal_per_person,
                            commodity_id, commodity_energy_kcal_kg,
                            network_complete, evidence, source_status):
    """Allocate land, compute food, then optimise actual capacity-limited flow.

    All crop options must produce the same supplied edible commodity with the
    same kcal/kg. Demand derives from fixed population only. Supplies derive
    only from the actual independent food budget. Multiple commodities must NOT
    be solved independently against the same network capacities.
    """
    provenance(evidence, source_status)
    for name, value in (("frame_id", frame_id), ("snapshot_id", snapshot_id), ("commodity_id", commodity_id)):
        if type(value) is not str or not value.strip():
            raise ValueError(name + " required")
    period = number(annual_period_seconds, "declared model year duration", positive=True)
    per_person = number(annual_energy_kcal_per_person, "annual dietary energy need", positive=True)
    composition = number(commodity_energy_kcal_kg, "edible commodity energy", positive=True)
    if type(network_complete) is not bool:
        raise ValueError("explicit network completeness required")
    if not isinstance(settlements, (tuple, list)) or not 1 <= len(settlements) <= 128:
        raise ValueError("supply 1..128 fixed settlement/network nodes")
    if any(not isinstance(n, Settlement) for n in settlements):
        raise ValueError("typed settlement records required")
    node_map = {n.node_id:n for n in settlements}
    if len(node_map) != len(settlements):
        raise ValueError("duplicate settlement would duplicate demand")
    if type(parcel_to_node) is not dict or set(parcel_to_node) != {p.parcel_id for p in parcels}:
        raise ValueError("every productive parcel needs exactly one explicit source node")
    if any(type(v) is not str or v not in node_map for v in parcel_to_node.values()):
        raise ValueError("parcel source node must resolve")
    for option in options:
        if option.crop_id != commodity_id:
            raise ValueError("independent multi-commodity capacity use is unsupported")
        if option.edible_energy_kcal_kg is not None and option.edible_energy_kcal_kg != composition:
            raise ValueError("mixed commodity composition cannot be collapsed into kg")
    all_synthetic = source_status == "SYNTHETIC TEST" and all(
        item.source_status == "SYNTHETIC TEST" for group in (parcels, options, water_pools) for item in group)
    result_status = "SYNTHETIC TEST" if all_synthetic else "WORKING NON-CANON"
    base = {"schema": "diadem.land-food-network-snapshot.r1", "snapshot_id": snapshot_id,
            "frame_id": frame_id, "source_status": result_status, "input_source_status": source_status,
            "evidence": evidence,
            "annual_period_seconds": period, "commodity_id": commodity_id,
            "production_installed": False, "canon_adoption": False,
            "full_nutritional_carrying_capacity": False, "full_category_acceptance": False}
    if source_status == "UNKNOWN":
        return {**base, "status": "UNKNOWN", "reason": "snapshot evidence unresolved",
                "land_food": None, "transport": None}
    population = sum(n.fixed_population for n in settlements)
    land = allocate_land_food(parcels, options, water_pools, frame_id=frame_id,
                              annual_energy_kcal_per_person=per_person, fixed_population=population)
    if land["status"] != "OPTIMAL":
        return {**base, "status": land["status"], "land_food": land, "transport": None}
    allocation = {r["option_id"]:r for r in land["allocations"]}
    supplies = {name:Fraction(0) for name in node_map}
    for row in land["food_budget"]["rows"]:
        placed = allocation[row["parcel_id"]]
        node = parcel_to_node[placed["parcel_id"]]
        # Account exactly for the represented physical budget, not a rounded
        # recomputation of production or supply inferred from population.
        supplies[node] += Fraction(row["available_food_kg_year"])
    demands = {name:Fraction(n.fixed_population)*Fraction(per_person)/Fraction(composition)
               for name, n in node_map.items()}
    nodes = [Node(name, supplies[name], demands[name], node_map[name].evidence) for name in sorted(node_map)]
    transport = solve_transport(nodes, links, period_seconds=period, commodity_id=commodity_id,
                                network_complete=network_complete, evidence_id=evidence)
    if not transport["solved"]:
        return {**base, "status": "MISSING_EVIDENCE", "land_food": land, "transport": transport}
    total_supply = sum(supplies.values(), Fraction(0))
    delivered = Fraction(transport["totals"]["served_kg"]["exact"])
    if Fraction(transport["totals"]["supply_kg"]["exact"]) != total_supply:
        raise ArithmeticError("transport supply differs from actual food budget")
    if Fraction(transport["totals"]["demand_kg"]["exact"]) != sum(demands.values(), Fraction(0)):
        raise ArithmeticError("transport demand differs from fixed population demand")
    exact_available_energy = total_supply*Fraction(composition)
    budget_energy = Fraction(land["food_budget"]["total_available_energy_kcal_year"])
    representation_residual = exact_available_energy-budget_energy
    # Multiplication/summation in the retained binary64 food budget rounds. Keep
    # its difference explicit; do not invent or round new supply to erase it.
    allowed = 64*max(1, len(allocation))*math.ulp(max(1.0, float(budget_energy)))
    if abs(float(representation_residual)) > allowed:
        raise ArithmeticError("edible energy composition does not match the actual food budget")
    return {**base, "status": "REFERENCE_SOLVED", "land_food": land, "transport": transport,
            "fixed_population": population, "delivered_edible_energy_kcal_year": float(delivered*Fraction(composition)),
            "food_energy_representation_residual_kcal": str(representation_residual),
            "supply_origin": "actual allocated parcel food_budget rows, independent of population",
            "demand_origin": "fixed settlement populations times supplied annual energy need",
            "limitations": ["energy-equivalent homogeneous commodity, not a nutritionally adequate diet",
                            "land objective maximises production before routing; not joint food-delivery optimisation",
                            "roads, site locations and Diadem interpretation are supplied, not generated here",
                            "one explicitly declared annual crop regime; no historical simulation"]}
