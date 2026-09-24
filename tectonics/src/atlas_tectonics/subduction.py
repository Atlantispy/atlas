"""Interface-aligned steady subduction reference engine (x right, y down).

P2/P1 Taylor--Hood wedge mechanics; continuous P2 temperature with separate
one-sided velocities in slab, lid and wedge. This is a prescribed local section,
not a freely sinking slab or a whole-mantle calculation. Public SI conversion is
explicit; mesh algebra uses km and slab-speed units for conditioning.
"""
from __future__ import annotations

from contextlib import contextmanager, ExitStack
from dataclasses import dataclass
import hashlib
import json
import math
import threading
import weakref
from time import perf_counter

import numpy as np
from scipy import sparse
from scipy.sparse.linalg import splu
from scipy.special import erf, expit

from ._validation import TectonicsError, scalar
from .constitutive import _cancel
from .resources import WorkBudget, select_budget
from .stokes_execution import _native_lease
from .subduction_mesh import build_mesh, basis, quadrature
from .subduction_linear import solve_stokes
from .subduction_transport import PreparedSubductionTransport

YEAR_S = 31557600.
SPEED_M_S = .05 / YEAR_S
KAPPA_M2_S = 3. / (3300. * 1250.)
ETA0_PA_S = 1e21
WORK_BYTES = 128*1024**2
MAX_NONLINEAR_ITERATIONS = 200
CASES = ('1a', '1b', '1c', '2a', '2b')
COUPLING_TRACES = ('nodal-p2-v1', 'mesh-linear-first-edge-v1')


def diagnostic_points_km():
    """Paper one-based T_ij is at (6*(i-1),6*(j-1)) km, not (6*i,6*j)."""
    return np.array([[60.,60.]]+[[6.*i,6.*i] for i in range(36)]+
                    [[6.*i,6.*j] for i in range(9,21) for j in range(9,i+1)])


def _freeze(a):
    a = np.ascontiguousarray(a)
    return np.frombuffer(a.tobytes(), dtype=a.dtype).reshape(a.shape)


def corner_flow(xy_km):
    """Unit-speed 45-degree Batchelor solution, apex (50,50) km.

    psi=r*f(theta), f=(a+b*theta)sin(theta)+d*theta*cos(theta).
    f(0)=f'(0)=f(alpha)=0, f'(alpha)=1. The undefined apex value is
    explicitly refused: slab/lid one-sided traces have different limits there.
    """
    xy = np.asarray(xy_km, dtype=float)
    if xy.shape[-1:] != (2,) or not np.isfinite(xy).all():
        raise TectonicsError('finite x-right/y-down points required')
    x, y = (xy-50.).T if xy.ndim == 2 else ((xy-50.)[..., 0], (xy-50.)[..., 1])
    if np.any((x < 0) | (y < 0) | (y > x) | ((x == 0) & (y == 0))):
        raise TectonicsError('corner flow requires wedge points away from apex')
    alpha = math.pi/4
    a = alpha*math.sin(alpha)/(alpha*alpha-math.sin(alpha)**2)
    d = -a
    b = -(math.sin(alpha)-alpha*math.cos(alpha))/(alpha*alpha-math.sin(alpha)**2)
    t = np.arctan2(y, x); c, s = np.cos(t), np.sin(t)
    f = (a+b*t)*s+d*t*c
    fp = b*s+(a+b*t)*c+d*c-d*t*s
    return np.stack((c*fp+s*f, s*fp-c*f), axis=-1)


def corner_streamfunction(xy_km):
    xy = np.asarray(xy_km, dtype=float)-50.
    x, y = xy[..., 0], xy[..., 1]
    alpha = math.pi/4
    a = alpha*math.sin(alpha)/(alpha*alpha-math.sin(alpha)**2)
    b = -(math.sin(alpha)-alpha*math.cos(alpha))/(alpha*alpha-math.sin(alpha)**2)
    t = np.arctan2(y, x)
    return (a+b*t)*y-a*t*x


def benchmark_viscosity(case, temperature_k, strain_ii_s):
    """Published separate creep laws with harmonic cap, evaluated in log space."""
    t, e = np.broadcast_arrays(np.asarray(temperature_k, float), np.asarray(strain_ii_s, float))
    if not np.isfinite(t).all() or np.any(t <= 0) or not np.isfinite(e).all() or np.any(e < 0):
        raise TectonicsError('positive absolute temperature and nonnegative finite strain required')
    if case in ('1a', '1b', '1c'): return np.full(t.shape, ETA0_PA_S)
    if case == '2a': logeta = math.log(1.32043e9)+335000./(8.3145*t)
    elif case == '2b':
        with np.errstate(divide='ignore'):
            logeta = math.log(28968.6)+540000./(3.5*8.3145*t)-(2.5/3.5)*np.log(e)
    else: raise TectonicsError('unknown subduction case')
    return 1e26*expit(logeta-math.log(1e26))


def _csr(local, rows, cols, shape):
    m, n = local.shape[-2:]
    return sparse.coo_matrix((local.ravel(),
        (np.broadcast_to(rows[:, :, None], (len(rows), m, n)).ravel(),
         np.broadcast_to(cols[:, None, :], (len(cols), m, n)).ravel())), shape=shape).tocsr()


class _HeatFactor:
    """A symmetric graph permutation changes storage, not the thermal equation."""
    def __init__(self, factor, permutation, statistics):
        self.factor, self.permutation, self.statistics = factor, permutation, statistics

    def solve(self, rhs):
        result = np.empty_like(rhs)
        result[self.permutation] = self.factor.solve(rhs[self.permutation])
        return result


