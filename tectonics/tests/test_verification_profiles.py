"""Developer profile topology, without executing a second scientific sweep."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import Mock, call, patch


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('focused_verification_profile', ROOT / 'verify.py')
profile = importlib.util.module_from_spec(spec)
spec.loader.exec_module(profile)


def selected(*names):
    tests = []
    for name in names:
        test = unittest.FunctionTestCase(lambda: None)
        test.id = lambda name=name: name
        tests.append(test)
    return unittest.TestSuite(tests)


def ids(selection):
    return {name for group in selection.values() for name in group}


class ProfileSelectionTests(unittest.TestCase):
    def test_exact_scopes_are_explicit_developer_selections(self):
        self.assertEqual(profile.FOCUSED_PATTERNS, {
            'i01': 'test_i01_*.py', 'i02': 'test_i02_*.py',
            'i02-quick': 'test_i02_*.py', 'i02-measurement': 'test_i02_*.py',
            'regional3d': 'test_regional*3d.py',
        })

    def test_real_i02_partition_is_complete_disjoint_and_keeps_fast_fault_controls(self):
        # Discovery imports definitions only: no harness, fixture or solve runs.
        full, full_selection = profile.focused_suite('i02')
        quick, quick_selection = profile.focused_suite('i02-quick')
        measurement, measurement_selection = profile.focused_suite('i02-measurement')
        full_ids, quick_ids, measurement_ids = map(ids, (full_selection, quick_selection, measurement_selection))
        self.assertEqual(measurement_ids, profile.I02_MEASUREMENT_TESTS)
        self.assertEqual(len(measurement_ids), 4)
        self.assertFalse(quick_ids & measurement_ids)
        self.assertEqual(quick_ids | measurement_ids, full_ids)
        self.assertEqual(full.countTestCases(), quick.countTestCases() + measurement.countTestCases())
        self.assertIn('test_i02_joined.TimingHarnessTests.test_a_run_that_fails_an_equality_check_withholds_every_timing', quick_ids)
        self.assertIn('test_i02_measurement.ComparisonTests.test_missing_extra_nonfinite_and_wrong_shape_results_are_refused', quick_ids)

    def test_real_i01_and_regional3d_include_every_matching_module(self):
        for name in ('i01', 'regional3d'):
            with self.subTest(profile=name):
                suite, selection = profile.focused_suite(name)
                selected_ids = ids(selection)
                modules = {path.stem for path in (ROOT / 'tests').glob(profile.FOCUSED_PATTERNS[name])}
                self.assertEqual({test.split('.')[0] for test in selected_ids}, modules)
                self.assertEqual(suite.countTestCases(), len(selected_ids))
        self.assertIn('test_regional_solver_selection3d', modules)
        self.assertIn('test_regional_evolution3d', modules)
        self.assertIn('test_regional_heat3d', modules)

    def test_unknown_names_and_options_refuse_without_discovery(self):
        with patch.object(profile.unittest, 'TestLoader', side_effect=AssertionError('unexpected discovery')), \
                patch.object(unittest.defaultTestLoader, 'discover', side_effect=AssertionError('broad fallback')):
            with self.assertRaisesRegex(ValueError, 'unknown focused'):
                profile.focused_suite('i03')
            with self.assertRaisesRegex(ValueError, 'unknown verification'):
                profile.verification_suite('--i03')

    def test_empty_and_duplicate_discovery_refuse(self):
        for group in (selected(), selected('same', 'same')):
            loader = Mock(errors=[], discover=Mock(return_value=group))
            with patch.object(profile.unittest, 'TestLoader', return_value=loader):
                with self.assertRaisesRegex(ValueError, 'empty or duplicated'):
                    profile.focused_suite('i01')

    def test_import_errors_cannot_disappear_into_a_filtered_partition(self):
        loader = Mock(errors=['synthetic import error'], discover=Mock(return_value=selected('failed')))
        with patch.object(profile.unittest, 'TestLoader', return_value=loader):
            with self.assertRaisesRegex(ValueError, 'discovery failed.*synthetic import error'):
                profile.focused_suite('i02-measurement')

    def test_each_stale_measurement_member_refuses_both_partitions(self):
        for missing in profile.I02_MEASUREMENT_TESTS:
            for name in ('i02-quick', 'i02-measurement'):
                with self.subTest(missing=missing, profile=name):
                    group = selected(*(profile.I02_MEASUREMENT_TESTS - {missing}), 'ordinary-test')
                    loader = Mock(errors=[], discover=Mock(return_value=group))
                    with patch.object(profile.unittest, 'TestLoader', return_value=loader):
                        with self.assertRaisesRegex(ValueError, 'stale or incomplete'):
                            profile.focused_suite(name)

    def test_empty_quick_partition_refuses(self):
        loader = Mock(errors=[], discover=Mock(return_value=selected(*profile.I02_MEASUREMENT_TESTS)))
        with patch.object(profile.unittest, 'TestLoader', return_value=loader):
            with self.assertRaisesRegex(ValueError, 'empty focused verification partition'):
                profile.focused_suite('i02-quick')

    def test_default_native_and_acceptance_keep_full_discovery_and_native_checks(self):
        for option in ('', '--native', '--acceptance'):
            with self.subTest(option=option), patch.object(unittest.defaultTestLoader, 'discover',
                    side_effect=lambda _root, pattern: selected(pattern)) as discover:
                suite, selection = profile.verification_suite(option)
            self.assertIsNone(selection)
            self.assertEqual(suite.countTestCases(), 2)
            self.assertEqual(discover.call_args_list, [
                call(str(ROOT / 'tests'), pattern='test_*.py'),
                call(str(ROOT / 'tests'), pattern='check_native_transport.py'),
            ])

    def test_core_remains_foundations_only(self):
        with patch.object(unittest.defaultTestLoader, 'discover', return_value=selected('core')) as discover:
            suite, selection = profile.verification_suite('--core')
        self.assertEqual(suite.countTestCases(), 1)
        self.assertIsNone(selection)
        discover.assert_called_once_with(str(ROOT / 'tests'), pattern='test_foundations.py')

    def test_existing_acceptance_profiles_keep_their_exact_selectors(self):
        for name in ('w01', 'w04', 'w05', 'w06'):
            expected = (selected(name), {name: [name]})
            with self.subTest(profile=name), patch.object(profile, name + '_suite', return_value=expected) as select, \
                    patch.object(unittest.defaultTestLoader, 'discover', side_effect=AssertionError('broad fallback')):
                self.assertIs(profile.verification_suite('--' + name), expected)
            select.assert_called_once_with()

    def test_new_profiles_do_not_append_full_native_checks(self):
        for name in profile.FOCUSED_PATTERNS:
            expected = (selected(name), {name: [name]})
            with self.subTest(profile=name), patch.object(profile, 'focused_suite', return_value=expected) as select, \
                    patch.object(unittest.defaultTestLoader, 'discover', side_effect=AssertionError('broad fallback')):
                self.assertIs(profile.verification_suite('--' + name), expected)
            select.assert_called_once_with(name)

    def test_direct_controls_run_once_and_multigrid_inherits_only_default_contracts(self):
        import test_regional_execution3d as reference
        import test_regional_multigrid3d as multigrid
        loader = unittest.TestLoader()
        default = set(loader.getTestCaseNames(reference.RegionalExecution3DTests))
        direct = set(loader.getTestCaseNames(reference.DirectGmresRegionalExecution3DTests))
        candidate = set(loader.getTestCaseNames(multigrid.MultigridRegionalExecution3DTests))
        self.assertEqual(direct, {
            'test_si_rescaling_and_direct_gmres_agree',
            'test_same_si_problem_under_any_scales_matches_or_refuses',
            'test_mis_scaled_solves_never_publish_a_wrong_field',
            'test_load_dominated_state_resolves_the_small_driving_velocity',
            'test_weak_region_rows_are_judged_by_their_own_magnitudes',
            'test_badly_scaled_contrast_is_refined_not_refused',
            'test_unconverged_refinement_correction_is_judged_not_discarded',
            'test_declared_mean_pressure_changes_pressure_not_velocity',
        })
        self.assertEqual(len(default), 18)
        self.assertEqual(candidate, default)
        self.assertFalse(default & direct)
        self.assertEqual(len(default | direct), 26)


if __name__ == '__main__':
    unittest.main()
