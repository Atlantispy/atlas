"""PRIVATE genuine forward producer binding, not native heat dispatch.

Only actual owner-derived calls (or explicitly marked internal test fixtures)
can invoke the one fixed standalone producer. No saved result, numerical
callback or replay API is accepted. The immutable exact-transfer result binds
the real input snapshot, plan, source stage, geometry, duration and scipy
ExecutionContext. Fixture output never claims actual-owner origin.

Projection, call, codec and retained snapshot worksets are derived from actual
operands; the fixed forward producer separately owns its derived stages. These
are accounted policies, NOT allocator/RSS or native whole-method acceptance. Native dispatch, the heat hold and production acceptance
remain unchanged. This is a non-hostile Python trust boundary, like native
issuance; it is not a sandbox against object.__new__ or arbitrary Python.

Decoded JSON views follow resources r4: a derived decode inventory, the stream
codec booked only while a snapshot identity is hashed, and one complete decode
at a time while an owner call is bound. The fixed producer is F10, which is F9
with the same derived inventory for its startup decode. Physics, checks and
identities of the r8 binding are otherwise unchanged.

R10 is R9 with the fixed producer F11: F10 with the precision choice of its
selective refinement corrected, as that kernel describes. Nothing else differs.

R11 is R10 with the fixed producer F12: F11 on numerical modules that hold a
result that exists at what it occupies, as that kernel describes. Nothing else differs.

R12 is R11 with the fixed producer F13: F12 metered by the process meter where
that supports the runtime, as that kernel describes. Nothing else differs.
"""

from concurrent.futures import CancelledError
from dataclasses import dataclass, field
from decimal import Decimal
from fractions import Fraction
import hashlib
import json
import sys
import weakref
from typing import cast

import numpy as np
from atlas_tectonics._private.integration.heat import native_projection as N
from atlas_tectonics._private.integration.heat import heat_ledger_issuer_patch as HEAT_LEDGER
from atlas_tectonics._private.integration.geometry import live_spatial_patch as LIVE_SPATIAL
from atlas_tectonics._private.codecs import heat_ledger_tables as HEAT_TABLES
from atlas_tectonics._private.integration.heat import indexed_runtime as INDEXED
from atlas_tectonics._private.integration.heat import mesh_patch as INDEXED_INPUTS
from atlas_tectonics._private.integration.geometry import spatial_indexed_patch as INDEXED_SPATIAL
from atlas_tectonics._private import private_heat_issuer_resources_r4 as RESOURCES
from atlas_tectonics._private.integration.heat import forward_kernel as F
from atlas_tectonics.integration.heat.mimetic_heat import MimeticGeometry, _enc, _hash, _json, _q
from atlas_tectonics.integration.coupling.regional_inventory import _project
from atlas_tectonics.integration.coupling.spatial_transport import _json_encoding_capacity, _workspace
from atlas_tectonics.regional.execution import RegionalMechanicalSnapshot
from atlas_tectonics._exact_runtime import selected

METHOD = 'private:uniform-k-composed-forward-contract.r12'
SCHEMA = 'atlas.private.composed-heat-advance.r12'
# Exactly the fields bind_owner_call and owner_projection_bytes read from the
# closed graph, the transported state and, after its metric exists, the mesh.
_GRAPH_FIELDS = {key: RESOURCES.ALL for key in (
    'start_time_s', 'end_time_s', 'source_flow_stage_id', 'funding_id', 'source',
    'end_support_id', 'grid_id', 'trajectory_id')}
_GRAPH_FIELDS['cells'] = RESOURCES.Rows(dict(cell_id=RESOURCES.ALL, end_volume_m3=RESOURCES.ALL))
_MESH_FIELDS = dict(cells=RESOURCES.Rows(dict(cell_id=RESOURCES.ALL)))


def _check(cancel):
    if cancel is not None and cancel():
        raise CancelledError('Private composed issuance cancelled')


