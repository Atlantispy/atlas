"""R4.1: constant-viscosity, incompressible MAC operator in a closed 2D box.

SPDX-License-Identifier: AGPL-3.0-only

x points right, z points UP from the bottom. This is not R2's inward depth.
Physical equations: -grad(p) + eta*laplacian(v) + f = 0, div(v) = 0.
Constant eta and incompressibility are essential to the vector-Laplacian form.
All walls are impermeable and free slip: normal velocity = 0 and normal
 derivative of tangential velocity = 0. No other boundary type is inferred.

Pressure is cell-centred; horizontal/vertical velocities occupy their respective
faces. Zero normal boundary unknowns are eliminated. Centred differences give
G = -D.T, including wall-adjacent cells. Pressure's constant nullspace is treated
by a zero-domain-mean Lagrange multiplier, not by omitting a continuity equation.
The augmented symmetric matrix is [A,G,0;G.T,0,c;0,c.T,0], c=1/sqrt(Np).

The ordinary route applies this matrix without assembly, using native arrays.
The free-slip, constant-coefficient velocity blocks are separable. Orthonormal
DST-I (normal nodes) and DCT-II (tangential centres) apply their exact discrete
inverse as a block MINRES preconditioner. It is NOT a general variable-viscosity
preconditioner or a 3D/spherical solver. The explicit small sparse direct route
assembles the stencils independently; it is a verification route, not a dense
inverse. Equations and new acceptance limits are registered in stokes_r4_1.json.

Only geometry/operators live here. Prepared execution, source identity and
self-contained snapshots reuse the existing infrastructure in stokes_execution.
Thermal/composition time integration and nonlinear laws remain unfinished R4.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np
try:
    from scipy.fft import dct, dst, idct, idst
    from scipy.sparse import bmat, block_diag, coo_matrix, diags, eye, kron
except ImportError:
    # Keep the previously supported explicit NumPy-only foundation route importable.
    dct = dst = idct = idst = None
    bmat = block_diag = coo_matrix = diags = eye = kron = None

from ._validation import TectonicsError, scalar, text, frozen, read_array, input_shape
from .resources import select_budget
from .constitutive import DiffusiveScales, RheologyProfile

_METHOD = 'atlas.stokes-mac-free-slip-2d.v1'
_BOUNDARY = 'all-walls-impermeable-free-slip'
_GAUGE = 'zero-domain-mean-dynamic-pressure'


@dataclass(frozen=True, slots=True)
class StokesBox2D:
    """Uniform rectangular support; metres, bottom at z=0, no hidden plate IDs.

    Shapes: u=(nz,nx+1), w=(nz+1,nx), p=(nz,nx). Only u[:,1:-1] and
    w[1:-1,:] are solved; boundary normal velocities are exactly zero.
    Resolution is a requested input, never reduced to meet a memory budget.
    """
    nx: int
    nz: int
    width_m: float
    height_m: float
    frame_id: str

    def __post_init__(self):
        for key in ('nx', 'nz'):
            n = getattr(self, key)
            if type(n) is not int or not 2 <= n < 2**31:
                raise TectonicsError('Stokes '+key+' must be an integer >=2 within sparse-index range')
        for key in ('width_m', 'height_m'):
            object.__setattr__(self, key, scalar(getattr(self, key), key, positive=True))
        text(self.frame_id, 'Stokes frame')
        if len(self.frame_id) > 512:
            raise TectonicsError('Stokes frame identifier exceeds metadata envelope')
        if self.unknowns >= 2**31:
            raise TectonicsError('Stokes problem exceeds supported sparse-index range')
        if self.width_m/self.nx == 0 or self.height_m/self.nz == 0:
            raise TectonicsError('Stokes spacing underflows')

    @property
    def unknowns(self):
        return self.nz*(self.nx-1) + self.nx*(self.nz-1) + self.nx*self.nz + 1

    def axes(self, location='pressure', *, budget=None):
        """Detached 1D coordinate axes; callers explicitly choose any mesh expansion."""
        if location not in ('pressure', 'u', 'w', 'force_x', 'force_z'):
            raise TectonicsError('unknown Stokes field location')
        with select_budget(budget).reserve(64*(self.nx+self.nz+2), category='stokes-coordinates'):
            x = np.arange(self.nx, dtype=float)+.5
            z = np.arange(self.nz, dtype=float)+.5
            if location == 'u':
                x = np.arange(self.nx+1, dtype=float)
            elif location == 'w':
                z = np.arange(self.nz+1, dtype=float)
            elif location == 'force_x':
                x = np.arange(1, self.nx, dtype=float)
            elif location == 'force_z':
                z = np.arange(1, self.nz, dtype=float)
            return frozen(x*(self.width_m/self.nx)), frozen(z*(self.height_m/self.nz))


@dataclass(frozen=True, slots=True)
class StokesSolvePolicy:
    """Finite admission/convergence policy, separate from the physical equations.

    Both residual gates are evaluated in the force-normalised nondimensional
    system, separately from MINRES's internal stopping criterion. No fallback,
    tolerance relaxation or mesh change follows a failure. The direct memory
    allowance deliberately bounds dense fill, not a hoped-for sparsity pattern.
    """
    method: str = 'minres'
    max_unknowns: int = 400_000
    direct_max_unknowns: int = 4096
    max_iterations: int = 128
    krylov_rtol: float = 1e-12
    momentum_tolerance: float = 1e-9
    divergence_tolerance: float = 1e-10
    gauge_tolerance: float = 1e-12
    work_balance_tolerance: float = 1e-9

    def __post_init__(self):
        if self.method not in ('minres', 'direct'):
            raise TectonicsError('Stokes method must be minres or explicit direct reference')
        for key in ('max_unknowns', 'direct_max_unknowns', 'max_iterations'):
            if type(getattr(self, key)) is not int or getattr(self, key) < 1:
                raise TectonicsError(key+' must be a positive integer')
        for key in ('krylov_rtol', 'momentum_tolerance', 'divergence_tolerance',
                    'gauge_tolerance', 'work_balance_tolerance'):
            v = scalar(getattr(self, key), key, positive=True)
            if not np.finfo(float).eps <= v <= 1e-3:
                raise TectonicsError(key+' outside explicit binary64 tolerance envelope')
            object.__setattr__(self, key, v)


def _scaling(box, scales, profile):
    if type(box) is not StokesBox2D or type(scales) is not DiffusiveScales or type(profile) is not RheologyProfile:
        raise TectonicsError('typed Stokes support, diffusive scales and rheology are required')
    if profile.family != 'constant' or profile.viscosity_bounds is not None:
        raise TectonicsError('R4.1 supports an unclipped constant R3 law only; variable/yielding R4 is unfinished')
    eta = dict(profile.parameters)['eta']
    pressure = scalar(eta*scales.stress_pa, 'Stokes pressure scale', positive=True)
    force = scalar(pressure/scales.length_m, 'Stokes force-density scale', positive=True)
    viscosity = scalar(eta*scales.viscosity_pa_s, 'Stokes physical viscosity', positive=True)
    hx = scalar((box.width_m/scales.length_m)/box.nx, 'scaled horizontal spacing', positive=True)
    hz = scalar((box.height_m/scales.length_m)/box.nz, 'scaled vertical spacing', positive=True)
    try:
        coeff = (1/hx)**2 + (1/hz)**2
    except OverflowError as exc:
        raise TectonicsError('Stokes coefficients exceed binary64 range') from exc
    if not math.isfinite(coeff) or coeff == 0:
        raise TectonicsError('Stokes coefficients exceed binary64 range')
    return dict(hx=hx, hz=hz, pressure_pa=pressure, force_n_m3=force,
                velocity_m_s=scales.velocity_m_s, viscosity_pa_s=viscosity,
                length_m=scales.length_m)


class _MACOperator:
    """Private, unchecked native stencil kernels; owner admits all scratch first."""
    def __init__(self, box, hx, hz):
        self.nx, self.nz = box.nx, box.nz
        self.hx, self.hz = hx, hz
        self.nu = self.nz*(self.nx-1)
        self.nw = self.nx*(self.nz-1)
        self.nv = self.nu+self.nw
        self.np = self.nx*self.nz
        self.n = self.nv+self.np+1
        self.c = 1/math.sqrt(self.np)

    def split(self, vector):
        return (vector[:self.nu].reshape(self.nz,self.nx-1),
                vector[self.nu:self.nv].reshape(self.nz-1,self.nx),
                vector[self.nv:-1].reshape(self.nz,self.nx), vector[-1])

    def velocity(self, u, w):
        # Normal Dirichlet stencil includes the eliminated zero wall values.
        # Tangential Neumann faces have no wall flux: a first/last diagonal is
        # reduced by one, not doubled as for a no-slip ghost-cell condition.
        ih, iz = (1/self.hx)**2, (1/self.hz)**2
        au = (2*ih)*u
        au[:,1:] -= ih*u[:,:-1]
        au[:,:-1] -= ih*u[:,1:]
        flux = iz*np.diff(u,axis=0)
        au[1:] += flux
        au[:-1] -= flux
        aw = (2*iz)*w
        aw[1:] -= iz*w[:-1]
        aw[:-1] -= iz*w[1:]
        flux = ih*np.diff(w,axis=1)
        aw[:,1:] += flux
        aw[:,:-1] -= flux
        return au,aw

    def divergence(self, u, w):
        d = np.zeros((self.nz,self.nx))
        # u_{i+1/2}-u_{i-1/2}, w_{j+1/2}-w_{j-1/2}; no boundary flux exists.
        d[:,:-1] += u/self.hx
        d[:,1:] -= u/self.hx
        d[:-1] += w/self.hz
        d[1:] -= w/self.hz
        return d

    def matvec(self, vector):
        u,w,p,gauge = self.split(vector)
        au,aw = self.velocity(u,w)
        au += np.diff(p,axis=1)/self.hx
        aw += np.diff(p,axis=0)/self.hz
        continuity = -self.divergence(u,w)+self.c*gauge
        return np.concatenate((au.ravel(),aw.ravel(),continuity.ravel(),[self.c*np.sum(p)]))

    def sparse_reference(self):
        """Independent Kronecker/face-incidence assembly, never stencil-probing I."""
        if diags is None:
            raise TectonicsError('SciPy sparse reference unavailable')
        def second(n, spacing, normal):
            diag = np.full(n,2.)
            if not normal:
                diag[0] -= 1; diag[-1] -= 1
            return diags((-np.ones(n-1),diag,-np.ones(n-1)),(-1,0,1),shape=(n,n),format='csr')*((1/spacing)**2)
        au = kron(eye(self.nz),second(self.nx-1,self.hx,True)) + kron(second(self.nz,self.hz,False),eye(self.nx-1))
        aw = kron(eye(self.nz-1),second(self.nx,self.hx,False)) + kron(second(self.nz-1,self.hz,True),eye(self.nx))
        a = block_diag((au,aw),format='csc')
        uidx = np.arange(self.nu).reshape(self.nz,self.nx-1)
        widx = np.arange(self.nw).reshape(self.nz-1,self.nx)+self.nu
        pid = np.arange(self.np).reshape(self.nz,self.nx)
        rows = np.concatenate((pid[:,:-1].ravel(),pid[:,1:].ravel(),pid[:-1].ravel(),pid[1:].ravel()))
        cols = np.concatenate((uidx.ravel(),uidx.ravel(),widx.ravel(),widx.ravel()))
        values = np.concatenate((np.full(self.nu,1/self.hx),np.full(self.nu,-1/self.hx),
                                 np.full(self.nw,1/self.hz),np.full(self.nw,-1/self.hz)))
        d = coo_matrix((values,(rows,cols)),shape=(self.np,self.nv)).tocsc()
        c = coo_matrix((np.full(self.np,self.c),(np.arange(self.np),np.zeros(self.np,dtype=int))),shape=(self.np,1)).tocsc()
        return bmat([[a,-d.T,None],[-d,None,c],[None,c.T,None]],format='csc')

    def energy(self, u, w):
        """Sum squared velocity differences independently of the matrix product.

        Closed free-slip box: int |grad(v)|^2 = int 2 e:e when div(v)=0.
        This returns a discrete total, not a cell heat source for future R4.2.
        """
        horizontal = (np.sum((u[:,0]/self.hx)**2) + np.sum((u[:,-1]/self.hx)**2)
                      + np.sum((np.diff(u,axis=1)/self.hx)**2))
        vertical = (np.sum((w[0]/self.hz)**2) + np.sum((w[-1]/self.hz)**2)
                    + np.sum((np.diff(w,axis=0)/self.hz)**2))
        tangent = np.sum((np.diff(u,axis=0)/self.hz)**2)+np.sum((np.diff(w,axis=1)/self.hx)**2)
        return float((horizontal+vertical+tangent)*self.hx*self.hz)


class _SeparableVelocityInverse:
    """Exact discrete free-slip velocity inverse, used only as preconditioning.

    The remaining Schur block is identity on mean-zero cosine pressure modes;
    the constant pressure mode is paired with the explicit gauge multiplier.
    This derivation relies on the uniform rectangle and constant coefficient.
    The independently checked full residual remains authoritative.
    """
    def __init__(self, op):
        if dct is None:
            raise TectonicsError('SciPy FFT preconditioner unavailable; no backend fallback')
        kx = 4*(np.sin(np.arange(op.nx)*np.pi/(2*op.nx))/op.hx)**2
        kz = 4*(np.sin(np.arange(op.nz)*np.pi/(2*op.nz))/op.hz)**2
        u = kz[:,None]+kx[None,1:]
        w = kz[1:,None]+kx[None,:]
        if not np.all(np.isfinite(u)) or not np.all(np.isfinite(w)) or min(u.min(),w.min()) <= 0:
            raise TectonicsError('invalid velocity spectrum')
        condition = max(u.max()/u.min(),w.max()/w.min())
        if condition > 1e12:
            raise TectonicsError('velocity condition estimate exceeds registered binary64 envelope')
        self._u = u.tobytes(); self._w = w.tobytes()
        self.condition_estimate = float(condition)
        self.op = op

    def apply(self, vector):
        op = self.op
        u,w,p,gauge = op.split(vector)
        du = np.frombuffer(self._u,dtype='f8').reshape(u.shape)
        dw = np.frombuffer(self._w,dtype='f8').reshape(w.shape)
        # workers=1 avoids hidden nested parallelism; outer coupled iterations are
        # not independent jobs and are never submitted as separately solved tiles.
        a = dct(dst(u,type=1,axis=1,norm='ortho',workers=1),type=2,axis=0,norm='ortho',workers=1)
        a /= du
        a = idst(idct(a,type=2,axis=0,norm='ortho',workers=1),type=1,axis=1,norm='ortho',workers=1)
        b = dct(dst(w,type=1,axis=0,norm='ortho',workers=1),type=2,axis=1,norm='ortho',workers=1)
        b /= dw
        b = idst(idct(b,type=2,axis=1,norm='ortho',workers=1),type=1,axis=0,norm='ortho',workers=1)
        return np.concatenate((a.ravel(),b.ravel(),p.ravel(),[gauge]))


def face_force_from_density(box, density_anomaly_kg_m3, gravity_m_s2, *, budget=None):
    """Explicit arithmetic face interpolation of a supplied cell density anomaly.

    This is one selected second-order interpolation on this uniform support, not
    a general conservative remap or a gravity solver. The source anomaly can come
    from R3's boussinesq_response. Reference density is not added a second time.
    Gravity is a constant Cartesian vector (gx,gz), z UP; downward gravity has
    negative gz. Inputs and interpolation policy must be retained by the caller's
    forcing provenance. No plate motion/traction or thermal advance is performed.
    """
    if type(box) is not StokesBox2D or input_shape(density_anomaly_kg_m3) != (box.nz,box.nx):
        raise TectonicsError('cell density anomaly must match the Stokes box')
    if input_shape(gravity_m_s2) != (2,):
        raise TectonicsError('constant (gx,gz) gravity required')
    with select_budget(budget).reserve(96*box.nx*box.nz+65536, category='stokes-face-force'):
        rho = read_array(density_anomaly_kg_m3,'density anomaly')
        g = read_array(gravity_m_s2,'gravity')
        def interpolate(a, b, acceleration):
            if acceleration == 0:
                return np.zeros_like(a)
            # Interpolate and multiply gravity at a shared binary exponent.
            # Rounding an intermediate subnormal mean (a+b)/2 before applying
            # gravity can spoil a normal, representable final force by 33%.
            # Scaling endpoints first also avoids (a+b) overflow and treats the
            # two endpoints symmetrically. No geometry or interpolation weights
            # change; final binary64 rounding remains explicit.
            _, exponent = np.frexp(np.maximum(np.abs(a),np.abs(b)))
            left = np.ldexp(a,-exponent)
            right = np.ldexp(b,-exponent)
            mean = (left+right)*.5
            gm, ge = math.frexp(float(acceleration))
            value = np.ldexp(mean*gm,exponent+ge)
            lost = (value==0)&(a!=-b)
            if np.any(lost):
                # Retain the established diagnostic for an unrepresentable mean
                # when the final force is also unrepresentable. A large gravity
                # factor may rescue that mean; it is not refused prematurely.
                if np.any(np.ldexp(mean[lost],exponent[lost])==0):
                    raise TectonicsError('density face mean underflows binary64 and final force is unrepresentable')
                raise TectonicsError('density face force underflows binary64')
            return value
        with np.errstate(over='raise', invalid='raise', under='ignore'):
            try:
                fx = interpolate(rho[:,:-1],rho[:,1:],g[0])
                fz = interpolate(rho[:-1],rho[1:],g[1])
            except FloatingPointError as exc:
                raise TectonicsError('face force exceeds binary64 range') from exc
        return frozen(fx),frozen(fz)
