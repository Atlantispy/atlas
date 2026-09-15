"""Conservative bounded water interfaces. No IO, terrain mutation or hydraulics.

See WATER_METHODS.md for source equations, predeclared tolerances and limits.
All elevation/stage arguments must share the caller's explicitly bound datum.
"""
from __future__ import annotations

import heapq
import math

MAX_CELLS = 16384
MAX_EDGES = 131072
MAX_BASINS = 4096
MAX_FOOTPRINT_REFERENCES = 262144
VOLUME_ATOL = 1e-9
AREA_ATOL = 1e-9
RTOL = 1e-12


def _num(value, name, *, positive=False, nonnegative=False):
    if type(value) not in (int, float):
        raise ValueError(name + " must be a finite number, not Boolean")
    try:
        value = float(value)
    except (ValueError, OverflowError) as exc:
        raise ValueError(name + " exceeds binary64") from exc
    if not math.isfinite(value) or positive and value <= 0 or nonnegative and value < 0:
        raise ValueError(name + " outside finite supported range")
    return value


def _sum(values):
    try:
        return _num(math.fsum(values), "derived sum")
    except OverflowError as exc:
        raise ValueError("derived sum overflow") from exc


def _values(values, name, *, positive=False, nonnegative=False):
    if type(values) is not list or not 1 <= len(values) <= MAX_CELLS:
        raise ValueError(name + " requires1..16384 list entries")
    return [_num(v, name, positive=positive, nonnegative=nonnegative) for v in values]


def _arrays(bed, area):
    bed = _values(bed, "bed_m")
    area = _values(area, "cell_area_m2", positive=True)
    if len(bed) != len(area):
        raise ValueError("array lengths differ")
    return bed, area


def _index(value, n):
    if type(value) is not int or not 0 <= value < n:
        raise ValueError("invalid cell index")
    return value


def _balance(residual, *magnitudes, atol=VOLUME_ATOL):
    residual = _num(residual, "ledger residual")
    scale = max([0.] + [abs(_num(v, "ledger scale")) for v in magnitudes])
    if abs(residual) > atol + RTOL * scale:
        raise ValueError("conservation/representation error exceeds declared tolerance")
    return residual


def priority_flood(bed_m, shape, outlet_indices, *, connectivity=4):
    """Minimax routing surface; seed cells are explicit computational outlets.

    The predecessor points to an earlier-popped cell, so equal levels do not
    need epsilon bed changes. This is NOT finite-water basin filling or D8
    steepest-descent routing on the raw physical bed.
    """
    bed = _values(bed_m, "bed_m")
    n = len(bed)
    if type(shape) not in (list, tuple) or len(shape) != 2 or any(type(v) is not int or v <= 0 for v in shape):
        raise ValueError("shape requires two positive integers")
    rows, cols = shape
    if rows * cols != n or type(connectivity) is not int or connectivity not in (4, 8):
        raise ValueError("shape/connectivity mismatch")
    if type(outlet_indices) is not list or not 1 <= len(outlet_indices) <= n:
        raise ValueError("explicit outlets required; crop edges are not implied")
    outlets = [_index(v, n) for v in outlet_indices]
    if len(set(outlets)) != len(outlets):
        raise ValueError("duplicate outlet")
    surface = list(bed)
    receivers = [None] * n
    seen = [False] * n
    heap = []
    for i in sorted(outlets):
        seen[i] = True
        heapq.heappush(heap, (bed[i], i))
    offsets = [(-1, 0), (0, -1), (0, 1), (1, 0)]
    if connectivity == 8:
        offsets += [(-1, -1), (-1, 1), (1, -1), (1, 1)]
    order = []
    while heap:
        level, i = heapq.heappop(heap)
        order.append(i)
        y, x = divmod(i, cols)
        neighbours = []
        for dy, dx in offsets:
            yy, xx = y + dy, x + dx
            if 0 <= yy < rows and 0 <= xx < cols:
                neighbours.append(yy * cols + xx)
        for j in sorted(neighbours):
            if not seen[j]:
                seen[j] = True
                surface[j] = max(level, bed[j])
                receivers[j] = i
                heapq.heappush(heap, (surface[j], j))
    depths = [_num(z - b, "conditioning depth", nonnegative=True) for z, b in zip(surface, bed)]
    return {"routing_surface_m": surface, "receivers": receivers, "pop_order": order,
            "conditioning_depth_m": depths, "physical_bed_changed": False,
            "boundary_status": "CALLER_DESIGNATED_COMPUTATIONAL_OUTLETS_NOT_AUTHENTICATED"}


