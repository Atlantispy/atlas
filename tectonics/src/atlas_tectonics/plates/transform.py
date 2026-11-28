"""W08 full-vector planar kinematics and conservative material observations.

Constant spatial-gradient intervals use a homogeneous matrix exponential, not
summed infinitesimal strains. A compatible prescribed nodal network is a separate
motion producer. Neither producer infers fault geometry or mechanical localisation.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from contextlib import ExitStack
import json
import math
import numpy as np
import shapely
from scipy.linalg import expm

from atlas_tectonics._validation import TectonicsError, input_shape, read_array, scalar
from atlas_tectonics._validation import _PLANAR_MAP_ERROR as MAP_ERROR
from atlas_tectonics.planet.geometry import PlanarGeometry, GeometryLimits, geometry_runtime
from atlas_tectonics.materials.materials import MaterialCohort, _catalogue, _name, _json, _immutable_bytes
from atlas_tectonics.integration.resources import WorkBudget, select_budget
from atlas_tectonics.integration.resources import check_event
from atlas_tectonics.integration.resources import record_id
from atlas_tectonics.integration.reuse import ExecutionContext, content_record


MAX_INTERVALS = 256
MAX_PARCELS = 4096
WORK_BYTES = 128*1024**2


def _budget(value):
    return WorkBudget(WORK_BYTES) if value is None else select_budget(value)


def _names(values, count, label):
    for name in values: _name(name, label)
    return values


def _polygons(values):
    if sum(g.vertex_count for g in values) > GeometryLimits().max_vertices:
        raise TectonicsError('total material polygon vertex limit exceeded')
    return values


@dataclass(frozen=True, slots=True, init=False)
class AffineMotionInterval:
    """v(x)=L@(x-anchor)+b, SI, throughout one dated constant-gradient interval."""
    end_time_s: float
    source_id: str
    _gradient: bytes = field(repr=False)
    _velocity: bytes = field(repr=False)
    _anchor: bytes = field(repr=False)

    def __init__(self, end_time_s, gradient_s, velocity_m_s, anchor_m, source_id):
        object.__setattr__(self, 'end_time_s', scalar(end_time_s, 'interval endpoint'))
        object.__setattr__(self, 'source_id', _name(source_id, 'motion source'))
        for key, value in (('_gradient', gradient_s), ('_velocity', velocity_m_s),
                           ('_anchor', anchor_m)):
            object.__setattr__(self, key, _immutable_bytes(read_array(value, key)))

    @property
    def gradient_s(self): return np.frombuffer(self._gradient).reshape(2, 2)
    @property
    def velocity_m_s(self): return np.frombuffer(self._velocity)
    @property
    def anchor_m(self): return np.frombuffer(self._anchor)
    def descriptor(self):
        return dict(end_time_s=self.end_time_s, gradient_s=self.gradient_s.tolist(),
                    velocity_m_s=self.velocity_m_s.tolist(), anchor_m=self.anchor_m.tolist(),
                    source_id=self.source_id)


def _finite_map(event, duration, origin, length_scale):
    # Scale homogeneous coordinates by a local physical length: translational
    # metres must not drive avoidable Padé overscaling in the dimensionless matrix.
    matrix = np.zeros((3, 3))
    matrix[:2, :2] = event.gradient_s*duration
    matrix[:2, 2] = (event.gradient_s@(origin-event.anchor_m)+event.velocity_m_s)*duration/length_scale
    with np.errstate(over='ignore', invalid='ignore', under='ignore'):
        result = expm(matrix)
    result[:2, 2] *= length_scale
    _valid_map(result[:2, :2])
    if not np.isfinite(result).all(): raise TectonicsError('finite affine map is not representable')
    return result


def _valid_map(f):
    j = float(np.linalg.det(f))
    if not math.isfinite(j) or j <= 0 or np.linalg.cond(f)*np.finfo(float).eps > MAP_ERROR:
        raise TectonicsError('inverted, singular or unresolved finite deformation')
    return j


def _mapped_polygon(g, f, shift, origin):
    old = shapely.get_coordinates(g._geom)
    local = old-origin
    mapped = local@f.T+shift
    actual = mapped+origin
    scale = max(float(np.max(np.ptp(local, axis=0))), math.sqrt(g.area_m2))
    if np.max(np.abs((actual-old)-(mapped-local))) > MAP_ERROR*scale:
        raise TectonicsError('coordinate origin cannot resolve prescribed physical motion')
    shape = shapely.set_coordinates(g._geom, actual)
    out = PlanarGeometry._from_shape(shape, g.frame_id)
    _valid_map(f)
    return out


@dataclass(frozen=True, slots=True)
class PlanarMotionState:
    polygons: tuple[PlanarGeometry, ...]
    parcel_ids: tuple[str, ...]
    time_s: float
    state_id: str
    _f: bytes = field(repr=False)
    _record: bytes = field(repr=False)
    @property
    def deformation_gradient(self): return np.frombuffer(self._f).reshape(len(self.polygons), 2, 2)
    @property
    def jacobian(self): return np.linalg.det(self.deformation_gradient)
    @property
    def right_cauchy_green(self):
        f = self.deformation_gradient
        return np.swapaxes(f, -1, -2)@f
    @property
    def green_strain(self): return (self.right_cauchy_green-np.eye(2))/2
    @property
    def nbytes(self): return len(self._f)+len(self._record)+sum(g.retained_bytes for g in self.polygons)
    def descriptor(self): return json.loads(self._record)


class PreparedAffineMotion:
    """One exact full-vector field over disjoint retained material footprints.

