"""Tiny synthetic remap tests; no retained terrain or annual generation."""
from copy import deepcopy
from fractions import Fraction as F
import unittest

from work.generator_upgrade_r13 import soil
from work.generator_upgrade_r14 import remap
from work.test_r13_soil import fixture, PROVENANCE


def column_fixture(*, cold=False, saturated=False):
    model, _, controls = fixture()
    model.update(freezing_model=soil.PAINTER_KARRA, clapeyron_beta=1.)
    state = soil.initial_state(model, [.1 if saturated else -1.], [272.9 if cold else 280.], elapsed_seconds=123.)
    layer = model['layers'][0]
    mass = F(2650)*(1-F(layer['theta_s']))*F(layer['thickness_m'])
    materials = [{'material_id': 'synthetic', 'phase': 'immobile_regolith',
                  'grain_density_kg_m3': 2650, 'dry_mass_kg_m2': str(mass), 'evidence': PROVENANCE['evidence']}]
    column = {'area_m2': 1., 'base_elevation_m': 10., 'model': model, 'soil': state, 'materials': materials}
    return column, controls


def law_fixture(column):
    layer, material = column['model']['layers'][0], column['materials'][0]
    law = {'reference_specific_volume_m3_kg': str(F(layer['thickness_m'])/F(material['dry_mass_kg_m2'])),
        'reference_water_m3_kg': 0., 'reference_ice_m3_kg': 0., 'water_volume_response': .1,
        'ice_volume_response': .2, 'relaxation_time_s': 60., 'min_porosity': .1, 'max_porosity': .9,
        'reference_porosity': layer['theta_s'], 'reference_ksat_m_s': layer['saturated_conductivity_m_s'],
        'reference_alpha_per_m': layer['vg_alpha_per_m'], 'ksat_porosity_exponent': 3.,
        'alpha_porosity_exponent': 1., 'mechanical_energy_per_bulk_volume_j_m3': 100., **PROVENANCE}
    return {'synthetic': law}


