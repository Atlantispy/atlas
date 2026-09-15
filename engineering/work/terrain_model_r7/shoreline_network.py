"""Read-only native D8/pool ownership for the bounded R4 shoreline operator.

Bed/storage cells own their supplied areas; x/y spacing sets centre distances.
This derives a current graph, not a whole-interval ownership or hydraulic PASS.
"""
from fractions import Fraction
import math

import phase_storage
from shoreline import ShorelineError, _state, _number, _vector, _sum, _product, _ids


class NetworkError(ShorelineError):
    """Invalid routed state or a numerical closure not supplied by this graph."""

    def __init__(self, message, **context):
        super().__init__(message)
        self.context = context


def _neighbours(i, shape, connectivity):
    r, c = divmod(i, shape[1])
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            if not dr and not dc or connectivity == 4 and abs(dr) + abs(dc) != 1:
                continue
            rr, cc = r + dr, c + dc
            if 0 <= rr < shape[0] and 0 <= cc < shape[1]:
                yield rr * shape[1] + cc, dr, dc


def _components(cells, shape, connectivity, bed=None):
    remaining, result = set(cells), []
    while remaining:
        first = min(remaining)
        remaining.remove(first)
        todo, found = [first], [first]
        while todo:
            i = todo.pop()
            for j, _, _ in _neighbours(i, shape, connectivity):
                if j in remaining and (bed is None or bed[j] == bed[i]):
                    remaining.remove(j)
                    todo.append(j)
                    found.append(j)
        result.append(sorted(found))
    return result


def _ratio(value):
    return {"numerator": value.numerator, "denominator": value.denominator}


def _members(bits, n):
    return [i for i in range(n) if bits & (1 << i)]


