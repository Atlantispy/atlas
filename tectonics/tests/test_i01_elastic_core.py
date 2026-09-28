"""Focused MC-07 elastic-core tests: stiffness and transfer depth from one declared interval, independent quadrature of
the core's shear density, the smooth through-core profile against the unchanged join for both signs of B, force
balance, a physical core shift against datum changes, the dry and uniform limits, zero rigidity refused as a core, and
atomic refusals. The bounded controls are called directly; no receipt is written and the CLI is exercised only for
exclusive creation.
SPDX-License-Identifier: AGPL-3.0-only
"""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"tools"))
import check_i01_elastic_core as k

j, gpe, water = k.j, k.gpe, k.water
DATUM = gpe.Datum(6474600000., -200e3)
RHO_C, H0 = 2800., 35e3
F = 1-RHO_C/3300.
TOL = j.quadrature_tolerance(DATUM)
CORE = {"material": "test core", "basis": "test assumption: a homogeneous core 5 to 20 km below the rock surface",
        "depth_reference": "rock_surface", "top_depth_m": 5e3, "bottom_depth_m": 20e3, "young_pa": 70e9, "poisson": .25}


def plate(core=CORE, shape=(16, 16)):
    return k.core_plate(core, DATUM, shape, 600e3, 400e3, rho_w_kg_m3=1000.)


def crust(surface):
    """One constant-density crust layer per cell whose dry surface is Z_ref + F*H0 + surface."""
    return ((H0+np.asarray(surface, dtype=float)/F).reshape(-1, 1), RHO_C, 0., 1000., 1000.)


def pattern(shape):
    y, x = np.indices(shape)
    return (500*np.cos(2*np.pi*x/shape[1])+300*np.cos(2*np.pi*y/shape[0])
            + 80*np.sin(2*np.pi*(x/shape[1]+y/shape[0])))


def mode_columns(shape=(16, 16), amplitude=10.):
    y, x = np.indices(shape)
    return crust(amplitude*np.cos(2*np.pi*(2*x/shape[1]+y/shape[0])))


def exact(p, cols, datum=DATUM, mean_water=1000., amplitude=10.):
    """The retained closed-form fully wet (2,1) state on this datum's dry surface."""
    z0 = gpe.columns(datum, *cols)["surface_elevation_m"].reshape(p.shape)
    return j.fourier_mode_state(p, z0, mode=(2, 1), mean_water_m=mean_water, bed_amplitude_m=amplitude,
                                surface_mean_m=j.reference_top(datum)+F*H0)


def produce(p, cols, state, volume, core=CORE, datum=DATUM):
    return k.core_loaded_gpe(datum, *cols, core, p, state, volume_m3=volume, **water.ARGS)


def smooth(datum, h, d, w, top, bottom, transfer=None):
    return k.smooth_core_column(datum, [h], [RHO_C], [RHO_C], rho_w_kg_m3=1000., water_depth_m=d, displacement_m=w,
                                core_top_m=top, core_bottom_m=bottom, transfer_pa=transfer)


