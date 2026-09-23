"""Independent endpoint material-transfer controls for moving planar regions."""
from concurrent.futures import CancelledError
from threading import Event
import unittest
from unittest import mock

import numpy as np
import shapely

from atlas_tectonics._validation import TectonicsError
from atlas_tectonics.geometry import PlanarGeometry, GeometryError
from atlas_tectonics.planar_exchange import planar_exchange
from atlas_tectonics.resources import WorkBudget, MemoryLimitError


def polygon(vertices, frame='synthetic-planar-metres'):
    return PlanarGeometry.polygon(vertices, frame_id=frame)


def box(x0, x1, y0=0., y1=1., frame='synthetic-planar-metres'):
    return polygon([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], frame)


def exchange(start, end, stock, *, regions=None, end_regions=None, deformation=None, **kwargs):
    if regions is None: regions = (box(0., 1.), box(1., 2.))
    if end_regions is None: end_regions = regions
    if deformation is None: deformation = np.tile(np.eye(2), (len(start), 1, 1))
    kwargs.setdefault('parcel_ids', tuple('parcel-'+str(i) for i in range(len(start))))
    kwargs.setdefault('region_ids', tuple('region-'+str(i) for i in range(len(regions))))
    kwargs.setdefault('exterior_id', 'retained-exterior')
    kwargs.setdefault('source_id', 'independent-exchange-controls')
    return planar_exchange(start, end, deformation, np.asarray(stock),
        start_regions=regions, end_regions=end_regions, **kwargs)


