"""Development tools: parallel runner, impact selector and candidate verifier, on small synthetic trees.

Standard library only; nothing here imports or runs Atlas. The runner tests start a few worker processes of the
current interpreter on a throwaway tests folder.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location('dev_'+name, ROOT/'tools'/(name+'.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


runner = load('run_tests_parallel')
impact = load('test_impact')
candidate = load('verify_candidate')


def git(cwd, *args):
    return subprocess.run(['git', '-c', 'core.autocrlf=false', '-c', 'user.name=t', '-c', 'user.email=t@example.invalid',
                           *args], cwd=str(cwd), check=True, capture_output=True, text=True).stdout


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(textwrap.dedent(text).encode())


class SlowRegistryTests(unittest.TestCase):
    TESTS = ['test_a.Slow.test_1', 'test_a.Slow.test_2', 'test_a.Fast.test_3', 'test_b.Heavy.test_4']

    def test_registered_tests_and_classes_are_omitted(self):
        kept, omitted = runner.quick_filter(self.TESTS, {'test_a.Slow.test_1': 70.0, 'test_b.Heavy': 90.0},
                                            ['test_*.py'])
        self.assertEqual(kept, ['test_a.Slow.test_2', 'test_a.Fast.test_3'])
        self.assertEqual(omitted, ['test_a.Slow.test_1', 'test_b.Heavy.test_4'])

    def test_a_stale_entry_in_scope_refuses_and_out_of_scope_is_ignored(self):
        with self.assertRaisesRegex(ValueError, 'stale.*test_a.Slow.test_gone'):
            runner.quick_filter(self.TESTS, {'test_a.Slow.test_gone': 70.0}, ['test_*.py'])
        kept, omitted = runner.quick_filter(self.TESTS, {'test_z.Other': 70.0}, ['test_a.py', 'test_b.py'])
        self.assertEqual((kept, omitted), (self.TESTS, []))

    def test_the_registry_is_read_from_verify_py_without_importing_it(self):
        with tempfile.TemporaryDirectory() as folder:
            write(Path(folder)/'tectonics'/'verify.py', '''
                raise SystemExit('must not be imported')
                SLOW_TESTS = MappingProxyType({
                    'test_a.Slow': 61.5,
                })
            ''')
            self.assertEqual(runner.load_slow_registry(folder), {'test_a.Slow': 61.5})
            Path(folder, 'slow.json').write_text('{"test_b.Heavy": 99}', encoding='utf-8')
            self.assertEqual(runner.load_slow_registry(folder, Path(folder, 'slow.json')), {'test_b.Heavy': 99.0})

    def test_default_patterns_are_the_trees_full_verification_discovery(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(runner.full_patterns(folder), ('test_*.py', 'check_native_transport.py'))  # fallback
            write(Path(folder)/'tectonics'/'verify.py', '''
                raise SystemExit('must not be imported')
                FULL_PATTERNS = ('test_*.py', 'check_native_transport.py', 'check_extra.py')
            ''')
            self.assertEqual(runner.full_patterns(folder),
                             ('test_*.py', 'check_native_transport.py', 'check_extra.py'))

    def test_a_default_run_includes_every_full_discovery_pattern(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)/'tree'
            (root/'tectonics'/'src').mkdir(parents=True)
            tests = root/'tectonics'/'tests'
            write(tests/'test_plain.py', 'import unittest\nclass A(unittest.TestCase):\n    def test_a(self):\n        pass\n')
            write(tests/'check_native_transport.py',
                  'import unittest\nclass N(unittest.TestCase):\n    def test_n(self):\n        pass\n')
            proc = subprocess.run([sys.executable, '-B', str(ROOT/'tools'/'run_tests_parallel.py'), '--root', str(root),
                                   '--python', sys.executable, '--run-dir', str(Path(folder)/'run')],
                                  capture_output=True, text=True)
            summary = json.loads((Path(folder)/'run'/'summary.json').read_text(encoding='utf-8'))
            self.assertEqual(proc.returncode, 0, proc.stdout+proc.stderr)
            self.assertEqual(sorted(summary['tests']), ['check_native_transport.N.test_n', 'test_plain.A.test_a'])
            self.assertEqual(summary['patterns'], ['test_*.py', 'check_native_transport.py'])

    def test_units_are_classes_unless_the_module_has_fixtures(self):
        units = runner.units_of(['m1.A.t1', 'm1.A.t2', 'm1.B.t3', 'm2.C.t4', 'm2.D.t5'], {'m2': True})
        self.assertEqual(units, {'m1.A': ['m1.A.t1', 'm1.A.t2'], 'm1.B': ['m1.B.t3'], 'm2': ['m2.C.t4', 'm2.D.t5']})


class ParallelRunnerTests(unittest.TestCase):
    """End to end on a throwaway tree: parallel and serial agree on every per-test outcome."""

    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        root = Path(cls.folder.name)/'tree'
        (root/'tectonics'/'src').mkdir(parents=True)
        tests = root/'tectonics'/'tests'
        write(tests/'test_one.py', '''
            import os, tempfile, unittest
            class Mixed(unittest.TestCase):
                def test_pass(self):
                    self.assertEqual(os.environ['OMP_NUM_THREADS'], '1')
                def test_fail(self):
                    self.assertEqual(1, 2)
                @unittest.skip('declared')
                def test_skip(self):
                    pass
                @unittest.expectedFailure
                def test_expected(self):
                    self.assertTrue(False)
                def test_subtests(self):
                    for i in range(3):
                        with self.subTest(i=i):
                            self.assertNotEqual(i, 1)
                def test_subtest_skip(self):
                    for i in range(2):
                        with self.subTest(i=i):
                            if i:
                                self.skipTest('declared')
            class Temp(unittest.TestCase):
                def test_private_temporary_folder(self):
                    self.assertTrue(os.path.basename(tempfile.gettempdir()).startswith('atw'))
        ''')
        write(tests/'test_two.py', '''
            import unittest
            STATE = []
            def setUpModule():
                STATE.append('module')
            class A(unittest.TestCase):
                def test_module_fixture_ran(self):
                    self.assertEqual(STATE, ['module'])
            class B(unittest.TestCase):
                @classmethod
                def setUpClass(cls):
                    raise RuntimeError('class fixture fails')
                def test_never(self):
                    pass
        ''')
        cls.root = root
        cls.runs = Path(cls.folder.name)/'runs'

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def run_tool(self, name, *extra):
        out = self.runs/name
        proc = subprocess.run([sys.executable, '-B', str(ROOT/'tools'/'run_tests_parallel.py'), '--root',
                               str(self.root), '--python', sys.executable, '--run-dir', str(out), '--workers', '3',
                               *extra], capture_output=True, text=True)
        return proc, json.loads((out/'summary.json').read_text(encoding='utf-8'))

    def test_parallel_matches_serial_and_records_every_outcome(self):
        parallel, first = self.run_tool('parallel')
        serial, second = self.run_tool('serial', '--serial')
        self.assertEqual(parallel.returncode, 1)              # one real failure and one fixture error
        self.assertFalse(first['passed'])
        outcomes = {k: v['outcome'] for k, v in first['tests'].items()}
        self.assertEqual(outcomes, {k: v['outcome'] for k, v in second['tests'].items()})
        self.assertEqual(outcomes['test_one.Mixed.test_pass'], 'success')
        self.assertEqual(outcomes['test_one.Mixed.test_fail'], 'failure')
        self.assertEqual(outcomes['test_one.Mixed.test_skip'], 'skipped')
        self.assertEqual(outcomes['test_one.Mixed.test_expected'], 'expected_failure')
        self.assertEqual(outcomes['test_one.Mixed.test_subtests'], 'failure')          # recorded, not lost
        self.assertEqual(outcomes['test_one.Mixed.test_subtests (i=1)'], 'failure')
        self.assertEqual(outcomes['test_one.Mixed.test_subtest_skip'], 'skipped')
        self.assertEqual(outcomes['test_one.Mixed.test_subtest_skip (i=1)'], 'skipped')
        self.assertEqual(outcomes['test_one.Temp.test_private_temporary_folder'], 'success')
        self.assertEqual(outcomes['test_two.A.test_module_fixture_ran'], 'success')
        self.assertIn('error', {outcomes[k] for k in outcomes if 'test_two.B' in k})
        self.assertEqual(sorted(first['units']), ['test_one.Mixed', 'test_one.Temp', 'test_two'])
        self.assertEqual(first['local_bytecode'], [])
        compared = subprocess.run([sys.executable, '-B', str(ROOT/'tools'/'run_tests_parallel.py'), '--compare',
                                   str(self.runs/'parallel'/'summary.json'), str(self.runs/'serial'/'summary.json')],
                                  capture_output=True, text=True)
        self.assertEqual(compared.returncode, 0, compared.stdout)

    def test_local_bytecode_fails_the_run(self):
        pyc = self.root/'tectonics'/'tests'/'__pycache__'/'stale.cpython-312.pyc'
        pyc.parent.mkdir(exist_ok=True)
        pyc.write_bytes(b'')
        try:
            _, summary = self.run_tool('bytecode', '--only', 'test_two.A')
        finally:
            pyc.unlink()
            pyc.parent.rmdir()
        self.assertEqual(summary['counts']['success'], 1)
        self.assertFalse(summary['passed'])
        self.assertEqual(len(summary['local_bytecode']), 1)

    def test_a_cache_inside_the_tree_refuses(self):
        proc = subprocess.run([sys.executable, '-B', str(ROOT/'tools'/'run_tests_parallel.py'), '--root',
                               str(self.root), '--python', sys.executable, '--run-dir', str(self.runs/'refused'),
                               '--pycache', str(self.root/'tectonics'/'src'/'cache')], capture_output=True, text=True)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn('outside src/tests', proc.stderr)


class SerialGroupTests(unittest.TestCase):
    def test_a_serial_unit_runs_alone_in_a_new_process_after_the_parallel_phase(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)/'tree'
            (root/'tectonics'/'src').mkdir(parents=True)
            tests = root/'tectonics'/'tests'
            write(tests/'shared_state.py', 'POLLUTED = []\n')
            write(tests/'test_order.py', '''
                import unittest
                import shared_state
                class A(unittest.TestCase):
                    def test_pollutes(self):
                        shared_state.POLLUTED.append(1)
                class B(unittest.TestCase):
                    def test_needs_a_clean_process(self):
                        self.assertEqual(shared_state.POLLUTED, [])
            ''')

            def run(name, *extra):
                proc = subprocess.run([sys.executable, '-B', str(ROOT/'tools'/'run_tests_parallel.py'), '--root',
                                       str(root), '--python', sys.executable, '--workers', '1', '--run-dir',
                                       str(Path(folder)/name), *extra], capture_output=True, text=True)
                summary = json.loads((Path(folder)/name/'summary.json').read_text(encoding='utf-8'))
                return summary['tests']['test_order.B.test_needs_a_clean_process']['outcome']
            self.assertEqual(run('shared'), 'failure')              # one worker: A runs first and pollutes
            # Both in the serial group: A still runs first, but B gets its own new process.
            self.assertEqual(run('serial', '--serial-unit', 'test_order.A', '--serial-unit', 'test_order.B'),
                             'success')


class TracerTests(unittest.TestCase):
    def test_a_fresh_traced_unit_records_execution_imports_and_data_reads(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)/'tree'
            (root/'tectonics'/'src').mkdir(parents=True)
            tests = root/'tectonics'/'tests'
            write(tests/'helper_mod.py', '''
                class K:
                    X = 1
                def used():
                    return 1
                def unused():
                    return 2
            ''')
            write(tests/'data.txt', 'payload\n')
            write(tests/'copied.txt', 'copied\n')
            (root/'listed').mkdir()
            write(tests/'test_traced.py', '''
                import os, shutil, tempfile, unittest
                import helper_mod
                HERE = os.path.dirname(os.path.abspath(__file__))
                class T(unittest.TestCase):
                    def test_a(self):
                        self.assertEqual(helper_mod.used(), 1)
                        with open(os.path.join(HERE, 'data.txt')) as f:
                            self.assertEqual(f.read(), 'payload\\n')
                        shutil.copy2(os.path.join(HERE, 'copied.txt'), tempfile.gettempdir())
                        os.listdir(os.path.join(HERE, '..', '..', 'listed'))
                        import importlib.metadata
                        list(importlib.metadata.distributions())        # lists every sys.path folder, names only
            ''')
            traces = Path(folder)/'traces'
            proc = subprocess.run([sys.executable, '-B', str(ROOT/'tools'/'run_tests_parallel.py'), '--root', str(root),
                                   '--python', sys.executable, '--run-dir', str(Path(folder)/'run'), '--fresh',
                                   '--trace-dir', str(traces)], capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stdout+proc.stderr)
            trace = json.loads((traces/'test_traced.T.json').read_text(encoding='utf-8'))
            norm = lambda paths: {os.path.normcase(p) for p in paths}
            helper, data = os.path.normcase(str(tests/'helper_mod.py')), os.path.normcase(str(tests/'data.txt'))
            self.assertIn(helper, norm(trace['modules']))                 # imported; class body counts as import
            self.assertIn(helper, norm(trace['executed']))                # used() ran
            functions = {f.split('::')[1] for f in trace['functions'] if os.path.normcase(f.split('::')[0]) == helper}
            self.assertEqual(functions, {'used'})                         # not unused(), not the class body K
            self.assertIn(data, norm(trace['opened']))
            self.assertNotIn(helper, norm(trace['opened']))               # compiling an import is not a data read
            self.assertEqual(trace['spawned'], [])
            self.assertIn(os.path.normcase(str(tests/'copied.txt')), norm(trace['copied']))   # copied in C
            scanned = norm(trace['scanned'])
            self.assertIn(os.path.normcase(str(root/'listed')), scanned)   # an explicit listing
            self.assertNotIn(os.path.normcase(str(tests)), scanned)        # the import system's search is not one


class SkeletonTests(unittest.TestCase):
    BASE = 'X = 1\n@deco\ndef f(a, b=2):\n    """doc"""\n    return a + b\nclass C:\n    k = 3\n    def m(self):\n        return 1\n'

    def test_body_only_changes(self):
        for new in (self.BASE.replace('return a + b', 'return a - b'),
                    self.BASE.replace('        return 1', '        x = 2\n        return x'),
                    self.BASE.replace('def m(self):\n', 'def m(self):\n\n')):
            with self.subTest(new=new):
                self.assertEqual(impact.change_kind(self.BASE.encode(), new.encode()), 'body')

    def test_structural_changes(self):
        for new in (self.BASE.replace('X = 1', 'X = 2'), self.BASE.replace('b=2', 'b=3'),
                    self.BASE.replace('@deco\n', ''), self.BASE.replace('    k = 3', '    k = 4'),
                    self.BASE.replace('"""doc"""', '"""other"""'),            # __doc__ is visible without a call
                    self.BASE.replace('return a + b', 'yield a + b'),          # now a generator function
                    self.BASE + 'def g():\n    pass\n', 'syntax error (\n'):
            with self.subTest(new=new):
                self.assertEqual(impact.change_kind(self.BASE.encode(), new.encode()), 'structural')

    def test_a_body_edit_that_parses_but_does_not_compile_is_caught(self):
        good = b'def f(x):\n    for i in x:\n        pass\n'
        bad = b'def f(x):\n    break\n'                 # parses; the compiler refuses 'break' outside a loop
        warns = b'def f(x):\n    return "\\d"\n'        # an invalid escape: a SyntaxWarning, an error here
        self.assertEqual(impact.change_kind(good, bad), 'body')
        self.assertEqual(impact.compiles(sys.executable, [('a.py', good), ('b.py', bad), ('c.py', warns)]),
                         [True, False, False])

    def test_code_observers_are_found_by_outermost_function(self):
        with tempfile.TemporaryDirectory() as folder:
            write(Path(folder)/'m.py', """
                import marshal
                def plain():
                    return 1
                def digest(f):
                    return marshal.dumps(f.__code__)
                class C:
                    def method(self):
                        def inner(g):
                            return g.__code__.co_consts
                        return inner
                    def other(self):
                        return 2
                if True:
                    def guarded(f):
                        return inspect.getsource(f)
                try:
                    pass
                except getattr(E, '__code__'):
                    pass
            """)
            write(Path(folder)/'n.py', 'X = [f.__code__ for f in ()]\ndef plain():\n    return 1\n')
            write(Path(folder)/'aliased.py', """
                import marshal as mm
                from inspect import getsource as gs
                import importlib
                def by_alias(code):
                    return mm.dumps(code)
                def by_imported_name(f):
                    return gs(f)
                def by_string(f):
                    return getattr(f, '__code__')
                def by_dynamic_import():
                    return importlib.import_module('dis')
                def by_frame():
                    return sys._getframe().f_lineno
                def by_inspect_stack():
                    return inspect.stack()
                def numpy_stack_is_not_introspection(np, x):
                    return np.stack(x)
                def plain():
                    return 1
            """)
            write(Path(folder)/'kern.py', 'import numba\ndef k():\n    return 1\n')
            write(Path(folder)/'broken.py', 'def (:\n')
            blobs = {'m.py': '', 'n.py': '', 'aliased.py': '', 'kern.py': '', 'broken.py': ''}
            self.assertEqual(impact._code_observers(folder, blobs), {
                'm.py': ['<module>', 'C.method', 'digest', 'guarded'],   # '<module>': the except clause
                'n.py': ['<module>'], 'broken.py': ['<module>'],          # unparsable: charged whole
                'aliased.py': ['by_alias', 'by_dynamic_import', 'by_frame', 'by_imported_name', 'by_inspect_stack',
                               'by_string']})
            self.assertEqual(impact._numba_files(folder, blobs), ['broken.py', 'kern.py'])


class ImpactSelectionTests(unittest.TestCase):
    """Selection rules on a small committed tree and a hand-written map (suite folder tectonics/tests)."""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        root = self.root = Path(self.folder.name)
        write(root/'pkg'/'a.py', 'def f():\n    return 1\nCONST = 1\n')
        write(root/'pkg'/'b.py', 'def g():\n    return 2\n')
        write(root/'pkg'/'kern.py', 'from numba import njit\n@njit\ndef k():\n    return 3\n')
        write(root/'tectonics'/'tests'/'test_x.py', 'def test():\n    pass\n')
        write(root/'tests'/'test_root.py', 'def test():\n    pass\n')
        write(root/'tools'/'helper.py', 'def h():\n    return 1\n')
        write(root/'data'/'case.json', '{}\n')
        write(root/'data'/'unused.json', '{}\n')
        write(root/'listed'/'sized.json', '{}\n')
        write(root/'.gitattributes', '*.json text eol=lf\n')
        git(root, 'init', '-q')
        git(root, 'add', '-A')
        git(root, 'commit', '-q', '-m', 'base')
        self.base = git(root, 'rev-parse', 'HEAD').strip()
        unit = dict(tests=['t'], complete=True, skipped=False, executed=[], modules=['pkg/a.py', 'pkg/b.py'],
                    opened=[], identity_reads=[], scanned=[], spawned=False, numba=False, observes_code=False)
        self.map = dict(schema=impact.SCHEMA, commit=self.base, files=impact.tracked_blobs(root),
                        numba_files=impact._numba_files(root, impact.tracked_blobs(root)), units={
                            'test_x.Runs_a': dict(unit, executed=['pkg/a.py']),
                            'test_x.Imports_only': dict(unit),
                            'test_x.Opens_case': dict(unit, opened=['data/case.json']),
                            'test_x.Native': dict(unit, numba=True),
                            'test_x.Observes': dict(unit, modules=['pkg/a.py'], observes_code=True),
                            'test_x.Lists': dict(unit, modules=[], scanned=['listed', 'pkg']),
                            'test_y.Spawns': dict(unit, modules=[], spawned=True),
                            'test_y.Failed': dict(unit, modules=[], complete=False),
                            'test_y.Skips': dict(unit, modules=[], skipped=True),
                        })
        self.always = ['test_y.Failed', 'test_y.Skips', 'test_y.Spawns']

    def tearDown(self):
        self.folder.cleanup()

    def select(self, base, head=None, files=None, the_map=None):
        return impact.select(the_map or self.map, self.root, base, head, files, python=sys.executable)

    def change(self, path, text):
        git(self.root, 'reset', '-q', '--hard', self.base)                         # one change at a time
        write(self.root/path, text)
        git(self.root, 'add', '-A')
        git(self.root, 'commit', '-q', '-m', 'change')
        return self.select(self.base, git(self.root, 'rev-parse', 'HEAD').strip())

    def test_a_body_change_selects_executors_observers_folder_listers_and_the_always_selected(self):
        result = self.change('pkg/a.py', 'def f():\n    return 5\nCONST = 1\n')
        self.assertFalse(result['all'])
        self.assertEqual(result['reasons']['pkg/a.py']['kind'], 'body')
        self.assertEqual(result['units'], ['test_x.Lists', 'test_x.Observes', 'test_x.Runs_a'] + self.always)
        self.assertEqual(result['modules'], [])

    def test_a_body_change_that_does_not_compile_counts_as_structural(self):
        result = self.change('pkg/a.py', 'def f():\n    break\nCONST = 1\n')
        self.assertEqual(result['reasons']['pkg/a.py']['kind'], 'structural')
        self.assertIn('test_x.Imports_only', result['units'])

    def test_a_structural_change_selects_the_importers_and_their_whole_modules(self):
        result = self.change('pkg/a.py', 'def f():\n    return 1\nCONST = 2\n')
        self.assertEqual(result['units'], ['test_x.Imports_only', 'test_x.Lists', 'test_x.Native',
                                           'test_x.Observes', 'test_x.Opens_case', 'test_x.Runs_a'] + self.always)
        self.assertEqual(result['modules'], ['test_x'])

    def test_a_numba_file_change_selects_every_compiling_unit(self):
        result = self.change('pkg/kern.py', 'from numba import njit\n@njit\ndef k():\n    return 4\n')
        self.assertIn('test_x.Native', result['units'])
        self.assertNotIn('test_x.Runs_a', result['units'])

    def test_data_files(self):
        self.assertEqual(self.change('data/case.json', '{"a": 1}\n')['units'], ['test_x.Opens_case'] + self.always)
        self.assertEqual(self.change('listed/sized.json', '{"a": 12}\n')['units'], ['test_x.Lists'] + self.always)
        self.assertTrue(self.change('data/unused.json', '{"a": 1}\n')['all'])

    def test_git_attributes_select_everything(self):
        self.assertTrue(self.change('.gitattributes', '*.json text eol=crlf\n')['all'])

    def test_added_deleted_renamed_and_unknown_files_select_everything(self):
        self.assertTrue(self.change('pkg/new.py', 'x = 1\n')['all'])
        os.remove(self.root/'pkg'/'b.py')
        git(self.root, 'add', '-A')
        git(self.root, 'commit', '-q', '-m', 'delete')
        self.assertTrue(self.select(self.base, 'HEAD')['all'])

    def test_test_files_inside_and_outside_the_recorded_suite(self):
        result = self.change('tectonics/tests/test_x.py', 'def test():\n    assert True\n')
        self.assertIn('test_x', result['modules'])
        result = self.change('tests/test_root.py', 'def test():\n    assert True\n')
        self.assertEqual(result['outside_scope'], ['tests/test_root.py'])
        result = self.change('tools/helper.py', 'def h():\n    return 2\n')
        self.assertEqual(result['untouched'], ['tools/helper.py'])

    def test_a_map_from_another_tree_counts_the_difference_as_changed(self):
        stale = dict(self.map, files=dict(self.map['files'], **{'pkg/b.py': '0'*40}))
        result = self.select(self.base, self.base, the_map=stale)
        self.assertEqual(result['reasons']['pkg/b.py']['kind'], 'structural')
        self.assertIn('test_x.Imports_only', result['units'])
        missing = dict(self.map, files={k: v for k, v in self.map['files'].items() if k != 'pkg/b.py'})
        self.assertTrue(self.select(self.base, self.base, the_map=missing)['all'])

    def test_files_mode_compares_the_map_with_the_root_head(self):
        # The root's HEAD moved past the map's commit (b.py changed); the listed working-tree change is to a.py only.
        write(self.root/'pkg'/'b.py', 'def g():\n    return 3\n')
        git(self.root, 'commit', '-q', '-am', 'drift')
        write(self.root/'pkg'/'a.py', 'def f():\n    return 5\nCONST = 1\n')
        result = self.select(None, files=['pkg/a.py'])
        self.assertEqual(result['reasons']['pkg/b.py']['kind'], 'structural')
        self.assertIn('test_x.Imports_only', result['units'])
        write(self.root/'pkg'/'new.py', 'x = 1\n')
        self.assertTrue(self.select(None, files=['pkg/new.py'])['all'])           # untracked: added
        os.remove(self.root/'pkg'/'b.py')
        self.assertTrue(self.select(None, files=['pkg/b.py'])['all'])             # deleted

    def test_a_different_interpreter_or_environment_selects_everything(self):
        recorded = dict(self.map, fingerprint=impact.fingerprint(sys.executable, self.root))
        self.assertFalse(self.select(self.base, self.base, the_map=recorded)['all'])
        other = dict(recorded, fingerprint=dict(recorded['fingerprint'], version='another'))
        self.assertTrue(self.select(self.base, self.base, the_map=other)['all'])
        with self.assertRaises(ValueError):
            impact.select(recorded, self.root, self.base, self.base)              # no interpreter given

    def test_inherited_pythonpath_changes_imports_and_selects_everything(self):
        first, second = self.root/'env_a', self.root/'env_b'
        for folder, value in ((first, 1), (second, 2)):
            write(folder/'external_probe.py', 'VALUE = %d\n' % value)
        observed, fingerprints = [], []
        for folder in (first, second):
            with patch.dict(os.environ, {'PYTHONPATH': str(folder)}):
                fingerprints.append(impact.fingerprint(sys.executable, self.root))
                args = SimpleNamespace(src=self.root/'tectonics'/'src', pycache=self.root/'external-cache')
                proc = subprocess.run([sys.executable, '-B', '-c', 'import external_probe; print(external_probe.VALUE)'],
                                      env=runner._child_env(args, self.root), capture_output=True, text=True, check=True)
                observed.append(proc.stdout.strip())
        self.assertEqual(observed, ['1', '2'])
        self.assertNotEqual(fingerprints[0], fingerprints[1])
        with patch.dict(os.environ, {'PYTHONPATH': str(second)}):
            recorded = dict(self.map, fingerprint=fingerprints[0])
            self.assertTrue(self.select(self.base, self.base, the_map=recorded)['all'])


class ImpactRecordTests(unittest.TestCase):
    def test_a_traced_run_keeps_original_provenance_and_refuses_relabelling(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)/'tree'
            (root/'tectonics'/'src').mkdir(parents=True)
            test = root/'tectonics'/'tests'/'test_tiny.py'
            write(test, 'import unittest\nclass T(unittest.TestCase):\n    def test_ok(self):\n        self.assertEqual(1, 1)\n')
            git(root, 'init', '-q')
            git(root, 'add', '-A')
            git(root, 'commit', '-q', '-m', 'fixture')
            args = SimpleNamespace(root=str(root), python=sys.executable, map=str(Path(folder)/'map.json'),
                                   from_run=None, run_dir=str(Path(folder)/'record'), workers=1, durations=None)
            self.assertEqual(impact.record(args), 0)
            original = json.loads(Path(args.map).read_text())
            self.assertTrue(original['provenance']['unchanged'])
            self.assertEqual(original['provenance']['before'], original['provenance']['after'])
            args.from_run = args.run_dir
            self.assertEqual(impact.record(args), 0)
            rebuilt = json.loads(Path(args.map).read_text())
            self.assertEqual(rebuilt['provenance'], original['provenance'])
            self.assertEqual(rebuilt['fingerprint'], original['fingerprint'])
            with patch.dict(os.environ, {'PYTHONPATH': str(Path(folder)/'different-import-path')}):
                with self.assertRaisesRegex(ValueError, 'runtime, environment'):
                    impact.record(args)
            summary_path = Path(args.run_dir)/'run'/'summary.json'
            summary = json.loads(summary_path.read_text())
            for provenance in (None, dict(summary['provenance'], unchanged=False)):
                summary_path.write_text(json.dumps(dict(summary, provenance=provenance)))
                with self.assertRaisesRegex(ValueError, 'source provenance'):
                    impact.record(args)
            summary_path.write_text(json.dumps(summary))
            write(test, test.read_text().replace('assertEqual(1, 1)', 'assertEqual(2, 2)'))
            git(root, 'commit', '-q', '-am', 'changed fixture')
            with self.assertRaisesRegex(ValueError, 'source provenance'):
                impact.record(args)
            self.assertEqual(json.loads(Path(args.map).read_text())['commit'], original['commit'])

    def test_source_mutation_during_tracing_cannot_produce_an_impact_map(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)/'tree'
            (root/'tectonics'/'src').mkdir(parents=True)
            write(root/'tectonics'/'tests'/'test_change.py', '''
                import pathlib, unittest
                class T(unittest.TestCase):
                    def test_changes_source(self):
                        path = pathlib.Path(__file__)
                        path.write_text(path.read_text() + '\\n# changed during the run\\n')
            ''')
            git(root, 'init', '-q')
            git(root, 'add', '-A')
            git(root, 'commit', '-q', '-m', 'fixture')
            args = SimpleNamespace(root=str(root), python=sys.executable, map=str(Path(folder)/'map.json'),
                                   from_run=None, run_dir=str(Path(folder)/'record'), workers=1, durations=None)
            with self.assertRaisesRegex(ValueError, 'source provenance'):
                impact.record(args)
            self.assertFalse(Path(args.map).exists())
            summary = json.loads((Path(args.run_dir)/'run'/'summary.json').read_text())
            self.assertFalse(summary['provenance']['unchanged'])


class CandidateVerifierTests(unittest.TestCase):
    def test_missing_impact_map_refuses_before_creating_a_run(self):
        with tempfile.TemporaryDirectory() as folder:
            work = Path(folder)/'work'
            with self.assertRaises(SystemExit):
                candidate.main(['--repo', folder, '--base', 'HEAD', '--combined', 'unused.patch',
                                '--python', sys.executable, '--tier', 'impact', '--work', str(work)])
            self.assertFalse(work.exists())

    def test_an_interrupted_tier_leaves_an_incomplete_summary(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder)/'repo'
            work = Path(folder)/'work'
            patch_path = Path(folder)/'candidate.patch'
            write(patch_path, 'diff --git a/x.py b/x.py\n')
            with patch.object(candidate.subprocess, 'run', return_value=Mock(returncode=0)), \
                    patch.object(candidate, 'git', return_value=''), \
                    patch.object(candidate, 'apply_all', return_value='same-tree'), \
                    patch.object(candidate, 'run_step', side_effect=KeyboardInterrupt):
                with self.assertRaises(KeyboardInterrupt):
                    candidate.main(['--repo', str(source), '--base', 'HEAD', '--combined', str(patch_path),
                                    '--python', sys.executable, '--tier', 'full', '--skip-static', '--work', str(work)])
            summary = json.loads((work/'summary.json').read_text())
            self.assertFalse(summary['completed'])
            self.assertFalse(summary['passed'])
            self.assertNotIn('tier', summary['steps'])

    def test_patch_paths_and_path_problems(self):
        data = b'diff --git a/x.py b/x.py\n--- a/x.py\n+++ b/x.py\ndiff --git a/old.txt b/new.txt\n'
        self.assertEqual(candidate.patch_paths(data), ['x.py', 'old.txt', 'new.txt'])
        self.assertEqual(candidate.path_problems(['ok/x.py']), [])
        self.assertEqual(len(candidate.path_problems(['../x', '/abs', '.atlas-dev/n.md', 'C:/x'])), 4)

    def test_chain_and_combined_agree_and_disagreements_fail(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)/'repo'
            write(root/'a.txt', 'one\n')
            git(root, 'init', '-q')
            git(root, 'add', '-A')
            git(root, 'commit', '-q', '-m', 'base')
            base = git(root, 'rev-parse', 'HEAD').strip()
            write(root/'a.txt', 'two\n')
            first = Path(folder)/'1.patch'
            first.write_bytes(subprocess.run(['git', 'diff'], cwd=root, capture_output=True, check=True).stdout)
            git(root, 'commit', '-q', '-am', 'two')
            write(root/'b.txt', 'new\n')
            git(root, 'add', '-A')
            second = Path(folder)/'2.patch'
            second.write_bytes(subprocess.run(['git', 'diff', '--cached'], cwd=root, capture_output=True,
                                              check=True).stdout)
            combined = Path(folder)/'c.patch'
            combined.write_bytes(subprocess.run(['git', 'diff', '--cached', base], cwd=root, capture_output=True,
                                                check=True).stdout)
            git(root, 'reset', '-q', '--hard', base)

            def verify(name, *patches, combined_patch=combined, expect=None):
                args = ['--repo', str(root), '--base', base, '--chain', *map(str, patches), '--combined',
                        str(combined_patch), '--python', sys.executable, '--tier', 'none', '--skip-static',
                        '--work', str(Path(folder)/name)]
                if expect:
                    args += ['--expect-tree', expect]
                code = candidate.main(args)
                return code, json.loads((Path(folder)/name/'summary.json').read_text(encoding='utf-8'))

            code, summary = verify('good', first, second)
            self.assertEqual(code, 0, summary)
            tree = summary['steps']['trees']['trees']['combined']
            self.assertEqual(summary['steps']['trees']['trees']['chain'], tree)
            self.assertEqual(summary['steps']['bytes_and_paths']['changed_paths'], ['a.txt', 'b.txt'])
            self.assertEqual(verify('expected', first, second, expect=tree[:8])[0], 0)
            self.assertEqual(verify('wrong-expectation', first, second, expect='0000000')[0], 1)
            code, summary = verify('short-chain', first)
            self.assertEqual(code, 1)
            self.assertFalse(summary['steps']['trees']['passed'])
            crlf = Path(folder)/'crlf.patch'
            crlf.write_bytes(combined.read_bytes().replace(b'new\n', b'new\r\n'))
            code, summary = verify('crlf', first, second, combined_patch=crlf)
            self.assertEqual(code, 1)
            self.assertTrue(any('CR byte' in p for p in summary['steps']['bytes_and_paths']['problems']))
            self.assertEqual(subprocess.run(['git', 'status', '--porcelain'], cwd=root, capture_output=True,
                                            text=True).stdout, '')          # the source repository is untouched
            with self.assertRaises(SystemExit):
                candidate.main(['--repo', str(root), '--base', base, '--combined', str(combined), '--python',
                                sys.executable, '--tier', 'none', '--work', str(root/'inside')])


if __name__ == '__main__':
    unittest.main()