Producer only: material ownership/source verification is performed by the
enclosing PreparedPlanarMaterials. Caller-owned polygons/results need allowance.
"""
    def __setattr__(self, name, value):
        object.__setattr__(self, name, value)

    def __init__(self, polygons, histories, *, parcel_ids, time_s, source_id, budget=None, cancel=None):
        check_event(cancel, 'regional transport cancelled; no candidate published'); polygons = _polygons(polygons)
        _names(parcel_ids, len(polygons), 'parcel IDs'); _name(source_id, 'motion source')
        if not 1 <= len(histories) <= MAX_INTERVALS:
            raise TectonicsError('one to 256 explicit affine history intervals required')
        time_s = scalar(time_s, 'initial epoch')
        resource = _budget(budget)
        lease = resource.reserve(1024*sum(g.vertex_count for g in polygons)+4096*len(histories)+65536,
                                 category='affine-motion-prepared')
        lease.__enter__(); preparation = ExitStack()
        try:
            preparation.enter_context(resource.reserve(2*1024**2, category='affine-motion-source'))
            ctx = preparation.enter_context(ExecutionContext('scipy'))
            self.execution_id = ctx.identity
            self._budget = resource; self._lease = lease; self._closed = False
            self.polygons = polygons; self.parcel_ids = parcel_ids; self.time_s = time_s
            self.histories = histories; self.source_id = source_id; self.frame_id = polygons[0].frame_id
            bounds = np.array([g.bounds for g in polygons]); origin = np.min(bounds[:, :2], axis=0)
            length = float(np.max(np.max(bounds[:, 2:], axis=0)-origin))
            self._origin = _immutable_bytes(origin); self._length = scalar(length, 'domain scale', positive=True)
            maps = [np.eye(3)]; times = [time_s]
            for event in histories:
                check_event(cancel, 'regional transport cancelled; no candidate published')
                current = _finite_map(event, event.end_time_s-times[-1], origin, length)@maps[-1]
                _valid_map(current[:2, :2]); maps.append(current); times.append(event.end_time_s)
            self._maps = _immutable_bytes(np.array(maps)); self._times = tuple(times)
            self.plan_id = record_id(content_record(dict(method='atlas.w08-affine-motion.v1',
                polygons=[g.geometry_id for g in polygons], parcel_ids=parcel_ids, time_s=time_s,
                source=source_id, history=[e.descriptor() for e in histories], runtime=geometry_runtime(),
                execution=self.execution_id)), self._maps, encode=_json)
            preparation.close()
            self._sealed = True
        except BaseException:
            try: preparation.close()
            finally: lease.__exit__(None, None, None)
            raise

    def evaluate(self, time_s, *, cancel=None):
        check_event(cancel, 'regional transport cancelled; no candidate published'); now = scalar(time_s, 'output time')
        j = int(np.searchsorted(self._times, now, side='right'))-1
        maps = np.frombuffer(self._maps).reshape(-1, 3, 3)
        origin = np.frombuffer(self._origin); transform = maps[j]
        if now != self._times[j]:
            transform = _finite_map(self.histories[j], now-self._times[j], origin, self._length)@transform
        f = transform[:2, :2]; _valid_map(f)
        with self._budget.reserve(1024*sum(g.vertex_count for g in self.polygons)+65536,
                                  category='affine-motion-output'):
            polygons = (self.polygons if now == self.time_s else
                        tuple(_mapped_polygon(g, f, transform[:2, 2], origin) for g in self.polygons))
            data = _immutable_bytes(np.broadcast_to(f, (len(polygons), 2, 2)).copy())
            record = dict(plan=self.plan_id, time_s=now, source=self.source_id,
                          frame=self.frame_id, physical_model='prescribed-constant-spatial-gradient',
                          polygons=[g.geometry_id for g in polygons], parcel_ids=self.parcel_ids)
            check_event(cancel, 'regional transport cancelled; no candidate published')
            return PlanarMotionState(polygons, self.parcel_ids, now, record_id(content_record(record), data, encode=_json), data, _json(record))

    def close(self):
        if not self._closed:
            object.__setattr__(self, '_closed', True); self._lease.__exit__(None, None, None)
    def __enter__(self): return self
    def __exit__(self, *args): self.close()


def boundary_flux_kg_s(*, thickness_m, density_kg_m3, length_m,
                       material_velocity_m_s, boundary_velocity_m_s, outward_normal):
    """Signed outward instantaneous rate. Only relative NORMAL motion crosses."""
    v = read_array(material_velocity_m_s, 'material velocity')
    b = read_array(boundary_velocity_m_s, 'boundary velocity')
    n = read_array(outward_normal, 'outward normal')
    return scalar(scalar(thickness_m, 'thickness', nonnegative=True)*
                  scalar(density_kg_m3, 'density', positive=True)*
                  scalar(length_m, 'boundary length', positive=True)*float((v-b)@n), 'mass flux')


def reframe_vectors(points_m, velocity_m_s, *, rotation, origin_m, frame_velocity_m_s):
    """Observe x'=Q(x-origin), v'=Q(v-frame_velocity); Q is fixed in time.

    A rotating observation frame additionally needs angular velocity and is not
    implied by this fixed-orientation moving-origin operation.
    """
    q = read_array(rotation, 'frame rotation')
    p = read_array(points_m, 'positions'); v = read_array(velocity_m_s, 'velocities')
    o = read_array(origin_m, 'frame origin'); u = read_array(frame_velocity_m_s, 'frame velocity')
    return (p-o)@q.T, (v-u)@q.T


@dataclass(frozen=True, slots=True)
class PlanarMaterialSnapshot:
    motion: object
    cohorts: tuple[MaterialCohort, ...]
    state_id: str
    _thickness: bytes = field(repr=False)
    _inventory: bytes = field(repr=False)
    _record: bytes = field(repr=False)
    @property
    def thickness_m(self): return np.frombuffer(self._thickness).reshape(len(self.cohorts), len(self.motion.polygons))
    def _field(self, i): return np.frombuffer(self._inventory).reshape(3, *self.thickness_m.shape)[i]
    @property
    def volume_m3(self): return self._field(0)
    @property
    def mass_kg(self): return self._field(1)
    @property
    def enthalpy_j(self): return self._field(2)
    @property
    def nbytes(self): return self.motion.nbytes+len(self._thickness)+len(self._inventory)+len(self._record)
    def descriptor(self): return json.loads(self._record)


@dataclass(frozen=True, slots=True)
class PlanarMaterialProjection:
    cohorts: tuple[MaterialCohort, ...]
    targets: tuple[PlanarGeometry, ...]
    projection_id: str
    account: object
    _record: bytes = field(repr=False)
    def _inside(self, i): return self.account.inside.reshape(3, len(self.cohorts), len(self.targets))[i]
    @property
    def volume_m3(self): return self._inside(0)
    @property
    def mass_kg(self): return self._inside(1)
    @property
    def enthalpy_j(self): return self._inside(2)
    @property
    def thickness_m(self): return self.volume_m3/np.array([g.area_m2 for g in self.targets])
    @property
    def outside(self): return self.account.outside.reshape(3, len(self.cohorts), -1)
    @property
    def nbytes(self): return self.account.nbytes+len(self._record)+sum(g.retained_bytes for g in self.targets)
    def descriptor(self): return json.loads(self._record)


class PreparedPlanarMaterials:
    """Source-bound material bridge for affine and compatible nodal motion.

    Cohort volume/mass/relative enthalpy stay with complete material parcels. The
    one retained latest view is derived, never silently used as a remapped state.
    Supplied motion is borrowed; close it separately after this owner is closed.
    """
    def __setattr__(self, name, value):
        object.__setattr__(self, name, value)

    def __init__(self, motion, cohorts, thickness_m, *, density_kg_m3, epoch_id,
                 datum_id, source_id, specific_enthalpy_j_kg=None, enthalpy_source=None,
                 context=None, budget=None, cancel=None):
        from atlas_tectonics.plates.deformation_network import PreparedDeformationNetwork
        from atlas_tectonics.history.planar_projection import PreparedPlanarProjection
        check_event(cancel, 'regional transport cancelled; no candidate published')
        self._budget = motion._budget if budget is None else select_budget(budget)
        # A separate budget must share the same root; do not evade a producer's
        # retained admission by running material operations under another envelope.
        def root(b):
            while b._parent is not None: b = b._parent
            return b
        if root(self._budget) is not root(motion._budget):
            raise TectonicsError('motion and materials need a shared resource ancestor')
        self.motion = motion
        reference = motion.evaluate(motion.time_s, cancel=cancel)
        polygons = _polygons(reference.polygons)
        ids = motion.triangle_ids if type(motion) is PreparedDeformationNetwork else motion.parcel_ids
        _catalogue(cohorts, motion.time_s)
        c, n = len(cohorts), len(polygons)
        for name, label in ((epoch_id, 'epoch'), (datum_id, 'datum'), (source_id, 'material source')): _name(name, label)
        if specific_enthalpy_j_kg is None:
            if enthalpy_source is not None: raise TectonicsError('enthalpy source without enthalpy field')
        elif input_shape(specific_enthalpy_j_kg) != (c, n):
            raise TectonicsError('specific enthalpy requires cohort,parcel shape')
        else: _name(enthalpy_source, 'enthalpy convention/source')
        lease = self._budget.reserve(160*c*n+reference.nbytes+32768*c+2*1024**2, category='planar-material-prepared')
        lease.__enter__(); ctx = None; owned = context is None
        try:
            ctx = ExecutionContext('scipy') if owned else context
            with PreparedPlanarProjection(polygons, polygons, source_ids=ids, target_ids=ids,
                                          source_id=source_id, budget=self._budget, cancel=cancel): pass
            h = read_array(thickness_m, 'cohort thickness', nonnegative=True)
            rho = read_array(density_kg_m3, 'density', nonnegative=True)
            heat = np.zeros_like(h) if specific_enthalpy_j_kg is None else read_array(specific_enthalpy_j_kg, 'specific enthalpy')
            with np.errstate(over='ignore', invalid='ignore', under='ignore'):
                volume = h*np.array([g.area_m2 for g in polygons]); mass = volume*rho[:, None]
                enthalpy = mass*heat
            if not all(np.isfinite(a).all() for a in (volume, mass, enthalpy)):
                raise TectonicsError('planar material inventories exceed numerical range')
            if np.any((h > 0) & (volume == 0)) or np.any((volume > 0) & (mass == 0)) or np.any((mass != 0)&(heat != 0)&(enthalpy == 0)):
                raise TectonicsError('positive material or nonzero enthalpy inventory underflows')
            self._lease = lease; self._context = ctx; self._owns_context = owned; self._closed = False
            self.cohorts = cohorts; self.parcel_ids = ids; self._reference = reference
            self._inventory = _immutable_bytes(np.stack((volume, mass, enthalpy)))
            self._rho = _immutable_bytes(rho)
            self._record = _json(dict(method='atlas.w08-planar-material.v1', motion=motion.plan_id,
                source=source_id, epoch=epoch_id, datum=datum_id, frame=polygons[0].frame_id,
                cohorts=[dict(cohort_id=k.cohort_id, material_id=k.material_id, origin_id=k.origin_id,
                              formation_time_s=k.formation_time_s) for k in cohorts], parcel_ids=ids,
                enthalpy_source=enthalpy_source, enthalpy_present=enthalpy_source is not None,
                execution=ctx.identity, geometry='retained-piecewise-constant-planar-parcels'))
            self.plan_id = record_id(content_record(json.loads(self._record)), self._inventory, self._rho, encode=_json)
            self._cache = None; self._cache_lease = None
            check_event(cancel, 'regional transport cancelled; no candidate published'); self._sealed = True
        except BaseException:
            lease.__exit__(None, None, None)
            if owned and ctx is not None: ctx.close()
            raise

    def _live(self, cancel=None):
        check_event(cancel, 'regional transport cancelled; no candidate published')

    def evaluate(self, time_s, *, cancel=None):
        self._live(cancel)
        result = self._evaluate(time_s, cancel=cancel)
        check_event(cancel, 'regional transport cancelled; no candidate published')
        return result

    def _evaluate(self, time_s, *, cancel=None):
        # Enclosing public operation verifies once before and after the complete
        # calculation; nested projection need not rehash the same source twice.
        with self._budget.reserve(128*len(self.cohorts)*len(self.parcel_ids)+65536,
                                  category='planar-material-output'):
            state = self.motion.evaluate(time_s, cancel=cancel)
            inventory = np.frombuffer(self._inventory).reshape(3, len(self.cohorts), len(self.parcel_ids))
            areas = np.array([g.area_m2 for g in state.polygons])
            expected = state.jacobian*np.array([g.area_m2 for g in self._reference.polygons])
            if np.any(np.abs(areas-expected) > MAP_ERROR*expected):
                raise TectonicsError('material geometry and finite Jacobian disagree')
            with np.errstate(over='raise', invalid='raise', divide='raise'):
                h = inventory[0]/areas
            if np.any((inventory[0] > 0) & (h == 0)): raise TectonicsError('deformed thickness underflows')
            record = dict(json.loads(self._record), plan=self.plan_id, motion_state=state.state_id, time_s=state.time_s)
            raw = _immutable_bytes(h)
            result = PlanarMaterialSnapshot(state, self.cohorts, record_id(content_record(record), raw, self._inventory, encode=_json), raw,
                                            self._inventory, _json(record))
            check_event(cancel, 'regional transport cancelled; no candidate published'); return result

    def project(self, time_s, targets, *, target_ids, exterior_id, source_id, cancel=None):
        from atlas_tectonics.history.planar_projection import PreparedPlanarProjection
        self._live(cancel); targets = _polygons(targets)
        _names(target_ids, len(targets), 'target IDs'); _name(exterior_id, 'retained exterior'); _name(source_id, 'view source')
        key = (float(time_s), tuple(g.geometry_id for g in targets), target_ids, exterior_id, source_id)
        if self._cache is not None and self._cache[0] == key: return self._cache[1]
        state = self._evaluate(time_s, cancel=cancel)
        with PreparedPlanarProjection(state.motion.polygons, targets, source_ids=self.parcel_ids,
                                      target_ids=target_ids, source_id=source_id, budget=self._budget, cancel=cancel) as p:
            account = p.apply(np.frombuffer(self._inventory).reshape(3*len(self.cohorts), -1), cancel=cancel)
            record = dict(state.descriptor(), state=state.state_id, target_ids=target_ids,
                          exterior_id=exterior_id, view_source=source_id, projection_plan=p.plan_id,
                          exterior_meaning='retained-outside-view-not-deleted-or-re-exported')
            result = PlanarMaterialProjection(self.cohorts, targets,
                record_id(content_record(record), account.inside.tobytes(), account.outside.tobytes(), encode=_json), account, _json(record))
        check_event(cancel, 'regional transport cancelled; no candidate published')
        if self._cache_lease is not None:
            self._cache_lease.__exit__(None, None, None)
            object.__setattr__(self, '_cache', None); object.__setattr__(self, '_cache_lease', None)
        lease = self._budget.reserve(result.nbytes+4096, category='planar-material-view-cache'); lease.__enter__()
        object.__setattr__(self, '_cache_lease', lease); object.__setattr__(self, '_cache', (key, result))
        return result

    def exchange(self, start_time_s, end_time_s, start_regions, end_regions, *,
                 region_ids, exterior_id, source_id, cancel=None):
        """Actual endpoint material transfers; moving regions retain relative motion.

        Field rows are volume for each cohort, then mass, then relative enthalpy.
        Source and destination axes include the explicitly named retained exterior.
        Crossing and returning to the same region is not counted as net export.
        """
        from atlas_tectonics.history.planar_exchange import planar_exchange
        self._live(cancel)
        start = scalar(start_time_s, 'exchange start'); end = scalar(end_time_s, 'exchange end')
        with self._budget.reserve(256*len(self.parcel_ids)+65536, category='planar-material-exchange'):
            first = self.motion.evaluate(start, cancel=cancel); last = self.motion.evaluate(end, cancel=cancel)
            between = last.deformation_gradient@np.linalg.inv(first.deformation_gradient)
            result = planar_exchange(first.polygons,last.polygons,between,
                np.frombuffer(self._inventory).reshape(3*len(self.cohorts),-1), start_regions=start_regions,
                end_regions=end_regions,parcel_ids=self.parcel_ids,region_ids=region_ids,exterior_id=exterior_id,
                source_id=source_id,budget=self._budget,cancel=cancel)
            record = dict(result.descriptor(), material_plan=self.plan_id, material=json.loads(self._record),
                start_time_s=start,end_time_s=end,start_motion=first.state_id,end_motion=last.state_id,
                field_order=[(quantity,c.cohort_id) for quantity in ('volume_m3','mass_kg','relative_enthalpy_j') for c in self.cohorts])
            result = replace(result,exchange_id=record_id(content_record(record),result._transfer,result._initial,result._final, encode=_json),_record=_json(record))
            check_event(cancel, 'regional transport cancelled; no candidate published'); return result

    def close(self):
        if not self._closed:
            if self._cache_lease is not None: self._cache_lease.__exit__(None, None, None)
            object.__setattr__(self, '_cache', None); object.__setattr__(self, '_closed', True)
            object.__setattr__(self, '_reference', None)
            self._lease.__exit__(None, None, None)
            if self._owns_context: self._context.close()
    def __enter__(self): self._live(); return self
    def __exit__(self, *args): self.close()
