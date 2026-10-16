"""Private completed-interval heat binding, distinct from every live issuer.

The caller must independently restore the committed parent/head, actual owner,
transport and source audit. This module authenticates the heat CAS against that
context; it cannot discover/open a workflow or resume an unpublished interval.
No OwnerHeatCall, SpatialOwnerTransport or ComposedHeatResult is constructed.
Historical source-inventory IDs remain authenticated provenance, not re-issued
donor inventories. Exact stored ledger checks reuse the frozen CAS9 equations.
JSON views follow resources r4: every stream hash of the committed exchange,
the owner definition or the runtime provenance is funded by its own codec
scope, and restore releases its decoded views before its closing re-validation.
"""
from dataclasses import dataclass, field
from hashlib import sha256
import json
import math
from pathlib import Path
import sys

import numpy as np
import private_heat_checkpoint_consumer_r10 as C
import private_heat_issuer_resources_r4 as R
import private_heat_native_issuer_r13 as I
import private_heat_snapshot_store_r4 as STORE
from atlas_tectonics.integration_spatial_owner import PreparedSpatialOwner, SpatialExteriorState
from atlas_tectonics.regional_collar3d import RegionalCollarState
from atlas_tectonics.regional_execution import RegionalMechanicalSnapshot
from atlas_tectonics.integration_exterior_mesh import ExteriorMesh
from atlas_tectonics.integration_mimetic_heat import MimeticGeometry
from atlas_tectonics.reuse import ExecutionContext
import spatial_indexed_patch as _INDEXED_SPATIAL
import private_heat_indexed_runtime as _INDEXED_HEAT

# Fixed dependencies retain their original paths and byte pins.
HERE = Path(C.__file__).resolve().parent
SCHEMA = 'atlas.private.restored-composed-heat-binding.r1'
EXCHANGE_SCHEMA = 'atlas.private.spatial-composed-advance.r1'
REF_SCHEMA = 'atlas.private.joined-heat-reference.r1'
_PINS = {
    'private_heat_checkpoint_consumer_r10.py': 'ccf72a4831f987b024dc38debedae7502ca3f1d1b3cfee980ff0f7ded2a0dec2',
    'private_heat_native_issuer_r13.py': '9395513acc8f2920fd244bdc08f1b052e2e98b7018a6c8c7e66b45dd9017536a',
    'private_heat_issuer_resources_r4.py': 'f80d741c76586a41fa1a49415c19f72a0bb1eb3b0e1726e1d8cb52df2dcffdd6',
    'private_heat_snapshot_store_r4.py': '8d2069737d55533f352a566b7b83fb46ea415a5fb58d57f10f66d14ec9aa1d49',
    'private_heat_forward_kernel_r13.py': '5c9ad7371e30f29ad56865cbad109c5bfce9fc0c5dab8fc0a015fa52e512826d',
    'private_heat_grouped_account_r1.py': '392eb3d3ed0d73dccbbdac1a2eddc5e1409ef1e8c5b84fd773bcc35e4d910d60',
    'private_heat_joined_consumer_r6.py': 'd6d3bcba91f39b304f80bb628ebd6af21be5d77c60db14e73bca250687fcba1e',
}
_SOURCES = {str(HERE/name): pin for name, pin in _PINS.items()}
_SOURCES[str(Path(__file__).resolve())] = R.source_hash(__file__)


def _verify(execution, cancel):
    R.check(cancel)
    if type(execution) is not ExecutionContext or execution.backend != 'scipy':
        raise TypeError('Fresh actual scipy execution context required')
    execution.verify_boundary()
    C._verify(cancel)
    I._verify_implementation()
    for path, pin in _SOURCES.items():
        if R.source_hash(path, cancel) != pin:
            raise ValueError('Cold binding source changed: '+path)


def _snapshot(snapshot, budget, cancel):
    if type(snapshot) is not RegionalMechanicalSnapshot:
        raise TypeError('Independently restored immutable native snapshot required')
    if I._snapshot_identity(snapshot, budget, cancel) != snapshot.result_id:
        raise ValueError('Restored native snapshot identity differs')


def _same_arrays(actual, expected):
    return (set(actual) == set(expected) and all(
        type(actual[k]) is np.ndarray and actual[k].dtype == np.dtype('float64')
        and actual[k].shape == expected[k].shape
        and np.array_equal(actual[k].view(np.uint8), expected[k].view(np.uint8)) for k in expected))


