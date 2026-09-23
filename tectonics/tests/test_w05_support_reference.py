"""Small analytic and tightening controls for the independent support oracle."""
import math
import unittest

import numpy as np
from numpy.testing import assert_allclose, assert_array_equal
from scipy.integrate import quad

from w05_support_reference import (green_response, piecewise_constant_response,
    piecewise_constant_cell_mean, smooth_listric_response, smooth_listric_cell_mean)


class W05SupportReferenceTests(unittest.TestCase):
    def test_green_area_parity_and_uniform_full_line_load(self):
        physics = dict(rigidity_n_m=4., restoring_pa_per_m=4.)
        alpha = math.sqrt(2.)
        positive = green_response(.7, **physics)
        negative = green_response(-.7, **physics)
        assert_allclose(negative, positive*np.array([1., -1., 1.]), rtol=0, atol=0)
        for order, expected in ((0, .25), (2, 0.)):
            value, error = quad(lambda t: 2.*alpha*green_response(alpha*t, **physics)[order],
                                0., np.inf, epsabs=1e-12, epsrel=1e-12)
            self.assertAlmostEqual(value, expected, delta=error+2e-13)
        values, errors = piecewise_constant_response(.3, [-2., 0., 3.], [8., 8.],
            far_left_pa=8., far_right_pa=8., absolute_tolerances=(1e-10, 1e-10, 1e-10), **physics)
        assert_allclose(values, [2., 0., 0.], rtol=0, atol=2e-11)
        self.assertTrue(np.all(errors < 1e-10))
        mean, error = piecewise_constant_cell_mean(-.5, 1.3, [-2., 0., 3.], [8., 8.],
            far_left_pa=8., far_right_pa=8., absolute_tolerance_m=1e-8, **physics)
        self.assertAlmostEqual(mean, 2., delta=error+2e-12)
        self.assertLess(error, 1e-8)

    def test_strip_closed_form_zero_and_subdivision(self):
        physics = dict(rigidity_n_m=4., restoring_pa_per_m=4.)
        alpha = math.sqrt(2.); halfwidth = .8; pressure = 3.
        actual, errors = piecewise_constant_response(0., [-halfwidth, halfwidth], [pressure],
            absolute_tolerances=(1e-11, 1e-11, 1e-11), **physics)
        r = halfwidth/alpha
        expected = [pressure/4.*(1.-math.exp(-r)*math.cos(r)), 0.,
                    -2.*pressure*math.exp(-r)*math.sin(r)/(4.*alpha**2)]
        assert_allclose(actual, expected, rtol=0, atol=2e-12)
        split, _ = piecewise_constant_response(0., [-halfwidth, -.2, .3, halfwidth], [pressure]*3,
            absolute_tolerances=(1e-11, 1e-11, 1e-11), **physics)
        assert_allclose(actual, split, rtol=0, atol=2e-12)
        mean, error = piecewise_constant_cell_mean(-.3, .3, [-halfwidth, halfwidth], [pressure],
                                                   absolute_tolerance_m=1e-9, **physics)
        self.assertGreater(mean, 0.)
        self.assertLess(mean, actual[0])
        self.assertLess(error, 1e-9)
        zero, error = piecewise_constant_response(12., [-1., 1.], [0.], **physics)
        assert_array_equal(zero, 0.); assert_array_equal(error, 0.)

    def test_smooth_kilometre_scale_tightening_and_true_cell_mean(self):
        physics = dict(depth_m=10_000., decay_length_m=10_000., trace_m=0.,
            density_kg_m3=2800., gravity_m_s2=9.81,
            rigidity_n_m=70e9*5000.**3/(12.*(1.-.25**2)), restoring_pa_per_m=3300.*9.81)
        zero, errors = smooth_listric_response(0., 0., **physics)
        assert_array_equal(zero, 0.); assert_array_equal(errors, 0.)
        loose, loose_error = smooth_listric_response(1000., 1000., **physics)
        tight, tight_error = smooth_listric_response(1000., 1000., **physics,
            absolute_tolerances=(1e-8, 1e-12, 1e-16), relative_tolerance=1e-11)
        self.assertLess(tight[0], 0.)  # Unloading near the basin gives upward rebound.
        self.assertTrue(np.all(np.abs(loose-tight) <= loose_error+tight_error+1e-13))
        mean, uncertainty = smooth_listric_cell_mean(-250., 250., 1000., **physics,
                                                    absolute_tolerance_m=1e-6)
        refined, refined_error = smooth_listric_cell_mean(-250., 250., 1000., **physics,
            absolute_tolerance_m=1e-8, relative_tolerance=1e-11)
        self.assertLess(mean, 0.)
        self.assertLessEqual(uncertainty, 1e-6)
        self.assertLessEqual(refined_error, 1e-8)
        self.assertLessEqual(abs(mean-refined), uncertainty+refined_error)
        centre, _ = smooth_listric_response(0., 1000., **physics)
        self.assertGreater(abs(refined-centre[0]), 1e-4)
        shifted = dict(physics, trace_m=1_000_000.)
        translated, _ = smooth_listric_response(1_001_000., 1000., **shifted)
        assert_allclose(translated, loose, rtol=0, atol=0.)
        with self.assertRaises(ValueError):
            smooth_listric_cell_mean(0., 1., 1000., **physics, absolute_tolerance_m=.02)


if __name__ == '__main__':
    unittest.main()
