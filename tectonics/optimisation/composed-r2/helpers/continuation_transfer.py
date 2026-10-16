"""Narrow caller plumbing for the first interval after an admitted restart.

No source file is written here, no physical stage runs and no funding identity
is changed. The current workflow supplies the exact retained parent bridge.
After a new current-plan partition exists, subsequent calls pass None and use
the original strict geometry binding. Pressure/funding plumbing is separately
owned by funding_transfer; this module does not substitute for that capability.
"""
from hashlib import sha256


COUPLING_SOURCE_SHA256 = '9938992a75e5a70323810a055be1e7e0b8519f44c04c56c0142ac1df90d327c7'
# partition_native_patch.transform_coupling(frozen). Its edit is disjoint from
# these three seams; that pinned transform runs first, then this one. Only this
# exact composed result is admitted from that input.
COUPLING_COMPACT_SOURCE_SHA256 = '0ef4c17d3c66fdd9d766c8f8ff75d34e89018e4c349e3ca6a220c584d06e19a5'
COUPLING_COMPACT_RESULT_SHA256 = '05f2414de10b89217f362da70966718f69a3a1aeb1e3c3a8a3895ce85d389779'
JOINED_SOURCE_SHA256 = '528832f2b10a74051a3123d00850c5f462cf8ebd76520e38ac8ba5aff763a078'


class ContinuationTransferRefused(ValueError):
    pass


def select_parent_transfer(parent_partition, funding, collar, budget, transfer):
    """Validate an explicit typed bridge; it cannot alias another old parent."""
    if transfer is None:
        return None                  # ordinary default performs no added work
    import geometry_transfer as G
    import workflow_transfer as W
    from atlas_tectonics.integration_differential_geometry import DifferentialPartition
    if (type(transfer) is not G.ParentGeometryTransfer or
            type(parent_partition) is not DifferentialPartition or
            parent_partition._resource is not budget or collar._budget is not budget):
        raise ContinuationTransferRefused('actual shared-budget parent and exact geometry capability required')
    if getattr(parent_partition, '_compact', None) is not None:
        return _select_compact_parent(parent_partition, funding, collar, budget, transfer)
    scratch = W._decode_allocation(budget, parent_partition._json)
    body = parent_partition.record()
    if body.get('collar_plan_id') == collar.plan_id:
        return None                  # later current-plan partitions stay strict
    if not transfer.matches(body, funding=funding, collar=collar, budget=budget):
        raise ContinuationTransferRefused('geometry transfer does not name this exact historical parent')
    assert scratch.size > 0
    return transfer


def _select_compact_parent(parent_partition, funding, collar, budget, transfer):
    # A compact parent refuses record(); its short marker _json is not a body.
    # Read the one header scalar as an owned row; identity stays with the view.
    from partition_native_patch import compact_view, partition_fields
    view = compact_view(parent_partition)
    header = partition_fields(parent_partition, ('collar_plan_id',))
    if header.value.get('collar_plan_id') == collar.plan_id:
        return None                  # later current-plan partitions stay strict
    if not transfer.matches_compact(view, funding=funding, collar=collar, budget=budget):
        raise ContinuationTransferRefused('geometry transfer does not name this exact historical parent')
    return transfer


def parent_geometry_transfer(workflow, parent_partition):
    """Obtain the capability from the actual current migrated workflow only."""
    base = getattr(workflow, '_migration', None)
    if base is None:
        return None
    import workflow_transfer as W
    from atlas_tectonics.integration_regional_workflow import CollarWorkflow
    if type(workflow) is not CollarWorkflow or type(base) is not W.MigratedWorkflowBase:
        raise ContinuationTransferRefused('actual migrated workflow and owned admitted base required')
    workflow._refresh()
    if parent_partition is not workflow._differential_partition:
        raise ContinuationTransferRefused('caller partition is not the currently accepted workflow parent')
    return select_parent_transfer(parent_partition, workflow._funding, workflow._collar,
                                  workflow._budget, base._bridge)


def _replace(source, expected_hash, changes, label):
    if type(source) is not str or sha256(source.encode()).hexdigest() != expected_hash:
        raise ContinuationTransferRefused(label+' differs from the reviewed exact source')
    for old, new in changes:
        if source.count(old) != 1:
            raise ContinuationTransferRefused(label+' caller seam missing or ambiguous')
        source = source.replace(old, new, 1)
    return source


