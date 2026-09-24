"""W12 identified products and a supported stationary W01--W04 assembly.

SPDX-License-Identifier: AGPL-3.0-only
No new physics, global-regime inference, historical migration or terrain claim.
Native ArrayStore owns durable bytes; a graph receipt alone is not a checkpoint.
"""
from contextlib import contextmanager
from dataclasses import asdict
import hashlib
import json
import threading

import numpy as np

from ._validation import TectonicsError, scalar
from .constitutive import _cancel
from .materials import _json
from .resources import select_budget
from .reuse import ExecutionContext
from .storage import ArrayStore
from .w03_workflow import (W03ColumnState, W03ExecutionContext,
    advance_w03_columns, save_w03_columns, load_w03_columns)
from .w04_workflow import W04SurfaceInputs, W04SupportPolicy, PreparedW04Support


SCHEMA = 'atlas.tectonics-product.v1'
CONTEXT_KEYS = {'world_id', 'snapshot_id', 'calendar_id', 'spatial_frame_id',
                'vertical_reference', 'scenario_id'}


def _hash(value):
    return hashlib.sha256(_json(value)).hexdigest()


def _context(value):
    if (type(value) is not dict or set(value) != CONTEXT_KEYS or
            any(type(x) is not str or not x.strip() or len(x) > 256 for x in value.values())):
        raise TectonicsError('complete explicit world/frame/datum/calendar/scenario context required')
    return json.loads(_json(value))


def _canonical(a):
    a = np.asarray(a)
    if a.dtype.kind not in 'biuf' or not np.isfinite(a).all():
        raise TectonicsError('finite real typed product fields required; use an explicit known mask')
    out = np.array(a, dtype=a.dtype.newbyteorder('<'), order='C', copy=True)
    if out.dtype.kind == 'f':
        out[out == 0] = 0.  # ArrayStore's existing signed-zero normalisation.
    return out


def _field_record(a, specification):
    return dict(specification, dtype=a.dtype.str, shape=list(a.shape),
                sha256=hashlib.sha256(a.tobytes()).hexdigest())


def _verify_native_bindings(descriptor, reference_identity):
    """Do not stamp an old native output as a current-source producer result."""
    bindings = set()
    # Existing producers use these exact schema-owned spellings. A generic
    # world/scenario context ID must not be mistaken for a runtime binding.
    aliases = {
        'atlas.w05-support-result.v1': 'execution',
        'atlas.w08-output.v1': 'execution',
        'atlas.tectonic-history-output.v1': 'execution',
        'atlas.regional-mechanical-snapshot.v1': 'context_id',
        'atlas.free-surface-state.v1': 'context_id',
        'atlas.free-surface-mechanics.v1': 'context_id',
    }
    def visit(value):
        if type(value) is dict:
            alias = aliases.get(value.get('schema'))
            if alias is not None and type(value.get(alias)) is str:
                bindings.add(value[alias])
            for key, item in value.items():
                if key == 'execution_id' and type(item) is str:
                    bindings.add(item)
                visit(item)
        elif type(value) in (list, tuple):
            for item in value:
                visit(item)
    visit(descriptor)
    if not bindings:
        raise TectonicsError('native output has no verifiable execution binding')
    with ExecutionContext('scipy') as scipy, ExecutionContext('numba') as numba:
        allowed = {reference_identity, scipy.identity, numba.identity,
                   _hash(dict(reference=reference_identity, scipy=scipy.identity))}
        if not bindings <= allowed:
            raise TectonicsError('native output source/runtime differs; no automatic rebind')