def _factor(matrix, budget, category):
    # Sparse factors are not bounded by matrix nnz. Admit an explicitly bounded
    # envelope before calling SuperLU, then verify its realised retained fill.
    # This accounts work, not process RSS or an allocator-enforced hard ceiling.
    n = matrix.shape[0]
    # Reuse headroom released by phase-local gradients. The parent 128MiB cap
    # still admits/refuses the combined work before allocation; it is unchanged.
    allowance = min(72*1024**2,int(20*n**1.5+48*matrix.nnz+1024**2))
    guard = budget.reserve(allowance, category=category)
    guard.__enter__()
    try:
        from scipy.sparse.csgraph import reverse_cuthill_mckee
        permutation = reverse_cuthill_mckee(matrix, symmetric_mode=True)
        ordered = matrix[permutation][:,permutation].tocsc()
        # SuperLU's documented diagonal preference retains off-diagonal pivots
        # when needed. This is still exact LU, not ILU/drop/compression.
        lu = splu(ordered, permc_spec='MMD_AT_PLUS_A', diag_pivot_thresh=.01,
                  options={'SymmetricMode': True})
        actual = sum(a.nbytes for m in (lu.L, lu.U) for a in (m.data, m.indices, m.indptr))
        realised = 3*actual+sum(a.nbytes for a in (ordered.data,ordered.indices,ordered.indptr))+2*permutation.nbytes+4096
        if realised > allowance:
            raise TectonicsError(f'sparse factor fill exceeds admitted allowance: {realised} > {allowance} bytes; n={n}')
        return _HeatFactor(lu, permutation, dict(ordering='RCM-MMD_AT_PLUS_A',
            diagonal_pivot_threshold=.01, symmetric_mode=True,
            factor_nnz=lu.L.nnz+lu.U.nnz, realised_accounted_bytes=realised,
            admitted_bytes=allowance)), guard
    except BaseException:
        guard.__exit__(None, None, None)
        raise


def _solve_checked(a, rhs, lu):
    value = lu.solve(rhs)
    residual = a@value-rhs
    scale = np.abs(a)@np.abs(value)+np.abs(rhs)
    error = float(np.max(np.abs(residual)/np.maximum(scale, np.finfo(float).tiny)))
    if not np.isfinite(value).all() or error > 1e-10:
        raise TectonicsError('steady linear equation residual failed')
    return value, error


def _slab_first_edge(mesh):
    """The unique P2 slab boundary edge incident on the wedge apex; length in m."""
    xy = mesh.points
    apex = np.flatnonzero(np.all(np.isclose(xy, 50., rtol=0., atol=1e-10), axis=1))
    if len(apex) != 1 or apex[0] >= mesh.vertex_count:
        raise TectonicsError('unique wedge-apex vertex required for coupling trace')
    apex = int(apex[0]); slab = np.isclose(xy[:, 0], xy[:, 1], rtol=0., atol=1e-10)
    found = []
    for k, (i, j) in enumerate(((0, 1), (1, 2), (2, 0))):
        edges = mesh.cells[:, [i, j, k+3]]
        take = ((edges[:, 0] == apex) | (edges[:, 1] == apex)) & slab[edges[:, 0]] & slab[edges[:, 1]]
        for a, b, middle in edges[take]:
            found.append((apex, int(b if a == apex else a), int(middle)))
    if len(found) != 1:
        raise TectonicsError('unique incident slab boundary edge required for coupling trace')
    edge = found[0]; p, q, middle = xy[list(edge)]
    length_m = float(np.linalg.norm(q-p)*1000.)
    if (not math.isfinite(length_m) or length_m <= 0. or q[1] <= 50. or
            not np.allclose(middle, (p+q)/2, rtol=0., atol=1e-10)):
        raise TectonicsError('invalid first slab P2 edge geometry')
    return edge, length_m


def _flow_boundary(mesh, case, coupling_trace='nodal-p2-v1'):
    if coupling_trace not in COUPLING_TRACES:
        raise TectonicsError('explicit supported coupling trace required')
    xy = mesh.points
    n = len(xy)
    slab = np.isclose(xy[:, 0], xy[:, 1], rtol=0, atol=1e-10)
    lid = np.isclose(xy[:, 1], 50., rtol=0, atol=1e-10)
    far = (xy[:, 0] == 660.) | (xy[:, 1] == 600.)
    fixed = slab | lid | (far if case == '1b' else False)
    value = np.zeros((n, 2)); value[slab] = 1/math.sqrt(2)
    if case == '1b':
        value[far] = corner_flow(xy[far])
        # Conservative P2 normal trace on outer edges. Endpoint values retain
        # analytic values; midpoint is the exact mean-flux projection. This
        # avoids incompatible total flux from pointwise interpolation.
        for k, (i, j) in enumerate(((0, 1), (1, 2), (2, 0))):
            ids = mesh.cells[:, [i, j, k+3]]
            p, q = xy[ids[:, 0]], xy[ids[:, 1]]
            selected = ((p[:, 0] == 660.) & (q[:, 0] == 660.)) | ((p[:, 1] == 600.) & (q[:, 1] == 600.))
            for edge in ids[selected]:
                p, q, _ = xy[edge]
                tangent = q-p; length = np.linalg.norm(tangent)
                normal = np.array([tangent[1], -tangent[0]])/length
                integral = float(corner_streamfunction(q)-corner_streamfunction(p))
                target = (6*integral/length - (value[edge[0]]+value[edge[1]])@normal)/4
                value[edge[2]] += (target-value[edge[2]]@normal)*normal
    # The wedge apex is stationary. Its point-only singularity is not removed by
    # a finite physical coupling ramp; first-edge approximation shrinks on refine.
    value[lid] = 0.
    if coupling_trace == 'mesh-linear-first-edge-v1' and case != '1a':
        # Mesh-tied numerical trace, not the UM physical ramp or PGC notch.
        # Endpoints 0,1 and midpoint .5 give speed s; legacy midpoint 1 gives
        # 3*s-2*s*s and a 12.5% overshoot. Every other prescribed node is intact.
        (first, last, middle), _ = _slab_first_edge(mesh)
        value[middle] = (value[first]+value[last])/2
    return np.r_[np.flatnonzero(fixed), np.flatnonzero(fixed)+n], np.r_[value[:, 0], value[:, 1]]


