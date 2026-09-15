"""Independent small numerical invariants; no retained/production terrain."""
import copy
import math
import unittest

import constructive as c


def volcano(**changes):
    args = dict(rows=2, cols=3, cell_size_m=2., vent_cells=[0],
                footprint=[True] * 6, thickness_weights=[1., 2., 3., 1., 2., 3.],
                supplied_solid_m3=24., deposit_porosity=.5,
                source_label="SYNTHETIC mapped shape")
    args.update(changes)
    return c.volcanic_emplacement([10.] * 6, **args)


def fallout(**changes):
    args = dict(rows=2, cols=2, cell_size_m=1., origin_x_m=-1., origin_y_m=-1.,
                footprint=[True] * 4, vent_x_m=0., vent_y_m=0.,
                wind_x_m_s=0., wind_y_m_s=0., fall_time_s=1.,
                diffusivity_m2_s=.5, supplied_solid_m3=100., deposit_porosity=.25,
                source_label="SYNTHETIC Gaussian")
    base = changes.pop("base", [0.] * (changes.get("rows", 2) * changes.get("cols", 2)))
    args.update(changes)
    return c.tephra_fallout(base, **args)


def glacier(**changes):
    args = dict(rows=1, cols=3, cell_size_m=2., ice_extent=[True, True, False],
                warm_bed=[True, True, False], sliding_speed_m_per_yr=[2., 3., 0.],
                bed_gradient=[0., 0., 0.], erosion_constant_yr_per_m=1e-4,
                duration_yr=10., erodible_thickness_m=[1.] * 3,
                receivers=[1, 2, -1], deposit_fraction=[0., .5, .5],
                bedrock_porosity=0., deposit_porosity=.5, law=c.GLACIAL_LAW,
                source_label="SYNTHETIC glacier forcing")
    args.update(changes)
    return c.glacial_erosion([3., 2., 1.], **args)


def wind(**changes):
    args = dict(rows=1, cols=3, cell_size_m=1., receivers=[1, 2, -1],
                friction_velocity_east_m_s=[1.] * 3, friction_velocity_north_m_s=[0.] * 3,
                threshold_m_s=[.2] * 3, grain_diameter_m=.00045,
                grain_density_kg_m3=2650., air_density_kg_m3=1.2,
                gravity_m_s2=9.81, porosity=.4, duration_s=10.,
                external_supply_solid_m3=[0.] * 3, law=c.AEOLIAN_LAW,
                source_label="SYNTHETIC wind")
    mobile = changes.pop("mobile", [.01, .01, .01])
    args.update(changes)
    return c.aeolian_transport(mobile, **args)


def frost(**changes):
    args = dict(rows=1, cols=3, cell_size_m=1., receivers=[1, 2, -1],
                cumulative_normal_heave_m=[.1] * 3, active_layer_m=[.2] * 3,
                outlet_gradient=[0., 0., 1.], porosity=.4,
                source_label="SYNTHETIC normal heave")
    surface = changes.pop("surface", [3., 2., 1.])
    mobile = changes.pop("mobile", [.3] * 3)
    args.update(changes)
    return c.frost_creep(surface, mobile, **args)


