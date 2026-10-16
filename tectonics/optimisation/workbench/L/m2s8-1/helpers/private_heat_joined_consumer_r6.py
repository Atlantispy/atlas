"""Explicit PRIVATE owner/collar consumer bridge; no MimeticHeatResult disguise.

Only forward() makes a live wrapper, by binding an actual owner call and running
the fixed I12/F13 producer. The full independently validated public cell residual
and paired-face ledger remains in that immutable result and in ArrayStore.
Consumers borrow a small sealed header; they do not decode/revalidate hundreds
of MB of exact ledger repeatedly. Changed original objects/runtime/source fail.

The separate checkpoint branch accepts only CAS9's owned, independently checked
detached view with its original LIVE call. It never turns it into live heat or
claims authentic cross-process recovery. That factory is deliberately absent.
Native package dispatch and production/resource acceptance remain unchanged;
the companion patch is opt-in and unapplied.
JSON views follow resources r4. A decoded heat record, and what was borrowed
from it, is dropped before its view is released.
"""
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import weakref

import private_heat_native_issuer_r13 as I
import private_heat_checkpoint_consumer_r10 as CAS
import private_heat_grouped_account_r1 as ACCOUNT
import live_spatial_patch as LIVE_SPATIAL
import heat_ledger_issuer_patch as HEAT_LEDGER
import heat_cold_patch as HEAT_COLD
import exchange_record_patch as EXCHANGE_RECORD
import private_heat_indexed_runtime as INDEXED

R = I.RESOURCES
METHOD = 'private-uniform-k-composed'
LABEL = 'PRIVATE uniform-k composed physical-face heat; original transported caloric stocks'
EXCHANGE_SCHEMA = 'atlas.private.spatial-composed-advance.r1'
REF_SCHEMA = 'atlas.private.joined-heat-reference.r1'
_PINS = {
    'private_heat_grouped_account_r1.py': '392eb3d3ed0d73dccbbdac1a2eddc5e1409ef1e8c5b84fd773bcc35e4d910d60',
    'private_heat_native_issuer_r13.py': '9395513acc8f2920fd244bdc08f1b052e2e98b7018a6c8c7e66b45dd9017536a',
    'private_heat_checkpoint_consumer_r10.py': 'd2f565d42045a8bbf23574634ffa7b76e61709538f97345bd8a011b341d054a4',
    'private_heat_forward_kernel_r13.py': '5c9ad7371e30f29ad56865cbad109c5bfce9fc0c5dab8fc0a015fa52e512826d',
}
_SELF_SHA = sha256(Path(__file__).read_bytes()).hexdigest()
_HEADER = ('schema', 'method_id', 'plan_id', 'state_id', 'duration_s', 'call_id', 'geometry_id',
           'genuine_forward_origin', 'origin_binding_status', 'fixed_forward_producer',
           'native_issue_performed', 'native_resource_admitted', 'production_acceptance',
           'endpoint_face_trace_status')


def _verify(cancel=None):
    R.check(cancel)
    here = Path(__file__).resolve().parent
    if (R.source_hash(__file__, cancel) != _SELF_SHA
            or any(R.source_hash(here/name, cancel) != pin for name,pin in _PINS.items())):
        raise ValueError('Fixed joined-consumer source changed')
    CAS._verify(cancel)


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('ascii')


def source_bindings(*, cancel=None):
    """Current fixed bridge/accounting sources, independently read, not inferred from CAS."""
    _verify(cancel)
    return dict(_PINS, **{Path(__file__).name: _SELF_SHA})


@dataclass(frozen=True, slots=True, weakref_slot=True, init=False)
class LiveJoinedHeat:
    """Original fixed forward result and call, never a detached replay."""
    _result: object
    _call: object
    _seal: tuple
    _header: bytes
    _reference: bytes

    def __init__(self, *args, **kwargs):
        raise TypeError('Use the fixed actual-owner forward consumer')

    @property
    def _budget(self):
        return self._call._budget

    @property
    def _geometry(self):
        return self._call._geometry

    @property
    def result_id(self):
        return self._result.result_id

    @property
    def array_names(self):
        return self._result.array_names

    def array(self, name):
        return self._result.array(name)

    def descriptor(self):
        """Explicit full caller-owned ledger copy; native seams use header()."""
        return self._result.descriptor()

    def header(self):
        return json.loads(self._header)

    def reference(self):
        return json.loads(self._reference)

    def plan_descriptor(self):
        return json.loads(self._call._plan)


