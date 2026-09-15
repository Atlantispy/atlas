"""Focused geometry, conservation and executed nonzero-root integration checks."""
from copy import deepcopy
from fractions import Fraction as F
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from work.generator_runtime_r12.store import Store
from work.generator_upgrade_r13 import soil
from work.generator_upgrade_r14 import pipeline as ground, reference
from work.generator_upgrade_r22 import moving_roots as roots, provenance as p


def recipe():
    spec = reference.recipe(duration_s=120., event_count=1)
    spec['schema'] = roots.SCHEMA
    spec['root_controls'] = {'weight_atol': 1e-8, 'position_atol_m': 1e-6}
    spec['roots'] = {}
    for key, cell in spec['cells'].items():
        spec['roots'][key] = {'kinematics': 'MATERIAL_ATTACHED_NO_GROWTH',
            'demand_policy': roots.POLICY, 'coordinate': 'DEPTH_BELOW_INITIAL_SURFACE_M',
            'vertical_reference': spec['context']['vertical_reference'],
            'bands': [{'band_id': 'existing-roots', 'start_m': 0., 'end_m': .2,
                'weight': 1., 'distribution': 'UNIFORM_WITHIN_SUPPLIED_BAND'}],
            'layer_accessibility': {'mineral': 'ACCESSIBLE'}, **reference.STATUS}
        for event in spec['events']:
            forcing = event['forcing'][key]; forcing.pop('root_withdrawal_m_s')
            forcing['potential_root_demand_m_s'] = 1e-7
            forcing['uptake'] = {'dry_zero_head_m': -100., 'dry_full_head_m': -10.,
                'wet_full_head_m': -.1, 'wet_zero_head_m': 0., **reference.STATUS}
    return spec