def build_network(state, *, dx_m, dy_m, external_outlets, runoff_m_year,
                  incoming_liquid_m3_year=None, incoming_solid_m3_year=None,
                  connectivity=4, activated_margins=None):
    """Return channel_kwargs plus exact ownership/catchment/event evidence.

    Input W/S must already describe routed, locally mixed positive-depth pools.
    Boundary rates are new parcels, not duplicates of local runoff. Native area
    is accumulated once; unknown external contributing area is NOT invented.
    Existing-pool zero-depth margins are never autoactivated. An explicit
    activated_margins={cell: existing_pool_id} assertion requires the driver's
    independently checked positive net-depth rate, including sediment/settling.
    """
    n, shape, area, _, _, water, solid, bed = _state(state, allow_liquid_remainder=True)
    residuals = phase_storage.liquid_remainders(water, getattr(state, 'liquid_remainder_m3', None))
    if any(residuals) and any(solid):
        raise NetworkError('nonzero liquid remainder with suspension requires exact phase transport')
    dx = _number(dx_m, "dx_m", 0, True)
    dy = _number(dy_m, "dy_m", 0, True)
    if type(connectivity) is not int or connectivity not in (4, 8):
        raise NetworkError("pool connectivity must be explicit 4 or 8")
    outlets = _ids(external_outlets, n, "external outlets")
    for i in outlets:
        r, c = divmod(i, shape[1])
        if r not in (0, shape[0]-1) and c not in (0, shape[1]-1):
            raise NetworkError("external outlet must be on a native edge")
        if water[i] or solid[i]:
            raise NetworkError("external outlet and stored pool phases must be disjoint")
    runoff = _vector(runoff_m_year, n, "runoff_m_year", 0, scalar=True)
    inlet_w = _vector([0.] * n if incoming_liquid_m3_year is None else incoming_liquid_m3_year,
                      n, "incoming_liquid_m3_year", 0)
    inlet_s = _vector([0.] * n if incoming_solid_m3_year is None else incoming_solid_m3_year,
                      n, "incoming_solid_m3_year", 0)
    if any(s > 0 and w == 0 for w, s in zip(inlet_w, inlet_s)):
        raise NetworkError("external suspension requires an explicit incoming liquid carrier")
    local = [_product(runoff[i], area[i], name="local runoff rate") for i in range(n)]
    supplied = [_sum((a, b)) for a, b in zip(local, inlet_w)]
    modules, binding = phase_storage._bound_sources()
    try:
        topology = modules["basin_topology.py"].extract_basin_topology(
            list(bed), list(shape), sorted(outlets), connectivity=connectivity)
        owner, stages, pools, exact_stages = [None] * n, {}, [], {}
        fbed, farea = list(map(Fraction, bed)), list(map(Fraction, area))
        wet = [i for i in range(n) if water[i] or solid[i]]
        for cells in _components(wet, shape, connectivity):
            name = "pool_%04d" % min(cells)
            volume = sum((Fraction(water[i]) + residuals[i] + Fraction(solid[i]) for i in cells), Fraction())
            exact_eta = phase_storage._exact_stage([fbed[i] for i in cells], [farea[i] for i in cells], volume)
            eta = _number(float(exact_eta), "pool stage")
            if any(exact_eta <= fbed[i] or eta <= bed[i] for i in cells):
                raise NetworkError("positive pool depth is not representable")
            total_w, total_s = _sum(water[i] for i in cells), _sum(solid[i] for i in cells)
            concentration = total_s / _sum((total_w, total_s))
            for i in cells:
                expected = (eta-bed[i]) * area[i]
                actual = _sum((water[i], solid[i]))
                phase_storage._check(actual-expected, actual, expected)
                phase_storage._check(solid[i]-concentration*actual, solid[i], concentration*actual)
                owner[i] = name
            stages[name], exact_stages[name] = eta, exact_eta
            pools.append({"id": name, "cell_indices": cells, "wet_cell_indices": list(cells),
                          "incipient_cell_indices": [], "stage_m": eta,
                          "exact_stage_m": _ratio(exact_eta), "liquid_m3": total_w,
                          "liquid_remainder_m3": phase_storage.ratio(sum((Fraction(water[i])+residuals[i] for i in cells), Fraction())-Fraction(total_w)),
                          "suspended_solid_m3": total_s, "solid_volume_fraction": concentration})

        # This is only an ownership assertion seam. Positive inflow alone does
        # not prove positive margin depth when local settling raises the bed.
        claims = {}
        for pool in pools:
            name = pool['id']
            for i in pool['cell_indices']:
                for j, _, _ in _neighbours(i, shape, connectivity):
                    if owner[j] is None and j not in outlets and bed[j] == stages[name]:
                        claims.setdefault(j, set()).add(name)
        asserted = {} if activated_margins is None else activated_margins
        if type(asserted) is not dict or len(asserted) > n:
            raise NetworkError('activated_margins requires a bounded cell-to-existing-pool mapping')
        activations = []
        for i, name in asserted.items():
            if type(i) is not int or not 0 <= i < n or type(name) is not str or name not in stages:
                raise NetworkError('invalid asserted margin or existing pool identity')
            if water[i] != 0 or solid[i] != 0 or owner[i] is not None or i in outlets:
                raise NetworkError('asserted margin is not a disjoint zero-phase native cell')
            if claims.get(i) != {name}:
                raise NetworkError('asserted margin lacks one unambiguous adjacent pool claim',
                                   cell_index=i, candidate_pool_ids=sorted(claims.get(i, [])))
            if bed[i] != stages[name]:
                raise NetworkError('asserted margin bed does not equal represented pool stage')
            if fbed[i] != exact_stages[name]:
                raise NetworkError('native margin contact is not exact; represented stage equality cannot authorise wetting')
            activations.append({'cell_index': i, 'pool_id': name, 'bed_m': bed[i],
                                'exact_stage_equals_bed': exact_stages[name] == fbed[i],
                                'status': 'DRIVER_ASSERTED_NET_DEPTH_RATE_NOT_PROVEN_BY_NETWORK'})
        for row in activations:
            i, name = row['cell_index'], row['pool_id']
            owner[i] = name
            pool = next(p for p in pools if p['id'] == name)
            pool['cell_indices'] = sorted([*pool['cell_indices'], i])
            pool['incipient_cell_indices'] = sorted([*pool['incipient_cell_indices'], i])

        raw, raw_length = [-1] * n, [0.] * n
        for i in range(n):
            if i in outlets:
                continue
            candidates = []
            for j, dr, dc in _neighbours(i, shape, 8):
                if bed[j] >= bed[i]:
                    continue
                distance = _number(math.hypot(dc*dx, dr*dy), "native link distance", 0, True)
                drop = _number(bed[i]-bed[j], "raw strict drop", 0, True)
                slope = _number(drop/distance, "raw strict slope", 0, True)
                candidates.append((slope, -j, j, distance))
            if candidates:
                _, _, raw[i], raw_length[i] = max(candidates)
        receivers = [raw[i] if owner[i] is None else -1 for i in range(n)]
        lengths = [raw_length[i] if owner[i] is None else 0. for i in range(n)]
        order = sorted(range(n), key=lambda i: (-bed[i], i))
        # Initial strict-graph discharge locates genuine positive-input pits.
        initial_q = list(supplied)
        for i in order:
            if receivers[i] >= 0:
                j = receivers[i]
                initial_q[j] = _sum((initial_q[j], initial_q[i]))
        new_events, incipient = [], [row['cell_index'] for row in activations]
        dry = [i for i in range(n) if owner[i] is None]
        for cells in _components(dry, shape, connectivity, bed):
            terminals = [i for i in cells if receivers[i] == -1 and i not in outlets and initial_q[i] > 0]
            if not terminals:
                continue
            lower = sorted({j for i in cells for j, _, _ in _neighbours(i, shape, 8) if bed[j] < bed[i]})
            if lower or any(i in outlets for i in cells):
                raise NetworkError("positive-flow draining flat requires a separate flat-routing closure",
                                   flat_cells=cells, lower_neighbours=lower, positive_terminal_cells=terminals)
            name = "pool_%04d" % min(cells)
            inflow = _sum(initial_q[i] for i in cells)
            if inflow <= 0:
                raise NetworkError("incipient bottom lacks actual right-limit inflow")
            for i in cells:
                owner[i], receivers[i], lengths[i] = name, -1, 0.
            eta = bed[cells[0]]
            stages[name], exact_stages[name] = eta, Fraction(eta)
            incipient.extend(cells)
            pools.append({"id": name, "cell_indices": cells, "wet_cell_indices": [],
                          "incipient_cell_indices": list(cells), "stage_m": eta,
                          "exact_stage_m": _ratio(Fraction(eta)), "liquid_m3": 0.,
                          "suspended_solid_m3": 0., "solid_volume_fraction": 0.})
            new_events.append({"kind": "INCIPIENT_BOTTOM_RIGHT_LIMIT", "time_offset_years": 0.,
                               "pool_id": name, "cell_indices": cells,
                               "actual_liquid_inflow_m3_year": inflow,
                               "invented_liquid_m3": 0., "invented_depth_m": 0.})

        masks = [1 << i for i in range(n)]
        q = list(supplied)
        for i in order:
            j = receivers[i]
            if j >= 0:
                if owner[i] is not None or not bed[i] > bed[j]:
                    raise NetworkError("contracted graph is not strict descending")
                if masks[j] & masks[i]:
                    raise NetworkError("native catchment double counting")
                masks[j] |= masks[i]
                q[j] = _sum((q[j], q[i]))
        contributing = [_sum(area[j] for j in _members(bits, n)) for bits in masks]
        destination_cell = [-1] * n
        for i in reversed(order):
            destination_cell[i] = i if receivers[i] < 0 else destination_cell[receivers[i]]
            if destination_cell[i] < 0:
                raise NetworkError("strict destination traversal did not terminate")
        destinations = [{"kind": "POOL" if owner[j] is not None else "EXTERNAL" if j in outlets else "DRY_NO_FLOW_TERMINAL",
                         "cell_index": j, "pool_id": owner[j]} for j in destination_cell]
        terminal_masks, complete = [], 0
        for i in range(n):
            if receivers[i] < 0:
                if complete & masks[i]:
                    raise NetworkError("terminal catchments overlap")
                complete |= masks[i]
                terminal_masks.append({"cell_index": i, "kind": destinations[i]["kind"],
                                       "native_area_m2": contributing[i], "source_membership_hex": hex(masks[i])})
                if owner[i] is None and i not in outlets and q[i] > 0:
                    raise NetworkError("positive-flow dry terminal was not classified")
        if complete != (1 << n)-1:
            raise NetworkError("terminal catchments omit native source area")
        rows = topology["basins"]
        by_id = {row["id"]: row for row in rows}
        margins, unsupported = [], []
        for pool in sorted(pools, key=lambda row: row["id"]):
            name, cells = pool["id"], pool["cell_indices"]
            cell_set, eta, exact_eta = set(cells), stages[name], exact_stages[name]
            catchment = 0
            for i in cells:
                if catchment & masks[i]:
                    raise NetworkError("pool catchment contains duplicate source cells")
                catchment |= masks[i]
            pool.update({"catchment_cell_indices": _members(catchment, n),
                         "native_contributing_area_m2": _sum(area[i] for i in _members(catchment, n)),
                         "actual_liquid_inflow_m3_year": _sum(q[i] for i in cells),
                         "local_runoff_m3_year": _sum(local[i] for i in cells),
                         "explicit_liquid_inlet_m3_year": _sum(inlet_w[i] for i in cells),
                         "dry_tributary_liquid_m3_year": _sum(q[i]-supplied[i] for i in cells)})
            boundary = sorted({j for i in cells for j, _, _ in _neighbours(i, shape, connectivity) if j not in cell_set})
            for j in boundary:
                if owner[j] is not None:
                    raise NetworkError("adjacent positive-depth pools were not a single component")
                if fbed[j] < exact_eta:
                    raise NetworkError("unowned native neighbour lies below current pool stage", pool_id=name, cell_index=j)
                if bed[j] == eta and j not in outlets:
                    margins.append({"pool_id": name, "cell_index": j, "stage_m": eta,
                                    "bed_m": bed[j], "exact_stage_equals_bed": exact_eta == fbed[j],
                                    "exact_freeboard_m": _ratio(fbed[j]-exact_eta),
                                    "pool_liquid_inflow_m3_year": pool["actual_liquid_inflow_m3_year"],
                                    "activation": "DRIVER_MUST_CHECK_NET_DEPTH_RATE_INCLUDING_SETTLING"})
            candidates = [row for row in rows if cell_set <= set(row["cell_indices"])]
            if not candidates:
                raise NetworkError("pool has no numerical basin ownership; state is not routed")
            row = min(candidates, key=lambda r: (len(r["cell_indices"]), r["id"]))
            sill = row["spill_m"]
            if sill is not None and exact_eta > Fraction(sill):
                raise NetworkError("pool state is above its exact spill; reroute first")
            event = next((e for e in topology["saddle_events"] if
                          e.get("source") == row["id"] or row["id"] in e.get("children", [])), None)
            spill = {"basin_id": row["id"], "spill_m": sill, "spill_to_leaf": row["spill_to_leaf"],
                     "at_exact_spill": sill is not None and exact_eta == Fraction(sill),
                     "kind": "CLOSED" if sill is None else "UNRESOLVED_EDGE",
                     "edge_cells": None, "receiver_cell": None, "receiver_pool_id": None,
                     "supports_current_driver": sill is None}
            if sill is not None:
                if event is None:
                    raise NetworkError("finite basin spill lacks a saddle-edge record")
                footprint = set(row["cell_indices"])
                edge = list(event["edge_cells"])
                outside = [j for j in edge if j not in footprint]
                if len(outside) != 1:
                    raise NetworkError("spill edge does not identify one geographic receiver")
                j = outside[0]
                spill.update(edge_cells=edge, receiver_cell=j, receiver_pool_id=owner[j])
                if j in outlets:
                    spill.update(kind="IMMEDIATE_EXTERNAL", supports_current_driver=True)
                elif owner[j] is not None:
                    spill.update(kind="EXISTING_POOL", supports_current_driver=False)
                else:
                    spill.update(kind="DRY_CORRIDOR_REQUIRES_CHANNEL_ROUTING", supports_current_driver=False)
                spill["receiver_raw_destination"] = destinations[j]
                if not spill["supports_current_driver"]:
                    unsupported.append({"pool_id": name, **spill,
                                        "actual_positive_liquid_input": pool["actual_liquid_inflow_m3_year"] > 0,
                                        "scope": "POTENTIAL_SPILL_NOT_AN_EXECUTED_EXPORT"})
            pool["spill"] = spill
            future = [bed[j] for j in boundary if bed[j] > eta]
            pool["next_native_wetting_stage_m"] = min(future) if future else None
        pool_in = _sum(row["actual_liquid_inflow_m3_year"] for row in pools)
        external = _sum(q[i] for i in outlets)
        unused = _sum(q[i] for i in range(n) if receivers[i] < 0 and owner[i] is None and i not in outlets)
        input_rate = _sum(supplied)
        residual = _sum((pool_in, external, unused, -input_rate))
        phase_storage._check(residual, input_rate, pool_in, external)
        return {"schema": "diadem.terrain.shoreline-network.v1", "status": "PASS_CURRENT_GRAPH_ONLY",
                "channel_kwargs": {"receivers": receivers, "link_lengths_m": lengths,
                                   "contributing_area_m2": contributing, "pool_owner": owner,
                                   "pool_stages_m": stages, "incipient_pool_cells": sorted(incipient),
                                   "external_outlets": sorted(outlets)},
                "pools": sorted(pools, key=lambda row: row["id"]), "raw_receivers": raw,
                "raw_link_lengths_m": raw_length, "dry_topological_order": order,
                "destination_cell_indices": destination_cell, "destinations": destinations,
                "catchment_membership_hex": [hex(v) for v in masks], "terminal_catchments": terminal_masks,
                "dry_no_flow_terminals": [i for i in range(n) if receivers[i] < 0 and owner[i] is None and i not in outlets],
                "zero_time_events": new_events, "zero_depth_margin_candidates": margins,
                "asserted_margin_activations": sorted(activations, key=lambda row: row['cell_index']),
                "unsupported_spill_routes": unsupported,
                "liquid_rates": {"local_runoff_m3_year": local, "explicit_inlet_m3_year": list(inlet_w),
                                 "at_native_cell_m3_year": q, "pool_delivery_m3_year": pool_in,
                                 "external_delivery_m3_year": external, "source_total_m3_year": input_rate,
                                 "routing_residual_m3_year": residual},
                "native_area_ledger": {"source_area_m2": _sum(area),
                                       "terminal_area_m2": _sum(row["native_area_m2"] for row in terminal_masks),
                                       "exact_membership_partition": True},
                "topology": topology, "source_binding": binding,
                "assumptions": {"channel_connectivity": 8, "pool_connectivity": connectivity,
                                "tie_break": "largest binary64 bed slope then lowest receiver index",
                                "dx_m": dx, "dy_m": dy, "area_basis": "caller native cell areas",
                                "external_contributing_area": "UNKNOWN_NOT_ADDED",
                                "phase_state_mutated": False, "zero_depth_margins_autoactivated": False,
                                "asserted_margin_net_depth_rate_verified": False,
                                "whole_interval_ownership_proven": False, "production_authorised": False}}
    finally:
        phase_storage._recheck(binding)