def _native_owner_binding(output, owner, description, cancel):
    """Authenticate an existing W06 output through its exact native owner, no run."""
    if owner is None:
        return None
    from .w06_workflow import PreparedW06Workflow, W06WorkflowCheckpoint
    from .workflow_ports import describe_workflow_output
    if type(owner) is not PreparedW06Workflow or type(output) is not W06WorkflowCheckpoint:
        raise TectonicsError('native_owner requires exact W06 workflow and checkpoint types')
    owner._check(cancel)
    if owner.checkpoint_id(output.output_index) != output.checkpoint_id:
        raise TectonicsError('W06 output belongs to a different native owner/schedule')
    retained = owner.load(output.output_index, cancel=cancel)
    if retained is None:
        raise TectonicsError('native W06 output is not retained or stored; export cannot compute it')
    expected = describe_workflow_output(retained)
    if (any(expected[key] != description[key] for key in
            ('route', 'source_output_id', 'descriptor', 'field_specs', 'dependencies')) or
            set(expected['fields']) != set(description['fields'])):
        raise TectonicsError('native W06 output metadata differs from authenticated owner')
    for name, field in expected['fields'].items():
        actual = description['fields'][name]
        if field.dtype != actual.dtype or field.shape != actual.shape or field.tobytes() != actual.tobytes():
            raise TectonicsError('native W06 output field differs from authenticated owner: '+name)
    owner._check(cancel)
    binding = dict(schema='atlas.w12-native-w06-owner.v1', execution_id=owner.execution_id,
        plan_id=owner.plan_id, checkpoint_id=output.checkpoint_id, output_index=output.output_index,
        authentication='exact open native owner.load; no physical output computation')
    if not owner.is_margin:
        binding['frame_id'] = owner.prepared.spreading.grid.frame_id
    return binding


def _native_frame_binding(descriptor, context):
    """Only compare explicitly declared identities; never infer a spatial map."""
    frames = set()
    def visit(value):
        if type(value) is dict:
            for key, item in value.items():
                if key == 'frame_id' and type(item) is str and item:
                    frames.add(item)
                visit(item)
        elif type(value) in (list, tuple):
            for item in value:
                visit(item)
    visit(descriptor)
    if len(frames) > 1:
        raise TectonicsError('multiple native frames require an explicit mapping; generic export does not supply one')
    if frames and context['spatial_frame_id'] not in frames:
        raise TectonicsError('caller spatial frame differs from the explicit native frame')
    return dict(native_frame_ids=sorted(frames), frame_identity_checked=bool(frames),
        scope='exact explicit frame identity only; no geometry/support transformation or datum/calendar inference')


def publish_workflow_output(output, store, *, context, scope, budget=None, cancel=None, native_owner=None):
    """Export an existing typed result, not manufacture a new physical result.

    The export is an independently identified consumer product. Native restart
    dependencies remain with the owning workflow; this export is not its restart.
    W06 ocean checkpoints require their exact open native_owner because their
    output state contains only opaque plan IDs, not a standalone runtime binding.
    """
    from .workflow_ports import describe_workflow_output
    if not isinstance(store, ArrayStore):
        raise TectonicsError('ArrayStore required')
    context = _context(context)
    if type(scope) is not str or not scope.strip():
        raise TectonicsError('explicit supported physical scope required')
    resource = store._budget if budget is None else select_budget(budget)
    with resource.reserve(4 << 20, category='w12-export-verifier'), ExecutionContext() as verifier:
        _cancel(cancel)
        description = describe_workflow_output(output)
        owner_binding = _native_owner_binding(output, native_owner, description, cancel)
        binding_descriptor = dict(native=description['descriptor'], native_owner=owner_binding)
        if description['route'] in ('w06-constant.v1','w06-history.v1') and owner_binding is None:
            raise TectonicsError('ocean W06 publication requires its exact open native_owner')
        _verify_native_bindings(binding_descriptor, verifier.identity)
        frame_binding = _native_frame_binding(binding_descriptor, context)
        fields = description['fields']
        total = sum(np.asarray(v).nbytes for v in fields.values())
        with resource.reserve(3*total+65536, category='w12-export-capture'):
            arrays = {k: _canonical(v) for k, v in fields.items()}
            record = dict(schema=SCHEMA, producer='atlas-tectonics-typed-export-v1',
                execution_id=verifier.identity, context=context, scope=scope,
                source_status='WORKING NON-CANON', route=description['route'],
                source_output_id=description['source_output_id'],
                native_descriptor=description['descriptor'],
                native_owner_binding=owner_binding, native_frame_binding=frame_binding,
                dependencies=description['dependencies'],
                fields={k: _field_record(v, description['field_specs'][k]) for k,v in arrays.items()},
                restart_semantics='consumer export only; use native owner and its complete restart dependencies')
            product = json.loads(_json(dict(record, product_id=_hash(record))))
            verifier.verify()
            store.put(product['product_id'], arrays, product, budget=resource, cancel=cancel)
            verifier.verify()
            return product


