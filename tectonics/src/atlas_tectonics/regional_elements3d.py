"""Bounded Cartesian Q2/Q1 Taylor--Hood volume and surface operators.

Coordinates and fields are dimensionless; the caller owns physical scaling,
boundary conditions, pressure gauge and solution acceptance. On each brick, 27
tensor-product Gauss points integrate the supplied coefficients. The velocity
form is ``integral 2*eta*symgrad(v):symgrad(u)`` and the pressure form is
``-integral q*div(u)``. This module does not evolve material or topology.

Sparse patterns are built once and filled one element at a time. No array of all
dense element matrices is retained. At the maximum 24**3 cells, A has at most
9*193**3 = 64,701,513 scalar entries: about 741 MiB for float64 values and int32
indices alone. Geometry, B, transient allocations and any factorisation need
additional memory; the caller must admit a mesh against its execution budget.
The velocity pattern is built on the first ``assemble`` call, so a caller that
applies the same form matrix-free (``regional_multigrid3d``) never allocates it.

SPDX-License-Identifier: AGPL-3.0-only
"""
from __future__ import annotations

from concurrent.futures import CancelledError
import hashlib
from itertools import product
import operator
from pathlib import Path

import numpy as np
from scipy.sparse import csr_matrix


_LOADED_SOURCE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_SIDES = {"x0": (0, 0), "x1": (0, 1), "y0": (1, 0),
          "y1": (1, 1), "z0": (2, 0), "z1": (2, 1)}


def _check(cancel):
    if cancel is not None and (cancel.is_set() if hasattr(cancel, "is_set") else cancel()):
        raise CancelledError("regional 3D element assembly cancelled")


def _frozen(value):
    """Immutable backing also prevents callers re-enabling the write flag."""
    value = np.ascontiguousarray(value)
    return np.frombuffer(value.tobytes(), dtype=value.dtype).reshape(value.shape)


def _field(value, shape, name, *, positive=False):
    try:
        raw = np.asarray(value)
        if np.iscomplexobj(raw):
            raise ValueError(f"{name} must be real")
        array = np.asarray(raw, dtype=np.float64)
    except (TypeError, OverflowError) as exc:
        raise ValueError(f"{name} must contain finite real numbers") from exc
    if array.shape != shape or not np.all(np.isfinite(array)):
        raise ValueError(f"{name} must be finite with shape {shape}")
    if positive and np.any(array <= 0.):
        raise ValueError(f"{name} must be positive")
    return array


def _shape(points, degree):
    """Tensor Lagrange values/gradients; x is slowest and z fastest."""
    nodes = np.asarray(tuple(product(range(degree + 1), repeat=3)))
    values, derivatives = [], []
    for axis in range(3):
        t = points[:, axis]
        if degree == 2:
            values.append(np.stack((.5*t*(t-1), 1-t*t, .5*t*(t+1)), axis=1))
            derivatives.append(np.stack((t-.5, -2*t, t+.5), axis=1))
        else:
            values.append(np.stack(((1-t)/2, (1+t)/2), axis=1))
            derivatives.append(np.stack((np.full_like(t, -.5), np.full_like(t, .5)), axis=1))
    factors = [values[axis][:, nodes[:, axis]] for axis in range(3)]
    basis = factors[0]*factors[1]*factors[2]
    gradient = np.empty((*basis.shape, 3))
    for axis in range(3):
        gradient[:, :, axis] = derivatives[axis][:, nodes[:, axis]]
        for other in range(3):
            if other != axis:
                gradient[:, :, axis] *= factors[other]
    return basis, gradient


def _grid(shape):
    return np.indices(shape, dtype=np.int32).reshape(3, -1).T