def _seal(result, call):
    return (result._snapshot, HEAT_LEDGER.seal_token(result._snapshot), result._snapshot._fields,
            result._plan_definition, call._snapshot, call._snapshot._metadata,
            call._snapshot._fields, call._plan)


def verify_live(value, *, cancel=None):
    _verify(cancel)
    if type(value) is not LiveJoinedHeat or type(value._result) is not I.ComposedHeatResult:
        raise TypeError('Actual private forward joined-heat wrapper required')
    if (value._call._fixture or len(value._seal) != 8
            or any(a is not b for a,b in zip(value._seal, _seal(value._result, value._call), strict=True))
            or value.result_id != value.header()['result_id']
            or value._result._geometry is not value._call._geometry
            or value._result._budget is not value._call._budget):
        raise ValueError('Immutable forward heat result/call changed or is a fixture')
    I._verify_call(value._call, cancel)
    return value.header()


def forward(owner, step, mesh, *, boundary, absolute_residual_target, execution, store, cancel=None):
    """Bind -> fixed producer -> authenticated CAS, once; no result injection."""
    _verify(cancel)
    if owner._heat_label != LABEL:
        raise ValueError('Owner must explicitly declare the private composed heat method')
    HEAT_LEDGER.require_candidate(store, owner, cancel=cancel)
    call = I.bind_owner_call(owner, step, mesh, boundary=boundary,
        absolute_residual_target=absolute_residual_target, execution=execution, cancel=cancel)
    result = I.advance(call, cancel=cancel)
    receipt = CAS.save(store, result, call, cancel=cancel)
    with HEAT_COLD.ledger_access(result._snapshot, budget=call._budget, cancel=cancel, resources=R) as decoded:
        meta = decoded.value
        header = {key: meta[key] for key in _HEADER}
        header['result_id'] = result.result_id
        if (meta['genuine_forward_origin'] is not True or call._fixture
                or meta['caller_snapshot']['owner_id'] != owner.owner_id):
            raise ValueError('Only actual owner forward output may join native consumers')
        with R.decoded(call._plan, budget=call._budget, cancel=cancel) as plan_owner:
            original_target = dict(plan_owner.value['original_target'])
        ref = dict(schema=REF_SCHEMA, **{k: header[k] for k in
            ('result_id', 'state_id', 'geometry_id', 'plan_id', 'call_id', 'duration_s')},
            method_id=I.METHOD, consumer_sources=source_bindings(cancel=cancel), checkpoint=receipt,
            loaded_dependency_identity=receipt['metadata']['bindings']['loaded_dependencies'],
            runtime_identity=receipt['metadata']['bindings']['runtime'],
            fixture_status=receipt['metadata']['bindings']['fixture_status'],
            original_target=original_target,
            ledger='complete immutable cell/paired-face ledger in authenticated CAS',
            native_admission=False, production_acceptance=False)
        # Header/receipt contain no per-cell residual or physical-face rational.
        with R.workspace(call._budget, 65536, cancel=cancel, category='private-joined-header-codec'):
            hb, rb = _json(header), _json(ref)
            # Last use of the decoded heat record and of what was borrowed from it.
            del meta, header, ref, original_target
            if len(hb)+len(rb) > 32768:
                raise ValueError('Joined heat reference exceeds its bounded schema')
            lease = call._budget.reserve(8192+len(hb)+len(rb), category='private-joined-header')
            lease.__enter__()
            try:
                value = object.__new__(LiveJoinedHeat)
                for name,data in dict(_result=result, _call=call, _seal=_seal(result, call),
                                      _header=hb, _reference=rb).items():
                    object.__setattr__(value, name, data)
                weakref.finalize(value, lease.__exit__, None, None, None)
            except BaseException:
                lease.__exit__(None, None, None)
                raise
    verify_live(value, cancel=cancel)
    return value


