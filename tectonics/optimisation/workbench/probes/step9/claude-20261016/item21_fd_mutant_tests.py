"""Item 21 mutants: test_fresh_interval_driver's wiring tests against a mutated fresh_interval_driver.

Usage (run by item21_fd_mutants.py): python -B item21_fd_mutant_tests.py <mutant-file>
The mutant file is loaded as fresh_interval_driver before the test module imports that name; every
other module resolves from the resumability folder three levels up. Exit 0 only if every test passes.
"""
import importlib.util
import sys
import unittest
from pathlib import Path

RESUMABILITY = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(RESUMABILITY))
spec = importlib.util.spec_from_file_location('fresh_interval_driver', sys.argv[1])
assert spec is not None and spec.loader is not None
driver = importlib.util.module_from_spec(spec)
sys.modules['fresh_interval_driver'] = driver
spec.loader.exec_module(driver)

import test_fresh_interval_driver as T  # noqa: E402

assert T.F is driver, 'the tests must import the mutant'
suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(case)
                           for case in (T.WiringTests, T.MeasurementHookTests))
result = unittest.TextTestRunner(stream=sys.stderr, verbosity=0, failfast=True).run(suite)
print(result.testsRun, 'tests run')
sys.exit(0 if result.wasSuccessful() else 1)