class DeclarationTests(unittest.TestCase):
    def test_one_interval_defines_stiffness_and_transfer_depth(self):
        core = k.elastic_core(CORE)
        self.assertEqual((core.thickness_m, core.shear_transfer_depth_m), (15e3, 12.5e3))
        p = plate()
        self.assertEqual(p, water.Plate((16, 16), 600e3, 400e3, 15e3))            # the retained plate constants
        self.assertEqual(p.rigidity_n_m, core.rigidity_n_m)
        self.assertEqual(k.ElasticCore(**CORE), core)                             # dataclass and mapping routes agree
        self.assertEqual(k.elastic_core(core), core)
        shear = k.core_shear_level(CORE)
        self.assertEqual((set(shear), shear["depth_below_bed_m"]), ({"depth_below_bed_m", "basis"}, 12.5e3))
        self.assertIn(CORE["basis"], shear["basis"])

    def test_shear_density_quadrature_and_rigidity_from_core_stresses(self):
        a, b = 5e3, 20e3
        total, moment = k.shear_moments(a, b)
        self.assertAlmostEqual(total, 1., delta=1e-14)
        self.assertAlmostEqual(moment, 12.5e3, delta=1e-8)
        for u in (0., .1, .25, .5, .9, 1.):
            self.assertAlmostEqual(k.carried_fraction(a+u*(b-a), a, b), 3*u*u-2*u**3, delta=1e-14)
        self.assertAlmostEqual(k.shear_moments(0., 15e3)[1], 7.5e3, delta=1e-8)
        core = k.elastic_core(CORE)
        for order in (2, 3):
            self.assertAlmostEqual(k.kirchhoff_rigidity(core, order), core.rigidity_n_m, delta=1e-12*core.rigidity_n_m)

    def test_rigidity_alone_does_not_locate_the_core(self):
        cores = [k.elastic_core(dict(CORE, top_depth_m=top, bottom_depth_m=top+15e3)) for top in (0., 5e3, 15e3)]
        self.assertEqual({c.rigidity_n_m for c in cores}, {cores[0].rigidity_n_m})
        self.assertEqual({plate(c) for c in cores}, {plate()})
        self.assertEqual([c.shear_transfer_depth_m for c in cores], [7.5e3, 12.5e3, 22.5e3])

    def test_declaration_refusals_leave_inputs_unchanged(self):
        unplaced = {key: value for key, value in CORE.items() if not key.endswith("_depth_m")}
        cases = [
            (unplaced, k.UNPLACED), (dict(unplaced, elastic_thickness_m=15e3), k.UNPLACED),
            (dict(unplaced, rigidity_n_m=2.1e22), k.UNPLACED), (dict(CORE, top_depth_m=None), k.UNPLACED),
            (dict(CORE, elastic_thickness_m=15e3), k.INVALID_CORE),
            (dict(CORE, top_depth_m=20e3, bottom_depth_m=5e3), k.INVALID_CORE),
            (dict(CORE, bottom_depth_m=5e3), k.INVALID_CORE), (dict(CORE, top_depth_m=-1.), k.OUTSIDE_ROCK),
            (dict(CORE, top_depth_m=np.full(4, 5e3)), k.UNSUPPORTED_CORE),
            (dict(CORE, young_pa=[70e9, 80e9]), k.UNSUPPORTED_CORE),
            ([CORE, dict(CORE, top_depth_m=25e3, bottom_depth_m=30e3)], k.UNSUPPORTED_CORE),
            (dict(CORE, layers=[CORE]), k.UNSUPPORTED_CORE),
            (dict(CORE, bottom_depth_m=float("nan")), k.INVALID_CORE), (dict(CORE, young_pa=float("inf")), k.INVALID_CORE),
            (dict(CORE, young_pa=True), k.INVALID_CORE), (dict(CORE, young_pa="70 GPa"), k.INVALID_CORE),
            (dict(CORE, young_pa=0.), k.INVALID_CORE), (dict(CORE, young_pa=1e300), k.INVALID_CORE),
            (dict(CORE, young_pa=10**400), k.INVALID_CORE),
            (dict(CORE, poisson=.5), k.INVALID_CORE), (dict(CORE, poisson=-1.), k.INVALID_CORE),
            (dict(CORE, basis=" "), k.INVALID_CORE), (dict(CORE, material=""), k.INVALID_CORE),
            (dict(CORE, basis=b"test"), k.INVALID_CORE), (dict(CORE, depth_reference="sea_surface"), k.INVALID_CORE),
            ("core", k.INVALID_CORE)]
        for declaration, expected in cases:
            with self.subTest(declaration=repr(declaration)[:90]):
                before = j.fingerprint(declaration)
                self.assertEqual(j.refusal_code(lambda: k.elastic_core(declaration)), expected)
                self.assertEqual(j.fingerprint(declaration), before)
        with self.assertRaises(j.Refusal) as caught:
            k.ElasticCore(**dict(CORE, bottom_depth_m=None))
        self.assertEqual(caught.exception.code, k.UNPLACED)
        auxetic = k.elastic_core(dict(CORE, poisson=-.2))              # physically admissible, not a retained Plate
        self.assertEqual(j.refusal_code(lambda: plate(auxetic)), k.UNSUPPORTED_CORE)


