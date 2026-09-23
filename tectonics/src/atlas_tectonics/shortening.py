"""W08 prescribed finite plane-strain shortening of retained W02 parcels.

Constant-property piecewise-constant parcels; no remap at intermediate outputs.
The complete moving domain is retained. A fixed-grid crop is a derived view,
with separately named exterior inventories, never a new transported state.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
import hashlib
import json
import math
import numpy as np

from ._validation import TectonicsError, scalar, read_array, input_shape
from .materials import MaterialState, _json, _name, _immutable_bytes
from .mesh import ColumnGrid1D
from .regional import _cancelled
from .remapping import _publish
from .resources import select_budget
from .reuse import ExecutionContext


MAX_SHORTENING_INTERVALS = 256
_ROUND = float(128*np.finfo(float).eps)
_GEOMETRY = 1e-12


def _id(record, *buffers):
    h = hashlib.sha256(_json(record))
    for buf in buffers:
        h.update(b'\0'); h.update(buf)
    return h.hexdigest()


def _sum_rows(values):
    return np.array([math.fsum(map(float, row)) for row in values])


def _balance(before, inside, outside):
    # Signed relative enthalpies can cancel. Scale by constituent stocks, not
    # a near-zero net heat balance, and compensate the complete residual.
    try:
        residual = math.fsum((*inside, *outside, *(-before)))
        scale = math.fsum((*np.abs(before), *np.abs(inside), *np.abs(outside)))
    except OverflowError as exc:
        raise TectonicsError('shortening account exceeds numerical range') from exc
    if not math.isfinite(residual) or abs(residual) > _ROUND*scale:
        raise TectonicsError('shortening extensive account does not reconcile')
    return residual


@dataclass(frozen=True, slots=True)
class ShorteningInterval:
    """Until end_time_s, v(x)=strain_rate_s*(x-anchor_m)+translation_m_s."""
    end_time_s: float
    strain_rate_s: float
    translation_m_s: float
    anchor_m: float
    source_id: str

    def __post_init__(self):
        for name in ('end_time_s', 'strain_rate_s', 'translation_m_s', 'anchor_m'):
            object.__setattr__(self, name, scalar(getattr(self, name), name))
        _name(self.source_id, 'history source')
        if self.strain_rate_s > 0:
            raise TectonicsError('shortening requires nonpositive strain rate; extension is a separate route')


@dataclass(frozen=True, slots=True)
class ShorteningState:
    plan_id: str
    material: MaterialState
    stretch: float
    translation_m: float
    intervals: int
    state_id: str

    @property
    def nbytes(self):
        return self.material.nbytes+self.material.grid.nbytes+len(self.material._transition_payload)


def _state(plan_id, material, stretch, shift, intervals):
    key = _id(dict(method='w08-shortening-state-v1', plan=plan_id,
                   material=material.state_id, stretch=stretch,
                   local_translation_m=shift, intervals=intervals))
    return ShorteningState(plan_id, material, stretch, shift, intervals, key)


@dataclass(frozen=True, slots=True)
class ShorteningProjection:
    material: MaterialState
    projection_id: str
    _fields: bytes
    _outside: bytes
    _record: bytes

    def _field(self, index):
        return np.frombuffer(self._fields, np.float64).reshape(
            3, len(self.material.cohorts), self.material.grid.cells)[index]

    def _exterior(self, index):
        return np.frombuffer(self._outside, np.float64).reshape(
            3, len(self.material.cohorts), 2)[index]

    @property
    def volume_m3(self): return self._field(0)
    @property
    def mass_kg(self): return self._field(1)
    @property
    def enthalpy_j(self): return self._field(2)
    @property
    def outside_volume_m3(self): return self._exterior(0)
    @property
    def outside_mass_kg(self): return self._exterior(1)
    @property
    def outside_enthalpy_j(self): return self._exterior(2)
    @property
    def nbytes(self):
        return (self.material.nbytes+self.material.grid.nbytes+len(self.material._transition_payload)
                +len(self._fields)+len(self._outside)+len(self._record))
    def descriptor(self): return json.loads(self._record)


def boundary_flux_kg_s(*, thickness_m, density_kg_m3, width_m,
                       material_normal_velocity_m_s, boundary_normal_velocity_m_s):
    """Signed outward mass rate; both velocities use the SAME outward normal."""
    h = scalar(thickness_m, 'thickness', nonnegative=True)
    rho = scalar(density_kg_m3, 'density', positive=True)
    width = scalar(width_m, 'boundary length/strike width', positive=True)
    u = scalar(material_normal_velocity_m_s, 'material normal velocity')
    ub = scalar(boundary_normal_velocity_m_s, 'boundary normal velocity')
    return scalar(h*rho*width*(u-ub), 'boundary mass flux')


def _segment(stretch, shift, event, duration, origin):
    z = scalar(event.strain_rate_s*duration, 'finite strain exponent')
    g = scalar(math.exp(z), 'finite stretch', positive=True)
    if z != 0 and g == 1:
        raise TectonicsError('finite strain is not resolvable in binary64')
    em1 = math.expm1(z)
    relative = 1. if z == 0 else em1/z
    s = scalar(stretch*g, 'composed finite stretch', positive=True)
    b = scalar(math.fsum((g*shift, -(event.anchor_m-origin)*em1,
                         event.translation_m_s*duration*relative)), 'composed translation')
    return s, b


def _overlaps(x, y):
    """Sorted union produces sparse intersections without an Ns*Nt matrix."""
    lo, hi = max(x[0], y[0]), min(x[-1], y[-1])
    if hi <= lo:
        return np.empty(0, np.int64), np.empty(0, np.int64), np.empty(0)
    edges = np.union1d(x[(x > lo) & (x < hi)], y[(y > lo) & (y < hi)])
    edges = np.r_[lo, edges, hi]
    donor = np.searchsorted(x, edges[:-1], side='right')-1
    target = np.searchsorted(y, edges[:-1], side='right')-1
    fraction = np.diff(edges)/np.diff(x)[donor]
    return donor, target, fraction


class PreparedShortening:
    """Source-bound exact history, compact parcel state and one verified view cache.

    A query integrates declared segments, not a simulation-timestep loop. All
    queries originate at the same retained reference; cropped views cannot be
    fed back as if they were an exact continuation. Caller-held output payloads
    outside the latest cache need the caller's retained-memory allowance.
    """
    def __setattr__(self, name, value):
        if getattr(self, '_sealed', False):
            raise AttributeError('prepared shortening is immutable')
        object.__setattr__(self, name, value)

    def __init__(self, initial, histories, *, density_kg_m3, width_m, datum_id,
                 source_id, specific_enthalpy_j_kg=None, enthalpy_source=None,
                 context=None, budget=None, cancel=None):
        _cancelled(cancel)
        if type(initial) is not MaterialState or type(initial.grid) is not ColumnGrid1D:
            raise TectonicsError('explicit W02 MaterialState on ColumnGrid1D required')
        c, n = len(initial.cohorts), initial.grid.cells
        if not 1 <= c <= 64 or n > 65536:
            raise TectonicsError('bounded shortening permits 64 cohorts and 65536 parcels')
        if (type(histories) is not tuple or not 1 <= len(histories) <= MAX_SHORTENING_INTERVALS
                or any(type(e) is not ShorteningInterval for e in histories)):
            raise TectonicsError('one to 256 explicit shortening history intervals required')
        start = initial.time_s
        for e in histories:
            if e.end_time_s <= start:
                raise TectonicsError('history endpoints must strictly increase from the initial epoch')
            scalar(e.end_time_s-start, 'history duration', positive=True)
            start = e.end_time_s
        _name(datum_id, 'datum'); _name(source_id, 'motion source')
        if input_shape(density_kg_m3) != (c,):
            raise TectonicsError('one constant reference density per cohort required')
        if specific_enthalpy_j_kg is None:
            if enthalpy_source is not None:
                raise TectonicsError('enthalpy provenance without an enthalpy field')
        else:
            if input_shape(specific_enthalpy_j_kg) != (c, n):
                raise TectonicsError('specific enthalpy must have cohort,parcel shape')
            _name(enthalpy_source, 'enthalpy source and thermodynamic convention')
        resource = select_budget(budget)
        lease = resource.reserve(96*c*n+256*n+4096*c+4096*len(histories)+2*1024**2,
                                 category='shortening-prepared')
        lease.__enter__()
        ctx = None; owned = context is None
        try:
            rho = read_array(density_kg_m3, 'density', nonnegative=True)
            if np.any(rho <= 0): raise TectonicsError('positive reference densities required')
            width = scalar(width_m, 'strike width', positive=True)
            hspec = (np.zeros((c, n)) if specific_enthalpy_j_kg is None else
                     read_array(specific_enthalpy_j_kg, 'specific enthalpy'))
            with np.errstate(over='ignore', invalid='ignore', divide='ignore'):
                volume = initial.thickness_m*(initial.grid.widths_m*width)
                mass = volume*rho[:, None]
                heat = mass*hspec
            if not all(np.isfinite(a).all() for a in (volume, mass, heat)):
                raise TectonicsError('material or thermal inventory exceeds numerical range')
            if (np.any((initial.thickness_m > 0) & (volume == 0)) or
                    np.any((volume > 0) & (mass == 0)) or
                    np.any((mass != 0) & (hspec != 0) & (heat == 0))):
                raise TectonicsError('positive material or thermal inventory underflows')
            ctx = ExecutionContext('reference') if owned else context
            if type(ctx) is not ExecutionContext or ctx.backend != 'reference':
                raise TectonicsError('reference execution context required for exact shortening')
            self._budget = resource; self._lease = lease; self._context = ctx
            self._owns_context = owned; self._closed = False
            self.execution_id = ctx.identity
            self.histories = histories; self.width_m = width
            self.datum_id = datum_id; self.source_id = source_id
            self.enthalpy_source = enthalpy_source
            self._rho = _immutable_bytes(rho)
            self._inventory = _immutable_bytes(np.stack((volume, mass, heat)))
            self._reference = initial
            origin = float(initial.grid.edges_m[0]); self._origin = origin
            maps = [(1., 0.)]; times = [initial.time_s]
            for e in histories:
                maps.append(_segment(*maps[-1], e, e.end_time_s-times[-1], origin))
                times.append(e.end_time_s)
            self._maps = tuple(maps); self._times = tuple(times)
            self.plan_id = _id(dict(method='atlas.w08-shortening.v1', initial=initial.state_id,
                history=[asdict(e) for e in histories], width_m=width, datum=datum_id,
                source=source_id, enthalpy_source=enthalpy_source, execution=self.execution_id,
                representation='retained-piecewise-constant-material-parcels'), self._rho, self._inventory)
            self.initial = _state(self.plan_id, initial, 1., 0., 0)
            self._cache = None; self._cache_lease = None
            ctx.verify(); _cancelled(cancel)
            self._sealed = True
        except BaseException:
            lease.__exit__(None, None, None)
            if owned and ctx is not None: ctx.close()
            raise

    @property
    def density_kg_m3(self): return np.frombuffer(self._rho, np.float64)

    def _inventories(self):
        return np.frombuffer(self._inventory, np.float64).reshape(
            3, len(self._reference.cohorts), self._reference.grid.cells)

    def _live(self, cancel=None):
        if self._closed: raise TectonicsError('shortening preparation is closed')
        _cancelled(cancel); self._context.verify()

    def _map(self, time_s):
        now = scalar(time_s, 'query time')
        if not self._times[0] <= now <= self._times[-1]:
            raise TectonicsError('query lies outside the supplied history')
        j = int(np.searchsorted(self._times, now, side='right'))-1
        if now == self._times[j]: return (*self._maps[j], j)
        return (*_segment(*self._maps[j], self.histories[j], now-self._times[j], self._origin), j+1)

    def _edges(self, stretch, shift):
        old = self._reference.grid
        with np.errstate(over='raise', invalid='raise'):
            edges = self._origin + ((old.edges_m-self._origin)*stretch+shift)
            widths = np.diff(edges); expected = old.widths_m*stretch
            displacement = (old.edges_m-self._origin)*(stretch-1.)+shift
            face_scale = np.r_[expected[0], np.minimum(expected[:-1], expected[1:]), expected[-1]]
        if (not np.isfinite(edges).all() or np.any(widths <= 0) or
                np.any(np.abs(widths-expected) > _GEOMETRY*expected) or
                np.any((displacement != 0) & (edges == old.edges_m)) or
                np.any(np.abs((edges-old.edges_m)-displacement) > _GEOMETRY*face_scale)):
            raise TectonicsError('finite motion is unresolvable in this coordinate frame')
        return edges

    def _check(self, state):
        if self._closed: raise TectonicsError('shortening preparation is closed')
        if (type(state) is not ShorteningState or state.plan_id != self.plan_id or
                state.material.cohorts != self._reference.cohorts or
                state.material.epoch_id != self._reference.epoch_id or
                state.material.grid.frame_id != self._reference.grid.frame_id):
            raise TectonicsError('state belongs to a different shortening history')
        s, b, j = self._map(state.material.time_s)
        if ((s, b, j) != (state.stretch, state.translation_m, state.intervals) or
                _state(self.plan_id, state.material, s, b, j).state_id != state.state_id or
                not np.array_equal(state.material.grid.edges_m, self._edges(s, b))):
            raise TectonicsError('state geometry/history identity mismatch')

    def evaluate(self, time_s, *, cancel=None):
        self._live(cancel)
        s, b, j = self._map(time_s)
        if time_s == self._reference.time_s: return self.initial
        c, n = len(self._reference.cohorts), self._reference.grid.cells
        with self._budget.reserve(64*c*n+192*n+8192*c+32768, category='shortening-evaluate'):
            grid = ColumnGrid1D(self._edges(s, b), frame_id=self._reference.grid.frame_id,
                                budget=self._budget)
            with np.errstate(over='raise', invalid='raise', divide='raise'):
                values = self._inventories()[0]/(grid.widths_m*self.width_m)
            if np.any((self._inventories()[0] > 0) & (values == 0)):
                raise TectonicsError('deformed thickness underflows')
            material = _publish(self._reference, grid, values, float(time_s),
                dict(operation='w08-exact-finite-shortening-v1', plan=self.plan_id,
                     stretch=s, local_translation_m=b, history_segments=j), budget=self._budget)
            result = _state(self.plan_id, material, s, b, j)
            _cancelled(cancel); self._context.verify()
            return result

    def project(self, state, target_grid, *, exterior_ids, source_id, cancel=None):
        self._live(cancel); self._check(state)
        if (type(target_grid) is not ColumnGrid1D or target_grid.cells > 65536 or
                target_grid.frame_id != state.material.grid.frame_id):
            raise TectonicsError('bounded target mesh in the same explicit frame required')
        if type(exterior_ids) is not tuple or len(exterior_ids) != 2:
            raise TectonicsError('named left and right exterior destinations required')
        for name in exterior_ids: _name(name, 'exterior destination')
        _name(source_id, 'projection geometry source')
        key = (state.state_id, target_grid.grid_id, exterior_ids, source_id)
        if self._cache is not None and self._cache[0] == key:
            _cancelled(cancel); return self._cache[1]
        c, ns, nt = len(state.material.cohorts), state.material.grid.cells, target_grid.cells
        with self._budget.reserve(160*c*(ns+nt)+256*(ns+nt)+8192*c+32768,
                                  category='shortening-project'):
            x, y = state.material.grid.edges_m, target_grid.edges_m
            donor, target, fraction = _overlaps(x, y)
            fields = np.zeros((3, c, nt))
            inventory = self._inventories()
            if len(donor):
                starts = np.r_[0, np.flatnonzero(np.diff(target))+1]
                fields[:, :, target[starts]] = np.add.reduceat(
                    inventory[:, :, donor]*fraction, starts, axis=2)
            widths = np.diff(x)
            left = np.maximum(0., np.minimum(x[1:], y[0])-x[:-1])/widths
            right = np.maximum(0., x[1:]-np.maximum(x[:-1], y[-1]))/widths
            outside = np.empty((3, c, 2))
            residuals = []
            for k in range(3):
                outside[k, :, 0] = _sum_rows(inventory[k]*left)
                outside[k, :, 1] = _sum_rows(inventory[k]*right)
                for row in range(c):
                    residuals.append(_balance(inventory[k, row], fields[k, row], outside[k, row]))
            if not np.isfinite(fields).all() or not np.isfinite(outside).all():
                raise TectonicsError('projection inventory exceeds numerical range')
            values = fields[0]/(target_grid.widths_m*self.width_m)
            record = dict(operation='w08-retained-parcel-projection-v1', source=state.state_id,
                plan=self.plan_id, target=target_grid.grid_id, geometry_source=source_id,
                exterior_ids=exterior_ids, frame=target_grid.frame_id, datum=self.datum_id,
                enthalpy_source=self.enthalpy_source, enthalpy_present=self.enthalpy_source is not None,
                exterior='retained-outside-view-not-deleted-or-re-exported', account_residuals=residuals)
            material = _publish(state.material, target_grid, values, state.material.time_s,
                                record, budget=self._budget)
            buffers = fields.tobytes(), outside.tobytes(), _json(record)
            result = ShorteningProjection(material, _id(record, *buffers), *buffers)
            self._context.verify(); _cancelled(cancel)
            # One retained exact view. Replacing it never changes scientific state.
            if self._cache_lease is not None:
                self._cache_lease.__exit__(None, None, None)
                object.__setattr__(self, '_cache_lease', None)
                object.__setattr__(self, '_cache', None)
            lease = self._budget.reserve(result.nbytes+4096, category='shortening-view-cache')
            lease.__enter__()
            object.__setattr__(self, '_cache_lease', lease)
            object.__setattr__(self, '_cache', (key, result))
            return result

    def close(self):
        if not self._closed:
            try:
                self._context.verify()
            finally:
                if self._cache_lease is not None: self._cache_lease.__exit__(None, None, None)
                object.__setattr__(self, '_cache', None)
                object.__setattr__(self, '_closed', True)
                self._lease.__exit__(None, None, None)
                if self._owns_context: self._context.close()

    def __enter__(self):
        self._live(); return self

    def __exit__(self, *args): self.close()
