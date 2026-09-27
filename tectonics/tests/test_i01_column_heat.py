"""Focused guards for the I01 layered-column heat coupling; no native import.
SPDX-License-Identifier: AGPL-3.0-only
"""
import copy
import dataclasses
import math
from pathlib import Path
import sys
import unittest

import numpy as np
from threadpoolctl import threadpool_limits

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"tools"))
import check_i01_column_heat as h

SPEC, WEAK = h.load_case()
LAW = h.weakening.law_of(WEAK)
RATE = WEAK["campaign"]["rate_s"]
BOUND = SPEC["representation"]["max_axial_strain"]


class Base(unittest.TestCase):
    def setUp(self):
        self.lease = threadpool_limits(limits=1, user_api="blas")
        self.addCleanup(self.lease.restore_original_limits)
        self.base, self.thermal, self.layers = h.setup(SPEC, WEAK, order=8)
        self.kappa0 = h.weakening.initial_history(self.base, WEAK)

    def run_heat(self, steps, strain, **kw):
        kw.setdefault("fractions", (1., 1.))
        base, thermal = kw.pop("base", self.base), kw.pop("thermal", self.thermal)
        return h.evolve_heat(base, thermal, LAW, kw.pop("kappa0", self.kappa0), rate=kw.pop("rate", RATE),
                             duration_s=strain/kw.pop("rate_for_time", RATE), steps=steps, strain_bound=BOUND,
                             temperature_step_k=5., policy=SPEC["policy"], **kw)