def accumulate_runoff(receivers, cell_area_m2, runoff_m_per_year, terminal_kinds):
    """Lossless static DAG accumulation with conservative fractional splits."""
    area = _values(cell_area_m2, "area", positive=True)
    runoff = _values(runoff_m_per_year, "runoff", nonnegative=True)
    n = len(area)
    if len(runoff) != n or type(receivers) is not list or len(receivers) != n or type(terminal_kinds) is not dict:
        raise ValueError("routing array/schema mismatch")
    edges, incoming = [], [[] for _ in range(n)]
    edge_count = 0
    dependencies = [0] * n
    terminals = []
    for i, row in enumerate(receivers):
        if type(row) is not list or len(row) > n:
            raise ValueError("edge list required")
        edge_count += len(row)
        if edge_count > MAX_EDGES:
            raise ValueError("routing graph exceeds bounded edge count")
        converted, used = [], set()
        for pair in row:
            if type(pair) not in (list, tuple) or len(pair) != 2:
                raise ValueError("edge requires index and fraction")
            j = _index(pair[0], n)
            fraction = _num(pair[1], "routing fraction", positive=True)
            if j == i or j in used or fraction > 1:
                raise ValueError("duplicate/self/invalid routing edge")
            used.add(j)
            converted.append((j, fraction))
            dependencies[j] += 1
        if converted and _sum(f for _, f in converted) != 1.:
            raise ValueError("outgoing fractions must sum exactly to1")
        if not converted:
            terminals.append(i)
        edges.append(sorted(converted))
    if (any(type(i) is not int for i in terminal_kinds) or set(terminal_kinds) != set(terminals) or
            any(v not in ("PHYSICAL_EXPORT", "PROVISIONAL_BOUNDARY", "UNRESOLVED_CROP", "BASIN_STORAGE") for v in terminal_kinds.values())):
        raise ValueError("each and only terminal needs an explicit permitted kind")
    heap = [i for i, count in enumerate(dependencies) if count == 0]
    heapq.heapify(heap)
    effective_area, discharge = [0.] * n, [0.] * n
    local_water = [_num(a * r, "local runoff volume rate", nonnegative=True) for a, r in zip(area, runoff)]
    order = []
    while heap:
        i = heapq.heappop(heap)
        order.append(i)
        donors = sorted(incoming[i])
        effective_area[i] = _sum([area[i]] + [a for _, a, _ in donors])
        discharge[i] = _sum([local_water[i]] + [q for _, _, q in donors])
        for j, fraction in edges[i]:
            incoming[j].append((i, effective_area[i] * fraction, discharge[i] * fraction))
            dependencies[j] -= 1
            if dependencies[j] == 0:
                heapq.heappush(heap, j)
    if len(order) != n:
        raise ValueError("nonterminal cycle in supplied routing graph")
    source_water = _sum(local_water)
    terminal_water = _sum(discharge[i] for i in terminals)
    source_area = _sum(area)
    terminal_area = _sum(effective_area[i] for i in terminals)
    water_residual = _balance(terminal_water - source_water, source_water, terminal_water)
    area_residual = _balance(terminal_area - source_area, source_area, terminal_area, atol=AREA_ATOL)
    return {"contributing_area_m2": effective_area, "discharge_m3_per_year": discharge,
            "topological_order": order,
            "terminals": [{"index": i, "kind": terminal_kinds[i], "area_m2": effective_area[i],
                           "discharge_m3_per_year": discharge[i]} for i in terminals],
            "source_water_m3_per_year": source_water, "terminal_water_m3_per_year": terminal_water,
            "water_residual_m3_per_year": water_residual, "area_residual_m2": area_residual,
            "terminal_authorities_independently_verified": False}


def _capacity(bed, area, level):
    return _sum(_num(max(level - z, 0.) * a, "storage volume", nonnegative=True) for z, a in zip(bed, area))