class _Wedge:
    def __init__(self, mesh, budget, *, coupling_trace='nodal-p2-v1'):
        if coupling_trace not in COUPLING_TRACES:
            raise TectonicsError('explicit supported coupling trace required')
        self.mesh, self.budget = mesh, budget
        self.coupling_trace = coupling_trace
        _, self.slab_first_edge_length_m = _slab_first_edge(mesh)
        self.bary, self.weights = quadrature(degree=6)
        self.N = basis(self.bary)
        self.G = None; self.geometry_guard = None
        self.cells = mesh.cells
        self.n, self.np = len(mesh.points), mesh.vertex_count
        self.vcells = np.concatenate((self.cells, self.cells+self.n), axis=1)
        self.last = None; self.guard = None; self.assembly_guard = None

    def close(self):
        self.last = None
        self._release_gradient()
        if self.guard is not None:
            self.guard.__exit__(None, None, None); self.guard = None
        if self.assembly_guard is not None:
            self.assembly_guard.__exit__(None,None,None); self.assembly_guard = None

    def _release_gradient(self):
        self.G = None
        if self.geometry_guard is not None:
            self.geometry_guard.__exit__(None,None,None); self.geometry_guard = None

    def _prepare_gradient(self):
        if self.G is not None: return
        self.geometry_guard = self.budget.reserve(8*len(self.cells)*len(self.bary)*6*2,
            category='subduction-flow-gradient')
        self.geometry_guard.__enter__()
        try:
            _, self.G, _ = basis(self.bary,self.mesh.grad_lambda,budget=self.budget)
        except BaseException:
            self._release_gradient(); raise

    def solve(self, case, eta, cancel=None):
        _cancel(cancel)
        eta = np.broadcast_to(eta, (len(self.cells),len(self.bary)))
        key = hashlib.sha256(eta.tobytes()+(case+'|'+self.coupling_trace).encode()).hexdigest()
        if self.last is not None and self.last[0] == key:
            kfree, gfree, rhs_v, rhs_p, mass, velocity_mass, mean, freev, fullv = self.last[1:]
        else:
            self.close()
            self._prepare_gradient()
            mesh, n, np_ = self.mesh, self.n, self.np
            self.assembly_guard=self.budget.reserve(8000*len(mesh.cells)+512*n+1048576,
                category='subduction-flow-assembly')
            self.assembly_guard.__enter__()
            gx, gy = self.G[..., 0], self.G[..., 1]
            w = mesh.area[:, None]*self.weights[None, :]*eta
            def gram(f, g): return np.einsum('eq,eqi,eqj->eij', w, f, g)
            xx, yy, xy = gram(gx, gx), gram(gy, gy), gram(gx, gy)
            local = np.concatenate((np.concatenate((2*xx+yy, xy.swapaxes(1, 2)), axis=2),
                                    np.concatenate((xy, xx+2*yy), axis=2)), axis=1)
            k = _csr(local, self.vcells, self.vcells, (2*n, 2*n))
            b = -np.einsum('eq,eqik,qj->eikj', mesh.area[:, None]*self.weights,
                          self.G, self.bary).transpose(0, 2, 1, 3).reshape(-1, 12, 3)
            g = _csr(b, self.vcells, self.cells[:, :3], (2*n, np_))
            fixed, fullv = (_flow_boundary(mesh, case) if self.coupling_trace == 'nodal-p2-v1'
                            else _flow_boundary(mesh, case, self.coupling_trace))
            freev = np.setdiff1d(np.arange(2*n), fixed)
            mean = None
            if case == '1b':
                mean = np.bincount(self.cells[:, :3].ravel(),
                    weights=np.repeat(mesh.area/3, 3), minlength=np_)
                mean /= np.sum(mean)
            pm = np.einsum('eq,qi,qj->eij',mesh.area[:,None]*self.weights/eta,self.bary,self.bary)
            mass = _csr(pm,self.cells[:,:3],self.cells[:,:3],(np_,np_))
            # Positive diagonal scaling of the sqrt(eta)-weighted P2 mass.
            # Row-sum lumping is invalid here: P2 vertex shape integrals vanish.
            # Rescaling the positive squared-basis diagonal retains each element's
            # total weighted mass (HRZ-style adaptation, not the paper's Qk rule).
            weighted = mesh.area[:,None]*self.weights*np.sqrt(eta)
            diagonal = np.einsum('eq,qi->ei',weighted,self.N*self.N)
            diagonal *= (weighted.sum(axis=1)/diagonal.sum(axis=1))[:,None]
            lumped = np.bincount(self.cells.ravel(),weights=diagonal.ravel(),minlength=n)
            velocity_mass = np.r_[lumped,lumped][freev]
            kfree, gfree = k[freev][:,freev].tocsr(),g[freev].tocsr()
            rhs_v, rhs_p = -(k@fullv)[freev], -(g.T@fullv)
            self.last = (key,kfree,gfree,rhs_v,rhs_p,mass,velocity_mass,mean,freev,fullv)
            cache_bytes=sum(a.nbytes for mat in (kfree,gfree,mass) for a in (mat.data,mat.indices,mat.indptr))
            cache_bytes+=sum(a.nbytes for a in (rhs_v,rhs_p,velocity_mass,freev,fullv))
            if mean is not None: cache_bytes+=mean.nbytes
            self.guard=self.budget.reserve(cache_bytes+65536,category='subduction-flow-matrices')
            self.guard.__enter__()
            del k,g,xx,yy,xy,local,b,pm,weighted,diagonal,lumped,w,gx,gy
            self.assembly_guard.__exit__(None,None,None); self.assembly_guard=None
        # Gradients are needed for assembly and final strain, not for the sparse
        # solve. Recompute this inexpensive geometric table after LU is released.
        self._release_gradient()
        solution, pressure, diagnostics = solve_stokes(kfree,gfree,rhs_v,rhs_p,
            pressure_mass=mass,velocity_mass_sqrt_eta=velocity_mass,
            pressure_mean_weights=mean,budget=self.budget,cancel=cancel)
        result = fullv.copy(); result[freev] = solution
        if case == '1b' and abs(diagnostics['gauge_multiplier']) > 1e-7:
            raise TectonicsError('prescribed wedge boundary has incompatible total flux')
        velocity = np.stack((result[:self.n], result[self.n:2*self.n]), axis=-1)
        self._prepare_gradient()
        gradient = np.einsum('eni,eqnj->eqij', velocity[self.cells], self.G)
        d = (gradient+gradient.swapaxes(-1, -2))/2
        strain = np.sqrt(.5*np.sum(d*d, axis=(-1, -2)))*SPEED_M_S/1000.
        divergence_rms = float(np.sqrt(np.sum((gradient[..., 0, 0]+gradient[..., 1, 1])**2*self.mesh.area[:, None]*self.weights)/np.sum(self.mesh.area)))
        _cancel(cancel)
        diagnostics['divergence_rms_per_km']=divergence_rms
        diagnostics.update(coupling_trace=self.coupling_trace,
                           slab_first_edge_length_m=self.slab_first_edge_length_m)
        return velocity, pressure, strain, diagnostics