class ThermalTests(Base):
    def test_phi_functions_limits_and_branch_continuity(self):
        e, p1, p2, p3 = h.phi_functions(np.array([0., -1+1e-12, -1-1e-12, -1e7]))
        self.assertEqual((p1[0], p2[0]), (1., .5))
        self.assertAlmostEqual(p3[0], 1/6, places=15)
        for p in (p1, p2, p3):
            self.assertLess(abs(p[1]-p[2])/abs(p[1]), 1e-11)
        self.assertAlmostEqual(p1[3]*1e7, 1., places=6)
        self.assertEqual(e[3], 0.)

    def test_geometry_and_interface_resistance(self):
        lay, dep, wt = h.geometry([l["thickness_m"] for l in self.layers], 8)
        np.testing.assert_array_equal(dep, self.base.depth_m)
        np.testing.assert_array_equal(wt, self.base.weight)
        props = [dict(name="a", conductivity_w_m_k=2., heat_capacity_j_kg_k=1e3, radiogenic_w_m3=0.),
                 dict(name="b", conductivity_w_m_k=5., heat_capacity_j_kg_k=1e3, radiogenic_w_m3=0.)]
        lay, dep, wt = h.geometry([1000., 3000.], 2)
        th = h.prepare_thermal(lay, dep, wt, [1000., 3000.], props, [3000., 3000.],
                               dict(top=dict(type="temperature", value_k=300.), bottom=dict(type="insulated")))
        g = th.conductance[1]                                     # across the 1000 m interface
        self.assertAlmostEqual(g, 1/((1000.-dep[1])/2.+(dep[2]-1000.)/5.), places=12)
        self.assertEqual(th.boundary_conductance[1], 0.)
        np.testing.assert_allclose(th.steady_k, 300., rtol=0, atol=1e-12)

    def test_steady_geotherm_reproduces_cookbook(self):
        thick = [l["thickness_m"] for l in WEAK["layers"]]
        ref = h.layered_steady(thick, SPEC["thermal_layers"], SPEC["boundaries"])
        self.assertAlmostEqual(ref["surface_flow"], .055, places=15)
        np.testing.assert_allclose(ref["interface_temperature"][:2], [633., 893.], rtol=0, atol=1e-9)
        errors = []
        for q in (16, 32):
            lay, dep, wt = h.geometry(thick, q)
            th = h.prepare_thermal(lay, dep, wt, thick, SPEC["thermal_layers"],
                                   [l["density_kg_m3"] for l in WEAK["layers"]], SPEC["boundaries"])
            errors.append(max(abs(t-ref["temperature"](z, int(li))) for t, z, li in zip(th.steady_k, dep, lay)))
            surface, internal, base = th.upward_flows(th.steady_k)
            self.assertLess(abs(surface-.055), 1e-12)
            self.assertLess(abs(base-.03), 1e-12)
        self.assertTrue(3.5 < errors[0]/errors[1] < 4.5)

    def test_insulated_uniform_source_exact_and_zero_source_bitwise(self):
        lay, dep, wt = h.geometry([1e4], 8)
        props = [dict(name="u", conductivity_w_m_k=2.5, heat_capacity_j_kg_k=750., radiogenic_w_m3=0.)]
        th = h.prepare_thermal(lay, dep, wt, [1e4], props, [2700.],
                               dict(top=dict(type="insulated"), bottom=dict(type="insulated")), reference_temperature=600.)
        prop = h.prepare_propagator(th, 1e12)
        theta = np.zeros(8)
        for _ in range(3):
            theta, _ = h.conduct(prop, theta, wt*1e-6, wt*1e-6)
        np.testing.assert_allclose(theta, 3e-6*1e12/(2700*750.), rtol=1e-12)
        new, integral = h.conduct(prop, np.zeros(8), np.zeros(8), np.zeros(8))
        self.assertFalse(np.any(new) or np.any(integral))

    def test_two_layer_eigenmode_and_energy_identity(self):
        em = SPEC["campaign"]["eigenmode"]
        (h1, h2), (k1, k2) = em["thickness_m"], em["conductivity_w_m_k"]
        c1, c2 = (d*c for d, c in zip(em["density_kg_m3"], em["heat_capacity_j_kg_k"]))
        mu, mode = h.two_layer_mode(h1, h2, k1, k2, c1, c2)
        props = [dict(name=n, conductivity_w_m_k=k, heat_capacity_j_kg_k=c, radiogenic_w_m3=0.)
                 for n, k, c in zip("ab", em["conductivity_w_m_k"], em["heat_capacity_j_kg_k"])]
        bc = dict(top=dict(type="temperature", value_k=273.), bottom=dict(type="temperature", value_k=273.))
        errors = []
        for q in (8, 16):
            lay, dep, wt = h.geometry([h1, h2], q)
            th = h.prepare_thermal(lay, dep, wt, [h1, h2], props, em["density_kg_m3"], bc)
            prop = h.prepare_propagator(th, 1/mu/2)
            theta = 100*mode(dep)
            for _ in range(2):
                new, integral = h.conduct(prop, theta, np.zeros(dep.size), np.zeros(dep.size))
                change = math.fsum(th.capacity*(new-theta))
                boundary = -th.boundary_conductance[0]*integral[0]-th.boundary_conductance[1]*integral[-1]
                self.assertLess(abs(change-boundary)/abs(boundary), 1e-10)
                theta = new
            errors.append(float(np.abs(theta-100*mode(dep)*math.exp(-1)).max()))
        self.assertTrue(3.3 < errors[0]/errors[1] < 4.7)