def _target_text(value, cancel=None):
    if type(value) is float:
        value = Decimal.from_float(value)
    F.INVENTORY._target_metadata(value, cancel)
    return str(value) if type(value) is Decimal else value


def _target_provenance(value):
    if type(value) is float:
        return dict(kind='represented-binary64', value=value.hex())
    if type(value) is Decimal:
        return dict(kind='Decimal', value=str(value))
    if type(value) is str:
        return dict(kind='decimal-string', value=value)
    raise ValueError('Original target must be float, Decimal or decimal string; no rational rounding')


def _validate_target_plan(plan):
    original = plan['original_target']
    if original['kind'] == 'represented-binary64':
        value = float.fromhex(original['value'])
    elif original['kind'] == 'Decimal':
        value = Decimal(original['value'])
    elif original['kind'] == 'decimal-string':
        value = original['value']
    else:
        raise ValueError('Unknown original target provenance')
    _target_text(value)
    return value




def _snapshot_identity(snapshot, budget, cancel=None):
    _check(cancel)
    if LIVE_SPATIAL.is_transport_snapshot(snapshot):
        return LIVE_SPATIAL.transport_identity(snapshot, budget, cancel)
    if type(snapshot) is HEAT_TABLES.CompactHeatSnapshot:
        return HEAT_LEDGER.snapshot_identity(snapshot, budget, cancel)
    if type(snapshot) is INDEXED_SPATIAL.IndexedSpatialSnapshot:
        return INDEXED_SPATIAL.snapshot_identity(snapshot)
    return _legacy_snapshot_identity(snapshot, budget, cancel)


def _legacy_snapshot_identity(snapshot, budget, cancel=None):
    with RESOURCES.decoded(snapshot._metadata, budget=budget, cancel=cancel) as owner:
        with RESOURCES.workspace(budget, 65536+1024*(len(snapshot._fields)+1), cancel=cancel), \
                RESOURCES.codec(owner, budget=budget, cancel=cancel):
            from atlas_tectonics.regional.execution import content_metadata
            return RESOURCES.stream_hash(dict(metadata=content_metadata(owner.value), arrays={
                name: dict(shape=shape, sha256=hashlib.sha256(raw).hexdigest())
                for name, shape, raw in snapshot._fields}), cancel)


def _origin_signature(owner, step, mesh):
    """Recompute native immutable identities; do not trust only cached IDs."""
    owner._verify()
    return dict(owner_id=owner.owner_id, owner_definition_id=_hash(owner._definition),
        funding_id=owner._funding.funding_id, component_count=owner._component_count,
        heat_capacity_j_kg_k=owner._collar._native._material.heat_capacity_j_kg_k,
        transport_id=step.result_id, state_id=step.result.result_id,
        parent_state_id=step.parent.state_id, source_stage_id=step.source.result_id,
        source_inventory_id=step.source.inventory.result_id,
        native_source_inventory_id=step.source.source_stage.inventory.result_id,
        graph_id=step.graph.geometry_id, thermal_mesh_id=mesh.geometry_id,
        duration_s=float(step.source.duration_s))


def _new_snapshot(metadata, arrays, budget, owner, attribute):
    """Admit immutable storage and native JSON/array copies BEFORE creation."""
    encoded, codec = _json_encoding_capacity(metadata, budget)
    payload = sum(value.nbytes for value in arrays.values())
    retained = 2048+encoded+payload+512*len(arrays)
    with _workspace(budget, codec+2*payload+65536, 'private-heat-snapshot-codec') as work:
        work.enter_context(budget.reserve(retained, category='private-heat-snapshot-retained'))
        snapshot = RegionalMechanicalSnapshot(metadata, arrays)
        object.__setattr__(owner, attribute, snapshot)
        # ExitStack cannot detach one context. A separately reserved owner lease
        # below overlaps until the construction stack closes, never undercharges.
        owned = budget.reserve(retained, category='private-heat-snapshot-owned')
        owned.__enter__()
        try:
            weakref.finalize(owner, owned.__exit__, None, None, None)
        except BaseException:
            owned.__exit__(None, None, None)
            raise
    return snapshot


