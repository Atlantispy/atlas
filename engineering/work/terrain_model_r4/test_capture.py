from copy import deepcopy
import json
import math
import unittest

import capture as c
from capture_fixtures import suite,split_recipe,unrepresentable_head_recipe
from test_event_settling import oracle


def run(recipe):return c.advance(c.CaptureState(**recipe['state']),**recipe['forcing'])


class CoupledCaptureTests(unittest.TestCase):
    def test_nine_repeatable_synthetic_scenarios_and_source_preservation(self):
        self.assertEqual(len(suite()),9)
        for recipe in suite():
            with self.subTest(scenario=recipe['scenario_id']):
                before=deepcopy(recipe);a,ra=run(recipe);b,rb=run(recipe)
                self.assertEqual(a,b);self.assertEqual(ra,rb);self.assertEqual(recipe,before)
                for key in ('liquid_ledger','solid_ledger'):
                    self.assertLessEqual(abs(ra[key]['residual']),ra[key]['tolerance'])
                self.assertFalse(ra['physical_acceptance']);self.assertFalse(ra['production_authorised'])

    def test_full_routed_single_and_nested_split_match_independent_oracles(self):
        for which in (1,2):
            state,report=run(split_recipe(which));expected=oracle(which)
            for field,key in (('liquid_m3','W'),('suspended_solid_m3','S'),('bed_solid_m3','B')):
                for actual,wanted in zip(getattr(state,field),expected[key]):
                    self.assertLessEqual(abs(actual-float(wanted)),1e-9+1e-12*abs(float(wanted)))
            events=report['steps'][0]['split_events']
            self.assertEqual(len(events),which)
            for actual,wanted in zip(events,expected['times']):
                self.assertLessEqual(abs(actual['absolute_time_years']-float(wanted)),1e-9+1e-11*float(wanted))

    def test_routed_equal_sill_inventory_is_not_spontaneously_mixed(self):
        recipe=suite()[-2];state,_=run(recipe)
        self.assertEqual(state.liquid_m3,tuple(recipe['state']['liquid_m3']))
        self.assertEqual(state.suspended_solid_m3,tuple(recipe['state']['suspended_solid_m3']))

    def test_genuinely_positive_head_rejoins_daughters(self):
        state,report=run(suite()[-1]);routing=report['steps'][0]['routing_after_settling']
        self.assertGreater(state.liquid_m3[1],0.)
        concentrations=[s/(w+s) for w,s in zip(state.liquid_m3,state.suspended_solid_m3)]
        self.assertLess(max(concentrations)-min(concentrations),1e-12)
        self.assertEqual(len([p for p in routing['active_pools'] if p['mixture_m3']>0]),1)

    def test_unrepresentable_positive_head_is_not_relabelled_as_zero(self):
        with self.assertRaisesRegex(ValueError,'representable'):run(unrepresentable_head_recipe())

    def test_repeated_capture_steps_and_same_prefix_restart(self):
        recipe=split_recipe(1);recipe['forcing'].update(steps=2,dt_years=.4)
        whole,report=run(recipe)
        one=deepcopy(recipe);one['forcing']['steps']=1
        first,_=run(one);restored=c.CaptureState(**json.loads(json.dumps(first.as_dict())))
        direct,rd=c.advance(first,**one['forcing']);rest,rr=c.advance(restored,**one['forcing'])
        self.assertEqual(direct,rest);self.assertEqual(rd,rr);self.assertEqual(whole,rest)
        for actual,wanted in zip(rest.suspended_solid_m3,oracle(1)['S']):
            self.assertLessEqual(abs(actual-float(wanted)),1e-9)

    def test_original_column_and_overflow_oracles(self):
        state,_=run(suite()[0]);self.assertAlmostEqual(state.suspended_solid_m3[0],.05,places=11)
        self.assertAlmostEqual(state.bed_m[0],.005,places=11)
        state,report=run(suite()[1]);r=report['steps'][0]
        self.assertAlmostEqual(r['exported_liquid_m3'],49.95,places=10)
        self.assertAlmostEqual(r['exported_suspended_solid_m3'],.05,places=10)


if __name__=='__main__':unittest.main()
