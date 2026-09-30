"""Matrix-free Q2 Stokes operator and hybrid geometric multigrid for 3D regions.

SPDX-License-Identifier: AGPL-3.0-only

Serves only the explicitly selected ``method='multigrid'`` of
``regional_execution3d.PreparedRegionalStokes3D``. The discrete equations are
those of ``regional_elements3d.TaylorHoodBox``: the same Q2/Q1 spaces, 27-point
Gauss rule, quadrature-point viscosity, full symmetric-gradient form and
``B = -integral q div(u)``. Nothing here changes a coefficient or a gate.

* Operator. Every brick of the regular mesh shares one reference gradient
  table, so ``A u + B^T p`` is two dense products per application: gather each
  element's 27 nodes by strided slicing, form ``2 eta D(u) - p I`` at the Gauss
  points and scatter back. The Q2 velocity matrix (about 183 nonzeros per row)
  is never stored.
* Gate products. The acceptance gates use ``|A|`` with ASSEMBLED entries, which
  can be smaller than the sum of element magnitudes. They are regenerated one
  node offset at a time (sum over elements first, then the absolute value), so
  every gate scale is the assembled one without retaining the matrix.
* Preconditioner. Upper block-triangular: an exact sparse factorisation of the
  1/eta-weighted Q1 pressure mass approximates the Schur complement, then one
  V-cycle approximates the velocity block. The cycle p-coarsens Q2 to Q1 on the
  same bricks (the Galerkin product is exactly Q1 assembly with the fine Gauss
  points and viscosities), h-coarsens Q1 on nested tensor grids with Galerkin
  operators and factors the coarsest level. Chebyshev-Jacobi smoothing uses a
  Lanczos estimate frozen at preparation, so the preconditioner is linear.
* Krylov. Flexible GMRES with deflated restarting (harmonic Ritz vectors),
  stopping only on the recomputed true residual ``||b - K x||_2 <= rtol ||b||_2``.

The caller owns resource admission, identity, scaling, gauges and acceptance.
"""
from __future__ import annotations

from concurrent.futures import CancelledError
import hashlib
from pathlib import Path

import numpy as np
from scipy import sparse
from scipy.linalg import eig, lstsq
from scipy.sparse.linalg import splu

_LOADED_SOURCE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
# Fixed numerical settings; the caller records them in its plan identity.
SETTINGS = dict(operator='matrix-free Q2 (shared reference gradients), assembled-entry gate products',
                block='upper triangular', schur='sparse LU of the 1/eta-weighted Q1 pressure mass',
                cycle='V(1,1): Q2 -> Q1 (same bricks) -> nested Q1 Galerkin levels -> sparse LU',
                smoother='Chebyshev-Jacobi', chebyshev_degree=4, smoothing_range=15.,
                lanczos_steps=10, eigen_safety=1.2, coarse_dofs=3000,
                krylov='FGMRES with deflated restarting', restart=60, deflation=20,
                # Aimed-for relative residual, stricter than the plan's 1e-11:
                # SciPy's left-preconditioned GMRES reference overshoots its own
                # target by one to two orders of magnitude, and stopping at 1e-11
                # gave larger forward errors and more refinement solves. Where
                # 1e-13 lies below a system's binary64 residual floor, the solve
                # stops at the floor and counts as converged only if the true
                # residual meets the plan's 1e-11, the reference's own target.
                krylov_rtol=1e-13)


def _check(cancel):
    if cancel is not None and (cancel.is_set() if hasattr(cancel, 'is_set') else cancel()):
        raise CancelledError('3D multigrid preparation cancelled')


def _nbytes(*arrays):
    total = 0
    for a in arrays:
        if a is None:
            continue
        if sparse.issparse(a):
            total += a.data.nbytes+a.indices.nbytes+a.indptr.nbytes
        else:
            total += a.nbytes
    return total


def _grid(shape):
    return np.indices(shape).reshape(3, -1).T


def projected_bytes(cells):
    """Upper bounds (bytes) admitted before a multigrid plan is built.

    ``structure``: mesh tables, divergence matrix, masks, the Q1 pattern,
    transfers, viscosity-weighted tables, the Q1 and Galerkin level matrices
    (at most 27 coupled nodes per row) and the pressure mass. ``work``: the
    Krylov basis (2*restart+1 vectors), element and stencil-plane transients,
    level vectors, the right-hand side and the published result envelope.
    Factors are admitted separately by ``factor_allowance``. These are
    accounting bounds, not an operating-system RSS guarantee. The fixed 56 MiB
    of work covers allocator and temporary slack: without it, measured
    solver-attributable peak private memory exceeded the total admitted bytes
    by up to 30 MB at 8-10 cells per axis (Windows scratch measurement).
    """
    cells = np.asarray(cells)
    nc = int(np.prod(cells)); nv = int(np.prod(2*cells+1)); nq = int(np.prod(cells+1))
    unknowns = 3*nv+nq+1
    structure = 12*1024**2+111*nv+20059*nq+1984*nc
    work = 56*1024**2+8*unknowns*(2*SETTINGS['restart']+31)+37592*nc+730*nv
    return dict(structure=structure, work=work)


