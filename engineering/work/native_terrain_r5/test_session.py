"""Focused shared-control ownership, exact numerical parity and portable export."""
from copy import deepcopy
from dataclasses import replace
from fractions import Fraction as F
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from work.native_terrain_r2 import provenance as numerical_p, test_evolve as fixture
from work.native_terrain_r3 import session as r3
from work.native_terrain_r4 import session as r4
from . import session as s, provenance as p, integrity
from .history import History


class SessionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.case = fixture.ContinuingStateTests
        cls.case.setUpClass()
        cls.addClassCleanup(cls.case.doClassCleanups)
        cls.folder = tempfile.TemporaryDirectory(prefix='r5-source-')
        cls.addClassCleanup(cls.folder.cleanup)
        root = Path(cls.folder.name)
        legacy = root / 'legacy.json'
        legacy.write_bytes(numerical_p.encoded({'envelope': cls.case.first}))
        r3path = root / 'r3/checkpoint.json'
        r3.save(r3path, r3.import_legacy(legacy, r3path.parent))
        cls.original_path = root / 'r4/checkpoint.json'
        r4.save(cls.original_path, r4.import_r3(r3path, cls.original_path.parent))
        cls.original_bytes = cls.original_path.read_bytes()

    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix='r5-session-')
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.target = self.root / 'a/checkpoint.json'
        self.current = s.save(self.target, s.import_r4(self.original_path, self.root / 'shared'))

    def test_lossless_branch_advance_and_restart(self):
        before = self.current.wrapper['envelope']['body']
        child = s.fork(self.current, self.root / 'b/checkpoint.json')
        self.assertEqual(integrity.scientific_sha(before), self.case.first['body_sha256'])
        self.assertEqual(child.wrapper['envelope']['body']['history'].root, before['history'].root)
        self.assertIsNot(child.wrapper['envelope']['body']['history'], before['history'])
        expected = self.case.executor.advance(self.case.first, F(1), self.case.acceptance, operation_id='r5-next')
        following = child.advance(self.case.executor, F(1), self.case.acceptance, operation_id='r5-next')
        saved = s.save(child.control_path, following)
        restarted = s.load(child.control_path)
        self.assertEqual(integrity.scientific_sha(restarted.wrapper['envelope']['body']), expected['body_sha256'])
        self.assertEqual(saved.wrapper['envelope']['body_sha256'], restarted.wrapper['envelope']['body_sha256'])
        self.assertEqual(len(before['history']), 1)
        self.assertEqual(len(s.load(self.target).wrapper['envelope']['body']['history']), 1)
        self.assertEqual(self.original_path.read_bytes(), self.original_bytes)

    def test_export_is_self_contained_and_relocatable(self):
        exported = s.export(self.current, self.root / 'exported')
        original_sha = self.current.wrapper['envelope']['body_sha256']
        self.assertEqual(exported.wrapper['envelope']['body_sha256'], original_sha)
        control = json.loads(Path(exported.control_path).read_bytes())
        self.assertEqual(control['history_store']['path'], 'store')
        shutil.move(self.root / 'exported', self.root / 'moved')
        # Break only this temporary test store; the moved export must still load.
        history = self.current.wrapper['envelope']['body']['history']
        (history.root / history.refs[0]['path']).unlink()
        moved = s.load(self.root / 'moved/checkpoint.json')
        self.assertEqual(moved.wrapper['envelope']['body_sha256'], original_sha)
        self.assertEqual(integrity.scientific_sha(moved.wrapper['envelope']['body']), self.case.first['body_sha256'])
        with self.assertRaises((ValueError, FileNotFoundError)):
            s.load(self.target)

    def test_tampering_missing_objects_and_traversal_fail_closed(self):
        history = self.current.wrapper['envelope']['body']['history']
        path = history.root / history.refs[0]['path']
        raw = path.read_bytes()
        path.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
        with self.assertRaises(ValueError):
            s.save(self.target, self.current)
        with self.assertRaises(ValueError):
            self.current.advance(self.case.executor, F(1), self.case.acceptance, operation_id='bad')
        path.write_bytes(raw)
        with self.assertRaises(ValueError):
            s._store_root({'schema': s.STORE_SCHEMA, 'path': '../shared'}, self.target)
        refs = history.refs
        refs[0]['path'] = '../escape.zst'
        with self.assertRaises(ValueError):
            History.from_refs(history.root, refs)

    def test_owner_prefix_store_source_and_schema_guards(self):
        with r3._control_lock(self.target):
            with self.assertRaises(FileExistsError):
                s.save(self.target, self.current)
        with self.assertRaises(ValueError):
            s.fork(self.current, self.target)
        with self.assertRaises(ValueError):
            s.save(self.root / 'wrong.json', self.current)
        bad = deepcopy(self.current)
        bad.execution_binding['sources']['session.py'] = '0' * 64
        with self.assertRaises(ValueError):
            bad.validate()
        bad = deepcopy(self.current.wrapper['envelope'])
        bad['integrity_schema'] = 'legacy-body-sha256'
        with self.assertRaises(ValueError):
            s.validate(bad)
        bad = deepcopy(self.current.wrapper['envelope'])
        bad['body']['history'] = bad['body']['history'].materialize()
        with self.assertRaises(ValueError):
            s._seal(bad['body'], bad['binding'])
        with self.assertRaises(ValueError):
            p.sha(bad['body'])
        # Prefix and store ownership checks must remain independent of scientific validation.
        wrapper = deepcopy(self.current.wrapper)
        wrapper['envelope']['body']['history'] = History(self.root / 'other')
        bad = replace(self.current, wrapper=wrapper)
        with patch.object(s.Session, 'validate', return_value=None):
            with self.assertRaisesRegex(ValueError, 'prefix'):
                s.save(self.target, bad)
        copied = History.from_history(self.current.wrapper['envelope']['body']['history'], self.root / 'copy')
        wrapper['envelope']['body']['history'] = copied
        with patch.object(s.Session, 'validate', return_value=None):
            with self.assertRaisesRegex(ValueError, 'store changed'):
                s.save(self.target, bad)


if __name__ == '__main__':
    unittest.main()
