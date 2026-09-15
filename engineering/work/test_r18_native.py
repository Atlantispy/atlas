"""One changed native-consumer check; explicitly synthetic, not world forcing."""
from copy import deepcopy
from fractions import Fraction as F
import hashlib
from pathlib import Path
import unittest

from work.generator_upgrade_r18 import composite, model, consumer
from work.generator_upgrade_r16 import regional

E = 'SYNTHETIC TEST: mixed rock native adapter, not Diadem hydrology or sediment calibration'
STATUS = 'SYNTHETIC TEST'


def fixture():
    path = Path(__file__).resolve()
    source = {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    packet = {'context': {'world_id': 'SYNTHETIC_NOT_DIADEM', 'snapshot_id': 'R18_NATIVE_CHECK',
        'spatial_frame_id': 'LOCAL_METRES_EAST_SOUTH', 'vertical_reference': 'LOCAL_METRES_UP'},
        'source_status': STATUS, 'evidence': E, 'owner_source': source, 'source_package': source}
    material = composite.create([
        {'unit_id': 'test-A', 'bulk_weight': '1/3', 'grain_density_kg_m3': 2700, 'porosity': '1/50'},
        {'unit_id': 'test-B', 'bulk_weight': '2/3', 'grain_density_kg_m3': 2500, 'porosity': '1/10'}],
        '7/300000', phase='bedrock', evidence=E)
    mid = material['material_id']
    supports = {key: {'xy_m': [x, 0], 'area_m2': 1} for key, x in (('upper', 0), ('lower', 10))}
    resolved = {key: {'basal_elevation_m': base, 'translation_m': 0,
        'layers': [{'compartment_id': 'test-body', 'material_id': mid, 'thickness_m': 10}],
        'interpretation': {'status': STATUS}} for key, base in (('upper', 0), ('lower', -1))}
    snapshot = model.build(packet, supports, {'samples': {key: {} for key in supports}},
                           resolved, {mid: material}, '1')
    return snapshot, mid


class NativeTests(unittest.TestCase):
    def test_exact_composite_erosion_deposition_and_binding(self):
        snapshot, mid = fixture()
        type(self).snapshot = snapshot
        forcing = {key: {'discharge_m3_year': 10., 'hydraulic_slope': .1,
            'source_status': STATUS, 'evidence': E} for key in ('upper', 'lower')}
        eroded = consumer.incise(snapshot, forcing, '1/1000')
        type(self).incision = eroded
        self.assertEqual({v['unit_id'] for v in eroded['constituent_balances']}, {'test-A', 'test-B'})
        self.assertTrue(all(F(v['eroded_mass_kg']) > 0 for v in eroded['constituent_balances']))
        def prop(name, value, unit):
            return {'name': name, 'value': value, 'unit': unit, 'evidence': E, 'status': STATUS}
        terrain = {'duration_years': .001, 'local_runoff_m3': {'upper': .01, 'lower': 0},
            'connectors': [{'connector_id': 'upper-lower', 'source_id': 'upper', 'receiver_id': 'lower',
                'length_m': 10, 'outlet_elevation_m': None, 'evidence': E},
                {'connector_id': 'outlet', 'source_id': 'lower', 'receiver_id': None,
                 'length_m': 10, 'outlet_elevation_m': 8, 'evidence': E}],
            'erosion_laws': [{'material_id': mid, 'phase': phase,
                'k_per_year': prop('erosion_coefficient_at_reference_runoff', '7/300000', '1/year'),
                'reference_runoff_m_year': prop('reference_runoff', 1., 'm/year')}
                for phase in ('bedrock', 'mobile_sediment')],
            'sediment_laws': [{'material_id': mid, 'settling_m_year': 1,
                'deposited_porosity': .4, 'deposition_order': 0, 'evidence': E}],
            'controls': {'max_relief_change_fraction': .25, 'max_solid_liquid_ratio': .1, 'evidence': E},
            'evidence': E, 'source_status': STATUS}
        moved = consumer.terrain_step(snapshot, terrain)
        type(self).transport = moved
        _, native = regional.p.backend()
        state = native.LandscapeState.from_dict(moved['state'])
        deposits = [layer for column in state.column_map.values() for layer in column.layers
                    if layer.phase == 'mobile_sediment']
        self.assertTrue(deposits)
        self.assertTrue(all(layer.mass_kg > 0 and layer.porosity == F(.4) for layer in deposits))
        for result in (eroded, moved):
            self.assertEqual(result['palette'], snapshot['scientific']['regional_input']['palette'])
            self.assertEqual(result['r18_input_scientific_sha256'], snapshot['execution']['scientific_sha256'])
            for row in result['constituent_balances']:
                self.assertEqual(row['residual_mass_kg'], '0')
                self.assertEqual(row['residual_solid_volume_m3'], '0')
        changed = deepcopy(terrain)
        changed['erosion_laws'][0]['k_per_year']['value'] = .1
        with self.assertRaises(ValueError):
            consumer.terrain_step(snapshot, changed)
        changed = deepcopy(snapshot)
        changed['scientific']['regional_input']['palette'][mid]['k_per_year'] = '1'
        with self.assertRaises(ValueError):
            consumer.incise(changed, forcing, '1/1000')


if __name__ == '__main__':
    unittest.main()
