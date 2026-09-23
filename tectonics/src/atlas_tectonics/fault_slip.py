"""Prescribed discontinuous translation along one named straight fault.

Both sides retain their entire finite material footprint. Tangential relative
motion supplies slip; normal creation, convergence and material transfer require
another physical route. The infinite straight interface is prescribed, not
inferred. This producer has no mechanics, earthquake cycle, or localisation law.
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
from shapely.strtree import STRtree

from ._validation import input_shape, read_array, scalar
from .geometry import (GeometryError, PlanarGeometry, _check_cancel, _json,
                       _label, _limits, geometry_runtime)
from .resources import WorkBudget, select_budget
from .reuse import ExecutionContext


MAX_SLIP_INTERVALS = 256
MAX_SLIP_PARCELS = 4096
_ROUND = float(128*np.finfo(float).eps)
_GEOMETRY_TOLERANCE = 1e-12


def _identity(record, *payloads):
    digest = hashlib.sha256(_json(record))
    for raw in payloads:
        digest.update(b'\0'); digest.update(raw)
    return digest.hexdigest()


def _dot(a, b):
    return math.fsum((float(a[0])*float(b[0]), float(a[1])*float(b[1])))


def _sum_vectors(a, b):
    return np.array([math.fsum((float(a[k]), float(b[k]))) for k in range(2)])


@dataclass(frozen=True, slots=True, init=False)
class SlipInterval:
    """Constant side and interface velocities in one common Cartesian SI frame."""
    end_time_s: float
    source_id: str
    _negative: bytes = field(repr=False)
    _positive: bytes = field(repr=False)
    _boundary: bytes = field(repr=False)

    def __init__(self, end_time_s, negative_velocity_m_s, positive_velocity_m_s,
                 boundary_velocity_m_s, source_id):
        vectors = (negative_velocity_m_s, positive_velocity_m_s, boundary_velocity_m_s)
        if any(input_shape(v, 'slip velocity') != (2,) for v in vectors):
            raise GeometryError('three explicit two-component SI velocities required')
        _label(source_id, 'fault-slip history source')
        object.__setattr__(self, 'end_time_s', scalar(end_time_s, 'history endpoint'))
        object.__setattr__(self, 'source_id', source_id)
        for name, value in zip(('_negative', '_positive', '_boundary'), vectors):
            object.__setattr__(self, name, read_array(value, 'slip velocity').tobytes())

    @property
    def negative_velocity_m_s(self): return np.frombuffer(self._negative, np.float64)
    @property
    def positive_velocity_m_s(self): return np.frombuffer(self._positive, np.float64)
    @property
    def boundary_velocity_m_s(self): return np.frombuffer(self._boundary, np.float64)
    def descriptor(self):
        return dict(end_time_s=self.end_time_s, source_id=self.source_id,
                    negative_velocity_m_s=self.negative_velocity_m_s.tolist(),
                    positive_velocity_m_s=self.positive_velocity_m_s.tolist(),
                    boundary_velocity_m_s=self.boundary_velocity_m_s.tolist())


@dataclass(frozen=True, slots=True, weakref_slot=True)
class FaultSlipState:
    polygons: tuple[PlanarGeometry, ...]
    parcel_ids: tuple[str, ...]
    time_s: float
    state_id: str
    plan_id: str
    frame_id: str
    source_id: str
    interface_id: str
    _gradient: bytes = field(repr=False)
    _jacobian: bytes = field(repr=False)
    _point: bytes = field(repr=False)
    _translations: bytes = field(repr=False)
    _record: bytes = field(repr=False)

    @property
    def deformation_gradient(self): return np.frombuffer(self._gradient, np.float64).reshape(-1, 2, 2)
    @property
    def jacobian(self): return np.frombuffer(self._jacobian, np.float64)
    @property
    def interface_point_m(self): return np.frombuffer(self._point, np.float64)
    @property
    def translations_m(self):
        """Rows: negative side, positive side, interface, relative to initial state."""
        return np.frombuffer(self._translations, np.float64).reshape(3, 2)
    @property
    def nbytes(self):
        """Retained definition bytes, excluding the separately admitted GEOS heap."""
        return (sum(len(raw) for raw in (self._gradient, self._jacobian, self._point,
                                        self._translations, self._record))
                + sum(p.retained_bytes for p in self.polygons))
    def descriptor(self): return json.loads(self._record)


def _disjoint(polygons, limits, budget, cancel):
    shapes = [p._geom for p in polygons]
    tree = STRtree(shapes)
    candidates = 0
    for i, shape in enumerate(shapes):
        _check_cancel(cancel)
        for j in tree.query(shape):
            j = int(j)
            if j <= i: continue
            candidates += 1
            if candidates > limits.max_overlay_pairs:
                raise GeometryError('fault parcel intersection envelope exceeds GeometryLimits')
            # The sum of input vertices is bounded before GEOS sees this pair.
            # The product limits possible intersection complexity, not just hits.
            if polygons[i].vertex_count*polygons[j].vertex_count > limits.max_overlay_pairs:
                raise GeometryError('fault parcel overlay complexity exceeds GeometryLimits')
            if polygons[i].overlay(polygons[j], limits=limits, budget=budget, cancel=cancel).area_m2 > 0:
                raise GeometryError('reference fault parcels overlap')


def _normal_motion(event, normal, duration, length_scale):
    boundary = event.boundary_velocity_m_s
    for velocity in (event.negative_velocity_m_s, event.positive_velocity_m_s):
        terms = (float(velocity[0])*float(normal[0]), float(velocity[1])*float(normal[1]),
                 -float(boundary[0])*float(normal[0]), -float(boundary[1])*float(normal[1]))
        residual = math.fsum(terms)
        scale = math.fsum(abs(x) for x in terms)
        # Use all constituent terms, not a small cancelled net velocity. A long
        # duration must also meet the physical geometry error bound: large common
        # frame translation cannot hide a meaningful normal opening/convergence.
        if (not math.isfinite(residual) or abs(residual) > _ROUND*scale
                or abs(residual*duration) > _GEOMETRY_TOLERANCE*length_scale):
            raise GeometryError('normal opening/convergence requires an explicit material-transfer route')


def _translated(polygon, shift, limits):
    old = shapely.get_coordinates(polygon._geom)
    actual = old+shift
    local = old-old[0]
    scale = max(float(np.max(np.ptp(local, axis=0))), math.sqrt(polygon.area_m2))
    if (not np.isfinite(actual).all()
            or np.any((shift != 0) & np.all(actual == old, axis=0))
            or np.max(np.abs((actual-old)-shift)) > _GEOMETRY_TOLERANCE*scale
            or np.max(np.abs((actual-actual[0])-local)) > _GEOMETRY_TOLERANCE*scale):
        raise GeometryError('fault translation is unresolvable in this physical frame')
    shape = shapely.set_coordinates(polygon._geom, actual)
    result = PlanarGeometry._from_shape(shape, polygon.frame_id, limits=limits)
    if abs(result.area_m2-polygon.area_m2) > _GEOMETRY_TOLERANCE*polygon.area_m2:
        raise GeometryError('translated parcel area is numerically unresolved')
    return result


class PreparedFaultSlip:
    """Finite parcels translated on two sides of one straight infinite interface.

    This route requires every side to share the interface's normal velocity. It
    preserves the complete footprint; moving finite ends do not create incoming
    material. Cropping and any named exterior inventories belong to the material
    consumer. Source/context authentication belongs to that consumer as well.
    """
    def __setattr__(self, name, value):
        if getattr(self, '_sealed', False): raise AttributeError('fault-slip plan is immutable')
        object.__setattr__(self, name, value)

    def __init__(self, polygons, histories, *, parcel_ids, sides, interface_point_m,
                 interface_normal, interface_id, time_s, source_id, budget=None,
                 cancel=None, limits=None):
        _check_cancel(cancel); policy = _limits(limits)
        if (type(polygons) is not tuple or not 1 <= len(polygons) <= MAX_SLIP_PARCELS
                or any(type(p) is not PlanarGeometry or p.kind != 'Polygon'
                       or p.is_empty or p.area_m2 <= 0 for p in polygons)):
            raise GeometryError('one to 4096 explicit positive-area planar parcels required')
        count = sum(p.vertex_count for p in polygons)
        if count > policy.max_vertices: raise GeometryError('fault parcel vertex limit exceeded')
        frame = polygons[0].frame_id
        if any(p.frame_id != frame for p in polygons): raise GeometryError('fault parcels require one frame')
        if type(parcel_ids) is not tuple or len(parcel_ids) != len(polygons):
            raise GeometryError('one stable parcel ID per polygon required')
        for name in parcel_ids: _label(name, 'fault parcel ID')
        if len(set(parcel_ids)) != len(parcel_ids): raise GeometryError('duplicate fault parcel ID')
        if (type(sides) is not tuple or len(sides) != len(polygons)
                or any(type(s) is not int or s not in (-1, 1) for s in sides)):
            raise GeometryError('each parcel requires its explicit -1 or +1 interface side')
        if (type(histories) is not tuple or not 1 <= len(histories) <= MAX_SLIP_INTERVALS
                or any(type(e) is not SlipInterval for e in histories)):
            raise GeometryError('one to 256 explicit SlipInterval histories required')
        if input_shape(interface_point_m) != (2,) or input_shape(interface_normal) != (2,):
            raise GeometryError('two-component interface point and unit normal required')
        _label(interface_id, 'interface ID'); _label(source_id, 'fault-slip source')
        start = scalar(time_s, 'initial epoch'); times = [start]
        for event in histories:
            if event.end_time_s <= times[-1]: raise GeometryError('fault history endpoints must increase')
            scalar(event.end_time_s-times[-1], 'fault interval duration', positive=True)
            times.append(event.end_time_s)
        resource = WorkBudget(128*1024**2) if budget is None else select_budget(budget)
        lease = resource.reserve(1024*count+4096*(len(polygons)+len(histories))+65536,
                                 category='fault-slip-prepared')
        lease.__enter__()
        try:
            with resource.reserve(512*count+4096*len(polygons)+65536+2*1024**2,
                                  category='fault-slip-prepare'), ExecutionContext('scipy') as context:
                point = read_array(interface_point_m, 'interface point')
                normal = read_array(interface_normal, 'interface normal')
                if abs(_dot(normal, normal)-1.) > _ROUND:
                    raise GeometryError('interface normal must be supplied as a unit vector')
                distances = []
                scales = []
                for polygon, side in zip(polygons, sides):
                    _check_cancel(cancel)
                    xy = shapely.get_coordinates(polygon._geom)
                    local = xy-xy[0]
                    scale = max(float(np.max(np.ptp(local, axis=0))), math.sqrt(polygon.area_m2))
                    signed = np.array([side*_dot(p-point, normal) for p in xy])
                    if not np.isfinite(signed).all() or np.any(signed < 0):
                        raise GeometryError('parcel crosses interface or occupies its wrong declared half-plane')
                    distances.append(float(np.min(signed))); scales.append(scale)
                _disjoint(polygons, policy, resource, cancel)
                scale = min(scales)  # smallest local parcel, never a distant global-origin magnitude
                scalar(scale, 'fault parcel physical scale', positive=True)
                prefix = [np.zeros((3, 2))]
                for j, event in enumerate(histories):
                    _check_cancel(cancel)
                    duration = times[j+1]-times[j]
                    _normal_motion(event, normal, duration, scale)
                    with np.errstate(over='raise', invalid='raise'):
                        velocities = (event.negative_velocity_m_s, event.positive_velocity_m_s,
                                      event.boundary_velocity_m_s)
                        shifts = np.array([_sum_vectors(prefix[-1][k], v*duration)
                                           for k, v in enumerate(velocities)])
                    # Relative signed distance is linear on each event. Its
                    # endpoint extrema certify half-plane containment for the
                    # entire interval; no temporal collision sampling is used.
                    for distance, parcel_scale, side in zip(distances, scales, sides):
                        relative = shifts[0 if side < 0 else 1]-shifts[2]
                        drift = side*_dot(relative, normal)
                        if abs(drift) > _GEOMETRY_TOLERANCE*parcel_scale or distance+drift < 0:
                            raise GeometryError('normal motion crosses interface or accumulates unresolved opening')
                    self._moved_point(point, shifts[2], scale)
                    prefix.append(shifts)
                self.polygons = polygons; self.histories = histories; self.parcel_ids = parcel_ids
                self.sides = sides; self.interface_id = interface_id
                self.time_s = start; self.frame_id = frame; self.source_id = source_id
                self._point = point.tobytes(); self._normal = normal.tobytes()
                self._prefix = np.asarray(prefix).tobytes(); self._times = tuple(times)
                self._scale = scale; self._vertices = count; self.limits = policy
                self._budget = resource; self._lease = lease
                self.execution_id = context.identity
                self._closed = False; self._lock = threading.Lock(); self._active = 0
                record = dict(method='atlas.w08-straight-fault-slip.v1', source_id=source_id,
                    frame_id=frame, time_s=start, interface_id=interface_id,
                    interface_point_m=point.tolist(), interface_normal=normal.tolist(),
                    parcel_ids=parcel_ids, sides=sides, polygons=[p.geometry_id for p in polygons],
                    histories=[e.descriptor() for e in histories], runtime=geometry_runtime(),
                    execution_id=self.execution_id,
                    motion='piecewise-rigid-side-translation', interface='prescribed-straight-infinite',
                    normal_velocity_tolerance_epsilon_units=128,
                    geometry_relative_tolerance=_GEOMETRY_TOLERANCE,
                    finite_ends='complete-footprints-retained-no-implicit-incoming-material')
                self._record = _json(record); self.plan_id = _identity(record, self._prefix)
                _check_cancel(cancel); self._sealed = True
        except (FloatingPointError, OverflowError) as exc:
            lease.__exit__(None, None, None)
            raise GeometryError('fault motion exceeds representable numerical range') from exc
        except BaseException:
            lease.__exit__(None, None, None); raise

    @staticmethod
    def _moved_point(point, shift, scale):
        actual = point+shift
        if (not np.isfinite(actual).all() or np.any((shift != 0) & (actual == point))
                or np.max(np.abs((actual-point)-shift)) > _GEOMETRY_TOLERANCE*scale):
            raise GeometryError('interface translation is unresolvable in this physical frame')
        return actual

    @property
    def interface_point_m(self): return np.frombuffer(self._point, np.float64)
    @property
    def interface_normal(self): return np.frombuffer(self._normal, np.float64)
    @property
    def nbytes(self):
        return (len(self._point)+len(self._normal)+len(self._prefix)+len(self._record)
                + sum(p.retained_bytes for p in self.polygons)+48*len(self.histories))
    def descriptor(self): return json.loads(self._record)

    @contextmanager
    def _query(self, cancel):
        with self._lock:
            if self._closed: raise GeometryError('fault-slip plan is closed')
            object.__setattr__(self, '_active', self._active+1)
        try:
            _check_cancel(cancel); yield
        finally:
            with self._lock: object.__setattr__(self, '_active', self._active-1)

    def evaluate(self, time_s, *, cancel=None):
        with self._query(cancel):
            now = scalar(time_s, 'fault output epoch')
            if not self._times[0] <= now <= self._times[-1]:
                raise GeometryError('fault output lies outside supplied history')
            lease = self._budget.reserve(1280*self._vertices+4096*len(self.polygons)+32768,
                                         category='fault-slip-state')
            lease.__enter__()
            try:
                with self._budget.reserve(512*self._vertices+32768, category='fault-slip-evaluate'):
                    j = int(np.searchsorted(self._times, now, side='right'))-1
                    shifts = np.frombuffer(self._prefix, np.float64).reshape(-1, 3, 2)[j]
                    if now != self._times[j]:
                        event = self.histories[j]; duration = now-self._times[j]
                        shifts = np.array([_sum_vectors(shifts[k], v*duration) for k, v in enumerate(
                            (event.negative_velocity_m_s, event.positive_velocity_m_s, event.boundary_velocity_m_s))])
                    point = self._moved_point(self.interface_point_m, shifts[2], self._scale)
                    output = []
                    for polygon, side in zip(self.polygons, self.sides):
                        _check_cancel(cancel)
                        shift = shifts[0 if side < 0 else 1]
                        output.append(polygon if not np.any(shift) else _translated(polygon, shift, self.limits))
                    gradient = np.tile(np.eye(2), (len(output), 1, 1)).tobytes()
                    jacobian = np.ones(len(output)).tobytes()
                    record = dict(method='atlas.w08-fault-slip-state.v1', plan_id=self.plan_id,
                        time_s=now, frame_id=self.frame_id, source_id=self.source_id,
                        interface_id=self.interface_id, interface_point_m=point.tolist(),
                        interface_normal=self.interface_normal.tolist(), sides=self.sides,
                        parcel_ids=self.parcel_ids, translations_m=shifts.tolist(),
                        polygons=[p.geometry_id for p in output],
                        physical_model='prescribed-discontinuous-straight-tangential-slip')
                    payloads = gradient, jacobian, point.tobytes(), shifts.tobytes(), _json(record)
                    state = FaultSlipState(tuple(output), self.parcel_ids, now, _identity(record, *payloads),
                        self.plan_id, self.frame_id, self.source_id, self.interface_id, *payloads)
                    _check_cancel(cancel)
                    weakref.finalize(state, lease.__exit__, None, None, None)
                    return state
            except (FloatingPointError, OverflowError) as exc:
                lease.__exit__(None, None, None)
                raise GeometryError('fault motion exceeds representable numerical range') from exc
            except BaseException:
                lease.__exit__(None, None, None); raise

    def close(self):
        with self._lock:
            if self._active: raise GeometryError('join active fault-slip queries before closing')
            if self._closed: return
            object.__setattr__(self, '_closed', True)
            object.__setattr__(self, 'polygons', ())
            object.__setattr__(self, 'histories', ())
            object.__setattr__(self, '_prefix', b'')
            self._lease.__exit__(None, None, None)

    def __enter__(self): return self
    def __exit__(self, *args): self.close()
