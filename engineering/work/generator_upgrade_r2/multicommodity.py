"""Bounded divisible multi-commodity transport, with exact represented accounting.

The supplied graph is an explicit physical hypothesis, not inferred infrastructure.
All commodities share the same throughput constraints. HiGHS proposes route flows;
exact rational contraction makes those flows feasible, and weak duality certifies
their objective gap. This is a static common-period model, not scheduling or policy.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from decimal import Decimal
from fractions import Fraction as F
import hashlib
import json
import math

import numpy as np
import scipy
from scipy.optimize import linprog
from scipy.sparse import csc_matrix


MAX_NODES = 32
MAX_LINKS = 128
MAX_COMMODITIES = 8
MAX_STOCKS = MAX_DEMANDS = MAX_GROUPS = 64
MAX_ROUTES = 4096
MAX_PATH_STEPS = 100_000
OBJECTIVE = "MAX_WEIGHTED_DELIVERED_KG"


class TransportError(ValueError):
    """Invalid physical contract or bounded computational envelope."""


@dataclass(frozen=True)
class Period:
    period_id: str
    duration_seconds: object


@dataclass(frozen=True)
class Commodity:
    commodity_id: str
    mass_basis: str
    unit: str
    evidence_id: str


@dataclass(frozen=True)
class Node:
    node_id: str
    mode: str
    evidence_id: str


@dataclass(frozen=True)
class Stock:
    stock_id: str
    node_id: str
    commodity_id: str
    available_kg: object
    period_id: str
    evidence_id: str


@dataclass(frozen=True)
class Demand:
    demand_id: str
    node_id: str
    commodity_id: str
    required_kg: object
    weight_per_kg: object
    period_id: str
    evidence_id: str


@dataclass(frozen=True)
class CapacityGroup:
    group_id: str
    capacity_kg: object
    period_id: str
    evidence_id: str


@dataclass(frozen=True)
class CapacityUse:
    group_id: str
    load_kg_per_kg_entering: object
    evidence_id: str


@dataclass(frozen=True)
class CommodityRule:
    commodity_id: str
    allowed: bool | None
    loss_fraction: object
    capacity_uses: tuple[CapacityUse, ...]
    evidence_id: str


@dataclass(frozen=True)
class Link:
    link_id: str
    from_node: str
    to_node: str
    kind: str
    travel_time_s: object
    available: bool | None
    rules: tuple[CommodityRule, ...]
    period_id: str
    evidence_id: str


@dataclass(frozen=True)
class Objective:
    name: str
    scenario_id: str
    evidence_id: str


def _label(value, name):
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise TransportError(name + ": nonblank bounded text required")
    return value


def _q(value, name, *, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float, F, Decimal)):
        raise TransportError(name + ": explicit finite real quantity required")
    try:
        value = F(value)
    except (ValueError, OverflowError) as exc:
        raise TransportError(name + ": finite rational quantity required") from exc
    if value < 0 or (positive and value == 0):
        raise TransportError(name + ": physical range violated")
    if value.numerator.bit_length() > 256 or value.denominator.bit_length() > 128:
        raise TransportError(name + ": input rational envelope exceeded")
    return value


def quantity(value):
    """JSON-safe exact quantity. `exact` is authoritative; value is binary64 view."""
    value = F(value)
    try:
        approx = float(value)
    except OverflowError as exc:
        raise TransportError("report quantity overflows binary64") from exc
    if not math.isfinite(approx) or (value and approx == 0):
        raise TransportError("report quantity is outside nonzero finite binary64 range")
    return {"exact": str(value), "value": approx}


def _canonical(value):
    if hasattr(value, "__dataclass_fields__"):
        return _canonical(asdict(value))
    if isinstance(value, dict):
        return {str(k): _canonical(v) for k, v in sorted(value.items())}
    if isinstance(value, (tuple, list)):
        return [_canonical(v) for v in value]
    if isinstance(value, (F, Decimal)):
        return {"rational": str(F(value))}
    return value


def _records(records, cls, id_field, limit):
    if not isinstance(records, (tuple, list)) or len(records) > limit:
        raise TransportError(cls.__name__ + ": bounded list/tuple required")
    result = {}
    for row in records:
        if not isinstance(row, cls):
            raise TransportError(cls.__name__ + ": typed record required")
        key = _label(getattr(row, id_field), id_field)
        _label(row.evidence_id, cls.__name__ + ".evidence_id")
        if key in result:
            raise TransportError(cls.__name__ + ": duplicate identity " + key)
        result[key] = row
    return dict(sorted(result.items()))


def _scaled(value, name):
    value = F(value)
    approx = float(value)
    if not math.isfinite(approx) or (value and (approx == 0 or abs(approx) < 1e-12)):
        raise TransportError(name + ": LP scaling envelope exceeded (nonzero minimum 1e-12)")
    return approx


def solve_multicommodity(nodes, commodities, stocks, demands, links, capacity_groups,
                         *, period, objective, network_complete, evidence_id,
                         relative_gap_tolerance=1e-8):
    """Maximise explicitly weighted delivered kg across one coupled physical graph.

    Stock is transport-available mass AFTER externally accounted local obligations
    and reserves. Period IDs identify the same complete time window, not merely its
    duration. All capacities are total kg-throughput over that window; group load
    factors translate each commodity's explicit mass basis. No implicit conversion.
    The returned exact fractions conserve mass identically, after conservative
    primal repair; only optimality is approximate, with an exact upper-bound check.
    """
    _label(evidence_id, "network evidence_id")
    if not isinstance(network_complete, bool):
        raise TransportError("network_complete: explicit bool required")
    if not isinstance(period, Period) or not isinstance(objective, Objective):
        raise TransportError("typed period and objective required")
    _label(period.period_id, "period_id")
    seconds = _q(period.duration_seconds, "period duration", positive=True)
    _label(objective.scenario_id, "objective scenario_id")
    _label(objective.evidence_id, "objective evidence_id")
    if objective.name != OBJECTIVE:
        raise TransportError("unsupported explicit objective")
    tol = _q(relative_gap_tolerance, "relative_gap_tolerance", positive=True)
    if not F(1, 10**12) <= tol <= F(1, 10**4):
        raise TransportError("relative gap tolerance must lie in [1e-12, 1e-4]")
    ns = _records(nodes, Node, "node_id", MAX_NODES)
    cs = _records(commodities, Commodity, "commodity_id", MAX_COMMODITIES)
    ss = _records(stocks, Stock, "stock_id", MAX_STOCKS)
    ds = _records(demands, Demand, "demand_id", MAX_DEMANDS)
    ls = _records(links, Link, "link_id", MAX_LINKS)
    gs = _records(capacity_groups, CapacityGroup, "group_id", MAX_GROUPS)
    if not ns or not cs:
        raise TransportError("at least one node and commodity required")
    for n in ns.values():
        _label(n.mode, "node mode")
    for c in cs.values():
        _label(c.mass_basis, "commodity mass_basis")
        if c.unit != "kg":
            raise TransportError("commodity unit must explicitly be kg, not persons or energy")
    unknown = [] if network_complete else ["network completeness"]

    def value(v, name, positive=False):
        if v is None:
            unknown.append(name)
            return None
        return _q(v, name, positive=positive)

    def bound(row):
        _label(row.period_id, "record period_id")
        if row.period_id != period.period_id:
            raise TransportError("incompatible period: " + row.period_id)

    supplies, needs, weights, capacities = {}, {}, {}, {}
    for key, row in ss.items():
        bound(row)
        if row.node_id not in ns or row.commodity_id not in cs:
            raise TransportError("unknown stock node/commodity")
        supplies[key] = value(row.available_kg, "stock:" + key)
    for key, row in ds.items():
        bound(row)
        if row.node_id not in ns or row.commodity_id not in cs:
            raise TransportError("unknown demand node/commodity")
        needs[key] = value(row.required_kg, "demand:" + key)
        weights[key] = value(row.weight_per_kg, "weight:" + key, True)
    for key, row in gs.items():
        bound(row)
        capacities[key] = value(row.capacity_kg, "capacity:" + key)
    rules, costs = {}, {}
    for key, row in ls.items():
        bound(row)
        if row.from_node not in ns or row.to_node not in ns or row.from_node == row.to_node:
            raise TransportError("link endpoints must be distinct known mode-specific nodes")
        changes_mode = ns[row.from_node].mode != ns[row.to_node].mode
        if row.kind not in {"TRAVEL", "TRANSFER"} or changes_mode != (row.kind == "TRANSFER"):
            raise TransportError("mode changes require explicit TRANSFER edges; TRAVEL retains mode")
        if row.available is not None and not isinstance(row.available, bool):
            raise TransportError("link availability must be bool or UNKNOWN")
        if row.available is None:
            unknown.append("availability:" + key)
        costs[key] = value(row.travel_time_s, "travel_time:" + key, True)
        if not isinstance(row.rules, (tuple, list)) or len(row.rules) > MAX_COMMODITIES:
            raise TransportError("bounded explicit link commodity rules required")
        seen = set()
        for rule in row.rules:
            if not isinstance(rule, CommodityRule) or rule.commodity_id not in cs or rule.commodity_id in seen:
                raise TransportError("invalid/duplicate commodity rule")
            seen.add(rule.commodity_id)
            _label(rule.evidence_id, "rule evidence_id")
            if rule.allowed is not None and not isinstance(rule.allowed, bool):
                raise TransportError("commodity eligibility must be bool or UNKNOWN")
            if rule.allowed is None:
                unknown.append("eligibility:" + key + ":" + rule.commodity_id)
                continue
            if not rule.allowed or row.available is False:
                continue
            loss = value(rule.loss_fraction, "loss:" + key + ":" + rule.commodity_id)
            if loss is not None and loss > 1:
                raise TransportError("loss fraction exceeds one")
            if not isinstance(rule.capacity_uses, (tuple, list)) or len(rule.capacity_uses) > MAX_GROUPS:
                raise TransportError("bounded explicit capacity group uses required")
            if not rule.capacity_uses:
                unknown.append("capacity uses:" + key + ":" + rule.commodity_id)
            uses = {}
            for use in rule.capacity_uses:
                if not isinstance(use, CapacityUse) or use.group_id not in gs or use.group_id in uses:
                    raise TransportError("invalid/duplicate capacity group use")
                _label(use.evidence_id, "capacity use evidence_id")
                uses[use.group_id] = value(use.load_kg_per_kg_entering, "load factor:" + key + ":" + use.group_id, True)
            rules[key, rule.commodity_id] = (loss, uses)
        if row.available is not False:
            for missing in cs.keys() - seen:
                unknown.append("commodity rule:" + key + ":" + missing)
    input_payload = dict(nodes=list(ns.values()), commodities=list(cs.values()), stocks=list(ss.values()),
                         demands=list(ds.values()), links=list(ls.values()), capacity_groups=list(gs.values()),
                         period=period, objective=objective, network_complete=network_complete,
                         evidence_id=evidence_id, relative_gap_tolerance=relative_gap_tolerance)
    digest = hashlib.sha256(json.dumps(_canonical(input_payload), sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    result = {"schema": "diadem.multicommodity-transport.r2", "source_status": "WORKING NON-CANON",
              "production_authorised": False, "input_sha256": digest,
              "period": {"period_id": period.period_id, "duration_seconds": quantity(seconds)},
              "objective": asdict(objective), "network_evidence_id": evidence_id,
              "commodity_contracts": [asdict(c) for c in cs.values()],
              "cost_objective": "NOT OPTIMISED; reported route-entry-mass-weighted travel/handling time",
              "temporal_feasibility": "NOT EVALUATED: static aggregate throughput, not dispatch/deadline feasibility",
              "solved": False}
    if unknown:
        return {**result, "status": "MISSING_EVIDENCE", "missing_evidence": sorted(set(unknown)),
                "routes": None, "stocks": None, "demands": None, "flows": None, "capacity_groups": None}

    # Every beneficial flow has a simple-path representation: losses cannot create
    # mass, group loads/costs are nonnegative, and circulation is never rewarded.
    adjacency = {n: [] for n in ns}
    for key, link in ls.items():
        if link.available:
            adjacency[link.from_node].append(key)
    routes, path_steps = [], 0
    reachable = {d: False for d in ds}
    for sk, stock in ss.items():
        if supplies[sk] == 0:
            continue
        # Connectivity is separate from positive-delivery feasibility: a known
        # zero-capacity or complete-loss route is a shortage, not missing topology.
        connected = {stock.node_id}
        queue = [stock.node_id]
        for node in queue:
            for link_id in adjacency[node]:
                link = ls[link_id]
                if (link_id, stock.commodity_id) in rules and link.to_node not in connected:
                    connected.add(link.to_node); queue.append(link.to_node)
        for dk, demand in ds.items():
            if demand.commodity_id == stock.commodity_id and demand.node_id in connected:
                reachable[dk] = True
        for dk, demand in ds.items():
            if stock.commodity_id != demand.commodity_id or needs[dk] == 0:
                continue
            stack = [(stock.node_id, (), frozenset([stock.node_id]), F(1), {}, F(0), ())]
            while stack:
                node, path, visited, survival, loads, cost, entries = stack.pop()
                path_steps += 1
                if path_steps > MAX_PATH_STEPS:
                    raise TransportError("simple-path search budget exceeded; no partial network optimum returned")
                if node == demand.node_id:
                    coefficients = {"stock:" + sk: F(1), "demand:" + dk: survival}
                    coefficients.update({"capacity:" + k: v for k, v in loads.items()})
                    upper = min([supplies[sk], needs[dk] / survival] +
                                [capacities[k] / v for k, v in loads.items()])
                    if upper:
                        routes.append({"stock": sk, "demand": dk, "commodity": stock.commodity_id,
                                       "links": path, "survival": survival, "loads": loads,
                                       "entry_fractions": entries, "cost": cost, "upper": upper,
                                       "coefficients": coefficients, "objective": survival * weights[dk]})
                        if len(routes) > MAX_ROUTES:
                            raise TransportError("route budget exceeded; no partial optimum returned")
                    continue
                for link_id in reversed(adjacency[node]):
                    link = ls[link_id]
                    rule = rules.get((link_id, stock.commodity_id))
                    if rule is None or link.to_node in visited or rule[0] == 1:
                        continue
                    loss, uses = rule
                    new_loads = dict(loads)
                    for group_id, factor in uses.items():
                        new_loads[group_id] = new_loads.get(group_id, F(0)) + survival * factor
                    stack.append((link.to_node, path + (link_id,), visited | {link.to_node},
                                  survival * (1 - loss), new_loads, cost + survival * costs[link_id],
                                  entries + (survival,)))

    caps = {**{"stock:" + k: v for k, v in supplies.items()},
            **{"demand:" + k: v for k, v in needs.items()},
            **{"capacity:" + k: v for k, v in capacities.items()}}
    labels = sorted(caps)
    row_index = {label: i for i, label in enumerate(labels)}
    rows = {label: {} for label in labels}
    for j, route in enumerate(routes):
        for label, a in route["coefficients"].items():
            rows[label][j] = a
    x = [F(0)] * len(routes)
    prices = {label: F(0) for label in labels}
    bound_prices = [F(0)] * len(routes)
    contraction = F(1)
    if routes:
        objective_scale = max(r["objective"] * r["upper"] for r in routes)
        rr, cc, vv = [], [], []
        for label in labels:
            for j, a in rows[label].items():
                rr.append(row_index[label]); cc.append(j)
                vv.append(_scaled(a * routes[j]["upper"] / caps[label], "constraint coefficient"))
        matrix = csc_matrix((vv, (rr, cc)), shape=(len(labels), len(routes)))
        c = [-_scaled(r["objective"] * r["upper"] / objective_scale, "objective coefficient") for r in routes]
        solved = linprog(c, A_ub=matrix, b_ub=np.ones(len(labels)), bounds=(0, 1), method="highs-ds",
                         options={"presolve": True, "primal_feasibility_tolerance": 1e-9,
                                  "dual_feasibility_tolerance": 1e-9, "time_limit": 10.0,
                                  "maxiter": 100_000, "simplex_dual_edge_weight_strategy": "steepest"})
        if not solved.success or solved.status != 0 or not np.isfinite(solved.x).all():
            return {**result, "status": "NUMERICAL_FAILURE", "reason": str(solved.message)}
        if len(solved.x) != len(routes) or len(solved.ineqlin.marginals) != len(labels) or not np.isfinite(solved.ineqlin.marginals).all():
            return {**result, "status": "NUMERICAL_FAILURE", "reason": "invalid solver primal/dual shape or values"}
        x = [F(float(min(1.0, max(0.0, z)))) * r["upper"] for z, r in zip(solved.x, routes)]
        # A nonnegative packing LP admits monotone downward exact feasibility repair.
        # This is a represented mass adjustment, never a hidden residual write-off.
        for label in labels:
            used = sum((a * x[j] for j, a in rows[label].items()), F(0))
            if used > caps[label]:
                factor = caps[label] / used
                contraction = min(contraction, factor)
                for j in rows[label]:
                    x[j] *= factor
        for label, marginal in zip(labels, solved.ineqlin.marginals):
            if caps[label]:
                prices[label] = max(F(0), -F(float(marginal))) * objective_scale / caps[label]
        for j, route in enumerate(routes):
            bound_prices[j] = max(F(0), route["objective"] - sum(
                (a * prices[label] for label, a in route["coefficients"].items()), F(0)))
    achieved = sum((r["objective"] * v for r, v in zip(routes, x)), F(0))
    upper = sum((caps[k] * prices[k] for k in labels), F(0)) + sum(
        (r["upper"] * p for r, p in zip(routes, bound_prices)), F(0))
    gap = upper - achieved
    if gap < 0 or gap > tol * upper:
        return {**result, "status": "NUMERICAL_FAILURE", "reason": "exact weak-duality gap gate failed",
                "objective_achieved": quantity(achieved), "objective_upper_bound": quantity(upper), "objective_gap": quantity(gap)}

    stock_use = {s: F(0) for s in ss}; served = {d: F(0) for d in ds}
    group_use = {g: F(0) for g in gs}
    incoming = {(n, c): F(0) for n in ns for c in cs}
    outgoing = dict(incoming)
    flow = {(l, c): [F(0), F(0)] for l in ls for c in cs}
    route_rows = []
    transport_cost = F(0)
    for j, (route, dispatched) in enumerate(zip(routes, x)):
        delivered = dispatched * route["survival"]
        stock_use[route["stock"]] += dispatched
        served[route["demand"]] += delivered
        transport_cost += dispatched * route["cost"]
        route_groups = []
        for g, load in sorted(route["loads"].items()):
            group_use[g] += dispatched * load
            route_groups.append({"group_id": g, "load_per_dispatched_kg": quantity(load), "load_kg": quantity(dispatched * load)})
        legs = []
        for l, entry_fraction in zip(route["links"], route["entry_fractions"]):
            entered = dispatched * entry_fraction
            exited = entered * (1 - rules[l, route["commodity"]][0])
            flow[l, route["commodity"]][0] += entered
            flow[l, route["commodity"]][1] += exited
            outgoing[ls[l].from_node, route["commodity"]] += entered
            incoming[ls[l].to_node, route["commodity"]] += exited
            legs.append({"link_id": l, "entered_kg": quantity(entered), "exited_kg": quantity(exited), "lost_kg": quantity(entered - exited)})
        route_rows.append({"route_id": j, "stock_id": route["stock"], "demand_id": route["demand"],
                           "commodity_id": route["commodity"], "link_ids": list(route["links"]),
                           "dispatched_kg": quantity(dispatched), "delivered_kg": quantity(delivered),
                           "lost_kg": quantity(dispatched - delivered), "survival_fraction": quantity(route["survival"]),
                           "dispatch_upper_kg": quantity(route["upper"]), "capacity_loads": route_groups, "legs": legs,
                           "cost_kg_s": quantity(dispatched * route["cost"]),
                           "objective_per_dispatched_kg": quantity(route["objective"]),
                           "dual_upper_price": quantity(bound_prices[j])})
    stock_rows = [{"stock_id": k, "node_id": s.node_id, "commodity_id": s.commodity_id, "evidence_id": s.evidence_id,
                   "available_kg": quantity(supplies[k]), "used_kg": quantity(stock_use[k]),
                   "unused_kg": quantity(supplies[k] - stock_use[k])} for k, s in ss.items()]
    demand_rows = []
    for k, d in ds.items():
        status = "FULFILLED" if served[k] == needs[k] else "SHORTAGE"
        if needs[k] == 0:
            status = "NO_DEMAND"
        elif not reachable[k] and any(supplies[s] > 0 and ss[s].commodity_id == d.commodity_id for s in ss):
            status = "NO_PATH_FROM_KNOWN_STOCK"
        demand_rows.append({"demand_id": k, "node_id": d.node_id, "commodity_id": d.commodity_id,
                            "evidence_id": d.evidence_id, "status": status, "weight_per_kg": quantity(weights[k]),
                            "required_kg": quantity(needs[k]), "delivered_kg": quantity(served[k]),
                            "shortage_kg": quantity(needs[k] - served[k])})
    flow_rows = [{"link_id": l, "commodity_id": c, "from_node": ls[l].from_node, "to_node": ls[l].to_node,
                  "entered_kg": quantity(a), "exited_kg": quantity(b), "lost_kg": quantity(a-b)}
                 for (l, c), (a, b) in sorted(flow.items())]
    node_rows = []
    for n in ns:
        for c in cs:
            used = sum((stock_use[k] for k, s in ss.items() if s.node_id == n and s.commodity_id == c), F(0))
            consumed = sum((served[k] for k, d in ds.items() if d.node_id == n and d.commodity_id == c), F(0))
            residual = used + incoming[n, c] - consumed - outgoing[n, c]
            if residual:
                raise TransportError("exact node mass balance failed")
            node_rows.append({"node_id": n, "commodity_id": c, "stock_used_kg": quantity(used),
                              "arrived_kg": quantity(incoming[n, c]), "delivered_kg": quantity(consumed),
                              "departed_kg": quantity(outgoing[n, c]), "residual_kg": quantity(residual)})
    for label in labels:
        if sum((a * x[j] for j, a in rows[label].items()), F(0)) > caps[label]:
            raise TransportError("exact capacity/stock/demand feasibility failed")
    totals = []
    for c in cs:
        available = sum((supplies[k] for k in ss if ss[k].commodity_id == c), F(0))
        dispatched = sum((stock_use[k] for k in ss if ss[k].commodity_id == c), F(0))
        delivered = sum((served[k] for k in ds if ds[k].commodity_id == c), F(0))
        required = sum((needs[k] for k in ds if ds[k].commodity_id == c), F(0))
        lost = sum((a-b for (l, co), (a, b) in flow.items() if co == c), F(0))
        if dispatched != delivered + lost:
            raise TransportError("exact commodity conservation failed")
        totals.append({"commodity_id": c, "stock_kg": quantity(available), "dispatched_kg": quantity(dispatched),
                       "delivered_kg": quantity(delivered), "loss_kg": quantity(lost), "unused_stock_kg": quantity(available-dispatched),
                       "demand_kg": quantity(required), "shortage_kg": quantity(required-delivered)})
    return {**result, "solved": True, "status": "ALL_DEMAND_SERVED" if all(served[k] == needs[k] for k in ds) else "PARTIAL_OR_UNSERVED_DEMAND",
            "stocks": stock_rows, "demands": demand_rows, "flows": flow_rows, "routes": route_rows,
            "node_balances": node_rows, "commodity_totals": totals,
            "capacity_groups": [{"group_id": k, "capacity_kg": quantity(capacities[k]), "used_kg": quantity(group_use[k]),
                                 "unused_kg": quantity(capacities[k]-group_use[k]), "evidence_id": g.evidence_id} for k, g in gs.items()],
            "transport_cost_kg_s": quantity(transport_cost),
            "certificate": {"arithmetic": "EXACT_RATIONAL_REPRESENTED_FLOWS", "mass_residual_kg": "0",
                            "capacity_violations": 0, "method": "highs-ds; monotone exact primal contraction; exact weak duality",
                            "scipy_version": scipy.__version__, "routes_enumerated": len(routes), "path_search_steps": path_steps,
                            "objective_achieved": quantity(achieved), "objective_upper_bound": quantity(upper),
                            "objective_gap": quantity(gap), "relative_gap_tolerance": quantity(tol),
                            "minimum_single_repair_factor": quantity(contraction),
                            "row_prices": [{"constraint": k, "capacity": quantity(caps[k]), "price": quantity(prices[k])} for k in labels],
                            "tie_policy": "Unspecified numerical optimum; no fairness or priority inferred beyond explicit weights",
                            "scope": "all enumerated simple routes on the complete supplied graph; no production or empirical validation"}}