class FourierTests(unittest.TestCase):
    """The fully wet (2,1) mode on the core's own plate, with the retained closed-form state."""

    def setUp(self):
        self.p = plate()
        self.cols = mode_columns()
        self.state = exact(self.p, self.cols)
        self.volume = 1000.*self.p.length_x_m*self.p.length_y_m
        self.r = produce(self.p, self.cols, self.state, self.volume)

    def test_smooth_profile_matches_producer_for_both_signs_of_B(self):
        r, excess = self.r, self.r["basal_overburden_excess_pa"]
        self.assertEqual(r["regime"], j.FLEXURAL)
        transfer = k.kirchhoff_transfer(k.elastic_core(CORE), self.p, self.state["displacement_m"])
        scale = 1000*9.81*float(np.max(self.state["depth_m"]))
        np.testing.assert_allclose(transfer, excess, rtol=0, atol=1e-7*scale)          # the core's shear carries B
        oracle = k.smooth_potential(DATUM, self.cols, self.state, 5e3, 20e3, rho_w_kg_m3=1000., transfer_pa=transfer)
        np.testing.assert_allclose(oracle["basal_pressure_pa"], DATUM.pressure_pa, rtol=0, atol=1e-7*scale)
        v_q = oracle["anomaly_j_m2"].reshape(self.p.shape)
        for mask in (excess > 1e3, excess < -1e3):
            self.assertTrue(np.any(mask))
            self.assertLessEqual(float(np.max(np.abs(v_q-r["gpe_anomaly_j_m2"])[mask])), TOL)
        t, t_q = (j.planar_traction(v, plate=self.p, reduction=1.) for v in (r["gpe_anomaly_j_m2"], v_q))
        self.assertLessEqual(float(np.max(np.abs(t-t_q))), TOL/25e3)
        for face in (5e3, 20e3):                          # a step at either core face is not this profile
            step = j.water_loaded_gpe(DATUM, *self.cols, self.p, self.state, volume_m3=self.volume,
                                      shear_level={"depth_below_bed_m": face, "basis": "contrast"}, **water.ARGS)
            self.assertGreater(float(np.max(np.abs(step["gpe_anomaly_j_m2"]-v_q))), 1000*TOL)

    def test_producer_is_the_unchanged_join_with_the_derived_level(self):
        joined = j.water_loaded_gpe(DATUM, *self.cols, self.p, self.state, volume_m3=self.volume,
                                    shear_level=k.core_shear_level(CORE), **water.ARGS)
        self.assertTrue(k.same_result(self.r, joined))
        record = self.r["elastic_core"]
        self.assertEqual((record["contract"], record["shear_transfer_depth_m"], record["rigidity_n_m"]),
                         (k.CONTRACT, 12.5e3, self.p.rigidity_n_m))
        self.assertFalse(self.r["finite_rigidity_closure"])
        cell = self.p.length_x_m*self.p.length_y_m/256
        self.assertAlmostEqual(float(np.sum(self.r["water_mass_kg_m2"]))*cell/(1000*self.volume), 1., places=10)
        # The explicitly declared surface core reproduces the retained control level Te/2 = 7.5 km bit for bit.
        surface = produce(self.p, self.cols, self.state, self.volume, core=dict(CORE, top_depth_m=0., bottom_depth_m=15e3))
        level = j.water_loaded_gpe(DATUM, *self.cols, self.p, self.state, volume_m3=self.volume,
                                   shear_level={"depth_below_bed_m": 7500., "basis": "retained control level"},
                                   **water.ARGS)
        np.testing.assert_array_equal(surface["gpe_anomaly_j_m2"], level["gpe_anomaly_j_m2"])

    def test_datum_translation_and_extension_leave_the_potential(self):
        v = self.r["gpe_anomaly_j_m2"]
        deeper, moved = j.deepen(DATUM, 1e5), j.translate(DATUM, 1e5)
        np.testing.assert_array_equal(produce(self.p, self.cols, self.state, self.volume, datum=deeper)
                                      ["gpe_anomaly_j_m2"], v)
        moved_state = exact(self.p, self.cols, datum=moved)
        np.testing.assert_array_equal(produce(self.p, self.cols, moved_state, self.volume, datum=moved)
                                      ["gpe_anomaly_j_m2"], v)
        both = TOL+j.quadrature_tolerance(deeper)
        h, d, w = self.cols[0][:, 0], self.state["depth_m"].ravel(), self.state["displacement_m"].ravel()
        for i in (0, 37, 101, 200):
            at = smooth(DATUM, h[i], d[i], w[i], 5e3, 20e3)["anomaly_j_m2"]
            self.assertAlmostEqual(smooth(deeper, h[i], d[i], w[i], 5e3, 20e3)["anomaly_j_m2"], at, delta=both)

    def test_retained_solver_state_within_propagated_bound(self):
        z0 = gpe.columns(DATUM, *self.cols)["surface_elevation_m"].reshape(self.p.shape)
        r = produce(self.p, self.cols, self.p.equilibrium(z0, self.volume, **water.ARGS), self.volume)
        self.assertEqual(r["regime"], j.FLEXURAL)
        bound = j.perturbation_bound(self.p, self.r, 12.5e3, 2e-6, 4e-6)+TOL
        self.assertLessEqual(float(np.max(np.abs(r["gpe_anomaly_j_m2"]-self.r["gpe_anomaly_j_m2"]))), bound)


