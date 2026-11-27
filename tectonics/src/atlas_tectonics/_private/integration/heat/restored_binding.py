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
from dataclasses import dataclass, field; import atlas_tectonics._identity as _atlas_identity
from hashlib import sha256
import json
import math

from atlas_tectonics._private.integration.heat import checkpoint_consumer as C
from atlas_tectonics._private import private_heat_issuer_resources_r4 as R
from atlas_tectonics._private.integration.heat import native_issuer as I
from atlas_tectonics._private.integration.heat import restored_binding_ram_context as B7
from atlas_tectonics.integration.coupling.spatial_owner import PreparedSpatialOwner, SpatialExteriorState
from atlas_tectonics.regional.collar3d import RegionalCollarState
from atlas_tectonics.regional.execution import RegionalMechanicalSnapshot
from atlas_tectonics.integration.coupling.exterior_mesh import ExteriorMesh
from atlas_tectonics.integration.heat.mimetic_heat import MimeticGeometry

SCHEMA = 'atlas.private.restored-composed-heat-binding.r1'
EXCHANGE_SCHEMA = 'atlas.private.spatial-composed-advance.r1'
REF_SCHEMA = 'atlas.private.joined-heat-reference.r1'
_PINS = {
    'private_heat_checkpoint_consumer_r10.py': '6e893fc31be71ee8ede77a6c936a56afea55659841f9ccc9a1a54440f878c4d1',
    'private_heat_native_issuer_r13.py': '64c32e64c0ad1375d2169b1da4cbb5e6a3eddc42d5ac68a527635db31cf26b07',
    'private_heat_issuer_resources_r4.py': '166dd82ba45500279b37c5189b56c78990f62b58470a45effa23c0e5b9b686b1',
    'private_heat_snapshot_store_r4.py': 'b5b5691d97ae847582f19072b870c26262b1adc5dafcc1b576cfa01179a5bb99',
    'private_heat_forward_kernel_r13.py': '78ea9cc2c64193dcb27e610b59cee3a51da0fee95c36e34fbf57623bb610f944',
    'private_heat_grouped_account_r1.py': 'c373deec02c82ec21de7d478ae291c1f510712672127e8e9d0bc7585b9a9482b',
    'private_heat_joined_consumer_r6.py': '590ca42d6093add4a966bd7dbaba1f446394f7f9d9eb61c9a1fc7a80a4c26059',
}
_RESTORE_SHA = 'b3b58c0cd4b721bca1e8d745fb7eb0cc1ee85f2c3dd09a2f34e2f91bdc655d8e'
_restore_bound = False


def _bind_restore(cancel):
    global _restore_bound
    R.check(cancel)
    if not _restore_bound:
        if B7._SELF_SHA != _RESTORE_SHA:
            raise ValueError('Cold binding source changed: '+_atlas_identity.relkey(B7.__file__))
        if _PINS != B7._PINS:
            raise ValueError('Cold binding sources differ from the selected restore')
        _restore_bound = True


def _snapshot(snapshot, budget, cancel, *, compact_transport=False):
    from atlas_tectonics._private.codecs.heat_ledger_tables import CompactHeatSnapshot
    from atlas_tectonics._private.integration.live_transport_result import CompactTransportSnapshot, identity as transport_identity
    if compact_transport and type(snapshot) is CompactTransportSnapshot:
        if transport_identity(snapshot, budget, cancel) != snapshot.result_id:
            raise ValueError('Restored compact transport snapshot identity differs')
        return
    if type(snapshot) is CompactHeatSnapshot:
        if snapshot.scope.run_budget is not budget:
            raise ValueError('Restored heat snapshot has another budget')
        snapshot.verify_identity(check=lambda: R.check(cancel))
        return
    if type(snapshot) is not RegionalMechanicalSnapshot:
        raise TypeError('Independently restored immutable native snapshot required')
    if I._snapshot_identity(snapshot, budget, cancel) != snapshot.result_id:
        raise ValueError('Restored native snapshot identity differs')


def _transport_metadata(snapshot, exchange, budget, cancel, work):
    """Borrow compact metadata for exactly this validation's work lifetime."""
    from atlas_tectonics._private.integration.live_transport_result import CompactTransportSnapshot
    if type(snapshot) is CompactTransportSnapshot:
        return _SV._Lazy(snapshot._record, work.stack)
    return work.stack.enter_context(R.decoded(snapshot._metadata, budget=budget, cancel=cancel)).value


