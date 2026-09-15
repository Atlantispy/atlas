"""Independent derivative, conservation and retained-law checks, not calibration."""
from dataclasses import replace
import math
import unittest

import numpy as np

from . import hydraulic_jacobian as hj, soil_water as w
from work.generator_upgrade_r5 import soil_water as old

E = 'SYNTHETIC ANALYTIC JACOBIAN ORACLE; NO DIADEM MATERIAL FIT'
S = 'SYNTHETIC TEST'


def fixture(*, layers=None, rain=1e-6, bottom='fixed_head', bottom_head=.2, uptake=False):
    layers = layers or (w.HydraulicLayer('a', .1, .04, .4, 2., 2., .5, 1e-5, E, S),
                        w.HydraulicLayer('b', .3, .06, .35, 1.3, 1.6, 0., 2e-6, E, S),
                        w.HydraulicLayer('c', .2, .02, .5, 3., 2.7, .8, 4e-6, E, S))
    column = w.Column('jacobian-oracle', layers, len(layers), E, S)
    law = w.Uptake(tuple(1/len(layers) for _ in layers), -100., -2., -.2, 0., E, S) if uptake else None
    forcing = w.Forcing(10., rain, 2e-7 if uptake else 0., law, E, S)
    boundary = w.Boundary(bottom, bottom_head if bottom == 'fixed_head' else None, E, S)
    return column, forcing, boundary


def old_fluxes(column, head, forcing, boundary):
    """Direct preserved R5 numerical equations, independent of this helper."""
    from dataclasses import asdict
    layers = tuple(old.HydraulicLayer(**asdict(v)) for v in column.layers)
    col = old.Column(column.column_id, layers, column.root_boundary_index, E, S)
    uptake = old.Uptake(**asdict(forcing.uptake)) if forcing.uptake else None
    force = old.Forcing(forcing.duration_seconds, forcing.surface_input_m_s,
                        forcing.potential_et_m_s, uptake, E, S)
    lower = old.Boundary(boundary.kind, boundary.head_m, E, S)
    return old._fluxes(col, np.array(head), force, lower)


def central(fun, point):
    h = np.array(point, dtype=float); result = []
    for i in range(len(h)):
        delta = 2e-6*max(abs(h[i]), .01)
        a, b = h.copy(), h.copy(); a[i] += delta; b[i] -= delta
        result.append((np.asarray(fun(a))-np.asarray(fun(b)))/(2*delta))
    return np.array(result).T