@dataclass(frozen=True, slots=True, weakref_slot=True, init=False)
class OwnerHeatCall:
    _snapshot: object = field(repr=False)
    _geometry: object = field(repr=False)
    _budget: object = field(repr=False)
    _execution: object = field(repr=False)
    _origin_objects: tuple = field(repr=False)
    _plan: bytes = field(repr=False)
    _fixture: bool
    _record_scope: object = field(repr=False)

    def __init__(self, *args, **kwargs):
        raise TypeError('Call origins are derived from actual native owner objects')

    @property
    def call_id(self):
        return self._snapshot.result_id

    def descriptor(self):
        return self._snapshot.descriptor()


def _make_call(metadata, arrays, geometry, execution, plan, origins, *, fixture=False, record_scope=None):
    """Internal construction; fixture origins are NEVER owner-admitted."""
    if selected.library() is not N.A.A.exact_library():
        raise ValueError('The GMP library used by this private projection is not the selected bound native backend')
    budget = geometry._budget
    plan_bytes, plan_codec = _json_encoding_capacity(plan, budget)
    target_work = RESOURCES.target_bytes(plan['absolute_residual_target_decimal'], budget=budget)
    identity_work = 65536
    with _workspace(budget, plan_bytes+plan_codec+target_work+identity_work, 'private-heat-call-definition'):
        scope = HEAT_LEDGER.required_scope(origins, budget, fixture=fixture, supplied=record_scope)
        out = object.__new__(OwnerHeatCall)
        object.__setattr__(out, "_record_scope", scope)
        for key, value in dict(_geometry=geometry, _budget=budget, _execution=execution,
                               _origin_objects=tuple(origins), _fixture=fixture).items():
            object.__setattr__(out, key, value)
        encoded = _json(plan)
        object.__setattr__(out, '_plan', encoded)
        owned = budget.reserve(2048+len(encoded), category='private-heat-call-definition-owned')
        owned.__enter__()
        try:
            weakref.finalize(out, owned.__exit__, None, None, None)
        except BaseException:
            owned.__exit__(None, None, None)
            raise
        meta = dict(metadata, plan_id=hashlib.sha256(encoded).hexdigest(),
                    geometry_id=geometry.geometry_id, execution=execution.provenance,
                    fixture_only=fixture)
        _new_snapshot(meta, arrays, budget, out, '_snapshot')
    return out


