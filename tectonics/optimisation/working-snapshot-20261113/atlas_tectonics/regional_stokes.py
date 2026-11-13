"""Bounded variable-viscosity, full-stress variational MAC core for W07.

SPDX-License-Identifier: AGPL-3.0-only

Coordinates are x-right, z-up. Pressure is compressive: sigma=-p I+2 eta D.
This module is numerical only; the public execution wrapper owns units, source
identity, admission and publication. There is no automatic direct fallback.

Normal velocity lives on cell faces, pressure/normal strain in cells, and shear
strain on vertices. Tangential boundary traces are explicit unknowns. Their
half-cell derivatives and trapezoidal boundary quadrature make the weak full
stress form exact for affine velocity, including at corners. A free corner's
unresolved point trace is linearly reconstructed in the shear-orthogonal
direction. This removes a point-only null mode, not a physical rigid mode.
"""
from __future__ import annotations

from time import perf_counter
from concurrent.futures import CancelledError

import numpy as np
from scipy import sparse
from scipy.sparse.linalg import LinearOperator, gmres, spilu, splu


SIDES = ("left", "right", "bottom", "top")
COMPONENTS = ("u", "w")
_NORMAL = ("u", "u", "w", "w")


def _normal(side):
    return _NORMAL[SIDES.index(side)]


def _check(cancel):
    if cancel is not None and (cancel.is_set() if hasattr(cancel, "is_set") else cancel()):
        raise CancelledError("regional Stokes calculation cancelled")


def _positive(value, name):
    value = float(value)
    if not np.isfinite(value) or value <= 0:
        raise ValueError(name + " must be finite and positive")
    return value


def boundary_coordinates(nx, nz, width, height, side, component):
    """Boundary sample coordinates; normal endpoints carry no face measure.

    Normal samples are [corner, face centres..., corner]. Tangential samples
    are vertices, including both corners. The normal endpoints validate the
    two prescribed traces meeting at a corner; they are not extra flux faces.
    """
    if side not in SIDES or component not in COMPONENTS:
        raise ValueError("unknown boundary side or component")
    horizontal = side in ("bottom", "top")
    n, length = (nx, width) if horizontal else (nz, height)
    q = (np.r_[0., (np.arange(n)+.5)*length/n, length]
         if component == _normal(side) else np.linspace(0., length, n+1))
    if horizontal:
        return q, np.full_like(q, 0. if side == "bottom" else height)
    return np.full_like(q, 0. if side == "left" else width), q


def _sample_boundaries(nx, nz, width, height, boundaries, pattern=None):
    if not isinstance(boundaries, dict) or set(boundaries) != set(SIDES):
        raise ValueError("all four boundary sides must be declared")
    values, kinds = {}, {}
    for side in SIDES:
        if not isinstance(boundaries[side], dict) or set(boundaries[side]) != set(COMPONENTS):
            raise ValueError("each boundary declares exactly u and w")
        values[side], kinds[side] = {}, {}
        for component in COMPONENTS:
            item = boundaries[side][component]
            if not isinstance(item, (tuple, list)) or len(item) != 2 or item[0] not in ("velocity", "traction"):
                raise ValueError("component requires exactly one velocity or traction declaration")
            kind, value = item
            if pattern is not None and kind != pattern[side][component]:
                raise ValueError("prepared boundary component type cannot change")
            x, z = boundary_coordinates(nx, nz, width, height, side, component)
            a = np.asarray(value(x, z) if callable(value) else value, dtype=np.float64)
            if a.ndim == 0:
                a = np.full(x.shape, float(a))
            if a.shape != x.shape or not np.all(np.isfinite(a)):
                raise ValueError("boundary samples have wrong shape or nonfinite values")
            a = a.copy()
            a.flags.writeable = False
            values[side][component], kinds[side][component] = a, kind
    return values, kinds


def _csr(rows, cols, data, shape):
    return sparse.coo_matrix((data, (rows, cols)), shape=shape).tocsr()