class CoreShiftTests(unittest.TestCase):
    def test_physical_shift_changes_potential_by_delta_B_but_datum_changes_do_not(self):
        p = plate()
        cols = crust(pattern(p.shape))
        z0 = gpe.columns(DATUM, *cols)["surface_elevation_m"].reshape(p.shape)
        volume = 200.*p.length_x_m*p.length_y_m
        state = p.equilibrium(z0, volume, **water.ARGS)
        self.assertTrue(0 < np.mean(state["depth_m"] > 0) < 1)
        shifted = dict(CORE, top_depth_m=8e3, bottom_depth_m=23e3)
        self.assertEqual(plate(shifted), p)                                          # same h, E and nu: same D
        r, r2 = produce(p, cols, state, volume), produce(plate(shifted), cols, state, volume, core=shifted)
        excess, v = r["basal_overburden_excess_pa"], r["gpe_anomaly_j_m2"]
        np.testing.assert_array_equal(r2["basal_overburden_excess_pa"], excess)
        rounding = 1e-12*float(np.max(np.abs(v)))
        np.testing.assert_allclose(r2["gpe_anomaly_j_m2"]-v, 3e3*excess, rtol=0, atol=rounding)
        t, t2 = (j.planar_traction(x["gpe_anomaly_j_m2"], plate=p, reduction=.7) for x in (r, r2))
        np.testing.assert_allclose(t2-t, j.planar_traction(3e3*excess, plate=p, reduction=.7), rtol=0,
                                   atol=rounding*.7/25e3)
        self.assertGreater(3e3*float(np.max(excess)-np.min(excess)), 1000*TOL)
        # Coordinate changes of the SAME core move no material: deepening is bitwise inert, and a translation moves
        # the column and its core together.
        np.testing.assert_array_equal(produce(p, cols, state, volume, datum=j.deepen(DATUM, 3e3))["gpe_anomaly_j_m2"], v)
        moved = j.translate(DATUM, 3e3)
        z0m = gpe.columns(moved, *cols)["surface_elevation_m"].reshape(p.shape)
        rm = produce(p, cols, p.equilibrium(z0m, volume, **water.ARGS), volume, datum=moved)
        self.assertLessEqual(float(np.max(np.abs(rm["gpe_anomaly_j_m2"]-v))),
                             j.perturbation_bound(p, r, 12.5e3, 1e-7, 2e-7)+TOL)
        h, d, w = cols[0][:, 0], state["depth_m"].ravel(), state["displacement_m"].ravel()
        for i in (0, 9, 77, 130, 255):
            base, deep = smooth(DATUM, h[i], d[i], w[i], 5e3, 20e3), smooth(DATUM, h[i], d[i], w[i], 8e3, 23e3)
            self.assertLessEqual(abs(base["anomaly_j_m2"]-float(v.flat[i])), TOL)
            self.assertAlmostEqual(deep["anomaly_j_m2"]-base["anomaly_j_m2"], 3e3*base["column_excess_pa"], delta=2*TOL)

    def test_core_may_reach_but_not_pass_the_thinnest_rock_base(self):
        p, cols = plate(), mode_columns()
        state, volume = exact(p, cols), 1000.*p.length_x_m*p.length_y_m
        thinnest = float(np.min(cols[0].sum(axis=1)))
        edge = dict(CORE, top_depth_m=thinnest-15e3, bottom_depth_m=thinnest)
        r = produce(plate(edge), cols, state, volume, core=edge)
        self.assertEqual((r["regime"], r["elastic_core"]["rock_below_core_m"]), (j.FLEXURAL, 0.))
        beyond = dict(CORE, top_depth_m=thinnest-15e3+1., bottom_depth_m=thinnest+1.)
        self.assertEqual(j.refusal_code(lambda: produce(plate(beyond), cols, state, volume, core=beyond)), k.OUTSIDE_ROCK)