class CouplingTests(Base):
    def test_arrhenius_repreparation_equals_kernel(self):
        arr = h.ArrheniusUpdate.of(self.base)
        same = arr.at(np.array(self.base.temperature_k))
        np.testing.assert_array_equal(same.log_c, self.base.log_c)
        np.testing.assert_array_equal(same.volume_rt, self.base.volume_rt)
        t = np.array(self.base.temperature_k)+25.
        moved = arr.at(t)
        for i in (0, 9, 17, 31):
            mech, grain, eta = self.base.layer_inputs[int(self.base.layer[i])]
            k = h.column.LocalLaw.prepare(mech, float(t[i]), float(self.base.reference_pa[i]), grain_m=grain,
                                          cohesion_pa=float(self.base.cohesion_pa[i]), friction_rad=float(self.base.friction_rad[i]),
                                          pore_pressure_pa=float(self.base.pore_pa[i]), plastic_viscosity_pa_s=eta)
            np.testing.assert_array_equal(np.asarray(k.log_coefficients), moved.log_c[i, :len(mech)])
        self.assertNotEqual(moved.fingerprint, same.fingerprint)
        self.assertFalse(moved.log_c.flags.writeable)
        for bad in (np.zeros(self.base.size), t[:3], t.astype(np.float32)[:0]):
            with self.assertRaises(ValueError):
                arr.at(bad)

    def test_no_heating_and_no_feedback_equal_reviewed_evolution(self):
        fixed = h.ArrheniusUpdate.of(self.base).at(np.array(self.thermal.steady_k))
        reviewed = h.weakening.evolve(fixed, LAW, self.kappa0, control="rate", value=RATE, duration_s=.02/RATE,
                                      steps=4, strain_bound=BOUND, policy=WEAK["policy"])
        cold = self.run_heat(4, .02, fractions=(0., 0.))
        frozen = self.run_heat(4, .02, feedback=False)
        self.assertFalse(np.any(cold["theta"]))
        for out in (cold, frozen):
            np.testing.assert_array_equal(out["kappa"], reviewed["kappa"])
            self.assertEqual(out["force_end"], reviewed["force_end"])
        self.assertGreater(float(frozen["theta"].min()), 0.)
        self.assertLess(frozen["accounts"]["energy_relative"], 1e-10)

    def test_feedback_lowers_force_with_closed_energy(self):
        on, off = self.run_heat(8, .03), self.run_heat(8, .03, feedback=False)
        self.assertLess(on["force_end"], off["force_end"])
        for out in (on, off):
            acc = out["accounts"]
            self.assertLess(acc["energy_relative"], 1e-10)
            self.assertLess(acc["partition_relative"], 1e-10)
            self.assertLess(abs(acc["heat_j_m2"]-acc["creep_work_j_m2"]-acc["plastic_work_j_m2"])/acc["heat_j_m2"], 1e-12)
            self.assertGreater(acc["surface_loss_j_m2"], 0.)

    def test_layer_warming_is_volume_weighted(self):
        """Quadratic departure a x^2 + b per layer: its depth mean is a/3 + b; the point mean over-weights layer ends."""
        x = np.tile(np.polynomial.legendre.leggauss(8)[0], 4)           # each point's position within its layer
        a, b = np.array([4., 1., 7., 2.]), np.array([.5, 3., 0., 1.])
        theta = a[self.base.layer]*x*x+b[self.base.layer]
        rows = h.summary(dict(self.run_heat(1, 1e-4), theta=theta), self.base)["warming_by_layer_k"]
        self.assertEqual(len(rows), 4)
        for li, row in enumerate(rows):
            m = self.base.layer == li
            self.assertEqual(row["maximum"], float(theta[m].max()))
            self.assertLess(abs(row["volume_weighted_mean"]-(a[li]/3+b[li])), 1e-13*(a[li]+b[li]))
            self.assertGreater(float(theta[m].mean())-row["volume_weighted_mean"], .1*a[li])   # 7/15 vs 1/3 of a

    def test_homogeneous_coupled_oracle_second_order(self):
        hc = SPEC["campaign"]["homogeneous"]
        layer = hc["layer"]
        base = h.weakening.prepare([layer], 4, closure=h.weakening.SUPPLIED)
        props = [dict(name=layer["name"], conductivity_w_m_k=2.5, heat_capacity_j_kg_k=750., radiogenic_w_m3=0.)]
        th = h.prepare_thermal(base.layer, base.depth_m, base.weight, [layer["thickness_m"]], props, [2700.],
                               dict(top=dict(type="insulated"), bottom=dict(type="insulated")),
                               reference_temperature=600., mechanical_fingerprint=base.fingerprint)
        duration = .04/RATE
        oracle = h.homogeneous_oracle(layer, hc["thermal"], LAW, RATE, 2., duration, (1., 1.))
        errors = []
        for n in (8, 16, 32):
            out = h.evolve_heat(base, th, LAW, np.full(4, 2.), rate=RATE, duration_s=duration, steps=n,
                                strain_bound=BOUND, temperature_step_k=5., fractions=(1., 1.), policy=SPEC["policy"])
            errors.append(h.relative_change(float(out["theta"][0]), oracle["temperature_rise"]))
            self.assertEqual(out["accounts"]["surface_loss_j_m2"], 0.)
        for o in h.order(errors):
            self.assertTrue(1.8 <= o <= 2.2, o)


