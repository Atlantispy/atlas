"""One bounded selected-seed continuation; fixture forcing is not Water input."""
from copy import deepcopy
from fractions import Fraction as F
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from work.generator_runtime_r12.store import Store
from work.generator_upgrade_r18 import consumer, working
from work.generator_upgrade_r22 import terrain, provenance as p

EVIDENCE = ('CONTROLLED WORKING INTERFACE CHECK ONLY: selected native R18 geology; '
    'arbitrary prescribed finite runoff/outlet/mobile laws for code verification, '
    'NOT owner-supplied Water forcing, a selected evolution dose, a catchment or a Sea join')


def clock():
    return {'calendar_id': 'CONTROLLED_INTERFACE_SECONDS_ONLY_NOT_DIADEM_CALENDAR',
        'seconds_per_year': 31536000, 'origin': 'CONSTRUCTOR_RELATIVE_NO_WORLD_DATE',
        'evidence': EVIDENCE, 'source_status': 'WORKING NON-CANON'}


def forcing(envelope):
    body = terrain.verify(envelope); point = next(iter(body['current_geometry']))
    original = terrain.original_erosion_laws(envelope)
    mobile = []
    for mid, descriptor in sorted(body['palette'].items()):
        mobile.append({'material_id': mid, 'phase': 'mobile_sediment',
            'k_per_year': {'name': 'erosion_coefficient_at_reference_runoff', 'value': 0,
                'unit': '1/year', 'evidence': EVIDENCE, 'status': 'WORKING NON-CANON'},
            'reference_runoff_m_year': {'name': 'reference_runoff', 'value': 1,
                'unit': 'm/year', 'evidence': EVIDENCE, 'status': 'WORKING NON-CANON'}})
    return {'duration_years': '1/1000', 'local_runoff_m3': {point: 160000},
        'connectors': [{'connector_id': 'EXPLICIT_INTERFACE_TEST_OUTLET', 'source_id': point,
            'receiver_id': None, 'length_m': 4000,
            'outlet_elevation_m': str(F(body['current_geometry'][point]['surface_m'])-1),
            'evidence': EVIDENCE}], 'erosion_laws': original+mobile,
        'sediment_laws': [{'material_id': mid, 'settling_m_year': 0,
            'deposited_porosity': '2/5', 'deposition_order': i, 'evidence': EVIDENCE}
            for i, mid in enumerate(sorted(body['palette']))],
        'controls': {'max_relief_change_fraction': '1/4', 'max_solid_liquid_ratio': '1/10', 'evidence': EVIDENCE},
        'evidence': EVIDENCE, 'source_status': 'WORKING NON-CANON'}


class TerrainContinuation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.seed = working.build({'r120_c80': {'xy_m': [2000, 2000], 'area_m2': 16000000}}, alternative='DEFAULT')
        cls.seed_bytes = p.encoded(cls.seed)
        cls.initial = terrain.from_seed(cls.seed, clock())
        cls.temporary = tempfile.TemporaryDirectory(prefix='r22-terrain-')
        cls.store = Store(Path(cls.temporary.name)/'c', terrain.cache_namespace(cls.initial))
        cls.first_forcing = forcing(cls.initial)
        cls.first = terrain.advance(cls.initial, cls.first_forcing, store=cls.store)
        cls.second_forcing = forcing(cls.first)
        cls.second = terrain.advance(cls.first, cls.second_forcing, store=cls.store)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_second_native_step_uses_first_evolved_state_and_clock(self):
        first, second = self.first['body'], self.second['body']
        row = second['history'][1]
        self.assertEqual(row['initial_state_sha256'], p.sha(first['current_state']))
        self.assertEqual(row['native_result']['r22_parent_state_sha256'], p.sha(first['current_state']))
        self.assertEqual(F(second['elapsed_years']), F(1, 500))
        self.assertEqual(F(second['elapsed_seconds']), F(31536000, 500))
        self.assertNotEqual(first['current_geometry'], self.initial['body']['current_geometry'])
        self.assertNotEqual(second['current_geometry'], first['current_geometry'])
        self.assertEqual(terrain.verify(self.second), second)

    def test_seed_construction_and_native_consumer_are_unchanged(self):
        self.assertEqual(p.encoded(self.seed), self.seed_bytes)
        self.assertEqual(p.encoded(self.second['body']['seed']), self.seed_bytes)
        self.assertEqual(self.second['body']['seed']['scientific']['stratigraphy'], self.seed['scientific']['stratigraphy'])
        self.assertIs(consumer.terrain_step.__globals__['verify'], consumer.verify)
        self.assertIs(consumer.terrain_step.__globals__['_lineage'], consumer._lineage)

    def test_current_view_names_child_and_retains_unknown_date_and_sea_registration(self):
        view = terrain.view(self.second)
        self.assertNotEqual(view['context']['snapshot_id'], view['seed_context']['snapshot_id'])
        self.assertEqual(view['state_sha256'], p.sha(self.second['body']['current_state']))
        self.assertEqual(view['seed_scientific_sha256'], self.seed['execution']['scientific_sha256'])
        self.assertEqual(view['role'], 'EVOLVED_WORKING_TERRAIN_CHILD')
        self.assertIsNone(view['world_date'])
        self.assertEqual(view['sea_vertical_registration'], 'NOT_ASSERTED')
        self.assertFalse(view['physical_acceptance_granted'])
        for key, support in view['supports'].items():
            self.assertEqual(support['surface_m'], self.second['body']['current_geometry'][key]['surface_m'])
            self.assertEqual(support['xy_m'], self.seed['scientific']['supports'][key]['xy_m'])

    def test_cache_reuses_exact_actual_parent_and_rejects_changed_original_k(self):
        with patch.object(terrain, 'FunctionType', side_effect=AssertionError('no native terrain rerun')):
            cached = terrain.advance(self.first, self.second_forcing, store=self.store)
        self.assertEqual(cached['body'], self.second['body'])
        self.assertTrue(cached['execution']['cache_hit'])
        changed = deepcopy(self.second_forcing)
        changed['erosion_laws'][0]['k_per_year']['value'] = '1'
        with self.assertRaisesRegex(ValueError, 'original-phase erosion law differs'):
            terrain.advance(self.first, changed)

    def test_tampered_current_geometry_and_double_clock_are_rejected(self):
        changed = deepcopy(self.second); key = next(iter(changed['body']['current_geometry']))
        changed['body']['current_geometry'][key]['surface_m'] = '0'
        changed['body_sha256'] = p.sha(changed['body'])
        with self.assertRaisesRegex(ValueError, 'current terrain geometry'):
            terrain.verify(changed)
        changed = deepcopy(self.second); changed['body']['elapsed_seconds'] = '0'
        changed['body_sha256'] = p.sha(changed['body'])
        with self.assertRaisesRegex(ValueError, 'current terrain geometry'):
            terrain.verify(changed)
        for row in self.second['body']['history']:
            for balance in row['native_result']['constituent_balances']:
                self.assertEqual(F(balance['residual_mass_kg']), 0)
                self.assertEqual(F(balance['residual_solid_volume_m3']), 0)


if __name__ == '__main__':
    unittest.main()
