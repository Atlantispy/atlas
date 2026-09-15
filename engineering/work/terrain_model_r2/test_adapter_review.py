"""Independent, in-memory regression checks for the reviewed material adapters.

No terrain generation, output writes, physical calibration or authority claims.
"""
from copy import deepcopy
import math
import unittest

import constructive
import core
import fixtures
import workflow


def bare_recipe(rows=3, cols=3, spacing=10.):
    recipe = fixtures.base(rows, cols, spacing, "independent_adapter_review")
    n = rows * cols
    recipe["initial"].update(bedrock_m=[0.] * n, mobile_solid_m3=[0.] * n,
                             porosity=[0.] * n)
    recipe["operations"] = []
    return recipe


def wind_op(n, receivers, north=None, east=None, duration=100.):
    return {"kind": "aeolian_transport", "deposition_target": "mobile", "parameters": {
        "receivers": receivers, "friction_velocity_east_m_s": east or [0.] * n,
        "friction_velocity_north_m_s": north or [0.] * n, "threshold_m_s": [.39] * n,
        "grain_diameter_m": .00045, "grain_density_kg_m3": 2700.,
        "air_density_kg_m3": 1.2, "gravity_m_s2": 9.81, "porosity": 0.,
        "duration_s": duration, "external_supply_solid_m3": [0.] * n,
        "law": constructive.AEOLIAN_LAW, "source_label": "SYNTHETIC adapter test"}}


def tephra_op(rows=3, cols=3, origin=(100., 200.)):
    return {"kind": "tephra_fallout", "deposition_target": "mobile", "parameters": {
        "origin_x_m": origin[0], "origin_y_m": origin[1],
        "footprint": [True] * (rows * cols), "vent_x_m": origin[0] + 15.,
        "vent_y_m": origin[1] + 15., "wind_x_m_s": 0., "wind_y_m_s": -1.,
        "fall_time_s": 10., "diffusivity_m2_s": 2., "supplied_solid_m3": 1.,
        "deposit_porosity": 0., "source_label": "SYNTHETIC south-frame fallout"}}


