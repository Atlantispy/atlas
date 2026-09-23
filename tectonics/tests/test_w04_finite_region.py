"""Independent uniform-plate controls; computational windows are not plate ends."""
from dataclasses import FrozenInstanceError
import math
import unittest

import numpy as np
from numpy.testing import assert_allclose, assert_array_equal
from scipy.integrate import quad

from atlas_tectonics._validation import TectonicsError
from atlas_tectonics.finite_flexure import FlexureBoundary1D, FiniteRegionFlexure
from atlas_tectonics.parameters import FlexureParameters
from atlas_tectonics.regional import RegionalGrid1D
from atlas_tectonics.resources import WorkBudget, MemoryLimitError


SOURCE = 'independent synthetic uniform-plate fixture; arbitrary SI values'
# D = E*Te**3/[12(1-nu**2)] = 1; K = delta_rho*g = 4; alpha = 1.
ELASTIC = FlexureParameters('finite-plate-fixture', SOURCE, 12., 1., 0., 4., 1.)
CONTINUOUS = FlexureBoundary1D('continuous', 'continuous', SOURCE)


def operator(cells=8, length=8., *, origin=0., left='continuous', right='continuous', budget=None):
    return FiniteRegionFlexure(RegionalGrid1D(cells, length, origin), ELASTIC,
        FlexureBoundary1D(left, right, SOURCE), budget=budget)


def primitive(distance):
    """Real, signed primitive of G for the D=1, K=4, alpha=1 control."""
    if distance == 0.:
        return 0.
    r = abs(distance)
    return math.copysign(1., distance)*(1.-math.exp(-r)*math.cos(r))/8.


def green(distance, derivative):
    """Independent scalar Green function and its first three derivatives."""
    r = abs(distance); decay = math.exp(-r)
    sign = 1. if distance > 0. else -1. if distance < 0. else 0.
    if derivative == 0:
        return decay*(math.cos(r)+math.sin(r))/8.
    if derivative == 1:
        return -sign*decay*math.sin(r)/4.
    if derivative == 2:
        return decay*(math.sin(r)-math.cos(r))/4.
    return sign*decay*math.cos(r)/2.


