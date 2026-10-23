"""Disposable standard-library source-construction controls; no Atlas imports."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import build_selection as B


class MaterialiserTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='combined-builder-test-')
        self.addCleanup(self.temporary.cleanup)
        self.repo = Path(self.temporary.name)
        real_repo = Path(B.__file__).resolve().parents[4]
        shared_path = self.repo / B.SHARED
        shared_path.parent.mkdir(parents=True)
        shared_path.write_bytes((real_repo / B.SHARED).read_bytes())
        self.utilities = B.shared(self.repo)
        self.output = self.repo / 'new-tree'
        self.entries = []
        for name in ('src/atlas_tectonics/example.py', 'helpers/example.py'):
            raw = b'raise AssertionError("Source construction must not execute me")\n'
            path = self.repo / 'inputs' / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            self.entries.append(dict(member='source/' + name,
                public_path=path.relative_to(self.repo).as_posix(), public_sha256=self.utilities.digest(raw)))
        self.mapping = dict(schema=B.SCHEMA, selected_members=2, source_maps=[],
            entries=self.entries, public_selection_sha256=self.utilities.generation(self.entries),
            **dict.fromkeys(B.FLAGS, False))
        self.map_path = self.repo / B.PREFIX / 'SOURCE-MAP.json'
        self.map_path.parent.mkdir(parents=True)

    def save(self, mapping=None):
        mapping = self.mapping if mapping is None else mapping
        raw = (json.dumps(mapping, indent=2) + '\n').encode()
        self.map_path.write_bytes(raw)
        return self.utilities.digest(raw)

    def test_build_complete_layout_and_refuse_existing(self):
        with patch.object(B, 'MAP_SHA', self.save()):
            self.assertEqual(B.materialise(self.repo, self.output)['files'], 2)
            manifest = json.loads((self.output / 'SOURCE-MANIFEST.json').read_bytes())
            self.assertEqual(len(manifest['files']), 2)
            for name, pin in manifest['files'].items():
                self.assertEqual(self.utilities.digest((self.output / name).read_bytes()), pin)
            with self.assertRaises(FileExistsError):
                B.materialise(self.repo, self.output)

    def test_map_content_and_authority_tampering_refuse(self):
        pin = self.save()
        self.map_path.write_bytes(self.map_path.read_bytes() + b' ')
        with patch.object(B, 'MAP_SHA', pin), self.assertRaisesRegex(ValueError, 'reviewed bytes'):
            B.materialise(self.repo, self.output)
        forged = copy.deepcopy(self.mapping)
        forged['runtime_admission'] = True
        with patch.object(B, 'MAP_SHA', self.save(forged)), self.assertRaisesRegex(ValueError, 'authority'):
            B.materialise(self.repo, self.output)
        self.assertFalse(self.output.exists())

    def test_payload_drift_and_duplicate_members_refuse(self):
        with patch.object(B, 'MAP_SHA', self.save()):
            (self.repo / self.entries[0]['public_path']).write_bytes(b'changed\n')
            with self.assertRaisesRegex(ValueError, 'source changed'):
                B.materialise(self.repo, self.output)
        forged = copy.deepcopy(self.mapping)
        forged['entries'].append(dict(self.entries[0]))
        with patch.object(B, 'MAP_SHA', self.save(forged)), self.assertRaisesRegex(ValueError, 'Duplicate'):
            B.materialise(self.repo, self.output)
        self.assertFalse(self.output.exists())

    def test_traversal_and_changed_shared_tool_refuse(self):
        forged = copy.deepcopy(self.mapping)
        forged['entries'][0]['public_path'] = '../escape.py'
        forged['public_selection_sha256'] = self.utilities.generation(forged['entries'])
        with patch.object(B, 'MAP_SHA', self.save(forged)), self.assertRaises(ValueError):
            B.materialise(self.repo, self.output)
        (self.repo / B.SHARED).write_bytes(b'raise AssertionError("must not execute")\n')
        with self.assertRaisesRegex(ValueError, 'tool changed'):
            B.materialise(self.repo, self.output)

    def test_write_failure_cleans_staging_without_output(self):
        pin = self.save()
        original = Path.write_bytes
        def fail(path, raw):
            if '.combined-selection-' in str(path):
                raise OSError('injected write failure')
            return original(path, raw)
        with patch.object(B, 'MAP_SHA', pin), patch.object(Path, 'write_bytes', fail):
            with self.assertRaisesRegex(OSError, 'injected'):
                B.materialise(self.repo, self.output)
        self.assertFalse(self.output.exists())
        self.assertFalse(list(self.repo.glob('.combined-selection-*')))

    def test_cli_failure_exit_and_no_output(self):
        self.save()
        result = subprocess.run([sys.executable, '-B', B.__file__, '--repo', str(self.repo),
                                 '--output', str(self.output)], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('refused', result.stderr)
        self.assertFalse(self.output.exists())


if __name__ == '__main__':
    unittest.main()