def _spd_factor(matrix):
    """Sparse LU of a symmetric positive-definite matrix with diagonal pivots.

    Symmetric ordering without row interchanges keeps the fill structural (the
    same for any positive viscosity field), so the admitted allowance holds.
    """
    return splu(matrix.tocsc(), permc_spec='MMD_AT_PLUS_A', diag_pivot_thresh=0.,
                options=dict(SymmetricMode=True))


def factor_allowance(geometry):
    """Admitted bytes for the coarse and pressure-mass factors (checked after).

    Structural fill bounds: at most about 30 n^(4/3) and 26 n^(4/3) entries were
    measured for the coarse and pressure-mass factors over 2-24 cells per axis,
    three boundary patterns and flat boxes; 66.6 and 48 n^(4/3) are admitted.
    """
    coarse = len(geometry.levels[-1]['free']) if geometry.levels else len(geometry.free1)
    mass = geometry.np
    entries = min(coarse*coarse, int(288*(coarse/3)**(4/3)))+min(mass*mass, int(48*mass**(4/3)))
    return 1024**2+12*entries+64*(coarse+mass)


def _node_mask(shape, pattern):
    """Constrained (node, component) mask of a tensor node grid, node-major."""
    index = _grid(shape)
    mask = np.zeros((len(index), 3), dtype=bool)
    for side, kinds in pattern.items():
        axis = 'xyz'.index(side[0])
        on = index[:, axis] == (0 if side[1] == '0' else shape[axis]-1)
        for component, kind in enumerate(kinds):
            if kind == 'velocity':
                mask[on, component] = True
    return mask.ravel()


def _coarse_line(coords):
    """Every other node plus the last one, and linear interpolation to the fine line."""
    n = len(coords)-1
    keep = np.arange(0, n+1, 2)
    if keep[-1] != n:
        keep = np.append(keep, n)
    rows, cols, values = [], [], []
    for i in range(n+1):
        j = int(np.searchsorted(keep, i))
        if j < len(keep) and keep[j] == i:
            rows.append(i); cols.append(j); values.append(1.)
        else:
            left, right = keep[j-1], keep[j]
            t = (coords[i]-coords[left])/(coords[right]-coords[left])
            rows += [i, i]; cols += [j-1, j]; values += [1.-t, t]
    return keep, sparse.csr_matrix((values, (rows, cols)), shape=(n+1, len(keep)))


def _stencil_offsets(local, kernel):
    """Group element-local node pairs by their global node offset.

    ``kernel[q, la, i, lb, j]`` is the per-point element form. For each offset
    ``d = lb - la`` the returned table stacks every local pair with that offset,
    so one product with (eta*w) gives all element contributions to that
    stencil plane.
    """
    nodes = _grid((local,)*3)
    difference = nodes[None, :, :]-nodes[:, None, :]                   # [a, b] = lb - la
    table = []
    span = local-1
    for d in _grid((2*span+1,)*3)-span:
        la, lb = np.nonzero(np.all(difference == d, axis=-1))
        blocks = np.moveaxis(kernel[:, la, :, lb, :], 0, 1)              # (q, pair, i, j)
        table.append((tuple(int(x) for x in d), nodes[la], np.ascontiguousarray(blocks.reshape(kernel.shape[0], -1))))
    return table


def _shift(shape, d):
    """Row and column slices of a node grid for the coupling i -> i + d."""
    rows = tuple(slice(max(0, -o), n-max(0, o)) for n, o in zip(shape, d))
    cols = tuple(slice(max(0, -o)+o, n-max(0, o)+o) for n, o in zip(shape, d))
    return rows, cols


