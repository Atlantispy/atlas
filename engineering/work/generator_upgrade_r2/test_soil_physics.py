"""Bounded soil physics checks; run normally and -OO with optional --receipt."""
from dataclasses import replace
from fractions import Fraction as F
import argparse
import hashlib
import itertools
import json
import math
from pathlib import Path
import sys
import time
import types
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
RAW = (HERE / "soil_physics.py").read_bytes()
soil = types.ModuleType("_tested_soil_physics_r2")
soil.__file__ = str(HERE / "soil_physics.py")
sys.modules[soil.__name__] = soil
exec(compile(RAW, soil.__file__, "exec", dont_inherit=True, optimize=sys.flags.optimize), soil.__dict__)


def q(value, unit, high=None, status="SYNTHETIC TEST"):
    return soil.Interval(value, value if high is None else high, unit, "explicit analytical fixture", status)


def unknown(unit, status="UNKNOWN"):
    return soil.Interval(None, None, unit, "no applicable property supplied", status)


def support(kind="SCALAR_REFERENCE", resolution=None, process=None):
    return soil.Support(kind, resolution, process, "fixture-scenario", "declared physical support")


def horizon(code, depth, identity=None):
    return soil.Horizon(identity or "h-"+"".join(code), tuple(code), depth if type(depth) is soil.Interval else q(depth, "m"),
                        unknown("m/s"), unknown("m/s"), "operational synthetic horizon")


def profile(horizons=(), absent=(), solum_absent=None):
    return soil.SoilProfile("profile", tuple(horizons), tuple(absent), solum_absent,
                            q(.7, "m"), q(4, "m"), q(8, "m"), support(), "explicit distinct depth meanings")


def roots(cohesion=0, depth=0, mode="ABSENT"):
    return soil.Roots(q(cohesion, "Pa"), q(depth, "m"), mode, "basal contact/strength/depth fixture")


def slope(**changes):
    case = soil.SlopeCase("slope", "SHALLOW_TRANSLATIONAL_SOIL", q(1, "m"), q(45, "degree"), q(20000, "N/m3"),
                          q(1000, "Pa"), q(45, "degree"), q(2000, "Pa"), roots(), support(),
                          "water-fixture", "material-fixture", "uniform vertical-depth static case")
    return replace(case, **changes)


def hydraulic(identity, depth, k, vertical=None):
    return soil.ConductivityLayer(identity, depth if type(depth) is soil.Interval else q(depth, "m"),
                                  k if type(k) is soil.Interval else q(k, "m/s"),
                                  k if type(k) is soil.Interval and vertical is None else q(k if vertical is None else vertical, "m/s"))