def _pattern(centres, velocity_shape, components):
    """CSR pattern for overlapping node supports, without global COO arrays."""
    lower = np.maximum(0, centres - np.where(centres % 2 == 0, 2, 1))
    upper = np.minimum(np.asarray(velocity_shape)-1,
                       centres + np.where(centres % 2 == 0, 2, 1))
    widths = upper-lower+1
    counts = np.prod(widths, axis=1, dtype=np.int32)
    indptr = np.empty(components*len(centres)+1, dtype=np.int32)
    indptr[0] = 0
    np.cumsum(np.repeat(3*counts, components), dtype=np.int32, out=indptr[1:])
    indices = np.empty(int(indptr[-1]), dtype=np.int32)
    ny, nz = velocity_shape[1:]
    for row, (low, high) in enumerate(zip(lower, upper)):
        neighbours = ((np.arange(low[0], high[0]+1)[:, None, None]*ny
                      + np.arange(low[1], high[1]+1)[None, :, None])*nz
                      + np.arange(low[2], high[2]+1)[None, None, :]).ravel()
        dofs = (3*neighbours[:, None]+np.arange(3)).ravel()
        indices[indptr[components*row]:indptr[components*(row+1)]] = np.tile(dofs, components)
    return _frozen(indptr), _frozen(indices), _frozen(lower), _frozen(widths)


