"""Caller and typed-capability controls; no material/geometry solve or claim."""
import ast
from copy import deepcopy
import gc
import importlib
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest

import continuation_transfer as C


HERE = Path(__file__).resolve().parent
INTEGRATION = HERE.parent/'runtime-integration-r1'
PACKAGE = INTEGRATION/'runtime-src/atlas_tectonics'
HEAT = HERE.parents[2]/'heat-repair-20261007'
JOINED = HEAT/'source/tectonics/tests/i04_differential_joined_control.py'
_temporary = None


def setUpModule():
    global _temporary
    import native_transfer as N
    import spatial_transfer as S
    import geometry_transfer as G
    import test_spatial_transfer as TS
    import test_geometry_transfer_integration as TG
    if any(k == 'atlas_tectonics' or k.startswith('atlas_tectonics.') for k in sys.modules):
        raise RuntimeError('clean process required; no loaded implementation replacement')
    _temporary = tempfile.TemporaryDirectory(prefix='ct-', dir=HERE)
    package = Path(_temporary.name)/'atlas_tectonics'
    shutil.copytree(PACKAGE, package, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    for name, transform in (('regional_execution.py', N.retained_snapshot_source),
            ('integration_spatial_owner.py', S.spatial_owner_source),
            ('integration_differential_geometry.py', G.transform),
            ('integration_differential_coupling.py', C.coupling_source)):
        path = package/name
        path.write_text(transform(path.read_text(encoding='utf8')), encoding='utf8')
    sys.path[:0] = [str(Path(_temporary.name)), str(INTEGRATION/'ram'), str(INTEGRATION/'helpers'),
                   str(HEAT), str(HEAT/'source/tectonics/tests')]
    TS.F = importlib.import_module('test_i04_regional_owner')
    TS.C = importlib.import_module('atlas_tectonics.regional_collar3d')
    TS.P = importlib.import_module('atlas_tectonics.integration_spatial_owner')
    TS.Snapshot = importlib.import_module('atlas_tectonics.regional_execution').RegionalMechanicalSnapshot
    TS.WorkBudget = importlib.import_module('atlas_tectonics.resources').WorkBudget
    TS.Registry = importlib.import_module('atlas_tectonics.integration_regional_inventory').ComponentRegistry
    TS.enc = importlib.import_module('atlas_tectonics.integration_mimetic_heat')._enc
    TS.TectonicsError = importlib.import_module('atlas_tectonics._validation').TectonicsError
    TG.D = importlib.import_module('atlas_tectonics.integration_differential_geometry')


def tearDownModule():
    if _temporary is not None:
        _temporary.cleanup()


class RemovePlumbing(ast.NodeTransformer):
    """Erase precisely the new capability plumbing, not numerical code."""
    def visit_ImportFrom(self, node):
        return None if node.module == 'continuation_transfer' else node

    def visit_Assign(self, node):
        if (len(node.targets) == 1 and isinstance(node.targets[0], ast.Attribute)
                and node.targets[0].attr == '_runtime_transfer'):
            return None
        return self.generic_visit(node)

    def visit_If(self, node):
        if (isinstance(node.test, ast.Compare) and isinstance(node.test.left, ast.Name)
                and node.test.left.id == '_runtime_transfer'):
            return None
        return self.generic_visit(node)

    def visit_arguments(self, node):
        pairs = [(arg, default) for arg, default in zip(node.kwonlyargs, node.kw_defaults, strict=True)
                 if arg.arg != '_runtime_transfer']
        node.kwonlyargs = [arg for arg, _ in pairs]
        node.kw_defaults = [default for _, default in pairs]
        return self.generic_visit(node)

    def visit_Call(self, node):
        node.keywords = [row for row in node.keywords if row.arg != '_runtime_transfer']
        return self.generic_visit(node)


class SourceTests(unittest.TestCase):
    def test_whole_default_program_ast_unchanged_after_exact_plumbing_removed(self):
        for path, transform in ((PACKAGE/'integration_differential_coupling.py', C.coupling_source),
                                (JOINED, C.joined_control_source)):
            original = path.read_text(encoding='utf8')
            changed = transform(original)
            compile(changed, '<proposed-caller>', 'exec')
            restored = RemovePlumbing().visit(ast.parse(changed))
            self.assertEqual(ast.dump(ast.parse(original)), ast.dump(restored))
            with self.assertRaises(C.ContinuationTransferRefused):
                transform(changed)
            with self.assertRaises(C.ContinuationTransferRefused):
                transform(original+'\n# changed source\n')

    def test_actual_propose_partition_call_forwards_same_typed_capability(self):
        source = C.coupling_source((PACKAGE/'integration_differential_coupling.py').read_text(encoding='utf8'))
        cls = next(n for n in ast.parse(source).body if isinstance(n, ast.ClassDef) and n.name == 'PreparedDifferentialIteration')
        method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'propose')
        call = next(n for n in ast.walk(method) if isinstance(n, ast.Call) and
                    isinstance(n.func, ast.Attribute) and n.func.attr == 'prepare_interval_partition')
        # Dispatch-only control: compile the actual call expression, without
        # constructing a fake physical driver, iteration or scientific result.
        invoke = ast.Expression(body=call)
        ast.fix_missing_locations(invoke)
        token, parent = object(), object()
        state = SimpleNamespace(_parent_partition=parent, _funding=object(), _sphere=object(),
            _collar=object(), _finite=object(), _max_components=8192, _budget=object(), _runtime_transfer=token)
        captured = []
        def receive(*args, **kwargs):
            captured.append((args, kwargs))
        namespace = dict(G=SimpleNamespace(prepare_interval_partition=receive), self=state, interval=object())
        eval(compile(invoke, '<actual-caller>', 'eval'), namespace)
        self.assertIs(captured[0][0][0], parent)
        self.assertIs(captured[0][1]['_runtime_transfer'], token)
        self.assertEqual(captured[0][1]['max_components'], 8192)
        state._runtime_transfer = None
        eval(compile(invoke, '<actual-default-caller>', 'eval'), namespace)
        self.assertIsNone(captured[1][1]['_runtime_transfer'])

    def test_default_no_capability_is_no_added_work_and_forged_workflow_refuses(self):
        self.assertIsNone(C.select_parent_transfer(None, None, None, None, None))
        self.assertIsNone(C.parent_geometry_transfer(object(), None))
        with self.assertRaises(C.ContinuationTransferRefused):
            C.parent_geometry_transfer(SimpleNamespace(_migration=object()), None)

    def test_fresh_process_contract_preserves_original_token_and_forbids_pickled_owners(self):
        text = ' '.join(C.FRESH_PROCESS_REOPEN_CONTRACT)
        self.assertIn('authenticated ORIGINAL reader token', text)
        self.assertIn('never pickle live plans', text)
        self.assertIn('fresh WorkBudget', text)


class TypedCapabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import test_spatial_transfer as TS
        TS.SpatialTransferTests.setUpClass()
        cls.budget = TS.SpatialTransferTests.budget

    @classmethod
    def tearDownClass(cls):
        import test_spatial_transfer as TS
        TS.SpatialTransferTests.tearDownClass()
        TS.SpatialTransferTests.collar = TS.SpatialTransferTests.native = None
        TS.SpatialTransferTests.old = TS.SpatialTransferTests.current = None
        gc.collect()
        if cls.budget.reserved_bytes:
            raise AssertionError(cls.budget.statistics())

    def test_actual_old_parent_and_current_plan_descendant_selection(self):
        import spatial_transfer as S
        import geometry_transfer as G
        import test_spatial_transfer as TS
        import test_geometry_transfer_integration as TG
        fixture = TS.SpatialTransferTests('test_old_root_restore_remains_strict')
        fixture.setUp()
        spatial = None
        try:
            with S.admit_migrated_spatial_owner(**fixture.args) as lease:
                spatial = lease.adopt()
            interval, record = TG.synthetic_geometry_and_partition(spatial=spatial,
                collar=fixture.collar, native_transfer=fixture.native_owned, budget=self.budget)
            bridge = G.bind_parent_geometry(native_transfer=fixture.native_owned,
                partition_descriptor=record, geometry=interval, funding=spatial.funding,
                collar=fixture.collar, budget=self.budget)
            partition = TG.D.DifferentialPartition.restore(record, spatial.funding, fixture.collar,
                interval, budget=self.budget, _runtime_transfer=bridge)
            original = partition.descriptor()
            self.assertIs(C.select_parent_transfer(partition, spatial.funding, fixture.collar,
                                                  self.budget, bridge), bridge)
            self.assertEqual(partition.descriptor(), original)
            with self.assertRaises(C.ContinuationTransferRefused):
                C.select_parent_transfer(partition, spatial.funding, fixture.collar, self.budget, object())
            with self.assertRaises(C.ContinuationTransferRefused):
                C.select_parent_transfer(partition, object(), fixture.collar, self.budget, bridge)
            # Explicit synthetic archive for the CURRENT plan. Actual restorer
            # accepts it under strict normal binding; no old-plan alias needed.
            current_record = TG.rehash_partition(dict(deepcopy(record), collar_plan_id=fixture.collar.plan_id))
            current = TG.D.DifferentialPartition.restore(current_record, spatial.funding,
                fixture.collar, interval, budget=self.budget)
            self.assertIsNone(C.select_parent_transfer(current, spatial.funding, fixture.collar,
                                                       self.budget, bridge))
            self.assertEqual(fixture.collar._native.statistics()['accepted_intervals'], 0)
            del interval, bridge, partition, current
        finally:
            if spatial is not None:
                spatial.owner.close()
            spatial = None
            gc.collect()
            fixture.tearDown()


if __name__ == '__main__':
    unittest.main(verbosity=2)