class ProfileTests(unittest.TestCase):
    def test_mineral_solum_excludes_organic_and_c_parent(self):
        value = soil.profile_outputs(profile((horizon("O", .125), horizon("A", .25), horizon("E", .125),
                                              horizon("B", .5), horizon("C", 2), horizon("R", 1))))
        self.assertEqual(value["mineral_solum_thickness_m"]["lower"], .875)
        self.assertEqual(value["surface_organic_thickness_m"]["lower"], .125)
        self.assertEqual(value["depth_to_rock_from_ground_m"]["lower"], 3)
        self.assertEqual(value["rooting_depth_m"]["lower"], .7)
        self.assertEqual(value["unconsolidated_thickness_m"]["lower"], 4)
        self.assertEqual(value["weathered_regolith_thickness_m"]["lower"], 8)
        self.assertIsNone(value["fertility"]["value"])

    def test_zero_solum_requires_explicit_absence(self):
        unresolved = soil.profile_outputs(profile((horizon("C", 2),)))
        self.assertEqual(unresolved["solum_mask"], "UNKNOWN")
        self.assertIsNone(unresolved["mineral_solum_thickness_m"]["lower"])
        absent = soil.profile_outputs(profile((horizon("C", 2),), solum_absent="explicit exposed parent without mineral solum"))
        self.assertEqual(absent["mineral_solum_thickness_m"]["lower"], 0)
        self.assertEqual(absent["solum_mask"], "EXPLICIT_ABSENCE")

    def test_organic_dominated_profile_retains_distinct_zero_solum(self):
        value = soil.profile_outputs(profile((horizon("O", 2), horizon("R", 1)), solum_absent="organic directly over rock"))
        self.assertEqual(value["surface_organic_thickness_m"]["lower"], 2)
        self.assertEqual(value["mineral_solum_thickness_m"]["upper"], 0)

    def test_truncated_profile_is_not_zero_soil(self):
        value = soil.profile_outputs(profile((horizon("A", .25), horizon("B", .5))))
        self.assertEqual(value["solum_mask"], "UNKNOWN")
        self.assertIsNone(value["depth_to_rock_from_ground_m"]["lower"])

    def test_empty_unknown_profile_is_not_absent_soil(self):
        value = soil.profile_outputs(profile())
        self.assertEqual(value["solum_mask"], "UNKNOWN")
        self.assertEqual(set(value["horizon_presence"].values()), {"UNKNOWN"})

    def test_absent_ambiguous_and_unknown_horizons_stay_distinct(self):
        value = soil.profile_outputs(profile((horizon("A", .25), horizon("BC", .5), horizon("R", 1)),
                                              absent=(("E", "explicit absence"),)))
        self.assertEqual(value["horizon_presence"]["A"], "PRESENT")
        self.assertEqual(value["horizon_presence"]["B"], "AMBIGUOUS")
        self.assertEqual(value["horizon_presence"]["E"], "ABSENT")
        self.assertEqual(value["horizon_presence"]["O"], "UNKNOWN")
        self.assertEqual(value["solum_mask"], "AMBIGUOUS")

    def test_ambiguous_pedogenic_horizon_still_allows_geometric_solum(self):
        value = soil.profile_outputs(profile((horizon("AE", .25), horizon("B", .5), horizon("CR", 1))))
        self.assertEqual(value["solum_mask"], "VALID")
        self.assertEqual(value["mineral_solum_thickness_m"]["lower"], .75)
        self.assertIsNone(value["depth_to_rock_from_ground_m"]["lower"])

    def test_unknown_organic_depth_does_not_erase_known_mineral_thickness(self):
        value = soil.profile_outputs(profile((horizon("O", unknown("m")), horizon("A", .25), horizon("C", 1))))
        self.assertIsNone(value["surface_organic_thickness_m"]["lower"])
        self.assertEqual(value["mineral_solum_thickness_m"]["lower"], .25)
        self.assertIsNone(value["horizons"][1]["top_depth_m"]["lower"])

    def test_unknown_mineral_thickness_propagates(self):
        value = soil.profile_outputs(profile((horizon("A", unknown("m")), horizon("C", 1))))
        self.assertEqual(value["solum_mask"], "UNKNOWN")

    def test_unknown_horizon_classification_is_not_an_invented_parent(self):
        value = soil.profile_outputs(profile((horizon("A", .25), horizon("", .5, "unclassified"), horizon("R", 1))))
        self.assertEqual(value["horizons"][1]["interpretation_mask"], "UNKNOWN")
        self.assertEqual(value["horizons"][1]["top_depth_m"]["lower"], .25)
        self.assertEqual(value["solum_mask"], "UNKNOWN")
        self.assertIsNone(value["mineral_solum_thickness_m"]["lower"])
        self.assertIsNone(value["depth_to_rock_from_ground_m"]["lower"])

    def test_interval_geometry_outward_encloses_exact_sum(self):
        value = soil.profile_outputs(profile((horizon("A", q(.1, "m", .2)), horizon("B", q(.2, "m", .4)), horizon("C", 1))))
        interval = value["mineral_solum_thickness_m"]
        self.assertLessEqual(F(interval["lower"]), F(.1)+F(.2))
        self.assertGreaterEqual(F(interval["upper"]), F(.2)+F(.4))

    def test_buried_organic_is_not_silently_mineralised(self):
        value = soil.profile_outputs(profile((horizon("A", .25), horizon("O", .5), horizon("C", 1))))
        self.assertEqual(value["solum_mask"], "AMBIGUOUS")

    def test_invalid_horizons_and_conflicting_absence_rejected(self):
        for body in (lambda: horizon("X", 1), lambda: horizon("A", 0),
                     lambda: profile((horizon("A", 1),), absent=(("A", "absent"),)),
                     lambda: profile((horizon("A", 1),), solum_absent="absent"),
                     lambda: profile((horizon("A", 1), horizon("A", 1)))):
            with self.assertRaises(ValueError):
                body()

    def test_rock_material_metadata_cannot_be_passed_as_horizon(self):
        with self.assertRaises(ValueError):
            soil.profile_outputs({"material_id": "rock", "mass_kg": 100})