def validate_plan(owner, definition, header, mesh):
    with _SV.access(definition, header) as (definition, header):
        _verify()
        if (owner._heat_label != LABEL or not _SV.is_record(definition)
                or _SV.identity(definition, lambda value: sha256(_json(value)).hexdigest()) != header.get('plan_id')
                or definition.get('schema') != 'atlas.private.composed-heat-plan.r1'
                or definition.get('method_id') != I.METHOD
                or definition.get('geometry_id') != header.get('geometry_id')
                or definition.get('conductivity_w_m_k') != [owner._definition['conductivity_w_m_k']]*len(mesh['cells'])):
            raise ValueError('Private joined plan differs from the declared original owner/geometry/conductivity')
        I._validate_target_plan(definition)


def validate_owner(value, owner, step, mesh, *, cancel=None):
    header = verify_live(value, cancel=cancel)
    if (any(a is not b for a,b in zip(value._call._origin_objects,
            (owner, step, mesh, step.result._snapshot), strict=True))
            or owner._heat_label != LABEL):
        raise ValueError('Joined heat belongs to another actual owner/transport/mesh')
    validate_plan(owner, value.plan_descriptor(), header, INDEXED.mesh_rows(mesh))
    return header


def validate_collar(value, collar, stage, mesh, *, cancel=None):
    header = verify_live(value, cancel=cancel)
    owner, step, original_mesh, _ = value._call._origin_objects
    if (owner._collar is not collar or original_mesh is not mesh
            or stage.spatial_result is not step.result or stage.spatial_graph is not step.graph
            or stage.source_stage is not step.source.source_stage
            or stage._source_flow_stage is not step.source or stage.parent is not step.source.parent):
        raise ValueError('Joined heat is not this actual collar transport/source interval')
    return header


def grouped_account(value, owner, step, mesh, *, cancel=None):
    """Owned canonical global projection; complete ledger remains on value."""
    validate_owner(value, owner, step, mesh, cancel=cancel)
    with LIVE_SPATIAL.input_stack() as _live_inputs, LIVE_SPATIAL.record_access(step.graph, scope=EXCHANGE_RECORD.required_scope(owner)) as graph:
        transported = _live_inputs.enter_context(LIVE_SPATIAL.transport_access(step.result, scope=EXCHANGE_RECORD.required_scope(owner)))
        metric = INDEXED.mesh_rows(mesh)
        prior = owner._bound(step.parent)['projection_accounts']['enthalpy_j']
        with R.workspace(owner._budget, 65536+4096*len(graph['cells']), cancel=cancel,
                         category='private-joined-account-index'):
            positions = {key: i for i,key in enumerate(transported['cell_ids'])}
            positive = {row['cell_id'] for row in graph['cells'] if I._q(row['end_volume_m3']) > 0}
            if positive != {row['logical_cell_id'] for row in metric['cells']}:
                raise ValueError('Complete original positive physical cells required')
            for row in graph['cells']:
                if row['cell_id'] not in positive:
                    at = positions[row['cell_id']]
                    if any(I._q(v[at]) for v in transported['exact_stocks'].values()):
                        raise ValueError('Zero-volume physical cell retained stocks')
            old = [transported['exact_stocks']['enthalpy_j'][positions[row['logical_cell_id']]] for row in metric['cells']]
            public = value.array('enthalpy_j').tolist()
            residuals = transported['exact_projection_accounts']['enthalpy_j'][:len(graph['cells'])]
            with HEAT_COLD.ledger_access(value._result._snapshot, budget=owner._budget, cancel=cancel, resources=R) as decoded:
                meta = decoded.value
                return ACCOUNT.calculate(prior, residuals, old, public, meta['exact_source_energy_j'],
                    meta['exact_outward_boundary_energy_j'], budget=owner._budget, cancel=cancel)


