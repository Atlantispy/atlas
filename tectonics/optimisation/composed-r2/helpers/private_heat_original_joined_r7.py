"""Pinned actual ACTUATED helper with explicit private heat orchestration.

The source's geometry, force, cancellation probe and numerical assertions are
retained. Changes expose private heat/cancellation and two observation seams,
remove failure-only duplicate transport, and own the large heat-ledger decode.
No native science module or historical test helper is patched. The root driver
selects its package, limits, source bindings, output paths and physical target.
R2 names the joined consumer successor of the resources r4 chain; nothing else.
R3 names the joined consumer of the forward kernel r11 chain; nothing else.
R4 names the joined consumer of the forward kernel r12 chain; nothing else.
R5 names the joined consumer of the forward kernel r13 chain, and adds one harness
edit: the producer's first inspection after publication, which re-reads the committed
endpoint through the cold reader, runs inside the process meter's re-read scope.
R6 exposes the existing native partition component work ceiling, retaining the 8192
default and refusing non-positive or non-integer selections before work.
R7 (16 Oct 2026) changes one account edit only: the two exact scalars of the owned
account inspection are read through heat_cold_patch.ledger_access. A compact r13
heat snapshot has no _metadata and is read through its ledger record; a native
snapshot keeps r6's exact decode branch. Nothing else differs from r6.
"""
import ast as _ast
from hashlib import sha256 as _sha256
from pathlib import Path as _Path

