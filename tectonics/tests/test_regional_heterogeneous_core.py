"""W07 Step 3: exact stress supports, interfaces and retained exponential MMS.

SPDX-License-Identifier: AGPL-3.0-only
"""
from concurrent.futures import CancelledError
import unittest
from unittest import mock

import numpy as np

from atlas_tectonics.regional_stokes import prepare_mac
from w07_interface_reference import interface_fields, interface_sites

CASE_MEASUREMENTS = []


def record_case(plan, result, case, **errors):
    """Small evidence payload for the Step 3 owner; no files or histories."""
    d = result["diagnostics"]
    CASE_MEASUREMENTS.append(dict(case=case, nx=plan.nx, nz=plan.nz, **errors,
        momentum=d["momentum_residual"], divergence=d["divergence_residual"],
        gauge=d["pressure_gauge_residual"], work=d["normalised_work_residual"],
        iterations=result["iterations"], corrections=d["defect_corrections"],
        retained_nbytes=plan.retained_nbytes, timings=result["timings"]))


def free_slip():
    return {s: {"u": ("velocity", 0.) if s in ("left", "right") else ("traction", 0.),
                "w": ("traction", 0.) if s in ("left", "right") else ("velocity", 0.)}
            for s in ("left", "right", "bottom", "top")}


def exponential_fields(x, z, width=2., height=1.):
    """Retained R4.3 continuum derivatives; no assembled-operator load."""
    kx, kz, amplitude, pressure = np.pi/width, np.pi/height, .04, .3
    eta = np.exp(1.3*x/width-.4*z/height)
    u = amplitude*kz*np.sin(kx*x)*np.cos(kz*z)
    w = -amplitude*kx*np.cos(kx*x)*np.sin(kz*z)
    exx = amplitude*kx*kz*np.cos(kx*x)*np.cos(kz*z)
    gamma = amplitude*(kx*kx-kz*kz)*np.sin(kx*x)*np.sin(kz*z)
    etax, etaz = eta*1.3/width, -.4*eta/height
    fx = eta*(kx*kx+kz*kz)*u-2*etax*exx-etaz*gamma-2*kx*pressure*np.sin(2*kx*x)*np.cos(kz*z)
    fz = eta*(kx*kx+kz*kz)*w-etax*gamma+2*etaz*exx-kz*pressure*np.cos(2*kx*x)*np.sin(kz*z)
    p = pressure*np.cos(2*kx*x)*np.cos(kz*z)
    return eta, u, w, p, fx, fz


def exponential_coefficients(nx, nz, width=2., height=1.):
    xc, zc = np.meshgrid((np.arange(nx)+.5)*width/nx, (np.arange(nz)+.5)*height/nz)
    xv, zv = np.meshgrid(np.linspace(0., width, nx+1), np.linspace(0., height, nz+1))
    return exponential_fields(xc, zc, width, height)[0], exponential_fields(xv, zv, width, height)[0]


def layered_problem(nx, nz, interface):
    """Exact integral compliance over each shear derivative's real support.

    This named 1-D series construction is specific to horizontal layered shear,
    not a general phase average. Boundary half-cell intervals are integrated too.
    """
    tau = 1./(interface+(1-interface)/1000.)
    def u(x, z):
        return tau*(np.minimum(z, interface)+np.maximum(z-interface, 0.)/1000.)
    z = np.r_[0., (np.arange(nz)+.5)/nz, 1.]
    lower, upper = z[:-1], z[1:]
    low_length = np.maximum(0., np.minimum(upper, interface)-lower)
    viscosity = np.diff(z)/(low_length+(np.diff(z)-low_length)/1000.)
    vertex = np.broadcast_to(viscosity[:, None], (nz+1, nx+1)).copy()
    center = np.broadcast_to(np.where((np.arange(nz)+.5)/nz < interface, 1., 1000.)[:, None], (nz, nx)).copy()
    bc = {s: {"u": ("velocity", u), "w": ("velocity", 0.)}
          for s in ("left", "right", "bottom", "top")}
    # Physical pressure datum through ONE normal-traction condition; u stays 1.
    bc["top"]["w"] = ("traction", -10.)
    return center, vertex, bc, u, tau