def _grouped_account_records(value, owner, step, mesh, *, graph, transported, metric, prior, cancel=None):
    """Owned canonical global projection; complete ledger remains on value."""
    validate_owner(value, owner, step, mesh, cancel=cancel)
    with R.workspace(owner._budget, 65536+4096*len(graph['cells']), cancel=cancel,
                     category='private-joined-account-index'):
        positions = {key: i for i,key in enumerate(transported['cell_ids'])}
        positive = {row['cell_id'] for row in graph['cells'] if I._q(row['end_volume_m3']) > 0}
        if positive != {row['logical_cell_id'] for row in metric['cells']}:
            raise ValueError('Complete original positive physical cells required')
        for row in graph['cells']:
            if row['cell_id'] not in positive:
                at = positions[row['cell_id']]
                if any(I._q(v[at]) for v in transported['exact_stocks'].values()):
                    raise ValueError('Zero-volume physical cell retained stocks')
        old = [transported['exact_stocks']['enthalpy_j'][positions[row['logical_cell_id']]] for row in metric['cells']]
        public = LIVE_SPATIAL.float_sequence(value.array('enthalpy_j'),
            scope=EXCHANGE_RECORD.required_scope(owner))
        residuals = transported['exact_projection_accounts']['enthalpy_j'][:len(graph['cells'])]
        with HEAT_COLD.ledger_access(value._result._snapshot, budget=owner._budget, cancel=cancel, resources=R) as decoded:
            meta = decoded.value
            return ACCOUNT.calculate(prior, residuals, old, public, meta['exact_source_energy_j'],
                meta['exact_outward_boundary_energy_j'], budget=owner._budget, cancel=cancel)


