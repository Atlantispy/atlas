"""Manufactured curl, flux and lifecycle controls for the thermal-only transfer."""
from concurrent.futures import CancelledError
from threading import Event
import unittest
from unittest import mock

import numpy as np

from atlas_tectonics._validation import TectonicsError
from atlas_tectonics.resources import WorkBudget, MemoryLimitError
from atlas_tectonics.subduction_mesh import P2Mesh, _triangle_geometry, basis, quadrature
from atlas_tectonics.subduction_transport import (PreparedSubductionTransport,
    _potential_gradient, _p3_derivatives, _P2_BARY)


def mesh_fixture(budget=None, *, vertices=None, triangles=None):
    owner = WorkBudget(32*1024**2) if budget is None else budget
    if vertices is None:
        vertices = np.array([[0., 0.], [1., 0.], [1., 1.], [0., 1.], [.5, .5]])
        triangles = np.array([[0, 1, 4], [1, 2, 4], [2, 3, 4], [3, 0, 4]])
    points = list(map(tuple, vertices)); edges = {}; cells = []
    for triangle in triangles:
        cell = list(triangle)
        for i, j in ((0, 1), (1, 2), (2, 0)):
            key = tuple(sorted((int(triangle[i]), int(triangle[j]))))
            if key not in edges:
                edges[key] = len(points); points.append(tuple(vertices[list(key)].mean(axis=0)))
            cell.append(edges[key])
        cells.append(cell)
    points = np.array(points); cells = np.array(cells)
    area, gradients = _triangle_geometry(points, cells)
    arrays = dict(points=points, cells=cells, regions=np.full(len(cells), 2), area=area,
        grad_lambda=gradients, global_nodes=np.arange(len(points)), global_elements=np.arange(len(cells)))
    return P2Mesh(arrays, len(vertices), (), 1., owner)


def polynomial(xy):
    x, y = xy[..., 0], xy[..., 1]
    return np.stack((2*x*y+4*y, -3*x*x-y*y+.7), axis=-1)


def streamfunction(xy):
    x, y = xy[..., 0], xy[..., 1]
    return x**3+x*y*y+2*y*y-.7*x


def independent_divergence(mesh, values):
    bary, _ = quadrature(6)
    _, derivatives, _ = basis(bary, mesh.grad_lambda)
    return np.einsum('eni,eqni->eq', values, derivatives)


