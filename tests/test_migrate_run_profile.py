"""tools/runs/migrate_run_profile.py: the moved field set and its four refusals."""
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('migrate_run_profile', ROOT / 'tools/runs/migrate_run_profile.py')
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


class MigrateRunProfileTest(unittest.TestCase):
    def setUp(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.dir = Path(holder.name)
        manifest = json.dumps({'completed_query_store': 'columnar', 'files': {'a.py': 'x'},
                               'installed_binding': {'qualification_status': 'diagnostic'}}).encode()
        (self.dir / 'm.json').write_bytes(manifest)
        self.profile = {'schema': 'atlas.fresh-interval-profile.v2', 'workspace': str(self.dir),
                        'source_manifest': {'path': 'm.json', 'sha256': _sha(manifest)}, 'native_root': 'n'}
        self.old = self.dir / 'old.json'
        self.raw = json.dumps(self.profile, sort_keys=True, indent=2).encode() + b'\n'
        self.old.write_bytes(self.raw)
        self.new = self.dir / 'new.json'

    def test_moves_the_two_values_and_keeps_the_form(self):
        digest = M.migrate(self.old, _sha(self.raw), self.new)
        out = self.new.read_bytes()
        expected = {k: v for k, v in self.profile.items() if k != 'source_manifest'}
        expected.update(completed_query_store='columnar', qualification_status='diagnostic')
        self.assertEqual(json.loads(out), expected)
        self.assertEqual(out, json.dumps(expected, sort_keys=True, indent=2).encode() + b'\n')
        self.assertEqual(digest, _sha(out))
        self.assertEqual(self.old.read_bytes(), self.raw)

    def test_refusals(self):
        with self.assertRaisesRegex(SystemExit, 'profile bytes differ'):
            M.migrate(self.old, '0' * 64, self.new)
        bad = dict(self.profile, source_manifest={'path': 'm.json', 'sha256': '0' * 64})
        raw = json.dumps(bad, sort_keys=True, indent=2).encode() + b'\n'
        self.old.write_bytes(raw)
        with self.assertRaisesRegex(SystemExit, 'source manifest bytes differ'):
            M.migrate(self.old, _sha(raw), self.new)
        self.old.write_bytes(self.raw)
        M.migrate(self.old, _sha(self.raw), self.new)
        with self.assertRaisesRegex(SystemExit, 'already moved'):
            M.migrate(self.new, _sha(self.new.read_bytes()), self.dir / 'again.json')
        with self.assertRaises(FileExistsError):
            M.migrate(self.old, _sha(self.raw), self.new)


if __name__ == '__main__':
    unittest.main()
