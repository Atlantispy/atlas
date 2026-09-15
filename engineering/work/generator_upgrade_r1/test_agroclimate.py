import copy
from dataclasses import replace
from decimal import Decimal, localcontext
import math
import unittest

from .agroclimate import RootZone, DayForcing, water_balance, crop_season, stress_coefficient


def soil():
    return RootZone(.32, .12, .8, .4, "FAO56 Example 37 scenario, not Diadem calibration", "SYNTHETIC TEST")


def dry_day(et=6):
    return DayForcing(0, 0, 0, 0, et)


class AgroclimateTests(unittest.TestCase):
    def test_fao56_published_example37(self):
        result = water_balance(soil(), [dry_day() for _ in range(10)], initial_depletion_mm=55)
        expected = [61, 67, 72.8, 78.3, 83.4, 88.2, 92.6, 96.9, 100.8, 104.5]
        self.assertAlmostEqual(result["total_available_water_mm"], 160)
        for row, published in zip(result["rows"], expected):
            self.assertLessEqual(abs(row["final_depletion_mm"]-published), .051)

    def test_dry_recession_independent_decimal(self):
        with localcontext() as ctx:
            ctx.prec = 60
            expected = Decimal(67)
            for _ in range(18):
                expected += (Decimal(160)-expected)/Decimal(96)*Decimal(6)
        actual = water_balance(soil(), [dry_day() for _ in range(18)], initial_depletion_mm=67)
        self.assertAlmostEqual(actual["final_depletion_mm"], float(expected), places=11)

    def test_water_stock_and_all_fluxes(self):
        day = DayForcing(50, 5, 8, 2, 6)
        result = water_balance(soil(), [day], initial_depletion_mm=20)
        self.assertAlmostEqual(result["totals"]["deep_percolation_mm"], 29)
        self.assertEqual(result["final_depletion_mm"], 0)
        self.assertAlmostEqual(result["water_residual_mm"], 0)
        self.assertEqual(result["net_irrigation_m3_m2"], .008)

    def test_fully_dry_and_no_et(self):
        root = soil()
        result = water_balance(root, [dry_day(20)], initial_depletion_mm=root.available_water_mm)
        self.assertEqual(result["totals"]["actual_et_mm"], 0)
        self.assertEqual(stress_coefficient(root, root.available_water_mm), 0)
        self.assertEqual(water_balance(root, [dry_day(0)], initial_depletion_mm=10)["final_depletion_mm"], 10)

    def test_et_cannot_consume_more_than_stock(self):
        result = water_balance(soil(), [dry_day(10000)], initial_depletion_mm=0)
        self.assertAlmostEqual(result["totals"]["actual_et_mm"], 160)
        self.assertAlmostEqual(result["final_depletion_mm"], 160)

    def test_input_immutability(self):
        days = [dry_day(), DayForcing(20, 2, 3, 0, 4)]
        before = copy.deepcopy(days)
        water_balance(soil(), days, initial_depletion_mm=55)
        self.assertEqual(days, before)

    def test_dry_water_balance_over_many_states(self):
        for initial in (0, 10, 64, 65, 80, 120, 159, 160):
            for et in (0, 1, 6, 50, 500):
                result = water_balance(soil(), [dry_day(et)]*20, initial_depletion_mm=initial)
                self.assertGreaterEqual(result["final_depletion_mm"], initial)
                self.assertLessEqual(result["final_depletion_mm"], soil().available_water_mm)
                self.assertAlmostEqual(result["water_residual_mm"], 0, places=10)

    def test_periodic_repetition_is_not_assumed(self):
        first = water_balance(soil(), [dry_day()]*10, initial_depletion_mm=0)
        second = water_balance(soil(), [dry_day()]*10, initial_depletion_mm=first["final_depletion_mm"])
        self.assertGreater(second["final_depletion_mm"], first["final_depletion_mm"])

    def test_stress_threshold_is_continuous(self):
        root = soil(); raw = root.available_water_mm*root.depletion_fraction
        self.assertEqual(stress_coefficient(root, raw), 1)
        self.assertAlmostEqual(stress_coefficient(root, math.nextafter(raw, math.inf)), 1)

    def _crop(self, **changes):
        args = dict(initial_depletion_mm=112, potential_yield_kg_m2=1,
                    yield_response_factor=1.2, minimum_valid_et_ratio=.4,
                    evidence="synthetic explicitly supported seasonal coefficients", source_status="SYNTHETIC TEST")
        args.update(changes)
        return crop_season(soil(), [dry_day(6)], **args)

    def test_yield_responds_to_actual_et(self):
        result = self._crop()
        self.assertEqual(result["status"], "MODELLED")
        self.assertAlmostEqual(result["actual_to_potential_et_ratio"], .5)
        self.assertAlmostEqual(result["yield_kg_m2"], .4)

    def test_full_water_retains_potential_yield(self):
        self.assertEqual(self._crop(initial_depletion_mm=0)["yield_kg_m2"], 1)

    def test_drought_not_silently_clipped_to_zero(self):
        result = self._crop(initial_depletion_mm=160, minimum_valid_et_ratio=0)
        self.assertEqual(result["status"], "OUTSIDE_REGIME")
        self.assertIsNone(result["yield_kg_m2"])

    def test_supported_regime_is_explicit(self):
        result = self._crop(minimum_valid_et_ratio=.7)
        self.assertEqual(result["status"], "OUTSIDE_REGIME")

    def test_unknown_is_not_zero_yield(self):
        for field in ("potential_yield_kg_m2", "yield_response_factor", "minimum_valid_et_ratio"):
            result = self._crop(**{field: None})
            self.assertEqual(result["status"], "UNKNOWN")
            self.assertIsNone(result["yield_kg_m2"])
        self.assertEqual(self._crop(source_status="UNKNOWN")["status"], "UNKNOWN")

    def test_zero_potential_et_rejects_yield_relation(self):
        result = crop_season(soil(), [dry_day(0)], initial_depletion_mm=0,
                             potential_yield_kg_m2=1, yield_response_factor=1,
                             minimum_valid_et_ratio=0, evidence="synthetic", source_status="SYNTHETIC TEST")
        self.assertEqual(result["status"], "OUTSIDE_REGIME")

    def test_soil_physical_guards(self):
        for changes in ({"field_capacity_m3_m3": .1}, {"wilting_point_m3_m3": -.1},
                        {"field_capacity_m3_m3": 1.1}, {"rooting_depth_m": 0},
                        {"depletion_fraction": 1}, {"depletion_fraction": True},
                        {"source_status": "UNKNOWN"}, {"evidence": ""}):
            with self.assertRaises(ValueError): replace(soil(), **changes)

    def test_forcing_guards(self):
        for key in DayForcing.__dataclass_fields__:
            for value in (-1, math.nan, math.inf, True, "1"):
                with self.assertRaises(ValueError): replace(dry_day(), **{key: value})
        with self.assertRaises(ValueError): DayForcing(1, 2, 0, 0, 1)

    def test_sequence_and_initial_guards(self):
        for days in ([], [dry_day()]*367, [None], "daily"):
            with self.assertRaises(ValueError): water_balance(soil(), days, initial_depletion_mm=0)
        for initial in (-1, 161, True, math.nan):
            with self.assertRaises(ValueError): water_balance(soil(), [dry_day()], initial_depletion_mm=initial)

    def test_invalid_coefficient_cannot_hide_behind_unknown(self):
        with self.assertRaises(ValueError): self._crop(potential_yield_kg_m2=None, yield_response_factor=-1)
        with self.assertRaises(ValueError): self._crop(minimum_valid_et_ratio=1.1)

    def test_evidence_and_unsupported_status(self):
        with self.assertRaises(ValueError): self._crop(evidence="")
        with self.assertRaises(ValueError): self._crop(source_status="APPROVED")

    def test_parameter_authority_does_not_promote_new_yield(self):
        result=self._crop(source_status="CANON")
        self.assertEqual(result["source_status"],"WORKING NON-CANON")
        self.assertEqual(result["parameter_source_status"],"CANON")


if __name__ == "__main__":
    unittest.main()