def _expected_bindings(reference, plan, geometry_id, transport_id, execution, cancel):
    """Derive from fixed code/current runtime and independently bound context."""
    import private_heat_joined_consumer_r6 as J
    sources = J.source_bindings(cancel=cancel)
    expected_sources = {name: _PINS[name] for name in (
        'private_heat_native_issuer_r13.py', 'private_heat_checkpoint_consumer_r10.py',
        'private_heat_forward_kernel_r13.py', 'private_heat_grouped_account_r1.py',
        'private_heat_joined_consumer_r6.py')}
    if sources != expected_sources:
        raise ValueError('Current joined consumer differs from agreed fixed sources')
    if (reference.get('schema') != REF_SCHEMA or reference.get('consumer_sources') != sources
            or reference.get('ledger') != 'complete immutable cell/paired-face ledger in authenticated CAS'):
        raise ValueError('Bounded composed heat reference required')
    expected = dict(consumer=R.stream_hash(C._SOURCES, cancel), call=reference['call_id'],
        plan=R.stream_hash(plan, cancel), geometry=geometry_id, state=transport_id,
        loaded_dependencies=I._LOADED_IMPLEMENTATION.descriptor()['identity'],
        runtime=R.stream_hash(execution.provenance, cancel),
        fixture_status=sha256(b'actual-owner').hexdigest())
    if (reference.get('plan_id') != expected['plan'] or reference.get('geometry_id') != geometry_id
            or reference.get('state_id') != transport_id
            or reference.get('loaded_dependency_identity') != expected['loaded_dependencies']
            or reference.get('runtime_identity') != expected['runtime']
            or reference.get('fixture_status') != expected['fixture_status']
            or reference.get('original_target') != plan.get('original_target')
            or reference.get('native_admission') is not False or reference.get('production_acceptance') is not False):
        raise ValueError('Committed heat source/runtime/plan/target/reference differs')
    return expected


def _inputs(ar, transport, mesh, component_count, cp):
    """Exact original producer projection and per-cell contiguous sum order."""
    keys = transport['cell_ids']
    if len(set(keys)) != len(keys):
        raise ValueError('Restored transport cell order contains duplicates')
    positions = {key: at for at, key in enumerate(keys)}
    fields = transport['exact_stocks']
    required = ('enthalpy_j', *(f'component_mass_kg:{i}' for i in range(component_count)))
    if any(k not in fields or len(fields[k]) != len(keys) for k in required):
        raise ValueError('Complete original transported energy/component fields required')
    old, capacity = [], []
    for row in mesh['cells']:
        ar.check()
        at = positions[row['logical_cell_id']]
        old.append(ar.public(ar.decode(fields['enthalpy_j'][at])))
        masses = np.asarray([ar.public(ar.decode(fields[f'component_mass_kg:{i}'][at]))
                             for i in range(component_count)], dtype=np.float64)
        capacity.append(float(np.sum(masses)*cp))
    if any(not math.isfinite(v) or v <= 0 for values in (old, capacity) for v in values):
        raise ValueError('Restored original E/C must be finite and positive')
    return dict(input_enthalpy_j=np.asarray(old), input_capacity_j_k=np.asarray(capacity),
                input_source_w=np.zeros(len(old)))


def _equations(snapshot, meta, geometry, expected, plan, dt, budget, cancel):
    # Holds what its exact arithmetic takes where the process meter supports the runtime;
    # elsewhere, and inside a scope that is metered already, its calculated reservations.
    with I.F.METER.scope(budget, ('private-cold-heat-equations',), 'cold-heat-equations'):
        _equations_body(snapshot, meta, geometry, expected, plan, dt, budget, cancel)


def _equations_body(snapshot, meta, geometry, expected, plan, dt, budget, cancel):
    G = R.A.exact_library()
    import private_heat_gmp_resources_r1 as GMP
    workspace = GMP.OwnedWorkspace(budget, 65536, category='private-cold-heat-equations', cancelled=cancel)
    workspace.__enter__()
    owner = R.O._OwnerWorkspace(workspace)
    try:
        ar = R._ProjectionArithmetic(workspace, G, GMP, len(geometry._cells), len(geometry._face_ids),
                                     1075, lambda: R.check(cancel))
        owner.arithmetic = ar
        arrays = {name: snapshot.array(name) for name in C._FIELDS}
        if any(v.dtype != np.dtype('float64') or v.shape != (len(geometry._cells),)
               or not np.isfinite(v).all() for v in arrays.values()):
            raise ValueError('Complete finite original stored heat arrays required')
        if not _same_arrays({k: arrays[k] for k in expected}, expected):
            raise ValueError('Saved heat inputs differ from independent transported E/C/source')
        C._equations(ar, meta, geometry, arrays, plan, dt)
        del arrays
        ar.settle(())
        owner.__exit__(None, None, None)
    except BaseException:
        owner.__exit__(*sys.exc_info())
        raise