class FiniteRegionFlexureTests(unittest.TestCase):
    def test_rectangular_patch_and_derivatives_match_independent_quadrature(self):
        plan = operator()
        self.assertEqual(plan.alpha_m, 1.)
        load = np.zeros(10); load[3] = 3.  # Pressure 3 on [3, 4].
        actual = plan.solve(load)
        centre = 3./4.*(1.-math.exp(-.5)*math.cos(.5))
        assert_allclose(actual[7, 0], centre, rtol=2e-14, atol=0.)
        assert_allclose(actual[7, [1, 3]], 0., rtol=0., atol=3e-15)
        for row in (0, 5, 7, 8, 16):
            x = row/2.
            breaks = [x] if 3. < x < 4. else None
            for derivative in range(4):
                expected = quad(lambda y: 3.*green(x-y, derivative), 3., 4.,
                    points=breaks, epsabs=2e-12, epsrel=2e-12)[0]
                with self.subTest(x=x, derivative=derivative):
                    assert_allclose(actual[row, derivative], expected, rtol=2e-12, atol=2e-13)
        # A positive pressure creates a negative forebulge; do not clip it.
        self.assertLess(actual[0, 0], 0.)

    def test_linear_fft_matches_direct_cell_integrals_without_wrapping(self):
        plan = operator()
        pressures = np.array([4., -2., 0., 3., 1., 0., -.5, 2.])
        actual = plan.solve(np.r_[pressures, 0., 0.])
        expected = [math.fsum(float(q)*(primitive(x-j)-primitive(x-j-1.))
                    for j, q in enumerate(pressures)) for x in np.arange(17)/2.]
        assert_allclose(actual[:, 0], expected, rtol=3e-13, atol=3e-14)
        one_edge = np.zeros(10); one_edge[0] = 1.
        response = plan.solve(one_edge)
        expected_far = primitive(8.)-primitive(7.)
        assert_allclose(response[-1, 0], expected_far, rtol=2e-12, atol=3e-15)
        self.assertGreater(abs(response[0, 0]), 100.*abs(response[-1, 0]))

    def test_explicit_uniform_and_unequal_far_halfline_loads(self):
        plan = operator()
        constant = plan.solve(np.full(10, 7.))
        assert_allclose(constant[:, 0], 7./4., rtol=2e-14, atol=3e-15)
        assert_allclose(constant[:, 1:], 0., rtol=0., atol=3e-15)
        load = np.zeros(10); load[-2:] = [2., 3.]
        actual = plan.solve(load)
        expected = []
        for x in np.arange(17)/2.:
            row = []
            for d in range(4):
                values = []
                for pressure, distance, direction in ((2., x, 1.), (3., 8.-x, -1.)):
                    e, c, s = math.exp(-distance), math.cos(distance), math.sin(distance)
                    derivative = (e*c/8., -e*(c+s)/8., e*s/4., e*(c-s)/4.)[d]
                    values.append(pressure*direction**d*derivative)
                row.append(math.fsum(values))
            expected.append(row)
        assert_allclose(actual, expected, rtol=2e-14, atol=3e-15)

    def test_constant_source_cell_subdivision_preserves_all_outputs(self):
        pressures = np.array([2., -1., 3., .5])
        coarse = operator(4, 8.).solve(np.r_[pressures, 1., -.5])
        fine = operator(8, 8.).solve(np.r_[np.repeat(pressures, 2), 1., -.5])
        # The same physical sample locations occur at every second fine row.
        assert_allclose(fine[::2], coarse, rtol=3e-13, atol=3e-14)

    def test_finite_large_restoring_coefficient_does_not_erase_far_load(self):
        parameters = FlexureParameters('range-control',SOURCE,1e308,1.,0.,1e308,1.)
        plan = FiniteRegionFlexure(RegionalGrid1D(1,1.),parameters,CONTINUOUS)
        result = plan.solve([0.,1e308,0.])
        assert_allclose(result[0,0],.5,rtol=2e-14,atol=0.)

    def test_crop_and_coordinate_translation_preserve_physical_response(self):
        pressures = np.array([0., 2., -1., 3., 0., 0., .5, 0.])
        plan = operator()
        original = plan.solve(np.r_[pressures, 0., 0.])
        extended = operator(15, 15., origin=-3.).solve(
            np.r_[np.zeros(3), pressures, np.zeros(4), 0., 0.])
        assert_allclose(extended[6:23], original, rtol=4e-13, atol=3e-14)
        shifted = operator(origin=1e9)
        assert_array_equal(shifted.solve(np.r_[pressures, 0., 0.]), original)
        self.assertNotEqual(shifted.operator_id, plan.operator_id)

    def test_omitted_load_bound_covers_an_added_finite_exterior_strip(self):
        plan = operator()
        pressure = 5.
        # Explicit extra source interval [-8,0]; inspect crop [2,6].
        expanded = operator(16, 16., origin=-8.)
        response = expanded.solve(np.r_[np.full(8, pressure), np.zeros(8), 0., 0.])
        crop = response[20:29, :3]
        bound = plan.omitted_load_bound_m(pressure, 0., 2., 2.)
        bounds = np.asarray(plan.omitted_response_bounds(pressure, 0., 2., 2.))
        expected_bound = pressure*math.exp(-2.)/(4.*math.sqrt(2.))
        self.assertGreaterEqual(bound, expected_bound*(1.-2e-15))
        assert_allclose(bound, expected_bound, rtol=3e-14, atol=0.)
        assert_allclose(bounds, [expected_bound, expected_bound*math.sqrt(2.),
            expected_bound*2.], rtol=3e-14, atol=0.)
        for derivative in range(3):
            with self.subTest(derivative=derivative):
                self.assertLessEqual(float(np.max(np.abs(crop[:, derivative]))), bounds[derivative])
                self.assertGreater(float(np.max(np.abs(crop[:, derivative]))), 0.)
        self.assertEqual(plan.omitted_load_bound_m(0., 0., 0., 0.), 0.)
        assert_array_equal(plan.omitted_response_bounds(0., 0., 0., 0.), [0., 0., 0.])

    def test_true_free_ends_admit_uniform_deflection_without_bending(self):
        plan = operator(left='free', right='free')
        result = plan.solve(np.r_[np.full(8, 3.), 0., 0.])
        assert_allclose(result[:, 0], .75, rtol=4e-13, atol=3e-14)
        assert_allclose(result[:, 1:], 0., rtol=0., atol=3e-14)
        # Clamping one genuine end changes the solution; these are not crops.
        mixed = operator(left='clamped', right='free').solve(np.r_[np.full(8, 3.), 0., 0.])
        assert_allclose(mixed[0, :2], 0., rtol=0., atol=3e-14)
        assert_allclose(mixed[-1, 2:], 0., rtol=0., atol=3e-14)
        self.assertGreater(abs(mixed[-1, 0]), .1)

    def test_true_clamped_ends_match_independent_symmetric_closed_form(self):
        plan = operator(left='clamped', right='clamped')
        result = plan.solve(np.r_[np.full(8, 3.), 0., 0.])
        # Even centre-based cosh/cos and sinh/sin solution, independent of the
        # implementation's four end-localised decaying modes and matrix inverse.
        b = 4.
        u = math.cosh(b)*math.cos(b); v = math.sinh(b)*math.sin(b)
        du = math.sinh(b)*math.cos(b)-math.cosh(b)*math.sin(b)
        dv = math.cosh(b)*math.sin(b)+math.sinh(b)*math.cos(b)
        determinant = u*dv-v*du
        a = -.75*dv/determinant; c = .75*du/determinant
        expected = []
        for y in np.arange(17)/2.-4.:
            u = math.cosh(y)*math.cos(y); v = math.sinh(y)*math.sin(y)
            du = math.sinh(y)*math.cos(y)-math.cosh(y)*math.sin(y)
            dv = math.cosh(y)*math.sin(y)+math.sinh(y)*math.cos(y)
            expected.append([.75+a*u+c*v, a*du+c*dv,
                -2*a*v+2*c*u, -2*a*dv+2*c*du])
        assert_allclose(result, expected, rtol=4e-12, atol=5e-14)
        assert_allclose(result[[0, -1], :2], 0., rtol=0., atol=3e-14)
        assert_allclose(result[:, 0], result[::-1, 0], rtol=4e-13, atol=3e-14)

    def test_invalid_boundaries_shapes_exterior_loads_and_short_physical_plate_refuse(self):
        for pair in (('continuous', 'free'), ('clamped', 'continuous'), ('periodic', 'periodic')):
            with self.subTest(pair=pair), self.assertRaises(TectonicsError):
                FlexureBoundary1D(*pair, SOURCE)
        plan = operator()
        for load in (np.zeros(8), np.zeros((1, 10)), np.full(10, math.nan), np.ma.array(np.zeros(10))):
            with self.subTest(shape=load.shape), self.assertRaises(TectonicsError):
                plan.solve(load)
        physical = operator(left='free', right='clamped')
        with self.assertRaisesRegex(TectonicsError, 'exterior'):
            physical.solve(np.r_[np.zeros(8), 1., 0.])
        with self.assertRaises(TectonicsError):
            physical.omitted_load_bound_m(1., 1., 0., 0.)
        for args in ((-1., 0., 0., 0.), (1., 0., -1., 0.), (math.inf, 0., 0., 0.)):
            with self.subTest(args=args), self.assertRaises(TectonicsError):
                plan.omitted_load_bound_m(*args)
        with self.assertRaisesRegex(TectonicsError, 'ill-conditioned'):
            operator(8, 1e-8, left='clamped', right='clamped')

    def test_immutable_outputs_operator_identity_and_budget_admission(self):
        tiny = WorkBudget(1)
        with self.assertRaises(MemoryLimitError): operator(budget=tiny)
        self.assertEqual(tiny.reserved_bytes, 0)
        budget = WorkBudget(1<<20)
        plan = operator(budget=budget)
        self.assertGreater(plan.setup_bytes, 0)
        self.assertEqual(budget.reserved_bytes, 0)
        self.assertGreater(plan.work_bytes((10,)), 0)
        source = np.zeros(10); source[3] = 3.
        result = plan.solve(source, budget=budget)
        before = result.copy(); source[:] = 0.
        assert_array_equal(result, before)
        with self.assertRaises(ValueError): result.setflags(write=True)
        with self.assertRaises(ValueError): result[0, 0] = 0.
        with self.assertRaises(FrozenInstanceError): plan.alpha_m = 2.
        with self.assertRaises(MemoryLimitError): plan.solve(source, budget=tiny)
        self.assertEqual(tiny.reserved_bytes, 0)
        self.assertEqual(budget.reserved_bytes, 0)
        self.assertEqual(plan.operator_id, operator().operator_id)
        self.assertNotEqual(plan.operator_id, operator(left='free', right='free').operator_id)


if __name__ == '__main__':
    unittest.main()
