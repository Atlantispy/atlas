"""Bitwise and admission regressions for the R3D/SL multigrid optimisations.

The NumPy references below preserve the pre-optimisation operation order.
These checks supplement the analytical multigrid controls; no tolerance changes.
SPDX-License-Identifier: AGPL-3.0-only
"""
import importlib.util
from pathlib import Path
import unittest
from unittest import mock

import numba
import numpy as np
from scipy import sparse

from atlas_tectonics import regional_multigrid3d as mg
from atlas_tectonics import regional_execution3d as execution3d
from atlas_tectonics import regional_solver_selection3d as selection
from atlas_tectonics.regional_elements3d import TaylorHoodBox
from atlas_tectonics.resources import MemoryLimitError, WorkBudget
from atlas_tectonics.stokes_execution import _native_lease
from test_regional_execution3d import pattern, prepare


def reference_apply(operator, velocity, pressure=None, divergence=False):
    """The retained pre-optimisation NumPy operator, including both layout copies."""
    g = operator.geometry
    nx, ny, nz = g.cells
    U = np.ascontiguousarray(velocity.reshape(*g.vshape, 3).transpose(3, 0, 1, 2))
    local = np.empty((27, 3, nx, ny, nz))
    for a, (i, j, k) in enumerate(mg._grid((3, 3, 3))):
        local[a] = U[:, i:i+2*nx:2, j:j+2*ny:2, k:k+2*nz:2]
    gradient = (g.gmat@local.reshape(27, 3*g.nc)).reshape(27, 3, 3, g.nc)
    stress = np.empty_like(gradient)
    np.add(gradient, gradient.transpose(0, 2, 1, 3), out=stress)
    stress *= operator._etaw_q[:, None, None, :]
    if pressure is not None:
        gathered = np.empty((8, nx, ny, nz))
        P = pressure.reshape(g.pshape)
        for a, (i, j, k) in enumerate(mg._grid((2, 2, 2))):
            gathered[a] = P[i:i+nx, j:j+ny, k:k+nz]
        pq = g.shape_p@gathered.reshape(8, -1)
        pq *= g.weights[:, None]
        for axis in range(3):
            stress[:, axis, axis, :] -= pq
    values = (g.gmat_t@stress.reshape(81, 3*g.nc)).reshape(27, 3, nx, ny, nz)
    result = np.zeros((3, *g.vshape))
    for a, (i, j, k) in enumerate(mg._grid((3, 3, 3))):
        result[:, i:i+2*nx:2, j:j+2*ny:2, k:k+2*nz:2] += values[a]
    out = result.transpose(1, 2, 3, 0).ravel()
    if not divergence:
        return out
    div = np.einsum('qdde->qe', gradient)*g.weights[:, None]
    p = np.zeros(g.pshape)
    local_p = (-(g.shape_p.T@div)).reshape(8, nx, ny, nz)
    for a, (i, j, k) in enumerate(mg._grid((2, 2, 2))):
        p[i:i+nx, j:j+ny, k:k+nz] += local_p[a]
    return out, p.ravel()


def reference_smooth(smoother, rhs, x):
    apply, inverse, upper, lower = smoother
    theta, delta = (upper+lower)/2, (upper-lower)/2
    sigma = theta/delta
    rho = 1/sigma
    direction = inverse*(rhs if x is None else rhs-apply(x))/theta
    x = direction.copy() if x is None else x+direction
    for _ in range(mg.SETTINGS['chebyshev_degree']-1):
        following = 1/(2*sigma-rho)
        direction = (following*rho)*direction+(2*following/delta)*(inverse*(rhs-apply(x)))
        x = x+direction
        rho = following
    return x


class BitwiseMultigridTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mesh = mesh = TaylorHoodBox((3, 4, 2), (1.3, .7, 1.1))
        rng = np.random.default_rng(82)
        eta = np.exp(2*rng.normal(size=(mesh.nc, 27)))
        B = sparse.csr_matrix((mesh._b_data, mesh._b_indices, mesh._b_ptr), shape=(mesh.np, 3*mesh.nv))
        mask = mg._node_mask(tuple(2*n+1 for n in mesh.cells), pattern())
        with _native_lease():
            cls.geometry = mg.StructuredGeometry(mesh, pattern(), np.flatnonzero(mask), np.flatnonzero(~mask), B)
            cls.operator = mg.MultigridStokes(cls.geometry, eta)

    def assert_bits(self, first, second):
        self.assertEqual(np.asarray(first).shape, np.asarray(second).shape)
        self.assertEqual(np.asarray(first).tobytes(), np.asarray(second).tobytes())

    def test_apply_matches_original_numpy_and_returns_detached_arrays(self):
        rng = np.random.default_rng(29)
        g, operator = self.geometry, self.operator
        with _native_lease():
            for strided in (False, True):
                velocity = rng.normal(size=6*g.nv)[::2] if strided else rng.normal(size=3*g.nv)
                p = rng.normal(size=g.np)
                for pressure in (None, p):
                    with self.subTest(strided=strided, pressure=pressure is not None):
                        expected = reference_apply(operator, velocity, pressure, True)
                        actual = operator.apply(velocity, pressure, True)
                        for left, right in zip(actual, expected):
                            self.assert_bits(left, right)
                        saved = tuple(a.tobytes() for a in actual)
                        self.assert_bits(operator.apply(velocity, pressure), expected[0])
                        operator.apply(-velocity, p)
                        self.assertEqual(saved, tuple(a.tobytes() for a in actual))

    def test_fused_smoothing_keeps_original_roundings_and_caller_input(self):
        rng = np.random.default_rng(63)
        rhs = rng.normal(size=3*self.geometry.nv)
        inverse, upper, lower = self.operator.smoothers[0][1:]
        reference = (lambda x: reference_apply(self.operator, x)*self.operator._mask, inverse, upper, lower)
        with _native_lease():
            for initial in (None, rng.normal(size=rhs.shape)):
                saved = None if initial is None else initial.tobytes()
                self.assert_bits(mg.MultigridStokes._smooth(self.operator.smoothers[0], rhs, initial),
                                 reference_smooth(reference, rhs, initial))
                self.assertEqual(saved, None if initial is None else initial.tobytes())

    def test_csr_transposes_keep_each_reduction_order(self):
        rng = np.random.default_rng(77)
        with _native_lease():
            p = rng.normal(size=self.geometry.np)
            self.assert_bits(self.geometry.Bt_free@p, (self.geometry.B.T@p)[self.geometry.free])
        # Exercise an actual nested geometry without assembling or factoring its
        # velocity operator. This also checks the retained restriction inventory.
        mesh = TaylorHoodBox((12, 12, 12), (1., 1., 1.))
        B = sparse.csr_matrix((mesh._b_data, mesh._b_indices, mesh._b_ptr), shape=(mesh.np, 3*mesh.nv))
        mask = mg._node_mask(tuple(2*n+1 for n in mesh.cells), pattern())
        geometry = mg.StructuredGeometry(mesh, pattern(), np.flatnonzero(mask), np.flatnonzero(~mask), B)
        self.assertTrue(geometry.levels)
        for level in geometry.levels:
            r = rng.normal(size=level['prolong'].shape[0])
            self.assert_bits(level['restrict']@r, level['prolong'].T@r)
        transpose_bytes = mg._nbytes(geometry.Bt_free)+sum(mg._nbytes(x['restrict']) for x in geometry.levels)
        self.assertLessEqual(transpose_bytes, mg._retained_extra_bytes(mesh.cells)[1])

    def test_structure_counts_all_retained_operator_arrays_and_row_cache(self):
        operator = self.operator
        # Independent inventory by ownership, including all coarse inverse
        # diagonals. The lazy row-sum cache is charged before its first use.
        arrays = [value for key, value in vars(operator).items()
                  if isinstance(value, np.ndarray) or sparse.issparse(value)]
        expected = operator.geometry.nbytes()+sum(mg._nbytes(x) for x in arrays)
        expected += sum(mg._nbytes(x) for x in operator.matrices)
        expected += sum(mg._nbytes(x[1]) for x in operator.smoothers)
        if operator._rowsum is None:
            expected += 8*3*operator.geometry.nv
        self.assertEqual(operator.structure_bytes(), expected)
        self.assertEqual(operator._gradient.nbytes+operator._pgather.nbytes,
                         mg._retained_extra_bytes(operator.geometry.cells)[0])


class MultigridAdmissionTests(unittest.TestCase):
    def test_projection_reserves_buffers_and_transpose_build_peak(self):
        cells = (16, 16, 16)
        nc, nv, nq = 16**3, 33**3, 17**3
        old_structure = 12*1024**2+111*nv+20059*nq+1984*nc
        old_work = 56*1024**2+8*(3*nv+nq+1)*(2*mg.SETTINGS['restart']+31)+37592*nc+730*nv
        buffers, transposes = mg._retained_extra_bytes(cells)
        self.assertEqual(buffers, 8_224_768)
        projected = mg.projected_bytes(cells)
        self.assertEqual(projected['structure'], old_structure+buffers+transposes)
        self.assertEqual(projected['work'], old_work+transposes)

    def test_refusal_precedes_mesh_allocation_and_returns_parent_reservations(self):
        cells = (2, 2, 2)
        projected = mg.projected_bytes(cells)
        parent = WorkBudget(projected['structure']+projected['work']-1)
        budget = WorkBudget(parent.max_bytes, parent=parent)
        with mock.patch.object(execution3d.elements3d, 'TaylorHoodBox') as build:
            with self.assertRaises(MemoryLimitError):
                prepare(cells=cells, method='multigrid', budget=budget)
            build.assert_not_called()
        self.assertEqual(parent.reserved_bytes, 0)
        self.assertEqual(budget.reserved_bytes, 0)

    def test_exact_complete_projection_admits_and_binds_numba(self):
        cells = (2, 2, 2)
        total = selection.multigrid_bytes(cells, np.array((1., 1., 1.))/cells, pattern())
        parent = WorkBudget(total)
        budget = WorkBudget(total, parent=parent)
        with prepare(cells=cells, method='multigrid', budget=budget) as plan:
            self.assertEqual(parent.reserved_bytes, total)
            self.assertEqual(plan._context.backend, 'numba')
            structure = plan._mg.structure_bytes()+sum(a.nbytes for a in (
                plan._mesh.velocity_coordinates, plan._mesh.velocity_cells, plan._mesh.pressure_cells,
                plan._mesh.quadrature_coordinates, plan._eta, plan._fixed, plan._free))
            self.assertLessEqual(structure, mg.projected_bytes(cells)['structure'])
        self.assertEqual(parent.reserved_bytes, 0)

    def test_unreviewed_or_disabled_numba_refuses_before_kernels_are_declared(self):
        path = Path(mg.__file__)
        for target, value in (('version', '0.0.unreviewed'), ('disabled', True)):
            spec = importlib.util.spec_from_file_location('_multigrid_admission_probe', path)
            module = importlib.util.module_from_spec(spec)
            patch = (mock.patch.object(numba, '__version__', value) if target == 'version'
                     else mock.patch.object(numba.config, 'DISABLE_JIT', value))
            with self.subTest(target=target), patch:
                with self.assertRaisesRegex(ImportError, 'requires enabled numba==0.65.1'):
                    spec.loader.exec_module(module)
                self.assertFalse(hasattr(module, '_gather27'))


if __name__ == '__main__':
    unittest.main()