class _IndexedCharge:
    """One reservation released only when its holder is dropped (held errors keep it)."""
    __slots__ = ('_guard',)

    def __init__(self, budget, size, category):
        self._guard = None
        guard = budget.reserve(size, category=category)
        guard.__enter__()
        self._guard = guard

    def __del__(self):
        guard, self._guard = self._guard, None
        if guard is not None:
            guard.__exit__(None, None, None)


def _indexed_spatial(snapshot, states):
    """Only the two spatial endpoint snapshots may be indexed; all others stay native."""
    return (type(snapshot) is _INDEXED_SPATIAL.IndexedSpatialSnapshot
            and any(snapshot is state._snapshot for state in states))


def _indexed_snapshot(snapshot, budget, cancel):
    # The issuer's indexed identity: the complete logical record streamed from
    # the owned metadata bytes and every byte of the sealed compact mesh.
    R.check(cancel)
    if snapshot._budget is not budget:
        raise ValueError('indexed snapshot has a foreign resource owner')
    if _INDEXED_SPATIAL.snapshot_identity(snapshot) != snapshot.result_id:
        raise ValueError('Restored native snapshot identity differs')


def _indexed_metadata_view(snapshot, budget, cancel):
    """r4 JSON view of indexed small metadata, decoded from an exact charged copy.

    Resources r4 admits exact ``bytes`` only, while indexed metadata is an
    owning bytes subclass. The copy is charged before it exists; a held
    traceback keeps both. The r4 view retains only the decoded value.
    """
    R.check(cancel)
    metadata = snapshot._metadata
    if not isinstance(metadata, bytes):
        raise TypeError('Owned indexed snapshot metadata bytes required')
    charge = _IndexedCharge(budget, 65536+len(metadata), 'private-cold-indexed-metadata')
    raw = bytes(metadata)
    view = R.decoded(raw, budget=budget, cancel=cancel)
    del raw, charge
    return view


class _IndexedThermal:
    """Bounded endpoint-mesh rows for the original checks; never an expanded record.

    Header fields come from one owned header decode, cells one owned row at a
    time, required boundary faces from the sealed integer face references.
    Other whole tables are refused rather than reported absent.
    """
    __slots__ = ('_mesh', '_rows', '_required')
    _WHOLE = frozenset(('faces', 'support_tables', 'grid_lines', 'thermal_shared_lines'))

    def __init__(self, mesh, budget):
        if type(mesh) is not ExteriorMesh or not mesh.is_compact or mesh._resource is not budget:
            raise TypeError('Actual same-budget compact endpoint mesh required')
        self._mesh, self._rows, self._required = mesh, _INDEXED_HEAT.mesh_rows(mesh), None

    def _faces(self):
        if self._required is None:
            view = _INDEXED_HEAT.stored_mesh(self._mesh)
            if not view._required:
                self._required = (None, None)
            else:
                indexes = view._arrays['required.face']
                charge = _IndexedCharge(view.budget, 65536+128*len(indexes), 'private-cold-indexed-required-faces')
                self._required = ([view.face_id(int(index)) for index in indexes], charge)
        return self._required[0]

    def __getitem__(self, name):
        if name == 'required_thermal_boundary_faces':
            faces = self._faces()
            if faces is None:
                raise KeyError(name)
            return faces
        if name in self._WHOLE:
            raise TypeError('Indexed endpoint mesh exposes rows, never a whole table: '+name)
        return self._rows[name]

    def get(self, name, default=None):
        try:
            return self[name]
        except KeyError:
            return default

    def __contains__(self, name):
        if name == 'cells':
            return True
        if name == 'required_thermal_boundary_faces':
            return self._faces() is not None
        if name in self._WHOLE:
            raise TypeError('Indexed endpoint mesh exposes rows, never a whole table: '+name)
        return name in self._rows.header.value


