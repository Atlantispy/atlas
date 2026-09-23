"""The W05 profile must not imply broader science, or pass skipped/empty work."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location('w05_verification_profile',
    Path(__file__).resolve().parents[1]/'verify.py')
profile = importlib.util.module_from_spec(spec)
spec.loader.exec_module(profile)


class AcceptanceStatus(unittest.TestCase):
    def test_pass_is_only_supported_dry_prescribed_case(self):
        record = profile.w05_acceptance_record(True)
        self.assertEqual(record['status'], 'PASS_SUPPORTED_DRY_LISTRIC_1D_W05')
        self.assertTrue(record['supported_workflow_accepted'])
        for phrase in ('Prescribed dry', 'constant-density', 'planar 1D', 'uniform elastic'):
            self.assertIn(phrase, record['scope'])
        self.assertEqual(set(record['numerical_methods']), {'motion', 'support', 'independent_reference'})
        self.assertIn('full crop', record['numerical_methods']['independent_reference'])
        for name in ('field_validated', 'whole_terrain_accepted', 'production_ready'):
            self.assertIs(record[name], False)
        self.assertEqual(record['R4_4_status'], 'HELD_INCOMPLETE')
        self.assertEqual(record['other_stage_acceptance'], 'UNCHANGED_NOT_DECIDED_BY_W05')
        self.assertTrue(record['empirical_challenge'].startswith('PENDING_'))

    def test_failure_skip_empty_and_drift_cannot_pass(self):
        test = unittest.FunctionTestCase(lambda: None)
        success = unittest.TestResult(); success.testsRun = 1
        self.assertTrue(profile._checks_passed(success, True))
        for kind in ('failure', 'error', 'skip', 'empty', 'drift'):
            result = unittest.TestResult(); result.testsRun = 0 if kind == 'empty' else 1
            if kind == 'failure': result.failures.append((test, 'synthetic failure'))
            if kind == 'error': result.errors.append((test, 'synthetic error'))
            if kind == 'skip': result.skipped.append((test, 'synthetic skip'))
            passed = profile._checks_passed(result, kind != 'drift')
            self.assertFalse(passed)
            self.assertEqual(profile.w05_acceptance_record(passed)['status'], 'FAIL_OR_INCOMPLETE')

    def test_explicit_bounded_selection_no_discovery_fallback(self):
        names = tuple(name for group in profile.W05_GATES.values() for name in group)
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(set(profile.W05_GATES), {'independent_reference_controls',
            'characteristic_kinematics_and_accounts', 'single_owner_load_support_and_envelopes',
            'combined_frozen_case', 'atomic_recovery_and_verified_reuse', 'acceptance_status_contract'})
        for name in names:
            self.assertTrue(name.startswith('test_w05_'))
        for name in ('test_w05_acceptance', 'test_w05_workflow', 'test_w05_support',
                     'test_w05_reference', 'test_w05_support_reference', 'test_w05_acceptance_profile'):
            self.assertIn(name, names)
        self.assertIn('test_w05_extension.W05ExtensionTests.test_separate_existing_ale_uniform_dilation', names)

        class SelectedTest(unittest.TestCase):
            def __init__(self, name):
                super().__init__(); self.name = name
            def id(self): return self.name
            def runTest(self): pass

        with patch.object(unittest.defaultTestLoader, 'loadTestsFromNames',
                side_effect=lambda group: unittest.TestSuite(SelectedTest(name) for name in group)), \
                patch.object(unittest.defaultTestLoader, 'discover', side_effect=AssertionError('broad fallback')):
            suite, gates = profile.w05_suite()
        self.assertEqual(suite.countTestCases(), len(names))
        self.assertEqual(tuple(name for group in gates.values() for name in group), names)
        for invalid in (unittest.TestSuite(), unittest.TestSuite([SelectedTest('same'), SelectedTest('same')])):
            with patch.object(unittest.defaultTestLoader, 'loadTestsFromNames', return_value=invalid):
                with self.assertRaisesRegex(ValueError, 'empty or duplicated W05'):
                    profile.w05_suite()


if __name__ == '__main__':
    unittest.main()