class StructuredGeometry:
    """Viscosity-independent structure, shareable by plans with equal geometry.

    Holds reference tables, masks, the divergence matrix, the Q1 sparsity
    pattern, nested transfer operators and the pressure-mass pattern. It keeps
    no viscosity or solution data, so a changed-coefficient plan may reuse it.
    """
    def __init__(self, mesh, pattern, fixed, free, B, cancel=None):
        _check(cancel)
        self.cells = tuple(mesh.cells)
        self.nc, self.nv, self.np = mesh.nc, mesh.nv, mesh.np
        self.vshape = tuple(2*n+1 for n in self.cells)
        self.pshape = tuple(n+1 for n in self.cells)
        self.pattern = {k: tuple(v) for k, v in pattern.items()}
        self.fixed, self.free = fixed, free
        self.B = B
        self.weights = np.asarray(mesh.quadrature_weights)
        g = np.asarray(mesh._grad_v)                                       # (q, a, d)
        self.gmat = np.ascontiguousarray(g.transpose(0, 2, 1).reshape(81, 27))
        self.gmat_t = np.ascontiguousarray(self.gmat.T)
        self.shape_p = np.asarray(mesh._shape_p)                           # (q, 8)
        self.shape_v = np.asarray(mesh._shape_v)
        kernel = np.asarray(mesh._kernel).reshape(27, 27, 3, 27, 3)
        self.kernel_diagonal = np.ascontiguousarray(np.einsum('qaiai->qai', kernel).reshape(27, 81))
        # Q2 tables are stored transposed: (pairs*9, 27) @ (27, nc) gives
        # component-major element blocks for the gate products.
        self.q2_offsets = [(d, nodes, np.ascontiguousarray(blocks.T)) for d, nodes, blocks in _stencil_offsets(3, kernel)]
        # Element-local Q1 -> Q2 interpolation: Q2 node positions 0, 1/2, 1.
        values = np.array([[1., 0.], [.5, .5], [0., 1.]])
        local27, local8 = _grid((3, 3, 3)), _grid((2, 2, 2))
        interp = (values[local27[:, 0]][:, local8[:, 0]]*values[local27[:, 1]][:, local8[:, 1]]
                  * values[local27[:, 2]][:, local8[:, 2]])                # (27, 8)
        q1_kernel = np.einsum('ap,qaibj,bs->qpisj', interp, kernel, interp)  # exact Galerkin form
        self.q1_offsets = _stencil_offsets(2, q1_kernel)
        # Q1 velocity level on the same bricks and its CSR pattern.
        fixed1 = _node_mask(self.pshape, pattern)
        self.free1 = np.flatnonzero(~fixed1)
        self._q1_pattern()
        _check(cancel)
        # Nested Q1 levels: coarsen the axes with the smallest spacing first.
        spacing = np.asarray(mesh._spacing)
        coords = [np.arange(n+1)*h for n, h in zip(self.cells, spacing)]
        self.levels = []
        shape, free_fine = self.pshape, self.free1
        while len(free_fine) > SETTINGS['coarse_dofs']:
            _check(cancel)
            widths = [float(np.max(np.diff(c))) if len(c) > 1 else np.inf for c in coords]
            smallest = min(widths)
            lines, keeps = [], []
            for axis in range(3):
                n = len(coords[axis])-1
                if n >= 2 and widths[axis] < 2*smallest*(1-1e-12):
                    keep, line = _coarse_line(coords[axis])
                else:
                    keep, line = np.arange(n+1), sparse.identity(n+1, format='csr')
                keeps.append(keep); lines.append(line)
            coarse_shape = tuple(len(k) for k in keeps)
            if coarse_shape == shape:
                break
            free_coarse = np.flatnonzero(~_node_mask(coarse_shape, pattern))
            if len(free_coarse) == 0:
                break
            nodes = sparse.kron(sparse.kron(lines[0], lines[1]), lines[2], format='csr')
            prolong = sparse.kron(nodes, sparse.identity(3), format='csr')[free_fine][:, free_coarse].tocsr()
            self.levels.append(dict(shape=coarse_shape, free=free_coarse, prolong=prolong))
            shape, free_fine = coarse_shape, free_coarse
            coords = [c[k] for c, k in zip(coords, keeps)]
        # Pressure-mass pattern (element pressure nodes).
        cells = np.asarray(mesh.pressure_cells)
        self.mass_rows = np.repeat(cells, 8, axis=1).ravel()
        self.mass_cols = np.tile(cells, (1, 8)).ravel()
        pw = np.asarray(mesh._pressure_weights)
        self.w = pw/np.sum(pw)

    def _q1_pattern(self):
        shape = self.pshape
        ids = np.arange(int(np.prod(shape))).reshape(shape)
        offsets = [tuple(int(x) for x in d) for d in _grid((3, 3, 3))-1]
        cols = np.full((*shape, 27), -1, dtype=np.int64)
        for t, d in enumerate(offsets):
            rows, source = _shift(shape, d)
            cols[rows+(t,)] = ids[source]
        valid = cols >= 0                                                   # (S, 27)
        entry = np.broadcast_to(valid[..., None, :, None], (*shape, 3, 27, 3))
        index = 3*cols[..., None, :, None]+np.arange(3)
        index = np.broadcast_to(index, (*shape, 3, 27, 3))[entry]
        counts = np.repeat(3*valid.reshape(-1, 27).sum(axis=1), 3)
        self.q1_indptr = np.concatenate(([0], np.cumsum(counts))).astype(np.int32)
        self.q1_indices = index.astype(np.int32)
        self.q1_entry = np.ascontiguousarray(entry)
        self.q1_offset_order = {d: t for t, d in enumerate(offsets)}

    def nbytes(self):
        """Retained bytes, including the (shared) divergence matrix."""
        levels = sum(_nbytes(level['prolong'], level['free']) for level in self.levels)
        tables = sum(t[2].nbytes+t[1].nbytes for t in self.q2_offsets+self.q1_offsets)
        return (levels+tables+_nbytes(self.B, self.free1, self.q1_indptr, self.q1_indices, self.q1_entry,
                                      self.mass_rows, self.mass_cols, self.gmat, self.gmat_t,
                                      self.kernel_diagonal, self.w))


