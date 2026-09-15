"""Independent tiny physical/LP/conservation oracles for actual land-food API."""
from dataclasses import replace
from fractions import Fraction as F
import itertools
import json
import math
import unittest
from unittest.mock import patch

from . import land_food as model
from .agroclimate import RootZone, DayForcing, crop_season


EVIDENCE = "EXPLICIT SYNTHETIC SCENARIO, NOT A CROP OR DIADEM CALIBRATION"
STATUS = "SYNTHETIC TEST"


def land(identifier="p", x=0, area=10, water="w"):
    return model.LandParcel(identifier, (x, 0, x+area, 1), water, EVIDENCE, STATUS)


def crop(identifier="a", parcel="p", energy=10, water=2, **kw):
    return model.CropOption(identifier, parcel, "synthetic_"+identifier, 1, 1, 0, energy, water, 1,
                            EVIDENCE, STATUS, **kw)


def pool(amount=10, name="w"):
    return model.WaterPool(name, amount, EVIDENCE, STATUS)


def allocate(parcels=None, crops=None, pools=None, **kw):
    return model.allocate_land_food(parcels if parcels is not None else [land()],
        crops if crops is not None else [crop(),crop("b",energy=6,water=0)],
        pools if pools is not None else [pool()], frame_id="SYNTHETIC_COMMON_METRE_FRAME",
        annual_energy_kcal_per_person=kw.pop("annual_energy_kcal_per_person", 100),
        fixed_population=kw.pop("fixed_population", 10), **kw)


def vertex_energy(e1, e2, w1, w2, water, area=10):
    """Independent exact two-variable vertex enumeration, no optimiser calls."""
    lines=[(F(1),F(0),F(0)),(F(0),F(1),F(0)),(F(1),F(1),F(area)),(F(w1),F(w2),F(water))]
    best=F(0)
    for a,b in itertools.combinations(lines,2):
        det=a[0]*b[1]-a[1]*b[0]
        if not det:
            continue
        x=(a[2]*b[1]-a[1]*b[2])/det; y=(a[0]*b[2]-a[2]*b[0])/det
        if x>=0 and y>=0 and x+y<=area and w1*x+w2*y<=water:
            best=max(best,e1*x+e2*y)
    return float(best)