def _element_velocity(mesh, wedge, wedge_element_velocity, bary):
    result = np.zeros((len(mesh.cells), len(bary), 2))
    result[mesh.regions == 0] = 1/math.sqrt(2)
    result[wedge.global_elements] = np.einsum('qn,eni->eqi', basis(bary), wedge_element_velocity)
    return result


class _Heat:
    def __init__(self, mesh, budget):
        self.mesh, self.budget = mesh, budget
        self.bary, self.weights = quadrature(degree=6)
        self.N = basis(self.bary)
        self.G = self.lap = None
        self.geometry_guard = None
        self._pinv = np.linalg.pinv(self.N)
        edges = np.concatenate([mesh.cells[:, [i,j,k+3]] for k,(i,j) in enumerate(((0,1),(1,2),(2,0)))])
        endpoints = np.sort(edges[:,:2], axis=1)
        _, inverse, count = np.unique(endpoints, axis=0, return_inverse=True, return_counts=True)
        take = count[inverse] == 1
        self.edges = edges[take]
        self.edge_elements = np.tile(np.arange(len(mesh.cells)),3)[take]
        self.edge_local = np.repeat(np.arange(3),len(mesh.cells))[take]
        q, w = np.polynomial.legendre.leggauss(6)
        self.edge_q, self.edge_w = (q+1)/2, w/2
        self.last = None; self.guard = None; self.matrix_guard = None; self.assembly_guard = None

    def close(self):
        self.last = None
        if self.guard is not None:
            self.guard.__exit__(None, None, None); self.guard = None
        for name in ('matrix_guard','assembly_guard'):
            guard=getattr(self,name)
            if guard is not None:
                guard.__exit__(None,None,None); setattr(self,name,None)
        self._release_gradient()

    def _release_gradient(self):
        self.G = self.lap = None
        if self.geometry_guard is not None:
            self.geometry_guard.__exit__(None,None,None); self.geometry_guard=None

    def _prepare_gradient(self):
        # Reconstruct this cheap table only for the heat phase. Retaining it while
        # factoring the larger mechanical blocks needlessly occupies ~13MiB on
        # the fine reference mesh. Geometry and polynomial arithmetic are unchanged.
        count=8*len(self.mesh.cells)*(len(self.bary)*6*2+6)
        self.geometry_guard=self.budget.reserve(count,category='subduction-heat-gradient')
        self.geometry_guard.__enter__()
        try:
            _,self.G,self.lap=basis(self.bary,self.mesh.grad_lambda,budget=self.budget)
        except BaseException:
            self.geometry_guard.__exit__(None,None,None); self.geometry_guard=None
            raise

    def solve(self, velocity, *, stabilisation, case, cancel=None):
        mesh = self.mesh; n = len(mesh.points)
        _cancel(cancel)
        key = hashlib.sha256(velocity.tobytes()+(stabilisation+case).encode()).hexdigest()
        if self.last is not None and self.last[0] == key:
            a, rhs, lu, free, full, raw, flux_weights = self.last[1:]
        else:
            self.close()
            self._prepare_gradient()
            self.assembly_guard=self.budget.reserve(4000*len(mesh.cells)+256*n+1048576,
                category='subduction-heat-assembly')
            self.assembly_guard.__enter__()
            # Divide SI equation by U/1000: diffusion coefficient has km units.
            k = KAPPA_M2_S/(SPEED_M_S*1000.)
            w = mesh.area[:, None]*self.weights
            adv = np.einsum('eqd,eqid->eqi', velocity, self.G)
            local = k*np.einsum('eq,eqid,eqjd->eij', w, self.G, self.G)
            # Conservative weak advection: -int grad(test).v*T plus the outer
            # advective flux below. Shared normal traces cancel at interfaces.
            local -= np.einsum('eq,eqi,qj->eij', w, adv, self.N)
            if stabilisation == 'supg':
                speed = np.linalg.norm(velocity, axis=-1)
                directional = np.sum(np.abs(np.einsum('eqd,eid->eqi', velocity, mesh.grad_lambda)), axis=-1)
                h = np.divide(2*speed, directional, out=np.sqrt(2*mesh.area)[:, None]*np.ones_like(speed), where=directional > 0)
                # P2 streamline scale (half linear-element length), consistent
                # residual includes the nonzero quadratic diffusive Laplacian.
                tau = 1/np.sqrt((4*speed/h)**2+(16*k/h**2)**2)
                nodal = np.einsum('nq,eqd->end', self._pinv, velocity)
                div = np.einsum('end,eqnd->eq', nodal, self.G)
                strong = adv + div[:,:,None]*self.N[None,:,:] - k*self.lap[:,None,:]
                local += np.einsum('eq,eqi,eqj->eij', w*tau, adv, strong)
            elif stabilisation != 'galerkin': raise TectonicsError('explicit galerkin or supg required')
            nodal = np.einsum('nq,eqd->end', self._pinv, velocity)
            flux_local = np.zeros_like(local)
            for edge_kind, (i,j) in enumerate(((0,1),(1,2),(2,0))):
                selected = self.edge_local == edge_kind
                elements = self.edge_elements[selected]
                if not len(elements): continue
                bary = np.zeros((len(self.edge_q),3))
                bary[:,i] = 1-self.edge_q; bary[:,j] = self.edge_q
                en = basis(bary)
                xyq = np.einsum('qn,end->eqd',en,mesh.points[mesh.cells[elements]])
                vq = np.einsum('qn,end->eqd',en,nodal[elements])
                tangent = mesh.points[mesh.cells[elements,j]]-mesh.points[mesh.cells[elements,i]]
                # Positive CCW triangles in x/y; right normal is outward.
                normal_ds = np.stack((tangent[:,1],-tangent[:,0]),axis=1)
                flux = np.einsum('eqd,ed->eq',vq,normal_ds)
                flux_local[elements] += np.einsum('q,eq,qi,qj->eij',self.edge_w,flux,en,en)
            local += flux_local
            flux_weights = np.zeros(n)
            np.add.at(flux_weights,mesh.cells.ravel(),flux_local.sum(axis=1).ravel())
            raw = _csr(local, mesh.cells, mesh.cells, (n, n))
            xy = mesh.points; x, y = xy.T
            fixed = (y == 0) | (x == 0) | ((x == 660.) & (y <= 50.))
            full = np.zeros(n)
            left = x == 0
            full[left] = 1300*erf(y[left]*1000/(2*math.sqrt(KAPPA_M2_S*50e6*YEAR_S)))
            lidright = (x == 660.) & (y <= 50.)
            full[lidright] = 1300*y[lidright]/50
            # One-sided velocity at boundary nodes is reconstructed within each
            # element from quadrature; conservative P2 fields are exactly recovered.
            right_nodes = np.unique(mesh.cells[(mesh.regions == 2)].ravel())
            # Sum and count one-sided wedge traces; never blend with slab/lid.
            vel_sum = np.zeros((n, 2)); count = np.zeros(n)
            ids = np.flatnonzero(mesh.regions == 2)
            np.add.at(vel_sum, mesh.cells[ids].ravel(), nodal[ids].reshape(-1,2))
            np.add.at(count, mesh.cells[ids].ravel(), 1)
            vel_sum[right_nodes] /= count[right_nodes, None]
            incoming = ((x == 660.) & (y > 50.) & (vel_sum[:,0] < 0)) | ((y == 600.) & (x > 600.) & (vel_sum[:,1] < 0))
            fixed |= incoming; full[incoming] = 1300.
            free = np.flatnonzero(~fixed)
            a = raw[free][:, free].tocsr(); rhs = -(raw@full)[free]
            cache_bytes=sum(v.nbytes for mat in (raw,a) for v in (mat.data,mat.indices,mat.indptr))
            cache_bytes+=sum(v.nbytes for v in (rhs,free,full,flux_weights))
            self.matrix_guard=self.budget.reserve(cache_bytes+65536,category='subduction-heat-matrices')
            self.matrix_guard.__enter__()
            del local,flux_local,adv,nodal,vel_sum,count,w
            if stabilisation=='supg': del strong,speed,directional,h,tau,div
            self.assembly_guard.__exit__(None,None,None); self.assembly_guard=None
            self._release_gradient()
            lu, self.guard = _factor(a, self.budget, 'subduction-heat-factor')
            self.last = (key, a, rhs, lu, free, full, raw, flux_weights)
        solution, error = _solve_checked(a, rhs, lu)
        constant_error=float(np.max(np.abs(raw@np.ones(n))))/max(float(np.max(np.asarray(abs(raw).sum(axis=1)))),np.finfo(float).tiny)
        if constant_error>1e-10:
            raise TectonicsError('conservative thermal operator does not preserve constant temperature')
        t = full.copy(); t[free] = solution
        if np.min(t+273.) <= 0:
            raise TectonicsError('thermal discretisation produced non-positive absolute temperature')
        # Reaction at each prescribed-temperature node is a declared heat input;
        # open natural boundaries have zero diffusive normal flux. The summed
        # discrete steady balance is independent of the linear residual norm.
        reaction = raw@t
        balance = float(np.sum(reaction[free]))
        scale = float(np.sum(np.abs(reaction)))
        if abs(balance) > 1e-9*max(1., scale): raise TectonicsError('thermal reaction balance failed')
        diffusive_input = float(np.sum(reaction)-balance)
        advective_export = float(flux_weights@t)
        heat_error = diffusive_input-advective_export
        if abs(heat_error) > 1e-9*max(1.,scale,abs(advective_export)):
            raise TectonicsError('independent boundary heat flux does not close')
        scale_w_m = 3300*1250*SPEED_M_S*1000
        _cancel(cancel)
        return t+273., dict(linear_residual=error, free_heat_balance=balance,
                           factor=lu.statistics,
                           constant_temperature_residual=constant_error,
                           reaction_scale=scale, boundary_heat_residual_w_m=heat_error*scale_w_m,
                           diffusive_input_w_m=diffusive_input*scale_w_m,
                           advective_export_relative_273k_w_m=advective_export*scale_w_m,
                           minimum_k=float(t.min()+273), maximum_k=float(t.max()+273))