class RefusalTests(Base):
    def test_step_refusals_are_atomic(self):
        refused = self.run_heat(4, .08)                    # 0.02 per step; the third exceeds 0.05
        exact = self.run_heat(2, .04)
        self.assertEqual((refused["status"], refused["accepted_steps"]), ("REFUSED_SMALL_STRAIN", 2))
        np.testing.assert_array_equal(refused["theta"], exact["theta"])
        np.testing.assert_array_equal(refused["kappa"], exact["kappa"])
        self.assertEqual(refused["accounts"], exact["accounts"])
        hot = self.run_heat(1, .04, rate=1e-13, rate_for_time=1e-13)
        self.assertEqual((hot["status"], hot["accepted_steps"]), ("REFUSED_TEMPERATURE_STEP", 0))
        self.assertFalse(np.any(hot["theta"]))
        self.assertEqual(hot["accounts"]["heat_j_m2"], 0.)

    def test_propagator_reuse_parity_and_mismatch(self):
        dt = .015/RATE/3
        a = self.run_heat(3, .015, propagator=h.prepare_propagator(self.thermal, dt))
        b = self.run_heat(3, .015, provider=lambda: h.prepare_propagator(self.thermal, dt))
        np.testing.assert_array_equal(a["theta"], b["theta"])
        self.assertEqual(a["accounts"], b["accounts"])
        with self.assertRaisesRegex(ValueError, "propagator"):
            self.run_heat(3, .015, propagator=h.prepare_propagator(self.thermal, 2*dt))

    def test_case_refuses_unadmitted_physics(self):
        for path, value in ((("representation", "advection_velocity_m_s"), 1e-10),
                            (("representation", "max_axial_strain"), .2),
                            (("representation", "control"), "supplied transmitted force"),
                            (("thermal_layers", 0, "conductivity_w_m_k"), [2.5, 3e-3]),
                            (("thermal_layers", 0, "latent_heat_j_kg"), 3e5),
                            (("boundaries", "bottom"), dict(type="flux", value_w_m2=.03)),
                            (("heat_fractions",), [1.5, 1.]),
                            (("policy", "max_steps"), 512)):
            bad = copy.deepcopy(SPEC)
            target = bad
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = value
            with self.subTest(path=path), self.assertRaises(ValueError):
                h.validate_case(bad)

    def test_direct_input_refusals(self):
        for steps in (0, 257, 2.):
            with self.subTest(steps=steps), self.assertRaises(ValueError):
                self.run_heat(steps, .01)
        other, _ = h.weakening.base_prepare(WEAK, order=8, offset_k=1.)
        for kw in (dict(rate=0.), dict(base=other), dict(theta0=np.zeros(3)), dict(fractions=(1., -1.))):
            with self.subTest(kw=list(kw)), self.assertRaises(ValueError):
                self.run_heat(2, .01, **kw)
        with self.assertRaises(ValueError):
            h.evolve_heat(self.base, self.thermal, LAW, self.kappa0, rate=RATE, duration_s=1e12, steps=2,
                          strain_bound=BOUND, temperature_step_k=6., fractions=(1., 1.), policy=SPEC["policy"])


