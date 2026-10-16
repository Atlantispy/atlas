"""The measured slow-test registry and --quick: a developer selection that never broadens or stands in for the gate."""
import importlib.util
import math
import sys
from pathlib import Path
from types import MappingProxyType
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('quick_verification_profile', ROOT / 'verify.py')
profile = importlib.util.module_from_spec(spec)
spec.loader.exec_module(profile)


def selected(*names):
    tests = []
    for name in names:
        test = unittest.FunctionTestCase(lambda: None)
        test.id = lambda name=name: name
        tests.append(test)
    return unittest.TestSuite(tests)


def ids(suite):
    return [test.id() for test in suite]


SYNTHETIC = MappingProxyType({
    'test_i01_alpha.SlowTests.test_long': 75.0,       # one test
    'test_i01_beta.HeavyFixture': 140.0,              # a whole class (its setUpClass dominates)
})
DISCOVERED = ('test_i01_alpha.SlowTests.test_long', 'test_i01_alpha.SlowTests.test_short',
              'test_i01_alpha.FastTests.test_a', 'test_i01_beta.HeavyFixture.test_x',
              'test_i01_beta.HeavyFixture.test_y', 'test_i01_beta.Light.test_z')


class QuickPartitionTests(unittest.TestCase):
    def test_measurement_partitions_validate_the_original_discovery(self):
        measurement = sorted(profile.I02_MEASUREMENT_TESTS)
        slow = 'test_i02_workflow.InspectionTests.test_invalid_requests_change_nothing'
        names = measurement + [slow, 'test_i02_other.Fast.test_short']
        loader = Mock(errors=[])
        loader.discover.side_effect = lambda *a, **kw: selected(*names)
        registry = MappingProxyType({slow: 65.2, measurement[0]: 40.0})
        with patch.object(profile, 'SLOW_TESTS', registry), \
                patch.object(profile.unittest, 'TestLoader', return_value=loader):
            suite, selection = profile.verification_suite('--i02-measurement', quick=True)
            self.assertEqual(ids(suite), measurement[1:])
            self.assertEqual(selection['omitted_slow'], measurement[:1])
            suite, selection = profile.verification_suite('--i02-quick', quick=True)
            self.assertEqual(ids(suite), ['test_i02_other.Fast.test_short'])
            self.assertEqual(selection['omitted_slow'], [slow])
            with patch.object(profile, 'SLOW_TESTS', MappingProxyType({'test_i02_other.Gone.test_x': 50.0})):
                with self.assertRaisesRegex(ValueError, 'stale'):
                    profile.verification_suite('--i02-measurement', quick=True)

    def test_quick_omits_exactly_the_registered_tests_and_classes(self):
        with patch.object(profile, 'SLOW_TESTS', SYNTHETIC):
            kept, omitted = profile.quick_partition(list(selected(*DISCOVERED)), ('test_i01_*.py',))
        self.assertEqual(ids(kept), ['test_i01_alpha.SlowTests.test_short', 'test_i01_alpha.FastTests.test_a',
                                     'test_i01_beta.Light.test_z'])
        self.assertEqual(omitted, ['test_i01_alpha.SlowTests.test_long', 'test_i01_beta.HeavyFixture.test_x',
                                   'test_i01_beta.HeavyFixture.test_y'])

    def test_a_stale_test_id_refuses(self):
        stale = MappingProxyType(dict(SYNTHETIC, **{'test_i01_alpha.SlowTests.test_renamed': 90.0}))
        with patch.object(profile, 'SLOW_TESTS', stale):
            with self.assertRaisesRegex(ValueError, 'slow-test registry is stale.*test_renamed'):
                profile.quick_partition(list(selected(*DISCOVERED)), ('test_i01_*.py',))

    def test_a_stale_class_id_refuses(self):
        stale = MappingProxyType(dict(SYNTHETIC, **{'test_i01_beta.GoneFixture': 90.0}))
        with patch.object(profile, 'SLOW_TESTS', stale):
            with self.assertRaisesRegex(ValueError, 'slow-test registry is stale.*GoneFixture'):
                profile.quick_partition(list(selected(*DISCOVERED)), ('test_i01_*.py',))

    def test_a_module_or_partial_name_is_not_a_registry_entry(self):
        for entry in ('test_i01_alpha', 'test_i01_alpha.Slow', 'test_i01_alpha.SlowTests.test_lon'):
            with self.subTest(entry=entry), patch.object(profile, 'SLOW_TESTS', MappingProxyType({entry: 90.0})):
                with self.assertRaisesRegex(ValueError, 'slow-test registry is stale'):
                    profile.quick_partition(list(selected(*DISCOVERED)), ('test_i01_*.py',))

    def test_entries_outside_the_selected_patterns_are_not_judged(self):
        other = MappingProxyType(dict(SYNTHETIC, **{'test_w05_gamma.Heavy': 200.0}))
        with patch.object(profile, 'SLOW_TESTS', other):
            kept, omitted = profile.quick_partition(list(selected(*DISCOVERED)), ('test_i01_*.py',))
        self.assertEqual(len(kept) + len(omitted), len(DISCOVERED))

    def test_an_empty_quick_partition_refuses(self):
        everything = MappingProxyType({'test_i01_alpha.SlowTests': 80.0, 'test_i01_alpha.FastTests': 80.0,
                                       'test_i01_beta.HeavyFixture': 80.0, 'test_i01_beta.Light': 80.0})
        with patch.object(profile, 'SLOW_TESTS', everything):
            with self.assertRaisesRegex(ValueError, 'empty quick'):
                profile.quick_partition(list(selected(*DISCOVERED)), ('test_i01_*.py',))

    def test_quick_focused_selection_discovers_once_and_filters(self):
        loader = Mock(errors=[], discover=Mock(return_value=selected(*DISCOVERED)))
        with patch.object(profile, 'SLOW_TESTS', SYNTHETIC), \
                patch.object(profile.unittest, 'TestLoader', return_value=loader):
            suite, selection = profile.verification_suite('--i01', quick=True)
        self.assertEqual(ids(suite), selection['i01'])
        self.assertEqual(len(selection['i01']), 3)
        self.assertEqual(len(selection['omitted_slow']), 3)

    def test_quick_full_selection_keeps_native_checks_and_omits_only_registered_tests(self):
        def discover(_root, pattern):
            return selected(*DISCOVERED) if pattern == 'test_*.py' else selected('check_native_transport.Native.test_n')
        with patch.object(profile, 'SLOW_TESTS', SYNTHETIC), \
                patch.object(unittest.defaultTestLoader, 'discover', side_effect=discover):
            suite, selection = profile.verification_suite('', quick=True)
        self.assertIn('check_native_transport.Native.test_n', ids(suite))
        self.assertEqual(len(ids(suite)), len(DISCOVERED) - 3 + 1)

    def test_full_patterns_are_exactly_what_the_full_run_discovers(self):
        # Tools (run_tests_parallel's default selection) read FULL_PATTERNS; it must not drift from the full run.
        patterns = []
        with patch.object(unittest.defaultTestLoader, 'discover',
                          side_effect=lambda _root, pattern: patterns.append(pattern) or selected(pattern)):
            profile.verification_suite('')
        self.assertEqual(tuple(patterns), profile.FULL_PATTERNS)

    def test_the_full_run_is_unchanged_by_the_registry(self):
        def discover(_root, pattern):
            return selected(*DISCOVERED) if pattern == 'test_*.py' else selected('check_native_transport.Native.test_n')
        with patch.object(profile, 'SLOW_TESTS', SYNTHETIC), \
                patch.object(unittest.defaultTestLoader, 'discover', side_effect=discover):
            suite, selection = profile.verification_suite('')
        self.assertIsNone(selection)
        self.assertEqual(suite.countTestCases(), len(DISCOVERED) + 1)

    def test_a_quick_run_never_reports_the_gate_status(self):
        self.assertEqual(profile.run_status(True, quick=True), 'PASS_QUICK_SELECTION_ONLY')
        self.assertEqual(profile.run_status(False, quick=True), 'FAIL_OR_INCOMPLETE')
        self.assertEqual(profile.run_status(True), 'PASS_MATHEMATICAL_TESTS_ONLY')

    def test_a_quick_profile_name_cannot_collide_with_an_existing_profile(self):
        self.assertEqual(profile.profile_name('i02', quick=True), 'quick:i02')
        self.assertEqual(profile.profile_name('i02'), 'i02')
        for name in profile.FOCUSED_PATTERNS:
            self.assertNotIn(profile.profile_name(name, quick=True), profile.FOCUSED_PATTERNS)


