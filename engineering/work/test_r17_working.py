"""Three focused actual-region checks; no full terrain, atlas or year run."""
from copy import deepcopy
from fractions import Fraction as F
import math
import unittest

from work.generator_upgrade_r16 import regional
from work.generator_upgrade_r17 import working as w, northern as n, provenance as p


class WorkingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec = w.inputs()
        cls.working_result = w.build()

    def test_real_sources_native_geometry_materials_and_exact_accounts(self):
        science = self.working_result['scientific']
        details = science['regional_input']
        self.assertFalse(details['current_dem_consumed'])
        self.assertFalse(details['applicability']['crop_is_physical_boundary'])
        for expected in self.spec['real_source_probe_cases']:
            key = expected['case_id']
            self.assertEqual(details['sampling']['samples'][key], expected['fields'])
            actual = science['stratigraphy'][key]
            self.assertTrue(math.isclose(float(F(actual['surface_m'])), expected['expected_initial_surface_m'], abs_tol=1e-8, rel_tol=0))
            self.assertTrue(math.isclose(float(F(actual['bottom_to_top'][0]['bottom_m'])), expected['expected_base_m'], abs_tol=1e-8, rel_tol=0))
            interpretation = details['interpretations'][key]
            for received, thickness in zip(interpretation['reference_thicknesses_m'], expected['expected_thickness_m']):
                self.assertTrue(math.isclose(float(F(received)), thickness, abs_tol=1e-8, rel_tol=0))
        materials = {row['material_id']: row for row in self.spec['materials']}
        for column in science['stratigraphy'].values():
            for layer in column['bottom_to_top']:
                material = materials[layer['material_id']]
                self.assertEqual(F(layer['grain_density_kg_m3']), material['grain_density_kg_m3'])
                self.assertEqual(F(layer['porosity']), F(str(material['porosity'])))
        for law in n.erosion_laws('WORKING NON-CANON', 'owner parameter check'):
            self.assertEqual(law['k_per_year']['value'], materials[law['material_id']]['k_per_year'])
            self.assertEqual(law['reference_runoff_m_year']['value'], 1.)
        for row in science['construction']['material_accounts']:
            self.assertEqual(row['residual_mass_kg'], '0')
            self.assertEqual(row['residual_solid_volume_m3'], '0')
        self.assertEqual(self.working_result['execution']['scientific_sha256'], p.sha(science))

    def test_actual_overlap_alternative_field_response_and_adjoining_validity(self):
        base = self.working_result['scientific']
        supports = w.probes(self.spec)
        changed = w.build({'overlap': supports['overlap']}, n.ALTERNATIVE)
        type(self).alternative_result = changed
        after = changed['scientific']['stratigraphy']['overlap']
        before = base['stratigraphy']['overlap']
        carbonate = next(row for row in before['bottom_to_top'] if row['material_id'] == 'R17_NORTH_CARBONATE')
        self.assertNotIn('R17_NORTH_CARBONATE', [row['material_id'] for row in after['bottom_to_top']])
        self.assertEqual(F(before['surface_m'])-F(after['surface_m']), F(carbonate['top_m'])-F(carbonate['bottom_m']))
        self.assertNotEqual(changed['scientific']['context']['snapshot_id'], base['context']['snapshot_id'])
        for row in changed['scientific']['construction']['material_accounts']:
            self.assertEqual(row['residual_mass_kg'], '0')
        # A labelled synthetic perturbation, never rewritten source arrays.
        sample = deepcopy(base['regional_input']['sampling']['samples']['crystalline'])
        sample['crown_massif_support'] += .125
        sample['affinity_nk_01'] = .125
        context = deepcopy(base['context']); context['world_id'] = 'SYNTHETIC_SOURCE_RESPONSE_TEST'
        recipe, _ = n.compile_recipe({'crystalline': sample}, {'crystalline': supports['crystalline']},
            context, base['owner_source'], 'SYNTHETIC TEST source-response perturbation', 'SYNTHETIC TEST')
        response = regional.build(recipe)['scientific']
        self.assertEqual(F(response['stratigraphy']['crystalline']['surface_m'])-F(base['stratigraphy']['crystalline']['surface_m']), 1000)
        sample['affinity_nk_01'] = 1.1
        with self.assertRaisesRegex(ValueError, 'no clipping'):
            n.compile_recipe({'crystalline': sample}, {'crystalline': supports['crystalline']},
                context, base['owner_source'], 'SYNTHETIC TEST', 'SYNTHETIC TEST')
        mask = w._mask(self.spec)
        adjoining = {'adjacent': {'xy_m': [730000, 118000], 'area_m2': 16000000}}
        w._check_supports(self.spec, adjoining, mask)
        outer_half = {'edge': {'xy_m': [732000, 118000], 'area_m2': 16000000}}
        w._check_supports(self.spec, outer_half, mask)
        mask[149, 262] = 0
        with self.assertRaisesRegex(ValueError, 'non-authoritative'):
            w._check_supports(self.spec, outer_half, mask)
        with self.assertRaisesRegex(ValueError, 'beyond selected'):
            w._check_supports(self.spec, {'other': {'xy_m': [0, 0], 'area_m2': 16000000}}, mask)

    def test_actual_generated_columns_enter_native_r14_and_keep_lineage(self):
        initial = self.working_result['scientific']
        forcing = {key: {'discharge_m3_year': 1e6, 'hydraulic_slope': .1,
            'evidence': 'CONTROLLED LOCAL RATE PROBE; not northern regional hydrology',
            'source_status': 'WORKING NON-CANON'} for key in initial['supports']}
        result = n.incise(self.working_result, forcing, '1/1000')
        type(self).erosion_result = result
        _, native = regional.p.backend()
        before = native.LandscapeState.from_dict(initial['state']).column_map
        after = native.LandscapeState.from_dict(result['state']).column_map
        laws = {row['material_id']: row['k_per_year']['value'] for row in n.erosion_laws('WORKING NON-CANON', 'rate oracle')}
        for key, column in before.items():
            rate = float((column.surface_m-after[key].surface_m)/F(1, 1000))
            self.assertTrue(math.isclose(rate, 100*laws[column.exposed.material_id], rel_tol=1e-12, abs_tol=1e-14))
        for row in result['receipt']['global_material_balance']:
            self.assertEqual(row['residual_mass_kg'], [0, 1])
            self.assertEqual(row['residual_solid_volume_m3'], [0, 1])
        self.assertEqual(result['r17_input_scientific_sha256'], self.working_result['execution']['scientific_sha256'])
        self.assertEqual(result['r17_regional_input_sha256'], p.sha(initial['regional_input']))
        altered = deepcopy(self.working_result)
        altered['scientific']['regional_input']['sampling']['samples']['crystalline']['affinity_ed_01'] = .9
        with self.assertRaisesRegex(ValueError, 'binding differs'):
            n.incise(altered, forcing, '1/1000')


if __name__ == '__main__':
    unittest.main()
