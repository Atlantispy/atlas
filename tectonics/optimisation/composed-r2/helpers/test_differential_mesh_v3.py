"""Actual fresh native wrapper from the compact packaging seam; no solver."""
import gc
import importlib
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

import exterior_mesh_patch
import mimetic_patch

HERE = Path(__file__).resolve().parent
TASK = HERE.parents[4]
BASE = HERE.parents[1]/'runtime-integration-r1'
_temporary = None
_old_path = None


def setUpModule():
    global _temporary, _old_path
    if any(name == 'atlas_tectonics' or name.startswith('atlas_tectonics.') for name in sys.modules):
        raise RuntimeError('fresh process required; no live runtime patching')
    _temporary = tempfile.TemporaryDirectory(prefix='mesh-producer-', dir=TASK/'_t')
    package = Path(_temporary.name)/'atlas_tectonics'
    shutil.copytree(BASE/'runtime-src'/'atlas_tectonics', package,
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    for name, transform in (('integration_exterior_mesh.py', exterior_mesh_patch.transform),
                            ('integration_mimetic_heat.py', mimetic_patch.mimetic_source)):
        target = package/name
        target.write_text(transform(target.read_text(encoding='utf8')), encoding='utf8')
    _old_path = list(sys.path)
    sys.path[:0] = [str(Path(_temporary.name)), str(BASE/'ram'), str(BASE/'helpers'),
                   str(HERE.parent), str(HERE.parents[3]/'heat-repair-20261007')]
    importlib.import_module('atlas_tectonics.integration_exterior_mesh')


def tearDownModule():
    if _old_path is not None:
        sys.path[:] = _old_path
    if _temporary is not None:
        _temporary.cleanup()


class FreshMeshV3Tests(unittest.TestCase):
    def test_missing_and_malformed_context_refused(self):
        import differential_mesh_patch as P
        for context in (None, {}, {'resolver': None, 'support_source': None, 'producer': 'b'*64}):
            with self.subTest(context=context), self.assertRaises(ValueError):
                P.produce({}, budget=None, context=context)

    def test_produce_actual_compact_wrapper_native_identity_and_metric_seal(self):
        from atlas_tectonics import integration_differential_mesh as D
        from atlas_tectonics.integration_exterior_mesh import ExteriorMesh
        from atlas_tectonics.integration_mimetic_heat import MimeticGeometry
        from atlas_tectonics.resources import WorkBudget
        from content_cache import create_retained_scope
        from interval_store_set import IntervalStoreSet
        import differential_mesh_patch as P
        import mesh_tables as M
        import private_heat_indexed_runtime as I
        from test_mesh_v3 import fixture
        budget = WorkBudget(1 << 30)
        scope = create_retained_scope(budget, process_epoch='fresh-native-mesh')
        path = Path(_temporary.name)/'store'; path.mkdir()
        stores = IntervalStoreSet.create_migration(path/'catalog.json', workflow_id='a'*64, scope=scope)
        candidate = stores.begin_interval(None, producer_identity='b'*64, runtime_identity='c'*64)
        old, record, source, partition, _ = fixture(scope, candidate, count=1)
        from hashlib import sha256
        expected = sha256(D._encode_mesh_record(record)).hexdigest()
        with self.assertRaisesRegex(ValueError, 'explicit resolver'):
            P.produce(record, budget=budget, context=None)
        issued = P.produce(record, budget=budget,
            context=dict(resolver=candidate, support_source=source, producer='b'*64))
        self.assertIs(type(issued), ExteriorMesh)
        self.assertIsNone(issued._json)
        self.assertEqual(issued.geometry_id, expected)
        self.assertIsNotNone(issued._compact.scope)
        view = issued._compact
        with self.assertRaises(RuntimeError):
            view.close()
        metric = MimeticGeometry.from_compact(view, budget=budget)
        del issued
        gc.collect()
        with self.assertRaises(RuntimeError):
            view.close()
        with patch.object(M.CompactMesh, 'iter_legacy_json', side_effect=AssertionError('second full stream')):
            self.assertEqual(I.metric_identity(metric), expected)
            self.assertEqual(I.metric_identity(metric), expected)
        del metric
        gc.collect(); view.close()
        source.close(); partition.close()
        del view, old, record
        candidate.close(); stores.close(); gc.collect(); scope.close()
        self.assertEqual(budget.reserved_bytes, 0, budget.statistics())


if __name__ == '__main__':
    unittest.main()
