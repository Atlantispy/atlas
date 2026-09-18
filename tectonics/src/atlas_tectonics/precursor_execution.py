"""R2 sampling adapters to the existing KernelExecutor; no second scheduler.

Only queries into one immutable starting state are independent. Global cell
validation runs before batching. Results are assembled in the caller's order;
CSR row/phase offsets are translated, never re-summed across physical cells.
Worker choice cannot change equations, precision, geometry or sampled histories.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
import threading

import numpy as np

from .execution import ExecutionPolicy, KernelExecutor, _AdmittedCall
from ._validation import input_shape, snapshot
from .geological_records import GeologyError, _names, _tuple
from .geometry import PlanarGeometry, _check_cancel
from .spherical_geometry import SphericalGeometry, _directions
from .geological_case import _check_geometry_frame


@dataclass(frozen=True, slots=True)
class PrecursorExecutionPolicy:
    """Execution only: independent of scientific sample identity.

    Small requests remain on the normal bulk serial path. Larger requests use
    the established ordered, memory-admitted local executor. Explicit serial and
    threads modes support matched-work comparisons. Spawn cannot share prepared
    native indexes and is refused, not silently replaced by another backend.

    Measured default: auto threads large indexed point queries. Small/unindexed
    points and cell queries remain bulk serial: tested cell workloads were slower
    with Python orchestration spread across threads. A caller can explicitly set
    a cell threshold after matched-work evidence on its workload, or select
    threads for verification. These choices never downgrade scientific accuracy.
    """
    kernel: ExecutionPolicy = field(default_factory=ExecutionPolicy)
    point_batch_size: int = 32_768
    cell_batch_size: int = 64
    min_parallel_points: int = 262_144
    min_parallel_cells: int | None = None

    def __post_init__(self):
        if type(self.kernel) is not ExecutionPolicy or self.kernel.mode == 'processes':
            raise GeologyError('precursor execution requires serial/auto/threads ExecutionPolicy')
        for name in ('point_batch_size', 'cell_batch_size', 'min_parallel_points', 'min_parallel_cells'):
            if name == 'min_parallel_cells' and getattr(self, name) is None:
                continue
            if type(getattr(self, name)) is not int or getattr(self, name) < 1:
                raise GeologyError(name+' must be a positive integer')

    def parallel(self, kind, count, *, indexed_points=True):
        if self.kernel.mode == 'serial' or self.kernel.max_workers == 1:
            return False
        if self.kernel.mode == 'threads':
            return True
        if kind == 'points':
            return indexed_points and count >= self.min_parallel_points
        return self.min_parallel_cells is not None and count >= self.min_parallel_cells


class _Cancellation:
    def __init__(self, external, aborted):
        self.external = external; self.aborted = aborted
    def is_set(self):
        return self.aborted.is_set() or (self.external is not None and self.external.is_set())


class _RequestLedger:
    """Whole-request limits, never multiplied by number of worker batches."""
    def __init__(self, limits, geometry_limits):
        self.limits = limits; self.geometry_limits = geometry_limits
        self._lock = threading.Lock()
        self.rows = 0; self.work = 0; self.hits = 0

    def charge(self, *, rows=0, work=0, hits=0):
        with self._lock:
            self.rows += rows; self.work += work; self.hits += hits
            if self.rows > self.limits.max_rows:
                raise GeologyError('whole-request sparse-row envelope exceeded')
            if self.work > self.limits.max_work_items:
                raise GeologyError('whole-request sampling work envelope exceeded')
            if self.hits > self.geometry_limits.max_hits:
                raise GeologyError('whole-request geometry-hit envelope exceeded')


class _WorkCounter(list):
    """Per-batch diagnostic with atomic global admission at every increment."""
    def __init__(self, ledger):
        super().__init__([0]); self.ledger = ledger
    def __setitem__(self, key, value):
        if self.ledger is not None:
            self.ledger.charge(work=value-self[key])
        super().__setitem__(key, value)


def _executor(plan):
    # Enter lazily on the driving thread, not during plan construction or a small
    # concurrent reader call. Reuse the pool on later large calls to this plan.
    if plan._executor is None:
        kernel = replace(plan.execution_policy.kernel, mode='threads')
        executor = KernelExecutor(kernel, budget=plan.budget)
        executor.__enter__()
        plan._executor = executor
    return plan._executor


def _point_bounds(plan, count, fields):
    case = plan.state.case
    rows = min(count*(len(case.provinces)+len(case.weak_zones)+1), plan.limits.max_rows)
    hits = min(count*len(case.geometries), plan.geometry_limits.max_hits)
    geometry_batch = min(count, plan.geometry_limits.batch_points)
    prior_batch = min(count, plan.limits.batch_points)
    # Joined local suballocations: capture/grouped arrays, index hits, geometry
    # predicates, prior fields and immutable output. Parent reserves this BEFORE
    # submission; the worker accounts inside a detached budget with this ceiling.
    return int(512*count + 32*count*len(fields) + 128*rows + 192*hits + 2048*geometry_batch + 160*prior_batch + (1<<20))


def _cell_rows(plan, count):
    case = plan.state.case
    unit_rows = sum(len(case.column(p.column_id).layers) for p in case.provinces)+len(plan.state.bodies)
    max_phases = max(len(u.layer.components)+1 for u in plan.state.units)
    rows = min(plan.limits.max_rows, count*unit_rows)
    phases = min(plan.limits.max_rows, rows*max_phases)
    return rows, phases


def _cell_bounds(plan, cells, fields):
    rows, phases = _cell_rows(plan, len(cells))
    vertices = max(c.footprint.vertex_count for c in cells)+sum(g.geometry.vertex_count for g in plan.state.case.geometries)
    support = sum(c.footprint.retained_bytes for c in cells)
    # Existing GEOS admission may still refuse a particularly complex evolving
    # fragment rather than exceeding this finite per-job allowance. No fallback
    # or increased geometry envelope is hidden in the execution adapter.
    return int(4096*vertices + 96*min(vertices*vertices, plan.geometry_limits.max_overlay_pairs)
               + 2048*(rows+phases) + 1024*len(cells)*(len(fields)+1) + 4*support + (2<<20))


def _accept(plan, kind, count, fields, result):
    from .precursor_sampling import InitialSamples
    if type(result) is not InitialSamples or result.state is not plan.state or result.kind != kind:
        raise GeologyError('sampling worker returned another state or representation')
    md = result.descriptor()
    if md['plan_id'] != plan.identity or md['requested_fields'] != list(fields):
        raise GeologyError('sampling worker changed method or requested fields')
    actual = len(result.array('depths_m' if kind == 'points' else 'cell_volume_m3'))
    if actual != count:
        raise GeologyError('sampling worker changed query length')
    return result


def _metadata(result):
    return {k: v for k, v in result.descriptor().items() if k not in ('schema', 'arrays', 'state_id', 'kind')}


def _offsets(parts, name):
    out = [np.array([0], dtype=np.int64)]; offset = 0
    for part in parts:
        a = part.array(name)
        out.append(a[1:]+offset)
        offset += int(a[-1])
    return np.concatenate(out)


def _merge_points(plan, parts):
    from .precursor_sampling import InitialSamples
    offsets = ('province_offsets', 'weak_zone_offsets')
    arrays = {name: (_offsets(parts, name) if name in offsets else
                     np.concatenate([r.array(name) for r in parts], axis=0)) for name in parts[0]._buffers}
    if len(arrays['province_candidates'])+len(arrays['weak_zone_codes']) > plan.limits.max_rows:
        raise GeologyError('merged point associations exceed whole-request limit')
    return InitialSamples(plan.state, 'points', _metadata(parts[0]), arrays)


def _merge_cells(plan, parts, cells):
    from .precursor_sampling import InitialSamples
    md = _metadata(parts[0]); arrays = {}
    for name in parts[0]._buffers:
        if name.startswith('support_') or name in ('cell_offsets', 'row_cell', 'phase_row'):
            continue
        arrays[name] = np.concatenate([p.array(name) for p in parts], axis=0)
    arrays['cell_offsets'] = _offsets(parts, 'cell_offsets')
    row_cell = []; phase_row = []; nc = 0; nr = 0
    for p in parts:
        row_cell.append(p.array('row_cell')+nc); phase_row.append(p.array('phase_row')+nr)
        nc += len(p.array('cell_volume_m3')); nr += len(p.array('row_cell'))
    arrays['row_cell'] = np.concatenate(row_cell); arrays['phase_row'] = np.concatenate(phase_row)
    if nr+len(arrays['phase_row']) > plan.limits.max_rows:
        raise GeologyError('merged cell records exceed whole-request limit')
    supports = {c.footprint.geometry_id: c.footprint for c in cells}
    md['supports'] = {}
    for i, (gid, g) in enumerate(sorted(supports.items())):
        name = 'support_'+str(i)
        arrays[name] = np.frombuffer(g.wkb if type(g) is PlanarGeometry else g._projected.wkb, dtype='u1')
        md['supports'][gid] = {'array': name, 'geometry': g.descriptor()}
    md['cells'] = [c.descriptor() for c in cells]
    md['overlay_work_items'] = sum(p.descriptor()['overlay_work_items'] for p in parts)
    if md['overlay_work_items'] > plan.limits.max_work_items:
        raise GeologyError('merged overlay work exceeds whole-request limit')
    return InitialSamples(plan.state, 'cells', md, arrays)


def _drive(plan, tasks, cancel, aborted):
    executor = _executor(plan)
    before = executor.statistics()
    stream = executor._admitted_calls(tasks, cancel=cancel)
    try:
        result = list(stream)
        after = executor.statistics()
        plan._last_execution = {
            'route': 'threads', 'batches': len(result),
            'parallel_jobs': after['parallel_jobs']-before['parallel_jobs'],
            'max_workers': after['max_workers'], 'peak_inflight': after['peak_inflight'],
            'accounted_executor_peak_bytes': after['peak_reserved_bytes'],
            'inner_threads': after['inner_threads'], 'process_rss_cap': False}
        return result
    finally:
        aborted.set()
        stream.close()


def sample_points(plan, points, depths_m, **kwargs):
    """Select whole-query serial or bounded threaded execution automatically."""
    fields = kwargs.get('fields', ()); cancel = kwargs.get('cancel')
    plan._check_request(kwargs['frame_id'], kwargs['epoch_id'], kwargs['depth_reference_id'])
    shape = input_shape(points, 'sampling points')
    dim = 2 if plan.state.case.topology.sphere is None else 3
    if len(shape) != 2 or shape[1] != dim or not 0 < shape[0] <= plan.limits.max_points:
        raise GeologyError('point dimensions or count outside sampling envelope')
    n = shape[0]
    if not plan.execution_policy.parallel('points', n, indexed_points=bool(plan.state.case.geometries)):
        plan._last_execution = {'route': 'serial', 'batches': 1, 'parallel_jobs': 0}
        return plan._sample_points_serial(points, depths_m, **kwargs)
    _names(fields, 'requested fields', ordered=True)
    depth_shape = input_shape(depths_m, 'depths')
    if depth_shape not in ((), (n,)):
        raise GeologyError('depth must be scalar or one value per point')
    feature_work = n*(len(plan.state.case.weak_zones)+len(plan.state.case.provinces)+len(plan.state.bodies)+1)
    if feature_work > plan.limits.max_work_items:
        raise GeologyError('point selector work exceeds policy; request explicit smaller batches')
    batch = plan.execution_policy.point_batch_size
    count = (n+batch-1)//batch
    rows = min(n*(len(plan.state.case.provinces)+len(plan.state.case.weak_zones)+1), plan.limits.max_rows)
    # Captured inputs, ALL retained results, merged arrays and final immutable
    # bytes are held under one aggregate reservation, not lost when jobs yield.
    retained = (3*(53+8*dim+9*len(fields)) + 2*(8*dim+8))*n + 12*rows + 65536*(count+1)
    with plan._dispatch_lock, plan._operation(cancel), plan.budget.reserve(retained, category='precursor-batch-results'):
        p = snapshot(points, 'point request'); z = snapshot(depths_m, 'depth request')
        if p.shape != shape or z.shape != depth_shape:
            raise GeologyError('sampling input shape changed during capture')
        aborted = threading.Event(); combined = _Cancellation(cancel, aborted)
        ledger = _RequestLedger(plan.limits, plan.geometry_limits)
        def tasks():
            for start in range(0, n, batch):
                stop = min(n, start+batch); xy = p[start:stop]
                depth = z if z.ndim == 0 else z[start:stop]
                def run(budget, xy=xy, depth=depth):
                    return plan._sample_points_serial(xy, depth, **(kwargs | {'cancel': combined}),
                                                      _admitted_budget=budget, _ledger=ledger)
                def accept(result, xy=xy, depth=depth):
                    result = _accept(plan, 'points', len(xy), fields, result)
                    expected = _directions(xy) if dim == 3 else xy
                    if not np.array_equal(result.array('points'), expected) or not np.all(result.array('depths_m') == depth):
                        raise GeologyError('sampling worker changed captured query coordinates')
                    return result
                yield _AdmittedCall(run, accept, aborted.set, stop-start, _point_bounds(plan, stop-start, fields))
        parts = _drive(plan, tasks(), combined, aborted)
        result = _merge_points(plan, parts)
        _check_cancel(cancel)
        return result


def sample_cells(plan, cells, **kwargs):
    """Validate the COMPLETE request before independently sampling its cells."""
    from .precursor_sampling import InitialSamplingCell, _check_cell_overlaps
    fields = kwargs.get('fields', ()); cancel = kwargs.get('cancel')
    plan._check_request(kwargs['frame_id'], kwargs['epoch_id'], kwargs['depth_reference_id'])
    _tuple(cells, 'sampling cells', allow_empty=False)
    if len(cells) > plan.limits.max_cells or any(type(c) is not InitialSamplingCell for c in cells):
        raise GeologyError('bounded tuple of typed initial sampling cells required')
    if not plan.execution_policy.parallel('cells', len(cells)):
        plan._last_execution = {'route': 'serial', 'batches': 1, 'parallel_jobs': 0}
        return plan._sample_cells_serial(cells, **kwargs)
    if len({c.cell_id for c in cells}) != len(cells):
        raise GeologyError('sampling cell IDs must be unique')
    _names(fields, 'requested fields', ordered=True)
    if any(name not in plan.state._maps['fields'] for name in fields):
        raise GeologyError('unknown requested field')
    overlap = kwargs.get('allow_overlapping_queries', False)
    if type(overlap) is not bool or type(kwargs.get('include_temperature', True)) is not bool:
        raise GeologyError('sampling switches must be bool')
    supports = {c.footprint.geometry_id: c.footprint for c in cells}
    vertices = sum(g.vertex_count for g in supports.values())
    if vertices > plan.geometry_limits.max_vertices:
        raise GeologyError('cell support vertices exceed explicit geometry policy')
    n = len(cells); rows, phases = _cell_rows(plan, n)
    # Count support repetitions across batches as well as the final deduplicated
    # result, plus bounded descriptor/row/phase assembly. This may refuse a very
    # large explicit request; it never removes geometry or changes the model.
    retained = (4*sum(c.footprint.retained_bytes for c in cells) + 512*vertices
                + 512*n + 384*rows + 192*phases + 64*n*len(fields) + (1<<20))
    with plan._dispatch_lock, plan._operation(cancel), plan.budget.reserve(retained, category='precursor-batch-results'):
        for g in supports.values():
            _check_cancel(cancel)
            _check_geometry_frame(plan.state.case.topology, g, plan.geometry_limits, plan.budget)
        if not overlap:
            _check_cell_overlaps(cells, plan.geometry_limits, plan.limits, plan.budget, cancel)
        aborted = threading.Event(); combined = _Cancellation(cancel, aborted)
        ledger = _RequestLedger(plan.limits, plan.geometry_limits)
        batch = plan.execution_policy.cell_batch_size
        def tasks():
            for start in range(0, n, batch):
                part = cells[start:start+batch]
                def run(budget, part=part):
                    return plan._sample_cells_serial(part, **(kwargs | {'cancel': combined}),
                                                     _admitted_budget=budget, _prevalidated=True, _ledger=ledger)
                def accept(result, part=part):
                    result = _accept(plan, 'cells', len(part), fields, result)
                    if result.descriptor()['cells'] != [c.descriptor() for c in part]:
                        raise GeologyError('sampling worker changed cell support')
                    return result
                yield _AdmittedCall(run, accept, aborted.set, len(part), _cell_bounds(plan, part, fields))
        parts = _drive(plan, tasks(), combined, aborted)
        result = _merge_cells(plan, parts, cells)
        _check_cancel(cancel)
        return result