class ColumnTests(unittest.TestCase):
    def test_core_across_heated_layers_matches_smooth_profile(self):
        p = plate(shape=(4, 4))
        upper = 15e3+2e3*np.cos(2*np.pi*np.arange(16)/16)
        cols = (np.column_stack([np.full(16, 20e3), upper]), [3000., 2750.], 3e-5, np.array([1100., 800.]),
                np.array([800., 300.]))
        z0 = gpe.columns(DATUM, *cols)["surface_elevation_m"].reshape(p.shape)
        volume = 300.*p.length_x_m*p.length_y_m
        state = p.equilibrium(z0, volume, **water.ARGS)
        straddling = dict(CORE, top_depth_m=10e3, bottom_depth_m=25e3)           # crosses the layer interface
        r = produce(plate(straddling, (4, 4)), cols, state, volume, core=straddling)
        self.assertEqual(r["regime"], j.FLEXURAL)
        tref = DATUM.reference_temperature_k
        h, rho, alpha, tb, tt = cols
        rb = [rho[i]*(1-alpha*(tb[i]-tref)) for i in range(2)]
        rt = [rho[i]*(1-alpha*(tt[i]-tref)) for i in range(2)]
        for i in (0, 5, 11):
            oracle = k.smooth_core_column(DATUM, h[i], rb, rt, rho_w_kg_m3=1000., water_depth_m=r["depth_m"].flat[i],
                                          displacement_m=r["displacement_m"].flat[i], core_top_m=10e3,
                                          core_bottom_m=25e3)
            self.assertLessEqual(abs(oracle["anomaly_j_m2"]-float(r["gpe_anomaly_j_m2"].flat[i])), TOL)
            self.assertAlmostEqual(oracle["column_excess_pa"], float(r["basal_overburden_excess_pa"].flat[i]), delta=1e-3)