def coupling_source(source):
    """Transform the inspected PDI constructor and one partition call only.

    Admits exactly the frozen coupling or its partition_native_patch transform;
    the latter must give the pinned composed result.
    """
    compact = type(source) is str and sha256(source.encode()).hexdigest() == COUPLING_COMPACT_SOURCE_SHA256
    result = _coupling_source(source, COUPLING_COMPACT_SOURCE_SHA256 if compact else COUPLING_SOURCE_SHA256)
    if compact and sha256(result.encode()).hexdigest() != COUPLING_COMPACT_RESULT_SHA256:
        raise ContinuationTransferRefused('composed differential coupling differs from the reviewed result')
    return result


def _coupling_source(source, expected_hash):
    return _replace(source, expected_hash, (
        ('                 heat_source, budget):',
         '                 heat_source, budget, _runtime_transfer=None):'),
        ('''        if type(initial_driver._lift) is not T.DifferentialPlateBoundaryLift:
''', '''        self._runtime_transfer = None
        if _runtime_transfer is not None:
            from continuation_transfer import select_parent_transfer
            self._runtime_transfer = select_parent_transfer(parent_partition, funding, collar, budget, _runtime_transfer)
        if type(initial_driver._lift) is not T.DifferentialPlateBoundaryLift:
'''),
        ('''                self._collar, finite_stock_state=self._finite, max_components=self._max_components, budget=self._budget)
''', '''                self._collar, finite_stock_state=self._finite, max_components=self._max_components, budget=self._budget,
                _runtime_transfer=self._runtime_transfer)
'''),
    ), 'differential coupling')


def joined_control_source(source):
    """Transform only the helper's actual workflow -> PDI capability argument.

    Apply this exact-base transform before other optional joined-control edits;
    the composed manifest binds the resulting helper and its full source closure.
    """
    return _replace(source, JOINED_SOURCE_SHA256, (
        ('''    with PreparedDifferentialIteration(sphere, network, current, parent, funding,
''', '''    from continuation_transfer import parent_geometry_transfer
    with PreparedDifferentialIteration(sphere, network, current, parent, funding,
'''),
        ('''            heat_source='test:no extra heat; native mechanical source booked once', budget=budget) as iteration, \\
''', '''            heat_source='test:no extra heat; native mechanical source booked once', budget=budget,
            _runtime_transfer=parent_geometry_transfer(workflow, parent)) as iteration, \\
'''),
    ), 'joined continuation control')


FRESH_PROCESS_REOPEN_CONTRACT = (
    'Process A composes the complete final source tree/helpers before any native import and records its actual runtime source identity.',
    'A tiny fixture may issue explicitly synthetic historical/runtime admissions, but retains actual native/spatial transfers, funding, original complete chain, partition, interval and source-audit bytes.',
    'Persist the original fixture archive operands and migration root in one temporary working store. Export only original immutable records/arrays plus admitted source evidence, never pickle live plans, owners, budgets or admission objects.',
    'Process A closes its ArrayStore and all leases, then exits. Process B starts with the SAME composed package/helper bytes, no loaded module replacement and a fresh WorkBudget.',
    'Historical admission and native origin must retain the authenticated ORIGINAL reader token and complete original inventory. Never recompute provenance from a new connection total_changes or the successor store after root publication; reauthenticate the unchanged readonly original DB/capsule with its stable recorded token.',
    'Process B restores original archive objects through the reviewed historical adapter, prepares current plans, reissues native/spatial/geometry transfers and separately authenticates runtime compatibility. It must reproduce the exact migration base and root IDs.',
    'Call CollarWorkflow.open_migrated on the existing root. Compare sequence/time, native/collar IDs and every array, complete spatial/finite/projection records, original funding descriptor/ID, geometry/partition IDs and complete original predecessor manifests.',
    'Assert no initial_state/funding call exists in the reopen path, native accepted_intervals stays zero, original immutable chain remains unchanged, and every reservation returns when owners/escaped buffers are released.',
    'Production uses the real source-bound historical admission and reviewed runtime policy, not fixture admissions. No new physics interval is required for this persistence test.',
)
