"""Item 21 mutants: test_width_gate's tests against a mutated width_gate.

Usage (run by item21_wg_mutants.py): python -B item21_wg_mutant_tests.py <mutant-file>
The mutant file is loaded as width_gate before the test module imports that name; every other
module resolves from the resumability folder three levels up. Exit 0 only if every test passes.
"""
import importlib.util
import sys
import unittest
from pathlib import Path

RESUMABILITY = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(RESUMABILITY))
spec = importlib.util.spec_from_file_location('width_gate', sys.argv[1])
assert spec is not None and spec.loader is not None
gate = importlib.util.module_from_spec(spec)
sys.modules['width_gate'] = gate
spec.loader.exec_module(gate)

import test_width_gate as T  # noqa: E402

assert T.G is gate, 'the tests must import the mutant'
suite = unittest.defaultTestLoader.loadTestsFromTestCase(T.WidthGateTests)
result = unittest.TextTestRunner(stream=sys.stderr, verbosity=0, failfast=True).run(suite)
print(result.testsRun, 'tests run')
sys.exit(0 if result.wasSuccessful() else 1)
