"""Independent actual-driver snow/demand boundary checks; no alternate solver."""
from fractions import Fraction as F
import unittest
from . import pipeline as p, hydromet as hm
from .reference import recipe


class CoupledHydrometTests(unittest.TestCase):
    def model(self,*,swe=1e-6):
        r=recipe()
        r['initial_swe_m']={k:swe for k in r['initial_swe_m']}
        for law in r['physical_recipe']['erosion']:law['k_per_year']=0
        return r,p.parse(r,'a'*64)

    def test_actual_depletion_split_transfers_each_snow_store_once(self):
        r,m=self.model();scenario=m.scenarios[0];initial=p.initial(m,scenario)
        out=p.trial(m,initial,r['events'][1],scenario,F(60))
        self.assertGreater(len(out['joint_history']),1)
        cursor=F()
        for row in out['joint_history']:
            self.assertEqual(F(row['start_seconds']),cursor)
            cursor+=F(row['duration_seconds'])
        self.assertEqual(cursor,60)
        for key in initial['snow']:
            self.assertEqual(out['snow'][key].swe_m,0)
            melt=sum((F(x['cells'][key]['snow_ledger']['melt_m']) for x in out['joint_history']),F())
            self.assertEqual(melt,initial['snow'][key].swe_m)

    def test_cold_then_warm_total_precipitation_not_counted_twice(self):
        r,m=self.model();scenario=m.scenarios[0];start=p.initial(m,scenario)
        cold=p.trial(m,start,r['events'][0],scenario,F(60))
        warm=p.trial(m,cold,r['events'][1],scenario,F(60))
        for key in start['snow']:
            rows=[x['cells'][key]['snow_ledger'] for x in warm['joint_history']]
            inputs=start['snow'][key].swe_m+sum((F(x['precipitation_m']) for x in rows),F())
            outputs=warm['snow'][key].swe_m+sum((F(x['liquid_to_soil_m']) for x in rows),F())
            self.assertEqual(inputs,outputs)

    def test_actual_PM_canopy_allocation_reaches_R3_root_forcing(self):
        r,m=self.model(swe=0);scenario=m.scenarios[0];start=p.initial(m,scenario);event=r['events'][1]
        generated=p.atmosphere(m,start['physical'],event)
        out=p.trial(m,start,event,scenario,F(60))
        for key,row in generated['cells'].items():
            expected=hm.penman_monteith(row,hm.DemandSurface(**event['surfaces'][key]),m.constants,
                evidence=event['evidence'],source_status=p.STATUS)['potential_evaporation_m_s']*event['vegetation'][key]['reference_demand_fraction']
            self.assertEqual(out['physical']['water'][key]['forcing']['potential_et_m_s'],expected)
            ledger=out['physical']['water'][key]['ledger']
            self.assertLessEqual(ledger['actual_et_m'],ledger['potential_et_m']*(1+1e-12))

    def test_complete_split_vs_two_halves_conserves_physical_SWE(self):
        r,m=self.model();scenario=m.scenarios[0];start=p.initial(m,scenario);event=r['events'][1]
        full=p.trial(m,start,event,scenario,F(60))
        half=p.trial(m,start,event,scenario,F(30));fine=p.trial(m,half,event,scenario,F(30))
        for key in start['snow']:
            self.assertEqual(full['snow'][key].swe_m,fine['snow'][key].swe_m)
            for quantity in ('precipitation_m','melt_m','liquid_to_soil_m'):
                totals=[sum((F(x['cells'][key]['snow_ledger'][quantity]) for x in s['joint_history']),F()) for s in (full,fine)]
                self.assertEqual(*totals)


if __name__=='__main__':unittest.main()
