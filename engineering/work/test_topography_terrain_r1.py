"""Focused current-state reuse, guards, migration and exact native parity."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from work.generator_runtime_r12.store import Store
from work.generator_upgrade_r22 import terrain as previous
from work.topography_r1 import terrain, provenance as p
from work.topography_r1_fixture import fixture, science


class TerrainOptimisation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.seed, cls.old, cls.new, cls.forcing = fixture()
        cls.reference = previous.advance(cls.old, cls.forcing)
        cls.child = terrain.advance(cls.new, cls.forcing)

    def test_exact_science_and_seed_preserved(self):
        self.assertEqual(science(self.reference), science(self.child))
        self.assertEqual(self.child['body']['seed'], self.seed)
        view = terrain.view(self.child)
        self.assertIsNone(view['world_date'])
        self.assertFalse(view['physical_acceptance_granted'])
        self.assertFalse(view['whole_diadem_year_verified'])

    def test_old_envelope_requires_explicit_authenticated_import(self):
        with self.assertRaises(ValueError):
            terrain.verify(self.reference)
        imported = terrain.import_r22(self.reference)
        self.assertEqual(imported['body'], self.reference['body'])
        self.assertNotEqual(imported['binding'], self.reference['binding'])
        terrain.verify(imported)

    def test_cache_reuses_only_verified_native_result(self):
        with tempfile.TemporaryDirectory(prefix='topo-') as directory:
            a = terrain.advance(self.new, self.forcing, cache_root=directory)
            with patch.object(terrain.consumer.terrain, 'trial', side_effect=AssertionError('cache reran native trial')):
                b = terrain.advance(self.new, self.forcing, cache_root=directory)
            self.assertTrue(b['execution']['cache_hit'])
            self.assertEqual(a['body'], b['body'])
            with patch.object(p, 'verify', side_effect=ValueError('source drift')):
                with self.assertRaisesRegex(ValueError, 'source drift'):
                    terrain.advance(self.new, self.forcing, cache_root=directory)
            with self.assertRaises(ValueError):
                terrain.advance(self.new, self.forcing, store=Store(Path(directory), 'different'))

    def test_rehashed_geometry_and_history_tamper_rejected(self):
        bad = deepcopy(self.child)
        key = next(iter(bad['body']['current_geometry']))
        bad['body']['current_geometry'][key]['surface_m'] = '123456'
        bad['body_sha256'] = p.sha(bad['body'])
        with self.assertRaises(ValueError):
            terrain.verify(bad)
        bad = deepcopy(self.child)
        bad['body']['history'][0]['duration_seconds'] = '1'
        row = bad['body']['history'][0]
        row['row_sha256'] = p.sha({k: v for k, v in row.items() if k != 'row_sha256'})
        bad['body_sha256'] = p.sha(bad['body'])
        with self.assertRaises(ValueError):
            terrain.verify(bad)

    def test_parent_metadata_mutation_during_trial_rejected(self):
        parent = deepcopy(self.new)
        actual = terrain.consumer.terrain.trial
        def mutate(*args, **kwargs):
            result = actual(*args, **kwargs)
            parent['execution']['physical_acceptance_granted'] = True
            return result
        with patch.object(terrain.consumer.terrain, 'trial', mutate):
            with self.assertRaisesRegex(ValueError, 'parent mutated'):
                terrain.advance(parent, self.forcing)

    def test_continuation_reuses_parent_parse_but_keeps_final_validation(self):
        with patch.object(terrain, '_validate', wraps=terrain._validate) as validate:
            after = terrain.advance(self.child, self.forcing)
        self.assertEqual(validate.call_count, 2)
        self.assertEqual(len(after['body']['history']), 2)
        self.assertEqual(after['body']['history'][1]['initial_state_sha256'],
                         p.sha(self.child['body']['current_state']))
        terrain.verify(after)


if __name__ == '__main__':
    unittest.main()