def _transport_matches(snapshot, transport, exchange, cancel):
    """Compare the complete transport at the original validation position."""
    from atlas_tectonics._private.integration.live_transport_result import CompactTransportSnapshot
    if type(snapshot) is CompactTransportSnapshot:
        presented = exchange.get('transport')
        projected_id = _SV.excluded_identity(
            presented, ('result_id',), lambda value: R.stream_hash(value, cancel))
        return (projected_id == snapshot._record.identity().sha256 and
                presented.get('result_id') == snapshot.result_id)
    return dict(transport, result_id=snapshot.result_id) == exchange.get('transport')


def _context(owner, parent_spatial_state, parent_collar_state, state, collar_state,
             mesh, transport_snapshot, source_audit, exchange, execution, target, budget, cancel, work,
             geometry=None):
    exchange = work.stack.enter_context(_SV.access(exchange))
    B7._verify(execution, cancel)
    if (type(owner) is not PreparedSpatialOwner or owner._budget is not budget
            or any(type(s) is not SpatialExteriorState or s._budget is not budget
                   for s in (parent_spatial_state, state))
            or any(type(s) is not RegionalCollarState for s in (parent_collar_state, collar_state))
            or type(mesh) is not ExteriorMesh or mesh._resource is not budget):
        raise TypeError('Independent restored actual owner/parent/head/mesh on one budget required')
    if owner._heat_label != 'PRIVATE uniform-k composed physical-face heat; original transported caloric stocks':
        raise ValueError('Restored owner must explicitly declare the composed heat method')
    from atlas_tectonics._private.codecs.compact_contracts import proving
    if proving():    # proof mode: validate_parent and the eight snapshot identities
        owner.validate_parent(parent_spatial_state, parent_collar_state)
        owner.validate_parent(state, collar_state)
        snapshots = (parent_spatial_state._snapshot, state._snapshot, parent_collar_state.fields,
            parent_collar_state.native_state, collar_state.fields, collar_state.native_state,
            transport_snapshot, source_audit)
        for snapshot in snapshots:
            if _indexed_spatial(snapshot, (parent_spatial_state, state)):
                _indexed_snapshot(snapshot, budget, cancel)
            else:
                _snapshot(snapshot, budget, cancel, compact_transport=snapshot is transport_snapshot)
    # r1 views carried a codec share for life. The stream hashes below are of
    # the committed exchange or a part of it; they are funded here for as long
    # as the caller's scope lives.
    work.stack.enter_context(_SV.codec_scope(exchange, budget, cancel, R.codec_for_value))
    parent = work.stack.enter_context(_HC.state_view(parent_spatial_state._snapshot, budget, cancel, R)).value
    current = work.stack.enter_context(_HC.state_view(state._snapshot, budget, cancel, R)).value
    if mesh.is_compact:
        thermal = _IndexedThermal(mesh, budget)
    else:
        thermal = work.stack.enter_context(R.decoded(mesh._json, budget=budget, cancel=cancel)).value
    transport = _transport_metadata(transport_snapshot, exchange, budget, cancel, work)
    audit = work.stack.enter_context(R.decoded(source_audit._metadata, budget=budget, cancel=cancel)).value
    graph, plan, ref = exchange['spatial_graph'], exchange['joined_heat_plan'], exchange['joined_heat']
    plan = _HC.native_plan(plan, work.stack)
    body = _SV.exchange_identity(exchange, state.state_id, lambda value: R.stream_hash(value, cancel)) if proving() else None
    # The graph the committed transport was solved on: the issued physical graph, or, for an
    # owner with finite stocks, the graph of the committed finite proposal, as the producer
    # (SpatialOwner.transport) and the native validate_exchange have it. Both are parts of
    # the exchange, whose identity is tested below.
    if owner._finite is not None:
        finite = exchange.get('finite_proposal')
        if not _SV.is_record(finite) or not _SV.is_record(finite.get('graph')):
            raise ValueError('Committed finite proposal of the transport is missing')
        transport_graph_id = (_SV.content_identity(finite['graph'], lambda value: R.stream_hash(value, cancel))
                              if proving() else None)
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
            or exchange.get('global_transport_id') != transport_snapshot.result_id
            or exchange.get('source_audit_id') != source_audit.result_id
            or graph['parent_state_id'] != parent_collar_state.result_id
            or graph['source_flow_stage_id'] != exchange['source_flow_stage_id']
            or transport['source_stage_id'] != exchange['source_flow_stage_id']
            or transport['state_id'] != parent_spatial_state.state_id
            or transport_graph_id is not None and transport.get('geometry_id') != transport_graph_id
            or proving() and (body != exchange.get('result_id')
                              or _SV.content_identity(graph, lambda value: R.stream_hash(value, cancel))
                              != exchange.get('spatial_graph_id')
                              or not _transport_matches(transport_snapshot, transport, exchange, cancel))):
        raise ValueError('Committed parent/head/source/transport/exchange chain differs')
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
    logical = [row['logical_cell_id'] for row in thermal['cells']]   # read by the plan comparison below
    if proving():
        positive = {row['cell_id'] for row in graph['cells'] if I._q(row['end_volume_m3']) > 0}
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
    for fid, (kind,value) in (plan['boundary'].items() if proving() else ()):
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
    _proved: tuple = field(repr=False)
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
        restored, compared = self._proved
        if _SV._reference(exchange) is restored:
            from atlas_tectonics._private.codecs.compact_contracts import proving
            if not proving():
                return    # restore()'s own exchange; proved_for is not asked then
            # restore() derived and checked everything below from these very objects (ruling 4b)
            if audit_arrays is not None and audit_arrays is not compared:
                with R.workspace(budget, 65536, cancel=cancel):
                    expected = {**{'spatial-transport:'+k: transport.array(k) for k in transport.array_names},
                                **{'joined-heat:'+k: self.array(k) for k in C._FIELDS}}
                    if not B7._same_arrays(audit_arrays, expected):
                        raise ValueError('Actual restored transport/heat audit arrays differ')
                    del expected
                object.__setattr__(self, '_proved', (restored, audit_arrays))
            return
        with _SV.codec_scope(exchange, budget, cancel, R.codec_for_value):
            if _SV.identity(exchange, lambda value: R.stream_hash(value, cancel)) != self._exchange_identity:
                raise ValueError('Restored committed exchange changed')
        with R.workspace(budget, 65536, cancel=cancel) as work:
            _context(owner, parent, parent_collar, state, collar_state, mesh, transport, audit,
                     exchange, execution, target, budget, cancel, work, geometry=self._geometry)
            _snapshot(self._snapshot, budget, cancel)
            if audit_arrays is not None:
                expected = {**{'spatial-transport:'+k: transport.array(k) for k in transport.array_names},
                            **{'joined-heat:'+k: self.array(k) for k in C._FIELDS}}
                if not B7._same_arrays(audit_arrays, expected):
                    raise ValueError('Actual restored transport/heat audit arrays differ')
                del expected
        B7._verify(execution, cancel)

    def proved_for(self, owner, state, collar_state, exchange, audit_arrays):
        """True only for restore()'s own objects and an arrays dict validate_for compared, in this process."""
        actual_owner, _, _, actual_state, actual_collar = self._context[:5]
        restored, compared = self._proved
        return (owner is actual_owner and state is actual_state and collar_state is actual_collar and
                _SV._reference(exchange) is restored and audit_arrays is not None and audit_arrays is compared)