class MultigridStokes:
    """Viscosity-dependent operator, gate products and linear preconditioner.

    Not thread-safe: element buffers are reused between applications; the owning
    plan is single-owner and non-reentrant.
    """
    def __init__(self, geometry, viscosity, cancel=None):
        g = self.geometry = geometry
        _check(cancel)
        eta = np.asarray(viscosity, dtype=float)
        nx, ny, nz = g.cells
        self._etaw = np.ascontiguousarray(eta*g.weights[None, :])          # (nc, 27)
        self._etaw_q = np.ascontiguousarray(self._etaw.T)                  # (27, nc)
        self._local = np.empty((27, 3, nx, ny, nz))                        # element buffers
        self._stress = np.empty((27, 3, 3, g.nc))
        self._rowsum = None
        self.applications = 0
        # The fine level works on full-length vectors held at zero on constrained
        # components, so no free-index copy is made per application.
        self._mask = np.ones(3*g.nv)
        self._mask[g.fixed] = 0.
        diagonal = self._diagonal()
        free_diagonal = diagonal[g.free]
        if not (np.all(np.isfinite(free_diagonal)) and np.all(free_diagonal > 0)):
            raise ValueError('multigrid requires a finite positive velocity diagonal')
        inverse = np.zeros(3*g.nv)
        inverse[g.free] = 1/free_diagonal
        # Level 1: Q1 on the same bricks (exact Galerkin product of the fine form).
        _check(cancel)
        A1 = sparse.csr_matrix((self._assemble_q1(cancel), g.q1_indices, g.q1_indptr),
                               shape=(3*int(np.prod(g.pshape)),)*2)
        matrices = [A1[g.free1][:, g.free1].tocsr()]
        del A1
        for level in g.levels:
            _check(cancel)
            P = level['prolong']
            matrices.append((P.T@(matrices[-1]@P)).tocsr())
        self.matrices = matrices
        # Smoothers: frozen Lanczos estimates of lambda_max(D^-1 A).
        self.smoothers = [self._chebyshev(self._apply_fine, inverse, self._mask, cancel)]
        for M in matrices[:-1]:
            _check(cancel)
            d = M.diagonal()
            if not (np.all(np.isfinite(d)) and np.all(d > 0)):
                raise ValueError('multigrid requires a finite positive coarse diagonal')
            self.smoothers.append(self._chebyshev(M.__matmul__, 1/d, None, cancel))
        _check(cancel)
        self.coarse = _spd_factor(matrices[-1])
        # Schur approximation: 1/eta-weighted Q1 pressure mass, exactly factored.
        _check(cancel)
        local = np.einsum('eq,qa,qb->eab', g.weights[None, :]/eta, g.shape_p, g.shape_p)
        mass = sparse.coo_matrix((local.ravel(), (g.mass_rows, g.mass_cols)), shape=(g.np, g.np)).tocsc()
        if not np.all(np.isfinite(mass.data)) or np.any(mass.diagonal() <= 0):
            raise ValueError('inverse-viscosity pressure mass is not representable')
        self.mass = _spd_factor(mass)
        self._mass_matrix = mass
        self.Sw = self.mass.solve(g.w)
        self.wSw = float(g.w@self.Sw)

    # ------------------------------------------------------------ structure
    def factor_bytes(self):
        return sum(_nbytes(f.L, f.U) for f in (self.coarse, self.mass))

    def structure_bytes(self):
        """Retained non-factor bytes of the geometry and these operators."""
        smoother = self.smoothers[0][1]
        # The |A| row-sum cache is created on first use; count it now.
        return (self.geometry.nbytes()+_nbytes(self._etaw, self._etaw_q, self._local, self._stress, self._mask,
                                               smoother, self._mass_matrix, self.Sw)
                + 8*3*self.geometry.nv+sum(_nbytes(M) for M in self.matrices))

    def levels(self):
        return [len(self.geometry.free)]+[M.shape[0] for M in self.matrices]

    # ------------------------------------------------------------ element kernels
    def _gather_p(self, P):
        nx, ny, nz = self.geometry.cells
        out = np.empty((8, nx, ny, nz))
        for a, (i, j, k) in enumerate(_grid((2, 2, 2))):
            out[a] = P[i:i+nx, j:j+ny, k:k+nz]
        return out.reshape(8, -1)

    def _scatter_p(self, local, P):
        nx, ny, nz = self.geometry.cells
        local = local.reshape(8, nx, ny, nz)
        for a, (i, j, k) in enumerate(_grid((2, 2, 2))):
            P[i:i+nx, j:j+ny, k:k+nz] += local[a]
        return P

    def apply(self, velocity, pressure=None, divergence=False):
        """Matrix-free ``A u + B^T p`` (and ``B u``) for full node-major vectors."""
        g = self.geometry
        nc = g.nc
        nx, ny, nz = g.cells
        # Component-major copies make every element gather/scatter a plain slice.
        U = np.ascontiguousarray(velocity.reshape(*g.vshape, 3).transpose(3, 0, 1, 2))
        local = self._local
        for a, (i, j, k) in enumerate(_grid((3, 3, 3))):
            local[a] = U[:, i:i+2*nx:2, j:j+2*ny:2, k:k+2*nz:2]
        gradient = (g.gmat@local.reshape(27, 3*nc)).reshape(27, 3, 3, nc)    # q, d, c, e = du_c/dx_d
        stress = self._stress
        np.add(gradient, gradient.transpose(0, 2, 1, 3), out=stress)
        stress *= self._etaw_q[:, None, None, :]
        if pressure is not None:
            pq = g.shape_p@self._gather_p(pressure.reshape(g.pshape))       # (q, nc)
            pq *= g.weights[:, None]
            for axis in range(3):
                stress[:, axis, axis, :] -= pq
        values = (g.gmat_t@stress.reshape(81, 3*nc)).reshape(27, 3, nx, ny, nz)
        result = np.zeros((3, *g.vshape))
        for a, (i, j, k) in enumerate(_grid((3, 3, 3))):
            result[:, i:i+2*nx:2, j:j+2*ny:2, k:k+2*nz:2] += values[a]
        out = result.transpose(1, 2, 3, 0).ravel()
        if not divergence:
            return out
        div = np.einsum('qdde->qe', gradient)*g.weights[:, None]
        p = np.zeros(g.pshape)
        self._scatter_p(-(g.shape_p.T@div), p)
        return out, p.ravel()

    def _diagonal(self):
        g = self.geometry
        nx, ny, nz = g.cells
        local = (self._etaw@g.kernel_diagonal).reshape(nx, ny, nz, 27, 3)
        out = np.zeros((*g.vshape, 3))
        for a, (i, j, k) in enumerate(_grid((3, 3, 3))):
            out[i:i+2*nx:2, j:j+2*ny:2, k:k+2*nz:2] += local[:, :, :, a]
        return out.ravel()

    def _planes(self, table, shape, stride, cancel=None):
        """Yield (offset, assembled 3x3 blocks on the node grid) one offset at a time."""
        nx, ny, nz = self.geometry.cells
        plane = np.zeros((*shape, 3, 3))
        for d, nodes, blocks in table:
            _check(cancel)
            values = (self._etaw@blocks).reshape(nx, ny, nz, len(nodes), 3, 3)
            plane.fill(0.)
            for t, (i, j, k) in enumerate(nodes):
                plane[i:i+stride*nx:stride, j:j+stride*ny:stride, k:k+stride*nz:stride] += values[:, :, :, t]
            yield d, plane

    def products(self, u, v=None, signed=True, cancel=None):
        """``A u`` and ``|A| v`` with assembled entries; ``v`` defaults to ``|u|``.

        One node offset at a time, element contributions are summed into the
        assembled coupling (component-major, ``plane[a, b]`` couples component a
        of node i with component b of node i+d); only then is the magnitude taken.
        """
        g = self.geometry
        nx, ny, nz = g.cells
        U = np.ascontiguousarray(u.reshape(*g.vshape, 3).transpose(3, 0, 1, 2))
        V = np.abs(U) if v is None else np.ascontiguousarray(v.reshape(*g.vshape, 3).transpose(3, 0, 1, 2))
        out = np.zeros((3, *g.vshape)) if signed else None
        magnitude = np.zeros((3, *g.vshape))
        plane = np.zeros((3, 3, *g.vshape))
        scratch = np.empty(g.vshape)
        for d, nodes, blocks in g.q2_offsets:
            _check(cancel)
            values = (blocks@self._etaw_q).reshape(len(nodes), 3, 3, nx, ny, nz)
            plane.fill(0.)
            for t, (i, j, k) in enumerate(nodes):
                plane[:, :, i:i+2*nx:2, j:j+2*ny:2, k:k+2*nz:2] += values[t]
            rows, cols = _shift(g.vshape, d)
            part = scratch[rows]
            for a in range(3):
                for b in range(3):
                    coupling = plane[(a, b)+rows]
                    if signed:
                        np.multiply(coupling, U[(b,)+cols], out=part)
                        out[(a,)+rows] += part
                    np.abs(coupling, out=coupling)
                    np.multiply(coupling, V[(b,)+cols], out=part)
                    magnitude[(a,)+rows] += part
        magnitude = magnitude.transpose(1, 2, 3, 0).ravel()
        return (out.transpose(1, 2, 3, 0).ravel() if signed else None), magnitude

    def row_magnitudes(self):
        """Assembled row sums of |A| (all rows), computed once."""
        if self._rowsum is None:
            self._rowsum = self.products(np.ones(3*self.geometry.nv), signed=False)[1]
        return self._rowsum

    def _assemble_q1(self, cancel):
        g = self.geometry
        planes = np.zeros((27, *g.pshape, 3, 3))
        for d, plane in self._planes(g.q1_offsets, g.pshape, 1, cancel):
            planes[g.q1_offset_order[d]] = plane
        # Row (node, a) lists its offsets in lexicographic column order, then b.
        return np.moveaxis(planes, 0, -2)[g.q1_entry]

    # ------------------------------------------------------------ multigrid
    def _apply_fine(self, x):
        """A_ff on a full-length vector that is zero on constrained components."""
        return self.apply(x)*self._mask

    def _chebyshev(self, apply, inverse, mask, cancel):
        n = len(inverse)
        scale = np.sqrt(inverse)
        v = np.cos(1.3*np.arange(n))+1.                     # deterministic start
        if mask is not None:
            v *= mask
        v /= np.linalg.norm(v)
        alpha, beta, previous, b = [], [], np.zeros(n), 0.
        for _ in range(min(SETTINGS['lanczos_steps'], n)):
            _check(cancel)
            w = scale*apply(scale*v)
            a = float(v@w)
            alpha.append(a)
            w = w-a*v-b*previous
            b = float(np.linalg.norm(w))
            if not b > 1e-14*abs(a):
                break
            beta.append(b)
            previous, v = v, w/b
        m = len(alpha)
        T = np.diag(alpha)+np.diag(beta[:m-1], 1)+np.diag(beta[:m-1], -1)
        upper = SETTINGS['eigen_safety']*float(np.max(np.linalg.eigvalsh(T)))
        if not (np.isfinite(upper) and upper > 0):
            raise ValueError('invalid multigrid smoothing bound')
        return (apply, inverse, upper, upper/SETTINGS['smoothing_range'])

    @staticmethod
    def _smooth(smoother, rhs, x):
        apply, inverse, upper, lower = smoother
        theta, delta = (upper+lower)/2, (upper-lower)/2
        sigma = theta/delta
        rho = 1/sigma
        direction = inverse*(rhs if x is None else rhs-apply(x))/theta
        x = direction.copy() if x is None else x+direction
        for _ in range(SETTINGS['chebyshev_degree']-1):
            following = 1/(2*sigma-rho)
            direction = (following*rho)*direction+(2*following/delta)*(inverse*(rhs-apply(x)))
            x = x+direction
            rho = following
        return x

    def _prolong(self, level, x):
        g = self.geometry
        if level > 0:
            return g.levels[level-1]['prolong']@x
        X = np.zeros(3*int(np.prod(g.pshape)))
        X[g.free1] = x
        X = X.reshape(*g.pshape, 3)
        for axis in range(3):
            X = np.moveaxis(X, axis, 0)
            Y = np.empty((2*X.shape[0]-1,)+X.shape[1:])
            Y[0::2] = X
            Y[1::2] = .5*(X[:-1]+X[1:])
            X = np.moveaxis(Y, 0, axis)
        # Coarse zeros on constrained faces interpolate to zeros there; the mask
        # only removes rounding-free structural zeros, it changes no value.
        return X.reshape(-1)*self._mask

    def _restrict(self, level, r):
        g = self.geometry
        if level > 0:
            return g.levels[level-1]['prolong'].T@r
        R = r.reshape(*g.vshape, 3)
        for axis in range(3):
            R = np.moveaxis(R, axis, 0)
            S = R[0::2].copy()
            S[:-1] += .5*R[1::2]
            S[1:] += .5*R[1::2]
            R = np.moveaxis(S, 0, axis)
        return R.reshape(-1)[g.free1]

    def _cycle(self, rhs, level):
        if level == len(self.smoothers):
            return self.coarse.solve(rhs)
        smoother = self.smoothers[level]
        x = self._smooth(smoother, rhs, None)
        coarse = self._cycle(self._restrict(level, rhs-smoother[0](x)), level+1)
        x = x+self._prolong(level, coarse)
        return self._smooth(smoother, rhs, x)

    def vcycle(self, rhs):
        """One V(1,1) cycle for A_ff on a free-component vector."""
        g = self.geometry
        full = np.zeros(3*g.nv)
        full[g.free] = rhs
        return self._cycle(full, 0)[g.free]

    # ------------------------------------------------------------ Stokes system
    def K(self, x, gauge):
        """[A_ff B_f^T 0; B_f 0 w; 0 w^T 0] x for x = (free velocity, pressure[, multiplier])."""
        g = self.geometry
        nf = len(g.free)
        u = np.zeros(3*g.nv)
        u[g.free] = x[:nf]
        p = x[nf:nf+g.np]
        y, div = self.apply(u, p, divergence=True)
        if gauge:
            return np.concatenate((y[g.free], div+g.w*x[-1], [g.w@p]))
        return np.concatenate((y[g.free], div))

    def precondition(self, r, gauge):
        g = self.geometry
        nf = len(g.free)
        rv, rp = r[:nf], r[nf:nf+g.np]
        zs = self.mass.solve(rp)
        if gauge:
            lam = (r[-1]+g.w@zs)/self.wSw
            zp = self.Sw*lam-zs
        else:
            zp = -zs
        zv = self.vcycle(rv-(g.B.T@zp)[g.free])
        self.applications += 1
        return np.concatenate((zv, zp, [lam])) if gauge else np.concatenate((zv, zp))

    def solve(self, b, gauge, rtol, maxiter, callback=None, accept=None):
        return fgmres_dr(lambda x: self.K(x, gauge), lambda r: self.precondition(r, gauge), b, rtol,
                         SETTINGS['restart'], SETTINGS['deflation'], maxiter, callback, accept)


