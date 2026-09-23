"""Focused W06 profile selection and status controls, no second physics sweep."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('w06_verification_profile',
    Path(__file__).resolve().parents[1]/'verify.py')
profile = importlib.util.module_from_spec(spec)
spec.loader.exec_module(profile)


class AcceptanceStatus(unittest.TestCase):
    def test_named_routes_and_scope(self):
        result = profile.w06_acceptance_record(True)
        self.assertEqual(result['status'], 'PASS_SUPPORTED_W06_WORKFLOW')
        self.assertTrue(result['supported_workflow_accepted'])
        self.assertEqual(result['routes'], ['constant_ocean', 'history_ocean', 'inherited_margin'])
        self.assertIn('without completed thermal solves', result['numerical_methods']['recovery'])
        self.assertIn('unchanged W06 Steps 2-4', result['component_evidence'])
        for key in ('field_validated', 'whole_terrain_accepted', 'production_ready'):
            self.assertFalse(result[key])
        self.assertEqual(result['R4_4_status'], 'HELD_INCOMPLETE')

    def test_failure_skip_empty_and_drift_cannot_pass(self):
        case = unittest.FunctionTestCase(lambda: None)
        for kind in ('failure', 'error', 'skip', 'empty', 'drift'):
            result = unittest.TestResult(); result.testsRun = 0 if kind == 'empty' else 1
            if kind == 'failure': result.failures.append((case, 'failure'))
            if kind == 'error': result.errors.append((case, 'error'))
            if kind == 'skip': result.skipped.append((case, 'skip'))
            passed = profile._checks_passed(result, kind != 'drift')
            self.assertFalse(passed)
            self.assertEqual(profile.w06_acceptance_record(passed)['status'], 'FAIL_OR_INCOMPLETE')

    def test_exact_nonempty_selection_without_discovery(self):
        names = tuple(name for group in profile.W06_GATES.values() for name in group)
        self.assertEqual(names, ('test_w06_workflow', 'test_execution_reuse.IdentityTests',
                                 'test_w06_acceptance_profile'))
        class Selected(unittest.TestCase):
            def __init__(self, name): super().__init__(); self.name = name
            def id(self): return self.name
            def runTest(self): pass
        with patch.object(unittest.defaultTestLoader, 'loadTestsFromNames',
                side_effect=lambda group: unittest.TestSuite(Selected(name) for name in group)), \
                patch.object(unittest.defaultTestLoader, 'discover', side_effect=AssertionError('broad discovery')):
            suite, gates = profile.w06_suite()
        self.assertEqual(suite.countTestCases(), 3)
        self.assertEqual(tuple(name for group in gates.values() for name in group), names)
        for invalid in (unittest.TestSuite(), unittest.TestSuite([Selected('x'), Selected('x')])):
            with patch.object(unittest.defaultTestLoader, 'loadTestsFromNames', return_value=invalid):
                with self.assertRaisesRegex(ValueError, 'empty or duplicated W06'):
                    profile.w06_suite()


if __name__ == '__main__':
    unittest.main()
