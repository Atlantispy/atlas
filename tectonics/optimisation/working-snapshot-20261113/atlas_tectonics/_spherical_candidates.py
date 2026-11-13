"""Conservative spherical broad phase for R2, never a polygon predicate.

Minor-arc area footprints lie in a conditioned hemisphere. A cap of radius < pi/2
containing all of a polygon's vertices contains its edges and areal interior by
geodesic convexity (holes can only remove area). We centre the cap on the vertex
mean when possible, rather than the common chart centre: otherwise a fine mesh
in one chart would have almost identical, useless enclosures.

On the unit sphere a cap of angular radius r is contained in the Euclidean ball
of radius 2*sin(r/2). Its coordinate bounds can therefore be indexed without
longitude seams or polar singularities. A 2D STRtree indexes two of the three
bounds; the third coordinate and cap-distance checks reject false positives.
Only final existing spherical overlays decide intersection. No approximate query,
snapping, feature-size cutoff or changed scientific tolerance is introduced.
"""
from __future__ import annotations

import math
from contextlib import contextmanager
import threading

import numpy as np
import shapely
from shapely.strtree import STRtree

from .geometry import GeometryError, _check_cancel
from .spherical_geometry import SphericalGeometry
from .resources import select_budget, reserve_budgets

# Outward guard on dimensionless enclosure arithmetic, not a polygon/area tolerance.
# Use a plain float so the existing loaded-constant provenance inventory covers it.
_PAD = float(512 * np.finfo(np.float64).eps)


def spherical_cap(geometry: SphericalGeometry) -> tuple[np.ndarray, float]:
    """Return a conservative, usually local cap, including every curved edge."""
    if type(geometry) is not SphericalGeometry or geometry.is_empty:
        raise GeometryError('nonempty spherical footprint required for cap')
    vertices = geometry.chart._unproject(shapely.get_coordinates(geometry._projected._geom))
    centre = np.sum(vertices, axis=0)
    norm = float(np.linalg.norm(centre))
    if norm > _PAD:
        centre = centre / norm
        radius = float(np.max(np.arctan2(np.linalg.norm(np.cross(vertices, centre), axis=1), vertices @ centre))) + _PAD
    else:
        radius = math.pi
    if radius >= math.pi / 2 - _PAD:
        # The established conditioned chart is a guaranteed hemispherical cover.
        # This fallback is geometric conservatism, not an approximate polygon.
        centre = np.asarray(geometry.chart.centre, dtype=np.float64)
        radius = float(np.max(np.arctan2(np.linalg.norm(np.cross(vertices, centre), axis=1), vertices @ centre))) + _PAD
    if not math.isfinite(radius) or radius >= math.pi / 2:
        raise GeometryError('spherical footprint has no certified conditioned cap')
    return centre, radius



