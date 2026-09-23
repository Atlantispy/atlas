"""Straight transform offsets and exact material-preserving side translations."""
import gc
import threading
import unittest
from concurrent.futures import CancelledError
from dataclasses import FrozenInstanceError
from unittest.mock import patch

import numpy as np

from atlas_tectonics.fault_slip import PreparedFaultSlip, SlipInterval
from atlas_tectonics.geometry import GeometryError, GeometryLimits, PlanarGeometry
from atlas_tectonics.resources import MemoryLimitError, WorkBudget


def parcels(frame='slip-frame'):
    return tuple(PlanarGeometry.polygon(xy, frame_id=frame) for xy in (
        [[-1000., -2000.], [0., -2000.], [0., 2000.], [-1000., 2000.]],
        [[0., -2000.], [1000., -2000.], [1000., 2000.], [0., 2000.]]))


def plan(polygons=None, histories=None, **kwargs):
    return PreparedFaultSlip(parcels() if polygons is None else polygons,
        histories or (SlipInterval(10., [0., -10.], [0., 20.], [0., 0.], 'prescribed-slip'),),
        parcel_ids=kwargs.pop('parcel_ids', ('west', 'east')), sides=kwargs.pop('sides', (-1, 1)),
        interface_point_m=kwargs.pop('interface_point_m', [0., 0.]),
        interface_normal=kwargs.pop('interface_normal', [1., 0.]),
        interface_id=kwargs.pop('interface_id', 'straight-fault'), time_s=kwargs.pop('time_s', 0.),
        source_id=kwargs.pop('source_id', 'slip-fixture-v1'), **kwargs)


