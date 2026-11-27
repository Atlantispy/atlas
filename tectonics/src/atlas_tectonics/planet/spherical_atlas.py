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

import numpy as np
import shapely
from shapely.geometry import Polygon, LineString

from atlas_shared.formulas import sphere
from atlas_tectonics.planet.coordinates import SphericalFrame
from atlas_tectonics._validation import read_array, scalar
from atlas_tectonics._validation import unit_rows
from atlas_tectonics.planet.geometry import (GeometryError, _limits, _label, _json, _point_shape,
                       _check_cancel, GeometryLimits)
from atlas_tectonics.integration.resources import select_budget, reserve_budgets, elements
from atlas_tectonics.integration.resources import _immutable_deepcopy
from atlas_tectonics.integration.resources import require_sha256
from atlas_tectonics.integration.reuse import content_record
from atlas_tectonics.planet.spherical_geometry import SphericalChart, SphericalGeometry, _directions, _ring_area
from atlas_tectonics.planet.geometry_index import GeometryFeature, GeometryIndex
from atlas_tectonics.plates.boundaries import (BoundaryRegion, BoundaryNetwork, SharedBoundary,
                         BoundaryJunction, BoundaryFrames, BoundaryKinematics)

_SCHEMA = 'atlas.closed-spherical-atlas.v1'
_METHOD = 'canonical-minor-arcs-oriented-manifold-v1'
# This is an ambiguity/refusal band in radians, never a coordinate snap grid.
_ANGULAR_RESOLUTION = 64 * np.finfo(float).eps
_AREA_TOLERANCE_SR = 2e-11


def _digest(value):
    return hashlib.sha256(_json(value)).hexdigest()


def _cycle(ids):
    """Canonical starting vertex only; never reverse the declared orientation."""
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
        outer = _cycle(self.vertex_ids)
        holes = tuple(sorted(_cycle(h) for h in self.holes))
        object.__setattr__(self, 'vertex_ids', outer)
        object.__setattr__(self, 'holes', holes)

    @property
    def rings(self):
        return (self.vertex_ids,) + self.holes

    def descriptor(self):
        return {'patch_id': self.patch_id, 'region_id': self.region_id,
                'plate_id': self.plate_id, 'vertex_ids': list(self.vertex_ids),
                'holes': [list(h) for h in self.holes], 'chart': self.chart.descriptor()}


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
        return unit_rows(a, GeometryError, 'zero or nonfinite direction') if bool(change) else a
    if change.any(): a[change] = unit_rows(a[change], GeometryError, 'zero or nonfinite direction')
    return a


_angle = sphere.angle_array


def _measure_ring(u):
    closed = np.concatenate((u, u[:1]))
    # Choose the fan anchor from captured coordinates, independent of vertex IDs.
    # Keep the original directed edge sequence for signed fans and concave rings.
    anchor = min(u, key=tuple)
    return _ring_area(closed, anchor)


def _face_geometry(patch, points, lookup, limits, budget):
    rings = [points[[lookup[v] for v in ring]] for ring in patch.rings]
    xy = [patch.chart._project(u) for u in rings]
    raw = Polygon(xy[0], xy[1:])
    if not raw.is_valid or raw.is_empty or raw.area <= 0:
        raise GeometryError('patch is not a simple, nonempty local polygon')
    geometry = SphericalGeometry.polygon(rings[0], holes=rings[1:], chart=patch.chart,
                                          limits=limits, budget=budget)
    areas = [_measure_ring(u) for u in rings]
    area = math.fsum([areas[0], *(-a for a in areas[1:])])
    if not math.isfinite(area) or area <= 0 or area >= 2*math.pi:
        raise GeometryError('unresolvable or non-hemispherical patch area')
    return geometry, area


def _face_source(source, sphere, names, points, ordered):
    """The atlas whose faces may stand in for _face_geometry, or None.

    _face_geometry reads only a patch's rings, its chart and the registered
    vertex directions. Reuse therefore requires the same sphere, the same sorted
    vertex IDs, byte-identical captured directions and the same patch count;
    _same_face then compares each face. A mismatch here rebuilds every face, a
    mismatch in _same_face rebuilds that face; neither is an error.
    """
    if source is None:
        return None
    if (source.sphere != sphere or source.vertex_ids != names or source._points != points.tobytes()
            or len(source.patches) != len(ordered)):
        return None
    return source


