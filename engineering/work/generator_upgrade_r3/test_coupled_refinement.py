"""Predeclared first-order coupled time-refinement checks on physical support.

120/60/30-second outer caps mean actual accepted split steps of 60/30/15 s.
For asymptotic first-order splitting, successive differences tend to ratio 2.
The deliberately broad, predeclared acceptance band [1.4, 3.0] permits pre-
asymptotic terms but rejects absent/degrading convergence. These are numerical
checks on one explicit scenario, not empirical or universal convergence claims.
"""
from copy import deepcopy
from fractions import Fraction as F
import math
import unittest
from unittest.mock import patch

from . import pipeline, reference
from .deps import landscape

STEP_CAPS = (120, 60, 30)
ORDER_RATIO_BAND = (1.4, 3.0)
# Fixed scientific test thresholds, declared before observing these runs.
FLOORS = {"sediment_export_kg": 1e-10, "height_change_m": 1e-10,
          "water_export_m3": 1e-10, "head_integral_m2": 1e-9}


def experiment(cap):
    recipe = reference.recipe()
    recipe["coupling_controls"].update(initial_dt_seconds=cap,max_dt_seconds=cap,min_dt_seconds=1)
    # Inner nonlinear/water error must be well below outer splitting differences.
    recipe["water_controls"].update(theta_atol=1e-8,head_atol_m=1e-8,
        flux_integral_atol_m=1e-10,relative_tolerance=1e-6,
        nonlinear_mass_atol_m=1e-12,total_mass_atol_m=1e-10)
    return recipe


def columns(result):
    return {k:landscape.Column.from_dict(p["column"]) for k,p in result["state"]["profiles"].items()}


def measures(result, recipe):
    final = columns(result)
    initial = {k:landscape.Column.from_dict(row["profile"]["column"]) for k,row in recipe["cells"].items()}
    history = result["state"]["history"]
    return {
        "sediment_export_kg": float(sum((F(row["exported_mass_kg"])
            for step in history for row in step["terrain"]["material_balances"]),F(0))),
        "height_change_m": float(sum((abs(final[k].surface_m-initial[k].surface_m) for k in final),F(0))),
        "water_export_m3": float(sum((F(step[key]) for step in history
            for key in ("runoff_export_m3","sediment_porewater_export_m3","bottom_out_m3")),F(0)))
    }


def physical_head_distance(left, right):
    """L1 pressure-head difference on shared *absolute elevation* intervals.

    No index matching and no translating each result to its own new surface.
    Non-overlap thickness is reported independently, never silently a zero head.
    Piecewise-constant values are the actual cell-centre pressure heads returned
    by the finite-volume solver, not a fabricated smooth pressure profile.
    """
    lc,rc=columns(left),columns(right)
    distance=0.0;nonoverlap=0.0
    for cell in lc:
        la=left["state"]["water"][cell]["layers"];ra=right["state"]["water"][cell]["layers"]
        ls=float(lc[cell].surface_m);rs=float(rc[cell].surface_m)
        covered=0.0
        for a in la:
            bottom_a=ls-a["bottom_depth_m"];top_a=ls-a["top_depth_m"]
            for b in ra:
                bottom_b=rs-b["bottom_depth_m"];top_b=rs-b["top_depth_m"]
                overlap=max(0.0,min(top_a,top_b)-max(bottom_a,bottom_b))
                distance+=overlap*abs(a["head_m"]-b["head_m"]);covered+=overlap
        thickness_l=sum(r["bottom_depth_m"]-r["top_depth_m"] for r in la)
        thickness_r=sum(r["bottom_depth_m"]-r["top_depth_m"] for r in ra)
        nonoverlap+=max(0.0,thickness_l+thickness_r-2*covered)
    return distance,nonoverlap


def run_refinement():
    recipes=[experiment(cap) for cap in STEP_CAPS]
    results=[pipeline.run(recipe) for recipe in recipes]
    values=[measures(result,recipe) for result,recipe in zip(results,recipes)]
    differences={name:[abs(values[i][name]-values[i+1][name]) for i in (0,1)] for name in values[0]}
    head=[physical_head_distance(results[i],results[i+1]) for i in (0,1)]
    differences["head_integral_m2"]=[row[0] for row in head]
    return recipes,results,{"caps_seconds":list(STEP_CAPS),"measures":values,"differences":differences,
        "ratios":{k:(v[0]/v[1] if v[1] else None) for k,v in differences.items()},
        "observed_orders":{k:(math.log2(v[0]/v[1]) if min(v)>0 else None) for k,v in differences.items()},
        "head_nonoverlap_m":[row[1] for row in head],"predeclared_ratio_band":list(ORDER_RATIO_BAND),
        "predeclared_floors":FLOORS}


class CoupledRefinementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.recipes,cls.results,cls.report=run_refinement()

    def test_same_physical_scenario_and_residence_time_at_all_caps(self):
        templates=[]
        for recipe in self.recipes:
            template=deepcopy(recipe)
            for key in ("initial_dt_seconds","max_dt_seconds"):
                template["coupling_controls"].pop(key)
            templates.append(template)
        self.assertEqual(templates[0],templates[1]);self.assertEqual(templates[1],templates[2])
        self.assertTrue(all(c["surface_residence_seconds"]==600 for r in self.recipes for c in r["cells"].values()))

    def test_actual_accepted_steps_follow_requested_refinement(self):
        for cap,result in zip(STEP_CAPS,self.results):
            history=result["state"]["history"]
            self.assertEqual({F(row["duration_seconds"]) for row in history},{F(cap,2)})
            self.assertEqual(sum((F(row["duration_seconds"]) for row in history),F(0)),240)

    def test_exported_solid_first_order(self):self.assert_order("sediment_export_kg")
    def test_changed_terrain_first_order(self):self.assert_order("height_change_m")
    def test_water_exports_first_order(self):self.assert_order("water_export_m3")
    def test_heads_on_common_physical_support_first_order(self):self.assert_order("head_integral_m2")

    def assert_order(self,name):
        a,b=self.report["differences"][name]
        self.assertGreater(min(a,b),FLOORS[name],"difference is unresolved at the predeclared test floor, not proof of order")
        self.assertGreaterEqual(a/b,ORDER_RATIO_BAND[0],self.report)
        self.assertLessEqual(a/b,ORDER_RATIO_BAND[1],self.report)

    def test_exact_solid_and_bounded_water_conservation_at_each_resolution(self):
        for result,recipe in zip(self.results,self.recipes):
            self.assertLessEqual(abs(float(F(result["water_residual_m3"]))),
                len(result["state"]["history"])*recipe["coupling_controls"]["budget_atol_m3"])
            for step in result["state"]["history"]:
                self.assertEqual(F(step["terrain"]["water_residual_m3"]),0)
                for row in step["terrain"]["material_balances"]:
                    self.assertEqual(F(row["mass_residual_kg"]),0);self.assertEqual(F(row["solid_residual_m3"]),0)

    def test_no_hidden_head_comparison_on_index_only(self):
        for result in self.results:
            for cell in result["state"]["water"].values():
                self.assertGreater(len(cell["layers"]),2,"actual deposited layers must reach Water")
        self.assertTrue(all(v>0 for v in self.report["head_nonoverlap_m"]))
        self.assertLess(self.report["head_nonoverlap_m"][1],self.report["head_nonoverlap_m"][0])

    def test_actual_next_trial_routes_from_previous_changed_surfaces(self):
        for result in self.results:
            history=result["state"]["history"]
            for previous,current in zip(history,history[1:]):
                self.assertEqual(previous["terrain"]["final_surfaces_m"],current["terrain"]["initial_surfaces_m"])
            for step in history:
                surfaces={k:F(v) for k,v in step["terrain"]["initial_surfaces_m"].items()}
                for row in step["terrain"]["water_routing"]:
                    receiver=F(row["outlet_elevation_m"]) if row["receiver_id"] is None else surfaces[row["receiver_id"]]
                    drop=surfaces[row["cell_id"]]-receiver
                    self.assertGreater(drop,0)
                    self.assertEqual(F(row["slope"]),drop/F(row["length_m"]))

    def test_wet_transfer_uses_each_actual_source_layer_water_ratio(self):
        recipe=experiment(120);model=pipeline.parse(recipe);before=pipeline.initial(model)
        actual=pipeline.tt.terrain_trial;captured=[]
        def trace(*args,**kwargs):
            out=actual(*args,**kwargs);captured.append(out);return out
        with patch.object(pipeline.tt,"terrain_trial",side_effect=trace):
            after=pipeline.trial(model,before,recipe["events"][0],F(60))
        self.assertEqual(len(captured),1);terrain=captured[0]
        source_ratio={}
        for event in terrain.erosion_events:
            cell,index=event["source_cell"],event["source_layer_index"]
            profile=before["profiles"][cell]
            source_ratio[cell,index]=profile.bindings[index].water_volume_m3/profile.column.layers[index].mass_kg
        expected_export=sum((source_ratio[r["source_cell"],r["source_layer_index"]]*r["mass_kg"] for r in terrain.exports),F(0))
        self.assertEqual(F(after["history"][-1]["sediment_porewater_export_m3"]),expected_export)
        imported=after["history"][-1]["wet_deposition"]
        self.assertEqual(len(imported),len(terrain.deposit_events))
        for deposit,receipt in zip(terrain.deposit_events,imported):
            expected=sum((source_ratio[r["source_cell"],r["source_layer_index"]]*r["mass_kg"] for r in deposit["sources"]),F(0))
            self.assertEqual(F(*receipt["imported_water_m3"]),expected)
            self.assertEqual(F(*receipt["water_residual_m3"]),0)

    def test_independent_common_elevation_head_norm_oracle(self):
        # Same surface-relative two-cell array, translated physical column:
        # interval [1,1.5] switches pressure from 1 to 0, so L1=0.5 m2.
        def sample(base):
            layers=tuple(landscape.Layer("rock",10,10,0,"bedrock","SYNTHETIC") for _ in range(2))
            col=landscape.Column(1,base,layers,"SYNTHETIC TEST")
            return {"state":{"profiles":{"x":{"column":col.as_dict()}},"water":{"x":{"layers":[
                {"top_depth_m":0,"bottom_depth_m":1,"head_m":1},
                {"top_depth_m":1,"bottom_depth_m":2,"head_m":0}]}}}}
        self.assertEqual(physical_head_distance(sample(0),sample(F(1,2))),(0.5,1.0))


if __name__=="__main__":unittest.main()
