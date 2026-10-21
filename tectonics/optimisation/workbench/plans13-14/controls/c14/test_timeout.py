"""One simulated timeout control; no science, wait, production child or queue action."""
import argparse
from hashlib import sha256
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest

HERE = Path(__file__).resolve().parent
DRIVER = HERE / 'qualify_heat_r2.py'
spec = importlib.util.spec_from_file_location('_r2_timeout_driver_fixture', DRIVER)
D = importlib.util.module_from_spec(spec)
spec.loader.exec_module(D)


class TimeoutControl(unittest.TestCase):
    def test_partial_timeout_streams_failed_result_nonzero_and_finality(self):
        with tempfile.TemporaryDirectory(prefix='timeout-fixture-', dir=HERE) as temporary:
            root = Path(temporary)
            child, profile = root / 'frozen-child.py', root / 'profile.json'
            child.write_bytes(b'# disposable child identity; never executed\n')
            profile.write_bytes(b'{"fixture":true}\n')
            bindings = {str(p): sha256(p.read_bytes()).hexdigest() for p in (child, profile, DRIVER)}
            source_checks, launches = [], []

            def source_inputs():
                source_checks.append(True)
                for name, pin in bindings.items():
                    D.checked(Path(name), pin)

            module = SimpleNamespace(__file__=str(child), CASES=D.CASES, ROOT=root,
                DERIVATION_SHA='d'*64, COMPOSITION_SHA='c'*64, PROFILE_SHA='p'*64,
                DELTA_SHA='e'*64, source_inputs=source_inputs)

            def simulated_timeout(command, **kwargs):
                launches.append(command)
                self.assertEqual(kwargs['timeout'], 180)
                self.assertTrue(kwargs['capture_output'])
                # A bounded known source fault proves finality actually checks
                # bytes after a timeout rather than merely setting a flag.
                profile.write_bytes(b'{"fixture":"changed during timeout"}\n')
                raise subprocess.TimeoutExpired(command, 180, output=b'partial stdout\r\n\xff',
                                                 stderr=b'partial stderr\n')

            output = root / 'evidence'
            code = D.run_cases(module, output, bindings, dict(fixture=True), 's'*64,
                               run_process=simulated_timeout)
            self.assertEqual(code, 1)
            self.assertEqual(len(launches), 1)
            self.assertEqual(len(source_checks), 2)
            self.assertEqual((output / 'identities.stdout.txt').read_bytes(), b'partial stdout\r\n\xff')
            self.assertEqual((output / 'identities.stderr.txt').read_bytes(), b'partial stderr\n')
            result = json.loads((output / 'result.json').read_bytes())
            self.assertEqual(result['status'], 'FAIL')
            self.assertEqual(result['failure']['case'], 'identities')
            self.assertEqual(result['cases'][0]['status'], 'TIMEOUT')
            self.assertTrue(result['cases'][0]['timed_out'])
            self.assertEqual(result['retries'], 0)
            self.assertFalse(result['source_finality']['passed'])
            check = next(row for row in result['source_finality']['checks'] if row['path'] == str(profile))
            self.assertEqual(check['status'], 'FAIL')
            self.assertEqual(result['source_finality']['original_declared_source_closure']['status'], 'FAIL')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit('Preserve original control evidence')
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(TimeoutControl))
    report = dict(status='PASS' if result.wasSuccessful() else 'FAIL', tests_run=result.testsRun,
        failures=len(result.failures), errors=len(result.errors), output=stream.getvalue(),
        source_pins={str(path): sha256(path.read_bytes()).hexdigest() for path in (DRIVER, Path(__file__).resolve())},
        scope='One bounded simulated TimeoutExpired with partial bytes and disposable source mutation; no science or wait')
    with args.output.open('x', encoding='utf8', newline='\n') as target:
        json.dump(report, target, indent=2)
        target.write('\n')
    print(json.dumps(report))
    raise SystemExit(0 if result.wasSuccessful() else 1)
