"""Four small regional construction/consumer checks; no soil/year simulation."""
from copy import deepcopy
import hashlib
from pathlib import Path
import tempfile
import unittest

from work.generator_upgrade_r16 import regional as r

E = 'SYNTHETIC TEST: explicit geometry/material/law values, not Diadem calibration'
STATUS = 'SYNTHETIC TEST'


def fixture(directory):
    path = Path(directory)/'contract.txt'; path.write_text(E, encoding='utf-8')
    def event(identity, cell, kind, **payload):
        return {'event_id': identity, 'cell_id': cell, 'kind': kind,
                'evidence': E, 'source_status': STATUS, **payload}
    recipe = {'schema': r.SCHEMA,
        'context': {'world_id': 'SYNTHETIC_NOT_DIADEM', 'snapshot_id': 'CONTROLLED_GEOLOGY',
            'spatial_frame_id': 'LOCAL_METRES_EAST_SOUTH', 'vertical_reference': 'LOCAL_METRES_UP'},
        'source_status': STATUS, 'evidence': E,
        'owner_source': {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()},
        'supports': {'upper': {'xy_m': [0, 0], 'area_m2': 1, 'basal_elevation_m': 0},
                     'lower': {'xy_m': [10, 0], 'area_m2': 1, 'basal_elevation_m': 0}}, 'events': []}
    for key in recipe['supports']:
        for material, density, porosity, thickness in (('basalt', 2800, .05, 2), ('shale', 2500, .2, 1)):
            recipe['events'].append(event(key+'-'+material, key, 'emplace', layer={
                'material_id': material, 'grain_density_kg_m3': density,
                'porosity': porosity, 'phase': 'bedrock', 'thickness_m': thickness, 'evidence': E}))
    recipe['events'] += [event('upper-translation', 'upper', 'translate_base', displacement_m=1),
                         event('lower-exposure', 'lower', 'strip_to_elevation', surface_m=2)]
    def prop(name, value, unit):
        return {'name': name, 'value': value, 'unit': unit, 'evidence': E, 'status': STATUS}
    forcing = {'duration_years': .001, 'local_runoff_m3': {'upper': .01, 'lower': 0},
        'connectors': [{'connector_id': 'upper-lower', 'source_id': 'upper', 'receiver_id': 'lower',
            'length_m': 10, 'outlet_elevation_m': None, 'evidence': E},
            {'connector_id': 'outlet', 'source_id': 'lower', 'receiver_id': None,
             'length_m': 10, 'outlet_elevation_m': -1, 'evidence': E}],
        'erosion_laws': [{'material_id': material, 'phase': phase,
            'k_per_year': prop('erosion_coefficient_at_reference_runoff', k, '1/year'),
            'reference_runoff_m_year': prop('reference_runoff', 1., 'm/year')}
            for material, k in (('basalt', .01), ('shale', .1))
            for phase in ('bedrock', 'mobile_sediment')],
        'sediment_laws': [{'material_id': material, 'settling_m_year': 1,
            'deposited_porosity': .4, 'deposition_order': i, 'evidence': E}
            for i, material in enumerate(('basalt', 'shale'))],
        'controls': {'max_relief_change_fraction': .25, 'max_solid_liquid_ratio': .1, 'evidence': E},
        'evidence': E, 'source_status': STATUS}
    return recipe, forcing


class RegionalTests(unittest.TestCase):
    def test_constructed_contacts_and_actual_exposed_geology(self):
        with tempfile.TemporaryDirectory() as directory:
            recipe, _ = fixture(directory)
            result = r.build(recipe)['scientific']
            self.assertEqual(result['stratigraphy']['upper']['surface_m'], '4')
            self.assertEqual(result['stratigraphy']['lower']['surface_m'], '2')
            self.assertEqual(result['stratigraphy']['upper']['exposed_material'], 'shale')
            self.assertEqual(result['stratigraphy']['lower']['exposed_material'], 'basalt')
            self.assertFalse(result['plate_motion_inferred'])

    def test_generated_geology_drives_real_r14_erosion(self):
        with tempfile.TemporaryDirectory() as directory:
            recipe, forcing = fixture(directory)
            snapshot = r.build(recipe)
            recipe['supports']['upper']['xy_m'][0] = 500
            self.assertEqual(snapshot['scientific']['supports']['upper']['xy_m'][0], 0)
            result = r.terrain_step(snapshot, forcing)
            changed = deepcopy(forcing)
            for law in changed['erosion_laws']:
                if law['material_id'] == 'shale':
                    law['k_per_year']['value'] *= 2
            faster = r.terrain_step(snapshot, changed)
            from fractions import Fraction
            self.assertLess(Fraction(faster['receipt']['final_surfaces_m']['upper']),
                            Fraction(result['receipt']['final_surfaces_m']['upper']))
            for row in result['receipt']['material_balances']:
                self.assertEqual(row['mass_residual_kg'], '0')
                self.assertEqual(row['solid_residual_m3'], '0')
            self.assertIn('actual_R14_erosion_receipt', result['receipt'])

    def test_source_state_and_geometry_rejection(self):
        with tempfile.TemporaryDirectory() as directory:
            recipe, forcing = fixture(directory)
            snapshot = r.build(recipe)
            altered = deepcopy(snapshot)
            altered['scientific']['context']['snapshot_id'] = 'CHANGED'
            with self.assertRaisesRegex(ValueError, 'state/receipt changed'):
                r.terrain_step(altered, forcing)
            forcing['connectors'][0]['length_m'] = 9
            with self.assertRaisesRegex(ValueError, 'connector length'):
                r.terrain_step(snapshot, forcing)
            recipe['owner_source']['sha256'] = '0'*64
            with self.assertRaisesRegex(ValueError, 'owner contract changed'):
                r.build(recipe)

    def test_unknown_and_synthetic_promotion_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            recipe, forcing = fixture(directory)
            snapshot = r.build(recipe)
            forcing['erosion_laws'][0]['k_per_year']['status'] = 'UNKNOWN'
            with self.assertRaisesRegex(ValueError, 'different input status'):
                r.terrain_step(snapshot, forcing)
            recipe['source_status'] = 'WORKING NON-CANON'
            with self.assertRaises(ValueError):
                r.build(recipe)


if __name__ == '__main__':
    unittest.main()