def read_product(store, product, *, budget=None, expected_context=None):
    """Authenticate current-source metadata and every field before consumption."""
    if not isinstance(store, ArrayStore) or type(product) is not dict:
        raise TectonicsError('typed store and product record required')
    resource = store._budget if budget is None else select_budget(budget)
    with resource.reserve(4 << 20, category='w12-read-verifier'), ExecutionContext() as verifier:
        if product.get('schema') != SCHEMA or product.get('execution_id') != verifier.identity:
            raise TectonicsError('product schema/source/runtime mismatch; no automatic rebind')
        _context(product.get('context'))
        if expected_context is not None and product['context'] != _context(expected_context):
            raise TectonicsError('product context differs')
        record = {k:v for k,v in product.items() if k != 'product_id'}
        pid = _hash(record)
        if product.get('product_id') != pid or store.metadata(pid) != product:
            raise TectonicsError('missing or altered product metadata')
        arrays = store.get(pid, budget=resource)
        if arrays is None or set(arrays) != set(product['fields']):
            raise TectonicsError('missing or incompatible product fields')
        for name, a in arrays.items():
            spec = product['fields'][name]
            if (a.dtype.str != spec['dtype'] or list(a.shape) != spec['shape'] or
                    hashlib.sha256(a.tobytes()).hexdigest() != spec['sha256'] or not np.isfinite(a).all()):
                raise TectonicsError('product field identity/shape differs: '+name)
        verifier.verify()
        return arrays