class LimitTests(unittest.TestCase):
    def test_dry_and_uniform_limits_admit_a_core(self):
        p = plate()
        cols = crust(pattern(p.shape))
        dry = gpe.columns(DATUM, *cols)
        z0 = dry["surface_elevation_m"].reshape(p.shape)
        r = produce(p, cols, p.equilibrium(z0, 0., **water.ARGS), 0.)
        self.assertEqual((r["regime"], r["no_transfer_limit"]), (j.COMPENSATED, j.ZERO_WATER))
        np.testing.assert_array_equal(r["gpe_anomaly_j_m2"], dry["gpe_anomaly_j_m2"].reshape(p.shape))
        flat = crust(np.zeros(p.shape))
        z_flat = gpe.columns(DATUM, *flat)["surface_elevation_m"].reshape(p.shape)
        volume = 1000.*p.length_x_m*p.length_y_m
        state = p.equilibrium(z_flat, volume, **water.ARGS)
        uniform = produce(p, flat, state, volume)
        self.assertEqual((uniform["regime"], uniform["no_transfer_limit"]), (j.COMPENSATED, j.UNIFORM_LOAD))
        bare = j.water_loaded_gpe(DATUM, *flat, p, state, volume_m3=volume, **water.ARGS)       # no level at all
        np.testing.assert_allclose(uniform["gpe_anomaly_j_m2"], bare["gpe_anomaly_j_m2"], rtol=0, atol=TOL)
        self.assertLessEqual(float(np.ptp(uniform["gpe_anomaly_j_m2"])), TOL)

    def test_zero_rigidity_is_refused_as_a_core_but_joins_without_one(self):
        cols = crust(pattern((16, 16)))
        airy = water.Plate((16, 16), 600e3, 400e3, 0.)
        z0 = gpe.columns(DATUM, *cols)["surface_elevation_m"].reshape(airy.shape)
        volume = 200.*airy.length_x_m*airy.length_y_m
        state = airy.equilibrium(z0, volume, **water.ARGS)
        before = j.fingerprint((cols, CORE, state))
        self.assertEqual(j.refusal_code(lambda: produce(airy, cols, state, volume)), k.NOT_A_CORE)
        self.assertEqual(j.fingerprint((cols, CORE, state)), before)
        r = j.water_loaded_gpe(DATUM, *cols, airy, state, volume_m3=volume, **water.ARGS)
        self.assertEqual((r["regime"], r["no_transfer_limit"]), (j.COMPENSATED, j.ZERO_RIGIDITY))
        for degenerate in (dict(CORE, young_pa=0.), dict(CORE, bottom_depth_m=CORE["top_depth_m"])):
            self.assertEqual(j.refusal_code(lambda: k.elastic_core(degenerate)), k.INVALID_CORE)