def bind_owner_call(owner, step, mesh, *, boundary, absolute_residual_target,
                    execution, cancel=None):
    """Forward owner seam; does not reconstruct, solve or issue a heat result.

    Mirrors current owner heat checks and its EXACT binary capacity operation
    order. Sources were already booked by transport: this owner route uses zero
    added power. A future general source route needs its own genuine producer.
    Caller-specified boundary/target are physical/solver inputs, not provenance.
    """
    _check(cancel)
    target_work = RESOURCES.target_bytes(absolute_residual_target, budget=owner._budget, cancel=cancel)
    with RESOURCES.workspace(owner._budget, target_work+65536, cancel=cancel, category='private-heat-owner-call') as scope:
        origin = _origin_signature(owner, step, mesh)
        target_text = _target_text(absolute_residual_target, cancel)
        target = Fraction(target_text)
        # One complete decode at a time. The graph and the transported state
        # are read through compact owned copies of exactly the fields used
        # below; the mesh decode lives only until its metric exists.
        g = scope.stack.enter_context(LIVE_SPATIAL.record_access(step.graph,
            scope=HEAT_LEDGER.required_scope((owner,), owner._budget)))
        t = scope.stack.enter_context(LIVE_SPATIAL.transport_access(step.result,
            scope=HEAT_LEDGER.required_scope((owner,), owner._budget)))
        if mesh.is_compact:
            return _bind_indexed_owner_call(owner, step, mesh, g=g, t=t, origin=origin,
                target=target, target_text=target_text, absolute_residual_target=absolute_residual_target,
                boundary=boundary, execution=execution, cancel=cancel)
        mv = scope.stack.enter_context(RESOURCES.decoded(mesh._json, budget=owner._budget, cancel=cancel))
        m = mv.value
        projection_bytes = RESOURCES.owner_projection_bytes(m, g, t, owner._component_count,
                                                            budget=owner._budget, cancel=cancel)
        scope.stack.enter_context(RESOURCES.workspace(owner._budget, projection_bytes,
            cancel=cancel, category='private-heat-owner-input-projection'))
        boundary = {} if boundary is None else dict(boundary)
        columns = {key: i for i, key in enumerate(t['cell_ids'])}
        cp = owner._collar._native._material.heat_capacity_j_kg_k
        old, capacity = [], []
        for row in m['cells']:
            at = columns[row['logical_cell_id']]
            old.append(_project(_q(t['exact_stocks']['enthalpy_j'][at])))
            mass = sum((_q(t['exact_stocks']['component_mass_kg:'+str(i)][at])
                        for i in range(owner._component_count)), Fraction(0))
            capacity.append(float(_project(mass)*cp))
            del mass
        k = float(owner._definition['conductivity_w_m_k'])
        geometry = MimeticGeometry(m, budget=owner._budget)
        for fid, entry in boundary.items():
            kind, value = entry
            value = float(value)
            boundary[fid] = [kind, value]
        # Last use of the complete mesh decode. The metric owns its encoding
        # and exact metrics, and its retained lease charges its face names
        # again. Cell names continue as an owned compact copy.
        cells = scope.stack.enter_context(RESOURCES.extracted(mv, _MESH_FIELDS,
            budget=owner._budget, cancel=cancel)).value['cells']
        del m, row
        mv.close()
        plan = dict(schema='atlas.private.composed-heat-plan.r1', method_id=METHOD,
                    geometry_id=geometry.geometry_id, conductivity_w_m_k=[k]*len(old),
                    absolute_residual_target=_enc(target), absolute_residual_target_decimal=target_text,
                    original_target=_target_provenance(absolute_residual_target),
                    boundary=boundary,
                    endpoint_face_trace_status=N.A.TRACE_STATUS)
        meta = dict(schema='atlas.private.composed-owner-call.r1', owner_id=owner.owner_id,
                    owner_definition_id=_hash(owner._definition), heat_capacity_j_kg_k=cp,
                    state_id=step.result.result_id, source_stage_id=step.source.result_id,
                    graph_id=step.graph.geometry_id, thermal_mesh_id=mesh.geometry_id,
                    duration_s=float(step.source.duration_s), cell_ids=[r['cell_id'] for r in cells],
                    source_policy='already-booked-transport; zero added heat source',
                    native_origin_signature=origin)
        arrays = dict(enthalpy_j=np.asarray(old), capacity_j_k=np.asarray(capacity),
                      source_w=np.zeros(len(old)))
        out = _make_call(meta, arrays, geometry, execution, plan,
                         (owner, step, mesh, step.result._snapshot))
        return out



