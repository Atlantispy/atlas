"""Tile-scoped, evidence-led 10 m channel-regeneration pilot.

This is deliberately isolated from the production Stage 6C outputs.  It proves
the routing contract on synthetic/small windows and fails closed when a result
is only a copy or cosmetic smoothing of an inherited water axis.

Coordinates are raster ``(row, col)`` cell centres.  Gradients are supplied as
``dZ/drow`` and ``dZ/dcol`` in metres per metre.  All generated results remain
WORKING PROPOSAL / REVIEW ONLY / NOT CANON.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import heapq
import json
import math
from pathlib import Path
from typing import Mapping, Protocol, Sequence

import numpy as np


D8 = (
    (-1, 0, 1.0),
    (-1, 1, math.sqrt(2.0)),
    (0, 1, 1.0),
    (1, 1, math.sqrt(2.0)),
    (1, 0, 1.0),
    (1, -1, math.sqrt(2.0)),
    (0, -1, 1.0),
    (-1, -1, math.sqrt(2.0)),
)

SEARCH_BUFFER_M = {"titan": 400.0, "major": 200.0, "tier2": 100.0, "tier1": 50.0}
WIDTH_LIMITS_M = {
    "titan": (30.0, 800.0),
    "major": (8.0, 250.0),
    "tier2": (0.5, 60.0),
    "tier1": (0.35, 20.0),
}

REQUIRED_FIELDS = (
    "elevation_m",
    "broad_gradient_row",
    "broad_gradient_col",
    "local_gradient_row",
    "local_gradient_col",
    "runoff_mm_y",
)


class RegenerationError(RuntimeError):
    """A fail-closed evidence, routing, topology, or anti-smoothing error."""


@dataclass(frozen=True)
class TileMetadata:
    tile_id: str
    field_name: str
    shape: tuple[int, int]
    dtype: str
    units: str
    cell_size_m: float = 10.0
    model_resolution_m: float = 10.0
    physical_source_resolution_m: float = 100.0
    effective_evidence_resolution_m: float = 100.0
    modelled_subgrid: bool = True
    uncertainty_class: str = "MODELLED_10M_REVIEW_ONLY"
    status: str = "WORKING PROPOSAL - REVIEW ONLY - NOT CANON"


@dataclass(frozen=True)
class TileRef:
    """Cache-neutral field reference.

    A production resolver may obtain this from recoverable Zstd chunks.  The
    routing code only requests verified arrays, so ``full``, ``ref`` and sparse
    residual ``patch`` entries share one interface.
    """

    kind: str
    content_hash: str
    metadata: TileMetadata
    target_hash: str | None = None
    base_hash: str | None = None
    patch_hash: str | None = None


class TileResolver(Protocol):
    def resolve(self, reference: TileRef) -> np.ndarray:
        """Return a hash-verified array for one field tile."""


def _array_hash(array: np.ndarray, metadata: TileMetadata) -> str:
    canonical = np.ascontiguousarray(array.astype(metadata.dtype, copy=False))
    header = json.dumps(asdict(metadata), sort_keys=True, separators=(",", ":")).encode("utf-8")
    digest = sha256()
    digest.update(header)
    digest.update(canonical.tobytes(order="C"))
    return digest.hexdigest()


class InMemoryTileStore:
    """Small test resolver implementing full/ref/patch cache semantics.

    It intentionally does not implement cache persistence or compression.  A
    production content-addressed store remains responsible for atomic ordered
    flushes, Zstd recovery, reuse and corruption rebuild.
    """

    def __init__(self) -> None:
        self._arrays: dict[str, np.ndarray] = {}
        self._patches: dict[str, tuple[np.ndarray, np.ndarray]] = {}

    def put_full(self, array: np.ndarray, metadata: TileMetadata) -> TileRef:
        value = np.ascontiguousarray(array.astype(metadata.dtype, copy=False))
        content_hash = _array_hash(value, metadata)
        self._arrays[content_hash] = value.copy()
        return TileRef("full", content_hash, metadata)

    def put_ref(self, target: TileRef, metadata: TileMetadata | None = None) -> TileRef:
        selected = metadata or target.metadata
        if selected != target.metadata:
            raise RegenerationError("A ref cannot silently change tile metadata")
        return TileRef("ref", target.content_hash, selected, target_hash=target.content_hash)

    def put_patch(
        self,
        base: TileRef,
        flat_indices: np.ndarray,
        residual_values: np.ndarray,
        metadata: TileMetadata | None = None,
    ) -> TileRef:
        selected = metadata or base.metadata
        if selected.shape != base.metadata.shape or selected.dtype != base.metadata.dtype:
            raise RegenerationError("Patch shape/dtype must match its base tile")
        indices = np.asarray(flat_indices, dtype=np.int64)
        residuals = np.asarray(residual_values, dtype=np.dtype(selected.dtype))
        if indices.ndim != 1 or residuals.ndim != 1 or indices.size != residuals.size:
            raise RegenerationError("Patch indices and residuals must be equal-length vectors")
        if indices.size and (indices.min() < 0 or indices.max() >= math.prod(selected.shape)):
            raise RegenerationError("Patch index outside tile")
        order = np.argsort(indices, kind="stable")
        indices, residuals = indices[order], residuals[order]
        if indices.size and np.any(indices[1:] == indices[:-1]):
            raise RegenerationError("Patch indices must be unique")
        patch_digest = sha256(indices.tobytes() + residuals.tobytes()).hexdigest()
        resolved = self.resolve(base).astype(selected.dtype, copy=True).ravel()
        resolved[indices] += residuals
        resolved = resolved.reshape(selected.shape)
        content_hash = _array_hash(resolved, selected)
        self._patches[patch_digest] = (indices.copy(), residuals.copy())
        return TileRef(
            "patch",
            content_hash,
            selected,
            base_hash=base.content_hash,
            patch_hash=patch_digest,
        )

    def resolve(self, reference: TileRef) -> np.ndarray:
        if reference.kind == "full":
            if reference.content_hash not in self._arrays:
                raise RegenerationError("Missing full tile payload")
            result = self._arrays[reference.content_hash].copy()
        elif reference.kind == "ref":
            if reference.target_hash not in self._arrays:
                raise RegenerationError("Missing referenced tile payload")
            result = self._arrays[reference.target_hash].copy()
        elif reference.kind == "patch":
            if reference.base_hash not in self._arrays or reference.patch_hash not in self._patches:
                raise RegenerationError("Missing patch base or residual payload")
            result = self._arrays[reference.base_hash].copy().ravel()
            indices, residuals = self._patches[reference.patch_hash]
            result[indices] += residuals
            result = result.reshape(reference.metadata.shape)
        else:
            raise RegenerationError(f"Unsupported tile reference kind: {reference.kind}")
        if result.shape != reference.metadata.shape:
            raise RegenerationError("Resolved tile shape does not match metadata")
        if _array_hash(result, reference.metadata) != reference.content_hash:
            raise RegenerationError("Resolved tile failed content-hash verification")
        return result


@dataclass(frozen=True)
class TopologyConstraint:
    source: tuple[int, int]
    ordered_contacts: tuple[tuple[int, int], ...]
    receiver: tuple[int, int]
    contact_ids: tuple[str, ...] = ()

    def anchors(self) -> tuple[tuple[int, int], ...]:
        return (self.source, *self.ordered_contacts, self.receiver)


@dataclass(frozen=True)
class RegenerationConfig:
    route_class: str
    persistence: str = "perennial"
    cell_size_m: float = 10.0
    max_uphill_step_m: float = 0.25
    minimum_cost_improvement: float = 0.02
    minimum_p95_displacement_m: float = 15.0
    copied_fraction_limit: float = 0.85
    cosmetic_near_fraction_limit: float = 0.90
    hydraulic_width_a: float = 4.2
    hydraulic_width_b: float = 0.46

    @property
    def search_buffer_m(self) -> float:
        try:
            return SEARCH_BUFFER_M[self.route_class]
        except KeyError as exc:
            raise RegenerationError(f"Unknown route class: {self.route_class}") from exc


@dataclass
class RegenerationResult:
    path_cells: list[tuple[int, int]]
    discharge_m3_s: list[float]
    width_m: list[float]
    metrics: dict[str, float | int | bool | str]
    lineage: dict[str, object]

    def serialisable(self) -> dict[str, object]:
        return {
            "path_cells": [list(cell) for cell in self.path_cells],
            "discharge_m3_s": self.discharge_m3_s,
            "width_m": self.width_m,
            "metrics": self.metrics,
            "lineage": self.lineage,
        }


def _box_mean(array: np.ndarray, radius: int) -> np.ndarray:
    padded = np.pad(array.astype(np.float64), radius, mode="edge")
    integral = np.pad(padded, ((1, 0), (1, 0)), mode="constant").cumsum(0).cumsum(1)
    width = 2 * radius + 1
    total = integral[width:, width:] - integral[:-width, width:] - integral[width:, :-width] + integral[:-width, :-width]
    return (total / float(width * width)).astype(np.float32)


def _robust_zero_one(array: np.ndarray, valid: np.ndarray) -> np.ndarray:
    values = array[valid & np.isfinite(array)]
    if not values.size:
        raise RegenerationError("Evidence field has no finite valid cells")
    low, high = np.percentile(values, (5.0, 95.0))
    if high - low < 1e-9:
        return np.full(array.shape, 0.5, dtype=np.float32)
    return np.clip((array - low) / (high - low), 0.0, 1.0).astype(np.float32)


def resolve_evidence_tiles(
    references: Mapping[str, TileRef], resolver: TileResolver
) -> tuple[dict[str, np.ndarray], dict[str, object]]:
    missing = sorted(set(REQUIRED_FIELDS) - set(references))
    if missing:
        raise RegenerationError("Missing required 10 m evidence fields: " + ", ".join(missing))
    first = references["elevation_m"].metadata
    if first.cell_size_m != 10.0 or first.model_resolution_m != 10.0:
        raise RegenerationError("Pilot requires 10 m cells and 10 m model resolution")
    if (
        first.physical_source_resolution_m != 100.0
        or first.effective_evidence_resolution_m != 100.0
        or not first.modelled_subgrid
    ):
        raise RegenerationError(
            "Modelled 10 m elevation must retain 100 m physical-source and effective-evidence authority"
        )
    arrays: dict[str, np.ndarray] = {}
    cache_kinds: dict[str, str] = {}
    hashes: dict[str, str] = {}
    for name in REQUIRED_FIELDS:
        reference = references[name]
        metadata = reference.metadata
        if metadata.field_name != name:
            raise RegenerationError(f"Field-name mismatch for {name}")
        if metadata.shape != first.shape or metadata.cell_size_m != first.cell_size_m:
            raise RegenerationError("Evidence tiles are not grid-aligned")
        if (
            metadata.model_resolution_m != first.model_resolution_m
            or metadata.physical_source_resolution_m != first.physical_source_resolution_m
            or metadata.effective_evidence_resolution_m != first.effective_evidence_resolution_m
        ):
            raise RegenerationError("Evidence resolution-authority metadata mismatch")
        if metadata.status != first.status:
            raise RegenerationError("Evidence status mismatch")
        value = resolver.resolve(reference).astype(np.float32, copy=False)
        if not np.all(np.isfinite(value)):
            raise RegenerationError(f"Non-finite evidence in {name}")
        arrays[name] = value
        cache_kinds[name] = reference.kind
        hashes[name] = reference.content_hash
    lineage = {
        "tile_id": first.tile_id,
        "cell_size_m": first.cell_size_m,
        "model_resolution_m": first.model_resolution_m,
        "physical_source_resolution_m": first.physical_source_resolution_m,
        "effective_evidence_resolution_m": first.effective_evidence_resolution_m,
        "modelled_subgrid": first.modelled_subgrid,
        "uncertainty_class": first.uncertainty_class,
        "status": first.status,
        "cache_reference_kinds": cache_kinds,
        "evidence_hashes": hashes,
    }
    return arrays, lineage


def validate_parent_conserving_elevation(
    elevation_10m: np.ndarray,
    parent_elevation_100m: np.ndarray,
    tolerance_m: float = 0.05,
) -> dict[str, float]:
    rows, cols = elevation_10m.shape
    if rows % 10 or cols % 10 or parent_elevation_100m.shape != (rows // 10, cols // 10):
        raise RegenerationError("10 m tile and 100 m parent do not form aligned 10x10 blocks")
    blocks = elevation_10m.reshape(rows // 10, 10, cols // 10, 10)
    block_means = blocks.mean(axis=(1, 3))
    error = np.abs(block_means - parent_elevation_100m)
    max_error = float(error.max())
    if max_error > tolerance_m:
        raise RegenerationError(f"10 m elevation violates parent block means: {max_error:.4f} m")
    within_variation = blocks.std(axis=(1, 3))
    constant_fraction = float(np.mean(within_variation < 1e-4))
    if constant_fraction > 0.10:
        raise RegenerationError(
            f"10 m elevation appears to repeat parent pixels ({constant_fraction:.1%} constant blocks)"
        )
    return {
        "maximum_parent_mean_error_m": max_error,
        "constant_parent_block_fraction": constant_fraction,
    }


def validate_gradient_evidence(arrays: Mapping[str, np.ndarray], cell_size_m: float) -> dict[str, float]:
    elevation = arrays["elevation_m"]
    derived_row, derived_col = np.gradient(elevation.astype(np.float64), cell_size_m)
    local_row = arrays["local_gradient_row"]
    local_col = arrays["local_gradient_col"]
    local_rmse = float(np.sqrt(np.mean((derived_row - local_row) ** 2 + (derived_col - local_col) ** 2)))
    local_scale = float(np.sqrt(np.mean(derived_row**2 + derived_col**2)))
    if local_rmse > max(0.02, 0.15 * max(local_scale, 1e-6)):
        raise RegenerationError(
            f"Local gradient is inconsistent with 10 m elevation (vector RMSE {local_rmse:.5f})"
        )
    broad_mag = np.hypot(arrays["broad_gradient_row"], arrays["broad_gradient_col"])
    local_mag = np.hypot(local_row, local_col)
    if float(np.std(broad_mag)) < 1e-7 or float(np.std(local_mag)) < 1e-7:
        raise RegenerationError("Broad/local gradient evidence is degenerate")
    return {
        "local_gradient_vector_rmse": local_rmse,
        "local_gradient_vector_rms": local_scale,
        "broad_gradient_rms": float(np.sqrt(np.mean(broad_mag**2))),
    }


def derive_regenerated_flow_evidence(
    arrays: dict[str, np.ndarray], cell_size_m: float
) -> dict[str, float | int | str]:
    """Build a fresh strict-downhill D8 graph and accumulate effective runoff.

    The resulting catchment area and discharge are derived from the supplied
    modelled 10 m elevation and runoff, never inherited from the old channel.
    A production surface must be hydrologically conditioned before this step;
    interior sinks are counted and exposed for review rather than hidden.
    """
    elevation = arrays["elevation_m"]
    runoff = np.maximum(arrays["runoff_mm_y"], 0.0)
    rows, cols = elevation.shape
    receiver = np.full(rows * cols, -1, dtype=np.int64)
    best_slope = np.zeros(rows * cols, dtype=np.float64)
    for row in range(rows):
        for col in range(cols):
            index = row * cols + col
            here = float(elevation[row, col])
            for dr, dc, distance in D8:
                rr, cc = row + dr, col + dc
                if rr < 0 or rr >= rows or cc < 0 or cc >= cols:
                    continue
                slope = (here - float(elevation[rr, cc])) / (distance * cell_size_m)
                if slope > best_slope[index] + 1e-12:
                    best_slope[index] = slope
                    receiver[index] = rr * cols + cc
    cell_area_km2 = (cell_size_m / 1000.0) ** 2
    accumulated_area = np.full(rows * cols, cell_area_km2, dtype=np.float64)
    accumulated_runoff_load = runoff.ravel().astype(np.float64) * cell_area_km2
    # Strictly downhill receivers make descending elevation a valid topological
    # order.  No local-runoff-times-total-catchment shortcut is used.
    order = np.argsort(elevation.ravel(), kind="stable")[::-1]
    for index in order:
        downstream = int(receiver[index])
        if downstream >= 0:
            accumulated_area[downstream] += accumulated_area[index]
            accumulated_runoff_load[downstream] += accumulated_runoff_load[index]
    arrays["regenerated_flow_accumulation_km2"] = accumulated_area.reshape(rows, cols).astype(np.float32)
    arrays["regenerated_effective_discharge_m3_s"] = (
        accumulated_runoff_load.reshape(rows, cols) / 31_557.6
    ).astype(np.float32)
    # Private working graph: it is never emitted as a raster band, but allows
    # the accepted analytical route to become the explicit receiver chain
    # before final discharge/width accumulation.
    arrays["__regenerated_receiver_flat"] = receiver
    interior = np.ones((rows, cols), dtype=bool)
    interior[[0, -1], :] = False
    interior[:, [0, -1]] = False
    sink_count = int(np.count_nonzero(interior.ravel() & (receiver < 0)))
    receiver_edges = np.column_stack(
        (np.flatnonzero(receiver >= 0).astype(np.int64), receiver[receiver >= 0].astype(np.int64))
    )
    graph_hash = sha256(receiver_edges.tobytes()).hexdigest()
    return {
        "flow_graph_method": "strict-downhill D8 on modelled 10 m elevation",
        "flow_graph_receiver_edge_count": int(receiver_edges.shape[0]),
        "flow_graph_interior_sink_count": sink_count,
        "flow_graph_hash": graph_hash,
        "effective_runoff_accumulation": "sum(local runoff_mm_y * 10 m cell area) over regenerated D8 graph",
    }


def accumulate_on_accepted_route(
    arrays: dict[str, np.ndarray], path: Sequence[tuple[int, int]], cell_size_m: float
) -> dict[str, float | int | str]:
    """Force accepted channel edges into the new graph, then re-accumulate.

    Sampling an unconditioned D8 accumulation raster along a neighbouring A*
    path can create false discharge resets.  This function makes each accepted
    downstream path edge an explicit receiver edge, retains lateral D8 inflow,
    and recomputes area/runoff in descending-elevation order.
    """
    elevation = arrays["elevation_m"]
    runoff = np.maximum(arrays["runoff_mm_y"], 0.0)
    rows, cols = elevation.shape
    receiver = np.asarray(arrays.get("__regenerated_receiver_flat"), dtype=np.int64).copy()
    if receiver.shape != (rows * cols,):
        raise RegenerationError("Missing regenerated receiver graph")
    forced_edges: list[tuple[int, int]] = []
    for here, there in zip(path[:-1], path[1:]):
        source = here[0] * cols + here[1]
        target = there[0] * cols + there[1]
        if float(elevation[there] - elevation[here]) > 1e-6:
            raise RegenerationError("Accepted route cannot force an uphill flow-graph edge")
        receiver[source] = target
        forced_edges.append((source, target))
    cell_area_km2 = (cell_size_m / 1000.0) ** 2
    accumulated_area = np.full(rows * cols, cell_area_km2, dtype=np.float64)
    accumulated_runoff_load = runoff.ravel().astype(np.float64) * cell_area_km2
    order = np.argsort(elevation.ravel(), kind="stable")[::-1]
    for index in order:
        downstream = int(receiver[index])
        if downstream >= 0:
            accumulated_area[downstream] += accumulated_area[index]
            accumulated_runoff_load[downstream] += accumulated_runoff_load[index]
    arrays["routed_flow_accumulation_km2"] = accumulated_area.reshape(rows, cols).astype(np.float32)
    arrays["routed_effective_discharge_m3_s"] = (
        accumulated_runoff_load.reshape(rows, cols) / 31_557.6
    ).astype(np.float32)
    q = np.asarray([arrays["routed_effective_discharge_m3_s"][cell] for cell in path], dtype=np.float64)
    minimum_increment = float(np.diff(q).min(initial=0.0))
    if minimum_increment < -1e-8:
        raise RegenerationError("Route-conditioned effective discharge decreases downstream")
    return {
        "accepted_route_receiver_edge_count": len(forced_edges),
        "accepted_route_receiver_edge_hash": sha256(np.asarray(forced_edges, dtype=np.int64).tobytes()).hexdigest(),
        "routed_discharge_minimum_downstream_increment_m3_s": minimum_increment,
        "routed_discharge_method": "accepted path edges forced into regenerated D8 graph, then lateral runoff re-accumulated",
    }


def densify_polyline(vertices: Sequence[tuple[int, int]]) -> list[tuple[int, int]]:
    if len(vertices) < 2:
        raise RegenerationError("Polyline needs at least two vertices")
    result: list[tuple[int, int]] = []
    for (r0, c0), (r1, c1) in zip(vertices[:-1], vertices[1:]):
        steps = max(abs(r1 - r0), abs(c1 - c0))
        for step in range(steps + 1):
            row = int(round(r0 + (r1 - r0) * step / max(steps, 1)))
            col = int(round(c0 + (c1 - c0) * step / max(steps, 1)))
            cell = (row, col)
            if not result or result[-1] != cell:
                result.append(cell)
    return result


def corridor_mask_from_axis(
    shape: tuple[int, int], old_axis: Sequence[tuple[int, int]], buffer_cells: int
) -> np.ndarray:
    mask = np.zeros(shape, dtype=bool)
    dense = densify_polyline(old_axis)
    radius2 = buffer_cells * buffer_cells
    for row, col in dense:
        r0, r1 = max(0, row - buffer_cells), min(shape[0], row + buffer_cells + 1)
        c0, c1 = max(0, col - buffer_cells), min(shape[1], col + buffer_cells + 1)
        rr, cc = np.ogrid[r0:r1, c0:c1]
        mask[r0:r1, c0:c1] |= (rr - row) ** 2 + (cc - col) ** 2 <= radius2
    return mask


def build_node_cost(arrays: Mapping[str, np.ndarray], corridor: np.ndarray) -> np.ndarray:
    elevation = arrays["elevation_m"]
    local_residual = elevation - _box_mean(elevation, radius=5)
    valley_position = _robust_zero_one(local_residual, corridor)
    regenerated_discharge = np.maximum(arrays["regenerated_effective_discharge_m3_s"], 0.0)
    regenerated_catchment = np.maximum(arrays["regenerated_flow_accumulation_km2"], 0.0)
    water_evidence = _robust_zero_one(
        np.log1p(regenerated_discharge * 1000.0) + 0.30 * np.log1p(regenerated_catchment), corridor
    )
    broad_mag = np.hypot(arrays["broad_gradient_row"], arrays["broad_gradient_col"])
    roughness = _robust_zero_one(broad_mag, corridor)
    cost = 0.45 + 2.4 * valley_position + 1.3 * (1.0 - water_evidence) + 0.25 * roughness
    return np.where(corridor, cost, np.inf).astype(np.float32)


def _step_cost(
    arrays: Mapping[str, np.ndarray], node_cost: np.ndarray, here: tuple[int, int], there: tuple[int, int], distance: float
) -> float:
    row, col = here
    rr, cc = there
    dz = float(arrays["elevation_m"][rr, cc] - arrays["elevation_m"][row, col])
    dr, dc = rr - row, cc - col
    broad_row = float(arrays["broad_gradient_row"][row, col])
    broad_col = float(arrays["broad_gradient_col"][row, col])
    local_row = float(arrays["local_gradient_row"][row, col])
    local_col = float(arrays["local_gradient_col"][row, col])

    def alignment(grow: float, gcol: float) -> float:
        magnitude = math.hypot(grow, gcol)
        if magnitude < 1e-8:
            return 0.0
        return max(-1.0, min(1.0, -(grow * dr + gcol * dc) / (magnitude * distance)))

    gradient_penalty = 0.45 * (1.0 - alignment(broad_row, broad_col)) + 0.20 * (
        1.0 - alignment(local_row, local_col)
    )
    uphill_penalty = 18.0 * max(dz, 0.0)
    return distance * (0.5 * float(node_cost[row, col]) + 0.5 * float(node_cost[rr, cc]) + gradient_penalty) + uphill_penalty


def _astar_leg(
    arrays: Mapping[str, np.ndarray],
    node_cost: np.ndarray,
    corridor: np.ndarray,
    start: tuple[int, int],
    goal: tuple[int, int],
    max_uphill_step_m: float,
    blocked: set[tuple[int, int]],
) -> tuple[list[tuple[int, int]], dict[str, int]]:
    rows, cols = corridor.shape
    for name, cell in (("start", start), ("goal", goal)):
        if not (0 <= cell[0] < rows and 0 <= cell[1] < cols and corridor[cell]):
            raise RegenerationError(f"Topology {name} lies outside the search corridor")
    start_index = start[0] * cols + start[1]
    goal_index = goal[0] * cols + goal[1]
    # Direction is part of the state, so a modest turn penalty suppresses D8
    # saw-toothing without rewarding proximity to the inherited axis.
    state_directions = 9
    start_state = start_index * state_directions + 8
    distance_so_far = np.full(rows * cols * state_directions, np.inf, dtype=np.float64)
    parent = np.full(rows * cols * state_directions, -1, dtype=np.int64)
    distance_so_far[start_state] = 0.0
    minimum_node = float(np.min(node_cost[corridor]))
    queue: list[tuple[float, int]] = [(0.0, start_state)]
    closed = np.zeros(rows * cols * state_directions, dtype=bool)
    goal_state = -1
    expanded_states = 0
    relaxed_edges = 0
    while queue:
        _, state = heapq.heappop(queue)
        if closed[state]:
            continue
        closed[state] = True
        expanded_states += 1
        index, previous_direction = divmod(state, state_directions)
        if index == goal_index:
            goal_state = state
            break
        row, col = divmod(index, cols)
        for direction, (dr, dc, step_distance) in enumerate(D8):
            rr, cc = row + dr, col + dc
            there = (rr, cc)
            if rr < 0 or rr >= rows or cc < 0 or cc >= cols or not corridor[rr, cc]:
                continue
            if there in blocked and there != goal:
                continue
            if float(arrays["elevation_m"][rr, cc] - arrays["elevation_m"][row, col]) > max_uphill_step_m:
                continue
            neighbour = rr * cols + cc
            neighbour_state = neighbour * state_directions + direction
            if closed[neighbour_state]:
                continue
            turn_penalty = 0.0
            if previous_direction < 8:
                pdr, pdc, pdistance = D8[previous_direction]
                cosine = (pdr * dr + pdc * dc) / (pdistance * step_distance)
                turn_penalty = 0.18 * (1.0 - max(-1.0, min(1.0, cosine)))
            proposed = distance_so_far[state] + _step_cost(
                arrays, node_cost, (row, col), there, step_distance
            ) + turn_penalty
            if proposed >= distance_so_far[neighbour_state]:
                continue
            distance_so_far[neighbour_state] = proposed
            parent[neighbour_state] = state
            relaxed_edges += 1
            heuristic = math.hypot(goal[0] - rr, goal[1] - cc) * minimum_node
            heapq.heappush(queue, (proposed + heuristic, neighbour_state))
    if start != goal and goal_state < 0:
        raise RegenerationError(f"No downhill evidence-led route between topology anchors {start} and {goal}")
    states = [goal_state]
    while states[-1] != start_state:
        states.append(int(parent[states[-1]]))
    states.reverse()
    cells = [divmod(state // state_directions, cols) for state in states]
    return cells, {"expanded_states": expanded_states, "relaxed_edges": relaxed_edges}


def route_with_topology(
    arrays: Mapping[str, np.ndarray],
    corridor: np.ndarray,
    topology: TopologyConstraint,
    config: RegenerationConfig,
) -> tuple[list[tuple[int, int]], np.ndarray, dict[str, int]]:
    node_cost = build_node_cost(arrays, corridor)
    route: list[tuple[int, int]] = []
    blocked: set[tuple[int, int]] = set()
    trace = {"expanded_states": 0, "relaxed_edges": 0, "routed_legs": 0}
    anchors = topology.anchors()
    for start, goal in zip(anchors[:-1], anchors[1:]):
        leg, leg_trace = _astar_leg(arrays, node_cost, corridor, start, goal, config.max_uphill_step_m, blocked)
        trace["expanded_states"] += leg_trace["expanded_states"]
        trace["relaxed_edges"] += leg_trace["relaxed_edges"]
        trace["routed_legs"] += 1
        if route:
            leg = leg[1:]
        route.extend(leg)
        blocked.update(route[:-1])
    if tuple(route[0]) != topology.source or tuple(route[-1]) != topology.receiver:
        raise RegenerationError("Route changed its required source or receiver")
    cursor = 0
    for contact in topology.ordered_contacts:
        try:
            cursor = route.index(contact, cursor) + 1
        except ValueError as exc:
            raise RegenerationError(f"Route lost required contact {contact}") from exc
    return route, node_cost, trace


def _path_cost(
    path: Sequence[tuple[int, int]], arrays: Mapping[str, np.ndarray], node_cost: np.ndarray
) -> float:
    total = 0.0
    geometric = 0.0
    for here, there in zip(path[:-1], path[1:]):
        distance = math.hypot(there[0] - here[0], there[1] - here[1])
        total += _step_cost(arrays, node_cost, here, there, distance)
        geometric += distance
    return total / max(geometric, 1e-9)


def _nearest_distances(a: Sequence[tuple[int, int]], b: Sequence[tuple[int, int]]) -> np.ndarray:
    aa = np.asarray(a, dtype=np.float32)
    bb = np.asarray(b, dtype=np.float32)
    result = np.full(len(aa), np.inf, dtype=np.float32)
    for start in range(0, len(aa), 512):
        block = aa[start : start + 512]
        squared = ((block[:, None, :] - bb[None, :, :]) ** 2).sum(axis=2)
        result[start : start + len(block)] = np.sqrt(squared.min(axis=1))
    return result


def anti_smoothing_gate(
    candidate: Sequence[tuple[int, int]],
    inherited_axis: Sequence[tuple[int, int]],
    arrays: Mapping[str, np.ndarray],
    node_cost: np.ndarray,
    config: RegenerationConfig,
    *,
    routed_by_evidence_engine: bool = False,
) -> dict[str, float | bool | str]:
    old = densify_polyline(inherited_axis)
    old_set = set(old)
    exact_fraction = sum(cell in old_set for cell in candidate) / max(len(candidate), 1)
    candidate_to_old = _nearest_distances(candidate, old)
    old_to_candidate = _nearest_distances(old, candidate)
    p95_cells = float(np.percentile(candidate_to_old, 95.0))
    hausdorff_cells = float(max(candidate_to_old.max(), old_to_candidate.max()))
    near_one_fraction = float(np.mean(candidate_to_old <= 1.0))
    candidate_cost = _path_cost(candidate, arrays, node_cost)
    old_cost = _path_cost(old, arrays, node_cost)
    improvement = float((old_cost - candidate_cost) / max(abs(old_cost), 1e-9))
    candidate_nodes = np.asarray([node_cost[cell] for cell in candidate], dtype=np.float64)
    corridor_nodes = node_cost[np.isfinite(node_cost)].astype(np.float64)
    forcing_support = float((np.median(corridor_nodes) - np.median(candidate_nodes)) / max(np.median(corridor_nodes), 1e-9))
    reason = "PASS"
    passed = True
    exact_or_near_copy = exact_fraction >= config.copied_fraction_limit
    cosmetic_coincidence = (
        near_one_fraction >= config.cosmetic_near_fraction_limit
        or p95_cells * config.cell_size_m < config.minimum_p95_displacement_m
    )
    materially_coincident = exact_or_near_copy or cosmetic_coincidence
    if exact_or_near_copy and not routed_by_evidence_engine:
        passed, reason = False, "REJECT_INHERITED_AXIS_REPRODUCTION"
    elif cosmetic_coincidence and not routed_by_evidence_engine:
        passed, reason = False, "REJECT_COSMETIC_SMOOTHING"
    elif materially_coincident and forcing_support >= 0.05:
        passed, reason = True, "PASS_COINCIDENT_EVIDENCE_OPTIMUM"
    elif materially_coincident:
        passed, reason = False, "REJECT_COINCIDENCE_WITHOUT_FORCING_SUPPORT"
    elif near_one_fraction >= config.cosmetic_near_fraction_limit and improvement < config.minimum_cost_improvement:
        passed, reason = False, "REJECT_COSMETIC_SMOOTHING"
    elif improvement < config.minimum_cost_improvement:
        passed, reason = False, "REJECT_NO_EVIDENCE_COST_IMPROVEMENT"
    metrics: dict[str, float | bool | str] = {
        "anti_smoothing_pass": passed,
        "anti_smoothing_reason": reason,
        "candidate_exactly_on_inherited_fraction": float(exact_fraction),
        "candidate_within_1_cell_of_inherited_fraction": near_one_fraction,
        "candidate_p95_displacement_m": p95_cells * config.cell_size_m,
        "symmetric_hausdorff_m": hausdorff_cells * config.cell_size_m,
        "candidate_evidence_cost_per_cell": candidate_cost,
        "inherited_evidence_cost_per_cell": old_cost,
        "evidence_cost_improvement_fraction": improvement,
        "candidate_forcing_support_fraction": forcing_support,
        "routed_by_evidence_engine": routed_by_evidence_engine,
        "inherited_axis_used_in_objective": False,
    }
    if not passed:
        raise RegenerationError(reason)
    return metrics


def derive_discharge_and_width(
    path: Sequence[tuple[int, int]], arrays: Mapping[str, np.ndarray], config: RegenerationConfig
) -> tuple[np.ndarray, np.ndarray, dict[str, object]]:
    mean_discharge = np.asarray(
        [arrays["routed_effective_discharge_m3_s"][cell] for cell in path], dtype=np.float64
    )
    persistence_multiplier = {"perennial": 2.2, "intermittent": 3.0, "ephemeral": 4.5}.get(config.persistence)
    if persistence_multiplier is None:
        raise RegenerationError(f"Unknown persistence class: {config.persistence}")
    design_discharge = mean_discharge * persistence_multiplier
    broad_magnitude = np.asarray(
        [math.hypot(arrays["broad_gradient_row"][cell], arrays["broad_gradient_col"][cell]) for cell in path],
        dtype=np.float64,
    )
    # Steep/confined reaches are narrower at a given proxy discharge.  This is
    # an explicit review-only assumption pending real hydraulic calibration.
    confinement = np.clip(1.0 / (1.0 + 2.5 * broad_magnitude), 0.58, 1.0)
    raw_width = config.hydraulic_width_a * np.power(np.maximum(design_discharge, 1e-6), config.hydraulic_width_b)
    lower, upper = WIDTH_LIMITS_M[config.route_class]
    width = np.clip(raw_width * confinement, lower, upper)
    if len(width) >= 8 and float(np.ptp(width)) < max(0.02, 0.005 * float(np.mean(width))):
        raise RegenerationError("Width output is effectively constant despite a routed reach")
    assumptions = {
        "discharge_equation": "Qmean is accumulated local runoff volume over the regenerated strict-downhill 10 m D8 graph",
        "design_flow_multiplier": persistence_multiplier,
        "width_equation": f"width_m = {config.hydraulic_width_a} * Qdesign^{config.hydraulic_width_b} * confinement",
        "confinement_equation": "clip(1 / (1 + 2.5 * broad_gradient_magnitude), 0.58, 1.0)",
        "class_width_limits_m": [lower, upper],
        "status": "REVIEW ONLY - UNCALIBRATED HYDRAULIC GEOMETRY",
    }
    return design_discharge, width, assumptions


def regenerate_tile_route(
    references: Mapping[str, TileRef],
    resolver: TileResolver,
    parent_elevation_100m: np.ndarray,
    corridor: np.ndarray,
    inherited_axis: Sequence[tuple[int, int]],
    topology: TopologyConstraint,
    config: RegenerationConfig,
) -> RegenerationResult:
    arrays, lineage = resolve_evidence_tiles(references, resolver)
    if corridor.shape != arrays["elevation_m"].shape:
        raise RegenerationError("Corridor mask is not aligned with the evidence tile")
    if not np.all(corridor[np.asarray(topology.anchors())[:, 0], np.asarray(topology.anchors())[:, 1]]):
        raise RegenerationError("A required topology anchor lies outside the search corridor")
    parent_metrics = validate_parent_conserving_elevation(arrays["elevation_m"], parent_elevation_100m)
    gradient_metrics = validate_gradient_evidence(arrays, config.cell_size_m)
    flow_metrics = derive_regenerated_flow_evidence(arrays, config.cell_size_m)
    route, node_cost, routing_trace = route_with_topology(arrays, corridor, topology, config)
    anti_metrics = anti_smoothing_gate(
        route,
        inherited_axis,
        arrays,
        node_cost,
        config,
        routed_by_evidence_engine=True,
    )
    elevations = np.asarray([arrays["elevation_m"][cell] for cell in route])
    uphill = np.diff(elevations)
    maximum_uphill = float(max(float(uphill.max(initial=0.0)), 0.0))
    if maximum_uphill > config.max_uphill_step_m + 1e-6:
        raise RegenerationError("Regenerated path violates downhill-continuity tolerance")
    routed_flow_metrics = accumulate_on_accepted_route(arrays, route, config.cell_size_m)
    discharge, width, width_assumptions = derive_discharge_and_width(route, arrays, config)
    metrics: dict[str, float | int | bool | str] = {
        **parent_metrics,
        **gradient_metrics,
        **flow_metrics,
        **anti_metrics,
        **routed_flow_metrics,
        "path_cell_count": len(route),
        "maximum_uphill_step_m": maximum_uphill,
        "width_min_m": float(width.min()),
        "width_max_m": float(width.max()),
        "discharge_min_m3_s": float(discharge.min()),
        "discharge_max_m3_s": float(discharge.max()),
        "topology_anchor_count": len(topology.anchors()),
    }
    lineage.update(
        {
            "route_class": config.route_class,
            "search_buffer_m": config.search_buffer_m,
            "persistence": config.persistence,
            "topology_contacts": list(topology.contact_ids),
            "hydraulic_geometry_assumptions": width_assumptions,
            "route_method": "D8 A* over terrain/runoff/catchment evidence; inherited axis used only to bound search",
            "axis_convention": "X/column increases east; Y/row increases south; map north is decreasing Y",
            "routing_trace": routing_trace,
            "route_cell_hash": sha256(np.asarray(route, dtype=np.int32).tobytes()).hexdigest(),
            "route_edge_hash": sha256(
                np.asarray(list(zip(route[:-1], route[1:])), dtype=np.int32).tobytes()
            ).hexdigest(),
            "routing_objective_terms": [
                "valley_position",
                "broad_downslope_alignment",
                "local_downslope_alignment",
                "regenerated_flow_accumulation",
                "regenerated_effective_discharge",
                "uphill_penalty",
                "direction_change_penalty",
            ],
            "inherited_axis_in_objective": False,
            "not_a_surveyed_10m_dem": True,
        }
    )
    return RegenerationResult(
        path_cells=route,
        discharge_m3_s=discharge.astype(float).tolist(),
        width_m=width.astype(float).tolist(),
        metrics=metrics,
        lineage=lineage,
    )


def save_result(path: Path, result: RegenerationResult) -> None:
    path.write_text(json.dumps(result.serialisable(), indent=2), encoding="utf-8")
