"""Pure, bounded numerical depression hierarchy; never a physical lake verdict."""
from collections import deque
import heapq
from itertools import groupby
import math

MAX_CELLS = 4096
MAX_BASINS = 4096
MAX_FOOTPRINT_REFERENCES = 262144


class UnsupportedTopologyError(ValueError):
    """Exact terrain topology cannot be represented by the storage API."""


def _number(value):
    if type(value) not in (int, float):
        raise ValueError("bed values must be finite numbers, not Boolean/coercible objects")
    try:
        value = float(value)
    except (OverflowError, ValueError):
        raise ValueError("bed value is not binary64 representable") from None
    if not math.isfinite(value):
        raise ValueError("bed value must be finite")
    return value


def _neighbours(i, rows, cols, connectivity):
    r, c = divmod(i, cols)
    offsets = ((-1, 0), (0, -1), (0, 1), (1, 0))
    if connectivity == 8:
        offsets += ((-1, -1), (-1, 1), (1, -1), (1, 1))
    return sorted((r + dr) * cols + c + dc for dr, dc in offsets
                  if 0 <= r + dr < rows and 0 <= c + dc < cols)


def _flat_receivers(bed, neighbours, outlets):
    n = len(bed)
    receivers = [None] * n
    seen = set()
    flat_count = 0
    for first in range(n):
        if first in seen:
            continue
        plateau = []
        queue = deque([first])
        seen.add(first)
        while queue:
            i = queue.popleft()
            plateau.append(i)
            for j in neighbours[i]:
                if j not in seen and bed[j] == bed[i]:
                    seen.add(j)
                    queue.append(j)
        flat_count += len(plateau) > 1
        seeds = []
        for i in sorted(plateau):
            lower = [j for j in neighbours[i] if bed[j] < bed[i]]
            if i in outlets:
                seeds.append(i)
            elif lower:
                receivers[i] = min(lower, key=lambda j: (bed[j], j))
                seeds.append(i)
        if not seeds:
            seeds = [min(plateau)]
        # Multi-source shortest cell-step paths. Heap ordering fixes all ties.
        distance = {i: 0 for i in seeds}
        heap = [(0, i) for i in seeds]
        heapq.heapify(heap)
        while heap:
            d, i = heapq.heappop(heap)
            for j in neighbours[i]:
                if bed[j] == bed[i] and j not in distance:
                    distance[j] = d + 1
                    receivers[j] = i
                    heapq.heappush(heap, (d + 1, j))
        if len(distance) != len(plateau):
            raise ValueError("internal plateau traversal failure")
    terminals = [None] * n
    for first in range(n):
        path = []
        current = first
        while terminals[current] is None and receivers[current] is not None:
            path.append(current)
            if len(path) > n:
                raise ValueError("internal receiver cycle")
            target = receivers[current]
            if bed[target] > bed[current]:
                raise ValueError("internal ascending receiver")
            current = target
        terminal = current if terminals[current] is None else terminals[current]
        terminals[current] = terminal
        for i in path:
            terminals[i] = terminal
    return receivers, terminals, flat_count


