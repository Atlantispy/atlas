"""Pure disposable-fixture checks: no Atlas import or production constructor run."""
import argparse
import ast
from hashlib import sha256
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, HERE / file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


B = load('_C14_source_constructor_fixtures', 'build_combined.py')
Q = load('_C14_qualification_report_fixtures', 'qualify_heat.py')


class FixtureInputs:
    def __init__(self, document):
        self.document = document

    def doc(self, path, pin):
        return self.document

    def raw(self, path, pin):
        raw = path.read_bytes()
        if sha256(raw).hexdigest() != pin:
            raise ValueError('fixture source digest differs')
        return raw


class ConstructorFixtures(unittest.TestCase):
    def test_literal_repin_preserves_every_other_byte(self):
        old, new = 'a' * 64, 'b' * 64
        before = ('# keep spacing\r\nPIN  =  "' + old + '"\r\nOTHER = 1\r\n').encode()
        self.assertEqual(B.literal_repin(before, old, new), before.replace(old.encode(), new.encode()))

    def test_literal_repin_refuses_missing_duplicate_and_comment_ambiguity(self):
        old, new = 'a' * 64, 'b' * 64
        for text in ('PIN="c"\n', 'P="%s"\nQ="%s"\n' % (old, old),
                     'P="%s"\n# "%s"\n' % (old, old)):
            with self.subTest(text=text), self.assertRaises(ValueError):
                B.literal_repin(text.encode(), old, new)

    def test_literal_repin_refuses_partial_or_invalid_digest(self):
        with self.assertRaises(ValueError):
            B.literal_repin(b'PIN="a"\n', 'a', 'b' * 64)

    def document(self, name, candidate, before, after):
        return dict(base=dict(path=str(B.BASE / 'composition.json'), sha256=B.BASE_PINS['composition'][1]),
            files={name: dict(base_sha256=before, output_sha256=after, candidate=str(candidate))})

    def test_additional_delta_admits_exact_disposable_source_and_refuses_mutation(self):
        with tempfile.TemporaryDirectory(dir=HERE) as tmp:
            candidate = Path(tmp) / 'module.py'
            candidate.write_bytes(b'VALUE = 2\n')
            pin = B.digest(candidate.read_bytes())
            doc = self.document('helpers/module.py', candidate, '1' * 64, pin)
            inputs = FixtureInputs(doc)
            payload, _ = B.additional_delta(inputs, Path(tmp) / 'map.json', 'f' * 64,
                {}, {'module.py': '1' * 64}, {})
            self.assertEqual(payload, {'helpers/module.py': b'VALUE = 2\n'})
            candidate.write_bytes(b'VALUE = 3\n')
            with self.assertRaisesRegex(ValueError, 'digest differs'):
                B.additional_delta(inputs, Path(tmp) / 'map.json', 'f' * 64,
                    {}, {'module.py': '1' * 64}, {})

    def test_additional_delta_refuses_wrong_base_and_path_escape(self):
        for name, base in (('helpers/../escape.py', B.BASE_PINS['composition'][1]),
                           ('helpers/module.py', '0' * 64)):
            doc = self.document(name, Path('unused.py'), None, '1' * 64)
            doc['base']['sha256'] = base
            with self.subTest(name=name), self.assertRaises(ValueError):
                B.additional_delta(FixtureInputs(doc), Path('fixture-map.json'), 'f' * 64, {}, {}, {})

    def test_additional_delta_protects_reviewed_kernel_and_helper(self):
        for name in (B.KERNEL, B.HELPER):
            doc = self.document('helpers/' + name, Path('unused.py'), None, '1' * 64)
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'cannot replace reviewed'):
                B.additional_delta(FixtureInputs(doc), Path('fixture-map.json'), 'f' * 64, {}, {}, {})

    def test_overlapping_resource_delta_requires_exact_C14_predecessor(self):
        doc = self.document('helpers/' + B.RESOURCES, Path('unused.py'), B.RESOURCES_L1, '1' * 64)
        with self.assertRaisesRegex(ValueError, 'additional predecessor differs'):
            B.additional_delta(FixtureInputs(doc), Path('fixture-map.json'), 'f' * 64, {},
                {B.RESOURCES: B.RESOURCES_L1}, {'helpers/' + B.RESOURCES: b'C14_RESOURCE = 1\n'})

    def test_certificate_report_retains_full_digest_and_refuses_numeric_or_fact_changes(self):
        baseline = ([(0.0, 1.0)], dict(precision_bits=128, rank=1))
        digest = Q.exact_certificate(*baseline, *baseline)
        self.assertEqual(len(digest), 64)
        for changed in (([(-0.0, 1.0)], baseline[1]),
                        ([(0.0, 1.0000000000000002)], baseline[1]),
                        (baseline[0], dict(precision_bits=128, rank=2))):
            with self.subTest(changed=changed), self.assertRaisesRegex(AssertionError, 'bounds or certificate facts differ'):
                Q.exact_certificate(*changed, *baseline)

    def test_constructor_and_qualifier_import_no_science(self):
        import sys
        self.assertFalse(any(name == 'atlas_tectonics' or name.startswith('atlas_tectonics.') or
            name.startswith('private_heat_') for name in sys.modules))


