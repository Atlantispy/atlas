"""Mutant checks of release_closure_check: each violation class is found, the clean and exempt cases pass."""
import sys
import tempfile
import unittest
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import release_closure_check as C

CLEAN = '''
from atlas_tectonics import reuse
from atlas_tectonics.helpers_x import measure_faces
LIMIT = 3
def f(x):
    if not x:
        raise ValueError('x')
    y = reuse.execution_mode()
    return measure_faces(y)
'''
MUTANTS = {
    'banned-import': ['import unittest', 'from unittest import mock', 'from atlas_tectonics import test_thing',
                      'import atlas_tectonics.probe_flow', 'from atlas_tectonics.sub import measure_area',
                      'import heat_ref_r3', 'import importlib\nimportlib.import_module("test_x")'],
    'module-rebinding': ['from atlas_tectonics import reuse\nreuse.execution_mode = lambda: "strict"',
                         'import atlas_tectonics.reuse as R\nR.LIMIT += 1',
                         'from atlas_tectonics import reuse\nsetattr(reuse, "LIMIT", 2)',
                         'from atlas_tectonics import reuse\ndel reuse.LIMIT',
                         'from atlas_tectonics.reuse import ExecutionContext\nExecutionContext.verify = None',
                         'import atlas_tectonics\natlas_tectonics.reuse.LIMIT = 4'],
    'mock-patch': ['from unittest import mock\nwith mock.patch("x"):\n    pass'],
    'constant-rebinding': ['LIMIT = 1\ndef g():\n    global LIMIT\n    LIMIT = 2'],
    'assert': ['def h(x):\n    assert x'],
}