@dataclass(frozen=True)
class SubductionResult:
    case: str
    identity: str
    points_xz_m: np.ndarray
    cells: np.ndarray
    regions: np.ndarray
    wedge_global_nodes: np.ndarray
    wedge_global_elements: np.ndarray
    temperature_k: np.ndarray
    wedge_velocity_m_s: np.ndarray
    transport_wedge_velocity_m_s: np.ndarray
    wedge_pressure_pa: np.ndarray
    diagnostics_c: tuple
    iterations: int
    _statistics: bytes

    @property
    def statistics(self): return json.loads(self._statistics)


class _LogViscosityAnderson:
    """Depth-three type-II AA with individually leased retained history.

    SCS algorithm/acceleration.html: regularised residual-difference least
    squares, beta=.5, and next-map residual safeguard. A rejected candidate
    restores the saved Picard step, not a changed material law or tolerance.
    """
    def __init__(self, budget=None):
        self.budget = budget if budget is not None else WorkBudget(WORK_BYTES, parent=select_budget(None))
        self.history = []; self.pending = None
        self.attempted = self.accepted = self.rejected = self.discarded = 0

    def clear_history(self):
        for _, _, lease in self.history:
            lease.__exit__(None, None, None)
        self.history.clear()

    def close(self):
        self.clear_history()
        if self.pending is not None:
            self.pending[2].__exit__(None, None, None); self.pending = None

    def accept(self, residual):
        if self.pending is None:
            return None
        fallback, previous_norm, lease = self.pending; self.pending = None
        lease.__exit__(None, None, None)
        if float(np.max(np.abs(residual))) > previous_norm:
            self.clear_history(); self.rejected += 1
            return fallback
        self.accepted += 1
        return None

    def propose(self, x, residual):
        x, residual = x.ravel(), residual.ravel()
        base = x+.5*residual
        if len(self.history) == 4:
            self.history.pop(0)[2].__exit__(None, None, None)
        lease = self.budget.reserve(2*x.nbytes, category='subduction-anderson-history'); lease.__enter__()
        try:
            self.history.append((x.copy(), residual.copy(), lease))
        except BaseException:
            lease.__exit__(None, None, None); raise
        if len(self.history) < 2:
            return base
        differences = [b[1]-a[1] for a, b in zip(self.history[:-1], self.history[1:])]
        gram = np.array([[np.dot(a, b) for b in differences] for a in differences])
        scale = float(np.trace(gram))
        if scale == 0.:
            return base
        try:
            coefficients = np.linalg.solve(gram+1e-12*scale*np.eye(len(differences)),
                np.array([np.dot(a, residual) for a in differences]))
        except np.linalg.LinAlgError:
            coefficients = np.array([np.inf])
        candidate = base.copy()
        if np.isfinite(coefficients).all() and np.linalg.norm(coefficients) <= 100.:
            for weight, dr, a, b in zip(coefficients, differences, self.history[:-1], self.history[1:]):
                candidate -= weight*(b[0]-a[0]+.5*dr)
            if (np.isfinite(candidate).all() and np.max(candidate) <= math.log(1e26/ETA0_PA_S)
                    and np.min(candidate) >= math.log(np.finfo(float).tiny)):
                lease = self.budget.reserve(base.nbytes, category='subduction-anderson-pending'); lease.__enter__()
                self.pending = (base, float(np.max(np.abs(residual))), lease)
                self.attempted += 1
                return candidate
        newest = self.history.pop(); self.clear_history(); self.history = [newest]
        self.discarded += 1
        return base


