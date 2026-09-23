"""Manufactured finite-element and conforming interface controls; no physics run."""
from concurrent.futures import CancelledError, ThreadPoolExecutor
import math
from threading import Event
import unittest

import numpy as np

from atlas_tectonics._validation import TectonicsError
from atlas_tectonics.resources import MemoryLimitError, WorkBudget
from atlas_tectonics.subduction_mesh import build_mesh, basis, quadrature, _triangle_geometry, _target


class SubductionMeshTests(unittest.TestCase):
    def test_grading_policy_is_explicit_and_preserved_by_wedge(self):
        for grading, divisor in (('interface-r3', 1.), ('corner-r4', 6000.), ('corner-r5', 60.)):
            with self.subTest(grading=grading), build_mesh(24., grading=grading) as mesh:
                self.assertTrue(mesh.grading_id.endswith(grading[-2:]))
                self.assertEqual(mesh.tip_target_m, 24000./divisor)
                with mesh.wedge() as wedge:
                    self.assertEqual(wedge.grading_id, mesh.grading_id)
                    self.assertEqual(wedge.tip_target_m, mesh.tip_target_m)
        for bad in ('automatic', None, []):
            with self.assertRaises(TectonicsError): build_mesh(24., grading=bad)

    def test_quadrature_integrates_all_barycentric_monomials_to_declared_degree(self):
        for degree, count in ((5, 7), (6, 12)):
            b, w = quadrature(degree)
            self.assertEqual(b.shape, (count, 3))
            self.assertTrue(np.all(w > 0.))
            self.assertAlmostEqual(float(w.sum()), 1., delta=1e-14)
            for i in range(degree+1):
                for j in range(degree+1-i):
                    for k in range(degree+1-i-j):
                        exact = 2.*math.factorial(i)*math.factorial(j)*math.factorial(k)/math.factorial(i+j+k+2)
                        value = float(w@(b[:, 0]**i*b[:, 1]**j*b[:, 2]**k))
                        self.assertAlmostEqual(value, exact, delta=1e-14)
        with self.assertRaises(TectonicsError):
            quadrature(7)

    def test_p2_nodal_basis_gradients_and_laplacian_reproduce_quadratic(self):
        nodes = np.array([[1., 0., 0.], [0., 1., 0.], [0., 0., 1.],
                         [.5, .5, 0.], [0., .5, .5], [.5, 0., .5]])
        np.testing.assert_array_equal(basis(nodes), np.eye(6))
        with build_mesh(30.) as mesh:
            b, _ = quadrature(6)
            n, dn, lap = basis(b, mesh.grad_lambda[:20])
            p = mesh.points[mesh.cells[:20]]; x, y = p[:, :, 0], p[:, :, 1]
            values = x*x+2*x*y-3*y*y+4*x-5*y+7
            xy = np.einsum('qi,eij->eqj', b, p[:, :3]); x, y = xy[:, :, 0], xy[:, :, 1]
            np.testing.assert_allclose(np.einsum('qi,ei->eq', n, values), x*x+2*x*y-3*y*y+4*x-5*y+7,
                                       atol=1e-8, rtol=2e-13)
            gradient = np.einsum('eqij,ei->eqj', dn, values)
            np.testing.assert_allclose(gradient[:, :, 0], 2*x+2*y+4, atol=2e-10, rtol=2e-13)
            np.testing.assert_allclose(gradient[:, :, 1], 2*x-6*y-5, atol=2e-10, rtol=2e-13)
            np.testing.assert_allclose(np.einsum('ei,ei->e', lap, values), -4., atol=2e-10, rtol=0.)
            np.testing.assert_allclose(dn.sum(axis=2), 0., atol=2e-13, rtol=0.)
            np.testing.assert_allclose(lap.sum(axis=1), 0., atol=2e-13, rtol=0.)
        with self.assertRaises(TectonicsError):
            basis([[1.1, -.1, 0.]])

    def test_region_areas_shared_p2_interfaces_and_wedge_global_maps(self):
        owner = WorkBudget(128*1024**2)
        with build_mesh(12., budget=owner) as mesh:
            self.assertGreater(owner.reserved_bytes, 0)
            self.assertTrue(np.all(mesh.area > 0.))
            for region, area in enumerate((180000., 31750., 184250.)):
                self.assertAlmostEqual(float(mesh.area[mesh.regions == region].sum()), area, delta=1e-8)
            p = mesh.points; c = mesh.cells
            for offset, (a, b) in enumerate(((0, 1), (1, 2), (2, 0)), 3):
                np.testing.assert_array_equal(p[c[:, offset]], .5*(p[c[:, a]]+p[c[:, b]]))
            usage = {}
            for cell, region in zip(c, mesh.regions):
                for a, b, m in ((0, 1, 3), (1, 2, 4), (2, 0, 5)):
                    key = tuple(sorted((cell[a], cell[b])))
                    usage.setdefault(key, []).append((int(region), int(cell[m])))
            interfaces = {(0, 1): 0, (0, 2): 0, (1, 2): 0}
            for edge, entries in usage.items():
                self.assertIn(len(entries), (1, 2))
                if len(entries) == 2:
                    self.assertEqual(entries[0][1], entries[1][1])
                    pair = tuple(sorted((entries[0][0], entries[1][0])))
                    if pair in interfaces:
                        interfaces[pair] += 1
                        coordinates = p[list(edge)]
                        np.testing.assert_array_equal(coordinates[:, 1],
                            np.full(2, 50.) if pair == (1, 2) else coordinates[:, 0])
            self.assertTrue(all(n > 0 for n in interfaces.values()))
            with mesh.wedge() as wedge:
                self.assertTrue(np.all(wedge.regions == 2))
                np.testing.assert_array_equal(wedge.points, p[wedge.global_nodes])
                np.testing.assert_array_equal(wedge.global_nodes[wedge.cells], c[wedge.global_elements])
                self.assertTrue(np.all(wedge.cells[:, :3] < wedge.vertex_count))
                self.assertTrue(np.all(wedge.cells[:, 3:] >= wedge.vertex_count))
                np.testing.assert_array_equal(wedge.pressure_nodes, wedge.points[:wedge.vertex_count])
        self.assertEqual(owner.reserved_bytes, 0)

    def test_locate_and_interpolate_are_exact_and_interface_temperature_is_continuous(self):
        with build_mesh(12.) as mesh:
            x, y = mesh.points.T
            field = 2.+3*x-4*y+5*x*y+.1*x*x-.2*y*y
            points = np.array([[0., 0.], [60., 60.], [216., 216.], [50., 50.], [300., 50.],
                               [660., 600.], [0., 600.], [87.25, 144.5], [234.2, 177.3]])
            x, y = points.T; exact = 2.+3*x-4*y+5*x*y+.1*x*x-.2*y*y
            np.testing.assert_allclose(mesh.interpolate(field, points), exact, atol=2e-9, rtol=3e-14)
            for region, pair in ((0, 2), (0, 1), (1, 2)):
                query = np.array([[60., 60.], [216., 216.]]) if pair == 2 and region == 0 else (
                    np.array([[10., 10.], [50., 50.]]) if pair == 1 else np.array([[50., 50.], [300., 50.]]))
                np.testing.assert_allclose(mesh.interpolate(field, query, region=region),
                    mesh.interpolate(field, query, region=pair), atol=2e-9, rtol=3e-14)
            with mesh.wedge() as wedge:
                query = np.array([[60., 60.], [400., 60.], [620., 550.]])
                np.testing.assert_allclose(wedge.interpolate(field[wedge.global_nodes], query),
                    mesh.interpolate(field, query, region=2), atol=1e-10, rtol=0.)
            for query, region in (([[20., 100.]], 2), ([[661., 40.]], None), ([[-1e-12, 0.]], None)):
                with self.assertRaises(TectonicsError):
                    mesh.locate(query, region=region)

    def test_adaptive_grading_and_refinement_increase_interface_resolution(self):
        counts = []
        for spacing in (16., 8.):
            with build_mesh(spacing) as mesh:
                centres = mesh.points[mesh.cells[:, :3]].mean(axis=1)
                d = np.minimum(np.abs(centres[:, 0]-centres[:, 1])/np.sqrt(2.), np.abs(centres[:, 1]-50.))
                self.assertLess(np.median(mesh.area[d < 8.]), .2*np.median(mesh.area[d > 100.]))
                counts.append((len(mesh.cells), np.count_nonzero(mesh.points[:, 0] == mesh.points[:, 1])))
        self.assertGreater(counts[1][0], counts[0][0])
        self.assertGreater(counts[1][1], counts[0][1])

    def test_normal_growth_and_remote_cap_follow_declared_global_refinement(self):
        for h in (6., 3., 1.5):
            for distance in (0., 5., 10., 20.):
                delta = distance/np.sqrt(2.)
                self.assertAlmostEqual(_target(100.+delta, 100.-delta, h), h+math.sqrt(h/6)*.25*distance, delta=1e-13)
            self.assertEqual(_target(150., 60., h), h+math.sqrt(h/6)*2.5)
            self.assertEqual(_target(325., 325., h), h+math.sqrt(h/6)*10.)
            self.assertEqual(_target(660., 0., h), 45.*math.sqrt(h/6))

    def test_remote_regions_also_refine(self):
        for point in ((660.,0.),(500.,300.),(325.,325.),(100.,10.)):
            sizes=[_target(*point,h) for h in (6.,3.,1.5,.05)]
            self.assertTrue(all(a>b for a,b in zip(sizes,sizes[1:])))
            self.assertLess(sizes[-1],sizes[0]/5.)

    def test_immutable_byte_arrays_close_thread_cancellation_and_budget_admission(self):
        owner = WorkBudget(128*1024**2)
        mesh = build_mesh(30., budget=owner)
        for name in ('points', 'cells', 'regions', 'area', 'grad_lambda', 'global_nodes', 'global_elements'):
            a = getattr(mesh, name)
            with self.assertRaises(ValueError):
                a.setflags(write=True)
            shape = a.shape; a.shape = (a.size,)
            self.assertEqual(getattr(mesh, name).shape, shape)
        with self.assertRaises(AttributeError):
            mesh.coordinate_system = 'metres'
        with ThreadPoolExecutor(max_workers=1) as pool:
            with self.assertRaises(TectonicsError):
                pool.submit(mesh.locate, [[60., 60.]]).result()
        cancelled = Event(); cancelled.set()
        with self.assertRaises(CancelledError):
            mesh.locate([[60., 60.]], cancel=cancelled)
        mesh.close(); mesh.close()
        with self.assertRaises(TectonicsError):
            mesh.locate([[60., 60.]])
        self.assertEqual(owner.reserved_bytes, 0)
        with self.assertRaises(CancelledError):
            build_mesh(10., budget=owner, cancel=cancelled)
        self.assertEqual(owner.reserved_bytes, 0)
        with self.assertRaises(MemoryLimitError):
            build_mesh(10., budget=WorkBudget(1024))
        for value in (0., -.1, float('nan'), True, .01, 201.):
            with self.assertRaises(TectonicsError):
                build_mesh(value)

    def test_retained_locator_footprint_is_warmed_and_survives_parent_close(self):
        owner = WorkBudget(128*1024**2)
        mesh = build_mesh(24., budget=owner)
        wedge = None
        try:
            before = owner.reserved_bytes
            old = sum(a.nbytes for a in mesh._arrays.values())+sum(
                1024*len(t.points) for _, t, _ in mesh._locators)+65536
            self.assertLess(before, old)
            payload = sum(a.nbytes for a in mesh._arrays.values())
            for _, tri, mapping in mesh._locators:
                self.assertIsNone(tri._qhull)
                self.assertIsNotNone(tri._transform)
                payload += mapping.nbytes+sum(v.nbytes for v in vars(tri).values()
                    if isinstance(v, np.ndarray))
            self.assertGreater(owner.reserved_bytes, payload)
            wedge = mesh.wedge()
            retained = owner.reserved_bytes-before
            tri = wedge._locators[0][1]
            snapshot = {key: id(value) for key, value in vars(tri).items()}
            mesh.close()
            self.assertEqual(owner.reserved_bytes, retained)
            wedge.locate([[60., 60.], [400., 60.], [620., 550.]])
            self.assertEqual(snapshot, {key: id(value) for key, value in vars(tri).items()})
            self.assertEqual(owner.reserved_bytes, retained)
            self.assertIsNone(tri._vertex_to_simplex)
            self.assertIsNone(tri._vertex_neighbor_vertices)
        finally:
            mesh.close()
            if wedge is not None: wedge.close()
        self.assertEqual(owner.reserved_bytes, 0)

    def test_negative_triangle_and_oversized_geometry_refuse_without_repair(self):
        with self.assertRaises(TectonicsError):
            _triangle_geometry(np.array([[0., 0.], [0., 1.], [1., 0.]]), np.array([[0, 1, 2]]))
        owner = WorkBudget(128*1024**2)
        with self.assertRaises(TectonicsError):
            build_mesh(.1, budget=owner)
        self.assertEqual(owner.reserved_bytes, 0)


if __name__ == '__main__':
    unittest.main()
