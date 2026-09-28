"""Focused MC-07 tests: dry parity, structural compensated limits, the conditional finite-rigidity join against
closed forms and an independent pressure quadrature, a tiny support that no amount of uniform water may hide,
datum/units/sign, layer splitting, reference mass, the traction operator and atomic refusals, including negative
depth. The bounded controls are called directly; no receipt is written and the CLI is exercised only for
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
import check_i01_water_gpe as j

gpe, water = j.gpe, j.water
DATUM = gpe.Datum(6474600000., -200e3)
RHO_C, H0 = 2800., 35e3
F = 1-RHO_C/3300.
SHEAR = {"depth_below_bed_m": 7500., "basis": "test assumption: homogeneous core in the uppermost 15 km"}
TOL = j.quadrature_tolerance(DATUM)


def plate(te=15e3, shape=(16, 16)):
    return water.Plate(shape, 600e3, 400e3, te)


def crust(surface):
    """One constant-density crust layer per cell whose dry surface is Z_ref + F*H0 + surface."""
    return ((H0+np.asarray(surface, dtype=float)/F).reshape(-1, 1), RHO_C, 0., 1000., 1000.)


def pattern(shape):
    y, x = np.indices(shape)
    return (500*np.cos(2*np.pi*x/shape[1])+300*np.cos(2*np.pi*y/shape[0])
            + 80*np.sin(2*np.pi*(x/shape[1]+y/shape[0])))


def solve(p, cols, mean_depth, datum=DATUM):
    z0 = gpe.columns(datum, *cols)["surface_elevation_m"].reshape(p.shape)
    volume = mean_depth*p.length_x_m*p.length_y_m
    return z0, volume, p.equilibrium(z0, volume, **water.ARGS)


def join(p, cols, state, volume, shear=None, datum=DATUM):
    return j.water_loaded_gpe(datum, *cols, p, state, volume_m3=volume, shear_level=shear, **water.ARGS)


def quad(datum, h, rho, d, w, split):
    """Independent pressure-profile oracle for one constant-density crust column."""
    return j.independent_column_anomaly(datum, [h], [rho], [rho], rho_w_kg_m3=1000., water_depth_m=d,
                                        displacement_m=w, split_depth_below_bed_m=split)


class CompensatedTests(unittest.TestCase):
    def test_zero_water_is_bitwise_dry_parity(self):
        p = plate()
        cols = crust(pattern(p.shape))
        dry = gpe.columns(DATUM, *cols)
        z0 = dry["surface_elevation_m"].reshape(p.shape)
        r = join(p, cols, p.equilibrium(z0, 0., **water.ARGS), 0.)
        self.assertEqual((r["regime"], r["no_transfer_limit"]), (j.COMPENSATED, j.ZERO_WATER))
        self.assertIsNone(r["sea_level_m"])
        self.assertFalse(r["finite_rigidity_closure"])
        np.testing.assert_array_equal(r["gpe_anomaly_j_m2"], dry["gpe_anomaly_j_m2"].reshape(p.shape))
        np.testing.assert_array_equal(j.planar_traction(r["gpe_anomaly_j_m2"], plate=p, reduction=.7),
                                      j.planar_traction(dry["gpe_anomaly_j_m2"].reshape(p.shape), plate=p, reduction=.7))
        np.testing.assert_array_equal(r["reference_rock_mass_kg_m2"], dry["reference_rock_mass_kg_m2"].reshape(p.shape))
        np.testing.assert_array_equal(r["water_mass_kg_m2"], 0.)

    def test_uniform_load_is_compensated_for_any_rigidity(self):
        cols, hw, q, g = crust(np.zeros((16, 16))), 1000., 1000/3300, 9.81
        runs = []
        for te in (15e3, 0.):
            p = plate(te)
            _, volume, state = solve(p, cols, hw)
            runs.append((p, state, volume, join(p, cols, state, volume)))
        (p, state, volume, stiff), (_, _, _, airy) = runs
        self.assertEqual((stiff["regime"], stiff["no_transfer_limit"]), (j.COMPENSATED, j.UNIFORM_LOAD))
        self.assertEqual((airy["regime"], airy["no_transfer_limit"]), (j.COMPENSATED, j.ZERO_RIGIDITY))
        for r in (stiff, airy):
            self.assertIsNone(r["shear_level"])
        # A declared level is still accepted where no load is transferred, and is immaterial there.
        declared = join(p, cols, state, volume, SHEAR)
        self.assertEqual((declared["regime"], declared["shear_level"]), (j.COMPENSATED, SHEAR))
        np.testing.assert_allclose(declared["gpe_anomaly_j_m2"], stiff["gpe_anomaly_j_m2"], atol=TOL, rtol=0)
        # Dry restoring force: q*hw, not the double-feedback rho_w*hw/(rho_m-rho_w).
        np.testing.assert_allclose(stiff["displacement_m"], q*hw, atol=1e-7, rtol=0)
        np.testing.assert_allclose(stiff["gpe_anomaly_j_m2"], airy["gpe_anomaly_j_m2"], atol=TOL, rtol=0)
        layered = gpe.columns(DATUM, [[H0, hw]], [RHO_C, 1000.], 0., 1000., 1000.)   # unchanged dry helper
        np.testing.assert_allclose(stiff["gpe_anomaly_j_m2"], layered["gpe_anomaly_j_m2"][0], atol=TOL, rtol=0)
        self.assertAlmostEqual(layered["surface_elevation_m"][0], stiff["sea_level_m"], delta=1e-6)
        closed = .5*g*RHO_C*F*H0*H0+g*1000*hw*(F*H0-q*hw/2+hw/2)    # delta U0 + g rho_w d (e0 - w/2 + d/2)
        np.testing.assert_allclose(stiff["gpe_anomaly_j_m2"], closed, atol=TOL, rtol=0)
        self.assertLess(float(np.max(np.abs(j.planar_traction(stiff["gpe_anomaly_j_m2"], plate=plate(), reduction=1.)))),
                        1e-6)

    def test_zero_rigidity_partly_wet_matches_unchanged_dry_helper(self):
        p = plate(0.)
        cols = crust(pattern(p.shape))
        _, volume, state = solve(p, cols, 200.)
        r = join(p, cols, state, volume)
        self.assertEqual((r["regime"], r["no_transfer_limit"]), (j.COMPENSATED, j.ZERO_RIGIDITY))
        d = r["depth_m"].ravel()
        wet = d > 0
        self.assertTrue(0 < wet.mean() < 1)
        h = cols[0][:, 0]
        direct = gpe.columns(DATUM, np.column_stack((h[wet], d[wet])), [RHO_C, 1000.], 0., 1000., 1000.)
        expected, top = j.water_layer_route(DATUM, cols, r["depth_m"], 1000.)
        np.testing.assert_array_equal(expected[wet], direct["gpe_anomaly_j_m2"])
        excess = float(np.max(np.abs(r["basal_overburden_excess_pa"])))
        np.testing.assert_allclose(r["gpe_anomaly_j_m2"].ravel(), expected, atol=excess*8000.+TOL, rtol=0)
        np.testing.assert_allclose(r["top_surface_m"].ravel(), top, atol=excess/(9.81*3300)+1e-6, rtol=0)


class FiniteRigidityTests(unittest.TestCase):
    def setUp(self):
        self.p = plate()
        y, x = np.indices(self.p.shape)
        self.cols = crust(10*np.cos(2*np.pi*(2*x/16+y/16)))
        self.z0 = gpe.columns(DATUM, *self.cols)["surface_elevation_m"].reshape(self.p.shape)
        self.volume = 1000.*self.p.length_x_m*self.p.length_y_m
        self.exact = j.fourier_mode_state(self.p, self.z0, mode=(2, 1), mean_water_m=1000., bed_amplitude_m=10.,
                                          surface_mean_m=j.reference_top(DATUM)+F*H0)
        self.h = self.cols[0][:, 0]
        self.w, self.d = self.exact["displacement_m"].ravel(), self.exact["depth_m"].ravel()
        self.b = self.exact["basal_overburden_excess_pa"].ravel()

    def test_oblique_mode_closed_form_and_independent_quadrature(self):
        solved = self.p.equilibrium(self.z0, self.volume, **water.ARGS)
        np.testing.assert_allclose(solved["displacement_m"], self.exact["displacement_m"], atol=2e-6, rtol=0)
        with self.assertRaises(j.Refusal) as caught:
            join(self.p, self.cols, solved, self.volume)
        self.assertEqual(caught.exception.code, j.UNDECLARED)
        r = join(self.p, self.cols, self.exact, self.volume, SHEAR)
        self.assertEqual(r["regime"], j.FLEXURAL)
        self.assertFalse(r["finite_rigidity_closure"])
        self.assertEqual(r["shear_level"], SHEAR)
        np.testing.assert_allclose(r["basal_overburden_excess_pa"].ravel(), self.b, atol=1e-5, rtol=0)
        np.testing.assert_allclose(r["flexural_support_pa"].ravel(), self.b, atol=1., rtol=0)
        for i in range(0, 256, 5):
            self.assertLessEqual(abs(float(r["gpe_anomaly_j_m2"].flat[i])-quad(DATUM, self.h[i], RHO_C, self.d[i],
                                                                               self.w[i], 7500.)), TOL)
        other = join(self.p, self.cols, solved, self.volume, SHEAR)
        bound = j.perturbation_bound(self.p, r, 7500., 2e-6, 4e-6)+TOL
        self.assertLessEqual(float(np.max(np.abs(other["gpe_anomaly_j_m2"]-r["gpe_anomaly_j_m2"]))), bound)

    def test_level_sensitivity_and_datum_extension(self):
        r = join(self.p, self.cols, self.exact, self.volume, SHEAR)
        deeper = j.deepen(DATUM, 1e5)
        np.testing.assert_array_equal(join(self.p, self.cols, self.exact, self.volume, SHEAR, datum=deeper)
                                      ["gpe_anomaly_j_m2"], r["gpe_anomaly_j_m2"])
        both = TOL+j.quadrature_tolerance(deeper)
        for i in (0, 37, 101, 200):
            at, at2 = (quad(DATUM, self.h[i], RHO_C, self.d[i], self.w[i], c) for c in (7500., 17500.))
            self.assertAlmostEqual(at2-at, 1e4*self.b[i], delta=2*TOL)                  # dV/dc = B, independently
            self.assertAlmostEqual(quad(deeper, self.h[i], RHO_C, self.d[i], self.w[i], 7500.), at, delta=both)
            naive = quad(DATUM, self.h[i], RHO_C, self.d[i], self.w[i], None)
            naive_deep = quad(deeper, self.h[i], RHO_C, self.d[i], self.w[i], None)
            self.assertAlmostEqual(naive_deep-naive, 1e5*self.b[i], delta=both)          # naive anomaly delta U_o is not
        self.assertGreater(1e5*float(self.b.max()-self.b.min()), 1000*both)
        r2 = join(self.p, self.cols, self.exact, self.volume, dict(SHEAR, depth_below_bed_m=17500.))
        np.testing.assert_allclose(r2["gpe_anomaly_j_m2"]-r["gpe_anomaly_j_m2"], 1e4*r["basal_overburden_excess_pa"],
                                   atol=1e-2, rtol=0)

    def test_vertical_translation_and_airy_rebuild_contrast(self):
        solved = self.p.equilibrium(self.z0, self.volume, **water.ARGS)
        r = join(self.p, self.cols, solved, self.volume, SHEAR)
        moved = j.translate(DATUM, 1e5)
        z0m = gpe.columns(moved, *self.cols)["surface_elevation_m"].reshape(self.p.shape)
        np.testing.assert_allclose(z0m, self.z0+1e5, atol=1e-9, rtol=0)
        rm = join(self.p, self.cols, self.p.equilibrium(z0m, self.volume, **water.ARGS), self.volume, SHEAR, datum=moved)
        bound = j.perturbation_bound(self.p, r, 7500., 1e-7, 2e-7)+TOL
        self.assertLessEqual(float(np.max(np.abs(rm["gpe_anomaly_j_m2"]-r["gpe_anomaly_j_m2"]))), bound)
        # Re-floating the flexed state through the dry helper is NOT this state: a large, discriminating contrast.
        rebuilt, _ = j.water_layer_route(DATUM, self.cols, solved["depth_m"], 1000.)
        self.assertGreater(float(np.max(np.abs(rebuilt-r["gpe_anomaly_j_m2"].ravel()))), 1000*TOL)


class SmallSupportTests(unittest.TestCase):
    """The reviewed reproducer: a genuine but tiny nonuniform support is flexural, whatever the uniform water."""

    @staticmethod
    def mode(p, mean_water, amplitude=1e-4):
        """The Fourier fixture's (2,1) mode at a 0.1 mm bed amplitude, with its exact fully wet state."""
        y, x = np.indices(p.shape)
        cols = crust(amplitude*np.cos(2*np.pi*(2*x/16+y/16)))
        z0 = gpe.columns(DATUM, *cols)["surface_elevation_m"].reshape(p.shape)
        exact = j.fourier_mode_state(p, z0, mode=(2, 1), mean_water_m=mean_water, bed_amplitude_m=amplitude,
                                     surface_mean_m=j.reference_top(DATUM)+F*H0)
        return cols, exact, mean_water*p.length_x_m*p.length_y_m

    def refused(self, p, cols, exact, volume):
        with self.assertRaises(j.Refusal) as caught:
            join(p, cols, exact, volume)
        return caught.exception.code

    def test_small_amplitude_mode_needs_a_declared_level(self):
        p = plate()
        cols, exact, volume = self.mode(p, 1000.)
        self.assertEqual(self.refused(p, cols, exact, volume), j.UNDECLARED)
        r = join(p, cols, exact, volume, SHEAR)
        self.assertEqual((r["regime"], r["no_transfer_limit"]), (j.FLEXURAL, None))
        # The retained force tolerance, misused as a classifier, called this compensated (review: about 2.15e-8) ...
        self.assertLess(r["flexural_support_relative"], j.POLICY["force_relative_tolerance"])
        # ... yet the level term it dropped exceeds the fixed oracle tolerance (review: about 2238 against 647 J/m2).
        self.assertGreater(float(np.max(np.abs(7500.*r["basal_overburden_excess_pa"]))), TOL)
        h, d, w = cols[0][:, 0], exact["depth_m"].ravel(), exact["displacement_m"].ravel()
        for i in range(0, 256, 5):
            self.assertLessEqual(abs(float(r["gpe_anomaly_j_m2"].flat[i])-quad(DATUM, h[i], RHO_C, d[i], w[i], 7500.)),
                                 TOL)
        # The same nonuniform bed on a zero-rigidity plate is the genuine Airy limit: compensated without a level.
        airy = plate(0.)
        r0 = join(airy, *self.mode(airy, 1000.))
        self.assertEqual((r0["regime"], r0["no_transfer_limit"]), (j.COMPENSATED, j.ZERO_RIGIDITY))

    def test_uniform_water_cannot_hide_the_same_nonuniform_support(self):
        p, ratios, reference = plate(), [], None
        for mean_water in (100., 1000., 4000.):
            cols, exact, volume = self.mode(p, mean_water)
            with self.subTest(mean_water=mean_water):
                if reference is None:
                    reference = exact["basal_overburden_excess_pa"]
                np.testing.assert_array_equal(exact["basal_overburden_excess_pa"], reference)   # the same closed-form B
                self.assertEqual(self.refused(p, cols, exact, volume), j.UNDECLARED)
                r = join(p, cols, exact, volume, SHEAR)
                self.assertEqual(r["regime"], j.FLEXURAL)
                np.testing.assert_allclose(r["basal_overburden_excess_pa"], reference, rtol=0,
                                           atol=1e-12*1000*9.81*float(np.max(exact["depth_m"])))
                ratios.append(r["flexural_support_relative"])
        # Added uniform water shrinks the L2 support-to-load ratio across the retained tolerance, so a residual-norm
        # classification would flip from flexural to compensated here; the structural one cannot.
        self.assertTrue(ratios[0] > j.POLICY["force_relative_tolerance"] > ratios[1] > ratios[2], ratios)


