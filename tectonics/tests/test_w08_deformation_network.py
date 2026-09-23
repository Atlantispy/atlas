"""Independent finite-P1 controls; these are prescribed, not inferred geology."""
import gc
import math
import threading
import unittest
from concurrent.futures import CancelledError
from dataclasses import FrozenInstanceError
from unittest.mock import patch

import numpy as np

from atlas_tectonics.deformation_network import NodalMotionInterval, PreparedDeformationNetwork
from atlas_tectonics.geometry import GeometryError, GeometryLimits
from atlas_tectonics.resources import MemoryLimitError, WorkBudget


def mesh():
    vertices = np.array([[-2., -1.], [2., -1.], [2., 1.], [-2., 1.], [0., 0.]])*1000
    triangles = np.array([[0, 1, 4], [1, 2, 4], [2, 3, 4], [3, 0, 4]])
    return vertices, triangles


def plan(vertices=None, triangles=None, histories=None, **kwargs):
    x, t = mesh()
    x = x if vertices is None else vertices
    t = t if triangles is None else triangles
    histories = histories if histories is not None else (NodalMotionInterval(10., np.zeros_like(x), 'stationary'),)
    return PreparedDeformationNetwork(x, t, histories, time_s=kwargs.pop('time_s', 0.),
        frame_id=kwargs.pop('frame_id', 'synthetic-local-SI'), source_id=kwargs.pop('source_id', 'authored-network'),
        triangle_ids=kwargs.pop('triangle_ids', tuple('triangle-'+str(i) for i in range(len(t)))), **kwargs)