class ReleaseClosureCheck(unittest.TestCase):
    def package(self, root, files):
        package = Path(root) / 'atlas_tectonics'
        (package / 'sub').mkdir(parents=True)
        for name in ('__init__.py', 'reuse.py', 'helpers_x.py', 'sub/__init__.py', 'sub/measure_area.py',
                     'test_thing.py', 'probe_flow.py'):
            (package / name).write_text('LIMIT = 1\ndef measure_faces(y):\n    return y\n', encoding='utf-8')
        for name, text in files.items():
            (package / name).write_text(text, encoding='utf-8')
        return package

    def test_clean_and_exempt(self):
        with tempfile.TemporaryDirectory() as root:
            package = self.package(root, {'clean.py': CLEAN, 'execution.py':
                                          '_POOL_SLOTS = 0\ndef s():\n    global _POOL_SLOTS\n    _POOL_SLOTS += 1'})
            report = C.check(package)
            self.assertEqual(report['findings'], [], report['findings'])
            self.assertTrue(report['passed'])
            self.assertEqual(sorted(Path(p).name for p in report['excluded_from_release']),
                             ['measure_area.py', 'probe_flow.py', 'test_thing.py'])

    def test_each_mutant_is_found(self):
        for kind, texts in MUTANTS.items():
            for text in texts:
                with self.subTest(kind=kind, text=text), tempfile.TemporaryDirectory() as root:
                    report = C.check(self.package(root, {'mutant.py': text}))
                    kinds = {item['kind'] for item in report['findings'] if item['file'].endswith('/mutant.py')}
                    self.assertIn(kind, kinds, report['findings'])
                    self.assertFalse(report['passed'])

    def check_source(self, source, filename='mutant.py'):
        with tempfile.TemporaryDirectory() as root:
            return C.check(self.package(root, {filename: source}))

    def test_import_aliases_and_keyword_name(self):
        for source in (
            'from importlib import import_module as load\nload("pytest")',
            'import importlib as il\nil.import_module(name="pytest")',
            'from builtins import __import__ as load\nload("pytest")',
            'import importlib\nload = importlib.import_module\nload("pytest")',
        ):
            with self.subTest(source=source):
                report = self.check_source(source)
                self.assertFalse(report['passed'])
                self.assertEqual(report['counts']['banned-import'], 1)

    def test_dynamic_module_and_simple_alias_rebinding(self):
        for source in (
            'import importlib\nr = importlib.import_module("atlas_tectonics.reuse")\nr.execution_mode = None',
            'from importlib import import_module as load\nr = load("atlas_tectonics.reuse")\nsetattr(r,"LIMIT",2)',
            'from atlas_tectonics import reuse\nr = reuse\ndel r.LIMIT',
            'import importlib\nr: object = importlib.import_module("atlas_tectonics.reuse")\nr.LIMIT=3',
            'import importlib\n(r := importlib.import_module("atlas_tectonics.reuse"))\nr.LIMIT=3',
            'import atlas_tectonics.reuse\nr=atlas_tectonics.reuse\nr.LIMIT=3',
        ):
            with self.subTest(source=source):
                report = self.check_source(source)
                self.assertFalse(report['passed'])
                self.assertEqual(report['counts']['module-rebinding'], 1)

    def test_unresolved_imports_fail_closed(self):
        for source in (
            'import importlib\nname="pytest"\nimportlib.import_module(name)',
            'from importlib import import_module as load\nload(name)',
            'import importlib\nimportlib.import_module(".reuse", package=unknown)',
            '__import__("reuse", level=1)',
            'from importlib import *',
        ):
            with self.subTest(source=source):
                report = self.check_source(source)
                self.assertFalse(report['passed'])
                self.assertIn('unresolved-import', report['counts'])

    def test_relative_package_init_and_module(self):
        for filename in ('__init__.py', 'clean.py'):
            for source, kind in (
                ('from . import test_thing', 'banned-import'),
                ('from . import reuse\nreuse.LIMIT=3', 'module-rebinding'),
                ('import importlib\nimportlib.import_module(".test_thing", __package__)', 'banned-import'),
                ('import importlib\nr=importlib.import_module(".reuse", __package__)\nr.LIMIT=3', 'module-rebinding'),
            ):
                with self.subTest(filename=filename, source=source):
                    report = self.check_source(source, filename)
                    self.assertFalse(report['passed'])
                    self.assertIn(kind, report['counts'])
        self.assertEqual(C._resolve('reuse', 2, 'atlas_tectonics.sub', True), 'atlas_tectonics.reuse')
        self.assertEqual(C._resolve('reuse', 2, 'atlas_tectonics.sub.worker'), 'atlas_tectonics.reuse')

    def test_literal_legitimate_imports_remain_supported(self):
        report = self.check_source('import importlib as il\nfrom importlib import import_module as load\n'
                                   'a=load("json")\nb=il.import_module(".reuse", __package__)\n'
                                   'c=load(".reuse", package="atlas_tectonics")\ny=b.execution_mode()')
        self.assertTrue(report['passed'], report)
        self.assertEqual(report['dynamic_imports'], [])

    def test_constant_destructuring_and_deletion(self):
        for change in ('LIMIT, x = 2, 3', '[x, [LIMIT]] = [1, [2]]',
                       '*LIMIT, x = [1, 2]', 'del LIMIT'):
            with self.subTest(change=change):
                report = self.check_source('LIMIT=1\ndef f():\n global LIMIT\n '+change)
                self.assertFalse(report['passed'])
                self.assertEqual(report['counts']['constant-rebinding'], 1)

    def test_exemptions_are_exact(self):
        source = '_POOL_SLOTS=0\ndef f():\n global _POOL_SLOTS\n _POOL_SLOTS, x = 1, 2\n del _POOL_SLOTS'
        self.assertTrue(self.check_source(source, 'execution.py')['passed'])
        self.assertFalse(self.check_source(source, 'other.py')['passed'])
        self.assertFalse(self.check_source('OTHER=0\ndef f():\n global OTHER\n OTHER=1', 'execution.py')['passed'])

    def test_missing_empty_and_wrong_package_roots(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            empty = root / 'atlas_tectonics'
            for target in (empty, root):
                report = C.check(target)
                self.assertFalse(report['passed'])
                self.assertEqual(report['counts'], {'invalid-package': 1})
            empty.mkdir()
            self.assertFalse(C.check(empty)['passed'])
            (root / '__init__.py').write_text('', encoding='utf8')
            self.assertFalse(C.check(root)['passed'])

    def test_cli_exit_status_for_invalid_and_unresolved(self):
        with tempfile.TemporaryDirectory() as root:
            package = self.package(root, {'bad.py': 'import importlib\nimportlib.import_module(name)'})
            for target in (package, Path(root) / 'absent'):
                done = subprocess.run([sys.executable, '-B', C.__file__, str(target)],
                                      capture_output=True, text=True, check=False, timeout=10)
                self.assertEqual(done.returncode, 1, done.stderr)
                self.assertIn('"passed": false', done.stdout)


if __name__ == '__main__':
    unittest.main()