class SubductionTransportTests(unittest.TestCase):
    def test_graded_boundary_closes_over_longest_edge_not_tiny_corner(self):
        width, tiny = 512., 2.**-12
        vertices = np.array([[0., 0.], [width, 0.], [width, width],
            [0., width], [0., tiny], [width/2, width/2]])+np.array([50., 50.])
        triangles = np.array([[0, 1, 5], [1, 2, 5], [2, 3, 5], [3, 4, 5], [4, 0, 5]])
        edge_derivative = np.array([[-5.5, 9., -4.5, 1.],
            [.125, -3.375, 3.375, -.125], [-1., 4.5, -9., 5.5]])
        with mesh_fixture(vertices=vertices, triangles=triangles) as mesh, PreparedSubductionTransport(mesh) as plan:
            lengths = []
            for element, edge in plan._boundary:
                i, j = ((0, 1), (1, 2), (2, 0))[edge]
                xy = mesh.points[mesh.cells[element, [i, j]]]
                lengths.append(np.linalg.norm(xy[1]-xy[0]))
            self.assertEqual(lengths[-1], max(lengths))
            self.assertEqual(min(lengths), tiny)
            source = polynomial((mesh.points[mesh.cells]-50.)/width)
            potential, net, flux_scale, mode = plan._boundary_values(source, None, None)
            self.assertEqual(mode, 'integrated-P2-normal-trace')
            self.assertLessEqual(abs(net), 128*np.finfo(float).eps*flux_scale)
            # Test the integrated trace directly, independently of the scalar
            # solve/interior bubble: closure round-off must not land on tiny.
            errors = []
            for element, edge in plan._boundary:
                i, j = ((0, 1), (1, 2), (2, 0))[edge]
                xy = mesh.points[mesh.cells[element, [i, j]]]
                tangent = xy[1]-xy[0]; length = np.linalg.norm(tangent)
                normal = np.array([tangent[1], -tangent[0]])/length
                local = potential[plan._cells[element, [i, 3+2*edge, 4+2*edge, j]]]
                actual = edge_derivative@(local-local[0])/length
                expected = source[element, [i, edge+3, j]]@normal
                errors.append(float(np.max(np.abs(actual-expected))))
            self.assertLess(max(errors), 1e-10)

    def test_tiny_translated_element_derivative_is_constant_gauge_invariant(self):
        # A translated, skewed 0.25 m-scale element in kilometre coordinates.
        # Dyadic coefficients preserve every local difference exactly even after
        # adding a large gauge: this isolates derivative cancellation from
        # information already rounded away in supplied nodal data.
        scale = 2.**-12
        vertices = np.array([[0., 0.], [3., 1.], [1., 2.]])*scale
        translated = vertices+np.array([512., -256.])
        _, gradients = _triangle_geometry(translated, np.array([[0, 1, 2]]))
        p3_bary = np.array([[1., 0., 0.], [0., 1., 0.], [0., 0., 1.],
            [2/3, 1/3, 0.], [1/3, 2/3, 0.], [0., 2/3, 1/3],
            [0., 1/3, 2/3], [1/3, 0., 2/3], [2/3, 0., 1/3], [1/3, 1/3, 1/3]])
        # psi = 3*x+6*y has exactly representable values at these P3 nodes.
        nodal = (p3_bary@np.array([0., 15., 15.])*scale)[None, :]
        derivatives = _p3_derivatives(_P2_BARY)
        expected = np.tile([3., 6.], (1, 6, 1))
        reference = _potential_gradient(derivatives, gradients, nodal)
        np.testing.assert_allclose(reference, expected, rtol=0., atol=2e-14)
        for gauge in (0., 2.**20, -2.**20):
            shifted = nodal+gauge
            np.testing.assert_array_equal(shifted-shifted[:, :1], nodal)
            np.testing.assert_array_equal(_potential_gradient(derivatives, gradients, shifted), reference)
        # A pure gauge must be exactly annihilated, not become a spurious flux.
        np.testing.assert_array_equal(_potential_gradient(derivatives, gradients,
            np.full((1, 10), 2.**20)), np.zeros((1, 6, 2)))

    def test_quadratic_divergence_free_field_is_preserved(self):
        with mesh_fixture() as mesh, PreparedSubductionTransport(mesh) as plan:
            supplied = polynomial(mesh.points[mesh.cells]); before = supplied.copy()
            result = plan.evaluate(supplied)
            np.testing.assert_allclose(result.element_node_velocity, supplied, rtol=3e-13, atol=3e-13)
            np.testing.assert_array_equal(supplied, before)
            self.assertLess(float(np.max(np.abs(independent_divergence(mesh, result.velocity)))), 2e-12)
            stats = result.diagnostics()
            self.assertLess(stats['interior_normal_max_jump'], 2e-12)
            self.assertLess(stats['boundary_normal_max_change'], 2e-12)
            self.assertLess(abs(stats['output_boundary_net_flux']), 2e-12)
            self.assertEqual(stats['boundary_mode'], 'integrated-P2-normal-trace')
            self.assertFalse(stats['mechanical_field_replaced'])

    def test_divergent_interior_perturbation_corrected_and_normal_trace_preserved(self):
        with mesh_fixture() as mesh, PreparedSubductionTransport(mesh) as plan:
            values = np.tile([1., .2], (len(mesh.points), 1))
            xy = mesh.points
            interior = (xy[:, 0] > 0) & (xy[:, 0] < 1) & (xy[:, 1] > 0) & (xy[:, 1] < 1)
            values[interior, 0] += .3+xy[interior, 0]
            values[interior, 1] += .2-xy[interior, 1]
            source = values[mesh.cells]
            self.assertGreater(float(np.max(np.abs(independent_divergence(mesh, source)))), 1.)
            result = plan.evaluate(source)
            self.assertLess(float(np.max(np.abs(independent_divergence(mesh, result.velocity)))), 2e-12)
            stats = result.diagnostics()
            self.assertGreater(stats['velocity_change_l2'], .01)
            self.assertLess(stats['boundary_normal_max_change'], 2e-12)
            self.assertLess(stats['interior_normal_max_jump'], 2e-12)
            self.assertGreater(stats['input_divergence_rms_per_km'], 1.)
            self.assertLess(stats['divergence_rms_per_km'], 2e-12)

    def test_constant_and_zero_fields_preserved_without_heat_source(self):
        with mesh_fixture() as mesh, PreparedSubductionTransport(mesh) as plan:
            for constant in ([2., -.7], [0., 0.]):
                values = np.tile(constant, (len(mesh.cells), 6, 1))
                result = plan.evaluate(values)
                np.testing.assert_allclose(result.velocity, values, rtol=0., atol=4e-14)
                self.assertLess(np.max(np.abs(independent_divergence(mesh, result.velocity))), 2e-13)

    def test_explicit_analytic_boundary_matches_cubic_streamfunction(self):
        with mesh_fixture() as mesh, PreparedSubductionTransport(mesh) as plan:
            supplied = polynomial(mesh.points[mesh.cells])
            integrated = plan.evaluate(supplied)
            analytic = plan.evaluate(supplied, boundary_streamfunction=streamfunction)
            np.testing.assert_allclose(analytic.velocity, supplied, rtol=3e-13, atol=3e-13)
            np.testing.assert_allclose(analytic.velocity, integrated.velocity, rtol=3e-13, atol=3e-13)
            self.assertEqual(analytic.diagnostics()['boundary_mode'], 'explicit-streamfunction')

    def test_incompatible_material_net_flux_refused_not_distributed_away(self):
        with mesh_fixture() as mesh, PreparedSubductionTransport(mesh) as plan:
            supplied = np.zeros((len(mesh.cells), 6, 2)); supplied[:, :, 0] = mesh.points[mesh.cells, 0]
            with self.assertRaisesRegex(TectonicsError, 'incompatible net material flux'):
                plan.evaluate(supplied)
            # Explicit alternate boundary authority is labelled, and its conflict
            # with the input field remains measured rather than hidden.
            result = plan.evaluate(supplied, boundary_streamfunction=lambda xy: np.zeros(len(xy)))
            self.assertAlmostEqual(result.diagnostics()['input_boundary_net_flux'], 1.)
            self.assertAlmostEqual(result.diagnostics()['output_boundary_net_flux'], 0.)
            self.assertGreater(result.diagnostics()['boundary_normal_max_change'], .9)
            self.assertEqual(result.diagnostics()['boundary_mode'], 'explicit-streamfunction')

    def test_boundary_quadratic_normal_trace_is_preserved_at_intermediate_points(self):
        with mesh_fixture() as mesh, PreparedSubductionTransport(mesh) as plan:
            source = polynomial(mesh.points[mesh.cells]); result = plan.evaluate(source)
            for element, edge in plan._boundary:
                i, j = ((0, 1), (1, 2), (2, 0))[edge]
                p, q = mesh.points[mesh.cells[element, [i, j]]]
                tangent = q-p; normal = np.array([tangent[1], -tangent[0]])/np.linalg.norm(tangent)
                t = np.array([.07, .29, .61, .93]); bary = np.zeros((len(t), 3))
                bary[:, i] = 1-t; bary[:, j] = t
                weights = basis(bary)
                expected = polynomial((1-t[:, None])*p+t[:, None]*q)@normal
                np.testing.assert_allclose((weights@result.velocity[element])@normal, expected, rtol=2e-13, atol=3e-13)

    def test_lazy_factor_reuse_release_and_immutable_output(self):
        import atlas_tectonics.subduction_transport as module
        budget = WorkBudget(16*1024**2)
        with mesh_fixture(budget) as mesh:
            mesh_bytes = budget.reserved_bytes
            with mock.patch.object(module, 'splu', wraps=module.splu) as factored:
                with PreparedSubductionTransport(mesh, budget=budget) as plan:
                    self.assertEqual(factored.call_count, 0); base = budget.reserved_bytes
                    values = polynomial(mesh.points[mesh.cells]); first = plan.evaluate(values)
                    self.assertEqual(factored.call_count, 1)
                    second = plan.evaluate(values)
                    self.assertEqual(factored.call_count, 1)
                    self.assertEqual(first.result_id, second.result_id)
                    self.assertGreater(budget.reserved_bytes, base)
                    plan.release_factor(); self.assertEqual(budget.reserved_bytes, base)
                    third = plan.evaluate(values); self.assertEqual(factored.call_count, 2)
                    np.testing.assert_array_equal(first.velocity, third.velocity)
                    for array in (first.velocity, first.streamfunction):
                        with self.assertRaises(ValueError): array.setflags(write=True)
                    changed = first.diagnostics(); changed['boundary_mode'] = 'bad'
                    self.assertNotEqual(first.diagnostics()['boundary_mode'], 'bad')
                    self.assertEqual(first.nbytes, len(first._velocity)+len(first._potential)+len(first._record))
                self.assertEqual(budget.reserved_bytes, mesh_bytes)
                with self.assertRaises(TectonicsError): plan.evaluate(values)
        self.assertEqual(budget.reserved_bytes, 0)

    def test_retained_lease_compacts_to_owned_storage_after_assembly(self):
        budget = WorkBudget(16*1024**2)
        with mesh_fixture(budget) as mesh:
            before = budget.reserved_bytes
            with PreparedSubductionTransport(mesh, budget=budget) as plan:
                payload = sum(a.nbytes for a in (plan._cells, plan._points, plan._interior,
                    plan._fixed, plan._free, plan._bary, plan._weights, plan._p2, plan._dq, plan._dn))
                payload += sum(a.nbytes for matrix in (plan._matrix, plan._boundary_matrix)
                    for a in (matrix.data, matrix.indices, matrix.indptr))
                self.assertGreaterEqual(plan.retained_payload_bytes, payload)
                self.assertGreater(plan.retained_allowance_bytes, plan.retained_payload_bytes)
                self.assertEqual(budget.reserved_bytes-before, plan.retained_allowance_bytes)
                self.assertLess(plan.retained_allowance_bytes, 4000*len(mesh.cells)+256*len(mesh.points)+65536)
                self.assertEqual(plan.budget.statistics()['categories']['subduction-transport-assembly'], 0)
                result = plan.evaluate(polynomial(mesh.points[mesh.cells]))
                plan.release_factor()
                self.assertEqual(budget.reserved_bytes-before, plan.retained_allowance_bytes)
                np.testing.assert_allclose(result.velocity, polynomial(mesh.points[mesh.cells]), atol=3e-13)
            self.assertEqual(budget.reserved_bytes, before)
        self.assertEqual(budget.reserved_bytes, 0)

    def test_budget_cancellation_invalid_inputs_and_boundary_callable(self):
        budget = WorkBudget(16*1024**2); stop = Event(); stop.set()
        with mesh_fixture(budget) as mesh:
            baseline = budget.reserved_bytes
            with self.assertRaises(MemoryLimitError): PreparedSubductionTransport(mesh, budget=WorkBudget(1024))
            with self.assertRaises(CancelledError): PreparedSubductionTransport(mesh, budget=budget, cancel=stop)
            self.assertEqual(budget.reserved_bytes, baseline)
            with PreparedSubductionTransport(mesh, budget=budget) as plan:
                retained = budget.reserved_bytes; values = polynomial(mesh.points[mesh.cells])
                with self.assertRaises(CancelledError): plan.evaluate(values, cancel=stop)
                self.assertEqual(budget.reserved_bytes, retained)
                for value in (np.zeros((4, 6)), np.full((4, 6, 2), np.nan)):
                    with self.assertRaises(TectonicsError): plan.evaluate(value)
                for callback in (True, lambda xy: np.zeros((len(xy), 1)), lambda xy: np.full(len(xy), np.inf)):
                    with self.assertRaises(TectonicsError): plan.evaluate(values, boundary_streamfunction=callback)
            self.assertEqual(budget.reserved_bytes, baseline)
        self.assertEqual(budget.reserved_bytes, 0)


if __name__ == '__main__': unittest.main()