class HydraulicJacobianTests(unittest.TestCase):
    def test_n2_properties_and_derivatives_against_closed_form(self):
        layer = fixture()[0].layers[0]
        kernel = hj.prepare(*fixture(layers=(layer,)))
        for h in (-100., -1., -.1, -1e-5, -1e-10, -1e-100):
            theta, k, capacity, dk = (v[0] for v in kernel.properties([h]))
            u = -layer.alpha_per_m*h; denom = 1+u*u
            se = 1/math.sqrt(denom); b = 1-u/math.sqrt(denom)
            a = layer.alpha_per_m*u/denom
            bp = layer.alpha_per_m/denom**1.5
            expected = (layer.theta_r+(layer.theta_s-layer.theta_r)*se,
                        layer.ksat_m_s*se**layer.mualem_l*b*b,
                        (layer.theta_s-layer.theta_r)*layer.alpha_per_m*u/denom**1.5,
                        layer.ksat_m_s*se**layer.mualem_l*(layer.mualem_l*a*b*b+2*b*bp))
            np.testing.assert_allclose([theta, k, capacity, dk], expected, rtol=2e-10, atol=1e-110)

    def test_saturated_branch_has_zero_storage_and_conductivity_derivatives(self):
        kernel = hj.prepare(*fixture())
        theta, k, capacity, dk = kernel.properties([0., .1, 100.])
        np.testing.assert_array_equal(theta, kernel.theta_s)
        np.testing.assert_array_equal(k, kernel.ksat)
        np.testing.assert_array_equal(capacity, np.zeros(3)); np.testing.assert_array_equal(dk, np.zeros(3))

    def test_zero_ksat_remains_exact_barrier_without_nan_derivative(self):
        column, forcing, boundary = fixture()
        column = replace(column, layers=tuple(replace(v, ksat_m_s=0.) for v in column.layers))
        kernel = hj.prepare(column, forcing, boundary)
        theta, k, c, dk = kernel.properties([-1., .2, -1e5])
        self.assertTrue(np.all(np.isfinite(theta))); self.assertTrue(np.all(np.isfinite(c)))
        np.testing.assert_array_equal(k, np.zeros(3)); np.testing.assert_array_equal(dk, np.zeros(3))
        flux = kernel.fluxes([-1., .2, -1e5])
        np.testing.assert_array_equal(flux.q, np.zeros(4)); np.testing.assert_array_equal(flux.flux_jacobian, np.zeros((4, 3)))

    def test_heterogeneous_capacity_and_conductivity_derivatives_independent_difference(self):
        args = fixture(); kernel = hj.prepare(*args)
        h = np.array([-.7, -1.3, -.03])
        theta, k, c, dk = kernel.properties(h)
        expected = central(lambda x: old_fluxes(args[0], x, args[1], args[2])[0], h)
        # Retained theta rows form a diagonal derivative; independent K calls.
        old_layers = tuple(old.HydraulicLayer(v.layer_id, v.thickness_m, v.theta_r, v.theta_s, v.alpha_per_m,
                                             v.n, v.mualem_l, v.ksat_m_s, E, S) for v in args[0].layers)
        kdiff = central(lambda x: [old.hydraulic_properties(v, float(a))[1] for v, a in zip(old_layers, x)], h)
        np.testing.assert_allclose(np.diag(c), expected, rtol=3e-7, atol=1e-11)
        np.testing.assert_allclose(np.diag(dk), kdiff, rtol=3e-6, atol=1e-14)

    def test_retained_values_agree_across_ordinary_unsaturated_regimes(self):
        args = fixture(uptake=True); kernel = hj.prepare(*args)
        for h in ((-.03, -.1, -.4), (-50., -3., -1.), (.1, .2, .3), (-.3, .1, -.8)):
            actual = kernel.fluxes(h); th, q, sink = old_fluxes(args[0], h, args[1], args[2])
            np.testing.assert_allclose(actual.theta, th, rtol=3e-15, atol=3e-16)
            np.testing.assert_allclose(actual.q, q, rtol=2e-12, atol=1e-18)
            np.testing.assert_allclose(actual.sink, sink, rtol=3e-15, atol=1e-25)

    def test_harmonic_flux_jacobian_matches_independent_retained_difference(self):
        args = fixture(); kernel = hj.prepare(*args); head = [-.7, -1.3, -.03]
        expected = central(lambda x: old_fluxes(args[0], x, args[1], args[2])[1], head)
        np.testing.assert_allclose(kernel.fluxes(head).flux_jacobian, expected, rtol=3e-6, atol=1e-14)

    def test_surface_imposed_flux_has_zero_derivative(self):
        kernel = hj.prepare(*fixture(rain=0.))
        row = kernel.fluxes([-.3, -.3, -.3])
        self.assertEqual(row.q[0], 0.); self.assertEqual(row.flux_jacobian[0, 0], 0.)

    def test_surface_head_cap_has_required_conductivity_and_head_terms(self):
        kernel = hj.prepare(*fixture(rain=1.))
        h = [-.3, -.3, -.3]; row = kernel.fluxes(h)
        expected = row.conductivity_derivative[0]*(1-h[0]/(.1/2))-row.conductivity[0]/(.1/2)
        self.assertEqual(row.flux_jacobian[0, 0], expected)
        self.assertLess(row.q[0], 1.)

    def test_surface_exact_switch_chooses_imposed_flux_derivative(self):
        args = fixture(); layer = args[0].layers[0]
        kernel = hj.prepare(*fixture(rain=layer.ksat_m_s))
        row = kernel.fluxes([0., -.3, -.3])
        self.assertEqual(row.q[0], layer.ksat_m_s); self.assertEqual(row.flux_jacobian[0, 0], 0.)

    def test_lower_boundary_derivatives_for_all_three_laws(self):
        h = [-.3, -.4, -.5]
        for kind in ('fixed_head', 'free_drainage', 'no_flow'):
            args = fixture(bottom=kind); kernel = hj.prepare(*args)
            expected = central(lambda x: old_fluxes(args[0], x, args[1], args[2])[1], h)
            np.testing.assert_allclose(kernel.fluxes(h).flux_jacobian[-1], expected[-1], rtol=2e-7, atol=1e-14)

    def test_feddes_active_segments_plateau_and_outside_derivatives(self):
        kernel = hj.prepare(*fixture(uptake=True))
        for heads in ((-50., -1., -.1), (-101., 0., .3)):
            row = kernel.fluxes(heads)
            expected = central(lambda x: kernel.fluxes(x).sink, heads)
            # Avoid differencing the exact h=0 kink, whose selected dry-side
            # derivative differs from a symmetric derivative by design.
            if heads[1] == 0.:
                expected[1, 1] = 0.
            np.testing.assert_allclose(np.diag(row.sink_derivative), expected, rtol=1e-8, atol=1e-16)
        for switch in (-100., -2., -.2, 0.):
            self.assertEqual(kernel.fluxes([switch]*3).sink_derivative[0], 0.)

    def test_mixed_residual_jacobian_matches_independent_equations(self):
        args = fixture(uptake=True); kernel = hj.prepare(*args)
        h = np.array([-50., -1., -.1]); theta_old = np.array([.15, .2, .3]); dt = 17.
        def residual(x):
            theta, q, sink = old_fluxes(args[0], x, args[1], args[2])
            return (theta-theta_old)*kernel.dz-dt*(q[:-1]-q[1:]-sink)
        value, jac = kernel.residual_and_jacobian(h, theta_old, dt)
        np.testing.assert_allclose(value, residual(h), rtol=2e-13, atol=2e-16)
        np.testing.assert_allclose(jac, central(residual, h), rtol=3e-6, atol=2e-11)

    def test_saturated_heterogeneous_thin_layer_matrix_has_exact_series_structure(self):
        base = fixture()[0].layers
        layers = tuple(replace(v, thickness_m=dz) for v, dz in zip(base, (2e-8, 3e-8, .5)))
        kernel = hj.prepare(*fixture(layers=layers, rain=0., bottom_head=1.))
        h = [.1, .2, .3]; dt = .01
        value, jac = kernel.residual_and_jacobian(h, kernel.theta_s, dt)
        g = [1/(a.thickness_m/(2*a.ksat_m_s)+b.thickness_m/(2*b.ksat_m_s)) for a, b in zip(layers, layers[1:])]
        expected = np.array([[2*layers[0].ksat_m_s/layers[0].thickness_m+g[0], -g[0], 0.],
                             [-g[0], g[0]+g[1], -g[1]],
                             [0., -g[1], g[1]+2*layers[2].ksat_m_s/layers[2].thickness_m]])*dt
        np.testing.assert_allclose(jac, expected, rtol=2e-15, atol=1e-19)

    def test_adjacent_nanometre_unsaturated_layers_do_not_erase_interface_derivatives(self):
        base = fixture()[0].layers
        layers = tuple(replace(v, thickness_m=dz) for v, dz in zip(base, (2.5e-8, 2.4e-8, .5)))
        args = fixture(layers=layers); kernel = hj.prepare(*args); h = [-.39, -.51, -.26]
        expected = central(lambda x: old_fluxes(args[0], x, args[1], args[2])[1], h)
        actual = kernel.fluxes(h).flux_jacobian
        np.testing.assert_allclose(actual, expected, rtol=2e-6, atol=1e-11)
        self.assertGreater(abs(actual[1, 0]), 1.)

    def test_internal_face_derivatives_cancel_in_total_mass_equation(self):
        kernel = hj.prepare(*fixture(uptake=True)); h = [-50., -.3, -.1]
        flux = kernel.fluxes(h); dt = 9.
        _, jac = kernel.residual_and_jacobian(h, flux.theta, dt)
        expected = kernel.dz*flux.capacity-dt*(flux.flux_jacobian[0]-flux.flux_jacobian[-1])+dt*flux.sink_derivative
        np.testing.assert_allclose(np.sum(jac, axis=0), expected, rtol=3e-15, atol=1e-17)
        for i in range(3):
            for j in range(3):
                if abs(i-j) > 1: self.assertEqual(jac[i, j], 0.)

    def test_prepared_arrays_are_readonly_and_bind_exact_source_objects(self):
        args = fixture(); kernel = hj.prepare(*args)
        self.assertIs(kernel.column, args[0]); self.assertIs(kernel.forcing, args[1]); self.assertIs(kernel.boundary, args[2])
        for name in ('dz', 'theta_r', 'theta_s', 'alpha', 'n', 'm', 'connectivity', 'ksat', 'weights'):
            with self.assertRaises(ValueError): getattr(kernel, name)[0] = 0.

    def test_nonfinite_boolean_complex_and_shape_inputs_reject(self):
        kernel = hj.prepare(*fixture())
        for heads in ([float('nan'), 0, 0], [float('inf'), 0, 0], [True]*3, [1j]*3, [-1.], [[-1.]*3]):
            with self.subTest(heads=heads), self.assertRaises(ValueError): kernel.properties(heads)
        for dt in (True, 0., -1., float('nan'), float('inf')):
            with self.assertRaises(ValueError): kernel.residual_and_jacobian([-1.]*3, [.2]*3, dt)

    def test_unknown_forcing_and_out_of_range_old_stock_reject(self):
        column, forcing, boundary = fixture()
        unknown = replace(forcing, surface_input_m_s=None)
        with self.assertRaises(ValueError): hj.prepare(column, unknown, boundary)
        kernel = hj.prepare(column, forcing, boundary)
        for theta in ([0.]*3, [1.]*3):
            with self.assertRaises(ValueError): kernel.residual_and_jacobian([-1.]*3, theta, 1.)


if __name__ == '__main__':
    unittest.main()