def basin_storage(bed_m, cell_area_m2, water_volume_m3, *, spill_m=None):
    """Weighted, piecewise-linear stage inversion on a supplied connected pool."""
    bed, area = _arrays(bed_m, cell_area_m2)
    volume = _num(water_volume_m3, "water volume", nonnegative=True)
    spill = None if spill_m is None else _num(spill_m, "spill elevation")
    if spill is not None and spill < min(bed):
        raise ValueError("spill below entire basin bed")
    capacity = None if spill is None else _capacity(bed, area, spill)
    retained = volume if capacity is None else min(volume, capacity)
    exported = volume - retained
    if retained == 0:
        return {"stage_m": None, "depth_m": [0.] * len(bed), "stored_volume_m3": 0.,
                "exported_volume_m3": exported, "spill_capacity_m3": capacity,
                "water_residual_m3": 0.}
    if capacity is not None and retained == capacity:
        stage = spill
    else:
        pairs = sorted(zip(bed, area))
        stage = pairs[0][0]
        wet_area = 0.
        remaining = retained
        for level, a in pairs:
            needed = _num((level - stage) * wet_area, "stage increment volume", nonnegative=True)
            if wet_area and remaining <= needed:
                stage += remaining / wet_area
                remaining = 0.
                break
            remaining -= needed
            stage = level
            wet_area = _sum((wet_area, a))
        if remaining:
            stage += remaining / wet_area
        stage = _num(stage, "water stage")
    depth = [_num(max(stage - z, 0.), "water depth", nonnegative=True) for z in bed]
    stored = _sum(d * a for d, a in zip(depth, area))
    residual = _balance(stored + exported - volume, stored, exported, volume)
    return {"stage_m": stage, "depth_m": depth, "stored_volume_m3": stored,
            "exported_volume_m3": exported, "spill_capacity_m3": capacity,
            "water_residual_m3": residual}


