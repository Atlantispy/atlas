"""Explicit private recovery factory for the frozen I12/J6 endpoint.

All provenance, original-input, exact ledger and endpoint checks are the frozen
B1 factory, except its collar index is read with the actual native flat-int or
XYZ-list policy. This factory legitimately issues the existing B1 detached
binding after those checks; it constructs neither a live heat call nor a new
heat result. Native runtime/producer source identity is never rewritten.

Additive RAM recovery successor; historical producer source identity is
separate from the immutable original producer identity.
JSON views follow resources r4, exactly as in the B1 successor it wraps.
"""
from hashlib import sha256
from pathlib import Path
import sys

import numpy as np
import private_heat_restored_binding_ram_context_r1 as B1

R, I, C, STORE = B1.R, B1.I, B1.C, B1.STORE
EXCHANGE_SCHEMA = B1.EXCHANGE_SCHEMA
ExteriorMesh = B1.ExteriorMesh
RestoredHeatBinding = B1.RestoredHeatBinding
_context = B1._context
_expected_bindings = B1._expected_bindings
_inputs = B1._inputs
_equations = B1._equations
_BINDING_SHA = 'afcf086e69eb2187ea3120834cff7983b57b91201e5c74633cc407235684f393'
_SELF_SHA = R.source_hash(__file__)


def source_bindings(cancel=None):
    result = {str(Path(B1.__file__).resolve()): _BINDING_SHA,
              str(Path(__file__).resolve()): _SELF_SHA}
    for path, expected in result.items():
        if R.source_hash(path, cancel) != expected:
            raise ValueError('Explicit recovery binding source changed: '+path)
    R.check(cancel)
    return result


def _verify(execution, cancel):
    source_bindings(cancel)
    B1._verify(execution, cancel)


def _collar_flat_index(index, shape):
    """Match regional_collar3d's actual full-grid index normalisation exactly."""
    if (type(shape) is not tuple or len(shape) != 3
            or any(type(n) is not int or n <= 0 for n in shape)):
        raise ValueError('Actual three-dimensional collar grid shape required')
    count = shape[0]*shape[1]*shape[2]
    if type(index) is int and 0 <= index < count:
        return index
    if (type(index) is not list or len(index) != 3
            or any(type(i) is not int or not 0 <= i < n
                   for i, n in zip(index, shape, strict=True))):
        raise ValueError('thermal collar index is not an actual full-grid coordinate')
    return int(np.ravel_multi_index(tuple(index), shape))


def _collar_value(array, index):
    if type(array) is not np.ndarray or array.dtype != np.dtype('float64'):
        raise ValueError('Actual native binary64 collar field required')
    return float(array.flat[_collar_flat_index(index, array.shape)])


def restore(store, receipt, *, owner, parent_spatial_state, parent_collar_state, spatial_state,
            collar_state, mesh, transport_snapshot, source_audit, exchange, execution,
            absolute_residual_target, expected_heat_result_id, budget, cancel=None):
    """Authenticate stored I12 heat against separately restored committed state.

    The workflow reader must provide its committed parent/head and expected ID;
    this is not a replacement for native workflow source/transaction recovery.
    No producer is called. Returned ownership includes every decoded heat view.
    """
    _verify(execution, cancel)
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
                    actual = ar.decode(_collar_value(collar_state.fields.array('enthalpy_j'), row['index']))
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