def _indexed_endpoint_differs(mesh, thermal, current, owner, graph, exchange):
    # The original endpoint gates, read from owned header rows. Indexed metadata
    # binds the sealed mesh by its streamed logical ID and must not also carry
    # an expanded copy; the whole mesh record is never rebuilt to compare it.
    return (mesh.geometry_id != current['thermal_mesh_id'] or 'thermal_mesh' in current
            or thermal['funding_id'] != owner._funding.funding_id or thermal['funding_id'] != graph['funding_id']
            or thermal['grid_id'] != owner._definition['grid_id'] or thermal['grid_id'] != graph['grid_id']
            or thermal['support_id'] != graph['end_support_id']
            or thermal['trajectory_id'] != graph['trajectory_id'] or thermal['time_s'] != graph['end_time_s']
            or ('source' in thermal) != ('source' in graph) or thermal.get('source') != graph.get('source')
            or 'booked_cell_rule' in thermal and thermal['booked_cell_rule'].get('closed_graph_id') != exchange['spatial_graph_id'])


def _indexed_geometry(mesh, geometry, budget, cancel):
    """Indexed metric of the sealed endpoint mesh; a retained one is rehashed by streaming."""
    if geometry is None:
        return MimeticGeometry.from_compact(_INDEXED_HEAT.stored_mesh(mesh), budget=budget)
    if (type(geometry) is not MimeticGeometry or geometry._budget is not budget
            or _INDEXED_HEAT.metric_identity(geometry, cancel=cancel) != mesh.geometry_id):
        raise ValueError('Retained restored metric differs from actual endpoint')
    return geometry


