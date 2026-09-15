"""Focused exact parity, mutation, atomic-control and restart checks."""
from copy import deepcopy
from dataclasses import replace
from fractions import Fraction as F
import json
from pathlib import Path
import tempfile
import unittest

from work.native_terrain_r2 import provenance as oldp
from work.native_terrain_r2.test_evolve import ContinuingStateTests as Fixture
from . import provenance as p, session as s


class SessionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Fixture.setUpClass()
        cls.addClassCleanup(Fixture.doClassCleanups)

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix='native-r3-session-')
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        original = self.root / 'legacy.json'
        original.write_bytes(oldp.encoded({'envelope': Fixture.migrated}))
        self.current = s.import_legacy(original, self.root / 'new')

    def test_exact_complete_envelope_and_restart_parity(self):
        checkpoint = self.root / 'new/checkpoint.json'
        current = s.save(checkpoint, self.current)
        first = current.advance(Fixture.executor, F(1), Fixture.acceptance, operation_id='successor-once')
        self.assertEqual(first.wrapper['envelope']['body_sha256'], Fixture.first['body_sha256'])
        material = deepcopy(first.wrapper['envelope'])
        material['body']['history'] = material['body']['history'].materialize()
        self.assertEqual(material, Fixture.first)
        self.assertEqual(len(current.wrapper['envelope']['body']['history']), 0)
        first = s.save(checkpoint, first)
        restored = s.load(checkpoint)
        self.assertEqual(restored.wrapper['envelope']['body_sha256'], Fixture.first['body_sha256'])
        expected = Fixture.executor.advance(Fixture.first, F(1), Fixture.acceptance, operation_id='next')
        actual = restored.advance(Fixture.executor, F(1), Fixture.acceptance, operation_id='next')
        self.assertEqual(actual.wrapper['envelope']['body_sha256'], expected['body_sha256'])

    def test_rejection_and_input_mutation_preserve_accepted_session(self):
        before = self.current.wrapper['envelope']['body_sha256']
        exact = replace(Fixture.acceptance, max_surface_error_m=F(), max_material_bulk_l1_error_m3=F(), max_halvings=0)
        with self.assertRaises(ValueError):
            self.current.advance(Fixture.executor, F(1), exact, operation_id='reject')
        self.assertEqual(self.current.wrapper['envelope']['body_sha256'], before)
        self.assertEqual(len(self.current.wrapper['envelope']['body']['history']), 0)
        bad = deepcopy(self.current)
        bad.wrapper['envelope']['body']['surface_water_exported_m3'] = '99'
        with self.assertRaises(ValueError):
            bad.validate()

    def test_changed_control_and_source_binding_refused(self):
        checkpoint = self.root / 'new/checkpoint.json'
        saved = s.save(checkpoint, self.current)
        before = checkpoint.read_bytes()
        checkpoint.write_bytes(before + b' ')
        with self.assertRaises(ValueError):
            s.save(checkpoint, saved)
        self.assertEqual(checkpoint.read_bytes(), before + b' ')
        bad = deepcopy(self.current)
        bad.execution_binding['sources']['session.py'] = '0' * 64
        with self.assertRaises(ValueError):
            bad.validate()

    def test_exclusive_control_writer_lock(self):
        checkpoint = self.root / 'new/checkpoint.json'
        saved = s.save(checkpoint, self.current)
        with s._control_lock(checkpoint):
            with self.assertRaises(FileExistsError):
                s.save(checkpoint, saved)
        self.assertFalse(checkpoint.with_name('checkpoint.json.lock').exists())
        s.save(checkpoint, saved)


if __name__ == '__main__':
    unittest.main()
