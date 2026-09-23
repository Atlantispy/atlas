"""Source-prescribed compatible P1 material motion on a convex triangular mesh.

Vertices follow exactly linear trajectories in each declared interval. This is
not constant spatial velocity-gradient integration, inferred fault geometry, or a
localisation law. Boundary velocities must be affine; interior motion may vary.
Positive element determinants throughout each interval and the affine, positive
boundary map preserve injectivity. No repair, transfer, or hidden remapping occurs.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
import hashlib
import json
import math
import threading
import weakref

import numpy as np
import shapely
from shapely.geometry import Polygon, LineString, Point
from shapely.strtree import STRtree

from ._validation import input_shape, read_array, scalar
from .geometry import (GeometryError, PlanarGeometry, _check_cancel, _json,
                       _label, _limits, geometry_runtime)
from .resources import WorkBudget, select_budget
from .reuse import ExecutionContext


MAX_NETWORK_INTERVALS = 256
MAX_NETWORK_TRIANGLES = 4096
_ROUND = float(128*np.finfo(float).eps)
_PHYSICAL_TOLERANCE = 1e-12  # relative to declared local length/velocity scales


def _identity(record, *payloads):
    digest = hashlib.sha256(_json(record))
    for payload in payloads:
        digest.update(b'\0'); digest.update(payload)
    return digest.hexdigest()


def _cross(a, b):
    return a[..., 0]*b[..., 1]-a[..., 1]*b[..., 0]


def _edges(vertices, triangles):
    points = vertices[triangles]
    return np.stack((points[:, 1]-points[:, 0], points[:, 2]-points[:, 0]), axis=-1)


def _det(matrix):
    return _cross(matrix[..., :, 0], matrix[..., :, 1])


def _inverse(matrix):
    determinant = _det(matrix)
    result = np.empty_like(matrix)
    result[..., 0, 0] = matrix[..., 1, 1]
    result[..., 1, 1] = matrix[..., 0, 0]
    result[..., 0, 1] = -matrix[..., 0, 1]
    result[..., 1, 0] = -matrix[..., 1, 0]
    return result/determinant[..., None, None]


def _positive_segment(start, delta, label):
    """det(E+s*dE) is quadratic; check both ends and every interior minimum."""
    a = _det(delta)
    b = (_cross(start[..., :, 0], delta[..., :, 1])
         + _cross(delta[..., :, 0], start[..., :, 1]))
    c = _det(start)
    scale = np.maximum(np.max(np.abs(start), axis=(-2, -1)),
                       np.max(np.abs(start+delta), axis=(-2, -1)))
    floor = _ROUND*scale*scale
    minimum = np.minimum(c, _det(start+delta))
    convex = a > 0
    stationary = np.zeros_like(a)
    np.divide(-b, 2*a, out=stationary, where=convex)
    interior = convex & (stationary > 0) & (stationary < 1)
    # Evaluate the actual edge matrix at the extremum, avoiding cancellation in
    # a*s*s+b*s+c when a nearly collapsing triangle recovers by the endpoint.
    stationary = np.where(interior, stationary, 0.)
    at_stationary = _det(start+stationary[..., None, None]*delta)
    minimum = np.where(interior, np.minimum(minimum, at_stationary), minimum)
    if (not np.isfinite(minimum).all() or not np.isfinite(floor).all()
            or np.any(minimum <= floor)):
        raise GeometryError(label+' collapses, inverts, or is numerically unresolved within interval')


@dataclass(frozen=True, slots=True, init=False)
class NodalMotionInterval:
    """Prescribed SI vertex velocities, constant along each material trajectory."""
    end_time_s: float
    source_id: str
    _velocity: bytes = field(repr=False)
    _nodes: int = field(repr=False)

    def __init__(self, end_time_s, velocity_m_s, source_id):
        end = scalar(end_time_s, 'history endpoint')
        _label(source_id, 'nodal motion source')
        shape = input_shape(velocity_m_s, 'nodal velocities')
        if len(shape) != 2 or shape[1] != 2 or not 3 <= shape[0] <= 3*MAX_NETWORK_TRIANGLES:
            raise GeometryError('bounded (nodes,2) nodal velocities required')
        # This bounded input record owns its immutable definition. A plan charges
        # retained references to these bytes to its shared execution budget.
        raw = read_array(velocity_m_s, 'nodal velocities').tobytes()
        object.__setattr__(self, 'end_time_s', end)
        object.__setattr__(self, 'source_id', source_id)
        object.__setattr__(self, '_velocity', raw)
        object.__setattr__(self, '_nodes', shape[0])

    @property
    def velocity_m_s(self):
        return np.frombuffer(self._velocity, np.float64).reshape(self._nodes, 2)

    def descriptor(self):
        return dict(end_time_s=self.end_time_s, source_id=self.source_id,
                    velocity_sha256=hashlib.sha256(self._velocity).hexdigest())


@dataclass(frozen=True, slots=True, weakref_slot=True)
class NetworkState:
    plan_id: str
    state_id: str
    time_s: float
    frame_id: str
    source_id: str
    triangle_ids: tuple[str, ...]
    polygons: tuple[PlanarGeometry, ...]
    _vertices: bytes = field(repr=False)
    _triangles: bytes = field(repr=False)
    _gradient: bytes = field(repr=False)
    _jacobian: bytes = field(repr=False)
    _record: bytes = field(repr=False)

    @property
    def vertices_m(self): return np.frombuffer(self._vertices, np.float64).reshape(-1, 2)
    @property
    def triangles(self): return np.frombuffer(self._triangles, np.int64).reshape(-1, 3)
    @property
    def deformation_gradient(self): return np.frombuffer(self._gradient, np.float64).reshape(-1, 2, 2)
    @property
    def jacobian(self): return np.frombuffer(self._jacobian, np.float64)
    @property
    def nbytes(self):
        """Definition bytes; held admission also allows native polygon storage."""
        return (sum(len(x) for x in (self._vertices, self._triangles, self._gradient,
                                    self._jacobian, self._record))
                + sum(p.retained_bytes for p in self.polygons))
    def descriptor(self): return json.loads(self._record)


def _mesh(local, triangles, limits, cancel):
    """Validate one conforming disk tiling its entire convex boundary polygon."""
    if len(np.unique(local, axis=0)) != len(local):
        raise GeometryError('duplicate mesh vertices')
    if len(np.unique(triangles)) != len(local):
        raise GeometryError('unused mesh nodes')
    if len(np.unique(np.sort(triangles, axis=1), axis=0)) != len(triangles):
        raise GeometryError('duplicate triangles')
    edge = _edges(local, triangles)
    _positive_segment(edge, np.zeros_like(edge), 'initial CCW triangle')
    owners = {}
    for tri in triangles:
        for a, b in zip(tri, np.roll(tri, -1)):
            key = tuple(sorted((int(a), int(b))))
            rows = owners.setdefault(key, [])
            rows.append((int(a), int(b)))
            if len(rows) > 2 or len(rows) == 2 and rows[0] != rows[1][::-1]:
                raise GeometryError('non-manifold or inconsistently oriented shared edge')
    boundary = [rows[0] for rows in owners.values() if len(rows) == 1]
    successor = dict(boundary)
    if (len(boundary) < 3 or len(successor) != len(boundary)
            or set(successor) != set(b for _, b in boundary)):
        raise GeometryError('one manifold boundary cycle required')
    ring = [min(successor)]
    while successor[ring[-1]] != ring[0]:
        nxt = successor.get(ring[-1])
        if nxt is None or nxt in ring or len(ring) >= len(boundary):
            raise GeometryError('invalid mesh boundary cycle')
        ring.append(nxt)
    if len(ring) != len(boundary):
        raise GeometryError('holes or disconnected mesh components are unsupported')
    region = Polygon(local[ring])
    if not region.is_valid or region.is_empty or not region.equals(region.convex_hull):
        raise GeometryError('initial mesh must tile one convex polygon')
    shapes = [Polygon(local[tri]) for tri in triangles]
    tree = STRtree(shapes)
    pairs = 0
    for i, shape in enumerate(shapes):
        _check_cancel(cancel)
        for j in tree.query(shape):
            j = int(j)
            if j <= i: continue
            pairs += 1
            if pairs > limits.max_overlay_pairs:
                raise GeometryError('mesh intersection envelope exceeds GeometryLimits')
            common = sorted(set(map(int, triangles[i])) & set(map(int, triangles[j])))
            intersection = shape.intersection(shapes[j])
            expected = (Point(local[common[0]]) if len(common) == 1 else
                        LineString(local[common]) if len(common) == 2 else None)
            if ((expected is None and not intersection.is_empty)
                    or expected is not None and not intersection.equals(expected)):
                raise GeometryError('mesh overlap, crossing, or nonconforming junction')
    if not shapely.union_all(shapes).equals(region):
        raise GeometryError('mesh has gaps or does not tile the convex boundary')
    return np.asarray(ring, dtype=np.int64), edge


def _boundary_map(local, displacement, ring):
    x = local[ring]-local[ring[0]]
    u = displacement[ring]-displacement[ring[0]]
    far = int(np.argmax(np.sum(x*x, axis=1)))
    third = int(np.argmax(np.abs(_cross(x[far], x))))
    basis = np.stack((x[far], x[third]), axis=-1)
    gradient = np.stack((u[far], u[third]), axis=-1) @ _inverse(basis)
    scale = max(float(np.max(np.abs(x))), float(np.max(np.abs(u))))
    if (not math.isfinite(scale) or scale <= 0 or not np.isfinite(gradient).all()
            or np.max(np.abs(x @ gradient.T-u)) > _PHYSICAL_TOLERANCE*scale):
        raise GeometryError('boundary velocities must fit one affine map on the physical scale')
    _positive_segment(np.eye(2), gradient, 'affine boundary map')


class PreparedDeformationNetwork:
    """Bounded immutable nodal history; output leases last until state collection.

    Caller closes this plan after active queries join. State objects remain valid
    and budget-accounted after close; dropping the final state reference releases
    its allowance. Context/source verification belongs to the integrating caller.
    """
    def __setattr__(self, name, value):
        if getattr(self, '_sealed', False):
            raise AttributeError('prepared deformation network is immutable')
        object.__setattr__(self, name, value)

    def __init__(self, vertices_m, triangles, histories, *, time_s, frame_id,
                 source_id, triangle_ids, budget=None, cancel=None, limits=None):
        _check_cancel(cancel)
        shape = input_shape(vertices_m, 'network vertices')
        t_shape = input_shape(triangles, 'network triangles')
        policy = _limits(limits)
        if (len(shape) != 2 or shape[1] != 2 or not 3 <= shape[0] <= policy.max_vertices
                or len(t_shape) != 2 or t_shape[1] != 3
                or not 1 <= t_shape[0] <= MAX_NETWORK_TRIANGLES
                or 4*t_shape[0] > policy.max_vertices):
            raise GeometryError('bounded node matrix and one to 4096 triangles required')
        n, m = shape[0], t_shape[0]
        if (type(histories) is not tuple or not 1 <= len(histories) <= MAX_NETWORK_INTERVALS
                or any(type(h) is not NodalMotionInterval or h._nodes != n for h in histories)):
            raise GeometryError('one to 256 matching nodal history intervals required')
        if type(triangle_ids) is not tuple or len(triangle_ids) != m:
            raise GeometryError('one stable triangle ID per triangle required')
        for name in triangle_ids: _label(name, 'triangle ID')
        if len(set(triangle_ids)) != m: raise GeometryError('duplicate triangle ID')
        _label(frame_id, 'network frame'); _label(source_id, 'network source')
        start = scalar(time_s, 'initial time')
        times = [start]
        for event in histories:
            if event.end_time_s <= times[-1]:
                raise GeometryError('history endpoints must strictly increase from initial time')
            scalar(event.end_time_s-times[-1], 'interval duration', positive=True)
            times.append(event.end_time_s)
        resource = WorkBudget(128*1024**2) if budget is None else select_budget(budget)
        h = len(histories)
        retained = (32*n*(h+1)+32*m*(h+1)+64*m+1024*h+65536)
        lease = resource.reserve(retained, category='deformation-network-retained')
        lease.__enter__()
        try:
            # Includes simultaneous endpoint arrays/bytes, topology dictionaries,
            # spatial-index/native geometry and bounded per-query candidates.
            with resource.reserve(retained+8192*m+512*n+65536+2*1024**2,
                                  category='deformation-network-prepare'), ExecutionContext('scipy') as ctx:
                self.execution_id = ctx.identity
                vertices = read_array(vertices_m, 'network vertices')
                raw_tri = np.asarray(triangles)
                if raw_tri.dtype.kind not in 'iu' or np.any(raw_tri < 0) or np.any(raw_tri >= n):
                    raise GeometryError('triangle indices must be in-range integers')
                tri = np.asarray(raw_tri, dtype=np.int64)
                origin = vertices[0].copy()
                local = vertices-origin
                if not np.isfinite(local).all(): raise GeometryError('unresolvable local coordinate range')
                ring, reference_edges = _mesh(local, tri, policy, cancel)
                inverse = _inverse(reference_edges)
                endpoints = [local.copy()]
                shifts = [np.zeros(2)]
                gradients = [np.broadcast_to(np.eye(2), (m, 2, 2)).copy()]
                for j, event in enumerate(histories):
                    _check_cancel(cancel)
                    with np.errstate(over='raise', invalid='raise', divide='raise'):
                        duration = times[j+1]-times[j]
                        displacement = event.velocity_m_s*duration
                        relative = displacement-displacement[0]
                        _boundary_map(endpoints[-1], relative, ring)
                        old_edges = _edges(endpoints[-1], tri)
                        _positive_segment(old_edges, _edges(relative, tri), 'material triangle')
                        new = endpoints[-1]+relative
                        shift = np.array([math.fsum((shifts[-1][k], displacement[0, k])) for k in range(2)])
                        self._physical_vertices(origin, shift, new, tri)
                        endpoints.append(new); shifts.append(shift)
                        gradients.append(np.eye(2)+(_edges(new, tri)-reference_edges) @ inverse)
                self._budget = resource; self._lease = lease; self._closed = False
                self._lock = threading.Lock(); self._active = 0
                self.time_s = start; self.frame_id = frame_id; self.source_id = source_id
                self.triangle_ids = triangle_ids; self.histories = histories; self.limits = policy
                self._times = tuple(times); self._origin = origin.tobytes()
                self._triangles = tri.tobytes(); self._inverse = inverse.tobytes()
                self._endpoints = np.asarray(endpoints).tobytes()
                self._shifts = np.asarray(shifts).tobytes()
                self._gradients = np.asarray(gradients).tobytes()
                self._n = n; self._m = m
                record = dict(method='atlas.w08-p1-deformation-network.v1', time_s=start,
                    frame_id=frame_id, source_id=source_id, triangle_ids=triangle_ids,
                    histories=[e.descriptor() for e in histories], runtime=geometry_runtime(),
                    boundary='affine-velocity-convex-fully-tiled',
                    motion='linear-material-vertex-trajectories-per-event',
                    execution=self.execution_id,
                    physical_scale_tolerance=_PHYSICAL_TOLERANCE,
                    determinant_guard_epsilon_units=128)
                self.plan_id = _identity(record, vertices.tobytes(), self._triangles)
                self._record = _json(record)
                _check_cancel(cancel); self._sealed = True
        except FloatingPointError as exc:
            lease.__exit__(None, None, None)
            raise GeometryError('network deformation exceeds numerical range') from exc
        except BaseException:
            lease.__exit__(None, None, None)
            raise

    @staticmethod
    def _physical_vertices(origin, shift, local, triangles):
        vertices = origin+(shift+local)
        expected = _edges(local, triangles)
        actual = _edges(vertices, triangles)
        scale = np.max(np.abs(expected), axis=(-2, -1))
        if (not np.isfinite(vertices).all() or
                np.any((shift != 0) & (vertices[0] == origin)) or
                np.any(np.max(np.abs(actual-expected), axis=(-2, -1)) > _PHYSICAL_TOLERANCE*scale)):
            raise GeometryError('deformed geometry is unresolvable in the physical frame')
        return vertices

    @property
    def nbytes(self):
        return (sum(len(getattr(self, name)) for name in
                    ('_origin', '_triangles', '_inverse', '_endpoints', '_shifts', '_gradients', '_record'))
                + sum(len(event._velocity) for event in self.histories))

    def descriptor(self): return json.loads(self._record)

    @contextmanager
    def _query(self, cancel):
        with self._lock:
            if self._closed: raise GeometryError('deformation network is closed')
            object.__setattr__(self, '_active', self._active+1)
        try:
            _check_cancel(cancel); yield
        finally:
            with self._lock: object.__setattr__(self, '_active', self._active-1)

    def evaluate(self, time_s, *, cancel=None):
        with self._query(cancel):
            now = scalar(time_s, 'query time')
            if not self._times[0] <= now <= self._times[-1]:
                raise GeometryError('query lies outside supplied nodal history')
            # Output geometry owns this allowance until its final reference dies.
            lease = self._budget.reserve(8192*self._m+256*self._n+32768,
                                         category='deformation-network-state')
            lease.__enter__()
            try:
                with self._budget.reserve(256*self._m+192*self._n+32768,
                                          category='deformation-network-evaluate'):
                    j = int(np.searchsorted(self._times, now, side='right'))-1
                    endpoints = np.frombuffer(self._endpoints, np.float64).reshape(-1, self._n, 2)
                    shifts = np.frombuffer(self._shifts, np.float64).reshape(-1, 2)
                    local, shift = endpoints[j], shifts[j]
                    tri = np.frombuffer(self._triangles, np.int64).reshape(-1, 3)
                    if now != self._times[j]:
                        displacement = self.histories[j].velocity_m_s*(now-self._times[j])
                        local = local+(displacement-displacement[0])
                        shift = shift+displacement[0]
                        gradient = (np.eye(2)+(_edges(local, tri)-_edges(endpoints[0], tri))
                                    @ np.frombuffer(self._inverse, np.float64).reshape(-1, 2, 2))
                    else:
                        gradient = np.frombuffer(self._gradients, np.float64).reshape(-1, self._m, 2, 2)[j]
                    vertices = self._physical_vertices(np.frombuffer(self._origin, np.float64), shift, local, tri)
                    jacobian = _det(gradient)
                    if not np.isfinite(gradient).all() or np.any(jacobian <= 0):
                        raise GeometryError('unresolvable evaluated deformation gradient')
                    polygons = []
                    for indices in tri:
                        _check_cancel(cancel)
                        polygons.append(PlanarGeometry.polygon(vertices[indices], frame_id=self.frame_id,
                                                              limits=self.limits, budget=self._budget))
                    record = dict(method='atlas.w08-network-state.v1', plan_id=self.plan_id,
                        time_s=now, frame_id=self.frame_id, source_id=self.source_id,
                        triangle_ids=self.triangle_ids, completed_intervals=j,
                        active_interval=j if now != self._times[j] else None)
                    payloads = vertices.tobytes(), self._triangles, gradient.tobytes(), jacobian.tobytes()
                    state_id = _identity(record, *payloads)
                    state = NetworkState(self.plan_id, state_id, now, self.frame_id, self.source_id,
                                         self.triangle_ids, tuple(polygons), *payloads, _json(record))
                    _check_cancel(cancel)
                    weakref.finalize(state, lease.__exit__, None, None, None)
                    return state
            except BaseException:
                lease.__exit__(None, None, None)
                raise

    def close(self):
        with self._lock:
            if self._active: raise GeometryError('join active network queries before close')
            if self._closed: return
            object.__setattr__(self, '_closed', True)
            for name in ('_endpoints', '_shifts', '_gradients', '_inverse', '_triangles', '_origin'):
                object.__setattr__(self, name, b'')
            object.__setattr__(self, 'histories', ())
            self._lease.__exit__(None, None, None)

    def __enter__(self): return self
    def __exit__(self, *args): self.close()