def _context(owner, parent_spatial_state, parent_collar_state, state, collar_state,
             mesh, transport_snapshot, source_audit, exchange, execution, target, budget, cancel, work,
             geometry=None):
    _verify(execution, cancel)
    if (type(owner) is not PreparedSpatialOwner or owner._budget is not budget
            or any(type(s) is not SpatialExteriorState or s._budget is not budget
                   for s in (parent_spatial_state, state))
            or any(type(s) is not RegionalCollarState for s in (parent_collar_state, collar_state))
            or type(mesh) is not ExteriorMesh or mesh._resource is not budget):
        raise TypeError('Independent restored actual owner/parent/head/mesh on one budget required')
    if owner._heat_label != 'PRIVATE uniform-k composed physical-face heat; original transported caloric stocks':
        raise ValueError('Restored owner must explicitly declare the composed heat method')
    owner.validate_parent(parent_spatial_state, parent_collar_state)
    owner.validate_parent(state, collar_state)
    snapshots = (parent_spatial_state._snapshot, state._snapshot, parent_collar_state.fields,
        parent_collar_state.native_state, collar_state.fields, collar_state.native_state,
        transport_snapshot, source_audit)
    for snapshot in snapshots:
        if _indexed_spatial(snapshot, (parent_spatial_state, state)):
            _indexed_snapshot(snapshot, budget, cancel)
        else:
            _snapshot(snapshot, budget, cancel)
    # r1 views carried a codec share for life. The stream hashes below are of
    # the committed exchange or a part of it; they are funded here for as long
    # as the caller's scope lives.
    work.stack.enter_context(R.codec_for_value(exchange, budget=budget, cancel=cancel))
    if _indexed_spatial(parent_spatial_state._snapshot, (parent_spatial_state, state)):
        parent_view = work.stack.enter_context(_indexed_metadata_view(
            parent_spatial_state._snapshot, budget, cancel))
    else:
        parent_view = work.stack.enter_context(R.decoded(
            parent_spatial_state._snapshot._metadata, budget=budget, cancel=cancel))
    # The selected fields are separately owned copies, never uncharged aliases.
    parent = work.stack.enter_context(R.extracted(parent_view,
        {'intervals': R.ALL, 'time_s': R.ALL}, budget=budget, cancel=cancel)).value
    parent_view.close()
    if _indexed_spatial(state._snapshot, (parent_spatial_state, state)):
        current = work.stack.enter_context(_indexed_metadata_view(state._snapshot, budget, cancel)).value
    else:
        current = work.stack.enter_context(R.decoded(state._snapshot._metadata, budget=budget, cancel=cancel)).value
    if mesh.is_compact:
        thermal_view, thermal = None, _IndexedThermal(mesh, budget)
    else:
        thermal_view = work.stack.enter_context(R.decoded(mesh._json, budget=budget, cancel=cancel))
        thermal = thermal_view.value
    transport_view = work.stack.enter_context(R.decoded(transport_snapshot._metadata, budget=budget, cancel=cancel))
    transport = transport_view.value
    audit_view = work.stack.enter_context(R.decoded(source_audit._metadata, budget=budget, cancel=cancel))
    audit = work.stack.enter_context(R.extracted(audit_view, {
        'schema': R.ALL, 'parent_state_id': R.ALL, 'start_time_s': R.ALL,
        'duration_s': R.ALL}, budget=budget, cancel=cancel)).value
    audit_view.close()
    graph, plan, ref = exchange['spatial_graph'], exchange['joined_heat_plan'], exchange['joined_heat']
    body = {k: v for k,v in exchange.items() if k not in ('state_id','result_id')}
    # The graph the committed transport was solved on: the issued physical graph, or, for an
    # owner with finite stocks, the graph of the committed finite proposal, as the producer
    # (SpatialOwner.transport) and the native validate_exchange have it. Both are parts of
    # the exchange, whose identity is tested below.
    if owner._finite is not None:
        finite = exchange.get('finite_proposal')
        if type(finite) is not dict or type(finite.get('graph')) is not dict:
            raise ValueError('Committed finite proposal of the transport is missing')
        transport_graph_id = R.stream_hash(finite['graph'], cancel)
    elif 'finite_proposal' in exchange:
        raise ValueError('Committed finite proposal has no actual stock owner')
    else:
        transport_graph_id = exchange['spatial_graph_id']
    if (exchange.get('schema') != EXCHANGE_SCHEMA or exchange.get('state_id') != state.state_id
            or exchange.get('owner_id') != owner.owner_id
            or exchange.get('parent_state_id') != parent_spatial_state.state_id
            or current['parent_state_id'] != parent_spatial_state.state_id
            or exchange.get('collar_state_id') != collar_state.result_id
            or current['intervals'] != parent['intervals']+1
            or R.stream_hash(dict(state_id=state.state_id, exchange=body), cancel) != exchange.get('result_id')
            or R.stream_hash(graph, cancel) != exchange.get('spatial_graph_id')
            or exchange.get('global_transport_id') != transport_snapshot.result_id
            or exchange.get('source_audit_id') != source_audit.result_id
            or graph['parent_state_id'] != parent_collar_state.result_id
            or graph['source_flow_stage_id'] != exchange['source_flow_stage_id']
            or transport['source_stage_id'] != exchange['source_flow_stage_id']
            or transport['state_id'] != parent_spatial_state.state_id
            or transport.get('geometry_id') != transport_graph_id
            or dict(transport, result_id=transport_snapshot.result_id) != exchange.get('transport')):
        raise ValueError('Committed parent/head/source/transport/exchange chain differs')
    # The exchange remains caller-owned throughout restoration/validation. Keep
    # the original metadata shape without re-copying its authenticated children.
    # Only this shallow dict table is new; use the existing copy/table inventory.
    entries = len(exchange['transport'])
    table_bytes = R._with_allocator(R.FIXED_COPY+R.DICT_UNIT
                                    +R._dict_entry(entries)[1]*(entries+1))
    work.stack.enter_context(R.workspace(budget, table_bytes, cancel=cancel,
                                        category='private-cold-transport-borrowed-table'))
    transport = {key: value for key, value in exchange['transport'].items()
                 if key != 'result_id'}
    transport_view.close()
    duration = ref['duration_s']
    if (type(duration) not in (int,float) or not math.isfinite(duration) or duration <= 0
            or I._q(graph['end_time_s'])-I._q(graph['start_time_s']) != I.Fraction(duration)
            or I._q(graph['start_time_s']) != I.Fraction(parent['time_s'])
            or I._q(graph['end_time_s']) != I.Fraction(current['time_s'])
            or audit.get('schema') != 'atlas.regional-evolution3d-source-audit.v1'
            or audit.get('parent_state_id') != parent_collar_state.native_state.result_id
            or audit.get('start_time_s') != parent['time_s'] or audit.get('duration_s') != duration
            or ref.get('duration_s') != duration):
        raise ValueError('Restored source audit/parent clock/duration differs')
    if mesh.is_compact:
        if _indexed_endpoint_differs(mesh, thermal, current, owner, graph, exchange):
            raise ValueError('Restored physical mesh is not the actual transported endpoint')
    else:
        if (mesh.geometry_id != current['thermal_mesh_id'] or thermal != current['thermal_mesh']
                or thermal['funding_id'] != owner._funding.funding_id or thermal['funding_id'] != graph['funding_id']
                or thermal['grid_id'] != owner._definition['grid_id'] or thermal['grid_id'] != graph['grid_id']
                or thermal['support_id'] != graph['end_support_id']
                or thermal['trajectory_id'] != graph['trajectory_id'] or thermal['time_s'] != graph['end_time_s']
                or ('source' in thermal) != ('source' in graph) or thermal.get('source') != graph.get('source')
                or 'booked_cell_rule' in thermal and thermal['booked_cell_rule'].get('closed_graph_id') != exchange['spatial_graph_id']):
            raise ValueError('Restored physical mesh is not the actual transported endpoint')
    # Equality above is still independent. The current-state view continues to
    # own this equivalent mesh until the existing enclosing view scope closes.
    if not mesh.is_compact:
        thermal = current['thermal_mesh']
        thermal_view.close()
    positive = {row['cell_id'] for row in graph['cells'] if I._q(row['end_volume_m3']) > 0}
    logical = [row['logical_cell_id'] for row in thermal['cells']]
    if len(set(logical)) != len(logical) or set(logical) != positive:
        raise ValueError('Every positive transported cell must appear exactly once')
    I._validate_target_plan(plan)
    if (plan['original_target'] != I._target_provenance(target)
            or plan['absolute_residual_target_decimal'] != I._target_text(target)
            or plan.get('method_id') != I.METHOD or plan.get('schema') != 'atlas.private.composed-heat-plan.r1'
            or plan.get('geometry_id') != mesh.geometry_id
            or plan.get('conductivity_w_m_k') != [float(owner._definition['conductivity_w_m_k'])]*len(logical)
            or not set(thermal.get('required_thermal_boundary_faces', ())).issubset(plan['boundary'])):
        raise ValueError('Original committed heat method/k/target/boundary differs')
    if mesh.is_compact:
        geometry = _indexed_geometry(mesh, geometry, budget, cancel)
    else:
        if geometry is None:
            geometry = MimeticGeometry(thermal, budget=budget)
        elif (type(geometry) is not MimeticGeometry or geometry._budget is not budget
              or sha256(geometry._encoded).hexdigest() != mesh.geometry_id):
            raise ValueError('Retained restored metric differs from actual endpoint')
    for fid, (kind,value) in plan['boundary'].items():
        if (fid not in geometry._face_ids or len(geometry._incidence[geometry._face_ids.index(fid)]) != 1
                or kind not in ('power','temperature') or type(value) not in (int,float)
                or not math.isfinite(value) or kind == 'temperature' and value <= 0):
            raise ValueError('Original finite exterior-only boundary declarations required')
    return current, thermal, transport, plan, ref, geometry, duration


