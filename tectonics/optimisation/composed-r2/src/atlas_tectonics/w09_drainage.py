"""Bounded physical drainage and complete depression adjacency for W09.

Routing never fills the physical bed. The priority-flood fields describe the
minimum escape level to a declared outlet; closed components have +inf escape
level and parent -1. Physical lake stocks and events belong to the water solver.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import hashlib
import heapq
import json
import math
from numbers import Integral

import numpy as np

from ._validation import TectonicsError, input_shape, snapshot, text
from .resources import select_budget


_MAX_NODES = 256
_MAX_LINKS = 2048
_SCHEMA = "atlas.w09-drainage.v1:steepest-flat-bfs-id-ties"


def _freeze(values, dtype):
    array = np.asarray(values, dtype=dtype, order="C")
    return np.frombuffer(array.tobytes(order="C"), dtype=dtype).reshape(array.shape)


@dataclass(frozen=True, eq=False)
class DrainageGeometry:
    """Detached immutable array payloads; caller owns retained-byte admission.

    ``basin_of`` encodes pit watersheds as 0, 1, ... in ascending pit-node order,
    and freely draining watersheds as ``-(outlet_node+1)``. ``saddles`` contains
    (basin_a, basin_b, elevation_m), with a nonnegative and b either a larger pit
    basin or the outlet encoding. Outlet-to-outlet edges need no lake saddle.
    Each pair retains its minimum boundary-edge max(bed_i, bed_j), including
    connections above a basin's first spill. This is not a spanning-tree cut.
    """

    bed_m: np.ndarray
    areas_m2: np.ndarray
    links: np.ndarray
    link_lengths_m: np.ndarray
    receivers: np.ndarray
    order: np.ndarray
    basin_of: np.ndarray
    basin_cells: tuple[np.ndarray, ...]
    saddles: tuple[tuple[int, int, float], ...]
    outlet_nodes: tuple[int, ...]
    spill_elevations_m: np.ndarray
    spill_parents: np.ndarray
    frame_id: str
    datum_id: str
    source_id: str
    signature: str

    @property
    def nbytes(self):
        """Retained numerical payload bytes, excluding Python object overhead."""
        return sum(array.nbytes for array in (
            self.bed_m, self.areas_m2, self.links, self.link_lengths_m,
            self.receivers, self.order, self.basin_of, self.spill_elevations_m,
            self.spill_parents, *self.basin_cells))


def _bounded_shape(value, name, limit, *, width=None):
    if not isinstance(value, (list, tuple, np.ndarray)):
        raise TectonicsError(f"{name}: an explicit array or sequence is required")
    try:
        count = len(value)
    except TypeError as exc:
        raise TectonicsError(f"{name}: an array is required") from exc
    if count > limit:
        raise TectonicsError(f"{name}: supported bound is {limit}")
    if not count:
        if isinstance(value, np.ndarray) and value.shape != ((0, width) if width else (0,)):
            raise TectonicsError(f"{name}: incorrect empty shape")
        return count
    shape = input_shape(value, name)
    if shape != ((count, width) if width else (count,)):
        raise TectonicsError(f"{name}: incorrect shape")
    return count


def _index(value, name, count):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Integral):
        raise TectonicsError(f"{name}: integer indices, not bool/float, are required")
    result = int(value)
    if not 0 <= result < count:
        raise TectonicsError(f"{name}: node index out of bounds")
    return result


def _flat_receivers(bed, neighbours, outlets):
    count = len(bed)
    receiver = np.arange(count, dtype=np.int64)
    for node in range(count):
        if node in outlets:
            continue
        best_slope = 0.0
        for other, length in neighbours[node]:
            if bed[other] >= bed[node]:
                continue
            slope = (float(bed[node]) - float(bed[other])) / length
            if not math.isfinite(slope) or slope <= 0:
                raise TectonicsError("positive physical slope is outside binary64 range")
            if slope > best_slope or (slope == best_slope and other < receiver[node]):
                best_slope, receiver[node] = slope, other

    seen = np.zeros(count, dtype=bool)
    distance = np.full(count, -1, dtype=np.int64)
    for start in range(count):
        if seen[start]:
            continue
        flat, queue = [], deque([start])
        seen[start] = True
        while queue:
            node = queue.popleft()
            flat.append(node)
            for other, _ in neighbours[node]:
                if not seen[other] and bed[other] == bed[node]:
                    seen[other] = True
                    queue.append(other)
        seeds = sorted(node for node in flat if receiver[node] != node or node in outlets)
        if not seeds:
            seeds = [min(flat)]
        queue = deque(seeds)
        for node in seeds:
            distance[node] = 0
        while queue:
            node = queue.popleft()
            for other, _ in neighbours[node]:
                if bed[other] == bed[node] and distance[other] < 0:
                    distance[other] = distance[node] + 1
                    queue.append(other)
        for node in flat:
            if distance[node] > 0:
                receiver[node] = min(other for other, _ in neighbours[node]
                                     if bed[other] == bed[node]
                                     and distance[other] == distance[node] - 1)
    return receiver


def _ordered_basins(receiver, outlets):
    count = len(receiver)
    donors = np.zeros(count, dtype=np.int64)
    for node, other in enumerate(receiver):
        if node != other:
            donors[other] += 1
    ready = [node for node in range(count) if donors[node] == 0]
    heapq.heapify(ready)
    order = []
    while ready:
        node = heapq.heappop(ready)
        order.append(node)
        other = int(receiver[node])
        if other != node:
            donors[other] -= 1
            if donors[other] == 0:
                heapq.heappush(ready, other)
    if len(order) != count:
        raise TectonicsError("drainage receiver cycle")
    pits = [node for node in range(count) if receiver[node] == node and node not in outlets]
    basin_of = np.full(count, -1, dtype=np.int64)
    for basin, node in enumerate(pits):
        basin_of[node] = basin
    for node in outlets:
        basin_of[node] = -(node + 1)
    for node in reversed(order):
        if receiver[node] != node:
            basin_of[node] = basin_of[receiver[node]]
    cells = tuple(_freeze(np.flatnonzero(basin_of == basin), np.int64)
                  for basin in range(len(pits)))
    return order, basin_of, cells


def _priority_flood(bed, neighbours, outlets):
    levels = np.full(len(bed), np.inf, dtype=np.float64)
    parents = np.full(len(bed), -1, dtype=np.int64)
    visited = np.zeros(len(bed), dtype=bool)
    queue = []
    for node in outlets:
        levels[node], parents[node], visited[node] = bed[node], node, True
        heapq.heappush(queue, (float(bed[node]), node))
    while queue:
        height, node = heapq.heappop(queue)
        for other, _ in neighbours[node]:
            if not visited[other]:
                visited[other] = True
                levels[other] = max(height, float(bed[other]))
                parents[other] = node
                heapq.heappush(queue, (float(levels[other]), other))
    return levels, parents


def _signature(arrays, saddles, outlets, identities):
    digest = hashlib.sha256()
    metadata = json.dumps([_SCHEMA, identities, outlets, saddles], ensure_ascii=True,
                          separators=(",", ":"), allow_nan=False).encode("ascii")
    digest.update(len(metadata).to_bytes(8, "little"))
    digest.update(metadata)
    for array in arrays:
        canonical = array.astype(array.dtype.newbyteorder("<"), copy=False)
        header = json.dumps([canonical.dtype.str, canonical.shape],
                            separators=(",", ":")).encode("ascii")
        digest.update(len(header).to_bytes(8, "little"))
        digest.update(header)
        digest.update(canonical.tobytes(order="C"))
    return digest.hexdigest()


def prepare_drainage(bed_m, areas_m2, links, link_lengths_m, outlet_nodes, *,
                     frame_id, datum_id, source_id, budget=None):
    """Prepare at most 256 nodes/2048 undirected links without physical filling.

    Nonnegative areas may include zero-storage internal connector/saddle nodes;
    outlets must have zero area. Every pit's minimum plateau must contain some
    positive storage area. Equal physical slopes choose the lower receiver ID.
    Exact-elevation flats use shortest-hop BFS to downhill/outlet seeds, then
    lower neighbour IDs; a closed flat chooses its lowest-ID node as pit.

    Preparation reserves bounded temporary work before array materialisation.
    The returned geometry owns no lease: a retaining plan must account its
    payload and its Python-object allowance for that plan's whole lifetime.
    """
    identities = []
    for name, value in (("frame_id", frame_id), ("datum_id", datum_id), ("source_id", source_id)):
        value = text(value, name)
        if len(value) > 1024 or len(value.encode("utf-8")) > 4096:
            raise TectonicsError(f"{name}: identity exceeds bounded size")
        identities.append(value)
    count = _bounded_shape(bed_m, "bed_m", _MAX_NODES)
    if count < 1:
        raise TectonicsError("at least one drainage node is required")
    if _bounded_shape(areas_m2, "areas_m2", _MAX_NODES) != count:
        raise TectonicsError("bed/area shape mismatch")
    edge_count = _bounded_shape(links, "links", _MAX_LINKS, width=2)
    if _bounded_shape(link_lengths_m, "link_lengths_m", _MAX_LINKS) != edge_count:
        raise TectonicsError("link/length shape mismatch")
    _bounded_shape(outlet_nodes, "outlet_nodes", count)
    # Includes detached inputs/results, hash serialisation, adjacency tuples,
    # sets/dictionaries/heaps and bounded Python work; not an RSS assertion.
    temporary_bytes = 16384 + 1024 * count + 1024 * edge_count
    with select_budget(budget).reserve(temporary_bytes, category="w09-drainage"):
        bed = snapshot(bed_m, "bed_m")
        areas = snapshot(areas_m2, "areas_m2", nonnegative=True)
        outlets = tuple(sorted(_index(node, "outlet_nodes", count) for node in outlet_nodes))
        if len(outlets) != len(set(outlets)):
            raise TectonicsError("duplicate outlet node")
        if any(areas[node] != 0 for node in outlets):
            raise TectonicsError("outlet nodes require zero storage area")
        lengths = (snapshot(link_lengths_m, "link_lengths_m") if edge_count
                   else _freeze([], np.float64))
        if np.any(lengths <= 0):
            raise TectonicsError("positive link lengths required")
        records, known = [], set()
        for index, pair in enumerate(links):
            a, b = sorted(_index(node, "links", count) for node in pair)
            if a == b or (a, b) in known:
                raise TectonicsError("links must be unique undirected non-self edges")
            known.add((a, b))
            records.append((a, b, float(lengths[index])))
        records.sort()
        edge_array = _freeze([(a, b) for a, b, _ in records], np.int64).reshape(edge_count, 2)
        lengths = _freeze([length for _, _, length in records], np.float64)
        neighbours = [[] for _ in range(count)]
        for a, b, length in records:
            neighbours[a].append((b, length))
            neighbours[b].append((a, length))
        for adjacent in neighbours:
            adjacent.sort()
        receiver = _flat_receivers(bed, neighbours, set(outlets))
        order, basin_of, basin_cells = _ordered_basins(receiver, set(outlets))
        for cells in basin_cells:
            bottom = float(np.min(bed[cells]))
            if not any(areas[node] > 0 for node in cells if bed[node] == bottom):
                raise TectonicsError("pit minimum plateau requires positive storage area")
        best_saddles = {}
        for a, b, _ in records:
            left, right = int(basin_of[a]), int(basin_of[b])
            if left == right or (left < 0 and right < 0):
                continue
            if left < 0 or (right >= 0 and left > right):
                left, right = right, left
            level = max(float(bed[a]), float(bed[b]))
            key = (left, right)
            if key not in best_saddles or level < best_saddles[key]:
                best_saddles[key] = level
        saddles = tuple((a, b, level) for (a, b), level in sorted(best_saddles.items()))
        flood_level, flood_parent = _priority_flood(bed, neighbours, outlets)
        receiver, order, basin_of = (_freeze(data, np.int64)
                                      for data in (receiver, order, basin_of))
        flood_level = _freeze(flood_level, np.float64)
        flood_parent = _freeze(flood_parent, np.int64)
        arrays = (bed, areas, edge_array, lengths, receiver, order, basin_of,
                  flood_level, flood_parent, *basin_cells)
        signature = _signature(arrays, saddles, outlets, identities)
        return DrainageGeometry(bed, areas, edge_array, lengths, receiver, order,
                                basin_of, basin_cells, saddles, outlets,
                                flood_level, flood_parent, *identities, signature)