class RemapTests(unittest.TestCase):
    def targets(self, column):
        return remap.layer_stocks(column['model'], column['soil'], column['materials'])

    def check_balances(self, result, controls):
        ledger = result['ledger']
        self.assertLessEqual(abs(F(ledger['water_residual_m'])), F(controls['water_atol_m']))
        self.assertLessEqual(abs(F(ledger['energy_residual_j_m2'])), F(controls['energy_atol_j_m2']))
        self.assertEqual(F(ledger['final_water_m'])-F(ledger['initial_target_water_m']), F(ledger['water_residual_m']))
        self.assertEqual(F(ledger['final_enthalpy_j_m2'])-F(ledger['initial_target_enthalpy_j_m2'])-F(ledger['mechanical_energy_j_m2']), F(ledger['energy_residual_j_m2']))

    def test_layer_stocks_keep_exact_represented_mass_water_and_dry_capacity(self):
        column, _ = column_fixture()
        row = self.targets(column)[0]; layer = column['model']['layers'][0]
        self.assertEqual(row['material'], column['materials'][0])
        self.assertEqual(F(row['water_m']), F(column['soil']['total_water'][0])*F(layer['thickness_m']))
        self.assertEqual(F(row['dry_heat_capacity_j_m2_k']), F(layer['dry_heat_capacity_j_m3_k'])*F(layer['thickness_m']))

    def test_inconsistent_initial_solid_geometry_rejected(self):
        column, _ = column_fixture()
        column['materials'][0]['dry_mass_kg_m2'] = '1'
        with self.assertRaisesRegex(ValueError, 'solid geometry'):
            self.targets(column)

    def test_warm_packing_change_conserves_W_E_mass_capacity_and_clock(self):
        column, controls = column_fixture()
        target = self.targets(column); target[0]['layer']['theta_s'] = .5
        result = remap.rebuild(column['model'], target, controls, elapsed_seconds=123.)
        self.check_balances(result, controls)
        self.assertEqual(result['materials'], column['materials'])
        self.assertEqual(result['soil']['elapsed_seconds'], 123.)
        self.assertGreater(result['model']['layers'][0]['thickness_m'], .1)
        self.assertLess(abs(float(F(result['ledger']['dry_capacity_residual_j_m2_k']))), 1e-8)
        self.assertEqual(result['soil']['temperature_k'][0], 273.15+result['soil']['temperature_offset_k'][0])

    def test_frozen_repacking_and_explicit_mechanical_heat_are_conservative(self):
        column, controls = column_fixture(cold=True)
        target = self.targets(column); target[0]['layer']['theta_s'] = .5
        result = remap.rebuild(column['model'], target, controls, elapsed_seconds=123., mechanical_energy_j_m2=[500.])
        self.check_balances(result, controls)
        self.assertGreater(result['soil']['ice_water'][0], 0.)
        self.assertEqual(F(result['ledger']['mechanical_energy_j_m2']), 500)
        self.assertFalse(result['ledger']['pressure_requires_resolution'])

    def test_unchanged_rebuild_preserves_laws_and_identity_with_declared_residuals(self):
        column, controls = column_fixture(cold=True)
        result = remap.rebuild(column['model'], self.targets(column), controls, elapsed_seconds=123.)
        self.check_balances(result, controls)
        self.assertEqual(result['model'], column['model'])
        self.assertAlmostEqual(result['soil']['head_m'][0], column['soil']['head_m'][0], delta=controls['head_atol_m'])
        self.assertAlmostEqual(result['soil']['temperature_offset_k'][0], column['soil']['temperature_offset_k'][0], delta=controls['temperature_atol_k'])

    def test_reversible_packing_and_nanometre_temperature_accuracy(self):
        column, controls = column_fixture(cold=True)
        original_phi = column['model']['layers'][0]['theta_s']
        targets = self.targets(column); targets[0]['layer']['theta_s'] = .5
        expanded = remap.rebuild(column['model'], targets, controls, elapsed_seconds=123.)
        reverse = remap.layer_stocks(expanded['model'], expanded['soil'], expanded['materials'])
        reverse[0]['layer']['theta_s'] = original_phi
        restored = remap.rebuild(expanded['model'], reverse, controls, elapsed_seconds=123.)
        self.check_balances(restored, controls)
        self.assertEqual(restored['model']['layers'][0]['thickness_m'], column['model']['layers'][0]['thickness_m'])
        self.assertAlmostEqual(restored['soil']['temperature_offset_k'][0], column['soil']['temperature_offset_k'][0], delta=1e-6)
        tiny, controls = column_fixture()
        tiny['model']['layers'][0]['thickness_m'] = 2.3e-8
        layer = tiny['model']['layers'][0]
        tiny['materials'][0]['dry_mass_kg_m2'] = str(F(2650)*(1-F(layer['theta_s']))*F(layer['thickness_m']))
        tiny['soil'] = soil.initial_state(tiny['model'], [-1.], [280.], elapsed_seconds=123.)
        result = remap.rebuild(tiny['model'], self.targets(tiny), controls, elapsed_seconds=123.)
        self.assertAlmostEqual(result['soil']['temperature_offset_k'][0], tiny['soil']['temperature_offset_k'][0], delta=controls['temperature_atol_k']*.01)
        self.assertEqual(result['model']['layers'][0]['thickness_m'], 2.3e-8)

    def test_saturated_seed_is_explicit_and_never_marked_resolved(self):
        column, controls = column_fixture(cold=True, saturated=True)
        target = self.targets(column)
        result = remap.rebuild(column['model'], target, controls, elapsed_seconds=123.)
        self.check_balances(result, controls)
        self.assertEqual(result['soil']['head_m'], [.1])
        self.assertTrue(result['ledger']['pressure_requires_resolution'])
        target[0]['head_guess_m'] = -.1
        with self.assertRaisesRegex(ValueError, 'nonnegative'):
            remap.rebuild(column['model'], target, controls, elapsed_seconds=123.)

    def test_overfill_and_at_residual_rejected_without_silent_water_ports(self):
        column, controls = column_fixture()
        for kind in ('overfill', 'residual'):
            target = self.targets(column); layer = target[0]['layer']
            value = F(layer['theta_s'])*F(layer['thickness_m'])+F(1,10**18) if kind == 'overfill' else F(layer['theta_r'])*F(layer['thickness_m'])
            target[0]['water_m'] = str(value)
            with self.assertRaisesRegex(ValueError, 'port'):
                remap.rebuild(column['model'], target, controls, elapsed_seconds=123.)

    def test_deformation_has_real_packing_hydraulic_and_energy_feedback(self):
        column, controls = column_fixture(cold=True)
        old = deepcopy(column); laws = law_fixture(column)
        result = remap.deform(column, laws, 60., controls)
        self.assertEqual(column, old)
        self.assertEqual(result['status'], 'MODELLED'); self.check_balances(result, controls)
        changed = result['column']; before, after = column['model']['layers'][0], changed['model']['layers'][0]
        self.assertGreater(after['theta_s'], before['theta_s'])
        self.assertGreater(after['saturated_conductivity_m_s'], before['saturated_conductivity_m_s'])
        self.assertAlmostEqual(after['saturated_conductivity_m_s'], laws['synthetic']['reference_ksat_m_s']*(after['theta_s']/before['theta_s'])**3, delta=1e-20)
        self.assertAlmostEqual(after['theta_r']*after['thickness_m'], before['theta_r']*before['thickness_m'], delta=1e-17)
        self.assertEqual(changed['soil']['elapsed_seconds'], old['soil']['elapsed_seconds'])
        self.assertGreater(float(F(result['ledger']['mechanical_energy_j_m2'])), 0.)

    def test_missing_unknown_and_out_of_range_deformation_laws_rejected(self):
        column, controls = column_fixture()
        with self.assertRaises(soil.UnknownInput):
            remap.deform(column, {}, 60., controls)
        laws = law_fixture(column); laws['synthetic']['source_status'] = 'UNKNOWN'
        with self.assertRaises(soil.UnknownInput):
            remap.deform(column, laws, 60., controls)
        laws = law_fixture(column); laws['synthetic']['water_volume_response'] = 100.
        with self.assertRaisesRegex(ValueError, 'porosity'):
            remap.deform(column, laws, 60., controls)

    def test_remap_inverse_budget_and_finite_energy_are_explicit(self):
        column, controls = column_fixture(cold=True)
        controls['max_nonlinear_evaluations'] = 1
        with self.assertRaisesRegex(ValueError, 'budget'):
            remap.rebuild(column['model'], self.targets(column), controls, elapsed_seconds=123.)
        controls['max_nonlinear_evaluations'] = 80
        with self.assertRaisesRegex(ValueError, 'finite'):
            remap.rebuild(column['model'], self.targets(column), controls, elapsed_seconds=123., mechanical_energy_j_m2=[float('inf')])

    def test_large_finite_carried_capacity_obeys_existing_integer_bit_bound(self):
        numerator, denominator = (1 << 8191)+1, (1 << 8190)+1
        represented = f'{numerator}/{denominator}'
        self.assertGreater(len(represented), 4096)
        self.assertLessEqual(len(represented), 5000)
        self.assertEqual(numerator.bit_length(), 8192)
        self.assertEqual(denominator.bit_length(), 8191)
        value = remap._q(represented, 'carried dry heat capacity', positive=True)
        self.assertEqual(value, F(numerator, denominator))
        self.assertEqual(float(value), 2.)
        too_many_bits = f'{(1 << 8192)+1}/{(1 << 8191)+1}'
        with self.assertRaisesRegex(ValueError, 'bounded finite'):
            remap._q(too_many_bits, 'carried dry heat capacity', positive=True)
        with self.assertRaisesRegex(ValueError, 'bounded represented'):
            remap._q('1'*5001, 'carried dry heat capacity', positive=True)


if __name__ == '__main__':
    unittest.main()
