"""W01 S7: described geology -> conserved cohorts -> bounded W02 evolution.

Initial thermal descriptions are retained, NOT evolved. The selected S6 spatial
reduction and frozen interval remain explicit. No new physical/numerical law.
"""
from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass, asdict, field
import hashlib
import json
import math

import numpy as np

from atlas_tectonics._validation import TectonicsError, scalar
from atlas_tectonics.planet.geometry import _check_cancel
from atlas_tectonics.history.geological_records import GeologySource
from atlas_tectonics.crust.precursor_sampling import (PreparedPrecursor, save_initial_samples,
                                 load_initial_samples)
from atlas_tectonics.regional.forcing import (PreparedRegionalForcing, save_regional_forcing,
                               load_regional_forcing, _source_from_record)
from atlas_tectonics.regional.workflow_geometry import RegionalColumnSupport, build_workflow_cells
from atlas_tectonics.materials.materials import (MaterialCohort, MaterialState, MaterialBoundary,
    material_timestep_limit, save_material_state, load_material_state, _end_time,
    _hash_array, _transition_record, _positive_total)
from atlas_tectonics.integration.reuse import ExecutionContext, PreparedInput, ReuseController, cached_material_transport, content_record
from atlas_tectonics.integration.resources import select_budget
from atlas_tectonics.integration.resources import json_sha256
from atlas_tectonics.integration.resources import canonical_json as _json

_SCHEMA = 'atlas.regional-workflow.v1'
_THERMAL = 'initial-epoch only; not evolved heat or temperature'
_MAX_STEPS = 256
_MAX_COHORTS = 4096


def _digest(value):  # every caller issues or re-makes workflow_id
    return hashlib.sha256(_json(content_record(value))).hexdigest()


@dataclass(frozen=True, slots=True)
class PoreFluidCohort:
    """An authored origin for one unit's explicit pore phase; never inferred.

Different units can share the SAME explicitly supplied cohort, or name distinct
histories even when their fluid material is identical. Source is evidence, while
cohort.origin_id is material provenance, exactly as in GeologicalCase.
"""
    unit_id: str
    cohort: MaterialCohort
    source: GeologySource

    def __post_init__(self):
        if (type(self.unit_id) is not str or not self.unit_id or
                type(self.cohort) is not MaterialCohort or type(self.source) is not GeologySource):
            raise TectonicsError('explicit unit, fluid cohort and source required')


def _cohorts(initial, fluid_cohorts):
    units = {u.unit_id: u for u in initial.units}
    catalogue = {x.cohort.cohort_id: x.cohort for x in initial.case.cohorts}
    fluid = {}
    for item in fluid_cohorts:
        unit = units.get(item.unit_id)
        if unit is None or unit.fluid_material_id != item.cohort.material_id:
            raise TectonicsError('pore history must name its actual unit and fluid material')
        if item.unit_id in fluid:
            raise TectonicsError('duplicate pore-fluid history for a unit')
        cohort = item.cohort
        if cohort.formation_time_s is not None and cohort.formation_time_s > initial.case.time_s:
            raise TectonicsError('pore cohort formation is later than the initial state')
        catalogue[cohort.cohort_id] = cohort
        fluid[item.unit_id] = cohort.cohort_id
    if not 0 < len(catalogue) <= _MAX_COHORTS:
        raise TectonicsError('workflow cohort count outside resource envelope')
    return tuple(catalogue[k] for k in sorted(catalogue)), fluid


