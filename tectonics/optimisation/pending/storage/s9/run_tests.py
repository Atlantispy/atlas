"""Run one S9 test module against base or candidate private_heat_indexed_runtime: run_tests.py base|new MODULE."""
import sys, unittest
from pathlib import Path
HERE = Path(__file__).resolve().parent
C = Path('C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10/fidelity-integration-20261005/'
         'continuation-repair-20261013/optimisation-20261014/resumability-r1/compact-geometry-r1')
first = HERE/'base' if sys.argv[1] == 'base' else HERE
sys.path[:0] = [str(first), str(C), str(HERE)]
if 'test_ram_context_indexed_patch' in sys.argv[2:]:
    # Harness shim = the integrated layout: the bundle ships the runtime file that is loaded.
    import test_private_heat_bundle_extended as BX
    _original = BX._helper_source
    BX._helper_source = lambda name: (first/name).read_bytes() if (first/name).is_file() else _original(name)
suite = unittest.defaultTestLoader.loadTestsFromNames(sys.argv[2:])
result = unittest.TextTestRunner(verbosity=1).run(suite)
for module in ('private_heat_indexed_runtime', 'mesh_tables', sys.argv[2]):
    if module in sys.modules:
        print('loaded', module, sys.modules[module].__file__)
sys.exit(not result.wasSuccessful())
