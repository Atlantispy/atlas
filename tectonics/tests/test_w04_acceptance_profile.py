"""W04 selection and acceptance status cannot silently broaden or pass missing gates."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location('w04_verification_profile',
    Path(__file__).resolve().parents[1] / 'verify.py')
profile = importlib.util.module_from_spec(spec)
spec.loader.exec_module(profile)


class AcceptanceStatus(unittest.TestCase):
    def test_pass_accepts_only_supported_stationary_planar_workflow(self):
        record = profile.w04_acceptance_record(True)
        self.assertEqual(record['status'], 'PASS_SUPPORTED_STATIONARY_PLANAR_1D_W04')
        self.assertIs(record['supported_workflow_accepted'], True)
        self.assertIn('stationary planar 1D', record['scope'])
        self.assertEqual(set(record['numerical_methods']),
            {'uniform_periodic', 'uniform_finite', 'variable_rigidity'})
        self.assertIn('finite-difference', record['numerical_methods']['uniform_periodic'])
        self.assertIn('Continuous', record['numerical_methods']['uniform_finite'])
        self.assertIn('mesh-change', record['numerical_methods']['variable_rigidity'])
        assumptions = ' '.join(record['assumptions'])
        for phrase in ('fixed in time', 'K is positive and constant',
                       'exact declared exterior loads', 'finite resolution',
                       'not rigorous continuum-error bounds'):
            self.assertIn(phrase, assumptions)
        for name in ('whole_terrain_accepted', 'field_validated', 'production_ready'):
            self.assertIs(record[name], False)
        self.assertEqual(record['R4_4_status'], 'HELD_INCOMPLETE')
        self.assertEqual(record['other_stage_acceptance'], 'UNCHANGED_NOT_DECIDED_BY_W04')
        self.assertTrue(record['unsupported_not_passed'])

    def test_failure_error_skip_empty_or_source_drift_cannot_pass(self):
        test = unittest.FunctionTestCase(lambda: None)
        success = unittest.TestResult(); success.testsRun = 1
        self.assertTrue(profile._checks_passed(success, True))
        cases = []
        failure = unittest.TestResult(); failure.testsRun = 1
        failure.failures.append((test, 'synthetic failure')); cases.append((failure, True))
        error = unittest.TestResult(); error.testsRun = 1
        error.errors.append((test, 'synthetic error')); cases.append((error, True))
        skipped = unittest.TestResult(); skipped.testsRun = 1
        skipped.skipped.append((test, 'synthetic skip')); cases.append((skipped, True))
        cases.extend(((unittest.TestResult(), True), (success, False)))
        for result, unchanged in cases:
            with self.subTest(result=result, unchanged=unchanged):
                passed = profile._checks_passed(result, unchanged)
                self.assertFalse(passed)
                record = profile.w04_acceptance_record(passed)
                self.assertEqual(record['status'], 'FAIL_OR_INCOMPLETE')
                self.assertIs(record['supported_workflow_accepted'], False)

    def test_exact_explicit_selection_rejects_empty_duplicate_and_discovery_fallback(self):
        names = tuple(name for group in profile.W04_GATES.values() for name in group)
        expected = (
            'test_w04_column_loads', 'test_foundations.FlexureTests',
            'test_w04_finite_region', 'test_w04_variable_flexure',
            'test_w04_acceptance', 'test_w04_load_reuse',
            'test_w04_workflow.W04WorkflowTests.test_surface_requires_correct_cells_complete_water_and_explicit_shapes',
            'test_w04_workflow.W04WorkflowTests.test_policy_ownership_periodic_scope_and_old_water_bath_stiffness_refuse',
            'test_w04_workflow.W04WorkflowTests.test_finite_capacity_and_linear_validity_limits_refuse',
            'test_w04_workflow.W04WorkflowTests.test_changed_source_datum_and_loaded_callable_refuse',
            'test_w04_regional_workflow.W04RegionalWorkflowTests.test_unknown_surroundings_gate_displacement_and_derivative_validity',
            'test_w04_variable_workflow.W04VariableWorkflowTests.test_source_profile_shape_frame_and_uncertainty_refuse',
            'test_w04_acceptance_profile',
        )
        self.assertEqual(names, expected)
        self.assertEqual(len(names), len(set(names)))

        class SelectedTest(unittest.TestCase):
            def __init__(self, name):
                super().__init__(); self.name = name
            def id(self):
                return self.name
            def runTest(self):
                pass

        def selected(group):
            return unittest.TestSuite(SelectedTest(name) for name in group)

        # Verify loader topology without importing or running the physical suites.
        with patch.object(unittest.defaultTestLoader, 'loadTestsFromNames', side_effect=selected) as load, \
                patch.object(unittest.defaultTestLoader, 'discover', side_effect=AssertionError('unbounded fallback')):
            suite, gates = profile.w04_suite()
        self.assertEqual(suite.countTestCases(), len(expected))
        self.assertEqual(tuple(name for group in gates.values() for name in group), expected)
        self.assertEqual(load.call_count, len(profile.W04_GATES))
        for invalid in (unittest.TestSuite(), unittest.TestSuite([SelectedTest('same'), SelectedTest('same')])):
            with patch.object(unittest.defaultTestLoader, 'loadTestsFromNames', return_value=invalid):
                with self.assertRaisesRegex(ValueError, 'empty or duplicated W04'):
                    profile.w04_suite()


if __name__ == '__main__':
    unittest.main()