def _initial_material(samples, forcing, fluid_cohorts, budget, cancel=None):
    """Accumulate actual intersection amounts before metric normalisation."""
    initial = samples.state
    catalogue, fluids = _cohorts(initial, fluid_cohorts)
    codes = {c.cohort_id: i for i, c in enumerate(catalogue)}
    md = samples.descriptor()
    grid = forcing.grid
    measure = grid.spacing_m * forcing.reduction.reference_width_m
    rows = samples.array('phase_row')
    count = len(rows)
    with budget.reserve(32*len(catalogue)*grid.cells+96*count+8192,
                        category='workflow-inventory'):
        keys = np.empty(count, dtype=np.int64)
        phase_codes = samples.array('phase_cohort_code')
        units = samples.array('unit_code')
        cells = samples.array('row_cell')
        for i, row in enumerate(rows):
            if i % 1024 == 0:
                _check_cancel(cancel)
            if phase_codes[i] < 0:
                unit_id = initial.units[int(units[row])].unit_id
                cohort_id = fluids[unit_id]
            else:
                cohort_id = md['cohort_ids'][int(phase_codes[i])]
            keys[i] = codes[cohort_id]*grid.cells + int(cells[row])
        # Stable grouping and fsum avoid loss growing with the number of geological
        # fragments. No renormalisation of authored phase-fraction residuals.
        _check_cancel(cancel)
        order = np.argsort(keys, kind='stable')
        _check_cancel(cancel)
        ordered = keys[order]
        volumes = samples.array('phase_volume_m3')[order]
        values = np.zeros((len(catalogue), grid.cells))
        starts = np.r_[0, np.flatnonzero(np.diff(ordered))+1, count]
        for group, (a, b) in enumerate(zip(starts[:-1], starts[1:])):
            if group % 1024 == 0:
                _check_cancel(cancel)
            if a == b:
                continue
            amount = math.fsum(map(float, volumes[a:b]))
            value = amount / measure
            values.flat[int(ordered[a])] = value
        _check_cancel(cancel)
        return MaterialState(grid, catalogue, values, time_s=initial.case.time_s,
                             epoch_id=initial.case.epoch_id, budget=budget)


@dataclass(frozen=True, slots=True, init=False)
class RegionalWorkflowState:
    """Immutable linked accepted states; initial definitions are shared once.

Parent links retain every W02 receipt/external account without copying earlier
arrays into each new state. Returned snapshots are caller-owned retained memory,
as are MaterialState results; keep a finite max_steps and explicit run budget.
"""
    initial_samples: object
    forcing: object
    support: RegionalColumnSupport
    fluid_cohorts: tuple
    material: MaterialState
    parent: object = field(repr=False)
    steps: int
    max_steps: int
    scheme: str
    backend: str
    execution_id: str
    workflow_id: str
    _root: object = field(repr=False)

    @property
    def root_id(self):
        return self.workflow_id if self._root is None else self._root.workflow_id

    def descriptor(self):
        record = dict(schema=_SCHEMA, initial_samples_id=self.initial_samples.sample_id,
            forcing_id=self.forcing.forcing_id, support=asdict(self.support),
            fluid_cohorts=[asdict(x) for x in self.fluid_cohorts],
            material_state_id=self.material.state_id,
            parent_id=None if self.parent is None else self.parent.workflow_id,
            root_id=None if self.parent is None else self.root_id,
            steps=self.steps, max_steps=self.max_steps, scheme=self.scheme,
            backend=self.backend, execution_id=self.execution_id,
            temperature_semantics=_THERMAL,
            inventory_semantics='phase volume / (reference arc-or-planar length * reference width); no density or compaction evolution')
        return json.loads(_json(record))

    @property
    def retained_bytes(self):
        size = (self.initial_samples.nbytes + self.initial_samples.state.retained_bytes_estimate
                + _forcing_bytes(self.forcing, self.initial_samples.state.case.topology))
        node = self
        while node is not None:
            size += node.material.nbytes + len(_json(node.material.descriptor())) + 8192
            node = node.parent
        return size


def _state(samples, forcing, support, fluids, material, parent, max_steps, scheme, backend, execution_id):
    obj = object.__new__(RegionalWorkflowState)
    values = dict(initial_samples=samples, forcing=forcing, support=support,
        fluid_cohorts=fluids, material=material, parent=parent,
        steps=0 if parent is None else parent.steps+1, max_steps=max_steps,
        scheme=scheme, backend=backend, execution_id=execution_id,
        _root=None if parent is None else parent if parent._root is None else parent._root)
    for k, v in values.items():
        object.__setattr__(obj, k, v)
    object.__setattr__(obj, 'workflow_id', json_sha256(content_record(obj.descriptor())))
    return obj


def _policy(scheme, backend, max_steps):
    if scheme not in ('muscl', 'upwind') or backend not in ('numba', 'reference'):
        raise TectonicsError('explicit supported scheme/backend required; no fallback')
    if type(max_steps) is not int or not 1 <= max_steps <= _MAX_STEPS:
        raise TectonicsError('workflow max_steps must be an integer in [1,256]')