class SupportTests(Base):
    """Thermal cells must be the mechanical quadrature's own, checked by value rather than by label."""

    def prepare(self, layer, depth, weight, thicknesses=None):
        thick = [l["thickness_m"] for l in self.layers] if thicknesses is None else thicknesses
        return h.prepare_thermal(layer, depth, weight, thick, SPEC["thermal_layers"],
                                 [l["density_kg_m3"] for l in self.layers], SPEC["boundaries"],
                                 mechanical_fingerprint=self.base.fingerprint)

    def test_one_percent_volume_mismatch_refused(self):
        """The review reproduction: 101 km of cells in a 100 km column ran COMPLETE with a zero residual."""
        b = self.base
        with self.assertRaisesRegex(ValueError, "declared thickness"):
            self.prepare(b.layer, b.depth_m, b.weight*1.01)
        last = np.array(b.weight)
        last[7] *= 1+1e-9                          # deepest upper-crust cell: formerly hidden by the forced face
        with self.assertRaisesRegex(ValueError, "declared thickness"):
            self.prepare(b.layer, b.depth_m, last)

    def test_same_size_foreign_support_refused_by_evolution(self):
        b = self.base
        shifted = [25e3, 15e3, 10e3, 50e3]
        foreign = self.prepare(*h.geometry(shifted, 8), shifted)            # valid on its own
        nudged = np.array(b.weight)
        nudged[3] = np.nextafter(nudged[3], np.inf)                         # within round-off: a valid support
        roundoff = self.prepare(b.layer, b.depth_m, nudged)
        for thermal in (foreign, roundoff):
            self.assertEqual((thermal.size, thermal.mechanical_fingerprint), (b.size, b.fingerprint))
            with self.assertRaisesRegex(ValueError, "mechanical quadrature"):
                self.run_heat(1, 1e-4, thermal=thermal)
            with self.assertRaisesRegex(ValueError, "mechanical quadrature"):
                h.coupled_run(SPEC, WEAK, b, thermal, steps=1, strain=1e-5)

    def test_replaced_dataclass_support_refused(self):
        """dataclasses.replace copies a frozen preparation with altered support but its old labels."""
        frozen, replace = h.weakening.frozen, dataclasses.replace
        b, th = self.base, self.thermal
        owner = np.array(b.layer)
        owner[7] = 1                                                        # upper-crust point claimed by the lower crust
        for name, base, thermal in (
                ("thermal widths", b, replace(th, volume_m=frozen(th.volume_m*1.01), capacity=frozen(th.capacity*1.01))),
                ("thermal depths", b, replace(th, depth_m=frozen(th.depth_m+1.))),
                ("thermal layer ownership", b, replace(th, layer=frozen(owner, int))),
                ("mechanical widths", replace(b, weight=frozen(b.weight*1.01)), th)):
            self.assertEqual((thermal.fingerprint, thermal.mechanical_fingerprint, base.fingerprint),
                             (th.fingerprint, th.mechanical_fingerprint, b.fingerprint))
            with self.subTest(name), self.assertRaisesRegex(ValueError, "mechanical quadrature"):
                self.run_heat(1, 1e-4, base=base, thermal=thermal)

    def test_malformed_support_refused(self):
        lay, dep, wt = np.array(self.base.layer), np.array(self.base.depth_m), np.array(self.base.weight)
        thick = [l["thickness_m"] for l in self.layers]

        def at(a, i, value):
            a = a.copy()
            a[i] = value
            return a
        cases = {
            "missing": (None, dep, wt, thick),
            "empty": (lay[:0], dep[:0], wt[:0], thick),
            "two-dimensional": (lay.reshape(4, 8), dep.reshape(4, 8), wt.reshape(4, 8), thick),
            "unequal lengths": (lay, dep[:-1], wt, thick),
            "fractional layer IDs": (lay.astype(float), dep, wt, thick),
            "boolean layer IDs": (lay.astype(bool), dep, wt, thick),
            "unordered layer IDs": (at(lay, 3, 1), dep, wt, thick),
            "ownership moved": (at(lay, 7, 1), dep, wt, thick),
            "last layer missing": (np.minimum(lay, 2), dep, wt, thick),
            "inner layer missing": (np.where(lay == 1, 2, lay), dep, wt, thick),
            "NaN depth": (lay, at(dep, 5, np.nan), wt, thick),
            "infinite depth": (lay, at(dep, 31, np.inf), wt, thick),
            "repeated depth": (lay, at(dep, 5, dep[4]), wt, thick),
            "complex depth": (lay, dep.astype(complex), wt, thick),
            "depth outside its cell": (lay, at(dep, 0, 1500.), wt, thick),
            "zero width": (lay, dep, at(wt, 5, 0.), thick),
            "negative width": (lay, dep, at(wt, 5, -wt[5]), thick),
            "infinite width": (lay, dep, at(wt, 5, np.inf), thick),
            "object widths": (lay, dep, wt.astype(object), thick),
            "no declared layers": (lay, dep, wt, []),
            "nonpositive thickness": (lay, dep, wt, thick[:3]+[-thick[3]]),
            "wrong declared thickness": (lay, dep, wt, thick[:3]+[thick[3]*1.01]),
        }
        for name, (layer, depth, weight, thicknesses) in cases.items():
            with self.subTest(name), self.assertRaises(ValueError):
                self.prepare(layer, depth, weight, thicknesses)

    def test_valid_layered_support_and_run_unchanged(self):
        """The valid pairing still runs; faces are cumulative Gauss widths and interfaces stay exact."""
        b, th = self.base, self.thermal
        thick = [l["thickness_m"] for l in self.layers]
        tops = np.concatenate([[0.], np.cumsum(thick)])
        for li in range(len(thick)):
            m = np.flatnonzero(b.layer == li)
            faces = tops[li]+np.cumsum(b.weight[m])
            np.testing.assert_array_equal(th.upper_face_m[m[:-1]], faces[:-1])
            np.testing.assert_array_equal(th.lower_face_m[m[1:]], faces[:-1])
            self.assertEqual((th.lower_face_m[m[0]], th.upper_face_m[m[-1]]), (tops[li], tops[li+1]))
            self.assertLess(abs(faces[-1]-tops[li+1]), 1e-12*tops[li+1])     # the interface moves by round-off only
        for q in (2, 16, 128):                                              # Gauss widths within twice the bound
            lay, _, wt = h.geometry(thick, q)
            for li, t in enumerate(thick):
                self.assertLessEqual(abs(math.fsum(wt[lay == li])-t), h.width_tolerance(q)/4*t)
        again = self.prepare(b.layer, b.depth_m, b.weight)
        self.assertEqual(again.fingerprint, th.fingerprint)
        for key in ("layer", "depth_m", "volume_m", "lower_face_m", "upper_face_m", "capacity", "conductance",
                    "steady_k"):
            np.testing.assert_array_equal(getattr(again, key), getattr(th, key))
        declared = math.fsum(l["density_kg_m3"]*p["heat_capacity_j_kg_k"]*l["thickness_m"]
                             for l, p in zip(self.layers, SPEC["thermal_layers"]))
        self.assertLess(abs(math.fsum(th.volume_m)-tops[-1]), 1e-9)
        self.assertLess(abs(math.fsum(th.capacity)/declared-1), 1e-13)
        out = h.coupled_run(SPEC, WEAK, b, th, steps=1, strain=1e-5)
        self.assertEqual((out["status"], out["accepted_steps"]), ("COMPLETE", 1))
        self.assertLess(out["accounts"]["energy_relative"], 1e-10)


if __name__ == "__main__":
    unittest.main()
