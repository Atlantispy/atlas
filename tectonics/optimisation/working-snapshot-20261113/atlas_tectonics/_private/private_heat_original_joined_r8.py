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
R7 changes one account edit only: the two exact scalars of the owned
account inspection are read through heat_cold_patch.ledger_access. A compact r13
heat snapshot has no _metadata and is read through its ledger record; a native
snapshot keeps r6's exact decode branch. Nothing else differs from r6.
R8 (G-R3-1 (b')) adds three derived edits for a compact, unpublished end
thermal mesh: it is built in the workflow store's retained scope over the proposal's
compact supports (publish_mesh_patch.mesh_options), its required boundary faces are
read by index, and its failure capture records its identity. CollarWorkflow._publish
publishes it after its partition. A native store keeps the native mesh.
"""
from atlas_tectonics.reuse import helper_source_digest as _helper_source_digest

import ast as _ast
from hashlib import sha256 as _sha256
from pathlib import Path as _Path

_HERE = _Path(__file__).resolve().parent
_SOURCE = _HERE / 'runtime_joined_control.py'
_SOURCE_SHA = '4004900c2e29d2f7e27f9671486f4881f0089a4838ccaec16b338219b8691659'
_ACCOUNTS_SOURCE = _HERE / 'runtime_global_accounts.py'
_ACCOUNTS_SHA = '79fd6477b9f94a000d192284ae2a3c2020dbf956eb350e4c3e8f5949eaee0b9e'
_PUBLIC_ACCOUNTS_SOURCE = _HERE.parent / 'integration_regional_workflow.py'
_PUBLIC_ACCOUNTS_SHA = '1d2ad480b7d3e15779bdc16566c753324626a3694de7c6aea4edfd5c535c2f63'
_ITERATOR_SOURCE = _HERE / 'spatial_indexed_patch.py'
_ITERATOR_SHA = '46a8f98e685bb0549ea53fc22f10c6bce44fe98d6190c0eb3c86a6d4c4038a33'
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
     "        import atlas_tectonics._private.private_heat_process_meter_r1 as _meter\n"
     "        import atlas_tectonics._private.private_heat_check3_recording_r1 as _check3_existing_reread\n"
     "        with _meter.read_scope(budget, 'producer-re-read-after-publication'), _check3_existing_reread.existing_reread(__file__):\n"
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
     "    import atlas_tectonics._private.heat_cold_patch as _HEAT_COLD\n"
     "    import atlas_tectonics._private.private_heat_joined_consumer_r6 as _joined\n"
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
_RESTART_EDITS = (('indexed-state-comparison-helper', 'import numpy as np\n', 'import numpy as np\nimport atlas_tectonics._private.private_heat_indexed_runtime as INDEXED_REOPEN\n'), ('explicit-completed-query-owner', '                              before_advance=None, completed_observer=None, max_partition_components=8192):', '                              before_advance=None, completed_observer=None, max_partition_components=8192,\n                              endpoint_checkpoints=None):'), ('forward-completed-query-owner', 'max_native_mask_leaves=native_mask_leaf_limit, budget=budget, parallel=ale_parallel)', 'max_native_mask_leaves=native_mask_leaf_limit, budget=budget, parallel=ale_parallel,\n                    _endpoint_checkpoints=endpoint_checkpoints)'), ('retain-indexed-reopen-operands', 'record=accepted.exterior.state.record(), fields=accepted.exterior.state.arrays(),', 'record=INDEXED_REOPEN.spatial_record(accepted.exterior.state), fields=accepted.exterior.state.arrays(),'), ('compare-indexed-reopen-operands', "    test.assertEqual(workflow.exterior_state.record(), expected['record'])", "    INDEXED_REOPEN.compare_spatial_records(test, workflow.exterior_state, expected['record'])"))
_MESH_EDITS = (('compact-unpublished-end-mesh', "            mesh = H.build_differential_mesh(funding, bounds, partition.supports, endpoint='end',\n                max_geometry_volume_error_m3=32*radius**3, max_leaves=thermal_max_leaves,\n                max_witness_refinements=thermal_witness_refinements,\n                closed_graph=solution.graph, budget=budget)\n", "            # (b') D1 at JC 408: compact and unpublished in the store's scope; _publish publishes it.\n            import atlas_tectonics._private.publish_mesh_patch as _PUBLISH_MESH\n            mesh = H.build_differential_mesh(funding, bounds, partition.supports, endpoint='end',\n                max_geometry_volume_error_m3=32*radius**3, max_leaves=thermal_max_leaves,\n                max_witness_refinements=thermal_witness_refinements,\n                closed_graph=solution.graph, budget=budget,\n                **_PUBLISH_MESH.mesh_options(workflow, partition))\n"), ('indexed-required-boundary-faces', "        boundary = {name: ('power', 0.) for name in mesh.record()['required_thermal_boundary_faces']}\n", "        _PUBLISH_MESH.note_end_mesh(partition, mesh, budget)\n        boundary = {name: ('power', 0.) for name in\n                    _PUBLISH_MESH.required_boundary_faces(mesh)}\n"), ('compact-mesh-failure-capture', '                    parts = dict(error=str(error), closed_graph=solution.graph.record, thermal_mesh=mesh.record)\n                    size = len(solution.graph._json)+len(mesh._json)\n', '                    mesh_part, mesh_bytes = _PUBLISH_MESH.failure_mesh_operand(mesh)\n                    parts = dict(error=str(error), closed_graph=solution.graph.record, thermal_mesh=mesh_part)\n                    size = len(solution.graph._json)+mesh_bytes\n'))
_EDITS = _EDITS + _PARTITION_EDITS + _RESTART_EDITS + (('scoped-overlap-helper', "_ALE_COMPUTE_CONTEXT = ContextVar('joined_ale_compute_context', default=None)\n\n", '_ALE_COMPUTE_CONTEXT = ContextVar(\'joined_ale_compute_context\', default=None)\n\ndef _write_overlap_witness(target, budget, graph_id, partition_id, plane, first, second, shared):\n    """Bounded optional write at the failure site; no payload survives this call."""\n    from atlas_tectonics.integration_exterior_mesh import _enc\n    def small(value):\n        return value if isinstance(value, str) and len(value) <= 256 else None\n    def identity(item):\n        key, sign, ring, ring_index, metadata = item\n        support = metadata.get(\'physical_support\')\n        support = support if isinstance(support, dict) else {}\n        return dict(key=small(key), sign=sign, plane_entry_index=ring_index,\n                    source=dict(kind=small(metadata.get(\'kind\')),\n                        logical_cell_id=small(metadata.get(\'logical_cell_id\')),\n                        physical_cell_id=small(metadata.get(\'physical_cell_id\')),\n                        differential_support_id=small(support.get(\'differential_support_id\')),\n                        support_logical_cell_id=small(support.get(\'logical_cell_id\')),\n                        voxel_id=small(support.get(\'voxel_id\'))))\n    rings = (first[2], second[2], shared)\n    counts = [len(ring) for ring in rings]\n    detail_ok = all(n <= 64 for n in counts)\n    if detail_ok:\n        for values in (plane, *(point for ring in rings for point in ring)):\n            if any(max(q.numerator.bit_length(), q.denominator.bit_length()) > 2048 for q in values):\n                detail_ok = False\n                break\n    with budget.try_reserve(4*1024*1024, category=\'thermal-overlap-witness\') as admitted:\n        if not admitted:\n            raise ValueError(\'optional overlap witness reservation declined: \'+repr(\n                (small(first[0]), first[1], small(second[0]), second[1], first[4] is second[4])))\n        payload = dict(schema=\'atlas.diagnostic.thermal-overlap-witness.v1\', graph_id=graph_id,\n            partition_id=partition_id, first=identity(first), second=identity(second),\n            same_key=first[0] == second[0], same_sign=first[1] == second[1],\n            same_candidate=first[4] is second[4],\n            ring_counts=counts, detail_status=\'COMPLETE\' if detail_ok else \'DECLINED_SIZE\')\n        if detail_ok:\n            payload.update(plane=list(map(_enc, plane)),\n                first_projected=[list(map(_enc, q)) for q in rings[0]],\n                second_projected=[list(map(_enc, q)) for q in rings[1]],\n                intersection=[list(map(_enc, q)) for q in rings[2]])\n        encoded = json.dumps(payload, sort_keys=True, separators=(\',\', \':\'), allow_nan=False)\n        if len(encoded) > 1024*1024:\n            raise ValueError(\'overlap witness encoded size exceeds bound\')\n        created = False\n        try:\n            stream = Path(target).open(\'x\', encoding=\'utf8\', newline=\'\\n\')\n            created = True\n            with stream:\n                stream.write(encoded)\n        except BaseException:\n            if created:\n                Path(target).unlink(missing_ok=True)\n            raise\n\n'), ('scoped-overlap-enter', '        # The exact closure names the components that carry material: those\n        # are the thermal cells, as the heat solve requires.\n        try:\n', "        # The exact closure names the components that carry material: those\n        # are the thermal cells, as the heat solve requires.\n        from atlas_tectonics import integration_exterior_mesh as _OVERLAP\n        witness_target = None if not folder else Path(folder)/('thermal-overlap-witness-%02d.json' % (before_head['intervals']+1))\n        witness_owner = None if witness_target is None else lambda plane, first, second, shared: _write_overlap_witness(\n            witness_target, budget, solution.graph.geometry_id, partition.partition_id, plane, first, second, shared)\n        witness_token = _OVERLAP._OVERLAP_OWNER.set(witness_owner)\n        try:\n"), ('scoped-overlap-reset', "            raise\n        boundary = {name: ('power', 0.) for name in mesh.record()['required_thermal_boundary_faces']}\n", "            raise\n        finally:\n            _OVERLAP._OVERLAP_OWNER.reset(witness_token)\n        boundary = {name: ('power', 0.) for name in mesh.record()['required_thermal_boundary_faces']}\n"), ('scoped-overlap-failure-notes', '                        error=str(error), closed_graph=solution.graph.record)\n', "                        error=str(error), closed_graph=solution.graph.record,\n                        overlap_witness_notes=getattr(error, '__notes__', []))\n")) + _MESH_EDITS


_POST_EDITS = (
    ('scoped-post-commit-transport',
     "        transported = accepted.exterior._transport.record()\n"
     "        created = created_tracer_bounds(transported, case.get('created_tracers', ()))\n"
     "        for name, (residual, bound) in created.items():\n"
     "            test.assertLessEqual(residual, bound, '%s projection error %.3e exceeds 1e-10 of its transported input, %.3e' %\n"
     "                                 (name, float(residual), float(bound)))\n",
     "        from atlas_tectonics._private import live_spatial_patch as _POST_TRANSPORT\n"
     "        with _POST_TRANSPORT.transport_access(accepted.exterior._transport, scope=getattr(owner, '_record_scope', None)) as transported:\n"
     "            created = {}\n"
     "            for name in case.get('created_tracers', ()):\n"
     "                created.update(created_tracer_bounds(transported, (name,)))\n"
     "                residual, bound = created[name]\n"
     "                test.assertLessEqual(residual, bound, '%s projection error %.3e exceeds 1e-10 of its transported input, %.3e' %\n"
     "                                     (name, float(residual), float(bound)))\n"
     "                _POST_TRANSPORT.release_columns(transported, 'exact_input_stocks')\n"
     "            projection_report = {name: [float(_q(row['sum_absolute_local_and_binary_residual'])),\n"
     "                                        float(_q(row['allowed']))]\n"
     "                for name, row in sorted(transported['field_errors'].items())}\n"),
    ('detached-projection-report',
     "            transport_projection_error_and_bound={name: [float(_q(row['sum_absolute_local_and_binary_residual'])),\n"
     "                                                         float(_q(row['allowed']))]\n"
     "                for name, row in sorted(transported['field_errors'].items())},\n",
     "            transport_projection_error_and_bound=projection_report,\n"),
)


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
            str(_PUBLIC_ACCOUNTS_SOURCE): _PUBLIC_ACCOUNTS_SHA,
            str(_ITERATOR_SOURCE): _ITERATOR_SHA,
            str(_Path(__file__).resolve()): _SELF_SHA}
    for path, expected in pins.items():
        if _helper_source_digest(_Path(path), owner_file=__file__) != expected:
            raise ValueError('Original joined fixture source changed: '+path)
    return pins


def derivation():
    """Exact frozen inputs and deterministic changes; no scientific execution."""
    source_bindings()
    return dict(schema='atlas.private.original-joined-derivation.r8',
                source=str(_SOURCE), source_sha256=_SOURCE_SHA,
                derived_text_sha256=_DERIVED_SHA,
                account_source=str(_ACCOUNTS_SOURCE), account_source_sha256=_ACCOUNTS_SHA,
                account_derived_text_sha256=_ACCOUNT_DERIVED_SHA,
                public_account_source=str(_PUBLIC_ACCOUNTS_SOURCE),
                public_account_source_sha256=_PUBLIC_ACCOUNTS_SHA,
                compact_iterator_source_sha256=_ITERATOR_SHA,
                private_inventory_derived_sha256=_PRIVATE_INVENTORY_SHA,
                changes=[label for label, _, _ in _EDITS]+['q297 end provider seam']+[label for label, _, _ in _POST_EDITS],
                account_changes=[label for label, _, _ in _ACCOUNT_EDITS],
                cancellation_scope='Actual advance callback; synthetic early-cancellation probe unchanged',
                scientific_changes=True, failure_transport_repeated=False,
                max_partition_components_default=8192,
                ceiling_scope='finite partition work allowance; native enforcement unchanged')


source_bindings()
_ORIGINAL_TEXT = _read_bound(_SOURCE, _SOURCE_SHA)
from atlas_tectonics._private.continuation_transfer import joined_control_source as _GEOMETRY_TRANSFER_SOURCE
_DERIVED_TEXT = _replace_exact(_GEOMETRY_TRANSFER_SOURCE(_ORIGINAL_TEXT), _EDITS)
from atlas_tectonics._private import q297_joined_provider_patch as _Q297_PROVIDER
_DERIVED_TEXT = _Q297_PROVIDER.transform(_DERIVED_TEXT)
_DERIVED_TEXT = _replace_exact(_DERIVED_TEXT, _POST_EDITS)
_DERIVED_SHA = _sha256(_DERIVED_TEXT.encode('utf8')).hexdigest()
_ACCOUNT_SOURCE_TEXT = _read_bound(_ACCOUNTS_SOURCE, _ACCOUNTS_SHA)
_ACCOUNT_ORIGINAL_TEXT = _function_text(_ACCOUNT_SOURCE_TEXT, 'check_global_accounts')
_ACCOUNT_DERIVED_TEXT = _replace_exact(_ACCOUNT_ORIGINAL_TEXT, _ACCOUNT_EDITS)
_ACCOUNT_DERIVED_SHA = _sha256(_ACCOUNT_DERIVED_TEXT.encode('utf8')).hexdigest()
exec(compile(_DERIVED_TEXT, str(_SOURCE)+'[private_heat_original_joined_r8]', 'exec'), globals())
# A separate globals dictionary retains the checker's original dependencies.
# The imported test module itself, and all native modules, remain untouched.
from atlas_tectonics._private import runtime_global_accounts as _ACCOUNTS
from atlas_tectonics import integration_regional_workflow as _PUBLIC_ACCOUNTS
if _Path(_PUBLIC_ACCOUNTS.__file__).resolve() != _PUBLIC_ACCOUNTS_SOURCE.resolve():
    raise ValueError('public inventory module is not the selected installed source')
if _Path(_PUBLIC_ACCOUNTS._COMPACT_SPATIAL.X.__file__).resolve() != _ITERATOR_SOURCE.resolve():
    raise ValueError('compact cell iterator is not the selected installed source')
_PUBLIC_ACCOUNT_TEXT = _function_text(_read_bound(_PUBLIC_ACCOUNTS_SOURCE, _PUBLIC_ACCOUNTS_SHA),
                                      'retained_inventory_accounts')
_PRIVATE_INVENTORY_TEXT = _replace_exact(_PUBLIC_ACCOUNT_TEXT, (
    ('bounded-compact-cell-iteration', "        for cell in record['cells']:\n",
     "        for cell in _COMPACT_SPATIAL.X.iter_state_cells(record['cells'], budget):\n"),))
_PRIVATE_INVENTORY_SHA = _sha256(_PRIVATE_INVENTORY_TEXT.encode('utf8')).hexdigest()
_PRIVATE_INVENTORY_NAMESPACE = dict(vars(_PUBLIC_ACCOUNTS))
exec(compile(_PRIVATE_INVENTORY_TEXT, str(_PUBLIC_ACCOUNTS_SOURCE)+'[diagnostic-compact-accounts]', 'exec'),
     _PRIVATE_INVENTORY_NAMESPACE)
_ACCOUNT_NAMESPACE = dict(vars(_ACCOUNTS))
_ACCOUNT_NAMESPACE['retained_inventory_accounts'] = _PRIVATE_INVENTORY_NAMESPACE['retained_inventory_accounts']
exec(compile(_ACCOUNT_DERIVED_TEXT, str(_ACCOUNTS_SOURCE)+'[owned-heat-scalars]', 'exec'),
     _ACCOUNT_NAMESPACE)
check_global_accounts = _ACCOUNT_NAMESPACE['check_global_accounts']