def extract_basin_topology(bed_m, shape, outlet_indices, *, connectivity=4):
    """Derive exact binary storage inputs for a <=4096-cell supplied grid.

    Boundary outlets must be explicit native edge cells; [] means closed.
    Equal-level joins explicitly request the storage function's optional mode.
    Footprints are complete drainage catchments, including their dry high cells.
    """
    if type(bed_m) is not list or not 1 <= len(bed_m) <= MAX_CELLS:
        raise ValueError("bed_m requires a nonempty bounded plain list")
    bed = [_number(v) for v in bed_m]
    n = len(bed)
    if (type(shape) not in (list, tuple) or len(shape) != 2 or
            any(type(v) is not int or v <= 0 for v in shape) or shape[0] * shape[1] != n):
        raise ValueError("shape requires two positive integers matching bed length")
    rows, cols = shape
    if type(connectivity) is not int or connectivity not in (4, 8):
        raise ValueError("connectivity must be exactly4 or8")
    if (type(outlet_indices) is not list or len(outlet_indices) > n or
            any(type(i) is not int or not 0 <= i < n for i in outlet_indices) or
            len(set(outlet_indices)) != len(outlet_indices)):
        raise ValueError("unique in-grid outlet indices required")
    outlets = set(outlet_indices)
    if any(divmod(i, cols)[0] not in (0, rows - 1) and divmod(i, cols)[1] not in (0, cols - 1) for i in outlets):
        raise ValueError("only explicitly supplied native edge outlets are supported")
    neighbours = [_neighbours(i, rows, cols, connectivity) for i in range(n)]
    receivers, terminals, flat_count = _flat_receivers(bed, neighbours, outlets)
    pits = sorted(set(terminals) - outlets)
    leaf_for_pit = {i: f"leaf_{i:04d}" for i in pits}
    labels = [None if t in outlets else leaf_for_pit[t] for t in terminals]
    leaf_cells = {leaf: [] for leaf in leaf_for_pit.values()}
    for i, leaf in enumerate(labels):
        if leaf is not None:
            leaf_cells[leaf].append(i)
    basins = [{"id": leaf, "cell_indices": cells, "children": [], "spill_m": None,
               "spill_to_leaf": None} for leaf, cells in leaf_cells.items()]
    by_id = {row["id"]: row for row in basins}
    references = sum(len(row["cell_indices"]) for row in basins)
    # None is a single abstract exterior, not an additional stored basin.
    exterior = "@exterior"
    numerical_labels = [exterior if label is None else label for label in labels]
    lowest_edges = {}
    for i in range(n):
        for j in neighbours[i]:
            if j <= i or numerical_labels[i] == numerical_labels[j]:
                continue
            pair = tuple(sorted((numerical_labels[i], numerical_labels[j])))
            edge = (max(bed[i], bed[j]), i, j)
            if pair not in lowest_edges or edge < lowest_edges[pair]:
                lowest_edges[pair] = edge
    ordered_edges = sorted((level, i, j, a, b) for (a, b), (level, i, j) in lowest_edges.items())
    parent = {name: name for name in [exterior] + list(leaf_cells)}
    active = {name: name for name in leaf_cells}
    active[exterior] = None
    owner = {}
    root_rows = []
    events = []

    def find(name):
        root = name
        while parent[root] != root:
            root = parent[root]
        while parent[name] != name:
            following = parent[name]
            parent[name] = root
            name = following
        return root

    def spill(node, level, target):
        row = by_id[node]
        if row["children"] and by_id[row["children"][0]]["spill_m"] > level:
            raise UnsupportedTopologyError("parent saddle cannot precede child merge")
        if min(bed[i] for i in row["cell_indices"]) >= level:
            raise UnsupportedTopologyError("finite basin has no positive storage below its saddle")
        row["spill_m"] = level
        row["spill_to_leaf"] = target

    # At one exact level all closed-component joins precede exterior joins.
    # This yields equal-height binary parent chains, not equal-height oceanlinks.
    def scheduled_edges():
        for _, batch in groupby(ordered_edges, key=lambda edge: edge[0]):
            batch = list(batch)
            ocean = find(exterior)
            closed = [edge for edge in batch if find(numerical_labels[edge[1]]) != ocean
                      and find(numerical_labels[edge[2]]) != ocean]
            exterior_edges = [edge for edge in batch if find(numerical_labels[edge[1]]) == ocean
                              or find(numerical_labels[edge[2]]) == ocean]
            yield from closed
            yield from exterior_edges

    for level, i, j, _, _ in scheduled_edges():
        a, b = numerical_labels[i], numerical_labels[j]
        ra, rb = find(a), find(b)
        if ra == rb:
            continue
        ocean = find(exterior)
        if ra == ocean or rb == ocean:
            if ra == ocean:
                a, b, ra, rb = b, a, rb, ra
                source_cell, target_cell = j, i
            else:
                source_cell, target_cell = i, j
            node = active[ra]
            target = None if b == exterior else b
            if target is not None:
                downstream = target
                while downstream in owner:
                    downstream = owner[downstream]
                downstream_spill = by_id[downstream]["spill_m"]
                if downstream_spill is None or downstream_spill >= level:
                    raise UnsupportedTopologyError("equal-level exterior transfer requires a non-strict storage hierarchy")
            spill(node, level, target)
            root_rows.append(node)
            parent[ra] = ocean
            events.append({"kind": "external_link", "source": node, "spill_m": level,
                           "spill_to_leaf": target, "edge_cells": [source_cell, target_cell]})
        else:
            left, right = active[ra], active[rb]
            spill(left, level, b)
            spill(right, level, a)
            cells = sorted(by_id[left]["cell_indices"] + by_id[right]["cell_indices"])
            references += len(cells)
            if references > MAX_FOOTPRINT_REFERENCES or len(basins) >= MAX_BASINS:
                raise ValueError("bounded hierarchy materialisation limit exceeded")
            node = f"merge_{len(basins):04d}"
            row = {"id": node, "cell_indices": cells, "children": [left, right],
                   "spill_m": None, "spill_to_leaf": None}
            basins.append(row)
            by_id[node] = row
            owner[left] = owner[right] = node
            parent[rb] = ra
            active[ra] = node
            events.append({"kind": "merge", "parent": node, "children": [left, right],
                           "spill_m": level, "edge_cells": [i, j], "edge_leaf_ids": [a, b]})
    if not outlets:
        if not pits or len({find(leaf) for leaf in leaf_cells}) != 1:
            raise ValueError("internal closed-grid connectivity failure")
        root_rows.append(active[find(next(iter(leaf_cells)))])
    elif any(find(leaf) != find(exterior) for leaf in leaf_cells):
        raise ValueError("internal supplied-outlet connectivity failure")
    simultaneous = any(row["children"] and row["spill_m"] is not None and
                       row["spill_m"] == by_id[row["children"][0]]["spill_m"] for row in basins)
    return {"status": "NUMERICAL_TOPOLOGY_ONLY_NOT_PHYSICAL_ACCEPTANCE", "shape": [rows, cols],
            "connectivity": connectivity, "basins": basins, "leaf_ids": list(leaf_cells),
            "leaf_pit_indices": {leaf: pit for pit, leaf in leaf_for_pit.items()},
            "cell_to_leaf": labels, "raw_receivers": receivers,
            "terminal_indices": terminals, "external_outlet_indices": sorted(outlets),
            "terminal_kinds": {i: "PROVISIONAL_BOUNDARY" if i in outlets else "BASIN_STORAGE"
                               for i in sorted(set(terminals))},
            "root_ids": sorted(root_rows), "saddle_events": events,
            "storage_options": {"allow_simultaneous_merges": simultaneous},
            "flat_component_count": flat_count, "footprint_reference_count": references,
            "boundary_status": "CALLER_DESIGNATED_EDGE_OUTLETS" if outlets else "EXPLICITLY_CLOSED_GRID",
            "physical_bed_changed": False, "physical_depression_origin": "UNRESOLVED",
            "lake_validity": "UNRESOLVED", "production_authorised": False}