def finish(owner, step, mesh, heat, collar_advance, *, cancel=None):
    """Native material endpoint bookkeeping with one exact grouped heat account.

This deliberately preserves the native non-heat stock/finite/dual-measure body.
It accepts ONLY an actual native endpoint adopting the SAME live heat wrapper.
The heat result remains private; this is not whole-method resource admission.
"""
    from atlas_tectonics import integration_spatial_owner as O
    from atlas_tectonics.regional_collar3d import RegionalCollarAdvance
    header = validate_owner(heat, owner, step, mesh, cancel=cancel)
    if (type(collar_advance) is not RegionalCollarAdvance
            or collar_advance.transport_stage is None or collar_advance.heat_stage is None
            or collar_advance.transport_stage.spatial_result is not step.result
            or collar_advance.transport_stage.spatial_graph is not step.graph
            or collar_advance.heat_stage.joined_result is not heat
            or collar_advance.heat_stage.joined_mesh is not mesh):
        raise O.TectonicsError('Actual joint transport/heat/native endpoint chain required')
    owner.validate_parent(step.parent, step.source.parent)
    with LIVE_SPATIAL.input_stack() as _live_inputs, LIVE_SPATIAL.record_access(step.graph, scope=EXCHANGE_RECORD.required_scope(owner)) as graph:
        old = owner._bound(step.parent)
        transported = _live_inputs.enter_context(LIVE_SPATIAL.transport_access(step.result, scope=EXCHANGE_RECORD.required_scope(owner)))
        metric = INDEXED.mesh_rows(mesh)
        if (header['state_id'] != step.result.result_id or header['geometry_id'] != mesh.geometry_id
                or mesh._resource is not owner._budget or heat._budget is not owner._budget):
            raise O.TectonicsError('Spatial heat is not the actual advected inventory and endpoint mesh')
        thermal = {row['logical_cell_id']: i for i,row in enumerate(metric['cells'])}
        with _grouped_account_records(heat, owner, step, mesh, graph=graph,
                transported=transported, metric=metric,
                prior=old['projection_accounts']['enthalpy_j'], cancel=cancel) as grouped:
            # Heat stays encoded: do NOT re-enter Python Fraction's huge LCM path.
            projection = {k: O._q(v) for k,v in old['projection_accounts'].items() if k != 'enthalpy_j'}
            physical_count = len(graph['cells'])
            for name in projection:
                projection[name] += sum(map(O._q, transported['exact_projection_accounts'][name][:physical_count]), O.Q(0))
            if LIVE_SPATIAL.EARLY_RELEASE:
                # Each non-enthalpy projection column was read once, above.
                LIVE_SPATIAL.release_columns(transported, 'exact_projection_accounts', keep=('enthalpy_j',))
            exact, native, cells = transported['exact_stocks'], collar_advance.state.fields, LIVE_SPATIAL.cell_sink(owner, cancel)
            for at,row in enumerate(graph['cells']):
                R.check(cancel)
                volume = O._q(row['end_volume_m3'])
                fields = {k: O._q(exact[k][at]) for k in owner._names if k != 'enthalpy_j'}
                if volume == 0:
                    if any(fields.values()) or O._q(exact['enthalpy_j'][at]):
                        raise O.TectonicsError('Vanished cell retained physical fields')
                    continue
                hi = thermal[row['cell_id']]
                fields['enthalpy_j'] = O.Q(float(heat.array('enthalpy_j')[hi]))
                if row['kind'] == 'collar':
                    ni = row['index']
                    for name in owner._names:
                        actual = (native.array('component_mass_kg')[int(name.rsplit(':', 1)[1])].flat[ni]
                                  if name.startswith('component_mass_kg:') else native.array(name).flat[ni])
                        if name == 'enthalpy_j':
                            if O.Q(float(actual)) != fields[name]:
                                raise O.TectonicsError('Native endpoint changed the actual joined heat result')
                        else:
                            projection[name] += fields[name]-O.Q(float(actual))
                else:
                    cells.append(dict(cell_id=row['cell_id'], source_key=row['source_key'],
                        volume_m3=O._enc(volume), exact={k: O._enc(v) for k,v in fields.items()}))
                    if graph.get('physical_geometry_family') == 'differential-plate-component-partition-v1':
                        cells[-1]['geometry_volume_error_m3'] = row['geometry_volume_error_m3']
            if LIVE_SPATIAL.EARLY_RELEASE:
                # Stock columns and the thermal lookup end with the cell loop;
                # the grouped account still holds both enthalpy slices.
                exact = thermal = None
                LIVE_SPATIAL.release_columns(transported, 'exact_stocks', keep=('enthalpy_j',))
            end = float(O._q(graph['end_time_s']))
            if O.Q(end) != O._q(graph['end_time_s']) or end != collar_advance.state.native_state.descriptor()['time_s']:
                raise O.TectonicsError('Shared spatial/native endpoint clock cannot be represented exactly')
            LIVE_SPATIAL.sort_cells(cells)
            accounts = {k: O._enc(v) for k,v in projection.items()}
            accounts['enthalpy_j'] = list(grouped.value['account'])
            record = dict(schema='atlas.spatial-exterior-state.v1', owner_id=owner.owner_id,
                funding_id=owner._funding.funding_id, time_s=end, intervals=old['intervals']+1,
                parent_state_id=step.parent.state_id, collar_state_id=collar_advance.state.result_id,
                support_id=graph['end_support_id'], trajectory_id=graph['trajectory_id'],
                trajectory=graph['trajectory'], grid_id=graph['grid_id'], thermal_mesh_id=mesh.geometry_id,
                thermal_mesh=INDEXED.stored_mesh(mesh), cells=LIVE_SPATIAL.state_cells(cells), projection_accounts=accounts)
            if owner._finite is not None:
                record['finite_stock_state'] = owner._finite.finish(step.finite_proposal, step.result).record()
            if owner._measure_policy is not None:
                record['measure_policy'] = owner._measure_policy
                record['native_material_quadrature_m3'] = [O._enc(O.Q(float(v))) for v in native.array(O.B_NAME).flat]
                owner._check_measures(record)
            state = owner._issue(record)
            del record, cells, old, metric, thermal, native, exact
            exchange = dict(schema=EXCHANGE_SCHEMA, owner_id=owner.owner_id,
                parent_state_id=step.parent.state_id, collar_state_id=collar_advance.state.result_id,
                source_flow_stage_id=step.source.result_id, source_audit_id=step.source.source_stage.source_audit.result_id,
                spatial_graph_id=step.graph.geometry_id, spatial_graph=LIVE_SPATIAL.reference(graph),
                global_transport_id=step.result.result_id, transport=LIVE_SPATIAL.reference(transported),
                joined_heat_id=heat.result_id, joined_heat=heat.reference(), joined_heat_plan=heat.plan_descriptor(),
                heat_boundary_account='outward boundary energy remains an actual external heat transfer',
                heat_projection_rule=grouped.value['proof']['rule'],
                physical_geometry='true volumes; thermal surrogate errors remain separately declared')
            if step.finite_proposal is not None:
                exchange['finite_proposal'] = step.finite_proposal.record()
            if step.measure_audit is not None:
                exchange['dual_measure_audit'] = json.loads(step.measure_audit)
            result = EXCHANGE_RECORD.build_advance(O.SpatialExteriorAdvance, state, exchange,
                step.result, heat, scope=EXCHANGE_RECORD.required_scope(owner),
                check=lambda: R.check(cancel))
            del exchange, graph, transported
            validate_owner(heat, owner, step, mesh, cancel=cancel)
            return result