def fill_spill_merge(bed_m, cell_area_m2, basins, leaf_water_m3, *, allow_simultaneous_merges=False):
    """Route finite water through an explicitly supplied binary basin forest.

    Footprints and geographic spill leaves are caller-supplied scientific
    inputs. Structural checks do not replace terrain-derived saddle evidence.
    The explicit opt-in permits equal-height child/parent merges, not equal-
    height exterior links or cycles. Default validation remains unchanged.
    """
    if type(allow_simultaneous_merges) is not bool:
        raise ValueError("allow_simultaneous_merges requires an explicit Boolean")
    bed, area = _arrays(bed_m, cell_area_m2)
    n = len(bed)
    if type(basins) is not list or not 1 <= len(basins) <= MAX_BASINS or type(leaf_water_m3) is not dict:
        raise ValueError("bounded basin list and leaf volume dictionary required")
    by_id, footprints, parent, references = {}, {}, {}, 0
    for row in basins:
        if type(row) is not dict or set(row) != {"id", "cell_indices", "children", "spill_m", "spill_to_leaf"}:
            raise ValueError("unsupported basin schema")
        name = row["id"]
        if type(name) is not str or not name.strip() or name in by_id:
            raise ValueError("nonblank unique basin IDs required")
        cells = row["cell_indices"]
        if type(cells) is not list or not 1 <= len(cells) <= n:
            raise ValueError("nonempty footprint required")
        cells = [_index(v, n) for v in cells]
        references += len(cells)
        if references > MAX_FOOTPRINT_REFERENCES or len(cells) != len(set(cells)):
            raise ValueError("duplicate or excessive footprint references")
        children = row["children"]
        if (type(children) is not list or len(children) not in (0, 2) or
                any(type(c) is not str or not c for c in children) or len(set(children)) != len(children)):
            raise ValueError("zero or two distinct child IDs required")
        spill = None if row["spill_m"] is None else _num(row["spill_m"], "spill")
        receiver = row["spill_to_leaf"]
        if receiver is not None and (type(receiver) is not str or not receiver):
            raise ValueError("spill receiver must be a leaf ID or null")
        by_id[name] = {"cells": sorted(cells), "children": list(children), "spill": spill, "to": receiver}
        footprints[name] = set(cells)
    for name, node in by_id.items():
        for child in node["children"]:
            if child not in by_id or child == name or child in parent:
                raise ValueError("missing/self/multiply-owned basin child")
            parent[child] = name
    roots = sorted(set(by_id) - set(parent))
    leaves = sorted(name for name, node in by_id.items() if not node["children"])
    if not roots or set(leaf_water_m3) != set(leaves):
        raise ValueError("all and only leaves require explicit water volumes")
    water = {name: _num(leaf_water_m3[name], "leaf water", nonnegative=True) for name in leaves}
    descendant_leaves, root_of, order = {}, {}, []
    stack = [(root, False, root) for root in reversed(roots)]
    seen = set()
    while stack:
        name, exiting, root = stack.pop()
        if exiting:
            node = by_id[name]
            descendant_leaves[name] = ({name} if not node["children"] else
                                       set().union(*(descendant_leaves[c] for c in node["children"])))
            order.append(name)
            continue
        if name in seen:
            raise ValueError("basin hierarchy cycle")
        seen.add(name)
        root_of[name] = root
        stack.append((name, True, root))
        stack.extend((c, False, root) for c in reversed(by_id[name]["children"]))
    if len(seen) != len(by_id):
        raise ValueError("disconnected basin cycle")
    root_cells = set()
    for root in roots:
        if root_cells & footprints[root]:
            raise ValueError("root footprints overlap")
        root_cells |= footprints[root]
    capacities = {}
    for name in order:
        node = by_id[name]
        cells = node["cells"]
        spill = node["spill"]
        if spill is None and (name in parent or node["to"] is not None):
            raise ValueError("only closed roots may have no finite spill")
        capacities[name] = None if spill is None else _capacity([bed[i] for i in cells], [area[i] for i in cells], spill)
        if capacities[name] is not None and capacities[name] <= 0:
            raise ValueError("finite basin requires positive capacity")
        if node["children"]:
            left, right = node["children"]
            merge = by_id[left]["spill"]
            if (merge is None or merge != by_id[right]["spill"] or
                    spill is not None and (spill < merge or spill == merge and not allow_simultaneous_merges)):
                raise ValueError("child sills must agree and lie below parent spill")
            if footprints[left] & footprints[right] or not (footprints[left] | footprints[right]) <= footprints[name]:
                raise ValueError("child footprints overlap or escape parent")
            marginal = footprints[name] - footprints[left] - footprints[right]
            if any(bed[i] < merge for i in marginal):
                raise ValueError("unaccounted storage below child merge level")
        if name in parent:
            siblings = by_id[parent[name]]["children"]
            sibling = next(c for c in siblings if c != name)
            if node["to"] not in descendant_leaves[sibling]:
                raise ValueError("geographic spill leaf must lie in sibling subtree")
        elif node["to"] is not None:
            target = node["to"]
            if target not in leaves or root_of[target] == name:
                raise ValueError("root must spill outside its own tree into a leaf")
            downstream_spill = by_id[root_of[target]]["spill"]
            if downstream_spill is None or spill is None or downstream_spill >= spill:
                raise ValueError("one-way root link requires strictly lower finite downstream sill")
    volumes = dict.fromkeys(by_id, 0.)
    merged = set()
    exported_parts = []
    merge_events = []
    merge_representation = []
    spill_events = []
    def active(name):
        while name in parent and parent[name] in merged:
            name = parent[name]
        return name
    def full(name):
        cap = capacities[name]
        return cap is not None and volumes[name] == cap
    for leaf in leaves:
        name, amount = active(leaf), water[leaf]
        steps = 0
        while amount > 0:
            steps += 1
            if steps > 4 * len(by_id) + 4:
                raise ValueError("spill traversal did not progress")
            name = active(name)
            capacity = capacities[name]
            available = amount if capacity is None else max(capacity - volumes[name], 0.)
            placed = min(amount, available)
            volumes[name] = _sum((volumes[name], placed))
            amount -= placed
            if capacity is not None and placed == available:
                volumes[name] = capacity
            if name in parent:
                up = parent[name]
                left, right = by_id[up]["children"]
                if full(left) and full(right):
                    if up not in merged:
                        merged.add(up)
                        volumes[up] = _sum((volumes[left], volumes[right]))
                        if allow_simultaneous_merges and by_id[up]["spill"] == by_id[left]["spill"]:
                            # A zero-margin simultaneous parent has exactly the
                            # same geometric storage as its full children. A
                            # nested sum can round differently from its flat
                            # capacity, despite representing the same water.
                            before = volumes[up]
                            represented = capacities[up]
                            adjustment = represented - before
                            bound = _sum(math.ulp(v) for v in (volumes[left], volumes[right], before, represented))
                            if abs(adjustment) > bound:
                                raise ValueError("simultaneous merge representation exceeds binary64 summation bound")
                            volumes[up] = represented
                            merge_representation.append({"basin": up, "nested_child_sum_m3": before,
                                                         "flat_capacity_m3": represented,
                                                         "adjustment_m3": adjustment, "ulp_bound_m3": bound})
                        merge_events.append({"basin": up, "stage_m": by_id[left]["spill"]})
                    name = up
                    if amount == 0:
                        break
                    continue
            if amount == 0:
                break
            target = by_id[name]["to"]
            spill_events.append({"from": name, "to_leaf": target, "volume_m3": amount})
            if target is None:
                exported_parts.append(amount)
                break
            name = target
    active_ids = sorted(name for name in by_id if active(name) == name and
                        (not by_id[name]["children"] or name in merged))
    depth, surface = [0.] * n, [None] * n
    pools = []
    for name in active_ids:
        node = by_id[name]
        pool = basin_storage([bed[i] for i in node["cells"]], [area[i] for i in node["cells"]],
                             volumes[name], spill_m=node["spill"])
        if pool["exported_volume_m3"] != 0:
            raise ValueError("active pool still contains unhandled overflow")
        for i, d in zip(node["cells"], pool["depth_m"]):
            depth[i] = d
            surface[i] = pool["stage_m"] if d > 0 else None
        pools.append({"id": name, **pool})
    input_volume = _sum(water.values())
    stored = _sum(depth[i] * area[i] for i in range(n))
    exported = _sum(exported_parts)
    residual = _balance(stored + exported - input_volume, input_volume, stored, exported)
    result = {"water_depth_m": depth, "water_surface_m": surface, "active_pools": pools,
            "merged_basins": sorted(merged), "merge_events": merge_events, "spill_events": spill_events,
            "input_volume_m3": input_volume, "stored_volume_m3": stored, "exported_volume_m3": exported,
            "water_residual_m3": residual, "physical_bed_changed": False,
            "hierarchy_geometry_independently_verified": False}
    if allow_simultaneous_merges:
        result["simultaneous_merge_representation"] = merge_representation
        result["merge_representation_adjustment_m3"] = _sum(row["adjustment_m3"] for row in merge_representation)
    return result


