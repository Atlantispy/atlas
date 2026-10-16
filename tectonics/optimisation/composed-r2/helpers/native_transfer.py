"""Narrow native/collar migrated-state admission; NOT a workflow/run permit.

Inputs are already authenticated by the checkpoint owner. This module checks
their complete native plan graph, exact payload IDs and unchanged physics,
then invokes the actual successor native/collar field gates. It does not read
a store, authenticate acceptance, debit funding or advance time.

The one additive native patch below retains an allocation through immutable
snapshot buffers. It is deliberately not applied to any installed/frozen
source here. Ordinary snapshots keep precisely their original bytes and IDs.
The enclosing workflow must retain/adopt the returned owned result, verify
source receipts and integrate its funding, spatial and transaction histories.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import inspect
import json
import math

import numpy as np


class TransferRefused(ValueError):
    """Unsupported or non-identical scientific/state contract."""


# Exact, reviewable additive patch for regional_execution.py. No monkeypatch,
# runtime identity assignment, metadata relabelling or global registry.
_SNAPSHOT_OLD = '''class RegionalMechanicalSnapshot:
    """Immutable steady outputs; accepted snapshots are not evolving checkpoints."""
    __slots__ = ('_metadata', '_fields', 'result_id')

    def __init__(self, metadata, arrays):
        encoded = _json(metadata)
        fields = tuple((key, tuple(value.shape), frozen(value).tobytes())
                       for key, value in sorted(arrays.items()))
'''
_SNAPSHOT_NEW = '''class _RetainedSnapshotBytes(bytes):
    """Keep admitted storage charged even through an escaped NumPy view."""
    def __new__(cls, value, owner):
        result = super().__new__(cls, value)
        object.__setattr__(result, '_allocation_owner', owner)
        return result

    def __setattr__(self, name, value):
        raise TectonicsError('retained snapshot buffer ownership is immutable')


class RegionalMechanicalSnapshot:
    """Immutable steady outputs; accepted snapshots are not evolving checkpoints."""
    __slots__ = ('_metadata', '_fields', 'result_id')

    def __init__(self, metadata, arrays, *, retained_owner=None):
        encoded = _json(metadata)
        fields = tuple((key, tuple(value.shape), frozen(value).tobytes())
                       for key, value in sorted(arrays.items()))
        if retained_owner is not None:
            encoded = _RetainedSnapshotBytes(encoded, retained_owner)
            fields = tuple((key, shape, _RetainedSnapshotBytes(raw, retained_owner))
                           for key, shape, raw in fields)
'''


def retained_snapshot_source(source: str) -> str:
    """Return the exact proposed successor source; caller owns publication.

    Only the known constructor is accepted. Reapplying or applying to another
    constructor fails, rather than silently changing a different implementation.
    """
    if type(source) is not str or source.count(_SNAPSHOT_OLD) != 1:
        raise TransferRefused('snapshot constructor differs from the reviewed patch base')
    return source.replace(_SNAPSHOT_OLD, _SNAPSHOT_NEW, 1)


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def _hash(value):
    return hashlib.sha256(_json(value)).hexdigest()


def _digest(value, label):
    if (type(value) is not str or len(value) != 64 or
            any(c not in '0123456789abcdef' for c in value)):
        raise TransferRefused(label+' must be an explicit lowercase SHA-256')
    return value


def _keys(value, required, optional=(), *, label):
    if type(value) is not dict or not set(required) <= set(value) or set(value)-set(required)-set(optional):
        raise TransferRefused(label+' has missing or unknown fields')


_TRANSPORT_KEYS = frozenset(('schema', 'cells', 'lengths_m', 'divergence_rtol',
    'max_velocity_correction_m_s', 'max_relative_correction', 'method', 'transport_method',
    'reconstruction', 'maximum_outgoing_courant', 'execution', 'field_order',
    'stress_evolution', 'moving_mesh'))
_HEAT_KEYS = frozenset(('schema', 'cells', 'lengths_m', 'heat_capacity_j_m3_k',
    'conductivity_w_m_k', 'cell_volume_m3', 'execution', 'method', 'boundary_convention',
    'enthalpy_convention', 'linear_relative_tolerance', 'energy_relative_tolerance',
    'automatic_substeps'))
_NATIVE_KEYS = frozenset(('schema', 'cells', 'lengths_m', 'frame_id', 'vertical_datum',
    'material', 'rheology', 'constitutive_scales', 'mechanical_scales', 'boundary_types',
    'mechanics_method', 'transport_method', 'transport_plan_id', 'composition_values',
    'include_viscous_heating', 'projection', 'constitutive_log_tolerance',
    'constitutive_max_iterations', 'constitutive_start', 'pressure', 'sampling', 'depth', 'execution'))
_NATIVE_OPTIONAL = frozenset(('max_components', 'pressure_space', 'physical_mean_pressure_pa',
    'incremental_plastic_history', 'pressure_reference', 'mechanics_selection_policy',
    'mechanics_selection_admission'))
_COLLAR_KEYS = frozenset(('schema', 'native_plan_id', 'volume_map_id', 'embedding', 'cells',
    'lengths_m', 'padding', 'transport_plan_id', 'heat_plan', 'material', 'source_rule',
    'flow_rule', 'scope'))
_NODES = ('native_transport', 'native_heat', 'native', 'collar_transport', 'collar_heat', 'collar')
_STATE_KEYS = frozenset(('schema', 'plan_id', 'frame_id', 'vertical_datum', 'time_s',
    'source', 'parent_state_id', 'inventory', 'histories'))
_FIELD_KEYS = frozenset(('schema', 'plan_id', 'source_id', 'parent_id', 'time_s'))
_REQUIRED_ARRAYS = frozenset(('component_mass_kg', 'enthalpy_j', 'tracer:damage',
    'tracer:accumulated_strain_ii', 'tracer:source_kappa', 'tracer:radial_plastic_kappa'))


def _prepared_plans(native, collar):
    from atlas_tectonics.regional_evolution3d import PreparedRegionalEvolution3D
    from atlas_tectonics.regional_collar3d import PreparedRegionalCollar3D
    if (type(native) is not PreparedRegionalEvolution3D or type(collar) is not PreparedRegionalCollar3D
            or collar._native is not native or collar._budget is not native._resource):
        raise TransferRefused('actual shared-owner native and collar plans required')
    native._verify()
    collar._verify()
    return (native._transport, native._heat, native, collar._transport, collar._heat, collar)


def current_plan_graph(native, collar):
    """Read actual prepared definitions; never set or impersonate their identity."""
    plans = _prepared_plans(native, collar)
    return {name: {'plan_id': plan.plan_id, 'definition': plan.descriptor()}
            for name, plan in zip(_NODES, plans, strict=True)}


def _scientific_graph(graph):
    """Remove only five enumerated execution paths and substitute named edges.

    The embedded collar heat definition must exactly equal its graph node.
    Nothing called execution/plan_id elsewhere is stripped or substituted.
    All remaining nested fields (including every rheology/source/geometry
    field) contribute byte-for-byte canonical JSON to the scientific ID.
    """
    _keys(graph, _NODES, label='plan graph')
    definitions, ids = {}, {}
    for name in _NODES:
        node = graph[name]
        _keys(node, ('plan_id', 'definition'), label=name+' node')
        definition = node['definition']
        if name.endswith('transport'):
            required, optional, schema = _TRANSPORT_KEYS, (), 'atlas.regional3d-transport-plan.v1'
        elif name.endswith('heat'):
            required, optional, schema = _HEAT_KEYS, (), 'atlas.regional-heat3d-plan.v1'
        elif name == 'native':
            required, optional, schema = _NATIVE_KEYS, _NATIVE_OPTIONAL, 'atlas.regional-evolution3d-plan.v1'
        else:
            required, optional, schema = _COLLAR_KEYS, ('component_registry', 'mechanics_scope'), 'atlas.regional-collar-plan.v1'
        _keys(definition, required, optional, label=name+' definition')
        if definition['schema'] != schema:
            raise TransferRefused('unknown '+name+' schema')
        ids[name] = _digest(node['plan_id'], name+' plan ID')
        if _hash(definition) != ids[name]:
            raise TransferRefused(name+' definition/ID mismatch')
        # Canonical JSON is also a defensive copy; NaN and opaque objects fail.
        definitions[name] = json.loads(_json(definition))
    native, collar = definitions['native'], definitions['collar']
    if (native['transport_plan_id'] != ids['native_transport'] or
            collar['native_plan_id'] != ids['native'] or
            collar['transport_plan_id'] != ids['collar_transport'] or
            _json(collar['heat_plan']) != _json(definitions['collar_heat'])):
        raise TransferRefused('explicit nested plan-ID correspondence failed')
    executions = {name: definitions[name]['execution'] for name in _NODES if name != 'collar'}
    for name, execution in executions.items():
        _digest(execution, name+' execution identity')
    if len(set(executions.values())) != 1:
        raise TransferRefused('one actual runtime required throughout a native/collar graph')
    for name in executions:
        del definitions[name]['execution']
    native['transport_plan_id'] = _hash(definitions['native_transport'])
    collar['native_plan_id'] = _hash(native)
    collar['transport_plan_id'] = _hash(definitions['collar_transport'])
    collar['heat_plan'] = definitions['collar_heat']
    return definitions, ids, executions


def compare_scientific_contract(historical_graph, current_graph):
    """Complete closed-schema graph equivalence, not compatibility permission."""
    old, old_ids, old_execution = _scientific_graph(historical_graph)
    new, new_ids, new_execution = _scientific_graph(current_graph)
    if _json(old) != _json(new):
        different = [name for name in _NODES if _json(old[name]) != _json(new[name])]
        raise TransferRefused('non-execution scientific contract changed: '+', '.join(different))
    # A shared old ID must never correspond to different new IDs (and vice versa).
    for a in _NODES:
        for b in _NODES:
            if (old_ids[a] == old_ids[b]) != (new_ids[a] == new_ids[b]):
                raise TransferRefused('derived plan ID alias correspondence changed')
    return dict(schema='atlas.native-collar-scientific-contract.v1',
        scientific_contract_id=_hash(dict(schema='atlas.native-collar-scientific-contract.v1',
                                          definitions=old)),
        plan_id_correspondence={name: dict(historical=old_ids[name], current=new_ids[name]) for name in _NODES},
        producer_execution=old_execution, reader_execution=new_execution)


def _array_records(arrays, label):
    if type(arrays) is not dict or not _REQUIRED_ARRAYS <= set(arrays) or len(arrays) > 67:
        raise TransferRefused(label+' requires the complete six-field history payload')
    records = {}
    for name, array in arrays.items():
        if (type(name) is not str or len(name) > 256 or
                name not in _REQUIRED_ARRAYS | {'material_quadrature_m3'} and not name.startswith('tracer:')):
            raise TransferRefused('unknown '+label+' array field')
        if (type(array) is not np.ndarray or array.dtype != np.dtype(np.float64)
                or not array.dtype.isnative or not array.flags.c_contiguous):
            raise TransferRefused(label+' payload must be native binary64 C-order; no conversion')
        records[name] = dict(dtype=array.dtype.str, shape=list(array.shape), nbytes=array.nbytes,
                            sha256=hashlib.sha256(memoryview(array).cast('B')).hexdigest())
    return records


def _snapshot_id(metadata, bindings):
    return _hash(dict(metadata=metadata, arrays={name: dict(shape=row['shape'], sha256=row['sha256'])
                                               for name, row in bindings.items()}))


class _Allocation:
    """One reservation, released only after the last retained byte owner dies."""
    def __init__(self, budget, size, *, category='native-collar-migrated-state-retained'):
        self._guard = None
        self.size = size
        guard = budget.reserve(size, category=category)
        guard.__enter__()
        self._guard = guard

    def __del__(self):
        guard = self._guard
        if guard is not None:
            self._guard = None
            guard.__exit__(None, None, None)


class _RecordBytes(bytes):
    def __new__(cls, value, allocation):
        result = super().__new__(cls, value)
        object.__setattr__(result, '_allocation', allocation)
        return result

    def __setattr__(self, name, value):
        raise TransferRefused('transfer provenance ownership is immutable')


@dataclass(frozen=True)
class OwnedMigratedNativeCollar:
    """Owned local state only; adopting this object conveys no run capability."""
    state: object
    _record: bytes

    @property
    def transfer_id(self):
        return hashlib.sha256(self._record).hexdigest()

    def record(self):
        return json.loads(self._record)

    @property
    def retained_bytes(self):
        return self._record._allocation.size


class MigratedStateLease:
    """Explicit local adoption boundary, with buffer-backed retained charging.

    Borrow state inside ``with lease`` for validation. ``adopt()`` returns its
    immutable owner object for workflow integration. Closing drops this lease's
    references; escaped states, arrays, or exception frames STILL retain the
    charge through their buffer owners. It never implies saved acceptance.
    """
    def __init__(self, value):
        self._value, self._active, self._closed = value, False, False

    def __enter__(self):
        if self._active or self._closed:
            raise TransferRefused('transfer lease is single-use')
        self._active = True
        return self

    def __exit__(self, *details):
        self._active, self._closed, self._value = False, True, None

    @property
    def state(self):
        if not self._active or self._value is None:
            raise TransferRefused('state must be borrowed inside the active transfer lease')
        return self._value.state

    def adopt(self):
        if not self._active or self._value is None:
            raise TransferRefused('transfer ownership may be adopted exactly once inside its lease')
        value, self._value = self._value, None
        return value


def _width(value):
    # Conservative bounded traversal BEFORE serialization or array copying.
    # Includes Python container/decoded-metadata overhead, not just JSON bytes.
    if value is None or type(value) is bool:
        return 32
    if type(value) is int:
        return 64+(value.bit_length()+7)//8
    if type(value) is float:
        if not math.isfinite(value):
            raise TransferRefused('nonfinite contract value')
        return 64
    if type(value) is str:
        return 128+8*len(value)
    if type(value) in (tuple, list):
        return 128+sum(32+_width(v) for v in value)
    if type(value) is dict:
        if any(type(k) is not str for k in value):
            raise TransferRefused('contract keys must be text')
        return 256+sum(64+_width(k)+_width(v) for k, v in value.items())
    raise TransferRefused('opaque contract value')


def admit_migrated_native_collar(*, native, collar, historical_graph,
        historical_native, historical_native_id, native_arrays, historical_collar,
        collar_arrays, origin):
    """Validate and copy an evolved native/collar endpoint without reinitialising.

    ``origin`` binds the external authenticated producer receipt, original store
    token and endpoint lineage. Hashes are bindings, NOT authentication here.
    Unsupported exterior-heat state fails closed; its owner needs a separate
    complete operator graph/transfer seam, never deletion from this payload.
    The shared WorkBudget admits transient copying/validation separately from
    exact persistent payload/provenance bytes plus bounded object overhead.
    A held exception retains transient charges while its frames retain data;
    successful outputs retain only persistent storage, including escaped views.
    """
    from atlas_tectonics.regional_execution import RegionalMechanicalSnapshot
    from atlas_tectonics.regional_collar3d import RegionalCollarState
    plans = _prepared_plans(native, collar)
    if 'retained_owner' not in inspect.signature(RegionalMechanicalSnapshot).parameters:
        raise TransferRefused('reviewed retained snapshot constructor support is required')
    _keys(origin, ('producer_receipt_sha256', 'store_token_sha256', 'endpoint_lineage_sha256'),
          label='authenticated origin binding')
    for name, value in origin.items():
        _digest(value, name)
    _keys(historical_native, _STATE_KEYS, label='historical native state')
    _keys(historical_collar, ('schema', 'fields', 'native', 'result_id'), label='historical collar state')
    _keys(historical_collar['fields'], _FIELD_KEYS, label='historical collar fields')
    # No allocation proportional to array elements before shared admission.
    # The supplied caller-owned input buffers remain charged to their caller.
    array_bytes = 0
    for arrays in (native_arrays, collar_arrays):
        if type(arrays) is not dict or len(arrays) > 67:
            raise TransferRefused('bounded complete field dictionaries required')
        for array in arrays.values():
            if type(array) is not np.ndarray:
                raise TransferRefused('exact ndarray payloads required')
            array_bytes += array.nbytes
    metadata_bytes = sum(_width(value) for value in
        (historical_graph, historical_native, historical_collar, origin))
    # Inspect already owned definitions without copying them before admission.
    metadata_bytes += sum(_width(plan._definition) for plan in plans)
    field_count = len(native_arrays)+len(collar_arrays)
    # _array may freeze each field; native _fields also retains total, T, td,
    # composition and damage plus quadrature and reduction temporaries. Collar
    # _fields validates native first, then its own full grid. Four field copies
    # and 24 extra scalar grids per domain cover these simultaneous arrays and
    # the constructor's ordinary bytes -> retained bytes conversion. No solver
    # or advance work envelope is retained or admitted by this path.
    scratch_size = (65536+4*array_bytes+12*metadata_bytes+8192*field_count+
                    192*(math.prod(native.cells)+math.prod(collar.cells))+
                    1024*len(native._composition))
    # Deliberately local, not a with/finally release: a held traceback keeps
    # this owner AND its partial decoded/copy/validation buffers alive together.
    _scratch = _Allocation(native._resource, scratch_size, category='native-collar-transfer-scratch')
    current = current_plan_graph(native, collar)
    with native._operation(None), collar._operation(None):
        compatibility = compare_scientific_contract(historical_graph, current)
        old_native_plan = historical_graph['native']['plan_id']
        old_collar_plan = historical_graph['collar']['plan_id']
        if (historical_native['schema'] != 'atlas.regional-evolution3d-state.v1' or
                historical_collar['schema'] != 'atlas.regional-collar-state.v1' or
                historical_collar['fields']['schema'] != 'atlas.regional-collar-fields.v1' or
                historical_native['plan_id'] != old_native_plan or
                historical_collar['fields']['plan_id'] != old_collar_plan or
                _json(historical_collar['native']) != _json(historical_native)):
            raise TransferRefused('historical state/graph/embedded-native binding differs')
        definition = current['native']['definition']
        if (historical_native['frame_id'] != definition['frame_id'] or
                historical_native['vertical_datum'] != definition['vertical_datum'] or
                historical_native['inventory'] != 'reference mass and sensible enthalpy m*cp*T' or
                historical_native['histories'] != 'mass-weighted scalar fields; no elastic tensor or free-surface state'):
            raise TransferRefused('native state scientific metadata differs')
        clock = historical_native['time_s']
        if (type(clock) not in (float, int) or not math.isfinite(clock) or clock < 0 or
                _json(clock) != _json(historical_collar['fields']['time_s'])):
            raise TransferRefused('historical exact native/collar clock differs')
        native_binding = _array_records(native_arrays, 'native')
        collar_binding = _array_records(collar_arrays, 'collar')
        if set(native_binding) != set(collar_binding):
            raise TransferRefused('historical native/collar history sets differ')
        if _snapshot_id(historical_native, native_binding) != _digest(historical_native_id, 'native state ID'):
            raise TransferRefused('historical native payload/ID mismatch')
        old_fields_id = _snapshot_id(historical_collar['fields'], collar_binding)
        old_collar_id = _hash(dict(fields_id=old_fields_id, native_state_id=historical_native_id))
        if old_collar_id != _digest(historical_collar['result_id'], 'collar state ID'):
            raise TransferRefused('historical collar payload/ID mismatch')
        transfer_input = dict(schema='atlas.native-collar-transfer-input.v1', compatibility=compatibility,
            origin=origin, historical_plan_graph=historical_graph, current_plan_graph=current,
            historical_native=historical_native, historical_native_id=historical_native_id,
            historical_collar=historical_collar, native_arrays=native_binding, collar_arrays=collar_binding)
        transfer_input_id = _hash(transfer_input)
        # Copy every exact field. Source and parent distinguish the new admitted
        # derivative from its historical source; old metadata is retained above.
        new_meta = dict(historical_native, plan_id=native.plan_id,
                        source=transfer_input_id, parent_state_id=historical_native_id)
        new_field_meta = dict(historical_collar['fields'], plan_id=collar.plan_id,
                             source_id=transfer_input_id, parent_id=old_collar_id)
        new_native_id = _snapshot_id(new_meta, native_binding)
        new_fields_id = _snapshot_id(new_field_meta, collar_binding)
        new_collar_record = dict(schema='atlas.regional-collar-state.v1', fields=new_field_meta,
            native=new_meta, result_id=_hash(dict(fields_id=new_fields_id, native_state_id=new_native_id)))
        record = dict(schema='atlas.native-collar-migrated-state.v1', input=transfer_input,
            transfer_input_id=transfer_input_id, current_native=new_meta,
            current_native_id=new_native_id, current_collar=new_collar_record,
            validation=dict(native_fields=True, collar_fields=True, payload_bytes_unchanged=True),
            elapsed_time_s=0, funding_debit_applied=False, scientific_acceptance=False,
            continuation_authorised=False)
        encoded_record = _json(record)
        # Exact retained payload + serialized metadata/provenance, with a
        # bounded allowance for tuple/bytes/shape/owner objects. This is NOT the
        # scratch/solver estimate and does not grow with solve complexity.
        retained_payload = array_bytes+len(_json(new_meta))+len(_json(new_field_meta))+len(encoded_record)
        retained_overhead = 4096+1024*field_count+256*sum(a.ndim for arrays in
            (native_arrays, collar_arrays) for a in arrays.values())
        allocation = _Allocation(native._resource, retained_payload+retained_overhead)
        new_native = RegionalMechanicalSnapshot(new_meta, native_arrays, retained_owner=allocation)
        new_fields = RegionalMechanicalSnapshot(new_field_meta, collar_arrays, retained_owner=allocation)
        new_state = RegionalCollarState(new_fields, new_native)
        native._fields(new_native)
        collar._fields(new_state)
        collar._exterior_bound(new_state, None)
        # Rehash actual owned copies, detecting concurrent/accidental input
        # mutation during construction as well as any implicit dtype conversion.
        if (_array_records({k: new_native.array(k) for k in new_native.array_names}, 'native') != native_binding or
                _array_records(new_state.arrays(), 'collar') != collar_binding):
            raise TransferRefused('copied historical bytes changed during transfer')
        if new_native.result_id != new_native_id or _json(new_state.record()) != _json(new_collar_record):
            raise TransferRefused('new immutable snapshot identity differs from exact transfer calculation')
        owned = OwnedMigratedNativeCollar(new_state, _RecordBytes(encoded_record, allocation))
        return MigratedStateLease(owned)