class MACPlan:
    """Reusable sparse full-stress operator and explicitly selected factors."""

    def __init__(self, nx, nz, width, height, eta, boundaries, *, eta_center=None,
                 eta_vertex=None, pressure_mean=None,
                 rigid_constraints=None, method="gmres", linear_rtol=1e-12,
                 max_iterations=1200, restart=60, cancel=None):
        start = perf_counter()
        _check(cancel)
        if isinstance(nx, bool) or isinstance(nz, bool) or int(nx) != nx or int(nz) != nz:
            raise ValueError("grid counts must be integers")
        self.nx, self.nz = int(nx), int(nz)
        if not (2 <= self.nx <= 64 and 2 <= self.nz <= 64):
            raise ValueError("W07 MAC core supports 2..64 cells per direction")
        self.width, self.height = _positive(width, "width"), _positive(height, "height")
        coefficients = self._coefficients(eta, eta_center, eta_vertex)
        self.dx, self.dz = self.width/self.nx, self.height/self.nz
        self.volume = self.dx*self.dz
        if method not in ("gmres", "direct"):
            raise ValueError("method must explicitly select gmres or direct")
        if not np.isfinite(linear_rtol) or not 0 < linear_rtol <= 1e-12:
            raise ValueError("linear_rtol must be positive and no looser than 1e-12")
        if isinstance(max_iterations, bool) or int(max_iterations) != max_iterations or max_iterations < 1:
            raise ValueError("max_iterations must be a positive integer")
        if isinstance(restart, bool) or int(restart) != restart or restart < 2:
            raise ValueError("restart must be an integer >=2")
        self.method, self.linear_rtol = method, float(linear_rtol)
        self.max_iterations, self.restart = int(max_iterations), int(restart)
        self._values, self.pattern = _sample_boundaries(nx, nz, width, height, boundaries)
        self.gauge_required = all(self.pattern[s][_normal(s)] == "velocity" for s in SIDES)
        if self.gauge_required:
            if pressure_mean is None or not np.isfinite(float(pressure_mean)):
                raise ValueError("all normal velocities require an explicit finite pressure mean")
            self.pressure_mean = float(pressure_mean)
        else:
            if pressure_mean is not None:
                raise ValueError("normal traction determines pressure; an extra gauge is forbidden")
            self.pressure_mean = None
        if rigid_constraints not in (None, "zero-mean-translation-rotation"):
            raise ValueError("unsupported rigid-mode constraint")
        self.rigid_constraints = rigid_constraints
        self._closed = False
        self._build(cancel)
        self.unknowns = self.velocity_unknowns+self.pressure_unknowns+self.rigid_modes+int(self.gauge_required)
        if self.method == "direct" and self.unknowns > 1024:
            raise ValueError("direct oracle is limited to 1024 augmented unknowns")
        self._lift(self._values)  # reject incompatible flux before factorisation
        _check(cancel)
        topology_s = perf_counter()-start
        self._install_numeric(coefficients, self._numeric(coefficients, cancel))
        self.timings["topology_s"] = topology_s
        self.timings["assembly_s"] += topology_s
        self.timings["prepare_s"] = perf_counter()-start

    def _coefficients(self, eta, eta_center, eta_vertex):
        """Copy source-defined stress coefficients; never infer an averaging law."""
        if eta_center is None and eta_vertex is None:
            if eta is None:
                raise ValueError("provide scalar eta or both explicit stress-site viscosities")
            scalar = _positive(eta, "eta")
            center = np.full((self.nz, self.nx), scalar)
            vertex = np.full((self.nz+1, self.nx+1), scalar)
        else:
            if eta is not None or eta_center is None or eta_vertex is None:
                raise ValueError("explicit stress-site viscosity requires eta=None and both eta_center and eta_vertex")
            scalar = None
            center = np.asarray(eta_center, dtype=np.float64)
            vertex = np.asarray(eta_vertex, dtype=np.float64)
            if center.shape != (self.nz, self.nx) or vertex.shape != (self.nz+1, self.nx+1):
                raise ValueError("eta_center/eta_vertex must match complete cell/vertex supports")
            if any(not np.all(np.isfinite(a)) or np.any(a <= 0.) for a in (center, vertex)):
                raise ValueError("stress-site viscosity must be finite and positive")
            center, vertex = center.copy(), vertex.copy()
        center.flags.writeable = vertex.flags.writeable = False
        return scalar, center, vertex

    def refill_viscosity(self, *, eta_center, eta_vertex, cancel=None):
        """Replace both stress-site coefficients, reusing fixed geometry/topology.

        Numeric matrices and factors are rebuilt for the actual current arrays.
        Validation, cancellation or factorisation failure preserves the old plan.
        The execution owner must admit the simultaneous old/new numeric storage.
        """
        if self._closed:
            raise RuntimeError("MAC plan is closed")
        _check(cancel)
        coefficients = self._coefficients(None, eta_center, eta_vertex)
        self._install_numeric(coefficients, self._numeric(coefficients, cancel))
        return dict(self.timings)

    def _install_numeric(self, coefficients, numeric):
        self.eta, self.eta_center, self.eta_vertex = coefficients
        self._eta_reference = min(float(self.eta_center.min()), float(self.eta_vertex.min()))
        self.__dict__.update(numeric)
        self._preconditioner = (LinearOperator(self.matrix.shape, self._precondition)
                                if self.method == "gmres" else None)
        self.matrix_nnz = int(self.matrix.nnz)
        self.retained_nbytes = self._retained_size()

    def _build(self, cancel):
        nx, nz, dx, dz = self.nx, self.nz, self.dx, self.dz
        nu = (nz+2)*(nx+1)
        self._iu = np.arange(nu).reshape(nz+2, nx+1)
        self._iw = np.arange(nu, nu+(nz+1)*(nx+2)).reshape(nz+1, nx+2)
        self.full_velocity_unknowns = int(self._iw[-1, -1]+1)
        nf, nc = self.full_velocity_unknowns, nx*nz
        self.pressure_unknowns = nc
        self._indices = {
            "left": {"u": self._iu[:, 0], "w": self._iw[:, 0]},
            "right": {"u": self._iu[:, -1], "w": self._iw[:, -1]},
            "bottom": {"u": self._iu[0, :], "w": self._iw[0, :]},
            "top": {"u": self._iu[-1, :], "w": self._iw[-1, :]},
        }
        self._weights = {}
        fixed = np.zeros(nf, dtype=bool)
        for side in SIDES:
            self._weights[side] = {}
            for component in COMPONENTS:
                ids = self._indices[side][component]
                h = dz if side in ("left", "right") else dx
                weights = np.full(len(ids), h)
                weights[[0, -1]] *= 0. if component == _normal(side) else .5
                self._weights[side][component] = weights
                if self.pattern[side][component] == "velocity":
                    fixed[ids] = True
        self._fixed = fixed
        # One shear-orthogonal point trace per entirely free corner is absent
        # from the bulk MAC space. Reconstruct it using the nearest two normal
        # face traces. The relation reproduces every affine velocity exactly.
        removed, relations = [], {}
        for ju, jw, si, sw, au, bw in ((0, 0, 0, 0, -2/dz, -2/dx),
                                       (0, 0, nx, nx+1, -2/dz, 2/dx),
                                       (nz+1, nz, 0, 0, 2/dz, -2/dx),
                                       (nz+1, nz, nx, nx+1, 2/dz, 2/dx)):
            iu, iw = self._iu[ju, si], self._iw[jw, sw]
            if fixed[iu] or fixed[iw]:
                continue
            near_u = (1, 2) if ju == 0 else (nz, nz-1)
            near_w = (1, 2) if sw == 0 else (nx, nx-1)
            ratio = bw/au
            relations[iw] = {iu: ratio,
                             self._iu[near_u[0], si]: -1.5*ratio,
                             self._iu[near_u[1], si]: .5*ratio,
                             self._iw[jw, near_w[0]]: 1.5,
                             self._iw[jw, near_w[1]]: -.5}
            removed.append(iw)
        self._independent = np.setdiff1d(np.arange(nf), removed)
        rev = np.full(nf, -1, dtype=int)
        rev[self._independent] = np.arange(len(self._independent))
        qr, qc, qv = list(self._independent), list(range(len(self._independent))), [1.]*len(self._independent)
        for row, terms in relations.items():
            for col, value in terms.items():
                qr.append(row); qc.append(rev[col]); qv.append(value)
        self._Q = _csr(qr, qc, qv, (nf, len(self._independent)))
        self._free_ind = np.flatnonzero(~fixed[self._independent])
        self._fixed_ind = np.flatnonzero(fixed[self._independent])
        self._P = self._Q[:, self._free_ind].tocsr()
        self.velocity_unknowns = self._P.shape[1]
        rows = np.arange(nc).reshape(nz, nx)
        self._Bx = _csr(np.r_[rows.ravel(), rows.ravel()],
                        np.r_[self._iu[1:-1, :-1].ravel(), self._iu[1:-1, 1:].ravel()],
                        np.r_[np.full(nc, -1/dx), np.full(nc, 1/dx)], (nc, nf))
        self._Bz = _csr(np.r_[rows.ravel(), rows.ravel()],
                        np.r_[self._iw[:-1, 1:-1].ravel(), self._iw[1:, 1:-1].ravel()],
                        np.r_[np.full(nc, -1/dz), np.full(nc, 1/dz)], (nc, nf))
        sr, sc, sv = [], [], []
        for j in range(nz+1):
            _check(cancel)
            for i in range(nx+1):
                row = j*(nx+1)+i
                zu, zl, az = ((1, 0, 2/dz) if j == 0 else
                              (nz+1, nz, 2/dz) if j == nz else (j+1, j, 1/dz))
                xr, xl, ax = ((1, 0, 2/dx) if i == 0 else
                              (nx+1, nx, 2/dx) if i == nx else (i+1, i, 1/dx))
                sr.extend((row,)*4)
                sc.extend((self._iu[zu, i], self._iu[zl, i], self._iw[j, xr], self._iw[j, xl]))
                sv.extend((az, -az, ax, -ax))
        self._S = _csr(sr, sc, sv, ((nz+1)*(nx+1), nf))
        qx, qz = np.ones(nx+1), np.ones(nz+1)
        qx[[0, -1]] = .5; qz[[0, -1]] = .5
        self._vertex_volume = self.volume*np.outer(qz, qx)
        self._body_weights = np.zeros(nf)
        self._body_weights[self._iu[1:-1, :]] = self.volume*qx[None, :]
        self._body_weights[self._iw[:, 1:-1]] = self.volume*qz[:, None]
        self._D = (self._Bx+self._Bz).tocsr()
        x, z = self.velocity_coordinates()
        rigid = np.zeros((nf, 3))
        rigid[:self._iu.size, 0] = 1.
        rigid[self._iu.size:, 1] = 1.
        rigid[:self._iu.size, 2] = -(z[:self._iu.size]-self.height/2)
        rigid[self._iu.size:, 2] = x[self._iu.size:]-self.width/2
        # Only continuum rigid modes left unconstrained by velocity data count.
        fixed_rigid = rigid[fixed, :]
        if len(fixed_rigid):
            _, singular, vt = np.linalg.svd(fixed_rigid, full_matrices=False)
            rank = int(np.sum(singular > 1e-12*max(1., singular[0])))
            null = vt[rank:].T
        else:
            null = np.eye(3)
        self._rigid = rigid@null
        self.rigid_modes = self._rigid.shape[1]
        if self.rigid_modes and self.rigid_constraints is None:
            raise ValueError("unresolved rigid motion requires explicit zero-mean translation/rotation constraints")
        self._Cfull = (self._body_weights[:, None]*self._rigid).T
        if self.rigid_modes:
            self._Cfull /= np.linalg.norm(self._Cfull, axis=1)[:, None]
        self._G = (-self.volume*self._P.T@self._D.T).tocsr()
        self._C = sparse.csr_matrix(self._Cfull@self._P)

    def _numeric(self, coefficients, cancel):
        start = perf_counter()
        _check(cancel)
        _, center, vertex = coefficients
        normal = sparse.diags((2*self.volume*center).ravel())
        shear = sparse.diags((self._vertex_volume*vertex).ravel())
        k = (self._Bx.T@normal@self._Bx+self._Bz.T@normal@self._Bz
             +self._S.T@shear@self._S).tocsr()
        a = (self._P.T@k@self._P).tocsr()
        g, c = self._G, self._C
        nc, nrigid, ng = self.pressure_unknowns, self.rigid_modes, int(self.gauge_required)
        gauge = sparse.csr_matrix(np.ones((nc, 1))/np.sqrt(nc)) if ng else sparse.csr_matrix((nc, 0))
        matrix = sparse.bmat([
            [a, g, c.T, sparse.csr_matrix((a.shape[0], ng))],
            [g.T, sparse.csr_matrix((nc, nc)), sparse.csr_matrix((nc, nrigid)), gauge],
            [c, sparse.csr_matrix((nrigid, nc)), sparse.csr_matrix((nrigid, nrigid)), sparse.csr_matrix((nrigid, ng))],
            [sparse.csr_matrix((ng, a.shape[0])), gauge.T, sparse.csr_matrix((ng, nrigid)), sparse.csr_matrix((ng, ng))]
        ], format="csr")
        if not np.all(np.isfinite(matrix.data)):
            raise ValueError("stress-site coefficients overflow the numerical operator")
        _check(cancel)
        factor_start = perf_counter()
        pressure_mass = .5*self.volume/center.ravel()
        if not np.all(np.isfinite(pressure_mass)) or np.any(pressure_mass <= 0.):
            raise ValueError("stress-site viscosity exceeds finite pressure-mass support")
        result = {"_K": k, "_A": a, "matrix": matrix, "_pressure_mass": pressure_mass}
        if self.method == "direct":
            result["_factor"] = splu(matrix.tocsc())
        else:
            # Inverse-viscosity pressure mass, with its weighted gauge below.
            # The rigid shift affects only the ILU, never physical stresses.
            pre_a = a
            if self.rigid_modes:
                eta_ref = min(float(center.min()), float(vertex.min()))
                pre_a = pre_a+sparse.eye(a.shape[0])*eta_ref*self.volume/min(self.width, self.height)**2
            factor = spilu(pre_a.tocsc(), drop_tol=1e-5, fill_factor=12., permc_spec="COLAMD")
            result["_factor"] = factor
            if self.rigid_modes:
                inverse = factor.solve(c.T.toarray())
                result["_rigid_inverse"] = inverse
                result["_rigid_schur"] = np.asarray(c@inverse)
        _check(cancel)
        result["timings"] = {"topology_s": 0., "assembly_s": factor_start-start,
                             "factor_s": perf_counter()-factor_start,
                             "prepare_s": perf_counter()-start}
        return result

    def _precondition(self, rhs):
        nv, npres = self.velocity_unknowns, self.pressure_unknowns
        v = self._factor.solve(rhs[:nv])
        h = rhs[nv:nv+npres]-self._G.T@v
        alpha = self._pressure_mass
        if self.gauge_required:
            # Solve [-diag(alpha), q; q.T, 0] exactly for q=1/sqrt(n).
            # Subtracting an unweighted pressure mean is wrong for variable eta.
            q = 1/np.sqrt(npres)
            multiplier = (rhs[-1]+q*np.sum(h/alpha))/(q*q*np.sum(1/alpha))
            pressure = (-h+q*multiplier)/alpha
            gauge = [multiplier]
        else:
            pressure, gauge = -h/alpha, []
        v -= self._factor.solve(self._G@pressure)
        if self.rigid_modes:
            rigid = np.linalg.solve(self._rigid_schur, self._C@v-rhs[nv+npres:nv+npres+self.rigid_modes])
            v -= self._rigid_inverse@rigid
        else:
            rigid = []
        return np.r_[v, pressure, rigid, gauge]

    def velocity_coordinates(self):
        """Coordinates in the complete returned velocity-vector ordering."""
        xu, zu = np.meshgrid(np.linspace(0., self.width, self.nx+1),
                             np.r_[0., (np.arange(self.nz)+.5)*self.dz, self.height])
        xw, zw = np.meshgrid(np.r_[0., (np.arange(self.nx)+.5)*self.dx, self.width],
                             np.linspace(0., self.height, self.nz+1))
        return np.r_[xu.ravel(), xw.ravel()], np.r_[zu.ravel(), zw.ravel()]

    def force_coordinates(self):
        """Two (x,z) array pairs in force_u and force_w shape/order."""
        return (np.meshgrid(np.linspace(0., self.width, self.nx+1),
                            (np.arange(self.nz)+.5)*self.dz),
                np.meshgrid((np.arange(self.nx)+.5)*self.dx,
                            np.linspace(0., self.height, self.nz+1)))

    def _lift(self, values):
        prescribed = np.zeros(self.full_velocity_unknowns)
        seen = np.zeros_like(prescribed, dtype=bool)
        for side in SIDES:
            for component in COMPONENTS:
                if self.pattern[side][component] != "velocity":
                    continue
                ids, vals = self._indices[side][component], values[side][component]
                overlap = seen[ids]
                if np.any(np.abs(prescribed[ids][overlap]-vals[overlap]) >
                          64*np.finfo(float).eps*np.maximum(1., np.abs(vals[overlap]))):
                    raise ValueError("contradictory prescribed corner traces")
                prescribed[ids] = vals
                seen[ids] = True
        if self.gauge_required:
            flux, absolute = 0., 0.
            for side, sign in (("left", -1.), ("right", 1.), ("bottom", -1.), ("top", 1.)):
                comp = _normal(side)
                terms = self._weights[side][comp]*values[side][comp]
                flux += sign*float(np.sum(terms))
                absolute += float(np.sum(np.abs(terms)))
            if abs(flux) > 1e-12*max(1., absolute):
                raise ValueError("prescribed normal velocity has incompatible net boundary flux")
        independent = np.zeros(len(self._independent))
        independent[self._fixed_ind] = prescribed[self._independent[self._fixed_ind]]
        return np.asarray(self._Q@independent).ravel()

    def _loads(self, force_u, force_w, values):
        fu, fw = np.asarray(force_u, dtype=float), np.asarray(force_w, dtype=float)
        if fu.shape != (self.nz, self.nx+1) or fw.shape != (self.nz+1, self.nx):
            raise ValueError("body forces must be sampled on both complete MAC face arrays")
        if not np.all(np.isfinite(fu)) or not np.all(np.isfinite(fw)):
            raise ValueError("body force contains nonfinite samples")
        force = np.zeros(self.full_velocity_unknowns)
        force[self._iu[1:-1]] = fu
        force[self._iw[:, 1:-1]] = fw
        body = force*self._body_weights
        traction = np.zeros_like(body)
        for side in SIDES:
            for component in COMPONENTS:
                if self.pattern[side][component] == "traction":
                    np.add.at(traction, self._indices[side][component],
                              self._weights[side][component]*values[side][component])
        if self.rigid_modes:
            load = body+traction
            residual = self._rigid.T@load
            scales = np.maximum(1., np.abs(self._rigid).T@(np.abs(body)+np.abs(traction)))
            if np.any(np.abs(residual) > 1e-11*scales):
                raise ValueError("external force/torque is incompatible with unconstrained rigid modes")
        return force, body, traction

    def _boundary_values(self, boundaries):
        if boundaries is None:
            return self._values
        return _sample_boundaries(self.nx, self.nz, self.width, self.height,
                                  boundaries, self.pattern)[0]

    def solve(self, force_u, force_w, *, boundaries=None, cancel=None):
        if self._closed:
            raise RuntimeError("MAC plan is closed")
        start = perf_counter()
        _check(cancel)
        values = self._boundary_values(boundaries)
        lift = self._lift(values)
        _, body, traction = self._loads(force_u, force_w, values)
        rhs = np.r_[self._P.T@(body+traction-self._K@lift),
                    self.volume*(self._D@lift), -self._Cfull@lift,
                    [self.pressure_mean*np.sqrt(self.pressure_unknowns)] if self.gauge_required else []]
        _check(cancel)
        iterations = 0
        def callback(_):
            nonlocal iterations
            iterations += 1
            _check(cancel)
            if iterations >= self.max_iterations:
                raise RuntimeError("regional GMRES iteration ceiling reached")
        def linear_solve(load):
            _check(cancel)
            if self.method == "direct":
                return self._factor.solve(load)
            if not np.any(load):
                return np.zeros(self.unknowns)
            answer, info = gmres(self.matrix, load, M=self._preconditioner,
                                 rtol=self.linear_rtol, atol=0., restart=self.restart,
                                 maxiter=self.max_iterations, callback=callback,
                                 callback_type="pr_norm")
            if info != 0:
                raise RuntimeError("regional GMRES did not converge; no direct fallback")
            return answer
        solution = linear_solve(rhs)
        nv, npres = self.velocity_unknowns, self.pressure_unknowns
        # Large eta times nonzero boundary lifts can hide small physical loads
        # in the algebraic RHS. At most two defect corrections use the separately
        # scattered current stresses, retaining every existing field gate and
        # the shared iteration ceiling. This is not a solver/tolerance fallback.
        for corrections in range(3):
            full = np.asarray(self._P@solution[:nv]).ravel()+lift
            result = self.evaluate(full, solution[nv:nv+npres], force_u, force_w,
                                   boundaries=boundaries, cancel=cancel)
            if result["diagnostics"]["gates_passed"] or corrections == 2:
                break
            defect = np.r_[-result["free_force_residual"],
                           self.volume*(result["exx"]+result["ezz"]).ravel(),
                           -self._Cfull@full,
                           [(self.pressure_mean-float(np.mean(result["p"])))*np.sqrt(npres)]
                           if self.gauge_required else []]
            correction = linear_solve(defect)
            solution[:nv+npres] += correction[:nv+npres]
            # This defect contains the physical stress load, not the old
            # algebraic constraint forces, so its multipliers replace them.
            solution[nv+npres:] = correction[nv+npres:]
        _check(cancel)
        residual = self.matrix@solution-rhs
        linear_residual = float(np.linalg.norm(residual)/max(np.linalg.norm(rhs), np.finfo(float).tiny))
        if linear_residual > self.linear_rtol:
            raise RuntimeError("regional algebraic residual failed its fixed tolerance")
        result["iterations"] = iterations
        result["diagnostics"]["defect_corrections"] = corrections
        result["diagnostics"]["linear_residual"] = linear_residual
        if not result["diagnostics"]["gates_passed"]:
            raise RuntimeError("regional independent field diagnostics failed fixed gates: " + str(result["diagnostics"]))
        result["constraint_multipliers"] = solution[nv+npres:].copy()
        result["timings"] = {**self.timings, "solve_s": perf_counter()-start}
        return result

    def evaluate(self, velocity_vector, pressure, force_u, force_w, *, boundaries=None, cancel=None):
        """Independently recompute strains, stresses, balances and work.

        This path does not multiply by the assembled stiffness/saddle matrix.
        It is also the public wrapper's post-SI-roundtrip validation seam.
        """
        if self._closed:
            raise RuntimeError("MAC plan is closed")
        _check(cancel)
        v, p = np.asarray(velocity_vector, dtype=float), np.asarray(pressure, dtype=float)
        if v.shape != (self.full_velocity_unknowns,) or p.size != self.pressure_unknowns:
            raise ValueError("evaluation fields have wrong shape")
        if not np.all(np.isfinite(v)) or not np.all(np.isfinite(p)):
            raise ValueError("evaluation fields must be finite")
        p = p.reshape(self.nz, self.nx)
        values = self._boundary_values(boundaries)
        lift = self._lift(values)
        force, body, traction = self._loads(force_u, force_w, values)
        u, w = v[self._iu], v[self._iw]
        exx = np.diff(u[1:-1], axis=1)/self.dx
        ezz = np.diff(w[:, 1:-1], axis=0)/self.dz
        du = np.diff(u, axis=0)/self.dz
        dw = np.diff(w, axis=1)/self.dx
        du[[0, -1]] *= 2.
        dw[:, [0, -1]] *= 2.
        gamma, divergence = du+dw, exx+ezz
        txx, tzz, txz = 2*self.eta_center*exx, 2*self.eta_center*ezz, self.eta_vertex*(du+dw)
        sxx, szz = txx-p, tzz-p
        # Direct stress/face flux scattering, independent of K and D matrices.
        stress_u, stress_w = np.zeros_like(u), np.zeros_like(w)
        stress_u[1:-1, :-1] -= sxx*self.dz
        stress_u[1:-1, 1:] += sxx*self.dz
        stress_w[:-1, 1:-1] -= szz*self.dx
        stress_w[1:, 1:-1] += szz*self.dx
        shear = txz*self._vertex_volume
        az = np.full((self.nz+1, 1), 1/self.dz)
        ax = np.full((1, self.nx+1), 1/self.dx)
        az[[0, -1]] *= 2.; ax[:, [0, -1]] *= 2.
        stress_u[:-1] -= shear*az
        stress_u[1:] += shear*az
        stress_w[:, :-1] -= shear*ax
        stress_w[:, 1:] += shear*ax
        internal = np.r_[stress_u.ravel(), stress_w.ravel()]
        residual = internal-body-traction
        free_residual = np.asarray(self._P.T@residual).ravel()
        reduced_reaction = np.asarray(self._Q.T@residual).ravel()
        reactions = np.zeros_like(v)
        reactions[self._independent[self._fixed_ind]] = reduced_reaction[self._fixed_ind]
        reaction_work = float(np.dot(reactions, v))
        body_work, prescribed_work = float(body@v), float(traction@v)
        dissipation = float(np.sum(2*self.eta_center*(exx**2+ezz**2))*self.volume
                            +np.sum(self.eta_vertex*gamma**2*self._vertex_volume))
        work_residual = dissipation-body_work-prescribed_work-reaction_work
        length = min(self.width, self.height)
        velocity_scale = max(1., float(np.max(np.abs(v))))
        stress_scale = max(self._eta_reference*velocity_scale/length, float(np.max(np.abs(p))),
                           *(float(np.max(np.abs(values[s][c]))) for s in SIDES for c in COMPONENTS
                             if self.pattern[s][c] == "traction"))
        force_scale = max(stress_scale/length, float(np.max(np.abs(force))), 1.)
        momentum = float(np.max(np.abs(free_residual), initial=0.)/(self.volume*force_scale))
        div_error = float(np.max(np.abs(divergence))/(velocity_scale/length))
        gauge_error = (abs(float(np.mean(p))-self.pressure_mean)/max(1., stress_scale)
                       if self.gauge_required else 0.)
        work_scale = max(abs(dissipation), abs(body_work)+abs(prescribed_work)+abs(reaction_work),
                         self._eta_reference*velocity_scale**2*self.width*self.height/length**2)
        bc_error = float(np.max(np.abs(v[self._fixed]-lift[self._fixed]), initial=0.)/velocity_scale)
        reconstructed = np.asarray(self._Q@v[self._independent]).ravel()
        corner_error = float(np.max(np.abs(reconstructed-v))/velocity_scale)
        rigid_error = float(np.max(np.abs(self._Cfull@v), initial=0.)/max(1., np.linalg.norm(v)))
        # Traction reactions use exactly the work/force boundary measures. The
        # zero-measure normal corner samples are extrapolated for reporting.
        boundary_velocities, boundary_tractions = {}, {}
        total_boundary_load = traction+reactions
        for side in SIDES:
            boundary_velocities[side], boundary_tractions[side] = {}, {}
            for component in COMPONENTS:
                ids, weights = self._indices[side][component], self._weights[side][component]
                boundary_velocities[side][component] = v[ids].copy()
                if self.pattern[side][component] == "traction":
                    tr = values[side][component].copy()
                else:
                    tr = np.zeros(len(ids))
                    positive = weights > 0.
                    tr[positive] = total_boundary_load[ids[positive]]/weights[positive]
                    if component == _normal(side):
                        tr[0] = 1.5*tr[1]-.5*tr[2]
                        tr[-1] = 1.5*tr[-2]-.5*tr[-3]
                boundary_tractions[side][component] = tr
        x, z = self.velocity_coordinates()
        net = body+total_boundary_load
        net_force = np.array([np.sum(net[:self._iu.size]), np.sum(net[self._iu.size:])])
        torque = float(np.dot(-(z[:self._iu.size]-self.height/2), net[:self._iu.size])
                       +np.dot(x[self._iu.size:]-self.width/2, net[self._iu.size:]))
        flux = float(np.sum(divergence)*self.volume)
        diagnostics = {"momentum_residual": momentum, "divergence_residual": div_error,
                       "pressure_gauge_residual": gauge_error,
                       "work_residual": work_residual, "normalised_work_residual": abs(work_residual)/work_scale,
                       "boundary_velocity_residual": bc_error, "corner_trace_residual": corner_error,
                       "rigid_constraint_residual": rigid_error, "net_boundary_flux": flux,
                       "dissipation": dissipation, "body_work": body_work,
                       "prescribed_traction_work": prescribed_work, "reaction_work": reaction_work,
                       "total_boundary_work": prescribed_work+reaction_work,
                       "net_force": net_force, "net_torque": torque,
                       "max_free_force_residual": float(np.max(np.abs(free_residual), initial=0.)),
                       "max_divergence": float(np.max(np.abs(divergence))),
                       "momentum_normalisation": self.volume*force_scale,
                       "divergence_normalisation": velocity_scale/length,
                       "pressure_normalisation": max(1., stress_scale),
                       "work_normalisation": work_scale,
                       "gates_passed": bool(momentum <= 1e-9 and div_error <= 1e-10 and gauge_error <= 1e-12
                                            and abs(work_residual)/work_scale <= 1e-9 and bc_error <= 1e-12
                                            and corner_error <= 1e-12 and rigid_error <= 1e-10)}
        _check(cancel)
        return {"velocity_vector": v.copy(), "u": u[1:-1].copy(), "w": w[:, 1:-1].copy(), "p": p.copy(),
                "free_force_residual": free_residual,
                "boundary_velocities": boundary_velocities, "boundary_tractions": boundary_tractions,
                "boundary_reactions": reactions, "exx": exx, "ezz": ezz, "exz": gamma/2,
                "reaction_coordinates": np.column_stack((x, z)),
                "reaction_measures": self._reaction_measures(),
                "tau_xx": txx, "tau_zz": tzz, "tau_xz": txz,
                "sigma_xx": sxx, "sigma_zz": szz, "sigma_xz": txz.copy(), "sigma_yy": -p,
                "diagnostics": diagnostics}

    def _reaction_measures(self):
        # Normal endpoints have no normal-face measure. At a mixed corner,
        # a point reaction fixed by the adjacent velocity side is explicitly
        # present here even if the tangential-side traction table stays natural.
        measures = np.zeros(self.full_velocity_unknowns)
        for side in SIDES:
            for component in COMPONENTS:
                np.maximum.at(measures, self._indices[side][component], self._weights[side][component])
        return measures

    def _retained_size(self):
        total = 0
        for value in vars(self).values():
            if isinstance(value, np.ndarray):
                total += value.nbytes
            elif sparse.issparse(value):
                total += value.data.nbytes+value.indices.nbytes+value.indptr.nbytes
        for factor in (self._factor.L, self._factor.U):
            total += factor.data.nbytes+factor.indices.nbytes+factor.indptr.nbytes
        total += self._factor.perm_r.nbytes+self._factor.perm_c.nbytes
        total += sum(a.nbytes for side in self._values.values() for a in side.values())
        return int(total)

    def close(self):
        if not self._closed:
            self._closed = True
            self._factor = self._preconditioner = None

    def __enter__(self):
        if self._closed:
            raise RuntimeError("MAC plan is closed")
        return self

    def __exit__(self, *exc):
        self.close()


def prepare_mac(nx, nz, width, height, eta, boundaries, **kwargs):
    """Prepare scalar eta, or eta=None with explicit eta_center and eta_vertex.

    Arrays use (nz,nx) cell centres and (nz+1,nx+1) shear vertices, including
    boundary vertices. Their source owns point or integral material sampling;
    this core never invents a phase mixing rule. Values are copied and frozen.
    """
    return MACPlan(nx, nz, width, height, eta, boundaries, **kwargs)