class QuickOptionTests(unittest.TestCase):
    def test_main_refuses_release_before_any_suite_or_w10_delegation(self):
        reuse = Mock(__file__=str(ROOT/'src/atlas_tectonics/reuse.py'))
        reuse.require_strict_execution.side_effect = ValueError('strict execution required')
        package = Mock(__file__=str(ROOT/'src/atlas_tectonics/__init__.py'), reuse=reuse)
        for option in ('--core', '--w10'):
            with self.subTest(option=option), patch.object(sys, 'argv', ['verify.py', option]), \
                    patch.object(sys, 'path', list(sys.path)), patch.object(sys, 'dont_write_bytecode', True), \
                    patch.dict(sys.modules, {'atlas_tectonics': package, 'numpy': Mock()}), \
                    patch.object(profile, 'source_inventory', return_value={}), \
                    patch.object(profile, 'verification_suite') as suite:
                with self.assertRaisesRegex(ValueError, 'strict execution'):
                    profile.main()
                suite.assert_not_called()

    def test_quick_combines_only_with_the_full_or_a_focused_selection(self):
        self.assertEqual(profile.parse_options(['--quick']), ('', True))
        self.assertEqual(profile.parse_options(['--quick', '--i02']), ('--i02', True))
        self.assertEqual(profile.parse_options(['--regional3d', '--quick']), ('--regional3d', True))
        self.assertEqual(profile.parse_options([]), ('', False))
        self.assertEqual(profile.parse_options(['--w05']), ('--w05', False))
        for argv in (['--quick', '--w01'], ['--quick', '--w04'], ['--quick', '--w05'], ['--quick', '--w06'],
                     ['--quick', '--core'], ['--quick', '--native'], ['--quick', '--acceptance'],
                     ['--quick', '--w10'], ['--quick', '--quick'], ['--quick', '--i01', '--i02'],
                     ['--i01', '--i02'], ['--i03'], ['quick']):
            with self.subTest(argv=argv):
                self.assertIsNone(profile.parse_options(argv))


class RegistryRecordTests(unittest.TestCase):
    def test_every_registered_entry_is_a_measured_slow_test_or_class_that_exists(self):
        # Loads only the registered modules (definitions; nothing runs).
        self.assertIsInstance(profile.SLOW_TESTS, MappingProxyType)
        loader = unittest.TestLoader()
        modules = {}
        for entry, seconds in profile.SLOW_TESTS.items():
            with self.subTest(entry=entry):
                self.assertTrue(math.isfinite(seconds) and seconds >= profile.SLOW_TEST_THRESHOLD_SECONDS)
                module = entry.split('.', 1)[0]
                if module not in modules:
                    modules[module] = [t.id() for t in _leaves(loader.loadTestsFromName(module))]
                    self.assertFalse(loader.errors)
                present = modules[module]
                self.assertTrue(entry in present or any(t.rsplit('.', 1)[0] == entry for t in present))


def _leaves(group):
    for item in group:
        if isinstance(item, unittest.TestSuite):
            yield from _leaves(item)
        else:
            yield item


if __name__ == '__main__':
    unittest.main()