class ColumnTests(unittest.TestCase):
    @staticmethod
    def thermal(split, warmer=0.):
        upper = 15e3+2e3*np.cos(2*np.pi*np.arange(16)/16)
        lower = [np.full(16, 10e3), np.full(16, 10e3)] if split else [np.full(16, 20e3)]
        bottom = ([1100., 950.] if split else [1100.])+[800.]
        top = ([950., 800.] if split else [800.])+[300.]
        rho = ([3000., 3000.] if split else [3000.])+[2750.]
        return (np.column_stack(lower+[upper]), rho, 3e-5, np.array(bottom)+warmer, np.array(top)+warmer)

    def test_layer_split_heating_reference_mass_and_quadrature(self):
        p = plate(shape=(4, 4))
        whole, split = self.thermal(False), self.thermal(True)
        _, volume, state = solve(p, whole, 300.)
        r = join(p, whole, state, volume, SHEAR)
        r_split = join(p, split, state, volume, SHEAR)
        for key in ("gpe_anomaly_j_m2", "basal_overburden_excess_pa", "reference_rock_mass_kg_m2",
                    "effective_rock_load_kg_m2", "surface_above_reference_m"):
            np.testing.assert_allclose(r_split[key], r[key], rtol=1e-12, atol=1e-3)
        tref = DATUM.reference_temperature_k
        h, rho, alpha, tb, tt = whole
        rb = [rho[k]*(1-alpha*(tb[k]-tref)) for k in range(2)]
        rt = [rho[k]*(1-alpha*(tt[k]-tref)) for k in range(2)]
        for i in (0, 5, 11):
            oracle = j.independent_column_anomaly(DATUM, h[i], rb, rt, rho_w_kg_m3=1000.,
                                                  water_depth_m=r["depth_m"].flat[i],
                                                  displacement_m=r["displacement_m"].flat[i],
                                                  split_depth_below_bed_m=7500.)
            self.assertAlmostEqual(float(r["gpe_anomaly_j_m2"].flat[i]), oracle, delta=TOL)
        warm = self.thermal(False, 100.)
        _, _, warm_state = solve(p, warm, 300.)
        r_warm = join(p, warm, warm_state, volume, SHEAR)
        np.testing.assert_array_equal(r_warm["reference_rock_mass_kg_m2"], r["reference_rock_mass_kg_m2"])
        self.assertTrue(np.all(r_warm["effective_rock_load_kg_m2"] < r["effective_rock_load_kg_m2"]))
        self.assertTrue(np.all(r_warm["dry_surface_m"] > r["dry_surface_m"]))
        self.assertFalse(np.allclose(r_warm["gpe_anomaly_j_m2"], r["gpe_anomaly_j_m2"]))
        cell = p.length_x_m*p.length_y_m/16
        self.assertAlmostEqual(float(np.sum(r["water_mass_kg_m2"]))*cell/(1000*volume), 1., places=10)

    def test_quadrature_oracle_reproduces_retained_dry_anomaly(self):
        h, rho, alpha, tb, tt = [20e3, 15e3], [3000., 2750.], 3e-5, [1100., 800.], [800., 300.]
        dry = gpe.columns(DATUM, [h], [rho], alpha, [tb], [tt])
        tref = DATUM.reference_temperature_k
        rb = [r*(1-alpha*(t-tref)) for r, t in zip(rho, tb)]
        rt = [r*(1-alpha*(t-tref)) for r, t in zip(rho, tt)]
        for split in (None, 12e3):
            got = j.independent_column_anomaly(DATUM, h, rb, rt, rho_w_kg_m3=1000., water_depth_m=0.,
                                               displacement_m=0., split_depth_below_bed_m=split)
            self.assertAlmostEqual(got, float(dry["gpe_anomaly_j_m2"][0]), delta=TOL)


