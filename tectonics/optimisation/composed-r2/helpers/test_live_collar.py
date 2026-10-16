"""Actual collar adoption and finite-boundary parity for scoped record inputs."""
import ast
from copy import deepcopy
from fractions import Fraction as Q
import gc
from hashlib import sha256
import importlib
from pathlib import Path
import shutil
import sys
import tempfile
import textwrap
from types import SimpleNamespace
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
TASK = HERE.parents[4]
BASE = HERE.parents[1]/'runtime-integration-r1'/'runtime-src'/'atlas_tectonics'
H = TASK/'fidelity-integration-20261005'/'heat-repair-20261007'
BASE_SHA = 'b7ea373217eb652c13067c9bb8754089315a670a115aacb1e88fe5f48c433d2c'


def setUpModule():
    global temporary, old_path, LC, L, LF, A, RC, E, F, FLOW, RecordCodec, RecordRef, CompactRecord, scope_for, WorkBudget
    if any(name == 'atlas_tectonics' or name.startswith('atlas_tectonics.') for name in sys.modules):
        raise RuntimeError('fresh process required; no mutable live runtime patching')
    if sha256((BASE/'regional_collar3d.py').read_bytes()).hexdigest() != BASE_SHA:
        raise RuntimeError('collar source baseline changed')
    temporary = tempfile.TemporaryDirectory(prefix='lc-', dir=TASK/'_t')
    package = Path(temporary.name)/'atlas_tectonics'
    shutil.copytree(BASE, package, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    old_path = list(sys.path)
    sys.path[:0] = [str(Path(temporary.name)), str(H/'source'/'tectonics'/'tests'), str(HERE.parent),
        str(HERE.parents[1]/'runtime-integration-r1'/'ram'),
        str(HERE.parents[1]/'runtime-integration-r1'/'helpers'), str(H)]
    LC = importlib.import_module('live_collar_patch')
    L = importlib.import_module('live_spatial_patch')
    LF = importlib.import_module('live_finite_patch')
    EP = importlib.import_module('exterior_mesh_patch')
    for name, transform in (
            ('integration_spatial_ale.py', L.ale_source),
            ('integration_spatial_transport.py', L.transport_source),
            ('integration_spatial_reservoir.py', LF.reservoir_source),
            ('regional_collar3d.py', LC.collar_source)):
        path = package/name
        path.write_text(transform(path.read_text()), encoding='utf8')
    # ExteriorMesh's compact admission API, without changing its native builder.
    path = package/'integration_exterior_mesh.py'
    path.write_text(EP.transform(path.read_bytes().decode()), encoding='utf8')
    A = importlib.import_module('atlas_tectonics.integration_spatial_ale')
    RC = importlib.import_module('atlas_tectonics.regional_collar3d')
    E = importlib.import_module('atlas_tectonics.integration_exterior_mesh')
    F = importlib.import_module('test_regional_collar_finite_adoption')
    FLOW = importlib.import_module('test_i04_spatial_workflow')
    RecordCodec = importlib.import_module('record_tables').RecordCodec
    views = importlib.import_module('record_views')
    RecordRef, CompactRecord = views.RecordRef, views.CompactRecord
    scope_for = importlib.import_module('content_cache').create_retained_scope
    WorkBudget = importlib.import_module('atlas_tectonics.resources').WorkBudget


def tearDownModule():
    sys.path[:] = old_path
    assert Path(temporary.name).resolve().parent == (TASK/'_t').resolve()
    temporary.cleanup()


def pack(value, scope):
    return RecordCodec().pack_record(value, record_schema='atlas.collar-fixture.v1', scope=scope, check=lambda: None)


def native_method(name):
    source = (BASE/'regional_collar3d.py').read_text()
    node = next(n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.FunctionDef) and n.name == name)
    namespace = dict(RC.__dict__)
    exec(compile(textwrap.dedent(''.join(source.splitlines(keepends=True)[node.lineno-1:node.end_lineno])),
                 '<original-collar-method>', 'exec'), namespace)
    return namespace[name]


def snapshot(snapshot):
    return snapshot.descriptor(), {name: snapshot.array(name).tobytes() for name in snapshot.array_names}