class MovingRoots(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec = recipe()
        cls.temporary = tempfile.TemporaryDirectory(prefix='r22-root-')
        cls.store = Store(Path(cls.temporary.name)/'c', p.sha(p.identity(moving_ground=True)))
        cls.result = roots.run(cls.spec, store=cls.store)
        if cls.result['scientific']['status'] != 'MODELLED_ROOTED_GROUND_FEEDBACK':
            raise AssertionError(cls.result['scientific']['reason'])

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_changed_geometry_has_actual_nonzero_uptake_and_no_deposit_roots(self):
        scientific = self.result['scientific']; deposits = []; uptakes = []
        for event in scientific['events']:
            for step in event['steps']:
                deposits.extend(step['transport']['ledger']['deposits'])
                for key, solved in step['soil_steps'].items():
                    self.assertEqual(solved['model'], step['transport']['cells'][key]['model'])
                    self.assertEqual(solved['result']['initial_state'], step['transport']['cells'][key]['soil'])
                    self.assertGreater(solved['result']['ledger']['root_withdrawal_m'], 0.)
                    uptakes.append(solved['result']['ledger']['root_withdrawal_m'])
                    for layer, weight in zip(solved['model']['layers'], solved['forcing']['uptake']['weights']):
                        if layer['layer_id'].startswith('transport-'):
                            self.assertEqual(weight, 0.)
                    self.assertLessEqual(F(solved['root_demand']['supported_potential_root_demand_m_s']), F(solved['root_demand']['original_potential_root_demand_m_s']))
        self.assertTrue(deposits); self.assertTrue(uptakes)
        final = scientific['final_cells']['upper']
        self.assertGreater(F(final['root_state']['lost_weight']), 0)
        self.assertNotEqual(final['model'], self.spec['cells']['upper']['model'])
        self.assertEqual(final['soil']['elapsed_seconds'], 120.)

    def test_material_water_energy_and_root_accounts_close_with_original_gates(self):
        scientific = self.result['scientific']
        self.assertLess(abs(scientific['accounts']['water_residual_m3']), self.spec['coupling_controls']['budget_water_atol_m3'])
        self.assertLess(abs(scientific['accounts']['energy_residual_j']), self.spec['coupling_controls']['budget_energy_atol_j'])
        for row in scientific['events']:
            self.assertTrue(roots.audit_event(row, self.spec['coupling_controls']))
            self.assertTrue(all(0 <= gate['error_ratio'] <= 1 for gate in row['acceptance']))
        for cell in scientific['final_cells'].values():
            state = cell['root_state']
            self.assertEqual(sum((F(x['weight']) for x in state['segments']), F())+F(state['lost_weight']), F(state['original_weight']))
        self.assertFalse(scientific['whole_diadem_year_verified'])

    def test_absolute_and_initial_depth_support_are_equivalent(self):
        spec = recipe(); cell = spec['cells']['upper']; support = spec['roots']['upper']
        depth = roots.initialise(cell, support, spec['context']['vertical_reference'])
        absolute = deepcopy(support); absolute['coordinate'] = 'ABSOLUTE_ELEVATION_M'
        absolute['bands'][0].update(start_m=cell['base_elevation_m'],
            end_m=str(F(cell['base_elevation_m'])+F(cell['model']['layers'][0]['thickness_m'])))
        self.assertEqual(depth, roots.initialise(cell, absolute, spec['context']['vertical_reference']))

    def test_top_erosion_clips_root_location_and_never_births_roots(self):
        spec = recipe(); cell = deepcopy(spec['cells']['upper'])
        supplied = deepcopy(spec['roots']['upper']); supplied['bands'][0].update(start_m=0., end_m=.01)
        cell['root_state'] = roots.initialise(cell, supplied, spec['context']['vertical_reference'])
        after = deepcopy(cell)
        after['model']['layers'][0]['thickness_m'] *= .8
        after['materials'][0]['dry_mass_kg_m2'] = str(F(cell['materials'][0]['dry_mass_kg_m2'])*F(4, 5))
        state, ledger = roots.move_roots(cell, after, operation='TRANSPORT')
        self.assertEqual(state['segments'], []); self.assertEqual(F(state['lost_weight']), 1)
        self.assertEqual(ledger['root_weight_residual'], '0')
        after['root_state'] = state
        forcing, demand = roots.mapped_forcing(after, spec['events'][0]['forcing']['upper'], 10.)
        self.assertEqual(forcing['root_withdrawal_m_s'], [0.])
        self.assertEqual(F(demand['supported_potential_root_demand_m_s']), 0)
        self.assertGreater(F(demand['unsupported_due_to_retired_roots_m_s']), 0)
        growing = deepcopy(after)
        growing['materials'][0]['dry_mass_kg_m2'] = cell['materials'][0]['dry_mass_kg_m2']
        with self.assertRaisesRegex(ValueError, 'material growth'):
            roots.move_roots(after, growing, operation='TRANSPORT')

    def test_excluded_strata_stale_weights_and_unsupplied_kinematics_are_rejected(self):
        spec = recipe(); root = spec['roots']['upper']
        root['layer_accessibility']['mineral'] = 'EXCLUDED'
        with self.assertRaisesRegex(ValueError, 'excluded stratum'):
            roots.validate(spec)
        spec = recipe(); spec['events'][0]['forcing']['upper']['uptake']['weights'] = [1.]
        with self.assertRaisesRegex(ValueError, 'stale layer weights'):
            roots.validate(spec)
        spec = recipe(); spec['roots']['upper']['kinematics'] = 'SURFACE_REANCHOR_EACH_STEP'
        with self.assertRaisesRegex(ValueError, 'material-attached'):
            roots.validate(spec)

    def test_root_state_tampering_cannot_pass_saved_readback(self):
        event = deepcopy(self.result['scientific']['events'][0])
        cell = event['steps'][0]['final_cells']['upper']
        cell['root_state']['lost_weight'] = '0'
        event['steps'][0]['final_cells_sha256'] = p.sha(event['steps'][0]['final_cells'])
        with self.assertRaises(ValueError):
            roots.audit_event(event, self.spec['coupling_controls'])

    def test_cached_completed_recipe_reuses_without_advancing_roots_or_soil(self):
        with patch.object(roots, 'advance_event', side_effect=AssertionError('no root/soil rerun')):
            resumed = roots.run(self.spec, store=self.store, resume=self.result['scientific']['checkpoint'])
        self.assertEqual(resumed['scientific'], self.result['scientific'])
        self.assertEqual(resumed['execution']['reused_events'], 1)

    def test_sealed_r14_nonzero_root_guard_and_native_globals_are_preserved(self):
        spec = reference.recipe(duration_s=1., event_count=1)
        spec['events'][0]['forcing']['upper']['root_withdrawal_m_s'] = [1e-7]
        with self.assertRaisesRegex(ValueError, 'geometry-aware biological adapter'):
            ground.validate(spec)
        self.assertIs(ground.advance_event.__globals__['_trial'], ground._trial)
        self.assertIs(ground.audit_interval.__globals__['soil_audit'].event, __import__('work.generator_upgrade_r13.audit', fromlist=['event']).event)
        self.assertIs(soil.advance.__globals__['_event'], soil._event)


if __name__ == '__main__':
    unittest.main()