def _forcing_bytes(forcing, shared_topology=None):
    size = (sum(a.nbytes for a in forcing.arrays().values())
            + len(forcing._descriptor) + len(forcing.samples._descriptor)
            + 4*len(_json(forcing.definition.descriptor())) + 16384)
    if forcing.definition.topology is not shared_topology:
        size += forcing.definition.topology.retained_bytes_estimate
    return size


def _verify_restored_samples(samples, forcing, support, budget, cancel):
    """Recheck the bridge without recomputing a single geological intersection."""
    cells = build_workflow_cells(samples.state, forcing, support, budget=budget, cancel=cancel)
    md = samples.descriptor()
    case = samples.state.case
    if (samples.kind != 'cells' or md['cells'] != [c.descriptor() for c in cells]
            or md['frame_id'] != forcing.section.frame_id or md['epoch_id'] != case.epoch_id
            or md['time_s'] != case.time_s or md['depth_reference_id'] != case.depth_reference_id
            or md['requested_fields'] or md['overlapping_queries_allowed']
            or md['cohort_ids'] != [x.cohort.cohort_id for x in case.cohorts]
            or md['material_ids'] != [x.material_id for x in case.materials]):
        raise TectonicsError('stored samples disagree with workflow geometry/definitions')
    with PreparedPrecursor(samples.state, budget=budget, cancel=cancel) as sampling:
        if md['plan_id'] != sampling.identity:
            raise TectonicsError('stored samples disagree with current sampling policy/source')


def _verify_history_step(parent, material, forcing, scheme, backend, budget, cancel):
    receipt = material.transition_record
    def boundary(key):
        raw = dict(receipt[key])
        if raw['exterior'] is not None:
            raw['exterior'] = tuple(tuple(x) for x in raw['exterior'])
        return MaterialBoundary(**raw)
    left, right = boundary('left'), boundary('right')
    _transition_record(parent, receipt['duration_s'], left, right,
        scheme, backend, _hash_array(forcing.face_velocity_m_s))
    material_timestep_limit(parent, forcing.face_velocity_m_s,
        left=left, right=right, scheme=scheme, backend=backend, budget=budget).maximum_duration_s
    for i, cohort in enumerate(parent.cohorts):
        _check_cancel(cancel)
        _positive_total(parent.thickness_m[i], backend)*parent.grid.spacing_m
        _positive_total(material.thickness_m[i], backend)*material.grid.spacing_m