def validate_saved(reference, checkpoint_owner, *, expected_result_id, arrays, budget, cancel=None):
    """Only independently validated CAS9 data; no cold-call factory implied."""
    _verify(cancel)
    if type(checkpoint_owner) is not R.P.OwnedSolve:
        raise TypeError('Live owned independently validated CAS9 checkpoint required; cold recovery unavailable')
    view = checkpoint_owner.value
    if type(view) is not CAS.ReloadedHeatView or view.fixture_only or view._call._budget is not budget:
        raise TypeError('Actual owner detached checkpoint required, never fixture heat')
    view.validate_live_call(cancel=cancel)
    if (type(reference) is not dict or reference.get('schema') != REF_SCHEMA
            or reference.get('consumer_sources') != source_bindings(cancel=cancel)
            or reference.get('result_id') != expected_result_id or view.result_id != expected_result_id
            or reference.get('call_id') != view._call.call_id
            or reference.get('method_id') != I.METHOD
            or reference.get('native_admission') is not False
            or reference.get('production_acceptance') is not False):
        raise ValueError('Saved composed reference identity/source differs')
    receipt = reference.get('checkpoint')
    if (type(receipt) is not dict or receipt.get('metadata', {}).get('result_id') != expected_result_id
            or R.stream_hash(receipt['metadata'], cancel) != receipt.get('invocation')
            or receipt['metadata'].get('bindings') != CAS._bindings(view._call, cancel)
            or receipt['metadata'].get('metadata_sha256') != HEAT_LEDGER.metadata_sha256(view._snapshot)):
        raise ValueError('Saved composed reference CAS receipt differs')
    for field,binding in (('loaded_dependency_identity','loaded_dependencies'),
                          ('runtime_identity','runtime'), ('fixture_status','fixture_status')):
        if reference.get(field) != receipt['metadata']['bindings'][binding]:
            raise ValueError('Saved composed reference runtime or fixture binding differs')
    with R.decoded(view._call._plan, budget=budget, cancel=cancel) as plan_owner:
        if reference.get('original_target') != plan_owner.value['original_target']:
            raise ValueError('Saved composed reference original target differs')
    with HEAT_COLD.ledger_access(view._snapshot, budget=budget, cancel=cancel, resources=R) as decoded:
        meta = decoded.value
        if any(reference.get(k) != meta[k] for k in ('state_id','geometry_id','plan_id','call_id','duration_s')):
            raise ValueError('Saved composed reference origin differs from the validated ledger')
        del meta
    if (set(arrays) != set(view._snapshot.array_names)
            or any(not I.np.array_equal(arrays[k].view(I.np.uint8), view.array(k).view(I.np.uint8)) for k in arrays)):
        raise ValueError('Saved joined audit arrays differ from the independently validated checkpoint')
    return view.result_id


def validate_saved_exchange(owner, state, exchange, audit_arrays, checkpoint_owner, *,
                            collar_state=None, cancel=None):
    """Explicit saved seam; an absent authentic recovery context fails closed."""
    with _SV.access(exchange) as exchange:
        if checkpoint_owner is None:
            raise TypeError('Composed exchange requires an independently authenticated owned checkpoint context')
        value = checkpoint_owner.value
        # Cold source-context successor is a distinct type, never an I12 call or
        # result. Its independently reviewed module is imported only at this seam.
        if type(value).__module__ == 'private_heat_restored_binding_r10':
            from private_heat_restored_binding_r10 import RestoredHeatBinding
            if type(value) is not RestoredHeatBinding or collar_state is None:
                raise TypeError('Actual restored heat binding and paired collar state required')
            value.validate_for(owner, state, collar_state, exchange, audit_arrays=audit_arrays, cancel=cancel)
            return exchange['joined_heat_id']
        heat = {k.removeprefix('joined-heat:'): v for k,v in audit_arrays.items() if k.startswith('joined-heat:')}
        result_id = validate_saved(exchange['joined_heat'], checkpoint_owner,
            expected_result_id=exchange['joined_heat_id'], arrays=heat, budget=owner._budget, cancel=cancel)
        if value._call._origin_objects[0] is not owner:
            raise ValueError('Saved live-call checkpoint belongs to another spatial owner')
        return result_id
import spatial_validation_patch as _SV  # compact validation r1
