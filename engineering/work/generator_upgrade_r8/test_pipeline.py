"""Actual source-bound R7 -> R8 joins, uncertainty and checkpoint replay."""
from copy import deepcopy
from fractions import Fraction as F
import unittest
from . import binding


class ConnectedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.b = binding.load(); cls.p = cls.b.pipeline
        cls.r = cls.b.reference.recipe(cls.b)
        cls.full = cls.b.run(cls.r)
        cls.soil = cls.full['soil_result']; cls.exposure = cls.full['seasonal']
        cls.member = sorted(cls.full['state']['members'])[0]
        cls.cell_id = 'lower'
        cls.cell = cls.full['state']['members'][cls.member][cls.cell_id]

    def altered(self, change):
        r = deepcopy(self.r); change(r)
        return self.p.evaluate_cell(self.b, r, self.soil, self.exposure, self.member, self.cell_id)

    def test_actual_parent_identity_and_completed_soil(self):
        self.assertEqual(self.soil['source_sha256'], self.b.parent.source_sha256)
        self.assertEqual(self.full['state']['soil_result_sha256'], self.p.seasonal.digest(self.soil))
        self.assertGreater(self.soil['state']['completed_exposures'], 0)

    def test_six_complete_source_cells(self):
        self.assertEqual(self.full['state']['completed_cells'], 6)
        self.assertEqual({m: set(cs) for m, cs in self.full['state']['members'].items()},
                         {m: set(cs) for m, cs in self.soil['state']['members'].items()})

    def test_108_actual_pft_counterfactuals(self):
        rows = [p for cs in self.full['state']['members'].values() for c in cs.values()
                for fam in c['pft_results'].values() for p in fam.values()]
        self.assertEqual(len(rows), 108)
        self.assertEqual({p['schema'] for p in rows}, {'diadem.pft-seasonal-admissibility.r8'})
        self.assertTrue(all(p['status'] in ('PASS', 'FAIL') for p in rows))

    def test_current_root_capacity_source_join(self):
        for fam in self.cell['pft_results'].values():
            for ident, row in fam.items():
                cap = self.cell['capacities'][ident]
                self.assertEqual(row['inputs']['capacity']['capacity_m'], cap['capacity_m'])
                self.assertEqual(row['source_binding']['capacity_sha256'], self.p.seasonal.digest(cap))
                self.assertEqual(row['source_binding']['soil_support_id'], self.cell['soil_support_id'])

    def test_exact_365_day_coverage(self):
        for fam in self.cell['pft_results'].values():
            for row in fam.values():
                self.assertEqual(sum((F(e['duration_seconds']) for e in row['inputs']['events']), F()), F(365*86400))

    def test_independent_water_ledgers(self):
        for fam in self.cell['pft_results'].values():
            for row in fam.values():
                for endpoint in ('lower', 'upper'):
                    cycle = row['water'][endpoint]
                    residual = cycle['initial_m'] + cycle['input_m'] - cycle['all_actual_transpiration_m'] - cycle['overflow_m'] - cycle['final_m']
                    self.assertLess(abs(residual), 1e-9)
                    self.assertLess(abs(float(F(cycle['numerical_residual_m']))), 1e-9)

    def test_snow_liquid_not_precipitation_double_counted(self):
        cycle = self.exposure['members'][self.member]['cells'][self.cell_id]
        liquid = sum(float(F(e['duration_seconds'])) * e['liquid_input_m_s'] for e in cycle['events'])
        for fam in self.cell['pft_results'].values():
            for row in fam.values():
                self.assertAlmostEqual(row['water']['lower']['input_m'], liquid, places=12)

    def test_new_terrain_seasonal_identity(self):
        self.assertEqual(self.full['state']['seasonal_sha256'], self.p.seasonal.digest(self.exposure))
        cycle = self.exposure['members'][self.member]['cells'][self.cell_id]
        for fam in self.cell['pft_results'].values():
            for row in fam.values():
                self.assertEqual(row['source_binding']['seasonal_cycle_sha256'], self.p.seasonal.digest(cycle))

    def test_real_reference_classes_compatible(self):
        for cs in self.full['state']['members'].values():
            for cell in cs.values():
                c = cell['classification']
                self.assertEqual(c['status'], 'MODELLED_POTENTIAL')
                self.assertIn(c['formation']['primary_code'], self.p.biomes.COMPATIBILITY[c['broad']['primary_code']])
                self.assertIn('COMPETITION_AND_DISTURBANCE_UNRESOLVED', c['uncertainty'])

    def test_map_area_not_ensemble_summed(self):
        for product in self.full['map_products'].values():
            self.assertEqual(F(product['represented_area_m2']), 3000000)
            self.assertEqual(sum((F(v) for v in product['class_area_m2'].values()), F()), 3000000)
            self.assertEqual(product['coverage'], 'ALL_SUPPLIED_CELLS')

    def test_transitions_preserve_declared_edges(self):
        for product in self.full['map_products'].values():
            self.assertFalse(product['transitions']['classes_modified'])
            self.assertEqual(len(product['transitions']['edges']), 1)
            self.assertEqual(product['transitions']['edges'][0]['length_m'], 1000)

    def test_real_cover_overlay_cannot_force_biome(self):
        def change(r):
            r['actual_vegetation_overlays'] = [{'overlay_id': 'forest', 'cell_ids': ['lower'], 'label': 'actual historical forest', 'evidence': 'separate test overlay', 'source_status': 'WORKING NON-CANON'}]
        changed = self.altered(change)
        self.assertEqual(self.p.seasonal.plain(changed['classification']), self.cell['classification'])

    def test_missing_aeration_is_unknown_not_wetland(self):
        changed = self.altered(lambda r: r['cell_context']['lower']['external_gates'].clear())
        statuses = {v['status'] for fam in changed['pft_results'].values() for v in fam.values()}
        self.assertLessEqual(statuses, {'UNKNOWN', 'FAIL'})
        self.assertIn('UNKNOWN', statuses)  # A separately proven necessary-condition FAIL still excludes a PFT.
        self.assertEqual(changed['classification']['status'], 'UNKNOWN')
        self.assertIsNone(changed['classification']['formation']['primary_code'])

    def test_failed_chemical_applicability_rejects_plants(self):
        def change(r):
            for spec in r['pfts'].values():
                spec['chemical_regime'].update(minimum_ph_water=13, maximum_ph_water=14)
        changed = self.altered(change)
        self.assertEqual({v['status'] for fam in changed['pft_results'].values() for v in fam.values()}, {'FAIL'})
        self.assertIsNone(changed['classification']['formation']['primary_code'])

    def test_missing_chemistry_not_fertility_index_substitution(self):
        cell = deepcopy(self.soil['state']['members'][self.member]['lower']); cell['fertility'] = None
        self.assertEqual(self.p.chemical_gate(cell, self.r['pfts']['grass']['chemical_regime'])['status'], 'UNKNOWN')

    def test_assay_protocol_mismatch_rejected(self):
        rule = deepcopy(self.r['pfts']['grass']['chemical_regime']); rule['cec_method'] = 'different method'
        with self.assertRaises(ValueError):
            self.p.chemical_gate(self.soil['state']['members'][self.member]['lower'], rule)

    def test_shallower_rooting_changes_actual_storage(self):
        changed = self.altered(lambda r: r['pfts']['grass']['rooting'].update(maximum_root_depth_m=0.1))
        self.assertLess(changed['capacities']['grass']['capacity_m'], self.cell['capacities']['grass']['capacity_m'])
        self.assertNotEqual(changed['pft_results']['R8_B']['grass']['metrics']['active_actual_to_potential_transpiration_ratio'],
                            self.cell['pft_results']['R8_B']['grass']['metrics']['active_actual_to_potential_transpiration_ratio'])

    def test_coequal_demand_hypotheses_are_actually_executed(self):
        rows = [self.cell['pft_results'][key]['grass'] for key in ('R8_A', 'R8_B', 'R8_C')]
        demands = [r['water']['lower']['active_potential_transpiration_m'] for r in rows]
        self.assertLess(demands[0], demands[1]); self.assertLess(demands[1], demands[2])
        self.assertTrue(all('may NOT be summed' in r['source_binding']['demand_hypothesis'] for r in rows))

    def test_mask_zero_distinct_from_unknown(self):
        sea = self.altered(lambda r: r['cell_context']['lower']['domain'].update(kind='SEA'))
        unknown = self.altered(lambda r: r['cell_context']['lower']['domain'].update(kind='UNKNOWN'))
        self.assertEqual(sea['classification']['formation']['primary_code'], 0)
        self.assertIsNone(unknown['classification']['formation'])

    def test_checkpoint_full_and_restart_exact(self):
        stopped = self.b.run(self.r, stop_after=1)
        saved = self.b.checkpoint(stopped)
        restored = self.b.run(self.r, resume=saved)
        self.assertEqual(restored, self.full)
        self.assertEqual(self.b.checkpoint(restored), self.b.checkpoint(self.full))
        self.assertEqual(stopped['state']['completed_cells'], 1)
        self.assertTrue(all(v['coverage']=='PARTIAL_CHECKPOINT' for v in stopped['map_products'].values()))

    def test_rechecksummed_forgery_rejected_by_actual_replay(self):
        checkpoint = self.b.checkpoint(self.full)
        checkpoint['state']['members'][self.member]['lower']['capacities']['grass']['capacity_m'] += 0.01
        checkpoint['state_sha256'] = self.p.seasonal.digest(checkpoint['state'])
        with self.assertRaisesRegex(ValueError, 'replay'):
            self.b.run(self.r, resume=checkpoint)

    def test_checkpoint_different_recipe_rejected(self):
        checkpoint = self.b.checkpoint(self.full); r = deepcopy(self.r); r['limits'] += ' changed'
        with self.assertRaisesRegex(ValueError, 'binding differs'):
            self.b.run(r, resume=checkpoint)

    def test_no_install_canon_or_optimisation_claim(self):
        for key in ('production_installed', 'canon_changed', 'optimisation_performed', 'actual_vegetation_used_as_classifier_input'):
            self.assertIs(self.full[key], False)

    def test_unknown_edge_endpoint_rejected_before_partial_execution(self):
        r = deepcopy(self.r); r['edges'][0]['a'] = 'absent'
        with self.assertRaisesRegex(ValueError, 'adjacency'):
            self.p.parse(self.b, r)

    def test_duplicate_reverse_edge_rejected(self):
        r = deepcopy(self.r); r['edges'].append({**r['edges'][0], 'a': 'lower', 'b': 'upper'})
        with self.assertRaisesRegex(ValueError, 'adjacency'):
            self.p.parse(self.b, r)

    def test_self_edge_rejected(self):
        r = deepcopy(self.r); r['edges'][0]['a'] = 'lower'
        with self.assertRaisesRegex(ValueError, 'adjacency'):
            self.p.parse(self.b, r)

    def test_duplicate_overlay_cell_rejected(self):
        r = deepcopy(self.r); r['actual_vegetation_overlays'] = [{'overlay_id':'x','cell_ids':['lower','lower'],'label':'x','evidence':'x','source_status':'CANON'}]
        with self.assertRaises(ValueError):
            self.p.parse(self.b, r)

    def test_political_forcing_rejected(self):
        r = deepcopy(self.r); r['political_border'] = 'forest'
        with self.assertRaises(ValueError):
            self.p.parse(self.b, r)

    def test_preinjected_chemical_gate_rejected(self):
        r = deepcopy(self.r); r['cell_context']['lower']['external_gates']['chemical_regime'] = {'status':'PASS','evidence':'injected'}
        with self.assertRaises(ValueError):
            self.p.parse(self.b, r)

    def test_missing_independent_domain_rejected(self):
        r = deepcopy(self.r); del r['cell_context']['lower']
        with self.assertRaises(ValueError):
            self.p.parse(self.b, r)

    def test_family_identity_mismatch_rejected(self):
        r = deepcopy(self.r); r['families'][0]['family_id'] = 'unbound'
        with self.assertRaises(ValueError):
            self.p.parse(self.b, r)

    def test_nonfinite_demand_rejected(self):
        r = deepcopy(self.r); r['pfts']['grass']['reference_transpiration_fraction'] = float('nan')
        with self.assertRaises(ValueError):
            self.p.parse(self.b, r)


if __name__ == '__main__':
    unittest.main()
