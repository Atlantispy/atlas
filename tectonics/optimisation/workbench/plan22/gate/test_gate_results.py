"""Focused result-boundary tests; never calls gate build/run or opens an IV store."""
import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'gate_s3l3.py'
spec = importlib.util.spec_from_file_location('candidate_gate', SOURCE)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


def record(identifier, kind, arm, module, count, *, failed=False):
    result = dict(run=count, failures=int(failed), errors=0, skipped=0,
                  bad={'synthetic_mutant': 'AssertionError'} if failed else {}, clean=True,
                  passed=not failed)
    if kind == 's3':
        result = dict(testsRun=count, failed_or_error=0, expected_outcome=True,
                      outcomes={f'test_{i}': 'ok' for i in range(count)})
    return dict(id=identifier, kind=kind, arm=arm, layout='composition', module=module,
                exit=int(failed), result=result)


records = []
for arm in ('b', 'c3', 'c4'):
    for module in (*gate.IDENTITY, 'test_interval_store_set'):
        records.append(record(f'w-{arm}-{module}', 'suite', arm, module, 10))
for arm in ('c3', 'c4'):
    records.append(record(f'w-{arm}-test_l3_carried_pages', 'suite', arm, 'test_l3_carried_pages', 22))
    for mode in ('lazy', 'consumers', 'own'):
        records.append(record(f's-{arm}-{mode}', 's3', arm, mode, gate.EXPECTED[mode]))
    records.append(record(f'g-{arm}', 'gate', arm, 'gate_cases', 3))
records.append(record('w-c4-test_s1a_guarded_read', 'suite', 'c4', 'test_s1a_guarded_read', gate.EXPECTED['test_s1a_guarded_read']))
records.append(record('s-n-negative', 's3', 'n', 'negative', 19))
records.append(record('g-m', 'gate', 'm', 'gate_cases', 3, failed=True))


class ResultBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.records = copy.deepcopy(records)

    def result(self, identifier):
        return next(r for r in self.records if r['id'] == identifier)['result']

    def accepted(self):
        return all(check['ok'] for check in gate.evaluate(self.records, {'test_s1_sealed_read'}, []))

    def test_valid_control_including_expected_mutant_exit(self):
        self.assertTrue(self.accepted())

    def test_nonzero_exit_and_timeout_rejected_for_every_positive_kind(self):
        for identifier in ('w-c3-test_record_views', 's-c3-lazy', 'g-c3'):
            for exit_code in (2, 'timeout'):
                with self.subTest(identifier=identifier, exit_code=exit_code):
                    self.setUp()
                    next(r for r in self.records if r['id'] == identifier)['exit'] = exit_code
                    self.assertFalse(self.accepted())

    def test_negative_exit_must_be_the_expected_failure(self):
        for exit_code in (0, 2, 'timeout'):
            with self.subTest(exit_code=exit_code):
                self.setUp()
                next(r for r in self.records if r['id'] == 'g-m')['exit'] = exit_code
                self.assertFalse(self.accepted())

    def test_added_identity_skip_is_rejected(self):
        for skips in (1, 10):
            with self.subTest(skips=skips):
                self.result('w-c3-test_record_views')['skipped'] = skips
                self.assertFalse(self.accepted())

    def test_unchanged_partial_skip_and_known_failure_remain_allowed(self):
        for arm in ('b', 'c3', 'c4'):
            self.result(f'w-{arm}-test_record_views')['skipped'] = 1
            self.result(f'w-{arm}-test_mesh_tables').update(failures=1, bad={'known': 'known baseline issue'})
        self.assertTrue(self.accepted())

    def test_all_skipped_or_zero_baseline_coverage_is_rejected(self):
        for run, skipped in ((10, 10), (0, 0)):
            with self.subTest(run=run, skipped=skipped):
                self.setUp()
                for arm in ('b', 'c3', 'c4'):
                    self.result(f'w-{arm}-test_record_views').update(run=run, skipped=skipped)
                self.assertFalse(self.accepted())

    def test_changed_s1_suite_cannot_drop_coverage_or_add_skips(self):
        for run, skipped in ((0, 0), (9, 0), (10, 1)):
            with self.subTest(run=run, skipped=skipped):
                self.setUp()
                self.result('w-c4-test_s1_sealed_read').update(run=run, skipped=skipped)
                self.assertFalse(self.accepted())

    def test_changed_s1_suite_may_fix_existing_failure_without_dropping_tests(self):
        for arm in ('b', 'c3'):
            self.result(f'w-{arm}-test_s1_sealed_read').update(failures=1, bad={'prior': 'prior issue'})
        self.assertTrue(self.accepted())

    def test_required_l3_s1_and_gate_cases_cannot_skip(self):
        for identifier in ('w-c3-test_l3_carried_pages', 'w-c4-test_s1a_guarded_read', 'g-c3'):
            with self.subTest(identifier=identifier):
                self.setUp()
                self.result(identifier)['skipped'] = 1
                self.assertFalse(self.accepted())

    def test_s3_outcomes_cannot_hide_skip_or_missing_coverage(self):
        for identifier in ('s-c3-lazy', 's-c3-consumers', 's-c3-own', 's-n-negative'):
            for change in ('skip', 'missing'):
                with self.subTest(identifier=identifier, change=change):
                    self.setUp()
                    outcomes = self.result(identifier)['outcomes']
                    if change == 'skip':
                        outcomes['test_0'] = 'skip'
                    else:
                        del outcomes['test_0']
                    self.assertFalse(self.accepted())


class PathConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='gate-paths-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.paths = {}
        for name in gate.PATH_KEYS:
            path = self.root / name
            if name in gate.DIRECTORY_KEYS:
                path.mkdir()
            else:
                path.mkdir()
                path = path / ('PORT.json' if name.endswith('_port') else name + '.py')
                path.write_text('{}', encoding='utf-8')
            self.paths[name] = str(path)
        self.paths['python'] = str(Path(sys.executable).resolve())
        self.config = self.root / 'paths.json'

    def configure(self):
        self.config.write_text(json.dumps(self.paths), encoding='utf-8')
        return gate.configure_paths(self.config)

    def test_explicit_locations_preserve_fixed_identity_pins(self):
        located = self.configure()
        self.assertEqual(located, {name: Path(path) for name, path in self.paths.items()})
        for name, (pin, form) in gate.PORT_PINS.items():
            self.assertEqual(gate.PORTS[name], (Path(self.paths[name + '_port']), pin, form))
        # Supplying locations does not authenticate files or permit a moved PORT.
        with self.assertRaisesRegex(ValueError, 's1a PORT.json digest moved'):
            gate.port_rows('s1a', gate.PORTS)

    def test_missing_and_identity_override_keys_refuse(self):
        original = dict(self.paths)
        del self.paths['s1a_port']
        with self.assertRaisesRegex(ValueError, 'exactly'):
            self.configure()
        self.paths = {**original, 's1a_sha256': '0' * 64}
        with self.assertRaisesRegex(ValueError, 'exactly'):
            self.configure()

    def test_port_directory_refuses_instead_of_guessing_a_file(self):
        self.paths['s1a_port'] = str(Path(self.paths['s1a_port']).parent)
        with self.assertRaisesRegex(ValueError, 's1a_port: expected an existing file'):
            self.configure()

    def test_different_existing_python_refuses(self):
        self.paths['python'] = self.paths['applier']
        with self.assertRaisesRegex(ValueError, 'run this gate with the configured interpreter'):
            self.configure()

    def test_relative_and_missing_paths_refuse(self):
        for path, message in (('relative/path', 'path must be absolute'),
                              (str(self.root / 'absent'), 'expected an existing file')):
            with self.subTest(path=path):
                self.paths['python'] = path
                with self.assertRaisesRegex(ValueError, message):
                    self.configure()

    def test_moved_input_pin_refuses_before_creating_output_or_launching_children(self):
        (Path(self.paths['base']) / 'composition.json').write_text('{}', encoding='utf-8')
        self.config.write_text(json.dumps(self.paths), encoding='utf-8')
        output = self.root / 'new-output'
        with self.assertRaisesRegex(ValueError, 'base composition.json digest moved'):
            gate.main(['verify', str(output), '--paths', str(self.config)])
        self.assertFalse(output.exists())


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, help='write a new JSON control result; does not run the full gate')
    args = parser.parse_args()
    suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(case)
                               for case in (ResultBoundaryTests, PathConfigurationTests))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    output = dict(schema='plan22.gate.public-controls.r1',
                  gate_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
                  test_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  tests_run=result.testsRun, failures=len(result.failures), errors=len(result.errors),
                  skipped=len(result.skipped), successful=result.wasSuccessful(),
                  scope='Synthetic result acceptance and path configuration only; no gate construction or IV run',
                  full_gate='NOT_RUN')
    if args.report:
        with args.report.open('x', encoding='utf-8', newline='\n') as stream:
            json.dump(output, stream, indent=2)
            stream.write('\n')
    print(json.dumps(output, sort_keys=True))
    raise SystemExit(0 if result.wasSuccessful() else 1)