class TaylorHoodBox:
    """Continuous Q2 velocity and Q1 pressure on a regular 3D brick mesh.

    Nodes, cells and quadrature points use lexicographic (x, y, z) ordering,
    with z varying fastest. Velocity DOFs are node-major: ``3*node+component``.
    ``quadrature_weights`` already include the physical Jacobian for one cell.
    All geometry and reusable sparse storage have immutable array backing.
    """

    def __init__(self, cells=(2, 2, 2), lengths=(1., 1., 1.)):
        try:
            supplied = tuple(cells)
            if len(supplied) != 3 or any(isinstance(n, (bool, np.bool_)) for n in supplied):
                raise ValueError("cells must contain three integers in [2, 24]")
            cells = tuple(operator.index(n) for n in supplied)
        except (TypeError, OverflowError) as exc:
            raise ValueError("cells must contain three integers in [2, 24]") from exc
        if any(n < 2 or n > 24 for n in cells):
            raise ValueError("cells must contain three integers in [2, 24]")
        lengths = _field(lengths, (3,), "lengths", positive=True)
        self.cells = cells
        self.lengths = tuple(float(value) for value in lengths)
        self._spacing = _frozen(lengths/np.asarray(cells))
        # Finite positive lengths can still overflow/underflow derived geometry.
        with np.errstate(over="ignore", under="ignore", divide="ignore", invalid="ignore"):
            jacobian = float(np.prod(self._spacing/2))
            domain_volume = float(np.prod(lengths))
            inverse_scale = 2/self._spacing
        if (not np.isfinite(jacobian) or jacobian <= 0
                or not np.isfinite(domain_volume) or domain_volume <= 0
                or not np.all(np.isfinite(inverse_scale))):
            raise ValueError("lengths exceed representable element geometry")
        self.nc = int(np.prod(cells))
        self._velocity_shape = tuple(2*n+1 for n in cells)
        pressure_shape = tuple(n+1 for n in cells)
        self._velocity_grid = _frozen(_grid(self._velocity_shape))
        pressure_grid = _grid(pressure_shape)
        cell_grid = _grid(cells)
        self.nv = len(self._velocity_grid)
        self.np = len(pressure_grid)
        self.velocity_coordinates = _frozen(self._velocity_grid*(self._spacing/2))
        self.pressure_coordinates = _frozen(pressure_grid*self._spacing)
        self._cell_grid = _frozen(cell_grid)
        self._origins = _frozen(cell_grid*self._spacing)

        local_q2 = _grid((3, 3, 3))
        local_q1 = _grid((2, 2, 2))
        velocity_indices = 2*cell_grid[:, None, :]+local_q2[None, :, :]
        pressure_indices = cell_grid[:, None, :]+local_q1[None, :, :]
        self.velocity_cells = _frozen(np.ravel_multi_index(
            velocity_indices.transpose(2, 0, 1), self._velocity_shape).astype(np.int32))
        self.pressure_cells = _frozen(np.ravel_multi_index(
            pressure_indices.transpose(2, 0, 1), pressure_shape).astype(np.int32))
        points, weights = np.polynomial.legendre.leggauss(3)
        quad_indices = _grid((3, 3, 3))
        reference = points[quad_indices]
        self.quadrature_weights = _frozen(np.prod(weights[quad_indices], axis=1)*jacobian)
        if np.any(self.quadrature_weights <= 0):
            raise ValueError("element quadrature weights underflow")
        self.quadrature_coordinates = _frozen(
            self._origins[:, None, :]+(reference[None, :, :]+1)*(self._spacing/2))
        shape_v, grad_v = _shape(reference, 2)
        shape_p, _ = _shape(reference, 1)
        self._shape_v = _frozen(shape_v)
        with np.errstate(over="ignore", invalid="ignore"):
            self._grad_v = _frozen(grad_v*inverse_scale)
        self._shape_p = _frozen(shape_p)
        self._shape_p_squared = _frozen(shape_p*shape_p)

        # The full symmetric-gradient kernel, indexed (q, a, i, b, j).
        g = self._grad_v
        with np.errstate(over="ignore", invalid="ignore"):
            kernel = np.einsum("qaj,qbi->qaibj", g, g)
            dot = np.einsum("qak,qbk->qab", g, g)
            for component in range(3):
                kernel[:, :, component, :, component] += dot
        if not np.all(np.isfinite(kernel)):
            raise ValueError("lengths exceed representable gradient products")
        self._kernel = _frozen(kernel.reshape(27, 81*81))
        self._a_ptr = self._a_indices = self._a_low = self._a_widths = None
        self._b_ptr, self._b_indices, self._b_low, self._b_widths = _pattern(
            2*pressure_grid, self._velocity_shape, 1)
        b_data = np.zeros(len(self._b_indices))
        local_b = -np.einsum("q,qp,qai->pai", self.quadrature_weights, shape_p, g).reshape(8, 81)
        pressure_weights = np.zeros(self.np)
        local_weights = self.quadrature_weights @ shape_p
        for cell in range(self.nc):
            nodes = self.velocity_cells[cell]
            pressures = self.pressure_cells[cell]
            slots = self._slots(pressures, nodes, self._b_low, self._b_widths)
            positions = self._b_ptr[pressures, None, None]+3*slots[:, :, None]+np.arange(3)
            b_data[positions.reshape(8, 81)] += local_b
            pressure_weights[pressures] += local_weights
        self._b_data = _frozen(b_data)
        self._pressure_weights = _frozen(pressure_weights)

    def _slots(self, rows, nodes, lower, widths):
        offsets = self._velocity_grid[nodes][None, :, :]-lower[rows, None, :]
        return ((offsets[:, :, 0]*widths[rows, None, 1]+offsets[:, :, 1])
                * widths[rows, None, 2]+offsets[:, :, 2])

    def assemble(self, viscosity, cancel=None):
        """Return A, B, integral(q_i), and integral(q_i**2/viscosity).

        A and B are CSR matrices. The final vector is an inverse-viscosity
        pressure mass diagonal for preconditioning, not the unweighted mass.
        Cancellation accepts an Event or a zero-argument truth-valued callable.
        """
        _check(cancel)
        viscosity = _field(viscosity, (self.nc, 27), "viscosity", positive=True)
        if self._a_ptr is None:
            # Built once, on first assembly; matrix-free users never allocate it.
            self._a_ptr, self._a_indices, self._a_low, self._a_widths = _pattern(
                self._velocity_grid, self._velocity_shape, 3)
        data = np.zeros(len(self._a_indices))
        pressure_mass_diagonal = np.zeros(self.np)
        components = np.arange(3)
        for cell in range(self.nc):
            _check(cancel)
            nodes = self.velocity_cells[cell]
            slots = self._slots(nodes, nodes, self._a_low, self._a_widths)
            row_dofs = 3*nodes[:, None]+components
            positions = (self._a_ptr[row_dofs][:, :, None, None]
                         + 3*slots[:, None, :, None]+components)
            element = (viscosity[cell]*self.quadrature_weights) @ self._kernel
            data[positions.ravel()] += element
            with np.errstate(over="ignore", divide="ignore", invalid="ignore"):
                mass = (self.quadrature_weights/viscosity[cell]) @ self._shape_p_squared
            pressure_mass_diagonal[self.pressure_cells[cell]] += mass
        _check(cancel)
        if not np.all(np.isfinite(data)) or not np.all(np.isfinite(pressure_mass_diagonal)):
            raise ValueError("viscosity produces non-finite element coefficients")
        if np.any(pressure_mass_diagonal <= 0):
            raise ValueError("inverse-viscosity pressure mass is not representable")
        a = csr_matrix((data, self._a_indices, self._a_ptr), shape=(3*self.nv, 3*self.nv))
        b = csr_matrix((self._b_data, self._b_indices, self._b_ptr), shape=(self.np, 3*self.nv))
        return a, b, self._pressure_weights.copy(), pressure_mass_diagonal

    def load(self, force, extra_stress=None):
        """Integrate N*f - symgrad(N):extra_stress into node-major DOFs."""
        force = _field(force, (self.nc, 27, 3), "force")
        stress = None if extra_stress is None else _field(
            extra_stress, (self.nc, 27, 3, 3), "extra_stress")
        rhs = np.zeros((self.nv, 3))
        for cell in range(self.nc):
            local = self._shape_v.T @ (force[cell]*self.quadrature_weights[:, None])
            if stress is not None:
                symmetric = .5*stress[cell]+.5*stress[cell].swapaxes(-1, -2)
                local -= np.einsum("q,qaj,qij->ai", self.quadrature_weights,
                                   self._grad_v, symmetric)
            rhs[self.velocity_cells[cell]] += local
        if not np.all(np.isfinite(rhs)):
            raise ValueError("load produces a non-finite integral")
        return rhs.ravel()

    def evaluate(self, velocity, pressure):
        """Evaluate fields, with gradient_q[..., i, j] = d(u_i)/d(x_j)."""
        velocity = _field(velocity, (self.nv, 3), "velocity")
        pressure = _field(pressure, (self.np,), "pressure")
        velocity_q = np.empty((self.nc, 27, 3))
        gradient_q = np.empty((self.nc, 27, 3, 3))
        pressure_q = np.empty((self.nc, 27))
        for cell in range(self.nc):
            local = velocity[self.velocity_cells[cell]]
            velocity_q[cell] = self._shape_v @ local
            # Sum(grad(N)) is zero analytically. Subtract the common nodal
            # offset before contraction to preserve rigid translation exactly.
            gradient_q[cell] = np.einsum("ai,qaj->qij", local-local[0], self._grad_v)
            pressure_q[cell] = self._shape_p @ pressure[self.pressure_cells[cell]]
        result = {"velocity_q": velocity_q, "gradient_q": gradient_q, "pressure_q": pressure_q}
        if not all(np.all(np.isfinite(array)) for array in result.values()):
            raise ValueError("fields produce non-finite quadrature values")
        return result

    def _face(self, side):
        if not isinstance(side, str) or side not in _SIDES:
            raise ValueError("side must be x0, x1, y0, y1, z0 or z1")
        axis, high = _SIDES[side]
        face_cells = np.flatnonzero(self._cell_grid[:, axis] == (self.cells[axis]-1 if high else 0))
        axes = [other for other in range(3) if other != axis]
        points, weights = np.polynomial.legendre.leggauss(3)
        pairs = _grid((3, 3, 1))[:, :2]
        reference = np.empty((9, 3))
        reference[:, axis] = 1. if high else -1.
        reference[:, axes] = points[pairs]
        shape, _ = _shape(reference, 2)
        surface_weights = np.prod(weights[pairs], axis=1)*np.prod(self._spacing[axes]/2)
        coordinates = self._origins[face_cells, None, :]+(reference[None, :, :]+1)*(self._spacing/2)
        return face_cells, shape, surface_weights, coordinates

    def boundary_quadrature(self, side):
        """Return (nface, 9, 3) surface coordinates in cell/point order."""
        return self._face(side)[3]

    def integrate_boundary_traction(self, side, traction):
        """Integrate a supplied Cartesian traction vector, with its sign intact.

        The caller supplies stress times the outward normal; this method does
        not add another normal sign. Each side includes every boundary face.
        """
        cells, shape, weights, _ = self._face(side)
        traction = _field(traction, (len(cells), 9, 3), "traction")
        rhs = np.zeros((self.nv, 3))
        for face, cell in enumerate(cells):
            rhs[self.velocity_cells[cell]] += shape.T @ (traction[face]*weights[:, None])
        if not np.all(np.isfinite(rhs)):
            raise ValueError("traction produces a non-finite integral")
        return rhs.ravel()