class PreparedSubduction:
    """Bounded steady benchmark-family section with explicit outflow adapter.

    ``natural-zero-diffusive-flux`` is the later xFieldstone weak-form adapter;
    it is NOT silently relabelled the ambiguous original2008 'zero curvature'.
    ``source_id`` must identify the selected adapter/scenario. Numerical results
    do not themselves certify original published benchmark acceptance.
    ``mesh-linear-first-edge-v1`` is an optional shrinking numerical trace,
    not the published UM finite physical ramp or the PGC removed-tip geometry.
    ``phase-local`` transport trades repeated operator construction for more
    memory headroom during mechanics/heat; ``retained`` remains the time-first
    default. Neither policy changes the mesh, physical laws or factor ceilings.
    """
    def __init__(self, spacing_km, *, source_id, outflow_operator,
                 stabilisation='supg', mesh_grading='interface-r3', coupling_trace='nodal-p2-v1',
                 refinement_points_km=None, transport_lifetime='retained',
                 context=None, budget=None, cancel=None):
        if outflow_operator != 'natural-zero-diffusive-flux':
            raise TectonicsError('only explicitly named natural diffusive outflow adapter implemented')
        if not isinstance(source_id, str) or not source_id.strip() or len(source_id) > 256:
            raise TectonicsError('bounded nonempty source ID required')
        if stabilisation not in ('supg', 'galerkin'): raise TectonicsError('explicit thermal method required')
        if coupling_trace not in COUPLING_TRACES: raise TectonicsError('explicit supported coupling trace required')
        if transport_lifetime not in ('retained','phase-local'):
            raise TectonicsError('explicit supported transport lifetime required')
        from .reuse import ExecutionContext
        self.budget = WorkBudget(WORK_BYTES, parent=select_budget(budget))
        self.context = context; self.own_context = context is None
        self._guard = self.budget.reserve(2*1024**2, category='subduction-source-context')
        self._guard.__enter__()
        self.mesh = self.wedge = self.flow = self.heat = self.transport = None
        self._work_guard = None; self._latest = None; self._closed = False
        self._owner = threading.get_ident(); self._active = False
        self._transport_lifetime = transport_lifetime
        self._transport_builds = 0
        self._transport_payload_bytes = self._transport_allowance_bytes = 0
        try:
            if self.context is None: self.context = ExecutionContext('scipy')
            if self.context.backend != 'scipy': raise TectonicsError('subduction requires scipy context')
            self.execution_id = self.context.identity
            with _native_lease():
                self.mesh = build_mesh(spacing_km, grading=mesh_grading,
                    refinement_points_km=refinement_points_km, budget=self.budget, cancel=cancel)
                self.wedge = self.mesh.wedge()
                # Retained basis/gradients and driving fields. Assembly scratch,
                # retained sparse matrices, factors and detached results have
                # separate leases: assembly must not remain charged/live at LU.
                e, w = len(self.mesh.cells), len(self.wedge.cells)
                work = 128*e+128*w+128*len(self.mesh.points)+2*1024**2
                self._work_guard = self.budget.reserve(work, category='subduction-fe-work')
                self._work_guard.__enter__()
                self.flow = _Wedge(self.wedge, self.budget, coupling_trace=coupling_trace)
                self.heat = _Heat(self.mesh, self.budget)
                if self._transport_lifetime == 'retained': self._prepare_transport(cancel)
            self.stabilisation, self.source_id, self.outflow = stabilisation, source_id, outflow_operator
            self.coupling_trace = coupling_trace
            self.slab_first_edge_length_m = self.flow.slab_first_edge_length_m
            record = dict(schema='atlas.subduction.v1', source_id=source_id, spacing_km=spacing_km,
                mesh_grading=self.mesh.grading_id, tip_target_m=self.mesh.tip_target_m,
                mesh_geometry_id=self.mesh.geometry_id,
                coupling_trace=coupling_trace, slab_first_edge_length_m=self.slab_first_edge_length_m,
                outflow_operator=outflow_operator, stabilisation=stabilisation, execution_id=self.execution_id,
                coordinates='x-right-y-down-km; outputs SI; positive-y velocity is downward')
            self.plan_id = hashlib.sha256(json.dumps(record, sort_keys=True, allow_nan=False).encode()).hexdigest()
            self.context.verify()
        except BaseException:
            self.close(); raise

    @contextmanager
    def _operation(self, cancel):
        if self._closed or self._active or threading.get_ident() != self._owner:
            raise TectonicsError('subduction plan closed, active or wrong driving thread')
        self.context.verify(); _cancel(cancel); self._active = True
        try:
            with _native_lease(): yield
            _cancel(cancel); self.context.verify()
        finally: self._active = False

    @property
    def transport_lifetime(self): return self._transport_lifetime

    def _prepare_transport(self, cancel):
        if self.transport is None:
            self.transport = PreparedSubductionTransport(self.wedge,budget=self.budget,cancel=cancel)
            self._transport_builds += 1
            self._transport_payload_bytes = self.transport.retained_payload_bytes
            self._transport_allowance_bytes = self.transport.retained_allowance_bytes

    def _project_velocity(self, velocity, case, cancel):
        # solve() already owns the native-thread lease; no additional outer
        # controller is introduced here. The transport kernel keeps its usual
        # native lease and returns detached bytes that survive operator close.
        self._prepare_transport(cancel)
        try:
            return self.transport.evaluate(velocity[self.wedge.cells],
                boundary_streamfunction=corner_streamfunction if case=='1a' else None,cancel=cancel)
        finally:
            if self._transport_lifetime == 'phase-local':
                self.transport.close()
                self.transport = None
            else:
                self.transport.release_factor()

    def solve(self, case, *, cancel=None):
        if case not in CASES: raise TectonicsError('unknown published subduction case')
        with self._operation(cancel), ExitStack() as nonlinear_work:
            if self._latest is not None and self._latest.case == case: return self._latest
            # A different request cannot reuse the one-entry result cache. Drop
            # our ownership now, not after the next large solve; any caller-held
            # result correctly keeps its own storage lease until released.
            self._latest = None
            start = perf_counter(); mesh, wedge = self.mesh, self.wedge
            b = self.heat.bary
            temperature = np.full(len(mesh.points), 1573.)
            velocity = np.zeros((len(wedge.points), 2)); pressure = np.zeros(wedge.vertex_count)
            strain = np.zeros((len(wedge.cells), len(b)))
            eta = np.ones_like(strain); nonlinear = case in ('2a', '2b')
            mixing = None
            if nonlinear:
                mixing = _LogViscosityAnderson(self.budget)
                nonlinear_work.callback(mixing.close)
            converged = False
            for iteration in range(1, MAX_NONLINEAR_ITERATIONS+1 if nonlinear else 2):
                _cancel(cancel)
                if case != '1a':
                    self.heat.close()
                    velocity, pressure, strain, mechanics = self.flow.solve(case, eta, cancel)
                    # Do not retain two large factors simultaneously. Same-case
                    # repeats reuse the complete result; other cases/iterations
                    # change boundaries or viscosity and cannot use this factor.
                    self.flow.close()
                else:
                    mechanics = dict(analytic_velocity=True)
                    not_apex=np.any(wedge.points!=50.,axis=1)
                    velocity[not_apex]=corner_flow(wedge.points[not_apex])
                projected=self._project_velocity(velocity,case,cancel)
                vq = _element_velocity(mesh, wedge, projected.element_node_velocity, b)
                new_t, thermal = self.heat.solve(vq, stabilisation=self.stabilisation, case=case, cancel=cancel)
                if not nonlinear:
                    temperature = new_t; converged = True; break
                with self.budget.reserve(12*eta.nbytes+4096, category='subduction-anderson-update'):
                    tq = np.einsum('qn,en->eq', self.heat.N, new_t[mesh.cells[wedge.global_elements]])
                    new_eta = benchmark_viscosity(case, tq, strain)/ETA0_PA_S
                    t_error = float(np.max(np.abs(new_t-temperature)))
                    log_eta = np.log(eta)
                    residual = np.log(new_eta/eta)
                    eta_error = float(np.max(np.abs(residual)))
                    fallback = mixing.accept(residual)
                    if fallback is not None:
                        eta = np.exp(fallback).reshape(eta.shape)
                        del tq, new_eta, log_eta, residual, fallback
                        continue
                    temperature = new_t
                    if t_error <= 1e-4 and eta_error <= 1e-7:
                        converged = True
                    else:
                        eta = np.exp(mixing.propose(log_eta, residual)).reshape(eta.shape)
                    del tq, new_eta, log_eta, residual, fallback
                if converged:
                    break
            if not converged:
                raise TectonicsError('steady nonlinear subduction did not converge within bound: '+
                    str(dict(iterations=iteration, temperature_delta=t_error, log_viscosity_residual=eta_error)))
            if mixing is not None:
                mixing.close()
            samples = diagnostic_points_km()
            values = mesh.interpolate(temperature, samples)-273.
            diagnostics = (float(values[0]), float(np.sqrt(np.mean(values[1:37]**2))), float(np.sqrt(np.mean(values[37:]**2))))
            # Public Atlas coordinates are x-right/z-up. Preserve the sign
            # conversion in both geometry and velocity; reverse triangle order
            # (including its edge-midpoint order) to retain positive orientation.
            points_xz = mesh.points*np.array([1000.,-1000.])
            public_velocity = velocity*np.array([SPEED_M_S,-SPEED_M_S])
            fields = (_freeze(points_xz), _freeze(mesh.cells[:,[0,2,1,5,4,3]]),
                _freeze(mesh.regions), _freeze(wedge.global_nodes), _freeze(wedge.global_elements),
                _freeze(temperature), _freeze(public_velocity),
                _freeze(projected.element_node_velocity[:,[0,2,1,5,4,3]]*np.array([SPEED_M_S,-SPEED_M_S])),
                _freeze(pressure*ETA0_PA_S*SPEED_M_S/1000.))
            h = hashlib.sha256((self.plan_id+case).encode())
            for a in fields: h.update(a.tobytes())
            statistics = dict(elapsed_s=perf_counter()-start, mechanics=mechanics, thermal=thermal,transport=projected.diagnostics(),
                transport_lifetime=self._transport_lifetime,
                transport_operator_builds=self._transport_builds,
                transport_operator_payload_bytes=self._transport_payload_bytes,
                transport_operator_allowance_bytes=self._transport_allowance_bytes,
                mesh_grading=mesh.grading_id, base_spacing_km=mesh.spacing_km,
                mesh_geometry_id=mesh.geometry_id,
                tip_target_m=mesh.tip_target_m,
                coupling_trace=self.coupling_trace,
                coupling_trace_applied=case != '1a' and self.coupling_trace == 'mesh-linear-first-edge-v1',
                slab_first_edge_length_m=self.slab_first_edge_length_m,
                accounted_peak_bytes=self.budget.peak_reserved_bytes, original2008_source_exact=False,
                outflow_operator=self.outflow, stabilisation=self.stabilisation,
                public_coordinates='x-right-z-up, metres; vz is negative for downward motion',
                pressure_support='first len(wedge_pressure_pa) wedge_global_nodes')
            if nonlinear:
                statistics['nonlinear'] = dict(method='safeguarded depth-3 log-viscosity Anderson; beta=.5',
                    evaluations=iteration, temperature_delta=t_error, log_viscosity_residual=eta_error,
                    accelerated_attempts=mixing.attempted, accepted=mixing.accepted,
                    rejected=mixing.rejected, discarded=mixing.discarded)
            lease = self.budget.reserve(sum(a.nbytes for a in fields)+4096,category='subduction-retained-result')
            lease.__enter__()
            try:
                result = SubductionResult(case, h.hexdigest(), *fields, diagnostics, iteration,
                    json.dumps(statistics,sort_keys=True,allow_nan=False).encode())
                weakref.finalize(result,lease.__exit__,None,None,None)
            except BaseException:
                lease.__exit__(None,None,None); raise
            self._latest = result
            return result

    def close(self):
        if self._closed: return
        if self._active or threading.get_ident() != self._owner:
            raise TectonicsError('close subduction plan on idle driving thread')
        try:
            for obj in (self.flow, self.heat, self.transport, self.wedge, self.mesh):
                if obj is not None: obj.close()
            self._latest = None
            if self._work_guard is not None: self._work_guard.__exit__(None,None,None)
            if self.own_context and self.context is not None: self.context.close()
        finally:
            self._guard.__exit__(None,None,None); self._closed = True

    def __enter__(self): return self
    def __exit__(self, *_): self.close()


