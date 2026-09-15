"""Focused R4 migration, schema, actual acceptance parity and restart tests."""
from copy import deepcopy
from dataclasses import replace
from fractions import Fraction as F
from pathlib import Path
import tempfile
import unittest

from work.native_terrain_r2 import provenance as numerical_p
from work.native_terrain_r2 import test_evolve as fixture_module
from work.native_terrain_r3 import session as old, provenance as oldp
from . import session as s, provenance as p, integrity


class SessionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.case = fixture_module.ContinuingStateTests
        cls.case.setUpClass()
        cls.addClassCleanup(cls.case.doClassCleanups)

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix='native-r4-')
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        legacy = self.root / 'legacy.json'
        legacy.write_bytes(numerical_p.encoded({'envelope': self.case.first}))
        r3 = old.import_legacy(legacy, self.root / 'r3')
        self.original_path = self.root / 'r3/checkpoint.json'
        self.original = old.save(self.original_path, r3)
        self.original_bytes = self.original_path.read_bytes()
        self.current = s.import_r3(self.original_path, self.root / 'r4')
        self.target = self.root / 'r4/checkpoint.json'

    def test_lossless_migration_advance_and_restart(self):
        self.assertEqual(integrity.scientific_sha(self.current.wrapper['envelope']['body']), self.case.first['body_sha256'])
        saved = s.save(self.target, self.current)
        expected = self.case.executor.advance(self.case.first, F(1), self.case.acceptance, operation_id='r4-next')
        following = saved.advance(self.case.executor, F(1), self.case.acceptance, operation_id='r4-next')
        self.assertEqual(integrity.scientific_sha(following.wrapper['envelope']['body']), expected['body_sha256'])
        saved = s.save(self.target, following)
        restarted = s.load(self.target)
        self.assertEqual(restarted.wrapper['envelope']['body_sha256'], saved.wrapper['envelope']['body_sha256'])
        self.assertEqual(integrity.scientific_sha(restarted.wrapper['envelope']['body']), expected['body_sha256'])
        self.assertEqual(self.original_path.read_bytes(), self.original_bytes)
        self.assertEqual(len(self.current.wrapper['envelope']['body']['history']), 1)

    def test_explicit_integrity_and_exact_history_required(self):
        original = self.current.wrapper['envelope']
        bad = deepcopy(original)
        bad['integrity_schema'] = 'legacy-body-sha256'
        with self.assertRaises(ValueError):
            s.validate(bad)
        bad = deepcopy(original)
        bad['body']['history'] = bad['body']['history'].materialize()
        with self.assertRaises(ValueError):
            s.validate(bad)
        with self.assertRaises(ValueError):
            s._seal(bad['body'], bad['binding'])
        with self.assertRaises(ValueError):
            p.sha(bad['body'])

    def test_tampered_archive_rejected_before_work_or_save(self):
        saved = s.save(self.target, self.current)
        history = saved.wrapper['envelope']['body']['history']
        archive = history.root / history.refs[0]['path']
        raw = archive.read_bytes()
        archive.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
        with self.assertRaises(ValueError):
            saved.advance(self.case.executor, F(1), self.case.acceptance, operation_id='no-write')
        with self.assertRaises(ValueError):
            s.save(self.target, saved)
        self.assertEqual(len(history), 1)
        self.assertEqual(self.original_path.read_bytes(), self.original_bytes)

    def test_source_and_writer_guard_reused(self):
        saved = s.save(self.target, self.current)
        bad = deepcopy(saved)
        bad.execution_binding['sources']['session.py'] = '0' * 64
        with self.assertRaises(ValueError):
            bad.validate()
        with old._control_lock(self.target):
            with self.assertRaises(FileExistsError):
                s.save(self.target, saved)
        with self.assertRaises(ValueError):
            s.import_r3(self.original_path, self.root / 'r3')
        with self.assertRaises(ValueError):
            s.import_r3(self.original_path, self.root / 'r3/nested')


if __name__ == '__main__':
    unittest.main()