def _bind_indexed_owner_call(owner, step, mesh, *, g, t, origin, target,
        target_text, absolute_residual_target, boundary, execution, cancel):
    # Called only after bind_owner_call's actual type/origin/runtime gates and
    # its owned graph/transport extraction. This does not admit supplied data.
    prepared = INDEXED_INPUTS.prepare_indexed_inputs(mesh, g, t,
        graph_id=step.graph.geometry_id, funding_id=owner._funding.funding_id,
        source_stage_id=step.source.result_id, parent_state_id=step.parent.state_id,
        duration_s=step.source.duration_s, component_count=owner._component_count,
        heat_capacity_j_kg_k=owner._collar._native._material.heat_capacity_j_kg_k,
        conductivity_w_m_k=owner._definition['conductivity_w_m_k'],
        boundary=boundary, budget=owner._budget, cancel=cancel)
    descriptor = prepared.descriptor()
    data = cast(dict, descriptor.value)
    # Preparation's scratch was released on return. Fund the new plan/list
    # containers separately before constructing them; this frame retains the
    # allocation if an escaping exception keeps any of those objects alive.
    assembly = INDEXED_INPUTS._Allocation(owner._budget,
        65536+256*len(data['cell_ids']), 'indexed-heat-owner-call-assembly')
    arrays = {name: prepared.array(name) for name in
              ('enthalpy_j', 'capacity_j_k', 'source_w')}
    plan = dict(schema='atlas.private.composed-heat-plan.r1', method_id=METHOD,
        geometry_id=cast(MimeticGeometry, prepared.geometry).geometry_id,
        conductivity_w_m_k=[data['conductivity_w_m_k']]*len(arrays['enthalpy_j']),
        absolute_residual_target=_enc(target), absolute_residual_target_decimal=target_text,
        original_target=_target_provenance(absolute_residual_target), boundary=data['boundary'],
        endpoint_face_trace_status=N.A.TRACE_STATUS)
    meta = dict(schema='atlas.private.composed-owner-call.r1', owner_id=owner.owner_id,
        owner_definition_id=_hash(owner._definition),
        heat_capacity_j_kg_k=data['heat_capacity_j_kg_k'],
        state_id=step.result.result_id, source_stage_id=step.source.result_id,
        graph_id=step.graph.geometry_id, thermal_mesh_id=mesh.geometry_id,
        duration_s=float(step.source.duration_s), cell_ids=data['cell_ids'],
        source_policy='already-booked-transport; zero added heat source',
        native_origin_signature=origin)
    out = _make_call(meta, arrays, prepared.geometry, execution, plan,
                     (owner, step, mesh, step.result._snapshot))
    del meta, plan, arrays, data, descriptor, prepared
    del assembly
    return out

def _verify_call_record(call, meta, cancel=None):
    _check(cancel)
    if (call.call_id != _snapshot_identity(call._snapshot, call._budget, cancel)
            or meta['geometry_id'] != INDEXED.metric_identity(call._geometry, cancel=cancel)
            or meta['plan_id'] != hashlib.sha256(call._plan).hexdigest()
            or meta['fixture_only'] is not call._fixture
            or call._geometry._budget is not call._budget
            or meta['execution'] != call._execution.provenance):
        raise ValueError('Actual caller snapshot, metric, plan or runtime changed')
    if not call._fixture:
        owner, step, mesh, snapshot = call._origin_objects
        if (step._owner is not owner or step.result._snapshot is not snapshot
                or _snapshot_identity(snapshot, owner._budget) != meta['state_id']
                or step.source.result_id != meta['source_stage_id']
                or float(step.source.duration_s) != meta['duration_s']
                or step.graph.geometry_id != meta['graph_id'] or mesh.geometry_id != meta['thermal_mesh_id']
                or owner.owner_id != meta['owner_id'] or mesh._resource is not call._budget
                or _hash(owner._definition) != meta['owner_definition_id']
                or owner._collar._native._material.heat_capacity_j_kg_k != meta['heat_capacity_j_kg_k']):
            raise ValueError('Actual native owner origin changed')
    if 'native_origin_signature' in meta:
        owner, step, mesh, snapshot = call._origin_objects
    elif call._fixture:
        if (len(call._origin_objects) != 1 or
                _snapshot_identity(call._origin_objects[0], call._budget, cancel) != meta['state_id']):
            raise ValueError('Explicit fixture snapshot changed')
    return meta


def _verify_funded_call_record(call, meta, cancel):
    with RESOURCES.workspace(call._budget, 65536, cancel=cancel, category='private-heat-identity-work'):
        _verify_call_record(call, meta, cancel)