class PlanarExchangeTests(unittest.TestCase):
    def test_translation_two_regions_exact_origin_destination_and_signed_heat(self):
        result = exchange((box(0., 1.), box(1., 2.)), (box(.5, 1.5), box(1.5, 2.5)),
                          [[10., 20.], [-2., 6.]])
        np.testing.assert_array_equal(result.transfer[0], [[5., 5., 0.], [0., 10., 10.], [0., 0., 0.]])
        np.testing.assert_array_equal(result.transfer[1], [[-1., -1., 0.], [0., 3., 3.], [0., 0., 0.]])
        np.testing.assert_array_equal(result.initial_stock, [[10., 20., 0.], [-2., 6., 0.]])
        np.testing.assert_array_equal(result.final_stock, [[5., 15., 10.], [-1., 2., 3.]])
        np.testing.assert_array_equal(result.residual, [0., 0.])

    def test_donor_split_by_initial_region_before_motion(self):
        result = exchange((box(0., 2.),), (box(1., 3.),), [[12.]])
        np.testing.assert_array_equal(result.transfer[0], [[0., 6., 0.], [0., 0., 6.], [0., 0., 0.]])
        np.testing.assert_array_equal(result.initial_stock, [[6., 6., 0.]])
        np.testing.assert_array_equal(result.final_stock, [[0., 6., 6.]])

    def test_common_region_motion_and_common_coordinate_translation(self):
        outputs = []
        for offset in (0., 1e6):
            sources = (box(offset, offset+1.), box(offset+1., offset+2.))
            ends = (box(offset+.5, offset+1.5), box(offset+1.5, offset+2.5))
            outputs.append(exchange(sources, ends, [[10., 20.]], regions=sources, end_regions=ends))
        for result in outputs:
            np.testing.assert_array_equal(result.transfer[0], [[10., 0., 0.], [0., 20., 0.], [0., 0., 0.]])
        np.testing.assert_array_equal(outputs[0].transfer, outputs[1].transfer)

    def test_tangential_shear_has_no_cross_interface_transfer(self):
        source = box(0., 2., 0., 2.)
        end = polygon([(0., 0.), (2., 0.), (3., 2.), (1., 2.)])
        regions = (box(-10., 10., 0., 1.), box(-10., 10., 1., 2.))
        result = exchange((source,), (end,), [[24.]], regions=regions,
                          deformation=np.array([[[1., .5], [0., 1.]]]))
        np.testing.assert_array_equal(result.transfer[0], [[12., 0., 0.], [0., 12., 0.], [0., 0., 0.]])

    def test_exterior_return_and_retention_are_explicit_without_repeat_counting(self):
        start = (box(-1., 0.), box(0., 1.), box(1., 2.), box(5., 6.))
        end = (box(0., 1.), box(1., 2.), box(2., 3.), box(6., 7.))
        result = exchange(start, end, [[10., 20., 30., 40.]])
        expected = [[0., 20., 0.], [0., 0., 30.], [10., 0., 40.]]
        np.testing.assert_array_equal(result.transfer[0], expected)
        np.testing.assert_array_equal(result.initial_stock, [[20., 30., 50.]])
        np.testing.assert_array_equal(result.final_stock, [[10., 20., 70.]])
        repeated = exchange(start, end, [[10., 20., 30., 40.]])
        self.assertEqual(result.exchange_id, repeated.exchange_id)

    def test_changed_area_preserves_extensive_stock_and_outside_piece(self):
        result = exchange((box(-1., 3.),), (box(0., 2.),), [[40.]],
            deformation=np.array([[[.5, 0.], [0., 1.]]]))
        # Initial exterior [-1,0] returns to region 0 and [2,3] to region 1.
        np.testing.assert_array_equal(result.transfer[0], [[10., 0., 0.], [0., 10., 0.], [10., 10., 0.]])
        self.assertEqual(float(result.transfer.sum()), 40.)

    def test_signed_large_cancellation_uses_compensated_accounts(self):
        sources = tuple(box(i, i+1) for i in range(3))
        ends = tuple(box(i+.5, i+1.5) for i in range(3))
        result = exchange(sources, ends, [[1e20, 3., -1e20], [1., -2., 3.]],
                          regions=(box(-1., 5.),))
        np.testing.assert_array_equal(result.transfer[:, 0, 0], [3., 2.])
        np.testing.assert_array_equal(result.initial_stock[:, 0], [3., 2.])
        np.testing.assert_array_equal(result.final_stock[:, 0], [3., 2.])
        np.testing.assert_array_equal(result.residual, [0., 0.])

    def test_conforming_triangle_maps_with_regions_cutting_shared_edges(self):
        before = np.array([[0., 0.], [2., 0.], [2., 2.], [0., 2.], [1., 1.]])
        after = before.copy(); after[4] = [1.2, .9]
        triangles = ((0, 1, 4), (1, 2, 4), (2, 3, 4), (3, 0, 4))
        sources = tuple(polygon(before[list(t)]) for t in triangles)
        ends = tuple(polygon(after[list(t)]) for t in triangles)
        matrices = np.array([(after[list(t)][1:]-after[t[0]]).T
            @np.linalg.inv((before[list(t)][1:]-before[t[0]]).T) for t in triangles])
        whole = exchange(sources, ends, [[1., 1., 1., 1.]],
                         regions=(box(0., 2., 0., 2.),), deformation=matrices)
        np.testing.assert_array_equal(whole.transfer[0], [[4., 0.], [0., 0.]])
        halves = exchange(sources, ends, [[1., 1., 1., 1.], [-2., -2., -2., -2.]],
            regions=(box(0., 1., 0., 2.), box(1., 2., 0., 2.)), deformation=matrices)
        # Source half-pieces of the top/bottom triangles export 1/12 each;
        # the left triangle exports 1/36 of its initial extensive inventory.
        expected = np.array([[65/36, 7/36, 0.], [0., 2., 0.], [0., 0., 0.]])
        np.testing.assert_allclose(halves.transfer[0], expected, rtol=2e-14, atol=2e-15)
        np.testing.assert_allclose(halves.transfer[1], -2*expected, rtol=2e-14, atol=4e-15)
        np.testing.assert_allclose(halves.initial_stock[0], [2., 2., 0.], rtol=2e-14)
        np.testing.assert_allclose(halves.final_stock[0], [65/36, 79/36, 0.], rtol=2e-14, atol=2e-15)
        self.assertLess(max(halves.descriptor()['donor_fraction_max_residuals']), 128*np.finfo(float).eps)

    def test_zero_stock_donor_still_checks_endpoint_transfer_fractions(self):
        # The map/endpoint difference is within the geometric gate, but exceeds
        # the stricter existing conservative fraction gate. Zero stocks cannot
        # conceal that material-assignment discrepancy.
        with self.assertRaisesRegex(TectonicsError, 'endpoint fractions'):
            exchange((box(0., 1.),), (box(0., 1.+2e-11),), [[0.]],
                     regions=(box(0., .5), box(.5, 2.)))

    def test_bad_map_correspondence_overlap_and_frames_refuse(self):
        source = box(0., 1.)
        for f in ([[[1., 0.], [0., 0.]]], [[[-1., 0.], [0., 1.]]],
                  [[[1e-8, 0.], [0., 1e8]]], [[[float('nan'), 0.], [0., 1.]]]):
            with self.assertRaises(TectonicsError): exchange((source,), (source,), [[1.]], deformation=f)
        with self.assertRaisesRegex(GeometryError, 'endpoint'):
            exchange((source,), (box(0., 2.),), [[1.]])
        with self.assertRaisesRegex(GeometryError, 'overlap'):
            exchange((source,), (source,), [[1.]], regions=(source, box(.5, 1.5)))
        with self.assertRaisesRegex(GeometryError, 'overlap'):
            exchange((source, box(2., 3.)), (source, box(.5, 1.5)), [[1., 2.]])
        with self.assertRaisesRegex(GeometryError, 'frame'):
            exchange((source,), (box(0., 1., frame='wrong'),), [[1.]])
        with self.assertRaises(TectonicsError): exchange((source,), (source,), [[1.]], exterior_id='region-0')
        with self.assertRaises(TectonicsError): exchange((source,), (source,), [[1.]], parcel_ids=('a', 'b'))

    def test_immutable_outputs_metadata_and_source_identity(self):
        source = box(0., 1.)
        result = exchange((source,), (source,), [[1.]])
        for values in (result.transfer, result.initial_stock, result.final_stock, result.residual):
            with self.assertRaises(ValueError): values.setflags(write=True)
        with self.assertRaises(AttributeError): result.fields = 2
        descriptor = result.descriptor(); descriptor['region_ids'].append('bad')
        self.assertEqual(result.descriptor()['account_order'], ['region-0', 'region-1', 'retained-exterior'])
        self.assertEqual(result.nbytes, sum(map(len, (result._transfer, result._initial,
            result._final, result._residual, result._record))))
        other = exchange((source,), (source,), [[1.]], source_id='different')
        self.assertNotEqual(result.exchange_id, other.exchange_id)

    def test_budget_cancellation_and_generated_piece_limits_release(self):
        source = box(0., 1.)
        with self.assertRaises(MemoryLimitError):
            exchange((source,), (source,), [[1.]], budget=WorkBudget(1024))
        budget = WorkBudget(8*1024**2); stop = Event(); stop.set()
        with self.assertRaises(CancelledError): exchange((source,), (source,), [[1.]], cancel=stop, budget=budget)
        stop.clear(); real = shapely.intersection
        def cancel_after_intersection(*args, **kwargs):
            result = real(*args, **kwargs); stop.set(); return result
        with mock.patch.object(shapely, 'intersection', cancel_after_intersection):
            with self.assertRaises(CancelledError):
                exchange((source,), (source,), [[1.]], cancel=stop, budget=budget)
        self.assertEqual(budget.reserved_bytes, 0)
        import atlas_tectonics.planar_exchange as module
        with mock.patch.object(module, 'MAX_PIECES', 2):
            with self.assertRaisesRegex(GeometryError, 'generated-piece'):
                exchange((box(0., 3.),), (box(0., 3.),), [[3.]],
                    regions=(box(0., 1.), box(1., 2.), box(2., 3.)), budget=budget)
        self.assertEqual(budget.reserved_bytes, 0)
        exchange((source,), (source,), [[1.]], budget=budget)
        self.assertEqual(budget.reserved_bytes, 0)


if __name__ == '__main__': unittest.main()