class HydraulicTests(unittest.TestCase):
    def test_micrometre_unit_conversion_is_not_identity(self):
        result = soil.ksat_um_s_to_m_s(q(2, "um/s", 10))
        self.assertLessEqual(F(result.lower), F(2, 1_000_000))
        self.assertGreaterEqual(F(result.upper), F(10, 1_000_000))
        self.assertLess(result.upper, .000011)

    def test_unknown_conductivity_conversion_preserves_unknown(self):
        result = soil.ksat_um_s_to_m_s(unknown("um/s", "CONFLICT"))
        self.assertIsNone(result.lower)
        self.assertEqual(result.source_status, "CONFLICT")

    def test_intrinsic_permeability_independent_dimensional_oracle(self):
        fluid = soil.Fluid(q(1000, "kg/m3"), q(.001, "Pa*s"), q(10, "m/s2"), q(300, "K"), "synthetic test liquid", "explicit supplied fluid state")
        result = soil.intrinsic_permeability(q(.0001, "m/s"), fluid)
        exact = F(.0001)*F(.001)/(1000*10)
        self.assertLessEqual(F(result.lower), exact)
        self.assertGreaterEqual(F(result.upper), exact)
        self.assertAlmostEqual(result.lower, 1e-11, delta=1e-25)
        self.assertEqual(result.unit, "m2")

    def test_intrinsic_interval_contains_all_input_corners(self):
        fluid = soil.Fluid(q(900, "kg/m3", 1100), q(.001, "Pa*s", .002), q(8, "m/s2", 10), q(280, "K", 310), "scenario liquid", "Cartesian physical intervals")
        result = soil.intrinsic_permeability(q(1e-5, "m/s", 1e-4), fluid)
        for k, mu, rho, g in itertools.product((1e-5, 1e-4), (.001, .002), (900, 1100), (8, 10)):
            exact = F(k)*F(mu)/(F(rho)*F(g))
            self.assertLessEqual(F(result.lower), exact)
            self.assertGreaterEqual(F(result.upper), exact)

    def test_intrinsic_requires_fluid_assumptions_and_consistent_units(self):
        with self.assertRaises(ValueError):
            soil.intrinsic_permeability(q(1, "m/s"), None)
        fluid = soil.Fluid(q(1000, "kg/m3"), q(.001, "Pa*s"), q(10, "m/s2"), unknown("K"), "water", "temperature unresolved")
        self.assertFalse(soil.intrinsic_permeability(q(1, "m/s"), fluid).known)
        with self.assertRaises(ValueError):
            soil.intrinsic_permeability(q(1, "m2"), fluid)

    def test_layered_series_parallel_analytical_values(self):
        result = soil.layered_ksat((hydraulic("a", 1, 4), hydraulic("b", 3, 1)))
        self.assertEqual(result["horizontal_m_s"]["lower"], 1.75)
        self.assertLessEqual(F(result["vertical_m_s"]["lower"]), F(16, 13))
        self.assertGreaterEqual(F(result["vertical_m_s"]["upper"]), F(16, 13))

    def test_layer_order_does_not_change_steady_equivalent(self):
        layers = (hydraulic("a", 1, 4), hydraulic("b", 3, 1))
        first, second = soil.layered_ksat(layers), soil.layered_ksat(tuple(reversed(layers)))
        for direction in ("horizontal_m_s", "vertical_m_s"):
            self.assertEqual(first[direction], second[direction])

    def test_single_anisotropic_layer_retains_directions(self):
        result = soil.layered_ksat((hydraulic("a", 2, 10, .5),))
        self.assertEqual(result["horizontal_m_s"]["lower"], 10)
        self.assertEqual(result["vertical_m_s"]["upper"], .5)

    def test_zero_conductivity_layer_blocks_vertical_not_horizontal(self):
        result = soil.layered_ksat((hydraulic("a", 1, 4), hydraulic("b", 1, 0)))
        self.assertEqual(result["vertical_m_s"]["upper"], 0)
        self.assertEqual(result["horizontal_m_s"]["lower"], 2)

    def test_uncertain_thickness_and_conductivity_contains_all_corners(self):
        layers = (hydraulic("a", q(1, "m", 2), q(2, "m/s", 4)), hydraulic("b", q(2, "m", 3), q(1, "m/s", 2)))
        result = soil.layered_ksat(layers)
        for h1, h2, k1, k2 in itertools.product((1, 2), (2, 3), (2, 4), (1, 2)):
            horizontal = F(h1*k1+h2*k2, h1+h2)
            vertical = F(h1+h2)/(F(h1, k1)+F(h2, k2))
            for direction, exact in (("horizontal_m_s", horizontal), ("vertical_m_s", vertical)):
                self.assertLessEqual(F(result[direction]["lower"]), exact)
                self.assertGreaterEqual(F(result[direction]["upper"]), exact)

    def test_uniform_property_remains_exact_with_uncertain_thickness(self):
        result = soil.layered_ksat((hydraulic("a", q(1, "m", 10), 2), hydraulic("b", q(2, "m", 20), 2)))
        for direction in ("horizontal_m_s", "vertical_m_s"):
            self.assertEqual(result[direction]["lower"], 2)
            self.assertEqual(result[direction]["upper"], 2)

    def test_unknown_direction_does_not_erase_known_other_direction(self):
        layer = soil.ConductivityLayer("a", q(1, "m"), q(2, "m/s"), unknown("m/s"))
        result = soil.layered_ksat((layer,))
        self.assertEqual(result["horizontal_m_s"]["lower"], 2)
        self.assertIsNone(result["vertical_m_s"]["lower"])

    def test_bad_layer_quantities_and_duplicate_inventory_rejected(self):
        for body in (lambda: hydraulic("a", 0, 1), lambda: hydraulic("a", 1, -1),
                     lambda: soil.layered_ksat(()), lambda: soil.layered_ksat((hydraulic("a", 1, 1), hydraulic("a", 1, 2)))):
            with self.assertRaises(ValueError):
                body()


