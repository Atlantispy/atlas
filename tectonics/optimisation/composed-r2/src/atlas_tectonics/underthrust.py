"""Conservative prescribed ramp-flat underthrusting in a labelled x/z section.

T_s(x,z)=(x+s,z+h(x+s)-h(x)) is the selected vertical-shear closure.
It preserves area and interface side, not bed-normal thickness or bed length.
Supplied generalised forces book external work; they are NOT inferred reactions.
Static host material is explicit and checked over the entire supplied motion.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
import hashlib
import json
import math
import threading

import numpy as np
import shapely
from shapely.geometry import Polygon
from shapely.strtree import STRtree

from ._validation import TectonicsError, input_shape, read_array, scalar
from .geometry import (PlanarGeometry, GeometryError, _limits, _label,
                       _check_cancel, _validate_shape, geometry_runtime)
from .materials import MaterialCohort, _json
from .planar_exchange import _area_shape
from .resources import WorkBudget, select_budget
from .reuse import ExecutionContext

MAX_PARCELS = 4096
MAX_INTERVALS = 256
MAX_RECEIVERS = 64
MAX_KNOTS = 64
MAP_ERROR = 1e-10
ROUND = float(128*np.finfo(float).eps)


def _id(record, *buffers):
    digest = hashlib.sha256(_json(record))
    for raw in buffers:
        digest.update(b'\0'); digest.update(raw)
    return digest.hexdigest()


@dataclass(frozen=True, slots=True, init=False)
class UnderthrustInterface:
    """Fixed, single-valued descending interface; positive x is downdip.

    Knots are metres (x,z up), not map x/y. Outside the knot range the two
    explicitly supplied end flats continue horizontally. The final segment must
    be the flat detachment at first_z-detachment_depth_m.
    """
    interface_id: str
    frame_id: str
    datum_id: str
    source_id: str
    detachment_depth_m: float
    section_azimuth_deg: float
    _knots: bytes = field(repr=False)

    def __init__(self, knots_xz_m, *, interface_id, frame_id, datum_id, source_id,
                 detachment_depth_m, section_azimuth_deg):
        shape = input_shape(knots_xz_m, 'interface knots')
        if len(shape) != 2 or shape[1] != 2 or not 2 <= shape[0] <= MAX_KNOTS:
            raise GeometryError('two to 64 explicit x/z interface knots required')
        values = read_array(knots_xz_m, 'interface knots')
        depth = scalar(detachment_depth_m, 'detachment depth', nonnegative=True)
        azimuth = scalar(section_azimuth_deg, 'section azimuth')
        if not 0 <= azimuth < 360:
            raise GeometryError('section azimuth must be in [0,360) degrees')
        if (np.any(np.diff(values[:, 0]) <= 0) or np.any(np.diff(values[:, 1]) > 0)
                or values[-1, 1] != values[-2, 1]
                or values[0, 1]-values[-1, 1] != depth):
            raise GeometryError('descending single-valued ramp and explicit flat detachment required')
        slopes = np.diff(values[:, 1])/np.diff(values[:, 0])
        if not np.isfinite(slopes).all():
            raise GeometryError('interface slope exceeds numerical range')
        for key, value in (('interface_id', interface_id), ('frame_id', frame_id),
                           ('datum_id', datum_id), ('source_id', source_id)):
            _label(value, key); object.__setattr__(self, key, value)
        object.__setattr__(self, 'detachment_depth_m', depth)
        object.__setattr__(self, 'section_azimuth_deg', azimuth)
        object.__setattr__(self, '_knots', values.tobytes())

    @property
    def knots_xz_m(self): return np.frombuffer(self._knots, np.float64).reshape(-1, 2)

    def height(self, x):
        p = self.knots_xz_m
        return np.interp(x, p[:, 0], p[:, 1])

    def descriptor(self):
        return dict(interface_id=self.interface_id, frame_id=self.frame_id,
                    datum_id=self.datum_id, source_id=self.source_id,
                    detachment_depth_m=self.detachment_depth_m,
                    section_azimuth_deg=self.section_azimuth_deg,
                    knots_xz_m=self.knots_xz_m.tolist(), axes='x-downdip,z-up',
                    endpoint_extension='supplied-horizontal-flats')


@dataclass(frozen=True, slots=True)
class UnderthrustParcel:
    parcel_id: str
    block_id: str
    role: str
    cohort: MaterialCohort
    polygon: PlanarGeometry
    density_kg_m3: float
    specific_enthalpy_j_kg: float | None = None
    enthalpy_source_id: str | None = None

    def __post_init__(self):
        _label(self.parcel_id, 'parcel ID'); _label(self.block_id, 'block ID')
        if self.role not in ('footwall', 'hangingwall', 'host'):
            raise GeometryError('explicit footwall, hangingwall or stationary host role required')
        if type(self.cohort) is not MaterialCohort:
            raise TectonicsError('actual MaterialCohort required')
        p = self.polygon
        if (type(p) is not PlanarGeometry or p.kind not in ('Polygon', 'MultiPolygon')
                or p.is_empty or p.area_m2 <= 0):
            raise GeometryError('positive occupied section polygon required')
        object.__setattr__(self, 'density_kg_m3', scalar(self.density_kg_m3, 'density', positive=True))
        if self.specific_enthalpy_j_kg is None:
            if self.enthalpy_source_id is not None:
                raise TectonicsError('enthalpy source without a known enthalpy')
        else:
            _label(self.enthalpy_source_id, 'enthalpy convention/source')
            object.__setattr__(self, 'specific_enthalpy_j_kg',
                               scalar(self.specific_enthalpy_j_kg, 'specific enthalpy'))

    def descriptor(self):
        return dict(parcel_id=self.parcel_id, block_id=self.block_id, role=self.role,
                    cohort=asdict(self.cohort), geometry_id=self.polygon.geometry_id,
                    density_kg_m3=self.density_kg_m3,
                    specific_enthalpy_j_kg=self.specific_enthalpy_j_kg,
                    enthalpy_source_id=self.enthalpy_source_id)


@dataclass(frozen=True, slots=True)
class UnderthrustInterval:
    """Horizontal velocities and Q conjugate to each block's horizontal slip.

    Q has units N and work is Q*ds, including its sign. It is a supplied work
    closure, not a force inferred from geometry or simply an unstated traction.
    Rates/forces are constant on this interval; histories may explicitly change.
    """
    end_time_s: float
    footwall_velocity_m_s: float
    hangingwall_velocity_m_s: float
    footwall_generalised_force_n: float
    hangingwall_generalised_force_n: float
    source_id: str
    work_source_id: str

    def __post_init__(self):
        for key in ('end_time_s', 'footwall_velocity_m_s', 'hangingwall_velocity_m_s',
                    'footwall_generalised_force_n', 'hangingwall_generalised_force_n'):
            object.__setattr__(self, key, scalar(getattr(self, key), key))
        if self.footwall_velocity_m_s < self.hangingwall_velocity_m_s:
            raise GeometryError('reverse relative slip is not this underthrusting route')
        _label(self.source_id, 'motion source'); _label(self.work_source_id, 'work source')


def _shift(shape, distance):
    xy = shapely.get_coordinates(shape)
    moved = xy.copy(); moved[:, 0] += distance
    scale = max(float(np.ptp(xy[:, 0])), math.sqrt(float(shape.area)))
    if (not np.isfinite(moved).all() or
            distance != 0 and np.all(moved[:, 0] == xy[:, 0]) or
            np.max(np.abs((moved[:, 0]-xy[:, 0])-distance)) > MAP_ERROR*scale):
        raise GeometryError('section displacement is unresolvable in this frame')
    return shapely.set_coordinates(shape, moved)


def _warp(polygon, interface, shift, flatten, budget, limits, cancel):
    """Split at slope changes, then apply exact affine maps to whole pieces.

    Flattening once prepares material coordinates (x,eta=z-h(x)). Evaluation
    translates x and unflattens; no time stepping or repeated material remap.
    """
    _check_cancel(cancel)
    lo, bottom, hi, top = polygon.bounds
    knots = interface.knots_xz_m[:, 0]-(0. if flatten else shift)
    cuts = np.r_[lo, knots[(knots > lo) & (knots < hi)], hi]
    complexity = polygon.vertex_count*len(cuts)
    if complexity > limits.max_overlay_pairs:
        raise GeometryError('interface split complexity exceeds GeometryLimits')
    with budget.reserve(2048*complexity+65536, category='underthrust-map'):
        parts = []
        vertices = 0
        for a, b in zip(cuts[:-1], cuts[1:]):
            _check_cancel(cancel)
            # A parcel wholly within one velocity domain needs no overlay.
            clipped = (polygon._geom if len(cuts) == 2 else
                       _area_shape(shapely.intersection(polygon._geom, shapely.box(a, bottom, b, top))))
            if clipped is None: continue
            xy = shapely.get_coordinates(clipped)
            mapped = xy.copy()
            if flatten:
                mapped[:, 1] -= interface.height(xy[:, 0])
            else:
                mapped[:, 0] += shift
                mapped[:, 1] += interface.height(mapped[:, 0])
            if not np.isfinite(mapped).all():
                raise GeometryError('section mapping exceeds finite range')
            scale = max(hi-lo, top-bottom, math.sqrt(polygon.area_m2))
            if (not flatten and shift != 0 and np.all(mapped[:, 0] == xy[:, 0]) or
                    not flatten and np.max(np.abs((mapped[:, 0]-xy[:, 0])-shift)) > MAP_ERROR*scale):
                raise GeometryError('section displacement is unresolvable in this frame')
            recovered = (mapped[:, 1]+interface.height(mapped[:, 0]) if flatten else
                         mapped[:, 1]-interface.height(mapped[:, 0]))
            if np.max(np.abs(recovered-xy[:, 1])) > MAP_ERROR*scale:
                raise GeometryError('section vertical offset is numerically unresolved')
            part = shapely.set_coordinates(clipped, mapped)
            _validate_shape(part, limits, allow_empty=False)
            vertices += int(shapely.get_num_coordinates(part))
            if vertices > limits.max_vertices:
                raise GeometryError('mapped section vertex limit exceeded')
            parts.append(part)
        if not parts: raise GeometryError('positive material disappeared during section mapping')
        shape = parts[0] if len(parts) == 1 else shapely.union_all(parts)
        result = PlanarGeometry._from_shape(shape, polygon.frame_id, limits=limits)
        if abs(result.area_m2-polygon.area_m2) > MAP_ERROR*polygon.area_m2:
            raise GeometryError('area-preserving section map failed its geometric error bound')
        return result


def _disjoint(polygons, budget, limits, cancel):
    tree = STRtree([p._geom for p in polygons]); pairs = 0
    for i, p in enumerate(polygons):
        _check_cancel(cancel)
        for j in tree.query(p._geom):
            j = int(j)
            if j <= i: continue
            pairs += 1
            if pairs > limits.max_overlay_pairs:
                raise GeometryError('section overlap pair limit exceeded')
            if p.overlay(polygons[j], budget=budget, limits=limits, cancel=cancel).area_m2 > 0:
                raise GeometryError('occupied section parcels/receivers overlap')


def _sweep(shape, first, last, limits):
    """Exact horizontal Minkowski sweep, including nonconvex shapes and holes."""
    a, b = sorted((first, last))
    if a == b: return _shift(shape, a)
    pieces = [_shift(shape, a), _shift(shape, b)]
    polygons = [shape] if shape.geom_type == 'Polygon' else list(shape.geoms)
    for polygon in polygons:
        for ring in (polygon.exterior, *polygon.interiors):
            xy = np.asarray(ring.coords)
            for p, q in zip(xy[:-1], xy[1:]):
                if p[1] == q[1]: continue
                pieces.append(Polygon([(p[0]+a, p[1]), (q[0]+a, q[1]),
                                       (q[0]+b, q[1]), (p[0]+b, p[1])]))
    result = shapely.union_all(pieces)
    _validate_shape(result, limits, allow_empty=False)
    return result


@dataclass(frozen=True, slots=True)
class UnderthrustState:
    polygons: tuple[PlanarGeometry, ...]
    parcel_ids: tuple[str, ...]
    destination_ids: tuple[str, ...]
    enthalpy_known: tuple[bool, ...]
    time_s: float
    plan_id: str
    state_id: str
    _fields: bytes = field(repr=False)
    _work: bytes = field(repr=False)
    _potential: bytes = field(repr=False)
    _displacement: bytes = field(repr=False)
    _record: bytes = field(repr=False)

    def _values(self):
        return np.frombuffer(self._fields, np.float64).reshape(3, len(self.parcel_ids), len(self.destination_ids))
    @property
    def volume_m3(self): return self._values()[0]
    @property
    def mass_kg(self): return self._values()[1]
    @property
    def enthalpy_j(self):
        """Only rows with enthalpy_known=True are physical heat accounts."""
        return self._values()[2]
    @property
    def boundary_work_j(self): return np.frombuffer(self._work, np.float64)
    @property
    def gravitational_change_j(self): return np.frombuffer(self._potential, np.float64)
    @property
    def displacement_m(self): return np.frombuffer(self._displacement, np.float64)
    @property
    def nbytes(self):
        return sum(map(len, (self._fields, self._work, self._potential, self._displacement,
                             self._record)))+sum(p.retained_bytes for p in self.polygons)
    def descriptor(self): return json.loads(self._record)


class PreparedUnderthrust:
    """One explicit section, full finite stock and source-verified latest reuse.

    Stationary hosts carry inventory and cannot be overwritten, even transiently.
    Receiver regions are reporting destinations, NOT vacant-space declarations.
    The separately named exterior retains its material; a crop never deletes it.
    Caller-held old outputs require their own memory allowance after replacement.
    """
    def __setattr__(self, name, value):
        if getattr(self, '_sealed', False): raise AttributeError('underthrust preparation is immutable')
        object.__setattr__(self, name, value)

    def __init__(self, interface, parcels, histories, *, time_s, epoch_id, width_m,
                 gravity_m_s2, receiver_regions, exterior_id, source_id,
                 host_space_source_id, budget=None, cancel=None):
        _check_cancel(cancel)
        if type(interface) is not UnderthrustInterface:
            raise GeometryError('explicit UnderthrustInterface required')
        if (type(parcels) is not tuple or not 2 <= len(parcels) <= MAX_PARCELS
                or any(type(p) is not UnderthrustParcel for p in parcels)):
            raise GeometryError('two to 4096 explicit material parcels required')
        if (type(histories) is not tuple or not 1 <= len(histories) <= MAX_INTERVALS
                or any(type(h) is not UnderthrustInterval for h in histories)):
            raise GeometryError('one to 256 explicit motion/work intervals required')
        if type(receiver_regions) is not tuple or not 1 <= len(receiver_regions) <= MAX_RECEIVERS:
            raise GeometryError('one to 64 named receiver polygons required')
        for name in (epoch_id, exterior_id, source_id, host_space_source_id): _label(name, 'section provenance')
        now = scalar(time_s, 'initial epoch')
        width = scalar(width_m, 'strike width', positive=True)
        gravity = scalar(gravity_m_s2, 'gravity', nonnegative=True)
        times = [now]
        for h in histories:
            if h.end_time_s <= times[-1]: raise TectonicsError('history endpoints must strictly increase')
            scalar(h.end_time_s-times[-1], 'interval duration', positive=True)
            times.append(h.end_time_s)
        ids = tuple(p.parcel_id for p in parcels)
        if len(set(ids)) != len(ids): raise TectonicsError('duplicate parcel ID')
        by_role = {role: {p.block_id for p in parcels if p.role == role}
                   for role in ('footwall', 'hangingwall', 'host')}
        if len(by_role['footwall']) != 1 or len(by_role['hangingwall']) != 1:
            raise GeometryError('one identified moving block on each interface side required')
        if (by_role['footwall'] & by_role['hangingwall'] or
                (by_role['footwall'] | by_role['hangingwall']) & by_role['host']):
            raise GeometryError('different motion roles cannot share a block ID')
        catalogue = {}
        for p in parcels:
            if p.polygon.frame_id != interface.frame_id: raise GeometryError('section frame mismatch')
            c = p.cohort
            if c.formation_time_s is not None and c.formation_time_s > now:
                raise TectonicsError('material formation is later than the initial state')
            if c.cohort_id in catalogue and catalogue[c.cohort_id] != c:
                raise TectonicsError('conflicting material cohort history')
            catalogue[c.cohort_id] = c
        names, receivers = [], []
        for entry in receiver_regions:
            if type(entry) is not tuple or len(entry) != 2:
                raise GeometryError('receiver entries must be (ID, polygon) tuples')
            label, p = entry; _label(label, 'receiver ID')
            if (type(p) is not PlanarGeometry or p.kind not in ('Polygon', 'MultiPolygon')
                    or p.is_empty or p.area_m2 <= 0 or p.frame_id != interface.frame_id):
                raise GeometryError('positive receiver polygon in the same section frame required')
            names.append(label); receivers.append(p)
        if len(set((*names, exterior_id))) != len(names)+1:
            raise GeometryError('receiver and retained-exterior IDs must be unique')
        limits = _limits(None)
        count = sum(p.polygon.vertex_count for p in parcels)+sum(p.vertex_count for p in receivers)
        if count > limits.max_vertices: raise GeometryError('section input vertex limit exceeded')
        resource = WorkBudget(128*1024**2, parent=select_budget(budget))
        guard = resource.reserve(4096*count+4096*(len(parcels)+len(histories))+4*1024**2,
                                 category='underthrust-prepared')
        guard.__enter__(); context = None
        try:
            self._budget = resource; self._guard = guard; self._limits = limits
            self.interface = interface; self.parcels = parcels; self.histories = histories
            self.width_m = width; self.gravity_m_s2 = gravity; self.time_s = now
            self.epoch_id = epoch_id; self.source_id = source_id; self.host_space_source_id = host_space_source_id
            self._times = tuple(times); self.receiver_regions = receiver_regions
            self.destination_ids = (*names, exterior_id)
            self._roles = tuple(0 if p.role == 'footwall' else 1 if p.role == 'hangingwall' else 2 for p in parcels)
            self._receivers = tuple(receivers); self._tree = STRtree([p._geom for p in receivers])
            originals = tuple(p.polygon for p in parcels)
            _disjoint(originals, resource, limits, cancel)
            _disjoint(tuple(receivers), resource, limits, cancel)
            flat = tuple(_warp(p, interface, 0., True, resource, limits, cancel) for p in originals)
            if sum(p.vertex_count for p in flat) > limits.max_vertices:
                raise GeometryError('flattened section vertex limit exceeded')
            for role, p in zip(self._roles, flat):
                eta = shapely.get_coordinates(p._geom)[:, 1]
                if role == 0 and np.max(eta) > 0 or role == 1 and np.min(eta) < 0:
                    raise GeometryError('material crosses the interface or has the wrong declared side')
            self._flat = flat
            self._check_hosts(cancel)
            with np.errstate(over='ignore', invalid='ignore', under='ignore'):
                volume = np.array([p.polygon.area_m2*width for p in parcels])
                mass = volume*np.array([p.density_kg_m3 for p in parcels])
                heat = mass*np.array([0. if p.specific_enthalpy_j_kg is None else p.specific_enthalpy_j_kg for p in parcels])
            if (not all(np.isfinite(a).all() for a in (volume, mass, heat))
                    or np.any(volume <= 0) or np.any(mass <= 0)
                    or any(p.specific_enthalpy_j_kg not in (None, 0.) and q == 0 for p, q in zip(parcels, heat))):
                raise TectonicsError('finite material/enthalpy stock is unrepresentable')
            self._stock = np.stack((volume, mass, heat)).tobytes()
            self._context = context = ExecutionContext('scipy')
            self.execution_id = context.identity
            record = dict(method='atlas.underthrust-vertical-shear.v1', interface=interface.descriptor(),
                          parcels=[p.descriptor() for p in parcels], histories=[asdict(h) for h in histories],
                          time_s=now, epoch_id=epoch_id, width_m=width, gravity_m_s2=gravity,
                          receivers=[(n, p.geometry_id) for n, p in receiver_regions], exterior_id=exterior_id,
                          source_id=source_id, host_space_source_id=host_space_source_id,
                          execution_id=self.execution_id, geometry_runtime=geometry_runtime())
            self.plan_id = _id(record, self._stock)
            self._record = _json(record)
            if len(self._record) > 512*1024:
                raise TectonicsError('underthrust definition metadata exceeds 512 KiB')
            self._owner = threading.get_ident(); self._active = False; self._closed = False
            self._latest = None; self._latest_guard = None
            self._stats = dict(computed_outputs=0, latest_hits=0)
            context.verify(); _check_cancel(cancel); self._sealed = True
        except BaseException:
            if context is not None: context.close()
            guard.__exit__(None, None, None)
            raise

    def _motion(self, now):
        t = scalar(now, 'query time')
        if not self._times[0] <= t <= self._times[-1]:
            raise TectonicsError('query outside supplied underthrust history')
        movement = [[], []]; work = [[], []]
        for i, h in enumerate(self.histories):
            dt = min(t, h.end_time_s)-self._times[i]
            if dt <= 0: break
            for role, (v, q) in enumerate(((h.footwall_velocity_m_s, h.footwall_generalised_force_n),
                                           (h.hangingwall_velocity_m_s, h.hangingwall_generalised_force_n))):
                distance = v*dt
                if v != 0 and distance == 0:
                    raise TectonicsError('nonzero block displacement underflows')
                if q != 0 and distance != 0 and q*distance == 0:
                    raise TectonicsError('nonzero supplied boundary work underflows')
                movement[role].append(scalar(distance, 'finite block displacement'))
                work[role].append(scalar(q*distance, 'supplied boundary work'))
        return (np.array([scalar(math.fsum(x), 'accumulated displacement') for x in movement]),
                np.array([scalar(math.fsum(x), 'accumulated boundary work') for x in work]))

    def _check_hosts(self, cancel):
        hosts = [p for p, role in zip(self._flat, self._roles) if role == 2]
        if not hosts: return
        tree = STRtree([p._geom for p in hosts]); pairs = 0
        prior = np.zeros(2)
        for interval in self.histories:
            current, _ = self._motion(interval.end_time_s)
            for p, role in zip(self._flat, self._roles):
                if role == 2: continue
                _check_cancel(cancel)
                with self._budget.reserve(8192*p.vertex_count+65536, category='underthrust-host-sweep'):
                    swept = _sweep(p._geom, prior[role], current[role], self._limits)
                    for j in tree.query(swept):
                        pairs += 1; host = hosts[int(j)]
                        if (pairs > self._limits.max_overlay_pairs or
                                int(shapely.get_num_coordinates(swept))*host.vertex_count > self._limits.max_overlay_pairs):
                            raise GeometryError('host-space intersection complexity exceeds GeometryLimits')
                        with self._budget.reserve(1024*(int(shapely.get_num_coordinates(swept))+host.vertex_count)+65536,
                                                  category='underthrust-host-overlap'):
                            if float(shapely.intersection(swept, host._geom).area) > 0:
                                raise GeometryError('motion enters occupied stationary host space')
            prior = current

    @contextmanager
    def _operation(self, cancel):
        if self._closed or self._active or threading.get_ident() != self._owner:
            raise TectonicsError('use an open idle underthrust plan on its owner thread')
        _check_cancel(cancel); self._context.verify()
        object.__setattr__(self, '_active', True)
        try: yield
        finally: object.__setattr__(self, '_active', False)

    def evaluate(self, time_s, *, cancel=None):
        with self._operation(cancel):
            displacement, work = self._motion(time_s)
            if self._latest is not None and self._latest.time_s == time_s:
                self._stats['latest_hits'] += 1
                _check_cancel(cancel); return self._latest
            n, r = len(self.parcels), len(self.destination_ids)
            count = sum(p.vertex_count for p in self._flat)
            with self._budget.reserve(128*n*r+4096*count+1024*n+65536, category='underthrust-evaluate'):
                polygons = tuple(p.polygon if role == 2 or displacement[role] == 0 else
                                 _warp(flat, self.interface, float(displacement[role]), False,
                                       self._budget, self._limits, cancel)
                                 for p, flat, role in zip(self.parcels, self._flat, self._roles))
                total_vertices = sum(p.vertex_count for p in polygons)
                if total_vertices > self._limits.max_vertices:
                    raise GeometryError('output section vertex limit exceeded')
                # The maps are injective within each side and side-preserving;
                # stationary hosts were checked for the whole continuous history.
                stock = np.frombuffer(self._stock, np.float64).reshape(3, n)
                fields = np.zeros((3, n, r)); potential = np.empty(n)
                hits = 0
                for i, p in enumerate(polygons):
                    _check_cancel(cancel)
                    areas = np.zeros(r); remaining = p
                    for j in sorted(int(k) for k in self._tree.query(p._geom)):
                        hits += 1
                        if hits > self._limits.max_hits: raise GeometryError('receiver intersection hit limit exceeded')
                        receiver = self._receivers[j]
                        areas[j] = p.overlay(receiver, budget=self._budget, limits=self._limits, cancel=cancel).area_m2
                        if areas[j]:
                            remaining = remaining.overlay(receiver, operation='difference', budget=self._budget,
                                                          limits=self._limits, cancel=cancel)
                    areas[-1] = remaining.area_m2
                    if abs(math.fsum(areas)-p.area_m2) > ROUND*p.area_m2:
                        raise GeometryError('receiving and exterior areas do not conserve occupied material')
                    fields[:, i, :] = stock[:, i, None]*(areas/p.area_m2)
                    if np.any((areas[None, :] > 0) & (stock[:, i, None] != 0) & (fields[:, i, :] == 0)):
                        raise TectonicsError('nonzero receiving material/enthalpy account underflows')
                    for k in range(3):
                        if abs(math.fsum(fields[k, i])-stock[k, i]) > ROUND*abs(stock[k, i]):
                            raise TectonicsError('tagged receiving material account failed')
                    dz = float(p._geom.centroid.y-self.parcels[i].polygon._geom.centroid.y)
                    potential[i] = stock[1, i]*self.gravity_m_s2*dz
                    if dz != 0 and self.gravity_m_s2 != 0 and potential[i] == 0:
                        raise TectonicsError('nonzero gravitational energy change underflows')
                if not np.isfinite(fields).all() or not np.isfinite(potential).all():
                    raise TectonicsError('section material/energy result exceeds finite range')
                known = tuple(p.specific_enthalpy_j_kg is not None for p in self.parcels)
                record = dict(plan_id=self.plan_id, execution_id=self.execution_id, time_s=float(time_s),
                              frame_id=self.interface.frame_id, datum_id=self.interface.datum_id,
                              epoch_id=self.epoch_id, interface=self.interface.descriptor(),
                              parcels=[p.descriptor() for p in self.parcels],
                              current_geometry_ids=[p.geometry_id for p in polygons],
                              destination_ids=self.destination_ids, enthalpy_known=known,
                              host_space_source_id=self.host_space_source_id,
                              boundary_work='supplied-generalised-force-times-horizontal-slip',
                              energy_residual_not_assigned_to_heat=True,
                              exterior='retained-material-not-a-second-export',
                              geometric_area_error_m2=[p.area_m2-ref.polygon.area_m2 for p, ref in zip(polygons, self.parcels)])
                raw = (fields.tobytes(), work.tobytes(), potential.tobytes(), displacement.tobytes())
                state = UnderthrustState(polygons, tuple(p.parcel_id for p in self.parcels), self.destination_ids,
                                        known, float(time_s), self.plan_id, _id(record, *raw), *raw, _json(record))
                self._context.verify(); _check_cancel(cancel)
                guard = self._budget.reserve(state.nbytes+2048*total_vertices+65536,
                                             category='underthrust-latest')
                guard.__enter__()
                old = self._latest_guard
                object.__setattr__(self, '_latest', state); object.__setattr__(self, '_latest_guard', guard)
                if old is not None: old.__exit__(None, None, None)
                self._stats['computed_outputs'] += 1
                return state

    def statistics(self): return dict(self._stats, resources=self._budget.statistics())

    def close(self):
        if self._closed: return
        if self._active or threading.get_ident() != self._owner:
            raise TectonicsError('close underthrust on its idle owner thread')
        object.__setattr__(self, '_closed', True)
        try: self._context.close()
        finally:
            if self._latest_guard is not None: self._latest_guard.__exit__(None, None, None)
            object.__setattr__(self, '_latest', None)
            self._guard.__exit__(None, None, None)

    def __enter__(self):
        if self._closed: raise TectonicsError('underthrust preparation is closed')
        return self
    def __exit__(self, *_): self.close()