class ConstructiveTests(unittest.TestCase):
    def assertLedger(self, result):
        q = result["ledger"]
        self.assertAlmostEqual(q["external_supply_solid_m3"] + q["eroded_solid_m3"],
                               q["deposited_solid_m3"] + q["exported_solid_m3"], delta=1e-12)
        self.assertLessEqual(abs(q["balance_residual_solid_m3"]), q["roundoff_allowance_solid_m3"])

    def test_volume_weight_oracle(self):
        got = volcano()
        self.assertEqual(got["deposition_m"], [1., 2., 3., 1., 2., 3.])
        self.assertEqual(got["surface_elevation_m"], [11., 12., 13., 11., 12., 13.])
        self.assertEqual(got["basal_area_m2"], 24.)
        self.assertEqual(got["height_above_local_base_m"], 3.)
        self.assertLedger(got)

    def test_volume_weight_scale_invariance(self):
        a = volcano()["deposition_m"]
        b = volcano(thickness_weights=[10., 20., 30., 10., 20., 30.])["deposition_m"]
        self.assertEqual(a, b)

    def test_volume_zero_supply(self):
        got = volcano(supplied_solid_m3=0.)
        self.assertEqual(got["deposition_m"], [0.] * 6)
        self.assertEqual(got["surface_elevation_m"], [10.] * 6)
        self.assertLedger(got)

    def test_volume_invalid_vent_footprint(self):
        cases = [dict(vent_cells=[]), dict(vent_cells=[0, 0]), dict(vent_cells=[True]),
                 dict(vent_cells=[6]), dict(footprint=[False] + [True] * 5),
                 dict(footprint=[True, False, True, False, False, False],
                      thickness_weights=[1., 0., 1., 0., 0., 0.])]
        for case in cases:
            with self.subTest(case=case), self.assertRaises(c.ConstructiveError):
                volcano(**case)

    def test_volume_disjoint_explicit_vents_allowed(self):
        got = volcano(vent_cells=[0, 2], footprint=[True, False, True, False, False, False],
                      thickness_weights=[1., 0., 2., 0., 0., 0.])
        self.assertEqual(got["deposition_m"], [4., 0., 8., 0., 0., 0.])
        self.assertLedger(got)

    def test_volume_nonzero_needs_shape(self):
        with self.assertRaises(c.ConstructiveError):
            volcano(thickness_weights=[0.] * 6)

    def test_gaussian_independent_rectangle_oracle(self):
        got = fallout()
        # Standard normal P(-1<X<1)^2, four symmetric quadrants.
        probability = math.erf(1 / math.sqrt(2)) ** 2
        self.assertAlmostEqual(got["retained_probability"], probability, delta=2e-15)
        for v in got["deposited_solid_m3_by_cell"]:
            self.assertAlmostEqual(v, 25 * probability, delta=1e-13)
        self.assertLedger(got)

    def test_gaussian_cell_refinement_additivity(self):
        coarse = fallout()
        fine = fallout(rows=4, cols=4, cell_size_m=.5, footprint=[True] * 16)
        self.assertAlmostEqual(coarse["ledger"]["deposited_solid_m3"],
                               fine["ledger"]["deposited_solid_m3"], delta=1e-13)
        self.assertAlmostEqual(coarse["ledger"]["exported_solid_m3"],
                               fine["ledger"]["exported_solid_m3"], delta=1e-13)

    def test_gaussian_wind_translation(self):
        a = fallout()
        b = fallout(vent_x_m=-2., wind_x_m_s=2.)
        self.assertEqual(a["deposition_m"], b["deposition_m"])
        self.assertEqual(b["gaussian_mean_m"], [0., 0.])

    def test_gaussian_mask_export_not_renormalised(self):
        all_cells = fallout()
        half = fallout(footprint=[True, False, True, False])
        self.assertEqual(half["deposition_m"][1::2], [0., 0.])
        self.assertEqual(half["deposition_m"][0], all_cells["deposition_m"][0])
        self.assertAlmostEqual(half["ledger"]["deposited_solid_m3"],
                               all_cells["ledger"]["deposited_solid_m3"] / 2, delta=1e-13)
        self.assertLedger(half)

    def test_gaussian_zero_and_far_tail(self):
        self.assertEqual(fallout(supplied_solid_m3=0.)["deposition_m"], [0.] * 4)
        far = fallout(vent_x_m=1e6)
        self.assertEqual(far["deposition_m"], [0.] * 4)
        self.assertEqual(far["ledger"]["exported_solid_m3"], 100.)

    def test_glacier_quadratic_source_and_routing_oracle(self):
        got = glacier()
        self.assertAlmostEqual(got["bedrock_erosion_m"][0], .004)
        self.assertAlmostEqual(got["bedrock_erosion_m"][1], .009)
        self.assertEqual(got["bedrock_erosion_m"][2], 0.)
        self.assertAlmostEqual(got["ledger"]["eroded_solid_m3"], .052)
        self.assertAlmostEqual(got["ledger"]["deposited_solid_m3"], .039)
        self.assertAlmostEqual(got["ledger"]["exported_solid_m3"], .013)
        self.assertLedger(got)

    def test_glacier_normal_to_vertical_conversion(self):
        got = glacier(bed_gradient=[math.sqrt(3), 0., 0.])
        self.assertAlmostEqual(got["bedrock_erosion_m"][0], .008)

    def test_glacier_cold_and_zero_forcing(self):
        cold = glacier(warm_bed=[False] * 3)
        zero = glacier(duration_yr=0.)
        for got in (cold, zero):
            self.assertEqual(got["bedrock_erosion_m"], [0.] * 3)
            self.assertEqual(got["deposition_m"], [0.] * 3)
            self.assertLedger(got)

    def test_glacier_source_cap_and_porosity(self):
        got = glacier(erodible_thickness_m=[.001, 0., 0.], bedrock_porosity=.2)
        self.assertEqual(got["bedrock_erosion_m"], [.001, 0., 0.])
        self.assertEqual(got["capped_cells"], [0])
        self.assertAlmostEqual(got["ledger"]["eroded_solid_m3"], .0032)
        self.assertLedger(got)

    def test_glacier_domain_and_law_rejections(self):
        for changes in (dict(warm_bed=[True] * 3), dict(sliding_speed_m_per_yr=[2., 3., 4.]),
                        dict(law="generic_ice"), dict(deposit_fraction=[0., 1.1, 0.])):
            with self.subTest(changes=changes), self.assertRaises(c.ConstructiveError):
                glacier(**changes)

    def test_aeolian_equation_and_grain_gravity_scaling(self):
        got = wind()
        expected = 25 * (1.2 / 2650) * math.sqrt(.00045 / 9.81) * (1 - .2 ** 2)
        self.assertAlmostEqual(got["saturated_flux_solid_m2_s"][0], expected, delta=1e-18)
        diameter = wind(grain_diameter_m=.0018)["saturated_flux_solid_m2_s"][0]
        gravity = wind(gravity_m_s2=9.81 * 4)["saturated_flux_solid_m2_s"][0]
        self.assertAlmostEqual(diameter, 2 * expected, delta=1e-18)
        self.assertAlmostEqual(gravity, expected / 2, delta=1e-18)
        self.assertLedger(got)

    def test_aeolian_zero_supply_and_zero_wind(self):
        empty = wind(mobile=[0.] * 3)
        self.assertEqual(empty["mobile_erosion_m"], [0.] * 3)
        for value in (0., .2):
            still = wind(friction_velocity_east_m_s=[value] * 3)
            self.assertEqual(still["mobile_thickness_m"], [.01] * 3)
            self.assertEqual(still["ledger"]["exported_solid_m3"], 0.)
        self.assertLedger(empty)

    def test_aeolian_inventory_exhaustion(self):
        got = wind(duration_s=1e12)
        self.assertEqual(got["mobile_thickness_m"], [0.] * 3)
        self.assertAlmostEqual(got["ledger"]["exported_solid_m3"], .018)
        self.assertLedger(got)

    def test_aeolian_capacity_drop_deposits(self):
        got = wind(friction_velocity_east_m_s=[1., 0., 1.])
        self.assertGreater(got["deposition_m"][1], 0.)
        self.assertEqual(got["mobile_erosion_m"][1], 0.)
        self.assertLedger(got)

    def test_aeolian_external_supply_zero_wind(self):
        got = wind(friction_velocity_east_m_s=[0.] * 3,
                   external_supply_solid_m3=[.3, 0., 0.])
        self.assertEqual(got["mobile_erosion_m"], [0.] * 3)
        self.assertAlmostEqual(got["deposition_m"][0], .5)
        self.assertLedger(got)

    def test_aeolian_whole_inventory(self):
        got = wind(external_supply_solid_m3=[.003, 0., 0.])
        after = math.fsum(h * .6 for h in got["mobile_thickness_m"])
        self.assertAlmostEqual(.018 + .003, after + got["ledger"]["exported_solid_m3"], delta=1e-14)

    def test_aeolian_wind_and_density_rejections(self):
        for changes in (dict(friction_velocity_east_m_s=[-1.] * 3),
                        dict(air_density_kg_m3=3000.), dict(law="arbitrary")):
            with self.subTest(changes=changes), self.assertRaises(c.ConstructiveError):
                wind(**changes)

    def test_frost_creep_kinematic_oracle(self):
        got = frost()
        #45degree plane: normal heave .1, along-surface .1, horizontal .1/sqrt2.
        for moved in got["potential_surface_displacement_m"]:
            self.assertAlmostEqual(moved, .1)
        self.assertAlmostEqual(got["one_hop_fraction"][0], .1 / math.sqrt(2))
        self.assertAlmostEqual(got["eroded_solid_m3_by_cell"][0], .2 * .6 * .1 / math.sqrt(2))
        self.assertLedger(got)

    def test_frost_one_hop_no_same_step_reentrainment(self):
        got = frost(mobile=[.3, 0., 0.], active_layer_m=[.2, 0., 0.])
        self.assertGreater(got["deposition_m"][1], 0.)
        self.assertEqual(got["deposition_m"][2], 0.)
        self.assertEqual(got["ledger"]["exported_solid_m3"], 0.)

    def test_frost_flat_zero_and_inventory(self):
        flat = frost(surface=[1.] * 3, outlet_gradient=[0.] * 3)
        zero = frost(cumulative_normal_heave_m=[0.] * 3)
        for got in (flat, zero):
            self.assertEqual(got["mobile_thickness_m"], [.3] * 3)
        moving = frost()
        self.assertAlmostEqual(.9 * .6, math.fsum(moving["mobile_thickness_m"]) * .6
                               + moving["ledger"]["exported_solid_m3"], delta=1e-14)

    def test_frost_uphill_and_subdivision_rejections(self):
        for changes in (dict(surface=[1., 2., 3.]), dict(active_layer_m=[1.] * 3),
                        dict(cumulative_normal_heave_m=[10.] * 3)):
            with self.subTest(changes=changes), self.assertRaises(c.ConstructiveError):
                frost(**changes)

    def test_receiver_cycle_nonlocal_and_type_rejection(self):
        for graph in ([1, 0, -1], [2, 2, -1], [True, 2, -1], [1, 2, 3]):
            with self.subTest(graph=graph), self.assertRaises(c.ConstructiveError):
                glacier(receivers=graph)

    def test_interior_export_rejected(self):
        with self.assertRaises(c.ConstructiveError):
            c._receivers([-1] * 9, 3, 3)

    def test_invalid_numbers_masks_and_resource_limits(self):
        for number in (True, "1", float("nan"), float("inf"), 10 ** 1000, -1.):
            with self.subTest(number=str(number)[:30]), self.assertRaises(c.ConstructiveError):
                volcano(supplied_solid_m3=number)
        for changes in (dict(rows=0), dict(rows=True), dict(rows=16385),
                        dict(footprint=[1] * 6), dict(deposit_porosity=1.),
                        dict(source_label=""), dict(cell_size_m=1e-300)):
            with self.subTest(changes=changes), self.assertRaises(c.ConstructiveError):
                volcano(**changes)

    def test_elevation_resolution_rejected(self):
        with self.assertRaises(c.ConstructiveError):
            fallout(base=[1e300] * 4)
        with self.assertRaises(c.ConstructiveError):
            c._lowered_surface([1e300], [.004])

    def test_derived_ratio_underflow_rejected(self):
        for changes in (dict(air_density_kg_m3=1e-300, grain_density_kg_m3=1e300),
                        dict(grain_diameter_m=1e-300, gravity_m_s2=1e300)):
            with self.subTest(changes=changes), self.assertRaises(c.ConstructiveError):
                wind(**changes)

    def test_maximum_supported_grid_runs(self):
        n = c.MAX_CELLS
        result = c.aeolian_transport([0.] * n, rows=1, cols=n, cell_size_m=1.,
            receivers=list(range(1, n)) + [-1],
            friction_velocity_east_m_s=[0.] * n, friction_velocity_north_m_s=[0.] * n,
            threshold_m_s=[.2] * n, grain_diameter_m=.00045,
            grain_density_kg_m3=2650., air_density_kg_m3=1.2, gravity_m_s2=9.81,
            porosity=.4, duration_s=1., external_supply_solid_m3=[0.] * n,
            law=c.AEOLIAN_LAW, source_label="SYNTHETIC resource limit")
        self.assertEqual(len(result["deposition_m"]), n)
        self.assertEqual(result["ledger"]["eroded_solid_m3"], 0.)

    def test_grid_edge_resolution_rejected(self):
        with self.assertRaises(c.ConstructiveError):
            fallout(origin_x_m=1e300)

    def test_input_preservation_and_determinism(self):
        inputs = dict(vent_cells=[0], footprint=[True] * 6,
                      thickness_weights=[1., 2., 3., 1., 2., 3.])
        before = copy.deepcopy(inputs)
        self.assertEqual(volcano(**inputs), volcano(**inputs))
        self.assertEqual(inputs, before)
        for run in (fallout, glacier, wind, frost, c.mixing_fixture):
            self.assertEqual(run(), run())

    def test_mixing_fixture_and_no_completion_claim(self):
        fixture = c.mixing_fixture()
        self.assertFalse(fixture["production_authorized"])
        for key in ("glacial", "tephra", "aeolian"):
            result = fixture[key]
            self.assertLedger(result)
            self.assertFalse(result["physical_validation_passed"])
            self.assertFalse(result["production_authorized"])
            self.assertFalse(result["full_landform_family_implemented"])
        initial = math.fsum(fixture["aeolian_initial_mobile_thickness_m"]) * 100 * .6
        final = math.fsum(fixture["aeolian"]["mobile_thickness_m"]) * 100 * .6
        self.assertAlmostEqual(initial, final + fixture["aeolian"]["ledger"]["exported_solid_m3"], delta=1e-12)


if __name__ == "__main__":
    unittest.main()
