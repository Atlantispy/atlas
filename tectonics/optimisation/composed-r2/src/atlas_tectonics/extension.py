"""W05 conservative prescribed listric motion, before load/support integration.

Fixed Eulerian columns. Only the hanging wall moves; its common-density cohorts
retain W02 formation histories and signed regional exchanges. No fault mechanics.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, field
import hashlib
import math
import numpy as np

from ._validation import TectonicsError, scalar, frozen, read_array, input_shape
from .materials import (MaterialCohort, MaterialState, MaterialBoundary, _name,
                        _json, _immutable_bytes, _account)
from .mesh import ColumnGrid1D
from .regional import _cancelled
from .remapping import _inventories, _publish, ale_timestep_limit
from .resources import select_budget, reserve_budgets
from .reuse import ExecutionContext, cached_ale_transport
from .storage import ArrayStore


MAX_EXTENSION_INTERVALS = 256


def _fractionate(fractions, thickness):
    with np.errstate(over='raise', invalid='raise'):
        values = fractions[:, None]*thickness[None, :]
    if np.any((fractions[:, None] > 0) & (thickness[None, :] > 0) & (values == 0)):
        raise TectonicsError('positive cohort inventory underflows')
    return values


def _within_budget(candidate, owner):
    node = candidate
    while node is not None:
        if node is owner:
            return
        node = node._parent
    raise TectonicsError('call/store budget must descend from the prepared run budget')


@dataclass(frozen=True, slots=True)
class ListricGeometry:
    crust_thickness_m: float
    detachment_depth_m: float
    surface_dip_rad: float
    trace_m: float
    source_id: str

    def __post_init__(self):
        _name(self.source_id, 'geometry source')
        for key in ('crust_thickness_m', 'detachment_depth_m', 'surface_dip_rad'):
            object.__setattr__(self, key, scalar(getattr(self, key), key, positive=True))
        object.__setattr__(self, 'trace_m', scalar(self.trace_m, 'trace'))
        if (self.detachment_depth_m >= self.crust_thickness_m or
                self.surface_dip_rad >= math.pi/2):
            raise TectonicsError('require 0 < depth < crust thickness and 0 < dip < pi/2')
        scalar(self.decay_length_m, 'fault decay length', positive=True)

    @property
    def decay_length_m(self):
        return self.detachment_depth_m/math.tan(self.surface_dip_rad)


def _mean_ramp(r):
    """1 - (1-exp(-r))/r, stable even when r is tiny; r > 0.

    This is the cell integral of the exponential ramp, not a point sample.
    The small-r polynomial has error below binary64 precision at r <= .01.
    """
    out = np.empty_like(r)
    small = r <= .01
    s = r[small]
    out[small] = s*(.5+s*(-1/6+s*(1/24+s*(-1/120+s*(1/720+s*(-1/5040+s/40320))))))
    s = r[~small]
    out[~small] = 1+np.expm1(-s)/s
    return out


def hangingwall_cell_means(grid, geometry, displacement_m=0., *, budget=None):
    """Analytically integrated translated initial H, an immutable geometry field.

    Explicitly limited to the declared exponential initial profile. This is not
    a replacement for evolution of arbitrary material arrays.
    """
    if type(grid) is not ColumnGrid1D or type(geometry) is not ListricGeometry:
        raise TectonicsError('typed grid and listric geometry required')
    a = scalar(displacement_m, 'horizontal displacement', nonnegative=True)
    with select_budget(budget).reserve(192*grid.cells+8192, category='extension-geometry'):
        try:
            with np.errstate(over='raise', invalid='raise', divide='raise'):
                edge = grid.edges_m-geometry.trace_m-a
                # Work with local active lengths, never differences of huge primitives.
                width = grid.widths_m
                if np.any(np.abs(np.diff(edge)-width) > 1e-12*width):
                    raise TectonicsError('translated coordinates do not resolve cell widths')
                lo = np.maximum(edge[:-1], 0.)
                hi = np.maximum(edge[1:], 0.)
                length = hi-lo
                active = length > 0
                result = np.zeros(grid.cells)
                r = length[active]/geometry.decay_length_m
                l = lo[active]/geometry.decay_length_m
                if np.any(r == 0) or np.any((lo[active] > 0) & (l == 0)):
                    raise TectonicsError('fault scale outside representable range')
                # <1-e^(-x/lambda)> = (1-e^(-lo/lambda)) + e^(-lo/lambda)*ramp(r).
                average = -np.expm1(-l)+np.exp(-l)*_mean_ramp(r)
                result[active] = geometry.detachment_depth_m*(length[active]/width[active])*average
                if (np.any(result < 0) or np.any(result > geometry.detachment_depth_m) or
                        np.any(result[active] == 0)):
                    raise TectonicsError('invalid or underflowed hanging-wall geometry')
                return frozen(result)
        except (FloatingPointError, OverflowError) as exc:
            raise TectonicsError('fault geometry exceeds numerical range') from exc


@dataclass(frozen=True, slots=True, init=False)
class ExtensionState:
    """Current material plus compact cumulative exchanges, not a trajectory copy.

    Retained returned states are charged by their owner, like W02 MaterialState.
    Construction is via a prepared mechanism; state_id binds all public content.
    """
    plan_id: str
    material: MaterialState
    intervals: int
    max_courant: float
    state_id: str
    _exchange: bytes = field(repr=False)

    @property
    def exchange_m2(self):
        """Cohort x (left,right), signed INTO the region; multiply by rho*W once."""
        return np.frombuffer(self._exchange, dtype=np.float64).reshape(len(self.material.cohorts), 2)

    @property
    def nbytes(self):
        return self.material.nbytes+len(self._exchange)


def _state(plan_id, material, intervals, maximum, exchange):
    payload = _immutable_bytes(exchange)
    record = dict(schema='atlas.w05-extension-state.v1', plan=plan_id,
                  material=material.state_id, intervals=intervals, max_courant=maximum)
    digest = hashlib.sha256(_json(record)+payload).hexdigest()
    result = object.__new__(ExtensionState)
    for key, value in (('plan_id', plan_id), ('material', material), ('intervals', intervals),
                       ('max_courant', maximum), ('_exchange', payload), ('state_id', digest)):
        object.__setattr__(result, key, value)
    return result


@dataclass(frozen=True, slots=True, init=False)
class PreparedListricExtension:
    """Source-bound fixed-grid W05 mechanism, reusing W02 native/cache machinery.

    The initial hanging wall may contain a spatially uniform mixture of named
    cohorts, all at the declared density. Arbitrary stratigraphy is not inferred.
    Source/runtime validation brackets each public operation, including cache use.
    """
    grid: ColumnGrid1D
    geometry: ListricGeometry
    density_kg_m3: float
    width_m: float
    velocity_m_s: float
    datum_id: str
    source_id: str
    execution_id: str
    plan_id: str
    initial: ExtensionState
    backend: str
    transport: str
    _footwall: bytes = field(repr=False)
    _velocity: bytes = field(repr=False)
    _zero: bytes = field(repr=False)
    _initial_inventory: bytes = field(repr=False)
    _fractions: bytes = field(repr=False)
    _context: object = field(repr=False, compare=False)
    _owns_context: bool = field(repr=False, compare=False)
    _budget: object = field(repr=False, compare=False)
    _lease: object = field(repr=False, compare=False)
    _closed: bool = field(repr=False, compare=False)

    def __init__(self, grid, geometry, *, velocity_m_s, density_kg_m3, width_m,
                 cohorts, fractions, time_s, epoch_id, datum_id, source_id,
                 backend='numba', transport='characteristic', context=None, budget=None, cancel=None):
        _cancelled(cancel)
        if type(grid) is not ColumnGrid1D or type(geometry) is not ListricGeometry:
            raise TectonicsError('typed ColumnGrid1D and ListricGeometry required')
        if not grid.edges_m[0] < geometry.trace_m < grid.edges_m[-1]:
            raise TectonicsError('domain must straddle the trace; left inflow is explicitly zero')
        if backend not in ('numba', 'reference'):
            raise TectonicsError('explicit numba/reference backend required')
        if transport not in ('characteristic', 'muscl'):
            raise TectonicsError('explicit characteristic/muscl transport required')
        if type(cohorts) is not tuple or not 1 <= len(cohorts) <= 64:
            raise TectonicsError('one to 64 named constant-density cohorts required')
        if grid.cells > 65536:
            raise TectonicsError('bounded W05 mechanism permits at most 65536 cells')
        if input_shape(fractions) != (len(cohorts),):
            raise TectonicsError('one fraction for each cohort required')
        fr = read_array(fractions, 'initial fractions', nonnegative=True)
        if math.fsum(fr) != 1.:
            raise TectonicsError('initial fractions must sum to one; no renormalisation')
        rho = scalar(density_kg_m3, 'crust density', positive=True)
        width = scalar(width_m, 'transverse width', positive=True)
        u = scalar(velocity_m_s, 'horizontal velocity', nonnegative=True)
        _name(datum_id, 'datum'); _name(source_id, 'mechanism source')
        _name(source_id+':right', 'boundary source')
        resource = select_budget(budget)
        retained = 8*len(cohorts)*grid.cells+32*grid.cells+128*len(cohorts)+16384
        lease = resource.reserve(retained, category='extension-prepared')
        lease.__enter__()
        owned = context is None
        ctx = None
        try:
            ctx = ExecutionContext(backend) if owned else context
            if type(ctx) is not ExecutionContext or ctx.backend != backend:
                raise TectonicsError('execution context/backend mismatch')
            execution_id = ctx.identity
            with resource.reserve(48*len(cohorts)*grid.cells+64*grid.cells+8192,
                                  category='extension-initialise'):
                h = hangingwall_cell_means(grid, geometry, budget=resource)
                material = MaterialState(grid, cohorts, _fractionate(fr, h),
                                         time_s=time_s, epoch_id=epoch_id, budget=resource)
                footwall = frozen(geometry.crust_thickness_m-h)
                if np.any(footwall <= 0):
                    raise TectonicsError('positive stationary footwall required')
                fields = dict(grid=grid, geometry=geometry, density_kg_m3=rho,
                              width_m=width, velocity_m_s=u, datum_id=datum_id,
                              source_id=source_id, backend=backend, transport=transport, execution_id=execution_id,
                              _footwall=_immutable_bytes(footwall),
                              _velocity=_immutable_bytes(np.full(grid.cells+1, u)),
                              _zero=_immutable_bytes(np.zeros(grid.cells+1)),
                              _initial_inventory=_immutable_bytes(_inventories(material.thickness_m, grid, backend)),
                              _fractions=_immutable_bytes(fr),
                              _context=ctx, _owns_context=owned, _budget=resource,
                              _lease=lease, _closed=False)
                for key, value in fields.items():
                    object.__setattr__(self, key, value)
                identity = dict(method='atlas.w05-listric-motion.v1', geometry=asdict(geometry),
                                grid=grid.grid_id, initial_material=material.state_id,
                                velocity_m_s=u, density_kg_m3=rho, width_m=width,
                                datum_id=datum_id, source_id=source_id, execution=execution_id,
                                scheme=transport, max_intervals=MAX_EXTENSION_INTERVALS)
                plan_id = hashlib.sha256(_json(identity)).hexdigest()
                object.__setattr__(self, 'plan_id', plan_id)
                object.__setattr__(self, 'initial', _state(plan_id, material, 0, 0., np.zeros((len(cohorts), 2))))
            ctx.verify(); _cancelled(cancel)
        except BaseException:
            lease.__exit__(None, None, None)
            if owned and ctx is not None:
                ctx.close()
            raise

    @property
    def footwall_thickness_m(self):
        return np.frombuffer(self._footwall, dtype=np.float64)

    def _check(self, state):
        if self._closed:
            raise TectonicsError('extension preparation is closed')
        if (type(state) is not ExtensionState or state.plan_id != self.plan_id or
                state.material.grid != self.grid or state.material.cohorts != self.initial.material.cohorts or
                state.material.epoch_id != self.initial.material.epoch_id or
                state.material.time_s < self.initial.material.time_s):
            raise TectonicsError('state belongs to a different extension reference')

    def advance(self, state, *, time_s, steps=1, store=None, controller=None,
                cache_policy=None, budget=None, cancel=None):
        """Advance equal requested intervals, retaining only current material/accounts.

        A public call is one verified execution; internal W02 transitions keep
        their normal safety/identity/cache checks. No stored state is mutated.
        Characteristic transport integrates the prescribed profile directly at
        the requested time (steps=1), without repeated interpolation or CFL
        substeps. It cannot accept arbitrary modified material. MUSCL is the
        general W02 comparison route; only that route has per-step result caching.
        """
        self._check(state); _cancelled(cancel); self._context.verify()
        end = scalar(time_s, 'target time')
        if end < state.material.time_s:
            raise TectonicsError('extension time cannot move backwards')
        if type(steps) is not int or steps < 1 or state.intervals+steps > MAX_EXTENSION_INTERVALS:
            raise TectonicsError('positive step count within 256 cumulative intervals required')
        if self.transport == 'characteristic' and (steps != 1 or any(
                v is not None for v in (store, controller, cache_policy))):
            raise TectonicsError('characteristic outputs require steps=1 and no per-step cache options')
        duration = scalar(end-state.material.time_s, 'advance duration', nonnegative=True)
        if state.material.time_s+duration != end:
            raise TectonicsError('requested endpoint is not representable by the elapsed time')
        if end == state.material.time_s:
            return state
        caller = self._budget if budget is None else select_budget(budget)
        _within_budget(caller, self._budget)
        if store is not None:
            if not isinstance(store, ArrayStore):
                raise TectonicsError('store must be an ArrayStore')
            _within_budget(store._budget, self._budget)
            # One active compute envelope must also descend from the store's
            # envelope: sibling allowances cannot silently bypass each other.
            _within_budget(caller, store._budget)
        # Also include a supplied store's envelope, even on its cheap-work bypass.
        budgets = (self._budget, caller) + ((store._budget,) if store is not None else ())
        c, n = len(state.material.cohorts), self.grid.cells
        with reserve_budgets(48*c*n+256*c+32768, *budgets, category='extension-advance'):
            if self.transport == 'characteristic':
                result = self._characteristic(state, end, budget=caller)
                _cancelled(cancel); self._context.verify()
                return result
            u = np.frombuffer(self._velocity, dtype=np.float64)
            zero = np.frombuffer(self._zero, dtype=np.float64)
            left = MaterialBoundary('open', {}, self.source_id+':left')
            right = MaterialBoundary('open', None, self.source_id+':right')
            start = state.material.time_s
            limit = ale_timestep_limit(state.material, u, zero, left=left, right=right,
                                       budget=caller)
            nominal = scalar((end-start)/steps, 'step duration', positive=True)
            if limit is not None and nominal > limit:
                raise TectonicsError('requested extension intervals exceed W02 CFL; choose more steps')
            material = state.material
            exchange = state.exchange_m2.copy()
            correction = np.zeros_like(exchange)
            maximum = state.max_courant
            for i in range(steps):
                target = end if i == steps-1 else start+(end-start)*((i+1)/steps)
                dt = scalar(target-material.time_s, 'resolved step duration', positive=True)
                if material.time_s+dt != target:
                    raise TectonicsError('requested substep endpoint is not representable')
                transition = cached_ale_transport(material, u, zero, dt, left=left, right=right,
                    scheme='muscl', backend=self.backend, store=store, controller=controller,
                    cache_policy=cache_policy, context=self._context, budget=caller, cancel=cancel)
                material = transition.state
                if material.time_s != target:
                    raise TectonicsError('transport did not reach the requested endpoint')
                delta = transition.accounts[:, 6:8]
                # Compensated running exchanges, fixed size rather than an interval list.
                total = exchange+delta
                correction += np.where(np.abs(exchange) >= np.abs(delta),
                    (exchange-total)+delta, (delta-total)+exchange)
                exchange = total
                maximum = max(maximum, float(np.max(transition.accounts[:, 5])))
            exchange += correction
            before = np.frombuffer(self._initial_inventory, dtype=np.float64)
            after = _inventories(material.thickness_m, self.grid, self.backend)
            for b, a, (lx, rx) in zip(before, after, exchange):
                _account(float(b), float(a), float(lx), float(rx), maximum)
            result = _state(self.plan_id, material, state.intervals+steps, maximum, exchange)
            _cancelled(cancel); self._context.verify()
            return result

    def _characteristic(self, state, end, *, budget):
        """Exact cell integrals and independently integrated boundary flux.

        Valid ONLY for this preparation's fixed exponential family, constant
        velocity and constant cohort fractions. Values come from the initial
        characteristic, not re-interpolation of previous cell averages.
        """
        elapsed = scalar(end-self.initial.material.time_s, 'elapsed time', positive=True)
        if self.initial.material.time_s+elapsed != end:
            raise TectonicsError('initial-to-output time is unrepresentable')
        displacement = scalar(self.velocity_m_s*elapsed, 'displacement', nonnegative=True)
        if self.velocity_m_s > 0 and displacement == 0:
            raise TectonicsError('prescribed displacement underflows')
        h = hangingwall_cell_means(self.grid, self.geometry, displacement, budget=budget)
        fractions = np.frombuffer(self._fractions, dtype=np.float64)
        values = _fractionate(fractions, h)
        # Integral of H0(R-s), s=0..a. Do not infer boundary flux by
        # subtracting inventories: that would make the balance check circular.
        right = float(self.grid.edges_m[-1]-self.geometry.trace_m)
        length = min(displacement, right)
        exported = 0.
        if length > 0:
            lo = max(right-displacement, 0.)/self.geometry.decay_length_m
            r = scalar(length/self.geometry.decay_length_m, 'swept fault interval', positive=True)
            mean = -math.expm1(-lo)+math.exp(-lo)*float(_mean_ramp(np.array([r]))[0])
            exported = scalar(self.geometry.detachment_depth_m*length*mean,
                              'integrated right export', positive=True)
        exchange = np.zeros((len(fractions), 2))
        exchange[:, 1] = -_fractionate(fractions, np.array([exported]))[:, 0]
        before = np.frombuffer(self._initial_inventory, dtype=np.float64)
        after = _inventories(values, self.grid, self.backend)
        swept = scalar(self.velocity_m_s*(end-state.material.time_s)/float(np.min(self.grid.widths_m)),
                       'swept-cell ratio', nonnegative=True)
        accounts = [_account(float(b), float(a), float(lx), float(rx), swept)
                    for b, a, (lx, rx) in zip(before, after, exchange)]
        record = dict(operation='listric-characteristic-v1', plan=self.plan_id,
                      initial_material=self.initial.material.state_id,
                      displacement_m=displacement, cumulative_cohort_accounts=accounts,
                      account_reference='initial_material', execution=self.execution_id)
        material = _publish(state.material, self.grid, values, end, record, budget=budget)
        return _state(self.plan_id, material, state.intervals+1,
                      max(state.max_courant, swept), exchange)

    def geometry_fields(self, state, *, budget=None):
        """Immutable columns: H, F, Hc and unflexed cell-mean surface change (m)."""
        self._check(state); self._context.verify()
        resource = self._budget if budget is None else select_budget(budget)
        _within_budget(resource, self._budget)
        with reserve_budgets(96*self.grid.cells+8192, self._budget, resource,
                            category='extension-output'):
            h = state.material.total_thickness(backend=self.backend, budget=resource)
            h0 = self.initial.material.total_thickness(backend=self.backend, budget=resource)
            f = self.footwall_thickness_m
            result = frozen(np.column_stack((h, f, f+h, h-h0)))
        self._context.verify()
        return result

    def close(self):
        if not self._closed:
            object.__setattr__(self, '_closed', True)
            try:
                if self._owns_context:
                    self._context.close()
            finally:
                self._lease.__exit__(None, None, None)

    def __enter__(self):
        self._check(self.initial)
        return self

    def __exit__(self, *args):
        self.close()
