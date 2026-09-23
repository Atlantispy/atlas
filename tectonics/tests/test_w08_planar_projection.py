"""Independent W08 planar area controls and signed conservative accounts."""
from concurrent.futures import CancelledError
import math
from threading import Event
import unittest
from unittest import mock

import numpy as np
import shapely
from shapely.geometry import Polygon, MultiPolygon

from atlas_tectonics._validation import TectonicsError
from atlas_tectonics.geometry import PlanarGeometry, GeometryError
from atlas_tectonics.planar_projection import PreparedPlanarProjection
from atlas_tectonics.resources import WorkBudget, MemoryLimitError


def polygon(points, frame='synthetic-planar-metres', **kwargs):
    return PlanarGeometry.polygon(points, frame_id=frame, **kwargs)


def box(x0, x1, y0=0., y1=1., **kwargs):
    return polygon([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], **kwargs)


def prepare(sources, targets, **kwargs):
    kwargs.setdefault('source_ids', tuple('donor-'+str(i) for i in range(len(sources))))
    kwargs.setdefault('target_ids', tuple('cell-'+str(i) for i in range(len(targets))))
    kwargs.setdefault('source_id', 'synthetic-exact-area-controls')
    return PreparedPlanarProjection(sources, targets, **kwargs)


def clipped_area(vertices, rectangle):
    """Independent scalar half-plane clipping, then shoelace area; no GEOS."""
    current = [tuple(p) for p in vertices]
    for axis, boundary, sign in ((0, rectangle[0], 1), (0, rectangle[1], -1),
                                  (1, rectangle[2], 1), (1, rectangle[3], -1)):
        result = []
        if not current: return 0.
        previous = current[-1]
        for point in current:
            old_inside = sign*(previous[axis]-boundary) >= 0
            inside = sign*(point[axis]-boundary) >= 0
            if old_inside != inside:
                t = (boundary-previous[axis])/(point[axis]-previous[axis])
                result.append(tuple(previous[k]+t*(point[k]-previous[k]) for k in range(2)))
            if inside: result.append(point)
            previous = point
        current = result
    return abs(math.fsum(current[i][0]*current[(i+1) % len(current)][1]
                         -current[(i+1) % len(current)][0]*current[i][1]
                         for i in range(len(current))))/2 if current else 0.