def _same_face(old, new):
    """Same patch ID, same oriented rings and the SAME chart object (not merely equal)."""
    return old.patch_id == new.patch_id and old.rings == new.rings and old.chart is new.chart


def _reused_face(source, face, patch, limits, budget):
    """What _face_geometry returns for this face, taken from an atlas built from identical inputs.

    _face_geometry is a deterministic function of the rings, the chart object and
    the vertex bytes, which _face_source and _same_face require to be identical,
    so the stored geometry and area are its exact result. The rebuild's other
    inputs are applied again unchanged: the two nested build reservations (same
    sizes and categories), so budget refusals and statistics match a rebuild,
    and its only limit-dependent check that the atlas envelope does not already
    imply (closed-ring coordinates against max_vertices, in _validate_shape).
    """
    count = sum(len(ring) for ring in patch.rings)
    with budget.reserve(1024*count+16384, category='spherical-build'):
        with budget.reserve(512*count+8192, category='geometry-build'):
            if count + len(patch.rings) > limits.max_vertices:
                raise GeometryError('result exceeds geometry vertex limit')
    return source.regions[face].geometry, float(source.patch_areas_sr[face])


def _vertex_links(points, edge_array, sides, patch_count, resolution, cancel):
    """Check the geometric link, not just combinatorial edge pairing.

    The left patch of each outgoing tangent must fill exactly the sector up to
    the next tangent's right patch. Every incident patch contributes one corner;
    a double winding, pinch, dangling fan or reversed local sheet is refused.
    """
    rays = [[] for _ in points]
    # Row-wise batch of the former per-ray 3-vector code. Cross products,
    # max/abs, division, the axis=-1 three-term sum and sqrt are elementwise or
    # per-row with the same operation order, so every ray is bit-identical. The
    # two dot products stay one 1-D matmul per row (same BLAS path as before).
    _check_cancel(cancel)
    count = len(edge_array)
    source = np.empty(2*count, dtype=np.intp); target = np.empty(2*count, dtype=np.intp)
    source[0::2] = edge_array[:, 0]; target[0::2] = edge_array[:, 1]
    source[1::2] = edge_array[:, 1]; target[1::2] = edge_array[:, 0]
    radial = points[source]; other = points[target]
    axis = np.eye(3)[np.argmin(np.abs(radial), axis=1)]
    east = unit_rows(np.cross(axis, radial), GeometryError, 'zero or nonfinite direction')
    north = np.cross(radial, east)
    normal = unit_rows(np.cross(radial + other, other - radial), GeometryError, 'zero or nonfinite direction')
    tangent = unit_rows(np.cross(normal, radial), GeometryError, 'zero or nonfinite direction')
    _check_cancel(cancel)
    for k in range(2*count):
        if k % 8192 == 0:
            _check_cancel(cancel)
        t = tangent[k]
        rays[source[k]].append((math.atan2(float(t @ north[k]), float(t @ east[k])),
                                k >> 1, 1 - 2*(k & 1)))
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
    edge_vertices = BoundaryNetwork.edge_vertices
    side_patches = BoundaryNetwork.side_regions
    @property
    def patch_areas_sr(self): return np.frombuffer(self._areas, dtype='f8')
    vertex_count = BoundaryNetwork.vertex_count
    edge_count = BoundaryNetwork.edge_count
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
        if isinstance(indices, np.ndarray):
            if np.ma.isMaskedArray(indices) or indices.ndim != 1 or indices.dtype.kind not in 'iu':
                raise GeometryError('unmasked one-dimensional integer indices required')
        elif any(type(i) is not int for i in indices):
            raise GeometryError('integer edge indices required')
        return np.array(indices, dtype='i8', copy=True)

    def role(self, index):
        i = int(self._indices([index])[0]); l, r = self.side_patches[i]
        return 'patch-seam' if self.patches[l].plate_id == self.patches[r].plate_id else 'interplate'

    @property
    def interplate_edges(self):
        return tuple(i for i, (l, r) in enumerate(self.side_patches)
                     if self.patches[l].plate_id != self.patches[r].plate_id)

    def edge(self, index, *, reverse=False):
        i = int(self._indices([index])[0]); a, b = self.vertex_directions[self.edge_vertices[i]]
        l, r = (self.patches[j] for j in self.side_patches[i])
        role = 'patch-seam' if l.plate_id == r.plate_id else 'interplate'
        out = SharedBoundary(self.edge_ids[i], tuple(a), tuple(b), l.region_id, r.region_id,
                             l.plate_id, r.plate_id, role)
        return out.reversed() if reverse else out

    def adjacency(self, *, by_plate=True):
        names = [p.plate_id if by_plate else p.region_id for p in self.patches]
        return tuple(sorted({tuple(sorted((names[l], names[r]))) for l, r in self.side_patches
                             if names[l] != names[r]}))

    def areas(self, *, by_plate=True):
        groups = {}
        for p, a in zip(self.patches, self.patch_areas_sr):
            name = p.plate_id if by_plate else p.region_id
            groups.setdefault(name, []).append(float(a))
        return {name: (math.fsum(values) * self.sphere.radius_m) * self.sphere.radius_m
                for name, values in sorted(groups.items())}

    def perimeters(self, *, by_plate=True):
        """Count actual owner changes only; internal patch cuts add no coastline."""
        names = [p.plate_id if by_plate else p.region_id for p in self.patches]
        groups = {n: [] for n in names}; points = self.vertex_directions
        for (a, b), (l, r) in zip(self.edge_vertices, self.side_patches):
            if names[l] != names[r]:
                length = float(_angle(points[a], points[b])) * self.sphere.radius_m
                groups[names[l]].append(length); groups[names[r]].append(length)
        return {name: math.fsum(values) for name, values in sorted(groups.items())}

    def junction(self, vertex_index, *, limits=None, budget=None, cancel=None):
        _check_cancel(cancel); limits = _limits(limits)
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
        return self._frames(indices, reverse, fraction, limits, budget, cancel)

    def _frames(self, indices, reverse, fraction, limits, budget, cancel, *, captured=False, emit=True):
        _check_cancel(cancel); limits = _limits(limits)
        f = scalar(fraction, 'fraction', nonnegative=True)
        n = self.edge_count if indices is None else len(indices)
        if n > limits.max_hits: raise GeometryError('frame output exceeds limit')
        with select_budget(budget).reserve(256*n + 1024*min(n, limits.batch_points)+8192,
                                           category='atlas-frames'):
            ids = indices if captured else self._indices(indices)
            p = np.empty((n, 3)); t = np.empty_like(p); normal = np.empty_like(p); length = np.empty(n)
            for start in range(0, n, limits.batch_points):
                _check_cancel(cancel); end = min(n, start+limits.batch_points)
                ab = self.vertex_directions[self.edge_vertices[ids[start:end]]]
                if reverse: ab = ab[:, ::-1]
                a, b = ab[:, 0], ab[:, 1]
                total, difference = a+b, b-a
                left = unit_rows(np.cross(total, difference), GeometryError, 'zero or nonfinite direction')
                theta = sphere.angle_array_from_chords(difference, total)
                radial = a if f == 0 else b if f == 1 else unit_rows(
                    np.cos(f*theta)[:, None]*a + np.sin(f*theta)[:, None]*np.cross(left, a), GeometryError, 'zero or nonfinite direction')
                with np.errstate(over='ignore', invalid='ignore'):
                    p[start:end] = radial*self.sphere.radius_m
                    t[start:end] = unit_rows(np.cross(left, radial), GeometryError, 'zero or nonfinite direction')
                    normal[start:end] = -left; length[start:end] = theta*self.sphere.radius_m
            _check_cancel(cancel)
            if emit:
                return BoundaryFrames((n, 3), p.tobytes(), t.tobytes(), normal.tobytes(), length.tobytes())

    def motion(self, velocities_by_plate, boundary_velocity_m_s, *, indices=None,
               reverse=False, budget=None, cancel=None):
        """Same stage-3 diagnostics on global verified sides, not a force model."""
        _check_cancel(cancel)
        ids = self._indices(self.interplate_edges if indices is None else indices)
        n = len(ids)
        with select_budget(budget).reserve(1024*n+16384, category='atlas-motion'):
            sides = self.side_patches[ids]
            if reverse: sides = sides[:, ::-1]
            def velocity(value):
                return np.broadcast_to(read_array(value, 'velocity'), (n, 3))
            left = np.empty((n, 3)); right = np.empty_like(left)
            groups = {}
            for row, (l, r) in enumerate(sides):
                for col, face in enumerate((l, r)):
                    groups.setdefault(self.patches[face].plate_id, [[], []])[col].append(row)
            for plate, rows in groups.items():
                v = velocity(velocities_by_plate[plate])
                for col, target in enumerate((left, right)):
                    sub = np.asarray(rows[col], dtype='i8'); target[sub] = v[sub]
            boundary = velocity(boundary_velocity_m_s)
            f = self._frames(ids, reverse, 0.5, None, budget, cancel, captured=True)
            with np.errstate(over='ignore', invalid='ignore'):
                relative = right-left
                result = np.column_stack((np.sum(relative*f.right_normal, axis=1),
                    np.sum(relative*f.tangent, axis=1), np.sum((left-boundary)*f.right_normal, axis=1),
                    np.sum((right-boundary)*f.right_normal, axis=1),
                    np.sum(relative*(f.position_m/self.sphere.radius_m), axis=1)))
            _check_cancel(cancel)
            return BoundaryKinematics(tuple(self.edge_ids[i] for i in ids), result.tobytes())

    def index(self, *, limits=None, budget=None):
        return SphericalAtlasIndex(self, limits=limits, budget=budget)

    def local_network(self, patch_id, *, limits=None, budget=None, cancel=None):
        """Stage-3 interoperability: one selected face in its own bounded chart."""
        from atlas_tectonics.plates.boundaries import build_boundary_network
        for p, region in zip(self.patches, self.regions):
            if p.patch_id == patch_id:
                return build_boundary_network(region.geometry, (region,), limits=limits, budget=budget, cancel=cancel)
        raise GeometryError('unknown patch')

    def __reduce__(self):
        return (_restore_atlas, (self.descriptor(), self._points))

    __deepcopy__ = _immutable_deepcopy