def local_sediment_deposition(*, incoming_solid_m3_per_year, water_discharge_m3_per_year,
                             settling_m_per_year, cell_area_m2, bed_m, receiving_stage_m,
                             interval_years, porosity=0):
    """Zero-entrainment SPACE column balance, capped by fixed-stage accommodation.

    No bedrock erosion, resuspension, chemistry or hydrodynamic stage solution.
    This function proposes a deposit; its caller owns the single material debit.
    """
    incoming = _num(incoming_solid_m3_per_year, "incoming solid flux", nonnegative=True)
    water = _num(water_discharge_m3_per_year, "water discharge", nonnegative=True)
    settling = _num(settling_m_per_year, "settling", nonnegative=True)
    area = _num(cell_area_m2, "area", positive=True)
    bed = _num(bed_m, "bed")
    stage = _num(receiving_stage_m, "receiving stage")
    dt = _num(interval_years, "interval", nonnegative=True)
    if _num(porosity, "porosity") != 0:
        raise ValueError("only zero-porosity solid-volume deposition is supported")
    if incoming > 0 and water == 0:
        raise ValueError("advected sediment cannot have zero carrier discharge")
    supplied = _num(incoming * dt, "supplied solid volume", nonnegative=True)
    accommodation = _num(max(stage - bed, 0.) * area, "accommodation", nonnegative=True)
    if water and settling and supplied:
        ratio = _num(settling * area / water, "settling/discharge ratio", nonnegative=True)
        # qout=qin/(1+V*a/Q); use its stable deposition complement.
        potential = _num(supplied * (ratio / (1. + ratio)), "potential deposit", nonnegative=True)
    else:
        potential = 0.
    deposited = min(potential, accommodation, supplied)
    exported = supplied - deposited
    # Exact inverse of the saturated accommodation bound; multiplying and
    # dividing by area otherwise can place the bed one ULP above its stage.
    new_bed = stage if accommodation > 0 and deposited == accommodation else bed + deposited / area
    new_bed = _num(new_bed, "proposed new bed")
    represented = _num((new_bed - bed) * area, "represented solid deposit", nonnegative=True)
    representation_residual = _balance(represented - deposited, deposited, supplied)
    residual = _balance(deposited + exported - supplied, supplied, deposited, exported)
    return {"supplied_solid_m3": supplied, "potential_deposit_m3": potential,
            "deposited_solid_m3": deposited, "exported_solid_m3": exported,
            "accommodation_m3": accommodation, "proposed_bed_m": new_bed,
            "bed_increment_m": new_bed - bed, "solid_residual_m3": residual,
            "representation_residual_m3": representation_residual,
            "receiving_stage_m": stage, "porosity": 0., "hydraulics_solved": False}