def _verified_call_with_binding(call, cancel):
    if type(call) is not OwnerHeatCall:
        raise TypeError('A forward-issued owner call is required')
    snapshot = call._snapshot
    metadata = snapshot._metadata
    view = RESOURCES.decoded(metadata, budget=call._budget, cancel=cancel)
    try:
        _verify_funded_call_record(call, view.value, cancel)
        return view, (snapshot, metadata)
    except BaseException:
        view.__exit__(*sys.exc_info())
        raise


def _verified_call(call, cancel=None):
    view, _ = _verified_call_with_binding(call, cancel)
    return view


def _verify_call(call, cancel=None):
    with _verified_call(call, cancel):
        pass


def _reverify_borrowed_call(call, meta, metadata_binding, cancel):
    snapshot, metadata = metadata_binding
    if call._snapshot is snapshot and snapshot._metadata is metadata:
        _verify_funded_call_record(call, meta, cancel)
    else:
        _verify_call(call, cancel)


@dataclass(frozen=True, slots=True, weakref_slot=True, init=False)
class ComposedHeatResult:
    _snapshot: object = field(repr=False)
    _budget: object = field(repr=False)
    _geometry: object = field(repr=False)
    _plan_definition: bytes = field(repr=False)

    def __init__(self, *args, **kwargs):
        raise TypeError('Composed results are issued only by a forward producer')

    @property
    def result_id(self):
        return self._snapshot.result_id

    @property
    def nbytes(self):
        return self._snapshot.nbytes

    @property
    def array_names(self):
        return self._snapshot.array_names

    def descriptor(self):
        return self._snapshot.descriptor()

    def plan_descriptor(self):
        return json.loads(self._plan_definition)

    def array(self, name):
        return self._snapshot.array(name)


def advance(call, *, cancel=None):
    """Fixed forward producer only; derived owned stages, no manual allowance."""
    metadata_owner, metadata_binding = _verified_call_with_binding(call, cancel)
    with metadata_owner:
        meta = metadata_owner.value
        with RESOURCES.decoded(call._plan, budget=call._budget, cancel=cancel) as plan_owner:
            plan = plan_owner.value
            n = len(call._geometry._cells)
            with RESOURCES.workspace(call._budget, 65536+1024*(8*n+32), cancel=cancel,
                                     category='private-heat-call-array-copies'):
                return _advance_verified(call, meta, plan, cancel, metadata_binding)