class RefusalTests(unittest.TestCase):
    def setUp(self):
        self.p = plate()
        self.cols = crust(pattern(self.p.shape))
        self.z0 = gpe.columns(DATUM, *self.cols)["surface_elevation_m"].reshape(self.p.shape)
        self.volume = 200.*self.p.length_x_m*self.p.length_y_m
        self.state = self.p.equilibrium(self.z0, self.volume, **water.ARGS)

    def code(self, *, core=CORE, p=None, state=None, cols=None, datum=DATUM):
        inputs = (datum, self.cols if cols is None else cols, core, self.p if p is None else p,
                  self.state if state is None else state)
        before = j.fingerprint(inputs)
        code = j.refusal_code(lambda: k.core_loaded_gpe(inputs[0], *inputs[1], *inputs[2:], volume_m3=self.volume,
                                                        **water.ARGS))
        self.assertEqual(before, j.fingerprint(inputs), "a refused call modified its inputs")
        return code

    def other(self, **change):
        return water.Plate(self.p.shape, 600e3, 400e3, **dict(dict(elastic_thickness_m=15e3), **change))

    def test_stiffness_material_and_solver_mismatches(self):
        self.assertIsNone(self.code())                                                 # the admitted reference call
        thinner = self.other(elastic_thickness_m=14e3)
        stale = thinner.equilibrium(self.z0, self.volume, **water.ARGS)
        self.assertEqual(self.code(p=thinner, state=stale), k.MISMATCH)
        self.assertEqual(self.code(p=self.other(young_pa=71e9)), k.MISMATCH)
        self.assertEqual(self.code(p=self.other(poisson=.3)), k.MISMATCH)
        same_d = dict(CORE, bottom_depth_m=17e3, young_pa=70e9*(15/12)**3)            # another material, about the same D
        self.assertEqual(self.code(core=same_d), k.MISMATCH)
        self.assertEqual(self.code(state=stale), j.EQUILIBRIUM)                         # the core's plate, a stale state
        airy_state = self.other(elastic_thickness_m=0.).equilibrium(self.z0, self.volume, **water.ARGS)
        self.assertEqual(self.code(state=airy_state), j.EQUILIBRIUM)
        self.assertEqual(self.code(p=self.other(elastic_thickness_m=0.), state=airy_state), k.NOT_A_CORE)
        self.assertEqual(self.code(p=self.other(rho_m_kg_m3=3250.)), j.MATERIAL)
        self.assertEqual(self.code(p=self.other(gravity_m_s2=9.8)), j.MATERIAL)
        self.assertEqual(self.code(p={"shape": self.p.shape}), j.UNSUPPORTED)
        self.assertEqual(self.code(core=dict(CORE, poisson=-.2)), k.UNSUPPORTED_CORE)

    def test_column_placement_and_datum_refusals(self):
        h = self.cols[0]
        thinnest = float(np.min(h.sum(axis=1)))
        beyond = dict(CORE, top_depth_m=thinnest-15e3+1., bottom_depth_m=thinnest+1.)
        self.assertEqual(self.code(core=beyond, p=plate(beyond)), k.OUTSIDE_ROCK)
        self.assertEqual(self.code(core=dict(CORE, top_depth_m=-100.)), k.OUTSIDE_ROCK)
        self.assertEqual(self.code(core={key: v for key, v in CORE.items() if key != "top_depth_m"}), k.UNPLACED)
        self.assertEqual(self.code(core=[CORE, CORE]), k.UNSUPPORTED_CORE)
        self.assertEqual(self.code(cols=(-h,)+self.cols[1:]), j.COLUMNS)
        self.assertEqual(self.code(cols=(h[:-1],)+self.cols[1:]), j.SHAPE)
        self.assertEqual(self.code(datum=gpe.Datum(DATUM.pressure_pa, DATUM.compensation_elevation_m, 3250.)), j.MATERIAL)


class CaseAndCliTests(unittest.TestCase):
    def test_case_policy_retained_values_and_bound_files(self):
        spec = k.load_case()
        self.assertEqual(spec["policy"], k.POLICY)
        ret = k.retained_inputs(spec)
        self.assertEqual((ret["control_shear_depth_m"], ret["rho_w_kg_m3"]), (7500, 1000.))
        for name in k.NEW_FILES+k.RETAINED+tuple(k.ACCEPTED_RECEIPTS):
            self.assertTrue((k.ROOT/name).is_file(), name)
        match = k.evidence_match(k.bindings())
        self.assertTrue(all(match["imported"].values()))
        self.assertEqual(set(match["retained"]), set(k.RETAINED))
        drifted = dict(spec, retained={"water_gpe_case": dict(spec["retained"]["water_gpe_case"],
                                                              control_shear_depth_m=7000)})
        with self.assertRaises(ValueError):
            k.retained_inputs(drifted)
        core = k.elastic_core(spec["controls"]["core"])
        self.assertEqual(k.core_plate(core, ret["datum"], (32, 32), 600e3, 400e3, rho_w_kg_m3=ret["rho_w_kg_m3"]),
                         water.fixture(32, ret["water"])[0])

    def test_bounded_controls_pass_without_writing_a_receipt(self):
        spec = k.load_case()
        ret = k.retained_inputs(spec)
        for name, control in k.CONTROLS:
            if name == "timing":
                continue
            with self.subTest(control=name):
                data = control(spec, ret)
                self.assertTrue(data["passed"], {key: value for key, value in data["checks"].items() if not value})

    def test_cli_refuses_to_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            existing = Path(folder)/"receipt.json"
            existing.write_text("{}", encoding="utf-8")
            argv = ["check_i01_elastic_core.py", "--output", str(existing)]
            with mock.patch.object(sys, "argv", argv), self.assertRaises(FileExistsError):
                k.main()
            self.assertEqual(existing.read_text(encoding="utf-8"), "{}")


if __name__ == "__main__":
    unittest.main()
