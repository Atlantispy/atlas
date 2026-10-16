"""Step 8 actual finite/dual parity and ownership; no physical acceptance."""
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
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
TASK = HERE.parents[4]
BASE = HERE.parents[1]/'runtime-integration-r1'/'runtime-src'/'atlas_tectonics'
H = TASK/'fidelity-integration-20261005'/'heat-repair-20261007'
BASE_HASHES = {
    'integration_spatial_reservoir.py': 'eb0946367aac5b9cee7ae3f735f8a96142f92548c88ec5940820cf91c85c2d9c',
    'integration_dual_geometry.py': 'a48347c0f1d49f3f9d4a745700a553c5b7c2ea17a24e7faec566c09c91e90e69',
    'integration_spatial_transport.py': '70cdfc9a5b0a4e6b518f6354550fc2a23b333a0474c07dfac55f670cdffde230',
    'integration_spatial_ale.py': 'f52e1d27f515b9c5d6f2de37762c46cd146c418ca3e4fb0244b121ccf5df3015',
    'integration_differential_geometry.py': '7d93bae4aef24b1124a05930a49a921662aff9aa36d4995ab62fac2bd19b1034',
}


def setUpModule():
    global _temporary, _old_path, LF, LIVE, RESERVOIR, DUAL, TRANSPORT, F, DF, ALE, DIFFERENTIAL
    global WorkBudget, RecordCodec, RecordRef, CompactRecord, create_retained_scope
    if any(name == 'atlas_tectonics' or name.startswith('atlas_tectonics.') for name in sys.modules):
        raise RuntimeError('fresh process required; no live runtime patching')
    for name, expected in BASE_HASHES.items():
        if sha256((BASE/name).read_bytes()).hexdigest() != expected:
            raise RuntimeError('finite fixture baseline source changed: '+name)
    _temporary = tempfile.TemporaryDirectory(prefix='lf-', dir=TASK/'_t')
    package = Path(_temporary.name)/'atlas_tectonics'
    shutil.copytree(BASE, package, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    _old_path = list(sys.path)
    sys.path[:0] = [str(Path(_temporary.name)), str(H/'source'/'tectonics'/'tests'),
                   str(HERE.parent), str(H)]
    LF = importlib.import_module('live_finite_patch')
    LIVE = importlib.import_module('live_spatial_patch')
    for name, transform in (
            ('integration_spatial_ale.py', LIVE.ale_source),
            ('integration_spatial_transport.py', LIVE.transport_source),
            ('integration_spatial_reservoir.py', LF.reservoir_source),
            ('integration_dual_geometry.py', LF.dual_source),
            ('integration_differential_geometry.py', LIVE.differential_source)):
        path = package/name
        path.write_text(transform(path.read_text()), encoding='utf8')
    RESERVOIR = importlib.import_module('atlas_tectonics.integration_spatial_reservoir')
    DUAL = importlib.import_module('atlas_tectonics.integration_dual_geometry')
    TRANSPORT = importlib.import_module('atlas_tectonics.integration_spatial_transport')
    ALE = importlib.import_module('atlas_tectonics.integration_spatial_ale')
    DIFFERENTIAL = importlib.import_module('atlas_tectonics.integration_differential_geometry')
    WorkBudget = importlib.import_module('atlas_tectonics.resources').WorkBudget
    RecordCodec = importlib.import_module('record_tables').RecordCodec
    views = importlib.import_module('record_views')
    RecordRef, CompactRecord = views.RecordRef, views.CompactRecord
    create_retained_scope = importlib.import_module('content_cache').create_retained_scope
    F = importlib.import_module('test_integration_spatial_reservoir')
    DF = importlib.import_module('test_integration_dual_geometry')


def tearDownModule():
    sys.path[:] = _old_path
    assert Path(_temporary.name).resolve().parent == (TASK/'_t').resolve()
    _temporary.cleanup()


def pack(value, scope):
    return RecordCodec().pack_record(value, record_schema='atlas.live-finite-fixture.v1', scope=scope, check=lambda: None)


def exported(ref):
    return ref.export(max_logical_bytes=4 << 20, max_owned_bytes=32 << 20)


def definition_node(source, name, class_name=None):
    body = ast.parse(source).body
    if class_name:
        body = next(node for node in body if isinstance(node, ast.ClassDef) and node.name == class_name).body
    return next(node for node in body if isinstance(node, ast.FunctionDef) and node.name == name)


class FiniteTests(unittest.TestCase):
    def setUp(self):
        self.budget = WorkBudget(64 << 20)
        self.scope = create_retained_scope(self.budget, process_epoch='live-finite-test')

    def tearDown(self):
        gc.collect()
        self.scope.close()
        self.assertEqual(self.budget.reserved_bytes, 0)

    def test_source_bound_numerical_bodies_and_duplicate_refusal(self):
        for name, transform in (('integration_spatial_reservoir.py', LF.reservoir_source),
                                ('integration_dual_geometry.py', LF.dual_source)):
            raw = (BASE/name).read_bytes()
            self.assertEqual(sha256(raw).hexdigest(), BASE_HASHES[name])
            source = raw.decode().replace('\r\n', '\n')
            changed = transform(source)
            with self.assertRaises(ValueError):
                transform(changed)
            if name == 'integration_dual_geometry.py':
                old = definition_node(source, 'physical_record')
                new = definition_node(changed, 'physical_record')
                for node in ast.walk(new):
                    if isinstance(node, ast.Call) and ast.unparse(node.func) == 'LIVE_FINITE.dual_copy':
                        node.func = ast.Name(id='deepcopy', ctx=ast.Load())
                self.assertEqual(ast.dump(old), ast.dump(new))
            else:
                old = definition_node(source, 'prepare', 'PreparedFiniteStocks')
                new = definition_node(changed, '_prepare_live', 'PreparedFiniteStocks')
                new.name = old.name
                for node in ast.walk(new):
                    if isinstance(node, ast.UnaryOp) and ast.unparse(node) == 'not LIVE_SPATIAL.is_record(physical_graph)':
                        node.operand = ast.Compare(left=ast.Call(func=ast.Name(id='type', ctx=ast.Load()),
                            args=[ast.Name(id='physical_graph', ctx=ast.Load())], keywords=[]),
                            ops=[ast.Is()], comparators=[ast.Name(id='dict', ctx=ast.Load())])
                # Compare guard-normalised text: the only physical prepare
                # change is accepting the validated scoped record accessor.
                expected = ast.unparse(old).replace('type(physical_graph) is not dict', 'not type(physical_graph) is dict')
                self.assertEqual(expected, ast.unparse(new))
                self.assertEqual(ast.dump(definition_node(source, '_finished_record', 'PreparedFiniteStocks')),
                                 ast.dump(definition_node(changed, '_finished_record', 'PreparedFiniteStocks')))

    def test_detach_only_mutable_rows_and_keep_provenance_owned(self):
        original = dict(F.geometry(1, 2), provenance={'method': 'unchanged', 'rows': ['a'*1024]*3})
        record = pack(original, self.scope)
        ref = record.root()
        result = LF.clone_mutable(ref, ('cells', 'transfers'), budget=self.budget)
        self.assertIsInstance(result['provenance'], RecordRef)
        result['cells'][0]['cell_id'] = 'private working change'
        with exported(ref) as saved:
            self.assertEqual(saved.value, original)
        with self.assertRaises(RuntimeError):
            record.close()
        del result
        ref.close(); record.close()

    def test_actual_prepare_transport_finish_exact_identity_and_output(self):
        from threadpoolctl import threadpool_limits
        physical = dict(zip(F.NAMES, ((Q(3),), (Q(6),), (Q(1),)), strict=True))
        graph = dict(F.geometry(1, 2), provenance={'unchanged': ['source evidence']*8})
        pristine = deepcopy(graph)
        with RESERVOIR.PreparedFiniteStocks('one-decode', [F.row('source', 'source', 1, 2, -3, 4)],
                field_names=F.NAMES, nonnegative_fields=F.POSITIVE, budget=self.budget) as owner:
            state = owner.initial()
            native = owner.prepare(state, graph, physical, [F.edge('source', 'supply', 1)], source_stage_id='finite source')
            expected_proposal = native.record()
            native_result, native_state = F.solve(owner, native, self.budget)
            expected_result, expected_state = native_result.record(), native_state.record()
            original = pack(graph, self.scope)
            ref = original.root()
            proposal = owner.prepare(state, ref, physical, [F.edge('source', 'supply', 1)], source_stage_id='finite source')
            # Step 8: unchanged graph fields stay borrowed from the live graph
            # record; only mutated rows and the proposal's own fields are packed.
            import live_composite
            self.assertIs(type(proposal._encoded), live_composite.LiveRecord)
            self.assertEqual(proposal._encoded.imports.count, 0)
            with proposal._encoded.root() as body, body.field('graph') as borrowed_graph, \
                    borrowed_graph.field('provenance') as provenance:
                self.assertIs(provenance._view, original)
            self.assertEqual(proposal.proposal_id, native.proposal_id)
            proposal_ref = proposal.record()
            with exported(proposal_ref) as actual:
                self.assertEqual(actual.value, expected_proposal)
            with LIVE.access(proposal_ref) as p:
                working, stocks = proposal._transport_inputs()
                with LIVE.construction(self.scope, budget=self.budget), threadpool_limits(1), \
                        TRANSPORT.PreparedSpatialTransport(working, budget=self.budget) as operator:
                    result = operator.advance(stocks, state_id=p['transport_parent_id'],
                        source_stage_id=p['source_stage_id'], max_projection_errors={k: Q(1, 10**12) for k in F.NAMES},
                        nonnegative_fields=F.POSITIVE)
                del working, stocks, operator
            proposal_ref.close()
            new_state = owner.finish(proposal, result)
            self.assertTrue(LIVE.is_transport_snapshot(result._snapshot))
            with result.record() as result_ref, exported(result_ref) as actual:
                self.assertEqual(actual.value, expected_result)
            self.assertEqual(new_state.record(), expected_state)
            for name in result._snapshot.array_names:
                self.assertEqual(result._snapshot.array(name).tobytes(), native_result._snapshot.array(name).tobytes())
            with exported(ref) as unchanged:
                self.assertEqual(unchanged.value, pristine)
            self.assertEqual(graph, pristine)
            del proposal, proposal_ref, result, new_state, native, native_result, native_state, state
            ref.close(); original.close()
        del owner, p

    def test_dual_physical_record_exact_output_and_source_unchanged(self):
        data = dict(DF.geometry(DF.cell('a', (9, 11), (10, 10)), exchanges=[DF.exchange(1)]),
                    schema='fixture.only', provenance={'original': ['untouched']*12})
        before = deepcopy(data)
        booked, errors = {'a': Q(100)}, {'a': (Q(0), Q(2))}
        finite = DF.finite(DF.stock('source', 2, 6))
        options = dict(geometric_starts={'a': Q(9)}, finite_measures={
            'source': dict(geometric_start_m3=Q(2), material_quadrature_m3=Q(6))})
        expected, expected_material = DUAL.physical_record(data, booked, errors, finite, **options)
        record = pack(data, self.scope)
        ref = record.root()
        actual, material = DUAL.physical_record(ref, booked, errors, finite, **options)
        self.assertIsInstance(actual['provenance'], RecordRef)
        self.assertEqual(material, expected_material)
        result = pack(dict(actual), self.scope)
        result_ref = result.root()
        with exported(result_ref) as decoded:
            self.assertEqual(decoded.value, expected)
        with exported(ref) as unchanged:
            self.assertEqual(unchanged.value, before)
        self.assertEqual(data, before)
        del actual
        result_ref.close(); result.close(); ref.close(); record.close()

    def test_prepare_failure_remains_paid_until_traceback_release(self):
        physical = dict(zip(F.NAMES, ((Q(3),), (Q(6),), (Q(1),)), strict=True))
        held = []
        with RESERVOIR.PreparedFiniteStocks('failure', [F.row('source', 'source', 1, 2, -3, 4)],
                field_names=F.NAMES, nonnegative_fields=F.POSITIVE, budget=self.budget) as owner:
            record = pack(F.geometry(1, 2), self.scope)
            ref = record.root()
            baseline = self.budget.reserved_bytes
            try:
                owner.prepare(owner.initial(), ref, physical, [F.edge('source', 'invalid', 1)], source_stage_id='failure')
            except Exception as error:
                self.assertIn('direction disagrees', str(error))
                held.append(error.__traceback__)
            else:
                self.fail('invalid finite exchange accepted')
            self.assertGreater(self.budget.reserved_bytes, baseline)
            with self.assertRaises(RuntimeError):
                record.close()
            held.clear(); gc.collect()
            self.assertEqual(self.budget.reserved_bytes, baseline)
            ref.close(); record.close()
        del owner

    def test_actual_typed_differential_closure_through_mutable_copy(self):
        with RESERVOIR.PreparedFiniteStocks('registry', [DF.stock('source', 2, 1)],
                field_names=('material_quadrature_m3',), nonnegative_fields=('material_quadrature_m3',),
                budget=self.budget) as owner:
            state = owner.initial()
            data = dict(DF.geometry(DF.cell('a', (0, 0), (2, 2)), exchanges=[DF.exchange(2)]),
                physical_geometry_family='differential-plate-component-partition-v1',
                component_registry_id='registry', finite_owner_id=owner.owner_id, finite_state_id=state.state_id,
                provenance={'complete': ['unchanged physical evidence']*8})
            pristine = deepcopy(data)
            for dual in (False, True):
                options = dict(budget=self.budget, geometry_volume_errors={})
                if dual:
                    options['material_quadrature_m3'] = {'a': Q(0)}
                native_bounds = ALE._issue(ALE.SpatialALEBounds, data, self.budget)
                native_graph = DIFFERENTIAL.close_differential_ale(native_bounds, {'a': Q(0)}, state, **options)
                expected = native_graph.record()
                with LIVE.construction(self.scope, budget=self.budget):
                    bounds = ALE._issue(ALE.SpatialALEBounds, data, self.budget)
                seen = []
                original_clone = LF.clone_mutable
                def observed(value, fields, *, budget):
                    copied = original_clone(value, fields, budget=budget)
                    if isinstance(LIVE.reference(value), RecordRef):
                        self.assertIsInstance(copied['provenance'], RecordRef)
                        seen.append(tuple(fields))
                    return copied
                with patch.object(LF, 'clone_mutable', observed):
                    graph = DIFFERENTIAL.close_differential_ale(bounds, {'a': Q(0)}, state, **options)
                self.assertTrue(seen)
                self.assertIs(type(graph), ALE.SpatialALEGraph)
                # Step 8: the closed graph borrows the live bounds content it
                # keeps unchanged instead of re-importing it into a second DAG.
                import live_composite
                self.assertIs(type(graph._json), live_composite.LiveRecord)
                self.assertEqual(graph._json.imports.count, 0)
                overrides = graph._json._ref._owner.value[5]
                self.assertIn('provenance', overrides)
                self.assertTrue(all(child._view is bounds._json for child in overrides.values()))
                self.assertEqual(graph.geometry_id, native_graph.geometry_id)
                result_ref, bounds_ref = graph.record(), bounds.record()
                with exported(result_ref) as result, exported(bounds_ref) as original:
                    self.assertEqual(result.value, expected)
                    self.assertEqual(original.value, pristine)
                self.assertEqual(data, pristine)
                result_ref.close(); bounds_ref.close()
                del graph, bounds, native_graph, native_bounds
            del state
        del owner


if __name__ == '__main__':
    unittest.main()
