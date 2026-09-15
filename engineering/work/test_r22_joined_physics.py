"""One changing-ground/root/evaporation check on the same material-water ledger."""
from copy import deepcopy
import unittest
from work.test_r22_moving_roots import recipe
from work.test_r22_crops import evaporation_fixture
from work.generator_upgrade_r22 import moving_roots, evaporation


class JoinedPhysics(unittest.TestCase):
    def test_rooted_changing_ground_and_evaporation_share_water_energy_and_donor(self):
        spec = recipe()
        boundary = evaporation_fixture()[2]['surface_evaporation']
        for event in spec['events']:
            for key, forcing in event['forcing'].items():
                forcing['surface_evaporation'] = deepcopy(boundary)
                forcing['surface_evaporation']['potential_m_s'] = 1e-8
                forcing['surface_evaporation']['applicability']['donor_layer_id'] = spec['cells'][key]['model']['layers'][0]['layer_id']
        result = moving_roots.run(spec, soil_backend=evaporation)['scientific']
        self.assertEqual(result['status'], 'MODELLED_ROOTED_GROUND_FEEDBACK', result['reason'])
        ev = roots = 0.
        for row in result['events']:
            moving_roots.audit_event(row, spec['coupling_controls'], soil_backend=evaporation)
            for step in row['steps']:
                for solved in step['soil_steps'].values():
                    ev += solved['result']['ledger']['surface_evaporation_m']
                    roots += solved['result']['ledger']['root_withdrawal_m']
                    self.assertEqual(solved['forcing']['surface_evaporation']['applicability']['donor_layer_id'],
                                     solved['model']['layers'][0]['layer_id'])
        self.assertGreater(ev, 0.)
        self.assertGreater(roots, 0.)
        self.assertLess(abs(result['accounts']['water_residual_m3']), spec['coupling_controls']['budget_water_atol_m3'])
        self.assertLess(abs(result['accounts']['energy_residual_j']), spec['coupling_controls']['budget_energy_atol_j'])


if __name__ == '__main__': unittest.main()