def fgmres_dr(apply, precondition, b, rtol, restart, deflation, maxiter, callback=None, accept=None):
    """Flexible GMRES with deflated restarting; returns (x, converged, iterations).

    Right preconditioning keeps ``A Z_j = V_{j+1} Hbar_j`` (Saad 1993), so a
    varying preconditioner stays admissible. At a restart the ``deflation``
    harmonic Ritz vectors of smallest magnitude (Morgan 2002) are kept in
    (V, Z) as in the flexible variant of Giraud, Gratton, Pinel and Vasseur
    (2010); an ill-conditioned or non-finite step restarts plainly instead.

    Every cycle ends by recomputing the true residual ``b - A x``. The solve aims
    for ``rtol ||b||_2``. A cycle whose true residual exceeds twice the
    recurrence's own estimate (rounding accumulated in a deflated basis) restarts
    plainly from the true residual. When the recurrence claims convergence that
    the true residual does not show, the next cycle restarts plainly with a
    tighter inner target, as SciPy's GMRES tightens its inner tolerance; if two
    such claims in a row do not halve the true residual, the attainable floor
    has been reached and the solve stops. ``converged`` is then (and at the
    iteration ceiling) true only if the recomputed true residual is at most
    ``accept ||b||_2`` (default ``rtol``). ``b`` is scaled internally, so no
    norm under- or overflows.
    """
    n = b.size
    x = np.zeros(n)
    size = float(np.max(np.abs(b))) if n else 0.
    if size == 0.:
        return x, True, 0
    if not np.isfinite(size):
        raise FloatingPointError('non-finite right-hand side')
    b = b/size
    bnorm = float(np.linalg.norm(b))
    target = rtol*bnorm
    acceptable = (rtol if accept is None else max(rtol, accept))*bnorm
    V = np.empty((restart+1, n)); Z = np.empty((restart, n))
    H = np.zeros((restart+1, restart)); c = np.zeros(restart+1)
    total, start = 0, 0
    r = b.copy()
    beta = bnorm
    inner = target
    floor = 64*np.finfo(float).eps*bnorm
    claimed_before = None

    def plain(r, beta):
        V[0] = r/beta
        H[:] = 0.; c[:] = 0.; c[0] = beta
        return 0

    start = plain(r, beta)
    while total < maxiter:
        j = start
        breakdown = claimed = False
        estimate = np.inf
        while j < restart and total < maxiter:
            Z[j] = precondition(V[j])
            w = apply(Z[j])
            h = V[:j+1]@w
            w -= V[:j+1].T@h
            correction = V[:j+1]@w                                     # classical Gram-Schmidt, twice
            w -= V[:j+1].T@correction
            h += correction
            norm = float(np.linalg.norm(w))
            H[:j+1, j] = h; H[j+1, j] = norm
            total += 1
            j += 1
            if not np.all(np.isfinite(h)) or not np.isfinite(norm):
                raise FloatingPointError('non-finite Krylov basis')
            y = lstsq(H[:j+1, :j], c[:j+1], check_finite=False)[0]
            estimate = float(np.linalg.norm(c[:j+1]-H[:j+1, :j]@y))
            if callback is not None:
                callback(estimate/bnorm)
            if norm > 0.:
                V[j] = w/norm
            else:
                breakdown = True
            if estimate <= inner or breakdown:
                claimed = estimate <= inner
                break
        y = lstsq(H[:j+1, :j], c[:j+1], check_finite=False)[0]
        x += Z[:j].T@y
        r = b-apply(x)
        beta = float(np.linalg.norm(r))
        if not np.isfinite(beta):
            raise FloatingPointError('non-finite Krylov residual')
        if beta <= target:
            return x*size, True, total
        if total >= maxiter:
            break
        if claimed:
            if claimed_before is not None and beta > .5*claimed_before:
                break                                   # attainable residual floor reached
            claimed_before = beta
            inner = max(floor, inner*min(.5, .5*estimate/beta))
            start = plain(r, beta)
            continue
        if breakdown or beta > 2*estimate:
            start = plain(r, beta)                      # resynchronise with the true residual
            continue
        start = _deflate(V, Z, H, c, y, j, deflation)
        if start is None:
            start = plain(r, beta)
    return x*size, bool(beta <= acceptable), total


