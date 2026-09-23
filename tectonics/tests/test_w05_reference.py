"""Small independent controls for the W05 quadrature reference itself."""
import math
import unittest

import numpy as np
from numpy.testing import assert_allclose, assert_array_equal

from w05_reference import (boundary_exchanges, fault_elevation, footwall_means,
    hanging_wall_means, homogeneous_dilation, parcel_map)


class W05ReferenceTests(unittest.TestCase):
    def test_cell_means_tiny_front_and_finite_domain_exchange(self):
        geometry = dict(depth_m=3., decay_length_m=2., trace_m=.4)
        edges = np.linspace(1., 7., 17)
        a = .7
        before = hanging_wall_means(edges, 0., **geometry)
        after = hanging_wall_means(edges, a, **geometry)
        fixed = footwall_means(edges, crust_thickness_m=10., **geometry)
        assert_allclose(fixed+before, 10., rtol=0, atol=4e-15)
        assert_array_equal(before, hanging_wall_means(edges, 0., **geometry))
        self.assertEqual(boundary_exchanges(edges[0], edges[-1], 0., **geometry), (0., 0.))

        # Closed-form primitive only in this moderate-argument check, not helper.
        def primitive(x):
            s = max(x-geometry['trace_m'], 0.)
            return 3.*(s+2.*math.expm1(-s/2.))

        left, right = boundary_exchanges(edges[0], edges[-1], a, **geometry)
        self.assertGreater(left, 0.)
        self.assertLess(right, 0.)
        assert_allclose((left, right),
            (primitive(edges[0])-primitive(edges[0]-a),
             primitive(edges[-1]-a)-primitive(edges[-1])), rtol=2e-13, atol=2e-15)
        difference = math.fsum(float(h*dx) for h, dx in zip(after-before, np.diff(edges)))
        self.assertAlmostEqual(difference, left+right, delta=2e-14)

        # At 80 decay lengths the known omitted full-line deficit is <1e-33.
        far = np.array([-.6, .4+a+160.])
        initial = hanging_wall_means(far, 0., **geometry)[0]
        final = hanging_wall_means(far, a, **geometry)[0]
        loss = (initial-final)*np.diff(far)[0]
        self.assertAlmostEqual(loss, 3.*a, delta=2e-13)
        assert_allclose(boundary_exchanges(*far, a, **geometry), (0., -3.*a), rtol=2e-14, atol=0)

        # Direct series of the local exponential, avoiding primitive cancellation.
        tiny = 1e-10
        tiny_geometry = dict(depth_m=3., decay_length_m=2., trace_m=0.)
        cross = hanging_wall_means([-tiny, tiny], 0., **tiny_geometry)[0]
        expected = 3.*tiny/8.-3.*tiny*tiny/48.
        self.assertGreater(cross, 0.)
        self.assertAlmostEqual(cross/expected, 1., delta=3e-15)
        translated = hanging_wall_means([.125-tiny, .125+tiny], .125, **tiny_geometry)[0]
        represented = .125+tiny-(.125-tiny)
        # The translated endpoints need not be exactly symmetric in binary64.
        positive = .125+tiny-.125
        expected = 3.*positive*positive/(4.*represented)-3.*positive**3/(24.*represented)
        self.assertAlmostEqual(translated/expected, 1., delta=3e-15)

    def test_parcel_geometry_unit_jacobian_and_separate_dilation(self):
        geometry = dict(depth_m=3., decay_length_m=2., trace_m=.4)
        x0 = np.array([.5, 1.5, 4.])
        basal = fault_elevation(x0, **geometry)
        a = .7
        x, z = parcel_map(x0, basal, a, **geometry)
        assert_allclose(z, fault_elevation(x, **geometry), rtol=0, atol=4e-16)
        _, elevated = parcel_map(x0, basal+.2, a, **geometry)
        assert_allclose(elevated-z, .2, rtol=0, atol=4e-16)
        unchanged = parcel_map(x0, basal, 0., **geometry)
        assert_array_equal(unchanged[0], x0)
        assert_array_equal(unchanged[1], basal)

        point = np.array([1.5, -.3]); epsilon = 1e-5
        columns = []
        for direction in np.eye(2):
            plus = np.asarray(parcel_map(*(point+epsilon*direction), a, **geometry))
            minus = np.asarray(parcel_map(*(point-epsilon*direction), a, **geometry))
            columns.append((plus-minus)/(2.*epsilon))
        self.assertAlmostEqual(np.linalg.det(np.column_stack(columns)), 1., delta=3e-11)

        edges = np.array([-2., -.5, 0., 1., 3.])
        h = np.array([2., 0., 5., 1.]); beta = 1.7
        moved, diluted = homogeneous_dilation(edges, h, beta)
        assert_array_equal(moved, beta*edges)
        assert_array_equal(diluted, h/beta)
        assert_allclose(diluted*np.diff(moved), h*np.diff(edges), rtol=3e-16, atol=0)


if __name__ == '__main__':
    unittest.main()
