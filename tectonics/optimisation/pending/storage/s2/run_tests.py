"""Run S2 tests against base or candidate sources: run_tests.py base|new MODULE..."""
import os, sys, unittest
from pathlib import Path
HERE = Path(__file__).resolve().parent
R = Path('C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10/fidelity-integration-20261005/'
         'continuation-repair-20261013/optimisation-20261014/resumability-r1')
variant = sys.argv[1]
first = [str(HERE/'base')] if variant == 'base' else [str(HERE)]
sys.path[:0] = first + [str(R/'composed-r2'/'helpers'), str(R/'diagnostic-captures'), str(R/'composed-r2'/'src')]
os.environ.setdefault('SO_R', str(R))
os.environ.setdefault('SO_TMP', str(HERE.parent/'tmp'))
(HERE.parent/'tmp').mkdir(exist_ok=True)
suite = unittest.defaultTestLoader.loadTestsFromNames(sys.argv[2:])
result = unittest.TextTestRunner(verbosity=1).run(suite)
for module in ('compact_restart_patch', 'ledger_fresh_interval', 'capture_store', 'storage_zstd_backend',
               'atlas_tectonics', 'test_ledger_fresh_interval'):
    if module in sys.modules:
        print('loaded', module, getattr(sys.modules[module], '__file__', None))
sys.exit(not result.wasSuccessful())