def solve_refined_diffusion_creep(spacing_km, *, source_id, outflow_operator,
                                 transport_lifetime='retained', context=None, budget=None, cancel=None):
    """One fixed whole-wedge indicator pass, then solve on its refined mesh.

    Returns ``(SubductionResult, metadata)``. This explicit case2a/corner-r5 route
    does not silently change PreparedSubduction defaults or any physical law.
    The pilot is closed before preparing the final solve, sharing one128MiB
    envelope. Callers may retain the immutable final result for verified reuse;
    this function has no unbounded global result cache. Zero indicators reuse
    the pilot directly. The result owns its field-storage lease after return.
    """
    from .subduction_refinement import select_refinement_points
    owner = WorkBudget(WORK_BYTES, parent=select_budget(budget))
    start = perf_counter()
    kwargs = dict(source_id=source_id, outflow_operator=outflow_operator,
                  mesh_grading='corner-r5', transport_lifetime=transport_lifetime,
                  context=context, budget=owner, cancel=cancel)
    # Bounded4096x2 detached coordinates and summary survive pilot close.
    with owner.reserve(256*1024, category='subduction-refinement-handoff'):
        with PreparedSubduction(spacing_km, **kwargs) as pilot:
            baseline = pilot.solve('2a', cancel=cancel)
            baseline_identity = baseline.identity
            baseline_diagnostics = baseline.diagnostics_c
            baseline_statistics = baseline.statistics
            pilot.heat.close(); pilot.flow.close()
            if pilot.transport is not None: pilot.transport.release_factor()
            with pilot._operation(cancel):
                points, selection = select_refinement_points(pilot.mesh, pilot.wedge,
                    baseline.temperature_k,
                    baseline.wedge_velocity_m_s/np.array([SPEED_M_S,-SPEED_M_S]),
                    budget=owner, cancel=cancel)
            if not len(points):
                return baseline, dict(selection=selection, pilot_identity=baseline_identity,
                    pilot_reused=True, elapsed_s=perf_counter()-start,
                    accounted_peak_bytes=owner.peak_reserved_bytes)
            del baseline
        # No pilot fields, sparse matrices or locators remain live at final LU.
        with PreparedSubduction(spacing_km, refinement_points_km=points, **kwargs) as refined:
            result = refined.solve('2a', cancel=cancel)
        metadata = dict(selection=selection, pilot_identity=baseline_identity,
            pilot_diagnostics_c=baseline_diagnostics, pilot_statistics=baseline_statistics,
            pilot_reused=False, elapsed_s=perf_counter()-start,
            accounted_peak_bytes=owner.peak_reserved_bytes)
        return result, metadata
