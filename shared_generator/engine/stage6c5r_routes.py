"""Deterministic route preparation for the Stage 6C.5R 10 m lenses.

The current hydrology geometry supplies frozen topology and a bounded search
corridor.  It is deliberately *not* a reward term in the routing objective.
Candidate paths are solved from the modelled terrain, must remain monotonic
downstream, and fail closed if their frozen endpoints or contacts cannot be
connected.  All outputs remain review-only analytical evidence.

Diadem map coordinates are expressed in kilometres and increase east in X and
south in Y.  Raster row therefore increases with map Y.  ``GridWindow`` keeps
that convention explicit and prevents an accidental north/south inversion.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import heapq
import json
import math
from typing import Iterable, Mapping, Sequence

import numpy as np
import shapely
from shapely.geometry import GeometryCollection, LineString, MultiLineString, Point, box

import algorithm_policy


METHOD_VERSION = "S6C5R_MONOTONIC_CORRIDOR_ROUTER_1.0.0"
STATUS = "WORKING PROPOSAL - REVIEW ONLY - NOT CANON"

# Stable neighbour order is part of deterministic tie-breaking.
D8: tuple[tuple[int, int, float], ...] = (
    (-1, 0, 1.0),
    (-1, 1, math.sqrt(2.0)),
    (0, 1, 1.0),
    (1, 1, math.sqrt(2.0)),
    (1, 0, 1.0),
    (1, -1, math.sqrt(2.0)),
    (0, -1, 1.0),
    (-1, -1, math.sqrt(2.0)),
)

CORRIDOR_RADII_M: Mapping[str, float] = {
    "titan": 400.0,
    "major": 200.0,
    "tier2": 100.0,
    "tier1": 50.0,
}

_CLASS_ALIASES: Mapping[str, str] = {
    "titan": "titan",
    "titan_river": "titan",
    "bc_001_r1": "titan",
    "major": "major",
    "major_river": "major",
    "tier2": "tier2",
    "tier_2": "tier2",
    "smaller_river": "tier2",
    "minor_river": "tier2",
    "tier1": "tier1",
    "tier_1": "tier1",
    "stream": "tier1",
}


class RouteReconstructionError(RuntimeError):
    """A fail-closed route preparation or routing error."""


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _cell_tuple(cell: Sequence[int]) -> tuple[int, int]:
    if len(cell) != 2:
        raise RouteReconstructionError(f"Grid cell must have two coordinates: {cell!r}")
    return int(cell[0]), int(cell[1])


@dataclass(frozen=True)
class GridWindow:
    """A north-up-equivalent local raster whose Y/row increases south.

    Production lenses use 300 x 300 cells at 10 m, i.e. 3 km square.  Smaller
    grids remain legal so the same code can be exercised by bounded fixtures.
    ``world_units_per_m`` defaults to 0.001 because Diadem vectors use km.
    """

    x_min: float
    y_min: float
    rows: int = 300
    cols: int = 300
    cell_size_m: float = 10.0
    world_units_per_m: float = 0.001

    def __post_init__(self) -> None:
        values = (self.x_min, self.y_min, self.cell_size_m, self.world_units_per_m)
        if not all(math.isfinite(float(value)) for value in values):
            raise RouteReconstructionError("Grid window values must be finite")
        if self.rows <= 0 or self.cols <= 0:
            raise RouteReconstructionError("Grid window dimensions must be positive")
        if self.cell_size_m <= 0 or self.world_units_per_m <= 0:
            raise RouteReconstructionError("Grid cell scales must be positive")

    @property
    def cell_size_world(self) -> float:
        return self.cell_size_m * self.world_units_per_m

    @property
    def x_max(self) -> float:
        return self.x_min + self.cols * self.cell_size_world

    @property
    def y_max(self) -> float:
        return self.y_min + self.rows * self.cell_size_world

    @property
    def shape(self) -> tuple[int, int]:
        return self.rows, self.cols

    @property
    def polygon(self):
        return box(self.x_min, self.y_min, self.x_max, self.y_max)

    def in_bounds(self, cell: Sequence[int]) -> bool:
        row, col = _cell_tuple(cell)
        return 0 <= row < self.rows and 0 <= col < self.cols

    def world_to_cell(self, x: float, y: float, *, clamp_boundary: bool = True) -> tuple[int, int]:
        """Map one point to its containing cell.

        A clipped point may lie exactly on the maximum window edge.  In that
        one case ``clamp_boundary`` maps it to the final in-window cell.
        """

        scale = self.cell_size_world
        raw_col = (float(x) - self.x_min) / scale
        raw_row = (float(y) - self.y_min) / scale
        col = math.floor(raw_col)
        row = math.floor(raw_row)
        epsilon = 1e-8
        if clamp_boundary:
            if col == self.cols and abs(raw_col - self.cols) <= epsilon:
                col = self.cols - 1
            if row == self.rows and abs(raw_row - self.rows) <= epsilon:
                row = self.rows - 1
        cell = int(row), int(col)
        if not self.in_bounds(cell):
            raise RouteReconstructionError(
                f"Coordinate ({x}, {y}) lies outside grid "
                f"[{self.x_min}, {self.y_min}, {self.x_max}, {self.y_max}]"
            )
        return cell

    def cell_center(self, cell: Sequence[int]) -> tuple[float, float]:
        row, col = _cell_tuple(cell)
        if not self.in_bounds((row, col)):
            raise RouteReconstructionError(f"Cell {(row, col)} lies outside grid")
        scale = self.cell_size_world
        return self.x_min + (col + 0.5) * scale, self.y_min + (row + 0.5) * scale

    def identity(self) -> dict[str, object]:
        return {
            **asdict(self),
            "x_max": self.x_max,
            "y_max": self.y_max,
            "axis_convention": "X/column east; Y/row south",
        }


@dataclass(frozen=True)
class SampledAxis:
    """Clipped raster cells, preserving source component and along-line order."""

    parts: tuple[tuple[tuple[int, int], ...], ...]
    source_geometry_type: str
    clipped_geometry_type: str
    sample_step_m: float
    boundary_runs: tuple[dict[str, object], ...]

    @property
    def cell_count(self) -> int:
        return sum(len(part) for part in self.parts)

    def serialisable(self) -> dict[str, object]:
        return {
            "parts": [[list(cell) for cell in part] for part in self.parts],
            "source_geometry_type": self.source_geometry_type,
            "clipped_geometry_type": self.clipped_geometry_type,
            "sample_step_m": self.sample_step_m,
            "boundary_runs": list(self.boundary_runs),
            "cell_count": self.cell_count,
        }


@dataclass(frozen=True)
class OrientedAxis:
    path_cells: tuple[tuple[int, int], ...]
    source_elevation_m: float
    receiver_elevation_m: float
    reversed_from_geometry: bool


@dataclass(frozen=True)
class RouteCandidate:
    path_cells: tuple[tuple[int, int], ...]
    coordinates: tuple[tuple[float, float], ...]
    metrics: Mapping[str, object]
    lineage: Mapping[str, object]

    def serialisable(self) -> dict[str, object]:
        return {
            "status": STATUS,
            "path_cells": [list(cell) for cell in self.path_cells],
            "coordinates": [list(coordinate) for coordinate in self.coordinates],
            "metrics": dict(self.metrics),
            "lineage": dict(self.lineage),
        }

    def geojson_feature(self, *, feature_id: str | None = None) -> dict[str, object]:
        properties = {
            "status": STATUS,
            "method": METHOD_VERSION,
            "route_cell_hash": self.lineage.get("route_cell_hash"),
        }
        if feature_id is not None:
            properties["feature_id"] = feature_id
        return {
            "type": "Feature",
            "properties": properties,
            "geometry": {
                "type": "LineString",
                "coordinates": [list(value) for value in self.coordinates],
            },
        }


def normalize_route_class(route_class: str) -> str:
    key = str(route_class).strip().lower().replace("-", "_").replace(" ", "_")
    try:
        return _CLASS_ALIASES[key]
    except KeyError as exc:
        raise RouteReconstructionError(
            f"No approved 6C.5R corridor radius for route class {route_class!r}"
        ) from exc


def corridor_radius_m(route_class: str) -> float:
    return float(CORRIDOR_RADII_M[normalize_route_class(route_class)])


def _line_members(geometry) -> list[LineString]:
    if geometry is None or geometry.is_empty:
        return []
    if isinstance(geometry, LineString):
        return [geometry]
    if isinstance(geometry, MultiLineString):
        return list(geometry.geoms)
    if isinstance(geometry, GeometryCollection):
        lines: list[LineString] = []
        for member in geometry.geoms:
            lines.extend(_line_members(member))
        return lines
    return []


def _deduplicate_consecutive(cells: Iterable[Sequence[int]]) -> tuple[tuple[int, int], ...]:
    result: list[tuple[int, int]] = []
    for value in cells:
        cell = _cell_tuple(value)
        if not result or result[-1] != cell:
            result.append(cell)
    return tuple(result)


def _densify_cells(cells: Sequence[tuple[int, int]]) -> tuple[tuple[int, int], ...]:
    """Fill every D8 cell crossed between sampled cells, preserving order."""

    if not cells:
        return ()
    result: list[tuple[int, int]] = [cells[0]]
    for (r0, c0), (r1, c1) in zip(cells[:-1], cells[1:]):
        steps = max(abs(r1 - r0), abs(c1 - c0))
        for index in range(1, steps + 1):
            cell = (
                int(round(r0 + (r1 - r0) * index / steps)),
                int(round(c0 + (c1 - c0) * index / steps)),
            )
            if cell != result[-1]:
                result.append(cell)
    return tuple(result)


def _boundary_sides(cell: tuple[int, int], shape: tuple[int, int]) -> tuple[str, ...]:
    row, col = cell
    rows, cols = shape
    sides: list[str] = []
    if row == 0:
        sides.append("north")
    if row == rows - 1:
        sides.append("south")
    if col == 0:
        sides.append("west")
    if col == cols - 1:
        sides.append("east")
    return tuple(sides)


def boundary_crossing_runs(
    path: Sequence[tuple[int, int]], shape: tuple[int, int]
) -> tuple[dict[str, object], ...]:
    """Summarise consecutive runs on a window boundary.

    A clipped route often follows a boundary for two or more sampled cells;
    reporting the run rather than each cell prevents inflated crossing counts.
    """

    runs: list[dict[str, object]] = []
    index = 0
    while index < len(path):
        sides = _boundary_sides(path[index], shape)
        if not sides:
            index += 1
            continue
        start = index
        all_sides = set(sides)
        while index + 1 < len(path):
            next_sides = _boundary_sides(path[index + 1], shape)
            if not next_sides:
                break
            index += 1
            all_sides.update(next_sides)
        kind = "interior"
        if start == 0:
            kind = "source"
        if index == len(path) - 1:
            kind = "receiver" if kind == "interior" else "source_and_receiver"
        runs.append(
            {
                "start_index": start,
                "end_index": index,
                "start_cell": list(path[start]),
                "end_cell": list(path[index]),
                "sides": sorted(all_sides),
                "kind": kind,
            }
        )
        index += 1
    return tuple(runs)


def _ordered_clipped_members(source: LineString, clipped) -> list[LineString]:
    members = _line_members(clipped)
    ordered: list[tuple[float, float, LineString]] = []
    for member in members:
        if member.length <= 0:
            continue
        coordinates = list(member.coords)
        first = float(source.project(Point(coordinates[0])))
        last = float(source.project(Point(coordinates[-1])))
        if last < first:
            member = LineString(coordinates[::-1])
            first, last = last, first
        ordered.append((first, last, member))
    ordered.sort(key=lambda value: (value[0], value[1], value[2].wkb_hex))
    return [value[2] for value in ordered]


def _sample_line(line: LineString, grid: GridWindow, sample_step_m: float) -> tuple[tuple[int, int], ...]:
    step_world = sample_step_m * grid.world_units_per_m
    steps = max(1, int(math.ceil(float(line.length) / step_world)))
    distances = np.linspace(0.0, float(line.length), steps + 1, dtype=np.float64)
    cells: list[tuple[int, int]] = []
    for distance in distances:
        point = line.interpolate(float(distance))
        cell = grid.world_to_cell(float(point.x), float(point.y), clamp_boundary=True)
        if not cells or cells[-1] != cell:
            cells.append(cell)
    return _densify_cells(cells)


def sample_geometry_to_grid(
    geometry,
    grid: GridWindow,
    *,
    sample_step_m: float | None = None,
) -> SampledAxis:
    """Clip LineString/MultiLineString geometry and sample ordered grid cells.

    Components retain their source order.  Pieces created by clipping retain
    their order along each source component.  Disconnected parts are never
    silently bridged.
    """

    if not isinstance(geometry, (LineString, MultiLineString)):
        raise RouteReconstructionError(
            f"Expected LineString or MultiLineString, received {getattr(geometry, 'geom_type', type(geometry).__name__)}"
        )
    if geometry.is_empty:
        raise RouteReconstructionError("Cannot sample an empty route geometry")
    step_m = float(sample_step_m if sample_step_m is not None else grid.cell_size_m / 2.0)
    if not math.isfinite(step_m) or step_m <= 0 or step_m > grid.cell_size_m:
        raise RouteReconstructionError("Sample step must be positive and no larger than one cell")

    parts: list[tuple[tuple[int, int], ...]] = []
    clipped_types: set[str] = set()
    for source in _line_members(geometry):
        clipped = source.intersection(grid.polygon)
        if clipped.is_empty:
            continue
        clipped_types.add(clipped.geom_type)
        for member in _ordered_clipped_members(source, clipped):
            sampled = _sample_line(member, grid, step_m)
            if len(sampled) >= 2:
                parts.append(sampled)
    if not parts:
        raise RouteReconstructionError("Route geometry has no two-cell segment inside the window")
    all_runs: list[dict[str, object]] = []
    for part_index, part in enumerate(parts):
        for run in boundary_crossing_runs(part, grid.shape):
            all_runs.append({"part_index": part_index, **run})
    return SampledAxis(
        parts=tuple(parts),
        source_geometry_type=geometry.geom_type,
        clipped_geometry_type="+".join(sorted(clipped_types)),
        sample_step_m=step_m,
        boundary_runs=tuple(all_runs),
    )


def orient_cells_downstream(
    cells: Sequence[tuple[int, int]],
    terrain_elevation_m: np.ndarray,
    *,
    endpoint_tolerance_m: float = 1e-6,
) -> OrientedAxis:
    """Orient one clipped axis from its higher endpoint to its lower endpoint."""

    path = _deduplicate_consecutive(cells)
    if len(path) < 2:
        raise RouteReconstructionError("A route axis requires at least two cells")
    terrain = np.asarray(terrain_elevation_m, dtype=np.float64)
    if terrain.ndim != 2:
        raise RouteReconstructionError("Terrain elevation must be a two-dimensional array")
    for cell in (path[0], path[-1]):
        if not (0 <= cell[0] < terrain.shape[0] and 0 <= cell[1] < terrain.shape[1]):
            raise RouteReconstructionError(f"Route endpoint {cell} lies outside terrain")
        if not math.isfinite(float(terrain[cell])):
            raise RouteReconstructionError(f"Route endpoint {cell} has non-finite elevation")
    first = float(terrain[path[0]])
    last = float(terrain[path[-1]])
    if abs(first - last) <= endpoint_tolerance_m:
        raise RouteReconstructionError(
            "Cannot infer downstream orientation: route endpoint elevations are indistinguishable"
        )
    reverse = first < last
    oriented = tuple(reversed(path)) if reverse else path
    return OrientedAxis(
        path_cells=oriented,
        source_elevation_m=float(terrain[oriented[0]]),
        receiver_elevation_m=float(terrain[oriented[-1]]),
        reversed_from_geometry=reverse,
    )


def corridor_mask_from_cells(
    shape: tuple[int, int],
    inherited_cells: Sequence[tuple[int, int]],
    route_class: str,
    *,
    cell_size_m: float = 10.0,
) -> np.ndarray:
    """Create the approved class-radius search corridor around an axis."""

    if len(shape) != 2 or shape[0] <= 0 or shape[1] <= 0:
        raise RouteReconstructionError(f"Invalid corridor shape {shape!r}")
    if not math.isfinite(cell_size_m) or cell_size_m <= 0:
        raise RouteReconstructionError("Cell size must be positive")
    dense = _densify_cells(_deduplicate_consecutive(inherited_cells))
    if len(dense) < 2:
        raise RouteReconstructionError("Cannot create corridor without a two-cell inherited axis")
    radius_m = corridor_radius_m(route_class)
    radius_cells = radius_m / cell_size_m
    if algorithm_policy.use_optimized("route_corridor_spans"):
        return _corridor_mask_spans(shape, dense, radius_cells)
    return _corridor_mask_reference(shape, dense, radius_cells)


def _corridor_mask_reference(
    shape: tuple[int, int], dense: Sequence[tuple[int, int]], radius_cells: float
) -> np.ndarray:
    """Retain the original disk-cell implementation as an exact replay oracle."""
    integer_radius = int(math.ceil(radius_cells))
    offsets: list[tuple[int, int]] = []
    for dr in range(-integer_radius, integer_radius + 1):
        for dc in range(-integer_radius, integer_radius + 1):
            if dr * dr + dc * dc <= radius_cells * radius_cells + 1e-12:
                offsets.append((dr, dc))
    mask = np.zeros(shape, dtype=bool)
    for row, col in dense:
        for dr, dc in offsets:
            rr, cc = row + dr, col + dc
            if 0 <= rr < shape[0] and 0 <= cc < shape[1]:
                mask[rr, cc] = True
    return mask


def _corridor_mask_spans(
    shape: tuple[int, int], dense: Sequence[tuple[int, int]], radius_cells: float
) -> np.ndarray:
    """Mark exact disk row spans instead of visiting every disk cell in Python.

    Inclusion uses precisely the reference integer predicate, including its
    epsilon; no Euclidean-distance approximation or raster dilation is used.
    Work per axis cell falls from O(radius squared) to O(radius), while writes
    within each contiguous span run in NumPy. Overlapping spans are idempotent.
    """
    integer_radius = int(math.ceil(radius_cells))
    limit = radius_cells * radius_cells + 1e-12
    spans: list[tuple[int, int]] = []
    # Derive half-widths using the original predicate instead of relying on
    # sqrt rounding at a non-integral radius. The width only decreases as the
    # absolute row offset grows, so this scan is O(radius), not O(radius squared).
    width = integer_radius
    for absolute_row in range(integer_radius + 1):
        while width >= 0 and absolute_row * absolute_row + width * width > limit:
            width -= 1
        if width < 0:
            break
        spans.append((absolute_row, width))
        if absolute_row:
            spans.append((-absolute_row, width))
    mask = np.zeros(shape, dtype=bool)
    for row, col in dense:
        for dr, half_width in spans:
            rr = row + dr
            if 0 <= rr < shape[0]:
                start = max(0, col - half_width)
                stop = min(shape[1], col + half_width + 1)
                if start < stop:
                    mask[rr, start:stop] = True
    return mask


def _validate_anchor_sequence(
    anchors: Sequence[tuple[int, int]], terrain: np.ndarray, corridor: np.ndarray, tolerance_m: float
) -> tuple[tuple[int, int], ...]:
    selected = tuple(_cell_tuple(cell) for cell in anchors)
    if len(selected) < 2:
        raise RouteReconstructionError("Routing requires frozen source and receiver cells")
    if len(set(selected)) != len(selected):
        raise RouteReconstructionError("Frozen endpoint/contact cells must be distinct")
    for cell in selected:
        row, col = cell
        if not (0 <= row < terrain.shape[0] and 0 <= col < terrain.shape[1]):
            raise RouteReconstructionError(f"Frozen topology cell {cell} lies outside terrain")
        if not corridor[cell]:
            raise RouteReconstructionError(f"Frozen topology cell {cell} lies outside corridor")
        if not math.isfinite(float(terrain[cell])):
            raise RouteReconstructionError(f"Frozen topology cell {cell} has non-finite elevation")
    elevations = [float(terrain[cell]) for cell in selected]
    for upstream, downstream in zip(elevations[:-1], elevations[1:]):
        if downstream > upstream + tolerance_m:
            raise RouteReconstructionError(
                "Frozen contacts are not in monotonic upstream-to-downstream elevation order"
            )
    return selected


def _astar_leg(
    terrain: np.ndarray,
    corridor: np.ndarray,
    start: tuple[int, int],
    goal: tuple[int, int],
    *,
    maximum_uphill_step_m: float,
    blocked: set[tuple[int, int]],
) -> tuple[list[tuple[int, int]], dict[str, object]]:
    rows, cols = terrain.shape
    cell_size_m = 1.0  # geometry is rescaled by caller in metrics; grid steps are the A* unit
    start_index = start[0] * cols + start[1]
    goal_index = goal[0] * cols + goal[1]
    g_score = np.full(rows * cols, np.inf, dtype=np.float64)
    parent = np.full(rows * cols, -1, dtype=np.int64)
    closed = np.zeros(rows * cols, dtype=bool)
    g_score[start_index] = 0.0
    queue: list[tuple[float, float, int]] = [(math.hypot(goal[0] - start[0], goal[1] - start[1]), 0.0, start_index)]
    expanded = 0
    relaxed = 0
    while queue:
        _, queued_g, index = heapq.heappop(queue)
        if closed[index] or queued_g > g_score[index] + 1e-12:
            continue
        closed[index] = True
        expanded += 1
        if index == goal_index:
            break
        row, col = divmod(index, cols)
        here_elevation = float(terrain[row, col])
        for dr, dc, step_cells in D8:
            rr, cc = row + dr, col + dc
            there = (rr, cc)
            if rr < 0 or rr >= rows or cc < 0 or cc >= cols:
                continue
            if not corridor[there] or not math.isfinite(float(terrain[there])):
                continue
            if there in blocked and there != goal:
                continue
            # Prevent a diagonal from jumping between two corner-touching
            # corridor islands.
            if dr and dc and not (corridor[row, cc] or corridor[rr, col]):
                continue
            there_elevation = float(terrain[there])
            if there_elevation > here_elevation + maximum_uphill_step_m + 1e-12:
                continue
            neighbour = rr * cols + cc
            if closed[neighbour]:
                continue
            drop_m = max(here_elevation - there_elevation, 0.0)
            # The objective has only geometric distance and terrain descent.
            # A small non-negative flatness penalty resolves alternatives
            # without ever rewarding proximity to the inherited axis.
            flatness_penalty = 0.05 / (1.0 + drop_m)
            step_cost = step_cells * cell_size_m * (1.0 + flatness_penalty)
            proposed = float(g_score[index]) + step_cost
            if proposed + 1e-12 >= float(g_score[neighbour]):
                continue
            g_score[neighbour] = proposed
            parent[neighbour] = index
            relaxed += 1
            heuristic = math.hypot(goal[0] - rr, goal[1] - cc) * cell_size_m
            heapq.heappush(queue, (proposed + heuristic, proposed, neighbour))
    if not closed[goal_index]:
        raise RouteReconstructionError(
            f"No monotonic route exists between frozen topology cells {start} and {goal}"
        )
    indices = [goal_index]
    while indices[-1] != start_index:
        previous = int(parent[indices[-1]])
        if previous < 0:
            raise RouteReconstructionError("A* parent chain is incomplete")
        indices.append(previous)
    indices.reverse()
    return [divmod(index, cols) for index in indices], {
        "expanded_cells": expanded,
        "relaxed_edges": relaxed,
        "objective_cost_grid_units": float(g_score[goal_index]),
    }


def monotonic_astar_route(
    terrain_elevation_m: np.ndarray,
    corridor: np.ndarray,
    source: Sequence[int],
    receiver: Sequence[int],
    *,
    ordered_contacts: Sequence[Sequence[int]] = (),
    maximum_uphill_step_m: float = 0.0,
) -> tuple[tuple[tuple[int, int], ...], dict[str, object]]:
    """Solve a deterministic monotonic route through frozen topology cells."""

    terrain = np.asarray(terrain_elevation_m, dtype=np.float64)
    allowed = np.asarray(corridor, dtype=bool)
    if terrain.ndim != 2 or terrain.shape != allowed.shape:
        raise RouteReconstructionError("Terrain and corridor must be aligned two-dimensional arrays")
    if maximum_uphill_step_m < 0 or not math.isfinite(maximum_uphill_step_m):
        raise RouteReconstructionError("Maximum uphill step must be finite and non-negative")
    anchors = _validate_anchor_sequence(
        (_cell_tuple(source), *(_cell_tuple(cell) for cell in ordered_contacts), _cell_tuple(receiver)),
        terrain,
        allowed,
        maximum_uphill_step_m,
    )
    route: list[tuple[int, int]] = []
    blocked: set[tuple[int, int]] = set()
    leg_traces: list[dict[str, object]] = []
    for leg_index, (start, goal) in enumerate(zip(anchors[:-1], anchors[1:])):
        leg, trace = _astar_leg(
            terrain,
            allowed,
            start,
            goal,
            maximum_uphill_step_m=maximum_uphill_step_m,
            blocked=blocked,
        )
        trace.update({"leg_index": leg_index, "start": list(start), "goal": list(goal)})
        leg_traces.append(trace)
        if route:
            leg = leg[1:]
        route.extend(leg)
        blocked.update(route[:-1])
    if not route or route[0] != anchors[0] or route[-1] != anchors[-1]:
        raise RouteReconstructionError("Candidate route changed a frozen endpoint")
    cursor = 0
    for contact in anchors[1:-1]:
        try:
            cursor = route.index(contact, cursor) + 1
        except ValueError as exc:
            raise RouteReconstructionError(f"Candidate route lost frozen contact {contact}") from exc
    elevations = np.asarray([terrain[cell] for cell in route], dtype=np.float64)
    maximum_uphill = float(max(float(np.diff(elevations).max(initial=0.0)), 0.0))
    if maximum_uphill > maximum_uphill_step_m + 1e-9:
        raise RouteReconstructionError("Candidate route violates monotonic elevation contract")
    return tuple(route), {
        "anchor_count": len(anchors),
        "frozen_contacts_retained": len(anchors) - 2,
        "leg_traces": leg_traces,
        "maximum_uphill_step_m": maximum_uphill,
        "source_elevation_m": float(elevations[0]),
        "receiver_elevation_m": float(elevations[-1]),
        "total_drop_m": float(elevations[0] - elevations[-1]),
        "inherited_axis_used_in_objective": False,
        "objective_terms": ["geometric_step_length", "terrain_descent_flatness_penalty"],
    }


def _nearest_distance_cells(
    source: Sequence[tuple[int, int]], target: Sequence[tuple[int, int]]
) -> np.ndarray:
    left = np.asarray(source, dtype=np.float64)
    right = np.asarray(target, dtype=np.float64)
    if left.size == 0 or right.size == 0:
        raise RouteReconstructionError("Divergence comparison requires two non-empty paths")
    result = np.full(len(left), np.inf, dtype=np.float64)
    for start in range(0, len(left), 512):
        block = left[start : start + 512]
        squared = np.square(block[:, None, :] - right[None, :, :]).sum(axis=2)
        result[start : start + len(block)] = np.sqrt(squared.min(axis=1))
    return result


def route_divergence_metrics(
    candidate: Sequence[tuple[int, int]],
    inherited: Sequence[tuple[int, int]],
    *,
    cell_size_m: float = 10.0,
) -> dict[str, object]:
    candidate_path = _deduplicate_consecutive(candidate)
    inherited_path = _densify_cells(_deduplicate_consecutive(inherited))
    if not candidate_path or not inherited_path:
        raise RouteReconstructionError("Divergence comparison requires non-empty paths")
    inherited_set = set(inherited_path)
    forward = _nearest_distance_cells(candidate_path, inherited_path)
    backward = _nearest_distance_cells(inherited_path, candidate_path)
    return {
        "candidate_exact_inherited_fraction": float(
            sum(cell in inherited_set for cell in candidate_path) / len(candidate_path)
        ),
        "candidate_mean_divergence_m": float(forward.mean() * cell_size_m),
        "candidate_p95_divergence_m": float(np.percentile(forward, 95.0) * cell_size_m),
        "candidate_max_divergence_m": float(forward.max() * cell_size_m),
        "symmetric_hausdorff_m": float(max(forward.max(), backward.max()) * cell_size_m),
    }


def _corridor_edge_mask(corridor: np.ndarray) -> np.ndarray:
    allowed = np.asarray(corridor, dtype=bool)
    padded = np.pad(allowed, 1, mode="constant", constant_values=False)
    interior = allowed.copy()
    rows, cols = allowed.shape
    for dr in range(3):
        for dc in range(3):
            if dr == 1 and dc == 1:
                continue
            interior &= padded[dr : dr + rows, dc : dc + cols]
    return allowed & ~interior


def route_diagnostics(
    candidate: Sequence[tuple[int, int]],
    inherited: Sequence[tuple[int, int]],
    corridor: np.ndarray,
    *,
    cell_size_m: float = 10.0,
) -> dict[str, object]:
    path = _deduplicate_consecutive(candidate)
    if not path:
        raise RouteReconstructionError("Cannot diagnose an empty route")
    edge = _corridor_edge_mask(corridor)
    edge_indices = [index for index, cell in enumerate(path) if edge[cell]]
    crossings = boundary_crossing_runs(path, corridor.shape)
    return {
        **route_divergence_metrics(path, inherited, cell_size_m=cell_size_m),
        "window_boundary_runs": list(crossings),
        "window_boundary_crossing_count": len(crossings),
        "corridor_edge_cell_count": len(edge_indices),
        "corridor_edge_fraction": float(len(edge_indices) / len(path)),
        "corridor_edge_route_indices": edge_indices,
        "corridor_edge_used": bool(edge_indices),
    }


def export_candidate_route_coordinates(
    path_cells: Sequence[tuple[int, int]], grid: GridWindow
) -> tuple[tuple[float, float], ...]:
    path = _deduplicate_consecutive(path_cells)
    if len(path) < 2:
        raise RouteReconstructionError("Candidate route requires at least two cells")
    return tuple(grid.cell_center(cell) for cell in path)


def build_route_candidate(
    terrain_elevation_m: np.ndarray,
    grid: GridWindow,
    inherited_cells: Sequence[tuple[int, int]],
    route_class: str,
    *,
    ordered_contacts: Sequence[Sequence[int]] = (),
    maximum_uphill_step_m: float = 0.0,
) -> RouteCandidate:
    """Orient an inherited axis, create its corridor, and solve a candidate."""

    terrain = np.asarray(terrain_elevation_m, dtype=np.float64)
    if terrain.shape != grid.shape:
        raise RouteReconstructionError("Terrain shape does not match grid window")
    route_kind = normalize_route_class(route_class)
    oriented = orient_cells_downstream(inherited_cells, terrain)
    corridor = corridor_mask_from_cells(
        terrain.shape,
        oriented.path_cells,
        route_kind,
        cell_size_m=grid.cell_size_m,
    )
    candidate, routing = monotonic_astar_route(
        terrain,
        corridor,
        oriented.path_cells[0],
        oriented.path_cells[-1],
        ordered_contacts=ordered_contacts,
        maximum_uphill_step_m=maximum_uphill_step_m,
    )
    metrics = {
        **routing,
        **route_diagnostics(
            candidate,
            oriented.path_cells,
            corridor,
            cell_size_m=grid.cell_size_m,
        ),
        "path_cell_count": len(candidate),
        "corridor_radius_m": corridor_radius_m(route_kind),
        "corridor_cell_count": int(np.count_nonzero(corridor)),
        "source_on_window_boundary": bool(_boundary_sides(candidate[0], grid.shape)),
        "receiver_on_window_boundary": bool(_boundary_sides(candidate[-1], grid.shape)),
    }
    route_array = np.asarray(candidate, dtype=np.int32)
    lineage = {
        "method": METHOD_VERSION,
        "status": STATUS,
        "grid": grid.identity(),
        "route_class": route_kind,
        "inherited_axis_role": "corridor and frozen topology only; never a cost reward",
        "inherited_axis_used_in_objective": False,
        "orientation_inferred_from_endpoint_terrain": True,
        "geometry_reversed_for_downstream_orientation": oriented.reversed_from_geometry,
        "route_cell_hash": sha256(route_array.tobytes(order="C")).hexdigest(),
        "semantic_hash": sha256(
            _canonical_json(
                {
                    "method": METHOD_VERSION,
                    "grid": grid.identity(),
                    "route_class": route_kind,
                    "inherited_cells": oriented.path_cells,
                    "ordered_contacts": [list(_cell_tuple(cell)) for cell in ordered_contacts],
                    "maximum_uphill_step_m": maximum_uphill_step_m,
                }
            ).encode("utf-8")
        ).hexdigest(),
    }
    return RouteCandidate(
        path_cells=candidate,
        coordinates=export_candidate_route_coordinates(candidate, grid),
        metrics=metrics,
        lineage=lineage,
    )


__all__ = [
    "CORRIDOR_RADII_M",
    "GridWindow",
    "METHOD_VERSION",
    "OrientedAxis",
    "RouteCandidate",
    "RouteReconstructionError",
    "STATUS",
    "SampledAxis",
    "boundary_crossing_runs",
    "build_route_candidate",
    "corridor_mask_from_cells",
    "corridor_radius_m",
    "export_candidate_route_coordinates",
    "monotonic_astar_route",
    "normalize_route_class",
    "orient_cells_downstream",
    "route_diagnostics",
    "route_divergence_metrics",
    "sample_geometry_to_grid",
]