class SphericalCandidateIndex:
    """Private, bounded read-only cap index. Owner joins readers before close.

    A query allocates at most one O(N) candidate row, never an all-pairs matrix.
    Stored geometry is shared. Native tree/bounds/cap memory stays admitted until
    close; callers budget geometry itself separately. Estimates are not RSS caps.
    """
    def __init__(self, geometries, *, budget=None, cancel=None):
        self.budget = select_budget(budget)
        self._lock = threading.Lock(); self._active = 0; self._closed = False
        self._guard = None; self._tree = None
        if type(geometries) is not tuple or not geometries:
            raise GeometryError('nonempty immutable footprint tuple required')
        first = geometries[0]
        if any(type(g) is not SphericalGeometry or g.is_empty or
               g.kind not in ('Polygon', 'MultiPolygon') or g.chart.sphere != first.chart.sphere for g in geometries):
            raise GeometryError('area footprints on one reference sphere required')
        n = len(geometries)
        max_vertices = max(g.vertex_count for g in geometries)
        allowance = 1536*n + 256*max_vertices + 16384
        self._guard = self.budget.reserve(allowance, category='spherical-candidates-retained')
        self._guard.__enter__()
        try:
            _check_cancel(cancel)
            centres = np.empty((n, 3)); radii = np.empty(n)
            for i, g in enumerate(geometries):
                _check_cancel(cancel)
                centres[i], radii[i] = spherical_cap(g)
            chords = 2*np.sin(radii/2) + _PAD
            lower = np.maximum(-1., centres-chords[:, None])-_PAD
            upper = np.minimum(1., centres+chords[:, None])+_PAD
            # Use the two most informative axes; dropping a coordinate may only
            # ADD candidates. Exact z/depth/cap filters are applied afterwards.
            axes = tuple(int(x) for x in np.argsort(np.ptp(centres, axis=0), kind='stable')[::-1])
            a, b, _ = axes
            boxes = shapely.box(lower[:, a], lower[:, b], upper[:, a], upper[:, b])
            self._tree = STRtree(boxes)
            # Own immutable bytes: external shape/write flag changes cannot edit
            # bounds under the native tree or later concurrent readers.
            self._centres = np.frombuffer(centres.tobytes(), dtype='f8').reshape(n, 3)
            self._radii = np.frombuffer(radii.tobytes(), dtype='f8')
            self._lower = np.frombuffer(lower.tobytes(), dtype='f8').reshape(n, 3)
            self._upper = np.frombuffer(upper.tobytes(), dtype='f8').reshape(n, 3)
            self._axes = axes
            self.count = n
            _check_cancel(cancel)
        except BaseException:
            self._tree = None
            self._guard.__exit__(None, None, None); self._guard = None
            raise

    def __enter__(self): return self
    def __exit__(self, *args): self.close()

    def close(self):
        with self._lock:
            if self._active:
                raise GeometryError('join active cap-index queries before close')
            if not self._closed:
                self._tree = None
                self._centres = self._radii = self._lower = self._upper = None
                self._closed = True
                self._guard.__exit__(None, None, None); self._guard = None

    @contextmanager
    def _operation(self):
        with self._lock:
            if self._closed: raise GeometryError('spherical candidate index is closed')
            self._active += 1
        try: yield
        finally:
            with self._lock: self._active -= 1

    def cap(self, index):
        return self._centres[index], float(self._radii[index])

    def query(self, geometry=None, *, index=None, budget=None, prepaid=False, cancel=None, diagnostics=None):
        """Sorted candidates whose enclosures might intersect; no area decisions.

        ``prepaid`` is internal to the R2 executor: its parent holds the complete
        job reservation while a detached child accounts within that allowance.
        Public callers normally join this index's and the query's budgets.
        """
        policy = self.budget if budget is None else select_budget(budget)
        budgets = (policy,) if prepaid else (self.budget, policy)
        with self._operation(), reserve_budgets(192*self.count+8192, *budgets,
                                                category='spherical-candidates-query'):
            _check_cancel(cancel)
            if index is not None:
                c, r = self.cap(index)
                lo, hi = self._lower[index], self._upper[index]
            else:
                c, r = spherical_cap(geometry)
                d = 2*math.sin(r/2)+_PAD
                lo = np.maximum(-1., c-d)-_PAD; hi = np.minimum(1., c+d)+_PAD
            a, b, z = self._axes
            hits = self._tree.query(shapely.box(lo[a], lo[b], hi[a], hi[b]))
            if diagnostics is not None:
                diagnostics['index_queries'] = diagnostics.get('index_queries', 0)+1
                diagnostics['box_candidates'] = diagnostics.get('box_candidates', 0)+len(hits)
            if len(hits):
                hits = hits[(self._lower[hits, z] <= hi[z]) & (self._upper[hits, z] >= lo[z])]
                # Bulk cap separation; angular margins admit boundary contacts.
                angle = np.arctan2(np.linalg.norm(np.cross(self._centres[hits], c), axis=1),
                                   np.sum(self._centres[hits]*c, axis=1))
                hits = hits[angle <= self._radii[hits]+r+_PAD]
            _check_cancel(cancel)
            return np.sort(hits)
