"""Focused release-policy checks of a composition, strict against a disposable packaged payload.

Each scenario runs in its own process (scenario.py): in strict with the successor's src, and in release as an
allow-listed tools entry of a payload laid out as reuse._packaged_mode requires (Atlas.exe, resources/python,
resources/atlas/tectonics with the marker). The payload copies the successor's src byte for byte and is deleted
afterwards. Small: one process at a time, well under 1 GiB, about a minute in all.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# ATLAS_COMPOSITION: the composition root to check (its src/ and helpers/); a discrimination run points it at a
# copy of the unchanged base. ATLAS_VENV: the virtual environment whose launcher the payload copies (default: the
# running interpreter's).
SUCCESSOR = Path(os.environ.get('ATLAS_COMPOSITION', '.'))
ENV = Path(os.environ.get('ATLAS_VENV', sys.prefix))
SCENARIO = Path(__file__).resolve().parent / 'scenario.py'
MARKER = {'schema': 'atlas.desktop-runtime.v1', 'identity_mode': 'release'}


def _payload(base):
    tectonics = base / 'resources' / 'atlas' / 'tectonics'
    shutil.copytree(SUCCESSOR / 'src', tectonics / 'src', ignore=shutil.ignore_patterns('__pycache__'))
    (tectonics / '.desktop-runtime.json').write_text(json.dumps(MARKER), encoding='utf-8')
    (tectonics / 'tools').mkdir()
    for name in ('new_world.py', 'other_tool.py'):
        shutil.copyfile(SCENARIO, tectonics / 'tools' / name)
    python = base / 'resources' / 'python'
    python.mkdir()
    shutil.copyfile(ENV / 'Scripts' / 'python.exe', python / 'python.exe')
    for folder in (python, base / 'resources'):
        shutil.copyfile(ENV / 'pyvenv.cfg', folder / 'pyvenv.cfg')
    (base / 'Atlas.exe').write_bytes(b'')
    return tectonics, python / 'python.exe'


@unittest.skipUnless((SUCCESSOR / 'src' / 'atlas_tectonics' / 'reuse.py').exists(),
                     'set ATLAS_COMPOSITION to a composition root')
class ReleasePayload(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='p39pl-')
        cls.base = Path(cls.temp.name)
        cls.tectonics, cls.packaged_python = _payload(cls.base)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def run_scenario(self, name, *, release, flags=(), entry='new_world.py'):
        work = Path(tempfile.mkdtemp(prefix='w-', dir=self.base))
        env = {k: v for k, v in os.environ.items() if k not in ('PYTHONOPTIMIZE', 'PYTHONPATH', 'PYTHONHOME')}
        env['PYTHONHASHSEED'] = '0'
        # The identity capture imports every package module, including the bare-name _fixtures/tests ones
        # (E1/E2: a release manifest leaves them out; held), so both arms put that folder on the path.
        if release:
            python, script, src = self.packaged_python, self.tectonics / 'tools' / entry, self.tectonics / 'src'
            extra = (ENV / 'Lib' / 'site-packages',)
        else:
            python, script, src, extra = ENV / 'Scripts' / 'python.exe', SCENARIO, SUCCESSOR / 'src', ()
        env['PYTHONPATH'] = os.pathsep.join(map(str, (src, src / 'atlas_tectonics' / '_fixtures' / 'tests',
                                                      SUCCESSOR / 'helpers', *extra)))
        done = subprocess.run([str(python), '-B', *flags, str(script), name, str(work)], env=env, cwd=str(work),
                              capture_output=True, text=True, timeout=300, check=False)
        self.assertEqual(done.returncode, 0, done.stderr[-2000:])
        lines = [line for line in done.stdout.splitlines() if line.startswith('{')]
        self.assertTrue(lines, done.stdout[-2000:] + done.stderr[-2000:])
        return json.loads(lines[-1])

    def both(self, name):
        strict, release = self.run_scenario(name, release=False), self.run_scenario(name, release=True)
        self.assertTrue(strict.get('ok'), strict)
        self.assertTrue(release.get('ok'), release)
        self.assertEqual((strict['mode'], release['mode']), ('strict', 'release'))
        return strict, release

    def test_mode_and_optimised_python(self):
        self.both('mode')
        refused = self.run_scenario('mode', release=True, flags=('-O',))
        self.assertFalse(refused['ok'])
        self.assertIn('release mode refuses optimised Python', refused['error'])
        self.assertEqual(self.run_scenario('mode', release=False, flags=('-O',))['mode'], 'strict')

    def test_entries(self):
        unlisted = self.run_scenario('mode', release=True, entry='other_tool.py')
        self.assertFalse(unlisted['ok'])
        self.assertIn('restricted to packaged desktop commands', unlisted['error'])
        worker = self.run_scenario('worker-entry', release=True)
        self.assertEqual((worker['ok'], worker['mode']), (True, 'release'))

    def test_evidence_refuses_release(self):
        strict, release = self.both('evidence')
        self.assertIsNone(strict['refused'])
        self.assertIn('scientific evidence requires strict execution mode', release['refused'])

    def test_source_hold_lifetime(self):
        strict, release = self.both('hold')
        self.assertTrue(strict['writable_after_close'])
        self.assertFalse(release['writable_after_close'])
        self.assertEqual(strict['identity'], release['identity'])

    def test_drift_refuses_publication_boundary(self):
        for result in self.both('drift'):
            self.assertIn('loaded implementation changed', result['drifted'])
            self.assertEqual(result['restored'], 'ok')

    def test_context_closed_meanwhile_is_skipped(self):
        for result in self.both('race'):
            self.assertEqual(result['closed_meanwhile'], 'skipped')

    def test_drift_refuses_seal_and_promote(self):
        for result in self.both('seal'):
            self.assertIn('loaded implementation changed', result['seal_drifted'])
            self.assertIn('loaded implementation changed', result['promote_drifted'])
            self.assertTrue(result['catalog_unchanged_while_drifted'])
            self.assertEqual(result['promoted_after_restore'], 0)

    def test_matched_workload_byte_identical(self):
        strict, release = self.both('parity')
        self.assertEqual(len(set(strict['digests'])), 1, strict)
        self.assertEqual(strict['digests'], release['digests'])
        self.assertEqual(strict['identity'], release['identity'])


if __name__ == '__main__':
    unittest.main()
