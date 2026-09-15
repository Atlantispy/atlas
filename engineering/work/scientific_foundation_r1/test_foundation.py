from __future__ import annotations

from dataclasses import replace
from fractions import Fraction as F
import hashlib
import json
import math
import unittest
from unittest.mock import patch
import numpy as np

from . import erosion, connectivity
from .materials import Column, Layer, PhysicalProperty
from .food import FoodParcel, food_budget


class DischargeTests(unittest.TestCase):
    def setUp(self):
        self.core = erosion.bound_core()
        self.state = self.core.State(self.core.Grid(2, 2, 1, 1), (2, 1, 2, 1), (0,)*4, (0,)*4, 2700, 2700)

    def step(self, runoff, **kw):
        return erosion.channel_step(self.core, self.state, runoff, (.01,)*4, (.005,)*4,
            1., 0., .01, (1, 3), reference_runoff_m_year=kw.get("reference", 1.),
            calibration_evidence="SYNTHETIC: declared 1 m/year coefficient reference")

    def test_million_fold_runoff_reduces_incision_thousand_fold(self):
        _, wet = self.step((1.,)*4)
        _, dry = self.step((1e-6,)*4)
        self.assertAlmostEqual(wet["rate_rock_loss_solid_m3"] / dry["rate_rock_loss_solid_m3"], 1000.)
        self.assertAlmostEqual(dry["rate_rock_loss_solid_m3"], 1e-7)

    def test_uniform_reference_reproduces_area_reference(self):
        old, old_receipt = self.core.channel_step(self.state, (1.,)*4, (.01,)*4, (.005,)*4, 1., 0., .01, (1,3))
        new, receipt = self.step((1.,)*4)
        self.assertEqual(old.as_dict(), new.as_dict())
        for key in old_receipt:
            self.assertEqual(receipt[key], old_receipt[key])

    def test_zero_runoff_zero_erosion(self):
        new, receipt = self.step((0.,)*4)
        self.assertEqual(new.as_dict(), self.state.as_dict())
        self.assertEqual(receipt["rock_loss_solid_m3"], 0)

    def test_spatial_runoff_is_not_replaced_by_global_mean(self):
        state, receipt = self.step((4., 0., 1., 0.))
        self.assertAlmostEqual((2-state.bedrock_m[0])/(2-state.bedrock_m[2]), 2.)
        self.assertEqual(receipt["water_input_m3"], .05)

    def test_reference_runoff_controls_coefficient_meaning(self):
        _, first = self.step((1.,)*4)
        _, second = self.step((1.,)*4, reference=4.)
        self.assertAlmostEqual(first["rate_rock_loss_solid_m3"], 2*second["rate_rock_loss_solid_m3"])

    def test_no_arbitrary_or_bad_reference(self):
        for ref in (None, False, 0, -1, float("nan"), float("inf")):
            with self.subTest(ref=ref), self.assertRaises(ValueError):
                self.step((1.,)*4, reference=ref)

    def test_intensity_avoids_intermediate_ratio_overflow(self):
        self.assertAlmostEqual(erosion.runoff_normalised_intensity(1e300, 1e-100, 1e-300)/1e200, 1.)

    def test_intensity_extreme_range_matches_decimal_oracle(self):
        from decimal import Decimal, localcontext
        q, slope, ref=1e308, 1e-100, 5e-324
        with localcontext() as ctx:
            ctx.prec=100
            expected=float((Decimal(q)/Decimal(ref)).sqrt()*Decimal(slope))
        result=erosion.runoff_normalised_intensity(q,slope,ref)
        self.assertLessEqual(abs(result-expected),2*math.ulp(expected))

    def test_confluence_and_conservative_deposition(self):
        self.state = self.core.State(self.core.Grid(3, 3, 1, 1), (4,3,4,3,2,3,2,1,2), (1.,)*9, (0,)*9, 2700, 2700)
        after, receipt = erosion.channel_step(self.core, self.state, (1.,)*9, (.001,)*9, (.001,)*9,
            1., .1, .001, (7,), reference_runoff_m_year=1., calibration_evidence="synthetic")
        self.assertEqual(receipt["water_discharge_m3_year"][7], 9.)
        self.assertLess(abs(receipt["solid_volume_residual_m3"]), 1e-12)
        self.assertLess(abs(receipt["water_residual_m3"]), 1e-15)
        self.assertEqual(self.state.mobile_solid_m3, (1.,)*9)

    def test_untrusted_core_alias_is_not_executed(self):
        self.core.raw_drainage = lambda *a: self.fail("caller alias must not execute")
        self.step((1.,)*4)

    def test_predecessor_bytes_unchanged(self):
        self.step((1.,)*4)
        self.assertEqual(hashlib.sha256(erosion.CORE_PATH.read_bytes()).hexdigest(), erosion.CORE_SHA256)

    def test_temporal_refinement_against_independent_exponential(self):
        # A bare two-cell reach with fixed outlet solves h'=-K sqrt(Q/Rref) h/L.
        # The analytic exponential is not derived from the implementation step.
        errors=[]
        for count in (10,20,40):
            state=self.state
            for _ in range(count):
                state,_=erosion.channel_step(self.core,state,(1.,)*4,(0.,)*4,(.5,)*4,
                    1.,0.,.2/count,(1,3),reference_runoff_m_year=1.,calibration_evidence="synthetic")
            errors.append(abs(state.bedrock_m[0]-(1+math.exp(-.1))))
        self.assertGreater(errors[0]/errors[1],1.95)
        self.assertGreater(errors[1]/errors[2],1.95)

    def test_erosion_rotation_consistency(self):
        normal,receipt=self.step((1.,)*4)
        rotated=self.core.State(self.core.Grid(2,2,1,1),(2,2,1,1),(0,)*4,(0,)*4,2700,2700)
        after,other=erosion.channel_step(self.core,rotated,(1.,)*4,(.01,)*4,(.005,)*4,
            1.,0.,.01,(2,3),reference_runoff_m_year=1.,calibration_evidence="synthetic")
        self.assertEqual(after.bedrock_m,(normal.bedrock_m[0],normal.bedrock_m[2],normal.bedrock_m[1],normal.bedrock_m[3]))
        self.assertEqual(receipt["rate_rock_loss_solid_m3"],other["rate_rock_loss_solid_m3"])


