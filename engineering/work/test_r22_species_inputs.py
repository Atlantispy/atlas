"""Actual register semantics and small exact consumer arithmetic."""
from fractions import Fraction as F
from copy import deepcopy
import unittest
from work.generator_upgrade_r22 import species_inputs as s


class SpeciesInputsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.r=s.load()

    def test_actual_register_overrides_and_unselected_vectors(self):
        self.assertEqual(self.r['counts']['numeric_records'],188)
        self.assertEqual(len(self.r['quantities']),200)
        effective=s.effective_taxon(self.r,'HS5')
        self.assertNotIn('Queen clutch frequency',effective['effective_remaining_biology'])
        self.assertIn('Queen clutch frequency',effective['original_taxon']['specific_remaining_biology'])
        h=s.quantity(self.r,'HS1:reef_releases:5')
        self.assertEqual(h['status'],'AVAILABLE_UNSELECTED')
        self.assertEqual(h['values_exact'],['4/5','1','6/5'])
        self.assertIsNone(h['selected_value'])
        with self.assertRaisesRegex(ValueError,'cannot be selected implicitly'): s._scalar(h)
        changed=deepcopy(self.r); changed['quantities'][0]['quantity']['value']=[500,3000]
        with self.assertRaisesRegex(ValueError,'register quantities or effective overrides changed'):
            s.quantity(changed,changed['quantities'][0]['id'])
        changed=deepcopy(self.r); changed['effective_overrides'][0]['effective']='unauthorised replacement'
        with self.assertRaisesRegex(ValueError,'register quantities or effective overrides changed'):
            s.effective_taxon(changed,'HS5')

    def test_source_clock_food_speed_and_delayed_cohort(self):
        calendar={'calendar_id':'EXPLICIT_TEST_APPLICATION','source_time_seconds':{'day':'100','hour':'10','week':'700'},
            'evidence':'SYNTHETIC TEST calendar join; source biology remains at its own status'}
        food=s.adult_food_demand(self.r,adult_entities=2,duration_seconds=200,calendar=calendar,application_evidence='SYNTHETIC TEST two ordinary adults')
        self.assertEqual(food['food_mass_kg_interval'],['32','56'])
        speed=s.segment_travel_time(self.r,'HS6:maintained_gardenway_speed:1',length_m=1000,
            route_regime='MAINTAINED_HUMID_GARDENWAY',calendar=calendar,application_evidence='SYNTHETIC TEST compatible one-km segment')
        self.assertEqual(speed['travel_time_seconds_interval'],['5','10'])
        self.assertIsNone(speed['movement_budget'])
        brood=s.ferrarachne_reference_cohort(self.r,laying_interval_seconds=1400,calendar=calendar,application_evidence='SYNTHETIC TEST sole Queen and protected-nursery application')
        self.assertEqual(brood['viable_eggs'],'9')
        self.assertEqual(brood['eventual_functional_adults'],'27/4')
        self.assertIsNone(brood['same_interval_successful_recruits'])
        with self.assertRaisesRegex(ValueError,'explicit source day'):
            s.quantity(self.r,'HS2:adult_food_demand:5',target_unit='kg source food/adult/s')

    def test_actual_red_wheat_account_cannot_be_crop_response(self):
        for label, expected in [('low',40),('neutral_reference',60),('high',80)]:
            out=s.red_wheat_grain_account(self.r,scenario_label=label,annually_harvested_area_m2=1000,
                application_evidence='SYNTHETIC TEST area; existing owner grain scenarios')
            self.assertEqual(F(out['usable_grain_kg']),expected)
            self.assertIsNone(out['potential_yield_kg_m2'])
            self.assertIsNone(out['edible_dry_yield_kg_m2'])
            self.assertFalse(out['et_stress_applied'])
        with self.assertRaisesRegex(ValueError,'meaning cannot change'):
            s.quantity(self.r,'bannerhaus_red_wheat_grass:usable_net_grain_yield:1',target_unit='kg edible dry matter/m2')


if __name__=='__main__': unittest.main()
