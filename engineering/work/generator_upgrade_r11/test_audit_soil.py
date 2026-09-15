"""Mutations of a real source-bound formed-soil/organic/water continuation."""
from copy import deepcopy
from fractions import Fraction as F
import unittest
from unittest.mock import patch
from . import audit_soil as a, soil_feedback, snapshot
from . import test_soil_feedback as fixtures


def test_data_bindings():
    return fixtures.test_data_bindings()


class SoilAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.SoilFeedbackTests.setUpClass()
        cls.fixture = fixtures.SoilFeedbackTests
        cls.bundle = cls.fixture.bundle
        cls.product = soil_feedback.reference_continuation(cls.fixture.adapter, cls.fixture.unit,
            cls.fixture.formed, cls.fixture.ecosystem, organic_grain_density_kg_m3=1500,
            source_binding_sha256=cls.bundle.source_sha256, evidence='Actual material/pressure audit regression')

    def check(self, product=None, ecosystem=None):
        return a.continuation(self.bundle, self.fixture.unit, self.fixture.formed,
            self.fixture.ecosystem if ecosystem is None else ecosystem,
            self.product if product is None else product)

    def rejected(self, change):
        p = deepcopy(self.product); change(p)
        with self.assertRaises(ValueError): self.check(p)

    def test_actual_saved_join_independent_accounts(self):
        result = self.check(); self.assertEqual(result['layers'], len(self.fixture.unit['hydrology']['column']['layers']))
        self.assertEqual(result['changed_organic_supports'], 1)
        self.assertGreater(result['accepted_water_steps'], 0)
        SoilAuditTests.actual_audit = result

    def test_auditor_never_calls_solver(self):
        native = self.fixture.sw
        class ReadOnlyNative:
            def __getattr__(self, name):
                if name in ('advance', '_step', '_stage'):
                    raise AssertionError('audit must not call solver')
                return getattr(native, name)
        with patch.object(a, '_native', return_value=ReadOnlyNative()): self.check()

    def test_changed_parent_source_rejected(self):
        self.rejected(lambda p: p.update(actual_r10_unit_sha256='0'*64))

    def test_changed_formed_source_rejected(self):
        self.rejected(lambda p: p.update(formed_cell_sha256='0'*64))

    def test_changed_source_binding_rejected(self):
        self.rejected(lambda p: p.update(source_binding_sha256='0'*64))

    def test_changed_ecosystem_source_even_rehashed_rejected(self):
        e = deepcopy(self.fixture.ecosystem); e['source_binding_sha256'] = '0'*64
        p = deepcopy(self.product); p['ecosystem_result_sha256'] = snapshot.sha(e)
        with self.assertRaises(ValueError): self.check(p, e)

    def test_joint_forged_organic_endpoint_and_delta_rejected(self):
        e = deepcopy(self.fixture.ecosystem); p = deepcopy(self.product)
        pair = e['final_state']['organic_state']['fast_carbon_kg_m2']; value = F(*pair)+1
        e['final_state']['organic_state']['fast_carbon_kg_m2'] = [value.numerator, value.denominator]
        row = e['events'][-1]['soil_material_change']
        row['organic_dry_mass_change_kg_m2'] = str(F(row['organic_dry_mass_change_kg_m2'])+1/F(e['inputs']['organic_law']['carbon_fraction_dry_matter']))
        p['ecosystem_result_sha256'] = snapshot.sha(e)
        with self.assertRaises(ValueError): self.check(p, e)

    def test_missing_layer_ledger_rejected(self):
        self.rejected(lambda p: p['rebind']['layer_ledgers'].pop())

    def test_wrong_rebound_column_hash_rejected(self):
        self.rejected(lambda p: p['rebind'].update(new_column_sha256='0'*64))

    def test_false_balanced_remap_water_rejected(self):
        def change(p):
            row = p['rebind']['layer_ledgers'][0]
            row['old_water_m'] = str(F(row['old_water_m'])+1)
            row['new_water_m'] = str(F(row['new_water_m'])+1)
        self.rejected(change)

    def test_changed_mineral_mass_even_input_rehashed_rejected(self):
        def change(p):
            r = p['rebind']; material = r['inputs']['material_layers']
            c = next(c for m in material.values() for c in m['constituents'] if c['kind'] == 'MINERAL')
            c['old_mass_kg_m2'] = c['new_mass_kg_m2'] = '999'
            r['inputs_sha256'] = snapshot.sha(r['inputs'])
        self.rejected(change)

    def test_changed_exact_packing_depth_rejected(self):
        self.rejected(lambda p: p['rebind']['layer_ledgers'][0].update(new_thickness_m_exact='999'))

    def test_frozen_phase_even_input_rehashed_rejected(self):
        def change(p):
            r = p['rebind']; key = next(iter(r['inputs']['ice_water_m_by_layer']))
            r['inputs']['ice_water_m_by_layer'][key] = '1/1000'; r['inputs_sha256'] = snapshot.sha(r['inputs'])
        self.rejected(change)

    def test_remap_pressure_cannot_claim_equilibrium(self):
        self.rejected(lambda p: p['rebind'].update(current_pressure_status='CURRENT'))

    def test_remap_cannot_consume_old_forcing(self):
        self.rejected(lambda p: p['rebind'].update(forcing_events_consumed=['old-year']))

    def test_solver_final_clock_rejected(self):
        self.rejected(lambda p: p['actual_water_step']['state'].update(elapsed_seconds=0))

    def test_solver_state_head_disagrees_with_pressure_layer(self):
        self.rejected(lambda p: p['actual_water_step']['state']['head_m'].__setitem__(0, -999.))

    def test_final_water_stock_disagrees_with_theta(self):
        self.rejected(lambda p: p['actual_water_step']['layers'][0].update(water_m3_m2_exact_represented='999'))

    def test_exact_internal_clock_rejected(self):
        self.rejected(lambda p: p['actual_water_step']['numerics']['accepted_steps_detail'][0].update(end_seconds_exact='999'))

    def test_duration_fraction_not_binary64_rejected(self):
        self.rejected(lambda p: p['actual_water_step']['numerics']['accepted_steps_detail'][0].update(dt_seconds_exact='1/3'))

    def test_controls_not_relaxed(self):
        self.rejected(lambda p: p['actual_water_step']['numerics']['controls'].update(total_mass_atol_m=1))

    def test_new_forcing_not_old_rain(self):
        self.rejected(lambda p: p['actual_water_step']['forcing'].update(surface_input_m_s=.1))

    def test_numerical_source_pin_rejected(self):
        self.rejected(lambda p: p['actual_water_step']['numerical_binding']['adapter'].update(sha256='0'*64))

    def test_pressure_requires_actual_fluid_conversion(self):
        self.rejected(lambda p: p['actual_water_step']['layers'][0].update(signed_pore_pressure_pa=999))

    def test_gross_flux_not_hidden_by_equal_net(self):
        def change(p):
            b = p['actual_water_step']['ledger']; b['face_downward_m'][-1] = b['face_upward_m'][-1] = 1
        self.rejected(change)

    def test_total_storage_not_self_reported(self):
        self.rejected(lambda p: p['actual_water_step']['ledger'].update(initial_storage_m=999, final_storage_m=999))

    def test_no_frozen_richards_claim(self):
        self.rejected(lambda p: p.update(frozen_richards_implemented=True))

    def test_actual_held_soil_thermal_audit(self):
        checked = a.thermal_reference(self.fixture.spec, self.fixture.thermal_result)
        self.assertEqual(checked['layers'], len(self.fixture.spec['cells']))
        self.assertFalse(checked['water_mass_changed']); SoilAuditTests.actual_thermal_audit = checked

    def test_thermal_joint_false_balanced_energy_rejected(self):
        p = deepcopy(self.fixture.thermal_result); row = p['events'][0]['thermal_result']['energy_ledger_j']
        row['initial'] = str(F(row['initial'])+1); row['final'] = str(F(row['final'])+1)
        with self.assertRaises(ValueError): a.thermal_reference(self.fixture.spec, p)

    def test_thermal_phase_not_trusted_from_status(self):
        p = deepcopy(self.fixture.thermal_result); samples = p['events'][0]['thermal_result']['accepted_steps'][0]['end_layers']
        samples[next(iter(samples))]['temperature_k'] = 999
        with self.assertRaises(ValueError): a.thermal_reference(self.fixture.spec, p)

    def test_thermal_cannot_be_current_richards_moisture(self):
        p = deepcopy(self.fixture.thermal_result); p['ecosystem_moisture_pairing'] = 'CURRENT'
        with self.assertRaises(ValueError): a.thermal_reference(self.fixture.spec, p)

    def test_thermal_internal_clock_changed(self):
        p = deepcopy(self.fixture.thermal_result)
        p['events'][0]['thermal_result']['accepted_steps'][0]['elapsed_seconds_exact'] = '999'
        with self.assertRaises(ValueError): a.thermal_reference(self.fixture.spec, p)


if __name__ == '__main__': unittest.main()