class CollarTests(unittest.TestCase):
    def test_source_fence_native_equations_and_duplicate_refusal(self):
        source = (BASE/'regional_collar3d.py').read_text()
        self.assertEqual(sha256((BASE/'regional_collar3d.py').read_bytes()).hexdigest(), BASE_SHA)
        changed = LC.collar_source(source)
        with self.assertRaises(ValueError):
            LC.collar_source(changed)
        for name, first in (('transport_from_spatial', 'donor'), ('heat_from_spatial', 'meta')):
            def tail(text):
                node = next(n for n in ast.walk(ast.parse(text)) if isinstance(n, ast.FunctionDef) and n.name == name)
                blocks = [n.body for n in ast.walk(node) if hasattr(n, 'body') and isinstance(n.body, list)]
                body = next(body for body in blocks if any(isinstance(n, ast.Assign) and
                    ast.unparse(n.targets[0]) == first for n in body))
                start = next(i for i, n in enumerate(body) if isinstance(n, ast.Assign) and ast.unparse(n.targets[0]) == first)
                return ast.dump(ast.Module(body=body[start:], type_ignores=[]))
            self.assertEqual(tail(source), tail(changed))

    def test_finite_native_and_compact_proposal_adoption_exact(self):
        budget = WorkBudget(64 << 20)
        scope = scope_for(budget, process_epoch='live-collar-finite')
        fixture = F.FiniteAdoption()
        owner, native, result = fixture.prepared(budget)
        with owner:
            expected = fixture.adopt(budget, owner, native, result)
            with L.construction(scope, budget=budget):
                proposal = fixture.propose(owner)
            self.assertIs(type(proposal._encoded), CompactRecord)
            self.assertEqual(proposal.proposal_id, native.proposal_id)
            actual = fixture.adopt(budget, owner, proposal, result)
            self.assertEqual(snapshot(actual.transport), snapshot(expected.transport))
            self.assertIs(actual.finite_proposal, proposal)
            working, stocks = proposal._transport_inputs()
            with L.construction(scope, budget=budget), F.threadpool_limits(1), F.PreparedSpatialTransport(
                    working, budget=budget) as operator:
                compact_result = operator.advance(stocks, state_id='spatial-parent', source_stage_id='source',
                    max_projection_errors={name: Q(1, 10**11) for name in F.NAMES}, nonnegative_fields=F.POSITIVE)
            del working, stocks, operator
            self.assertIsInstance(compact_result.record(), RecordRef)
            self.assertEqual(compact_result.result_id, result.result_id)
            # A whole proposal decode would violate this consumer contract.
            with proposal.record() as public, proposal.graph() as graph:
                complete_ids = (proposal.proposal_id, public.identity().sha256, graph.identity().sha256)
            with compact_result.record() as public:
                complete_ids += (public.identity().sha256,)
                for name in ('exact_input_stocks', 'exact_stocks', 'binary_stock_projection_accounts'):
                    with public.field(name) as fields:
                        complete_ids += (fields.identity().sha256,)
            original_export = RecordRef.export
            def bounded_export(ref, **kwargs):
                self.assertNotIn(ref.identity().sha256, complete_ids)
                return original_export(ref, **kwargs)
            with patch.object(RecordRef, 'export', bounded_export):
                again = fixture.adopt(budget, owner, proposal, compact_result)
            self.assertEqual(snapshot(again.transport), snapshot(expected.transport))
            del actual, expected, again, proposal, native, result, compact_result
        del owner
        gc.collect(); scope.close()
        self.assertEqual(budget.reserved_bytes, 0)

    def test_foreign_scope_and_escaped_row_remain_owned(self):
        budget = WorkBudget(32 << 20)
        other_budget = WorkBudget(32 << 20)
        first = scope_for(budget, process_epoch='collar-first')
        second = scope_for(other_budget, process_epoch='collar-second')
        a, b = pack(F.physical_graph(), first), pack(F.physical_graph(), second)
        with LC.record_access(a.root(), budget) as left, LC.record_access(b.root(), other_budget) as right:
            with self.assertRaisesRegex(ValueError, 'one shared retained scope'):
                LC.same_scope(left, right)
            row = left['cells'][0]
        del left, right
        before = budget.reserved_bytes
        self.assertEqual(row['cell_id'], 'physical')
        del row
        self.assertLess(budget.reserved_bytes, before)
        a.close(); b.close(); first.close(); second.close()
        self.assertEqual(budget.reserved_bytes, 0)
        self.assertEqual(other_budget.reserved_bytes, 0)

    def test_finite_changed_fields_refuse_and_failure_owners_remain_paid(self):
        budget = WorkBudget(64 << 20)
        scope = scope_for(budget, process_epoch='live-collar-failure')
        fixture = F.FiniteAdoption()
        owner, native, result = fixture.prepared(budget)
        with owner:
            with L.construction(scope, budget=budget):
                proposal = fixture.propose(owner)
            before = budget.reserved_bytes
            held = []
            try:
                fixture.adopt(budget, owner, proposal, result, registry='changed registry')
            except F.TectonicsError as error:
                self.assertEqual(str(error), F.REFUSED)
                held.append(error.__traceback__)
            else:
                self.fail('changed finite registry accepted')
            self.assertGreater(budget.reserved_bytes, before)
            with self.assertRaises(RuntimeError):
                proposal._encoded.close()
            held.clear(); gc.collect()
            self.assertEqual(budget.reserved_bytes, before)
            for changes in (dict(layout=F.physical_graph(3)), dict(source_id='other'), dict(registry=None)):
                with self.assertRaises(F.TectonicsError):
                    fixture.adopt(budget, owner, proposal, result, **changes)
            del proposal, native, result
        del owner
        gc.collect(); scope.close()
        self.assertEqual(budget.reserved_bytes, 0)

    def test_prefix_comparison_all_fields_rows_and_source_unchanged(self):
        budget = WorkBudget(32 << 20)
        scope = scope_for(budget, process_epoch='live-collar-prefix')
        original = dict(F.physical_graph(), provenance={'unchanged': ['evidence']*16})
        extended = deepcopy(original)
        extended['finite_inventory'] = {'registry_id': 'registry'}
        extended['cells'].append(dict(cell_id='supply', kind='inventory'))
        extended['transfers'].append(dict(face_id='supply-face'))
        body, physical = pack(extended, scope), pack(original, scope)
        with LC.record_access(body.root(), budget) as view, LC.record_access(physical.root(), budget) as geometry:
            self.assertTrue(LC.extension_matches(view, geometry))
            self.assertTrue(LC.extension_matches(view, original))
            self.assertEqual([row['kind'] for row in LC.inventory_tail(view['cells'], 1)], ['inventory'])
            for changed in (dict(original, extra='unexpected'), dict(original, source='changed'),
                            dict(original, cells=[dict(original['cells'][0], end_volume_m3=['0x3', '0x1'])])):
                self.assertFalse(LC.extension_matches(view, changed))
            self.assertEqual(view['cells'][0], original['cells'][0])
        with body.root() as ref, ref.export(max_logical_bytes=1 << 20, max_owned_bytes=4 << 20) as unchanged:
            self.assertEqual(unchanged.value, extended)
        del view, geometry
        body.close(); physical.close(); scope.close()
        self.assertEqual(budget.reserved_bytes, 0)

    def test_actual_common_collar_graph_transport_heat_and_endpoint_parity(self):
        import mesh_tables as M
        from threadpoolctl import threadpool_limits
        with threadpool_limits(1), FLOW.actual_spatial_fixture() as case:
            budget, collar = case['budget'], case['collar']
            scope = scope_for(budget, process_epoch='live-collar-common')
            initial = FLOW.thermal_mesh(case, case['wall'], 'start')
            with FLOW.PreparedSpatialOwner(case['funding'], collar, case['bounds'], initial,
                    method='implicit-upwind', max_projection_errors=FLOW.allowances(case), budget=budget) as owner:
                parent = collar.initial_state_from_funding(case['funding'], case['owner'])
                route = SimpleNamespace(exterior_state=owner.initial_state,
                    source_flow_stage=lambda duration, _collar=collar, _parent=parent, **kw:
                        _collar.source_flow_stage(_parent, duration, **kw))
                source, bounds, mesh, wall = FLOW.next_interval(case, route)
                graph = owner.close_graph(owner.initial_state, source, bounds)
                step = owner.transport(owner.initial_state, source, graph)
                heat = owner.heat(step, mesh)
                ordinary = native_method('transport_from_spatial')(collar, source, step.result, graph, method='implicit-upwind')
                old_heat = native_method('heat_from_spatial')(collar, ordinary, heat, mesh)
                expected = collar.endpoint_from_transport(ordinary, old_heat)
                record = graph.record()
                with L.construction(scope, budget=budget):
                    compact_graph = A._issue(A.SpatialALEGraph, record, budget)
                    compact_step = owner.transport(owner.initial_state, source, graph)
                self.assertEqual(compact_step.result.result_id, step.result.result_id)
                blobs = {}
                metadata, arrays = M.pack_mesh(mesh.record(), support_writer=blobs.__setitem__, budget=budget)
                view = M.CompactMesh(metadata, arrays, support_reader=lambda identity, size, _blobs=blobs: _blobs[identity],
                    expected_geometry_id=mesh.geometry_id, budget=budget, scope=scope)
                compact_mesh = E.ExteriorMesh.from_compact(view, budget=budget)
                with compact_step.result.record() as public:
                    self.assertIsInstance(public, RecordRef)
                    complete_ids = [public.identity().sha256, compact_graph.geometry_id]
                    for name in ('exact_input_stocks', 'exact_stocks', 'binary_stock_projection_accounts'):
                        with public.field(name) as fields:
                            complete_ids.append(fields.identity().sha256)
                original_export = RecordRef.export
                def bounded_export(ref, **kwargs):
                    self.assertNotIn(ref.identity().sha256, complete_ids)
                    return original_export(ref, **kwargs)
                with patch.object(RecordRef, 'export', bounded_export):
                    adopted = collar.transport_from_spatial(source, compact_step.result, compact_graph, method='implicit-upwind')
                    actual_heat = collar.heat_from_spatial(adopted, heat, compact_mesh)
                actual = collar.endpoint_from_transport(adopted, actual_heat)
                self.assertEqual(snapshot(adopted.transport), snapshot(ordinary.transport))
                self.assertEqual(snapshot(actual_heat.heat), snapshot(old_heat.heat))
                self.assertEqual(snapshot(actual.state.fields), snapshot(expected.state.fields))
                self.assertEqual(actual.state.result_id, expected.state.result_id)
                self.assertEqual(compact_graph.geometry_id, graph.geometry_id)
                del actual, actual_heat, adopted, compact_mesh, view, metadata, arrays, blobs, compact_graph, compact_step
                del ordinary, old_heat, expected, source, bounds, mesh, wall, graph, step, heat, parent, route, record
            del owner, initial
            gc.collect(); scope.close()
            case.clear()
        del collar, case
        gc.collect()
        self.assertEqual(budget.reserved_bytes, 0)


if __name__ == '__main__':
    unittest.main()