class PreparedRegionalWorkflow:
    """Prepare S5/S6 once; branch or resume the same bounded material workflow.

The plan admits its retained preparation for its lifetime. Advance admits all
new linked candidate states during the call, then transfers ownership to caller.
    Consecutive steps are sequential; independent branches may use separate plans.
"""
    def __setattr__(self, name, value):
        object.__setattr__(self, name, value)

    def __init__(self, initial, definition, section, reduction, grid, support, *,
                 fluid_cohorts=(), include_temperature=True, scheme='muscl',
                 backend='numba', max_steps=256, budget=None, cancel=None):
        _check_cancel(cancel)
        _policy(scheme, backend, max_steps)
        _cohorts(initial, fluid_cohorts)
        resource = select_budget(budget)
        with ExitStack() as setup:
            context = setup.enter_context(ExecutionContext(backend))
            # Individual producers release their operation leases when returning
            # caller-owned outputs. Here the workflow is that caller: hold those
            # outputs while subsequent producers allocate their own workspace.
            with ExitStack() as staged:
                with PreparedRegionalForcing(definition, section, reduction, budget=resource, cancel=cancel) as motion:
                    forcing = motion.faces(grid, frame_id=section.frame_id,
                        epoch_id=definition.epoch_id, start_time_s=definition.start_time_s,
                        duration_s=definition.duration_s, cancel=cancel)
                staged.enter_context(resource.reserve(_forcing_bytes(forcing, initial.case.topology),
                                                       category='workflow-setup-retained'))
                cells = build_workflow_cells(initial, forcing, support, budget=resource, cancel=cancel)
                staged.enter_context(resource.reserve(sum(c.footprint.retained_bytes+512 for c in cells),
                                                       category='workflow-setup-retained'))
                with PreparedPrecursor(initial, budget=resource, cancel=cancel) as sampling:
                    samples = sampling.sample_cells(cells, frame_id=section.frame_id,
                        epoch_id=definition.epoch_id, depth_reference_id=initial.case.depth_reference_id,
                        include_temperature=include_temperature, cancel=cancel)
                staged.enter_context(resource.reserve(samples.nbytes, category='workflow-setup-retained'))
                material = _initial_material(samples, forcing, fluid_cohorts, resource, cancel)
                root = _state(samples, forcing, support, fluid_cohorts, material, None,
                              max_steps, scheme, backend, context.identity)
                self._configure(root, context, setup, resource)
                # Brief conservative overlap during handover; never double-held
                # for the prepared plan's lifetime or left uncharged between calls.
            _check_cancel(cancel)
            self._stack = setup.pop_all()

    def _configure(self, root, context, stack, budget):
        self._root = root
        self._context = context
        self._budget = budget
        self._closed = False
        self._controller = ReuseController()
        stack.enter_context(budget.reserve(root.retained_bytes+16384,
                                          category='workflow-prepared'))
        self._velocity = PreparedInput(root.forcing.face_velocity_m_s, budget=budget)

    @classmethod
    def from_state(cls, state, *, budget=None, cancel=None):
        """Resume verified stored definitions without re-sampling geology."""
        _check_cancel(cancel)
        _policy(state.scheme, state.backend, state.max_steps)
        obj = cls.__new__(cls)
        resource = select_budget(budget)
        with ExitStack() as setup:
            context = setup.enter_context(ExecutionContext(state.backend))
            root = state if state._root is None else state._root
            obj._configure(root, context, setup, resource)
            _check_cancel(cancel)
            obj._stack = setup.pop_all()
        return obj

    def _live(self, cancel=None):
        _check_cancel(cancel)

    def initialise(self):
        self._live()
        return self._root

    def advance(self, state, duration_s=None, *, left, right, store=None,
                cache_policy=None, cancel=None):
        self._live(cancel)
        end = _end_time(self._root.material, state.forcing.duration_s)
        remaining = end-state.material.time_s
        dt = remaining if duration_s is None else scalar(duration_s, 'duration_s', positive=True)
        target = _end_time(state.material, dt)
        adviser = material_timestep_limit(state.material, self._velocity.array,
            left=left, right=right, scheme=state.scheme, backend=state.backend, budget=self._budget)
        cap = adviser.maximum_duration_s
        if cap is not None and dt/cap > state.max_steps-state.steps:
            raise TectonicsError('workflow step budget cannot cover the requested interval')
        required = 1 if cap is None else math.ceil(dt/cap)
        if required > state.max_steps-state.steps:
            raise TectonicsError('workflow step budget cannot cover the requested interval')
        current = state
        with ExitStack() as candidates:
            while current.material.time_s < target:
                self._live(cancel)
                if current.steps >= state.max_steps:
                    raise TectonicsError('workflow step budget exhausted; no partial result published')
                interval = target-current.material.time_s
                if cap is not None:
                    interval = min(interval, cap)
                candidates.enter_context(self._budget.reserve(
                    current.material.nbytes+16384+8192*len(current.material.cohorts),
                    category='workflow-candidate-history'))
                result = cached_material_transport(current.material, self._velocity, interval,
                    left=left, right=right, scheme=state.scheme, backend=state.backend,
                    store=store, budget=self._budget, context=self._context,
                    controller=self._controller, cache_policy=cache_policy, cancel=cancel)
                current = _state(state.initial_samples, state.forcing, state.support,
                    state.fluid_cohorts, result.state, current, state.max_steps,
                    state.scheme, state.backend, state.execution_id)
            self._live(cancel)
            return current

    def close(self):
        if not self._closed:
            self._closed = True
            self._stack.close()

    def __enter__(self):
        self._live()
        return self

    def __exit__(self, *args):
        self.close()