class TractionTests(unittest.TestCase):
    def test_mode_derivative_sign_units_reduction_and_zero_net_force(self):
        p = plate(shape=(16, 8))
        y, x = np.indices(p.shape)
        dx, dy = p.length_x_m/8, p.length_y_m/16
        kx, ky = 2*np.pi*3/p.length_x_m, 2*np.pi*2/p.length_y_m
        theta = kx*x*dx+ky*y*dy
        v = 1e9*np.cos(theta)                                                     # J/m2
        t = j.planar_traction(v, plate=p, reduction=.6)                            # Pa
        # -gamma grad V: just past a potential maximum (sin theta > 0) the push is towards increasing x and y.
        np.testing.assert_allclose(t[..., 0], .6e9*np.sin(theta)*np.sin(kx*dx)/dx, rtol=0, atol=1e-12*.6e9*kx)
        np.testing.assert_allclose(t[..., 1], .6e9*np.sin(theta)*np.sin(ky*dy)/dy, rtol=0, atol=1e-12*.6e9*ky)
        np.testing.assert_allclose(j.planar_traction(v, plate=p, reduction=1.2), 2*t, rtol=1e-15, atol=0)
        self.assertLess(float(np.max(np.abs(t.sum(axis=(0, 1))))), 1e-9*float(np.max(np.abs(t))))
        np.testing.assert_array_equal(j.planar_traction(np.full(p.shape, 7e14), plate=p, reduction=1.), 0.)

    def test_invalid_traction_inputs(self):
        p = plate(shape=(4, 4))
        for field, gamma in ((np.zeros((4, 5)), 1.), (np.full((4, 4), np.nan), 1.),
                             (np.zeros((4, 4)), 0.), (np.zeros((4, 4)), True)):
            with self.subTest(shape=field.shape, gamma=gamma), self.assertRaises(j.Refusal):
                j.planar_traction(field, plate=p, reduction=gamma)
        with self.assertRaises(j.Refusal):
            j.planar_traction(np.zeros((4, 4)), plate={"shape": (4, 4)}, reduction=1.)


