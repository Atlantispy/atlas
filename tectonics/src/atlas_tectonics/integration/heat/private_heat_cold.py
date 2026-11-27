"""PRIVATE completed-workflow recovery seam; no operator or numerical replay.

Called only after CollarWorkflow's unchanged complete lineage walk. It rereads
the committed immediate parent/head, restores native typed states and physical
mesh, then authenticates the saved heat CAS through RestoredHeatBinding. The
returned owner is borrowed only during native validate_exchange. Closing it
leaves the independently restored workflow endpoint, not an injected heat call.

The declared target is recovered verbatim from the committed full heat plan,
whose hash is independently bound by the original heat CAS. No default target,
source reseeding, geometry integration or already-solved-input factory exists.
Native restore scopes are reused. Extra snapshot/copy charges follow their
existing width policy; these are accounting reservations, not allocator bounds.
"""
from decimal import Decimal
import json
import sys

from atlas_tectonics._private.integration.heat import restored_binding as B
from atlas_tectonics._private.integration.geometry import partition_workflow_patch as _COMPACT_PARTITION
from atlas_tectonics._private.integration.geometry import spatial_indexed_patch as _COMPACT_INDEXED
from atlas_tectonics.integration.coupling.regional_workflow import _hash
from atlas_tectonics.integration.coupling.regional_inventory import _width
from atlas_tectonics.regional.execution import RegionalMechanicalSnapshot
from atlas_tectonics.integration.reuse import ExecutionContext

R = B.R
_PREFIXES = ('exterior-fv:', 'source-audit:', 'spatial-audit:', 'spatial-record:',
             'differential-network:', 'differential-record:', 'partition-record:',
             'certification-record:', 'certification-force:')


def _verify(cancel):
    R.check(cancel)


def original_target(plan):
    """Recover the *tagged* declaration; never infer it from residual/output."""
    B.I._validate_target_plan(plan)
    original = plan['original_target']
    kind, value = original['kind'], original['value']
    if kind == 'represented-binary64':
        result = float.fromhex(value)
    elif kind == 'Decimal':
        result = Decimal(value)
    elif kind == 'decimal-string':
        result = value
    else:
        raise ValueError('Unknown original target provenance')
    return result


def _exchange_target(exchange):
    plan = exchange['joined_heat_plan']
    if type(exchange) is dict and type(plan) is dict:
        original = plan.get('original_target')
        if (type(original) is dict and type(original.get('kind')) is str
                and type(original.get('value')) is str):
            result = B.I._validate_target_plan(plan)
            if set(original) != {'kind', 'value'}:
                raise ValueError('Complete original target declaration required')
            if B.I._target_provenance(result) != original:
                raise ValueError('Original target representation changed')
            return result
    return original_target(plan)


def _links(parent, head):
    """Immediate committed links in addition to the caller's full chain walk."""
    if (type(parent) is not dict or type(head) is not dict
            or head.get('kind') != 'successor' or parent.get('kind') not in ('root', 'successor', 'migrated-root')
            or head.get('parent_key') != parent.get('key')
            or head.get('parent_digest') != _hash(parent)
            or head.get('sequence') != parent.get('sequence', -1)+1
            or head.get('workflow_id') != parent.get('workflow_id')
            or head.get('funding_id') != parent.get('funding_id')):
        raise ValueError('Committed immediate parent/head identity differs')


def _snapshot_charge(metadata, arrays):
    return R.L._size(65536+4*_width(metadata)+4*sum(v.nbytes for v in arrays.values())
                     +8192*len(arrays))


def _restore_parent(workflow, parent, budget, work):
    """Return owned native snapshots; retire parent read/decode scratch before heat.

    Both native restores construct immutable RegionalMechanicalSnapshot values:
    metadata is encoded and fields are copied into bytes. Keep their existing
    retained reservations on work; shorten only the borrowed source lifetime.
    """
    payload = collar_arrays = exterior_arrays = records = old = _unused = None
    parent_collar = parent_spatial = None
    store = workflow._store
    try:
        payload = _COMPACT_PARTITION.workflow_arrays(store, parent['key'], budget=budget)
        if payload is None:
            raise ValueError('Committed immediate parent arrays are missing')
        collar_arrays = {k: v for k, v in payload.items() if not k.startswith(_PREFIXES)}
        exterior_arrays = {k.removeprefix('exterior-fv:'): v for k, v in payload.items()
                           if k.startswith('exterior-fv:')}
        records = {k: v for k, v in payload.items() if k.startswith('spatial-record:')}
        work.stack.enter_context(budget.reserve(
            _snapshot_charge(parent['state'], collar_arrays), category='private-cold-parent-retained'))
        parent_collar = workflow._collar.restore(parent['state'], collar_arrays)
        with workflow._spatial_restore_records(
                parent['exterior_state'], parent.get('exterior_advance'), records, budget, store=store) as (old, _unused):
            work.stack.enter_context(budget.reserve(
                _HC.snapshot_charge(old, exterior_arrays, _snapshot_charge), category='private-cold-exterior-retained'))
            parent_spatial = workflow._exterior_owner.restore(old, exterior_arrays)
            from atlas_tectonics._private.codecs.compact_contracts import proving
            if proving():    # proof mode only
                workflow._exterior_owner.validate_parent(parent_spatial, parent_collar)
        return parent_collar, parent_spatial
    finally:
        # Also retire our references in an escaping traceback. Native callees
        # remain responsible for their own failed construction and cleanup.
        payload = collar_arrays = exterior_arrays = records = old = _unused = None
        parent_collar = parent_spatial = None