def save_regional_workflow(state, store, *, budget=None, cancel=None):
    """Publish dependency-first linked snapshots in the existing deduplicated store."""
    _check_cancel(cancel)
    with ExecutionContext(state.backend):
        save_initial_samples(state.initial_samples, store, budget=budget, cancel=cancel)
        save_regional_forcing(state.forcing, store, budget=budget, cancel=cancel)
        pending = []
        node = state
        while node is not None:
            _check_cancel(cancel)
            if store.contains(node.workflow_id):
                if store.metadata(node.workflow_id) != node.descriptor():
                    raise TectonicsError('stored workflow binding differs')
                break
            pending.append(node)
            node = node.parent
        for node in reversed(pending):
            save_material_state(node.material, store, budget=budget, cancel=cancel)
            store.put(node.workflow_id, {'node': np.empty(0, dtype='u1')}, node.descriptor(),
                      budget=budget, cancel=cancel)
    return state.workflow_id


def load_regional_workflow(store, workflow_id, *, budget=None, cancel=None):
    """Restore original descriptions/receipts, not regenerated or re-evolved fields."""
    resource = store._budget if budget is None else select_budget(budget)
    _check_cancel(cancel)
    metadata = store.metadata(workflow_id)
    if metadata is None:
        return None
    try:
        _policy(metadata['scheme'], metadata['backend'], metadata['max_steps'])
        with ExecutionContext(metadata['backend']) as context, ExitStack() as retained:
            records = []
            key = workflow_id
            while key is not None:
                _check_cancel(cancel)
                if len(records) > metadata['max_steps']:
                    raise TectonicsError('workflow history exceeds declared bound')
                record = store.metadata(key)
                payload = store.get(key, budget=resource)
                if (record is None or record.get('schema') != _SCHEMA or _digest(record) != key
                    or payload is None or set(payload) != {'node'}
                    or payload['node'].dtype != np.dtype('u1') or payload['node'].shape != (0,)):
                    raise TectonicsError('invalid workflow snapshot/dependency')
                retained.enter_context(resource.reserve(len(_json(record))+8192,
                                                        category='workflow-restore'))
                records.append((key, record))
                key = record['parent_id']
            root_record = records[-1][1]
            samples = load_initial_samples(store, root_record['initial_samples_id'], budget=resource, cancel=cancel)
            if samples is None:
                raise TectonicsError('workflow initial sample dependency missing')
            retained.enter_context(resource.reserve(samples.nbytes + samples.state.retained_bytes_estimate,
                                                    category='workflow-restore'))
            forcing = load_regional_forcing(store, root_record['forcing_id'], budget=resource, cancel=cancel)
            if forcing is None:
                raise TectonicsError('workflow forcing dependency missing')
            retained.enter_context(resource.reserve(_forcing_bytes(forcing, samples.state.case.topology),
                                                    category='workflow-restore'))
            raw_support = dict(root_record['support'])
            raw_support['source'] = _source_from_record(raw_support['source'])
            support = RegionalColumnSupport(**raw_support)
            fluids = tuple(PoreFluidCohort(x['unit_id'], MaterialCohort(**x['cohort']),
                _source_from_record(x['source'])) for x in root_record['fluid_cohorts'])
            _verify_restored_samples(samples, forcing, support, resource, cancel)
            parent = None
            for key, record in reversed(records):
                _check_cancel(cancel)
                material = load_material_state(store, record['material_state_id'], budget=resource)
                if material is None:
                    raise TectonicsError('workflow material dependency missing')
                retained.enter_context(resource.reserve(material.nbytes+16384, category='workflow-restore'))
                if parent is None:
                    expected = _initial_material(samples, forcing, fluids, resource, cancel)
                    if material.state_id != expected.state_id:
                        raise TectonicsError('root inventory disagrees with retained initial samples')
                else:
                    _verify_history_step(parent.material, material, forcing, metadata['scheme'],
                                         metadata['backend'], resource, cancel)
                current = _state(samples, forcing, support, fluids, material, parent,
                    metadata['max_steps'], metadata['scheme'], metadata['backend'], context.identity)
                if current.workflow_id != key or current.descriptor() != record:
                    raise TectonicsError('restored workflow binding differs')
                if material.time_s > _end_time(samples.state.case, forcing.duration_s):
                    raise TectonicsError('restored workflow exceeds original forcing interval')
                parent = current
            _check_cancel(cancel)
            return parent
    except (KeyError, TypeError, AttributeError, OverflowError) as exc:
        raise TectonicsError('malformed workflow snapshot') from exc