class RefusalTests(unittest.TestCase):
    def setUp(self):
        self.p = plate()
        self.cols = crust(pattern(self.p.shape))
        self.z0, self.volume, self.state = solve(self.p, self.cols, 200.)
        self.area = self.p.length_x_m*self.p.length_y_m

    def restate(self, displacement, volume=None):
        loaded = self.z0-displacement
        level, depth, _, _ = water._fill(loaded, (self.volume if volume is None else volume)/self.area)
        return dict(displacement_m=displacement, bed_m=loaded, depth_m=depth, sea_level_m=level)

    def code(self, state, *, volume=None, shear=SHEAR, cols=None, p=None, datum=DATUM, **contract):
        cols = self.cols if cols is None else cols
        inputs = (state, cols, shear)
        before = j.fingerprint(inputs)
        code = j.refusal_code(lambda: j.water_loaded_gpe(
            datum, *cols, self.p if p is None else p, state, volume_m3=self.volume if volume is None else volume,
            shear_level=shear, **dict(water.ARGS, **contract)))
        self.assertEqual(before, j.fingerprint(inputs), "a refused call modified its inputs")
        return code

    def test_double_counting_and_stale_deflections_refused_atomically(self):
        s, q = self.state, self.p.density_ratio
        self.assertEqual(self.code(dict(s, depth_m=2*s["depth_m"])), j.LOAD)
        self.assertEqual(self.code(self.restate(s["displacement_m"]+q*s["depth_m"])), j.EQUILIBRIUM)
        twice = self.p.equilibrium(self.z0, 2*self.volume, **water.ARGS)
        self.assertEqual(self.code(self.restate(twice["displacement_m"]-s["displacement_m"], 2*self.volume),
                                   volume=2*self.volume), j.EQUILIBRIUM)
        self.assertEqual(self.code(plate(0.).equilibrium(self.z0, self.volume, **water.ARGS)), j.EQUILIBRIUM)
        self.assertEqual(self.code(self.restate(np.zeros(self.p.shape))), j.EQUILIBRIUM)
        flat = crust(np.zeros(self.p.shape))
        z_flat = gpe.columns(DATUM, *flat)["surface_elevation_m"].reshape(self.p.shape)
        feedback = np.full(self.p.shape, 1000*200./(3300-1000))                    # (rho_m - rho_w) g with full load
        loaded = z_flat-feedback
        level, depth, _, _ = water._fill(loaded, 200.)
        forged = dict(displacement_m=feedback, bed_m=loaded, depth_m=depth, sea_level_m=level)
        self.assertEqual(self.code(forged, cols=flat), j.EQUILIBRIUM)
        self.assertEqual(join(self.p, self.cols, s, self.volume, SHEAR)["regime"], j.FLEXURAL)

    def test_reference_material_shape_and_forged_inputs(self):
        s, h = self.state, self.cols[0]
        self.assertEqual(self.code(self.p.equilibrium(self.z0+100., self.volume, **water.ARGS)), j.REFERENCE)
        self.assertEqual(self.code(s, cols=(h.reshape(16, 16).T.reshape(-1, 1),)+self.cols[1:]), j.REFERENCE)
        self.assertEqual(self.code(s, p=water.Plate((16, 16), 600e3, 400e3, 15e3, rho_m_kg_m3=3250.)), j.MATERIAL)
        self.assertEqual(self.code(s, p=water.Plate((16, 16), 600e3, 400e3, 15e3, gravity_m_s2=9.8)), j.MATERIAL)
        self.assertEqual(self.code(s, cols=(h[:-1],)+self.cols[1:]), j.SHAPE)
        self.assertEqual(self.code({"status": j.PASS, "law": "atlas.fixed-datum-support-water.v1"}), j.SHAPE)
        forged = {"status": j.PASS, "displacement_m": np.zeros(self.p.shape), "bed_m": self.z0.copy(),
                  "depth_m": np.zeros(self.p.shape), "sea_level_m": None}
        self.assertEqual(self.code(forged), j.LOAD)
        self.assertEqual(self.code(s, geometry="sphere"), j.UNSUPPORTED)
        self.assertEqual(self.code(s, connectivity="isolated_lakes"), j.UNSUPPORTED)
        self.assertEqual(self.code(s, p={"shape": (16, 16)}), j.UNSUPPORTED)
        bad = s["depth_m"].copy()
        bad[3, 3] = np.inf
        self.assertEqual(self.code(dict(s, depth_m=bad)), j.NONFINITE)
        for volume, expected in ((0., j.LOAD), (-1., j.INVALID), (True, j.INVALID)):
            self.assertEqual(self.code(s, volume=volume), expected)
        self.assertEqual(self.code(s, cols=(-h,)+self.cols[1:]), j.COLUMNS)

    def test_shear_level_datum_and_water_in_rock_guards(self):
        s, h = self.state, self.cols[0]
        self.assertEqual(self.code(s, shear=None), j.UNDECLARED)
        for depth in (0., float(np.min(h)), 1e9):
            self.assertEqual(self.code(s, shear=dict(SHEAR, depth_below_bed_m=depth)), j.OUTSIDE)
        for declaration in (dict(SHEAR, basis=""), dict(SHEAR, depth_below_bed_m=float("nan")),
                            dict(SHEAR, depth_below_bed_m=True), {"depth_below_bed_m": 7500.}, 7500.):
            self.assertEqual(self.code(s, shear=declaration), j.INVALID)
        wet_rock = (np.hstack((h, np.full((len(h), 1), 50.))), [RHO_C, 1000.], 0., 1000., 1000.)
        self.assertEqual(self.code(s, cols=wet_rock), j.WATER_IN_ROCK)
        flat = crust(np.zeros(self.p.shape))
        shallow = gpe.Datum(9.81*(RHO_C*H0+3300*10.), -200e3)                       # 10 m dry mantle fill
        z_shallow = gpe.columns(shallow, *flat)["surface_elevation_m"].reshape(self.p.shape)
        state = self.p.equilibrium(z_shallow, self.volume, **water.ARGS)
        self.assertEqual(self.code(state, cols=flat, datum=shallow), j.BELOW)

    def test_negative_depth_at_a_dry_cell_refused_however_small(self):
        s = self.state
        dry = np.flatnonzero(s["depth_m"] == 0)
        self.assertGreater(dry.size, 0)
        for value in (-1e-7, -np.finfo(float).tiny, -5e-324):   # inside every geometric and force tolerance
            depth = s["depth_m"].copy()
            depth.flat[dry[0]] = value
            with self.subTest(depth=value):
                self.assertEqual(self.code(dict(s, depth_m=depth)), j.NEGATIVE_WATER)
                self.assertEqual(self.code(dict(s, depth_m=depth), shear=None), j.NEGATIVE_WATER)   # before any account
        self.assertEqual(float(s["depth_m"].flat[dry[0]]), 0.)
        signed = s["depth_m"].copy()
        signed.flat[dry[0]] = -0.                                   # a signed zero is zero water, not negative water
        np.testing.assert_array_equal(join(self.p, self.cols, dict(s, depth_m=signed), self.volume, SHEAR)["gpe_anomaly_j_m2"],
                                      join(self.p, self.cols, s, self.volume, SHEAR)["gpe_anomaly_j_m2"])