class StabilityTests(unittest.TestCase):
    def test_independent_45_degree_stress_oracle(self):
        result = soil.factor_of_safety(slope(roots=roots(500, 2, "BASAL")))
        # gamma*z=20000Pa; normal=tau=10000Pa; effective=8000Pa;
        # resistance=1000+500+8000=9500Pa; FS=.95.
        self.assertEqual(result["mask"], "VALID")
        self.assertAlmostEqual(result["factor_of_safety"], .95, delta=2e-15)
        self.assertAlmostEqual(result["driving_shear_pa"], 10000, delta=2e-10)
        self.assertAlmostEqual(result["effective_normal_stress_pa"], 8000, delta=2e-10)

    def test_dry_cohesionless_tangent_ratio(self):
        result = soil.factor_of_safety(slope(slope_degrees=q(30, "degree"), effective_friction_degrees=q(40, "degree"),
                                            effective_cohesion_pa=q(0, "Pa"), pore_pressure_pa=q(0, "Pa")))
        expected = math.tan(math.radians(40))/math.tan(math.radians(30))
        self.assertAlmostEqual(result["factor_of_safety"], expected, delta=2e-15)

    def test_cohesionless_dry_stability_independent_of_depth_weight(self):
        base = slope(effective_cohesion_pa=q(0, "Pa"), pore_pressure_pa=q(0, "Pa"))
        first = soil.factor_of_safety(base)
        second = soil.factor_of_safety(replace(base, vertical_failure_depth_m=q(2, "m"), bulk_unit_weight_n_m3=q(40000, "N/m3")))
        self.assertEqual(first["factor_of_safety"], second["factor_of_safety"])

    def test_water_pressure_reduces_resistance_by_correct_amount(self):
        first = soil.factor_of_safety(slope(pore_pressure_pa=q(0, "Pa")))
        second = soil.factor_of_safety(slope(pore_pressure_pa=q(2000, "Pa")))
        self.assertAlmostEqual(first["factor_of_safety"]-second["factor_of_safety"], .2, delta=2e-15)

    def test_added_basal_root_strength_increases_fs(self):
        first = soil.factor_of_safety(slope())
        second = soil.factor_of_safety(slope(roots=roots(500, 2, "BASAL")))
        self.assertAlmostEqual(second["factor_of_safety"]-first["factor_of_safety"], .05, delta=2e-15)

    def test_below_root_failure_receives_zero_basal_contribution(self):
        first = soil.factor_of_safety(slope())
        second = soil.factor_of_safety(slope(roots=roots(5000, .5, "BASAL")))
        self.assertEqual(first["factor_of_safety"], second["factor_of_safety"])
        self.assertEqual(second["effective_basal_root_cohesion_pa"], 0)
        self.assertEqual(second["root_geometry_flag"], "ROOTS_DO_NOT_REACH_FAILURE_PLANE")

    def test_unknown_root_strength_is_irrelevant_below_all_roots(self):
        root = soil.Roots(unknown("Pa"), q(.5, "m"), "BASAL", "all roots above plane")
        self.assertEqual(soil.factor_of_safety(slope(roots=root))["factor_of_safety"], soil.factor_of_safety(slope())["factor_of_safety"])

    def test_lateral_roots_are_not_silently_basal(self):
        with self.assertRaises(ValueError):
            roots(5000, 2, "LATERAL_ONLY")
        result = soil.factor_of_safety(slope(roots=roots(0, 2, "LATERAL_ONLY")))
        self.assertEqual(result["effective_basal_root_cohesion_pa"], 0)
        self.assertEqual(result["root_geometry_flag"], "LATERAL_ONLY")

    def test_unknown_water_or_strength_is_masked_not_dry_zero(self):
        for change in ({"pore_pressure_pa": unknown("Pa")}, {"effective_cohesion_pa": unknown("Pa")},
                       {"pore_pressure_pa": q(0, "Pa", 1000)}):
            result = soil.factor_of_safety(slope(**change))
            self.assertEqual(result["mask"], "UNKNOWN")
            self.assertIsNone(result["factor_of_safety"])

    def test_unresolved_root_geometry_is_masked(self):
        root = soil.Roots(q(500, "Pa"), unknown("m"), "BASAL", "depth unknown")
        self.assertEqual(soil.factor_of_safety(slope(roots=root))["mask"], "UNKNOWN")

    def test_unsupported_hydraulic_and_zero_shear_regimes_masked(self):
        for case in (slope(pore_pressure_pa=q(-10, "Pa")), slope(pore_pressure_pa=q(20000, "Pa")),
                     slope(slope_degrees=q(0, "degree"))):
            result = soil.factor_of_safety(case)
            self.assertEqual(result["mask"], "INAPPLICABLE")
            self.assertIsNone(result["factor_of_safety"])

    def test_rockfall_deep_failure_and_cell_mean_are_separate(self):
        for case in (slope(regime="ROCKFALL"), slope(regime="DEEP_FAILURE"),
                     slope(support=support("CELL_MEAN", 1000, 1000))):
            self.assertEqual(soil.factor_of_safety(case)["mask"], "INAPPLICABLE")

    def test_representative_subgrid_support_is_explicit(self):
        case = slope(support=support("SUBGRID_CASE", 1000, 20))
        result = soil.factor_of_safety(case)
        self.assertEqual(result["mask"], "VALID")
        self.assertEqual(result["inputs"]["support"]["process_support_m"], 20)

    def test_grid_preserves_partial_unknown_and_inapplicable_cases(self):
        cells = ((slope(), slope(case_id="unknown", pore_pressure_pa=unknown("Pa"))),
                 (slope(regime="ROCKFALL"),), (slope(pore_pressure_pa=unknown("Pa")),), (slope(),))
        result = soil.stability_grid((2, 2), cells)
        self.assertEqual([x["mask"] for x in result["cells"]], ["PARTIAL", "INAPPLICABLE", "UNKNOWN", "VALID"])
        self.assertFalse(result["cells"][0]["complete_for_supplied_cases"])
        self.assertIsNone(result["cells"][1]["known_case_minimum"])
        self.assertEqual(result["support_mode"], "INDEXED_SCALAR_REFERENCE_NOT_MAPPED")
        json.dumps(result, allow_nan=False)

    def test_positive_friction_underflow_is_not_valid_zero_resistance(self):
        with self.assertRaisesRegex(ValueError, "friction angle underflows"):
            soil.factor_of_safety(slope(effective_friction_degrees=q(math.nextafter(0.0, 1.0), "degree"),
                                        effective_cohesion_pa=q(0, "Pa"), pore_pressure_pa=q(0, "Pa")))
        exact_zero = soil.factor_of_safety(slope(effective_friction_degrees=q(0, "degree"),
                                                 effective_cohesion_pa=q(0, "Pa"), pore_pressure_pa=q(0, "Pa")))
        self.assertEqual(exact_zero["mask"], "VALID")
        self.assertEqual(exact_zero["factor_of_safety"], 0)

    def test_mapped_cases_and_indexed_references_do_not_mix(self):
        mapped = slope(support=support("SUBGRID_CASE", 1000, 20))
        result = soil.stability_grid((1, 1), ((mapped,),))
        self.assertEqual(result["support_mode"], "DECLARED_REPRESENTATIVE_CASE_GRID")
        scalar = slope(support=support("SCALAR_REFERENCE", 1000, 20))
        with self.assertRaises(ValueError):
            soil.stability_grid((1, 2), ((mapped,), (scalar,)))

    def test_grid_rejects_bad_inventory_duplicate_cases_or_mixed_frames(self):
        for shape, cells in (((True, 1), ((slope(),),)), ((1, 2), ((slope(),),)),
                             ((1, 1), ((slope(), slope()),)),
                             ((1, 2), ((slope(),), (slope(support=support("SUBGRID_CASE", 1000, 10)),)))):
            with self.assertRaises(ValueError):
                soil.stability_grid(shape, cells)

    def test_invalid_parameters_units_and_absent_root_contradiction(self):
        for change in ({"slope_degrees": q(90, "degree")}, {"effective_friction_degrees": q(-1, "degree")},
                       {"bulk_unit_weight_n_m3": q(20, "kN/m3")}, {"vertical_failure_depth_m": q(0, "m")},
                       {"effective_cohesion_pa": q(-1, "Pa")}):
            with self.assertRaises(ValueError):
                slope(**change)
        with self.assertRaises(ValueError):
            roots(0, 2, "ABSENT")


