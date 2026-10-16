"""One authentic ordinary-owner heat/finish control; no private heat solve."""
import ast
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest

HERE = Path(__file__).resolve().parent
TASK = HERE.parents[4]
BASE = HERE.parents[1]/'runtime-integration-r1/runtime-src/atlas_tectonics'


def method_source(source, name):
    node = next(n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.FunctionDef) and n.name == name)
    return textwrap.dedent(''.join(source.splitlines(keepends=True)[node.lineno-1:node.end_lineno]))


def child(paths, *, finish_only=False):
    import gc
    from types import SimpleNamespace
    from unittest.mock import patch
    sys.path[:0] = paths
    import test_i04_spatial_workflow as F
    import live_spatial_patch as L
    import spatial_indexed_patch as SIP
    import mesh_tables as M
    from atlas_tectonics import integration_spatial_owner as O
    from atlas_tectonics import integration_spatial_ale as A
    from atlas_tectonics import integration_exterior_mesh as E
    from atlas_tectonics import regional_collar3d as RC
    from content_cache import create_retained_scope
    from record_views import RecordRef
    from threadpoolctl import threadpool_limits
    test = unittest.TestCase()
    raw = (BASE/'integration_spatial_owner.py').read_bytes()
    baseline = raw.decode().replace('\r\n', '\n')
    changed = Path(O.__file__).read_text()
    expected_source = '0973cb3f0bccc833f476bbfa555864d62a6f906035b871f73e9d8a9c1ded9559'
    test.assertEqual(sha256(raw).hexdigest(), expected_source)
    native = {}
    for name in ('close_graph', 'transport', 'heat', 'finish'):
        namespace = dict(O.__dict__)
        exec(compile(method_source(baseline, name), '<native-owner-'+name+'>', 'exec'), namespace)
        native[name] = namespace[name]
    collar_source = (BASE/'regional_collar3d.py').read_text()
    for name in ('transport_from_spatial', 'heat_from_spatial'):
        namespace = dict(RC.__dict__)
        exec(compile(method_source(collar_source, name), '<native-collar-'+name+'>', 'exec'), namespace)
        native[name] = namespace[name]
    # The heat caloric assembly and both finish conservation loops are exact
    # native AST bodies. Only access, geometry construction and packaging differ.
    for method, targets in (('heat', ('row',)), ('finish', ('name', '(at, row)'))):
        def loops(source):
            tree = ast.parse(method_source(source, method))
            return {ast.unparse(n.target): ast.dump(n) for n in ast.walk(tree)
                    if isinstance(n, ast.For) and ast.unparse(n.target) in targets}
        test.assertEqual(loops(baseline), loops(changed))

    def arrays(holder):
        return {name: holder.array(name).tobytes() for name in holder.array_names}

    def digest_parts(parts):
        digest, size = sha256(), 0
        for part in parts:
            digest.update(part); size += len(part)
        return digest.hexdigest(), size

    with threadpool_limits(1), F.actual_spatial_fixture() as case:
        budget, collar = case['budget'], case['collar']
        scope = create_retained_scope(budget, process_epoch='live-native-owner-control')
        initial = F.thermal_mesh(case, case['wall'], 'start')
        with O.PreparedSpatialOwner(case['funding'], collar, case['bounds'], initial,
                method='implicit-upwind', max_projection_errors=F.allowances(case), budget=budget) as owner:
            parent = collar.initial_state_from_funding(case['funding'], case['owner'])
            route = SimpleNamespace(exterior_state=owner.initial_state,
                source_flow_stage=lambda duration, _parent=parent, _collar=collar, **kw:
                    _collar.source_flow_stage(_parent, duration, **kw))
            source, bounds, mesh, wall = F.next_interval(case, route)
            graph = native['close_graph'](owner, owner.initial_state, source, bounds)
            step = native['transport'](owner, owner.initial_state, source, graph)
            heat = native['heat'](owner, step, mesh)
            transport = native['transport_from_spatial'](collar, source, step.result, graph, method='implicit-upwind')
            heated = native['heat_from_spatial'](collar, transport, heat, mesh)
            endpoint = collar.endpoint_from_transport(transport, heated)
            expected = native['finish'](owner, step, mesh, heat, endpoint)
            expected_state = expected.state.record()
            expected_record = expected.record()
            owner._record_scope = scope
            with L.construction(scope, budget=budget):
                compact_bounds = A._issue(A.SpatialALEBounds, bounds.record(), budget)
            compact_graph = owner.close_graph(owner.initial_state, source, compact_bounds)
            test.assertEqual(compact_graph.geometry_id, graph.geometry_id)
            compact_step = owner.transport(owner.initial_state, source, compact_graph)
            test.assertEqual(compact_step.result.result_id, step.result.result_id)
            body, blobs = mesh.record(), {}
            metadata, fields = M.pack_mesh(body, support_writer=blobs.__setitem__, budget=budget)
            view = M.CompactMesh(metadata, fields, support_reader=lambda identity, size, _blobs=blobs: _blobs[identity],
                expected_geometry_id=mesh.geometry_id, budget=budget, scope=scope)
            compact_mesh = E.ExteriorMesh.from_compact(view, budget=budget)
            required_body = dict(body, required_thermal_boundary_faces=[next(
                row['face_id'] for row in body['faces'] if len(row['owners']) == 1)])
            required_metadata, required_fields = M.pack_mesh(required_body,
                support_writer=blobs.__setitem__, budget=budget)
            required_view = M.CompactMesh(required_metadata, required_fields,
                support_reader=lambda identity, size, _blobs=blobs: _blobs[identity],
                expected_geometry_id=M.digest(required_body), budget=budget, scope=scope)
            required_mesh = E.ExteriorMesh.from_compact(required_view, budget=budget)
            with test.assertRaisesRegex(O.TectonicsError, 'open native and reservoir-cut thermal faces'):
                owner.heat(compact_step, required_mesh)
            del required_mesh, required_view, required_metadata, required_fields, required_body
            del body, metadata, fields
            with compact_step.result.record() as ref:
                full_ids = {ref.identity().sha256, compact_graph.geometry_id}
            original_export = RecordRef.export
            def bounded_export(ref, **kwargs):
                test.assertNotIn(ref.identity().sha256, full_ids)
                return original_export(ref, **kwargs)

            # A refused real owner call retains its paid decoded fields while
            # the diagnostic traceback is held; retry consumes the same inputs.
            if not finish_only:
                before, held = budget.reserved_bytes, []
                cause = ValueError('original heat cause')
                def fail(*args, **kwargs):
                    raise RuntimeError('ordinary owner heat failure') from cause
                with patch.object(O.PreparedMimeticHeat3D, 'advance', fail):
                    try:
                        owner.heat(compact_step, compact_mesh)
                    except RuntimeError as error:
                        test.assertEqual(str(error), 'ordinary owner heat failure')
                        test.assertIs(error.__cause__, cause)
                        held.append(error.__traceback__)
                    else:
                        test.fail('injected real owner heat failure missing')
                test.assertGreater(budget.reserved_bytes, before)
                held.clear(); gc.collect()
                test.assertEqual(budget.reserved_bytes, before)

            with patch.object(RecordRef, 'export', bounded_export):
                actual_heat = owner.heat(compact_step, compact_mesh)
                test.assertEqual(actual_heat.result_id, heat.result_id)
                test.assertEqual(actual_heat.descriptor(), heat.descriptor())
                test.assertEqual(arrays(actual_heat._snapshot), arrays(heat._snapshot))
                adopted = collar.transport_from_spatial(source, compact_step.result, compact_graph, method='implicit-upwind')
                hot = collar.heat_from_spatial(adopted, actual_heat, compact_mesh)
                actual_endpoint = collar.endpoint_from_transport(adopted, hot)
                actual = owner.finish(compact_step, compact_mesh, actual_heat, actual_endpoint)
            test.assertEqual(actual.result_id, expected.result_id)
            test.assertEqual(actual.state.state_id, expected.state.state_id)
            test.assertEqual({k: v.tobytes() for k, v in actual.state.arrays().items()},
                             {k: v.tobytes() for k, v in expected.state.arrays().items()})
            logical = SIP.logical_record(actual.state)
            test.assertIs(logical['thermal_mesh'], view)
            test.assertEqual(digest_parts(SIP.iter_logical_json(dict(logical))),
                digest_parts((json.dumps(expected_state, sort_keys=True, separators=(',', ':'), allow_nan=False).encode(),)))
            with actual.record() as ref:
                test.assertIsInstance(ref, RecordRef)
                test.assertEqual(ref.identity().sha256,
                    sha256(json.dumps(expected_record, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest())
            result = dict(status='PASS', actual_native_owner=True, private_heat_solve=False,
                heat_id=actual_heat.result_id, state_id=actual.state.state_id, exchange_id=actual.result_id,
                exact_heat_arrays=True, exact_state_arrays=True, exact_state_record=True, exact_exchange_record=True,
                numerical_ast_unchanged=True, failure_paid_until_traceback_release=not finish_only,
                finish_only_retry=finish_only,
                required_boundary_refusal=True,
                baseline_source_sha256=expected_source,
                source_sha256={name: sha256(Path(module.__file__).read_bytes()).hexdigest() for name, module in
                    (('live_spatial_patch.py', L), ('integration_spatial_owner.py', O),
                     ('integration_spatial_ale.py', A), ('integration_exterior_mesh.py', E))})
            del logical, actual, actual_endpoint, hot, adopted, actual_heat, compact_mesh, view, blobs, compact_step, compact_graph, compact_bounds
            del expected, expected_record, expected_state, endpoint, heated, transport, heat, step, graph
            del source, bounds, mesh, wall, route, parent
        del owner, initial
        gc.collect(); scope.close(); case.clear()
    del collar, case
    gc.collect()
    test.assertEqual(budget.reserved_bytes, 0)
    result['final_reserved_bytes'] = budget.reserved_bytes
    print(json.dumps(result, sort_keys=True), flush=True)


def legacy_child(paths):
    """The actual transformed legacy route fits its original admission limit."""
    import gc
    from types import SimpleNamespace
    sys.path[:0] = paths
    import test_i04_spatial_workflow as F
    import live_spatial_patch as L
    import mesh_tables as M
    from atlas_tectonics import integration_spatial_owner as O
    from atlas_tectonics import regional_collar3d as RC
    from threadpoolctl import threadpool_limits
    test = unittest.TestCase()
    native, baseline_hashes = {}, {}
    for module, names in ((O, ('close_graph', 'transport')), (RC, ('transport_from_spatial',))):
        path = BASE/Path(module.__file__).name
        raw = path.read_bytes()
        baseline_hashes[path.name] = sha256(raw).hexdigest()
        source = raw.decode().replace('\r\n', '\n')
        for name in names:
            namespace = dict(module.__dict__)
            exec(compile(method_source(source, name), '<native-'+name+'>', 'exec'), namespace)
            native[name] = namespace[name]
    test.assertEqual(baseline_hashes['integration_spatial_owner.py'],
        '0973cb3f0bccc833f476bbfa555864d62a6f906035b871f73e9d8a9c1ded9559')

    def arrays(value):
        return {name: (array.dtype.str, array.shape, array.tobytes())
                for name, array in value.arrays().items()}

    with threadpool_limits(1), F.actual_spatial_fixture() as case:
        budget, collar = case['budget'], case['collar']
        test.assertEqual(budget.max_bytes, 256 << 20)
        initial = F.thermal_mesh(case, case['wall'], 'start')
        with O.PreparedSpatialOwner(case['funding'], collar, case['bounds'], initial,
                method='implicit-upwind', max_projection_errors=F.allowances(case), budget=budget) as owner:
            parent = collar.initial_state_from_funding(case['funding'], case['owner'])
            route = SimpleNamespace(exterior_state=owner.initial_state,
                source_flow_stage=lambda duration, _parent=parent, _collar=collar, **kw:
                    _collar.source_flow_stage(_parent, duration, **kw))
            source, bounds, mesh, wall = F.next_interval(case, route)
            graph = native['close_graph'](owner, owner.initial_state, source, bounds)
            step = native['transport'](owner, owner.initial_state, source, graph)
            expected = native['transport_from_spatial'](collar, source, step.result, graph,
                method='implicit-upwind')
            actual_graph = owner.close_graph(owner.initial_state, source, bounds)
            actual_step = owner.transport(owner.initial_state, source, actual_graph)
            actual = collar.transport_from_spatial(source, actual_step.result, actual_graph,
                method='implicit-upwind')
            test.assertIs(type(actual_graph._json), bytes)
            test.assertFalse(L.is_transport_snapshot(actual_step.result._snapshot))
            test.assertEqual(actual_graph.geometry_id, graph.geometry_id)
            test.assertEqual(actual_graph.record(), graph.record())
            test.assertEqual(actual_step.result.result_id, step.result.result_id)
            test.assertEqual(actual_step.result.record(), step.result.record())
            test.assertEqual(arrays(actual_step.result), arrays(step.result))
            test.assertEqual(actual.result_id, expected.result_id)
            test.assertEqual(actual.record(), expected.record())
            test.assertEqual(actual.transport.descriptor(), expected.transport.descriptor())
            test.assertEqual({name: actual.transport.array(name).tobytes() for name in actual.transport.array_names},
                {name: expected.transport.array(name).tobytes() for name in expected.transport.array_names})
            before = budget.reserved_bytes
            with L.record_access(actual_graph) as record:
                test.assertEqual(budget.reserved_bytes-before, M._decode_charge(actual_graph._json))
                test.assertEqual(record['schema'], actual_graph.record()['schema'])
            del record
            test.assertEqual(budget.reserved_bytes, before)
            with L.transport_access(actual_step.result) as record:
                test.assertEqual(budget.reserved_bytes-before,
                    M._decode_charge(actual_step.result._snapshot._metadata))
                test.assertEqual(record['geometry_id'], actual_graph.geometry_id)
            del record
            test.assertEqual(budget.reserved_bytes, before)
            result = dict(status='PASS', legacy_256mib=True, heat_solve=False,
                graph_id=actual_graph.geometry_id, transport_id=actual_step.result.result_id,
                adoption_id=actual.result_id, exact_records=True, exact_arrays=True,
                audited_decode_charge=True, baseline_source_sha256=baseline_hashes,
                source_sha256={Path(module.__file__).name: sha256(Path(module.__file__).read_bytes()).hexdigest()
                    for module in (L, M, O, RC)})
            del actual, actual_step, actual_graph, expected, step, graph
            del source, bounds, mesh, wall, route, parent
        del owner, initial
        case.clear()
    del collar, case
    gc.collect()
    test.assertEqual(budget.reserved_bytes, 0)
    result['final_reserved_bytes'] = budget.reserved_bytes
    print(json.dumps(result, sort_keys=True), flush=True)


class NativeOwnerTests(unittest.TestCase):
    def test_actual_ordinary_heat_finish_parity_and_failure_ownership(self):
        self.run_fixture()

    def test_transformed_legacy_256mib_graph_transport_adoption(self):
        self.run_fixture(legacy_only=True)

    def run_fixture(self, *, finish_only=False, legacy_only=False):
        import test_live_composition as composition
        with tempfile.TemporaryDirectory(prefix='lno-', dir=TASK/'_t') as directory:
            self.assertEqual(Path(directory).resolve().parent, (TASK/'_t').resolve())
            root, helpers, ram, _ = composition.write_layout(directory)
            paths = [str(root), str(helpers), str(ram), str(composition.B.H/'source/tectonics/tests')]
            completed = subprocess.run([sys.executable, '-B', str(Path(__file__).resolve()),
                                        '--legacy-child' if legacy_only else '--child', json.dumps(paths),
                                        json.dumps(finish_only)],
                cwd=directory, text=True, capture_output=True, timeout=180)
            self.assertEqual(completed.returncode, 0, completed.stdout+'\n'+completed.stderr)
            print(completed.stdout.strip())


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--child':
        child(json.loads(sys.argv[2]), finish_only=json.loads(sys.argv[3]))
    elif len(sys.argv) > 1 and sys.argv[1] == '--legacy-child':
        legacy_child(json.loads(sys.argv[2]))
    elif len(sys.argv) > 1 and sys.argv[1] == '--legacy-only':
        NativeOwnerTests().run_fixture(legacy_only=True)
    elif len(sys.argv) > 1 and sys.argv[1] == '--finish-only':
        NativeOwnerTests().run_fixture(finish_only=True)
    else:
        unittest.main(verbosity=2)