def _advance_verified(call, meta, plan, cancel, metadata_binding):
    values = {name: call._snapshot.array(name).tolist() for name in call._snapshot.array_names}
    conductivity = plan['conductivity_w_m_k']
    issued_inputs = F._IssuedInputs((call._geometry, values['enthalpy_j'], values['capacity_j_k'],
        meta['duration_s'], values['source_w'], plan['boundary'], conductivity[0],
        plan['absolute_residual_target_decimal'], call._budget))
    # The fixed issuer supplies the exact bytes created by the owned sealer.
    sealed_output = []
    with F.advance(call._geometry, values['enthalpy_j'], values['capacity_j_k'],
            meta['duration_s'], values['source_w'], plan['boundary'],
            conductivity=conductivity[0],
            absolute_residual_target=plan['absolute_residual_target_decimal'],
            budget=call._budget, cancelled=cancel, _issued_inputs=issued_inputs,
            _sealed_output=sealed_output) as numerical_owner:
        del issued_inputs
        try:
            produced, diagnostics = numerical_owner.value
            _reverify_borrowed_call(call, meta, metadata_binding, cancel)
            projection_owner = N._project(produced, call._geometry, cell_ids=meta['cell_ids'],
                enthalpy_j=values['enthalpy_j'], capacity_j_k=values['capacity_j_k'],
                source_w=values['source_w'], duration_s=meta['duration_s'], state_id=meta['state_id'],
                absolute_residual_target=_q(plan['absolute_residual_target']), budget=call._budget,
                cancel=cancel, record_scope=HEAT_LEDGER.verify_scope(call),
                sealed_output=sealed_output)
        finally:
            sealed_output.clear()
        del values
        # The solve result and its unread diagnostics end here: projection
        # verified and decoded its own independent copy (verified_private).
        del produced, diagnostics
        numerical_owner.close()
        with projection_owner:
            projected, private = projection_owner.value
            fixed, powers = {}, {}
            for f, linked in enumerate(call._geometry._incidence):
                if len(linked) != 1:
                    continue
                kind, value = plan['boundary'].get(call._geometry._face_ids[f], ('power', 0.))
                if kind == 'temperature':
                    fixed[str(f)] = N._q(value)
                else:
                    powers[str(f)] = N._q(meta['duration_s'])*N._q(value)
            actual_fixed = {str(f): v for f, v in projected['boundary_exact']['boundary_temperature'].items()}
            actual_power = {str(f): v for f, v in projected['boundary_exact']['prescribed_boundary_energy'].items()}
            record = projected['metadata']
            record.pop('unverified_advance_context')
            record.update(schema=SCHEMA, method_id=METHOD, private_correction_method_id=private['method_id'],
                plan_id=meta['plan_id'], state_id=meta['state_id'], duration_s=meta['duration_s'],
                call_id=call.call_id, caller_snapshot=meta,
                origin_binding_status=('TEST_FIXTURE_NOT_NATIVE_OWNER' if call._fixture
                                       else 'FORWARD_ACTUAL_OWNER_SNAPSHOT'),
                genuine_forward_origin=not call._fixture,
                fixed_forward_producer='private_heat_forward_kernel_r13.advance',
                native_issue_performed=False, native_resource_admitted=False,
                whole_method_memory_inventory_certified=False, native_heat_dispatch_enabled=False,
                production_acceptance=False, endpoint_face_trace_status=N.A.TRACE_STATUS,
                source_policy=meta['source_policy'],
                resource_scope='Derived call, projection, snapshot/codec and fixed-forward policies; not allocator/RSS or native admission')
            result = object.__new__(ComposedHeatResult)
            object.__setattr__(result, '_budget', call._budget)
            object.__setattr__(result, '_geometry', call._geometry)
            object.__setattr__(result, '_plan_definition', call._plan)
            lease = call._budget.reserve(1024+len(call._plan), category='private-heat-result-plan')
            lease.__enter__()
            try:
                weakref.finalize(result, lease.__exit__, None, None, None)
            except BaseException:
                lease.__exit__(None, None, None)
                raise
            snapshot = HEAT_LEDGER.package_result(record, {key: np.asarray(value, dtype=np.float64)
                          for key, value in projected['arrays'].items()}, call, cancel=cancel)
            object.__setattr__(result, '_snapshot', snapshot)
            _verify_call(call, cancel)
            # All borrowed numerical records die before their owning workspace.
            del projected, private, record, fixed, powers, actual_fixed, actual_power
    return result


def issue_saved(*args, **kwargs):
    raise ValueError('Saved low/high/private results have no native forward origin; replay issuance is forbidden')


def advance_legacy_packaging(call, *, cancel=None):
    """Fixed forward producer only; derived owned stages, no manual allowance."""
    metadata_owner, metadata_binding = _verified_call_with_binding(call, cancel)
    with metadata_owner:
        meta = metadata_owner.value
        with RESOURCES.decoded(call._plan, budget=call._budget, cancel=cancel) as plan_owner:
            plan = plan_owner.value
            n = len(call._geometry._cells)
            with RESOURCES.workspace(call._budget, 65536+1024*(8*n+32), cancel=cancel,
                                     category='private-heat-call-array-copies'):
                return _advance_legacy_packaging_verified(call, meta, plan, cancel, metadata_binding)