_HERE = _Path(__file__).resolve().parent
_SOURCE = _Path('C:\\Users\\LOCAL_USER\\Documents\\Codex\\2026-09-02\\the-diadem-local-tasks-10\\fidelity-integration-20261005\\heat-repair-20261007\\source\\tectonics\\tests\\i04_differential_joined_control.py')
_SOURCE_SHA = '528832f2b10a74051a3123d00850c5f462cf8ebd76520e38ac8ba5aff763a078'
_ACCOUNTS_SOURCE = _Path('C:\\Users\\LOCAL_USER\\Documents\\Codex\\2026-09-02\\the-diadem-local-tasks-10\\fidelity-integration-20261005\\heat-repair-20261007\\source\\tectonics\\tests\\test_i04_spatial_workflow.py')
_ACCOUNTS_SHA = 'c7063bb01cb583e94e5f5b5aa0fd5e78cece7903a95e51a2fe2411293241d00d'
_SELF_SHA = _sha256(_Path(__file__).read_bytes()).hexdigest()
_REPEAT = '''                    try:
                        repeated = owner.transport(spatial_state, source, solution.graph,
                                                   finite_exchanges=exchanges).result
                        size += len(repeated._snapshot._metadata)
                        parts['transport'] = repeated.record
                    except Exception as repeat_error:
                        parts['transport_error'] = '%s: %s' % (type(repeat_error).__name__, repeat_error)
'''
_OLD_FAILURE_COMMENT = '''            # Failure-only replay operands of the joint transport and heat:
            # the closed graph, the thermal mesh and, when it can be repeated,
            # the transport result. Nothing is repaired or admitted from them.
            # The refusal text is taken before the transport is repeated, and
            # the repeat runs before the encoding is reserved. A repeat that
            # refuses is recorded in the capture; a capture that fails is a
            # note on this refusal, never its replacement.
'''
_EDITS = (
    ('explicit-private-parameters',
     '                              thermal_max_leaves=64, thermal_witness_refinements=8, ale_parallel=None):',
     '                              thermal_max_leaves=64, thermal_witness_refinements=8, ale_parallel=None,\n'
     '                              heat_execution=None, absolute_heat_residual_target=None, cancel=None,\n'
     '                              before_advance=None, completed_observer=None):'),
    ('validate-observation-callbacks',
     '    # Refused before any expensive work, like the ceilings below.\n',
     '    for callback in (cancel, before_advance, completed_observer):\n'
     '        if callback is not None and not callable(callback):\n'
     "            raise TypeError('Optional driver callbacks must be callable')\n"
     '    # Refused before any expensive work, like the ceilings below.\n'),
    ('forward-private-arguments',
     '            differential_solution=solution, heat_boundary=boundary, finite_exchanges=exchanges)\n',
     '            differential_solution=solution, heat_boundary=boundary, finite_exchanges=exchanges)\n'
     '        if heat_execution is not None or absolute_heat_residual_target is not None:\n'
     '            arguments.update(heat_execution=heat_execution,\n'
     '                             absolute_heat_residual_target=absolute_heat_residual_target)\n'),
    ('gate-and-cancel-real-advance-only',
     '        try:\n            accepted = workflow.advance_spatial(source, bounds, mesh, **arguments)\n',
     '        if before_advance is not None:\n'
     '            before_advance(source, bounds, mesh, solution)\n'
     '        try:\n'
     '            accepted = workflow.advance_spatial(source, bounds, mesh, cancel=cancel, **arguments)\n'),
    ('retain-original-failure-without-repeat', _REPEAT, ''),
    ('correct-failure-comment', _OLD_FAILURE_COMMENT,
     '            # Retain existing graph and mesh only. The original exception\n'
     '            # and traceback survive; transport is never repeated here.\n'),
    ('observe-completed-endpoint-before-audit',
     '        check_global_accounts(test, spatial_state, source, accepted)\n',
     '        if completed_observer is not None:\n'
     '            completed_observer(accepted)\n'
     '        check_global_accounts(test, spatial_state, source, accepted, cancel=cancel)\n'),
    ('re-read-after-publication-under-the-process-meter',
     "        test.assertEqual(workflow.inspect()['intervals'], before_head['intervals']+1)\n",
     "        # The first inspection after publication re-reads the committed endpoint through the\n"
     "        # cold reader. Where the process meter applies, the ledger follows the process while it\n"
     "        # does; where it does not, nothing differs.\n"
     "        import private_heat_process_meter_r1 as _meter\n"
     "        with _meter.read_scope(budget, 'producer-re-read-after-publication'):\n"
     "            workflow.inspect()\n"
     "        test.assertEqual(workflow.inspect()['intervals'], before_head['intervals']+1)\n"),
)
_ACCOUNT_EDITS = (
    ('owned-account-cancel-parameter',
     'def check_global_accounts(test, before_exterior, source, result):',
     'def check_global_accounts(test, before_exterior, source, result, *, cancel=None):'),
    ('owned-two-scalar-inspection',
     "    heat = result.exterior._heat.descriptor()\n"
     "    outgoing = W._decode(heat['exact_outward_boundary_energy_j'])\n"
     "    heating = W._decode(heat['exact_source_energy_j'])\n",
     "    import heat_cold_patch as _HEAT_COLD\n"
     "    import private_heat_joined_consumer_r6 as _joined\n"
     "    heat = result.exterior._heat\n"
     "    if type(heat) is _joined.LiveJoinedHeat:\n"
     "        _joined.verify_live(heat, cancel=cancel)\n"
     "        with _HEAT_COLD.ledger_access(heat._result._snapshot,\n"
     "                budget=heat._budget, cancel=cancel, resources=_joined.R) as decoded:\n"
     "            outgoing = W._decode(decoded.value['exact_outward_boundary_energy_j'])\n"
     "            heating = W._decode(decoded.value['exact_source_energy_j'])\n"
     "    else:\n"
     "        heat = heat.descriptor()\n"
     "        outgoing = W._decode(heat['exact_outward_boundary_energy_j'])\n"
     "        heating = W._decode(heat['exact_source_energy_j'])\n"),
)


_PARTITION_EDITS = (('explicit-partition-component-ceiling', '                              before_advance=None, completed_observer=None):', '                              before_advance=None, completed_observer=None, max_partition_components=8192):'), ('validate-partition-component-ceiling-before-work', '    for callback in (cancel, before_advance, completed_observer):\n', "    if type(max_partition_components) is not int or max_partition_components < 1:\n        raise ValueError('max_partition_components must be an explicit positive integer work ceiling')\n    for callback in (cancel, before_advance, completed_observer):\n"), ('forward-partition-component-ceiling', 'max_orientation_leaves=orientation_max_leaves, max_partition_components=8192,', 'max_orientation_leaves=orientation_max_leaves, max_partition_components=max_partition_components,'))
_RESTART_EDITS = (('indexed-state-comparison-helper', 'import numpy as np\n', 'import numpy as np\nimport private_heat_indexed_runtime as INDEXED_REOPEN\n'), ('explicit-completed-query-owner', '                              before_advance=None, completed_observer=None, max_partition_components=8192):', '                              before_advance=None, completed_observer=None, max_partition_components=8192,\n                              endpoint_checkpoints=None):'), ('forward-completed-query-owner', 'max_native_mask_leaves=native_mask_leaf_limit, budget=budget, parallel=ale_parallel)', 'max_native_mask_leaves=native_mask_leaf_limit, budget=budget, parallel=ale_parallel,\n                    _endpoint_checkpoints=endpoint_checkpoints)'), ('retain-indexed-reopen-operands', 'record=accepted.exterior.state.record(), fields=accepted.exterior.state.arrays(),', 'record=INDEXED_REOPEN.spatial_record(accepted.exterior.state), fields=accepted.exterior.state.arrays(),'), ('compare-indexed-reopen-operands', "    test.assertEqual(workflow.exterior_state.record(), expected['record'])", "    INDEXED_REOPEN.compare_spatial_records(test, workflow.exterior_state, expected['record'])"))
_EDITS = _EDITS + _PARTITION_EDITS + _RESTART_EDITS