class CaseAndCliTests(unittest.TestCase):
    def test_case_policy_retained_values_and_bound_files(self):
        spec = j.load_case()
        self.assertEqual(spec["policy"], j.POLICY)
        ret = j.retained_inputs(spec)
        self.assertEqual(ret["datum"].mantle_density_kg_m3, water.Plate((4, 4), 1., 1., 1.).rho_m_kg_m3)
        self.assertEqual(ret["datum"].gravity_m_s2, water.Plate((4, 4), 1., 1., 1.).gravity_m_s2)
        for name in j.NEW_FILES+j.RETAINED+tuple(j.ACCEPTED_RECEIPTS):
            self.assertTrue((j.ROOT/name).is_file(), name)
        match = j.evidence_match(j.bindings())
        self.assertTrue(all(match["imported"].values()))
        self.assertEqual(set(match["retained"]), set(j.RETAINED))
        drifted = dict(spec, retained=dict(spec["retained"], gpe_case=dict(spec["retained"]["gpe_case"], reduction=2)))
        with self.assertRaises(ValueError):
            j.retained_inputs(drifted)

    def test_bounded_controls_pass_without_writing_a_receipt(self):
        spec = j.load_case()
        ret = j.retained_inputs(spec)
        for name, control in j.CONTROLS:
            if name == "timing":
                continue
            with self.subTest(control=name):
                data = control(spec, ret)
                self.assertTrue(data["passed"], {k: v for k, v in data["checks"].items() if not v})

    def test_cli_refuses_to_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            existing = Path(folder)/"receipt.json"
            existing.write_text("{}", encoding="utf-8")
            argv = ["check_i01_water_gpe.py", "--output", str(existing)]
            with mock.patch.object(sys, "argv", argv), self.assertRaises(FileExistsError):
                j.main()
            self.assertEqual(existing.read_text(encoding="utf-8"), "{}")


if __name__ == "__main__":
    unittest.main()
