from dataclasses import replace
from fractions import Fraction
import unittest

from .integration import Settlement, food_transport_snapshot
from .land_food import LandParcel, CropOption, WaterPool
from .transport import Link
from .reference import food_network_reference, EVIDENCE


def simple(**changes):
    args = dict(parcels=[LandParcel("field",(0,0,10,1),"water",EVIDENCE,"SYNTHETIC TEST")],
        options=[CropOption("crop","field","grain",1,1,0,1000,.2,.5,EVIDENCE,"SYNTHETIC TEST")],
        water_pools=[WaterPool("water",2,EVIDENCE,"SYNTHETIC TEST")],
        settlements=[Settlement("farm",0,EVIDENCE),Settlement("town",2,EVIDENCE)],
        parcel_to_node={"field":"farm"}, links=[Link("road","farm","town",1000,1,8,0,True,"foot",EVIDENCE)],
        frame_id="test-metres",snapshot_id="test-year",annual_period_seconds=365*86400,
        annual_energy_kcal_per_person=3000,commodity_id="grain",commodity_energy_kcal_kg=1000,
        network_complete=True,evidence=EVIDENCE,source_status="SYNTHETIC TEST")
    args.update(changes)
    return food_transport_snapshot(**args)


class IntegrationTests(unittest.TestCase):
    def test_actual_crop_land_food_transport_chain(self):
        result = food_network_reference()
        self.assertEqual(result["crop_season"]["status"], "MODELLED")
        whole = result["food_network"]
        self.assertEqual(whole["status"], "REFERENCE_SOLVED")
        self.assertAlmostEqual(whole["land_food"]["food_budget"]["allocated_area_m2"], 5)
        self.assertAlmostEqual(whole["transport"]["totals"]["served_kg"]["value"], 5)
        self.assertAlmostEqual(whole["transport"]["totals"]["shortage_kg"]["value"], 1)
        self.assertEqual(whole["transport"]["routes"][0]["link_ids"], ["road"])

    def test_more_water_produces_more_food_not_more_people(self):
        low = food_network_reference(water_m3=2)["food_network"]
        high = food_network_reference(water_m3=4)["food_network"]
        self.assertGreater(high["land_food"]["food_budget"]["total_available_energy_kcal_year"],
                           low["land_food"]["food_budget"]["total_available_energy_kcal_year"])
        self.assertEqual(high["fixed_population"],low["fixed_population"])

    def test_population_changes_demand_not_production(self):
        low = food_network_reference(population=1)["food_network"]
        high = food_network_reference(population=20)["food_network"]
        self.assertEqual(high["land_food"]["food_budget"]["total_available_energy_kcal_year"],
                         low["land_food"]["food_budget"]["total_available_energy_kcal_year"])
        self.assertGreater(high["transport"]["totals"]["demand_kg"]["value"],low["transport"]["totals"]["demand_kg"]["value"])

    def test_bottleneck_limits_real_delivery(self):
        whole = food_network_reference(water_m3=4,road_capacity_kg=2)["food_network"]
        self.assertEqual(whole["transport"]["totals"]["served_kg"]["exact"], "2")
        self.assertEqual(whole["transport"]["totals"]["additional_network_limited_deficit_kg"]["exact"], "4")

    def test_barrier_is_not_proximity(self):
        whole=simple(links=[])
        self.assertEqual(whole["transport"]["totals"]["served_kg"]["exact"], "0")
        self.assertEqual(next(n for n in whole["transport"]["nodes"] if n["node_id"]=="town")["status"],"NO_PATH_FROM_KNOWN_SUPPLY")

    def test_source_mapping_is_explicit(self):
        for mapping in ({},{"field":"missing"},{"field":"farm","extra":"town"}):
            with self.assertRaises(ValueError): simple(parcel_to_node=mapping)

    def test_unknown_water_stops_supply_and_transport(self):
        whole=simple(water_pools=[WaterPool("water",None,EVIDENCE,"UNKNOWN")])
        self.assertEqual(whole["status"],"UNKNOWN")
        self.assertIsNone(whole["transport"])

    def test_incomplete_network_is_not_disconnection(self):
        whole=simple(network_complete=False)
        self.assertEqual(whole["status"],"MISSING_EVIDENCE")
        self.assertIsNone(whole["transport"]["flows"])

    def test_shared_capacity_not_reused_for_different_crops(self):
        with self.assertRaises(ValueError): simple(commodity_id="another-grain")
        with self.assertRaises(ValueError): simple(commodity_energy_kcal_kg=2000)

    def test_duplicate_settlements_cannot_duplicate_demand(self):
        with self.assertRaises(ValueError): simple(settlements=[Settlement("farm",1,EVIDENCE),Settlement("farm",2,EVIDENCE)])

    def test_fixed_counts_reject_bad_types(self):
        for count in (-1, True, 1.5, None):
            with self.assertRaises(ValueError): Settlement("node",count,EVIDENCE)

    def test_snapshot_and_period_guards(self):
        for changes in ({"snapshot_id":""},{"frame_id":""},{"annual_period_seconds":0},
                        {"network_complete":1},{"evidence":""}):
            with self.assertRaises(ValueError): simple(**changes)

    def test_unknown_snapshot_does_not_claim_production(self):
        whole=simple(source_status="UNKNOWN")
        self.assertEqual(whole["status"],"UNKNOWN")
        self.assertFalse(whole["production_installed"])
        self.assertIsNone(whole["land_food"])

    def test_repeat_exact(self):
        self.assertEqual(food_network_reference(),food_network_reference())

    def test_mass_accounting_matches_real_production(self):
        whole=simple()
        budget=whole["land_food"]["food_budget"]
        expected=sum((Fraction(r["available_food_kg_year"]) for r in budget["rows"]),Fraction())
        self.assertEqual(Fraction(whole["transport"]["totals"]["supply_kg"]["exact"]),expected)

    def test_input_canon_does_not_promote_new_outputs(self):
        result=simple(source_status="CANON")
        self.assertEqual(result["source_status"],"WORKING NON-CANON")
        self.assertEqual(result["input_source_status"],"CANON")

    def test_mixed_real_and_synthetic_inputs_are_not_pure_synthetic(self):
        result=simple(water_pools=[WaterPool("water",2,EVIDENCE,"WORKING NON-CANON")])
        self.assertEqual(result["source_status"],"WORKING NON-CANON")


if __name__ == "__main__":unittest.main()