def build_spherical_atlas(sphere, vertices, patches, *, limits=None, budget=None, cancel=None,
                          angular_resolution_rad=_ANGULAR_RESOLUTION, source_bindings=None,
                          reuse_faces_from=None, _restored=False):
    """Validate and join a complete conforming spherical partition.

    ``vertices`` maps globally shared IDs to directions in sphere.frame_id. Each
    ID has ONE authoritative position, normalised once during capture. Duplicate
    geometric vertices under different IDs are refused, not welded. Every vertex
    must be used; all face edges must match in opposite directions by exact IDs.
    ``angular_resolution_rad`` controls rejection of ambiguous geometry; it does
    not fill missing faces or move coordinates. No user-selected area tolerance.

    ``reuse_faces_from`` optionally names an existing SphericalAtlas over the same
    vertex registry, typically the same faces with new region/plate owners. A
    face whose patch ID, rings and chart object match, with byte-identical vertex
    directions, takes its local polygon and area from that atlas instead of
    recomputing them from identical inputs. Every other check and identity is
    computed as without it, so the result is the same atlas either way.
    """
    _check_cancel(cancel); limits = _limits(limits); policy = select_budget(budget)
    count = sum(len(ring) for p in patches for ring in p.rings)
    if len(vertices) < 4 or len(vertices) > limits.max_vertices or count > limits.max_vertices:
        raise GeometryError('atlas vertex/half-edge envelope exceeded')
    resolution = scalar(angular_resolution_rad, 'angular resolution', positive=True)
    if resolution < _ANGULAR_RESOLUTION or resolution > 1e-6:
        raise GeometryError('unsupported spherical ambiguity resolution')
    bindings = {} if source_bindings is None else source_bindings
    try: provenance = _json(bindings)
    except (TypeError, ValueError, OverflowError) as exc: raise GeometryError('invalid source-binding provenance') from exc
    with policy.reserve(4096*count + 1024*len(vertices) + 2*len(provenance)+65536, category='atlas-build'):
        for name in vertices: _label(name, 'vertex ID')
        names = tuple(sorted(vertices)); lookup = {name: i for i, name in enumerate(names)}
        data = []
        for name in names:
            data.append(read_array(vertices[name], 'vertex'))
        points = np.asarray(data, dtype='f8'); del data
        if _restored:
            if np.any(np.abs(np.linalg.norm(points, axis=1)-1) > 16*np.finfo(float).eps):
                raise GeometryError('saved atlas vertices are not unit directions')
        else: points = _capture_directions(points)
        ordered = tuple(sorted(patches, key=lambda p: p.patch_id))
        reused = _face_source(reuse_faces_from, sphere, names, points, ordered)
        owners, edge_uses, used, geometry, areas = {}, {}, set(), [], []
        for face, p in enumerate(ordered):
            _check_cancel(cancel)
            owners[p.region_id] = p.plate_id
            for ring in p.rings:
                used.update(ring)
                ids = [lookup[v] for v in ring]
                # One row-wise _angle per ring. Row i is the same elementwise IEEE
                # arithmetic and length-3 reduction as _angle(points[a], points[b])
                # for its pair, so every theta and the check order are unchanged.
                index = np.asarray(ids, dtype=np.intp)
                thetas = _angle(points[index], points[np.roll(index, -1)]).tolist()
                for (a, b), theta in zip(zip(ids, ids[1:] + ids[:1]), thetas):
                    if theta <= resolution or theta >= math.pi-resolution:
                        raise GeometryError('zero, unresolved or antipodal spherical edge')
                    key = (min(a, b), max(a, b))
                    row = edge_uses.setdefault(key, [-1, -1])
                    column = 0 if a < b else 1
                    row[column] = face
            if reused is not None and _same_face(reused.patches[face], p):
                g, area = _reused_face(reused, face, p, limits, policy)
            else:
                g, area = _face_geometry(p, points, lookup, limits, policy)
            geometry.append(BoundaryRegion(p.patch_id, p.plate_id, g)); areas.append(area)
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
        chi = len(names)-len(edges)+sum(1-len(p.holes) for p in ordered)
        offsets, incidence = _vertex_links(points, edges, sides, len(ordered), resolution, cancel)
        area_sum = math.fsum(areas)
        if abs(area_sum-4*math.pi) > _AREA_TOLERANCE_SR:
            raise GeometryError('spherical area closure failed; no normalisation of areas allowed')
        sphere_record = sphere.descriptor()
        patch_records, charts = [], []
        for patch in ordered:
            description = patch.descriptor()
            charts.append(description.pop('chart'))
            patch_records.append(description)
        intrinsic = {'schema': _SCHEMA, 'method': _METHOD, 'sphere': sphere_record, 'vertices': list(names),
                     'patches': patch_records}
        point_bytes = points.tobytes()
        digest = hashlib.sha256(_json(intrinsic))
        digest.update(b'\0')
        digest.update(point_bytes)
        geometry_id = digest.hexdigest()
        context = {'geometry_id': geometry_id, 'charts': charts,
                   'resolution': resolution, 'bindings': bindings}
        identifier = _digest(content_record(context))
        edge_ids = tuple(_digest({'schema': 'atlas.global-edge.v1', 'sphere': sphere_record,
                                 'ends': [points[a].tolist(), points[b].tolist()],
                                 'regions': [ordered[l].region_id, ordered[r].region_id],
                                 'plates': [ordered[l].plate_id, ordered[r].plate_id]})
                         for (a, b), (l, r) in zip(edges, sides))
        obj = object.__new__(SphericalAtlas)
        values = {'sphere': sphere, 'patches': ordered, 'vertex_ids': names, 'edge_ids': edge_ids,
                  'regions': tuple(geometry), 'atlas_id': identifier, 'geometry_id': geometry_id,
                  '_points': point_bytes, '_edges': edges.tobytes(), '_sides': sides.tobytes(),
                  '_areas': np.asarray(areas, dtype='f8').tobytes(), '_offsets': offsets.tobytes(),
                  '_incidence': incidence.tobytes(), '_provenance': provenance, '_resolution': resolution,
                  '_stats': _json({'patches': len(ordered), 'vertices': len(names), 'edges': len(edges),
                                  'euler_characteristic': chi, 'area_steradians': area_sum,
                                  'area_residual_sr': area_sum-4*math.pi, 'unpaired_edges': 0,
                                  'topology_halfedges': count, 'global_dense_pair_matrix': False})}
        for key, value in values.items(): object.__setattr__(obj, key, value)
        obj._frames(None, False, 0.5, limits, policy, cancel, emit=False)
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
        object.__setattr__(self, name, value)

    def __init__(self, atlas, *, limits=None, budget=None):
        from scipy.spatial import cKDTree
        import threading
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
                candidate = unit_rows(np.array([math.fsum(points[:,j]) for j in range(3)]), GeometryError, 'zero or nonfinite direction')
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

    _close_refusal = 'join active queries before closing atlas index'
    close = GeometryIndex.close

    def query(self, directions, *, by_plate=True, angular_tolerance_rad=_ANGULAR_RESOLUTION,
              budget=None, cancel=None):
        _check_cancel(cancel)
        tol = scalar(angular_tolerance_rad, 'angular tolerance', nonnegative=True)
        if any(tol >= p.chart.min_cosine/4 for p in self._atlas.patches):
            raise GeometryError('boundary band exceeds chart validity')
        with self._lock:
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
                    seen = np.zeros(len(block),dtype=bool)
                    for face, selected in sorted(candidates.items()):
                        selected = np.asarray(selected,dtype='i8')
                        result = self._atlas.regions[face].geometry.classify(block[selected],
                            angular_tolerance_rad=tol,limits=self.limits,budget=policy,cancel=cancel)
                        hit = selected[result >= 0]; seen[hit] = True
                        if len(rows)+len(hit)>limit: raise GeometryError('atlas query output exceeds max_hits; use smaller batches')
                        rows.extend((start+int(i),owners[face]) for i in hit)
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
    limits = _limits(limits)
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
    _check_cancel(cancel)
    return store.put(atlas.atlas_id, {'directions': atlas.vertex_directions}, atlas.descriptor(),
                     budget=budget,cancel=cancel)