def _advance_legacy_packaging_verified(call, meta, plan, cancel, metadata_binding):
    values = {name: call._snapshot.array(name).tolist() for name in call._snapshot.array_names}
    conductivity = plan['conductivity_w_m_k']
    # The fixed issuer supplies the exact bytes created by the owned sealer.
    sealed_output = []
    with F.advance(call._geometry, values['enthalpy_j'], values['capacity_j_k'],
            meta['duration_s'], values['source_w'], plan['boundary'],
            conductivity=conductivity[0],
            absolute_residual_target=plan['absolute_residual_target_decimal'],
            budget=call._budget, cancelled=cancel, _sealed_output=sealed_output) as numerical_owner:
        try:
            produced, diagnostics = numerical_owner.value
            _reverify_borrowed_call(call, meta, metadata_binding, cancel)
            projection_owner = N._project(produced, call._geometry, cell_ids=meta['cell_ids'],
                enthalpy_j=values['enthalpy_j'], capacity_j_k=values['capacity_j_k'],
                source_w=values['source_w'], duration_s=meta['duration_s'], state_id=meta['state_id'],
                absolute_residual_target=_q(plan['absolute_residual_target']), budget=call._budget, cancel=cancel,
                sealed_output=sealed_output)
        finally:
            sealed_output.clear()
        with projection_owner:
            projected, private = projection_owner.value
            fixed, powers = {}, {}
            for f, linked in enumerate(call._geometry._incidence):
                if len(linked) != 1:
                    continue
                kind, value = plan['boundary'].get(call._geometry._face_ids[f], ('power', 0.))
                if kind == 'temperature':
                    fixed[str(f)] = N._q(value)
                else:
                    powers[str(f)] = N._q(meta['duration_s'])*N._q(value)
            actual_fixed = {str(f): v for f, v in projected['boundary_exact']['boundary_temperature'].items()}
            actual_power = {str(f): v for f, v in projected['boundary_exact']['prescribed_boundary_energy'].items()}
            record = projected['metadata']
            record.pop('unverified_advance_context')
            record.update(schema=SCHEMA, method_id=METHOD, private_correction_method_id=private['method_id'],
                plan_id=meta['plan_id'], state_id=meta['state_id'], duration_s=meta['duration_s'],
                call_id=call.call_id, caller_snapshot=meta,
                origin_binding_status=('TEST_FIXTURE_NOT_NATIVE_OWNER' if call._fixture
                                       else 'FORWARD_ACTUAL_OWNER_SNAPSHOT'),
                genuine_forward_origin=not call._fixture,
                fixed_forward_producer='private_heat_forward_kernel_r13.advance',
                native_issue_performed=False, native_resource_admitted=False,
                whole_method_memory_inventory_certified=False, native_heat_dispatch_enabled=False,
                production_acceptance=False, endpoint_face_trace_status=N.A.TRACE_STATUS,
                source_policy=meta['source_policy'],
                resource_scope='Derived call, projection, snapshot/codec and fixed-forward policies; not allocator/RSS or native admission')
            result = object.__new__(ComposedHeatResult)
            object.__setattr__(result, '_budget', call._budget)
            object.__setattr__(result, '_geometry', call._geometry)
            object.__setattr__(result, '_plan_definition', call._plan)
            lease = call._budget.reserve(1024+len(call._plan), category='private-heat-result-plan')
            lease.__enter__()
            try:
                weakref.finalize(result, lease.__exit__, None, None, None)
            except BaseException:
                lease.__exit__(None, None, None)
                raise
            _new_snapshot(record, {key: np.asarray(value, dtype=np.float64)
                          for key, value in projected['arrays'].items()}, call._budget, result, '_snapshot')
            _verify_call(call, cancel)
            # All borrowed numerical records die before their owning workspace.
            del produced, diagnostics, projected, private, record, fixed, powers, actual_fixed, actual_power
    return result