class DeformationNetworkTests(unittest.TestCase):
    def test_translation_and_exact_source_snapshot(self):
        x, _ = mesh(); velocity = np.tile([3., -7.], (len(x), 1))
        event = NodalMotionInterval(10, velocity, 'authored-translation')
        velocity[:] = 1e9
        with plan(histories=(event,)) as p:
            initial = p.evaluate(0); out = p.evaluate(10)
            np.testing.assert_array_equal(initial.vertices_m, x)
            np.testing.assert_array_equal(out.vertices_m, x+[30., -70.])
            np.testing.assert_array_equal(out.jacobian, np.ones(4))
            np.testing.assert_array_equal(out.deformation_gradient, np.tile(np.eye(2), (4, 1, 1)))
            self.assertEqual(out.triangle_ids, p.triangle_ids)
            self.assertEqual(out.frame_id, 'synthetic-local-SI')
            self.assertEqual(p.time_s, 0.)
            self.assertGreater(out.nbytes, 0)
            self.assertEqual(out.descriptor()['plan_id'], p.plan_id)

    def test_simple_shear_reference_area_and_thickness(self):
        x, _ = mesh(); velocity = np.c_[.025*x[:, 1], np.zeros(len(x))]
        with plan(histories=(NodalMotionInterval(10, velocity, 'affine-shear'),)) as p:
            out = p.evaluate(10)
            expected = np.array([[1., .25], [0., 1.]])
            np.testing.assert_allclose(out.deformation_gradient, np.tile(expected, (4, 1, 1)), atol=1e-14)
            np.testing.assert_allclose(out.jacobian, 1., atol=1e-14)
            np.testing.assert_allclose(30000/out.jacobian, 30000., atol=1e-9)
            self.assertAlmostEqual(math.fsum(g.area_m2 for g in out.polygons), 8e6)

    def test_finite_rotation_endpoint_and_chord_meaning(self):
        x, _ = mesh(); rotation = np.array([[0., -1.], [1., 0.]])
        velocity = (x @ rotation.T-x)/10
        with plan(histories=(NodalMotionInterval(10, velocity, 'prescribed-rotation-chord'),)) as p:
            end, middle = p.evaluate(10), p.evaluate(5)
            np.testing.assert_allclose(end.deformation_gradient, np.tile(rotation, (4, 1, 1)), atol=1e-14)
            np.testing.assert_allclose(end.jacobian, 1., atol=1e-14)
            np.testing.assert_allclose(middle.jacobian, .5, atol=1e-14)
            np.testing.assert_allclose(end.deformation_gradient.transpose(0, 2, 1) @ end.deformation_gradient,
                                       np.tile(np.eye(2), (4, 1, 1)), atol=1e-14)

    def test_oblique_distributed_stepover_source_challenge(self):
        # Fixed source fixture: affine far-field shear plus interior upward
        # displacement. Lower triangles dilate; upper triangles shorten. This is
        # a distributed restraining/releasing analogue, not a predicted fault.
        x, tri = mesh()
        velocity = np.c_[.025*x[:, 1], np.zeros(len(x))]
        velocity[4] += [10., 20.]
        with plan(histories=(NodalMotionInterval(10, velocity, 'stepover-interior-map-v1'),)) as p:
            out = p.evaluate(10)
            np.testing.assert_allclose(out.vertices_m, x+10*velocity, atol=1e-11)
            # Direct base*height areas: horizontal far-field top/bottom edges
            # move in x only; the common interior vertex shifts 200 m upwards.
            self.assertAlmostEqual(out.jacobian[0], 1.2, places=13)
            self.assertAlmostEqual(out.jacobian[2], .8, places=13)
            self.assertAlmostEqual(30000/out.jacobian[0], 25000., places=7)
            self.assertAlmostEqual(30000/out.jacobian[2], 37500., places=7)
            self.assertAlmostEqual(math.fsum(g.area_m2 for g in out.polygons), 8e6)
            for i in range(4):
                for j in range(i+1, 4):
                    self.assertEqual(out.polygons[i]._geom.intersection(out.polygons[j]._geom).area, 0.)
            for i, indices in enumerate(tri):
                coordinates = np.asarray(out.polygons[i]._geom.exterior.coords)[:-1]
                np.testing.assert_array_equal(coordinates, out.vertices_m[indices])

    def test_one_two_four_partitions_across_events(self):
        x, _ = mesh()
        first = np.c_[.0125*x[:, 1], np.zeros(len(x))]
        first[4] += [3., 5.]
        second = np.tile([-2., 4.], (len(x), 1))
        results = []
        for partitions in (1, 2, 4):
            histories = tuple(NodalMotionInterval(8*k/partitions, first, 'first')
                              for k in range(1, partitions+1))
            histories += tuple(NodalMotionInterval(8+4*k/partitions, second, 'second')
                               for k in range(1, partitions+1))
            with plan(histories=histories) as p: results.append(p.evaluate(12))
        for out in results[1:]:
            np.testing.assert_allclose(out.vertices_m, results[0].vertices_m, atol=1e-10, rtol=0)
            np.testing.assert_allclose(out.deformation_gradient, results[0].deformation_gradient, atol=1e-13, rtol=0)

    def test_nonaffine_boundary_refuses(self):
        x, _ = mesh(); velocity = np.zeros_like(x); velocity[0, 0] = 1.
        with self.assertRaisesRegex(GeometryError, 'boundary velocities'):
            plan(histories=(NodalMotionInterval(10, velocity, 'bad-boundary'),))

    def test_transient_inversion_with_positive_endpoint_refuses(self):
        x, _ = mesh()
        # diag(-2,-.5) has positive final determinant, but diagonal stretches
        # vanish at 1/3 and 2/3; endpoint-only checks would wrongly accept it.
        final = x @ np.diag([-2., -.5])
        with self.assertRaisesRegex(GeometryError, 'within interval'):
            plan(histories=(NodalMotionInterval(1, final-x, 'recovered-orientation'),))

    def test_midpoint_touch_then_recovery_refuses(self):
        x, _ = mesh()
        with self.assertRaisesRegex(GeometryError, 'within interval'):
            plan(histories=(NodalMotionInterval(1, -2*x, '180-degree-chord'),))

    def test_interior_triangle_inversion_refuses(self):
        x, _ = mesh(); v = np.zeros_like(x); v[4, 1] = 2000.
        with self.assertRaisesRegex(GeometryError, 'material triangle'):
            plan(histories=(NodalMotionInterval(1, v, 'interior-crosses-boundary'),))

    def test_invalid_meshes_refuse(self):
        x, t = mesh()
        cases = [(x, t[[0, 1, 2]]), (x, np.r_[t, t[:1]]),
                 (x, t[:, ::-1]), (np.r_[x, [[9., 9.]]], t),
                 (x, np.r_[t, [[0, 2, 4]]])]
        for vertices, triangles in cases:
            with self.subTest(triangles=triangles.tolist()), self.assertRaises(GeometryError):
                plan(vertices=vertices, triangles=triangles)
        duplicated = x.copy(); duplicated[4] = duplicated[0]
        with self.assertRaisesRegex(GeometryError, 'duplicate mesh vertices'): plan(vertices=duplicated)
        with self.assertRaisesRegex(GeometryError, 'integers'): plan(triangles=t.astype(float))

    def test_concavity_hole_and_nonconforming_node_refuse(self):
        # Remove a corner from a 3x3 grid triangulation: an L-shaped domain is
        # conforming but violates the deliberately narrow convex-boundary route.
        x = np.array([[0,0],[1,0],[2,0],[0,1],[1,1],[2,1],[0,2],[1,2]], dtype=float)
        t = np.array([[0,1,4],[0,4,3],[1,2,5],[1,5,4],[3,4,7],[3,7,6]])
        with self.assertRaisesRegex(GeometryError, 'convex'): plan(vertices=x, triangles=t)
        # A T-junction on the diagonal is geometrically tiled but not conforming.
        x = np.array([[0,0],[2,0],[2,2],[0,2],[1,1]], dtype=float)
        t = np.array([[0,1,2],[0,4,3],[4,2,3]])
        with self.assertRaises(GeometryError): plan(vertices=x, triangles=t)
        x = np.array([[0,0],[3,0],[3,3],[0,3],[1,1],[2,1],[2,2],[1,2]], dtype=float)
        t = np.array([[0,1,5],[0,5,4],[1,2,6],[1,6,5],
                      [2,3,7],[2,7,6],[3,0,4],[3,4,7]])
        with self.assertRaisesRegex(GeometryError, 'holes'): plan(vertices=x, triangles=t)

    def test_identity_source_frame_and_order(self):
        with plan() as a, plan(source_id='different-source') as b, plan(frame_id='different-frame') as c:
            self.assertNotEqual(a.plan_id, b.plan_id); self.assertNotEqual(a.plan_id, c.plan_id)
            self.assertIn('geos', a.descriptor()['runtime'])
            self.assertEqual(a.evaluate(0).state_id, a.evaluate(0).state_id)
        with plan(triangle_ids=('d','c','b','a')) as p:
            self.assertEqual(p.evaluate(0).triangle_ids, ('d','c','b','a'))
        with self.assertRaises(GeometryError): plan(triangle_ids=('a',)*4)
        with self.assertRaises(ValueError): plan(source_id='')

    def test_all_arrays_and_records_are_immutable(self):
        with plan() as p:
            state = p.evaluate(4)
            for array in (state.vertices_m, state.triangles, state.deformation_gradient,
                          state.jacobian, p.histories[0].velocity_m_s):
                with self.assertRaises(ValueError): array.setflags(write=True)
                array.shape = (array.size,)
            self.assertEqual(state.vertices_m.shape, (5, 2))
            with self.assertRaises(AttributeError): p.time_s = 3
            with self.assertRaises(FrozenInstanceError): state.time_s = 3
            descriptor = state.descriptor(); descriptor['time_s'] = 99
            self.assertEqual(state.descriptor()['time_s'], 4)

    def test_bounds_time_and_geometry_limits(self):
        x, _ = mesh(); event = NodalMotionInterval(10, np.zeros_like(x), 'zero')
        for events in ((), [event], (event, event), (event,)*257):
            with self.subTest(events=len(events)), self.assertRaises(GeometryError): plan(histories=events)
        with self.assertRaises(GeometryError): plan(limits=GeometryLimits(max_vertices=15))
        with plan() as p:
            for value in (-1, 11, float('nan'), True):
                with self.assertRaises(ValueError): p.evaluate(value)

    def test_cancel_refusal_and_no_leaked_lease(self):
        cancel = threading.Event(); cancel.set(); budget = WorkBudget(4*1024**2)
        with self.assertRaises(CancelledError): plan(cancel=cancel, budget=budget)
        self.assertEqual(budget.reserved_bytes, 0)
        cancel.clear()
        with plan(budget=budget) as p:
            baseline = budget.reserved_bytes; cancel.set()
            with self.assertRaises(CancelledError): p.evaluate(2, cancel=cancel)
            self.assertEqual(budget.reserved_bytes, baseline)
        self.assertEqual(budget.reserved_bytes, 0)

    def test_budget_preallocation_output_lifetime_and_close(self):
        tiny = WorkBudget(1)
        with patch('atlas_tectonics.deformation_network.read_array') as read:
            with self.assertRaises(MemoryLimitError): plan(budget=tiny)
            # The event record is built before plan admission; mesh arrays are not.
            self.assertLessEqual(read.call_count, 1)
        self.assertEqual(tiny.reserved_bytes, 0)
        budget = WorkBudget(4*1024**2); p = plan(budget=budget)
        out = p.evaluate(2); p.close(); p.close()
        self.assertGreater(budget.reserved_bytes, 0)
        self.assertEqual(out.vertices_m.shape, (5, 2))
        with self.assertRaisesRegex(GeometryError, 'closed'): p.evaluate(0)
        del out; gc.collect()
        self.assertEqual(budget.reserved_bytes, 0)
        with plan() as p: self.assertEqual(p._budget.max_bytes, 128*1024**2)

    def test_unresolvable_frame_translation_refuses(self):
        x, _ = mesh(); x += 1e16
        with self.assertRaisesRegex(GeometryError, 'unresolvable'):
            plan(vertices=x, histories=(NodalMotionInterval(1, np.full_like(x, 1e-6), 'lost-shift'),))

    def test_nonfinite_or_masked_source_refuses(self):
        x, _ = mesh(); bad = np.zeros_like(x); bad[0, 0] = np.nan
        for velocities in (bad, np.ma.array(x, mask=False), [[True, False]]*5):
            with self.assertRaises(ValueError): NodalMotionInterval(1, velocities, 'bad')


if __name__ == '__main__': unittest.main()