def load_spherical_atlas(store, atlas_id, *, limits=None, budget=None, cancel=None):
    require_sha256(atlas_id, GeometryError, 'lowercase SHA256 identity required'); _check_cancel(cancel)
    values=store.get(atlas_id,budget=budget)
    if values is None: return None
    desc=store.metadata(atlas_id)
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
    sphere = next(iter(networks.values())).domain.chart.sphere
    total = sum(n.vertex_count + n.edge_count for n in networks.values())
    if total > limits.max_vertices or len(vertices) > limits.max_vertices:
        raise GeometryError('source network or registry envelope exceeded')
    provided = {} if region_bindings is None else region_bindings
    with policy.reserve(4096*total+65536, category='atlas-stitch'):
        canonical = {}
        for name, value in vertices.items():
            _label(name, 'shared vertex')
            canonical[name] = _capture_directions(read_array(value, 'registered direction'))
        patches, sources, candidates = [], [], 0
        for name, network in sorted(networks.items()):
            _check_cancel(cancel); _label(name, 'network name')
            binding = vertex_bindings[name]
            original = unit_rows(network.domain.chart._unproject(network.vertex_xy), GeometryError, 'zero or nonfinite direction')
            mapped = np.array([canonical[v] for v in binding])
            errors = _angle(original, mapped)
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
                                    j,k=k,j
                                pieces.append(((network.vertex_xy[j,axis]-a[axis])/direction[axis],j,k))
                            pieces.sort()
                            for _, j, k in pieces:
                                if not path: path.append(j)
                                path.append(k)
                        ring_ids.append(tuple(binding[i] for i in path[:-1]))
                    patch_id = 'patch-'+_digest((name,region.region_id,component))[:32]
                    patches.append(SphericalPatch(patch_id,provided.get((name,region.region_id),region.region_id),
                        region.plate_id,ring_ids[0],network.domain.chart,tuple(ring_ids[1:])))
        # Reuse the captured unit directions without a second normalisation step.
        return build_spherical_atlas(sphere,canonical,tuple(patches),limits=limits,budget=policy,
            cancel=cancel,source_bindings={'networks':sources, 'attachment_band_rad':_ANGULAR_RESOLUTION,
                                         'candidate_segments':candidates},_restored=True)
