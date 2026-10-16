"""S2 r9 harness (run_tests_r8.py with a fail-closed seed check): run_tests_r9.py FOLDERS MODULE... (FOLDERS, ";"-separated, first on sys.path, then the composed helpers,
diagnostic-captures and composed runtime source, as run_tests.py did). Prints the file each module loaded from."""
import os
import sys
import unittest
from pathlib import Path

if sys.flags.hash_randomization != 0:
    raise SystemExit('refusing: the string-hash seed is not 0 (run without -I or -E, with PYTHONHASHSEED=0)')

T = Path(__file__).resolve().parents[3]
R = T/'fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1'
TMP = T/'so'/'tmp'
folders = [str(Path(item).resolve()) for item in sys.argv[1].split(os.pathsep)]
sys.path[:0] = folders+[str(R/'composed-r2'/'helpers'), str(R/'diagnostic-captures'), str(R/'composed-r2'/'src')]
os.environ.setdefault('SO_R', str(R))
os.environ.setdefault('SO_TMP', str(TMP))
TMP.mkdir(exist_ok=True)
suite = unittest.defaultTestLoader.loadTestsFromNames(sys.argv[2:])
result = unittest.TextTestRunner(verbosity=1).run(suite)
for module in ('compact_restart_patch', 'ledger_fresh_interval', 'capture_store', 'storage_zstd_backend',
               'compact_restart_store', 'test_ledger_fresh_interval', 'test_wp16_preadvance'):
    if module in sys.modules:
        print('loaded', module, getattr(sys.modules[module], '__file__', None))
sys.exit(not result.wasSuccessful())
