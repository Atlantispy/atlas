"""Tiny Resources fixed-area seasonal/dry reference, not physical R13 evidence."""
from copy import deepcopy
from fractions import Fraction as F
import unittest

from work.generator_upgrade_r21 import crops, land, reduced, reduced_reference


class ReducedReferenceTests(unittest.TestCase):
    def test_resources_fixed_areas_finite_stock_and_actual_yield(self):
        outputs = {}
        for case, expected_area in (('seasonal', 10), ('exclusion', 8), ('dry', 10)):
            spec = reduced_reference.scenario(case)
            original = deepcopy(spec)
            admitted = land.prepare(**spec['land'])
            self.assertEqual(admitted['status'], 'PREPARED')
            self.assertEqual(F(admitted['ledger']['candidate_union_area_m2_exact']), expected_area)
            self.assertTrue(all(row['status'] == 'ADMITTED_HYPOTHESIS' for row in admitted['plots']))
            result = reduced.run(spec['plans'], spec['water'])
            self.assertEqual(spec, original)
            self.assertEqual(result['status'], 'MODELLED')
            self.assertEqual(F(result['planted_area_m2']), expected_area)
            self.assertFalse(result['physical_hydraulics_executed'])
            water = result['water']
            self.assertEqual(F(water['initial_stock_m3']), F(water['remaining_stock_m3'])+F(water['total_withdrawal_m3']))
            self.assertEqual(F(water['total_withdrawal_m3']), F(water['total_net_m3'])+F(water['loss_m3']))
            self.assertEqual(water['residual_m3'], '0')
            self.assertEqual(water['delivery_residual_m3'], '0')
            self.assertEqual(len(water['days']), 4)
            self.assertEqual(len(result['crops']), 2)
            for plan, actual in zip(spec['plans'], result['crops']):
                self.assertEqual(F(actual['planted_area_m2']), F(plan['area_m2']))
                direct_plan = deepcopy(plan)
                direct_plan['daily_forcing'] = actual['actual_daily_forcing']
                direct = crops.execute(direct_plan, actual['irrigation_deliveries'])
                self.assertEqual(actual['daily_water'], direct['daily_water'])
                self.assertEqual(actual['harvests'], direct['harvests'])
            outputs[case] = result
        wet, dry = outputs['seasonal'], outputs['dry']
        self.assertEqual(wet['water']['total_withdrawal_m3'], '2')
        self.assertEqual(wet['water']['total_net_m3'], '1')
        self.assertEqual(sum(F(row['irrigation_rationing_totals']['requested_gross_delivery_m3']) for row in wet['crops']), 4)
        self.assertEqual(sum(F(row['irrigation_rationing_totals']['unmet_gross_delivery_m3']) for row in wet['crops']), 2)
        self.assertEqual(dry['water']['total_withdrawal_m3'], '0')
        self.assertLess(sum(F(row['total_edible_dry_kg']) for row in dry['crops']),
                        sum(F(row['total_edible_dry_kg']) for row in wet['crops']))
        # Storage may buffer the finite-water seasonal case; do not assert an
        # immediate penalty merely because irrigation request was unfulfilled.
        spec = reduced_reference.scenario('exclusion')
        self.assertEqual(reduced.run(list(reversed(spec['plans'])), spec['water']), outputs['exclusion'])


if __name__ == '__main__':
    unittest.main()
