"""Tests of the read-only tectonics environment checker, not tests of Atlas's generator."""
from __future__ import annotations

import contextlib
from copy import deepcopy
import importlib.metadata as metadata
import io
import json
from pathlib import Path
import re
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools import check_tectonics_environment as guard

LOCK = {
    'schema': guard.SCHEMA, 'status': 'synthetic', 'observed': '2026-09-26',
    'declared_by': 'pyproject.toml', 'provenance': 'synthetic fixture',
    'scope': {'implementation': 'cpython', 'python': '3.12.14', 'sys_platform': 'win32',
              'machine': 'AMD64', 'pointer_bits': 64},
    'observation': {'system': 'Windows', 'release': '11', 'os_version': '10.0.26200',
                    'compiler': 'MSC', 'build': 'main'},
    'routes': {
        'core': {'requirements': 'req/core.txt', 'declared': 'dependencies', 'includes': [],
                 'note': 'core', 'packages': {
                     'alpha': {'version': '1.0', 'wheel': 'cp312-cp312-win_amd64', 'status': 'tested',
                               'direct': True, 'evidence': ['evidence.json']},
                     'beta-lib': {'version': '2.0.post1', 'wheel': 'py3-none-any',
                                  'status': 'installed', 'required_by': ['alpha']}}},
        'visual': {'requirements': 'req/visual.txt', 'declared': 'extra visual', 'includes': ['core'],
                   'note': 'visual', 'packages': {
                       'gamma': {'version': '3.0', 'wheel': 'py2.py3-none-any', 'status': 'installed',
                                 'direct': True}}}},
    'not_pinned': {'pip': 'installer'},
    'unpinned_tools': {},
    'limits': ['synthetic only'],
}
FACTS = {'implementation': 'cpython', 'python': '3.12.14', 'sys_platform': 'win32', 'machine': 'AMD64',
         'pointer_bits': 64, 'system': 'Windows', 'release': '11', 'os_version': '10.0.26200',
         'compiler': 'MSC', 'build': 'main'}
CORE = '# comment\n--only-binary=:all:\nalpha==1.0  # inline comment\nBeta_Lib==2.0.post1\n'
VISUAL = '-r core.txt\n\ngamma==3.0\n'
NUMERICAL = {'numpy', 'scipy', 'numba', 'llvmlite', 'blosc2', 'shapely', 'threadpoolctl',
             'psutil', 'matplotlib', 'atlas_tectonics'}


def dist_info(site: Path, name: str, version: str, tags=('py3-none-any',)) -> None:
    folder = site / f"{name.replace('-', '_')}-{version}.dist-info"
    folder.mkdir(parents=True)
    (folder / 'METADATA').write_text(f'Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n',
                                     encoding='utf-8')
    if tags is not None:
        (folder / 'WHEEL').write_text('Wheel-Version: 1.0\n' + ''.join(f'Tag: {t}\n' for t in tags),
                                      encoding='utf-8')


class TectonicsEnvironmentTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / 'repo'
        self.site = Path(temp.name) / 'site'
        self.lock = deepcopy(LOCK)
        self.facts = dict(FACTS)
        self.write('req/core.txt', CORE)
        self.write('req/visual.txt', VISUAL)
        dist_info(self.site, 'alpha', '1.0', ('cp312-cp312-win_amd64',))
        dist_info(self.site, 'beta_lib', '2.0.post1')
        dist_info(self.site, 'gamma', '3.0', ('py2-none-any', 'py3-none-any'))
        dist_info(self.site, 'pip', '26.0')

    def write(self, relative, text):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')

    def replace_dist(self, name, version, tags=('py3-none-any',)):
        for folder in self.site.glob(f"{name.replace('-', '_')}-*.dist-info"):
            shutil.rmtree(folder)
        if version is not None:
            dist_info(self.site, name, version, tags)

    def run_check(self, routes=('core', 'visual'), paths=()):
        guard.validate(self.lock)
        selected = guard.selected_routes(self.lock, routes)
        files = guard.check_files(self.root, self.lock, selected)
        found = guard.installed(metadata.distributions(path=[str(self.site), *map(str, paths)]))
        return guard.check(self.lock, selected, self.facts, found, files)

    def test_matching_environment_passes_with_tested_and_installed_counts(self):
        failures, notes, lines = self.run_check()
        self.assertEqual(failures, [])
        self.assertIn('core       matched 2 pinned distributions (1 tested, 1 installed only)', lines)
        self.assertIn('visual     matched 1 pinned distribution (0 tested, 1 installed only)', lines)
        self.assertTrue(lines[0].startswith('scope      cpython 3.12.14, win32, AMD64, 64-bit'))
        self.assertEqual(notes, ['1 other installed distribution outside the checked routes, not checked'])
        self.assertEqual(guard.selected_routes(self.lock, ['visual']), ['core', 'visual'])

    def test_version_problems_are_readable_failures(self):
        cases = {
            'core alpha: installed 1.1, pinned 1.0': lambda: self.replace_dist('alpha', '1.1'),
            'visual gamma: not installed; pinned 3.0': lambda: self.replace_dist('gamma', None),
        }
        for message, change in cases.items():
            with self.subTest(message):
                self.setUp()
                change()
                self.assertIn(message, self.run_check()[0])
        self.setUp()
        other = self.site.parent / 'other-site'
        dist_info(other, 'alpha', '1.1', ('cp312-cp312-win_amd64',))
        self.assertIn('core alpha: several installed versions (1.0, 1.1); pinned 1.0',
                      self.run_check(paths=[other])[0])

    def test_scope_is_enforced_but_provenance_differences_are_notes(self):
        for key, value in (('python', '3.12.10'), ('sys_platform', 'linux'), ('machine', 'x86_64'),
                           ('implementation', 'pypy'), ('pointer_bits', 32)):
            with self.subTest(key=key):
                self.facts = dict(FACTS, **{key: value})
                failures = self.run_check()[0]
                self.assertEqual(len(failures), 1, failures)
                self.assertTrue(failures[0].startswith(f'scope {key}: running {value!r}'))
        self.facts = dict(FACTS, os_version='10.0.22631', build='other build')
        failures, notes, _ = self.run_check()
        self.assertEqual(failures, [])
        self.assertTrue(any(n.startswith("os_version is '10.0.22631'") for n in notes), notes)
        self.assertTrue(any(n.startswith("build is 'other build'") for n in notes), notes)

    def test_same_version_from_a_different_build_is_only_a_note(self):
        for tags, shown in ((('cp312-abi3-win_amd64',), 'cp312-abi3-win_amd64'), (None, 'none')):
            with self.subTest(tags=tags):
                self.replace_dist('alpha', '1.0', tags)
                failures, notes, _ = self.run_check()
                self.assertEqual(failures, [])
                self.assertIn(f'alpha 1.0: installed wheel tag {shown}, observed cp312-cp312-win_amd64; '
                              'same version, different build', notes)

    def test_pip_inputs_must_match_the_record(self):
        for text, missing in (('alpha==1.1\nbeta-lib==2.0.post1\n', 'alpha'),
                              ('alpha==1.0\n', 'beta-lib'),
                              (CORE + 'delta==1.0\n', 'delta')):
            with self.subTest(text=text):
                self.write('req/core.txt', guard.ONLY_BINARY + '\n' + text)
                self.assertTrue(any(f.startswith('lock core: req/core.txt disagrees with the record for')
                                    and missing in f for f in self.run_check()[0]))
        for line in ('alpha>=1.0', 'alpha==1.0; sys_platform == "win32"', 'alpha[extra]==1.0',
                     'alpha==1.0 --hash=sha256:' + 'a' * 64, '--index-url https://example.invalid/simple',
                     '-e .', '-r ../core.txt', '-r core.txt', 'alpha==1.0\nAlpha==1.0'):
            with self.subTest(line=line):
                self.write('req/core.txt', line + '\n')
                with self.assertRaises(guard.LockError):
                    self.run_check()

    def test_wheel_only_policy_is_required_in_selected_include_tree(self):
        self.write('req/core.txt', CORE.replace(guard.ONLY_BINARY + '\n', ''))
        with self.assertRaisesRegex(guard.LockError, 'wheel-only'):
            self.run_check()
        # A directive inherited from core protects the visual installation too.
        self.write('req/core.txt', CORE)
        self.assertEqual(guard.check_files(self.root, self.lock, ['visual']), [])

    def test_include_traversal_refuses_repeated_and_excessive_files(self):
        self.write('req/empty.txt', '# empty include\n')
        self.write('req/core.txt', CORE + '-r empty.txt\n-r empty.txt\n')
        with self.assertRaisesRegex(guard.LockError, 'repeated include'):
            self.run_check()
        includes = []
        for index in range(33):
            name = f'part{index}.txt'
            self.write('req/' + name, '# empty include\n')
            includes.append('-r ' + name + '\n')
        self.write('req/core.txt', CORE + ''.join(includes))
        with self.assertRaisesRegex(guard.LockError, 'include file limit'):
            self.run_check()

    def test_malformed_record_is_refused(self):
        core = lambda lock: lock['routes']['core']
        alpha = lambda lock: core(lock)['packages']['alpha']
        beta = lambda lock: core(lock)['packages']['beta-lib']
        changes = {
            'schema': lambda lock: lock.update(schema='other'),
            'unknown field': lambda lock: lock.update(repin=True),
            'scope key': lambda lock: lock['scope'].pop('machine'),
            'pointer bits text': lambda lock: lock['scope'].update(pointer_bits='64'),
            'tested without evidence': lambda lock: alpha(lock).pop('evidence'),
            'installed with evidence': lambda lock: beta(lock).update(evidence=['evidence.json']),
            'direct and required_by': lambda lock: alpha(lock).update(required_by=['beta-lib']),
            'neither direct nor required_by': lambda lock: beta(lock).pop('required_by'),
            'direct false': lambda lock: alpha(lock).update(direct=False),
            'unknown status': lambda lock: alpha(lock).update(status='verified'),
            'unnormalised name': lambda lock: core(lock)['packages'].update(Beta_Lib=beta(lock)),
            'pinned twice': lambda lock: lock['routes']['visual']['packages'].update(alpha=alpha(lock)),
            'unknown include': lambda lock: lock['routes']['visual'].update(includes=['gpu']),
            'self include': lambda lock: core(lock).update(includes=['core']),
            'nested include': lambda lock: core(lock).update(includes=['visual']),
            'unknown requirer': lambda lock: beta(lock).update(required_by=['omega']),
            'loose version': lambda lock: alpha(lock).update(version='latest'),
            'no limits': lambda lock: lock.update(limits=[]),
            'unknown pin field': lambda lock: alpha(lock).update(sha256='a' * 64),
        }
        for name, change in changes.items():
            with self.subTest(name):
                lock = deepcopy(LOCK)
                change(lock)
                with self.assertRaises(guard.LockError):
                    guard.validate(lock)
        for body in ('{"schema": 1, "schema": 2}', '{"value": 1e999}', '{"value": NaN}', '{'):
            with self.subTest(body=body):
                self.write('lock.json', body)
                with self.assertRaises(guard.LockError):
                    guard.load_lock(self.root, 'lock.json')
        with self.assertRaises(guard.LockError):
            guard.selected_routes(self.lock, ['gpu'])

    def test_cli_reads_metadata_only_imports_nothing_numerical_and_writes_nothing(self):
        self.write('lock.json', json.dumps(self.lock))
        arguments = ['--root', str(self.root), '--lock', 'lock.json', '--all']
        # Replace only the checker's module reference, never importlib.metadata itself.
        synthetic = SimpleNamespace(distributions=lambda: metadata.distributions(path=[str(self.site)]))

        def snapshot():
            return {p: p.read_bytes() if p.is_file() else None
                    for base in (self.root, self.site) for p in base.rglob('*')}

        before, modules = snapshot(), set(sys.modules)
        output = io.StringIO()
        with patch.object(guard, 'metadata', synthetic), \
                patch.object(guard, 'interpreter_facts', lambda: dict(FACTS)), \
                contextlib.redirect_stdout(output):
            self.assertEqual(guard.main(arguments), 0)
        self.assertEqual(snapshot(), before)
        self.assertFalse({name.split('.')[0] for name in set(sys.modules) - modules} & NUMERICAL)
        for fragment in ('PASS: installed metadata matches lock.json for core, visual',
                         'not native-binary identity', 'nothing was installed or changed'):
            self.assertIn(fragment, output.getvalue())
        errors = io.StringIO()
        with patch.object(guard, 'metadata', synthetic), \
                patch.object(guard, 'interpreter_facts', lambda: dict(FACTS, python='3.12.10')), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(errors):
            self.assertEqual(guard.main(arguments), 1)
            self.assertEqual(guard.main(['--root', str(self.root), '--lock', 'absent.json']), 1)
        self.assertEqual(snapshot(), before)
        self.assertIn('Nothing was installed, upgraded or repinned', errors.getvalue())

    def test_checked_in_record_matches_pyproject_evidence_and_privacy(self):
        repository = Path(__file__).resolve().parents[1]
        lock = guard.load_lock(repository)
        routes = guard.selected_routes(lock, list(lock['routes']))
        self.assertEqual(guard.check_files(repository, lock, routes), [])
        try:
            import tomllib
        except ImportError:  # Python 3.10 has no TOML reader; the other checks still ran.
            self.skipTest('tomllib unavailable')
        project = tomllib.loads((repository / lock['declared_by']).read_text(encoding='utf-8'))['project']
        declared = {'core': project['dependencies'], **project['optional-dependencies']}
        for route, spec in lock['routes'].items():
            names = {guard.normal(re.match(r'[A-Za-z0-9._-]+', text).group()) for text in declared[route]}
            direct = {name for name, pin in spec['packages'].items() if pin.get('direct')}
            self.assertEqual(direct, names, route)
            for name, pin in spec['packages'].items():
                for evidence in pin.get('evidence', ()):
                    text = (repository / evidence).read_text(encoding='utf-8')
                    self.assertIn(f'"{name}": "{pin["version"]}"', text, f'{name} in {evidence}')
        for relative in [guard.DEFAULT_LOCK] + [spec['requirements'] for spec in lock['routes'].values()]:
            text = (repository / relative).read_text(encoding='utf-8')
            self.assertIsNone(re.search(r'[A-Za-z]:[\\/]|\\\\|/home/|/Users/', text), relative)


if __name__ == '__main__':
    unittest.main()
