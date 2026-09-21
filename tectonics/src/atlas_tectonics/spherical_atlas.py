"""W01 3B: a closed spherical atlas, without a privileged global projection.

The source is a shared vertex registry and oriented, conforming polygon patches.
Each patch uses an existing conditioned gnomonic chart, but edges, incidence,
measurements and plate IDs are global. A plate/region can span any number of
patches, contain holes, be disconnected, or cover the complete sphere.

Validation is NOT merely 'areas add to 4*pi'. Simple, injective local faces,
two opposite uses per edge, and a once-around vertex link make the assembled
map a local homeomorphism. The connected compact surface then covers S^2 once;
Euler characteristic and an independently summed area provide extra checks.
No coordinate clustering, repair, snapping, gap tolerance, or physics is supplied.

Input geometry must already be conforming. At a seam, both patches reference the
same vertices in the same subdivision. A T-junction or crossing that was not
explicitly noded is refused. Authoritative topology uses IDs, not a proximity test.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import math
from typing import Any, Mapping

import numpy as np
import shapely
from shapely.geometry import Polygon, LineString

from .coordinates import SphericalFrame
from ._validation import read_array, scalar, input_shape
from .geometry import (GeometryError, _limits, _label, _json, _point_shape,
                       _check_cancel, GeometryLimits)
from .resources import select_budget, reserve_budgets, elements
from .spherical_geometry import SphericalChart, SphericalGeometry, _directions, _ring_area
from .geometry_index import GeometryFeature, GeometryIndex
from .boundaries import (BoundaryRegion, BoundaryNetwork, SharedBoundary,
                         BoundaryJunction, BoundaryFrames, BoundaryKinematics, _sha)

_SCHEMA = 'atlas.closed-spherical-atlas.v1'
_METHOD = 'canonical-minor-arcs-oriented-manifold-v1'
# This is an ambiguity/refusal band in radians, never a coordinate snap grid.
_ANGULAR_RESOLUTION = 64 * np.finfo(float).eps
_AREA_TOLERANCE_SR = 2e-11


def _digest(value):
    return hashlib.sha256(_json(value)).hexdigest()


def _cycle(ids):
    """Canonical starting vertex only; never reverse the declared orientation."""
    if type(ids) is not tuple or len(ids) < 3:
        raise GeometryError('an explicit tuple of at least three distinct vertex IDs is required')
    for name in ids:
        _label(name, 'vertex ID')
    if len(set(ids)) != len(ids):
        raise GeometryError('a patch ring repeats a vertex (do not repeat its closing ID)')
    k = ids.index(min(ids))
    return ids[k:] + ids[:k]


@dataclass(frozen=True, slots=True)
class SphericalPatch:
    """One oriented local face; region and plate identities survive patch changes.

    The outer ring is counter-clockwise and holes clockwise in this chart.
    Every edge is the minor great-circle arc between registered vertices. The
    chart only selects a well-conditioned, unambiguous local interior, not metres.
    A large/holed region may alternatively be represented as several simple faces.
    """
    patch_id: str
    region_id: str
    plate_id: str
    vertex_ids: tuple[str, ...]
    chart: SphericalChart
    holes: tuple[tuple[str, ...], ...] = ()

    def __post_init__(self):
        for name in ('patch_id', 'region_id', 'plate_id'):
            _label(getattr(self, name), name)
        if type(self.chart) is not SphericalChart:
            raise GeometryError('explicit SphericalChart required')
        if type(self.holes) is not tuple:
            raise GeometryError('holes must be an explicit tuple')
        outer = _cycle(self.vertex_ids)
        holes = tuple(sorted(_cycle(h) for h in self.holes))
        all_ids = outer + tuple(v for h in holes for v in h)
        if len(set(all_ids)) != len(all_ids):
            raise GeometryError('patch rings must not share or repeat vertices')
        object.__setattr__(self, 'vertex_ids', outer)
        object.__setattr__(self, 'holes', holes)

    @property
    def rings(self):
        return (self.vertex_ids,) + self.holes

    def descriptor(self):
        return {'patch_id': self.patch_id, 'region_id': self.region_id,
                'plate_id': self.plate_id, 'vertex_ids': list(self.vertex_ids),
                'holes': [list(h) for h in self.holes], 'chart': self.chart.descriptor()}


def _unit(a):
    scale = np.max(np.abs(a), axis=-1, keepdims=True)
    if np.any(scale == 0) or not np.isfinite(scale).all():
        raise GeometryError('zero or nonfinite direction')
    v = a / scale
    return v / np.sqrt(np.sum(v * v, axis=-1, keepdims=True))


def _capture_directions(a):
    """Keep an existing unit registry byte-stable across chart reattachment.

    Binary64 directions produced by normalisation have a norm within a few ulps
    of one. Renormalising those at every import drifts coordinates and identifiers.
    Preserve such already-unit data (same 16-epsilon contract as restoration),
    normalising only input rows whose magnitudes do not represent unit directions.
    This changes no seam topology and never merges different registered vertices.
    """
    a = np.array(a, dtype='f8', copy=True)
    with np.errstate(over='ignore', invalid='ignore'):
        norms = np.linalg.norm(a, axis=-1)
    change = np.abs(norms-1) > 16*np.finfo(float).eps
    if a.ndim == 1:
        return _unit(a) if bool(change) else a
    if change.any(): a[change] = _unit(a[change])
    return a


def _angle(a, b):
    return 2 * np.arctan2(np.linalg.norm(a-b, axis=-1), np.linalg.norm(a+b, axis=-1))


def _measure_ring(u):
    closed = np.concatenate((u, u[:1]))
    # A canonical boundary vertex is the fan anchor. Changing the working chart
    # cannot change this evaluation. Signed fans support concave simple polygons.
    return _ring_area(closed, u[0])


def _face_geometry(patch, points, lookup, limits, budget):
    rings = [points[[lookup[v] for v in ring]] for ring in patch.rings]
    xy = [patch.chart._project(u) for u in rings]
    raw = Polygon(xy[0], xy[1:])
    if not raw.is_valid or raw.is_empty or raw.area <= 0:
        raise GeometryError('patch is not a simple, nonempty local polygon')
    if not shapely.is_ccw(raw.exterior) or any(shapely.is_ccw(h) for h in raw.interiors):
        raise GeometryError('patch orientation must keep its interior on the left')
    geometry = SphericalGeometry.polygon(rings[0], holes=rings[1:], chart=patch.chart,
                                          limits=limits, budget=budget)
    areas = [_measure_ring(u) for u in rings]
    area = math.fsum([areas[0], *(-a for a in areas[1:])])
    if not math.isfinite(area) or area <= 0 or area >= 2*math.pi:
        raise GeometryError('unresolvable or non-hemispherical patch area')
    return geometry, area


def _vertex_links(points, edge_array, sides, patch_count, resolution, cancel):
    """Check the geometric link, not just combinatorial edge pairing.

    The left patch of each outgoing tangent must fill exactly the sector up to
    the next tangent's right patch. Every incident patch contributes one corner;
    a double winding, pinch, dangling fan or reversed local sheet is refused.
    """
    rays = [[] for _ in points]
    for i, (a, b) in enumerate(edge_array):
        if i % 4096 == 0:
            _check_cancel(cancel)
        for source, target, sign in ((a, b, 1), (b, a, -1)):
            radial = points[source]
            axis = np.eye(3)[int(np.argmin(np.abs(radial)))]
            east = _unit(np.cross(axis, radial))
            north = np.cross(radial, east)
            normal = _unit(np.cross(radial + points[target], points[target] - radial))
            tangent = _unit(np.cross(normal, radial))
            angle = math.atan2(float(tangent @ north), float(tangent @ east))
            rays[source].append((angle, i, sign))
    offsets, incidence = [0], []
    for rows in rays:
        _check_cancel(cancel)
        rows.sort()
        if len(rows) < 2:
            raise GeometryError('unpaired/dangling spherical vertex')
        sectors = []
        for k, (angle, edge, sign) in enumerate(rows):
            next_angle, other, other_sign = rows[(k+1) % len(rows)]
            gap = (next_angle - angle) % (2*math.pi)
            if gap <= resolution:
                raise GeometryError('coincident or numerically ambiguous junction rays')
            left = int(sides[edge, 0 if sign > 0 else 1])
            next_right = int(sides[other, 1 if other_sign > 0 else 0])
            if left != next_right:
                raise GeometryError('spherical junction sectors overlap or leave a gap')
            sectors.append(left)
        if len(set(sectors)) != len(sectors):
            raise GeometryError('a patch wraps around or repeats a junction corner')
        incidence.extend((e, s) for _, e, s in rows)
        offsets.append(len(incidence))
    return np.array(offsets, dtype='i8'), np.array(incidence, dtype='i8')


@dataclass(frozen=True, slots=True, init=False)
class SphericalAtlas:
    """Closed static planetary ownership and chart-independent edge geometry.

    One immutable global direction per named vertex; two sides per edge, no
    exterior owner. Indices are representation-specific, while edge IDs exclude
    working charts. Reuse index() for repeated point queries; it holds its own
    retained-budget reservation until close(). The atlas payload itself remains
    caller-owned, as do existing BoundaryNetwork and MaterialState payloads.
    """
    sphere: SphericalFrame
    patches: tuple[SphericalPatch, ...]
    vertex_ids: tuple[str, ...]
    edge_ids: tuple[str, ...]
    regions: tuple[BoundaryRegion, ...]
    atlas_id: str
    geometry_id: str
    _points: bytes = field(repr=False)
    _edges: bytes = field(repr=False)
    _sides: bytes = field(repr=False)
    _areas: bytes = field(repr=False)
    _offsets: bytes = field(repr=False)
    _incidence: bytes = field(repr=False)
    _provenance: bytes = field(repr=False)
    _resolution: float
    _stats: bytes = field(repr=False)

    def __init__(self, *args, **kwargs):
        raise GeometryError('use build_spherical_atlas()')

    @property
    def vertex_directions(self): return np.frombuffer(self._points, dtype='f8').reshape(-1, 3)
    @property
    def edge_vertices(self): return np.frombuffer(self._edges, dtype='i8').reshape(-1, 2)
    @property
    def side_patches(self): return np.frombuffer(self._sides, dtype='i8').reshape(-1, 2)
    @property
    def patch_areas_sr(self): return np.frombuffer(self._areas, dtype='f8')
    @property
    def vertex_count(self): return len(self.vertex_ids)
    @property
    def edge_count(self): return len(self.edge_ids)
    @property
    def plate_ids(self): return tuple(sorted({p.plate_id for p in self.patches}))
    @property
    def region_ids(self): return tuple(sorted({p.region_id for p in self.patches}))
    @property
    def statistics(self):
        import json
        return json.loads(self._stats)
    @property
    def retained_bytes_estimate(self):
        payload = sum(len(v) for v in (self._points, self._edges, self._sides, self._areas,
                      self._offsets, self._incidence, self._provenance, self._stats))
        return (payload + sum(r.geometry.retained_bytes for r in self.regions)
                + 1024 * (self.vertex_count + self.edge_count + len(self.patches)))

    def descriptor(self):
        import json
        return {'schema': _SCHEMA, 'method': _METHOD, 'sphere': self.sphere.descriptor(),
                'vertex_ids': list(self.vertex_ids), 'patches': [p.descriptor() for p in self.patches],
                'angular_resolution_rad': self._resolution,
                'source_bindings': json.loads(self._provenance),
                'geometry_id': self.geometry_id, 'atlas_id': self.atlas_id}

    def _indices(self, indices=None):
        if indices is None: return np.arange(self.edge_count, dtype='i8')
        if type(indices) not in (tuple, list, np.ndarray):
            raise GeometryError('explicit edge indices required')
        if isinstance(indices, np.ndarray):
            if np.ma.isMaskedArray(indices) or indices.ndim != 1 or indices.dtype.kind not in 'iu':
                raise GeometryError('unmasked one-dimensional integer indices required')
        elif any(type(i) is not int for i in indices):
            raise GeometryError('integer edge indices required')
        if len(indices) > self.edge_count or any(int(i) < 0 or int(i) >= self.edge_count for i in indices):
            raise GeometryError('edge selection out of range')
        return np.array(indices, dtype='i8', copy=True)

    def role(self, index):
        i = int(self._indices([index])[0]); l, r = self.side_patches[i]
        return 'patch-seam' if self.patches[l].plate_id == self.patches[r].plate_id else 'interplate'

    @property
    def interplate_edges(self):
        return tuple(i for i, (l, r) in enumerate(self.side_patches)
                     if self.patches[l].plate_id != self.patches[r].plate_id)

    def edge(self, index, *, reverse=False):
        if type(reverse) is not bool: raise GeometryError('reverse must be bool')
        i = int(self._indices([index])[0]); a, b = self.vertex_directions[self.edge_vertices[i]]
        l, r = (self.patches[j] for j in self.side_patches[i])
        out = SharedBoundary(self.edge_ids[i], tuple(a), tuple(b), l.region_id, r.region_id,
                             l.plate_id, r.plate_id, self.role(i))
        return out.reversed() if reverse else out

    def adjacency(self, *, by_plate=True):
        if type(by_plate) is not bool: raise GeometryError('by_plate must be bool')
        names = [p.plate_id if by_plate else p.region_id for p in self.patches]
        return tuple(sorted({tuple(sorted((names[l], names[r]))) for l, r in self.side_patches
                             if names[l] != names[r]}))

    def areas(self, *, by_plate=True):
        if type(by_plate) is not bool: raise GeometryError('by_plate must be bool')
        groups = {}
        for p, a in zip(self.patches, self.patch_areas_sr):
            name = p.plate_id if by_plate else p.region_id
            groups.setdefault(name, []).append(float(a))
        return {name: (math.fsum(values) * self.sphere.radius_m) * self.sphere.radius_m
                for name, values in sorted(groups.items())}

    def perimeters(self, *, by_plate=True):
        """Count actual owner changes only; internal patch cuts add no coastline."""
        if type(by_plate) is not bool: raise GeometryError('by_plate must be bool')
        names = [p.plate_id if by_plate else p.region_id for p in self.patches]
        groups = {n: [] for n in names}; points = self.vertex_directions
        for (a, b), (l, r) in zip(self.edge_vertices, self.side_patches):
            if names[l] != names[r]:
                length = float(_angle(points[a], points[b])) * self.sphere.radius_m
                groups[names[l]].append(length); groups[names[r]].append(length)
        return {name: math.fsum(values) for name, values in sorted(groups.items())}

    def junction(self, vertex_index, *, limits=None, budget=None, cancel=None):
        _check_cancel(cancel); limits = _limits(limits)
        if type(vertex_index) is not int or not 0 <= vertex_index < self.vertex_count:
            raise GeometryError('vertex index out of range')
        offsets = np.frombuffer(self._offsets, dtype='i8')
        rows = np.frombuffer(self._incidence, dtype='i8').reshape(-1, 2)[offsets[vertex_index]:offsets[vertex_index+1]]
        if len(rows)**2 > limits.max_overlay_pairs:
            raise GeometryError('junction pair limit exceeded')
        with select_budget(budget).reserve(512*len(rows)**2+8192, category='atlas-junction'):
            sectors, present, adjacent = [], set(), set()
            for i, sign in rows:
                l, r = self.side_patches[i]
                if sign < 0: l, r = r, l
                a, b = self.patches[l].region_id, self.patches[r].region_id
                sectors.append(a); present.update((a, b))
                if a != b: adjacent.add(tuple(sorted((a, b))))
            ordered = sorted(present)
            contacts = tuple((a, b) for i, a in enumerate(ordered) for b in ordered[i+1:]
                             if (a, b) not in adjacent)
            _check_cancel(cancel)
            return BoundaryJunction(self.vertex_ids[vertex_index], tuple(self.vertex_directions[vertex_index]),
                tuple(int(e) for e, _ in rows), tuple(int(s) for _, s in rows), tuple(sectors), contacts)

    def frames(self, indices=None, *, reverse=False, fraction=0.5, limits=None, budget=None, cancel=None):
        _check_cancel(cancel); limits = _limits(limits)
        f = scalar(fraction, 'fraction', nonnegative=True)
        if f > 1 or type(reverse) is not bool:
            raise GeometryError('fraction in [0,1] and boolean reverse required')
        if indices is not None and type(indices) not in (tuple, list, np.ndarray):
            raise GeometryError('explicit edge selection required')
        if isinstance(indices, np.ndarray) and indices.ndim != 1:
            raise GeometryError('one-dimensional edge selection required')
        n = self.edge_count if indices is None else len(indices)
        if n > limits.max_hits: raise GeometryError('frame output exceeds limit')
        with select_budget(budget).reserve(256*n + 1024*min(n, limits.batch_points)+8192,
                                           category='atlas-frames'):
            ids = self._indices(indices)
            p = np.empty((n, 3)); t = np.empty_like(p); normal = np.empty_like(p); length = np.empty(n)
            for start in range(0, n, limits.batch_points):
                _check_cancel(cancel); end = min(n, start+limits.batch_points)
                ab = self.vertex_directions[self.edge_vertices[ids[start:end]]]
                if reverse: ab = ab[:, ::-1]
                a, b = ab[:, 0], ab[:, 1]
                left = _unit(np.cross(a+b, b-a)); theta = _angle(a, b)
                radial = a if f == 0 else b if f == 1 else _unit(
                    np.cos(f*theta)[:, None]*a + np.sin(f*theta)[:, None]*np.cross(left, a))
                with np.errstate(over='ignore', invalid='ignore'):
                    p[start:end] = radial*self.sphere.radius_m
                    t[start:end] = _unit(np.cross(left, radial))
                    normal[start:end] = -left; length[start:end] = theta*self.sphere.radius_m
            if not all(np.isfinite(x).all() for x in (p, t, normal, length)):
                raise GeometryError('spherical metric outside binary64 range')
            _check_cancel(cancel)
            return BoundaryFrames((n, 3), p.tobytes(), t.tobytes(), normal.tobytes(), length.tobytes())

    def motion(self, velocities_by_plate, boundary_velocity_m_s, *, indices=None,
               reverse=False, budget=None, cancel=None):
        """Same stage-3 diagnostics on global verified sides, not a force model."""
        _check_cancel(cancel)
        if not isinstance(velocities_by_plate, Mapping): raise GeometryError('plate velocity mapping required')
        ids = self._indices(self.interplate_edges if indices is None else indices)
        if len(np.unique(ids)) != len(ids): raise GeometryError('duplicate motion selection')
        if type(reverse) is not bool: raise GeometryError('reverse must be bool')
        n = len(ids)
        with select_budget(budget).reserve(1024*n+16384, category='atlas-motion'):
            sides = self.side_patches[ids]
            if reverse: sides = sides[:, ::-1]
            def velocity(value):
                if input_shape(value, 'velocity') not in ((3,), (n, 3)):
                    raise GeometryError('velocity must be a vector or match selected edges')
                return np.broadcast_to(read_array(value, 'velocity'), (n, 3))
            left = np.empty((n, 3)); right = np.empty_like(left)
            groups = {}
            for row, (l, r) in enumerate(sides):
                for col, face in enumerate((l, r)):
                    groups.setdefault(self.patches[face].plate_id, [[], []])[col].append(row)
            for plate, rows in groups.items():
                if plate not in velocities_by_plate: raise GeometryError('missing plate velocity')
                v = velocity(velocities_by_plate[plate])
                for col, target in enumerate((left, right)):
                    sub = np.asarray(rows[col], dtype='i8'); target[sub] = v[sub]
            boundary = velocity(boundary_velocity_m_s)
            f = self.frames(ids, reverse=reverse, budget=budget, cancel=cancel)
            with np.errstate(over='ignore', invalid='ignore'):
                relative = right-left
                result = np.column_stack((np.sum(relative*f.right_normal, axis=1),
                    np.sum(relative*f.tangent, axis=1), np.sum((left-boundary)*f.right_normal, axis=1),
                    np.sum((right-boundary)*f.right_normal, axis=1),
                    np.sum(relative*(f.position_m/self.sphere.radius_m), axis=1)))
            if not np.isfinite(result).all(): raise GeometryError('velocity exceeds numerical range')
            _check_cancel(cancel)
            return BoundaryKinematics(tuple(self.edge_ids[i] for i in ids), result.tobytes())

    def index(self, *, limits=None, budget=None):
        return SphericalAtlasIndex(self, limits=limits, budget=budget)

    def local_network(self, patch_id, *, limits=None, budget=None, cancel=None):
        """Stage-3 interoperability: one selected face in its own bounded chart."""
        from .boundaries import build_boundary_network
        for p, region in zip(self.patches, self.regions):
            if p.patch_id == patch_id:
                return build_boundary_network(region.geometry, (region,), limits=limits, budget=budget, cancel=cancel)
        raise GeometryError('unknown patch')

    def __reduce__(self):
        return (_restore_atlas, (self.descriptor(), self._points))

    def __deepcopy__(self, memo):
        memo[id(self)] = self
        return self


def build_spherical_atlas(sphere, vertices, patches, *, limits=None, budget=None, cancel=None,
                          angular_resolution_rad=_ANGULAR_RESOLUTION, source_bindings=None,
                          _restored=False):
    """Validate and join a complete conforming spherical partition.

    ``vertices`` maps globally shared IDs to directions in sphere.frame_id. Each
    ID has ONE authoritative position, normalised once during capture. Duplicate
    geometric vertices under different IDs are refused, not welded. Every vertex
    must be used; all face edges must match in opposite directions by exact IDs.
    ``angular_resolution_rad`` controls rejection of ambiguous geometry; it does
    not fill missing faces or move coordinates. No user-selected area tolerance.
    """
    _check_cancel(cancel); limits = _limits(limits); policy = select_budget(budget)
    if type(sphere) is not SphericalFrame or not isinstance(vertices, Mapping):
        raise GeometryError('explicit sphere and shared vertex mapping required')
    if (type(patches) not in (tuple, list) or not patches or
            any(type(p) is not SphericalPatch for p in patches)):
        raise GeometryError('explicit nonempty SphericalPatch sequence required')
    count = sum(len(ring) for p in patches for ring in p.rings)
    if len(vertices) < 4 or len(vertices) > limits.max_vertices or count > limits.max_vertices:
        raise GeometryError('atlas vertex/half-edge envelope exceeded')
    resolution = scalar(angular_resolution_rad, 'angular resolution', positive=True)
    if resolution < _ANGULAR_RESOLUTION or resolution > 1e-6:
        raise GeometryError('unsupported spherical ambiguity resolution')
    bindings = {} if source_bindings is None else source_bindings
    try: provenance = _json(bindings)
    except (TypeError, ValueError, OverflowError) as exc: raise GeometryError('invalid source-binding provenance') from exc
    if type(bindings) is not dict or len(provenance) > 512*count + 65536:
        raise GeometryError('source bindings exceed metadata envelope')
    with policy.reserve(4096*count + 1024*len(vertices) + 2*len(provenance)+65536, category='atlas-build'):
        for name in vertices: _label(name, 'vertex ID')
        names = tuple(sorted(vertices)); lookup = {name: i for i, name in enumerate(names)}
        data = []
        for name in names:
            if _point_shape(vertices[name], 3) != (3,): raise GeometryError('one direction per vertex required')
            data.append(read_array(vertices[name], 'vertex'))
        points = np.asarray(data, dtype='f8'); del data
        if _restored:
            if np.any(np.abs(np.linalg.norm(points, axis=1)-1) > 16*np.finfo(float).eps):
                raise GeometryError('saved atlas vertices are not unit directions')
        else: points = _capture_directions(points)
        if len(np.unique(points, axis=0)) != len(points):
            raise GeometryError('duplicate geometric vertices must use one shared ID')
        ordered = tuple(sorted(patches, key=lambda p: p.patch_id))
        if len({p.patch_id for p in ordered}) != len(ordered): raise GeometryError('duplicate patch ID')
        registered = set(lookup)
        owners, edge_uses, used, geometry, areas = {}, {}, set(), [], []
        for face, p in enumerate(ordered):
            _check_cancel(cancel)
            if p.chart.sphere != sphere: raise GeometryError('patch sphere/radius/frame mismatch')
            if p.region_id in owners and owners[p.region_id] != p.plate_id:
                raise GeometryError('one geological region cannot have conflicting plate ownership')
            owners[p.region_id] = p.plate_id
            for ring in p.rings:
                if not set(ring) <= registered: raise GeometryError('patch names an unregistered vertex')
                used.update(ring)
                ids = [lookup[v] for v in ring]
                for a, b in zip(ids, ids[1:] + ids[:1]):
                    theta = float(_angle(points[a], points[b]))
                    if theta <= resolution or theta >= math.pi-resolution:
                        raise GeometryError('zero, unresolved or antipodal spherical edge')
                    key = (min(a, b), max(a, b))
                    row = edge_uses.setdefault(key, [-1, -1])
                    column = 0 if a < b else 1
                    if row[column] != -1: raise GeometryError('duplicate directed edge/same-side ownership')
                    row[column] = face
            g, area = _face_geometry(p, points, lookup, limits, policy)
            geometry.append(BoundaryRegion(p.patch_id, p.plate_id, g)); areas.append(area)
        if used != set(names): raise GeometryError('unused registered vertex')
        if any(-1 in s or s[0] == s[1] for s in edge_uses.values()):
            raise GeometryError('unpaired seam/gap or inconsistent seam subdivision')
        edges = np.array(sorted(edge_uses), dtype='i8'); sides = np.array([edge_uses[e] for e in sorted(edge_uses)], dtype='i8')
        # Connected face adjacency prevents two independent closed surfaces being
        # accepted merely because each component has individually paired edges.
        graph = [[] for _ in ordered]
        for l, r in sides: graph[l].append(int(r)); graph[r].append(int(l))
        seen, stack = {0}, [0]
        while stack:
            _check_cancel(cancel)
            for nxt in graph[stack.pop()]:
                if nxt not in seen: seen.add(nxt); stack.append(nxt)
        if len(seen) != len(ordered): raise GeometryError('atlas contains disconnected surface sheets')
        chi = len(names)-len(edges)+sum(1-len(p.holes) for p in ordered)
        if chi != 2: raise GeometryError('closed atlas must have spherical Euler characteristic two')
        offsets, incidence = _vertex_links(points, edges, sides, len(ordered), resolution, cancel)
        area_sum = math.fsum(areas)
        if abs(area_sum-4*math.pi) > _AREA_TOLERANCE_SR:
            raise GeometryError('spherical area closure failed; no normalisation of areas allowed')
        total_metric = (area_sum*sphere.radius_m)*sphere.radius_m
        if not math.isfinite(total_metric) or total_metric <= 0:
            raise GeometryError('planet area outside positive binary64 range')
        intrinsic = {'schema': _SCHEMA, 'method': _METHOD, 'sphere': sphere.descriptor(), 'vertices': list(names),
                     'patches': [{k: v for k, v in p.descriptor().items() if k != 'chart'} for p in ordered]}
        geometry_id = hashlib.sha256(_json(intrinsic)+b'\0'+points.tobytes()).hexdigest()
        context = {'geometry_id': geometry_id, 'charts': [p.chart.descriptor() for p in ordered],
                   'resolution': resolution, 'bindings': bindings}
        identifier = _digest(context)
        edge_ids = tuple(_digest({'schema': 'atlas.global-edge.v1', 'sphere': sphere.descriptor(),
                                 'ends': [points[a].tolist(), points[b].tolist()],
                                 'regions': [ordered[l].region_id, ordered[r].region_id],
                                 'plates': [ordered[l].plate_id, ordered[r].plate_id]})
                         for (a, b), (l, r) in zip(edges, sides))
        obj = object.__new__(SphericalAtlas)
        values = {'sphere': sphere, 'patches': ordered, 'vertex_ids': names, 'edge_ids': edge_ids,
                  'regions': tuple(geometry), 'atlas_id': identifier, 'geometry_id': geometry_id,
                  '_points': points.tobytes(), '_edges': edges.tobytes(), '_sides': sides.tobytes(),
                  '_areas': np.asarray(areas, dtype='f8').tobytes(), '_offsets': offsets.tobytes(),
                  '_incidence': incidence.tobytes(), '_provenance': provenance, '_resolution': resolution,
                  '_stats': _json({'patches': len(ordered), 'vertices': len(names), 'edges': len(edges),
                                  'euler_characteristic': chi, 'area_steradians': area_sum,
                                  'area_residual_sr': area_sum-4*math.pi, 'unpaired_edges': 0,
                                  'topology_halfedges': count, 'global_dense_pair_matrix': False})}
        for key, value in values.items(): object.__setattr__(obj, key, value)
        obj.frames(limits=limits, budget=policy, cancel=cancel)
        _check_cancel(cancel)
        return obj


@dataclass(frozen=True, slots=True)
class AtlasHits:
    """All matching owner IDs, including both sides on an interplate boundary.

    Patch seams of the same owner collapse to a single owner. No arbitrary
    first/nearest-owner choice is made. Query points exactly on a plate junction
    intentionally have multiple owners; they are not a coverage overlap.
    """
    owner_ids: tuple[str, ...]
    candidate_pairs: int
    exhaustive_pairs: int
    _payload: bytes = field(repr=False)
    @property
    def pairs(self): return np.frombuffer(self._payload, dtype='i8').reshape(-1, 2)


class SphericalAtlasIndex:
    """Bounded native cap pruning followed by existing exact local predicates.

    A conditioned patch lies in the geodesically convex cap containing all of
    its vertices. Radius buckets prevent one large patch from widening every
    fine-patch query. cKDTree uses chord distances ONLY for conservative candidate
    pruning; final ownership uses local polygon and spherical boundary predicates.
    Trees are prepared once, immutable during queries, and charged until close.
    """
    def __setattr__(self, name, value):
        if name in ("_atlas", "limits", "budget") and hasattr(self, name):
            raise GeometryError("index definitions are immutable")
        object.__setattr__(self, name, value)

    def __init__(self, atlas, *, limits=None, budget=None):
        from scipy.spatial import cKDTree
        import threading
        if type(atlas) is not SphericalAtlas: raise GeometryError('SphericalAtlas required')
        self._atlas = atlas; self.limits = _limits(limits); self.budget = select_budget(budget)
        if sum(len(r) for p in atlas.patches for r in p.rings) > self.limits.max_vertices:
            raise GeometryError('atlas index vertex envelope exceeded')
        self._guard = self.budget.reserve(1024*len(atlas.patches)+16384, category='atlas-index-retained')
        self._guard.__enter__(); self._lock = threading.Lock(); self._active = 0; self._closed = False
        try:
            lookup = {name: i for i, name in enumerate(atlas.vertex_ids)}
            grouped = {}; self._groups = []
            for i, p in enumerate(atlas.patches):
                centre = np.asarray(p.chart.centre)
                points = atlas.vertex_directions[[lookup[v] for v in p.vertex_ids]]
                radius = float(np.max(_angle(points, centre)))
                # A shared chart may cover many small pieces. Its centre gives
                # an unnecessarily huge cap for pieces near the chart's edge.
                # The vertex-mean cap is tighter when it remains hemispherical;
                # positive dot products make that cap geodesically convex, so it
                # contains every edge and the polygon interior (also if concave).
                candidate = _unit(np.sum(points, axis=0))
                candidate_radius = float(np.max(_angle(points, candidate)))
                if np.all(points @ candidate > 0) and candidate_radius < radius:
                    centre, radius = candidate, candidate_radius
                bucket = math.ceil(math.log2(max(radius, _ANGULAR_RESOLUTION)))
                grouped.setdefault(bucket, []).append((i, centre, radius))
            for values in grouped.values():
                ids = np.array([v[0] for v in values], dtype='i8')
                centres = np.array([v[1] for v in values]); radii = np.array([v[2] for v in values])
                self._groups.append((cKDTree(centres, copy_data=True), ids, radii, float(radii.max())))
        except BaseException:
            self._guard.__exit__(None, None, None)
            raise

    def __enter__(self): return self
    def __exit__(self, *args): self.close()

    def close(self):
        with self._lock:
            if self._active: raise GeometryError('join active queries before closing atlas index')
            if not self._closed:
                self._groups.clear(); self._closed = True; self._guard.__exit__(None, None, None)

    def query(self, directions, *, by_plate=True, angular_tolerance_rad=_ANGULAR_RESOLUTION,
              budget=None, cancel=None):
        _check_cancel(cancel)
        if type(by_plate) is not bool: raise GeometryError('by_plate must be bool')
        tol = scalar(angular_tolerance_rad, 'angular tolerance', nonnegative=True)
        if any(tol >= p.chart.min_cosine/4 for p in self._atlas.patches):
            raise GeometryError('boundary band exceeds chart validity')
        with self._lock:
            if self._closed: raise GeometryError('atlas index is closed')
            self._active += 1
        try:
            count = elements(_point_shape(directions, 3))//3
            limit = self.limits.max_hits
            max_batch = max(1, limit//max(len(g[1]) for g in self._groups))
            batch = min(self.limits.batch_points, max_batch)
            policy = self.budget if budget is None else select_budget(budget)
            required = 96*min(count*len(self._atlas.patches),limit)+128*count+65536
            with reserve_budgets(required, policy, self.budget, category='atlas-owner-query'):
                points = _directions(directions).reshape(-1,3)
                names = self._atlas.plate_ids if by_plate else self._atlas.region_ids
                lookup = {name: i for i, name in enumerate(names)}
                owners = [lookup[p.plate_id if by_plate else p.region_id] for p in self._atlas.patches]
                rows = []; candidate_count = 0
                for start in range(0,count,batch):
                    _check_cancel(cancel); block = points[start:start+batch]
                    candidates = {}
                    for tree, ids, radii, maximum in self._groups:
                        # Outward padding covers tree/direction rounding and the
                        # declared boundary band. It NEVER changes final geometry.
                        reach = 2*math.sin(min(math.pi,maximum+tol)/2)+256*np.finfo(float).eps
                        raw = tree.query_ball_point(block, reach, workers=1)
                        lengths = np.fromiter((len(v) for v in raw), dtype='i8', count=len(block))
                        size = int(lengths.sum())
                        if size > limit:
                            raise GeometryError('atlas query raw-candidate capacity exceeded')
                        if not size: continue
                        query_rows = np.repeat(np.arange(len(block), dtype='i8'), lengths)
                        local = np.fromiter((j for values in raw for j in values), dtype='i8', count=size)
                        # Vectorised broad-phase rejection: no per-candidate
                        # Python trigonometry or point-by-feature distance table.
                        chord = np.linalg.norm(block[query_rows]-tree.data[local], axis=1)
                        allowed = 2*np.sin(np.minimum(math.pi,radii[local]+tol)/2)+256*np.finfo(float).eps
                        keep = chord <= allowed
                        selected_rows = query_rows[keep]; faces = ids[local[keep]]
                        candidate_count += len(faces)
                        if not len(faces): continue
                        order = np.argsort(faces, kind='stable')
                        faces = faces[order]; selected_rows = selected_rows[order]
                        ends = np.r_[np.flatnonzero(faces[1:] != faces[:-1])+1, len(faces)]
                        pos = 0
                        for end in ends:
                            candidates[int(faces[pos])] = selected_rows[pos:end]
                            pos = int(end)
                        if sum(map(len,candidates.values())) > limit:
                            raise GeometryError('atlas query candidate capacity exceeded')
                    seen = np.zeros(len(block),dtype=bool)
                    for face, selected in sorted(candidates.items()):
                        selected = np.asarray(selected,dtype='i8')
                        result = self._atlas.regions[face].geometry.classify(block[selected],
                            angular_tolerance_rad=tol,limits=self.limits,budget=policy,cancel=cancel)
                        hit = selected[result >= 0]; seen[hit] = True
                        if len(rows)+len(hit)>limit: raise GeometryError('atlas query output exceeds max_hits; use smaller batches')
                        rows.extend((start+int(i),owners[face]) for i in hit)
                    if not seen.all():
                        raise GeometryError('numerical query cannot establish coverage; no nearest-owner fallback')
                array = np.unique(np.asarray(rows,dtype='i8').reshape(-1,2),axis=0)
                _check_cancel(cancel)
                return AtlasHits(names,candidate_count,count*len(self._atlas.patches),array.tobytes())
        finally:
            with self._lock: self._active -= 1

    def query_batches(self, batches, **kwargs):
        for batch in batches:
            yield self.query(batch, **kwargs)
            del batch


def _restore_atlas(desc, payload, *, limits=None, budget=None, cancel=None):
    if (type(desc) is not dict or set(desc) != {'schema','method','sphere','vertex_ids','patches',
           'angular_resolution_rad','source_bindings','geometry_id','atlas_id'} or
           desc['schema'] != _SCHEMA or desc['method'] != _METHOD):
        raise GeometryError('invalid spherical atlas descriptor')
    limits = _limits(limits)
    if type(payload) is not bytes or type(desc['vertex_ids']) is not list or type(desc['patches']) is not list:
        raise GeometryError('invalid atlas payload or inventory')
    if len(desc['vertex_ids']) > limits.max_vertices or len(desc['patches']) > limits.max_vertices:
        raise GeometryError('saved atlas exceeds limits')
    if len(payload) != 24*len(desc['vertex_ids']): raise GeometryError('atlas vertex payload length mismatch')
    try:
        names = desc['vertex_ids']
        if names != sorted(set(names)): raise GeometryError('stored vertex IDs must be unique and sorted')
        s = desc['sphere']; sphere = SphericalFrame(s['radius_m'], s['frame_id'])
        if sphere.descriptor() != s: raise GeometryError('stored sphere metadata mismatch')
        patches = []
        for row in desc['patches']:
            if type(row) is not dict or set(row) != {'patch_id','region_id','plate_id','vertex_ids','holes','chart'}:
                raise GeometryError('invalid stored patch')
            patches.append(SphericalPatch(row['patch_id'],row['region_id'],row['plate_id'],
                tuple(row['vertex_ids']), SphericalChart.from_descriptor(row['chart']),
                tuple(tuple(h) for h in row['holes'])))
        points = np.frombuffer(payload, dtype='f8').reshape(-1,3)
        out = build_spherical_atlas(sphere, dict(zip(names,points)), tuple(patches), limits=limits,
            budget=budget, cancel=cancel, angular_resolution_rad=desc['angular_resolution_rad'],
            source_bindings=desc['source_bindings'], _restored=True)
        if out.descriptor() != desc: raise GeometryError('restored atlas identity mismatch')
        return out
    except (TypeError,KeyError,ValueError) as exc:
        if isinstance(exc,GeometryError): raise
        raise GeometryError('malformed spherical atlas snapshot') from exc


def save_spherical_atlas(atlas, store, *, budget=None, cancel=None):
    from .storage import ArrayStore
    _check_cancel(cancel)
    if type(atlas) is not SphericalAtlas or not isinstance(store,ArrayStore):
        raise GeometryError('typed atlas and ArrayStore required')
    return store.put(atlas.atlas_id, {'directions': atlas.vertex_directions}, atlas.descriptor(),
                     budget=budget,cancel=cancel)


def load_spherical_atlas(store, atlas_id, *, limits=None, budget=None, cancel=None):
    _sha(atlas_id); _check_cancel(cancel)
    values=store.get(atlas_id,budget=budget)
    if values is None: return None
    if set(values) != {'directions'} or values['directions'].dtype != np.dtype('f8') or values['directions'].ndim != 2 or values['directions'].shape[1] != 3:
        raise GeometryError('atlas snapshot array contract mismatch')
    desc=store.metadata(atlas_id)
    if type(desc) is not dict or desc.get('atlas_id') != atlas_id:
        raise GeometryError('atlas snapshot identity mismatch')
    return _restore_atlas(desc,values['directions'].tobytes(),limits=limits,budget=budget,cancel=cancel)


def stitch_spherical_networks(networks, vertices, vertex_bindings, *, region_bindings=None,
                             limits=None, budget=None, cancel=None):
    """Join existing stage-3 networks through explicit shared-vertex bindings.

    networks maps a patch name to a BoundaryNetwork; vertex_bindings maps each
    name to the global vertex IDs in its network.vertex_xy order. vertices is the
    authoritative registry. This deliberately is NOT nearest-neighbour welding.
    Independently projected copies are checked within the fixed 64-epsilon
    angular round-off band; the measured attachment errors and input identities
    are recorded. Larger differences are refused, not snapped or reprojected away.

    The global definition is the registered geometry supplied by the caller.
    Source charts remain local numerical views. All source edge subdivisions
    must already be conforming; missing seam nodes are not guessed.
    """
    _check_cancel(cancel); limits = _limits(limits); policy = select_budget(budget)
    if not isinstance(networks, Mapping) or not networks or not isinstance(vertex_bindings, Mapping):
        raise GeometryError('named networks and explicit vertex bindings required')
    if not isinstance(vertices, Mapping) or set(networks) != set(vertex_bindings):
        raise GeometryError('network/binding inventory mismatch')
    if any(type(n) is not BoundaryNetwork or not n.spherical for n in networks.values()):
        raise GeometryError('only spherical stage-3 boundary networks can be stitched')
    sphere = next(iter(networks.values())).domain.chart.sphere
    total = sum(n.vertex_count + n.edge_count for n in networks.values())
    if total > limits.max_vertices or len(vertices) > limits.max_vertices:
        raise GeometryError('source network or registry envelope exceeded')
    provided = {} if region_bindings is None else region_bindings
    if not isinstance(provided, Mapping): raise GeometryError('explicit region binding mapping required')
    valid_region_keys = {(name, r.region_id) for name, n in networks.items() for r in n.regions}
    if not set(provided) <= valid_region_keys: raise GeometryError('unknown regional owner binding')
    with policy.reserve(4096*total+65536, category='atlas-stitch'):
        canonical = {}
        for name, value in vertices.items():
            _label(name, 'shared vertex')
            if _point_shape(value, 3) != (3,): raise GeometryError('one shared direction required')
            canonical[name] = _capture_directions(read_array(value, 'registered direction'))
        patches, sources, candidates = [], [], 0
        for name, network in sorted(networks.items()):
            _check_cancel(cancel); _label(name, 'network name')
            if network.domain.chart.sphere != sphere: raise GeometryError('stitched spherical frames differ')
            binding = vertex_bindings[name]
            if type(binding) is not tuple or len(binding) != network.vertex_count or len(set(binding)) != len(binding):
                raise GeometryError('one distinct global vertex ID per local network vertex required')
            if not set(binding) <= set(canonical): raise GeometryError('unknown registered seam vertex')
            original = _unit(network.domain.chart._unproject(network.vertex_xy))
            mapped = np.array([canonical[v] for v in binding])
            errors = _angle(original, mapped)
            if np.any(errors > _ANGULAR_RESOLUTION):
                raise GeometryError('source seam coordinates disagree with the explicit shared definition')
            sources.append({'name': name, 'network_id': network.network_id,
                            'vertex_bindings': list(binding), 'maximum_attachment_error_rad': float(errors.max()),
                            'region_bindings': [[r.region_id, provided.get((name,r.region_id),r.region_id)]
                                                for r in network.regions]})
            for region_index, region in enumerate(network.regions):
                # The network retains authored regions in their source charts,
                # but its atomic edges and index use the declared domain chart.
                aligned = region.geometry.in_chart(network.domain.chart, limits=limits, budget=policy)
                shape = shapely.orient_polygons(aligned._projected._geom)
                parts = [shape] if shape.geom_type == 'Polygon' else list(shape.geoms)
                for component, poly in enumerate(parts):
                    ring_ids = []
                    for ring in [poly.exterior, *poly.interiors]:
                        path = []
                        xy = np.asarray(ring.coords)
                        for a, b in zip(xy[:-1], xy[1:]):
                            _check_cancel(cancel)
                            segment = LineString((a,b)); pieces=[]
                            direction = b-a
                            axis = int(np.argmax(np.abs(direction)))
                            for i in network._tree.query(segment):
                                candidates += 1
                                if candidates > limits.max_overlay_pairs:
                                    raise GeometryError('seam attachment candidate limit exceeded')
                                i = int(i)
                                if not segment.covers(network._shapes[i]): continue
                                j, k = (int(v) for v in network.edge_vertices[i])
                                if (network.vertex_xy[k,axis]-network.vertex_xy[j,axis])*direction[axis] < 0:
                                    j,k=k,j; side=1
                                else: side=0
                                if network.side_regions[i,side] != region_index:
                                    raise GeometryError('source boundary side contradicts its region ring')
                                pieces.append(((network.vertex_xy[j,axis]-a[axis])/direction[axis],j,k))
                            pieces.sort()
                            if not pieces: raise GeometryError('source ring is missing shared atomic segments')
                            for _, j, k in pieces:
                                if path and path[-1] != j:
                                    raise GeometryError('source ring atomic segments are discontinuous')
                                if not path: path.append(j)
                                path.append(k)
                        if path[-1] != path[0]: raise GeometryError('source ring is not closed')
                        ring_ids.append(tuple(binding[i] for i in path[:-1]))
                    patch_id = 'patch-'+_digest((name,region.region_id,component))[:32]
                    patches.append(SphericalPatch(patch_id,provided.get((name,region.region_id),region.region_id),
                        region.plate_id,ring_ids[0],network.domain.chart,tuple(ring_ids[1:])))
        # Reuse the captured unit directions without a second normalisation step.
        return build_spherical_atlas(sphere,canonical,tuple(patches),limits=limits,budget=policy,
            cancel=cancel,source_bindings={'networks':sources, 'attachment_band_rad':_ANGULAR_RESOLUTION,
                                         'candidate_segments':candidates},_restored=True)