class RegionalHeterogeneousCoreTests(unittest.TestCase):
    def test_b06_independent_source_and_frozen_manual_interfaces(self):
        for variant in ("aspect-source", "frozen-manual"):
            for family, grids in (("aligned", (16, 32, 64)), ("unaligned", (15, 31, 63))):
                collected = []
                for n in grids:
                    center, vertex = interface_sites(n, n)
                    with self.subTest(variant=variant, family=family, n=n), prepare_mac(n, n, 1., 1., None,
                             free_slip(), eta_center=center, eta_vertex=vertex, pressure_mean=0.) as plan:
                        (xu, zu), (xw, zw) = plan.force_coordinates()
                        xc, zc = np.meshgrid((np.arange(n)+.5)/n, (np.arange(n)+.5)/n)
                        ue = interface_fields(xu, zu, variant=variant)
                        we = interface_fields(xw, zw, variant=variant)
                        pe = interface_fields(xc, zc, variant=variant)[2]
                        pe -= np.mean(pe)  # both problems have an actual free pressure gauge
                        result = plan.solve(ue[3], we[4])
                        qu, qw = np.ones_like(result["u"]), np.ones_like(result["w"])
                        qu[:, [0, -1]] = .5; qw[[0, -1]] = .5
                        ev = np.sqrt((np.sum(qu*(result["u"]-ue[0])**2)+np.sum(qw*(result["w"]-we[1])**2)) /
                                     (np.sum(qu*ue[0]**2)+np.sum(qw*we[1]**2)))
                        ep = np.linalg.norm(result["p"]-pe)/np.linalg.norm(pe)
                        collected.append((ev, ep))
                        record_case(plan, result, variant+"/"+family, velocity_l2=float(ev), pressure_l2=float(ep))
                self.assertEqual(len(collected), 3)
                self.assertLessEqual(collected[-1][0], .02, (variant, family, collected))
                self.assertLessEqual(collected[-1][1], .05, (variant, family, collected))
                for coarse, fine in zip(collected, collected[1:]):
                    np.testing.assert_array_less(fine, coarse, err_msg=str((variant, family, collected)))

    def test_explicit_support_validation_and_scalar_equivalence(self):
        nx, nz = 8, 4
        c, v = np.ones((nz, nx)), np.ones((nz+1, nx+1))
        args = (nx, nz, 2., 1.)
        invalid = [(None, None, None), (1., c, v), (None, c, None), (None, c, v[:-1]),
                   (None, c*0., v), (None, c, v*np.nan)]
        for eta, center, vertex in invalid:
            with self.subTest(eta=eta), self.assertRaises(ValueError):
                prepare_mac(*args, eta, free_slip(), eta_center=center, eta_vertex=vertex, pressure_mean=0.)
        with prepare_mac(*args, 1., free_slip(), pressure_mean=0.) as scalar, \
                prepare_mac(*args, None, free_slip(), eta_center=c, eta_vertex=v, pressure_mean=0.) as explicit:
            np.testing.assert_array_equal(scalar.matrix.toarray(), explicit.matrix.toarray())
            c[:] = 5.; v[:] = 9.
            np.testing.assert_array_equal(explicit.eta_center, 1.)
            np.testing.assert_array_equal(explicit.eta_vertex, 1.)
            self.assertFalse(explicit.eta_center.flags.writeable)
            (x, z), (xw, zw) = scalar.force_coordinates()
            load = exponential_fields(x, z)[4], exponential_fields(xw, zw)[5]
            a, b = scalar.solve(*load), explicit.solve(*load)
            np.testing.assert_array_equal(a["velocity_vector"], b["velocity_vector"])
            np.testing.assert_array_equal(a["p"], b["p"])

    def test_retained_exponential_mms_equal_and_unequal_spacing(self):
        for width in (2., 3.):
            collected = []
            for n in (8, 16, 32):
                nx, nz = 2*n, n
                center, vertex = exponential_coefficients(nx, nz, width)
                with self.subTest(width=width, n=n), prepare_mac(nx, nz, width, 1., None, free_slip(),
                         eta_center=center, eta_vertex=vertex, pressure_mean=0.) as plan:
                    (xu, zu), (xw, zw) = plan.force_coordinates()
                    xc, zc = np.meshgrid((np.arange(nx)+.5)*plan.dx, (np.arange(nz)+.5)*plan.dz)
                    ue = exponential_fields(xu, zu, width)
                    we = exponential_fields(xw, zw, width)
                    pe = exponential_fields(xc, zc, width)[3]
                    result = plan.solve(ue[4], we[5])
                    self.assertTrue(result["diagnostics"]["gates_passed"])
                    qu, qw = np.ones_like(result["u"]), np.ones_like(result["w"])
                    qu[:, [0, -1]] = .5; qw[[0, -1]] = .5
                    err = [np.sqrt(np.sum(q*(result[key]-expected)**2)*plan.volume)
                           for q, key, expected in ((qu, "u", ue[1]), (qw, "w", we[2]), (1., "p", pe))]
                    collected.append(err)
                    record_case(plan, result, "exponential/width="+str(width), errors_l2=err)
                    self.assertLess(plan.retained_nbytes, 128*1024**2)
            for coarse, fine in zip(collected, collected[1:]):
                np.testing.assert_array_less(3.7, np.asarray(coarse)/fine)
                np.testing.assert_array_less(np.asarray(coarse)/fine, 4.5)

    def test_b06_aligned_unaligned_layered_series_velocity_stress_work_datum(self):
        for interface in (.5, .37):
            for n in (16, 32, 64):
                center, vertex, bc, analytic_u, tau = layered_problem(n, n, interface)
                with self.subTest(interface=interface, n=n), prepare_mac(n, n, 1., 1., None, bc,
                         eta_center=center, eta_vertex=vertex) as plan:
                    fu, fw = np.zeros((n, n+1)), np.zeros((n+1, n))
                    result = plan.solve(fu, fw)
                    (xu, zu), _ = plan.force_coordinates()
                    exact = analytic_u(xu, zu)
                    self.assertLess(np.linalg.norm(result["u"]-exact)/np.linalg.norm(exact), .01)
                    np.testing.assert_allclose(result["u"], exact, atol=1e-9, rtol=0.)
                    np.testing.assert_allclose(result["w"], 0., atol=1e-9, rtol=0.)
                    np.testing.assert_allclose(result["p"], 10., atol=1e-8, rtol=0.)
                    np.testing.assert_allclose(result["tau_xz"], tau, atol=1e-8, rtol=0.)
                    self.assertLess(abs(result["diagnostics"]["dissipation"]-tau)/tau, .01)
                    self.assertAlmostEqual(result["diagnostics"]["total_boundary_work"], tau, delta=1e-8)
                    record_case(plan, result, "layered/a="+str(interface),
                                velocity_max=float(np.max(np.abs(result["u"]-exact))),
                                pressure_max=float(np.max(np.abs(result["p"]-10.))),
                                shear_max=float(np.max(np.abs(result["tau_xz"]-tau))),
                                shear_work_relative=abs(result["diagnostics"]["dissipation"]-tau)/tau)

    def test_heterogeneous_pure_traction_rigid_constraints_and_direct_parity(self):
        n = 4
        xc, zc = np.meshgrid((np.arange(n)+.5)/n, (np.arange(n)+.5)/n)
        xv, zv = np.meshgrid(np.arange(n+1)/n, np.arange(n+1)/n)
        center, vertex = 1+xc+zc, 1+xv+zv
        bc = {s: {"u": ("traction", 0.), "w": ("traction", 0.)}
              for s in ("left", "right", "bottom", "top")}
        bc["left"]["u"] = ("traction", lambda x, z: -2*(1+z))
        bc["right"]["u"] = ("traction", lambda x, z: 2*(2+z))
        bc["bottom"]["w"] = ("traction", lambda x, z: 2*(1+x))
        bc["top"]["w"] = ("traction", lambda x, z: -2*(2+x))
        outputs = []
        for method in ("gmres", "direct"):
            with prepare_mac(n, n, 1., 1., None, bc, eta_center=center, eta_vertex=vertex,
                    rigid_constraints="zero-mean-translation-rotation", method=method) as plan:
                result = plan.solve(np.full((n, n+1), -2.), np.full((n+1, n), 2.))
                (xu, _), (_, zw) = plan.force_coordinates()
                np.testing.assert_allclose(result["u"], xu-.5, atol=1e-9, rtol=0.)
                np.testing.assert_allclose(result["w"], -(zw-.5), atol=1e-9, rtol=0.)
                np.testing.assert_allclose(result["p"], 0., atol=1e-9, rtol=0.)
                self.assertEqual(plan.rigid_modes, 3)
                outputs.append(result)
        np.testing.assert_allclose(outputs[0]["velocity_vector"], outputs[1]["velocity_vector"], atol=1e-9, rtol=0.)

    def test_numeric_refill_reuses_geometry_and_matches_fresh_operator(self):
        nx, nz = 8, 4
        center, vertex = exponential_coefficients(nx, nz)
        args = (nx, nz, 2., 1., None, free_slip())
        with prepare_mac(*args, eta_center=center, eta_vertex=vertex, pressure_mean=.2) as plan:
            topology = [getattr(plan, k) for k in ("_Bx", "_Bz", "_S", "_P", "_D", "_G", "_C")]
            (xu, zu), (xw, zw) = plan.force_coordinates()
            load = exponential_fields(xu, zu)[4], exponential_fields(xw, zw)[5]
            before = plan.solve(*load)
            with self.assertRaises(CancelledError):
                plan.refill_viscosity(eta_center=center*2., eta_vertex=vertex*3., cancel=lambda: True)
            with mock.patch("atlas_tectonics.regional_stokes.spilu", side_effect=RuntimeError("factor failed")):
                with self.assertRaisesRegex(RuntimeError, "factor failed"):
                    plan.refill_viscosity(eta_center=center*2., eta_vertex=vertex*3.)
            np.testing.assert_array_equal(before["p"], plan.solve(*load)["p"])
            plan.refill_viscosity(eta_center=center*2., eta_vertex=vertex*3.)
            for old, key in zip(topology, ("_Bx", "_Bz", "_S", "_P", "_D", "_G", "_C")):
                self.assertIs(old, getattr(plan, key))
            with prepare_mac(*args, eta_center=center*2., eta_vertex=vertex*3., pressure_mean=.2) as fresh:
                np.testing.assert_array_equal(plan.matrix.toarray(), fresh.matrix.toarray())
                a, b = plan.solve(*load), fresh.solve(*load)
                np.testing.assert_array_equal(a["velocity_vector"], b["velocity_vector"])
                np.testing.assert_array_equal(a["p"], b["p"])
            self.assertEqual(plan.timings["topology_s"], 0.)

    def test_returned_field_stress_and_work_use_both_current_supports(self):
        center, vertex = exponential_coefficients(8, 4)
        with prepare_mac(8, 4, 2., 1., None, free_slip(), eta_center=center, eta_vertex=vertex,
                         pressure_mean=0.) as plan:
            (xu, zu), (xw, zw) = plan.force_coordinates()
            load = exponential_fields(xu, zu)[4], exponential_fields(xw, zw)[5]
            result = plan.solve(*load)
            np.testing.assert_array_equal(result["tau_xx"], 2*center*result["exx"])
            np.testing.assert_array_equal(result["tau_xz"], 2*vertex*result["exz"])
            # evaluate must keep working with no assembled physical operator.
            with mock.patch.object(plan, "_K", None), mock.patch.object(plan, "matrix", None):
                checked = plan.evaluate(result["velocity_vector"], result["p"], *load)
            self.assertTrue(checked["diagnostics"]["gates_passed"])
            plan.refill_viscosity(eta_center=center, eta_vertex=vertex*2.)
            stale = plan.evaluate(result["velocity_vector"], result["p"], *load)
            self.assertFalse(stale["diagnostics"]["gates_passed"])


if __name__ == "__main__":
    unittest.main()
