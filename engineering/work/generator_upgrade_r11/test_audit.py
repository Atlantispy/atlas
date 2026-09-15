"""Independent rejection tests against actually computed joined products."""
from copy import deepcopy
from fractions import Fraction as F
import unittest
from . import audit, binding, fixtures


class AuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle = binding.load(); cls.parent = fixtures.parent(cls.bundle)
        cls.recipe = cls.bundle.reference.recipe(cls.bundle)
        cls.pipeline = cls.bundle.module('pipeline')
        groups = cls.pipeline.parent_units(cls.bundle, cls.recipe, cls.parent)
        cls.key = sorted(groups)[0]; cls.units = groups[cls.key]
        cls.product = cls.pipeline.evaluate_group(cls.bundle, cls.recipe, cls.parent, cls.key, cls.units)

    def test_actual_group_independent_accounts(self):
        checked = audit.group(self.bundle, self.recipe, self.parent, self.key, self.units, self.product)
        self.assertEqual(checked['water']['windows'], 12)
        self.assertGreater(checked['water']['ice_bearing_node_endpoints'], 0)
        self.assertGreater(checked['human']['restricted_capacity_windows'], 0)

    def test_false_zero_water_residual_not_trusted(self):
        p = deepcopy(self.product['water']); p['events'][0]['nodes']['upper']['ledger']['final_water_kg'] = '999'
        with self.assertRaisesRegex(ValueError, 'balance'):
            audit.water(p)

    def test_water_store_reset_rejected(self):
        p = deepcopy(self.product['water']); p['events'][1]['nodes']['upper']['start']['water_mass_kg'] = '999'
        with self.assertRaisesRegex(ValueError, 'reset|endpoint'):
            audit.water(p)

    def test_internal_substep_clock_rejected(self):
        p = deepcopy(self.product['water']); p['events'][0]['accepted_steps'][0]['end_seconds_exact'] = '7'
        with self.assertRaisesRegex(ValueError, 'clock'):
            audit.water(p)

    def test_carbon_creation_rejected(self):
        p = deepcopy(self.product['ecosystems']['upper']); p['events'][0]['budgets_kg_m2']['C']['final'] = '999'
        with self.assertRaisesRegex(ValueError, 'balance'):
            audit.ecosystem(p)

    def test_signed_nutrient_residual_not_clipped(self):
        p = deepcopy(self.product['ecosystems']['upper']); row = p['events'][0]['budgets_kg_m2']['N']
        row['numerical_residual'] = '0' if row['numerical_residual'] != '0' else '1/1000'
        with self.assertRaisesRegex(ValueError, 'balance'):
            audit.ecosystem(p)

    def test_food_stock_inflation_rejected(self):
        p = deepcopy(self.product['human']); p['events'][-1]['food'][0]['closing_kg'] = '999'
        with self.assertRaisesRegex(ValueError, 'balance'):
            audit.human(p)

    def test_calendar_rename_without_join_rejected(self):
        p = deepcopy(self.product['water']); p['events'][0]['event_id'] = 'unrelated-event'
        with self.assertRaisesRegex(ValueError, 'chronology'):
            audit.water(p)

    def test_delivery_in_advance_rejected(self):
        p = deepcopy(self.product['water']); p['events'][0]['deliveries'][0]['available_after_seconds'] = '0'
        with self.assertRaisesRegex(ValueError, 'delivery'):
            audit.water(p)

    def test_exposure_not_probability(self):
        p = deepcopy(self.product['human']); p['events'][0]['hazard_exposure'][0]['probability'] = .5
        with self.assertRaisesRegex(ValueError, 'exposure'):
            audit.human(p)

    def test_jointly_forged_water_ledger_cannot_hide_stock_change(self):
        p = deepcopy(self.product['water']); row = p['events'][0]['nodes']['upper']['ledger']
        for key in ('final_water_kg','external_in_kg'):
            row[key] = str(F(row[key])+1)
        with self.assertRaisesRegex(ValueError, 'endpoint'):
            audit.water(p)

    def test_water_final_state_not_just_reported_clock(self):
        p = deepcopy(self.product['water']); p['final_state']['nodes']['upper']['energy_j'] = '123'
        with self.assertRaisesRegex(ValueError, 'last endpoint'):
            audit.water(p)

    def test_fabricated_terminal_volume_rejected(self):
        p = deepcopy(self.product['water']); row = p['events'][0]['deliveries'][0]
        row['delivered_volume_m3'] = str(F(row['delivered_volume_m3'])+1)
        row['requested_volume_m3'] = str(F(row['requested_volume_m3'])+1)
        with self.assertRaisesRegex(ValueError, 'volume/mass'):
            audit.water(p)

    def test_omitted_nutrient_not_reported_as_audited(self):
        p = deepcopy(self.product['ecosystems']['upper']); del p['annual_budgets_kg_m2']['K']
        for event in p['events']:
            del event['budgets_kg_m2']['K']
        with self.assertRaisesRegex(ValueError, 'element inventory'):
            audit.ecosystem(p)

    def test_ecosystem_source_time_not_only_self_consistent_output(self):
        p = deepcopy(self.product['ecosystems']['upper']); p['events'][0]['duration_seconds'] = '1'
        with self.assertRaisesRegex(ValueError, 'chronology'):
            audit.ecosystem(p)

    def test_ecosystem_jointly_forged_budget_not_actual_stock(self):
        p = deepcopy(self.product['ecosystems']['upper']); row = p['events'][0]['budgets_kg_m2']['K']
        for key in ('final','external_input'):
            row[key] = str(F(row[key])+1)
        with self.assertRaisesRegex(ValueError, 'endpoint'):
            audit.ecosystem(p)

    def test_represented_capacity_cannot_increase(self):
        p = deepcopy(self.product['human']); row = p['events'][0]['capacity_responses'][0]['numerical_representation']
        row['represented_capacity_kg'] = str(F(row['exact_capacity_kg'])+1)
        with self.assertRaisesRegex(ValueError, 'representation'):
            audit.human(p)

    def test_forged_final_human_stock_rejected(self):
        p = deepcopy(self.product['human']); p['state']['water_m3']['upper'] = '123'
        with self.assertRaisesRegex(ValueError, 'native stock'):
            audit.human(p)

    def test_phase_partition_must_follow_actual_energy(self):
        p = deepcopy(self.product['water']); row = p['events'][0]['nodes']['lake']['end']
        row['liquid_water_kg'] = str(F(row['liquid_water_kg'])+1)
        row['ice_water_kg'] = str(F(row['ice_water_kg'])-1)
        # Keep the phase sum unchanged; its independent enthalpy equation still rejects.
        with self.assertRaisesRegex(ValueError, 'phase'):
            audit.water(p)


if __name__ == '__main__':
    unittest.main()