class RuntimeEnvironmentFixtures(unittest.TestCase):
    def clean_env(self):
        env = {key: value for key, value in os.environ.items()
               if not key.upper().startswith(('PYTHON', 'PYDEVD', 'COVERAGE'))}
        env.update(PYTHONHASHSEED='0', PYTHONDONTWRITEBYTECODE='1', OMP_NUM_THREADS='1',
                   OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1')
        return env

    def probe(self, flags=('-B', '-s', '-P'), env=None):
        # This subprocess imports only the source preparer and stdlib. Its real
        # interpreter flags/environment are the disposable fault fixture.
        source = HERE / 'qualify_heat.py'
        command = ('import importlib.util,json; '
            's=importlib.util.spec_from_file_location("_runtime_contract_fixture",%r); '
            'm=importlib.util.module_from_spec(s); s.loader.exec_module(m); '
            'print(json.dumps(m.validate_runtime(),sort_keys=True))') % str(source)
        return subprocess.run([sys.executable, *flags, '-c', command],
            env=self.clean_env() if env is None else env, capture_output=True, text=True,
            timeout=15, check=False)

    def test_real_seed_zero_and_required_flags_pass(self):
        done = self.probe()
        self.assertEqual(done.returncode, 0, done.stderr)
        actual = json.loads(done.stdout)
        self.assertEqual(actual['hash_randomization'], 0)
        self.assertEqual(actual['python_environment'],
                         dict(PYTHONHASHSEED='0', PYTHONDONTWRITEBYTECODE='1'))
        self.assertTrue(actual['safe_path'])
        self.assertEqual((actual['dont_write_bytecode'], actual['no_user_site']), (1, 1))

    def test_real_nonzero_and_missing_seed_refuse(self):
        for seed in ('1', None):
            env = self.clean_env()
            if seed is None:
                env.pop('PYTHONHASHSEED')
            else:
                env['PYTHONHASHSEED'] = seed
            done = self.probe(env=env)
            with self.subTest(seed=seed):
                self.assertNotEqual(done.returncode, 0)
                self.assertIn('actual hash_randomization == 0', done.stderr)

    def test_real_ignored_environment_refuses_even_with_seed_zero(self):
        for ignored in ('-E', '-I'):
            done = self.probe(flags=('-B', '-s', '-P', ignored))
            with self.subTest(flag=ignored):
                self.assertNotEqual(done.returncode, 0)
                self.assertIn('-I/-E are forbidden', done.stderr)

    def test_real_missing_site_or_safe_path_flags_refuse(self):
        for flags in (('-B', '-P'), ('-B', '-s')):
            done = self.probe(flags=flags)
            with self.subTest(flags=flags):
                self.assertNotEqual(done.returncode, 0)
                self.assertIn('actual -B -s -P flags', done.stderr)
        flags = SimpleNamespace(hash_randomization=0, ignore_environment=0, isolated=0,
                                dont_write_bytecode=0, no_user_site=1, safe_path=True)
        with self.assertRaisesRegex(AssertionError, 'actual -B -s -P flags'):
            Q.validate_runtime(flags=flags, environ=self.clean_env())

    def test_real_dirty_python_or_parallel_environment_refuses(self):
        for key, value, marker in (('PYTHONPATH', '', 'requires only PYTHONHASHSEED'),
                ('OPENBLAS_NUM_THREADS', '2', 'single-threaded BLAS/OpenMP'),
                ('COVERAGE_PROCESS_START', 'unused-fixture', 'clean debugger/coverage')):
            env = self.clean_env()
            env[key] = value
            done = self.probe(env=env)
            with self.subTest(variable=key):
                self.assertNotEqual(done.returncode, 0)
                self.assertIn(marker, done.stderr)

    def test_main_and_direct_child_refuse_before_source_or_runtime_reads(self):
        for operation in (Q.main, lambda: Q.child('identities', HERE)):
            with self.subTest(operation=operation), patch.object(Q, 'validate_runtime',
                    side_effect=AssertionError('disposable invalid runtime')) as validate, \
                    patch.object(Q, 'source_inputs') as sources, patch.object(Q, 'configure') as configure:
                with self.assertRaisesRegex(AssertionError, 'disposable invalid runtime'):
                    operation()
                validate.assert_called_once_with()
                sources.assert_not_called()
                configure.assert_not_called()


def unchanged_constructor_evidence():
    path = HERE / 'fixture-result-r1.json'
    raw = path.read_bytes()
    expected = '038b7cc176474d6a94be16a104cde506663db9cdc0798ce2ef0a1b243caaadcd'
    if sha256(raw).hexdigest() != expected:
        raise AssertionError('Preserved constructor fixture evidence changed')
    checks = (
        ('test_builder.py', 'ConstructorFixtures', 'd198991bcb9ff0074f54dfbb5600c0d2a6a32bf1d2412f53b9493c527ebab529'),
        ('qualify_heat.py', 'exact_certificate', 'ded805d6c558f41eed24417829c2f5cad84ea4bb0c8d496405f5488303d3f8a1'),
        ('build_combined.py', 'additional_delta', '312e61c76d6d8f52db7fbf418fedf6194fb5a4ef041bb60602aa1b1752abd055'),
        ('build_combined.py', 'literal_repin', '5932f089565359215b76bbaa10cc5de78bc0246c20945751741deddd058f80c5'),
    )
    for file, member, pin in checks:
        text = (HERE / file).read_text(encoding='utf8')
        node = next(n for n in ast.parse(text).body if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name == member)
        if sha256(ast.get_source_segment(text, node).encode()).hexdigest() != pin:
            raise AssertionError('Reused fixture/source scope changed: ' + member)
    previous = json.loads(raw)
    if previous['status'] != 'PASS' or previous['tests_run'] != 9 or sha256(
            (HERE / 'build_combined.py').read_bytes()).hexdigest() != previous['source_pins'][str(HERE / 'build_combined.py')]:
        raise AssertionError('Original constructor result/source identity differs')
    return dict(path=str(path), sha256=expected, tests_reused=9,
        unchanged_scopes=[dict(file=file, member=member, sha256=pin) for file, member, pin in checks],
        note='Original nine fixture tests not repeated; relevant bodies and builder bytes freshly match')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--suite', choices=('constructor', 'runtime'), default='constructor')
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit('Preserve previous fixture evidence')
    output = io.StringIO()
    reused = unchanged_constructor_evidence() if args.suite == 'runtime' else None
    case = RuntimeEnvironmentFixtures if args.suite == 'runtime' else ConstructorFixtures
    result = unittest.TextTestRunner(stream=output, verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(case))
    record = dict(status='PASS' if result.wasSuccessful() else 'FAIL', tests_run=result.testsRun,
        failures=len(result.failures), errors=len(result.errors), output=output.getvalue(), suite=args.suite,
        reused_unchanged_checks=reused,
        source_pins={str(HERE / name): sha256((HERE / name).read_bytes()).hexdigest()
                     for name in ('build_combined.py', 'qualify_heat.py', 'test_builder.py')},
        scope='Pure disposable fixtures only; no constructor execution or Atlas runtime import')
    with args.output.open('x', encoding='utf8', newline='\n') as stream:
        json.dump(record, stream, indent=2)
        stream.write('\n')
    print(json.dumps(record))
    raise SystemExit(0 if result.wasSuccessful() else 1)
