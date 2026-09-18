"""W01 stage 3: static, oriented shared boundaries from verified area coverage.

A boundary segment is stored once with its left/right REGION indices. Regions
carry separate plate IDs: a join between patches of one plate is not a tectonic
boundary. Domain-exterior sides are explicit (-1), never an invented plate.

Polygon rings are oriented with occupied material to their left (CCW shells,
CW holes). Native noding inserts existing intersections/vertices and removes
coincident duplicate segments. Side attribution uses those directed source
segments, NOT epsilon-offset sample points, nearest owners, snapping or repair.
A spherical network uses one explicitly conditioned gnomonic domain chart for
connectivity only; frames and lengths are evaluated in sphere Cartesian axes.
No whole-sphere stitching, plate evolution or force/polarity inference is claimed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import math
from typing import Any, Mapping

import numpy as np
import shapely
from shapely.errors import GEOSException
from shapely.geometry import LineString, MultiLineString
from shapely.strtree import STRtree

from ._validation import read_array, scalar, input_shape
from .resources import elements, select_budget
from .geometry import (GeometryError, GeometryLimits, PlanarGeometry, _limits,
                       _label, _json, _typed_frozen, _check_cancel, _point_shape)
from .spherical_geometry import SphericalGeometry, SphericalChart

_SCHEMA = 'atlas.shared-boundaries.v1'
_METHOD = 'oriented-rings-native-noding-binary64-v1'


@dataclass(frozen=True, slots=True)
class BoundaryRegion:
    """A polygonal ownership region; region identity is distinct from plate ID."""
    region_id: str
    plate_id: str
    geometry: PlanarGeometry | SphericalGeometry

    def __post_init__(self):
        _label(self.region_id, 'region ID'); _label(self.plate_id, 'plate ID')
        if type(self.geometry) not in (PlanarGeometry, SphericalGeometry):
            raise GeometryError('explicit supported region geometry required')
        if self.geometry.is_empty or self.geometry.kind not in ('Polygon', 'MultiPolygon'):
            raise GeometryError('boundary owners must have nonempty polygonal area')


def _shape(g):
    return g._projected._geom if type(g) is SphericalGeometry else g._geom


def _to_chart(g, domain, limits, budget):
    if type(g) is not type(domain):
        raise GeometryError('boundary geometry must use one space')
    if type(domain) is SphericalGeometry:
        # Explicitly use the declared domain chart, not an automatically selected
        # projection. Reprojection may reveal a tiny gap; never snap it closed.
        return g.in_chart(domain.chart, limits=limits, budget=budget)
    if g.frame_id != domain.frame_id:
        raise GeometryError('boundary geometry frame mismatch')
    return g


def _polygon_parts(g):
    if g.geom_type == 'Polygon':
        yield g
    else:
        yield from g.geoms


def _point_key(value):
    # Signed zero denotes the same geometric location; the input geometry IDs
    # still preserve their original bytes. This is not coordinate quantisation.
    return tuple(0. if x == 0 else float(x) for x in value)


def _unit_rows(a):
    a = np.asarray(a, dtype=np.float64)
    scale = np.max(np.abs(a), axis=-1, keepdims=True)
    if not np.isfinite(scale).all() or np.any(scale == 0):
        raise GeometryError('direction is zero or outside numerical range')
    scaled = a / scale
    return scaled / np.sqrt(np.sum(scaled * scaled, axis=-1, keepdims=True))


def _direction(a, b):
    with np.errstate(over='ignore', invalid='ignore'):
        return _unit_rows(np.asarray(b) - np.asarray(a))


def _sha(value):
    if (type(value) is not str or len(value) != 64 or
            any(c not in '0123456789abcdef' for c in value)):
        raise GeometryError('lowercase SHA256 identity required')
    return value


@dataclass(frozen=True, slots=True)
class SharedBoundary:
    """One directed view. Reversal keeps the geometric ID and swaps both sides.

    Coordinates are metres for a plane, unit directions for a sphere. This is a
    view of an atomic segment, not a velocity or a constitutive fault/slab model.
    """
    boundary_id: str
    start: tuple[float, ...]
    end: tuple[float, ...]
    left_region_id: str | None
    right_region_id: str | None
    left_plate_id: str | None
    right_plate_id: str | None
    role: str
    orientation: int = 1

    def reversed(self):
        return SharedBoundary(self.boundary_id, self.end, self.start,
            self.right_region_id, self.left_region_id, self.right_plate_id,
            self.left_plate_id, self.role, -self.orientation)


@dataclass(frozen=True, slots=True)
class BoundaryJunction:
    """Incident outgoing half-edges in counter-clockwise cyclic order.

    signs tells whether the outgoing ray agrees with the stored edge direction.
    sectors[k] is the region between ray k and the next CCW ray; None is outside.
    Point contacts are distinct from positive-length shared-boundary adjacency.
    Ordinary polygon corners are vertices but not tectonic triple junctions.
    """
    vertex_id: str
    position: tuple[float, ...]
    edge_indices: tuple[int, ...]
    signs: tuple[int, ...]
    sector_region_ids: tuple[str | None, ...]
    contact_region_pairs: tuple[tuple[str, str], ...]
    @property
    def degree(self): return len(self.edge_indices)


@dataclass(frozen=True, slots=True)
class BoundaryFrames:
    """Detached immutable batch of metric positions and orthonormal frames."""
    _shape: tuple[int, int]
    _points: bytes = field(repr=False)
    _tangents: bytes = field(repr=False)
    _normals: bytes = field(repr=False)
    _lengths: bytes = field(repr=False)
    @property
    def position_m(self): return np.frombuffer(self._points, dtype='f8').reshape(self._shape)
    @property
    def tangent(self): return np.frombuffer(self._tangents, dtype='f8').reshape(self._shape)
    @property
    def right_normal(self): return np.frombuffer(self._normals, dtype='f8').reshape(self._shape)
    @property
    def length_m(self): return np.frombuffer(self._lengths, dtype='f8')


@dataclass(frozen=True, slots=True)
class BoundaryKinematics:
    """Rows: opening, tangential, left-normal-in-boundary-frame,
    right-normal-in-boundary-frame, relative-radial velocity (all m/s).

    The radial column is zero on a plane. On a sphere it is reported, not silently
    discarded or interpreted as admissible 1D transport. No inferred slip law.
    """
    boundary_ids: tuple[str, ...]
    _values: bytes = field(repr=False)
    @property
    def values_m_s(self): return np.frombuffer(self._values, dtype='f8').reshape(-1, 5)
    @property
    def opening_m_s(self): return self.values_m_s[:, 0]
    @property
    def tangential_m_s(self): return self.values_m_s[:, 1]


@dataclass(frozen=True, slots=True, init=False)
class BoundaryNetwork:
    """Immutable, reusable static network with compact edge/incidence arrays.

    Build through build_boundary_network(). Construction/query workspace uses the
    shared WorkBudget. The owner must reserve retained_bytes_estimate while holding
    this object; native GEOS/STRtree memory is estimated, not an enforced heap cap.
    No process-global cache is created. Pickle/storage restoration rebuilds derived
    geometry and verifies network identity instead of trusting serialised indexes.
    IDs identify this static definition, not permanent geological boundary labels.
    """
    domain: PlanarGeometry | SphericalGeometry
    regions: tuple[BoundaryRegion, ...]
    network_id: str
    edge_ids: tuple[str, ...]
    vertex_ids: tuple[str, ...]
    _vertices: bytes = field(repr=False)
    _edges: bytes = field(repr=False)
    _sides: bytes = field(repr=False)
    _offsets: bytes = field(repr=False)
    _incidence: bytes = field(repr=False)
    _region_offsets: bytes = field(repr=False)
    _region_uses: bytes = field(repr=False)
    _shapes: Any = field(repr=False, compare=False)
    _tree: Any = field(repr=False, compare=False)
    _construction: bytes = field(repr=False)

    def __init__(self, *args, **kwargs):
        raise GeometryError('use build_boundary_network()')

    @property
    def spherical(self): return type(self.domain) is SphericalGeometry
    @property
    def region_ids(self): return tuple(r.region_id for r in self.regions)
    @property
    def plate_ids(self): return tuple(r.plate_id for r in self.regions)
    @property
    def vertex_xy(self):
        """Native topology coordinates: m in a plane, dimensionless in a chart."""
        return np.frombuffer(self._vertices, dtype='f8').reshape(-1, 2)
    @property
    def edge_vertices(self): return np.frombuffer(self._edges, dtype='i8').reshape(-1, 2)
    @property
    def side_regions(self):
        """Left/right region indices; -1 explicitly denotes outside the domain."""
        return np.frombuffer(self._sides, dtype='i8').reshape(-1, 2)
    @property
    def edge_count(self): return len(self.edge_ids)
    @property
    def vertex_count(self): return len(self.vertex_ids)
    @property
    def nbytes(self):
        return sum(map(len, (self._vertices, self._edges, self._sides,
                              self._offsets, self._incidence, self._region_offsets,
                              self._region_uses, self._construction)))
    @property
    def retained_bytes_estimate(self):
        # Immutable domain/region geometry may be shared elsewhere: count it once
        # at the owning application, not again for every reference to this network.
        return self.nbytes + 768*self.edge_count + 256*self.vertex_count + 4096
    @property
    def statistics(self):
        import json
        return json.loads(self._construction)

    def _indices(self, indices, *, max_count=None):
        if indices is None:
            return np.arange(self.edge_count, dtype=np.int64)
        if type(indices) not in (tuple, list, np.ndarray):
            raise GeometryError('explicit edge indices required')
        if isinstance(indices, np.ndarray) and indices.ndim != 1:
            raise GeometryError('one-dimensional edge indices required')
        if max_count is not None and len(indices) > max_count:
            raise GeometryError('edge query exceeds declared output limit')
        if isinstance(indices, np.ndarray):
            if np.ma.isMaskedArray(indices) or indices.ndim != 1 or indices.dtype.kind not in 'iu':
                raise GeometryError('unmasked integer edge indices required')
            if indices.dtype.kind == 'u' and np.any(indices > np.iinfo(np.int64).max):
                raise GeometryError('edge index out of range')
        elif any(type(i) is not int for i in indices):
            raise GeometryError('integer edge indices required')
        ids = np.array(indices, dtype=np.int64, copy=True)
        if ids.ndim != 1 or np.any(ids < 0) or np.any(ids >= self.edge_count):
            raise GeometryError('edge index out of range')
        return ids

    def role(self, edge_index):
        i = int(self._indices([edge_index])[0]); left, right = self.side_regions[i]
        if left < 0 or right < 0: return 'exterior'
        return 'patch-seam' if self.regions[left].plate_id == self.regions[right].plate_id else 'interplate'

    @property
    def interplate_edges(self):
        return tuple(i for i, (l, r) in enumerate(self.side_regions)
                     if l >= 0 and r >= 0 and self.regions[l].plate_id != self.regions[r].plate_id)

    def edge(self, edge_index, *, reverse=False):
        if type(reverse) is not bool: raise GeometryError('reverse must be bool')
        i = int(self._indices([edge_index])[0]); xy = self.vertex_xy[self.edge_vertices[i]]
        points = self.domain.chart._unproject(xy) if self.spherical else xy
        l, r = self.side_regions[i]
        lr = self.regions[l] if l >= 0 else None; rr = self.regions[r] if r >= 0 else None
        out = SharedBoundary(self.edge_ids[i], tuple(points[0]), tuple(points[1]),
            None if lr is None else lr.region_id, None if rr is None else rr.region_id,
            None if lr is None else lr.plate_id, None if rr is None else rr.plate_id, self.role(i))
        return out.reversed() if reverse else out

    def uses(self, region_id):
        """(edge index, orientation) pairs with this region always on the left."""
        if region_id not in self.region_ids: raise GeometryError('unknown region')
        i = self.region_ids.index(region_id)
        offsets = np.frombuffer(self._region_offsets, dtype='i8')
        uses = np.frombuffer(self._region_uses, dtype='i8').reshape(-1, 2)
        return tuple((int(e), int(sign)) for e, sign in uses[offsets[i]:offsets[i+1]])

    def adjacency(self, *, by_plate=True):
        if type(by_plate) is not bool: raise GeometryError('by_plate must be bool')
        out = set()
        for l, r in self.side_regions:
            if l < 0 or r < 0: continue
            a, b = self.regions[l], self.regions[r]
            pair = (a.plate_id, b.plate_id) if by_plate else (a.region_id, b.region_id)
            if pair[0] != pair[1]: out.add(tuple(sorted(pair)))
        return tuple(sorted(out))

    def junction(self, vertex_index, *, limits=None, budget=None, cancel=None):
        _check_cancel(cancel); limits = _limits(limits)
        if type(vertex_index) is not int or not 0 <= vertex_index < self.vertex_count:
            raise GeometryError('vertex index out of range')
        offsets = np.frombuffer(self._offsets, dtype='i8')
        incidence = np.frombuffer(self._incidence, dtype='i8').reshape(-1, 2)
        rows = incidence[offsets[vertex_index]:offsets[vertex_index+1]]
        if len(rows)**2 > limits.max_overlay_pairs:
            raise GeometryError('junction contact-pair envelope exceeded')
        with select_budget(budget).reserve(512*len(rows)**2+8192, category='boundary-junction'):
            return self._junction_record(vertex_index, rows, cancel)

    def _junction_record(self, vertex_index, rows, cancel):
        sectors = []; present = set(); adjacent_here = set()
        for edge, sign in rows:
            l, r = self.side_regions[edge]
            if sign < 0: l, r = r, l
            sectors.append(None if l < 0 else self.regions[l].region_id)
            if l >= 0: present.add(int(l))
            if r >= 0: present.add(int(r))
            if l >= 0 and r >= 0: adjacent_here.add(tuple(sorted((int(l), int(r)))))
        contacts = []
        ordered = sorted(present)
        for pos, a in enumerate(ordered):
            _check_cancel(cancel)
            for b in ordered[pos+1:]:
                if (a, b) not in adjacent_here:
                    contacts.append((self.regions[a].region_id, self.regions[b].region_id))
        xy = self.vertex_xy[vertex_index]
        position = self.domain.chart._unproject(xy[None, :])[0] if self.spherical else xy
        _check_cancel(cancel)
        return BoundaryJunction(self.vertex_ids[vertex_index], tuple(position),
            tuple(int(e) for e, s in rows), tuple(int(s) for e, s in rows),
            tuple(sectors), tuple(contacts))

    def frames(self, indices=None, *, reverse=False, fraction=0.5, limits=None, budget=None, cancel=None):
        """Frames on directed atomic edges. Spherical normals point tangentially right.

        fraction is arc-length fraction on spheres, not planar chart fraction.
        Frames at vertices belong to the selected edge, never an averaged junction.
        """
        _check_cancel(cancel); limits = _limits(limits)
        if type(reverse) is not bool: raise GeometryError('reverse must be bool')
        f = scalar(fraction, 'edge fraction', nonnegative=True)
        if f > 1: raise GeometryError('fraction must be in [0,1]')
        if indices is not None and type(indices) not in (tuple, list, np.ndarray):
            raise GeometryError('explicit edge indices required')
        if isinstance(indices, np.ndarray) and indices.ndim != 1:
            raise GeometryError('one-dimensional edge indices required')
        n = self.edge_count if indices is None else len(indices)
        if n > limits.max_hits: raise GeometryError('edge query exceeds max_hits')
        dim = 3 if self.spherical else 2
        with select_budget(budget).reserve(256*n + 1024*min(n, limits.batch_points)+8192, category='boundary-frames'):
            ids = self._indices(indices, max_count=limits.max_hits)
            positions = np.empty((n, dim)); tangents = np.empty_like(positions)
            normals = np.empty_like(positions); lengths = np.empty(n)
            for start in range(0, n, limits.batch_points):
                _check_cancel(cancel); stop = min(start+limits.batch_points, n)
                xy = self.vertex_xy[self.edge_vertices[ids[start:stop]]]
                if reverse: xy = xy[:, ::-1]
                if self.spherical:
                    ab = self.domain.chart._unproject(xy); a, b = ab[:, 0], ab[:, 1]
                    # Stable short-arc normal: cross(a+b,b-a)=2 cross(a,b).
                    normal_left = _unit_rows(np.cross(a+b, b-a))
                    theta = 2*np.arctan2(np.linalg.norm(a-b, axis=1), np.linalg.norm(a+b, axis=1))
                    if np.any(theta <= 0) or np.any(theta >= math.pi):
                        raise GeometryError('unresolvable or antipodal boundary arc')
                    if f == 0: radial = a
                    elif f == 1: radial = b
                    else:
                        initial = np.cross(normal_left, a)
                        radial = _unit_rows(np.cos(f*theta)[:, None]*a + np.sin(f*theta)[:, None]*initial)
                    tangents[start:stop] = _unit_rows(np.cross(normal_left, radial))
                    normals[start:stop] = -normal_left
                    with np.errstate(over='ignore', invalid='ignore'):
                        positions[start:stop] = radial*self.domain.chart.sphere.radius_m
                        lengths[start:stop] = theta*self.domain.chart.sphere.radius_m
                else:
                    a, b = xy[:, 0], xy[:, 1]
                    with np.errstate(over='ignore', invalid='ignore'):
                        d = b-a
                    t = _unit_rows(d)
                    tangents[start:stop] = t
                    normals[start:stop] = np.column_stack((t[:, 1], -t[:, 0]))
                    with np.errstate(over='ignore', invalid='ignore'):
                        positions[start:stop] = (1-f)*a + f*b
                        lengths[start:stop] = np.hypot(d[:, 0], d[:, 1])
            if any(not np.isfinite(x).all() for x in (positions, tangents, normals, lengths)) or np.any(lengths <= 0):
                raise GeometryError('boundary metric outside numerical range')
            _check_cancel(cancel)
            return BoundaryFrames((n, dim), positions.tobytes(), tangents.tobytes(), normals.tobytes(), lengths.tobytes())

    def motion(self, velocities_by_plate: Mapping[str, Any], boundary_velocity_m_s, *,
               indices=None, reverse=False, budget=None, cancel=None):
        """Project supplied velocities using verified sides; no motion is generated.

        Default rows are interplate edges, not exterior or same-plate patch joins.
        Each named plate supplies one constant vector or one vector per selected
        edge midpoint in the NETWORK axes (m/s). Boundary velocity is explicit.
        """
        _check_cancel(cancel)
        if not isinstance(velocities_by_plate, Mapping): raise GeometryError('plate velocity mapping required')
        selected_ids = self.interplate_edges if indices is None else indices
        if type(selected_ids) not in (tuple, list, np.ndarray) or (isinstance(selected_ids,np.ndarray) and selected_ids.ndim != 1):
            raise GeometryError('one-dimensional edge selection required')
        n = len(selected_ids); dim = 3 if self.spherical else 2
        if n > self.edge_count: raise GeometryError('motion selection must not duplicate edges')
        if type(reverse) is not bool: raise GeometryError('reverse must be bool')
        with select_budget(budget).reserve(1024*n+16384, category='boundary-motion'):
            ids = self._indices(selected_ids)
            if len(np.unique(ids)) != n: raise GeometryError('motion selection must not duplicate edges')
            sides = self.side_regions[ids]
            if reverse: sides = sides[:, ::-1]
            if np.any(sides < 0): raise GeometryError('exterior-side motion needs a separately specified exterior model')
            def velocity(value):
                if input_shape(value, 'velocity') not in ((dim,), (n, dim)):
                    raise GeometryError('velocity must match selected edge coordinates')
                a = read_array(value, 'velocity')
                if a.shape not in ((dim,), (n, dim)):
                    raise GeometryError('velocity must be a vector or one vector per selected edge')
                return np.broadcast_to(a, (n, dim))
            names = sorted({self.regions[int(x)].plate_id for x in sides.flat})
            if not set(names) <= set(velocities_by_plate): raise GeometryError('missing velocity for a verified plate owner')
            left = np.empty((n, dim)); right = np.empty_like(left)
            # Build sparse owner groups in one pass. Do not scan every edge once
            # for every plate (quadratic for finely partitioned regional models).
            groups = {plate: [[], []] for plate in names}
            for row, (l, r) in enumerate(sides):
                groups[self.regions[l].plate_id][0].append(row)
                groups[self.regions[r].plate_id][1].append(row)
            for plate in names:
                v = velocity(velocities_by_plate[plate])
                for column, target in ((0, left), (1, right)):
                    selected = np.asarray(groups[plate][column], dtype=np.int64)
                    target[selected] = v[selected]
            boundary = velocity(boundary_velocity_m_s)
            frames = self.frames(ids, reverse=reverse, budget=budget, cancel=cancel)
            with np.errstate(over='ignore', invalid='ignore'):
                relative = right-left; normal = frames.right_normal; tangent = frames.tangent
                out = np.column_stack((np.sum(relative*normal, axis=1), np.sum(relative*tangent, axis=1),
                    np.sum((left-boundary)*normal, axis=1), np.sum((right-boundary)*normal, axis=1), np.zeros(n)))
                if self.spherical:
                    radial = frames.position_m/self.domain.chart.sphere.radius_m
                    out[:, 4] = np.sum(relative*radial, axis=1)
            if not np.isfinite(out).all(): raise GeometryError('boundary velocity outside numerical range')
            _check_cancel(cancel)
            return BoundaryKinematics(tuple(self.edge_ids[i] for i in ids), out.tobytes())

    def validate_trace(self, trace, *, left_region_id, right_region_id, limits=None, budget=None, cancel=None):
        """Verify a directed trace lies on the claimed shared sides.

        Returns unique (edge index, orientation) uses in trace order. Partial-edge
        traces are allowed; off-network pieces, branching/multipart traces and
        wrong side declarations are refused. An input is never snapped to a seam.
        """
        _check_cancel(cancel); limits = _limits(limits)
        if type(trace) is not type(self.domain) or trace.kind != 'LineString' or trace.is_empty:
            raise GeometryError('one explicit directed trace in the network space required')
        names = self.region_ids
        if any(x is not None and x not in names for x in (left_region_id, right_region_id)):
            raise GeometryError('unknown declared boundary owner')
        t = _to_chart(trace, self.domain, limits, budget); g = _shape(t)
        if t.vertex_count > limits.max_vertices:
            raise GeometryError('trace exceeds vertex limit')
        with select_budget(budget).reserve(1024*(self.edge_count+t.vertex_count)+16384, category='boundary-trace'):
            found = []; queries = 0
            for segment_no, (a, b) in enumerate(zip(np.asarray(g.coords)[:-1], np.asarray(g.coords)[1:])):
                _check_cancel(cancel); segment = LineString((a, b)); pieces = []
                candidates = self._tree.query(segment); queries += len(candidates)
                if queries > limits.max_overlay_pairs: raise GeometryError('trace candidate limit exceeded')
                for i in sorted(map(int, candidates)):
                    inter = shapely.intersection(segment, self._shapes[i], grid_size=0.)
                    if inter.is_empty or inter.length == 0: continue
                    if inter.geom_type not in ('LineString', 'MultiLineString'):
                        raise GeometryError('ambiguous trace intersection')
                    xy = self.vertex_xy[self.edge_vertices[i]]
                    sign = 1 if float(np.dot(_direction(a, b), _direction(*xy))) > 0 else -1
                    l, r = self.side_regions[i]
                    if sign < 0: l, r = r, l
                    actual = (None if l < 0 else names[l], None if r < 0 else names[r])
                    if actual != (left_region_id, right_region_id):
                        raise GeometryError('trace direction/side declaration disagrees with geometry')
                    pieces.append(inter)
                    distance = float(segment.project(inter.representative_point()))
                    found.append((segment_no, distance, i, sign))
                if not pieces or not segment.difference(shapely.union_all(pieces, grid_size=0.)).is_empty:
                    raise GeometryError('trace has off-network or numerically unresolved pieces')
            # Per-segment queries are stable; global ordering follows the original
            # segment/overlap measure, not the arbitrary STRtree enumeration order.
            ordered = []
            for _, _, i, sign in sorted(found, key=lambda x: (x[0], x[1], x[2])):
                if not ordered or ordered[-1] != (i, sign): ordered.append((i, sign))
            _check_cancel(cancel)
            return tuple(ordered)

    def descriptor(self):
        return {'schema': _SCHEMA, 'method': _METHOD, 'domain': self.domain.descriptor(),
                'regions': [{'region_id': r.region_id, 'plate_id': r.plate_id,
                             'geometry': r.geometry.descriptor()} for r in self.regions],
                'network_id': self.network_id}

    def __reduce__(self): return (_restore_network, (self.domain, self.regions, self.network_id))
    def __deepcopy__(self, memo): memo[id(self)] = self; return self


def _restore_network(domain, regions, expected):
    out = build_boundary_network(domain, regions)
    if out.network_id != expected: raise GeometryError('restored boundary-network identity mismatch')
    return out


def build_boundary_network(domain, regions, *, limits=None, budget=None, cancel=None):
    """Build complete static coverage, oriented atomic edges and cyclic junctions.

    Regions may use distinct spherical charts only if they can be expressed in the
    explicit domain chart AND exact native coverage/side checks succeed. Floating
    reprojection slivers are refused, not reconciled with a widening tolerance.
    A genuinely whole-sphere/multi-domain seam graph is a later geometry extension.
    """
    _check_cancel(cancel); limits = _limits(limits); policy = select_budget(budget)
    if type(domain) not in (PlanarGeometry, SphericalGeometry) or domain.is_empty or domain.kind not in ('Polygon', 'MultiPolygon'):
        raise GeometryError('explicit nonempty polygonal domain required')
    if type(regions) not in (tuple, list) or not regions or any(type(r) is not BoundaryRegion for r in regions):
        raise GeometryError('explicit nonempty BoundaryRegion sequence required')
    regions = tuple(sorted(regions, key=lambda r: r.region_id))
    if len({r.region_id for r in regions}) != len(regions): raise GeometryError('duplicate region ID')
    vertex_count = domain.vertex_count + sum(r.geometry.vertex_count for r in regions)
    if vertex_count > limits.max_vertices: raise GeometryError('boundary input vertex limit exceeded')
    with policy.reserve(2048*vertex_count+16384, category='boundary-build'):
        aligned = [_to_chart(r.geometry, domain, limits, policy) for r in regions]
        shapes = [_shape(g) for g in aligned]; domain_shape = _shape(domain)
        region_tree = STRtree(shapes); region_pairs = 0
        for i, g in enumerate(shapes):
            _check_cancel(cancel)
            if not domain_shape.covers(g): raise GeometryError('region lies outside the declared domain')
            for j in region_tree.query(g):
                j = int(j)
                if j <= i: continue
                region_pairs += 1
                if region_pairs > limits.max_overlay_pairs: raise GeometryError('region candidate limit exceeded')
                if shapely.relate_pattern(g, shapes[j], 'T********'):
                    raise GeometryError('region interiors overlap; ownership cannot be inferred')
        # This is coverage validation, never a replacement for the original regions.
        union = shapely.union_all(shapes, grid_size=0.)
        if not domain_shape.equals(union): raise GeometryError('gap or unresolved coverage: no snapping/repair permitted')
        lines = []; owners = []; vectors = []
        for owner, g in enumerate(shapes):
            oriented = shapely.orient_polygons(g, exterior_cw=False)
            for polygon in _polygon_parts(oriented):
                for ring in (polygon.exterior, *polygon.interiors):
                    xy = np.asarray(ring.coords)
                    for a, b in zip(xy[:-1], xy[1:]):
                        lines.append(LineString((a, b))); owners.append(owner); vectors.append(_direction(a, b))
        tree = STRtree(lines); candidates = 0
        # Conservative pre-admission for arrangement growth using spatial candidate
        # pairs, not a dense N-by-N matrix. Crossing bound can overestimate real size.
        for i, line in enumerate(lines):
            _check_cancel(cancel)
            candidates += sum(int(j) > i for j in tree.query(line))
            if candidates > limits.max_overlay_pairs: raise GeometryError('boundary intersection envelope exceeds limit')
        potential = len(lines) + 2*candidates
        with policy.reserve(1536*potential+8192, category='boundary-arrangement'):
            _check_cancel(cancel)
            try: noded = shapely.node(MultiLineString(lines))
            except GEOSException as exc: raise GeometryError('boundary noding failed; no repair attempted') from exc
            if shapely.get_num_coordinates(noded) > 2*limits.max_vertices:
                raise GeometryError('noded boundary exceeds vertex envelope')
            atoms = set()
            for line in noded.geoms:
                xy = np.asarray(line.coords)
                for a, b in zip(xy[:-1], xy[1:]):
                    p, q = _point_key(a), _point_key(b)
                    if p == q: raise GeometryError('noding produced a zero-length boundary')
                    atoms.add((p, q) if p < q else (q, p))
            if len(atoms) > limits.max_vertices: raise GeometryError('too many boundary segments')
            atoms = sorted(atoms); sides = []; edge_shapes = []; attributions = 0
            for p, q in atoms:
                _check_cancel(cancel); atom = LineString((p, q)); direction = _direction(p, q)
                side = [-1, -1]
                for j in tree.query(atom):
                    j = int(j); attributions += 1
                    if attributions > 8*limits.max_overlay_pairs: raise GeometryError('boundary attribution limit exceeded')
                    if not lines[j].covers(atom): continue
                    column = 0 if float(np.dot(direction, vectors[j])) > 0 else 1
                    if side[column] not in (-1, owners[j]):
                        raise GeometryError('multiple owners on the same boundary side')
                    side[column] = owners[j]
                if side == [-1, -1] or side[0] == side[1]:
                    raise GeometryError('boundary has no unique nondegenerate owner')
                if -1 in side and not domain_shape.boundary.covers(atom):
                    raise GeometryError('unpaired internal edge; no inferred exterior material')
                if -1 not in side and domain_shape.boundary.covers(atom):
                    raise GeometryError('two owners on a declared exterior boundary')
                sides.append(side); edge_shapes.append(atom)
            vertices = sorted({p for atom in atoms for p in atom}); lookup = {v: i for i, v in enumerate(vertices)}
            edges = [(lookup[a], lookup[b]) for a, b in atoms]
            incidence = [[] for _ in vertices]
            for i, (a, b) in enumerate(edges):
                d = _direction(vertices[a], vertices[b]); angle = math.atan2(d[1], d[0])
                incidence[a].append((angle, i, 1))
                incidence[b].append((math.atan2(-d[1], -d[0]), i, -1))
            offsets = [0]; halfedges = []
            for rays in incidence:
                rays.sort()
                if len(rays) < 2: raise GeometryError('dangling polygon boundary')
                if len({angle for angle, i, sign in rays}) != len(rays):
                    raise GeometryError('ambiguous coincident junction directions')
                for k, (_, i, sign) in enumerate(rays):
                    _, j, sign2 = rays[(k+1) % len(rays)]
                    left = sides[i][0 if sign > 0 else 1]
                    right_next = sides[j][1 if sign2 > 0 else 0]
                    if left != right_next: raise GeometryError('junction angular sectors have inconsistent ownership')
                halfedges.extend((i, sign) for angle, i, sign in rays); offsets.append(len(halfedges))
            # Region-to-edge CSR keeps repeated ownership lookup linear in the
            # requested perimeter, not a full-network scan per region.
            uses_by_region = [[] for _ in regions]
            for i, (l, r) in enumerate(sides):
                if l >= 0: uses_by_region[l].append((i, 1))
                if r >= 0: uses_by_region[r].append((i, -1))
            region_offsets = [0]; region_uses = []
            for uses in uses_by_region:
                region_uses.extend(uses); region_offsets.append(len(region_uses))
            obj = object.__new__(BoundaryNetwork)
            data = {'domain': domain, 'regions': regions,
                    '_vertices': np.asarray(vertices, dtype='f8').tobytes(),
                    '_edges': np.asarray(edges, dtype='i8').tobytes(),
                    '_sides': np.asarray(sides, dtype='i8').tobytes(),
                    '_offsets': np.asarray(offsets, dtype='i8').tobytes(),
                    '_incidence': np.asarray(halfedges, dtype='i8').tobytes(),
                    '_region_offsets': np.asarray(region_offsets, dtype='i8').tobytes(),
                    '_region_uses': np.asarray(region_uses, dtype='i8').tobytes(),
                    '_shapes': tuple(edge_shapes), '_tree': STRtree(edge_shapes)}
            context = {'schema': _SCHEMA, 'method': _METHOD, 'domain': domain.descriptor(),
                       'regions': [{'region_id': r.region_id, 'plate_id': r.plate_id,
                                    'geometry': r.geometry.descriptor()} for r in regions]}
            prefix = _json(context)
            # Hash shared definitions once; do not rehash an O(regions) header for
            # each O(edges) record. Source identity still binds the full definition.
            prefix_digest = hashlib.sha256(prefix).digest()
            for k, v in data.items(): object.__setattr__(obj, k, v)
            edge_ids = tuple(hashlib.sha256(prefix_digest+b'\0edge\0'+_json((atoms[i], sides[i]))).hexdigest() for i in range(len(atoms)))
            vertex_ids = tuple(hashlib.sha256(prefix_digest+b'\0vertex\0'+_json(v)).hexdigest() for v in vertices)
            object.__setattr__(obj, 'edge_ids', edge_ids); object.__setattr__(obj, 'vertex_ids', vertex_ids)
            h = hashlib.sha256(prefix)
            for key in ('_vertices', '_edges', '_sides', '_offsets', '_incidence', '_region_offsets', '_region_uses'):
                h.update(b'\0'+data[key])
            object.__setattr__(obj, 'network_id', h.hexdigest())
            statistics = {'input_segments': len(lines), 'region_candidate_pairs': region_pairs,
                          'segment_candidate_pairs': candidates, 'attribution_candidates': attributions,
                          'unique_segments': len(atoms), 'vertices': len(vertices)}
            object.__setattr__(obj, '_construction', _json(statistics))
            # Geometry/connectivity can be valid while conversion to physical units
            # overflows. Validate metrics before publishing the network as usable.
            obj.frames(limits=limits, budget=policy, cancel=cancel)
            _check_cancel(cancel)
            return obj


def save_boundary_network(network, store, *, budget=None, cancel=None):
    """One self-contained snapshot via ArrayStore; no new persistence framework.

    Native trees and derived incidence rebuild from the identified definitions.
    Repeated typed WKB bytes deduplicate in the existing chunk store. The network
    ID also binds derived connectivity so a different reconstruction is refused.
    """
    from .storage import ArrayStore
    if type(network) is not BoundaryNetwork or not isinstance(store, ArrayStore):
        raise GeometryError('typed network and existing ArrayStore required')
    _check_cancel(cancel)
    arrays = {}
    for name, geometry in [('domain', network.domain)] + [('region_'+str(i), r.geometry) for i, r in enumerate(network.regions)]:
        raw = geometry._projected.wkb if type(geometry) is SphericalGeometry else geometry.wkb
        arrays[name] = np.frombuffer(raw, dtype='u1')
    return store.put(network.network_id, arrays, network.descriptor(), budget=budget, cancel=cancel)


def load_boundary_network(store, network_id, *, limits=None, budget=None, cancel=None):
    """Validate stored definitions, rebuild sides/junctions, check exact identity."""
    _sha(network_id); _check_cancel(cancel)
    arrays = store.get(network_id, budget=budget)
    if arrays is None: return None
    meta = store.metadata(network_id)
    if (type(meta) is not dict or set(meta) != {'schema','method','domain','regions','network_id'} or
            meta['schema'] != _SCHEMA or meta['method'] != _METHOD or meta['network_id'] != network_id or
            type(meta['regions']) is not list):
        raise GeometryError('invalid boundary snapshot metadata')
    limits = _limits(limits)
    if len(meta['regions']) > limits.max_vertices: raise GeometryError('saved region count exceeds limit')
    if set(arrays) != {'domain', *('region_'+str(i) for i in range(len(meta['regions'])))}:
        raise GeometryError('boundary snapshot inventory mismatch')
    def restore(name, descriptor):
        a = arrays[name]
        if a.dtype != np.dtype('u1') or a.ndim != 1: raise GeometryError('invalid geometry payload')
        if descriptor.get('space') == 'planar-metres':
            g = PlanarGeometry.from_wkb(a.tobytes(), frame_id=descriptor['frame_id'], limits=limits, budget=budget)
        elif descriptor.get('space') == 'sphere-minor-arcs':
            chart = SphericalChart.from_descriptor(descriptor['chart'])
            g = SphericalGeometry.from_projected_wkb(a.tobytes(), chart=chart, limits=limits, budget=budget)
        else: raise GeometryError('unsupported saved geometry space')
        if g.descriptor() != descriptor: raise GeometryError('saved geometry identity mismatch')
        return g
    try:
        domain = restore('domain', meta['domain']); regions = []
        for i, row in enumerate(meta['regions']):
            if type(row) is not dict or set(row) != {'region_id','plate_id','geometry'}:
                raise GeometryError('invalid saved boundary region')
            regions.append(BoundaryRegion(row['region_id'], row['plate_id'], restore('region_'+str(i), row['geometry'])))
        out = build_boundary_network(domain, tuple(regions), limits=limits, budget=budget, cancel=cancel)
        if out.network_id != network_id: raise GeometryError('saved boundary connectivity mismatch')
        return out
    except (KeyError, TypeError, AttributeError) as exc:
        raise GeometryError('invalid boundary snapshot') from exc