def _deflate(V, Z, H, c, y, j, deflation):
    """Keep k harmonic Ritz directions; returns the new start index or None."""
    k = min(deflation, j-1)
    if k < 1 or H[j, j-1] == 0.:
        return None
    Hbar, square = H[:j+1, :j], H[:j, :j]
    with np.errstate(all='ignore'):
        try:
            values, vectors = eig(Hbar.T@Hbar, square.T, check_finite=False)
        except (np.linalg.LinAlgError, ValueError):
            return None
    finite = np.isfinite(values)
    if not np.any(finite):
        return None
    order = [i for i in np.argsort(np.where(finite, np.abs(values), np.inf)) if finite[i]]
    columns, used = [], set()
    for i in order:
        if len(columns) >= k:
            break
        if i in used:
            continue
        vector = vectors[:, i]
        if abs(values[i].imag) > 1e-12*abs(values[i]):
            partner = int(np.argmin(np.abs(values-np.conj(values[i]))))
            used.update((i, partner))
            if len(columns)+2 > k:
                continue
            columns += [vector.real, vector.imag]
        else:
            used.add(i)
            columns.append(vector.real)
    if not columns:
        return None
    residual = c[:j+1]-Hbar@y
    block = np.zeros((j+1, len(columns)+1))
    block[:j, :len(columns)] = np.column_stack(columns)
    block[:, -1] = residual
    if not np.all(np.isfinite(block)):
        return None
    Q, R = np.linalg.qr(block)
    if np.any(np.abs(np.diag(R)[:-1]) <= 1e-12*np.max(np.abs(np.diag(R)))):
        return None
    k = len(columns)
    Qk = Q[:j, :k]
    Hnew = Q.T@Hbar@Qk
    V[:k+1] = Q.T@V[:j+1]
    Z[:k] = Qk.T@Z[:j]
    H[:] = 0.; H[:k+1, :k] = Hnew
    cnew = Q.T@residual
    c[:] = 0.; c[:k+1] = cnew
    return k