class LandFoodTests(unittest.TestCase):
    def test_analytical_land_water_tradeoff(self):
        result=allocate()
        self.assertEqual(result["status"],"OPTIMAL")
        self.assertAlmostEqual(result["food_budget"]["total_available_energy_kcal_year"],80)
        self.assertEqual({r["option_id"]:r["allocated_area_m2"] for r in result["allocations"]},{"a":5,"b":5})
        self.assertEqual(result["water_ledger"][0]["withdrawal_m3_year"],10)
        self.assertLessEqual(result["solver"]["certified_gap_kcal_year"],1e-12)

    def test_shared_water_is_not_repeated_per_parcel(self):
        result=allocate([land("p",0),land("q",20)], [crop("a","p"),crop("b","q",8,1)], [pool(15)])
        self.assertEqual(result["status"],"OPTIMAL")
        self.assertAlmostEqual(result["food_budget"]["total_available_energy_kcal_year"],105)
        self.assertEqual(result["water_ledger"][0]["withdrawal_m3_year"],15)
        # Independent half-square-metre brute force includes this exact optimum.
        best=max(10*x+8*y for x in [k/2 for k in range(21)] for y in [k/2 for k in range(21)] if 2*x+y<=15)
        self.assertEqual(best,105)

    def test_two_variable_exact_vertex_oracles(self):
        for e1,e2,w1,w2,water in ((10,6,2,0,10),(7,11,1,3,16),(3,5,2,1,7),
                                  (12,8,3,2,19),(0,4,0,1,3),(1,1,1,1,8),(9,1,7,0,4)):
            with self.subTest(parameters=(e1,e2,w1,w2,water)):
                result=allocate(crops=[crop("a",energy=e1,water=w1),crop("b",energy=e2,water=w2)],pools=[pool(water)])
                self.assertEqual(result["status"],"OPTIMAL",result)
                expected=vertex_energy(e1,e2,w1,w2,water)
                self.assertAlmostEqual(result["food_budget"]["total_available_energy_kcal_year"],expected,places=7)
                self.assertGreaterEqual(result["solver"]["energy_upper_bound_kcal_year"]+1e-12,expected)

    def test_efficiency_gross_net_loss_conservation(self):
        result=allocate(crops=[replace(crop(),irrigation_efficiency=.5),crop("b",energy=6,water=0)])
        self.assertEqual(result["status"],"OPTIMAL")
        self.assertAlmostEqual(result["food_budget"]["total_available_energy_kcal_year"],70)
        water=result["water_ledger"][0]
        self.assertEqual(water["withdrawal_m3_year"],10)
        self.assertEqual(water["delivered_irrigation_m3_year"],5)
        self.assertEqual(water["delivery_loss_m3_year"],5)
        self.assertEqual(water["withdrawal_m3_year"],water["delivered_irrigation_m3_year"]+water["delivery_loss_m3_year"])

    def test_land_and_water_sensitivity(self):
        outputs=[allocate(pools=[pool(w)]) for w in (0,4,10,20,40)]
        energies=[r["food_budget"]["total_available_energy_kcal_year"] for r in outputs]
        self.assertEqual(energies,[60,68,80,100,100])
        doubled=allocate(parcels=[land(area=20)],pools=[pool(20)])
        self.assertEqual(doubled["food_budget"]["total_available_energy_kcal_year"],160)

    def test_yield_energy_loss_response(self):
        option=replace(crop(water=0),attainable_yield_kg_m2_year=2,edible_fraction=.75,loss_fraction=.2,edible_energy_kcal_kg=100)
        result=allocate(crops=[option],pools=[pool(0)])
        self.assertAlmostEqual(result["food_budget"]["total_available_energy_kcal_year"],1200)
        row=result["food_budget"]["rows"][0]
        self.assertEqual((row["harvest_kg_year"],row["non_edible_kg_year"],row["loss_kg_year"],row["available_food_kg_year"]),(20,5,3,12))
        self.assertEqual(row["mass_residual_kg_year"],0)

    def test_population_and_energy_need_do_not_create_supply(self):
        small=allocate(fixed_population=1,annual_energy_kcal_per_person=10)
        large=allocate(fixed_population=100000,annual_energy_kcal_per_person=1000)
        for key in ("allocations","water_ledger","physical_input_sha256","solver"):
            self.assertEqual(small[key],large[key])
        self.assertEqual(small["food_budget"]["total_available_energy_kcal_year"],large["food_budget"]["total_available_energy_kcal_year"])
        self.assertNotEqual(small["food_budget"]["energy_demand_kcal_year"],large["food_budget"]["energy_demand_kcal_year"])

    def test_overlapping_productive_rectangles_reject(self):
        with self.assertRaisesRegex(ValueError,"overlap"):
            allocate([land("p"),land("q",5)],[],[pool()])
        self.assertEqual(allocate([land("p"),land("q",10)],[],[pool()])["status"],"OPTIMAL")

    def test_fractional_strips_are_disjoint_and_within_real_stock(self):
        parcel=model.LandParcel("p",(-3.25,4.5,6.75,6),"w",EVIDENCE,STATUS)
        result=allocate([parcel],[crop("a",energy=9,water=7),crop("b",energy=1,water=0)],[pool(4)])
        self.assertEqual(result["status"],"OPTIMAL",result)
        rows=result["allocations"]
        for row in rows:
            x0,y0,x1,y1=row["bounds_m"]
            self.assertEqual((x1-x0)*(y1-y0),row["allocated_area_m2"])
            self.assertGreaterEqual(x0,parcel.bounds_m[0]);self.assertLessEqual(x1,parcel.bounds_m[2])
        for first,second in itertools.combinations(rows,2):
            a,b=first["bounds_m"],second["bounds_m"]
            self.assertLessEqual(min(a[2],b[2])-max(a[0],b[0]),0)
        self.assertLessEqual(math.fsum(r["allocated_area_m2"] for r in rows),parcel.area_m2)
        self.assertLessEqual(result["water_ledger"][0]["withdrawal_m3_year"],4)

    def test_permutation_invariant_and_repeatable_ties(self):
        ps=[land("p"),land("q",20)]
        os=[crop("a","p",1,1),crop("b","p",1,1),crop("c","q",1,1)]
        expected=allocate(ps,os,[pool(8)])
        for order in itertools.permutations(os):
            self.assertEqual(allocate(list(reversed(ps)),list(order),[pool(8)]),expected)

    def test_zero_irrigation_is_known_not_unknown(self):
        result=allocate(crops=[crop(water=0)],pools=[pool(0)])
        self.assertEqual(result["status"],"OPTIMAL")
        self.assertEqual(result["food_budget"]["total_available_energy_kcal_year"],100)

    def test_missing_coefficients_remain_unknown(self):
        for field in ("attainable_yield_kg_m2_year","edible_fraction","loss_fraction","edible_energy_kcal_kg","net_irrigation_m3_m2_year","irrigation_efficiency"):
            with self.subTest(field=field):
                result=allocate(crops=[replace(crop(),**{field:None})])
                self.assertEqual(result["status"],"UNKNOWN")
                self.assertIsNone(result["allocations"]);self.assertIsNone(result["food_budget"])
        self.assertEqual(allocate(pools=[pool(None)])["status"],"UNKNOWN")

    def test_unknown_sources_and_outside_regime_cannot_be_promoted(self):
        self.assertEqual(allocate(crops=[replace(crop(),source_status="UNKNOWN")])["status"],"UNKNOWN")
        self.assertEqual(allocate(parcels=[replace(land(),source_status="UNKNOWN")])["status"],"UNKNOWN")
        self.assertEqual(allocate(crops=[replace(crop(),applicability="OUTSIDE_REGIME")])["status"],"OUTSIDE_REGIME")

    def test_minimum_land_and_water_have_explicit_infeasibility(self):
        for crops in ([crop(minimum_area_m2=11)],
                      [crop(minimum_area_m2=6)],
                      [crop(minimum_area_m2=4),crop("b",minimum_area_m2=7,water=0)]):
            result=allocate(crops=crops)
            self.assertEqual(result["status"],"INFEASIBLE")
            self.assertIsNone(result["food_budget"])
        result=allocate(crops=[crop(minimum_area_m2=2,maximum_area_m2=3),crop("b",energy=6,water=0)])
        self.assertEqual(result["status"],"OPTIMAL")
        self.assertEqual(result["allocations"][0]["allocated_area_m2"],3)

    def test_no_water_connection_does_not_create_a_rainfed_yield(self):
        result=allocate([land(water=None)],[crop()],[])
        self.assertEqual(result["status"],"OPTIMAL")
        self.assertEqual(result["food_budget"]["total_available_energy_kcal_year"],0)
        result=allocate([land(water=None)],[crop(minimum_area_m2=1)],[])
        self.assertEqual(result["status"],"INFEASIBLE")

    def test_separate_pools_cannot_transfer_water_implicitly(self):
        ps=[land("p",water="w"),land("q",20,water="v")]
        result=allocate(ps,[crop("a","p",10,1),crop("b","q",1,1)],[pool(0,"w"),pool(10,"v")])
        self.assertEqual(result["food_budget"]["total_available_energy_kcal_year"],10)

    def test_duplicate_identities_and_broken_references_reject(self):
        for ps,os,ws in (([land(),land()],[],[pool()]),([land()],[crop(),crop()],[pool()]),
                         ([land()],[],[pool(),pool()]),([land()],[crop(parcel="missing")],[pool()]),
                         ([land()],[],[])):
            with self.assertRaises(ValueError):allocate(ps,os,ws)

    def test_invalid_numeric_quantities_reject(self):
        for value in (float("nan"),float("inf"),-float("inf"),-1,True):
            for field in ("attainable_yield_kg_m2_year","net_irrigation_m3_m2_year","minimum_area_m2"):
                with self.subTest(value=value,field=field),self.assertRaises(ValueError):replace(crop(),**{field:value})
            with self.assertRaises(ValueError):pool(value)
        for efficiency in (0,1.1):
            with self.assertRaises(ValueError):replace(crop(),irrigation_efficiency=efficiency)
        with self.assertRaises(ValueError):allocate(fixed_population=True)
        with self.assertRaises(ValueError):allocate(relative_optimality_tolerance=.1)

    def test_empty_explicit_land_has_zero_known_production(self):
        result=allocate([],[],[])
        self.assertEqual(result["status"],"OPTIMAL")
        self.assertEqual(result["food_budget"]["total_available_energy_kcal_year"],0)

    def test_actual_food_budget_is_called_and_pin_drift_rejects(self):
        food=model._food_module()
        with patch.object(food,"food_budget",wraps=food.food_budget) as budget,patch.object(model,"_food_module",return_value=food):
            result=allocate()
        self.assertEqual(budget.call_count,1)
        self.assertEqual(result["food_budget"]["schema"],"diadem.independent-food-energy-budget.r1")
        with patch.dict(model.FOOD_PINS,{"food.py":"0"*64}),self.assertRaisesRegex(ValueError,"changed"):
            allocate()

    def test_independent_weak_duality_certificate(self):
        # Deliberately non-optimal zero resource prices remain a genuine upper bound.
        upper=model._dual_upper_bound([10,6],[[1,1],[2,0]],[10,10],[0,0],[10,10],[0,0])
        self.assertEqual(upper,160)
        optimal=model._dual_upper_bound([10,6],[[1,1],[2,0]],[10,10],[0,0],[10,10],[6,2])
        self.assertEqual(optimal,80)

    def test_tiny_physical_units_do_not_disable_constraints_or_objective(self):
        result=allocate(crops=[crop(energy=1e-12,water=1e-12)],pools=[pool(5e-12)])
        self.assertEqual(result["status"],"OPTIMAL",result)
        self.assertAlmostEqual(result["allocations"][0]["allocated_area_m2"],5)
        self.assertTrue(math.isclose(result["food_budget"]["total_available_energy_kcal_year"],5e-12,rel_tol=1e-10,abs_tol=0))
        self.assertLessEqual(result["water_ledger"][0]["withdrawal_m3_year"],5e-12)

    def test_solver_failure_is_not_zero_production(self):
        from types import SimpleNamespace
        with patch.object(model,"linprog",return_value=SimpleNamespace(success=False,message="synthetic numerical failure")):
            result=allocate()
        self.assertEqual(result["status"],"NUMERICAL_FAILURE")
        self.assertIsNone(result["food_budget"])

    def test_actual_agroclimate_result_reaches_allocator_and_food_budget(self):
        root=RootZone(.3,.1,1,.5,EVIDENCE,STATUS)
        season=crop_season(root,[DayForcing(0,0,5,0,5) for _ in range(4)],initial_depletion_mm=0,
            potential_yield_kg_m2=2,yield_response_factor=1,minimum_valid_et_ratio=.5,evidence=EVIDENCE,source_status=STATUS)
        option=model.option_from_crop_season(season_result=season,option_id="a",parcel_id="p",crop_id="synthetic",
            edible_fraction=.5,loss_fraction=.1,edible_energy_kcal_kg=1000,irrigation_efficiency=.5,
            evidence=EVIDENCE,source_status=STATUS,one_crop_season_per_year=True)
        result=allocate(crops=[option],pools=[pool(.2)])
        self.assertEqual(result["status"],"OPTIMAL",result)
        self.assertAlmostEqual(result["allocations"][0]["allocated_area_m2"],5)
        self.assertAlmostEqual(result["food_budget"]["total_available_energy_kcal_year"],4500)
        self.assertAlmostEqual(result["water_ledger"][0]["withdrawal_m3_year"],.2)
        self.assertAlmostEqual(result["water_ledger"][0]["delivered_irrigation_m3_year"],.1)
        self.assertIn("crop-season result sha256",result["food_budget"]["rows"][0]["evidence"])
        json.dumps(result,allow_nan=False)
        for annual in (False,None,1):
            with self.assertRaises(ValueError):
                model.option_from_crop_season(season_result=season,option_id="a",parcel_id="p",crop_id="synthetic",
                    edible_fraction=.5,loss_fraction=.1,edible_energy_kcal_kg=1000,irrigation_efficiency=.5,
                    evidence=EVIDENCE,source_status=STATUS,one_crop_season_per_year=annual)


if __name__ == "__main__":
    unittest.main()
