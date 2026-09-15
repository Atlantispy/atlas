from copy import deepcopy
from dataclasses import replace
import math
import unittest

import capture as c
from capture_fixtures import suite


def run(recipe):
    return c.advance(c.CaptureState(**recipe["state"]),**recipe["forcing"])


class CaptureTests(unittest.TestCase):
    def test_closed_column_joint_geometry_and_phase_oracle(self):
        state,report=run(suite()[0])
        self.assertAlmostEqual(state.suspended_solid_m3[0],.05,places=11)
        self.assertAlmostEqual(state.bed_solid_m3[0],.05,places=11)
        self.assertAlmostEqual(state.bed_m[0],.005,places=11)
        self.assertAlmostEqual(state.liquid_m3[0],100.,places=11)
        self.assertAlmostEqual(report["steps"][-1]["routing_after_settling"]["water_surface_m"][0],10.01,places=11)

    def test_mixed_overflow_exports_both_phases(self):
        state,report=run(suite()[1]);r=report["steps"][0]
        self.assertAlmostEqual(sum(state.liquid_m3),49.95,places=10)
        self.assertAlmostEqual(sum(state.suspended_solid_m3),.05,places=10)
        self.assertAlmostEqual(r["exported_liquid_m3"],49.95,places=10)
        self.assertAlmostEqual(r["exported_suspended_solid_m3"],.05,places=10)

    def test_bed_only_input_displaces_water_without_fake_suspension(self):
        state,report=run(suite()[3]);r=report["steps"][0]
        self.assertAlmostEqual(state.bed_m[1],.1,places=11)
        self.assertAlmostEqual(sum(state.liquid_m3),49.,places=10)
        self.assertAlmostEqual(r["exported_liquid_m3"],1.,places=10)
        self.assertEqual(sum(state.suspended_solid_m3),0.)

    def test_smooth_tracer_refinement_has_declared_order(self):
        recipe=suite()[2];expected=.1*(-math.expm1(-.1));errors=[]
        for steps in (10,20,40):
            recipe["forcing"].update(steps=steps,dt_years=1./steps)
            state,_=run(recipe);errors.append(abs(sum(state.suspended_solid_m3)-expected))
        for a,b in zip(errors,errors[1:]):self.assertGreaterEqual(math.log2(a/b),.8)

    def test_restart_state_is_complete_and_step_equivalent(self):
        recipe=suite()[4];whole,_=run(recipe)
        state=c.CaptureState(**recipe["state"]);forcing=deepcopy(recipe["forcing"]);forcing["steps"]=2
        halfway,_=c.advance(state,**forcing)
        restored=c.CaptureState(**halfway.as_dict())
        rest,_=c.advance(restored,**forcing)
        self.assertEqual(whole,rest)

    def test_every_fixture_is_repeatable_and_inputs_preserved(self):
        for recipe in suite():
            original=deepcopy(recipe);a,ra=run(recipe);b,rb=run(recipe)
            self.assertEqual(recipe,original);self.assertEqual(a,b);self.assertEqual(ra,rb)
            self.assertFalse(ra["physical_acceptance"]);self.assertFalse(ra["shoreline_capture_acceptance"])
            self.assertLessEqual(abs(ra["liquid_ledger"]["residual"]),ra["liquid_ledger"]["tolerance"])
            self.assertLessEqual(abs(ra["solid_ledger"]["residual"]),ra["solid_ledger"]["tolerance"])

    def test_empty_closed_flat_remains_exactly_flat(self):
        state=c.CaptureState([2,2],[1.]*4,[3.]*4,[0.]*4,[0.]*4,[0.]*4)
        result,report=c.advance(state,steps=2,dt_years=1.,outlets=[],connectivity=4,
            liquid_input_m3_year=[0.]*4,suspended_input_m3_year=[0.]*4,bed_input_solid_m3_year=[0.]*4,
            settling_m_year=1.,source_label="SYNTHETIC empty")
        self.assertEqual(result.bed_m,state.bed_m);self.assertEqual(result.liquid_m3,state.liquid_m3)

    def test_wrong_phase_status_geometry_and_numeric_inputs_rejected(self):
        source=c.CaptureState(**suite()[0]["state"])
        for changes in ({"liquid_m3":[0.]},{"source_status":"CANON"},{"cell_area_m2":[0.]},{"time_years":True},
                        {"bedrock_m":[float("nan")]},{"solid_density_kg_m3":0.}):
            with self.assertRaises(ValueError):replace(source,**changes)
        recipe=suite()[1];recipe["forcing"]["liquid_input_m3_year"]=[0.]*3
        recipe["forcing"]["suspended_input_m3_year"]=[0.,1.,0.]
        with self.assertRaisesRegex(ValueError,"carrier"):run(recipe)

    def test_step_and_wall_envelopes(self):
        for changes in ({"steps":0},{"steps":True},{"steps":4097},{"wall_seconds":0},{"dt_years":float("inf")}):
            recipe=suite()[0];recipe["forcing"].update(changes)
            with self.assertRaises(ValueError):run(recipe)


if __name__=="__main__":unittest.main()