def restore(store, receipt, *, owner, parent_spatial_state, parent_collar_state, spatial_state,
            collar_state, mesh, transport_snapshot, source_audit, exchange, execution,
            absolute_residual_target, expected_heat_result_id, budget, cancel=None):
    """Authenticate stored I12 heat against separately restored committed state.

    The workflow reader must provide its committed parent/head and expected ID;
    this is not a replacement for native workflow source/transaction recovery.
    No producer is called. Returned ownership includes every decoded heat view.
    """
    with _SV.access(exchange) as exchange:
        _bind_restore(cancel)
        return B7._restore(store, receipt, owner, parent_spatial_state, parent_collar_state, spatial_state,
                           collar_state, mesh, transport_snapshot, source_audit, exchange, execution,
                           absolute_residual_target, expected_heat_result_id, budget, cancel,
                           context_for=_context, binding_type=RestoredHeatBinding,
                           collar_value=B7._collar_value, cold=True)


from atlas_tectonics._private.integration.geometry import spatial_validation_patch as _SV  # compact validation r1

from atlas_tectonics._private.integration.heat import heat_cold_patch as _HC
from atlas_tectonics._private.integration.geometry import spatial_indexed_patch as _INDEXED_SPATIAL
from atlas_tectonics._private.integration.heat import indexed_runtime as _INDEXED_HEAT


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