class BindingTests(unittest.TestCase):
    def test_interval_validation_and_source_status(self):
        for body in (lambda: q(math.nan, "m"), lambda: q(True, "m"), lambda: q(3, "m", 2),
                     lambda: q(1, "m", status="UNKNOWN"),
                     lambda: soil.Interval(None, 1, "m", "missing", "UNKNOWN")):
            with self.assertRaises(ValueError):
                body()

    def test_owner_binding_and_actual_reference(self):
        self.assertEqual(hashlib.sha256(soil.OWNER_PATH.read_bytes()).hexdigest(), soil.OWNER_SHA256)
        value = soil.verification_reference()
        self.assertEqual(value, soil.verification_reference())
        self.assertAlmostEqual(value["stability"]["factor_of_safety"], .95, delta=2e-15)
        json.dumps(value, allow_nan=False)

    def test_owner_drift_fails_closed_without_editing_owner_source(self):
        with mock.patch.object(soil, "OWNER_SHA256", "0"*64), self.assertRaises(ValueError):
            soil.profile_outputs(profile())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    paths = [HERE / "soil_physics.py", HERE / "test_soil_physics.py", HERE / "SOIL_DESIGN.md", soil.OWNER_PATH,
             HERE.parent / "generator_upgrade_r1/landscape.py", HERE.parent / "terrain_model_r7/hillslope_kernel.py"]
    before = {str(path.resolve()): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    def ids(node):
        return [item for child in node for item in ids(child)] if isinstance(node, unittest.TestSuite) else [node.id()]
    inventory = ids(suite)
    start = time.perf_counter()
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    elapsed = time.perf_counter()-start
    after = {path: hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in before}
    receipt = {"schema": "soil-physics-r2-verification", "tests_run": result.testsRun, "test_ids": inventory,
               "failures": [(t.id(), message) for t, message in result.failures],
               "errors": [(t.id(), message) for t, message in result.errors],
               "skipped": [(t.id(), message) for t, message in result.skipped],
               "elapsed_seconds": elapsed, "python_optimize": sys.flags.optimize,
               "executed_soil_source_sha256": hashlib.sha256(RAW).hexdigest(),
               "sources_before": before, "sources_after": after,
               "source_preservation_pass": before == after,
               "status": "PASS" if result.wasSuccessful() and before == after else "FAIL"}
    if args.receipt:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(json.dumps(receipt, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    return 0 if receipt["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