@dataclass(frozen=True, slots=True, init=False)
class RestoredHeatBinding:
    """Borrowed detached evidence, valid only while its returned owner lives."""
    _snapshot: object = field(repr=False)
    _geometry: object = field(repr=False)
    _context: tuple = field(repr=False)
    _exchange_identity: str
    _plan: bytes = field(repr=False)
    fixture_only: bool = False

    def __init__(self, *args, **kwargs):
        raise TypeError('Use authenticated completed-interval restore; no heat injection')

    @property
    def result_id(self):
        return self._snapshot.result_id

    def array(self, name):
        if name == 'face_temperature_k':
            raise I.N.A.EndpointTraceUnavailable(I.N.A.TRACE_STATUS)
        return self._snapshot.array(name)

    def descriptor(self):
        return self._snapshot.descriptor()

    def plan_descriptor(self):
        return json.loads(self._plan)

    def validate_for(self, owner, state, collar_state, exchange, *, audit_arrays=None, cancel=None):
        actual_owner, parent, parent_collar, actual_state, actual_collar, mesh, transport, audit, execution, target, budget = self._context
        if owner is not actual_owner or state is not actual_state or collar_state is not actual_collar:
            raise ValueError('Restored binding belongs to a different actual owner/endpoint')
        with R.codec_for_value(exchange, budget=budget, cancel=cancel):
            if R.stream_hash(exchange, cancel) != self._exchange_identity:
                raise ValueError('Restored committed exchange changed')
        with R.workspace(budget, 65536, cancel=cancel) as work:
            _context(owner, parent, parent_collar, state, collar_state, mesh, transport, audit,
                     exchange, execution, target, budget, cancel, work, geometry=self._geometry)
            _snapshot(self._snapshot, budget, cancel)
            if audit_arrays is not None:
                expected = {**{'spatial-transport:'+k: transport.array(k) for k in transport.array_names},
                            **{'joined-heat:'+k: self.array(k) for k in C._FIELDS}}
                if not _same_arrays(audit_arrays, expected):
                    raise ValueError('Actual restored transport/heat audit arrays differ')
                del expected
        _verify(execution, cancel)


