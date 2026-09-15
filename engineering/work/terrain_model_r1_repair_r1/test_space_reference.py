"""Small independent algebra, geometry, provenance and rejection fixtures."""
from copy import deepcopy
from dataclasses import asdict, replace
import hashlib
import json
import math
from pathlib import Path
import unittest
from unittest.mock import patch

import space_reference as s


class SpaceReferenceTests(unittest.TestCase):
    def setUp(self):
        self.recipe = s.load_benchmark()
        self.p = s.Parameters(**self.recipe["parameters"])
        spec = self.recipe["single_cell"]
        self.cell = s.CellState(**spec, bedrock_m=spec["surface_m"] - spec["cover_m"])

    def assertNear(self, actual, expected, kind="flux_m3_per_year"):
        limits = self.recipe["tolerances"][kind]
        self.assertTrue(math.isfinite(actual))
        self.assertLessEqual(abs(actual - expected), limits["atol"] + limits["rtol"] * max(abs(actual), abs(expected)))

    def test_contract_bytes_defaults_and_runtime_tolerances(self):
        self.assertEqual(hashlib.sha256(s.BENCHMARK_PATH.read_bytes()).hexdigest(), s.BENCHMARK_SHA256)
        self.assertEqual(asdict(s.PUBLISHED_PARAMETERS), self.recipe["parameters"])
        for name, pair in s.TOLERANCES.items():
            self.assertEqual(pair, (self.recipe["tolerances"][name]["atol"], self.recipe["tolerances"][name]["rtol"]))
        with self.assertRaises(TypeError):
            s.TOLERANCES["state_m"] = (1, 1)

    def test_independent_single_cell_rational_oracle(self):
        # exp(-ln(7/2))=2/7. The independent oracle is not local_rates.
        self.assertNear(self.cell.cover_m, math.log(7 / 2), "state_m")
        result = s.local_rates(self.cell)
        for field, expected in (("slope", 7 / 10000),
                                ("entrainment_m_per_year", 5 / 10000),
                                ("deposition_m_per_year", 5 / 10000),
                                ("erosion_m_per_year", 1 / 10000)):
            self.assertNear(result[field], expected, "slope" if field == "slope" else "rate_m_per_year")
        self.assertNear(result["outgoing_sediment_m3_per_year"], 1)
        self.assertEqual(result["water_m3_per_year"], 10000)
        self.assertNear(result["cover_change_m_per_year"], 0, "rate_m_per_year")
        self.assertNear(result["bedrock_change_m_per_year"], 0, "rate_m_per_year")

    def test_equilibrium_predictions_independent_values(self):
        oracle = s.equilibrium_predictions(10000)
        self.assertNear(oracle["cover_m"], math.log(3.5), "state_m")
        self.assertNear(oracle["slope"], .0007, "slope")
        self.assertNear(oracle["sediment_m3_per_year"], 1)
        downstream = s.equilibrium_predictions(40000)
        self.assertNear(downstream["slope"], .00035, "slope")
        self.assertNear(downstream["sediment_m3_per_year"], 4)

    def test_confluence_area_and_flux_once(self):
        result = s.evaluate_network(self.recipe["network"])
        self.assertEqual([n["contributing_area_m2"] for n in result["nodes"]], [10000, 10000, 30000, 40000])
        for field, expected in (("incoming_sediment_m3_per_year", [0, 0, 2, 3]),
                                ("outgoing_sediment_m3_per_year", [1, 1, 3, 4])):
            for node, value in zip(result["nodes"], expected, strict=True):
                self.assertNear(node[field], value)
        self.assertNear(result["external_sediment_m3_per_year"], 4)
        self.assertNear(result["total_bedrock_supply_m3_per_year"], 4)
        self.assertNear(result["total_mobile_change_m3_per_year"], 0)
        self.assertNear(result["solid_volume_residual_m3_per_year"], 0)
        self.assertEqual(result["external_water_m3_per_year"], 40000)

    def test_network_input_unchanged_and_non_topological_order(self):
        network = deepcopy(self.recipe["network"])
        network["nodes"].reverse()
        before = deepcopy(network)
        result = s.evaluate_network(network)
        self.assertEqual(network, before)
        self.assertEqual([n["id"] for n in result["nodes"]], [n["id"] for n in before["nodes"]])
        self.assertNear(result["external_sediment_m3_per_year"], 4)

    def test_surface_geometry_and_arbitrary_datum(self):
        self.assertLess(self.cell.bedrock_m, 0)  # Relative bedrock is not clipped.
        twice = replace(self.cell, receiver_x_m=200)
        self.assertNear(twice.slope, self.cell.slope / 2, "slope")
        shifted = replace(self.cell, bedrock_m=self.cell.bedrock_m + 100,
                          surface_m=self.cell.surface_m + 100, receiver_surface_m=100)
        self.assertNear(s.local_rates(shifted)["erosion_m_per_year"], .0001, "rate_m_per_year")

    def test_no_cover_disables_sediment_entrainment_not_rock_erosion(self):
        bare = replace(self.cell, cover_m=0, bedrock_m=self.cell.surface_m)
        result = s.local_rates(bare)
        self.assertEqual(result["entrainment_m_per_year"], 0)
        self.assertNear(result["erosion_m_per_year"], .00035, "rate_m_per_year")
        self.assertNear(result["solid_volume_residual_m3_per_year"], 0)

    def test_zero_slope_allows_deposition_from_supplied_flux(self):
        flat = replace(self.cell, receiver_surface_m=self.cell.surface_m,
                       incoming_sediment_m3_per_year=1)
        result = s.local_rates(flat)
        self.assertEqual(result["entrainment_m_per_year"], 0)
        self.assertEqual(result["erosion_m_per_year"], 0)
        self.assertNear(result["outgoing_sediment_m3_per_year"], 1 / 6)
        self.assertNear(result["mobile_change_m3_per_year"], 5 / 6)
        self.assertNear(result["solid_volume_residual_m3_per_year"], 0)

    def test_positive_parameters_reject_invalid_numbers(self):
        for field in ("sediment_erodibility", "bedrock_erodibility", "uplift_m_per_year",
                      "cover_scale_m", "settling_m_per_year", "runoff_m_per_year"):
            for value in (0, -1, float("nan"), float("inf"), -float("inf"), True, "1", 10**1000):
                with self.subTest(field=field, value=str(value)[:30]), self.assertRaises(ValueError):
                    replace(self.p, **{field: value})

    def test_unsupported_laws_units_and_thresholds(self):
        for field, value in (("area_exponent", 1), ("slope_exponent", 2), ("porosity", .1),
                             ("fines_fraction", .1), ("sediment_threshold_m_per_year", .001),
                             ("bedrock_threshold_m_per_year", .001), ("forcing_basis", "water_discharge"),
                             ("erodibility_units", "1/m"), ("porosity", False)):
            with self.subTest(field=field), self.assertRaises(ValueError):
                replace(self.p, **{field: value})
        with self.assertRaises(TypeError):
            s.Parameters(**{**self.recipe["parameters"], "time_step": 1})

    def test_cell_numeric_rejections(self):
        for field in ("x_m", "y_m", "width_m", "contributing_area_m2", "cover_m", "surface_m",
                      "incoming_sediment_m3_per_year", "bedrock_m", "receiver_surface_m"):
            for value in (float("nan"), float("inf"), True, 10**1000):
                with self.subTest(field=field), self.assertRaises(ValueError):
                    replace(self.cell, **{field: value})
        for field, value in (("width_m", 0), ("width_m", -1), ("width_m", 1e-300),
                             ("contributing_area_m2", 0), ("contributing_area_m2", 9999),
                             ("cover_m", -1), ("incoming_sediment_m3_per_year", -1)):
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                replace(self.cell, **{field: value})

    def test_incompatible_geometry_units_and_surface(self):
        for changes in ({"receiver_x_m": 0}, {"receiver_surface_m": .08},
                        {"surface_m": .08}, {"length_units": "km"}, {"area_units": "km2"},
                        {"sediment_flux_units": "kg/year"}, {"receiver_vertical_datum": "other"},
                        {"vertical_datum": ""}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(self.cell, **changes)

    def test_derived_nonfinite_and_underflow_fail_closed(self):
        with self.assertRaises(ValueError):
            replace(self.cell, width_m=1e308)
        with self.assertRaises(ValueError):
            replace(self.cell, bedrock_m=1e308, cover_m=1e308, surface_m=1e308)
        with self.assertRaises(ValueError):
            s.equilibrium_predictions(10000, replace(self.p, runoff_m_per_year=1e-300,
                                                   sediment_erodibility=1e-300))
        with self.assertRaises(ValueError):
            s.local_rates(self.cell, replace(self.p, settling_m_per_year=1e308))
        for area in (0, -1, float("nan"), float("inf"), True, 10**1000):
            with self.subTest(area=str(area)[:30]), self.assertRaises(ValueError):
                s.equilibrium_predictions(area)

    def test_network_bad_inventory_and_geometry(self):
        for mutate in (
            lambda n: n.update(frame="geographic_degrees"),
            lambda n: n.update(extra=0),
            lambda n: n["outlet"].update(status="WATER_STAGE"),
            lambda n: n["outlet"].update(surface_m="0"),
            lambda n: n["nodes"][0].update(surface_m="0"),
            lambda n: n["nodes"][0].update(receiver="absent"),
            lambda n: n["nodes"][0].update(id="head_e"),
            lambda n: n["nodes"][0].update(receiver="head_w"),
            lambda n: n["nodes"].clear(),
            lambda n: n.update(nodes=n["nodes"] * 5),
            lambda n: n["nodes"][0].update(x_m=100),
            lambda n: n["nodes"][0].update(x_m=-50),
        ):
            network = deepcopy(self.recipe["network"])
            mutate(network)
            with self.subTest(network=network), self.assertRaises(ValueError):
                s.evaluate_network(network)

    def test_contract_mutation_rejected_without_editing_source(self):
        with patch.object(Path, "read_bytes", return_value=b"{}"):
            with self.assertRaisesRegex(ValueError, "contract changed"):
                s.load_benchmark()

    def test_import_and_postrun_implementation_binding(self):
        with patch.object(s, "IMPORTED_SOURCE_SHA256", "0" * 64):
            with self.assertRaisesRegex(ValueError, "since import"):
                s.run_benchmark()
        original_read = Path.read_bytes
        source_reads = 0
        def altered_second_read(path):
            nonlocal source_reads
            data = original_read(path)
            if path == Path(s.__file__):
                source_reads += 1
                if source_reads > 1:
                    return data + b"# mutation fixture"
            return data
        with patch.object(Path, "read_bytes", altered_second_read):
            with self.assertRaisesRegex(ValueError, "during evaluation"):
                s.run_benchmark()

    def test_report_pass_is_numerical_only_and_json_finite(self):
        result = s.run_benchmark()
        self.assertEqual(result["status"], "PASS_ANALYTICAL_REFERENCE")
        self.assertTrue(all(result["checks"].values()))
        for key in ("terrain_generated", "time_integration_performed", "physical_acceptance",
                    "production_authorized", "diadem_canon_changed"):
            self.assertIs(result[key], False)
        self.assertEqual(result["implementation_sha256"], s.IMPORTED_SOURCE_SHA256)
        self.assertEqual(result["contract_sha256"], s.BENCHMARK_SHA256)
        json.dumps(result, allow_nan=False)
        self.assertEqual(result, s.run_benchmark())


if __name__ == "__main__":
    unittest.main()