class FaultSlipTests(unittest.TestCase):
    def test_real_opposing_slip_preserves_full_footprints(self):
        original = parcels()
        with plan(original) as p:
            initial = p.evaluate(0); end = p.evaluate(10)
            self.assertEqual(initial.polygons, original)
            self.assertEqual(end.polygons[0].bounds, (-1000., -2100., 0., 1900.))
            self.assertEqual(end.polygons[1].bounds, (0., -1800., 1000., 2200.))
            self.assertEqual(end.polygons[0]._geom.intersection(end.polygons[1]._geom).area, 0.)
            np.testing.assert_array_equal(end.translations_m, [[0., -100.], [0., 200.], [0., 0.]])
            np.testing.assert_array_equal(end.jacobian, [1., 1.])
            np.testing.assert_array_equal(end.deformation_gradient, np.tile(np.eye(2), (2, 1, 1)))
            self.assertEqual(sum(g.area_m2 for g in end.polygons), 8e6)
            self.assertEqual(end.parcel_ids, ('west', 'east'))
            self.assertEqual(end.interface_id, 'straight-fault')
            self.assertGreater(end.nbytes, sum(g.retained_bytes for g in end.polygons))
            self.assertEqual(p.descriptor()['execution_id'], p.execution_id)

    def test_common_frame_translation_and_zero_relative_normal_flux(self):
        base = SlipInterval(10, [0., -10.], [0., 20.], [0., 0.], 'base')
        common = np.array([3., 7.])
        shifted = SlipInterval(10, base.negative_velocity_m_s+common,
                               base.positive_velocity_m_s+common, common, 'common-frame')
        with plan(histories=(base,)) as p, plan(histories=(shifted,)) as q:
            a, b = p.evaluate(10), q.evaluate(10)
            np.testing.assert_array_equal(b.interface_point_m, [30., 70.])
            for original, moved in zip(a.polygons, b.polygons):
                np.testing.assert_array_equal(np.array(moved.bounds), np.array(original.bounds)+[30.,70.,30.,70.])
            normal = q.interface_normal
            self.assertEqual(float((shifted.negative_velocity_m_s-shifted.boundary_velocity_m_s)@normal), 0.)
            self.assertEqual(float((shifted.positive_velocity_m_s-shifted.boundary_velocity_m_s)@normal), 0.)

    def test_event_offsets_and_one_two_four_partitions(self):
        outputs = []
        for n in (1, 2, 4):
            histories = tuple(SlipInterval(8*k/n, [0., -10.], [0., 20.], [0., 0.], 'first')
                              for k in range(1, n+1))
            histories += tuple(SlipInterval(8+4*k/n, [0., 2.], [0., -3.], [0., 1.], 'second')
                               for k in range(1, n+1))
            with plan(histories=histories) as p: outputs.append(p.evaluate(12))
        for out in outputs:
            np.testing.assert_array_equal(out.translations_m, [[0., -72.], [0., 148.], [0., 4.]])
            self.assertEqual(out.polygons, outputs[0].polygons)

    def test_oblique_interface_tangential_motion(self):
        # Exact rational unit normal and tangent, avoiding a test fixture whose
        # rounded trigonometry places an authored corner across its interface.
        normal, tangent = np.array([.6, .8]), np.array([.8, -.6])
        west = PlanarGeometry.polygon([[-.6, -.8], [0., 0.], [.8, -.6], [.2, -1.4]], frame_id='oblique')
        east = PlanarGeometry.polygon([[0., 0.], [.6, .8], [1.4, .2], [.8, -.6]], frame_id='oblique')
        event = SlipInterval(1, -tangent, tangent, [0., 0.], 'oblique-tangent')
        with plan((west, east), (event,), interface_normal=normal) as p:
            out = p.evaluate(1)
            np.testing.assert_array_equal(out.jacobian, [1., 1.])
            self.assertAlmostEqual(sum(g.area_m2 for g in out.polygons), 2.)

    def test_reject_normal_opening_convergence_and_boundary_mismatch(self):
        cases = (([-1.,0.], [1.,0.], [0.,0.]), ([1.,0.], [-1.,0.], [0.,0.]),
                 ([0.,0.], [0.,0.], [1.,0.]))
        for negative, positive, boundary in cases:
            with self.subTest(negative=negative), self.assertRaisesRegex(GeometryError, 'normal opening'):
                plan(histories=(SlipInterval(1, negative, positive, boundary, 'bad-normal'),))

    def test_big_common_motion_cannot_hide_normal_drift(self):
        # The constituent roundoff gate alone admits a small residual next to
        # 1e10 m/s frame motion; the physical local-length gate still refuses it.
        event = SlipInterval(1, [1e10+1e-4, 0.], [1e10, 0.], [1e10, 0.], 'bad-frame-scaled-drift')
        with self.assertRaisesRegex(GeometryError, 'normal opening'): plan(histories=(event,))

    def test_wrong_sides_crossing_and_overlap_refuse(self):
        for sides in ((1, -1), (0, 1), (False, 1), [-1, 1]):
            with self.subTest(sides=sides), self.assertRaises(GeometryError): plan(sides=sides)
        crossing = PlanarGeometry.polygon([[-1.,-1.],[1.,-1.],[1.,1.],[-1.,1.]], frame_id='slip-frame')
        with self.assertRaisesRegex(GeometryError, 'crosses'): plan((crossing, parcels()[1]))
        west, _ = parcels()
        with self.assertRaisesRegex(GeometryError, 'overlap'): plan((west, west), sides=(-1, -1))

    def test_bad_source_frame_normal_and_ids(self):
        with self.assertRaises(ValueError): plan(source_id='')
        with self.assertRaises(ValueError): plan(interface_id='')
        with self.assertRaises(GeometryError): plan(parcel_ids=('same', 'same'))
        with self.assertRaisesRegex(GeometryError, 'one frame'): plan((parcels()[0], parcels('other')[1]))
        for normal in ([0.,0.], [2.,0.], [1.], [float('nan'),0.]):
            with self.subTest(normal=normal), self.assertRaises(ValueError): plan(interface_normal=normal)

    def test_immutable_inputs_outputs_and_identity(self):
        velocity = np.array([0., -10.]); event = SlipInterval(10, velocity, [0.,20.], [0.,0.], 'immutable')
        velocity[:] = 100.
        with plan(histories=(event,)) as p, plan(histories=(event,), source_id='other') as q:
            self.assertNotEqual(p.plan_id, q.plan_id)
            out = p.evaluate(10)
            for array in (event.negative_velocity_m_s, p.interface_normal, out.interface_point_m,
                          out.deformation_gradient, out.jacobian, out.translations_m):
                with self.assertRaises(ValueError): array.setflags(write=True)
                array.shape = (array.size,)
            self.assertEqual(out.deformation_gradient.shape, (2, 2, 2))
            with self.assertRaises(AttributeError): p.time_s = 2
            with self.assertRaises(FrozenInstanceError): event.end_time_s = 2
            self.assertEqual(out.translations_m[0, 1], -100.)
            desc = out.descriptor(); desc['time_s'] = 3
            self.assertEqual(out.descriptor()['time_s'], 10.)

    def test_cancel_budget_lifetime_and_closed_guards(self):
        cancel = threading.Event(); cancel.set(); budget = WorkBudget(8*1024**2)
        with self.assertRaises(CancelledError): plan(cancel=cancel, budget=budget)
        self.assertEqual(budget.reserved_bytes, 0)
        cancel.clear(); p = plan(budget=budget); baseline = budget.reserved_bytes
        cancel.set()
        with self.assertRaises(CancelledError): p.evaluate(3, cancel=cancel)
        self.assertEqual(budget.reserved_bytes, baseline)
        out = p.evaluate(3); p.close(); p.close()
        self.assertGreater(budget.reserved_bytes, 0)
        self.assertEqual(out.jacobian.tolist(), [1., 1.])
        with self.assertRaisesRegex(GeometryError, 'closed'): p.evaluate(0)
        del out; gc.collect(); self.assertEqual(budget.reserved_bytes, 0)
        tiny = WorkBudget(1)
        with patch('atlas_tectonics.fault_slip.ExecutionContext') as context:
            with self.assertRaises(MemoryLimitError): plan(budget=tiny)
            context.assert_not_called()
        self.assertEqual(tiny.reserved_bytes, 0)

    def test_limits_history_and_query_bounds(self):
        event = SlipInterval(10, [0.,0.], [0.,0.], [0.,0.], 'zero')
        for history in ((event, event), (event,)*257, [event]):
            with self.assertRaises(GeometryError): plan(histories=history)
        with self.assertRaises(GeometryError): plan(limits=GeometryLimits(max_vertices=9))
        with plan() as p:
            self.assertEqual(p._budget.max_bytes, 128*1024**2)
            for now in (-1, 11, float('nan'), True):
                with self.assertRaises(ValueError): p.evaluate(now)


if __name__ == '__main__': unittest.main()
