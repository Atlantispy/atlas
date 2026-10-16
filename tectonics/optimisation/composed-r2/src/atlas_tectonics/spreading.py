"""W06.2: exact constant-velocity ridge birth with finite reference-mass feeds.

An empty initial ocean, two continuously born strips, fixed Eulerian cells.
No melting, thermal evolution, water, support, plate-history events or restart
store is supplied here. Array fields are projections, not geological cohorts.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, field
import hashlib
import math
import numpy as np

from ._validation import TectonicsError, scalar, frozen
from .materials import _name, _json, _immutable_bytes, _account, _ROUNDOFF
from .mesh import ColumnGrid1D
from .regional import _cancelled
from .resources import select_budget, reserve_budgets
from .reuse import ExecutionContext


MAX_SPREADING_INTERVALS = 256
MAX_SPREADING_CELLS = 65536
MAX_SPREADING_PHASES = 16


@dataclass(frozen=True, slots=True)
class RidgeMotion:
    ridge_position_m: float
    left_velocity_m_s: float
    right_velocity_m_s: float
    ridge_velocity_m_s: float
    left_plate_id: str
    right_plate_id: str
    ridge_id: str
    event_id: str
    source_id: str

    def __post_init__(self):
        for key in ('ridge_position_m', 'left_velocity_m_s', 'right_velocity_m_s',
                    'ridge_velocity_m_s'):
            object.__setattr__(self, key, scalar(getattr(self, key), key))
        for key in ('left_plate_id', 'right_plate_id', 'ridge_id', 'event_id', 'source_id'):
            _name(getattr(self, key), key)
        if self.left_plate_id == self.right_plate_id:
            raise TectonicsError('distinct left and right plates required')
        if self.left_velocity_m_s > 0 or self.right_velocity_m_s < 0:
            raise TectonicsError('this fixed-window route requires outward plate velocities')
        scalar(self.ridge_velocity_m_s-self.left_velocity_m_s, 'left half rate', positive=True)
        scalar(self.right_velocity_m_s-self.ridge_velocity_m_s, 'right half rate', positive=True)
        scalar(self.right_velocity_m_s-self.left_velocity_m_s, 'full rate', positive=True)


@dataclass(frozen=True, slots=True)
class SpreadingPhase:
    """One fixed-thickness reference-density phase and its finite external feed."""
    phase_id: str
    source_id: str
    thickness_m: float
    density_kg_m3: float
    stock_kg: float

    def __post_init__(self):
        _name(self.phase_id, 'phase'); _name(self.source_id, 'finite feed')
        for key in ('thickness_m', 'density_kg_m3'):
            object.__setattr__(self, key, scalar(getattr(self, key), key, positive=True))
        object.__setattr__(self, 'stock_kg', scalar(self.stock_kg, 'stock', nonnegative=True))


@dataclass(frozen=True, slots=True)
class BirthStrip:
    """Full (unclipped) affine birth history; offsets are relative to plan.time_s.

    Cooling onset equals accretion in this selected hot-birth family only.
    Spatially interpolate offsets within the strip, never across the ridge.
    Zero-width initial strips describe the event but contain no material.
    """
    side: str
    left_m: float
    right_m: float
    birth_offset_left_s: float
    birth_offset_right_s: float
    plate_id: str
    ridge_id: str
    event_id: str


def _product(*values):
    result = scalar(math.prod(values), 'spreading product', nonnegative=True)
    if result == 0 and all(v > 0 for v in values):
        raise TectonicsError('positive spreading quantity underflows')
    return result


def _geometry_inputs(grid, motion, elapsed_s):
    if type(grid) is not ColumnGrid1D or type(motion) is not RidgeMotion:
        raise TectonicsError('typed grid and RidgeMotion required')
    if grid.cells > MAX_SPREADING_CELLS:
        raise TectonicsError('spreading cell budget exceeded')
    age = scalar(elapsed_s, 'elapsed time', nonnegative=True)
    edge = grid.edges_m
    r0 = motion.ridge_position_m
    if not edge[0] < r0 < edge[-1]:
        raise TectonicsError('initial ridge must lie strictly inside source window')
    try:
        positions = tuple(scalar(math.fsum((r0, u*age)), 'advected coordinate') for u in
                          (motion.left_velocity_m_s, motion.ridge_velocity_m_s,
                           motion.right_velocity_m_s))
    except (OverflowError, ValueError) as exc:
        raise TectonicsError('spreading coordinates exceed numerical range') from exc
    left, ridge, right = positions
    if not edge[0] < ridge < edge[-1]:
        raise TectonicsError('active ridge leaves represented source window')
    if age > 0:
        for actual, rate in ((ridge-left, motion.ridge_velocity_m_s-motion.left_velocity_m_s),
                             (right-ridge, motion.right_velocity_m_s-motion.ridge_velocity_m_s)):
            expected = _product(rate, age)
            coordinate_roundoff = 2*max(math.ulp(v) for v in positions)
            if actual <= 0 or abs(actual-expected) > _ROUNDOFF*expected+coordinate_roundoff:
                raise TectonicsError('coordinates cannot resolve born strip width')
    return age, positions


def ridge_cell_geometry(grid, motion, elapsed_s, *, budget=None, cancel=None):
    """Immutable (side,cell,3): occupied width, youngest age, oldest age, in m/s/s.

    Width > 0 is the validity mask; absent cells have three zeros, not a valid
    zero-age ocean. Within each side/cell intersection ages are UNIFORMLY
    distributed over the returned interval. This is not a mean-age model.
    Independent side clipping preserves cells which straddle the ridge.
    """
    _cancelled(cancel)
    age, (left, ridge, right) = _geometry_inputs(grid, motion, elapsed_s)
    with select_budget(budget).reserve(256*grid.cells+8192, category='spreading-geometry'):
        out = np.zeros((2, grid.cells, 3))
        if age == 0:
            return frozen(out)
        # Integrate in an onset-local frame so large absolute coordinates do not
        # turn small newborn widths into differences of rounded positions.
        edge = grid.edges_m-motion.ridge_position_m
        if np.any(np.abs(np.diff(edge)-grid.widths_m) > _ROUNDOFF*grid.widths_m):
            raise TectonicsError('onset-local coordinates cannot resolve cell widths')
        left = motion.left_velocity_m_s*age
        ridge = motion.ridge_velocity_m_s*age
        right = motion.right_velocity_m_s*age
        rates = (motion.ridge_velocity_m_s-motion.left_velocity_m_s,
                 motion.right_velocity_m_s-motion.ridge_velocity_m_s)
        try:
            with np.errstate(over='raise', invalid='raise', divide='raise'):
                for side, (start, end), rate in zip((0, 1), ((left, ridge), (ridge, right)), rates):
                    lo = np.maximum(edge[:-1], start)
                    hi = np.minimum(edge[1:], end)
                    active = hi > lo
                    low, high = lo[active], hi[active]
                    widths = high-low
                    if side == 0:
                        young, old = (ridge-high)/rate, (ridge-low)/rate
                        young[high == ridge] = 0.
                        old[low == left] = age
                    else:
                        young, old = (low-ridge)/rate, (high-ridge)/rate
                        young[low == ridge] = 0.
                        old[high == right] = age
                    if (np.any(young < 0) or np.any(old > age) or
                            np.any(old <= young) or not np.isfinite(old).all()):
                        raise TectonicsError('cell birth interval is not numerically resolvable')
                    out[side, active, 0] = widths
                    out[side, active, 1] = young
                    out[side, active, 2] = old
                if np.any(out[:, :, 0].sum(axis=0) > grid.widths_m*(1+_ROUNDOFF)):
                    raise TectonicsError('born strips overlap a cell')
                _cancelled(cancel)
                return frozen(out)
        except (FloatingPointError, OverflowError) as exc:
            raise TectonicsError('spreading geometry exceeds numerical range') from exc


@dataclass(frozen=True, slots=True, init=False)
class SpreadingState:
    """Immutable event-to-now projection, not a copy of prior output history.

    All retained returned states need a caller-owned allowance, like W02 states.
    Parent IDs record actual continuation; canonical strip histories do not
    depend on how many intermediate outputs were requested.
    """
    plan_id: str
    time_s: float
    elapsed_s: float
    intervals: int
    parent_state_id: str | None
    state_id: str
    strips: tuple[BirthStrip, BirthStrip]
    _cells: int = field(repr=False)
    _phases: int = field(repr=False)
    _geometry: bytes = field(repr=False)
    _accounts: bytes = field(repr=False)

    @property
    def cell_geometry(self):
        return np.frombuffer(self._geometry, dtype=np.float64).reshape(2, self._cells, 3)

    @property
    def accounts_kg(self):
        """Phase x (created,remaining,represented,left_export,right_export,residual)."""
        return np.frombuffer(self._accounts, dtype=np.float64).reshape(self._phases, 6)

    @property
    def nbytes(self):
        return len(self._geometry)+len(self._accounts)+2048


def _state_identity(plan_id, time_s, elapsed_s, intervals, parent_state_id, strips,
                    cells, phases, geometry, accounts):
    record = dict(schema='atlas.w06-spreading-state.v1', plan=plan_id, time_s=time_s,
                  elapsed_s=elapsed_s, intervals=intervals, parent=parent_state_id,
                  strips=[asdict(s) for s in strips], cells=cells, phases=phases)
    digest = hashlib.sha256(_json(record))
    digest.update(geometry); digest.update(accounts)
    return digest.hexdigest()


def _make_state(plan_id, time_s, elapsed_s, intervals, parent, strips, geometry, accounts):
    raw, mass = _immutable_bytes(geometry), _immutable_bytes(accounts)
    n, p = geometry.shape[1], accounts.shape[0]
    fields = dict(plan_id=plan_id, time_s=time_s, elapsed_s=elapsed_s, intervals=intervals,
                  parent_state_id=parent, strips=strips, _cells=n, _phases=p,
                  _geometry=raw, _accounts=mass)
    fields['state_id'] = _state_identity(plan_id, time_s, elapsed_s, intervals, parent,
                                       strips, n, p, raw, mass)
    result = object.__new__(SpreadingState)
    for key, value in fields.items():
        object.__setattr__(result, key, value)
    return result


def _within_budget(candidate, owner):
    node = candidate
    while node is not None:
        if node is owner:
            return
        node = node._parent
    raise TectonicsError('call budget must descend from the prepared run budget')


@dataclass(frozen=True, slots=True, init=False)
class PreparedRidgeSpreading:
    """Bounded constant history with source-verified exact outputs and finite feeds.

    Each immutable state is a candidate branch of the supplied feedstocks, not
    permission to spend one real reservoir twice across independently committed
    runs. A later transaction/workflow owner must serialise such publication.
    """
    grid: ColumnGrid1D
    motion: RidgeMotion
    phases: tuple[SpreadingPhase, ...]
    time_s: float
    epoch_id: str
    width_m: float
    source_id: str
    execution_id: str
    plan_id: str
    initial: SpreadingState
    _context: object = field(repr=False, compare=False)
    _owns_context: bool = field(repr=False, compare=False)
    _budget: object = field(repr=False, compare=False)
    _lease: object = field(repr=False, compare=False)
    _closed: bool = field(repr=False, compare=False)

    def __init__(self, grid, motion, phases, *, time_s, epoch_id, width_m,
                 source_id, context=None, budget=None, cancel=None):
        _cancelled(cancel); _geometry_inputs(grid, motion, 0.)
        if (type(phases) is not tuple or not 1 <= len(phases) <= MAX_SPREADING_PHASES
                or any(type(p) is not SpreadingPhase for p in phases)):
            raise TectonicsError('one to sixteen typed spreading phases required')
        if (len({p.phase_id for p in phases}) != len(phases) or
                len({p.source_id for p in phases}) != len(phases)):
            raise TectonicsError('distinct phase IDs and non-duplicated finite feed IDs required')
        origin = scalar(time_s, 'ridge onset time')
        width = scalar(width_m, 'bookkeeping width', positive=True)
        _name(epoch_id, 'epoch'); _name(source_id, 'spreading source')
        for p in phases:
            _product(p.thickness_m, p.density_kg_m3, width)
        resource = select_budget(budget)
        lease = resource.reserve(64*grid.cells+2048*len(phases)+16384,
                                 category='spreading-prepared')
        lease.__enter__()
        owned, ctx = context is None, None
        try:
            ctx = ExecutionContext('reference') if owned else context
            if type(ctx) is not ExecutionContext or ctx.backend != 'reference':
                raise TectonicsError('reference ExecutionContext required for exact spreading')
            execution_id = ctx.identity
            descriptor = dict(method='atlas.w06-constant-ridge.v1', grid=grid.grid_id,
                              motion=asdict(motion), phases=[asdict(p) for p in phases],
                              time_s=origin, epoch_id=epoch_id, width_m=width,
                              source_id=source_id, execution=execution_id,
                              max_intervals=MAX_SPREADING_INTERVALS)
            values = dict(grid=grid, motion=motion, phases=phases, time_s=origin,
                          epoch_id=epoch_id, width_m=width, source_id=source_id,
                          execution_id=execution_id, plan_id=hashlib.sha256(_json(descriptor)).hexdigest(),
                          _context=ctx, _owns_context=owned, _budget=resource,
                          _lease=lease, _closed=False)
            for key, value in values.items():
                object.__setattr__(self, key, value)
            initial = self._evaluate(origin, 0., 0, None, resource, cancel)
            object.__setattr__(self, 'initial', initial)
            ctx.verify(); _cancelled(cancel)
        except BaseException:
            lease.__exit__(None, None, None)
            if owned and ctx is not None:
                ctx.close()
            raise

    def _check(self, state):
        if self._closed:
            raise TectonicsError('spreading preparation is closed')
        if (type(state) is not SpreadingState or state.plan_id != self.plan_id or
                state._cells != self.grid.cells or state._phases != len(self.phases)):
            raise TectonicsError('state belongs to a different spreading plan')
        if state.state_id != _state_identity(state.plan_id, state.time_s, state.elapsed_s,
                state.intervals, state.parent_state_id, state.strips, state._cells,
                state._phases, state._geometry, state._accounts):
            raise TectonicsError('spreading state content no longer matches its identity')

    def _evaluate(self, end, elapsed, intervals, parent, resource, cancel):
        """Closed-form total demand and exports; never incremental stock clipping."""
        _, (left, ridge, right) = _geometry_inputs(self.grid, self.motion, elapsed)
        created_width = _product(self.motion.right_velocity_m_s-self.motion.left_velocity_m_s, elapsed)
        demands = [_product(created_width, self.width_m, p.thickness_m, p.density_kg_m3)
                   for p in self.phases]
        if any(m > p.stock_kg for p, m in zip(self.phases, demands)):
            raise TectonicsError('finite spreading feed exhausted; transaction refused')
        with resource.reserve(160*self.grid.cells+1024*len(self.phases)+8192,
                              category='spreading-state'):
            geometry = ridge_cell_geometry(self.grid, self.motion, elapsed,
                                           budget=resource, cancel=cancel)
            represented_width = math.fsum(geometry[:, :, 0].flat)
            # Geometric crossing integrals, independent of the projected cell sum.
            local_edges = self.grid.edges_m[[0, -1]]-self.motion.ridge_position_m
            exported = (max(float(local_edges[0])-self.motion.left_velocity_m_s*elapsed, 0.),
                        max(self.motion.right_velocity_m_s*elapsed-float(local_edges[1]), 0.))
            accounts = np.zeros((len(self.phases), 6))
            for i, (p, created) in enumerate(zip(self.phases, demands)):
                remaining = p.stock_kg-created
                represented, lx, rx = (_product(length, self.width_m, p.thickness_m,
                                                p.density_kg_m3)
                                       for length in (represented_width, *exported))
                _account(p.stock_kg, remaining, -created, 0., 0.)
                residual = _account(created, represented, -lx, -rx, 0.)[4]
                accounts[i] = created, remaining, represented, lx, rx, residual
            # Separate total closure, not only each phase's result.
            _account(math.fsum(accounts[:, 0]), math.fsum(accounts[:, 2]),
                     -math.fsum(accounts[:, 3]), -math.fsum(accounts[:, 4]), 0.)
            strips = (
                BirthStrip('left', left, ridge, 0., elapsed, self.motion.left_plate_id,
                           self.motion.ridge_id, self.motion.event_id),
                BirthStrip('right', ridge, right, elapsed, 0., self.motion.right_plate_id,
                           self.motion.ridge_id, self.motion.event_id))
            _cancelled(cancel)
            return _make_state(self.plan_id, end, elapsed, intervals, parent,
                               strips, geometry, accounts)

    def advance(self, state, *, time_s, budget=None, cancel=None):
        self._check(state); _cancelled(cancel); self._context.verify()
        end = scalar(time_s, 'requested time')
        if end < state.time_s:
            raise TectonicsError('spreading time cannot move backwards')
        resource = self._budget if budget is None else select_budget(budget)
        _within_budget(resource, self._budget)
        if end == state.time_s:
            return state
        if state.intervals >= MAX_SPREADING_INTERVALS:
            raise TectonicsError('spreading exceeds 256 cumulative requested intervals')
        elapsed = scalar(end-self.time_s, 'elapsed from ridge onset', positive=True)
        duration = scalar(end-state.time_s, 'advance duration', positive=True)
        if self.time_s+elapsed != end or state.time_s+duration != end:
            raise TectonicsError('clock cannot resolve requested endpoint')
        result = self._evaluate(end, elapsed, state.intervals+1, state.state_id, resource, cancel)
        self._context.verify(); _cancelled(cancel)
        return result

    def phase_thickness(self, state, *, budget=None):
        """Phase x cell mean reference thickness; full continuous histories stay separate."""
        self._check(state); self._context.verify()
        resource = self._budget if budget is None else select_budget(budget)
        _within_budget(resource, self._budget)
        p, n = len(self.phases), self.grid.cells
        with reserve_budgets(32*p*n+64*n+8192, resource, self._budget,
                            category='spreading-projection'):
            try:
                with np.errstate(over='raise', invalid='raise', divide='raise'):
                    fraction = state.cell_geometry[:, :, 0].sum(axis=0)/self.grid.widths_m
                    values = np.array([phase.thickness_m for phase in self.phases])[:, None]*fraction
                    if np.any((fraction > 0)[None, :] & (values == 0)):
                        raise TectonicsError('positive projected thickness underflows')
                    result = frozen(values)
            except FloatingPointError as exc:
                raise TectonicsError('spreading projection exceeds numerical range') from exc
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
