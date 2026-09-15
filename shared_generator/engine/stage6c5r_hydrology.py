"""Profile-aware hydrology helpers for the repaired Stage 6C.5R pilot.

The module deliberately separates two surfaces:

* land elevation, whose 100 m parent means remain authoritative; and
* channel-bed elevation, which follows stored 3D major-river controls or a
  clearly labelled, D3-constrained minor-stream reconstruction.

The channel-bed controls are analytical routing evidence.  They are never
silently written back into the parent-conserving land surface.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import islice
import json
from pathlib import Path
from typing import Iterable, Mapping, Sequence

import numpy as np
import shapely
from shapely.geometry import LineString, Point, shape

import algorithm_policy


METHOD_VERSION = "S6C5R_PROFILE_AWARE_HYDROLOGY_2.0.1_RECEIVER_ORIENTED"

# Geometry arrays are private to each call and bounded independently of the
# number of route cells. The shared profile remains immutable.
_PROJECTION_BLOCK_SIZE = 2048


def _project_chainage_reference(line: LineString, xy: Iterable[tuple[float, float]]) -> np.ndarray:
    """Retained scalar GEOS reference, also used without Shapely array APIs."""
    return np.asarray(
        [line.project(Point(float(x), float(y))) for x, y in xy], dtype=np.float64
    )


def _project_chainage(line: LineString, xy: Iterable[tuple[float, float]]) -> np.ndarray:
    """Batch the same GEOS projection without per-point Python geometry calls."""
    point_array = getattr(shapely, "points", None)
    locate = getattr(shapely, "line_locate_point", None)
    if not algorithm_policy.use_optimized("river_profile_sampling") or not callable(point_array) or not callable(locate):
        return _project_chainage_reference(line, xy)
    batches: list[np.ndarray] = []
    source = iter(xy)
    while True:
        block = [(float(x), float(y)) for x, y in islice(source, _PROJECTION_BLOCK_SIZE)]
        if not block:
            break
        batches.append(np.asarray(locate(line, point_array(block)), dtype=np.float64))
    return np.concatenate(batches) if batches else np.empty(0, dtype=np.float64)


class HydrologyProfileError(RuntimeError):
    """Fail-closed profile or topology error."""


@dataclass(frozen=True)
class MajorBedProfile:
    route_id: str
    line_2d: LineString
    chainage_km: np.ndarray
    elevation_m: np.ndarray
    properties: Mapping[str, object]


def _chainage_xy(coordinates: np.ndarray) -> np.ndarray:
    if coordinates.ndim != 2 or coordinates.shape[0] < 2 or coordinates.shape[1] < 2:
        raise HydrologyProfileError("A river profile must contain at least two XY vertices")
    steps = np.hypot(np.diff(coordinates[:, 0]), np.diff(coordinates[:, 1]))
    return np.concatenate(([0.0], np.cumsum(steps, dtype=np.float64)))


class ActiveMajorBedProfiles:
    """Hash-bound, route-ID keyed access to the current 3D major-bed controls."""

    def __init__(self, path: Path):
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        profiles: dict[str, MajorBedProfile] = {}
        for feature in payload.get("features", []):
            properties = dict(feature.get("properties") or {})
            route_id = str(properties.get("route_id") or "")
            if not route_id or route_id in profiles:
                raise HydrologyProfileError(f"Missing or duplicate major profile route_id: {route_id!r}")
            geometry = shape(feature.get("geometry"))
            if geometry.geom_type != "LineString" or not bool(geometry.has_z):
                raise HydrologyProfileError(f"Major profile {route_id} is not a 3D LineString")
            coordinates = np.asarray(geometry.coords, dtype=np.float64)
            if coordinates.shape[1] < 3 or not bool(np.all(np.isfinite(coordinates[:, :3]))):
                raise HydrologyProfileError(f"Major profile {route_id} has invalid XYZ coordinates")
            chainage = _chainage_xy(coordinates)
            if not bool(np.all(np.diff(chainage) > 0.0)):
                raise HydrologyProfileError(f"Major profile {route_id} has repeated planimetric vertices")
            elevation = coordinates[:, 2]
            if bool(np.any(np.diff(elevation) > 1e-7)):
                raise HydrologyProfileError(f"Major profile {route_id} is not monotone downstream")
            profiles[route_id] = MajorBedProfile(
                route_id=route_id,
                line_2d=LineString(coordinates[:, :2]),
                chainage_km=chainage,
                elevation_m=elevation,
                properties=properties,
            )
        if len(profiles) != 30:
            raise HydrologyProfileError(f"Expected 30 active major profiles, found {len(profiles)}")
        self._profiles = profiles

    @property
    def route_ids(self) -> frozenset[str]:
        return frozenset(self._profiles)

    def validate_axes(self, axes: Iterable[tuple[LineString, Mapping[str, object]]]) -> dict[str, float]:
        axis_by_id = {str(properties.get("route_id")): geometry for geometry, properties in axes}
        if set(axis_by_id) != set(self._profiles):
            missing = sorted(set(axis_by_id) - set(self._profiles))
            extra = sorted(set(self._profiles) - set(axis_by_id))
            raise HydrologyProfileError(f"Major axis/profile route-ID mismatch missing={missing} extra={extra}")
        deviations: list[float] = []
        for route_id, axis in axis_by_id.items():
            if axis.geom_type != "LineString":
                raise HydrologyProfileError(f"Major axis {route_id} is not a LineString")
            deviations.append(float(axis.hausdorff_distance(self._profiles[route_id].line_2d)))
        maximum = max(deviations, default=0.0)
        # One 100 m source cell is the largest defensible planimetric tolerance.
        if maximum > 0.100001:
            raise HydrologyProfileError(
                f"Major bed profile departs from its active axis by {maximum:.6f} km"
            )
        return {
            "major_profile_count": float(len(deviations)),
            "major_axis_profile_maximum_hausdorff_km": maximum,
        }

    def sample_z(self, route_id: str, xy: Sequence[tuple[float, float]]) -> np.ndarray:
        profile = self._profiles.get(str(route_id))
        if profile is None:
            raise HydrologyProfileError(f"No current major bed profile for {route_id}")
        projected = _project_chainage(profile.line_2d, xy)
        result = np.interp(projected, profile.chainage_km, profile.elevation_m)
        # A clipped/sample path can arrive in either direction.  Store and use
        # the route in downstream order, but never pair vertices by array index.
        return result.astype(np.float64)

    def properties(self, route_id: str) -> Mapping[str, object]:
        try:
            return self._profiles[str(route_id)].properties
        except KeyError as error:
            raise HydrologyProfileError(f"No current major bed profile for {route_id}") from error


def downstream_order(
    path_cells: Sequence[tuple[int, int]],
    bed_elevation_m: Sequence[float],
) -> tuple[tuple[tuple[int, int], ...], tuple[float, ...]]:
    path = tuple((int(row), int(col)) for row, col in path_cells)
    bed = np.asarray(bed_elevation_m, dtype=np.float64)
    if len(path) != len(bed) or len(path) < 2:
        raise HydrologyProfileError("Bed profile/path length mismatch")
    if float(bed[0]) < float(bed[-1]):
        path = tuple(reversed(path))
        bed = bed[::-1]
    return path, tuple(float(value) for value in bed)


def make_minor_bed_profile(
    path_cells: Sequence[tuple[int, int]],
    land_elevation_m: np.ndarray,
    *,
    nominal_depth_m: float,
    median_slope_m_per_km: float | None,
    minimum_drop_m_per_cell: float,
    cell_size_km: float = 0.01,
) -> tuple[tuple[tuple[int, int], ...], tuple[float, ...], dict[str, float | str]]:
    """Create a separate, monotone minor-bed control from D3 route evidence.

    D3 supplies a connected downstream graph and reach-level slope evidence,
    but no per-vertex Z.  This function therefore returns an explicitly
    modelled vertical control; it does not claim surveyed or authoritative Z.
    """

    path = tuple((int(row), int(col)) for row, col in path_cells)
    if len(path) < 2:
        raise HydrologyProfileError("A minor route part needs at least two cells")
    surface = np.asarray([land_elevation_m[cell] for cell in path], dtype=np.float64)
    # Orientation comes from the registered reach graph/receiver contact.  Do
    # not second-guess it from broad land elevation: that was the original
    # terrain-versus-bed category error this repair removes.
    # The enriched D3 slope is an absolute, sparsely sampled classification
    # summary from unconditioned terrain, not a per-vertex bed constraint.  Keep
    # it in lineage for explanation, but do not force that scalar gradient onto
    # the local 10 m bed.
    required_drop = float(minimum_drop_m_per_cell)
    target = surface - float(nominal_depth_m)
    bed = target.copy()
    for index in range(1, len(bed)):
        bed[index] = min(float(target[index]), float(bed[index - 1]) - required_drop)
    return path, tuple(float(value) for value in bed), {
        "vertical_control": "MODELLED_FROM_D3_CONNECTED_GRAPH_AND_LOCAL_SURFACE_NOT_OBSERVED_Z",
        "nominal_depth_m": float(nominal_depth_m),
        "applied_minimum_drop_m_per_cell": required_drop,
        "d3_median_slope_diagnostic_m_per_km": (
            None if median_slope_m_per_km is None else float(median_slope_m_per_km)
        ),
        "maximum_bed_below_local_land_surface_m": float(np.max(surface - bed)),
    }


def enforce_strict_bed_drop(
    bed_elevation_m: Sequence[float], minimum_drop_m_per_cell: float
) -> tuple[tuple[float, ...], float]:
    bed = np.asarray(bed_elevation_m, dtype=np.float64).copy()
    maximum_adjustment = 0.0
    for index in range(1, len(bed)):
        permitted = float(bed[index - 1]) - float(minimum_drop_m_per_cell)
        if float(bed[index]) >= permitted:
            original = float(bed[index])
            bed[index] = permitted
            maximum_adjustment = max(maximum_adjustment, original - permitted)
    return tuple(float(value) for value in bed), maximum_adjustment
