"""W06.4 exact piecewise ridge histories, finite births and first exits.

The fixed-window route requires outward plate velocities, so material cannot
re-enter after export. Events are supplied, never inferred breakup or dynamics.
An output samples the complete semantic history; outputs create no new cohorts.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import math

import numpy as np

from ._validation import TectonicsError, frozen, scalar
from .materials import _account, _immutable_bytes, _json, _name, _ROUNDOFF
from .mesh import ColumnGrid1D
from .regional import _cancelled
from .resources import select_budget
from .reuse import ExecutionContext
from .spreading import (MAX_SPREADING_CELLS, MAX_SPREADING_INTERVALS,
                        MAX_SPREADING_PHASES, SpreadingPhase, _product, _within_budget)


MAX_HISTORY_EVENTS = 256


@dataclass(frozen=True, slots=True)
class PlateReassignment:
    side: str
    from_plate_id: str
    to_plate_id: str
    source_id: str

    def __post_init__(self):
        if self.side not in ('left', 'right'):
            raise TectonicsError('reassignment side must be left or right')
        for key in ('from_plate_id', 'to_plate_id', 'source_id'):
            _name(getattr(self, key), key)
        if self.from_plate_id == self.to_plate_id:
            raise TectonicsError('reassignment must change the named plate')


@dataclass(frozen=True, slots=True)
class RidgeHistoryEvent:
    offset_s: float
    ridge_position_m: float
    left_velocity_m_s: float
    right_velocity_m_s: float
    ridge_velocity_m_s: float
    left_plate_id: str
    right_plate_id: str
    ridge_id: str
    event_id: str
    source_id: str
    active: bool = True
    reassignments: tuple[PlateReassignment, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, 'offset_s', scalar(self.offset_s, 'event offset', nonnegative=True))
        for key in ('ridge_position_m', 'left_velocity_m_s', 'right_velocity_m_s', 'ridge_velocity_m_s'):
            object.__setattr__(self, key, scalar(getattr(self, key), key))
        for key in ('left_plate_id', 'right_plate_id', 'ridge_id', 'event_id', 'source_id'):
            _name(getattr(self, key), key)
        if type(self.active) is not bool or self.left_plate_id == self.right_plate_id:
            raise TectonicsError('explicit activity and distinct side plate IDs required')
        if (type(self.reassignments) is not tuple or len(self.reassignments) > 2
                or any(type(r) is not PlateReassignment for r in self.reassignments)
                or len({r.side for r in self.reassignments}) != len(self.reassignments)):
            raise TectonicsError('at most one typed reassignment per side required')
        if self.active:
            if self.left_velocity_m_s > 0 or self.right_velocity_m_s < 0:
                raise TectonicsError('fixed-window history requires outward plate velocities')
            scalar(self.ridge_velocity_m_s-self.left_velocity_m_s, 'left half rate', positive=True)
            scalar(self.right_velocity_m_s-self.ridge_velocity_m_s, 'right half rate', positive=True)
        elif any(v != 0. for v in (self.left_velocity_m_s, self.right_velocity_m_s,
                                   self.ridge_velocity_m_s)):
            raise TectonicsError('inactive history requires a stationary welded boundary')


@dataclass(frozen=True, slots=True)
class HistoryBirthStrip:
    """Unclipped affine birth strip; plate_id denotes its current side assignment.

    Already exported parts are trajectories, not resident ownership. Their
    ownership at first exit is separately retained in HistoryExport.
    """
    side: str
    left_m: float
    right_m: float
    birth_offset_left_s: float
    birth_offset_right_s: float
    birth_event_id: str
    birth_source_id: str
    birth_plate_id: str
    plate_id: str
    ridge_id: str

    @property
    def cooling_offset_left_s(self):
        return self.birth_offset_left_s

    @property
    def cooling_offset_right_s(self):
        return self.birth_offset_right_s


@dataclass(frozen=True, slots=True)
class HistoryExport:
    """One birth interval crossing during one exit-motion interval.

    Endpoint fields are paired in increasing birth order; the exit-age order
    need not be increasing when velocities change. This records the first exit,
    never later motion/ownership outside the source window.
    """
    side: str
    exported_width_m: float
    birth_offset_first_s: float
    birth_offset_last_s: float
    exit_offset_first_s: float
    exit_offset_last_s: float
    exit_age_first_s: float
    exit_age_last_s: float
    birth_event_id: str
    birth_source_id: str
    birth_plate_id: str
    plate_id: str
    ridge_id: str
    exit_event_id: str
    exit_source_id: str


@dataclass(frozen=True, slots=True, init=False)
class HistorySpreadingState:
    plan_id: str
    time_s: float
    elapsed_s: float
    intervals: int
    parent_state_id: str | None
    state_id: str
    ridge_position_m: float
    created_width_m: float
    strips: tuple[HistoryBirthStrip, ...]
    exports: tuple[HistoryExport, ...]
    _cells: int = field(repr=False)
    _phases: int = field(repr=False)
    _intersections: bytes = field(repr=False)
    _centres: bytes = field(repr=False)
    _valid: bytes = field(repr=False)
    _accounts: bytes = field(repr=False)

    @property
    def intersections(self):
        """Rows: cell index, strip index, width m, youngest age s, oldest age s.

        Indices are exactly represented float64 integers. Storage is proportional
        to actual intersections; this is not a cells-by-events array.
        """
        return np.frombuffer(self._intersections, dtype=np.float64).reshape(-1, 5)

    @property
    def centre_age_s(self):
        return np.frombuffer(self._centres, dtype=np.float64).reshape(self._cells, 2)[:, 0]

    @property
    def centre_strip_index(self):
        return np.frombuffer(self._centres, dtype=np.float64).reshape(self._cells, 2)[:, 1]

    @property
    def centre_valid(self):
        return np.frombuffer(self._valid, dtype=np.bool_)

    @property
    def accounts_kg(self):
        """Phase x (created, remaining, resident, left export, right export, residual)."""
        return np.frombuffer(self._accounts, dtype=np.float64).reshape(self._phases, 6)

    @property
    def nbytes(self):
        return (len(self._intersections)+len(self._centres)+len(self._valid)+len(self._accounts)
                + 16384*len(self.strips)+32768*len(self.exports)+2048)


def _state_identity(state):
    record = dict(schema='atlas.w06-history-state.v1', plan=state.plan_id,
        time_s=state.time_s, elapsed_s=state.elapsed_s, intervals=state.intervals,
        parent=state.parent_state_id, ridge_position_m=state.ridge_position_m,
        created_width_m=state.created_width_m, cells=state._cells, phases=state._phases,
        strips=[asdict(s) for s in state.strips], exports=[asdict(e) for e in state.exports])
    digest = hashlib.sha256(_json(record))
    for raw in (state._intersections, state._centres, state._valid, state._accounts):
        digest.update(raw)
    return digest.hexdigest()


def _event_catalogue(grid, events, origin):
    if type(grid) is not ColumnGrid1D or grid.cells > MAX_SPREADING_CELLS:
        raise TectonicsError('typed bounded ColumnGrid1D required')
    if (type(events) is not tuple or not 1 <= len(events) <= MAX_HISTORY_EVENTS
            or any(type(e) is not RidgeHistoryEvent for e in events)):
        raise TectonicsError('one to 256 typed semantic events required')
    if events[0].offset_s != 0. or events[0].reassignments:
        raise TectonicsError('history starts at offset zero without reassignment')
    if len({e.event_id for e in events}) != len(events):
        raise TectonicsError('semantic event IDs must be unique')
    bounds = grid.edges_m[[0, -1]]
    for i, event in enumerate(events):
        absolute = scalar(origin+event.offset_s, 'absolute semantic event time')
        if absolute-origin != event.offset_s:
            raise TectonicsError('clock cannot resolve semantic event offsets')
        if not bounds[0] < event.ridge_position_m < bounds[1]:
            raise TectonicsError('declared ridge lies outside the source window')
        if i == 0:
            continue
        previous = events[i-1]
        duration = scalar(event.offset_s-previous.offset_s, 'event duration', positive=True)
        expected = scalar(math.fsum((previous.ridge_position_m,
            previous.ridge_velocity_m_s*duration)), 'continuous ridge position')
        if event.ridge_position_m != expected or event.ridge_id != previous.ridge_id:
            raise TectonicsError('ridge jumps or changed ridge identity are unsupported')
        changed = {side for side in ('left', 'right')
                   if getattr(previous, side+'_plate_id') != getattr(event, side+'_plate_id')}
        if {r.side for r in event.reassignments} != changed:
            raise TectonicsError('plate ownership change requires complete explicit reassignment')
        for row in event.reassignments:
            if (row.from_plate_id != getattr(previous, row.side+'_plate_id')
                    or row.to_plate_id != getattr(event, row.side+'_plate_id')):
                raise TectonicsError('reassignment does not match previous and next plate IDs')


def _age_at(strip, x, elapsed):
    first = elapsed-strip.birth_offset_left_s
    last = elapsed-strip.birth_offset_right_s
    fraction = (x-strip.left_m)/(strip.right_m-strip.left_m)
    age = first+(last-first)*fraction
    age = np.where(x == strip.left_m, first, age)
    age = np.where(x == strip.right_m, last, age)
    if np.any(age < 0) or np.any(age > elapsed) or not np.isfinite(age).all():
        raise TectonicsError('affine cooling history is outside its declared interval')
    return age


def _project(grid, strips, elapsed, ridge, cancel):
    edges = grid.edges_m; centres = grid.centres_m
    rows = []; middle = np.zeros((grid.cells, 2)); middle[:, 1] = -1.
    valid = np.zeros(grid.cells, dtype=np.bool_)
    occupied = np.zeros(grid.cells)
    for index, strip in enumerate(strips):
        _cancelled(cancel)
        start = max(0, int(np.searchsorted(edges, strip.left_m, side='right'))-1)
        stop = min(grid.cells, int(np.searchsorted(edges, strip.right_m, side='left')))
        if stop <= start:
            continue
        cell = np.arange(start, stop)
        left = np.maximum(edges[cell], strip.left_m)
        right = np.minimum(edges[cell+1], strip.right_m)
        widths = right-left
        a = _age_at(strip, left, elapsed); b = _age_at(strip, right, elapsed)
        if np.any(widths <= 0) or np.any(a == b):
            raise TectonicsError('positive strip intersection has unresolved birth width')
        block = np.column_stack((cell, np.full(len(cell), index), widths, np.minimum(a, b), np.maximum(a, b)))
        rows.append(block); occupied[cell] += widths
        # Birth intervals are [start,end). Left-side age decreases with x;
        # right-side age increases with x, so its spatial convention reverses.
        c = centres[cell]
        mask = ((c >= strip.left_m) & (c < strip.right_m) if strip.side == 'left'
                else (c > strip.left_m) & (c <= strip.right_m))
        # A sampled ridge point has zero age while spreading and an older age
        # after welding. Assign this measure-zero endpoint once, to the most
        # recent left strip, without manufacturing a finite-width birth cell.
        if strip.side == 'left' and strip.right_m == ridge:
            mask |= c == ridge
        selected = cell[mask]
        if np.any(valid[selected]):
            raise TectonicsError('history strips overlap a sampled centre')
        middle[selected, 0] = _age_at(strip, c[mask], elapsed)
        middle[selected, 1] = index; valid[selected] = True
    if np.any(occupied > grid.widths_m*(1+_ROUNDOFF)):
        raise TectonicsError('history strips overlap represented cells')
    intersections = np.concatenate(rows) if rows else np.empty((0, 5))
    return intersections, middle, valid


def _exports(events, durations, elapsed, bounds, crossing_strips, cancel):
    exports = []
    for i, born in enumerate(events):
        if not born.active or durations[i] == 0:
            continue
        birth_end = born.offset_s+durations[i]
        for side, boundary in zip(('left', 'right'), bounds):
            if (born.event_id, side) not in crossing_strips:
                continue
            velocity_name = side+'_velocity_m_s'; plate_name = side+'_plate_id'
            slope = born.ridge_velocity_m_s-getattr(born, velocity_name)
            rate = abs(slope); oldest_position = born.ridge_position_m
            exported_until = born.offset_s
            for j in range(i, len(events)):
                _cancelled(cancel)
                motion = events[j]; duration = durations[j]
                if duration == 0:
                    continue
                velocity = getattr(motion, velocity_name)
                final_position = scalar(math.fsum((oldest_position, velocity*duration)),
                                        'export trajectory coordinate')
                if velocity != 0.:
                    cutoff = born.offset_s+(boundary-final_position)/slope
                    cutoff = min(birth_end, max(born.offset_s, cutoff))
                    if cutoff < exported_until:
                        raise TectonicsError('outward history unexpectedly re-enters source window')
                    if cutoff > exported_until:
                        first, last = exported_until, cutoff
                        def exit_at(birth):
                            position = math.fsum((oldest_position, slope*(birth-born.offset_s)))
                            return scalar(math.fsum((motion.offset_s, (boundary-position)/velocity)),
                                          'first exit offset', nonnegative=True)
                        exit_first, exit_last = exit_at(first), exit_at(last)
                        if cutoff < birth_end:
                            exit_last = motion.offset_s+duration
                        tolerance = _ROUNDOFF*max(elapsed, 1.)
                        if (exit_first < motion.offset_s-tolerance
                                or exit_last > motion.offset_s+duration+tolerance
                                or exit_first > exit_last+tolerance
                                or exit_first < first or exit_last < last):
                            raise TectonicsError('first exit lies outside its motion/birth interval')
                        exports.append(HistoryExport(side, _product(rate, last-first), first, last,
                            exit_first, exit_last, exit_first-first, exit_last-last,
                            born.event_id, born.source_id, getattr(born, plate_name),
                            getattr(motion, plate_name), born.ridge_id, motion.event_id, motion.source_id))
                        exported_until = cutoff
                oldest_position = final_position
    return tuple(exports)


@dataclass(frozen=True, slots=True, init=False)
class PreparedSpreadingHistory:
    grid: ColumnGrid1D
    events: tuple[RidgeHistoryEvent, ...]
    phases: tuple[SpreadingPhase, ...]
    time_s: float
    epoch_id: str
    width_m: float
    source_id: str
    execution_id: str
    plan_id: str
    initial: HistorySpreadingState
    _context: object = field(repr=False, compare=False)
    _owns_context: bool = field(repr=False, compare=False)
    _budget: object = field(repr=False, compare=False)
    _lease: object = field(repr=False, compare=False)
    _closed: bool = field(repr=False, compare=False)

    def __init__(self, grid, events, phases, *, time_s, epoch_id, width_m, source_id,
                 context=None, budget=None, cancel=None):
        _cancelled(cancel)
        origin = scalar(time_s, 'history onset time'); _event_catalogue(grid, events, origin)
        if (type(phases) is not tuple or not 1 <= len(phases) <= MAX_SPREADING_PHASES
                or any(type(p) is not SpreadingPhase for p in phases)):
            raise TectonicsError('one to sixteen typed spreading phases required')
        if (len({p.phase_id for p in phases}) != len(phases)
                or len({p.source_id for p in phases}) != len(phases)):
            raise TectonicsError('distinct phase and finite feed IDs required')
        width = scalar(width_m, 'bookkeeping width', positive=True)
        _name(epoch_id, 'epoch'); _name(source_id, 'history source')
        for phase in phases:
            _product(width, phase.thickness_m, phase.density_kg_m3)
        resource = select_budget(budget)
        lease = resource.reserve(64*grid.cells+32768*len(events)+16384*len(phases)+16384,
                                 category='spreading-history-prepared')
        lease.__enter__(); owned, ctx = context is None, None
        try:
            ctx = ExecutionContext('reference') if owned else context
            if type(ctx) is not ExecutionContext or ctx.backend != 'reference':
                raise TectonicsError('reference ExecutionContext required for spreading history')
            execution_id = ctx.identity
            descriptor = dict(method='atlas.w06-piecewise-ridge.v1', grid=grid.grid_id,
                events=[asdict(e) for e in events], phases=[asdict(p) for p in phases],
                time_s=origin, epoch_id=epoch_id, width_m=width, source_id=source_id,
                execution=execution_id, max_intervals=MAX_SPREADING_INTERVALS,
                max_events=MAX_HISTORY_EVENTS)
            for key, value in dict(grid=grid, events=events, phases=phases, time_s=origin,
                    epoch_id=epoch_id, width_m=width, source_id=source_id, execution_id=execution_id,
                    plan_id=hashlib.sha256(_json(descriptor)).hexdigest(), _context=ctx,
                    _owns_context=owned, _budget=resource, _lease=lease, _closed=False).items():
                object.__setattr__(self, key, value)
            object.__setattr__(self, 'initial', self._evaluate(origin, 0., 0, None, resource, cancel))
            ctx.verify(); _cancelled(cancel)
        except BaseException:
            lease.__exit__(None, None, None)
            if owned and ctx is not None:
                ctx.close()
            raise

    def _check(self, state):
        if self._closed:
            raise TectonicsError('spreading history preparation is closed')
        if (type(state) is not HistorySpreadingState or state.plan_id != self.plan_id
                or state._cells != self.grid.cells or state._phases != len(self.phases)):
            raise TectonicsError('state belongs to a different spreading history')
        if state.state_id != _state_identity(state):
            raise TectonicsError('spreading history state no longer matches its identity')

    def _evaluate(self, end, elapsed, intervals, parent, resource, cancel):
        count = int(np.searchsorted([e.offset_s for e in self.events], elapsed, side='right'))
        events = self.events[:count]; current = events[-1]
        durations = [min(elapsed, self.events[i+1].offset_s if i+1 < len(self.events) else elapsed)
                     -event.offset_s for i, event in enumerate(events)]
        ridge = scalar(math.fsum((current.ridge_position_m,
            current.ridge_velocity_m_s*durations[-1])), 'current ridge position')
        bounds = self.grid.edges_m[[0, -1]]
        if not bounds[0] < ridge < bounds[1]:
            raise TectonicsError('ridge leaves represented source window')
        created = scalar(math.fsum(_product(e.right_velocity_m_s-e.left_velocity_m_s, dt)
                                  for e, dt in zip(events, durations) if e.active),
                         'total born width', nonnegative=True)
        demands = [_product(created, self.width_m, p.thickness_m, p.density_kg_m3) for p in self.phases]
        if any(demand > phase.stock_kg for demand, phase in zip(demands, self.phases)):
            raise TectonicsError('finite spreading feed exhausted; transaction refused')
        first_birth = next((i for i, event in enumerate(events)
                            if event.active and durations[i] > 0), None)
        export_sides = 0
        if first_birth is not None:
            for side, boundary in zip(('left', 'right'), bounds):
                oldest = scalar(math.fsum([events[first_birth].ridge_position_m]+[
                    getattr(event, side+'_velocity_m_s')*duration
                    for event, duration in zip(events[first_birth:], durations[first_birth:])]),
                    'oldest outward trajectory')
                export_sides += int(oldest < boundary if side == 'left' else oldest > boundary)
        # At most two strips per event, cells+strips intersections, and one
        # export per birth-side/exit-event pair. Reserve before quadratic work.
        # UTF-8 metadata may contain 256-character identifiers, each of which
        # expands under ASCII JSON escaping. Include the temporary dictionaries
        # and serialised state identity, not merely the dataclass slot payload.
        # Outward velocities make this exact: if the oldest outer parcel has
        # not left, no younger parcel on that side could have left earlier.
        export_bound = export_sides*count*(count+1)//2
        work = (256*self.grid.cells+32768*count+32768*export_bound
                +16384*len(self.phases)+32768)
        with resource.reserve(work, category='spreading-history-state'):
            strips = []
            for side in ('left', 'right'):
                velocity_name = side+'_velocity_m_s'; plate_name = side+'_plate_id'
                suffix = 0.
                for i in range(count-1, -1, -1):
                    _cancelled(cancel)
                    event = events[i]; duration = durations[i]
                    later = suffix
                    suffix = scalar(math.fsum((suffix, getattr(event, velocity_name)*duration)),
                                    'piecewise plate displacement')
                    if not event.active or duration == 0:
                        continue
                    first = scalar(math.fsum((event.ridge_position_m, suffix)), 'old strip endpoint')
                    # Use the same canonical event position and displacement
                    # as its neighbour, so semantic boundaries share identical
                    # floating-point coordinates (not approximately equal gaps).
                    last = (scalar(math.fsum((events[i+1].ridge_position_m, later)),
                                   'young strip endpoint') if i+1 < count else ridge)
                    expected = _product(abs(event.ridge_velocity_m_s-getattr(event, velocity_name)), duration)
                    width = abs(last-first)
                    if (width <= 0 or abs(width-expected) > _ROUNDOFF*expected
                            +2*max(math.ulp(first), math.ulp(last))):
                        raise TectonicsError('coordinates cannot resolve history strip width')
                    left, right = min(first, last), max(first, last)
                    birth_first, birth_last = event.offset_s, event.offset_s+duration
                    lo, hi = ((birth_first, birth_last) if side == 'left' else (birth_last, birth_first))
                    strips.append(HistoryBirthStrip(side, left, right, lo, hi, event.event_id,
                        event.source_id, getattr(event, plate_name), getattr(current, plate_name), event.ridge_id))
            strips = tuple(sorted(strips, key=lambda s: (s.left_m, s.right_m)))
            for left, right in zip(strips[:-1], strips[1:]):
                tolerance = 4*max(math.ulp(left.right_m), math.ulp(right.left_m))
                if abs(left.right_m-right.left_m) > tolerance:
                    raise TectonicsError('semantic birth strips have a gap or overlap')
            intersections, centres, valid = _project(self.grid, strips, elapsed, ridge, cancel)
            crossing = {(strip.birth_event_id, strip.side) for strip in strips
                        if (strip.left_m < bounds[0] if strip.side == 'left' else strip.right_m > bounds[1])}
            exports = (_exports(events, durations, elapsed, bounds, crossing, cancel)
                       if crossing else ())
            represented = math.fsum(intersections[:, 2])
            left_export = math.fsum(e.exported_width_m for e in exports if e.side == 'left')
            right_export = math.fsum(e.exported_width_m for e in exports if e.side == 'right')
            _account(created, represented, -left_export, -right_export, 0.)
            accounts = np.zeros((len(self.phases), 6))
            for i, (phase, demand) in enumerate(zip(self.phases, demands)):
                remaining = phase.stock_kg-demand
                resident, lx, rx = (_product(length, self.width_m, phase.thickness_m, phase.density_kg_m3)
                                     for length in (represented, left_export, right_export))
                _account(phase.stock_kg, remaining, -demand, 0., 0.)
                residual = _account(demand, resident, -lx, -rx, 0.)[4]
                accounts[i] = demand, remaining, resident, lx, rx, residual
            _account(math.fsum(accounts[:, 0]), math.fsum(accounts[:, 2]),
                     -math.fsum(accounts[:, 3]), -math.fsum(accounts[:, 4]), 0.)
            result = object.__new__(HistorySpreadingState)
            for key, value in dict(plan_id=self.plan_id, time_s=end, elapsed_s=elapsed,
                    intervals=intervals, parent_state_id=parent, ridge_position_m=ridge,
                    created_width_m=created, strips=strips, exports=exports,
                    _cells=self.grid.cells, _phases=len(self.phases),
                    _intersections=_immutable_bytes(intersections), _centres=_immutable_bytes(centres),
                    _valid=valid.tobytes(), _accounts=_immutable_bytes(accounts)).items():
                object.__setattr__(result, key, value)
            object.__setattr__(result, 'state_id', _state_identity(result))
            _cancelled(cancel)
            return result

    def advance(self, state, *, time_s, budget=None, cancel=None):
        self._check(state); _cancelled(cancel); self._context.verify()
        end = scalar(time_s, 'requested history time')
        if end < state.time_s:
            raise TectonicsError('spreading history cannot move backwards')
        resource = self._budget if budget is None else select_budget(budget)
        _within_budget(resource, self._budget)
        if end == state.time_s:
            return state
        if state.intervals >= MAX_SPREADING_INTERVALS:
            raise TectonicsError('spreading exceeds 256 cumulative requested intervals')
        elapsed = scalar(end-self.time_s, 'elapsed from history onset', positive=True)
        duration = scalar(end-state.time_s, 'history advance duration', positive=True)
        if self.time_s+elapsed != end or state.time_s+duration != end:
            raise TectonicsError('clock cannot resolve requested history endpoint')
        result = self._evaluate(end, elapsed, state.intervals+1, state.state_id, resource, cancel)
        self._context.verify(); _cancelled(cancel)
        return result

    def phase_thickness(self, state, *, budget=None):
        self._check(state); self._context.verify()
        resource = self._budget if budget is None else select_budget(budget)
        _within_budget(resource, self._budget)
        with resource.reserve(32*len(self.phases)*self.grid.cells+64*self.grid.cells+8192,
                              category='spreading-history-projection'):
            occupied = np.zeros(self.grid.cells)
            rows = state.intersections
            np.add.at(occupied, rows[:, 0].astype(np.intp), rows[:, 2])
            fraction = occupied/self.grid.widths_m
            values = np.array([p.thickness_m for p in self.phases])[:, None]*fraction
            if np.any((fraction > 0)[None, :] & (values == 0)):
                raise TectonicsError('positive history thickness underflows')
            result = frozen(values)
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
