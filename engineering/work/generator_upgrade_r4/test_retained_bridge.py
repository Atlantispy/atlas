from fractions import Fraction as F
import unittest
from . import retained_bridge as bridge, hydromet as hm

E='EXPLICIT FIXED-FORCING SENSITIVITY: actual A monthly totals as constant monthly rates; no observed event chronology'


def run(**changes):
    kwargs=dict(initial_swe_m_by_scenario={s.scenario_id:F(0) for s in hm.snow_scenarios()},
        initial_stock_evidence='SYNTHETIC initial zero SWE assumption, not a measured or equilibrated A snowpack',
        model_day_seconds=86400,coefficient_day_seconds=86400,disaggregation_evidence=E,source_sha256='d'*64)
    kwargs.update(changes)
    return bridge.run(100,100,**kwargs)


class RetainedBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.result=run()

    def test_actual_A_source_and_twelve_real_months(self):
        parent=self.result['parent']
        self.assertEqual((parent['row'],parent['col'],parent['cell_km']),(100,100,5))
        self.assertEqual(parent['months'],['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'])
        self.assertEqual(len(parent['fields']['temperature_c']),12)
        self.assertTrue(parent['source_bindings'])
        self.assertFalse(parent['new_terrain_compatible'])
        self.assertEqual(self.result['duration_seconds'],365*86400)

    def test_all_three_coequal_full_monthly_ledgers(self):
        self.assertEqual(set(self.result['members']),{s.scenario_id for s in hm.snow_scenarios()})
        for member in self.result['members'].values():
            self.assertEqual(member['scenario']['standing'],'COEQUAL_SENSITIVITY')
            self.assertEqual(len(member['monthly']),12)
            self.assertEqual(member['annual_total_water_residual_m'],0)
            self.assertEqual(member['initial_swe_m']+member['annual_precipitation_m'],
                member['final_swe_m']+member['annual_liquid_to_soil_m'])

    def test_retained_snowfall_enters_once_without_repartition(self):
        fields=self.result['parent']['fields']
        for member in self.result['members'].values():
            for index,row in enumerate(member['monthly']):
                l=row['snow_ledger']
                self.assertEqual(l['snowfall_m'],F(fields['snowfall_we_mm'][index])/1000)
                self.assertEqual(l['rain_m']+l['snowfall_m'],F(fields['precipitation_mm'][index])/1000)
                self.assertEqual(l['liquid_to_soil_m'],l['rain_m']+l['melt_m'])

    def test_retained_pet_is_not_invented_PM_or_actual_ET(self):
        self.assertFalse(self.result['pm_recomputed']);self.assertFalse(self.result['realised_et_computed'])
        fields=self.result['parent']['fields']
        for member in self.result['members'].values():
            self.assertEqual(member['annual_retained_pet_m'],sum((F(v)/1000 for v in fields['pet_mm']),F()))
            for index,row in enumerate(member['monthly']):
                self.assertIsNone(row['actual_et_m'])
                self.assertEqual(row['retained_pet_mean_m_s']*row['duration_seconds'],F(fields['pet_mm'][index])/1000)

    def test_explicit_initial_stock_and_day_conventions_required(self):
        with self.assertRaises(ValueError):run(initial_swe_m_by_scenario={})
        with self.assertRaises(ValueError):run(model_day_seconds=0)
        with self.assertRaises(ValueError):run(disaggregation_evidence='')

    def test_repeat_source_bound_reference_exact(self):
        self.assertEqual(self.result,run())


if __name__=='__main__':unittest.main()