def restore_checkpoint(workflow, *, parent, head, spatial_state, collar_state,
                       source_audit, exchange, audit_arrays, cancel=None):
    """Owned detached binding from existing workflow CAS, never a live call.

    Intended `_refresh` hook only. Parent/head must be the rows accepted by that
    native chain walk: the workflow's chain walk read them, and its batch and
    closing token cover the store.
    Current endpoint objects/source audit are already restored by the workflow.
    """
    with _SV.access(exchange) as exchange:
        workflow._verify()
        _links(parent, head)
        store, budget = workflow._store, workflow._budget
        root = json.loads(workflow._root)
        if (head['workflow_id'] != root['workflow_id'] or head['funding_id'] != workflow._funding.funding_id
                or head['state']['result_id'] != collar_state.result_id
                or head['native_state_id'] != collar_state.native_state.result_id
                or head['exterior_state']['state_id'] != spatial_state.state_id
                or head['exterior_advance']['result_id'] != exchange.get('result_id')
                or head['advance']['source_audit_id'] != source_audit.result_id):
            raise ValueError('Restored head/source/exchange differs from committed workflow')
        work = R.workspace(budget, 65536, cancel=cancel, category='private-cold-workflow')
        work.__enter__()
        try:
            execution = work.stack.enter_context(ExecutionContext('scipy'))
            parent_collar, parent_spatial = _restore_parent(workflow, parent, budget, work)
            # Use the actual endpoint's immutable mesh record, already independently
            # restored and hash-bound by the native owner. This is no geometry solve.
            # The endpoint decode serves only this mesh restore (resources r4).
            if type(spatial_state._snapshot) is _COMPACT_INDEXED.IndexedSpatialSnapshot:
                # The indexed endpoint keeps its sealed compact mesh beside small
                # metadata; the expanded mesh record is never rebuilt to restore it.
                # Resources r4 decodes exact bytes only, and indexed metadata is an
                # owning bytes subclass: decode a plain copy charged before it
                # exists. The reservation leaves with the copy; a held traceback
                # keeps both (an entered, unexited reservation exits on collection).
                endpoint_metadata = spatial_state._snapshot._metadata
                endpoint_charge = budget.reserve(65536+len(endpoint_metadata),
                                                 category='private-cold-indexed-endpoint-metadata')
                endpoint_charge.__enter__()
                endpoint_metadata = bytes(endpoint_metadata)
                with R.decoded(endpoint_metadata, budget=budget, cancel=cancel) as endpoint:
                    del endpoint_metadata
                    view = spatial_state._snapshot._mesh
                    mesh = B.ExteriorMesh.from_compact(view, budget=budget)
                    del view
                endpoint_charge.__exit__(None, None, None)
                del endpoint_charge
            else:
                with R.decoded(spatial_state._snapshot._metadata, budget=budget, cancel=cancel) as endpoint:
                    mesh = B.ExteriorMesh.restore(endpoint.value['thermal_mesh'],
                        geometry_id=endpoint.value['thermal_mesh_id'], budget=budget)
            transport_fields = {k.removeprefix('spatial-transport:'): v for k, v in audit_arrays.items()
                                if k.startswith('spatial-transport:')}
            metadata = {k: v for k, v in exchange['transport'].items() if k != 'result_id'}
            work.stack.enter_context(budget.reserve(
                _snapshot_charge(metadata, transport_fields), category='private-cold-transport-retained'))
            transport = RegionalMechanicalSnapshot(metadata, transport_fields)
            target = _exchange_target(exchange)
            binding = work.stack.enter_context(B.restore(store, exchange['joined_heat']['checkpoint'],
                owner=workflow._exterior_owner, parent_spatial_state=parent_spatial,
                parent_collar_state=parent_collar, spatial_state=spatial_state, collar_state=collar_state,
                mesh=mesh, transport_snapshot=transport, source_audit=source_audit, exchange=exchange,
                execution=execution, absolute_residual_target=target,
                expected_heat_result_id=exchange['joined_heat_id'], budget=budget, cancel=cancel))
            binding.value.validate_for(workflow._exterior_owner, spatial_state, collar_state, exchange,
                                       audit_arrays=audit_arrays, cancel=cancel)
            del metadata, transport_fields
            return R.P.OwnedSolve(binding.value, work)
        except BaseException:
            work.__exit__(*sys.exc_info())
            raise
from atlas_tectonics._private.integration.heat import heat_cold_patch as _HC
from atlas_tectonics._private.integration.geometry import spatial_validation_patch as _SV
