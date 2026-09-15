"""Focused connected-feedback checks; no old terrain or full world/year run."""
from copy import deepcopy
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from work.generator_upgrade_r13 import storage
from work.generator_upgrade_r13 import soil
from work.generator_runtime_r12.store import Store
from work.generator_upgrade_r14 import pipeline as g, provenance as p, reference


class Feedback(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix='g14-')
        cls.base = Path(cls.tmp.name).resolve()
        cls.spec = reference.recipe(duration_s=600., event_count=2)
        cls.store = Store(cls.base/'c', p.sha(p.identity()))
        cls.journal = storage.Journal(cls.base/'r', cls.spec)
        cls.snapshots = []
        def commit(value):
            cls.journal.commit(value); cls.snapshots.append(deepcopy(value))
        cls.result = g.run(cls.spec, store=cls.store, on_checkpoint=commit)
        if cls.result['scientific']['status'] != 'MODELLED_GROUND_FEEDBACK':
            raise AssertionError(cls.result['scientific']['reason'])

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_actual_changed_geometry_reaches_soil_and_next_period(self):
        rows = self.result['scientific']['events']
        self.assertEqual(rows[1]['initial_cells'], rows[0]['final_cells'])
        self.assertTrue(any(step['transport']['ledger']['deposits'] for row in rows for step in row['steps']))
        final = rows[-1]['final_cells']['upper']
        self.assertNotEqual(final['model'], self.spec['cells']['upper']['model'])
        for row in rows:
            for step in row['steps']:
                for key, solved in step['soil_steps'].items():
                    self.assertEqual(solved['result']['initial_state'], step['transport']['cells'][key]['soil'])
                    self.assertEqual(solved['model'], step['transport']['cells'][key]['model'])
                    self.assertEqual(solved['result']['status'], 'MODELLED')
        self.assertEqual(final['soil']['elapsed_seconds'], 1200.)

    def test_independent_accounts_and_coupled_temporal_gate(self):
        science = self.result['scientific']
        for row in science['events']:
            self.assertTrue(g.audit_event(row, self.spec['coupling_controls']))
            self.assertTrue(all(0 <= step['error_ratio'] <= 1 for step in row['acceptance']))
        self.assertLess(abs(science['accounts']['water_residual_m3']), 1e-7)
        self.assertLess(abs(science['accounts']['energy_residual_j']), 1.)

    def test_successor_composition_is_explicit_and_sealed_code_untouched(self):
        from work.generator_upgrade_r14 import erosion
        _, native = p.backend()
        self.assertIs(native.terrain_trial.__globals__, vars(native))
        self.assertIs(native.landscape.advance.__globals__, vars(native.landscape))
        self.assertIs(native.terrain_trial.__globals__['landscape'], native.landscape)
        self.assertIsNot(native.landscape.advance, erosion.advance)
        for event in self.result['scientific']['events']:
            for step in event['steps']:
                receipt = step['transport']['ledger']['terrain']
                self.assertEqual(receipt['schema'], 'diadem.runoff-layered-sediment-trial.r14')
                self.assertNotIn('actual_R1_erosion_receipt', receipt)
                self.assertEqual(receipt['actual_R14_erosion_receipt']['schema'], erosion.SCHEMA)
        p.verify_backend()

    def test_representation_error_has_one_cumulative_budget(self):
        row = {'water_input_m3': 0., 'water_output_m3': 0.,
               'energy_input_j': 0., 'energy_output_j': 0.,
               'transport': {'ledger': {'material_export_kg': {},
                    'erosion_local_mass_representation_error_bound_kg': '1/1000'}}}
        g.audit_budget(self.spec['cells'], self.spec['cells'], [row], self.spec['coupling_controls'])
        with self.assertRaisesRegex(g.StepFailure, 'representation budget'):
            g.audit_budget(self.spec['cells'], self.spec['cells'], [row]*11, self.spec['coupling_controls'])
        row['transport']['ledger']['erosion_local_mass_representation_error_bound_kg'] = '-1'
        with self.assertRaisesRegex(g.StepFailure, 'representation budget'):
            g.audit_budget(self.spec['cells'], self.spec['cells'], [row], self.spec['coupling_controls'])

    def test_completed_cache_reuse_does_not_calculate(self):
        with patch.object(g, 'advance_event', side_effect=AssertionError('no event recomputation')):
            resumed = g.run(self.spec, store=self.store, resume=self.result['scientific']['checkpoint'])
        self.assertEqual(resumed['scientific'], self.result['scientific'])
        self.assertEqual(resumed['execution']['reused_events'], 2)

    def test_actual_incremental_journal_readback(self):
        self.assertEqual(storage.load(self.base/'r'), {'recipe': self.spec, **self.result})
        self.assertIn(1, [s['scientific']['completed_events'] for s in self.snapshots])

    def test_prefix_resume_computes_only_remaining_event(self):
        prefix = next(s['scientific']['checkpoint'] for s in self.snapshots if s['scientific']['completed_events'] == 1)
        original = g.advance_event
        with patch.object(g, 'advance_event', wraps=original) as solve:
            resumed = g.run(self.spec, store=self.store, resume=prefix)
        self.assertEqual(solve.call_count, 1)
        self.assertEqual(resumed['scientific'], self.result['scientific'])

    def test_changed_or_uncertified_checkpoint_rejected(self):
        checkpoint = deepcopy(self.result['scientific']['checkpoint'])
        checkpoint['source_sha256'] = '0'*64
        with self.assertRaisesRegex(ValueError, 'source/recipe'):
            g.run(self.spec, store=self.store, resume=checkpoint)
        empty = Store(self.base/'empty', self.store.namespace)
        with self.assertRaisesRegex(ValueError, 'certificate'):
            g.run(self.spec, store=empty, resume=self.result['scientific']['checkpoint'])

    def test_rehashed_tampered_history_is_not_certified(self):
        cp = deepcopy(self.result['scientific']['checkpoint'])
        cp['state']['accepted_events'][0]['acceptance'][0]['error_ratio'] += .01
        cp['state_sha256'] = p.sha(cp['state'])
        with self.assertRaisesRegex(ValueError, 'certificate'):
            g.run(self.spec, store=self.store, resume=cp)

    def test_profile_redistribution_is_not_hidden_by_unchanged_totals(self):
        old = self.spec['cells']; full = deepcopy(old); half = deepcopy(old)
        full['upper']['model']['layers'][0]['theta_s'] += .1
        row = self.result['scientific']['events'][0]['steps'][0]
        ratio, errors = g.compare(self.spec, old, full, half, [row], [row])
        self.assertGreater(errors['upper/porosity'], 1.)
        self.assertGreater(ratio, 1.)

    def test_cumulative_errors_do_not_get_a_fresh_budget_each_step(self):
        row = {'water_input_m3': 0., 'water_output_m3': 0.,
               'energy_input_j': .01, 'energy_output_j': 0.,
               'transport': {'ledger': {'material_export_kg': {},
                    'erosion_local_mass_representation_error_bound_kg': '0'}}}
        with self.assertRaisesRegex(g.StepFailure, 'cumulative'):
            g.audit_budget(self.spec['cells'], self.spec['cells'], [row]*101, self.spec['coupling_controls'])

    def test_unknown_material_response_retains_prefix_without_default(self):
        spec = deepcopy(self.spec); spec['deformation_laws']['mineral']['source_status'] = 'UNKNOWN'
        result = g.run(spec)
        self.assertEqual(result['scientific']['status'], 'UNKNOWN')
        self.assertEqual(result['scientific']['completed_events'], 0)

    def test_layer_indexed_roots_cannot_be_silently_moved(self):
        spec = deepcopy(self.spec)
        spec['events'][0]['forcing']['upper']['root_withdrawal_m_s'] = [1e-9]
        with self.assertRaisesRegex(ValueError, 'geometry-aware biological'):
            g.validate(spec)

    def test_synthetic_inputs_cannot_be_promoted(self):
        spec = deepcopy(self.spec); spec['source_status'] = 'WORKING NON-CANON'
        with self.assertRaisesRegex(ValueError, 'cannot be promoted'):
            g.validate(spec)

    def test_cold_soil_drives_packing_then_actually_advances(self):
        spec = reference.recipe(duration_s=60., event_count=1, erosion=False)
        for key, cell in spec['cells'].items():
            cell['soil'] = soil.initial_state(cell['model'], [-1.], [272.9])
            cell['surface_water_m3'] = 0.; cell['surface_enthalpy_j'] = 0.
            forcing = spec['events'][0]['forcing'][key]
            forcing['surface_water_flux_m_s'] = 0.
            forcing['top_heat']['value'] = forcing['bottom_heat']['value'] = 272.9
        final, row = g._trial(spec, spec['cells'], spec['events'][0], 60.)
        self.assertGreater(final['upper']['soil']['ice_water'][0], 0.)
        self.assertNotEqual(final['upper']['model']['layers'][0]['thickness_m'], .2)
        self.assertEqual(final['upper']['soil']['elapsed_seconds'], 60.)
        self.assertLess(abs(row['accounts']['water_residual_m3']), 1e-7)

    def test_combined_split_refinement_reduces_geometry_difference(self):
        spec = reference.recipe(duration_s=600., event_count=1, erosion=False)
        heights = []
        for pieces in (1, 2, 4):
            state = deepcopy(spec['cells'])
            for _ in range(pieces):
                state, row = g._trial(spec, state, spec['events'][0], 600./pieces)
            heights.append(sum(layer['thickness_m'] for layer in state['upper']['model']['layers']))
        coarse, fine = abs(heights[1]-heights[0]), abs(heights[2]-heights[1])
        self.assertGreater(coarse, 1e-12)
        self.assertGreater(coarse, 1.5*fine)


if __name__ == '__main__':
    unittest.main()