class ColumnTests(unittest.TestCase):
    def setUp(self):
        self.rock = Layer("limestone", 2700, 2700, 0, "bedrock", "synthetic rock")
        self.soil = Layer("regolith", 1300, 2600, F(1,2), "immobile_regolith", "synthetic soil")
        self.sand = Layer("sand", 500, 2500, F(1,5), "mobile_sediment", "synthetic sand")
        self.column = Column(1, -2, (self.rock, self.soil, self.sand), "SYNTHETIC TEST")

    def test_burial_and_reexposure_keep_identity(self):
        self.assertEqual(self.column.exposed.material_id, "sand")
        after, receipt = self.column.strip_mass(500)
        self.assertEqual(after.exposed, self.soil)
        self.assertEqual(receipt["removed_layers"], (self.sand,))
        self.assertEqual(receipt["mass_residual_kg"], 0)
        self.assertEqual(after.deposit(self.sand), self.column)

    def test_erosion_through_contact_is_persistent(self):
        after, receipt = self.column.strip_mass(800)
        self.assertEqual(after.exposed.material_id, "regolith")
        self.assertEqual(after.exposed.mass_kg, 1000)
        self.assertEqual([p.material_id for p in receipt["removed_layers"]], ["sand", "regolith"])
        after2, _ = after.strip_mass(1000)
        self.assertEqual(after2.exposed, self.rock)

    def test_finite_stock_no_invented_underlying_rock(self):
        after, receipt = self.column.strip_mass(5000)
        self.assertIsNone(after.exposed)
        self.assertEqual(after.surface_m, -2)
        self.assertEqual(receipt["unmet_mass_kg"], 500)

    def test_independent_bulk_height_oracle(self):
        self.assertEqual(self.column.surface_m, F(1,4))
        self.assertEqual(self.column.mass_kg, 4500)

    def test_json_recovery_preserves_exact_column(self):
        altered, _ = self.column.strip_mass(F(1,3))
        self.assertEqual(Column.from_dict(json.loads(json.dumps(altered.as_dict()))), altered)

    def test_sequential_removal_matches_one_total(self):
        first, _ = self.column.strip_mass(F(1000,3))
        second, _ = first.strip_mass(F(1400,3))
        single, _ = self.column.strip_mass(800)
        self.assertEqual(second, single)

    def test_bad_layers_reject(self):
        for change in ({"mass_kg": -1}, {"porosity": 1}, {"grain_density_kg_m3": 0}, {"material_id": ""}, {"evidence": ""}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                replace(self.sand, **change)

    def test_ordinal_affinity_cannot_be_permeability(self):
        score = PhysicalProperty("carbonate_affinity", .8, "1", "working score", "WORKING NON-CANON")
        with self.assertRaisesRegex(ValueError, "meaning/units"):
            score.require("permeability", "m2")

    def test_unknown_property_not_zero(self):
        item = PhysicalProperty("permeability", None, "m2", "unresolved", "UNKNOWN")
        with self.assertRaisesRegex(ValueError, "unresolved"):
            item.require("permeability", "m2")


class FoodTests(unittest.TestCase):
    def setUp(self):
        self.parcel = FoodParcel("one", 100, 2, .5, .1, 1000, 50, 50, "synthetic explicit yield/water", "SYNTHETIC TEST")

    def budget(self, parcel=None, population=10):
        return food_budget([self.parcel if parcel is None else parcel], available_land_m2=200,
            annual_energy_kcal_per_person=10000, fixed_population=population)

    def test_exact_independent_mass_and_energy_example(self):
        value = self.budget()
        self.assertEqual(value["total_available_energy_kcal_year"], 90000)
        self.assertEqual(value["energy_only_person_equivalents"], 9)
        self.assertEqual(value["rows"][0]["mass_residual_kg_year"], 0)
        self.assertEqual(value["energy_balance_kcal_year"], -10000)

    def test_population_cannot_create_supply(self):
        a, b = self.budget(population=1), self.budget(population=10000)
        self.assertEqual(a["total_available_energy_kcal_year"], b["total_available_energy_kcal_year"])
        self.assertEqual(b["fixed_population"], 10000)

    def test_land_changes_independent_supply(self):
        a = self.budget()
        b = self.budget(replace(self.parcel, allocated_area_m2=200))
        self.assertEqual(b["total_available_energy_kcal_year"], 2*a["total_available_energy_kcal_year"])

    def test_unknown_yield_remains_unknown(self):
        result = self.budget(replace(self.parcel, attainable_yield_kg_m2_year=None, source_status="UNKNOWN"))
        self.assertIsNone(result["total_available_energy_kcal_year"])
        self.assertIsNone(result["energy_only_person_equivalents"])
        self.assertEqual(result["unknown_parcel_ids"], ["one"])

    def test_water_deficit_does_not_invent_drought_yield(self):
        with self.assertRaisesRegex(ValueError, "water regime"):
            self.budget(replace(self.parcel, crop_water_available_m3_year=49))

    def test_land_overallocation_and_duplicates_reject(self):
        with self.assertRaisesRegex(ValueError, "exceeds"):
            self.budget(replace(self.parcel, allocated_area_m2=201))
        with self.assertRaisesRegex(ValueError, "duplicate"):
            food_budget([self.parcel]*2, available_land_m2=1000, annual_energy_kcal_per_person=1, fixed_population=1)

    def test_energy_equivalent_overflow_cannot_escape_as_infinity(self):
        parcel=FoodParcel("tiny",1,1,1,0,1,0,0,"synthetic","SYNTHETIC TEST")
        with self.assertRaisesRegex(ValueError,"person equivalents"):
            food_budget([parcel],available_land_m2=1,annual_energy_kcal_per_person=1e-320,fixed_population=1)


class ConnectivityTests(unittest.TestCase):
    def test_barrier_blocks_nearby_endpoints(self):
        allowed = np.ones((5,5), bool); allowed[:,2] = False
        a = np.zeros((5,5), bool); b = a.copy(); a[2,1] = True; b[2,3] = True
        value = connectivity.seasonal_reachability(a,b,allowed,dx_m=1,dy_m=1,max_endpoint_distance_m=10,max_unsuitable_gap_m=10)
        self.assertFalse(value["reachable_both"].any())

    def test_pass_allows_real_detour(self):
        allowed = np.ones((5,5), bool); allowed[1:,2] = False
        seed = np.zeros((5,5), bool); seed[2,1] = True
        distance = connectivity.path_distance(seed,allowed,dx_m=1,dy_m=1)
        self.assertEqual(distance[2,3], 6.)

    def test_diagonal_cannot_cut_blocked_corner(self):
        allowed = np.eye(2,dtype=bool); seed = np.zeros((2,2),bool); seed[0,0]=True
        self.assertTrue(math.isinf(connectivity.path_distance(seed,allowed,dx_m=1,dy_m=1)[1,1]))

    def test_no_endpoint_is_infinite_not_fabricated_nearby(self):
        self.assertTrue(np.isinf(connectivity.path_distance(np.zeros((2,2),bool),np.ones((2,2),bool),dx_m=1,dy_m=1)).all())

    def test_anisotropic_cell_support(self):
        seed=np.zeros((3,3),bool); seed[0,0]=True
        distance=connectivity.path_distance(seed,np.ones((3,3),bool),dx_m=3,dy_m=4)
        self.assertEqual(distance[1,1],5.)
        self.assertEqual(distance[0,2],6.)

    def test_gap_limit_is_enforced_along_path(self):
        a=np.zeros((1,9),bool); b=a.copy(); a[0,0]=True; b[0,8]=True
        value=connectivity.seasonal_reachability(a,b,np.ones((1,9),bool),dx_m=1,dy_m=1,max_endpoint_distance_m=10,max_unsuitable_gap_m=3)
        self.assertFalse(value["reachable_both"].any())

    def test_inherited_gap_is_explicitly_radius_not_segment_length(self):
        a=np.zeros((1,7),bool); b=a.copy(); a[0,0]=True; b[0,6]=True
        value=connectivity.seasonal_reachability(a,b,np.ones((1,7),bool),dx_m=1,dy_m=1,max_endpoint_distance_m=10,max_unsuitable_gap_m=3)
        self.assertTrue(value["reachable_both"].all())
        self.assertIn("radius, not continuous",value["gap_parameter_semantics"])

    def predictors(self):
        shape=(5,5); ones=np.ones(shape,np.float32); zero=np.zeros(shape,np.float32)
        alpine=zero.copy(); alpine[:,0]=1
        winter=zero.copy(); winter[:,-1]=1
        return dict(alpine=alpine, monthly={"snowfree_fraction":ones}, atmospheric_moisture=ones,
            mean_slope=zero,movement_p={"mean_slope_degrees_max":30.,"ruggedness_11km_m_max":200.,
                "seasonal_endpoint_support_min":.9,"dry_or_unsuitable_gap_km_max":10.,
                "summer_winter_endpoint_distance_km_max":20.,"avalanche_track_danger_max":.5},
            ruggedness=zero,raw={"A":{"winter_browse":winter}},family="A",generic_shelter=ones,
            water_margin=ones,snow_persistence=zero,trough=ones,tpi=zero,relative_position=zero,
            surface_stability=ones,avalanche_track=zero,land=np.ones(shape,bool),volcanic_danger=zero,
            snow_p={"geothermal_danger_max":.5})

    def test_actual_hs17_component_uses_path_connectivity(self):
        predictors=self.predictors()
        free=connectivity.corrected_hs17_movement(predictors,dx_m=1000,dy_m=1000)
        self.assertTrue((free["movement_support"]>0).any())
        predictors["land"][:,2]=False
        blocked=connectivity.corrected_hs17_movement(predictors,dx_m=1000,dy_m=1000)
        self.assertFalse((blocked["movement_support"]>0).any())
        self.assertNotIn("movement",predictors["raw"]["A"])

    def test_actual_hs17_opens_only_at_usable_pass(self):
        predictors=self.predictors(); predictors["mean_slope"][:,2]=40
        blocked=connectivity.corrected_hs17_movement(predictors,dx_m=1000,dy_m=1000)
        self.assertFalse(blocked["reachable_both"].any())
        predictors["mean_slope"][0,2]=0
        passed=connectivity.corrected_hs17_movement(predictors,dx_m=1000,dy_m=1000)
        self.assertTrue(passed["reachable_both"].any())

    def test_non_boolean_masks_and_misaligned_arrays_reject(self):
        with self.assertRaises(ValueError):
            connectivity.path_distance(np.ones((2,2)),np.ones((2,2),bool),dx_m=1,dy_m=1)
        predictors=self.predictors(); predictors["mean_slope"]=np.ones((2,2))
        with self.assertRaises(ValueError):
            connectivity.corrected_hs17_movement(predictors,dx_m=1000,dy_m=1000)

    def test_predecessor_drift_rejects(self):
        with patch.object(connectivity,"HS17_SHA256","0"*64), self.assertRaisesRegex(ValueError,"source changed"):
            connectivity.corrected_hs17_movement(self.predictors(),dx_m=1000,dy_m=1000)

    def test_missing_subpredictor_cannot_turn_into_positive_support(self):
        predictors=self.predictors(); predictors["monthly"]["snowfree_fraction"][0,0]=np.nan
        with self.assertRaisesRegex(ValueError,"missing physical support"):
            connectivity.corrected_hs17_movement(predictors,dx_m=1000,dy_m=1000)

    def test_missing_threshold_is_not_empty_habitat(self):
        predictors=self.predictors(); predictors["movement_p"]["seasonal_endpoint_support_min"]=np.nan
        with self.assertRaisesRegex(ValueError,"supported range"):
            connectivity.corrected_hs17_movement(predictors,dx_m=1000,dy_m=1000)

    def test_barrier_unreachable_result_matches_independent_flood_fill(self):
        rng=np.random.default_rng(127)
        for _ in range(20):
            allowed=rng.uniform(size=(6,7))>.25
            allowed[0,0]=True
            seed=np.zeros((6,7),bool); seed[0,0]=True
            seen={(0,0)}; queue=[(0,0)]
            # Four-face flood reachability is identical to no-corner-cut D8,
            # and independent of the weighted shortest-path implementation.
            for row,col in queue:
                for rr,cc in ((row-1,col),(row+1,col),(row,col-1),(row,col+1)):
                    if 0<=rr<6 and 0<=cc<7 and allowed[rr,cc] and (rr,cc) not in seen:
                        seen.add((rr,cc)); queue.append((rr,cc))
            result=connectivity.path_distance(seed,allowed,dx_m=3,dy_m=4)
            self.assertEqual(set(zip(*np.where(np.isfinite(result)))),seen)


if __name__ == "__main__":
    unittest.main()
