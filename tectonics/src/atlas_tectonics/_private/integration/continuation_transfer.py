"""Narrow caller plumbing for the first interval after an admitted restart.

No source file is written here, no physical stage runs and no funding identity
is changed. The current workflow supplies the exact retained parent bridge.
After a new current-plan partition exists, subsequent calls pass None and use
the original strict geometry binding. Pressure/funding plumbing is separately
owned by funding_transfer; this module does not substitute for that capability.
"""
from atlas_shared.errors import AtlasError


class ContinuationTransferRefused(ValueError, AtlasError):
    pass


def select_parent_transfer(parent_partition, funding, collar, budget, transfer):
    """Validate an explicit typed bridge; it cannot alias another old parent."""
    if transfer is None:
        return None                  # ordinary default performs no added work
    from atlas_tectonics._private.integration import workflow_transfer as W
    if getattr(parent_partition, '_compact', None) is not None:
        return _select_compact_parent(parent_partition, funding, collar, budget, transfer)
    _scratch = W._decode_allocation(budget, parent_partition._json)
    body = parent_partition.record()
    if body.get('collar_plan_id') == collar.plan_id:
        return None                  # later current-plan partitions stay strict
    if not transfer.matches(body, funding=funding, collar=collar, budget=budget):
        raise ContinuationTransferRefused('geometry transfer does not name this exact historical parent')
    return transfer


def _select_compact_parent(parent_partition, funding, collar, budget, transfer):
    # A compact parent refuses record(); its short marker _json is not a body.
    # Read the one header scalar as an owned row; identity stays with the view.
    from atlas_tectonics._private.integration.geometry.partition_native_patch import compact_view, partition_fields
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
    workflow._refresh()
    return select_parent_transfer(parent_partition, workflow._funding, workflow._collar,
                                  workflow._budget, base._bridge)


def _replace(source, changes, label):
    for old, new in changes:
        source = source.replace(old, new, 1)
    return source


def joined_control_source(source):
    """Transform only the helper's actual workflow -> PDI capability argument.

    Apply this transform before other optional joined-control edits.
    """
    return _replace(source, (
        ('''    with PreparedDifferentialIteration(sphere, network, current, parent, funding,
''', '''    from atlas_tectonics._private.integration.continuation_transfer import parent_geometry_transfer
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