def restore(store, receipt, *, owner, parent_spatial_state, parent_collar_state, spatial_state,
            collar_state, mesh, transport_snapshot, source_audit, exchange, execution,
            absolute_residual_target, expected_heat_result_id, budget, cancel=None):
    """Authenticate stored I12 heat against separately restored committed state.

    The workflow reader must provide its committed parent/head and expected ID;
    this is not a replacement for native workflow source/transaction recovery.
    No producer is called. Returned ownership includes every decoded heat view.
    """
    work = R.workspace(budget, 65536, cancel=cancel, category='private-cold-heat-binding')
    work.__enter__()
    try:
        # The decoded context and heat views serve this function's checks
        # only: they are released before the binding's own re-validation.
        views = work.stack.enter_context(R.workspace(budget, 0, cancel=cancel,
                                                     category='private-cold-heat-views'))
        current, thermal, transported, plan, ref, geometry, dt = _context(owner, parent_spatial_state,
            parent_collar_state, spatial_state, collar_state, mesh, transport_snapshot, source_audit,
            exchange, execution, absolute_residual_target, budget, cancel, views)
        if (exchange['joined_heat_id'] != expected_heat_result_id or ref['result_id'] != expected_heat_result_id
                or ref['checkpoint'] != receipt or ref.get('method_id') != I.METHOD):
            raise ValueError('Independently expected committed heat result/CAS reference differs')
        with R.codec_for_value(dict(sources=C._SOURCES, provenance=execution.provenance),
                               budget=budget, cancel=cancel):
            bindings = _expected_bindings(ref, plan, geometry.geometry_id, transport_snapshot.result_id, execution, cancel)
        saved = work.stack.enter_context(STORE.restore(store, receipt, expected_result_id=expected_heat_result_id,
            bindings=bindings, budget=budget, cancel=cancel))
        view = views.stack.enter_context(R.decoded(saved.value._metadata, budget=budget, cancel=cancel))
        meta = view.value
        origin = meta['caller_snapshot']
        cp = owner._collar._native._material.heat_capacity_j_kg_k
        with R.codec_for_value(owner._definition, budget=budget, cancel=cancel):
            definition_id = R.stream_hash(owner._definition, cancel)
            transport_identity = R.stream_hash(dict(parent=parent_spatial_state.state_id,
                source=exchange['source_flow_stage_id'], graph=exchange['spatial_graph_id'],
                transport=transport_snapshot.result_id), cancel)
        if (meta.get('schema') != I.SCHEMA or meta.get('method_id') != I.METHOD
                or meta.get('fixed_forward_producer') != 'private_heat_forward_kernel_r13.advance'
                or meta.get('origin_binding_status') != 'FORWARD_ACTUAL_OWNER_SNAPSHOT'
                or meta.get('genuine_forward_origin') is not True or origin.get('fixture_only') is not False
                or meta.get('call_id') != ref['call_id'] or meta.get('plan_id') != bindings['plan']
                or meta.get('geometry_id') != geometry.geometry_id or meta.get('state_id') != transport_snapshot.result_id
                or meta.get('duration_s') != dt or meta.get('cell_ids') != [r['cell_id'] for r in thermal['cells']]
                or meta.get('face_ids') != list(geometry._face_ids)
                or meta.get('loaded_dependencies') != I._LOADED_IMPLEMENTATION.descriptor()
                or origin.get('execution') != execution.provenance or origin.get('private_sources') != dict(I._IMPORTED_SOURCES)
                or origin.get('plan_id') != bindings['plan'] or origin.get('geometry_id') != geometry.geometry_id
                or origin.get('state_id') != transport_snapshot.result_id or origin.get('duration_s') != dt
                or origin.get('cell_ids') != meta['cell_ids']
                or origin.get('loaded_dependencies') != meta['loaded_dependencies']
                or origin.get('owner_id') != owner.owner_id or origin.get('owner_definition_id') != definition_id
                or origin.get('heat_capacity_j_kg_k') != cp or origin.get('source_stage_id') != exchange['source_flow_stage_id']
                or origin.get('graph_id') != exchange['spatial_graph_id'] or origin.get('thermal_mesh_id') != mesh.geometry_id
                or origin.get('source_policy') != 'already-booked-transport; zero added heat source'
                or meta.get('source_policy') != origin['source_policy']
                or meta.get('endpoint_face_trace_status') != I.N.A.TRACE_STATUS
                or any(meta.get(k) is not False for k in ('native_issue_performed','native_resource_admitted',
                    'native_heat_dispatch_enabled','production_acceptance','whole_method_memory_inventory_certified'))
                or saved.value.array_names != C._FIELDS):
            raise ValueError('Stored heat owner/plan/source/runtime/order/provenance differs')
        sig = origin['native_origin_signature']
        expected_sig = dict(owner_id=owner.owner_id, owner_definition_id=definition_id,
            funding_id=owner._funding.funding_id, component_count=owner._component_count, heat_capacity_j_kg_k=cp,
            transport_id=transport_identity,
            state_id=transport_snapshot.result_id, parent_state_id=parent_spatial_state.state_id,
            source_stage_id=exchange['source_flow_stage_id'], graph_id=exchange['spatial_graph_id'],
            thermal_mesh_id=mesh.geometry_id, duration_s=dt)
        if any(sig.get(k) != v for k,v in expected_sig.items()):
            raise ValueError('Historical producer origin differs from restored actual context')
        # Historical inventory IDs are bound by the original call ID and CAS;
        # these snapshots are NOT reconstructed or claimed independently read.
        if set(sig) != {*expected_sig, 'source_inventory_id', 'native_source_inventory_id'}:
            raise ValueError('Original producer source-inventory provenance is incomplete')
        import private_heat_gmp_resources_r1 as GMP
        arithmetic = GMP.OwnedWorkspace(budget, 65536, category='private-cold-input-projection', cancelled=cancel)
        arithmetic.__enter__()
        held = R.O._OwnerWorkspace(arithmetic)
        try:
            ar = R._ProjectionArithmetic(arithmetic, R.A.exact_library(), GMP, len(geometry._cells),
                len(geometry._face_ids), 1075, lambda: R.check(cancel))
            held.arithmetic = ar
            inputs = _inputs(ar, transported, thermal, owner._component_count, cp)
            call_arrays = {key.removeprefix('input_'): value for key,value in inputs.items()}
            with R.codec(view, budget=budget, cancel=cancel):
                if R.stream_hash(dict(metadata=origin, arrays={k: dict(shape=list(v.shape),
                        sha256=sha256(memoryview(v).cast('B')).hexdigest()) for k,v in call_arrays.items()}), cancel) != ref['call_id']:
                    raise ValueError('Original call identity does not match re-derived transported inputs')
            _equations(saved.value, meta, geometry, inputs, plan, dt, budget, cancel)
            exterior = {row['cell_id']: row for row in current['cells']}
            for at, row in enumerate(thermal['cells']):
                public = ar.decode(float(saved.value.array('enthalpy_j')[at]))
                if row['kind'] == 'collar':
                    actual = ar.decode(float(collar_state.fields.array('enthalpy_j').flat[row['index']]))
                else:
                    actual = ar.decode(exterior[row['logical_cell_id']]['exact']['enthalpy_j'])
                if not ar.equal(actual, public):
                    raise ValueError('Restored endpoint changed the actual stored heat enthalpy')
            del exterior, public, actual
            del inputs, call_arrays
            ar.settle(())
            held.__exit__(None, None, None)
        except BaseException:
            held.__exit__(*sys.exc_info())
            raise
        exchange_identity = R.stream_hash(exchange, cancel)
        # Last use of the decoded context and heat views and of their codec scope.
        del current, thermal, transported, meta, origin, sig, row
        views.__exit__(None, None, None)
        result = object.__new__(RestoredHeatBinding)
        context = (owner, parent_spatial_state, parent_collar_state, spatial_state, collar_state,
                   mesh, transport_snapshot, source_audit, execution, absolute_residual_target, budget)
        for name,value in dict(_snapshot=saved.value, _geometry=geometry, _context=context,
                _exchange_identity=exchange_identity, _plan=I._json(plan), fixture_only=False).items():
            object.__setattr__(result, name, value)
        result.validate_for(owner, spatial_state, collar_state, exchange, cancel=cancel)
        _verify(execution, cancel)
        return R.P.OwnedSolve(result, work)
    except BaseException:
        work.__exit__(*sys.exc_info())
        raise
