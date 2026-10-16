"""Fresh-process actual imports/metrics for the combined private source only.

No historical endpoint, compatibility permit or real heat solve is issued.
The heat control is the existing two-cell numerical fixture.

Adapted for the v2 composer (W3): construct() now takes the reviewed-inputs
document instead of ad hoc pins, and composes the complete helper and RAM sets
itself, so the predecessor's I/ram, I/helpers and historical H roots are no
longer put on sys.path (M13: no H root). The checks themselves are unchanged.
"""
import importlib
from pathlib import Path
import sys
import tempfile
import unittest

import assemble_resumable as A


class ComposedGeometryImport(unittest.TestCase):
    def test_actual_indexed_metrics_heat_and_filter_package_together(self):
        if any(k == 'atlas_tectonics' or k.startswith('atlas_tectonics.') for k in sys.modules):
            self.fail('fresh process required; no running runtime replacement')
        document, _ = A.reviewed_document()
        composition = A.construct(document)
        saved_path = list(sys.path)
        # Short task-local path prevents Windows extension MAX_PATH failures.
        with tempfile.TemporaryDirectory(prefix='combined-metric-', dir=A.WORKSPACE) as temporary:
            root = Path(temporary)
            try:
                for name, raw in {**composition.native, **composition.helpers, **composition.ram}.items():
                    target = root/name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with target.open('xb') as stream:
                        stream.write(raw)
                # The compact-geometry directory supplies only the fixture module.
                sys.path[:0] = [str(root), str(A.HERE/'compact-geometry-r1')]
                fixture = importlib.import_module('test_mimetic_indexed')
                for alias, name in (('B', 'integration_volume_bounds'),
                                    ('E', 'integration_exterior_mesh'),
                                    ('V', 'integration_volume'),
                                    ('M', 'integration_mimetic_heat')):
                    setattr(fixture, alias, importlib.import_module('atlas_tectonics.'+name))
                fixture.WorkBudget = importlib.import_module('atlas_tectonics.resources').WorkBudget
                fixture.TectonicsError = importlib.import_module('atlas_tectonics._validation').TectonicsError
                for name in ('integration_filtered_predicates', 'integration_exact_gmp',
                             'integration_endpoint_checkpoints', 'integration_component_volume_auto'):
                    module = importlib.import_module('atlas_tectonics.'+name)
                    self.assertTrue(Path(module.__file__).resolve().is_relative_to(root))
                # Reuse the exact fixtures; no independent full suite duplicate.
                checks = ('test_exact_metrics_and_operator_match_without_full_expansion',
                          'test_arbitrary_precision_thin_positive_cells_remain_exact',
                          'test_failed_validation_retains_charges_while_traceback_is_held')
                for name in checks:
                    with self.subTest(check=name):
                        getattr(fixture.IndexedMimetic(name), name)()
                for name, raw in composition.helpers.items():
                    self.assertEqual((root/name).read_bytes(), raw)
                for name, pin in document['files'].items():
                    self.assertEqual(A.digest((A.HERE/name).read_bytes()), pin)
            finally:
                sys.path[:] = saved_path
                # The process is a test only; release imported module globals
                # before Windows tries to remove the owned temporary tree.
                for key, module in tuple(sys.modules.items()):
                    filename = getattr(module, '__file__', None)
                    if filename and Path(filename).resolve().is_relative_to(root):
                        del sys.modules[key]


if __name__ == '__main__':
    unittest.main()