class PlanarProjectionTests(unittest.TestCase):
    def test_analytic_sheared_rectangle_exact_areas(self):
        source = polygon([(0., 0.), (2., 0.), (3., 1.), (1., 1.)])
        with prepare((source,), (box(0., 1.), box(1., 2.), box(2., 3.))) as plan:
            np.testing.assert_array_equal(plan.donor, [0, 0, 0])
            np.testing.assert_array_equal(plan.target, [0, 1, 2])
            np.testing.assert_array_equal(plan.area_m2, [.5, 1., .5])
            np.testing.assert_array_equal(plan.fraction, [.25, .5, .25])
            result = plan.apply(np.array([[8.], [-12.]]))
            np.testing.assert_array_equal(result.inside, [[2., 4., 2.], [-3., -6., -3.]])
            np.testing.assert_array_equal(result.outside, [[0.], [0.]])
            np.testing.assert_array_equal(result.residual, [0., 0.])

    def test_analytic_45_degree_rotated_square_crop(self):
        r = math.sqrt(2.)
        source = polygon([(0., -r), (r, 0.), (0., r), (-r, 0.)])
        with prepare((source,), (box(-1., 1., -1., 1.),)) as plan:
            area = 8*(math.sqrt(2.)-1.)
            self.assertAlmostEqual(plan.area_m2[0], area, places=14)
            self.assertAlmostEqual(plan.fraction[0], area/4, places=14)
            result = plan.apply(np.array([[40.], [-20.]]))
            np.testing.assert_allclose(result.inside[:, 0], [10*area, -5*area], rtol=1e-14)
            np.testing.assert_allclose(result.outside[:, 0], [40-10*area, -20+5*area], rtol=1e-14)

    def test_8_16_32_affine_parcels_against_independent_clipping(self):
        angle = .41
        rotation = np.array([[math.cos(angle), -math.sin(angle)],
                             [math.sin(angle), math.cos(angle)]])
        transform = rotation@np.array([[.8, .6], [0., 1.2]])
        rectangles = tuple((x, x+.25, -.25, 1.75) for x in np.arange(-.25, 1.25, .25))
        targets = tuple(box(*r[:2], *r[2:]) for r in rectangles)
        totals = []
        for count in (8, 16, 32):
            coordinates = [np.array([(i/count, 0.), ((i+1)/count, 0.),
                ((i+1)/count, 1.), (i/count, 1.)])@transform.T for i in range(count)]
            sources = tuple(polygon(v) for v in coordinates)
            with prepare(sources, targets) as plan:
                expected = np.array([math.fsum(clipped_area(v, r) for v in coordinates)
                                     for r in rectangles])
                result = plan.apply(np.array([[g.area_m2 for g in sources]]))
                np.testing.assert_allclose(result.inside[0], expected, rtol=1e-13, atol=2e-15)
                totals.append(result.inside[0])
                self.assertLess(plan.candidate_count, count*len(targets))
        for total in totals[1:]: np.testing.assert_allclose(total, totals[0], rtol=1e-13, atol=2e-15)

    def test_per_donor_crops_disjoint_view_and_no_double_exports(self):
        sources = (box(0., 1.), box(1., 2.), box(3., 4.))
        stock = np.array([[10., 20., 30.], [-5., 12., -8.]])
        with prepare(sources, (box(.5, 1.5),)) as crop:
            result = crop.apply(stock)
            np.testing.assert_array_equal(result.inside, [[15.], [3.5]])
            np.testing.assert_array_equal(result.outside, [[5., 10., 30.], [-2.5, 6., -8.]])
            repeated = crop.apply(stock)
            self.assertEqual(repeated.projection_id, result.projection_id)
        with prepare(sources, (box(10., 11.),)) as disjoint:
            result = disjoint.apply(stock)
            self.assertEqual(len(disjoint.donor), 0)
            np.testing.assert_array_equal(result.inside, [[0.], [0.]])
            np.testing.assert_array_equal(result.outside, stock)
        with prepare(sources, (box(-1., 5.),)) as complete:
            result = complete.apply(stock)
            np.testing.assert_array_equal(result.inside, [[60.], [-1.]])
            self.assertFalse(np.any(result.outside))

    def test_signed_cancellation_compensated_and_source_order(self):
        sources = tuple(box(i, i+1) for i in range(6))
        stock = np.array([[1e20, 3., -1e20, -4., 11., -7.], [1., -2., 3., -4., 5., -6.]])
        order = [5, 2, 4, 0, 3, 1]
        with prepare(sources, (box(0., 6.),)) as first:
            a = first.apply(stock)
            np.testing.assert_array_equal(a.inside[:, 0], [3., -3.])
            np.testing.assert_array_equal(a.residual, [0., 0.])
            with prepare(tuple(sources[i] for i in order), (box(0., 6.),),
                         source_ids=tuple(first.source_ids[i] for i in order)) as second:
                b = second.apply(stock[:, order])
                np.testing.assert_array_equal(a.inside, b.inside)
                self.assertNotEqual(first.plan_id, second.plan_id)

    def test_holes_and_multipart_are_occupied_area_not_envelopes(self):
        ring = polygon([(0., 0.), (3., 0.), (3., 3.), (0., 3.)],
                       holes=([(1., 1.), (2., 1.), (2., 2.), (1., 2.)],))
        with prepare((ring,), (box(1., 2., 1., 2.),)) as hole:
            self.assertEqual(len(hole.donor), 0)
            np.testing.assert_array_equal(hole.apply(np.array([[8.]])).outside, [[8.]])
        native = MultiPolygon([Polygon([(0., 0.), (1., 0.), (1., 1.), (0., 1.)]),
                               Polygon([(3., 0.), (4., 0.), (4., 1.), (3., 1.)])])
        multi = PlanarGeometry.from_wkb(shapely.to_wkb(native), frame_id=ring.frame_id)
        with prepare((multi,), (box(0., 4.),)) as full:
            np.testing.assert_array_equal(full.area_m2, [2.])
            np.testing.assert_array_equal(full.outside_fraction, [0.])

    def test_boundary_contacts_are_zero_and_pairs_deterministic(self):
        sources = tuple(box(i, i+1) for i in range(32))
        with prepare(sources, sources) as first, prepare(sources, sources) as second:
            np.testing.assert_array_equal(first.donor, np.arange(32))
            np.testing.assert_array_equal(first.target, np.arange(32))
            self.assertEqual(first.candidate_count, 94)
            self.assertEqual(first.plan_id, second.plan_id)
            np.testing.assert_array_equal(first.fraction, np.ones(32))

    def test_positive_overlap_invalid_frames_ids_types_refuse_and_release(self):
        source = box(0., 1.); overlap = box(.5, 1.5); budget = WorkBudget(8*1024**2)
        for sources, targets in (((source, overlap), (source,)),
                                 ((source,), (source, overlap))):
            with self.assertRaisesRegex(GeometryError, 'overlap'):
                prepare(sources, targets, budget=budget)
            self.assertEqual(budget.reserved_bytes, 0)
        with self.assertRaisesRegex(GeometryError, 'frame'):
            prepare((source,), (box(0., 1., frame='other'),))
        with self.assertRaises(GeometryError): prepare((source,), (source,), source_ids=('x', 'y'))
        with self.assertRaises(GeometryError): prepare((source, box(2., 3.)), (source,), source_ids=('x', 'x'))
        with self.assertRaises(GeometryError): prepare((source,)*4097, (source,))
        with self.assertRaises(GeometryError): prepare([source], (source,))
        with self.assertRaises(GeometryError):
            prepare((source,), (PlanarGeometry.polyline([(0., 0.), (1., 1.)], frame_id=source.frame_id),))

    def test_geometry_vertex_candidate_and_overlay_bounds(self):
        from dataclasses import replace
        import atlas_tectonics.planar_projection as module
        source = box(0., 1.)
        for change in (dict(max_vertices=9), dict(max_overlay_pairs=24)):
            limits = replace(module.DEFAULT_GEOMETRY_LIMITS, **change)
            with mock.patch.object(module, 'DEFAULT_GEOMETRY_LIMITS', limits):
                with self.assertRaises(GeometryError): prepare((source,), (source,))
        limits = replace(module.DEFAULT_GEOMETRY_LIMITS, max_hits=1)
        with mock.patch.object(module, 'DEFAULT_GEOMETRY_LIMITS', limits):
            with self.assertRaises(GeometryError):
                prepare((box(0., 2.),), (box(0., 1.), box(1., 2.)))
            with self.assertRaisesRegex(GeometryError, 'topology candidate'):
                prepare((box(0., 1.), box(1., 2.), box(2., 3.)), (box(10., 11.),))

    def test_budget_retained_until_close_and_apply_refusal_has_no_leak(self):
        source = box(0., 1.)
        with self.assertRaises(MemoryLimitError): prepare((source,), (source,), budget=WorkBudget(1))
        budget = WorkBudget(128*1024)
        plan = prepare((source,), (source,), budget=budget)
        retained = budget.reserved_bytes
        self.assertGreater(retained, plan.nbytes)
        with self.assertRaises(MemoryLimitError): plan.apply(np.ones((10000, 1)))
        self.assertEqual(budget.reserved_bytes, retained)
        result = plan.apply(np.ones((2, 1)))
        self.assertEqual(budget.reserved_bytes, retained)
        plan.close(); plan.close()
        self.assertEqual(budget.reserved_bytes, 0)
        np.testing.assert_array_equal(result.inside, [[1.], [1.]])
        with self.assertRaises(GeometryError): plan.apply(np.ones((1, 1)))

    def test_cancellation_initial_mid_geometry_and_apply(self):
        source = box(0., 1.); stop = Event(); stop.set(); budget = WorkBudget(8*1024**2)
        with self.assertRaises(CancelledError): prepare((source,), (source,), cancel=stop, budget=budget)
        stop.clear(); real = shapely.intersection
        def interrupt(*args, **kwargs):
            result = real(*args, **kwargs); stop.set(); return result
        with mock.patch.object(shapely, 'intersection', interrupt):
            with self.assertRaises(CancelledError): prepare((source,), (source,), cancel=stop, budget=budget)
        self.assertEqual(budget.reserved_bytes, 0)
        with prepare((source,), (source,), budget=budget) as plan:
            with self.assertRaises(CancelledError): plan.apply(np.ones((1, 1)), cancel=stop)
            with self.assertRaises(GeometryError): plan.apply(np.ones((1, 1)), cancel=object())
        self.assertEqual(budget.reserved_bytes, 0)

    def test_immutable_input_results_descriptors_and_identity(self):
        source = box(0., 1.)
        with prepare((source,), (source,)) as plan:
            values = np.ones((2, 1)); result = plan.apply(values); values[:] = 4.
            np.testing.assert_array_equal(result.inside, [[1.], [1.]])
            for a in (result.inside, result.outside, result.residual, plan.fraction, plan.donor):
                with self.assertRaises(ValueError): a.setflags(write=True)
            with self.assertRaises(AttributeError): plan.source_id = 'altered'
            with self.assertRaises(AttributeError): result.fields = 3
            record = plan.descriptor(); record['runtime']['geos'] = 'changed'
            self.assertNotEqual(plan.descriptor()['runtime']['geos'], 'changed')
            self.assertEqual(result.nbytes, sum(map(len, (result._inside, result._outside,
                                                         result._residual, result._record))))
            with prepare((source,), (source,), source_id='other') as other:
                self.assertNotEqual(plan.plan_id, other.plan_id)
            with prepare((source,), (box(0., .5),)) as other:
                self.assertNotEqual(plan.plan_id, other.plan_id)

    def test_numeric_shape_finiteness_and_unresolvable_stocks_refuse(self):
        source = box(0., 1.)
        with prepare((source,), (box(0., .5),)) as plan:
            for values in (np.ones(1), np.ones((1, 2)), np.empty((0, 1)), [[True]],
                           [[float('nan')]], [[float('inf')]], [[np.nextafter(0., 1.)]]):
                with self.assertRaises(TectonicsError): plan.apply(values)
            np.testing.assert_array_equal(plan.apply(np.zeros((1, 1))).residual, [0.])


if __name__ == '__main__': unittest.main()