def _replace_exact(source, edits):
    result = source
    for label, before, after in edits:
        if result.count(before) != 1:
            raise ValueError('Original joined derivative anchor differs: '+label)
        result = result.replace(before, after, 1)
    return result


def _function_text(source, name):
    nodes = [node for node in _ast.parse(source).body
             if isinstance(node, _ast.FunctionDef) and node.name == name]
    if len(nodes) != 1:
        raise ValueError('Exactly one original account checker required')
    return _ast.get_source_segment(source, nodes[0])+'\n'


def _read_bound(path, expected):
    raw = path.read_bytes()
    if _sha256(raw).hexdigest() != expected:
        raise ValueError('Original joined source changed while loading: '+str(path))
    return raw.decode('utf8').replace('\r\n', '\n')


def source_bindings():
    pins = {str(_SOURCE): _SOURCE_SHA, str(_ACCOUNTS_SOURCE): _ACCOUNTS_SHA,
            str(_Path(__file__).resolve()): _SELF_SHA}
    for path, expected in pins.items():
        if _sha256(_Path(path).read_bytes()).hexdigest() != expected:
            raise ValueError('Original joined fixture source changed: '+path)
    return pins


def derivation():
    """Exact frozen inputs and deterministic changes; no scientific execution."""
    source_bindings()
    return dict(schema='atlas.private.original-joined-derivation.r7',
                source=str(_SOURCE), source_sha256=_SOURCE_SHA,
                derived_text_sha256=_DERIVED_SHA,
                account_source=str(_ACCOUNTS_SOURCE), account_source_sha256=_ACCOUNTS_SHA,
                account_derived_text_sha256=_ACCOUNT_DERIVED_SHA,
                changes=[label for label, _, _ in _EDITS],
                account_changes=[label for label, _, _ in _ACCOUNT_EDITS],
                cancellation_scope='Actual advance callback; synthetic early-cancellation probe unchanged',
                scientific_changes=False, failure_transport_repeated=False,
                max_partition_components_default=8192,
                ceiling_scope='finite partition work allowance; native enforcement unchanged')


source_bindings()
_ORIGINAL_TEXT = _read_bound(_SOURCE, _SOURCE_SHA)
from continuation_transfer import joined_control_source as _GEOMETRY_TRANSFER_SOURCE
_DERIVED_TEXT = _replace_exact(_GEOMETRY_TRANSFER_SOURCE(_ORIGINAL_TEXT), _EDITS)
_DERIVED_SHA = _sha256(_DERIVED_TEXT.encode('utf8')).hexdigest()
_ACCOUNT_SOURCE_TEXT = _read_bound(_ACCOUNTS_SOURCE, _ACCOUNTS_SHA)
_ACCOUNT_ORIGINAL_TEXT = _function_text(_ACCOUNT_SOURCE_TEXT, 'check_global_accounts')
_ACCOUNT_DERIVED_TEXT = _replace_exact(_ACCOUNT_ORIGINAL_TEXT, _ACCOUNT_EDITS)
_ACCOUNT_DERIVED_SHA = _sha256(_ACCOUNT_DERIVED_TEXT.encode('utf8')).hexdigest()
exec(compile(_DERIVED_TEXT, str(_SOURCE)+'[private_heat_original_joined_r7]', 'exec'), globals())
# A separate globals dictionary retains the checker's original dependencies.
# The imported test module itself, and all native modules, remain untouched.
import test_i04_spatial_workflow as _ACCOUNTS
_ACCOUNT_NAMESPACE = dict(vars(_ACCOUNTS))
exec(compile(_ACCOUNT_DERIVED_TEXT, str(_ACCOUNTS_SOURCE)+'[owned-heat-scalars]', 'exec'),
     _ACCOUNT_NAMESPACE)
check_global_accounts = _ACCOUNT_NAMESPACE['check_global_accounts']