class AdapterReviewTests(unittest.TestCase):
    def test_north_wind_deposits_in_actual_northern_neighbour(self):
        recipe = bare_recipe()
        recipe["initial"]["mobile_solid_m3"][4] = 10.
        op = wind_op(9, [-1, -1, -1, -1, 1, -1, -1, -1, -1],
                     north=[0., 0., 0., 0., .6, 0., 0., 0., 0.])
        recipe["operations"] = [op]
        original = deepcopy(recipe)
        result = workflow.execute(recipe)
        moved = result["operations"][0]["result"]["deposited_solid_m3_by_cell"]
        self.assertGreater(moved[1], 0.)
        self.assertEqual(moved[7], 0.)
        self.assertEqual(sum(v > 0 for v in moved), 1)
        self.assertAlmostEqual(math.fsum(result["state"]["mobile_solid_m3"]), 10., places=12)
        self.assertEqual(recipe, original)
        op["parameters"]["friction_velocity_north_m_s"][4] = -.6
        with self.assertRaisesRegex(ValueError, "direction"):
            workflow.execute(recipe)

    def test_tephra_nonzero_origin_matches_independent_south_frame_integrals(self):
        recipe = bare_recipe()
        recipe["grid"].update(origin_x_m=100., origin_y_m=200.)
        op = tephra_op()
        op["parameters"]["footprint"][6] = False
        recipe["operations"] = [op]
        result = workflow.execute(recipe)["operations"][0]["result"]
        scale = math.sqrt(80.)
        expected = []
        for r in range(3):
            for c in range(3):
                px = .5 * (math.erf((100. + (c + 1) * 10. - 115.) / scale)
                           - math.erf((100. + c * 10. - 115.) / scale))
                py = .5 * (math.erf((200. + (r + 1) * 10. - 205.) / scale)
                           - math.erf((200. + r * 10. - 205.) / scale))
                expected.append(px * py if r * 3 + c != 6 else 0.)
        for actual, wanted in zip(result["deposited_solid_m3_by_cell"], expected):
            self.assertAlmostEqual(actual, wanted, places=14)
        self.assertEqual(result["gaussian_mean_m"], [115., 205.])
        self.assertGreater(sum(expected[:3]), sum(expected[6:]))
        self.assertEqual(result["delivered_frame"], "synthetic_local_m_x_east_y_south")

    def test_tephra_cannot_override_shared_origin(self):
        recipe = bare_recipe()
        recipe["operations"] = [tephra_op()]
        with self.assertRaisesRegex(ValueError, "origin"):
            workflow.execute(recipe)

    def test_asymmetric_emplacement_restores_cell_identity(self):
        recipe = bare_recipe()
        weights = [float(i + 1) for i in range(9)]
        recipe["operations"] = [{"kind": "volcanic_emplacement", "deposition_target": "bedrock",
            "parameters": {"vent_cells": [1], "footprint": [True] * 9,
                "thickness_weights": weights, "supplied_solid_m3": 9.,
                "deposit_porosity": 0., "source_label": "SYNTHETIC mapped footprint"}}]
        result = workflow.execute(recipe)
        self.assertEqual(result["operations"][0]["result"]["vent_cells"], [1])
        for actual, weight in zip(result["state"]["bedrock_m"], weights):
            self.assertAlmostEqual(actual, 9. * weight / sum(weights) / 100., places=14)

    def test_glacial_gradient_comes_from_current_surface(self):
        recipe = deepcopy(fixtures.suite()[4])
        recipe["operations"] = recipe["operations"][:1]
        result = workflow.execute(recipe)
        erosion = result["operations"][0]["result"]["bedrock_erosion_m"]
        expected = [.004 * math.sqrt(1.02), .009 * math.sqrt(1.02), 0., 0., 0., 0.]
        for actual, wanted in zip(erosion, expected):
            self.assertAlmostEqual(actual, wanted, places=14)
        solid = result["operations"][0]["result"]["ledger"]["eroded_solid_m3"]
        geometric_loss = math.fsum(a - b for a, b in zip(
            recipe["initial"]["bedrock_m"], result["state"]["bedrock_m"])) * 100.
        self.assertAlmostEqual(solid, geometric_loss, places=11)
        recipe["operations"][0]["parameters"]["bed_gradient"] = [0.] * 6
        with self.assertRaisesRegex(ValueError, "geometry"):
            workflow.execute(recipe)

    def test_glacial_nonzero_rock_porosity_is_rejected(self):
        recipe = deepcopy(fixtures.suite()[4])
        recipe["operations"] = recipe["operations"][:1]
        recipe["operations"][0]["parameters"]["bedrock_porosity"] = .5
        with self.assertRaisesRegex(ValueError, "nonporous"):
            workflow.execute(recipe)

    def test_aeolian_phase_density_mismatch_is_rejected(self):
        recipe = bare_recipe(2, 2)
        op = wind_op(4, [1, -1, 3, -1])
        op["parameters"]["grain_density_kg_m3"] = 1000.
        recipe["operations"] = [op]
        with self.assertRaisesRegex(ValueError, "density"):
            workflow.execute(recipe)

    def test_porosity_contrast_old_overshoot_rejected_small_step_is_bounded(self):
        state = core.State(core.Grid(2, 2, 1., 1.), (0.,) * 4,
                           (1., 0., 1., 0.), (0., .99, 0., .99), 2700., 2700.)
        with self.assertRaisesRegex(ValueError, "stability"):
            core.hillslope_step(state, [1.] * 4, .1)
        after, evidence = core.hillslope_step(state, [1.] * 4, .0005)
        self.assertLessEqual(evidence["explicit_cfl"], .2)
        self.assertLessEqual(max(after.surface_m), max(state.surface_m))
        self.assertGreaterEqual(min(after.surface_m), min(state.surface_m))
        self.assertAlmostEqual(math.fsum(after.mobile_solid_m3), 2., places=14)

    def test_bedrock_emplacement_over_cover_is_rejected(self):
        recipe = bare_recipe(2, 2)
        recipe["initial"]["mobile_solid_m3"][0] = 1.
        recipe["operations"] = [{"kind": "volcanic_emplacement", "deposition_target": "bedrock",
            "parameters": {"vent_cells": [0], "footprint": [True] * 4,
                "thickness_weights": [1.] * 4, "supplied_solid_m3": 1.,
                "deposit_porosity": 0., "source_label": "SYNTHETIC burial rejection"}}]
        with self.assertRaisesRegex(ValueError, "burial"):
            workflow.execute(recipe)

    def test_repeated_organic_densities_are_bound_to_existing_layer(self):
        recipe = deepcopy(fixtures.suite()[6])
        recipe["operations"] = recipe["operations"][:1]
        first = workflow.execute(recipe)
        second = deepcopy(recipe["operations"][0])
        layer = first["auxiliary_layers"]["organic"]
        for name in ("organic_kg", "mineral_kg", "void_ratio"):
            second[name] = layer[name]
        second["duration_years"] = 0.
        recipe["operations"].append(second)
        unchanged = workflow.execute(recipe)
        self.assertEqual(first["state"]["surface_m"], unchanged["state"]["surface_m"])
        for density in ("organic_grain_density_kg_m3", "mineral_grain_density_kg_m3"):
            bad = deepcopy(recipe)
            bad["operations"][1]["parameters"][density] /= 2.
            with self.subTest(density=density), self.assertRaisesRegex(ValueError, "densities"):
                workflow.execute(bad)

    def test_intermediate_forcing_excursion_cannot_hide_in_zero_final_change(self):
        recipe = bare_recipe(2, 2)
        recipe["operations"] = [{"kind": "volcanic_emplacement", "deposition_target": "mobile",
            "parameters": {"vent_cells": [0], "footprint": [True, False, False, False],
                "thickness_weights": [1., 0., 0., 0.], "supplied_solid_m3": 1.,
                "deposit_porosity": 0., "source_label": "SYNTHETIC transient excursion"}},
            wind_op(4, [1, -1, 3, -1], east=[1., 1., 0., 0.], duration=1e6)]
        recipe["coupling"]["terrain_forcing_max_change_m"] = .02
        result = workflow.execute(recipe)
        self.assertEqual(result["change_m"], [0.] * 4)
        self.assertAlmostEqual(result["operations"][0]["maximum_height_change_m"], .01)
        recipe["coupling"]["terrain_forcing_max_change_m"] = .005
        with self.assertRaisesRegex(ValueError, "during sequence"):
            workflow.execute(recipe)

    def test_bed_change_invalidates_and_recomputation_restores_basin_result(self):
        recipe = deepcopy(fixtures.suite()[3])
        basin = deepcopy(recipe["operations"][0])
        # The existing basin grid uses1m cells and0m origin; use a matching
        # small single-source fallout input, with all Gaussian mass accounted.
        deposit = tephra_op(2, 3, (0., 0.))
        deposit["parameters"].update(vent_x_m=1.5, vent_y_m=.5,
            wind_y_m_s=0., fall_time_s=1., diffusivity_m2_s=.1,
            supplied_solid_m3=.01)
        recipe["operations"].append(deposit)
        stale = workflow.execute(recipe)
        self.assertIsNone(stale["water"])
        self.assertEqual(stale["water_status"], "STALE_BED_CHANGED_REQUIRES_RECOMPUTATION")
        self.assertIsNotNone(stale["operations"][0]["result"])
        recipe["operations"].append(basin)
        refreshed = workflow.execute(recipe)
        self.assertIsNotNone(refreshed["water"])
        self.assertEqual(refreshed["water_status"], "CURRENT_ON_EXACT_REPRESENTED_BED")

    def test_eight_current_fixtures_remain_numerical_not_physical_acceptance(self):
        for recipe in fixtures.suite():
            with self.subTest(scenario=recipe["scenario_id"]):
                original = deepcopy(recipe)
                result = workflow.execute(recipe)
                self.assertEqual(recipe, original)
                self.assertFalse(result["production_authorised"])
                self.assertFalse(result["diadem_canon_changed"])
                self.assertEqual(result["gates"]["physical_C"], "INCOMPLETE")
                self.assertTrue(all(math.isfinite(v) for v in result["state"]["surface_m"]))

    def test_prior_capture_failure_is_retained_as_rejection_not_repaired(self):
        with self.assertRaisesRegex(ValueError, "gradient|relief|timestep|step"):
            workflow.execute(fixtures.near_flat_capture_regression())


if __name__ == "__main__":
    unittest.main()