class PreparedColumnAssembly:
    """One supplied W03 column history and W04 support, through native recovery.

    Reservoir placement and extra pressure are explicit prescribed policies, not
    inferred hydrology. Deflections are totals from the fixed reference, never
    incrementally added to a previous output. The initial state retains W01/W02.
    """
    def __setattr__(self, key, value):
        if getattr(self, '_sealed', False) and not key.startswith('_'):
            raise AttributeError('prepare a new identified assembly to change its definition')
        object.__setattr__(self, key, value)

    def __init__(self, initial, initial_surface, support_policy, schedule, *, store,
                 context, source_id, reservoir_weights, external_pressure_pa,
                 budget=None, cancel=None):
        _cancel(cancel)
        if (type(initial) is not W03ColumnState or type(initial_surface) is not W04SurfaceInputs
                or type(support_policy) is not W04SupportPolicy or not isinstance(store, ArrayStore)):
            raise TectonicsError('typed native column, surface, support and store required')
        if initial_surface.state_id != initial.state_id:
            raise TectonicsError('initial surface belongs to a different column state')
        if type(source_id) is not str or not source_id.strip():
            raise TectonicsError('authored assembly source required')
        if type(schedule) not in (tuple, list) or not 1 <= len(schedule) <= 255:
            raise TectonicsError('one to 255 continuations plus initial output required')
        steps, previous = [], initial.time_s
        for item in schedule:
            if type(item) is not dict or set(item) != {'time_s', 'top_effective_stress_pa'}:
                raise TectonicsError('explicit time and scalar effective traction required')
            now = scalar(item['time_s'], 'output time')
            traction = scalar(item['top_effective_stress_pa'], 'effective traction', nonnegative=True)
            if now <= previous:
                raise TectonicsError('strictly increasing continuation times required')
            steps.append(dict(time_s=now, top_effective_stress_pa=traction)); previous = now
        self._context_record = _json(_context(context))
        geological = initial.source_workflow.initial_samples.state.case
        frame = initial.source_workflow.initial_samples.descriptor()['frame_id']
        if (context['spatial_frame_id'] != frame or
                context['vertical_reference'] != geological.depth_reference_id):
            raise TectonicsError('graph frame/datum must equal the actual geological source')
        self._budget = store._budget if budget is None else select_budget(budget)
        if self._budget is not store._budget:
            raise TectonicsError('assembly and store must share their explicit budget owner')
        n = initial.material.grid.cells
        weights, pressure = _canonical(reservoir_weights), _canonical(external_pressure_pa)
        if (weights.shape != (n,) or pressure.shape != (n,) or np.any(weights < 0)
                or not np.isclose(np.sum(weights), 1., rtol=0., atol=32*np.finfo(float).eps)):
            raise TectonicsError('one normalised nonnegative reservoir weight and pressure per actual cell required')
        weights.setflags(write=False); pressure.setflags(write=False)
        self._weights, self._pressure = weights, pressure
        self.initial, self.initial_surface, self.support_policy, self.store = initial, initial_surface, support_policy, store
        self._schedule = _json(steps)
        self._closed, self._active, self._owner = False, False, threading.get_ident()
        self._verifier = self._support = self._lease = None
        self._stats = dict(computed_outputs=0, restored_outputs=0)
        try:
            self._lease = self._budget.reserve(8*1024**2+16*initial.material.nbytes+65536,
                                               category='w12-assembly-retained')
            self._lease.__enter__()
            self._verifier = W03ExecutionContext()
            if self._verifier.identity != initial.execution_id:
                raise TectonicsError('initial columns belong to a different execution')
            self._support = PreparedW04Support(initial, initial_surface, support_policy, budget=self._budget, cancel=cancel)
            self._definition = _json(dict(schema='atlas.w12-column-assembly.v1', source_id=source_id,
                context=context, initial_state_id=initial.state_id, initial_surface_id=initial_surface.input_id,
                support_plan_id=self._support.plan_id, support_policy=asdict(support_policy), schedule=steps,
                reservoir_weights=weights.tolist(), external_pressure_pa=pressure.tolist(),
                allocation='prescribed fixed fractions of current finite reservoir',
                pressure='prescribed fixed additional pressure; not effective compaction traction',
                execution_id=self._verifier.identity))
            self.plan_id = hashlib.sha256(self._definition).hexdigest()
            self._sealed = True
        except BaseException:
            self.close()
            raise

    @property
    def context(self):
        return json.loads(self._context_record)

    def verify(self):
        if self._closed or threading.get_ident() != self._owner:
            raise TectonicsError('assembly is closed or used outside its owning thread')
        self._verifier.verify()
        if self._verifier.identity != json.loads(self._definition)['execution_id']:
            raise TectonicsError('assembly source/runtime changed')

    def _key(self, index):
        return _hash(dict(schema='atlas.w12-column-checkpoint.v1', plan_id=self.plan_id, index=index))

    def _surface(self, state, cancel):
        return W04SurfaceInputs(state, self.initial_surface.cell_ids,
            self._weights*state.reservoir_fluid_m3, self._pressure,
            source_id=json.loads(self._definition)['source_id'], budget=self._budget, cancel=cancel)

    @contextmanager
    def _operation(self, cancel):
        self.verify(); _cancel(cancel)
        if self._active:
            raise TectonicsError('assembly execution is not reentrant')
        self._active = True
        try:
            yield
            self.verify(); _cancel(cancel)
        finally:
            self._active = False

    def _save(self, state, surface, result, index, cancel):
        # Persist native closure first; publish its graph-visible commit last.
        save_w03_columns(state, self.store, budget=self._budget, cancel=cancel)
        product = publish_workflow_output(result, self.store, context=self.context,
            scope='stationary described columns; prescribed loads; total elastic response from initial reference',
            budget=self._budget, cancel=cancel)
        arrays = self.store.get(product['product_id'], budget=self._budget)
        arrays = dict(arrays, cohort_thickness_m=state.material.thickness_m,
                      grain_volume_m3=state.compaction.grain_volume_m3,
                      void_ratio=state.compaction.void_ratio,
                      reservoir_volume_m3=surface.reservoir_volume_m3)
        specifications = dict(product['fields'])
        for name, unit, owner in (('cohort_thickness_m','m','W02-material'),
                ('grain_volume_m3','m3','W03-compaction'), ('void_ratio','1','W03-compaction'),
                ('reservoir_volume_m3','m3','W03-finite-water')):
            arrays[name] = _canonical(arrays[name])
            specifications[name] = _field_record(arrays[name], dict(units=unit,
                support='actual ordered W01 sampled columns', owner=owner, known='all values known'))
        base = {k:v for k,v in product.items() if k != 'product_id'}
        base.update(producer='atlas-tectonics-column-assembly-v1', plan_id=self.plan_id,
            definition=json.loads(self._definition), fields=specifications,
            time_s=state.time_s, epoch_id=state.material.epoch_id, output_index=index,
            native_state_id=state.state_id, native_state_descriptor=state.descriptor(),
            accounts=dict(total_fluid_m3=state.total_fluid_m3,
                reservoir_fluid_m3=state.reservoir_fluid_m3,
                pore_fluid_m3=float(np.sum(state.compaction.grain_volume_m3*state.compaction.void_ratio)),
                surface_allocation_source=surface.source_id,
                load_ownership='W04 total reference load; thermal exactly once; feedback not applied'),
            restart=dict(checkpoint_id=self._key(index), native_state_id=state.state_id,
                plan_id=self.plan_id, store_dependency='complete ArrayStore including native W01/W02/W03 closure',
                current_source_required=True, output_index=index),
            restart_semantics='reconstruct this exact prepared definition and reopen its complete native store')
        complete = json.loads(_json(dict(base, product_id=_hash(base))))
        self.store.put(complete['product_id'], arrays, complete, budget=self._budget, cancel=cancel)
        self.store.put(self._key(index), {'commit':np.empty(0, dtype='u1')},
            dict(schema='atlas.w12-column-checkpoint.v1', plan_id=self.plan_id,
                 output_index=index, product_id=complete['product_id']), budget=self._budget, cancel=cancel)
        return complete

    def verify_product(self, product):
        self.verify()
        if (type(product) is not dict or product.get('plan_id') != self.plan_id
                or product.get('definition') != json.loads(self._definition)):
            raise TectonicsError('product belongs to a different assembly definition')
        index = product.get('output_index')
        if type(index) is not int or not 0 <= index <= len(json.loads(self._schedule)):
            raise TectonicsError('product index outside declared schedule')
        meta = self.store.metadata(self._key(index))
        expected = dict(schema='atlas.w12-column-checkpoint.v1', plan_id=self.plan_id,
                        output_index=index, product_id=product.get('product_id'))
        marker = self.store.get(self._key(index), budget=self._budget)
        if meta != expected or marker is None or set(marker) != {'commit'} or marker['commit'].shape != (0,):
            raise TectonicsError('assembly output lacks its completed native commit')
        arrays = read_product(self.store, product, budget=self._budget, expected_context=self.context)
        state = load_w03_columns(self.store, product['native_state_id'], budget=self._budget)
        if state is None or json.loads(_json(state.descriptor())) != product['native_state_descriptor']:
            raise TectonicsError('native state dependency differs')
        expected_time = self.initial.time_s if index == 0 else json.loads(self._schedule)[index-1]['time_s']
        if state.time_s != expected_time or product['time_s'] != expected_time:
            raise TectonicsError('native time does not match the declared assembly schedule')
        for name, a in (('cohort_thickness_m',state.material.thickness_m),
                ('grain_volume_m3',state.compaction.grain_volume_m3), ('void_ratio',state.compaction.void_ratio)):
            if not np.array_equal(arrays[name], a):
                raise TectonicsError('native state and exported field disagree')
        self.verify()

    def read_fields(self, product):
        self.verify_product(product)
        return read_product(self.store, product, budget=self._budget, expected_context=self.context)

    def run(self, output_index=None, *, cancel=None):
        with self._operation(cancel):
            schedule = json.loads(self._schedule)
            target = len(schedule) if output_index is None else output_index
            if type(target) is not int or not 0 <= target <= len(schedule):
                raise TectonicsError('output index outside the declared schedule')
            state, product = self.initial, None
            for index in range(target+1):
                _cancel(cancel)
                saved = self.store.metadata(self._key(index))
                if saved is not None:
                    product = self.store.metadata(saved.get('product_id'))
                    self.verify_product(product)
                    restored = load_w03_columns(self.store, product['native_state_id'], budget=self._budget)
                    if index and restored.parent_state_id != state.state_id:
                        raise TectonicsError('restored continuation has a different native parent')
                    state = restored
                    self._stats['restored_outputs'] += 1
                    continue
                if any(self.store.contains(self._key(j)) for j in range(index+1, len(schedule)+1)):
                    raise TectonicsError('checkpoint prefix is incomplete; restore the complete store')
                if index:
                    state = advance_w03_columns(state, **schedule[index-1], store=self.store,
                        budget=self._budget, context=self._verifier, cancel=cancel)
                surface = self.initial_surface if index == 0 else self._surface(state, cancel)
                support = self._support.solve(state, surface, store=self.store, cancel=cancel)
                product = self._save(state, surface, support, index, cancel)
                self._stats['computed_outputs'] += 1
            return product

    def statistics(self):
        return dict(self._stats)

    def close(self):
        if getattr(self, '_closed', False):
            return
        if getattr(self, '_active', False):
            raise TectonicsError('finish or cancel active work before closing')
        try:
            if self._support is not None:
                self._support.close()
        finally:
            try:
                if self._verifier is not None:
                    self._verifier.close()
            finally:
                if self._lease is not None:
                    self._lease.__exit__(None, None, None)
                self._closed = True

    def __enter__(self):
        self.verify()
        return self

    def __exit__(self, *args):
        self.close()
