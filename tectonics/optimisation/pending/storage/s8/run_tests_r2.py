"""Run S8 tests (rebased onto RF c36ad987) against base or candidate reader sources: run_tests.py base|new MODULE..."""
import sys, unittest
from pathlib import Path
HERE = Path(__file__).resolve().parent
R = Path('C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10/fidelity-integration-20261005/'
         'continuation-repair-20261013/optimisation-20261014/resumability-r1')
first = HERE/'r2'/'base' if sys.argv[1] == 'base' else HERE/'r2'
sys.path[:0] = [str(first), str(R), str(R/'compact-geometry-r1'), str(R.parent/'runtime-integration-r1'/'runtime-src')]
suite = unittest.defaultTestLoader.loadTestsFromNames(sys.argv[2:])
result = unittest.TextTestRunner(verbosity=1).run(suite)
for module in ('reopen_prepared_restart', 'reopen_fresh_restart', 'content_cache', 'run_prepared_restart'):
    if module in sys.modules:
        print('loaded', module, sys.modules[module].__file__)
sys.exit(not result.wasSuccessful())
